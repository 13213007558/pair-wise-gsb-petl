from __future__ import absolute_import, print_function, division


import os
import gc
import logging
from datetime import datetime
import platform

import pytest

from petl.compat import next

from petl.errors import FieldSelectionError, ArgumentError, SortComparisonError
from petl.test.helpers import ieq, eq_
from petl.util import nrows
from petl.transform.basics import cat
from petl.transform.sorts import sort, mergesort, issorted, SortField


logger = logging.getLogger(__name__)
debug = logger.debug


def test_sort_1():

    table = (('foo', 'bar'),
             ('C', '2'),
             ('A', '9'),
             ('A', '6'),
             ('F', '1'),
             ('D', '10'))

    result = sort(table, 'foo')
    expectation = (('foo', 'bar'),
                   ('A', '9'),
                   ('A', '6'),
                   ('C', '2'),
                   ('D', '10'),
                   ('F', '1'))
    ieq(expectation, result)


def test_sort_2():

    table = (('foo', 'bar'),
             ('C', '2'),
             ('A', '9'),
             ('A', '6'),
             ('F', '1'),
             ('D', '10'))

    result = sort(table, key=('foo', 'bar'))
    expectation = (('foo', 'bar'),
                   ('A', '6'),
                   ('A', '9'),
                   ('C', '2'),
                   ('D', '10'),
                   ('F', '1'))
    ieq(expectation, result)

    result = sort(table)  # default is lexical sort
    expectation = (('foo', 'bar'),
                   ('A', '6'),
                   ('A', '9'),
                   ('C', '2'),
                   ('D', '10'),
                   ('F', '1'))
    ieq(expectation, result)


def test_sort_3():

    table = (('foo', 'bar'),
             ('C', '2'),
             ('A', '9'),
             ('A', '6'),
             ('F', '1'),
             ('D', '10'))

    result = sort(table, 'bar')
    expectation = (('foo', 'bar'),
                   ('F', '1'),
                   ('D', '10'),
                   ('C', '2'),
                   ('A', '6'),
                   ('A', '9'))
    ieq(expectation, result)


def test_sort_4():

    table = (('foo', 'bar'),
             ('C', 2),
             ('A', 9),
             ('A', 6),
             ('F', 1),
             ('D', 10))

    result = sort(table, 'bar')
    expectation = (('foo', 'bar'),
                   ('F', 1),
                   ('C', 2),
                   ('A', 6),
                   ('A', 9),
                   ('D', 10))
    ieq(expectation, result)


def test_sort_5():

    table = (('foo', 'bar'),
             (2.3, 2),
             (1.2, 9),
             (2.3, 6),
             (3.2, 1),
             (1.2, 10))

    expectation = (('foo', 'bar'),
                   (1.2, 9),
                   (1.2, 10),
                   (2.3, 2),
                   (2.3, 6),
                   (3.2, 1))

    # can use either field names or indices (from 1) to specify sort key
    result = sort(table, key=('foo', 'bar'))
    ieq(expectation, result)
    result = sort(table, key=(0, 1))
    ieq(expectation, result)
    result = sort(table, key=('foo', 1))
    ieq(expectation, result)
    result = sort(table, key=(0, 'bar'))
    ieq(expectation, result)


def test_sort_6():

    table = (('foo', 'bar'),
             (2.3, 2),
             (1.2, 9),
             (2.3, 6),
             (3.2, 1),
             (1.2, 10))

    expectation = (('foo', 'bar'),
                   (3.2, 1),
                   (2.3, 6),
                   (2.3, 2),
                   (1.2, 10),
                   (1.2, 9))

    result = sort(table, key=('foo', 'bar'), reverse=True)
    ieq(expectation, result)


def test_sort_buffered():

    table = (('foo', 'bar'),
             ('C', 2),
             ('A', 9),
             ('A', 6),
             ('F', 1),
             ('D', 10))

    # test sort forwards
    expectation = (('foo', 'bar'),
                   ('F', 1),
                   ('C', 2),
                   ('A', 6),
                   ('A', 9),
                   ('D', 10))
    result = sort(table, 'bar')
    ieq(expectation, result)
    result = sort(table, 'bar', buffersize=2)
    ieq(expectation, result)

    # sort in reverse
    expectation = (('foo', 'bar'),
                   ('D', 10),
                   ('A', 9),
                   ('A', 6),
                   ('C', 2),
                   ('F', 1))

    result = sort(table, 'bar', reverse=True)
    ieq(expectation, result)
    result = sort(table, 'bar', reverse=True, buffersize=2)
    ieq(expectation, result)

    # no key
    expectation = (('foo', 'bar'),
                   ('F', 1),
                   ('D', 10),
                   ('C', 2),
                   ('A', 9),
                   ('A', 6))
    result = sort(table, reverse=True)
    ieq(expectation, result)
    result = sort(table, reverse=True, buffersize=2)
    ieq(expectation, result)


def test_sort_buffered_tempdir():

    table = (('foo', 'bar'),
             ('C', 2),
             ('A', 9),
             ('A', 6),
             ('F', 1),
             ('D', 10))

    # test sort forwards
    expectation = (('foo', 'bar'),
                   ('F', 1),
                   ('C', 2),
                   ('A', 6),
                   ('A', 9),
                   ('D', 10))
    result = sort(table, 'bar')
    ieq(expectation, result)
    tempdir = 'tmp'
    if not os.path.exists(tempdir):
        os.mkdir(tempdir)
    result = sort(table, 'bar', buffersize=2, tempdir=tempdir)
    ieq(expectation, result)


def test_sort_buffered_independent():

    table = (('foo', 'bar'),
             ('C', 2),
             ('A', 9),
             ('A', 6),
             ('F', 1),
             ('D', 10))
    expectation = (('foo', 'bar'),
                   ('F', 1),
                   ('C', 2),
                   ('A', 6),
                   ('A', 9),
                   ('D', 10))

    result = sort(table, 'bar', buffersize=4)
    nrows(result)  # cause data to be cached
    # check that two row iterators are independent, i.e., consuming rows
    # from one does not affect the other
    it1 = iter(result)
    it2 = iter(result)
    eq_(expectation[0], next(it1))
    eq_(expectation[1], next(it1))
    eq_(expectation[0], next(it2))
    eq_(expectation[1], next(it2))
    eq_(expectation[2], next(it2))
    eq_(expectation[2], next(it1))


def _get_names(l):
    return [x.name for x in l]


def test_sort_buffered_cleanup():

    table = (('foo', 'bar'),
             ('C', 2),
             ('A', 9),
             ('A', 6),
             ('F', 1),
             ('D', 10))
    result = sort(table, 'bar', buffersize=2)
    debug('initially filecache should be empty')
    eq_(None, result._filecache)
    debug('pull rows through, should populate file cache')
    eq_(5, nrows(result))
    eq_(3, len(result._filecache))
    debug('check all files exist')
    filenames = _get_names(result._filecache)
    for fn in filenames:
        assert os.path.exists(fn), fn
    debug('delete object and garbage collect')
    del result
    gc.collect()
    debug('check all files have been deleted')
    for fn in filenames:
        assert not os.path.exists(fn), fn


@pytest.mark.skipif(platform.python_implementation() == 'PyPy', reason='SKIP sort cleanup test (PyPy)')
def test_sort_buffered_cleanup_open_iterator():

    table = (('foo', 'bar'),
             ('C', 2),
             ('A', 9),
             ('A', 6),
             ('F', 1),
             ('D', 10))
    # check if cleanup is robust against open iterators
    result = sort(table, 'bar', buffersize=2)
    debug('pull rows through, should populate file cache')
    eq_(5, nrows(result))
    eq_(3, len(result._filecache))
    debug('check all files exist')
    filenames = _get_names(result._filecache)
    for fn in filenames:
        assert os.path.exists(fn), fn
    debug(filenames)
    debug('open an iterator')
    it = iter(result)
    next(it)
    next(it)
    debug('delete objects and garbage collect')
    del result
    del it
    gc.collect()
    for fn in filenames:
        assert not os.path.exists(fn), fn


def test_sort_empty():
    table = (('foo', 'bar'),)
    expect = (('foo', 'bar'),)
    actual = sort(table)
    ieq(expect, actual)


def test_sort_none():

    table = (('foo', 'bar'),
             ('C', 2),
             ('A', 9),
             ('A', None),
             ('F', 1),
             ('D', 10))

    result = sort(table, 'bar')
    print(list(result))
    expectation = (('foo', 'bar'),
                   ('A', None),
                   ('F', 1),
                   ('C', 2),
                   ('A', 9),
                   ('D', 10))
    ieq(expectation, result)

    dt = datetime.now().replace

    table = (('foo', 'bar'),
             ('C', dt(hour=5)),
             ('A', dt(hour=1)),
             ('A', None),
             ('F', dt(hour=9)),
             ('D', dt(hour=17)))

    result = sort(table, 'bar')
    expectation = (('foo', 'bar'),
                   ('A', None),
                   ('A', dt(hour=1)),
                   ('C', dt(hour=5)),
                   ('F', dt(hour=9)),
                   ('D', dt(hour=17)))
    ieq(expectation, result)


def test_sort_headerless_no_keys():
    """
    Sorting a headerless table without specifying cols should be a no-op.
    """
    table = []
    result = sort(table)
    expectation = []
    ieq(expectation, result)


def test_sort_headerless_explicit():
    """
    But if you specify keys, they must exist.
    """
    table = []
    with pytest.raises(FieldSelectionError):
        for i in sort(table, 'foo'):
            pass

# TODO test sort with native comparison


def test_mergesort_1():

    table1 = (('foo', 'bar'),
              ('A', 6),
              ('C', 2),
              ('D', 10),
              ('A', 9),
              ('F', 1))

    table2 = (('foo', 'bar'),
              ('B', 3),
              ('D', 10),
              ('A', 10),
              ('F', 4))

    # should be same as concatenate then sort (but more efficient, esp. when
    # presorted)
    expect = sort(cat(table1, table2))

    actual = mergesort(table1, table2)
    ieq(expect, actual)
    ieq(expect, actual)

    actual = mergesort(sort(table1), sort(table2), presorted=True)
    ieq(expect, actual)
    ieq(expect, actual)


def test_mergesort_2():

    table1 = (('foo', 'bar'),
              ('A', 9),
              ('C', 2),
              ('D', 10),
              ('A', 6),
              ('F', 1))

    table2 = (('foo', 'baz'),
              ('B', 3),
              ('D', 10),
              ('A', 10),
              ('F', 4))

    # should be same as concatenate then sort (but more efficient, esp. when
    # presorted)
    expect = sort(cat(table1, table2), key='foo')

    actual = mergesort(table1, table2, key='foo')
    ieq(expect, actual)
    ieq(expect, actual)

    actual = mergesort(sort(table1, key='foo'), sort(table2, key='foo'),
                       key='foo', presorted=True)
    ieq(expect, actual)
    ieq(expect, actual)


def test_mergesort_3():

    table1 = (('foo', 'bar'),
              ('A', 9),
              ('C', 2),
              ('D', 10),
              ('A', 6),
              ('F', 1))

    table2 = (('foo', 'baz'),
              ('B', 3),
              ('D', 10),
              ('A', 10),
              ('F', 4))

    # should be same as concatenate then sort (but more efficient, esp. when
    # presorted)
    expect = sort(cat(table1, table2), key='foo', reverse=True)

    actual = mergesort(table1, table2, key='foo', reverse=True)
    ieq(expect, actual)
    ieq(expect, actual)

    actual = mergesort(sort(table1, key='foo', reverse=True),
                       sort(table2, key='foo', reverse=True),
                       key='foo', reverse=True, presorted=True)
    ieq(expect, actual)
    ieq(expect, actual)


def test_mergesort_4():

    table1 = (('foo', 'bar', 'baz'),
              (1, 'A', True),
              (2, 'B', None),
              (4, 'C', True))
    table2 = (('bar', 'baz', 'quux'),
              ('A', True, 42.0),
              ('B', False, 79.3),
              ('C', False, 12.4))

    expect = sort(cat(table1, table2), key='bar')

    actual = mergesort(table1, table2, key='bar')
    ieq(expect, actual)
    ieq(expect, actual)


def test_mergesort_empty():

    table1 = (('foo', 'bar'),
              ('A', 9),
              ('C', 2),
              ('D', 10),
              ('F', 1))

    table2 = (('foo', 'bar'),)

    expect = table1
    actual = mergesort(table1, table2, key='foo')
    ieq(expect, actual)
    ieq(expect, actual)


def test_issorted():

    table1 = (('foo', 'bar', 'baz'),
              ('a', 1, True),
              ('b', 3, True),
              ('b', 2))
    assert issorted(table1, key='foo')
    assert not issorted(table1, key='foo', reverse=True)
    assert not issorted(table1, key='foo', strict=True)

    table2 = (('foo', 'bar', 'baz'),
              ('b', 2, True),
              ('a', 1, True),
              ('b', 3))
    assert not issorted(table2, key='foo')

    table3 = (('foo', 'bar', 'baz'),
              ('a', 1, True),
              ('b', 2, True),
              ('b', 3))
    assert issorted(table3, key=('foo', 'bar'))
    assert issorted(table3)

    table4 = (('foo', 'bar', 'baz'),
              ('a', 1, True),
              ('b', 3, True),
              ('b', 2))
    assert not issorted(table4, key=('foo', 'bar'))
    assert not issorted(table4)

    table5 = (('foo', 'bar', 'baz'),
              ('b', 3, True),
              ('b', 2),
              ('a', 1, True))
    assert not issorted(table5, key='foo')
    assert issorted(table5, key='foo', reverse=True)
    assert not issorted(table5, key='foo', reverse=True, strict=True)


def test_sort_missing_cell_numeric():
    """ Sorting table with missing values raises IndexError #385 """
    tbl = (('a', 'b'), ('4',), ('2', '1'), ('1',))
    expect = (('a', 'b'), ('1',), ('2', '1'), ('4',))

    tbl_sorted = sort(tbl)
    ieq(expect, tbl_sorted)


def test_sort_missing_cell_text():
    """ Sorting table with missing values raises IndexError #385 """
    tbl = (('a', 'b', 'c'), ('C',), ('A', '4', '5'))
    expect = (('a', 'b', 'c'), ('A', '4', '5'), ('C',))

    tbl_sorted = sort(tbl)
    ieq(expect, tbl_sorted)


def test_sort_spec():
    # per-field spec: priority descending with missing last,
    # name ascending with missing first
    table = (('name', 'priority'),
             ('b', 2),
             ('a', None),
             (None, 1),
             ('c', 3),
             ('a', 1))
    spec = [SortField('priority', reverse=True, missing_position='last'),
            SortField('name', missing_position='first')]
    expectation = (('name', 'priority'),
                   ('c', 3),
                   ('b', 2),
                   (None, 1),
                   ('a', 1),
                   ('a', None))

    result = sort(table, spec=spec)
    ieq(expectation, result)
    ieq(expectation, result)  # second pass comes from the cache

    # tiny buffer forces chunked sort with file-based merge,
    # must agree exactly with the in-memory result
    result = sort(table, spec=spec, buffersize=1)
    ieq(expectation, result)
    ieq(expectation, result)


def test_sort_spec_missing_position_not_flipped():
    # missing position is independent of the sort direction
    table = (('foo', 'bar'),
             ('C', 2),
             ('A', None),
             ('F', 1),
             ('D', 10))

    spec = [SortField('bar', missing_position='last')]
    expectation = (('foo', 'bar'),
                   ('F', 1),
                   ('C', 2),
                   ('D', 10),
                   ('A', None))
    ieq(expectation, sort(table, spec=spec))

    # same missing position under descending direction
    spec = [SortField('bar', reverse=True, missing_position='last')]
    expectation = (('foo', 'bar'),
                   ('D', 10),
                   ('C', 2),
                   ('F', 1),
                   ('A', None))
    ieq(expectation, sort(table, spec=spec))

    # and missing first under descending direction
    spec = [SortField('bar', reverse=True, missing_position='first')]
    expectation = (('foo', 'bar'),
                   ('A', None),
                   ('D', 10),
                   ('C', 2),
                   ('F', 1))
    ieq(expectation, sort(table, spec=spec))


def test_sort_spec_stable():
    # rows comparing equal under the whole spec keep their input order
    table = (('foo', 'bar', 'baz'),
             ('A', 1, 'x'),
             ('B', 1, 'y'),
             ('A', 1, 'z'),
             ('B', 1, 'w'),
             ('A', 2, 'v'))
    spec = [SortField('foo'), SortField('bar')]
    expectation = (('foo', 'bar', 'baz'),
                   ('A', 1, 'x'),
                   ('A', 1, 'z'),
                   ('A', 2, 'v'),
                   ('B', 1, 'y'),
                   ('B', 1, 'w'))
    ieq(expectation, sort(table, spec=spec))
    # stability must hold through the chunked merge path too
    ieq(expectation, sort(table, spec=spec, buffersize=1))


def test_sort_spec_all_missing_field():
    # a field where every value is missing falls through to the next
    # field, and full ties keep the input order
    table = (('foo', 'bar', 'baz'),
             ('b', None, 2),
             ('a', None, 1),
             ('b', None, 1),
             ('a', None, 3))
    spec = [SortField('bar', missing_position='last'),
            SortField('foo'),
            SortField('baz', reverse=True)]
    expectation = (('foo', 'bar', 'baz'),
                   ('a', None, 3),
                   ('a', None, 1),
                   ('b', None, 2),
                   ('b', None, 1))
    ieq(expectation, sort(table, spec=spec))
    ieq(expectation, sort(table, spec=spec, buffersize=1))


def test_sort_spec_buffered_matches_memory():
    # compound spec with mixed directions and missing positions, tiny
    # buffer to force a multi-way file merge, compared row by row with
    # the pure in-memory result, iterating repeatedly
    table = [('name', 'priority', 'score')]
    data = [('b', 2, 1.5), ('a', None, 2.5), (None, 1, None),
            ('c', 3, 1.5), ('a', 1, 2.5), ('b', None, 0.5),
            (None, None, 1.5), ('a', 3, None), ('c', 1, 0.5)]
    table += data
    spec = [SortField('priority', reverse=True, missing_position='last'),
            SortField('name', missing_position='first'),
            SortField('score', missing_position='last')]

    in_memory = sort(table, spec=spec, buffersize=1000)
    expected = list(in_memory)
    # in-memory result is cached, second pass must be identical
    eq_(expected, list(in_memory))

    for buffersize in (1, 2, 3):
        buffered = sort(table, spec=spec, buffersize=buffersize)
        actual = list(buffered)
        eq_(len(expected), len(actual))
        for want, got in zip(expected, actual):
            eq_(want, got)
        # repeated iteration over the file cache must be identical
        eq_(expected, list(buffered))


def test_sort_spec_plain_fields():
    # plain field names in a spec use the defaults and behave like key
    table = (('foo', 'bar'),
             ('C', 2),
             ('A', 9),
             ('A', 6),
             ('F', 1),
             ('D', 10))
    expectation = (('foo', 'bar'),
                   ('A', 6),
                   ('A', 9),
                   ('C', 2),
                   ('D', 10),
                   ('F', 1))
    ieq(expectation, sort(table, spec=['foo', 'bar']))
    ieq(expectation, sort(table, spec=[SortField('foo'), SortField('bar')]))
    ieq(expectation, sort(table, spec=[{'field': 'foo'},
                                       {'field': 'bar'}]))


def test_sort_spec_callable_missing():
    # a callable decides which values count as missing
    table = (('foo', 'bar'),
             ('C', 2),
             ('A', ''),
             ('F', 1),
             ('D', None))
    spec = [SortField('bar', missing=lambda v: v is None or v == '',
                      missing_position='last')]
    expectation = (('foo', 'bar'),
                   ('F', 1),
                   ('C', 2),
                   ('A', ''),
                   ('D', None))
    ieq(expectation, sort(table, spec=spec))
    ieq(expectation, sort(table, spec=spec, buffersize=1))


def test_sort_spec_short_rows():
    # values absent from short rows count as missing
    table = (('foo', 'bar'),
             ('C', 2),
             ('A',),
             ('F', 1))
    spec = [SortField('bar', missing_position='first')]
    expectation = (('foo', 'bar'),
                   ('A',),
                   ('F', 1),
                   ('C', 2))
    ieq(expectation, sort(table, spec=spec))
    ieq(expectation, sort(table, spec=spec, buffersize=1))


def test_sort_spec_incomparable():
    # incomparable non-missing values raise an error reporting the
    # field and the source rows involved
    table = (('foo', 'bar'),
             ('C', 2),
             ('A', 'x'),
             ('F', 1))
    spec = [SortField('bar')]
    with pytest.raises(SortComparisonError) as excinfo:
        list(sort(table, spec=spec))
    message = str(excinfo.value)
    assert "'bar'" in message
    assert "'x'" in message
    assert "('A', 'x')" in message
    # also raised from the chunked merge path
    with pytest.raises(SortComparisonError):
        list(sort(table, spec=spec, buffersize=1))


def test_sort_spec_ambiguous():
    table = (('foo', 'bar'),
             ('C', 2),
             ('A', 9))
    spec = [SortField('bar')]
    # spec cannot be combined with key
    with pytest.raises(ArgumentError):
        sort(table, key='bar', spec=spec)
    # spec cannot be combined with reverse
    with pytest.raises(ArgumentError):
        sort(table, reverse=True, spec=spec)
    # invalid missing position
    with pytest.raises(ArgumentError):
        SortField('bar', missing_position='middle')
    # empty spec
    with pytest.raises(ArgumentError):
        sort(table, spec=[])
