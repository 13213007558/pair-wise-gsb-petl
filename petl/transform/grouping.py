from __future__ import absolute_import, print_function, division


import itertools
import operator
import os
from collections import OrderedDict
from tempfile import NamedTemporaryFile

import petl.config as config
from petl.compat import next, string_types, pickle, text_type
from petl.comparison import Comparable
from petl.errors import ArgumentError
from petl.util.base import Table, asindices, Record, rowgetter
from petl.transform.sorts import _iterchunk, _mergesorted


# Value emitted in the key columns of a subtotal row to mark a dimension
# that is not part of the grouping set. Distinct from None, which is a
# genuine key value. grouping_id provides the SQL-standard, structured
# way to tell the two apart programmatically.
class GroupingNull(object):

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(GroupingNull, cls).__new__(cls)
        return cls._instance

    def __repr__(self):
        return 'GROUPING_NULL'

    def __str__(self):
        return 'GROUPING_NULL'


GROUPING_NULL = GroupingNull()


class _NamedTempFileDeleteOnGC(object):
    """Temporary pickle chunk file deleted when garbage collected."""

    def __init__(self, name):
        self.name = name

    def __del__(self):
        try:
            os.unlink(self.name)
        except OSError:
            pass


class Aggregate(object):
    """Base class for custom aggregations used with grouping_sets().

    A concrete aggregation must declare whether partial states can safely
    be merged by setting the boolean class attribute ``mergeable``.

    Set ``mergeable = True`` (or subclass :class:`MergeableAggregate`)
    and implement :meth:`update`, :meth:`merge` and :meth:`finalize`
    for a distributive aggregation such as a weighted average::

        >>> from petl.transform.grouping import MergeableAggregate
        >>> class WeightedMean(MergeableAggregate):
        ...     def initial(self):
        ...         return [0.0, 0]
        ...     def update(self, state, value):
        ...         x, w = value
        ...         if x is not None:
        ...             state[0] += x * w
        ...             state[1] += w
        ...     def merge(self, state, other):
        ...         state[0] += other[0]
        ...         state[1] += other[1]
        ...     def finalize(self, state):
        ...         return state[0] / state[1] if state[1] else None

    Set ``mergeable = False`` and implement :meth:`update` and
    :meth:`finalize` for an aggregation that must see all values of a
    group in one pass (e.g. :func:`list` or a median)::

        >>> class FirstValue(Aggregate):
        ...     mergeable = False
        ...     def initial(self):
        ...         return []
        ...     def update(self, state, value):
        ...         if not state:
        ...             state.append(value)
        ...     def finalize(self, state):
        ...         return state[0] if state else None

    An :class:`Aggregate` instance is itself callable, so custom
    aggregations may also be passed directly to :func:`petl.aggregate`.
    """

    #: Must be explicitly set to True or False by concrete subclasses.
    mergeable = None

    def initial(self):
        """Return a fresh aggregation state for an empty group."""
        raise NotImplementedError

    def update(self, state, value):
        """Fold a single row/value into state."""
        raise NotImplementedError

    def merge(self, state, other):
        """Merge the partial other state into state in place."""
        raise NotImplementedError

    def finalize(self, state):
        """Return the output value for state."""
        raise NotImplementedError

    def _check_declared(self):
        if not isinstance(self.mergeable, bool):
            raise ArgumentError(
                'custom aggregation %r must explicitly declare a boolean'
                ' "mergeable" attribute' % type(self).__name__)

    def __call__(self, iterable):
        self._check_declared()
        state = self.initial()
        for value in iterable:
            self.update(state, value)
        return self.finalize(state)


class MergeableAggregate(Aggregate):
    """Base class for custom aggregations that are distributive, i.e.
    groups may be accumulated independently into partial states and those
    states may then be combined via merge()."""

    mergeable = True


# ---------------------------------------------------------------------------
# built-in mergeable aggregation states: sum, count, min/max
# ---------------------------------------------------------------------------


_NO_VALUE = object()


class _CountState(object):

    __slots__ = ['n']

    def __init__(self, n=0):
        self.n = n


def _count_update(state, value):
    state.n += 1


def _count_merge(state, other):
    state.n += other.n


def _count_finalize(state):
    return state.n


class _SumState(object):

    __slots__ = ['total', 'seen']

    def __init__(self, total=0, seen=False):
        self.total = total
        self.seen = seen


def _sum_update(state, value):
    if value is not None:
        state.total = state.total + value
        state.seen = True


def _sum_merge(state, other):
    if other.seen:
        state.total = state.total + other.total
        state.seen = True


def _sum_finalize(state):
    return state.total if state.seen else None


class _MinMaxState(object):

    __slots__ = ['value']

    def __init__(self):
        self.value = _NO_VALUE


def _make_min_update(less):
    def _update(state, value):
        if value is not None and (state.value is _NO_VALUE
                                  or (Comparable(value) < Comparable(state.value))
                                  == less):
            state.value = value
    return _update


def _min_update(state, value):
    if value is None:
        return
    if state.value is _NO_VALUE or Comparable(value) < Comparable(state.value):
        state.value = value


def _max_update(state, value):
    if value is None:
        return
    if state.value is _NO_VALUE or Comparable(value) > Comparable(state.value):
        state.value = value


def _minmax_merge(pick):
    def _merge(state, other):
        if other.value is not _NO_VALUE:
            if state.value is _NO_VALUE or pick(
                    Comparable(other.value), Comparable(state.value)):
                state.value = other.value
    return _merge


_min_merge = _minmax_merge(operator.lt)
_max_merge = _minmax_merge(operator.gt)


def _minmax_finalize(state):
    return None if state.value is _NO_VALUE else state.value


# registry of built-in, distributive aggregations
_BUILTIN_MERGEABLE = {
    len: (_CountState, _count_update, _count_merge, _count_finalize),
    sum: (_SumState, _sum_update, _sum_merge, _sum_finalize),
    min: (_MinMaxState, _min_update, _min_merge, _minmax_finalize),
    max: (_MinMaxState, _max_update, _max_merge, _minmax_finalize),
}


def _make_spec(fun):
    """Return (mergeable, spec) where spec is a tuple of callables.

    For a mergeable aggregation: (initial, update, merge, finalize).
    For a plain callable: (None, fun, None, None).
    """
    if isinstance(fun, Aggregate):
        fun._check_declared()
        if fun.mergeable:
            return True, (fun.initial, fun.update, fun.merge, fun.finalize)
        return False, (fun.initial, fun.update, None, fun.finalize)
    builtin = _BUILTIN_MERGEABLE.get(fun)
    if builtin is not None:
        return True, builtin
    if callable(fun):
        return False, (None, fun, None, None)
    raise ArgumentError('aggregation must be callable, found %r' % (fun,))


def _normalise_aggregations(aggregation, value, field):
    """Return (OrderedDict outfld -> (srcfld, fun), simple)."""
    if callable(aggregation):
        return OrderedDict([(field, (value, aggregation))]), True
    if aggregation is None or isinstance(aggregation, (list, tuple, dict)):
        out = OrderedDict()
        if aggregation is None:
            pass
        elif isinstance(aggregation, (list, tuple)):
            for t in aggregation:
                out[t[0]] = t[1:]
        else:
            for k, v in aggregation.items():
                out[k] = v
        normalised = OrderedDict()
        for outfld, agg in out.items():
            if callable(agg):
                srcfld, fun = None, agg
            elif isinstance(agg, string_types):
                srcfld, fun = agg, list
            elif len(agg) == 1 and isinstance(agg[0], string_types):
                srcfld, fun = agg[0], list
            elif len(agg) == 1 and callable(agg[0]):
                srcfld, fun = None, agg[0]
            elif len(agg) == 2:
                srcfld, fun = agg
            else:
                raise ArgumentError('invalid aggregation: %r, %r'
                                    % (outfld, agg))
            normalised[outfld] = (srcfld, fun)
        return normalised, False
    raise ArgumentError('expected aggregation is callable, list, tuple, dict'
                        ' or None')


def _make_getter(hdr, srcfld):
    if srcfld is None:
        return lambda rec: rec
    indices = asindices(hdr, srcfld)
    if isinstance(srcfld, (list, tuple)):
        return rowgetter(*indices)
    idx = indices[0]
    return lambda rec: rec[idx] if idx < len(rec) else None


def _normalise_sets(sets, key_specs, hdr):
    """Normalise grouping sets to an ordered list of unique position
tuples (positions index the key dimensions, in key order)."""
    key_indices = asindices(hdr, key_specs)
    if len(set(key_indices)) != len(key_indices):
        raise ArgumentError('key fields must be unique, found %r'
                            % (key_specs,))
    seen = OrderedDict()
    if sets is None:
        raise ArgumentError('sets must be provided')
    for spec in sets:
        if spec is None:
            members = []
        elif isinstance(spec, (list, tuple)):
            members = spec
        else:
            members = (spec,)
        positions = []
        for member in members:
            if isinstance(member, string_types) and member in key_specs:
                pos = key_specs.index(member)
            else:
                try:
                    hidx = asindices(hdr, member)[0]
                except Exception:
                    raise ArgumentError(
                        'grouping set member %r is not one of the key fields'
                        % (member,))
                if hidx not in key_indices:
                    raise ArgumentError(
                        'grouping set member %r is not one of the key fields'
                        % (member,))
                pos = key_indices.index(hidx)
            if pos not in positions:
                positions.append(pos)
        positions.sort()
        canonical = tuple(positions)
        if canonical not in seen:
            seen[canonical] = True
    return list(seen.keys()), key_indices


def _grouping_id(positions, ndims):
    gid = 0
    for p in range(ndims):
        if p not in positions:
            gid |= 1 << (ndims - 1 - p)
    return gid


def grouping_sets(table, key, sets, aggregation=None, value=None,
                  field='value', buffersize=None, tempdir=None):
    """Aggregate rows over several GROUPING SETS in a single pass.

    Groups are computed for the region/product pair, each single
    dimension and the whole table simultaneously::

        >>> import petl as etl
        >>> from collections import OrderedDict
        >>> table1 = [['region', 'product', 'units'],
        ...           ['east', 'a', 1],
        ...           ['east', 'a', None],
        ...           ['west', None, 2],
        ...           ['west', 'b', 3]]
        >>> result = etl.grouping_sets(
        ...     table1, key=('region', 'product'),
        ...     sets=[('region', 'product'), ('region',), ('product',), ()],
        ...     aggregation=OrderedDict([
        ...         ('n', len),
        ...         ('total', ('units', sum)),
        ...         ('minu', ('units', min)),
        ...         ('maxu', ('units', max))]))
        >>> for row in etl.data(result):
        ...     print(row)
        ('east', 'a', 2, 1, 1, 1, 0)
        ('west', None, 1, 2, 2, 2, 0)
        ('west', 'b', 1, 3, 3, 3, 0)
        ('east', GROUPING_NULL, 2, 1, 1, 1, 1)
        ('west', GROUPING_NULL, 2, 5, 2, 3, 1)
        (GROUPING_NULL, None, 1, 2, 2, 2, 2)
        (GROUPING_NULL, 'a', 2, 1, 1, 1, 2)
        (GROUPING_NULL, 'b', 1, 3, 3, 3, 2)
        (GROUPING_NULL, GROUPING_NULL, 4, 6, 1, 3, 3)

    Dimensions absent from a grouping set are reported as
    :data:`GROUPING_NULL`; a genuine key value of ``None`` remains ``None``.
    The trailing ``grouping_id`` column follows the SQL standard: its bit
    for a dimension is 1 when that dimension was aggregated away (the most
    significant key column contributes the most significant bit).

    Duplicate grouping sets are only computed once. The grand total set
    (the empty set) always emits one row, even on empty input; empty-group
    values then follow each aggregation's own definition (e.g. count 0,
    min/max and sum over no non-null values are ``None``).

    ``sum``, ``len`` (count) and ``min``/``max`` keep mergeable partial
    states. A plain callable (e.g. ``list``) is treated as non-mergeable
    and rows are buffered; when the buffer exceeds ``buffersize`` rows,
    sorted chunks are spilled to ``tempdir`` and merge-grouped per set, so
    states belonging to different grouping sets are never combined. A
    :class:`MergeableAggregate` subclass explicitly opts into state
    merging; an :class:`Aggregate` subclass with ``mergeable = False``
    does not.

    The upstream table is read exactly once. The simple aggregation
    signature (``aggregation`` callable plus optional ``value`` field) and
    the multi-aggregation mapping are both supported, mirroring
    :func:`petl.transform.reductions.aggregate`.

    See also :func:`rollup` and :func:`cube`, which expand onto this same
    interface.

    """

    return GroupingSetsView(table, key=key, sets=sets,
                            aggregation=aggregation, value=value,
                            field=field, buffersize=buffersize,
                            tempdir=tempdir)


Table.grouping_sets = grouping_sets


def rollup(table, key, aggregation=None, value=None, field='value',
           buffersize=None, tempdir=None):
    """Equivalent to :func:`grouping_sets` with the ROLLUP hierarchy of
sets: for key columns ``(a, b)`` the sets are ``(a, b)``, ``(a,)`` and
``()`` (grand total)."""
    key_specs = _key_as_tuple(key)
    sets = [tuple(key_specs[:i]) for i in range(len(key_specs), 0, -1)]
    sets.append(())
    return grouping_sets(table, key, sets, aggregation=aggregation,
                         value=value, field=field, buffersize=buffersize,
                         tempdir=tempdir)


Table.rollup = rollup


def cube(table, key, aggregation=None, value=None, field='value',
         buffersize=None, tempdir=None):
    """Equivalent to :func:`grouping_sets` with every subset of the key
columns as a grouping set (CUBE). For key columns ``(a, b)`` the sets are
``(a, b)``, ``(a,)``, ``(b,)`` and ``()`` (grand total)."""
    key_specs = _key_as_tuple(key)
    n = len(key_specs)
    sets = []
    for mask in range(2 ** n):
        sets.append(tuple(p for p in range(n)
                          if not (mask >> (n - 1 - p)) & 1))
    return grouping_sets(table, key, sets, aggregation=aggregation,
                         value=value, field=field, buffersize=buffersize,
                         tempdir=tempdir)


Table.cube = cube


def _key_as_tuple(key):
    if key is None or callable(key):
        raise ArgumentError('grouping sets require key field name(s), got %r'
                            % (key,))
    if isinstance(key, (list, tuple)):
        return tuple(key)
    return key,


class GroupingSetsView(Table):

    def __init__(self, table, key, sets, aggregation=None, value=None,
                 field='value', buffersize=None, tempdir=None):
        self.table = table
        self.key = _key_as_tuple(key)
        self.sets_arg = sets
        self.aggregation = aggregation
        self.value = value
        self.field = field
        if buffersize is None:
            self.buffersize = config.sort_buffersize
        else:
            self.buffersize = buffersize
        self.tempdir = tempdir

    def __iter__(self):
        return itergroupingsets(self.table, self.key, self.sets_arg,
                                self.aggregation, self.value, self.field,
                                self.buffersize, self.tempdir)


def itergroupingsets(table, key_specs, sets_arg, aggregation, value, field,
                     buffersize, tempdir):
    it = iter(table)
    try:
        hdr = next(it)
    except StopIteration:
        hdr = ()
    flds = list(map(text_type, hdr))

    set_positions, key_indices = _normalise_sets(sets_arg, key_specs, hdr)
    ndims = len(key_specs)
    n_sets = len(set_positions)

    aggs, _ = _normalise_aggregations(aggregation, value, field)
    outflds = list(aggs.keys())
    if 'grouping_id' in outflds:
        raise ArgumentError("'grouping_id' is a reserved output field name")
    yield tuple(list(key_specs) + list(outflds) + ['grouping_id'])

    # one descriptor per output aggregation:
    # (srcfld, mergeable, (initial, update, merge, finalize), getter)
    descriptors = []
    any_nonmergeable = False
    for outfld in outflds:
        srcfld, fun = aggs[outfld]
        mergeable, funcs = _make_spec(fun)
        getter = _make_getter(hdr, srcfld)
        descriptors.append((mergeable, funcs, getter))
        if not mergeable:
            any_nonmergeable = True

    # per-set key accessors (raw, order-preserving tuples)
    set_getters = [rowgetter(*[key_indices[p] for p in positions])
                   for positions in set_positions]

    # states[i][j] = {rawkey: state} for mergeable agg j in set i
    states = [[dict() if descriptors[j][0] else None
               for j in range(len(descriptors))]
              for _ in range(n_sets)]
    # which sets need row buffering for non-mergeable aggregations
    buffered_sets = [any(not descriptors[j][0] for j in range(len(descriptors)))
                     for _ in range(n_sets)]

    row_buffer = [] if any_nonmergeable else None
    chunk_files = [[] for _ in range(n_sets)]
    spill_flag = [False]
    if buffersize is not None and buffersize <= 0:
        raise ArgumentError('buffersize must be a positive int or None')

    def flush_buffer():
        for i in range(n_sets):
            if not buffered_sets[i] or not row_buffer:
                continue
            items = [(set_getters[i](rec), rec) for rec in row_buffer]
            items.sort(key=lambda item: Comparable(item[0]))
            with NamedTemporaryFile(dir=tempdir, delete=False,
                                    mode='wb') as f:
                wrapper = _NamedTempFileDeleteOnGC(f.name)
                for item in items:
                    pickle.dump(item, f, protocol=-1)
                f.flush()
                chunk_files[i].append(wrapper)
        spill_flag[0] = True
        del row_buffer[:]

    nrows_seen = 0
    for rec in (Record(row, flds) for row in it):
        vals = None
        if any_nonmergeable:
            vals = [getter(rec) for _, _, getter in descriptors]
        for i in range(n_sets):
            rawkey = set_getters[i](rec)
            for j, (mergeable, funcs, getter) in enumerate(descriptors):
                if mergeable:
                    # mergeable states are updated independently per set;
                    # they are never combined across sets
                    state_map = states[i][j]
                    state = state_map.get(rawkey)
                    if state is None:
                        state = funcs[0]()
                        state_map[rawkey] = state
                    funcs[1](state, vals[j] if vals is not None
                             else getter(rec))
        if any_nonmergeable:
            row_buffer.append(rec)
            if buffersize is not None and len(row_buffer) >= buffersize:
                flush_buffer()
        nrows_seen += 1

    def value_for(set_idx, j, rawkey, rows):
        mergeable, funcs, getter = descriptors[j]
        if mergeable:
            state = states[set_idx][j].get(rawkey)
            if state is None:
                state = funcs[0]()
            return funcs[3](state)
        initial, update, _, finalize = funcs
        if initial is None:
            # plain callable: one shot over the whole group's values
            return update(getter(row) for row in rows)
        state = initial()
        for row in rows:
            update(state, getter(row))
        return finalize(state)

    def emit_row(set_idx, rawkey, positions, rows):
        outkey = []
        key_by_pos = {p: rawkey[k]
                      for k, p in enumerate(positions)}
        for p in range(ndims):
            outkey.append(key_by_pos[p] if p in key_by_pos
                          else GROUPING_NULL)
        aggvals = [value_for(set_idx, j, rawkey, rows)
                   for j in range(len(descriptors))]
        gid = _grouping_id(positions, ndims)
        return tuple(outkey + aggvals + [gid])

    # materialise any in-memory groups for buffered sets
    mem_groups = None
    if any_nonmergeable and not spill_flag[0]:
        mem_groups = [dict() for _ in range(n_sets)]
        for rec in row_buffer:
            for i in range(n_sets):
                if buffered_sets[i]:
                    rawkey = set_getters[i](rec)
                    group = mem_groups[i].get(rawkey)
                    if group is None:
                        group = []
                        mem_groups[i][rawkey] = group
                    group.append(rec)

    for set_idx in range(n_sets):
        positions = set_positions[set_idx]
        if nrows_seen == 0:
            if len(positions) == 0:
                yield emit_row(set_idx, (), positions, [])
            continue
        if buffered_sets[set_idx]:
            if spill_flag[0]:
                chunk_iters = [_iterchunk(w.name)
                               for w in chunk_files[set_idx]]
                merged = _mergesorted(
                    lambda item: Comparable(item[0]), False,
                    *chunk_iters)
                for rawkey, group_items in itertools.groupby(
                        merged, key=lambda item: item[0]):
                    rows = [item[1] for item in group_items]
                    yield emit_row(set_idx, rawkey, positions, rows)
            else:
                for rawkey in sorted(mem_groups[set_idx].keys(),
                                     key=Comparable):
                    rows = mem_groups[set_idx][rawkey]
                    yield emit_row(set_idx, rawkey, positions, rows)
        else:
            all_keys = set()
            for j in range(len(descriptors)):
                all_keys.update(states[set_idx][j].keys())
            for rawkey in sorted(all_keys, key=Comparable):
                yield emit_row(set_idx, rawkey, positions, [])
