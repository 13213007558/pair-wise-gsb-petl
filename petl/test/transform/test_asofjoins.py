from __future__ import absolute_import, division, print_function

from petl import asofjoin
from petl.util.base import Table
from petl.test.helpers import ieq


def _tables():
    trades = (
        ('product', 'time', 'price'),
        ('B', 1, 11),
        ('A', 2, 10),
        ('A', 5, 15),
        ('A', None, 16),
        ('C', 3, 30),
    )
    quotes = (
        ('product', 'time', 'quote'),
        ('A', 1, 'a1'),
        ('B', 2, 'b2'),
        ('A', 2, 'a2-first'),
        ('A', 2, 'a2-last'),
        ('A', 4, 'a4'),
        ('B', None, 'b-null'),
    )
    return trades, quotes


def test_asofjoin_backward():
    trades, quotes = _tables()
    expect = (
        ('product', 'time', 'price', 'time', 'quote'),
        ('A', None, 16, None, None),
        ('A', 2, 10, 2, 'a2-last'),
        ('A', 5, 15, 4, 'a4'),
        ('B', 1, 11, None, None),
        ('C', 3, 30, None, None),
    )
    ieq(expect, asofjoin(trades, quotes, key='product', time='time'))


def test_asofjoin_forward():
    trades, quotes = _tables()
    expect = (
        ('product', 'time', 'price', 'time', 'quote'),
        ('A', None, 16, None, None),
        ('A', 2, 10, 2, 'a2-first'),
        ('A', 5, 15, None, None),
        ('B', 1, 11, 2, 'b2'),
        ('C', 3, 30, None, None),
    )
    actual = asofjoin(trades, quotes, key='product', time='time',
                      direction='forward')
    ieq(expect, actual)


def test_asofjoin_nearest_and_tolerance():
    trades, quotes = _tables()
    expect = (
        ('product', 'time', 'price', 'time', 'quote'),
        ('A', None, 16, None, None),
        ('A', 2, 10, 2, 'a2-last'),
        ('A', 5, 15, 4, 'a4'),
        ('B', 1, 11, 2, 'b2'),
        ('C', 3, 30, None, None),
    )
    actual = asofjoin(trades, quotes, key='product', time='time',
                      direction='nearest')
    ieq(expect, actual)

    expect_tolerance = (
        ('product', 'time', 'price', 'time', 'quote'),
        ('A', None, 16, None, None),
        ('A', 2, 10, 2, 'a2-last'),
        ('A', 5, 15, 4, 'a4'),
        ('B', 1, 11, 2, 'b2'),
        ('C', 3, 30, None, None),
    )
    actual_tolerance = asofjoin(trades, quotes, key='product', time='time',
                                direction='nearest', tolerance=1)
    ieq(expect_tolerance, actual_tolerance)


def test_asofjoin_exclusive():
    trades, quotes = _tables()
    expect = (
        ('product', 'time', 'price', 'time', 'quote'),
        ('A', None, 16, None, None),
        ('A', 2, 10, 1, 'a1'),
        ('A', 5, 15, 4, 'a4'),
        ('B', 1, 11, None, None),
        ('C', 3, 30, None, None),
    )
    actual = asofjoin(trades, quotes, key='product', time='time',
                      inclusive=False)
    ieq(expect, actual)


def test_asofjoin_nearest_equal_distance_prefers_backward():
    trades = (
        ('product', 'time', 'price'),
        ('A', 3, 10),
    )
    quotes = (
        ('product', 'time', 'quote'),
        ('A', 2, 'back'),
        ('A', 4, 'forward'),
    )
    expect = (
        ('product', 'time', 'price', 'time', 'quote'),
        ('A', 3, 10, 2, 'back'),
    )
    actual = asofjoin(trades, quotes, key='product', time='time',
                      direction='nearest')
    ieq(expect, actual)


def test_asofjoin_repeated_left_time_is_stable():
    trades = (
        ('product', 'time', 'price'),
        ('A', 2, 10),
        ('A', 2, 11),
    )
    quotes = (
        ('product', 'time', 'quote'),
        ('A', 2, 'first'),
        ('A', 2, 'last'),
    )
    expect_backward = (
        ('product', 'time', 'price', 'time', 'quote'),
        ('A', 2, 10, 2, 'last'),
        ('A', 2, 11, 2, 'last'),
    )
    expect_forward = (
        ('product', 'time', 'price', 'time', 'quote'),
        ('A', 2, 10, 2, 'first'),
        ('A', 2, 11, 2, 'first'),
    )
    ieq(expect_backward, asofjoin(trades, quotes, key='product',
                                  time='time'))
    ieq(expect_forward, asofjoin(trades, quotes, key='product', time='time',
                                 direction='forward'))


def test_asofjoin_tolerance_excludes_distant_matches():
    trades = (
        ('product', 'time', 'price'),
        ('A', 6, 10),
    )
    quotes = (
        ('product', 'time', 'quote'),
        ('A', 4, 'back'),
        ('A', 8, 'forward'),
    )
    expect = (
        ('product', 'time', 'price', 'time', 'quote'),
        ('A', 6, 10, None, None),
    )
    for direction in ('backward', 'forward', 'nearest'):
        actual = asofjoin(trades, quotes, key='product', time='time',
                          direction=direction, tolerance=1)
        ieq(expect, actual)


def test_asofjoin_zero_time_matches_but_null_does_not():
    trades = (
        ('product', 'trade_time', 'price'),
        ('A', 0, 10),
        ('B', 0, 20),
    )
    quotes = (
        ('product', 'quote_time', 'quote'),
        ('A', 0, 'zero'),
        ('B', None, 'null'),
    )
    expect = (
        ('product', 'trade_time', 'price', 'quote_time', 'quote'),
        ('A', 0, 10, 0, 'zero'),
        ('B', 0, 20, None, None),
    )
    actual = asofjoin(trades, quotes, key='product', ltime='trade_time',
                      rtime='quote_time')
    ieq(expect, actual)


def test_asofjoin_compound_key():
    trades = (
        ('region', 'product', 'time', 'price'),
        ('east', 'A', 2, 10),
        ('west', 'A', 2, 20),
    )
    quotes = (
        ('region', 'product', 'time', 'quote'),
        ('east', 'A', 1, 'east-back'),
        ('east', 'A', 2, 'east-exact'),
        ('west', 'A', 2, 'west-exact'),
    )
    expect = (
        ('region', 'product', 'time', 'price', 'time', 'quote'),
        ('east', 'A', 2, 10, 2, 'east-exact'),
        ('west', 'A', 2, 20, 2, 'west-exact'),
    )
    actual = asofjoin(trades, quotes, key=['region', 'product'],
                      time='time')
    ieq(expect, actual)


def test_asofjoin_unsorted_preserve_order_and_external_sort(tmpdir):
    trades, quotes = _tables()
    actual = asofjoin(trades, quotes, key='product', time='time',
                      buffersize=2, tempdir=str(tmpdir),
                      preserve_order=True)
    expect = (
        ('product', 'time', 'price', 'time', 'quote'),
        ('B', 1, 11, None, None),
        ('A', 2, 10, 2, 'a2-last'),
        ('A', 5, 15, 4, 'a4'),
        ('A', None, 16, None, None),
        ('C', 3, 30, None, None),
    )
    ieq(expect, actual)


class _LimitedRight(Table):

    def __init__(self, n):
        self.n = n
        self.consumed = 0

    def __iter__(self):
        yield ('product', 'time', 'quote')
        for i in range(self.n):
            self.consumed += 1
            if self.consumed > 1000:
                raise AssertionError('right table was scanned too far')
            yield ('A', 50 + i, i)


def test_asofjoin_presorted_nearest_does_not_materialise_right():
    trades = (
        ('product', 'time', 'price'),
        ('A', 0, 0),
        ('A', 52, 52),
        ('A', 55, 55),
    )
    quotes = _LimitedRight(1000000)
    actual = asofjoin(trades, quotes, key='product', time='time',
                      direction='nearest', presorted=True)
    rows = [row for row in actual]
    assert rows[1] == ('A', 0, 0, 50, 0)
    assert rows[2] == ('A', 52, 52, 52, 2)
    assert rows[3] == ('A', 55, 55, 55, 5)
    assert quotes.consumed == 7
