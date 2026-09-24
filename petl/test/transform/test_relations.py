# -*- coding: utf-8 -*-
from __future__ import absolute_import, print_function, division


import logging

import pytest

import petl as etl
from petl.transform.relations import validate_relations
from petl.test.helpers import ieq
from petl.errors import ArgumentError, FieldSelectionError


logger = logging.getLogger(__name__)
debug = logger.debug


HEADER = ('name', 'table', 'row', 'fields', 'value', 'error',
          'ref_table', 'ref_fields')


def test_unique_composite_key():
    # third table holding duplicate compound keys and nulls
    events = (('day', 'slot', 'room'),
              ('mon', 1, 'a'),
              ('mon', 1, 'b'),
              ('tue', 2, 'c'),
              ('tue', 2, 'd'),
              ('wed', None, 'e'),
              (None, 3, 'f'))
    constraints = [
        dict(name='uq_events', table='events', fields=('day', 'slot')),
    ]
    expect = (HEADER,
              ('uq_events', 'events', 1, ('day', 'slot'), ('mon', 1),
               'UniqueViolation', None, None),
              ('uq_events', 'events', 2, ('day', 'slot'), ('mon', 1),
               'UniqueViolation', None, None),
              ('uq_events', 'events', 3, ('day', 'slot'), ('tue', 2),
               'UniqueViolation', None, None),
              ('uq_events', 'events', 4, ('day', 'slot'), ('tue', 2),
               'UniqueViolation', None, None))
    actual = validate_relations({'events': events}, constraints)
    debug(actual)
    ieq(expect, actual)
    ieq(expect, actual)


def test_foreign_key_composite():
    schedule = (('day', 'slot'),
                ('mon', 1),
                ('tue', 2),
                ('thu', 4))
    events = (('day', 'slot', 'room'),
              ('mon', 1, 'a'),
              ('fri', 5, 'b'),
              ('tue', 2, 'c'),
              ('sat', 6, 'd'))
    constraints = [
        dict(name='fk_events_schedule', table='events',
             fields=('day', 'slot'), references='schedule',
             ref_fields=('day', 'slot')),
    ]
    expect = (HEADER,
              ('fk_events_schedule', 'events', 2, ('day', 'slot'),
               ('fri', 5), 'ForeignKeyViolation', 'schedule',
               ('day', 'slot')),
              ('fk_events_schedule', 'events', 4, ('day', 'slot'),
               ('sat', 6), 'ForeignKeyViolation', 'schedule',
               ('day', 'slot')))
    actual = validate_relations({'events': events, 'schedule': schedule},
                                constraints)
    debug(actual)
    ieq(expect, actual)
    ieq(expect, actual)


def test_mutual_references():
    # two tables referencing each other
    parents = (('pid', 'child_id'),
               (1, 10),
               (2, 20),
               (3, 99))
    children = (('cid', 'parent_id'),
                (10, 1),
                (20, 2),
                (30, 4))
    constraints = [
        dict(name='fk_parents_child', table='parents', fields='child_id',
             references='children', ref_fields='cid'),
        dict(name='fk_children_parent', table='children',
             fields='parent_id', references='parents', ref_fields='pid'),
    ]
    expect = (HEADER,
              ('fk_parents_child', 'parents', 3, ('child_id',), (99,),
               'ForeignKeyViolation', 'children', ('cid',)),
              ('fk_children_parent', 'children', 3, ('parent_id',), (4,),
               'ForeignKeyViolation', 'parents', ('pid',)))
    actual = validate_relations({'parents': parents, 'children': children},
                                constraints)
    debug(actual)
    ieq(expect, actual)
    ieq(expect, actual)


def test_foreign_key_nulls_ignore_by_default():
    schedule = (('day', 'slot'),
                ('mon', 1),
                ('tue', 2))
    events = (('day', 'slot', 'room'),
              ('mon', 1, 'a'),
              ('wed', None, 'e'),
              (None, 3, 'f'))
    constraints = [
        dict(name='fk_events_schedule', table='events',
             fields=('day', 'slot'), references='schedule',
             ref_fields=('day', 'slot')),
    ]
    expect = (HEADER,)
    actual = validate_relations({'events': events, 'schedule': schedule},
                                constraints)
    debug(actual)
    ieq(expect, actual)
    ieq(expect, actual)


def test_foreign_key_nulls_report():
    schedule = (('day', 'slot'),
                ('mon', 1),
                ('tue', 2))
    events = (('day', 'slot', 'room'),
              ('mon', 1, 'a'),
              ('wed', None, 'e'),
              (None, 3, 'f'))
    constraints = [
        dict(name='fk_events_schedule', table='events',
             fields=('day', 'slot'), references='schedule',
             ref_fields=('day', 'slot'), nulls='report'),
    ]
    # null keys sort before everything else, so (None, 3) comes first
    expect = (HEADER,
              ('fk_events_schedule', 'events', 3, ('day', 'slot'),
               (None, 3), 'NullKeyViolation', 'schedule', ('day', 'slot')),
              ('fk_events_schedule', 'events', 2, ('day', 'slot'),
               ('wed', None), 'NullKeyViolation', 'schedule',
               ('day', 'slot')))
    actual = validate_relations({'events': events, 'schedule': schedule},
                                constraints)
    debug(actual)
    ieq(expect, actual)
    ieq(expect, actual)


def test_foreign_key_target_not_unique():
    source = (('id', 'code'),
              (1, 'x'),
              (2, 'y'),
              (3, 'z'))
    target = (('code', 'v'),
              ('x', 1),
              ('x', 2),
              ('y', 3))
    constraints = [
        dict(name='fk_source_target', table='source', fields='code',
             references='target', ref_fields='code'),
    ]
    # the duplicated target key 'x' is reported as a uniqueness problem on
    # each row holding it, not silently resolved to the first row
    expect = (HEADER,
              ('fk_source_target', 'target', 1, ('code',), ('x',),
               'UniqueViolation', 'source', ('code',)),
              ('fk_source_target', 'target', 2, ('code',), ('x',),
               'UniqueViolation', 'source', ('code',)),
              ('fk_source_target', 'source', 3, ('code',), ('z',),
               'ForeignKeyViolation', 'target', ('code',)))
    actual = validate_relations({'source': source, 'target': target},
                                constraints)
    debug(actual)
    ieq(expect, actual)
    ieq(expect, actual)


def test_default_ref_fields():
    left = (('key', 'v'), (1, 'a'), (2, 'b'))
    right = (('key', 'w'), (1, 'x'))
    constraints = [
        dict(name='fk_left_right', table='left', fields='key',
             references='right'),
    ]
    expect = (HEADER,
              ('fk_left_right', 'left', 2, ('key',), (2,),
               'ForeignKeyViolation', 'right', ('key',)))
    actual = validate_relations({'left': left, 'right': right}, constraints)
    debug(actual)
    ieq(expect, actual)
    ieq(expect, actual)


def test_tables_as_pairs():
    left = (('key',), (1,), (2,))
    right = (('key',), (2,),)
    constraints = [
        dict(name='fk', table='left', fields='key', references='right'),
    ]
    expect = (HEADER,
              ('fk', 'left', 1, ('key',), (1,), 'ForeignKeyViolation',
               'right', ('key',)))
    actual = validate_relations([('left', left), ('right', right)],
                                constraints)
    debug(actual)
    ieq(expect, actual)


class OneShot(object):
    # a table that can be iterated exactly once
    def __init__(self, rows):
        self._rows = rows
        self.iterations = 0

    def __iter__(self):
        self.iterations += 1
        assert self.iterations == 1, 'table consumed more than once'
        return iter(self._rows)


def test_one_shot_iterators_consumed_once():
    # each table is referenced by several constraints but may only be
    # consumed once
    parents = OneShot((('pid', 'child_id'),
                       (1, 10),
                       (2, 20),
                       (3, 99)))
    children = OneShot((('cid', 'parent_id'),
                        (10, 1),
                        (20, 2),
                        (30, 4)))
    constraints = [
        dict(name='pk_parents', table='parents', fields='pid'),
        dict(name='fk_parents_child', table='parents', fields='child_id',
             references='children', ref_fields='cid'),
        dict(name='pk_children', table='children', fields='cid'),
        dict(name='fk_children_parent', table='children',
             fields='parent_id', references='parents', ref_fields='pid'),
    ]
    expect = (HEADER,
              ('fk_parents_child', 'parents', 3, ('child_id',), (99,),
               'ForeignKeyViolation', 'children', ('cid',)),
              ('fk_children_parent', 'children', 3, ('parent_id',), (4,),
               'ForeignKeyViolation', 'parents', ('pid',)))
    actual = validate_relations({'parents': parents, 'children': children},
                                constraints)
    ieq(expect, actual)
    # iterate the result again, served from the key stream caches
    ieq(expect, actual)
    assert parents.iterations == 1
    assert children.iterations == 1


def test_disk_backed_cache(tmp_path):
    # force the sort machinery to spill to temporary chunk files
    events = (('day', 'slot', 'room'),
              ('mon', 1, 'a'),
              ('mon', 1, 'b'),
              ('tue', 2, 'c'),
              ('tue', 2, 'd'),
              ('wed', None, 'e'),
              (None, 3, 'f'))
    schedule = (('day', 'slot'),
                ('mon', 1),
                ('tue', 2))
    constraints = [
        dict(name='uq_events', table='events', fields=('day', 'slot')),
        dict(name='fk_events_schedule', table='events',
             fields=('day', 'slot'), references='schedule',
             ref_fields=('day', 'slot'), nulls='report'),
    ]
    expect = (HEADER,
              ('uq_events', 'events', 1, ('day', 'slot'), ('mon', 1),
               'UniqueViolation', None, None),
              ('uq_events', 'events', 2, ('day', 'slot'), ('mon', 1),
               'UniqueViolation', None, None),
              ('uq_events', 'events', 3, ('day', 'slot'), ('tue', 2),
               'UniqueViolation', None, None),
              ('uq_events', 'events', 4, ('day', 'slot'), ('tue', 2),
               'UniqueViolation', None, None),
              ('fk_events_schedule', 'events', 6, ('day', 'slot'),
               (None, 3), 'NullKeyViolation', 'schedule', ('day', 'slot')),
              ('fk_events_schedule', 'events', 5, ('day', 'slot'),
               ('wed', None), 'NullKeyViolation', 'schedule',
               ('day', 'slot')))
    actual = validate_relations({'events': events, 'schedule': schedule},
                                constraints, buffersize=2,
                                tempdir=str(tmp_path))
    debug(actual)
    ieq(expect, actual)
    ieq(expect, actual)


def test_source_tables_not_modified():
    events = [('day', 'slot', 'room'),
              ['mon', 1, 'a'],
              ['mon', 1, 'b']]
    schedule = [('day', 'slot'),
                ['mon', 1]]
    snapshot_events = [list(row) for row in events]
    snapshot_schedule = [list(row) for row in schedule]
    constraints = [
        dict(name='uq_events', table='events', fields=('day', 'slot')),
        dict(name='fk_events_schedule', table='events',
             fields=('day', 'slot'), references='schedule',
             ref_fields=('day', 'slot')),
    ]
    problems = validate_relations({'events': events,
                                   'schedule': schedule}, constraints)
    assert etl.nrows(problems) == 2
    assert [list(row) for row in events] == snapshot_events
    assert [list(row) for row in schedule] == snapshot_schedule


def test_unknown_table():
    with pytest.raises(ArgumentError):
        validate_relations({'a': (('f',), (1,))},
                           [dict(name='c', table='b', fields='f')])


def test_unknown_references():
    with pytest.raises(ArgumentError):
        validate_relations({'a': (('f',), (1,))},
                           [dict(name='c', table='a', fields='f',
                                 references='b')])


def test_invalid_nulls_policy():
    with pytest.raises(ArgumentError):
        validate_relations(
            {'a': (('f',), (1,)), 'b': (('f',), (1,))},
            [dict(name='c', table='a', fields='f', references='b',
                  nulls='bogus')])


def test_mismatched_key_length():
    with pytest.raises(ArgumentError):
        validate_relations(
            {'a': (('f', 'g'), (1, 2)), 'b': (('f',), (1,))},
            [dict(name='c', table='a', fields=('f', 'g'), references='b',
                  ref_fields='f')])


def test_missing_field():
    table = (('foo', 'bar'), (1, 'a'))
    constraints = [dict(name='uq', table='t', fields='missing')]
    actual = validate_relations({'t': table}, constraints)
    with pytest.raises(FieldSelectionError):
        debug(actual)


def test_empty_tables():
    constraints = [
        dict(name='fk', table='a', fields='f', references='b'),
    ]
    actual = validate_relations({'a': (('f',),), 'b': (('f',),)},
                                constraints)
    expect = (HEADER,)
    ieq(expect, actual)
