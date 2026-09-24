from __future__ import absolute_import, print_function, division


import os
import gc
import logging
from datetime import datetime
import platform

import pytest

from petl.compat import next

from petl.errors import ArgumentError, FieldSelectionError
from petl.test.helpers import ieq, eq_
from petl.util import nrows
from petl.transform.basics import cat
from petl.transform.sorts import sort, mergesort, issorted, SortSpec


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
    with pytest.raises(FieldSelectionError):
        list(sort(table, sort_specs=[SortSpec('foo')]))

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


def test_sort_specs_compound_directions_and_missing_positions():
    table = (
        ('priority', 'name', 'source_order'),
        (1, None, 1),
        (None, 'B', 2),
        (2, 'A', 3),
        (1, 'A', 4),
        (None, None, 5),
        (2, None, 6),
        (1, 'B', 7),
        (None, 'A', 8),
        (1, 'A', 9),
    )
    specs = [
        SortSpec('priority', descending=True, missing_position='last'),
        SortSpec('name', reverse=False, missing_position='first'),
    ]
    expectation = (
        ('priority', 'name', 'source_order'),
        (2, None, 6),
        (2, 'A', 3),
        (1, None, 1),
        (1, 'A', 4),
        (1, 'A', 9),
        (1, 'B', 7),
        (None, None, 5),
        (None, 'A', 8),
        (None, 'B', 2),
    )

    in_memory = sort(table, sort_specs=specs)
    buffered = sort(table, sort_specs=specs, buffersize=1)
    ieq(expectation, in_memory)
    ieq(expectation, in_memory)
    ieq(list(in_memory), buffered)
    ieq(expectation, buffered)

    first = iter(buffered)
    second = iter(buffered)
    eq_(expectation[0], next(first))
    eq_(expectation[0], next(second))
    eq_(expectation[1], next(first))
    eq_(expectation[1], next(second))
    eq_(expectation[2], next(second))
    eq_(expectation[2], next(first))


def test_sort_specs_accept_mappings_tuples_and_custom_missing_values():
    table = (
        ('value', 'source_order'),
        (2, 1),
        (-1, 2),
        (1, 3),
        (-1, 4),
    )
    specs = [
        {
            'field': 'value',
            'direction': 'desc',
            'missing_value': -1,
            'missing_position': 'first',
        },
    ]
    expectation = (
        ('value', 'source_order'),
        (-1, 2),
        (-1, 4),
        (2, 1),
        (1, 3),
    )

    actual = sort(table, sort_specs=specs)
    ieq(expectation, actual)

    tuple_specs = [('value', 'desc', None, -1, 'first')]
    ieq(expectation, sort(table, sort_specs=tuple_specs, buffersize=1))


def test_sort_specs_is_missing():
    table = (
        ('value', 'source_order'),
        ('present', 1),
        ('missing', 2),
        ('another', 3),
        ('missing', 4),
    )
    specs = [
        SortSpec(
            'value',
            is_missing=lambda value: value == 'missing',
            missing_position='first',
        )
    ]
    expectation = (
        ('value', 'source_order'),
        ('missing', 2),
        ('missing', 4),
        ('another', 3),
        ('present', 1),
    )

    ieq(expectation, sort(table, sort_specs=specs))
    ieq(expectation, sort(table, sort_specs=specs, buffersize=1))


def test_sort_specs_all_missing_is_stable():
    table = (
        ('value', 'source_order'),
        (None, 3),
        (None, 1),
        (None, 2),
    )
    specs = [SortSpec('value', missing_position='first')]
    expectation = table

    ieq(expectation, sort(table, sort_specs=specs))
    ieq(expectation, sort(table, sort_specs=specs, buffersize=1))


def test_sort_specs_random_rows_match_memory_and_multiway_merge():
    table = [('priority', 'name', 'tie_order')]
    for index, (priority, name) in enumerate((
        (None, None), (2, None), (1, 'A'), (3, None), (None, 'B'),
        (2, 'A'), (1, None), (3, 'A'), (2, 'B'), (None, 'A'),
        (1, 'B'), (3, 'B'), (2, 'A'), (1, 'A'), (None, None),
    ), start=1):
        table.append((priority, name, index))

    specs = [
        SortSpec('priority', descending=True, missing_position='last'),
        SortSpec('name', missing_position='first'),
    ]
    in_memory = list(sort(table, sort_specs=specs))
    buffered = list(sort(table, sort_specs=specs, buffersize=2))

    eq_(len(in_memory), len(table))
    eq_(in_memory, buffered)
    assert in_memory[1][0] == 3
    assert in_memory[-1][0] is None
    assert buffered[1][0] == 3 and buffered[1][1] is None


def test_sort_specs_incomparable_values_report_field_and_rows():
    table = (
        ('value', 'source_order'),
        ('x', 1),
        (1, 2),
    )
    specs = [SortSpec('value')]

    with pytest.raises(TypeError) as excinfo:
        list(sort(table, sort_specs=specs))
    message = str(excinfo.value)
    assert "field 'value'" in message
    assert "('x', 1)" in message
    assert "(1, 2)" in message

    with pytest.raises(TypeError) as excinfo:
        list(sort(table, sort_specs=specs, buffersize=1))
    message = str(excinfo.value)
    assert "field 'value'" in message
    assert "('x', 1)" in message
    assert "(1, 2)" in message


def test_sort_specs_cannot_combine_with_key_or_reverse():
    table = (('foo', 'bar'), (1, 2))
    specs = [SortSpec('foo')]

    with pytest.raises(ArgumentError):
        list(sort(table, key='foo', sort_specs=specs))
    with pytest.raises(ArgumentError):
        list(sort(table, reverse=True, sort_specs=specs))


def test_sort_specs_accept_alias_and_iterator():
    table = (
        ('priority', 'name'),
        (1, 'B'),
        (2, None),
        (None, 'A'),
    )
    expected = (
        ('priority', 'name'),
        (2, None),
        (1, 'B'),
        (None, 'A'),
    )

    def make_specs():
        yield SortSpec('priority', descending=True)
        yield SortSpec('name', missing_position='first')

    ieq(expected, sort(table, specs=make_specs()))
    with pytest.raises(ArgumentError):
        list(sort(table, key='priority', specs=[SortSpec('priority')]))
    with pytest.raises(ArgumentError):
        list(sort(
            table,
            sort_specs=[SortSpec('priority')],
            specs=[SortSpec('priority')],
        ))


def test_mergesort_sort_specs():
    table1 = (
        ('priority', 'name'),
        (1, 'B'),
        (None, 'A'),
    )
    table2 = (
        ('priority', 'name'),
        (2, None),
        (1, 'A'),
    )
    specs = [
        SortSpec('priority', descending=True, missing_position='last'),
        SortSpec('name', missing_position='first'),
    ]
    expectation = (
        ('priority', 'name'),
        (2, None),
        (1, 'A'),
        (1, 'B'),
        (None, 'A'),
    )

    actual = mergesort(table1, table2, sort_specs=specs)
    ieq(expectation, actual)

    presorted1 = sort(table1, sort_specs=specs, buffersize=1)
    presorted2 = sort(table2, sort_specs=specs, buffersize=1)
    actual = mergesort(presorted1, presorted2, presorted=True,
                       sort_specs=specs)
    ieq(expectation, actual)
