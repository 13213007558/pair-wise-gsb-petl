from __future__ import absolute_import, division, print_function

import itertools

import pytest

from petl import asofjoin
from petl.errors import ArgumentError
from petl.test.helpers import ieq


def test_asofjoin_backward_quotes_unsorted_preserve_left_order():
    trades = (
        ('market', 'product', 'time', 'trade_id'),
        ('X', 'A', 10, 't2'),
        ('Y', 'A', 5, 't3'),
        ('X', 'A', 4, 't1'),
        ('X', 'B', 7, 't4'),
        ('X', 'A', None, 't5'),
    )
    quotes = (
        ('market', 'product', 'time', 'price'),
        ('X', 'A', 8, 108),
        ('X', 'A', 3, 103),
        ('X', 'A', 3, 103.5),
        ('Y', 'A', 6, 106),
        ('X', 'B', 9, 109),
        ('X', 'B', 6, 106.5),
        ('X', 'A', None, 999),
    )

    actual = asofjoin(
        trades, quotes, key=['market', 'product'], time='time',
        direction='backward', preserve_left_order=True, buffersize=2
    )
    expect = (
        ('market', 'product', 'time', 'trade_id', 'time', 'price'),
        ('X', 'A', 10, 't2', 8, 108),
        ('Y', 'A', 5, 't3', None, None),
        ('X', 'A', 4, 't1', 3, 103),
        ('X', 'B', 7, 't4', 6, 106.5),
        ('X', 'A', None, 't5', None, None),
    )
    ieq(expect, actual)
    ieq(expect, actual)


def test_asofjoin_directions_presorted():
    left = (
        ('product', 'time', 'trade_id'),
        ('A', 2, 't1'),
        ('A', 3, 't2'),
        ('A', 4, 't3'),
    )
    right = (
        ('product', 'time', 'price'),
        ('A', 2, 20),
        ('A', 4, 40),
    )

    actual = asofjoin(left, right, key='product', time='time',
                      direction='backward', presorted=True)
    expect = (
        ('product', 'time', 'trade_id', 'time', 'price'),
        ('A', 2, 't1', 2, 20),
        ('A', 3, 't2', 2, 20),
        ('A', 4, 't3', 4, 40),
    )
    ieq(expect, actual)

    actual = asofjoin(left, right, key='product', time='time',
                      direction='forward', presorted=True)
    expect = (
        ('product', 'time', 'trade_id', 'time', 'price'),
        ('A', 2, 't1', 2, 20),
        ('A', 3, 't2', 4, 40),
        ('A', 4, 't3', 4, 40),
    )
    ieq(expect, actual)

    actual = asofjoin(left, right, key='product', time='time',
                      direction='nearest', presorted=True)
    expect = (
        ('product', 'time', 'trade_id', 'time', 'price'),
        ('A', 2, 't1', 2, 20),
        ('A', 3, 't2', 2, 20),
        ('A', 4, 't3', 4, 40),
    )
    ieq(expect, actual)


def test_asofjoin_disallow_equal_times():
    left = (
        ('product', 'time', 'trade_id'),
        ('A', 2, 't1'),
        ('A', 3, 't2'),
        ('A', 4, 't3'),
    )
    right = (
        ('product', 'time', 'price'),
        ('A', 2, 20),
        ('A', 4, 40),
    )

    actual = asofjoin(left, right, key='product', time='time',
                      direction='backward', allow_exact_matches=False,
                      presorted=True)
    expect = (
        ('product', 'time', 'trade_id', 'time', 'price'),
        ('A', 2, 't1', None, None),
        ('A', 3, 't2', 2, 20),
        ('A', 4, 't3', 2, 20),
    )
    ieq(expect, actual)

    actual = asofjoin(left, right, key='product', time='time',
                      direction='forward', allow_exact_matches=False,
                      presorted=True)
    expect = (
        ('product', 'time', 'trade_id', 'time', 'price'),
        ('A', 2, 't1', 4, 40),
        ('A', 3, 't2', 4, 40),
        ('A', 4, 't3', None, None),
    )
    ieq(expect, actual)

    actual = asofjoin(left, right, key='product', time='time',
                      direction='nearest', allow_equal=False,
                      presorted=True)
    expect = (
        ('product', 'time', 'trade_id', 'time', 'price'),
        ('A', 2, 't1', 4, 40),
        ('A', 3, 't2', 2, 20),
        ('A', 4, 't3', 2, 20),
    )
    ieq(expect, actual)


def test_asofjoin_nearest_tie_and_tolerance():
    left = (
        ('product', 'time', 'trade_id'),
        ('A', 4, 't1'),
        ('A', 10, 't2'),
    )
    right = (
        ('product', 'time', 'price'),
        ('A', 3, 30),
        ('A', 5, 50),
        ('A', 12, 120),
    )

    actual = asofjoin(left, right, key='product', time='time',
                      direction='nearest', presorted=True)
    expect = (
        ('product', 'time', 'trade_id', 'time', 'price'),
        ('A', 4, 't1', 3, 30),
        ('A', 10, 't2', 12, 120),
    )
    ieq(expect, actual)

    actual = asofjoin(left, right, key='product', time='time',
                      direction='nearest', tolerance=1, presorted=True)
    expect = (
        ('product', 'time', 'trade_id', 'time', 'price'),
        ('A', 4, 't1', 3, 30),
        ('A', 10, 't2', None, None),
    )
    ieq(expect, actual)


def test_asofjoin_null_times_are_not_zero():
    left = (
        ('product', 'time', 'trade_id'),
        ('A', None, 't1'),
        ('A', 0, 't2'),
        ('A', 1, 't3'),
    )
    right = (
        ('product', 'time', 'price'),
        ('A', None, 999),
        ('A', 0, 100),
    )

    actual = asofjoin(left, right, key='product', time='time',
                      direction='backward', presorted=True)
    expect = (
        ('product', 'time', 'trade_id', 'time', 'price'),
        ('A', None, 't1', None, None),
        ('A', 0, 't2', 0, 100),
        ('A', 1, 't3', 0, 100),
    )
    ieq(expect, actual)


def test_asofjoin_lrkey_and_lrtime():
    left = (
        ('sku', 'trade_time', 'qty'),
        ('A', 5, 10),
        ('B', 7, 20),
    )
    right = (
        ('product', 'quote_time', 'price'),
        ('A', 4, 100),
        ('B', 9, 200),
    )

    actual = asofjoin(left, right, lkey='sku', rkey='product',
                      ltime='trade_time', rtime='quote_time',
                      direction='backward', presorted=True)
    expect = (
        ('sku', 'trade_time', 'qty', 'quote_time', 'price'),
        ('A', 5, 10, 4, 100),
        ('B', 7, 20, None, None),
    )
    ieq(expect, actual)


def test_asofjoin_presorted_is_incremental_with_large_right():
    left = (
        ('product', 'time', 'trade_id'),
        ('A', 5.5, 't1'),
        ('A', 7.5, 't2'),
    )

    def quotes():
        yield ('product', 'time', 'price')
        n = 0
        while True:
            yield ('A', n, n * 10)
            n += 1

    expected_times = {
        'backward': (5, 7),
        'forward': (6, 8),
        'nearest': (5, 7),
    }
    for direction, times in expected_times.items():
        actual = asofjoin(left, quotes(), key='product', time='time',
                          direction=direction, presorted=True)
        expect = (
            ('product', 'time', 'trade_id', 'time', 'price'),
            ('A', 5.5, 't1', times[0], times[0] * 10),
            ('A', 7.5, 't2', times[1], times[1] * 10),
        )
        ieq(expect, itertools.islice(actual, 3))


def test_asofjoin_natural_key_and_stable_duplicate_times():
    left = (
        ('product', 'time', 'trade_id'),
        ('A', 3, 't1'),
    )
    right = (
        ('product', 'time', 'price'),
        ('A', 3, 100),
        ('A', 3, 101),
    )

    actual = asofjoin(left, right, time='time', direction='backward',
                      presorted=True)
    expect = (
        ('product', 'time', 'trade_id', 'time', 'price'),
        ('A', 3, 't1', 3, 100),
    )
    ieq(expect, actual)


def test_asofjoin_invalid_arguments():
    left = (('product', 'time'), ('A', 1))
    right = (('product', 'time'), ('A', 1))

    with pytest.raises(ArgumentError):
        asofjoin(left, right, key='product', time='time',
                 direction='sideways')
    with pytest.raises(ArgumentError):
        asofjoin(left, right, key='product', time='time', tolerance=-1)
    with pytest.raises(ArgumentError):
        asofjoin(left, right, key='product', time='time', presorted=True,
                 preserve_left_order=True)
    with pytest.raises(ArgumentError):
        asofjoin(left, right, key='product')
