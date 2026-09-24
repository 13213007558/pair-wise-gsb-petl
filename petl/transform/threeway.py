from __future__ import absolute_import, division, print_function

import itertools
from collections import namedtuple

from petl.comparison import comparable_itemgetter
from petl.compat import next
from petl.errors import ArgumentError, DuplicateKeyError
from petl.transform.basics import addrownumbers
from petl.transform.sorts import sort
from petl.util.base import Table, asindices, header


class _MissingType(object):
    # sentinel for a field that is absent from a table's header, which must
    # be distinguished from a cell value of None

    def __repr__(self):
        return 'MISSING'


MISSING = _MissingType()


#: Reasons reported in the conflicts table.
CONFLICT_BOTH_MODIFIED = 'both_modified'
CONFLICT_DELETE_VS_MODIFY = 'delete_vs_modify'
CONFLICT_BOTH_ADDED = 'both_added'


#: Result of :func:'threewaymerge', a pair of table views.
ThreeWayMergeResult = namedtuple('ThreeWayMergeResult',
                                 ['merged', 'conflicts'])


def threewaymerge(base, left, right, key, missing=None, buffersize=None,
                  tempdir=None, cache=True):
    """
    Perform a three-way merge of two tables ('left' and 'right') that were
    both derived from a common 'base' table, matching rows by the given
    business 'key'. Returns a pair of table views, (merged, conflicts).
    E.g.::

        >>> import petl as etl
        >>> base = [['id', 'name', 'qty'],
        ...         [1, 'apple', 10],
        ...         [2, 'banana', 20],
        ...         [3, 'cherry', 30]]
        >>> # left changed qty of row 1 and deleted row 2
        ... left = [['id', 'name', 'qty'],
        ...         [1, 'apple', 11],
        ...         [3, 'cherry', 30]]
        >>> # right changed qty of row 2
        ... right = [['id', 'name', 'qty'],
        ...          [1, 'apple', 10],
        ...          [2, 'banana', 25],
        ...          [3, 'cherry', 30]]
        >>> merged, conflicts = etl.threewaymerge(base, left, right, key='id')
        >>> merged.lookall()
        +----+----------+-----+
        | id | name     | qty |
        +====+==========+=====+
        |  1 | 'apple'  |  11 |
        +----+----------+-----+
        |  3 | 'cherry' |  30 |
        +----+----------+-----+

        >>> conflicts.lookall()
        +----+-------+------------+------------+-------------+----------+----------+-----------+--------------------+
        | id | field | base_value | left_value | right_value | base_row | left_row | right_row | reason             |
        +====+=======+============+============+=============+==========+==========+===========+====================+
        |  2 | 'qty' |         20 | None       |          25 |        2 | None     |         2 | 'delete_vs_modify' |
        +----+-------+------------+------------+-------------+----------+----------+-----------+--------------------+

    Changes made by only one side, or made identically by both sides, are
    merged. If both sides changed the same field to different values, the
    row is reported in the conflicts table instead of being merged. A row
    deleted on one side is dropped from the merged table only if the other
    side did not modify it, otherwise a conflict is reported. Rows added on
    both sides under the same key are merged only if they are identical.

    The conflicts table reports the conflicting field, the original value
    from each of the three tables and the 1-based row number of the record
    in each source table ('None' where the row or field is absent).

    Fields may appear in a different order in each table, and tables may
    have different sets of fields. A field that is absent from a table's
    header is treated as missing, which is distinct from a cell value of
    'None'; missing values are represented as 'missing' (default 'None')
    in the output.

    By default, duplicate key values in any of the input tables are
    rejected with a 'petl.errors.DuplicateKeyError' locating all
    offending rows; no implicit pairing of duplicate rows is attempted.

    The 'buffersize', 'tempdir' and 'cache' arguments are passed through to
    'petl.transform.sorts.sort', which is used to order each input by
    the key before merging. Use a small 'buffersize' to force external
    sorting; the order of the merged rows and conflicts is stable either
    way.

    """

    merged = ThreeWayMergeView(base, left, right, key, missing=missing,
                               buffersize=buffersize, tempdir=tempdir,
                               cache=cache)
    conflicts = ThreeWayConflictsView(base, left, right, key, missing=missing,
                                      buffersize=buffersize, tempdir=tempdir,
                                      cache=cache)
    return ThreeWayMergeResult(merged, conflicts)


Table.threewaymerge = threewaymerge


def _keyfields(key):
    if isinstance(key, (list, tuple)):
        return list(key)
    return [key]


def _rownumfield(hdr):
    f = 'rownum'
    while f in hdr:
        f = '_' + f
    return f


class ThreeWayMergeView(Table):

    def __init__(self, base, left, right, key, missing=None, buffersize=None,
                 tempdir=None, cache=True):
        self.base = base
        self.left = left
        self.right = right
        self.key = key
        self.missing = missing
        self.buffersize = buffersize
        self.tempdir = tempdir
        self.cache = cache

    def __iter__(self):
        it = _iterthreeway(self.base, self.left, self.right, self.key,
                           self.missing, self.buffersize, self.tempdir,
                           self.cache)
        for event in it:
            if event[0] == 'header':
                yield event[1]
            elif event[0] == 'merged':
                yield event[1]


class ThreeWayConflictsView(Table):

    def __init__(self, base, left, right, key, missing=None, buffersize=None,
                 tempdir=None, cache=True):
        self.base = base
        self.left = left
        self.right = right
        self.key = key
        self.missing = missing
        self.buffersize = buffersize
        self.tempdir = tempdir
        self.cache = cache

    def __iter__(self):
        it = _iterthreeway(self.base, self.left, self.right, self.key,
                           self.missing, self.buffersize, self.tempdir,
                           self.cache)
        for event in it:
            if event[0] == 'header':
                yield event[2]
            elif event[0] == 'conflict':
                yield event[1]


def _iterthreeway(base, left, right, key, missing, buffersize, tempdir,
                  cache):
    keyfields = _keyfields(key)
    tables = (('base', base), ('left', left), ('right', right))

    # validate headers and determine the union of data fields, preserving
    # the order fields first appear in across base, left, right
    hdrs = dict()
    for name, tbl in tables:
        hdr = header(tbl)
        for f in keyfields:
            if f not in hdr:
                raise ArgumentError(
                    'key field %r not found in %s table header: %r'
                    % (f, name, hdr))
        hdrs[name] = hdr
    datafields = list()
    for name, tbl in tables:
        for f in hdrs[name]:
            if f not in keyfields and f not in datafields:
                datafields.append(f)

    mergedhdr = tuple(keyfields + datafields)
    conflictshdr = tuple(keyfields) + (
        'field', 'base_value', 'left_value', 'right_value',
        'base_row', 'left_row', 'right_row', 'reason')
    yield ('header', mergedhdr, conflictshdr)

    groups = _iterkeygroups(tables, keyfields, buffersize, tempdir, cache)
    for rows in groups:
        for event in _mergegroup(keyfields, datafields, rows, missing):
            yield event


def _iterkeygroups(tables, keyfields, buffersize, tempdir, cache):
    # prepare a sorted, row-numbered iterator per source, then merge the
    # three sorted streams of key groups
    names = list()
    groupits = list()
    rowhdrs = list()
    for name, tbl in tables:
        names.append(name)
        hdr = header(tbl)
        rownumfield = _rownumfield(hdr)
        numbered = addrownumbers(tbl, start=1, field=rownumfield)
        sortedtbl = sort(numbered, key=list(keyfields) + [rownumfield],
                         buffersize=buffersize, tempdir=tempdir, cache=cache)
        it = iter(sortedtbl)
        hdr = next(it)
        rowhdrs.append(hdr)
        kind = asindices(hdr, keyfields)
        getk = comparable_itemgetter(*kind)
        groupits.append(itertools.groupby(it, key=getk))

    pending = [None, None, None]
    active = [False, False, False]
    for i, git in enumerate(groupits):
        try:
            pending[i] = next(git)
            active[i] = True
        except StopIteration:
            pass

    while any(active):
        # find the smallest pending key
        minkey = None
        for i in range(3):
            if active[i] and (minkey is None or pending[i][0] < minkey):
                minkey = pending[i][0]
        rows = dict()
        for i in range(3):
            if not active[i]:
                continue
            kval, grp = pending[i]
            if minkey < kval or kval < minkey:
                continue
            grp = list(grp)
            if len(grp) > 1:
                rownums = [row[0] for row in grp]
                raise DuplicateKeyError(
                    kval.inner,
                    '%s table rows: %s' % (names[i], rownums))
            row = grp[0]
            # row number was prepended by addrownumbers
            rows[names[i]] = (row[0], dict(zip(rowhdrs[i][1:], row[1:])))
            try:
                pending[i] = next(groupits[i])
            except StopIteration:
                active[i] = False
        yield rows


def _outvalue(side, field, missing):
    if side is None:
        return missing
    value = side[1].get(field, MISSING)
    return missing if value is MISSING else value


def _conflictrow(keyfields, keyvals, field, b, l, r, missing, reason):
    row = list(keyvals)
    row.append(field)
    for side in (b, l, r):
        row.append(_outvalue(side, field, missing))
    for side in (b, l, r):
        row.append(side[0] if side is not None else None)
    row.append(reason)
    return ('conflict', tuple(row))


def _mergedrow(keyfields, datafields, keyvals, values, missing):
    row = list(keyvals)
    for f in datafields:
        value = values.get(f, MISSING)
        row.append(missing if value is MISSING else value)
    return ('merged', tuple(row))


def _mergegroup(keyfields, datafields, rows, missing):
    b = rows.get('base')
    l = rows.get('left')
    r = rows.get('right')
    for side in (b, l, r):
        if side is not None:
            keyvals = [side[1][f] for f in keyfields]
            break

    if b is None:
        # added on one or both sides
        if l is not None and r is not None:
            diffs = [f for f in datafields
                     if l[1].get(f, MISSING) != r[1].get(f, MISSING)]
            if diffs:
                for f in diffs:
                    yield _conflictrow(keyfields, keyvals, f, b, l, r,
                                       missing, CONFLICT_BOTH_ADDED)
            else:
                yield _mergedrow(keyfields, datafields, keyvals, l[1],
                                 missing)
        elif l is not None:
            yield _mergedrow(keyfields, datafields, keyvals, l[1], missing)
        else:
            yield _mergedrow(keyfields, datafields, keyvals, r[1], missing)
        return

    if l is None and r is None:
        # deleted on both sides
        return

    if l is None or r is None:
        # deleted on one side, deletion stands only if the other side did
        # not modify the record
        keep = r if l is None else l
        diffs = [f for f in datafields
                 if keep[1].get(f, MISSING) != b[1].get(f, MISSING)]
        for f in diffs:
            yield _conflictrow(keyfields, keyvals, f, b, l, r, missing,
                               CONFLICT_DELETE_VS_MODIFY)
        return

    # present in all three tables, merge field by field
    values = dict()
    diffs = list()
    for f in datafields:
        bv = b[1].get(f, MISSING)
        lv = l[1].get(f, MISSING)
        rv = r[1].get(f, MISSING)
        lchanged = lv != bv
        rchanged = rv != bv
        if lchanged and rchanged:
            if lv == rv:
                values[f] = lv
            else:
                diffs.append(f)
        elif lchanged:
            values[f] = lv
        elif rchanged:
            values[f] = rv
        else:
            values[f] = bv
    if diffs:
        for f in diffs:
            yield _conflictrow(keyfields, keyvals, f, b, l, r, missing,
                               CONFLICT_BOTH_MODIFIED)
    else:
        yield _mergedrow(keyfields, datafields, keyvals, values, missing)
