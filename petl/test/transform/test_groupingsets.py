from __future__ import absolute_import, print_function, division


import os

from collections import OrderedDict

from petl.test.helpers import ieq, eq_
from petl.util import strjoin
from petl.transform.groupingsets import groupingsets, rollup, cube,     Aggregator


table1 = (('region', 'product', 'sales'),
          ('north', 'apple', 3),
          ('north', 'pear', 7),
          ('south', 'apple', 2),
          ('south', 'pear', 4))


def _agg():
    aggregation = OrderedDict()
    aggregation['total'] = 'sales', sum
    aggregation['count'] = len
    return aggregation


def test_groupingsets():
    table2 = groupingsets(
        table1,
        keys=[('region',), ('product',), ('region', 'product'), ()],
        aggregation=_agg())
    expect2 = (('region', 'product', 'grouping_id', 'total', 'count'),
               ('north', None, 2, 10, 2),
               ('south', None, 2, 6, 2),
               (None, 'apple', 1, 5, 2),
               (None, 'pear', 1, 11, 2),
               ('north', 'apple', 0, 3, 1),
               ('north', 'pear', 0, 7, 1),
               ('south', 'apple', 0, 2, 1),
               ('south', 'pear', 0, 4, 1),
               (None, None, 3, 16, 4))
    ieq(expect2, table2)
    ieq(expect2, table2)  # can iterate twice


def test_groupingsets_simple_callable():
    table2 = groupingsets(table1, keys=[('region',), ()],
                          aggregation=sum, value='sales')
    expect2 = (('region', 'grouping_id', 'value'),
               ('north', 0, 10),
               ('south', 0, 6),
               (None, 1, 16))
    ieq(expect2, table2)


def test_groupingsets_real_none_vs_subtotal():
    # real None values in the data must be distinguishable from the None
    # used for dimensions that are not part of a grouping set
    table = (('region', 'product', 'sales'),
             (None, 'apple', 1),
             ('north', 'apple', 2),
             (None, 'pear', 5))
    actual = groupingsets(table, keys=[('region',), ()],
                          aggregation=_agg())
    expect = (('region', 'grouping_id', 'total', 'count'),
              (None, 0, 6, 2),      # real None group
              ('north', 0, 2, 1),
              (None, 1, 8, 3))      # grand total, region aggregated away
    ieq(expect, actual)


def test_groupingsets_group_in_only_one_dimension():
    # region 'east' only ever appears with product 'apple'
    table = (('region', 'product', 'sales'),
             ('east', 'apple', 9),
             ('west', 'pear', 1))
    actual = groupingsets(table, keys=[('region',), ('product',), ()],
                          aggregation=_agg())
    expect = (('region', 'product', 'grouping_id', 'total', 'count'),
              ('east', None, 2, 9, 1),
              ('west', None, 2, 1, 1),
              (None, 'apple', 1, 9, 1),
              (None, 'pear', 1, 1, 1),
              (None, None, 3, 10, 2))
    ieq(expect, actual)


def test_groupingsets_empty_table():
    table = (('region', 'product', 'sales'),)
    aggregation = OrderedDict()
    aggregation['total'] = 'sales', sum
    aggregation['count'] = len
    aggregation['minsales'] = 'sales', min
    aggregation['maxsales'] = 'sales', max
    aggregation['joined'] = 'region', strjoin(', ')
    aggregation['listed'] = 'sales', list
    actual = groupingsets(table, keys=[('region',), ('region', 'product'),
                                       ()],
                          aggregation=aggregation)
    # only the grand total row is produced, with values determined by
    # each aggregation applied to empty input
    expect = (('region', 'product', 'grouping_id', 'total', 'count',
               'minsales', 'maxsales', 'joined', 'listed'),
              (None, None, 3, 0, 0, None, None, '', []))
    ieq(expect, actual)


def test_groupingsets_duplicate_sets_are_deduped():
    actual = groupingsets(table1,
                          keys=[('region',), ('region',), (), None, ()],
                          aggregation=_agg())
    expect = (('region', 'grouping_id', 'total', 'count'),
              ('north', 0, 10, 2),
              ('south', 0, 6, 2),
              (None, 1, 16, 4))
    ieq(expect, actual)


def test_groupingsets_no_aggregation():
    actual = groupingsets(table1, keys=[('region',), ()])
    expect = (('region', 'grouping_id'),
              ('north', 0),
              ('south', 0),
              (None, 1))
    ieq(expect, actual)


def test_rollup():
    actual = rollup(table1, keys=('region', 'product'), aggregation=_agg())
    expect = groupingsets(table1,
                          keys=[('region', 'product'), ('region',), ()],
                          aggregation=_agg())
    ieq(expect, actual)
    ieq(expect, actual)


def test_cube():
    actual = cube(table1, keys=('region', 'product'), aggregation=_agg())
    expect = groupingsets(table1,
                          keys=[('region', 'product'), ('region',),
                                ('product',), ()],
                          aggregation=_agg())
    ieq(expect, actual)


def test_groupingsets_single_pass():
    # upstream must be read exactly once, however many sets are requested
    iterations = []

    class CountingSource(object):
        def __iter__(self):
            iterations.append(1)
            return iter(table1)

    table2 = groupingsets(
        CountingSource(),
        keys=[('region',), ('product',), ('region', 'product'), ()],
        aggregation=_agg())
    # iterate manually, as list() would also call __len__ as a hint
    rows = [row for row in iter(table2)]
    eq_(10, len(rows))
    eq_(1, len(iterations))


def test_groupingsets_spill(tmp_path):
    # force spilling with a tiny buffer; results must be identical and
    # states from different sets must not be merged together
    keys = [('region',), ('product',), ('region', 'product'), ()]
    expect = (('region', 'product', 'grouping_id', 'total', 'count'),
              ('north', None, 2, 10, 2),
              ('south', None, 2, 6, 2),
              (None, 'apple', 1, 5, 2),
              (None, 'pear', 1, 11, 2),
              ('north', 'apple', 0, 3, 1),
              ('north', 'pear', 0, 7, 1),
              ('south', 'apple', 0, 2, 1),
              ('south', 'pear', 0, 4, 1),
              (None, None, 3, 16, 4))
    actual = groupingsets(table1, keys=keys, aggregation=_agg(),
                          buffersize=1, tempdir=str(tmp_path))
    ieq(expect, actual)
    # spill files are cleaned up
    eq_([], os.listdir(str(tmp_path)))


def test_groupingsets_spill_colliding_keys(tmp_path):
    # the same key value appears in different grouping sets; spilling
    # must not merge states across sets
    table = (('region', 'product', 'sales'),
             ('a', 'a', 1),
             ('a', 'b', 2),
             ('b', 'a', 4))
    keys = [('region',), ('product',)]
    expect = (('region', 'product', 'grouping_id', 'total', 'count'),
              ('a', None, 2, 3, 2),
              ('b', None, 2, 4, 1),
              (None, 'a', 1, 5, 2),
              (None, 'b', 1, 2, 1))
    for buffersize in (None, 1, 2, 3):
        actual = groupingsets(table, keys=keys, aggregation=_agg(),
                              buffersize=buffersize, tempdir=str(tmp_path))
        ieq(expect, actual)


class Mean(Aggregator):
    # custom aggregation that declares itself mergeable
    mergeable = True

    def initial(self):
        return (0, 0)

    def update(self, state, value):
        return (state[0] + value, state[1] + 1)

    def merge(self, left, right):
        return (left[0] + right[0], left[1] + right[1])

    def finalize(self, state):
        if state[1] == 0:
            return None
        return state[0] / state[1]


def test_groupingsets_custom_mergeable_aggregator(tmp_path):
    aggregation = OrderedDict()
    aggregation['mean'] = 'sales', Mean()
    expect = (('region', 'grouping_id', 'mean'),
              ('north', 0, 5.0),
              ('south', 0, 3.0),
              (None, 1, 4.0))
    for buffersize in (None, 1):
        actual = groupingsets(table1, keys=[('region',), ()],
                              aggregation=aggregation,
                              buffersize=buffersize,
                              tempdir=str(tmp_path))
        ieq(expect, actual)


class NonMergeableMax(Aggregator):
    # custom aggregation that declares itself non-mergeable
    mergeable = False

    def initial(self):
        return []

    def update(self, state, value):
        state.append(value)
        return state

    def finalize(self, state):
        if not state:
            return None
        return max(state)


def test_groupingsets_nonmergeable_disables_spill(tmp_path):
    # a non-mergeable custom aggregation must not be spilled, but the
    # results must still be correct and the upstream read only once
    aggregation = OrderedDict()
    aggregation['mx'] = 'sales', NonMergeableMax()
    expect = (('region', 'grouping_id', 'mx'),
              ('north', 0, 7),
              ('south', 0, 4),
              (None, 1, 7))
    actual = groupingsets(table1, keys=[('region',), ()],
                          aggregation=aggregation,
                          buffersize=1, tempdir=str(tmp_path))
    ieq(expect, actual)
    # nothing was spilled to disk
    eq_([], os.listdir(str(tmp_path)))


def test_groupingsets_list_aggregation_spec():
    actual = groupingsets(table1, keys=[('region',), ()],
                          aggregation=[('total', 'sales', sum),
                                       ('count', len)])
    expect = (('region', 'grouping_id', 'total', 'count'),
              ('north', 0, 10, 2),
              ('south', 0, 6, 2),
              (None, 1, 16, 4))
    ieq(expect, actual)


def test_groupingsets_min_max():
    aggregation = OrderedDict()
    aggregation['lo'] = 'sales', min
    aggregation['hi'] = 'sales', max
    actual = groupingsets(table1, keys=[('region',), ()],
                          aggregation=aggregation)
    expect = (('region', 'grouping_id', 'lo', 'hi'),
              ('north', 0, 3, 7),
              ('south', 0, 2, 4),
              (None, 1, 2, 7))
    ieq(expect, actual)
