from __future__ import absolute_import, print_function, division


import os
import heapq
from tempfile import NamedTemporaryFile
import itertools
import logging
from collections import namedtuple
import operator
from petl.compat import pickle, next, text_type, string_types


import petl.config as config
from petl.comparison import comparable_itemgetter
from petl.errors import ArgumentError
from petl.util.base import Table, asindices


logger = logging.getLogger(__name__)
warning = logger.warning
info = logger.info
debug = logger.debug


_MISSING_POSITIONS = {
    'first': 0,
    'start': 0,
    'last': 2,
    'end': 2,
}


class SortSpec(namedtuple('SortSpec', ['field', 'reverse', 'is_missing',
                                       'missing', 'missing_position'])):
    """Per-field sort specification."""

    __slots__ = ()

    def __new__(cls, field, descending=False, is_missing=None, missing=None,
                missing_position='last', reverse=None):
        if reverse is not None:
            if descending:
                raise ArgumentError('descending and reverse are equivalent')
            descending = _normalize_direction(reverse)
        else:
            descending = _normalize_direction(descending)
        if is_missing is not None and not callable(is_missing):
            raise ArgumentError('is_missing must be callable')
        missing_position = _normalize_missing_position(missing_position)
        return super(SortSpec, cls).__new__(cls, field, descending, is_missing,
                                            missing, missing_position)

    @property
    def descending(self):
        return self.reverse


def _normalize_direction(value):
    if isinstance(value, string_types):
        direction = value.lower()
        if direction in ('asc', 'ascending', 'forward'):
            return False
        if direction in ('desc', 'descending', 'reverse'):
            return True
        raise ArgumentError('invalid sort direction: %r' % value)
    return bool(value)


def _normalize_missing_position(value):
    if isinstance(value, bool) or not isinstance(value, string_types):
        raise ArgumentError("missing position must be 'first' or 'last'")
    try:
        return _MISSING_POSITIONS[value.lower()]
    except KeyError:
        raise ArgumentError("missing position must be 'first' or 'last'")


def _prepare_sort_specs(sort_specs):
    if isinstance(sort_specs, (SortSpec, dict) + string_types + (int,)):
        sort_specs = [sort_specs]
    try:
        sort_specs = iter(sort_specs)
    except TypeError:
        raise ArgumentError('sort specs must be a sequence of field specs')
    prepared = [_prepare_sort_spec(spec) for spec in sort_specs]
    if not prepared:
        raise ArgumentError('at least one sort field is required')
    return tuple(prepared)


def _prepare_sort_spec(spec):
    if isinstance(spec, SortSpec):
        return spec
    if isinstance(spec, dict):
        return _sort_spec_from_mapping(spec)
    if isinstance(spec, (list, tuple)):
        return _sort_spec_from_sequence(spec)
    raise ArgumentError('invalid sort spec: %r' % (spec,))


def _sort_spec_from_mapping(spec):
    field = None
    field_found = False
    for name in ('field', 'key', 'name', 'index'):
        if name in spec:
            field = spec[name]
            field_found = True
            break
    if not field_found:
        raise ArgumentError('sort spec must identify a field')

    reverse = False
    if 'direction' in spec:
        reverse = _normalize_direction(spec['direction'])
    if 'ascending' in spec:
        reverse = not bool(spec['ascending'])
    if 'descending' in spec:
        reverse = _normalize_direction(spec['descending'])
    if 'reverse' in spec:
        reverse = _normalize_direction(spec['reverse'])

    is_missing = None
    for name in ('is_missing', 'missing_if'):
        if name in spec:
            is_missing = spec[name]
            break

    missing = None
    for name in ('missing_value', 'missing', 'na_value'):
        if name in spec:
            missing = spec[name]
            break

    missing_position = 'last'
    if 'nulls_first' in spec:
        missing_position = 'first' if spec['nulls_first'] else 'last'
    elif 'missing_first' in spec:
        missing_position = 'first' if spec['missing_first'] else 'last'
    else:
        for name in ('missing_position', 'na_position', 'nulls_position',
                     'nulls', 'position'):
            if name in spec:
                missing_position = spec[name]
                break

    return SortSpec(field, reverse=reverse, is_missing=is_missing,
                    missing=missing, missing_position=missing_position)


def _sort_spec_from_sequence(spec):
    try:
        if len(spec) == 1:
            return SortSpec(spec[0])
        if len(spec) == 2:
            return SortSpec(spec[0], reverse=spec[1])
        if len(spec) == 3:
            field, reverse, third = spec
            if callable(third):
                return SortSpec(field, reverse=reverse, is_missing=third)
            return SortSpec(field, reverse=reverse, missing_position=third)
        if len(spec) == 4:
            field, reverse, is_missing, missing_position = spec
            return SortSpec(field, reverse=reverse, is_missing=is_missing,
                            missing_position=missing_position)
        if len(spec) == 5:
            return SortSpec(*spec)
    except ArgumentError:
        raise
    except TypeError:
        pass
    raise ArgumentError('invalid sort spec: %r' % (spec,))


class _ResolvedSortSpec(namedtuple('_ResolvedSortSpec', [
    'field', 'index', 'reverse', 'is_missing', 'missing', 'missing_rank'
])):
    pass


def _resolve_sort_specs(header, sort_specs):
    indices = asindices(header, [spec.field for spec in sort_specs])
    fields = list(header)
    resolved = []
    for spec, index in zip(sort_specs, indices):
        field = fields[index] if index < len(fields) else spec.field
        resolved.append(_ResolvedSortSpec(
            field, index, spec.reverse, spec.is_missing, spec.missing,
            spec.missing_position
        ))
    return tuple(resolved)


class _FieldSortKey(namedtuple('_FieldSortKey', [
    'field', 'value', 'row', 'is_missing', 'reverse', 'rank'
])):
    __slots__ = ()


class _RowSortKey(namedtuple('_RowSortKey', ['fields', 'row'])):
    __slots__ = ()

    def __lt__(self, other):
        for left, right in zip(self.fields, other.fields):
            comparison = _compare_field_keys(left, right)
            if comparison != 0:
                return comparison < 0
        return False

    def __eq__(self, other):
        if not isinstance(other, _RowSortKey):
            return False
        for left, right in zip(self.fields, other.fields):
            try:
                if _compare_field_keys(left, right) != 0:
                    return False
            except TypeError:
                return False
        return True

    def __ne__(self, other):
        return not self == other


def _compare_field_keys(left, right):
    if left.is_missing or right.is_missing:
        if left.is_missing != right.is_missing:
            return left.rank - right.rank
        return 0

    if left.reverse:
        if _value_less(right, left):
            return -1
        if _value_less(left, right):
            return 1
    else:
        if _value_less(left, right):
            return -1
        if _value_less(right, left):
            return 1
    return 0


def _value_less(left, right):
    try:
        return left.value < right.value
    except TypeError:
        raise TypeError(
            'incomparable sort values for field %r: row %r has %r, '
            'row %r has %r' % (
                left.field, left.row, left.value, right.row, right.value
            )
        )


def _make_row_sort_key(specs, row):
    fields = []
    for spec in specs:
        absent = False
        try:
            value = row[spec.index]
        except (IndexError, KeyError):
            absent = True
            value = spec.missing

        if absent:
            is_missing = True
        elif spec.is_missing is not None:
            is_missing = bool(spec.is_missing(value))
        else:
            is_missing = value is spec.missing

        fields.append(_FieldSortKey(
            spec.field, value, row, is_missing, spec.reverse,
            spec.missing_rank if is_missing else 1
        ))
    return _RowSortKey(tuple(fields), row)


def sort(table, key=None, reverse=False, buffersize=None, tempdir=None,
         cache=True, sort_specs=None, specs=None):
    """

    `specs` is accepted as an alias for `sort_specs`.
    Sort the table. Field names or indices (from zero) can be used to specify
    the key. E.g.::

        >>> import petl as etl
        >>> table1 = [['foo', 'bar'],
        ...           ['C', 2],
        ...           ['A', 9],
        ...           ['A', 6],
        ...           ['F', 1],
        ...           ['D', 10]]
        >>> table2 = etl.sort(table1, 'foo')
        >>> table2
        +-----+-----+
        | foo | bar |
        +=====+=====+
        | 'A' |   9 |
        +-----+-----+
        | 'A' |   6 |
        +-----+-----+
        | 'C' |   2 |
        +-----+-----+
        | 'D' |  10 |
        +-----+-----+
        | 'F' |   1 |
        +-----+-----+

        >>> # sorting by compound key is supported
        ... table3 = etl.sort(table1, key=['foo', 'bar'])
        >>> table3
        +-----+-----+
        | foo | bar |
        +=====+=====+
        | 'A' |   6 |
        +-----+-----+
        | 'A' |   9 |
        +-----+-----+
        | 'C' |   2 |
        +-----+-----+
        | 'D' |  10 |
        +-----+-----+
        | 'F' |   1 |
        +-----+-----+

        >>> # if no key is specified, the default is a lexical sort
        ... table4 = etl.sort(table1)
        >>> table4
        +-----+-----+
        | foo | bar |
        +=====+=====+
        | 'A' |   6 |
        +-----+-----+
        | 'A' |   9 |
        +-----+-----+
        | 'C' |   2 |
        +-----+-----+
        | 'D' |  10 |
        +-----+-----+
        | 'F' |   1 |
        +-----+-----+

    The `buffersize` argument should be an `int` or `None`.

    If the number of rows in the table is less than `buffersize`, the table
    will be sorted in memory. Otherwise, the table is sorted in chunks of
    no more than `buffersize` rows, each chunk is written to a temporary file,
    and then a merge sort is performed on the temporary files.

    If `buffersize` is `None`, the value of
    `petl.config.sort_buffersize` will be used. By default this is
    set to 100000 rows, but can be changed, e.g.::

        >>> import petl.config
        >>> petl.config.sort_buffersize = 500000

    If `petl.config.sort_buffersize` is set to `None`, this forces
    all sorting to be done entirely in memory.

    By default the results of the sort will be cached, and so a second pass over
    the sorted table will yield rows from the cache and will not repeat the
    sort operation. To turn off caching, set the `cache` argument to `False`.

    Use `sort_specs` for per-field directions and missing value positions.
    Each item is a :class:`SortSpec`, mapping, or field/value tuple. Missing
    positions are ``'first'`` or ``'last'`` and do not change with the field
    direction. `sort_specs` cannot be combined with `key` or `reverse`.

    """

    if sort_specs is not None and specs is not None:
        raise ArgumentError('specs and sort_specs are aliases')
    if sort_specs is None:
        sort_specs = specs
    if sort_specs is not None:
        if key is not None or reverse:
            raise ArgumentError(
                'sort_specs cannot be combined with key or reverse'
            )
        sort_specs = _prepare_sort_specs(sort_specs)

    return SortView(table, key=key, reverse=reverse, buffersize=buffersize,
                    tempdir=tempdir, cache=cache, sort_specs=sort_specs)


Table.sort = sort


def _iterchunk(fn):
    # reopen so iterators from file cache are independent
    debug('iterchunk, opening %s' % fn)
    with open(fn, 'rb') as f:
        try:
            while True:
                yield pickle.load(f)
        except EOFError:
            pass
    debug('end of iterchunk, closed %s' % fn)


class _Keyed(namedtuple('Keyed', ['key', 'obj'])):
    #  Override default behavior of namedtuple comparisons, only keys need to be compared for heapmerge
    def __eq__(self, other):
        if not hasattr(other, 'key'):
            return False
        try:
            return self.key == other.key
        except TypeError:
            return False

    def __lt__(self, other):
        return self.key < other.key

    def __le__(self, other):
        return self.key <= other.key

    def __ne__(self, other):
        return not self == other

    def __gt__(self, other):
        return other.key < self.key

    def __ge__(self, other):
        return not (self.key < other.key)


def _heapqmergesorted(key=None, *iterables):
    """Return a single iterator over the given iterables, sorted by the
    given `key` function, assuming the input iterables are already sorted by
    the same function. (I.e., the merge part of a general merge sort.) Uses
    :func:`heapq.merge` for the underlying implementation."""

    if key is None:
        keyed_iterables = iterables
        for element in heapq.merge(*keyed_iterables):
            yield element
    else:
        keyed_iterables = [(_Keyed(key(obj), obj) for obj in iterable)
                           for iterable in iterables]
        for element in heapq.merge(*keyed_iterables):
            yield element.obj


def _shortlistmergesorted(key=None, reverse=False, *iterables):
    """Return a single iterator over the given iterables, sorted by the
    given `key` function, assuming the input iterables are already sorted by
    the same function. (I.e., the merge part of a general merge sort.) Uses
    :func:`min` (or :func:`max` if ``reverse=True``) for the underlying
    implementation."""

    if reverse:
        op = max
    else:
        op = min
    if key is not None:
        opkwargs = {'key': key}
    else:
        opkwargs = dict()
    # populate initial shortlist
    # (remember some iterables might be empty)
    iterators = list()
    shortlist = list()
    for iterable in iterables:
        it = iter(iterable)
        try:
            first = next(it)
            iterators.append(it)
            shortlist.append(first)
        except StopIteration:
            pass
    # do the mergesort
    while iterators:
        nxt = op(shortlist, **opkwargs)
        yield nxt
        nextidx = shortlist.index(nxt)
        try:
            shortlist[nextidx] = next(iterators[nextidx])
        except StopIteration:
            del shortlist[nextidx]
            del iterators[nextidx]


def _mergesorted(key=None, reverse=False, *iterables):
    # N.B., I've used heapq for normal merge sort and shortlist merge sort for
    # reverse merge sort because I've assumed that heapq.merge is faster and
    # so is preferable but it doesn't support reverse sorting so the shortlist
    # merge sort has to be used for reverse sorting. Some casual profiling
    # suggests there isn't much between the two in terms of speed, but might be
    # worth profiling more carefully

    if reverse:
        return _shortlistmergesorted(key, True, *iterables)
    else:
        return _heapqmergesorted(key, *iterables)


class SortView(Table):
    def __init__(self, source, key=None, reverse=False, buffersize=None,
                 tempdir=None, cache=True, sort_specs=None):
        self.source = source
        self.key = key
        self.reverse = reverse
        self.sort_specs = sort_specs
        if buffersize is None:
            self.buffersize = config.sort_buffersize
        else:
            self.buffersize = buffersize
        self.tempdir = tempdir
        self._cache = cache
        self._hdrcache = None
        self._memcache = None
        self._filecache = None
        self._getkey = None

    def clearcache(self):
        debug('clear cache')
        self._hdrcache = None
        self._memcache = None
        self._filecache = None
        self._getkey = None

    def __iter__(self):
        source = self.source
        key = self.key
        reverse = self.reverse
        if self._cache and self._memcache is not None:
            return self._iterfrommemcache()
        elif self._cache and self._filecache is not None:
            return self._iterfromfilecache()
        else:
            return self._iternocache(source, key, reverse)

    def _iterfrommemcache(self):
        debug('iterate from memory cache')
        yield tuple(self._hdrcache)
        for row in self._memcache:
            yield tuple(row)

    def _iterfromfilecache(self):
        # create a reference to the filecache here, so cleanup happens in the
        # correct order
        filecache = self._filecache
        filenames = list(map(operator.attrgetter('name'), filecache))
        debug('iterate from file cache: %r', filenames)
        yield tuple(self._hdrcache)
        chunkiters = [_iterchunk(fn) for fn in filenames]
        rows = _mergesorted(self._getkey, self.reverse, *chunkiters)
        try:
            for row in rows:
                yield tuple(row)
        finally:
            debug('attempt cleanup from generator')
            # N.B., need to ensure that any open files are closed **before**
            # temporary files are deleted, as deletion will fail on Windows
            # if file is in use (i.e., still open)
            del chunkiters
            del rows
            del filecache
            debug('exiting generator')

    def _iternocache(self, source, key, reverse):
        debug('iterate without cache')
        self.clearcache()
        if self.sort_specs is not None:
            self.sort_specs = _prepare_sort_specs(self.sort_specs)
        it = iter(source)

        try:
            hdr = next(it)
        except StopIteration:
            if key is None and self.sort_specs is None:
                return  # nothing to do on a table without headers
            hdr = []
        yield tuple(hdr)

        if self.sort_specs is not None:
            resolved_specs = _resolve_sort_specs(hdr, self.sort_specs)
        elif key is not None:
            # convert field selection into field indices
            indices = asindices(hdr, key)
        else:
            indices = range(len(hdr))
        # now use field indices to construct a _getkey function
        if self.sort_specs is not None:
            def getkey(row):
                return _make_row_sort_key(resolved_specs, row)
            reverse = False
        else:
            getkey = comparable_itemgetter(*indices)

        # TODO support native comparison

        # initialise the first chunk
        rows = list(itertools.islice(it, 0, self.buffersize))
        rows.sort(key=getkey, reverse=reverse)

        # have we exhausted the source iterator?
        if self.buffersize is None or len(rows) < self.buffersize:
            # yes, table fits within sort buffer

            if self._cache:
                debug('caching mem')
                self._hdrcache = hdr
                self._memcache = rows
                # actually not needed to iterate from memcache
                self._getkey = getkey

            for row in rows:
                yield tuple(row)

        else:
            # no, table is too big, need to sort in chunks

            chunkfiles = []

            while rows:

                # dump the chunk
                with NamedTemporaryFile(dir=self.tempdir, delete=False,
                                        mode='wb') as f:
                    # N.B., we **don't** want the file to be deleted on close,
                    # but we **do** want the file to be deleted when self
                    # is garbage collected, or when the program exits. When
                    # all references to the wrapper are gone, the file should
                    # get deleted.
                    wrapper = _NamedTempFileDeleteOnGC(f.name)
                    debug('created temporary chunk file %s' % f.name)
                    for row in rows:
                        pickle.dump(row, f, protocol=-1)
                    f.flush()
                    chunkfiles.append(wrapper)

                # grab the next chunk
                rows = list(itertools.islice(it, 0, self.buffersize))
                rows.sort(key=getkey, reverse=reverse)

            if self._cache:
                debug('caching files')
                self._hdrcache = hdr
                self._filecache = chunkfiles
                self._getkey = getkey

            chunkiters = [_iterchunk(f.name) for f in chunkfiles]
            for row in _mergesorted(getkey, reverse, *chunkiters):
                yield tuple(row)


class _NamedTempFileDeleteOnGC(object):

    def __init__(self, name):
        self.name = name

    def delete(self, unlink=os.unlink, log=logger.debug):
        name = self.name
        try:
            log('deleting %s' % name)
            unlink(name)
        except Exception as e:
            log('exception deleting %s: %s' % (name, e))
            raise
        else:
            log('deleted %s' % name)

    def __del__(self):
        self.delete()

    def __str__(self):
        return self.name

    def __repr__(self):
        return self.name


def mergesort(*tables, **kwargs):
    """
    Combine multiple input tables into one sorted output table. E.g.::

        >>> import petl as etl
        >>> table1 = [['foo', 'bar'],
        ...           ['A', 9],
        ...           ['C', 2],
        ...           ['D', 10],
        ...           ['A', 6],
        ...           ['F', 1]]
        >>> table2 = [['foo', 'bar'],
        ...           ['B', 3],
        ...           ['D', 10],
        ...           ['A', 10],
        ...           ['F', 4]]
        >>> table3 = etl.mergesort(table1, table2, key='foo')
        >>> table3.lookall()
        +-----+-----+
        | foo | bar |
        +=====+=====+
        | 'A' |   9 |
        +-----+-----+
        | 'A' |   6 |
        +-----+-----+
        | 'A' |  10 |
        +-----+-----+
        | 'B' |   3 |
        +-----+-----+
        | 'C' |   2 |
        +-----+-----+
        | 'D' |  10 |
        +-----+-----+
        | 'D' |  10 |
        +-----+-----+
        | 'F' |   1 |
        +-----+-----+
        | 'F' |   4 |
        +-----+-----+

    If the input tables are already sorted by the given key, give
    ``presorted=True`` as a keyword argument.

    This function is equivalent to concatenating the input tables using
    :func:`cat` then sorting, however this function will typically be more
    efficient, especially if the input tables are presorted.

    Keyword arguments:

    key : string or tuple of strings, optional
        Field name or tuple of fields to sort by (defaults to `None` lexical
        sort)
    reverse : bool, optional
        `True` if sort in reverse (descending) order (defaults to `False`)
    presorted : bool, optional
        `True` if inputs are already sorted by the given key (defaults to
        `False`)
    missing : object
        Value to fill with when input tables have different fields (defaults to
        `None`)
    header : sequence of strings, optional
        Specify a fixed header for the output table
    buffersize : int, optional
        Limit the number of rows in memory per input table when inputs are not
        presorted

    sort_specs : sequence, optional
        Per-field sort specifications; cannot be combined with `key` or
        `reverse`.

    """

    return MergeSortView(tables, **kwargs)


Table.mergesort = mergesort


class MergeSortView(Table):
    def __init__(self, tables, key=None, reverse=False, presorted=False,
                 missing=None, header=None, buffersize=None, tempdir=None,
                 cache=True, sort_specs=None, specs=None):
        if sort_specs is not None and specs is not None:
            raise ArgumentError('specs and sort_specs are aliases')
        if sort_specs is None:
            sort_specs = specs
        if sort_specs is not None:
            if key is not None or reverse:
                raise ArgumentError(
                    'sort_specs cannot be combined with key or reverse'
                )
            sort_specs = _prepare_sort_specs(sort_specs)
        self.key = key
        self.sort_specs = sort_specs
        if presorted:
            self.tables = tables
        else:
            self.tables = [sort(t, key=key, reverse=reverse,
                                buffersize=buffersize, tempdir=tempdir,
                                cache=cache, sort_specs=sort_specs)
                           for t in tables]
        self.missing = missing
        self._header = header
        self.reverse = reverse

    def __iter__(self):
        return itermergesort(self.tables, self.key, self._header, self.missing,
                             self.reverse, self.sort_specs)


def itermergesort(sources, key, header, missing, reverse, sort_specs=None):
    # first need to standardise headers of all input tables
    # borrow this from itercat - TODO remove code smells

    its = [iter(t) for t in sources]
    src_hdrs = []
    for it in its:
        try:
            src_hdrs.append(next(it))
        except StopIteration:
            src_hdrs.append([])

    if header is None:
        # determine output fields by gathering all fields found in the sources
        outhdr = list()
        for hdr in src_hdrs:
            for f in list(map(text_type, hdr)):
                if f not in outhdr:
                    # add any new fields as we find them
                    outhdr.append(f)
    else:
        # predetermined output fields
        outhdr = header
    yield tuple(outhdr)

    def _standardisedata(it, hdr, ofs):
        flds = list(map(text_type, hdr))
        # now construct and yield the data rows
        for _row in it:
            try:
                # should be quickest to do this way
                yield tuple(_row[flds.index(fo)] if fo in flds else missing
                            for fo in ofs)
            except IndexError:
                # handle short rows
                outrow = [missing] * len(ofs)
                for i, fi in enumerate(flds):
                    try:
                        outrow[ofs.index(fi)] = _row[i]
                    except IndexError:
                        pass  # be relaxed about short rows
                yield tuple(outrow)

    # wrap all iterators to standardise fields
    sits = [_standardisedata(it, hdr, outhdr)
            for hdr, it in zip(src_hdrs, its)]

    # now determine key function
    getkey = None
    if sort_specs is not None:
        prepared_specs = _prepare_sort_specs(sort_specs)
        resolved_specs = _resolve_sort_specs(outhdr, prepared_specs)
        def getkey(row):
            return _make_row_sort_key(resolved_specs, row)
        reverse = False
    elif key is not None:
        # convert field selection into field indices
        indices = asindices(outhdr, key)
        # now use field indices to construct a _getkey function
        # N.B., this will probably raise an exception on short rows
        getkey = comparable_itemgetter(*indices)

    # OK, do the merge sort
    for row in _shortlistmergesorted(getkey, reverse, *sits):
        yield row


def issorted(table, key=None, reverse=False, strict=False):
    """
    Return True if the table is ordered (i.e., sorted) by the given key. E.g.::

        >>> import petl as etl
        >>> table1 = [['foo', 'bar', 'baz'],
        ...           ['a', 1, True],
        ...           ['b', 3, True],
        ...           ['b', 2]]
        >>> etl.issorted(table1, key='foo')
        True
        >>> etl.issorted(table1, key='bar')
        False
        >>> etl.issorted(table1, key='foo', strict=True)
        False
        >>> etl.issorted(table1, key='foo', reverse=True)
        False

    """

    # determine the operator to use when comparing rows
    if reverse and strict:
        op = operator.lt
    elif reverse and not strict:
        op = operator.le
    elif strict:
        op = operator.gt
    else:
        op = operator.ge

    it = iter(table)
    try:
        flds = [text_type(f) for f in next(it)]
    except StopIteration:
        flds = []
    if key is None:
        prev = next(it)
        for curr in it:
            if not op(curr, prev):
                return False
            prev = curr
    else:
        getkey = comparable_itemgetter(*asindices(flds, key))
        prev = next(it)
        prevkey = getkey(prev)
        for curr in it:
            currkey = getkey(curr)
            if not op(currkey, prevkey):
                return False
            prevkey = currkey
    return True


Table.issorted = issorted
