from __future__ import absolute_import, print_function, division


import itertools
import operator
import os
import pickle
import tempfile
from collections import OrderedDict


from petl.compat import string_types
from petl.errors import ArgumentError
from petl.util.base import Table
from petl import config


class Aggregator(object):
    """Base class for aggregations used with the groupingsets transform.

    Subclasses must implement initial(), update() and finalize(). If
    partial states can be combined (which allows intermediate results to
    be spilled to disk when the memory budget is exceeded), set the class
    attribute 'mergeable' to True and implement merge(). If 'mergeable'
    is False, spilling is disabled and all state is kept in memory, so
    the upstream is never re-read.

    """

    mergeable = True

    def initial(self):
        """Return a fresh initial state."""
        raise NotImplementedError

    def update(self, state, value):
        """Fold a single value into the state, returning the new state."""
        raise NotImplementedError

    def merge(self, left, right):
        """Combine two partial states into one."""
        raise NotImplementedError

    def finalize(self, state):
        """Produce the output value from the final state."""
        raise NotImplementedError


class SumAggregator(Aggregator):

    def initial(self):
        return 0

    def update(self, state, value):
        return state + value

    def merge(self, left, right):
        return left + right

    def finalize(self, state):
        return state


class CountAggregator(Aggregator):

    def initial(self):
        return 0

    def update(self, state, value):
        return state + 1

    def merge(self, left, right):
        return left + right

    def finalize(self, state):
        return state


class _Missing(object):
    """Pickle-safe singleton used as the empty state for min/max."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = object.__new__(cls)
        return cls._instance

    def __reduce__(self):
        return (_Missing, ())


MISSING = _Missing()


class MinAggregator(Aggregator):

    def initial(self):
        return MISSING

    def update(self, state, value):
        if state is MISSING:
            return value
        return min(state, value)

    def merge(self, left, right):
        if left is MISSING:
            return right
        if right is MISSING:
            return left
        return min(left, right)

    def finalize(self, state):
        if state is MISSING:
            return None
        return state


class MaxAggregator(Aggregator):

    def initial(self):
        return MISSING

    def update(self, state, value):
        if state is MISSING:
            return value
        return max(state, value)

    def merge(self, left, right):
        if left is MISSING:
            return right
        if right is MISSING:
            return left
        return max(left, right)

    def finalize(self, state):
        if state is MISSING:
            return None
        return state


class CollectAggregator(Aggregator):
    """Wraps an arbitrary callable. Values are collected into a list and
    the callable is applied once at the end. Concatenation of the
    buffered value lists is an exact merge, so spilling remains safe."""

    def __init__(self, func):
        self.func = func

    def initial(self):
        return []

    def update(self, state, value):
        state.append(value)
        return state

    def merge(self, left, right):
        return left + right

    def finalize(self, state):
        return self.func(state)


def _as_aggregator(agg):
    if isinstance(agg, Aggregator):
        return agg
    if agg is sum:
        return SumAggregator()
    if agg is len:
        return CountAggregator()
    if agg is min:
        return MinAggregator()
    if agg is max:
        return MaxAggregator()
    if callable(agg):
        return CollectAggregator(agg)
    raise ArgumentError('invalid aggregation function: %r' % (agg,))


def _normalise_sets(keys):
    if keys is None:
        keys = [()]
    if isinstance(keys, string_types):
        keys = [(keys,)]
    sets = []
    seen = set()
    key_fields = []
    for s in keys:
        if s is None:
            s = ()
        elif isinstance(s, string_types):
            s = (s,)
        else:
            s = tuple(s)
        if s in seen:
            continue
        seen.add(s)
        sets.append(s)
        for f in s:
            if f not in key_fields:
                key_fields.append(f)
    return sets, key_fields


def _normalise_aggregations(aggregation, value, field):
    spec = OrderedDict()
    if aggregation is None:
        pass
    elif callable(aggregation) or isinstance(aggregation, Aggregator):
        spec[field] = (value, aggregation)
    elif isinstance(aggregation, (list, tuple)):
        for t in aggregation:
            if len(t) == 1:
                spec[t[0]] = (None, list)
            elif len(t) == 2:
                if isinstance(t[1], string_types):
                    spec[t[0]] = (t[1], list)
                else:
                    spec[t[0]] = (None, t[1])
            else:
                spec[t[0]] = t[1:]
    elif isinstance(aggregation, dict):
        for outfld, agg in aggregation.items():
            if callable(agg) or isinstance(agg, Aggregator):
                spec[outfld] = (None, agg)
            elif isinstance(agg, string_types):
                spec[outfld] = (agg, list)
            elif len(agg) == 1 and isinstance(agg[0], string_types):
                spec[outfld] = (agg[0], list)
            elif len(agg) == 1:
                spec[outfld] = (None, agg[0])
            elif len(agg) == 2:
                spec[outfld] = tuple(agg)
            else:
                raise ArgumentError(
                    'invalid aggregation: %r, %r' % (outfld, agg))
    else:
        raise ArgumentError(
            'expected aggregation is callable, list, tuple, dict or None, '
            'found %r' % (aggregation,))
    return spec


def _make_getter(srcfld, hdr):
    if srcfld is None:
        return lambda row: row
    if isinstance(srcfld, (list, tuple)):
        idxs = [hdr.index(f) for f in srcfld]
        return operator.itemgetter(*idxs)
    idx = hdr.index(srcfld)
    return operator.itemgetter(idx)


def groupingsets(table, keys, aggregation=None, value=None, buffersize=None,
                 tempdir=None, field='value'):
    """Aggregate over multiple grouping sets in a single pass over the
    upstream table. E.g.::

        >>> import petl as etl
        >>> table1 = [['region', 'product', 'sales'],
        ...           ['north', 'apple', 3],
        ...           ['north', 'pear', 7],
        ...           ['south', 'apple', 2],
        ...           ['south', 'pear', 4]]
        >>> # subtotals by region, by product, by both, and grand total
        ... table2 = etl.groupingsets(
        ...     table1,
        ...     keys=[('region',), ('product',), ('region', 'product'), ()],
        ...     aggregation={'total': ('sales', sum), 'count': len})
        >>> table2.lookall()
        +---------+---------+-------------+-------+-------+
        | region  | product | grouping_id | total | count |
        +=========+=========+=============+=======+=======+
        | 'north' | None    |           2 |    10 |     2 |
        +---------+---------+-------------+-------+-------+
        | 'south' | None    |           2 |     6 |     2 |
        +---------+---------+-------------+-------+-------+
        | None    | 'apple' |           1 |     5 |     2 |
        +---------+---------+-------------+-------+-------+
        | None    | 'pear'  |           1 |    11 |     2 |
        +---------+---------+-------------+-------+-------+
        | 'north' | 'apple' |           0 |     3 |     1 |
        +---------+---------+-------------+-------+-------+
        | 'north' | 'pear'  |           0 |     7 |     1 |
        +---------+---------+-------------+-------+-------+
        | 'south' | 'apple' |           0 |     2 |     1 |
        +---------+---------+-------------+-------+-------+
        | 'south' | 'pear'  |           0 |     4 |     1 |
        +---------+---------+-------------+-------+-------+
        | None    | None    |           3 |    16 |     4 |
        +---------+---------+-------------+-------+-------+

    The 'keys' argument is a list of grouping sets, where each set is a
    tuple of field names to group by; the empty tuple () (or None)
    denotes the grand total. Duplicate sets are removed, keeping the
    first occurrence.

    Every output row contains all key fields; fields that are not part
    of the grouping set a row belongs to are filled with None. The
    'grouping_id' column distinguishes these from real None values in
    the data: it is a bitmask where bit i is set if the i-th key field
    has been aggregated away in that row (0 means all key fields are
    real values, 2 ** n - 1 is the grand total).

    The upstream table is read exactly once, no matter how many grouping
    sets are requested. Aggregation state is maintained per grouping
    set, so states from different sets are never combined.

    The built-in functions sum, len, min and max are evaluated using
    mergeable aggregation states. Any other callable is applied to the
    collected list of values. Custom aggregations may instead be given
    as an Aggregator instance, which explicitly declares whether its
    partial states can be merged via the 'mergeable' attribute.

    If the number of distinct groups exceeds 'buffersize', intermediate
    states are spilled to disk under 'tempdir' and merged at the end, so
    memory usage stays bounded. If 'buffersize' is None, the value of
    petl.config.sort_buffersize is used. Spilling is disabled if any
    custom aggregation declares itself non-mergeable.

    See also rollup() and cube().

    """

    return GroupingSetsView(table, keys, aggregation=aggregation, value=value,
                            buffersize=buffersize, tempdir=tempdir,
                            field=field)


Table.groupingsets = groupingsets


def rollup(table, keys, aggregation=None, value=None, buffersize=None,
           tempdir=None, field='value'):
    """Convenience wrapper around groupingsets() that expands 'keys' into
    the grouping sets of a SQL ROLLUP, i.e., all prefixes of 'keys' from
    the full key list down to the empty set (grand total). E.g.,
    rollup(table, ('region', 'product'), ...) is equivalent to
    groupingsets(table, [('region', 'product'), ('region',), ()], ...).

    """

    if isinstance(keys, string_types):
        keys = (keys,)
    keys = tuple(keys)
    sets = [keys[:i] for i in range(len(keys), -1, -1)]
    return groupingsets(table, sets, aggregation=aggregation, value=value,
                        buffersize=buffersize, tempdir=tempdir, field=field)


Table.rollup = rollup


def cube(table, keys, aggregation=None, value=None, buffersize=None,
         tempdir=None, field='value'):
    """Convenience wrapper around groupingsets() that expands 'keys' into
    the grouping sets of a SQL CUBE, i.e., all possible subsets of
    'keys', including the empty set (grand total).

    """

    if isinstance(keys, string_types):
        keys = (keys,)
    keys = tuple(keys)
    sets = []
    for r in range(len(keys), -1, -1):
        sets.extend(itertools.combinations(keys, r))
    return groupingsets(table, sets, aggregation=aggregation, value=value,
                        buffersize=buffersize, tempdir=tempdir, field=field)


Table.cube = cube


class GroupingSetsView(Table):

    def __init__(self, source, keys, aggregation=None, value=None,
                 buffersize=None, tempdir=None, field='value'):
        self.source = source
        self.sets, self.key_fields = _normalise_sets(keys)
        self.aggregation = _normalise_aggregations(aggregation, value, field)
        if buffersize is None:
            buffersize = config.sort_buffersize
        self.buffersize = buffersize
        self.tempdir = tempdir

    def __iter__(self):
        return itergroupingsets(self.source, self.sets, self.key_fields,
                                self.aggregation, self.buffersize,
                                self.tempdir)


def _spill(states, tempdir, spills):
    fd, path = tempfile.mkstemp(prefix='petl-groupingsets-', dir=tempdir)
    with os.fdopen(fd, 'wb') as f:
        pickle.dump(states, f, protocol=2)
    spills.append(path)


def _merge_states(dst, src, aggregators):
    for si in range(len(src)):
        dd = dst[si]
        for k, st in src[si].items():
            existing = dd.get(k)
            if existing is None:
                dd[k] = st
            else:
                for ai, agg in enumerate(aggregators):
                    existing[ai] = agg.merge(existing[ai], st[ai])


def itergroupingsets(source, sets, key_fields, aggregation, buffersize,
                     tempdir):
    it = iter(source)
    hdr = tuple(next(it))

    keyidx = [hdr.index(f) for f in key_fields]

    outflds = []
    aggregators = []
    getters = []
    for outfld, (srcfld, agg) in aggregation.items():
        outflds.append(outfld)
        aggregators.append(_as_aggregator(agg))
        getters.append(_make_getter(srcfld, hdr))

    # per grouping set: positions of its fields within key_fields, and
    # the grouping_id bitmask (bit i set <=> key_fields[i] aggregated)
    set_specs = []
    for s in sets:
        positions = tuple(key_fields.index(f) for f in s)
        gid = 0
        for i, f in enumerate(key_fields):
            if f not in s:
                gid |= 1 << i
        set_specs.append((positions, gid))

    yield tuple(key_fields) + ('grouping_id',) + tuple(outflds)

    spillable = all(agg.mergeable for agg in aggregators)
    states = [dict() for _ in sets]
    ngroups = 0
    spills = []
    try:
        for row in it:
            keyvals = tuple(row[i] for i in keyidx)
            aggvals = [g(row) for g in getters]
            for si, (positions, gid) in enumerate(set_specs):
                k = tuple(keyvals[p] for p in positions)
                d = states[si]
                st = d.get(k)
                if st is None:
                    st = [agg.initial() for agg in aggregators]
                    d[k] = st
                    ngroups += 1
                for ai, agg in enumerate(aggregators):
                    st[ai] = agg.update(st[ai], aggvals[ai])
            if spillable and buffersize is not None \
                    and ngroups >= buffersize:
                _spill(states, tempdir, spills)
                states = [dict() for _ in sets]
                ngroups = 0

        # merge spilled partitions and the in-memory states, per set
        combined = [dict() for _ in sets]
        for path in spills:
            with open(path, 'rb') as f:
                _merge_states(combined, pickle.load(f), aggregators)
        _merge_states(combined, states, aggregators)
    finally:
        for path in spills:
            if os.path.exists(path):
                os.remove(path)

    # the empty grouping set always yields exactly one grand total row,
    # even when the input table had no data rows
    for si, (positions, gid) in enumerate(set_specs):
        if not positions and () not in combined[si]:
            combined[si][()] = [agg.initial() for agg in aggregators]

    for si, (positions, gid) in enumerate(set_specs):
        for k, st in combined[si].items():
            outrow = [None] * len(key_fields)
            for p, v in zip(positions, k):
                outrow[p] = v
            outrow.append(gid)
            for ai, agg in enumerate(aggregators):
                outrow.append(agg.finalize(st[ai]))
            yield tuple(outrow)
