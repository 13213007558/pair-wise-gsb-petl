# -*- coding: utf-8 -*-
from __future__ import absolute_import, print_function, division

from tempfile import NamedTemporaryFile

from petl.compat import pickle
from petl.errors import ArgumentError
from petl.util.base import Table


class Missing(object):
    """
    Sentinel type used as the default marker for missing values in
    :func:`petl.io.nested.flattenrecords`. The singleton instance
    :data:`MISSING` is not equal to None (JSON null) or to any other
    value, so absent fields can be told apart from explicit nulls in
    the input records.

    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(Missing, cls).__new__(cls)
        return cls._instance

    def __repr__(self):
        return '<missing>'

    def __reduce__(self):
        # pickle round-trips to the singleton
        return (Missing, ())


MISSING = Missing()


class RecordSchemaError(ValueError):
    """
    Raised by :func:`petl.io.nested.flattenrecords` when an input record
    does not conform to the schema discovered so far. Carries the
    1-based input record number as .line and the offending field as a
    tuple of path segments as .path.

    """

    def __init__(self, line, path, message):
        self.line = line
        self.path = tuple(path)
        super(RecordSchemaError, self).__init__(
            'record %s, field %s: %s'
            % (line, format_path(self.path), message))


def format_path(path):
    """
    Render a field path (a tuple of key segments) unambiguously, e.g.
    ('a', 'b') becomes record['a']['b'].

    """
    return 'record' + ''.join('[%r]' % (segment,) for segment in path)


def flattenrecords(records, missing=MISSING, on_conflict='error',
                   spool_maxbytes=2 ** 20, tempdir=None):
    """
    Flatten a one-shot stream of nested records (e.g. decoded JSON
    objects) into a rectangular table. The full schema is discovered
    before any row is emitted, so fields that only appear in later
    records still get their own column. E.g.::

        >>> import petl as etl
        >>> records = [{'name': 'Gilbert', 'geo': {'lat': 51.5, 'lon': 0.1}},
        ...            {'name': 'Alexa', 'tags': ['x', 'y']},
        ...            {'name': 'May', 'geo': {'lat': 40.7}, 'extra.field': 1}]
        >>> table = etl.flattenrecords(records)
        >>> table
        +-----------+----------------+----------------+------------+------------------+
        | ('name',) | ('geo', 'lat') | ('geo', 'lon') | ('tags',)  | ('extra.field',) |
        +===========+================+================+============+==================+
        | 'Gilbert' |           51.5 |            0.1 | <missing>  | <missing>        |
        +-----------+----------------+----------------+------------+------------------+
        | 'Alexa'   | <missing>      | <missing>      | ['x', 'y'] | <missing>        |
        +-----------+----------------+----------------+------------+------------------+
        | 'May'     |           40.7 | <missing>      | <missing>  |                1 |
        +-----------+----------------+----------------+------------+------------------+

    Each header entry is a tuple of key path segments, so a key that
    literally contains a dot (e.g. 'extra.field') is never confused
    with nesting: ('extra.field',) and ('extra', 'field') are
    different fields. Columns are ordered by first discovery.

    Dictionaries are recursively expanded; lists and any other
    non-mapping values are kept as a single value. Values are passed
    through unchanged - no date or number inference is applied, strings
    stay strings.

    The missing argument is the marker used for fields absent from a
    record. It defaults to the :data:`MISSING` sentinel, which is
    distinct from None (JSON null).

    If the same path holds a scalar in some records and a mapping in
    others, the behaviour is selected with on_conflict:

    - 'error' (default): raise :class:`RecordSchemaError`, reporting the
      input record number and the field path.
    - 'branch': keep both type branches, i.e. the scalar value stays in
      the column for the path itself and the mapping is expanded into
      its own sub-columns.

    The source iterator is consumed exactly once. While the schema is
    discovered, flattened records are spooled through a buffer bounded
    to roughly spool_maxbytes bytes in memory, spilling to a temporary
    file (under tempdir if given) beyond that, so arbitrarily large
    inputs can be handled. The resulting table can be iterated more
    than once.

    """
    return FlattenRecordsView(records, missing=missing,
                              on_conflict=on_conflict,
                              spool_maxbytes=spool_maxbytes,
                              tempdir=tempdir)


class FlattenRecordsView(Table):

    def __init__(self, records, missing=MISSING, on_conflict='error',
                 spool_maxbytes=2 ** 20, tempdir=None):
        if on_conflict not in ('error', 'branch'):
            raise ArgumentError(
                "on_conflict must be 'error' or 'branch', got %r"
                % (on_conflict,))
        self._records = records
        self._missing = missing
        self._on_conflict = on_conflict
        self._spool = _BoundedSpool(spool_maxbytes, tempdir)
        self._header = None

    def __iter__(self):
        if self._header is None:
            self._discover_schema()
        header = self._header
        yield header
        index = dict((path, i) for i, path in enumerate(header))
        missing = self._missing
        for flat in self._spool:
            row = [missing] * len(header)
            for path, value in flat:
                row[index[path]] = value
            yield tuple(row)

    def _discover_schema(self):
        header = list()
        seen = set()
        leaf_paths = set()
        branch_paths = set()
        on_conflict = self._on_conflict
        for line, record in enumerate(self._records, start=1):
            flat = list()
            flatten_record(record, line, (), flat,
                           leaf_paths, branch_paths, on_conflict)
            for path, _value in flat:
                if path not in seen:
                    seen.add(path)
                    header.append(path)
            self._spool.append(flat)
        self._header = tuple(header)


def flatten_record(record, line, prefix, out,
                   leaf_paths, branch_paths, on_conflict):
    if not isinstance(record, dict):
        raise RecordSchemaError(
            line, prefix,
            'expected a mapping, found %r' % (record,))
    for key, value in record.items():
        path = prefix + (key,)
        if isinstance(value, dict):
            if on_conflict == 'error' and path in leaf_paths:
                raise RecordSchemaError(
                    line, path,
                    'value is a mapping but this field was previously '
                    'observed with a scalar value')
            branch_paths.add(path)
            flatten_record(value, line, path, out,
                           leaf_paths, branch_paths, on_conflict)
        else:
            if on_conflict == 'error' and path in branch_paths:
                raise RecordSchemaError(
                    line, path,
                    'value is not a mapping but this field was previously '
                    'observed as a mapping')
            leaf_paths.add(path)
            out.append((path, value))


class _BoundedSpool(object):
    """
    Buffer pickled items in memory up to a byte budget, then spill over
    to a temporary file. Items can be replayed any number of times.

    """

    def __init__(self, maxbytes, tempdir=None):
        self._maxbytes = maxbytes
        self._tempdir = tempdir
        self._chunks = list()
        self._size = 0
        self._file = None

    def append(self, item):
        chunk = pickle.dumps(item, protocol=-1)
        if self._file is None:
            self._chunks.append(chunk)
            self._size += len(chunk)
            if self._size > self._maxbytes:
                self._spill()
        else:
            self._file.write(chunk)

    def _spill(self):
        self._file = NamedTemporaryFile(dir=self._tempdir)
        for chunk in self._chunks:
            self._file.write(chunk)
        self._chunks = None

    def __iter__(self):
        if self._file is None:
            for chunk in self._chunks:
                yield pickle.loads(chunk)
        else:
            self._file.flush()
            self._file.seek(0)
            try:
                while True:
                    yield pickle.load(self._file)
            except EOFError:
                pass
