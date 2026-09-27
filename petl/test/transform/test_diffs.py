from __future__ import absolute_import, print_function, division


import pytest

from petl.test.helpers import ieq
from petl.transform.diffs import tablediff, applypatch, TablePatch, \
    PatchConflict


def test_tablediff_unique_key_update():
    source = (('id', 'name', 'qty'),
              (1, 'apples', 3),
              (2, 'bananas', 7),
              (3, 'pears', 1))
    target = (('id', 'name', 'qty'),
              (1, 'apples', 4),
              (3, 'pears', 1),
              (4, 'figs', 9))
    patch = tablediff(source, target, key='id')
    assert isinstance(patch, TablePatch)
    assert patch.key == ('id',)
    assert patch.ops == [
        ('update', (1,), {'id': 1, 'name': 'apples', 'qty': 3},
         {'id': 1, 'name': 'apples', 'qty': 4}),
        ('delete', {'id': 2, 'name': 'bananas', 'qty': 7}, 1),
        ('add', {'id': 4, 'name': 'figs', 'qty': 9}, 1),
    ]
    result = applypatch(source, patch)
    ieq(target, result)
    ieq(target, result)  # second pass, e.g. to check repeatable


def test_tablediff_composite_key():
    source = (('a', 'b', 'v'),
              ('x', 1, 10),
              ('x', 2, 20))
    target = (('a', 'b', 'v'),
              ('x', 1, 10),
              ('x', 2, 99))
    patch = tablediff(source, target, key=('a', 'b'))
    assert patch.key == ('a', 'b')
    assert patch.ops == [
        ('update', ('x', 2), {'a': 'x', 'b': 2, 'v': 20},
         {'a': 'x', 'b': 2, 'v': 99}),
    ]
    ieq(target, applypatch(source, patch))


def test_tablediff_duplicate_keys_uses_multiset():
    # same key on multiple rows; must not pair rows into updates
    source = (('id', 'v'),
              (1, 'a'),
              (1, 'b'),
              (1, 'b'))
    target = (('id', 'v'),
              (1, 'b'),
              (1, 'c'),
              (1, 'c'))
    patch = tablediff(source, target, key='id')
    assert ('delete', {'id': 1, 'v': 'a'}, 1) in patch.ops
    assert ('delete', {'id': 1, 'v': 'b'}, 1) in patch.ops
    assert ('add', {'id': 1, 'v': 'c'}, 2) in patch.ops
    assert not any(op[0] == 'update' for op in patch.ops)
    ieq(target, applypatch(source, patch))


def test_tablediff_field_order_independent():
    source = (('id', 'name', 'qty'),
              (1, 'apples', 3))
    target = (('qty', 'id', 'name'),
              (4, 1, 'apples'))
    patch = tablediff(source, target, key='id')
    assert patch.ops == [
        ('update', (1,), {'id': 1, 'name': 'apples', 'qty': 3},
         {'qty': 4, 'id': 1, 'name': 'apples'}),
    ]
    result = applypatch(source, patch)
    # output follows the target field order
    ieq((('qty', 'id', 'name'),
         (4, 1, 'apples')), result)


def test_tablediff_missing_column_is_not_none():
    # a missing column is not the same as a column with value None
    source = (('id', 'v'),
              (1, 'a'))
    target = (('id', 'v', 'w'),
              (1, 'a', None))
    patch = tablediff(source, target, key='id')
    assert patch.added_fields == ('w',)
    assert patch.ops == [
        ('update', (1,), {'id': 1, 'v': 'a'},
         {'id': 1, 'v': 'a', 'w': None}),
    ]
    ieq(target, applypatch(source, patch))


def test_tablediff_added_and_removed_columns():
    source = (('id', 'v', 'old'),
              (1, 'a', 'x'))
    target = (('id', 'v', 'new'),
              (1, 'a', 'y'))
    patch = tablediff(source, target, key='id')
    assert patch.added_fields == ('new',)
    assert patch.removed_fields == ('old',)
    assert patch.ops == [
        ('update', (1,), {'id': 1, 'v': 'a', 'old': 'x'},
         {'id': 1, 'v': 'a', 'new': 'y'}),
    ]
    ieq(target, applypatch(source, patch))


def test_tablediff_added_columns_duplicate_key():
    source = (('id', 'v'),
              (1, 'a'),
              (1, 'b'))
    target = (('id', 'v', 'w'),
              (1, 'a', 5),
              (1, 'b', 6))
    patch = tablediff(source, target, key='id')
    assert patch.added_fields == ('w',)
    assert ('delete', {'id': 1, 'v': 'a'}, 1) in patch.ops
    assert ('delete', {'id': 1, 'v': 'b'}, 1) in patch.ops
    assert ('add', {'id': 1, 'v': 'a', 'w': 5}, 1) in patch.ops
    assert ('add', {'id': 1, 'v': 'b', 'w': 6}, 1) in patch.ops
    ieq(target, applypatch(source, patch))


def test_tablediff_empty():
    source = (('id', 'v'),
              (1, 'a'),
              (2, 'b'))
    patch = tablediff(source, source, key='id')
    assert patch.ops == []
    assert len(patch) == 0
    ieq(source, applypatch(source, patch))


def test_tablediff_empty_tables():
    source = (('id', 'v'),)
    target = (('id', 'v'),)
    patch = tablediff(source, target, key='id')
    assert patch.ops == []
    ieq(target, applypatch(source, patch))


def test_tablediff_single_pass_inputs():
    # source and target may be readable only once
    source = iter([('id', 'v'), (1, 'a'), (2, 'b')])
    target = iter([('id', 'v'), (2, 'b'), (3, 'c')])
    patch = tablediff(source, target, key='id')
    assert ('delete', {'id': 1, 'v': 'a'}, 1) in patch.ops
    assert ('add', {'id': 3, 'v': 'c'}, 1) in patch.ops
    result = applypatch(iter([('id', 'v'), (1, 'a'), (2, 'b')]), patch)
    ieq((('id', 'v'), (2, 'b'), (3, 'c')), result)


def test_tablediff_external_sort():
    # small buffersize forces the external (file based) sort path
    source = [('id', 'v')] + [(i, str(i)) for i in range(50, 0, -1)]
    target = [('id', 'v')] + [(i, str(i)) for i in range(60, 10, -1)]
    patch = tablediff(source, target, key='id', buffersize=7)
    assert ('delete', {'id': 1, 'v': '1'}, 1) in patch.ops
    assert ('add', {'id': 60, 'v': '60'}, 1) in patch.ops
    result = applypatch(source, patch)
    ieq(sorted(target[1:]), sorted(result[1:]))


def test_applypatch_conflict_value_changed():
    source = (('id', 'qty'),
              (1, 3),
              (2, 7))
    target = (('id', 'qty'),
              (1, 4),
              (2, 7))
    patch = tablediff(source, target, key='id')
    # someone changes a value after the patch was generated
    changed = (('id', 'qty'),
               (1, 99),
               (2, 7))
    with pytest.raises(PatchConflict) as excinfo:
        list(applypatch(changed, patch))
    assert "row with key (1,) has changed" in str(excinfo.value)
    assert "'qty': expected 3, found 99" in str(excinfo.value)


def test_applypatch_conflict_row_removed():
    source = (('id', 'qty'),
              (1, 3),
              (2, 7))
    target = (('id', 'qty'),
              (1, 4),
              (2, 7))
    patch = tablediff(source, target, key='id')
    changed = (('id', 'qty'),
               (2, 7))
    with pytest.raises(PatchConflict) as excinfo:
        list(applypatch(changed, patch))
    assert 'no row found with key (1,)' in str(excinfo.value)


def test_applypatch_conflict_multiplicity():
    source = (('id', 'v'),
              (1, 'a'),
              (1, 'a'),
              (2, 'b'))
    target = (('id', 'v'),
              (2, 'b'),)
    patch = tablediff(source, target, key='id')
    assert ('delete', {'id': 1, 'v': 'a'}, 2) in patch.ops
    # someone removes one of the copies after the patch was generated
    changed = (('id', 'v'),
               (1, 'a'),
               (2, 'b'))
    with pytest.raises(PatchConflict) as excinfo:
        list(applypatch(changed, patch))
    assert 'expected 2 copies' in str(excinfo.value)
    assert 'found 1' in str(excinfo.value)


def test_applypatch_conflict_fields_changed():
    source = (('id', 'v'),
              (1, 'a'))
    target = (('id', 'v'),
              (1, 'b'))
    patch = tablediff(source, target, key='id')
    changed = (('id', 'v', 'w'),
               (1, 'a', 5))
    with pytest.raises(PatchConflict) as excinfo:
        list(applypatch(changed, patch))
    assert 'fields added since diff' in str(excinfo.value)


def test_applypatch_preserves_concurrent_adds():
    source = (('id', 'qty'),
              (1, 3),
              (2, 7))
    target = (('id', 'qty'),
              (1, 4),
              (2, 7))
    patch = tablediff(source, target, key='id')
    # someone appends a new row after the patch was generated
    changed = (('id', 'qty'),
               (1, 3),
               (2, 7),
               (3, 1))
    result = applypatch(changed, patch)
    ieq((('id', 'qty'),
         (1, 4),
         (2, 7),
         (3, 1)), result)


def test_applypatch_roundtrip_restores_multiset():
    source = (('id', 'v'),
              (1, 'a'),
              (1, 'a'),
              (2, 'b'),
              (3, 'c'))
    target = (('id', 'v'),
              (1, 'a'),
              (2, 'b'),
              (2, 'b'),
              (4, 'd'))
    patch = tablediff(source, target, key='id')
    result = applypatch(source, patch)
    ieq(sorted(target[1:]), sorted(list(result)[1:]))
