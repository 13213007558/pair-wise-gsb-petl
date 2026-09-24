from __future__ import absolute_import, print_function, division

from datetime import datetime, timedelta

import pytest

from petl.errors import ArgumentError, LateEventError
from petl.test.helpers import ieq
from petl.transform.sessions import sessionize


def test_basic_sessions_released_at_end_of_input():
    # no watermark configured, end of input acts as final watermark
    table = (('user', 'time'),
             ('alice', 1),
             ('alice', 3),
             ('alice', 10),
             ('bob', 2))
    result = sessionize(table, key='user', time='time', gap=5)
    expect = (('user', 'session_start', 'session_end', 'event_count'),
              ('alice', 1, 3, 2),
              ('bob', 2, 2, 1),
              ('alice', 10, 10, 1))
    ieq(expect, result)


def test_session_released_only_after_watermark():
    def source():
        yield ('user', 'time', 'mark')
        yield ('u1', 1, None)
        yield ('u1', 3, None)
        yield (None, None, 9)  # watermark 9 closes [1, 3] with gap 5
        raise AssertionError('input consumed past the watermark')

    result = sessionize(source(), key='user', time='time', gap=5,
                        watermark='mark')
    it = iter(result)
    assert next(it) == ('user', 'session_start', 'session_end',
                        'event_count')
    # the session must be emitted without consuming any more input
    assert next(it) == ('u1', 1, 3, 2)


def test_stepwise_watermarks_interleaved_users():
    table = (('user', 'time', 'mark'),
             ('alice', 1, None),
             ('bob', 2, None),
             ('alice', 4, None),
             (None, None, 6),    # closes nothing yet
             ('bob', 8, None),   # new session for bob
             (None, None, 9),    # closes alice [1, 4] and bob [2, 2]
             ('alice', 20, None),
             (None, None, 30))
    result = sessionize(table, key='user', time='time', gap=5,
                        watermark='mark')
    expect = (('user', 'session_start', 'session_end', 'event_count'),
              ('alice', 1, 4, 2),
              ('bob', 2, 2, 1),
              ('bob', 8, 8, 1),
              ('alice', 20, 20, 1))
    ieq(expect, result)


def test_max_out_of_orderness():
    table = (('user', 'time'),
             ('u1', 5),
             ('u1', 7),
             ('u1', 20))
    result = sessionize(table, key='user', time='time', gap=3,
                        max_out_of_orderness=2)
    # after u1@20 the implicit watermark is 18, closing [5, 7]
    expect = (('user', 'session_start', 'session_end', 'event_count'),
              ('u1', 5, 7, 2),
              ('u1', 20, 20, 1))
    ieq(expect, result)


def test_max_out_of_orderness_late_event_raises():
    table = (('user', 'time'),
             ('u1', 20),
             ('u1', 4))  # implicit watermark is 18, 4 is way too late
    result = sessionize(table, key='user', time='time', gap=3,
                        max_out_of_orderness=2)
    with pytest.raises(LateEventError):
        list(result)


def test_late_event_bridging_sessions():
    table = (('user', 'time', 'mark', 'amount'),
             ('u1', 10, None, 1),
             ('u1', 11, None, 2),
             ('u1', 15, None, 4),
             ('u1', 16, None, 8),
             (None, None, 13, None),
             ('u1', 13, None, 16),  # late, bridges [10, 11] and [15, 16]
             (None, None, 30, None))
    aggregation = {'total': (0, lambda state, row: state + row['amount'],
                             lambda a, b: a + b)}
    result = sessionize(table, key='user', time='time', gap=3,
                        watermark='mark', aggregation=aggregation)
    expect = (('user', 'session_start', 'session_end', 'event_count',
               'total'),
              ('u1', 10, 16, 5, 31))
    ieq(expect, result)


def test_late_event_extends_open_session():
    table = (('user', 'time', 'mark'),
             ('u1', 10, None),
             ('u1', 20, None),
             (None, None, 12),
             ('u1', 12, None),  # late, but [10, 10] is still open
             (None, None, 40))
    result = sessionize(table, key='user', time='time', gap=5,
                        watermark='mark')
    expect = (('user', 'session_start', 'session_end', 'event_count'),
              ('u1', 10, 12, 2),
              ('u1', 20, 20, 1))
    ieq(expect, result)


def test_late_event_in_closed_range_raises():
    table = (('user', 'time', 'mark'),
             ('u1', 1, None),
             ('u1', 2, None),
             (None, None, 10),  # emits [1, 2]
             ('u1', 3, None))   # too late, would have extended [1, 2]
    result = sessionize(table, key='user', time='time', gap=3,
                        watermark='mark')
    with pytest.raises(LateEventError):
        list(result)


def test_late_event_diverted_to_problem_stream():
    table = (('user', 'time', 'mark'),
             ('u1', 1, None),
             ('u1', 2, None),
             (None, None, 10),  # emits [1, 2]
             ('u1', 3, None),   # diverted, emitted results unchanged
             ('u1', 20, None))
    late = []
    result = sessionize(table, key='user', time='time', gap=3,
                        watermark='mark', on_late=late)
    expect = (('user', 'session_start', 'session_end', 'event_count'),
              ('u1', 1, 2, 2),
              ('u1', 20, 20, 1))
    ieq(expect, result)
    assert late == [('u1', 3, None)]


def test_invalid_on_late():
    table = (('user', 'time'), ('u1', 1))
    result = sessionize(table, key='user', time='time', gap=3,
                        on_late='bogus')
    with pytest.raises(ArgumentError):
        list(result)


def test_aggregation_with_mutable_state():
    table = (('user', 'time', 'mark', 'action'),
             ('u1', 10, None, 'a'),
             ('u1', 15, None, 'b'),
             (None, None, 12, None),
             ('u1', 12, None, 'c'),  # late, bridges the two sessions
             (None, None, 30, None))
    aggregation = [('actions', (set,
                                lambda state, row: state.add(row['action']),
                                lambda a, b: a | b))]
    result = sessionize(table, key='user', time='time', gap=3,
                        watermark='mark', aggregation=aggregation)
    expect = (('user', 'session_start', 'session_end', 'event_count',
               'actions'),
              ('u1', 10, 15, 3, {'a', 'b', 'c'}))
    ieq(expect, result)


def test_datetime_gap():
    t0 = datetime(2024, 1, 1, 12, 0, 0)
    table = (('user', 'time'),
             ('u1', t0),
             ('u1', t0 + timedelta(seconds=10)),
             ('u1', t0 + timedelta(seconds=41)))
    result = sessionize(table, key='user', time='time',
                        gap=timedelta(seconds=30))
    expect = (('user', 'session_start', 'session_end', 'event_count'),
              ('u1', t0, t0 + timedelta(seconds=10), 2),
              ('u1', t0 + timedelta(seconds=41),
               t0 + timedelta(seconds=41), 1))
    ieq(expect, result)


def test_compound_key():
    table = (('user', 'device', 'time'),
             ('u1', 'phone', 1),
             ('u1', 'phone', 2),
             ('u1', 'laptop', 1))
    result = sessionize(table, key=('user', 'device'), time='time', gap=3)
    expect = (('user', 'device', 'session_start', 'session_end',
               'event_count'),
              ('u1', 'phone', 1, 2, 2),
              ('u1', 'laptop', 1, 1, 1))
    ieq(expect, result)


def test_empty_table():
    table = (('user', 'time'),)
    result = sessionize(table, key='user', time='time', gap=5)
    expect = (('user', 'session_start', 'session_end', 'event_count'),)
    ieq(expect, result)


def test_non_monotonic_watermark_ignored():
    table = (('user', 'time', 'mark'),
             ('u1', 1, None),
             (None, None, 10),
             (None, None, 5),   # stale watermark, must be ignored
             ('u1', 3, None))   # still late relative to watermark 10
    result = sessionize(table, key='user', time='time', gap=3,
                        watermark='mark')
    with pytest.raises(LateEventError):
        list(result)
