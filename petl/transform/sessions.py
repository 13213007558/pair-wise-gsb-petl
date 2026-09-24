from __future__ import absolute_import, print_function, division


import copy

from petl.errors import ArgumentError, LateEventError
from petl.util.base import Table, asindices


def sessionize(table, key, time, gap, aggregate=None, watermark=None,
               max_out_of_order=None, on_late='error'):
    """
    Group events into sessions per key, where two consecutive events
    belong to the same session if their timestamps are no more than
    `gap` apart. E.g.::

        >>> import petl as etl
        >>> table1 = [['user', 'time', 'action'],
        ...           ['alice', 1, 'login'],
        ...           ['alice', 3, 'click'],
        ...           ['alice', 10, 'logout'],
        ...           ['bob', 2, 'login'],
        ...           ['bob', 4, 'click']]
        >>> table2 = etl.sessionize(table1, key='user', time='time', gap=5)
        >>> table2
        +---------+-------+-----+-------+
        | user    | start | end | count |
        +=========+=======+=====+=======+
        | 'alice' |     1 |   3 |     2 |
        +---------+-------+-----+-------+
        | 'alice' |    10 |  10 |     1 |
        +---------+-------+-----+-------+
        | 'bob'   |     2 |   4 |     2 |
        +---------+-------+-----+-------+

    Events may arrive out of order. A session is only emitted once the
    watermark guarantees that no further events can belong to it, i.e.,
    when ``session end + gap <= watermark``. The watermark advances in
    two ways, which may be combined:

    * Explicit watermark records in the input: if the `watermark`
      argument names a field, any row with a non-``None`` value in that
      field is treated as a watermark record carrying that value, not
      as an event.
    * If `max_out_of_order` is given, a watermark of
      ``max timestamp seen so far - max_out_of_order`` is derived from
      the events themselves.

    The end of the input acts as a final watermark, flushing all
    remaining sessions. Only sessions that are still open (i.e., could
    still be extended or merged) are kept in memory.

    An event arriving with a timestamp at or before the current
    watermark is late. A late event that still falls within `gap` of an
    open session legally extends it; a late event that would have
    belonged to an already emitted session cannot be incorporated
    without changing results that were already output. Such events are
    handled according to `on_late`: ``'error'`` (the default) raises
    :class:`petl.errors.LateEventError`, ``'problems'`` diverts them to
    a separate problem stream available via the ``problems`` attribute
    of the returned table, and ``'ignore'`` silently drops them.

    A (late or on-time) event may also fall within `gap` of two
    separate open sessions, bridging them; in that case the sessions
    are merged into one.

    The `aggregate` argument optionally maps output field names to
    ``(zero, update, merge)`` tuples describing a mergeable aggregate
    state. ``zero`` is a callable returning the initial state (or an
    immutable initial value), ``update(state, row)`` folds one event
    row into the state, and ``merge(state_a, state_b)`` combines the
    states of two sessions being merged. An optional fourth element
    ``finalize(state)`` transforms the state before output. E.g.::

        >>> table3 = etl.sessionize(
        ...     table1, key='user', time='time', gap=5,
        ...     aggregate={'actions': (list,
        ...                            lambda st, row: st + [row[2]],
        ...                            lambda a, b: a + b)})
        >>> table3
        +---------+-------+-----+-------+--------------------+
        | user    | start | end | count | actions            |
        +=========+=======+=====+=======+====================+
        | 'alice' |     1 |   3 |     2 | ['login', 'click'] |
        +---------+-------+-----+-------+--------------------+
        | 'alice' |    10 |  10 |     1 | ['logout']         |
        +---------+-------+-----+-------+--------------------+
        | 'bob'   |     2 |   4 |     2 | ['login', 'click'] |
        +---------+-------+-----+-------+--------------------+

    Timestamps may be numbers or :class:`datetime.datetime` values (use
    a :class:`datetime.timedelta` for `gap` and `max_out_of_order` in
    the latter case).

    .. versionadded:: 1.7.27

    """

    return SessionizeView(table, key, time, gap, aggregate=aggregate,
                          watermark=watermark,
                          max_out_of_order=max_out_of_order,
                          on_late=on_late)


Table.sessionize = sessionize


class SessionizeView(Table):

    def __init__(self, table, key, time, gap, aggregate=None,
                 watermark=None, max_out_of_order=None, on_late='error'):
        self.table = table
        self.key = key
        self.time = time
        self.gap = gap
        self.agg = aggregate
        self.watermark = watermark
        self.max_out_of_order = max_out_of_order
        if on_late not in ('error', 'problems', 'ignore'):
            raise ArgumentError("on_late must be one of 'error', "
                                "'problems' or 'ignore': %r" % (on_late,))
        self.on_late = on_late
        self._problems = None
        self._complete = False

    @property
    def problems(self):
        """A table of events that arrived too late to be incorporated,
        with an additional ``reason`` field. Only meaningful when
        ``on_late='problems'``. Iterating it forces the underlying
        stream to be consumed to completion if it has not been yet.
        """
        return ProblemsView(self)

    def __iter__(self):
        return itersessions(self)


class ProblemsView(Table):

    def __init__(self, view):
        self.view = view

    def __iter__(self):
        view = self.view
        if not view._complete:
            # drive a full pass so the problem stream is populated
            for _ in itersessions(view):
                pass
        try:
            hdr = tuple(next(iter(view.table)))
        except StopIteration:
            return
        yield hdr + ('reason',)
        for row in view._problems:
            yield row


class _Session(object):

    __slots__ = ('start', 'end', 'count', 'states')

    def __init__(self, start, end, count, states):
        self.start = start
        self.end = end
        self.count = count
        self.states = states


def _initial_states(agg_specs):
    states = {}
    for field, spec in agg_specs.items():
        zero = spec[0]
        states[field] = zero() if callable(zero) else copy.deepcopy(zero)
    return states


def itersessions(view):
    it = iter(view.table)
    try:
        hdr = tuple(next(it))
    except StopIteration:
        return

    gap = view.gap
    key_indices = asindices(hdr, view.key)
    time_index = asindices(hdr, view.time)[0]
    wm_index = asindices(hdr, view.watermark)[0] \
        if view.watermark is not None else None

    aggregate = view.agg or {}
    agg_fields = tuple(aggregate.keys())
    agg_update = {f: spec[1] for f, spec in aggregate.items()}
    agg_merge = {f: spec[2] for f, spec in aggregate.items()}
    agg_finalize = {f: spec[3] for f, spec in aggregate.items()
                    if len(spec) > 3}

    out_hdr = tuple(hdr[i] for i in key_indices) \
        + ('start', 'end', 'count') + agg_fields
    yield out_hdr

    problems = []
    view._problems = problems
    view._complete = False

    # open (not yet certainly closed) sessions per key, each kept as a
    # list of _Session sorted by start time
    open_sessions = {}
    explicit_wm = None
    derived_wm = None
    watermark = None
    max_time = None

    def make_row(key_values, session):
        states = session.states
        values = tuple(
            agg_finalize[f](states[f]) if f in agg_finalize else states[f]
            for f in agg_fields
        )
        return key_values + (session.start, session.end,
                             session.count) + values

    def close_sessions():
        # emit sessions the watermark proves complete
        for k in list(open_sessions.keys()):
            remaining = []
            for session in open_sessions[k]:
                if session.end + gap <= watermark:
                    yield make_row(k, session)
                else:
                    remaining.append(session)
            if remaining:
                open_sessions[k] = remaining
            else:
                del open_sessions[k]

    def new_session(row, t):
        states = _initial_states(aggregate)
        for f in agg_fields:
            states[f] = agg_update[f](states[f], row)
        return _Session(t, t, 1, states)

    def merge_sessions(touched, row, t):
        # fold the touched sessions and the new event into one session,
        # in timestamp order
        states = _initial_states(aggregate)
        count = 0
        applied = False
        for session in touched:
            if not applied and t <= session.end:
                for f in agg_fields:
                    states[f] = agg_update[f](states[f], row)
                applied = True
            for f in agg_fields:
                states[f] = agg_merge[f](states[f], session.states[f])
            count += session.count
        if not applied:
            for f in agg_fields:
                states[f] = agg_update[f](states[f], row)
        count += 1
        start = min([s.start for s in touched] + [t])
        end = max([s.end for s in touched] + [t])
        return _Session(start, end, count, states)

    for row in it:
        row = tuple(row)
        if wm_index is not None and row[wm_index] is not None:
            # explicit watermark record
            w = row[wm_index]
            if explicit_wm is None or w > explicit_wm:
                explicit_wm = w
            if watermark is None or explicit_wm > watermark:
                watermark = explicit_wm
            for out in close_sessions():
                yield out
            continue

        k = tuple(row[i] for i in key_indices)
        t = row[time_index]

        if view.max_out_of_order is not None:
            if max_time is None or t > max_time:
                max_time = t
            d = max_time - view.max_out_of_order
            if derived_wm is None or d > derived_wm:
                derived_wm = d
            if watermark is None or derived_wm > watermark:
                watermark = derived_wm
            for out in close_sessions():
                yield out

        sessions = open_sessions.setdefault(k, [])
        touched = [s for s in sessions
                   if s.start - gap <= t <= s.end + gap]
        if not touched:
            if watermark is not None and t <= watermark:
                # too late: its session was already emitted, and the
                # emitted results must not be changed retroactively
                if view.on_late == 'error':
                    raise LateEventError(row, watermark)
                elif view.on_late == 'problems':
                    problems.append(
                        row + ('event arrived after the watermark closed '
                               'its session',))
                # 'ignore' drops the event
                continue
            session = new_session(row, t)
            sessions.append(session)
            sessions.sort(key=lambda s: s.start)
        else:
            merged = merge_sessions(touched, row, t)
            remaining = [s for s in sessions if s not in touched]
            remaining.append(merged)
            remaining.sort(key=lambda s: s.start)
            open_sessions[k] = remaining

    # end of input acts as a final watermark: flush everything left
    for k in open_sessions:
        for session in open_sessions[k]:
            yield make_row(k, session)
    open_sessions.clear()
    view._complete = True
