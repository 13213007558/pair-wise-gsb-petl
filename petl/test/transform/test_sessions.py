from __future__ import absolute_import, print_function, division

from datetime import datetime, timedelta

import pytest

import petl as etl
from petl.errors import LateEventError
from petl.test.helpers import ieq
from petl.transform.sessions import sessionize


def test_sessionize_basic():
    table = (('user', 'time'),
             ('alice', 1),
             ('alice', 3),
             ('alice', 10),
             ('alice', 12),
             ('alice', 30))
    result = sessionize(table, key='user', time='time', gap=5)
    expect = (('user', 'start', 'end', 'count'),
              ('alice', 1, 3, 2),
              ('alice', 10, 12, 2),
              ('alice', 30, 30, 1))
    ieq(expect, result)
    ieq(expect, result)  # repeat, to check repeatable


def test_sessionize_interleaved_users():
    # events for different users arrive interleaved and slightly
    # out of order
    table = (('user', 'time'),
             ('alice', 1),
             ('bob', 2),
             ('alice', 3),
             ('bob', 5),
             ('alice', 20),
             ('bob', 30),
             ('alice', 19),
             ('alice', 4),
             ('bob', 32))
    result = sessionize(table, key='user', time='time', gap=5)
    expect = (('user', 'start', 'end', 'count'),
              ('alice', 1, 4, 3),
              ('alice', 19, 20, 2),
              ('bob', 2, 5, 2),
              ('bob', 30, 32, 2))
    ieq(expect, result)


def test_sessionize_compound_key():
    table = (('user', 'device', 'time'),
             ('alice', 'phone', 1),
             ('alice', 'laptop', 2),
             ('alice', 'phone', 3))
    result = sessionize(table, key=('user', 'device'), time='time', gap=5)
    expect = (('user', 'device', 'start', 'end', 'count'),
              ('alice', 'phone', 1, 3, 2),
              ('alice', 'laptop', 2, 2, 1))
    ieq(expect, result)


def test_sessionize_fluent():
    table = (('user', 'time'), ('alice', 1), ('alice', 3))
    result = etl.wrap(table).sessionize(key='user', time='time', gap=5)
    expect = (('user', 'start', 'end', 'count'), ('alice', 1, 3, 2))
    ieq(expect, result)


def test_sessionize_watermark_records():
    # explicit watermark records close sessions as they advance
    table = (('user', 'time', 'wm'),
             ('alice', 1, None),
             ('alice', 3, None),
             (None, None, 8),  # 3 + 5 <= 8, first session closes
             ('alice', 20, None),
             ('alice', 22, None),
             (None, None, 30),  # 22 + 5 <= 30, second session closes
             ('bob', 40, None))  # flushed at end of input
    result = sessionize(table, key='user', time='time', gap=5,
                        watermark='wm')
    expect = (('user', 'start', 'end', 'count'),
              ('alice', 1, 3, 2),
              ('alice', 20, 22, 2),
              ('bob', 40, 40, 1))
    ieq(expect, result)


def test_sessionize_streams_before_input_end():
    # sessions are emitted as soon as the watermark proves them
    # complete, without consuming the rest of the input
    pulled = []

    def source():
        yield ('user', 'time', 'wm')
        for row in (('alice', 1, None),
                    ('alice', 3, None),
                    (None, None, 8),
                    ('bob', 20, None),
                    ('bob', 22, None)):
            pulled.append(row)
            yield row

    result = sessionize(source(), key='user', time='time', gap=5,
                        watermark='wm')
    it = iter(result)
    assert next(it) == ('user', 'start', 'end', 'count')
    assert next(it) == ('alice', 1, 3, 2)
    # only the rows up to the watermark record were consumed
    assert len(pulled) == 3
    assert list(it) == [('bob', 20, 22, 2)]


def test_sessionize_max_out_of_order():
    # watermark derived from the events themselves
    table = (('user', 'time'),
             ('alice', 1),
             ('alice', 3),
             ('alice', 20),   # watermark 10, closes [1, 3]
             ('alice', 22),   # watermark 12, [20, 22] still open
             ('alice', 40))   # watermark 30, closes [20, 22]
    result = sessionize(table, key='user', time='time', gap=5,
                        max_out_of_order=10)
    expect = (('user', 'start', 'end', 'count'),
              ('alice', 1, 3, 2),
              ('alice', 20, 22, 2),
              ('alice', 40, 40, 1))
    ieq(expect, result)


def test_sessionize_bridge_event_merges_sessions():
    # a late event bridges two sessions that are both still open
    table = (('user', 'time', 'wm'),
             ('alice', 1, None),
             ('alice', 11, None),   # gap 5: separate session
             (None, None, 3),       # watermark 3, both still open
             ('alice', 6, None))    # within gap of both, merges them
    result = sessionize(table, key='user', time='time', gap=5,
                        watermark='wm')
    expect = (('user', 'start', 'end', 'count'),
              ('alice', 1, 11, 3))
    ieq(expect, result)


def test_sessionize_late_event_extends_open_session():
    table = (('user', 'time', 'wm'),
             ('alice', 1, None),
             ('alice', 5, None),
             (None, None, 8),    # 5 + 5 > 8, session still open
             ('alice', 7, None),  # late (7 <= 8) but legally extends
             (None, None, 12))   # 7 + 5 <= 12, session closes
    result = sessionize(table, key='user', time='time', gap=5,
                        watermark='wm')
    expect = (('user', 'start', 'end', 'count'),
              ('alice', 1, 7, 3))
    ieq(expect, result)


def test_sessionize_too_late_event_problems():
    table = (('user', 'time', 'wm'),
             ('alice', 1, None),
             ('alice', 3, None),
             (None, None, 8),    # closes session [1, 3]
             ('alice', 4, None),  # too late, belongs to closed session
             ('alice', 20, None))
    result = sessionize(table, key='user', time='time', gap=5,
                        watermark='wm', on_late='problems')
    # emitted sessions are unaffected by the late event
    expect = (('user', 'start', 'end', 'count'),
              ('alice', 1, 3, 2),
              ('alice', 20, 20, 1))
    ieq(expect, result)
    problems = result.problems
    expect_problems = (('user', 'time', 'wm', 'reason'),
                       ('alice', 4, None,
                        'event arrived after the watermark closed '
                        'its session'))
    ieq(expect_problems, problems)


def test_sessionize_problems_without_iterating_sessions():
    # iterating the problem stream alone drives the transform
    table = (('user', 'time', 'wm'),
             ('alice', 1, None),
             (None, None, 6),
             ('alice', 2, None))
    result = sessionize(table, key='user', time='time', gap=5,
                        watermark='wm', on_late='problems')
    problems = list(result.problems)
    assert problems[0] == ('user', 'time', 'wm', 'reason')
    assert len(problems) == 2
    assert problems[1][:3] == ('alice', 2, None)


def test_sessionize_too_late_event_errors():
    table = (('user', 'time', 'wm'),
             ('alice', 1, None),
             ('alice', 3, None),
             (None, None, 8),
             ('alice', 4, None))
    result = sessionize(table, key='user', time='time', gap=5,
                        watermark='wm')
    with pytest.raises(LateEventError):
        list(result)


def test_sessionize_too_late_event_ignored():
    table = (('user', 'time', 'wm'),
             ('alice', 1, None),
             (None, None, 6),
             ('alice', 2, None))
    result = sessionize(table, key='user', time='time', gap=5,
                        watermark='wm', on_late='ignore')
    expect = (('user', 'start', 'end', 'count'),
              ('alice', 1, 1, 1))
    ieq(expect, result)


def test_sessionize_aggregate():
    table = (('user', 'time', 'value'),
             ('alice', 1, 10),
             ('alice', 3, 20),
             ('alice', 30, 5))
    result = sessionize(table, key='user', time='time', gap=5,
                        aggregate={'total': (0,
                                             lambda st, row: st + row[2],
                                             lambda a, b: a + b)})
    expect = (('user', 'start', 'end', 'count', 'total'),
              ('alice', 1, 3, 2, 30),
              ('alice', 30, 30, 1, 5))
    ieq(expect, result)


def test_sessionize_aggregate_merged_on_bridge():
    # aggregate states of bridged sessions are combined via merge
    table = (('user', 'time', 'value'),
             ('alice', 1, 10),
             ('alice', 11, 20),
             ('alice', 6, 5))   # bridges the two open sessions
    result = sessionize(table, key='user', time='time', gap=5,
                        aggregate={'total': (0,
                                             lambda st, row: st + row[2],
                                             lambda a, b: a + b)})
    expect = (('user', 'start', 'end', 'count', 'total'),
              ('alice', 1, 11, 3, 35))
    ieq(expect, result)


def test_sessionize_aggregate_finalize():
    table = (('user', 'time', 'value'),
             ('alice', 1, 10),
             ('alice', 3, 30))
    result = sessionize(
        table, key='user', time='time', gap=5,
        aggregate={'mean': (lambda: [0, 0],
                            lambda st, row: [st[0] + row[2], st[1] + 1],
                            lambda a, b: [a[0] + b[0], a[1] + b[1]],
                            lambda st: st[0] // st[1])})
    expect = (('user', 'start', 'end', 'count', 'mean'),
              ('alice', 1, 3, 2, 20))
    ieq(expect, result)


def test_sessionize_datetimes():
    d = datetime(2023, 1, 1, 12, 0, 0)
    m = timedelta(minutes=1)
    table = (('user', 'time'),
             ('alice', d),
             ('alice', d + 2 * m),
             ('alice', d + 60 * m))
    result = sessionize(table, key='user', time='time',
                        gap=timedelta(minutes=5))
    expect = (('user', 'start', 'end', 'count'),
              ('alice', d, d + 2 * m, 2),
              ('alice', d + 60 * m, d + 60 * m, 1))
    ieq(expect, result)


def test_sessionize_empty():
    result = sessionize([], key='user', time='time', gap=5)
    assert list(result) == []


def test_sessionize_invalid_on_late():
    from petl.errors import ArgumentError
    table = (('user', 'time'), ('alice', 1))
    with pytest.raises(ArgumentError):
        sessionize(table, key='user', time='time', gap=5,
                   on_late='bogus')
