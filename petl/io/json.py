# -*- coding: utf-8 -*-
from __future__ import absolute_import, print_function, division

# standard library dependencies
import io
import json
import inspect
from collections import OrderedDict
from itertools import chain, islice
from json.encoder import JSONEncoder
from os import unlink
from tempfile import NamedTemporaryFile

from petl.compat import PY2, integer_types
from petl.compat import pickle
from petl.errors import ArgumentError, NestedRecordError
from petl.io.sources import read_source_from_arg, write_source_from_arg
# internal dependencies
from petl.util.base import data, Table, dicts as _dicts, iterpeek


class _MissingValue(object):

    def __repr__(self):
        return '<MISSING>'


class _TypeBranch(object):

    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return '<%s>' % self.name


MISSING = _MissingValue()
VALUE_BRANCH = _TypeBranch('value')
DICT_BRANCH = _TypeBranch('dict')


def fromnestedrecords(records, missing=MISSING, on_type_conflict='reject',
                      spool=1000):
    """
    Flatten an iterable of nested dictionaries into a rectangular table.

    All records are inspected before the header is emitted. Field names are
    tuples of path segments, so dots in original keys do not represent nested
    levels. Dictionaries are expanded recursively and lists are retained as a
    single value. Strings, numbers, booleans and ``None`` are returned without
    inference or conversion.

    Missing values use the distinct :data:`petl.io.json.MISSING` marker by
    default, so a missing field is distinguishable from JSON ``null``. Pass a
    different object as `missing` to customize the marker.

    By default, a path that is sometimes a value and sometimes a dictionary
    raises :class:`petl.errors.NestedRecordError`. Set `on_type_conflict` to
    ``'branch'`` to retain both forms; the path gets an additional
    :data:`VALUE_BRANCH` or :data:`DICT_BRANCH` segment.

    One-shot iterators are consumed only once. At most `spool` records are
    retained in memory; remaining records are replayed from a bounded
    temporary pickle spool. Set ``spool=None`` to retain all records in
    memory.

        >>> import petl as etl
        >>> records = [
        ...     {'id': 1, 'name': {'first': 'Ada'}, 'tags': ['x']},
        ...     {'id': 2, 'name': {'first': 'Grace', 'last': 'Hopper'}},
        ... ]
        >>> table = etl.fromnestedrecords(records)
        >>> list(table) == [
        ...     (('id',), ('name', 'first'), ('tags',), ('name', 'last')),
        ...     (1, 'Ada', ['x'], etl.MISSING),
        ...     (2, 'Grace', etl.MISSING, 'Hopper'),
        ... ]
        True

    """

    if on_type_conflict not in ('reject', 'branch'):
        raise ArgumentError("on_type_conflict must be 'reject' or 'branch'")
    if spool is not None and (not isinstance(spool, integer_types)
                              or isinstance(spool, bool) or spool < 0):
        raise ArgumentError('spool must be a non-negative integer or None')
    return NestedRecordsView(records, missing=missing,
                             on_type_conflict=on_type_conflict, spool=spool)


fromnesteddicts = fromnestedrecords
flattennestedrecords = fromnestedrecords


class NestedRecordsView(Table):

    def __init__(self, records, missing, on_type_conflict, spool):
        self._records = records
        self.missing = missing
        self.on_type_conflict = on_type_conflict
        self.spool = spool
        self._header = None
        self.schema = None
        self._replay_records = None
        self._filecache = None
        self._prepared = False

    def __iter__(self):
        self._prepare()
        yield self._header
        for record in self._replay():
            yield flattennestedrecord(record, self.schema, self._header,
                                      self.missing)

    def _prepare(self):
        if self._prepared:
            return

        schema = newnestednode()
        schema['kind'] = 'dict'
        fields = []
        field_set = set()
        iterator = iter(self._records)
        one_shot = (iterator is self._records
                    or inspect.isgenerator(self._records))
        memory_records = []
        cache_file = None

        try:
            for line_number, record in enumerate(iterator, 1):
                discovernestedrecord(record, line_number, schema, fields,
                                     field_set, self.on_type_conflict)
                if one_shot:
                    if cache_file is None and (self.spool is not None and
                                               len(memory_records) >=
                                               self.spool):
                        cache_file = _open_cache_file()
                        for cached_record in memory_records:
                            pickle.dump(cached_record, cache_file,
                                        protocol=-1)
                        memory_records = []
                    if cache_file is None:
                        memory_records.append(record)
                    else:
                        pickle.dump(record, cache_file, protocol=-1)
        except Exception:
            if cache_file is not None:
                cache_file.close()
                unlink(cache_file.name)
            raise

        self.schema = schema
        self._header = tuple(fields)
        if cache_file is None:
            self._replay_records = (memory_records if one_shot
                                    else self._records)
        else:
            self._filecache = cache_file
        self._prepared = True

    def _replay(self):
        if self._filecache is None:
            for record in self._replay_records:
                yield record
            return

        self._filecache.seek(0)
        while True:
            try:
                yield pickle.load(self._filecache)
            except EOFError:
                break

    def __del__(self):
        if self._filecache is not None:
            self._filecache.close()
            unlink(self._filecache.name)


def _open_cache_file():
    if PY2:
        return NamedTemporaryFile(delete=False, mode='wb+', bufsize=0)
    return NamedTemporaryFile(delete=False, mode='wb+', buffering=0)


def newnestednode():
    return {'kind': None, 'children': OrderedDict()}


def discovernestedrecord(record, line_number, schema, fields, field_set,
                         on_type_conflict):
    if not isinstance(record, dict):
        raise NestedRecordError(
            line_number, (),
            'record is %s, expected a dictionary' % type(record).__name__)

    stack = [((), record, schema)]
    while stack:
        path, value, node = stack.pop()
        if isinstance(value, dict):
            node, path = _ensure_nested_dict(node, path, line_number, fields,
                                             field_set, on_type_conflict)
            for key in reversed(list(value.keys())):
                child = node['children'].get(key)
                if child is None:
                    child = newnestednode()
                    node['children'][key] = child
                stack.append((path + (key,), value[key], child))
        else:
            node, path = _ensure_nested_value(node, path, line_number, fields,
                                              field_set, on_type_conflict)
            _add_nested_field(path, fields, field_set)


def _ensure_nested_dict(node, path, line_number, fields, field_set,
                        on_type_conflict):
    if node['kind'] == 'dict':
        return node, path
    if node['kind'] == 'branch':
        return node['children'][DICT_BRANCH], path + (DICT_BRANCH,)
    if node['kind'] == 'value':
        if on_type_conflict == 'reject':
            raise NestedRecordError(line_number, path,
                                    'expected a value, encountered a '
                                    'dictionary')
        _branch_nested_node(node, path, 'value', fields, field_set)
        return node['children'][DICT_BRANCH], path + (DICT_BRANCH,)
    node['kind'] = 'dict'
    return node, path


def _ensure_nested_value(node, path, line_number, fields, field_set,
                         on_type_conflict):
    if node['kind'] == 'value':
        return node, path
    if node['kind'] == 'branch':
        return node['children'][VALUE_BRANCH], path + (VALUE_BRANCH,)
    if node['kind'] == 'dict':
        if on_type_conflict == 'reject':
            raise NestedRecordError(line_number, path,
                                    'expected a dictionary, encountered a '
                                    'value')
        _branch_nested_node(node, path, 'dict', fields, field_set)
        return node['children'][VALUE_BRANCH], path + (VALUE_BRANCH,)
    node['kind'] = 'value'
    return node, path


def _branch_nested_node(node, path, existing_kind, fields, field_set):
    if existing_kind == 'dict':
        dict_child = {'kind': 'dict', 'children': node['children']}
        value_child = {'kind': 'value', 'children': OrderedDict()}
        children = ((DICT_BRANCH, dict_child), (VALUE_BRANCH, value_child))
        branch_segment = DICT_BRANCH
    else:
        value_child = {'kind': 'value', 'children': OrderedDict()}
        dict_child = {'kind': 'dict', 'children': OrderedDict()}
        children = ((VALUE_BRANCH, value_child), (DICT_BRANCH, dict_child))
        branch_segment = VALUE_BRANCH

    node['kind'] = 'branch'
    node['children'] = OrderedDict(children)
    _branch_nested_fields(path, existing_kind, branch_segment, fields,
                          field_set)


def _branch_nested_fields(path, existing_kind, branch_segment, fields,
                          field_set):
    path_length = len(path)
    for index, field in enumerate(fields):
        if existing_kind == 'value':
            matches = field == path
        else:
            matches = field[:path_length] == path
        if matches:
            branched_field = path + (branch_segment,) + field[path_length:]
            field_set.remove(field)
            field_set.add(branched_field)
            fields[index] = branched_field


def _add_nested_field(path, fields, field_set):
    if path not in field_set:
        field_set.add(path)
        fields.append(path)


def flattennestedrecord(record, schema, header, missing):
    row = [missing] * len(header)
    indices = dict((field, index) for index, field in enumerate(header))
    stack = [((), record, schema)]

    while stack:
        path, value, node = stack.pop()
        if node['kind'] == 'branch':
            if isinstance(value, dict):
                node = node['children'][DICT_BRANCH]
                path = path + (DICT_BRANCH,)
            else:
                node = node['children'][VALUE_BRANCH]
                path = path + (VALUE_BRANCH,)

        if node['kind'] == 'dict':
            for key in reversed(list(value.keys())):
                child = node['children'].get(key)
                if child is not None:
                    stack.append((path + (key,), value[key], child))
        elif path in indices:
            row[indices[path]] = value

    return tuple(row)


def fromnestedjson(source, lines=False, missing=MISSING,
                   on_type_conflict='reject', spool=1000, *args, **kwargs):
    """
    Extract nested JSON objects into a rectangular table.

    With ``lines=True`` each input line is parsed as a JSON object. Otherwise
    the source must contain a JSON array. The parsed records are flattened by
    :func:`fromnestedrecords`.

    """

    source = read_source_from_arg(source)
    return NestedJsonView(source, lines=lines, missing=missing,
                          on_type_conflict=on_type_conflict, spool=spool,
                          args=args, kwargs=kwargs)


class NestedJsonView(Table):

    def __init__(self, source, lines, missing, on_type_conflict, spool,
                 args, kwargs):
        self.source = source
        self.lines = lines
        self.missing = missing
        self.on_type_conflict = on_type_conflict
        self.spool = spool
        self.args = args
        self.kwargs = kwargs

    def __iter__(self):
        with self.source.open('rb') as source_file:
            if not PY2:
                source_file = io.TextIOWrapper(source_file, encoding='utf-8',
                                               newline='', write_through=True)
            try:
                if self.lines:
                    records = _iternestedjsonlines(source_file, self.args,
                                                   self.kwargs)
                else:
                    records = json.load(source_file, *self.args,
                                        **self.kwargs)
                table = fromnestedrecords(
                    records, missing=self.missing,
                    on_type_conflict=self.on_type_conflict, spool=self.spool)
                for row in table:
                    yield row
            finally:
                if not PY2:
                    source_file.detach()


def _iternestedjsonlines(source_file, args, kwargs):
    for line_number, line in enumerate(source_file, 1):
        try:
            yield json.loads(line, *args, **kwargs)
        except ValueError as error:
            raise NestedRecordError(line_number, (),
                                    'could not parse JSON: %s' % error)


def fromjson(source, *args, **kwargs):
    """
    Extract data from a JSON file. The file must contain a JSON array as
    the top level object, and each member of the array will be treated as a
    row of data. E.g.::

        >>> import petl as etl
        >>> data = '''
        ... [{"foo": "a", "bar": 1},
        ... {"foo": "b", "bar": 2},
        ... {"foo": "c", "bar": 2}]
        ... '''
        >>> with open('example.file1.json', 'w') as f:
        ...     f.write(data)
        ...
        74
        >>> table1 = etl.fromjson('example.file1.json', header=['foo', 'bar'])
        >>> table1
        +-----+-----+
        | foo | bar |
        +=====+=====+
        | 'a' |   1 |
        +-----+-----+
        | 'b' |   2 |
        +-----+-----+
        | 'c' |   2 |
        +-----+-----+

    Setting argument `lines` to `True` will enable to
    infer the document as a JSON lines document. For more details about JSON lines
    please visit https://jsonlines.org/.

    An empty JSON lines file produces a table with no data rows. If no
    `header` is supplied, the table has an empty header tuple.

        >>> import petl as etl
        >>> data_with_jlines = '''{"name": "Gilbert", "wins": [["straight", "7S"], ["one pair", "10H"]]}
        ... {"name": "Alexa", "wins": [["two pair", "4S"], ["two pair", "9S"]]}
        ... {"name": "May", "wins": []}
        ... {"name": "Deloise", "wins": [["three of a kind", "5S"]]}'''
        ...
        >>> with open('example.file2.json', 'w') as f:
        ...     f.write(data_with_jlines)
        ...
        223
        >>> table2 = etl.fromjson('example.file2.json', lines=True)
        >>> table2
        +-----------+-------------------------------------------+
        | name      | wins                                      |
        +===========+===========================================+
        | 'Gilbert' | [['straight', '7S'], ['one pair', '10H']] |
        +-----------+-------------------------------------------+
        | 'Alexa'   | [['two pair', '4S'], ['two pair', '9S']]  |
        +-----------+-------------------------------------------+
        | 'May'     | []                                        |
        +-----------+-------------------------------------------+
        | 'Deloise' | [['three of a kind', '5S']]               |
        +-----------+-------------------------------------------+

    If your JSON file does not fit this structure, you will need to parse it
    via :func:`json.load` and select the array to treat as the data, see also
    :func:`petl.io.json.fromdicts`.

    .. versionchanged:: 1.1.0

    If no `header` is specified, fields will be discovered by sampling keys
    from the first `sample` objects in `source`. The header will be
    constructed from keys in the order discovered. Note that this
    ordering may not be stable, and therefore it may be advisable to specify
    an explicit `header` or to use another function like
    :func:`petl.transform.headers.sortheader` on the resulting table to
    guarantee stability.

    With `sample=1`, only the first object's keys are used. An empty input
    array produces an empty header and no data rows.

    """

    source = read_source_from_arg(source)
    return JsonView(source, *args, **kwargs)


class JsonView(Table):
    def __init__(self, source, *args, **kwargs):
        self.source = source
        self.missing = kwargs.pop('missing', None)
        self._header = kwargs.pop('header', None)
        self.sample = kwargs.pop('sample', 1000)
        self.lines = kwargs.pop('lines', False)
        self.args = args
        self.kwargs = kwargs

    def __iter__(self):
        with self.source.open('rb') as f:
            if not PY2:
                # wrap buffer for text IO
                f = io.TextIOWrapper(f, encoding='utf-8', newline='',
                                     write_through=True)
            try:
                if self.lines:
                    for row in iterjlines(f, self._header, self.missing):
                        yield row
                else:
                    dicts = json.load(f, *self.args, **self.kwargs)
                    for row in iterdicts(dicts, self._header, self.sample,
                                         self.missing):
                        yield row
            finally:
                if not PY2:
                    f.detach()


def fromdicts(dicts, header=None, sample=1000, missing=None):
    """
    View a sequence of Python :class:`dict` as a table. E.g.::

        >>> import petl as etl
        >>> dicts = [{"foo": "a", "bar": 1},
        ...          {"foo": "b", "bar": 2},
        ...          {"foo": "c", "bar": 2}]
        >>> table1 = etl.fromdicts(dicts, header=['foo', 'bar'])
        >>> table1
        +-----+-----+
        | foo | bar |
        +=====+=====+
        | 'a' |   1 |
        +-----+-----+
        | 'b' |   2 |
        +-----+-----+
        | 'c' |   2 |
        +-----+-----+

    Argument `dicts` can also be a generator, the output of generator
    is iterated and cached using a temporary file to support further
    transforms and multiple passes of the table:

        >>> import petl as etl
        >>> dicts = ({"foo": chr(ord("a")+i), "bar":i+1} for i in range(3))
        >>> table1 = etl.fromdicts(dicts, header=['foo', 'bar'])
        >>> table1
        +-----+-----+
        | foo | bar |
        +=====+=====+
        | 'a' |   1 |
        +-----+-----+
        | 'b' |   2 |
        +-----+-----+
        | 'c' |   3 |
        +-----+-----+

    If `header` is not specified, `sample` items from `dicts` will be
    inspected to discovery dictionary keys. Note that the order in which
    dictionary keys are discovered may not be stable,

    A sample size of one discovers the first dictionary's keys. Empty
    inputs produce an empty header and no data rows, including with
    `sample=1`.

    See also :func:`petl.io.json.fromjson`.

    .. versionchanged:: 1.1.0

    If no `header` is specified, fields will be discovered by sampling keys
    from the first `sample` dictionaries in `dicts`. The header will be
    constructed from keys in the order discovered. Note that this
    ordering may not be stable, and therefore it may be advisable to specify
    an explicit `header` or to use another function like
    :func:`petl.transform.headers.sortheader` on the resulting table to
    guarantee stability.

    .. versionchanged:: 1.7.5

    Full support of generators passed as `dicts` has been added, leveraging
    `itertools.tee`.

    .. versionchanged:: 1.7.11

    Generator support has been modified to use temporary file cache
    instead of `itertools.tee` due to high memory usage.

    """
    view = DictsGeneratorView if inspect.isgenerator(dicts) else DictsView
    return view(dicts, header=header, sample=sample, missing=missing)


class _DictsAttr(object):
    """Reads as the input data, calls as the inherited Table.dicts() method.

    Only exists to keep `.dicts` working both ways in the v1.x series; v2 can
    drop it along with the property below.
    """

    def __init__(self, view):
        self._view = view

    def __call__(self, *sliceargs, **kwargs):
        return _dicts(self._view, *sliceargs, **kwargs)

    def __iter__(self):
        return iter(self._view._dicts)

    def __next__(self):
        return next(self._view._dicts)

    next = __next__

    def __len__(self):
        return len(self._view._dicts)

    def __getitem__(self, item):
        return self._view._dicts[item]

    def __eq__(self, other):
        return self._view._dicts == other

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash(self._view._dicts)

    def __repr__(self):
        return repr(self._view._dicts)

    def __getattr__(self, name):
        if name.startswith('_'):
            raise AttributeError(name)
        return getattr(self._view._dicts, name)


class DictsView(Table):

    def __init__(self, dicts, header=None, sample=1000, missing=None):
        self._dicts = dicts
        self._header = header
        self.sample = sample
        self.missing = missing

    def __iter__(self):
        return iterdicts(self._dicts, self._header, self.sample, self.missing)

    @property
    def dicts(self):
        # `.dicts` was the raw input data, which shadowed Table.dicts() (#643).
        # A property on the subclass wins over the inherited method, so both
        # uses keep working until v2.
        return _DictsAttr(self)

    @dicts.setter
    def dicts(self, value):
        self._dicts = value


class DictsGeneratorView(DictsView):

    def __init__(self, dicts, header=None, sample=1000, missing=None):
        super(DictsGeneratorView, self).__init__(dicts, header, sample, missing)
        self._filecache = None
        self._cached = 0

    def __iter__(self):
        if not self._header:
            self._determine_header()
        yield self._header

        if not self._filecache:
            if PY2:
                self._filecache = NamedTemporaryFile(delete=False, mode='wb+', bufsize=0)
            else:
                self._filecache = NamedTemporaryFile(delete=False, mode='wb+', buffering=0)

        position = 0
        it = iter(self._dicts)
        while True:
            if position < self._cached:
                self._filecache.seek(position)
                row = pickle.load(self._filecache)
                position = self._filecache.tell()
                yield row
                continue
            try:
                o = next(it)
            except StopIteration:
                break
            row = tuple(o.get(f, self.missing) for f in self._header)
            self._filecache.seek(self._cached)
            pickle.dump(row, self._filecache, protocol=-1)
            self._cached = position = self._filecache.tell()
            yield row

    def _determine_header(self):
        it = iter(self._dicts)
        header = list()
        peek = list(islice(it, self.sample))
        it = chain(peek, it)
        self._dicts = it
        for o in peek:
            if hasattr(o, 'keys'):
                header += [k for k in o.keys() if k not in header]
        self._header = tuple(header)
        return it

    def __del__(self):
        if self._filecache:
            self._filecache.close()
            unlink(self._filecache.name)


def iterjlines(f, header, missing):
    it = iter(f)

    if header is None:
        header = list()
        try:
            peek, it = iterpeek(it, 1)
        except StopIteration:
            yield tuple()
            return
        json_obj = json.loads(peek)
        if hasattr(json_obj, 'keys'):
            header += [k for k in json_obj.keys() if k not in header]
    yield tuple(header)

    for o in it:
        json_obj = json.loads(o)
        yield tuple(json_obj[f] if f in json_obj else missing for f in header)


def iterdicts(dicts, header, sample, missing):
    it = iter(dicts)

    # determine header row
    if header is None:
        # discover fields
        header = list()
        peek = list(islice(it, sample))
        it = chain(peek, it)
        for o in peek:
            if hasattr(o, 'keys'):
                header += [k for k in o.keys() if k not in header]
    yield tuple(header)

    # generate data rows
    for o in it:
        yield tuple(o.get(f, missing) for f in header)


def tojson(table, source=None, prefix=None, suffix=None, *args, **kwargs):
    """
    Write a table in JSON format, with rows output as JSON objects. E.g.::

        >>> import petl as etl
        >>> table1 = [['foo', 'bar'],
        ...           ['a', 1],
        ...           ['b', 2],
        ...           ['c', 2]]
        >>> etl.tojson(table1, 'example.file3.json', sort_keys=True)
        >>> # check what it did
        ... print(open('example.file3.json').read())
        [{"bar": 1, "foo": "a"}, {"bar": 2, "foo": "b"}, {"bar": 2, "foo": "c"}]



    Setting argument `lines` to `True` will enable to
    infer the writing format as a JSON lines . For more details about JSON lines
    please visit https://jsonlines.org/.

        >>> import petl as etl
        >>> table1 = [['name', 'wins'],
        ...           ['Gilbert', [['straight', '7S'], ['one pair', '10H']]],
        ...           ['Alexa', [['two pair', '4S'], ['two pair', '9S']]],
        ...           ['May', []],
        ...           ['Deloise',[['three of a kind', '5S']]]]
        >>> etl.tojson(table1, 'example.file3.jsonl', lines = True, sort_keys=True)
        >>> # check what it did
        ... print(open('example.file3.jsonl').read())
        {"name": "Gilbert", "wins": [["straight", "7S"], ["one pair", "10H"]]}
        {"name": "Alexa", "wins": [["two pair", "4S"], ["two pair", "9S"]]}
        {"name": "May", "wins": []}
        {"name": "Deloise", "wins": [["three of a kind", "5S"]]}

    Note that this is currently not streaming, all data is loaded into memory
    before being written to the file.

    """

    obj = [row for row in _dicts(table)]
    _writejson(source, obj, prefix, suffix, *args, **kwargs)


Table.tojson = tojson


def tojsonarrays(table, source=None, prefix=None, suffix=None,
                 output_header=False, *args, **kwargs):
    """
    Write a table in JSON format, with rows output as JSON arrays. E.g.::

        >>> import petl as etl
        >>> table1 = [['foo', 'bar'],
        ...           ['a', 1],
        ...           ['b', 2],
        ...           ['c', 2]]
        >>> etl.tojsonarrays(table1, 'example.file4.json')
        >>> # check what it did
        ... print(open('example.file4.json').read())
        [["a", 1], ["b", 2], ["c", 2]]

    Note that this is currently not streaming, all data is loaded into memory
    before being written to the file.

    """

    if output_header:
        obj = [row for row in table]
    else:
        obj = [row for row in data(table)]
    _writejson(source, obj, prefix, suffix, *args, **kwargs)


Table.tojsonarrays = tojsonarrays


def _writejson(source, obj, prefix, suffix, *args, **kwargs):
    lines = kwargs.pop('lines', False)
    encoder = JSONEncoder(*args, **kwargs)
    source = write_source_from_arg(source)
    with source.open('wb') as f:
        if PY2:
            # write directly to buffer
            _writeobj(encoder, obj, f, prefix, suffix, lines=lines)
        else:
            # wrap buffer for text IO
            f = io.TextIOWrapper(f, encoding='utf-8', newline='',
                                 write_through=True)
            try:
                _writeobj(encoder, obj, f, prefix, suffix, lines=lines)
            finally:
                f.detach()


def _writeobj(encoder, obj, f, prefix, suffix, lines=False):
    if prefix is not None:
        f.write(prefix)
    if lines:
        for rec in obj:
            for chunk in encoder.iterencode(rec):
                f.write(chunk)
            f.write('\n')
    else:
        for chunk in encoder.iterencode(obj):
            f.write(chunk)
    if suffix is not None:
        f.write(suffix)
