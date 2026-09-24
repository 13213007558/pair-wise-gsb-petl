# -*- coding: utf-8 -*-
from __future__ import absolute_import, print_function, division


import operator
from petl.compat import text_type


from petl.comparison import Comparable
from petl.errors import ArgumentError
from petl.transform.sorts import sort
from petl.util.base import Table, asindices, rowgetter, Record


def validate(table, constraints=None, header=None):
    """
    Validate a `table` against a set of `constraints` and/or an expected
    `header`, e.g.::

        >>> import petl as etl
        >>> # define some validation constraints
        ... header = ('foo', 'bar', 'baz')
        >>> constraints = [
        ...     dict(name='foo_int', field='foo', test=int),
        ...     dict(name='bar_date', field='bar', test=etl.dateparser('%Y-%m-%d')),
        ...     dict(name='baz_enum', field='baz', assertion=lambda v: v in ['Y', 'N']),
        ...     dict(name='not_none', assertion=lambda row: None not in row),
        ...     dict(name='qux_int', field='qux', test=int, optional=True),
        ... ]
        >>> # now validate a table
        ... table = (('foo', 'bar', 'bazzz'),
        ...          (1, '2000-01-01', 'Y'),
        ...          ('x', '2010-10-10', 'N'),
        ...          (2, '2000/01/01', 'Y'),
        ...          (3, '2015-12-12', 'x'),
        ...          (4, None, 'N'),
        ...          ('y', '1999-99-99', 'z'),
        ...          (6, '2000-01-01'),
        ...          (7, '2001-02-02', 'N', True))
        >>> problems = etl.validate(table, constraints=constraints, header=header)
        >>> problems.lookall()
        +--------------+-----+-------+--------------+------------------+
        | name         | row | field | value        | error            |
        +==============+=====+=======+==============+==================+
        | '__header__' |   0 | None  | None         | 'AssertionError' |
        +--------------+-----+-------+--------------+------------------+
        | 'foo_int'    |   2 | 'foo' | 'x'          | 'ValueError'     |
        +--------------+-----+-------+--------------+------------------+
        | 'bar_date'   |   3 | 'bar' | '2000/01/01' | 'ValueError'     |
        +--------------+-----+-------+--------------+------------------+
        | 'baz_enum'   |   4 | 'baz' | 'x'          | 'AssertionError' |
        +--------------+-----+-------+--------------+------------------+
        | 'bar_date'   |   5 | 'bar' | None         | 'AttributeError' |
        +--------------+-----+-------+--------------+------------------+
        | 'not_none'   |   5 | None  | None         | 'AssertionError' |
        +--------------+-----+-------+--------------+------------------+
        | 'foo_int'    |   6 | 'foo' | 'y'          | 'ValueError'     |
        +--------------+-----+-------+--------------+------------------+
        | 'bar_date'   |   6 | 'bar' | '1999-99-99' | 'ValueError'     |
        +--------------+-----+-------+--------------+------------------+
        | 'baz_enum'   |   6 | 'baz' | 'z'          | 'AssertionError' |
        +--------------+-----+-------+--------------+------------------+
        | '__len__'    |   7 | None  |            2 | 'AssertionError' |
        +--------------+-----+-------+--------------+------------------+
        | 'baz_enum'   |   7 | 'baz' | None         | 'AssertionError' |
        +--------------+-----+-------+--------------+------------------+
        | '__len__'    |   8 | None  |            4 | 'AssertionError' |
        +--------------+-----+-------+--------------+------------------+

    Returns a table of validation problems.

    """  # noqa

    return ProblemsView(table, constraints=constraints, header=header)


Table.validate = validate


class ProblemsView(Table):

    def __init__(self, table, constraints, header):
        self.table = table
        self.constraints = constraints
        self._header = header

    def __iter__(self):
        return iterproblems(self.table, self.constraints, self._header)


def normalize_constraints(constraints, flds):
    """
    This method renders local constraints such that return value is:
      * a list, not None
      * a list of dicts
      * a list of non-optional constraints or optional with defined field

    .. note:: We use a new variable 'local_constraints' because the constraints
              parameter may be a mutable collection, and we do not wish to
              cause side-effects by modifying it locally
    """
    local_constraints = constraints or []
    local_constraints = [dict(**c) for c in local_constraints]
    local_constraints = [
        c for c in local_constraints
        if c.get('field') in flds or
        not c.get('optional')
    ]
    return local_constraints


def iterproblems(table, constraints, expected_header):

    outhdr = ('name', 'row', 'field', 'value', 'error')
    yield outhdr

    it = iter(table)
    try:
        actual_header = next(it)
    except StopIteration:
        actual_header = []

    if expected_header is None:
        flds = list(map(text_type, actual_header))
    else:
        expected_flds = list(map(text_type, expected_header))
        actual_flds = list(map(text_type, actual_header))
        try:
            assert expected_flds == actual_flds
        except Exception as e:
            yield ('__header__', 0, None, None, type(e).__name__)
        flds = expected_flds

    local_constraints = normalize_constraints(constraints, flds)

    # setup getters
    for constraint in local_constraints:
        if 'getter' not in constraint:
            if 'field' in constraint:
                # should ensure FieldSelectionError if bad field in constraint
                indices = asindices(flds, constraint['field'])
                getter = operator.itemgetter(*indices)
                constraint['getter'] = getter

    # generate problems
    expected_len = len(flds)
    for i, row in enumerate(it):
        row = tuple(row)

        # row length constraint
        l = None
        try:
            l = len(row)
            assert l == expected_len
        except Exception as e:
            yield ('__len__', i+1, None, l, type(e).__name__)

        # user defined constraints
        row = Record(row, flds)
        for constraint in local_constraints:
            name = constraint.get('name', None)
            field = constraint.get('field', None)
            assertion = constraint.get('assertion', None)
            test = constraint.get('test', None)
            getter = constraint.get('getter', lambda x: x)
            try:
                target = getter(row)
            except Exception as e:
                # getting target value failed, report problem
                yield (name, i+1, field, None, type(e).__name__)
            else:
                value = target if field else None
                if test is not None:
                    try:
                        test(target)
                    except Exception as e:
                        # test raised exception, report problem
                        yield (name, i+1, field, value, type(e).__name__)
                if assertion is not None:
                    try:
                        assert assertion(target)
                    except Exception as e:
                        # assertion raised exception, report problem
                        yield (name, i+1, field, value, type(e).__name__)


def validate_relations(tables, constraints, buffersize=None, tempdir=None):
    """
    Validate relational constraints across a collection of named tables,
    e.g. composite unique keys and composite foreign keys, typically before
    loading a set of related tables into a database. E.g.::

        >>> import petl as etl
        >>> orders = [
        ...     ("order_id", "region", "amount"),
        ...     (1, "east", 10.0),
        ...     (2, "west", 20.0),
        ...     (2, "west", 30.0),
        ... ]
        >>> items = [
        ...     ("item_id", "order_id", "region"),
        ...     ("a", 1, "east"),
        ...     ("b", 2, "west"),
        ...     ("c", 3, "east"),
        ...     ("d", None, None),
        ... ]
        >>> tables = {"orders": orders, "items": items}
        >>> constraints = [
        ...     dict(name="pk_orders", type="unique", table="orders",
        ...          fields=("order_id", "region")),
        ...     dict(name="fk_items_orders", type="foreign_key",
        ...          table="items", fields=("order_id", "region"),
        ...          references="orders", ref_fields=("order_id", "region")),
        ... ]
        >>> problems = etl.validate_relations(tables, constraints)
        >>> problems.lookall()
        +-------------------+----------+-----+------------------------+-------------+-----------+------------------------+-----------------------+
        | name              | table    | row | fields                 | value       | ref_table | ref_fields             | error                 |
        +===================+==========+=====+========================+=============+===========+========================+=======================+
        | 'pk_orders'       | 'orders' |   2 | ('order_id', 'region') | (2, 'west') | None      | None                   | 'UniqueViolation'     |
        +-------------------+----------+-----+------------------------+-------------+-----------+------------------------+-----------------------+
        | 'pk_orders'       | 'orders' |   3 | ('order_id', 'region') | (2, 'west') | None      | None                   | 'UniqueViolation'     |
        +-------------------+----------+-----+------------------------+-------------+-----------+------------------------+-----------------------+
        | 'fk_items_orders' | 'orders' |   2 | ('order_id', 'region') | (2, 'west') | None      | None                   | 'UniqueViolation'     |
        +-------------------+----------+-----+------------------------+-------------+-----------+------------------------+-----------------------+
        | 'fk_items_orders' | 'orders' |   3 | ('order_id', 'region') | (2, 'west') | None      | None                   | 'UniqueViolation'     |
        +-------------------+----------+-----+------------------------+-------------+-----------+------------------------+-----------------------+
        | 'fk_items_orders' | 'items'  |   3 | ('order_id', 'region') | (3, 'east') | 'orders'  | ('order_id', 'region') | 'ForeignKeyViolation' |
        +-------------------+----------+-----+------------------------+-------------+-----------+------------------------+-----------------------+

    The `tables` argument maps names to tables (a dictionary, or a sequence
    of ``(name, table)`` pairs). Each table is consumed at most once, no
    matter how many constraints reference it, so tables may be given as
    one-shot iterators.

    The `constraints` argument is a sequence of dictionaries. A unique key
    constraint looks like::

        dict(name="pk_orders", type="unique", table="orders",
             fields=("order_id", "region"))

    and a foreign key constraint looks like::

        dict(name="fk_items_orders", type="foreign_key", table="items",
             fields=("order_id", "region"), references="orders",
             ref_fields=("order_id", "region"), nulls="ignore")

    If `ref_fields` is not given, it defaults to the same field names as
    `fields`. The `nulls` option controls how foreign key rows containing
    `None` values are treated: with `"ignore"` (the default) they are
    skipped, with `"forbid"` they are reported as `"NullKeyViolation"`
    problems.

    Returns a table of validation problems with the columns `name`,
    `table`, `row`, `fields`, `value`, `ref_table`, `ref_fields` and
    `error`, where `row` is the 1-based number of the offending row in the
    source table, and `value` is the offending key. Possible errors are
    `"UniqueViolation"` (a key appears more than once in a table declared
    as unique, or in the referenced table of a foreign key),
    `"ForeignKeyViolation"` (a foreign key has no matching referenced key)
    and `"NullKeyViolation"` (a foreign key containing `None` under a
    `nulls="forbid"` policy).

    Note that when checking a foreign key, duplicate keys in the
    referenced table are reported as `"UniqueViolation"` problems rather
    than being masked by arbitrarily matching the first row.

    Tables are sorted by their key fields to find duplicates and to match
    foreign keys against referenced keys. The `buffersize` and `tempdir`
    arguments are passed through to :func:`petl.transform.sorts.sort`, so
    tables larger than the sort buffer are processed via temporary files
    and a merge sort. Validation never modifies the source tables.

    """

    tables = _normalize_tables(tables)
    constraints = _normalize_relational_constraints(constraints, tables)
    return RelationProblemsView(tables, constraints, buffersize=buffersize,
                                tempdir=tempdir)


class RelationProblemsView(Table):

    def __init__(self, tables, constraints, buffersize=None, tempdir=None):
        self.tables = tables
        self.constraints = constraints
        self.buffersize = buffersize
        self.tempdir = tempdir

    def __iter__(self):
        return iterrelationproblems(self.tables, self.constraints,
                                    buffersize=self.buffersize,
                                    tempdir=self.tempdir)


def _normalize_tables(tables):
    if hasattr(tables, "items"):
        items = list(tables.items())
    else:
        items = list(tables)
    table_map = dict()
    for name, table in items:
        if name in table_map:
            raise ArgumentError("duplicate table name: %r" % (name,))
        table_map[name] = table
    return table_map


def _as_field_tuple(spec):
    if isinstance(spec, (list, tuple)):
        return tuple(spec)
    return (spec,)


def _normalize_relational_constraints(constraints, tables):
    local_constraints = list()
    for constraint in constraints or []:
        # work on a copy, do not modify the caller data
        c = dict(constraint)
        ctype = c.get("type")
        if ctype is None:
            ctype = "foreign_key" if "references" in c else "unique"
        if ctype not in ("unique", "foreign_key"):
            raise ArgumentError("invalid constraint type: %r" % (ctype,))
        name = c.get("name")
        table = c.get("table")
        if table not in tables:
            raise ArgumentError("constraint %r declares unknown table: %r"
                                % (name, table))
        if "fields" not in c:
            raise ArgumentError("constraint %r does not declare any fields"
                                % (name,))
        fields = _as_field_tuple(c["fields"])
        normalized = dict(name=name, type=ctype, table=table, fields=fields)
        if ctype == "foreign_key":
            ref_table = c.get("references")
            if ref_table not in tables:
                raise ArgumentError(
                    "constraint %r references unknown table: %r"
                    % (name, ref_table))
            ref_fields = _as_field_tuple(c.get("ref_fields", fields))
            if len(ref_fields) != len(fields):
                raise ArgumentError(
                    "constraint %r declares %d fields but %d referenced "
                    "fields" % (name, len(fields), len(ref_fields)))
            nulls = c.get("nulls", "ignore")
            if nulls not in ("ignore", "forbid"):
                raise ArgumentError(
                    "constraint %r has invalid nulls policy: %r, expected "
                    "'ignore' or 'forbid'" % (name, nulls))
            normalized.update(references=ref_table, ref_fields=ref_fields,
                              nulls=nulls)
        local_constraints.append(normalized)
    return local_constraints


def iterrelationproblems(tables, constraints, buffersize=None, tempdir=None):

    yield ("name", "table", "row", "fields", "value",
           "ref_table", "ref_fields", "error")

    caches = dict()

    def cache_for(name):
        if name not in caches:
            caches[name] = _RelationalTableCache(tables[name],
                                                 buffersize=buffersize,
                                                 tempdir=tempdir)
        return caches[name]

    for constraint in constraints:
        name = constraint["name"]
        if constraint["type"] == "unique":
            sorted_table = cache_for(constraint["table"]).sorted_by(
                constraint["fields"])
            for problem in _iter_unique_problems(
                    sorted_table, name, constraint["table"],
                    constraint["fields"]):
                yield problem
        else:
            child_sorted = cache_for(constraint["table"]).sorted_by(
                constraint["fields"])
            ref_sorted = cache_for(constraint["references"]).sorted_by(
                constraint["ref_fields"])
            # a foreign key implies the referenced key is unique, so report
            # duplicates on the referenced side rather than arbitrarily
            # matching the first row
            for problem in _iter_unique_problems(
                    ref_sorted, name, constraint["references"],
                    constraint["ref_fields"]):
                yield problem
            for problem in _iter_fk_problems(child_sorted, ref_sorted,
                                             constraint):
                yield problem


class _RowNumbersView(Table):
    """Append a source row number column to a table, numbering data rows
    from 1."""

    def __init__(self, table):
        self.table = table

    def __iter__(self):
        it = iter(self.table)
        try:
            hdr = next(it)
        except StopIteration:
            return
        flds = list(map(text_type, hdr))
        rowfield = "__row__"
        while rowfield in flds:
            rowfield = "_" + rowfield
        yield tuple(hdr) + (rowfield,)
        for i, row in enumerate(it):
            yield tuple(row) + (i + 1,)


class _RelationalTableCache(object):
    """Provide sorted views of a table on demand, caching sorted results so
    the underlying table is consumed at most once, no matter how many
    constraints reference it. Sorting spills to temporary files via the
    standard sort machinery when a table does not fit in the sort buffer."""

    def __init__(self, table, buffersize=None, tempdir=None):
        self._table = table
        self._buffersize = buffersize
        self._tempdir = tempdir
        self._sorted = dict()

    def sorted_by(self, fields):
        fields = tuple(fields)
        if fields not in self._sorted:
            if self._sorted:
                # chain off an existing (cached) sorted view, so the
                # original table is not consumed again
                source = next(iter(self._sorted.values()))
            else:
                source = _RowNumbersView(self._table)
            self._sorted[fields] = sort(source, key=list(fields),
                                        buffersize=self._buffersize,
                                        tempdir=self._tempdir, cache=True)
        return self._sorted[fields]


def _key_getter(hdr, fields):
    # rows carry the source row number appended as the last column by
    # _RowNumbersView, so only the key fields need to be selected here
    return rowgetter(*asindices(hdr, fields))


def _iter_unique_problems(sorted_table, name, table, fields):
    it = iter(sorted_table)
    try:
        hdr = next(it)
    except StopIteration:
        return
    getkey = _key_getter(hdr, fields)
    previous_key = previous_row = None
    have_previous = False
    in_duplicate = False
    for row in it:
        row = tuple(row)
        key = getkey(row)
        if have_previous and key == previous_key:
            if not in_duplicate:
                in_duplicate = True
                yield (name, table, previous_row[-1], fields, previous_key,
                       None, None, "UniqueViolation")
            yield (name, table, row[-1], fields, key,
                   None, None, "UniqueViolation")
        else:
            in_duplicate = False
            previous_key = key
            previous_row = row
            have_previous = True


def _iter_fk_problems(child_sorted, ref_sorted, constraint):
    name = constraint["name"]
    table = constraint["table"]
    fields = constraint["fields"]
    ref_table = constraint["references"]
    ref_fields = constraint["ref_fields"]
    nulls = constraint["nulls"]

    child_it = iter(child_sorted)
    try:
        child_hdr = next(child_it)
    except StopIteration:
        return
    child_getkey = _key_getter(child_hdr, fields)

    ref_it = iter(ref_sorted)
    try:
        ref_hdr = next(ref_it)
    except StopIteration:
        ref_hdr = []
    ref_getkey = _key_getter(ref_hdr, ref_fields)

    # both sides are sorted by key, so a merge pass suffices to find
    # foreign keys with no matching referenced key
    sentinel = object()
    ref_row = next(ref_it, sentinel)
    if ref_row is sentinel:
        ref_key = None
        ref_available = False
    else:
        ref_key = Comparable(ref_getkey(tuple(ref_row)))
        ref_available = True

    for row in child_it:
        row = tuple(row)
        key = child_getkey(row)
        if any(value is None for value in key):
            if nulls == "forbid":
                yield (name, table, row[-1], fields, key, ref_table,
                       ref_fields, "NullKeyViolation")
            continue
        comparable_key = Comparable(key)
        while ref_available and ref_key < comparable_key:
            # advance to the next distinct referenced key
            ref_row = next(ref_it, sentinel)
            if ref_row is sentinel:
                ref_available = False
            else:
                next_ref_key = Comparable(ref_getkey(tuple(ref_row)))
                if next_ref_key != ref_key:
                    ref_key = next_ref_key
        if not ref_available or ref_key != comparable_key:
            yield (name, table, row[-1], fields, key, ref_table, ref_fields,
                   "ForeignKeyViolation")
