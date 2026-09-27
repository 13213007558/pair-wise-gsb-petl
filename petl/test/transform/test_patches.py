from __future__ import absolute_import, print_function, division

from collections import Counter

import pytest

import petl as etl
from petl.comparison import MISSING
from petl.errors import PatchConflict
from petl.test.helpers import ieq


class OneShotTable(object):

    def __init__(self, rows):
        self.rows = iter(rows)
        self.iterations = 0

    def __iter__(self):
        self.iterations += 1
        if self.iterations > 1:
            raise AssertionError('table was iterated more than once')
        return self.rows


def _rows(table):
    return list(table)[1:]


def test_tablediff_unique_key_update():
    source = [['id', 'name'], [1, 'a'], [2, 'b']]
    target = [['name', 'id'], ['a', 1], ['c', 2]]

    patch = etl.tablediff(source, target, 'id')
    operations = _rows(patch.operations)

    assert operations == [
        ('keep', (1, 'a'), (1, 'a'), 1, {}),
        ('update', (2, 'b'), (2, 'c'), 1, {'name': ('b', 'c')}),
    ]
    ieq(target, etl.applytablediff(patch, source))


def test_tablediff_duplicate_key_uses_full_row_multiset():
    source = [['id', 'value'], [1, 'a'], [1, 'b'], [2, 'x']]
    target = [['id', 'value'], [1, 'a'], [1, 'c']]

    patch = etl.tablediff(source, target, 'id')
    operations = _rows(patch.operations)

    assert ('update',) not in {operation[0] for operation in operations}
    assert sorted(operation[:4] for operation in operations) == sorted([
        ('keep', (1, 'a'), (1, 'a'), 1),
        ('delete', (1, 'b'), None, 1),
        ('insert', None, (1, 'c'), 1),
        ('delete', (2, 'x'), None, 1),
    ])
    assert Counter(map(tuple, _rows(etl.applytablediff(patch, source)))) == \
        Counter(map(tuple, _rows(target)))


def test_tablediff_repeated_identical_rows_uses_multiplicity():
    source = [['id', 'value'], [1, 'a'], [1, 'a'], [1, 'b']]
    target = [['id', 'value'], [1, 'a']]

    patch = etl.tablediff(source, target, 'id')
    assert sorted(operation[:4]
                  for operation in _rows(patch.operations)) == sorted([
        ('keep', (1, 'a'), (1, 'a'), 1),
        ('delete', (1, 'a'), None, 1),
        ('delete', (1, 'b'), None, 1),
    ])
    assert Counter(map(tuple, _rows(etl.applytablediff(patch, source)))) == \
        Counter(map(tuple, _rows(target)))


def test_tablediff_duplicate_runs_interleaved_after_external_sort():
    source = [['id', 'value'], [1, 'a'], [1, 'b'], [1, 'a']]
    target = [['id', 'value'], [1, 'a'], [1, 'c']]

    patch = etl.tablediff(source, target, 'id', buffersize=2)
    operations = _rows(patch.operations)

    assert sorted(operation[:4] for operation in operations) == sorted([
        ('keep', (1, 'a'), (1, 'a'), 1),
        ('delete', (1, 'a'), None, 1),
        ('delete', (1, 'b'), None, 1),
        ('insert', None, (1, 'c'), 1),
    ])
    assert Counter(map(tuple, _rows(etl.applytablediff(patch, source)))) == \
        Counter(map(tuple, _rows(target)))


def test_tablediff_reports_added_and_removed_columns():
    source = [['id', 'old'], [1, 'a'], [2, None]]
    target = [['id', 'new'], [1, 'b'], [2, None]]

    patch = etl.tablediff(source, target, 'id')

    assert patch.fields_removed == ('old',)
    assert patch.fields_added == ('new',)
    result = _rows(etl.applytablediff(patch, source))
    assert Counter(result) == Counter([(1, 'b'), (2, None)])


def test_tablediff_distinguishes_missing_cell_from_none():
    source = [['id', 'old', 'extra'], [1, None, 'x']]
    target = [['id', 'old'], [1]]

    patch = etl.tablediff(source, target, 'id')
    update = _rows(patch.operations)[0]

    assert update[0] == 'update'
    assert update[4] == {
        'old': (None, MISSING),
        'extra': ('x', MISSING),
    }
    assert _rows(etl.applytablediff(patch, source)) == [(1,)]


def test_applytablediff_conflict_reports_changed_row_and_field():
    source = [['id', 'name'], [1, 'a'], [2, 'b']]
    target = [['id', 'name'], [1, 'a'], [2, 'c']]
    changed = [['id', 'name'], [1, 'a'], [2, 'changed']]
    patch = etl.tablediff(source, target, 'id')

    with pytest.raises(PatchConflict) as excinfo:
        list(etl.applytablediff(patch, changed))

    error = excinfo.value
    assert error.operation == 'update'
    assert error.expected == (2, 'b')
    assert error.actual == (2, 'changed')
    assert "('name', 'b', 'changed')" in str(error)


def test_applytablediff_conflict_on_duplicate_multiset():
    source = [['id', 'value'], [1, 'a'], [1, 'b']]
    target = [['id', 'value'], [1, 'a'], [1, 'c']]
    changed = [['id', 'value'], [1, 'a'], [1, 'changed']]
    patch = etl.tablediff(source, target, 'id')

    with pytest.raises(PatchConflict) as excinfo:
        list(etl.applytablediff(patch, changed))

    error = excinfo.value
    assert error.operation == 'delete'
    assert error.expected == (1, 'b')
    assert error.actual == (1, 'changed')


def test_applytablediff_conflict_on_unexpected_row():
    source = [['id', 'name'], [1, 'a']]
    target = [['id', 'name']]
    changed = [['id', 'name'], [1, 'a'], [2, 'extra']]
    patch = etl.tablediff(source, target, 'id')

    with pytest.raises(PatchConflict) as excinfo:
        list(etl.applytablediff(patch, changed))

    assert excinfo.value.operation == 'unexpected'
    assert excinfo.value.actual == (2, 'extra')


def test_applytablediff_conflict_on_changed_schema():
    source = [['id', 'name'], [1, 'a']]
    target = [['id', 'name'], [1, 'b']]
    changed = [['id', 'other'], [1, 'a']]
    patch = etl.tablediff(source, target, 'id')

    with pytest.raises(PatchConflict):
        list(etl.applytablediff(patch, changed))


def test_tablediff_one_pass_and_external_sort():
    source = OneShotTable((('id', 'value'), (3, 'c'), (1, 'a'), (2, 'b'),
                           (1, 'a')))
    target = OneShotTable((('id', 'value'), (1, 'a'), (1, 'z'), (3, 'c')))

    patch = etl.tablediff(source, target, 'id', buffersize=2)
    result = list(etl.applytablediff(patch, OneShotTable((
        ('id', 'value'), (3, 'c'), (1, 'a'), (2, 'b'), (1, 'a'))),
        buffersize=2))

    assert Counter(result[1:]) == Counter(
        [(1, 'a'), (1, 'z'), (3, 'c')])
