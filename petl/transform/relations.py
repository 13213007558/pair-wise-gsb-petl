# -*- coding: utf-8 -*-
from __future__ import absolute_import, print_function, division


import itertools
import logging
from collections import OrderedDict
from operator import itemgetter


import petl.config as config
from petl.compat import text_type
from petl.comparison import Comparable
from petl.errors import ArgumentError
from petl.util.base import Table, iterdata
from petl.transform.basics import cut, addrownumbers
from petl.transform.sorts import sort


logger = logging.getLogger(__name__)
warning = logger.warning
info = logger.info
debug = logger.debug


PROBLEMS_HEADER = ('name', 'table', 'row', 'fields', 'value', 'error',
                   'ref_table', 'ref_fields')

UNIQUE_VIOLATION = 'UniqueViolation'
FOREIGN_KEY_VIOLATION = 'ForeignKeyViolation'
NULL_KEY_VIOLATION = 'NullKeyViolation'

NULLS_IGNORE = 'ignore'
NULLS_REPORT = 'report'


def validate_relations(tables, constraints, buffersize=None, tempdir=None):
    """
    Check a set of named tables against relational constraints, i.e.,
    composite unique keys and composite foreign keys, e.g.::

        >>> import petl as etl
        >>> orders = (('order_id', 'customer'),
        ...           (1, 'alice'),
        ...           (2, 'bob'))
        >>> items = (('item', 'order_id'),
        ...          ('apple', 1),
        ...          ('banana', 2),
        ...          ('cherry', 3),
        ...          ('damson', None))
        >>> constraints = [
        ...     dict(name='pk_orders', table='orders', fields='order_id'),
        ...     dict(name='fk_items_orders', table='items',
        ...          fields='order_id', references='orders',
        ...          ref_fields='order_id', nulls='report'),
        ... ]
        >>> problems = etl.validate_relations({'orders': orders,
        ...                                    'items': items}, constraints)
        >>> problems.lookall()
        +-------------------+---------+-----+---------------+---------+-----------------------+-----------+---------------+
        | name              | table   | row | fields        | value   | error                 | ref_table | ref_fields    |
        +===================+=========+=====+===============+=========+=======================+===========+===============+
        | 'fk_items_orders' | 'items' |   4 | ('order_id',) | (None,) | 'NullKeyViolation'    | 'orders'  | ('order_id',) |
        +-------------------+---------+-----+---------------+---------+-----------------------+-----------+---------------+
        | 'fk_items_orders' | 'items' |   3 | ('order_id',) | (3,)    | 'ForeignKeyViolation' | 'orders'  | ('order_id',) |
        +-------------------+---------+-----+---------------+---------+-----------------------+-----------+---------------+

    The tables argument maps table names to tables, either as a dictionary
    or as a sequence of (name, table) pairs. The constraints argument
    is a sequence of dictionaries, each declaring either a unique key
    constraint or a foreign key constraint:

    - name: the constraint name, reported with any problems found
    - table: the name of the table the constraint applies to
    - fields: a field name or sequence of field names making up the
      (possibly compound) key
    - references: (foreign keys only) the name of the referenced table
    - ref_fields: (foreign keys only) a field name or sequence of field
      names making up the key in the referenced table, defaults to the
      value of fields
    - nulls: (foreign keys only) how to handle rows where any component
      of the foreign key is None; 'ignore' (the default) skips such
      rows, 'report' emits a 'NullKeyViolation' problem for them

    A constraint without references is treated as a unique key
    constraint on table.

    Returns a table of problems with the header ('name', 'table', 'row',
    'fields', 'value', 'error', 'ref_table', 'ref_fields'), where row
    is the 1-based number of the offending data row in table, value
    is the offending key as a tuple, and error is one of
    'UniqueViolation', 'ForeignKeyViolation' or
    'NullKeyViolation'. The ref_table and ref_fields values
    identify the other side of a foreign key constraint, and are None
    for unique key constraints.

    If a foreign key matches a key that occurs more than once in the
    referenced table, a 'UniqueViolation' problem is reported for each
    row of the referenced table holding the duplicated key, i.e., the
    lookup does not silently keep the first matching row.

    Each input table is consumed at most once, no matter how many
    constraints reference it, so tables may be given as one-shot iterators.
    Key projections are cached and sorted using the same buffer and
    temporary file facilities as petl.transform.sorts.sort; the
    buffersize and tempdir arguments are passed through to it. Checking
    does not modify the source tables in any way.

    """  # noqa

    return RelationProblemsView(tables, constraints, buffersize=buffersize,
                                tempdir=tempdir)


class RelationProblemsView(Table):

    def __init__(self, tables, constraints, buffersize=None, tempdir=None):
        if hasattr(tables, 'items'):
            tables = tables.items()
        self._tables = OrderedDict(tables)
        if buffersize is None:
            buffersize = config.sort_buffersize
        self._buffersize = buffersize
        self._tempdir = tempdir
        self._constraints = [_normalize_constraint(c, self._tables)
                             for c in constraints]
        # lazily built {(table name, key fields): sorted key stream view},
        # built at most once so one-shot source iterators are consumed once
        self._key_streams = None

    def __iter__(self):
        if self._key_streams is None:
            self._key_streams = self._build_key_streams()
        yield PROBLEMS_HEADER
        for constraint in self._constraints:
            if constraint['references'] is None:
                groups = _iter_key_groups(
                    self._iter_key_stream(constraint['table'],
                                          constraint['fields']))
                for problem in _iter_unique_problems(constraint, groups):
                    yield problem
            else:
                source_groups = _iter_key_groups(
                    self._iter_key_stream(constraint['table'],
                                          constraint['fields']))
                target_groups = _iter_key_groups(
                    self._iter_key_stream(constraint['references'],
                                          constraint['ref_fields']))
                for problem in _iter_foreign_key_problems(
                        constraint, source_groups, target_groups):
                    yield problem

    def _build_key_streams(self):
        # figure out which key projections are needed from each table
        roles = OrderedDict()
        for constraint in self._constraints:
            _register_role(roles, constraint['table'], constraint['fields'])
            if constraint['references'] is not None:
                _register_role(roles, constraint['references'],
                               constraint['ref_fields'])
        # consume each table at most once, projecting the needed fields plus
        # row numbers, and cache the projection via the sort machinery so
        # it can be re-iterated (from memory or temporary files) by as many
        # constraints as needed
        projections = OrderedDict()
        rowfields = {}
        for name, fieldtuples in roles.items():
            needed = []
            for fields in fieldtuples:
                for field in fields:
                    if field not in needed:
                        needed.append(field)
            rowfield = '__row__'
            while rowfield in needed:
                rowfield = '_' + rowfield
            projection = cut(self._tables[name], *needed)
            projection = addrownumbers(projection, field=rowfield)
            projection = sort(projection, key=rowfield,
                              buffersize=self._buffersize,
                              tempdir=self._tempdir, cache=True)
            projections[name] = projection
            rowfields[name] = rowfield
        # build a sorted key stream per (table, fields) role, shared by all
        # constraints using the same role
        streams = {}
        for name, fieldtuples in roles.items():
            rowfield = rowfields[name]
            for fields in fieldtuples:
                stream = cut(projections[name], *(list(fields) + [rowfield]))
                stream = sort(stream, key=list(fields),
                              buffersize=self._buffersize,
                              tempdir=self._tempdir, cache=True)
                streams[(name, fields)] = stream
        return streams

    def _iter_key_stream(self, table, fields):
        stream = self._key_streams[(table, fields)]
        for row in iterdata(stream):
            yield tuple(row[:-1]), row[-1]


def _normalize_constraint(constraint, tables):
    constraint = dict(constraint)
    name = constraint.get('name')
    table = constraint.get('table')
    if table not in tables:
        raise ArgumentError('unknown table: %r' % (table,))
    fields = constraint.get('fields')
    if fields is None:
        raise ArgumentError('constraint %r is missing fields' % (name,))
    fields = _astuple(fields)
    references = constraint.get('references')
    if references is None:
        ref_fields = None
        nulls = None
    else:
        if references not in tables:
            raise ArgumentError('unknown table: %r' % (references,))
        ref_fields = _astuple(constraint.get('ref_fields', fields))
        if len(ref_fields) != len(fields):
            raise ArgumentError(
                'constraint %r has %d key fields but %d referenced fields'
                % (name, len(fields), len(ref_fields)))
        nulls = constraint.get('nulls', NULLS_IGNORE)
        if nulls not in (NULLS_IGNORE, NULLS_REPORT):
            raise ArgumentError(
                "constraint %r has invalid nulls policy %r, expected "
                "'ignore' or 'report'" % (name, nulls))
    return dict(name=name, table=table, fields=fields,
                references=references, ref_fields=ref_fields, nulls=nulls)


def _astuple(fields):
    if isinstance(fields, text_type):
        return (fields,)
    return tuple(fields)


def _register_role(roles, table, fields):
    roles.setdefault(table, [])
    if fields not in roles[table]:
        roles[table].append(fields)


def _iter_key_groups(stream):
    # stream is sorted by key, so equal keys are adjacent
    for key, group in itertools.groupby(stream, key=itemgetter(0)):
        yield key, [rowno for _, rowno in group]


def _iter_unique_problems(constraint, groups):
    name = constraint['name']
    table = constraint['table']
    fields = constraint['fields']
    for key, rownos in groups:
        if len(rownos) > 1:
            for rowno in sorted(rownos):
                yield (name, table, rowno, fields, key,
                       UNIQUE_VIOLATION, None, None)


def _iter_foreign_key_problems(constraint, source_groups, target_groups):
    name = constraint['name']
    table = constraint['table']
    fields = constraint['fields']
    ref_table = constraint['references']
    ref_fields = constraint['ref_fields']
    report_nulls = constraint['nulls'] == NULLS_REPORT
    target = next(target_groups, None)
    for key, rownos in source_groups:
        if any(value is None for value in key):
            if report_nulls:
                for rowno in sorted(rownos):
                    yield (name, table, rowno, fields, key,
                           NULL_KEY_VIOLATION, ref_table, ref_fields)
            continue
        comparable = Comparable(key)
        while target is not None and Comparable(target[0]) < comparable:
            target = next(target_groups, None)
        if target is not None and Comparable(target[0]) == comparable:
            target_rownos = target[1]
            if len(target_rownos) > 1:
                # the referenced key is not unique, report every row
                # holding it rather than silently keeping the first
                for rowno in sorted(target_rownos):
                    yield (name, ref_table, rowno, ref_fields, key,
                           UNIQUE_VIOLATION, table, fields)
        else:
            for rowno in sorted(rownos):
                yield (name, table, rowno, fields, key,
                       FOREIGN_KEY_VIOLATION, ref_table, ref_fields)
