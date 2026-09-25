# -*- coding: utf-8 -*-
from __future__ import absolute_import, print_function, division

from collections import OrderedDict

import pytest

from petl.test.helpers import ieq
from petl import flattenrecords, MISSING, RecordSchemaError
from petl.errors import ArgumentError
from petl.io.nested import flatten_record


def test_late_fields_are_discovered():
    records = [OrderedDict([('a', 1)]),
               OrderedDict([('a', 2)]),
               OrderedDict([('a', 3), ('late', 'x')])]
    table = flattenrecords(records)
    expected = [(('a',), ('late',)),
                (1, MISSING),
                (2, MISSING),
                (3, 'x')]
    ieq(expected, table)
    ieq(expected, table)


def test_header_order_is_first_discovery():
    records = [OrderedDict([('b', 1), ('a', 2)]),
               OrderedDict([('c', 3), ('a', 4)])]
    table = flattenrecords(records)
    ieq([(('b',), ('a',), ('c',)),
         (1, 2, MISSING),
         (MISSING, 4, 3)],
        table)


def test_dotted_keys_not_confused_with_nesting():
    records = [{'a.b': 1, 'a': {'b': 2}}]
    table = flattenrecords(records)
    ieq([(('a.b',), ('a', 'b')),
         (1, 2)],
        table)


def test_lists_kept_as_single_value():
    records = [{'wins': [['straight', '7S'], ['one pair', '10H']]},
               {'wins': []}]
    table = flattenrecords(records)
    ieq([(('wins',),),
         ([['straight', '7S'], ['one pair', '10H']],),
         ([],)],
        table)


def test_deep_nesting():
    records = [{'a': {'b': {'c': 1}}}, {'a': {'b': {'c': 2, 'd': 3}}}]
    table = flattenrecords(records)
    ieq([(('a', 'b', 'c'), ('a', 'b', 'd')),
         (1, MISSING),
         (2, 3)],
        table)


def test_missing_marker_is_not_none():
    records = [{'a': None}, {'b': 1}]
    table = flattenrecords(records)
    expect_header = (('a',), ('b',))
    rows = list(table)
    assert rows[0] == expect_header
    # explicit JSON null is preserved as None
    assert rows[1] == (None, MISSING)
    # absent field uses the marker, which is not None
    assert rows[2] == (MISSING, 1)
    assert rows[2][0] is not None
    assert rows[2][0] != None  # noqa: E711
    assert rows[2][0] is MISSING


def test_custom_missing():
    records = [{'a': 1}, {'b': 2}]
    table = flattenrecords(records, missing='')
    ieq([(('a',), ('b',)),
         (1, ''),
         ('', 2)],
        table)


def test_conflict_error_scalar_then_mapping():
    records = [{'a': 1}, {'a': {'b': 2}}]
    table = flattenrecords(records)
    with pytest.raises(RecordSchemaError) as excinfo:
        list(table)
    err = excinfo.value
    assert err.line == 2
    assert err.path == ('a',)
    assert '2' in str(err)
    assert "'a'" in str(err)


def test_conflict_error_mapping_then_scalar():
    records = [{'a': {'b': 2}}, {'x': 1}, {'a': 1}]
    table = flattenrecords(records)
    with pytest.raises(RecordSchemaError) as excinfo:
        list(table)
    err = excinfo.value
    assert err.line == 3
    assert err.path == ('a',)


def test_conflict_error_nested_path():
    records = [{'a': {'b': {'c': 1}}}, {'a': {'b': 5}}]
    table = flattenrecords(records)
    with pytest.raises(RecordSchemaError) as excinfo:
        list(table)
    err = excinfo.value
    assert err.line == 2
    assert err.path == ('a', 'b')


def test_conflict_branch_keeps_both_type_branches():
    records = [OrderedDict([('a', 1)]),
               OrderedDict([('a', OrderedDict([('b', 2)]))]),
               OrderedDict([('a', 3)])]
    table = flattenrecords(records, on_conflict='branch')
    ieq([(('a',), ('a', 'b')),
         (1, MISSING),
         (MISSING, 2),
         (3, MISSING)],
        table)


def test_invalid_on_conflict():
    with pytest.raises(ArgumentError):
        flattenrecords([], on_conflict='ignore')


def test_non_mapping_record_error():
    records = [{'a': 1}, [1, 2, 3]]
    table = flattenrecords(records)
    with pytest.raises(RecordSchemaError) as excinfo:
        list(table)
    err = excinfo.value
    assert err.line == 2
    assert err.path == ()


@pytest.mark.parametrize('kind', ['list', 'iterator', 'generator'])
def test_one_shot_source_consumed_once(kind):
    consumed = []

    def source():
        for record in [{'a': 1}, {'a': 2, 'b': 'x'}, {'a': 3}]:
            consumed.append(record)
            yield record

    if kind == 'list':
        records = [{'a': 1}, {'a': 2, 'b': 'x'}, {'a': 3}]
    elif kind == 'iterator':
        records = iter(source())
    else:
        records = source()
    table = flattenrecords(records)
    expected = [(('a',), ('b',)),
                (1, MISSING),
                (2, 'x'),
                (3, MISSING)]
    ieq(expected, table)
    if kind != 'list':
        n = len(consumed)
        assert n == 3
        # second pass replays the spool without touching the source again
        ieq(expected, table)
        assert len(consumed) == n


def test_bounded_spool_spills_to_file(tmp_path):
    records = ({'a': i, 'b': {'c': str(i)}} for i in range(100))
    table = flattenrecords(records, spool_maxbytes=0,
                           tempdir=str(tmp_path))
    expected = [(('a',), ('b', 'c'))]
    expected += [(i, str(i)) for i in range(100)]
    ieq(expected, table)
    # spilled file is replayable
    ieq(expected, table)


def test_spool_and_memory_give_same_results():
    records = [{'a': i, 'b': [i]} for i in range(50)]
    in_memory = flattenrecords(iter(list(records)), spool_maxbytes=2 ** 20)
    spilled = flattenrecords(iter(list(records)), spool_maxbytes=1)
    ieq(in_memory, spilled)


def test_empty_input():
    table = flattenrecords(iter([]))
    ieq([()], table)
    ieq([()], table)


def test_empty_mapping_contributes_no_fields():
    records = [{'a': {}}, {'a': {'b': 1}}]
    table = flattenrecords(records)
    ieq([(('a', 'b'),),
         (MISSING,),
         (1,)],
        table)


def test_values_passed_through_without_inference():
    records = [{'date': '2020-01-01', 'num': '001', 'qty': '1.5'}]
    table = flattenrecords(records)
    ieq([(('date',), ('num',), ('qty',)),
         ('2020-01-01', '001', '1.5')],
        table)


def test_missing_singleton_survives_pickle():
    from petl.compat import pickle
    assert pickle.loads(pickle.dumps(MISSING)) is MISSING


def test_flatten_record_line_and_path_in_error():
    with pytest.raises(RecordSchemaError) as excinfo:
        flatten_record('oops', 7, (), list(), set(), set(), 'error')
    err = excinfo.value
    assert err.line == 7
    assert err.path == ()
