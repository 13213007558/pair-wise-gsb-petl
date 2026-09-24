from __future__ import absolute_import, print_function, division

import operator
from collections import OrderedDict

from petl.errors import ArgumentError, LateEventError
from petl.util.base import Table, asindices, Record


def sessionize(table, key, time, gap, watermark=None,
               max_out_of_orderness=None, aggregation=None,
               on_late='error'):
    """
    Group a stream of events into sessions, one output row per session.

    Events are grouped by `key` (e.g., a user id). Within a key, two
    adjacent events belong to different sessions if their event times
    (taken from the `time` field) are more than `gap` apart. The input
    does not need to be sorted; events may arrive slightly out of
    order.

    A session is only emitted once a watermark confirms that no more
    events can belong to it, i.e., once the watermark reaches
    ``session_end + gap``. Watermarks can be supplied in two ways,
    which may be combined:

    - Explicit watermark records in the input: if `watermark` names a
      field, any row where that field is not `None` is treated as a
      watermark record carrying a watermark value instead of an event.
    - A maximum out-of-orderness: if `max_out_of_orderness` is given,
      the watermark is implicitly advanced to ``max(event time seen
      so far) - max_out_of_orderness`` after every event.

    A watermark value ``W`` is a promise that no more events with
    event time less than or equal to ``W`` will arrive. Events
    breaking that promise are *late*:

    - A late event that still falls within the gap of a session that
      has not been emitted yet is merged into that session. Such an
      event may even bridge two open sessions, in which case they are
      merged into one.
    - A late event that falls in a range that has already been
      emitted cannot be accommodated without silently changing
      results that have already been produced. By default a
      :class:`petl.errors.LateEventError` is raised. Pass a mutable
      sequence (e.g., a list) as `on_late` to divert such events to
      a separate problem stream instead; the offending row is
      appended to the sequence and processing continues.

    The end of the input is treated as a final watermark at
    infinity: any sessions still open are emitted when the input is
    exhausted. Only sessions that cannot be emitted yet are held in
    memory.

    The output has the key fields followed by ``session_start``,
    ``session_end`` and ``event_count``. Additional aggregated state
    can be computed with the `aggregation` argument, a mapping (or
    sequence of pairs) of output field name to a ``(zero, add,
    merge)`` triple, where ``zero`` is a callable returning a fresh
    state (or an immutable initial value), ``add(state, row)`` folds
    an event row into the state (the row is a record supporting
    access by field name; the return value is used as the new state,
    or the state is assumed to have been mutated in place if ``None``
    is returned), and ``merge(state1, state2)`` combines the states
    of two sessions when they are merged.

    E.g.::

        >>> import petl as etl
        >>> table = [['user', 'time', 'mark', 'action'],
        ...          ['alice', 1, None, 'login'],
        ...          ['bob', 2, None, 'click'],
        ...          ['alice', 4, None, 'click'],
        ...          [None, None, 5, None],
        ...          ['alice', 12, None, 'logout'],
        ...          ['bob', 8, None, 'click'],
        ...          [None, None, 20, None]]
        >>> result = etl.sessionize(table, key='user', time='time',
        ...                         gap=5, watermark='mark')
        >>> for row in result:
        ...     print(row)
        ('user', 'session_start', 'session_end', 'event_count')
        ('alice', 1, 4, 2)
        ('bob', 2, 2, 1)
        ('bob', 8, 8, 1)
        ('alice', 12, 12, 1)

    With an aggregation::

        >>> table2 = [['user', 'time', 'amount'],
        ...           ['alice', 1, 10],
        ...           ['alice', 3, 5],
        ...           ['alice', 20, 7]]
        >>> agg = {'total': (0, lambda state, row: state + row['amount'],
        ...                  lambda a, b: a + b)}
        >>> result = etl.sessionize(table2, key='user', time='time',
        ...                         gap=5, aggregation=agg)
        >>> for row in result:
        ...     print(row)
        ('user', 'session_start', 'session_end', 'event_count', 'total')
        ('alice', 1, 3, 2, 15)
        ('alice', 20, 20, 1, 7)

    """

    return SessionizeView(table, key=key, time=time, gap=gap,
                          watermark=watermark,
                          max_out_of_orderness=max_out_of_orderness,
                          aggregation=aggregation, on_late=on_late)


Table.sessionize = sessionize


class SessionizeView(Table):

    def __init__(self, source, key=None, time=None, gap=None,
                 watermark=None, max_out_of_orderness=None,
                 aggregation=None, on_late='error'):
        self.source = source
        self.key = key
        self.time = time
        self.gap = gap
        self.watermark = watermark
        self.max_out_of_orderness = max_out_of_orderness
        self.aggregation = aggregation
        self.on_late = on_late

    def __iter__(self):
        return itersessionize(self.source, self.key, self.time, self.gap,
                              self.watermark, self.max_out_of_orderness,
                              self.aggregation, self.on_late)


class _Session(object):

    __slots__ = ('start', 'end', 'count', 'states')

    def __init__(self, start, end, count, states):
        self.start = start
        self.end = end
        self.count = count
        self.states = states


def _normalise_aggregation(aggregation):
    if aggregation is None:
        return []
    if hasattr(aggregation, 'items'):
        items = list(aggregation.items())
    else:
        items = list(aggregation)
    spec = []
    for name, s in items:
        zero, add, merge = s
        spec.append((name, zero, add, merge))
    return spec


def _fresh_states(spec):
    return [zero() if callable(zero) else zero
            for _, zero, _, _ in spec]


def _add_event(states, spec, rec):
    out = []
    for state, (_, _, add, _) in zip(states, spec):
        new = add(state, rec)
        out.append(state if new is None else new)
    return out


def _merge_states(states1, states2, spec):
    return [merge(s1, s2)
            for s1, s2, (_, _, _, merge) in zip(states1, states2, spec)]


def itersessionize(source, key, time, gap, watermark_field,
                   max_out_of_orderness, aggregation, on_late):
    if on_late != 'error' and not hasattr(on_late, 'append'):
        raise ArgumentError(
            "on_late must be 'error' or a mutable sequence")
    spec = _normalise_aggregation(aggregation)

    it = iter(source)
    try:
        hdr = next(it)
    except StopIteration:
        return
    hdr = list(hdr)

    key_indices = asindices(hdr, key)
    time_index = asindices(hdr, time)[0]
    if watermark_field is not None:
        watermark_index = asindices(hdr, watermark_field)[0]
    else:
        watermark_index = None

    getkey = operator.itemgetter(*key_indices)
    key_fields = tuple(hdr[i] for i in key_indices)
    agg_names = tuple(name for name, _, _, _ in spec)
    outhdr = key_fields + ('session_start', 'session_end',
                           'event_count') + agg_names
    yield outhdr

    # sessions that cannot be emitted yet, per key, sorted by start
    open_sessions = OrderedDict()
    explicit_watermark = None
    max_event_time = None
    # single-item list, so the advance() closure can update it
    flushed_watermark = [None]

    def current_watermark():
        candidates = []
        if explicit_watermark is not None:
            candidates.append(explicit_watermark)
        if max_out_of_orderness is not None and max_event_time is not None:
            candidates.append(max_event_time - max_out_of_orderness)
        if candidates:
            return max(candidates)
        return None

    def session_row(k, s):
        key_values = k if isinstance(k, tuple) else (k,)
        return key_values + (s.start, s.end, s.count) + tuple(s.states)

    def advance():
        # emit sessions the watermark confirms as complete
        w = current_watermark()
        if w is None:
            return []
        if flushed_watermark[0] is not None and w <= flushed_watermark[0]:
            return []
        flushed_watermark[0] = w
        rows = []
        for k in list(open_sessions.keys()):
            sessions = open_sessions[k]
            while sessions and sessions[0].end + gap <= w:
                rows.append(session_row(k, sessions.pop(0)))
            if not sessions:
                del open_sessions[k]
        # emit each batch in chronological order of session start
        rows.sort(key=lambda r: r[len(key_fields)])
        return rows

    for row in it:
        if watermark_index is not None and row[watermark_index] is not None:
            w = row[watermark_index]
            if explicit_watermark is None or w > explicit_watermark:
                explicit_watermark = w
        else:
            t = row[time_index]
            k = getkey(row)
            w = current_watermark()
            sessions = open_sessions.get(k)
            if sessions is None:
                sessions = []
                open_sessions[k] = sessions

            # find open sessions within the gap of this event
            matches = []
            for i, s in enumerate(sessions):
                if s.start - gap > t:
                    break
                if s.end + gap >= t:
                    matches.append(i)

            if w is not None and t <= w and not matches:
                # late event in an already emitted range
                if on_late == 'error':
                    raise LateEventError(tuple(row), w)
                on_late.append(tuple(row))
                continue

            rec = Record(row, hdr)
            if matches:
                group = sessions[matches[0]:matches[-1] + 1]
                start = min([t] + [s.start for s in group])
                end = max([t] + [s.end for s in group])
                count = 1 + sum(s.count for s in group)
                states = list(group[0].states)
                for s in group[1:]:
                    states = _merge_states(states, s.states, spec)
                states = _add_event(states, spec, rec)
                merged = _Session(start, end, count, states)
                sessions[matches[0]:matches[-1] + 1] = [merged]
            else:
                states = _add_event(_fresh_states(spec), spec, rec)
                session = _Session(t, t, 1, states)
                idx = 0
                while idx < len(sessions) and sessions[idx].end + gap < t:
                    idx += 1
                sessions.insert(idx, session)

            if max_event_time is None or t > max_event_time:
                max_event_time = t

        for out in advance():
            yield out

    # end of input acts as a final watermark
    rows = []
    for k in list(open_sessions.keys()):
        for s in open_sessions[k]:
            rows.append(session_row(k, s))
    open_sessions.clear()
    rows.sort(key=lambda r: r[len(key_fields)])
    for row in rows:
        yield row
