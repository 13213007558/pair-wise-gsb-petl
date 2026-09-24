from __future__ import absolute_import, division, print_function

import pytest

from petl import threewaymerge
from petl.errors import ArgumentError, DuplicateKeyError
from petl.test.helpers import ieq


def test_merge_disjoint_changes():
    base = (('id', 'name', 'qty'),
            (1, 'apple', 10),
            (2, 'banana', 20),
            (3, 'cherry', 30))
    # left changes qty of row 1, right changes name of row 1
    left = (('id', 'name', 'qty'),
            (1, 'apple', 11),
            (2, 'banana', 20),
            (3, 'cherry', 30))
    right = (('id', 'name', 'qty'),
             (1, 'apricot', 10),
             (2, 'banana', 20),
             (3, 'cherry', 30))
    merged, conflicts = threewaymerge(base, left, right, key='id')
    expect = (('id', 'name', 'qty'),
              (1, 'apricot', 11),
              (2, 'banana', 20),
              (3, 'cherry', 30))
    ieq(expect, merged)
    ieq(expect, merged)  # check twice
    ieq((('id', 'field', 'base_value', 'left_value', 'right_value',
          'base_row', 'left_row', 'right_row', 'reason'),), conflicts)


def test_merge_identical_changes():
    base = (('id', 'qty'), (1, 10))
    left = (('id', 'qty'), (1, 11))
    right = (('id', 'qty'), (1, 11))
    merged, conflicts = threewaymerge(base, left, right, key='id')
    ieq((('id', 'qty'), (1, 11)), merged)
    ieq((('id', 'field', 'base_value', 'left_value', 'right_value',
          'base_row', 'left_row', 'right_row', 'reason'),), conflicts)


def test_conflict_same_field():
    base = (('id', 'qty'), (1, 10), (2, 20))
    left = (('id', 'qty'), (1, 11), (2, 20))
    right = (('id', 'qty'), (1, 12), (2, 20))
    merged, conflicts = threewaymerge(base, left, right, key='id')
    # conflicting row is not merged
    ieq((('id', 'qty'), (2, 20)), merged)
    expect = (('id', 'field', 'base_value', 'left_value', 'right_value',
               'base_row', 'left_row', 'right_row', 'reason'),
              (1, 'qty', 10, 11, 12, 1, 1, 1, 'both_modified'))
    ieq(expect, conflicts)
    ieq(expect, conflicts)  # check twice


def test_delete_unmodified():
    base = (('id', 'qty'), (1, 10), (2, 20), (3, 30))
    # left deletes row 2, right deletes row 3, both delete row 1... not quite:
    # left deletes 1 and 2, right deletes 1 and 3
    left = (('id', 'qty'), (3, 30))
    right = (('id', 'qty'), (2, 20))
    merged, conflicts = threewaymerge(base, left, right, key='id')
    # row 1 deleted on both sides, rows 2 and 3 deleted where unmodified
    ieq((('id', 'qty'),), merged)
    ieq((('id', 'field', 'base_value', 'left_value', 'right_value',
          'base_row', 'left_row', 'right_row', 'reason'),), conflicts)


def test_delete_vs_modify():
    base = (('id', 'qty'), (1, 10), (2, 20))
    # left deletes row 1, right modifies it
    left = (('id', 'qty'), (2, 20))
    right = (('id', 'qty'), (1, 15), (2, 20))
    merged, conflicts = threewaymerge(base, left, right, key='id')
    ieq((('id', 'qty'), (2, 20)), merged)
    expect = (('id', 'field', 'base_value', 'left_value', 'right_value',
               'base_row', 'left_row', 'right_row', 'reason'),
              (1, 'qty', 10, None, 15, 1, None, 1, 'delete_vs_modify'))
    ieq(expect, conflicts)


def test_added():
    base = (('id', 'qty'), (1, 10))
    # left adds row 2, both add identical row 3
    left = (('id', 'qty'), (1, 10), (2, 20), (3, 30))
    right = (('id', 'qty'), (1, 10), (3, 30))
    merged, conflicts = threewaymerge(base, left, right, key='id')
    expect = (('id', 'qty'), (1, 10), (2, 20), (3, 30))
    ieq(expect, merged)
    ieq((('id', 'field', 'base_value', 'left_value', 'right_value',
          'base_row', 'left_row', 'right_row', 'reason'),), conflicts)


def test_added_both_different():
    base = (('id', 'qty'), (1, 10))
    # both sides add row 2 with different values
    left = (('id', 'qty'), (1, 10), (2, 20))
    right = (('id', 'qty'), (1, 10), (2, 21))
    merged, conflicts = threewaymerge(base, left, right, key='id')
    ieq((('id', 'qty'), (1, 10)), merged)
    expect = (('id', 'field', 'base_value', 'left_value', 'right_value',
               'base_row', 'left_row', 'right_row', 'reason'),
              (2, 'qty', None, 20, 21, None, 2, 2, 'both_added'))
    ieq(expect, conflicts)


def test_field_order_differs():
    base = (('id', 'name', 'qty'), (1, 'apple', 10))
    left = (('qty', 'id', 'name'), (11, 1, 'apple'))
    right = (('name', 'qty', 'id'), ('apricot', 10, 1))
    merged, conflicts = threewaymerge(base, left, right, key='id')
    ieq((('id', 'name', 'qty'), (1, 'apricot', 11)), merged)
    ieq((('id', 'field', 'base_value', 'left_value', 'right_value',
          'base_row', 'left_row', 'right_row', 'reason'),), conflicts)


def test_missing_column_is_not_none():
    # base has a column with a None value, left drops the column entirely,
    # right sets it - all three states must be distinguished
    base = (('id', 'qty'), (1, None))
    left = (('id',), (1,))
    right = (('id', 'qty'), (1, 5))
    merged, conflicts = threewaymerge(base, left, right, key='id')
    # both sides changed the field differently (drop vs set), so conflict
    ieq((('id', 'qty'),), merged)
    expect = (('id', 'field', 'base_value', 'left_value', 'right_value',
               'base_row', 'left_row', 'right_row', 'reason'),
              (1, 'qty', None, None, 5, 1, 1, 1, 'both_modified'))
    ieq(expect, conflicts)


def test_missing_column_onesided():
    # left drops a column, right leaves it alone - the drop is merged
    base = (('id', 'qty'), (1, 10))
    left = (('id',), (1,))
    right = (('id', 'qty'), (1, 10))
    merged, conflicts = threewaymerge(base, left, right, key='id')
    ieq((('id', 'qty'), (1, None)), merged)
    ieq((('id', 'field', 'base_value', 'left_value', 'right_value',
          'base_row', 'left_row', 'right_row', 'reason'),), conflicts)


def test_new_column_added():
    # left adds a new column, it appears in the merged header
    base = (('id', 'qty'), (1, 10))
    left = (('id', 'qty', 'price'), (1, 10, 100))
    right = (('id', 'qty'), (1, 10))
    merged, conflicts = threewaymerge(base, left, right, key='id')
    ieq((('id', 'qty', 'price'), (1, 10, 100)), merged)


def test_compound_key():
    base = (('id', 'sub', 'qty'), (1, 'a', 10), (1, 'b', 20))
    left = (('id', 'sub', 'qty'), (1, 'a', 11), (1, 'b', 20))
    right = (('id', 'sub', 'qty'), (1, 'a', 10), (1, 'b', 21))
    merged, conflicts = threewaymerge(base, left, right, key=('id', 'sub'))
    expect = (('id', 'sub', 'qty'), (1, 'a', 11), (1, 'b', 21))
    ieq(expect, merged)


def test_duplicate_keys_rejected():
    base = (('id', 'qty'), (1, 10), (2, 20), (2, 21), (3, 30))
    left = (('id', 'qty'), (1, 10))
    right = (('id', 'qty'), (1, 10))
    merged, conflicts = threewaymerge(base, left, right, key='id')
    with pytest.raises(DuplicateKeyError) as excinfo:
        list(merged)
    assert excinfo.value.key == 2
    # all offending rows are located
    assert 'base table rows: [2, 3]' in str(excinfo.value)


def test_duplicate_keys_rejected_left():
    base = (('id', 'qty'), (1, 10))
    left = (('id', 'qty'), (1, 10), (1, 11))
    right = (('id', 'qty'), (1, 10))
    merged, conflicts = threewaymerge(base, left, right, key='id')
    with pytest.raises(DuplicateKeyError) as excinfo:
        list(conflicts)
    assert 'left table rows: [1, 2]' in str(excinfo.value)


def test_missing_key_field():
    base = (('id', 'qty'), (1, 10))
    left = (('qty',), (10,))
    right = (('id', 'qty'), (1, 10))
    merged, conflicts = threewaymerge(base, left, right, key='id')
    with pytest.raises(ArgumentError):
        list(merged)


def test_external_sort_stability():
    # force external sorting with a tiny buffersize, results must be
    # identical to in-memory sorting and stable across iterations
    n = 30
    base = [('id', 'qty', 'name')]
    left = [('id', 'qty', 'name')]
    right = [('id', 'qty', 'name')]
    # reverse order so sorting actually has to do something
    for i in range(n, 0, -1):
        base.append((i, i * 10, 'n%s' % i))
        left.append((i, i * 10 + (1 if i % 3 == 0 else 0), 'n%s' % i))
        right.append((i, i * 10 + (2 if i % 5 == 0 else 0), 'n%s' % i))
    expect_merged = [('id', 'qty', 'name')]
    expect_conflicts = [('id', 'field', 'base_value', 'left_value',
                         'right_value', 'base_row', 'left_row', 'right_row',
                         'reason')]
    for i in range(1, n + 1):
        lch = i % 3 == 0
        rch = i % 5 == 0
        if lch and rch:
            expect_conflicts.append(
                (i, 'qty', i * 10, i * 10 + 1, i * 10 + 2,
                 n - i + 1, n - i + 1, n - i + 1, 'both_modified'))
        elif lch:
            expect_merged.append((i, i * 10 + 1, 'n%s' % i))
        elif rch:
            expect_merged.append((i, i * 10 + 2, 'n%s' % i))
        else:
            expect_merged.append((i, i * 10, 'n%s' % i))
    expect_merged = tuple(map(tuple, expect_merged))
    expect_conflicts = tuple(map(tuple, expect_conflicts))

    for buffersize in (None, 1, 4):
        merged, conflicts = threewaymerge(base, left, right, key='id',
                                          buffersize=buffersize)
        ieq(expect_merged, merged)
        ieq(expect_merged, merged)  # check twice
        ieq(expect_conflicts, conflicts)
        ieq(expect_conflicts, conflicts)  # check twice
