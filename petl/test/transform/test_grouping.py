from __future__ import absolute_import, print_function, division


from collections import OrderedDict

import pytest

from petl.test.helpers import ieq
from petl.errors import ArgumentError
from petl.transform.grouping import grouping_sets, rollup, cube, \
    GROUPING_NULL, Aggregate, MergeableAggregate


TABLE = (('region', 'product', 'units'),
         ('east', 'a', 1),
         ('east', 'a', None),
         ('west', None, 2),
         ('west', 'b', 3))


def _aggs():
    aggs = OrderedDict()
    aggs['n'] = len
    aggs['total'] = ('units', sum)
    aggs['minu'] = ('units', min)
    aggs['maxu'] = ('units', max)
    return aggs


def test_grouping_sets_all_four():
    expect = (('region', 'product', 'n', 'total', 'minu', 'maxu',
               'grouping_id'),
              ('east', 'a', 2, 1, 1, 1, 0),
              ('west', None, 1, 2, 2, 2, 0),
              ('west', 'b', 1, 3, 3, 3, 0),
              ('east', GROUPING_NULL, 2, 1, 1, 1, 1),
              ('west', GROUPING_NULL, 2, 5, 2, 3, 1),
              (GROUPING_NULL, None, 1, 2, 2, 2, 2),
              (GROUPING_NULL, 'a', 2, 1, 1, 1, 2),
              (GROUPING_NULL, 'b', 1, 3, 3, 3, 2),
              (GROUPING_NULL, GROUPING_NULL, 4, 6, 1, 3, 3))
    result = grouping_sets(TABLE, ('region', 'product'),
                           [('region', 'product'), ('region',),
                            ('product',), ()],
                           _aggs())
    ieq(expect, result)
    ieq(expect, result)  # iterable can be read twice


def test_grouping_id_distinguishes_real_none():
    result = grouping_sets(TABLE, ('region', 'product'),
                           [('product',), ()], {'n': len})
    rows = list(result)
    hdr = rows[0]
    assert hdr == ('region', 'product', 'n', 'grouping_id')
    # genuine None key for product is not replaced by GROUPING_NULL
    product_none = [r for r in rows[1:] if r[1] is None][0]
    assert product_none[0] is GROUPING_NULL
    assert product_none[3] == 2
    grand = [r for r in rows[1:] if r[3] == 3][0]
    assert grand[0] is GROUPING_NULL and grand[1] is GROUPING_NULL
    # every grouping-null cell corresponds to a set grouping_id bit
    for r in rows[1:]:
        if r[0] is GROUPING_NULL:
            assert r[3] & 2
        if r[1] is GROUPING_NULL:
            assert r[3] & 1


def test_grouping_sets_single_dimension_only():
    # a set with only one dimension: absent region columns are nulled out
    result = grouping_sets(TABLE, ('region', 'product'),
                           [('product',)], {'n': len})
    rows = list(result)
    assert rows[0] == ('region', 'product', 'n', 'grouping_id')
    assert set(tuple(r) for r in rows[1:]) == {
        (GROUPING_NULL, None, 1, 2),
        (GROUPING_NULL, 'a', 2, 2),
        (GROUPING_NULL, 'b', 1, 2),
    }


def test_grouping_sets_duplicate_sets_deduped():
    sets = [('region',), ('region',), (), ('region',), ()]
    seen = _consume(grouping_sets(
        TABLE, ('region', 'product'), sets, {'n': len}))
    # ('region',) -> 2 groups + () grand total = 3 data rows
    assert len(seen) == 4  # incl. header


def test_grouping_sets_empty_table():
    empty = (('region', 'product', 'units'),)
    result = grouping_sets(empty, ('region', 'product'),
                           [('region', 'product'), ('region',),
                            ('product',), ()],
                           _aggs())
    rows = list(result)
    assert rows[0] == ('region', 'product', 'n', 'total', 'minu', 'maxu',
                       'grouping_id')
    # only the grand total set emits a row; empty group follows each
    # aggregation's own definition
    assert rows[1] == (GROUPING_NULL, GROUPING_NULL, 0, None, None, None, 3)
    assert len(rows) == 2


def test_grouping_sets_empty_table_non_grand_sets_emit_nothing():
    empty = (('region', 'product', 'units'),)
    result = grouping_sets(empty, ('region', 'product'),
                           [('region',), ('product',)],
                           {'n': len})
    assert list(result) == [('region', 'product', 'n', 'grouping_id')]


def test_rollup_expands_prefixes():
    result = rollup(TABLE, ('region', 'product'), _aggs())
    gids = sorted(r[-1] for r in list(result)[1:])
    # pair (0), region prefix (1), grand total (3)
    assert gids == [0, 0, 0, 1, 1, 3]


def test_cube_expands_all_subsets():
    result = cube(TABLE, ('region', 'product'), {'n': len})
    gids = {r[-1] for r in list(result)[1:]}
    # 00, 01, 10, 11
    assert gids == {0, 1, 2, 3}


def test_rollup_cube_scalar_key():
    result = rollup(TABLE, 'region', {'n': len})
    assert {r[-1] for r in list(result)[1:]} == {0, 1}
    result = cube(TABLE, 'region', {'n': len})
    assert {r[-1] for r in list(result)[1:]} == {0, 1}


def test_states_are_not_merged_across_sets():
    # sum by region and sum over the whole table must not mix: the grand
    # total is the union of regional totals, never added to a regional
    # group's state
    result = grouping_sets(TABLE, ('region', 'product'),
                           [('region',), ()], {'n': len,
                                               'total': ('units', sum)})
    rows = list(result)[1:]
    region_rows = {r[0]: r for r in rows if r[-1] == 1}
    grand = [r for r in rows if r[-1] == 3][0]
    assert region_rows['east'][3] == 1
    assert region_rows['west'][3] == 5
    assert grand[3] == 6
    # counts never double-count rows across the two sets
    assert region_rows['east'][2] + region_rows['west'][2] == grand[2]


def test_simple_signature():
    result = grouping_sets(TABLE, ('region',), [('region',), ()],
                           sum, value='units')
    rows = list(result)
    assert rows[0] == ('region', 'value', 'grouping_id')
    assert set(rows[1:]) == {
        ('east', 1, 0), ('west', 5, 0), (GROUPING_NULL, 6, 1),
    }


def test_simple_signature_count_and_field():
    result = grouping_sets(TABLE, 'region', [('region',), ()], len,
                           field='nrows')
    rows = list(result)
    assert rows[0] == ('region', 'nrows', 'grouping_id')
    assert set(rows[1:]) == {
        ('east', 2, 0), ('west', 2, 0), (GROUPING_NULL, 4, 1),
    }


class WeightedMean(MergeableAggregate):

    def initial(self):
        return [0.0, 0]

    def update(self, state, value):
        x, w = value
        if x is not None:
            state[0] += x * w
            state[1] += w

    def merge(self, state, other):
        state[0] += other[0]
        state[1] += other[1]

    def finalize(self, state):
        return state[0] / state[1] if state[1] else None


def test_custom_mergeable_aggregate():
    table = (('k', 'x', 'w'),
             ('a', 10, 1), ('a', 20, 3),
             ('b', 40, 1), ('b', None, 1))
    result = grouping_sets(table, 'k', [('k',), ()],
                           {'wm': (('x', 'w'), WeightedMean())})
    rows = list(result)
    assert rows[0] == ('k', 'wm', 'grouping_id')
    by = {r[0]: r[1] for r in rows[1:]}
    assert by['a'] == 17.5
    assert by['b'] == 40.0
    # the None x row still contributes nowhere; grand total uses only
    # non-null x values: (10+60+40)/5
    assert by[GROUPING_NULL] == 22.0


class FirstValue(Aggregate):
    mergeable = False

    def initial(self):
        return []

    def update(self, state, value):
        if not state:
            # state keeps the whole first value
            state.append(value)

    def finalize(self, state):
        return state[0] if state else None


def test_custom_nonmergeable_aggregate_spilled():
    table = [('k', 'v')] + [(c, i) for c in ('a', 'b')
                            for i in range(6)]
    result = grouping_sets(table, 'k', [('k',), ()],
                           {'first': ('v', FirstValue()),
                            'vals': ('v', list)},
                           buffersize=3, tempdir=None)
    rows = list(result)
    by = {r[0]: r[1:] for r in rows[1:]}
    assert by['a'][:2] == (0, list(range(6)))
    assert by['b'][:2] == (0, list(range(6)))
    assert by[GROUPING_NULL][0] == 0
    assert sorted(by[GROUPING_NULL][1]) == [i for i in range(6) for _ in (0, 1)]
    assert by[GROUPING_NULL][2] == 1


def test_nonmergeable_in_memory_matches_spilled():
    table = [('region', 'product', 'units')] + [
        ('east' if i % 2 else 'west', 'p%d' % (i % 3), i)
        for i in range(12)]
    aggs = OrderedDict([('n', len), ('units', ('units', list))])
    inmem = _consume(grouping_sets(table, ('region', 'product'),
                                   [('region', 'product'), ('region',),
                                    ('product',), ()], aggs))
    spilled = _consume(grouping_sets(table, ('region', 'product'),
                                     [('region', 'product'), ('region',),
                                      ('product',), ()], aggs,
                                     buffersize=4))
    assert inmem == spilled
    # per-set lists are complete: spilling never combines states across
    # grouping sets, so the grand total has exactly 12 values
    grand = [r for r in inmem[1:] if r[-1] == 3][0]
    assert sorted(grand[3]) == list(range(12))


def test_mergeable_only_needs_no_buffering_and_reads_upstream_once():
    reads = [0]

    data = list(TABLE)

    class CountingSource(object):
        def __iter__(self):
            reads[0] += 1
            return iter(data)

    result = grouping_sets(CountingSource(), ('region', 'product'),
                           [('region', 'product'), ('region',),
                            ('product',), ()], _aggs())
    # iterate once without list()'s length-hint (__len__) probe
    for _ in iter(result):
        pass
    assert reads[0] == 1


def test_aggregate_requires_declared_mergeable():
    class Broken(Aggregate):
        def initial(self):
            return None

        def update(self, state, value):
            pass

        def finalize(self, state):
            return state

    result = grouping_sets(TABLE, 'region', [()],
                           {'x': ('units', Broken())})
    with pytest.raises(ArgumentError):
        list(result)


def test_reserved_grouping_id_field_rejected():
    with pytest.raises(ArgumentError):
        list(grouping_sets(TABLE, 'region', [()],
                           {'grouping_id': len}))


def test_invalid_set_member_rejected():
    with pytest.raises(ArgumentError):
        list(grouping_sets(TABLE, ('region', 'product'),
                           [('units',)], {'n': len}))


def _consume(view):
    return list(view)
