from __future__ import absolute_import, print_function, division


import logging

import pytest

import petl as etl
from petl.test.helpers import ieq, eq_
from petl.util.vis import lookall
from petl.errors import DuplicateKeyError
from petl.transform.intervals import intervallookup, intervallookupone, \
    facetintervallookup, facetintervallookupone, intervaljoin, \
    intervalleftjoin, intervaljoinvalues, intervalsubtract, \
    collapsedintervals, _Interval, intervalantijoin, INTERVAL_RELATIONS, \
    INVERSE_INTERVAL_RELATIONS


logger = logging.getLogger(__name__)
debug = logger.debug


try:
    import intervaltree # noqa: F401
except ImportError as e:
    pytest.skip('SKIP interval tests: %s' % e, allow_module_level=True)
else:

    def test_intervallookup():

        table = (('start', 'stop', 'value'),
                 (1, 4, 'foo'),
                 (3, 7, 'bar'),
                 (4, 9, 'baz'))

        lkp = intervallookup(table, 'start', 'stop')

        actual = lkp.search(0, 1)
        expect = []
        eq_(expect, actual)

        actual = lkp.search(1, 2)
        expect = [(1, 4, 'foo')]
        eq_(expect, actual)

        actual = lkp.search(2, 4)
        expect = [(1, 4, 'foo'), (3, 7, 'bar')]
        eq_(expect, actual)

        actual = lkp.search(2, 5)
        expect = [(1, 4, 'foo'), (3, 7, 'bar'), (4, 9, 'baz')]
        eq_(expect, actual)

        actual = lkp.search(9, 14)
        expect = []
        eq_(expect, actual)

        actual = lkp.search(19, 140)
        expect = []
        eq_(expect, actual)

        actual = lkp.search(1)
        expect = [(1, 4, 'foo')]
        eq_(expect, actual)

        actual = lkp.search(2)
        expect = [(1, 4, 'foo')]
        eq_(expect, actual)

        actual = lkp.search(4)
        expect = [(3, 7, 'bar'), (4, 9, 'baz')]
        eq_(expect, actual)

        actual = lkp.search(5)
        expect = [(3, 7, 'bar'), (4, 9, 'baz')]
        eq_(expect, actual)

    def test_intervallookup_include_stop():

        table = (('start', 'stop', 'value'),
                 (1, 4, 'foo'),
                 (3, 7, 'bar'),
                 (4, 9, None))

        lkp = intervallookup(table, 'start', 'stop', value='value',
                             include_stop=True)

        actual = lkp.search(0, 1)
        expect = ['foo']
        eq_(expect, actual)

        actual = lkp.search(1, 2)
        expect = ['foo']
        eq_(expect, actual)

        actual = lkp.search(2, 4)
        expect = ['foo', 'bar', None]
        eq_(expect, actual)

        actual = lkp.search(2, 5)
        expect = ['foo', 'bar', None]
        eq_(expect, actual)

        actual = lkp.search(9, 14)
        expect = [None]
        eq_(expect, actual)

        actual = lkp.search(19, 140)
        expect = []
        eq_(expect, actual)

        actual = lkp.search(1)
        expect = ['foo']
        eq_(expect, actual)

        actual = lkp.search(2)
        expect = ['foo']
        eq_(expect, actual)

        actual = lkp.search(4)
        expect = ['foo', 'bar', None]
        eq_(expect, actual)

        actual = lkp.search(5)
        expect = ['bar', None]
        eq_(expect, actual)

    def test_intervallookupone():

        table = (('start', 'stop', 'value'),
                 (1, 4, 'foo'),
                 (3, 7, 'bar'),
                 (4, 9, 'baz'))

        lkp = intervallookupone(table, 'start', 'stop', value='value')

        actual = lkp.search(0, 1)
        expect = None
        eq_(expect, actual)

        actual = lkp.search(1, 2)
        expect = 'foo'
        eq_(expect, actual)

        try:
            lkp.search(2, 4)
        except DuplicateKeyError:
            pass
        else:
            assert False, 'expected error'

        try:
            lkp.search(2, 5)
        except DuplicateKeyError:
            pass
        else:
            assert False, 'expected error'

        try:
            lkp.search(4, 5)
        except DuplicateKeyError:
            pass
        else:
            assert False, 'expected error'

        try:
            lkp.search(5, 7)
        except DuplicateKeyError:
            pass
        else:
            assert False, 'expected error'

        actual = lkp.search(8, 9)
        expect = 'baz'
        eq_(expect, actual)

        actual = lkp.search(9, 14)
        expect = None
        eq_(expect, actual)

        actual = lkp.search(19, 140)
        expect = None
        eq_(expect, actual)

        actual = lkp.search(0)
        expect = None
        eq_(expect, actual)

        actual = lkp.search(1)
        expect = 'foo'
        eq_(expect, actual)

        actual = lkp.search(2)
        expect = 'foo'
        eq_(expect, actual)

        try:
            lkp.search(4)
        except DuplicateKeyError:
            pass
        else:
            assert False, 'expected error'

        try:
            lkp.search(5)
        except DuplicateKeyError:
            pass
        else:
            assert False, 'expected error'

        actual = lkp.search(8)
        expect = 'baz'
        eq_(expect, actual)

    def test_intervallookupone_not_strict():

        table = (('start', 'stop', 'value'),
                 (1, 4, 'foo'),
                 (3, 7, 'bar'),
                 (4, 9, 'baz'))

        lkp = intervallookupone(table, 'start', 'stop', value='value',
                                strict=False)

        actual = lkp.search(0, 1)
        expect = None
        eq_(expect, actual)

        actual = lkp.search(1, 2)
        expect = 'foo'
        eq_(expect, actual)

        actual = lkp.search(2, 4)
        expect = 'foo'
        eq_(expect, actual)

        actual = lkp.search(2, 5)
        expect = 'foo'
        eq_(expect, actual)

        actual = lkp.search(4, 5)
        expect = 'bar'
        eq_(expect, actual)

        actual = lkp.search(5, 7)
        expect = 'bar'
        eq_(expect, actual)

        actual = lkp.search(8, 9)
        expect = 'baz'
        eq_(expect, actual)

        actual = lkp.search(9, 14)
        expect = None
        eq_(expect, actual)

        actual = lkp.search(19, 140)
        expect = None
        eq_(expect, actual)

        actual = lkp.search(0)
        expect = None
        eq_(expect, actual)

        actual = lkp.search(1)
        expect = 'foo'
        eq_(expect, actual)

        actual = lkp.search(2)
        expect = 'foo'
        eq_(expect, actual)

        actual = lkp.search(4)
        expect = 'bar'
        eq_(expect, actual)

        actual = lkp.search(5)
        expect = 'bar'
        eq_(expect, actual)

        actual = lkp.search(8)
        expect = 'baz'
        eq_(expect, actual)

    def test_facetintervallookup():

        table = (('type', 'start', 'stop', 'value'),
                 ('apple', 1, 4, 'foo'),
                 ('apple', 3, 7, 'bar'),
                 ('orange', 4, 9, 'baz'))

        lkp = facetintervallookup(table, key='type', start='start', stop='stop')

        actual = lkp['apple'].search(0, 1)
        expect = []
        eq_(expect, actual)

        actual = lkp['apple'].search(1, 2)
        expect = [('apple', 1, 4, 'foo')]
        eq_(expect, actual)

        actual = lkp['apple'].search(2, 4)
        expect = [('apple', 1, 4, 'foo'), ('apple', 3, 7, 'bar')]
        eq_(expect, actual)

        actual = lkp['apple'].search(2, 5)
        expect = [('apple', 1, 4, 'foo'), ('apple', 3, 7, 'bar')]
        eq_(expect, actual)

        actual = lkp['orange'].search(2, 5)
        expect = [('orange', 4, 9, 'baz')]
        eq_(expect, actual)

        actual = lkp['orange'].search(9, 14)
        expect = []
        eq_(expect, actual)

        actual = lkp['orange'].search(19, 140)
        expect = []
        eq_(expect, actual)

        actual = lkp['apple'].search(0)
        expect = []
        eq_(expect, actual)

        actual = lkp['apple'].search(1)
        expect = [('apple', 1, 4, 'foo')]
        eq_(expect, actual)

        actual = lkp['apple'].search(2)
        expect = [('apple', 1, 4, 'foo')]
        eq_(expect, actual)

        actual = lkp['apple'].search(4)
        expect = [('apple', 3, 7, 'bar')]
        eq_(expect, actual)

        actual = lkp['apple'].search(5)
        expect = [('apple', 3, 7, 'bar')]
        eq_(expect, actual)

        actual = lkp['orange'].search(5)
        expect = [('orange', 4, 9, 'baz')]
        eq_(expect, actual)

    def test_facetintervallookupone():

        table = (('type', 'start', 'stop', 'value'),
                 ('apple', 1, 4, 'foo'),
                 ('apple', 3, 7, 'bar'),
                 ('orange', 4, 9, 'baz'))

        lkp = facetintervallookupone(table, key='type', start='start',
                                     stop='stop', value='value')

        actual = lkp['apple'].search(0, 1)
        expect = None
        eq_(expect, actual)

        actual = lkp['apple'].search(1, 2)
        expect = 'foo'
        eq_(expect, actual)

        try:
            lkp['apple'].search(2, 4)
        except DuplicateKeyError:
            pass
        else:
            assert False, 'expected error'

        try:
            lkp['apple'].search(2, 5)
        except DuplicateKeyError:
            pass
        else:
            assert False, 'expected error'

        actual = lkp['apple'].search(4, 5)
        expect = 'bar'
        eq_(expect, actual)

        actual = lkp['orange'].search(4, 5)
        expect = 'baz'
        eq_(expect, actual)

        actual = lkp['apple'].search(5, 7)
        expect = 'bar'
        eq_(expect, actual)

        actual = lkp['orange'].search(5, 7)
        expect = 'baz'
        eq_(expect, actual)

        actual = lkp['apple'].search(8, 9)
        expect = None
        eq_(expect, actual)

        actual = lkp['orange'].search(8, 9)
        expect = 'baz'
        eq_(expect, actual)

        actual = lkp['orange'].search(9, 14)
        expect = None
        eq_(expect, actual)

        actual = lkp['orange'].search(19, 140)
        expect = None
        eq_(expect, actual)

        actual = lkp['apple'].search(0)
        expect = None
        eq_(expect, actual)

        actual = lkp['apple'].search(1)
        expect = 'foo'
        eq_(expect, actual)

        actual = lkp['apple'].search(2)
        expect = 'foo'
        eq_(expect, actual)

        actual = lkp['apple'].search(4)
        expect = 'bar'
        eq_(expect, actual)

        actual = lkp['apple'].search(5)
        expect = 'bar'
        eq_(expect, actual)

        actual = lkp['orange'].search(5)
        expect = 'baz'
        eq_(expect, actual)

        actual = lkp['apple'].search(8)
        expect = None
        eq_(expect, actual)

        actual = lkp['orange'].search(8)
        expect = 'baz'
        eq_(expect, actual)

    def test_facetintervallookup_compound():

        table = (('type', 'variety', 'start', 'stop', 'value'),
                 ('apple', 'cox', 1, 4, 'foo'),
                 ('apple', 'fuji', 3, 7, 'bar'),
                 ('orange', 'mandarin', 4, 9, 'baz'))

        lkp = facetintervallookup(table, key=('type', 'variety'), start='start',
                                  stop='stop')

        actual = lkp['apple', 'cox'].search(1, 2)
        expect = [('apple', 'cox', 1, 4, 'foo')]
        eq_(expect, actual)

        actual = lkp['apple', 'cox'].search(2, 4)
        expect = [('apple', 'cox', 1, 4, 'foo')]
        eq_(expect, actual)

    def test_intervaljoin():

        left = (('begin', 'end', 'quux'),
                (1, 2, 'a'),
                (2, 4, 'b'),
                (2, 5, 'c'),
                (9, 14, 'd'),
                (9, 140, 'e'),
                (1, 1, 'f'),
                (2, 2, 'g'),
                (4, 4, 'h'),
                (5, 5, 'i'),
                (1, 8, 'j'))

        right = (('start', 'stop', 'value'),
                 (1, 4, 'foo'),
                 (3, 7, 'bar'),
                 (4, 9, 'baz'))

        actual = intervaljoin(left, right,
                              lstart='begin', lstop='end',
                              rstart='start', rstop='stop')
        expect = (('begin', 'end', 'quux', 'start', 'stop', 'value'),
                  (1, 2, 'a', 1, 4, 'foo'),
                  (2, 4, 'b', 1, 4, 'foo'),
                  (2, 4, 'b', 3, 7, 'bar'),
                  (2, 5, 'c', 1, 4, 'foo'),
                  (2, 5, 'c', 3, 7, 'bar'),
                  (2, 5, 'c', 4, 9, 'baz'),
                  (1, 8, 'j', 1, 4, 'foo'),
                  (1, 8, 'j', 3, 7, 'bar'),
                  (1, 8, 'j', 4, 9, 'baz'))
        debug(lookall(actual))
        ieq(expect, actual)
        ieq(expect, actual)

    # endpoint table covering all 13 Allen's interval algebra relations
    # against the reference interval [5, 10)
    _relations_left = (('begin', 'end', 'tag'),
                       (1, 3, 'before'),
                       (3, 5, 'meets'),
                       (4, 7, 'overlaps'),
                       (5, 7, 'starts'),
                       (6, 8, 'during'),
                       (7, 10, 'finishes'),
                       (5, 10, 'equals'),
                       (8, 12, 'overlapped_by'),
                       (5, 12, 'started_by'),
                       (4, 12, 'contains'),
                       (4, 10, 'finished_by'),
                       (10, 12, 'met_by'),
                       (12, 14, 'after'))
    _relations_right = (('start', 'stop', 'value'),
                        (5, 10, 'ref'))

    def test_intervaljoin_relations():

        actual = intervaljoin(_relations_left, _relations_right,
                              lstart='begin', lstop='end',
                              rstart='start', rstop='stop',
                              relations=INTERVAL_RELATIONS)
        expect = (('begin', 'end', 'tag', 'start', 'stop', 'value',
                   'relation'),
                  (1, 3, 'before', 5, 10, 'ref', 'before'),
                  (3, 5, 'meets', 5, 10, 'ref', 'meets'),
                  (4, 7, 'overlaps', 5, 10, 'ref', 'overlaps'),
                  (5, 7, 'starts', 5, 10, 'ref', 'starts'),
                  (6, 8, 'during', 5, 10, 'ref', 'during'),
                  (7, 10, 'finishes', 5, 10, 'ref', 'finishes'),
                  (5, 10, 'equals', 5, 10, 'ref', 'equals'),
                  (8, 12, 'overlapped_by', 5, 10, 'ref', 'overlapped_by'),
                  (5, 12, 'started_by', 5, 10, 'ref', 'started_by'),
                  (4, 12, 'contains', 5, 10, 'ref', 'contains'),
                  (4, 10, 'finished_by', 5, 10, 'ref', 'finished_by'),
                  (10, 12, 'met_by', 5, 10, 'ref', 'met_by'),
                  (12, 14, 'after', 5, 10, 'ref', 'after'))
        ieq(expect, actual)
        ieq(expect, actual)
        # each pair of intervals is reported at most once, even though all
        # relations were selected
        eq_(len(expect) - 1, len(list(actual)) - 1)

    def test_intervaljoin_relations_selection():

        # select a subset of relations, given as a list
        actual = intervaljoin(_relations_left, _relations_right,
                              lstart='begin', lstop='end',
                              rstart='start', rstop='stop',
                              relations=['during', 'contains'])
        expect = (('begin', 'end', 'tag', 'start', 'stop', 'value',
                   'relation'),
                  (6, 8, 'during', 5, 10, 'ref', 'during'),
                  (4, 12, 'contains', 5, 10, 'ref', 'contains'))
        ieq(expect, actual)
        ieq(expect, actual)

        # a single relation may be given as a plain string
        actual = intervaljoin(_relations_left, _relations_right,
                              lstart='begin', lstop='end',
                              rstart='start', rstop='stop',
                              relations='meets')
        expect = (('begin', 'end', 'tag', 'start', 'stop', 'value',
                   'relation'),
                  (3, 5, 'meets', 5, 10, 'ref', 'meets'))
        ieq(expect, actual)
        ieq(expect, actual)

        # 'equal' is accepted as an alias of 'equals'
        actual = intervaljoin(_relations_left, _relations_right,
                              lstart='begin', lstop='end',
                              rstart='start', rstop='stop',
                              relations='equal')
        expect = (('begin', 'end', 'tag', 'start', 'stop', 'value',
                   'relation'),
                  (5, 10, 'equals', 5, 10, 'ref', 'equals'))
        ieq(expect, actual)
        ieq(expect, actual)

        # unknown relations are rejected
        with pytest.raises(AssertionError):
            intervaljoin(_relations_left, _relations_right,
                         lstart='begin', lstop='end',
                         rstart='start', rstop='stop',
                         relations='bogus')

    def test_intervaljoin_relations_inverse():

        # exchanging the left and right tables yields inverse relations
        forward = intervaljoin(_relations_left, _relations_right,
                               lstart='begin', lstop='end',
                               rstart='start', rstop='stop',
                               relations=INTERVAL_RELATIONS)
        backward = intervaljoin(_relations_right, _relations_left,
                                lstart='start', lstop='stop',
                                rstart='begin', rstop='end',
                                relations=INTERVAL_RELATIONS)
        forward_rows = list(forward)[1:]
        backward_rows = list(backward)[1:]
        eq_(len(forward_rows), len(backward_rows))
        backward_by_tag = {row[5]: row for row in backward_rows}
        for row in forward_rows:
            tag = row[2]
            relation = row[6]
            eq_(INVERSE_INTERVAL_RELATIONS[relation],
                backward_by_tag[tag][6])

    def test_intervaljoin_relations_custom_field():

        actual = intervaljoin(_relations_left, _relations_right,
                              lstart='begin', lstop='end',
                              rstart='start', rstop='stop',
                              relations='during', relation_field='allen')
        expect = (('begin', 'end', 'tag', 'start', 'stop', 'value', 'allen'),
                  (6, 8, 'during', 5, 10, 'ref', 'during'))
        ieq(expect, actual)
        ieq(expect, actual)

    def test_intervalleftjoin_relations():

        left = (('begin', 'end', 'tag'),
                (1, 3, 'u'),   # before, not selected
                (6, 8, 'v'),   # during
                (20, 30, 'w'),
                (3, 3, 'x'))   # empty interval (stop excluded)
        right = (('start', 'stop', 'value'),
                 (5, 10, 'ref'))
        actual = intervalleftjoin(left, right,
                                  lstart='begin', lstop='end',
                                  rstart='start', rstop='stop',
                                  relations='during')
        expect = (('begin', 'end', 'tag', 'start', 'stop', 'value',
                   'relation'),
                  (1, 3, 'u', None, None, None, None),
                  (6, 8, 'v', 5, 10, 'ref', 'during'),
                  (20, 30, 'w', None, None, None, None),
                  (3, 3, 'x', None, None, None, None))
        ieq(expect, actual)
        ieq(expect, actual)

    def test_intervaljoin_relations_faceted_compound():

        left = (('fruit', 'sort', 'begin', 'end'),
                ('apple', 'cox', 1, 3),
                ('apple', 'cox', 6, 8),
                ('apple', 'fuji', 6, 8),
                ('orange', 'mandarin', 6, 8))
        right = (('type', 'variety', 'start', 'stop', 'value'),
                 ('apple', 'cox', 5, 10, 'foo'),
                 ('apple', 'fuji', 5, 10, 'bar'))
        expect = (('fruit', 'sort', 'begin', 'end', 'type', 'variety',
                   'start', 'stop', 'value', 'relation'),
                  ('apple', 'cox', 1, 3, 'apple', 'cox', 5, 10, 'foo',
                   'before'),
                  ('apple', 'cox', 6, 8, 'apple', 'cox', 5, 10, 'foo',
                   'during'),
                  ('apple', 'fuji', 6, 8, 'apple', 'fuji', 5, 10, 'bar',
                   'during'))
        actual = intervaljoin(left, right, lstart='begin', lstop='end',
                              rstart='start', rstop='stop',
                              lkey=('fruit', 'sort'),
                              rkey=('type', 'variety'),
                              relations=('before', 'during'))
        ieq(expect, actual)
        ieq(expect, actual)

        # left join keeps unmatched rows, including missing facet keys
        expect = (('fruit', 'sort', 'begin', 'end', 'type', 'variety',
                   'start', 'stop', 'value', 'relation'),
                  ('apple', 'cox', 1, 3, 'apple', 'cox', 5, 10, 'foo',
                   'before'),
                  ('apple', 'cox', 6, 8, 'apple', 'cox', 5, 10, 'foo',
                   'during'),
                  ('apple', 'fuji', 6, 8, 'apple', 'fuji', 5, 10, 'bar',
                   'during'),
                  ('orange', 'mandarin', 6, 8, None, None, None, None, None,
                   None))
        actual = intervalleftjoin(left, right, lstart='begin', lstop='end',
                                  rstart='start', rstop='stop',
                                  lkey=('fruit', 'sort'),
                                  rkey=('type', 'variety'),
                                  relations=('before', 'during'))
        ieq(expect, actual)
        ieq(expect, actual)

    def test_intervaljoin_relations_boundaries():

        left = (('begin', 'end', 'tag'),
                (1, 5, 'touch'),
                (1, 4, 'gap'))
        right = (('start', 'stop', 'value'),
                 (5, 10, 'ref'))

        # default: start included, stop excluded, so [1, 5) and [5, 10) are
        # adjacent but disjoint
        actual = intervaljoin(left, right, lstart='begin', lstop='end',
                              rstart='start', rstop='stop',
                              relations=INTERVAL_RELATIONS)
        expect = (('begin', 'end', 'tag', 'start', 'stop', 'value',
                   'relation'),
                  (1, 5, 'touch', 5, 10, 'ref', 'meets'),
                  (1, 4, 'gap', 5, 10, 'ref', 'before'))
        ieq(expect, actual)
        ieq(expect, actual)

        # with both endpoints included, [1, 5] and [5, 10] share the point 5
        actual = intervaljoin(left, right, lstart='begin', lstop='end',
                              rstart='start', rstop='stop',
                              relations=INTERVAL_RELATIONS,
                              include_stop=True)
        expect = (('begin', 'end', 'tag', 'start', 'stop', 'value',
                   'relation'),
                  (1, 5, 'touch', 5, 10, 'ref', 'overlaps'),
                  (1, 4, 'gap', 5, 10, 'ref', 'before'))
        ieq(expect, actual)
        ieq(expect, actual)

    def test_intervaljoin_relations_zero_length():

        left = (('begin', 'end', 'tag'),
                (3, 3, 'p1'),
                (7, 7, 'p2'),
                (10, 10, 'p3'),
                (12, 12, 'p4'))
        right = (('start', 'stop', 'value'),
                 (5, 10, 'ref'))

        # zero-length intervals are empty by default (stop excluded) and so
        # never match
        actual = intervalleftjoin(left, right, lstart='begin', lstop='end',
                                  rstart='start', rstop='stop',
                                  relations=INTERVAL_RELATIONS)
        expect = (('begin', 'end', 'tag', 'start', 'stop', 'value',
                   'relation'),
                  (3, 3, 'p1', None, None, None, None),
                  (7, 7, 'p2', None, None, None, None),
                  (10, 10, 'p3', None, None, None, None),
                  (12, 12, 'p4', None, None, None, None))
        ieq(expect, actual)
        ieq(expect, actual)

        # with both endpoints included, a zero-length interval is a point
        actual = intervaljoin(left, right, lstart='begin', lstop='end',
                              rstart='start', rstop='stop',
                              relations=INTERVAL_RELATIONS,
                              include_stop=True)
        expect = (('begin', 'end', 'tag', 'start', 'stop', 'value',
                   'relation'),
                  (3, 3, 'p1', 5, 10, 'ref', 'before'),
                  (7, 7, 'p2', 5, 10, 'ref', 'during'),
                  (10, 10, 'p3', 5, 10, 'ref', 'finishes'),
                  (12, 12, 'p4', 5, 10, 'ref', 'after'))
        ieq(expect, actual)
        ieq(expect, actual)

    def test_intervaljoin_relations_invalid():

        right = (('start', 'stop', 'value'),
                 (5, 10, 'ref'))

        # reversed interval in the left table
        left = (('begin', 'end'), (5, 3))
        with pytest.raises(ValueError):
            list(intervaljoin(left, right, lstart='begin', lstop='end',
                              rstart='start', rstop='stop',
                              relations='overlaps'))

        # reversed interval in the right table
        left = (('begin', 'end'), (1, 2))
        badright = (('start', 'stop', 'value'), (9, 4, 'ref'))
        with pytest.raises(ValueError):
            list(intervaljoin(left, badright, lstart='begin', lstop='end',
                              rstart='start', rstop='stop',
                              relations='overlaps'))

    def test_intervalantijoin_relations():

        left = (('begin', 'end', 'tag'),
                (1, 3, 'u'),
                (6, 8, 'v'),
                (20, 30, 'w'))
        right = (('start', 'stop', 'value'),
                 (5, 10, 'ref'))
        actual = intervalantijoin(left, right, lstart='begin', lstop='end',
                                  rstart='start', rstop='stop',
                                  relations=('during', 'contains'))
        expect = (('begin', 'end', 'tag'),
                  (1, 3, 'u'),
                  (20, 30, 'w'))
        ieq(expect, actual)
        ieq(expect, actual)

    def test_intervaljoin_include_stop():

        left = (('begin', 'end', 'quux'),
                (1, 2, 'a'),
                (2, 4, 'b'),
                (2, 5, 'c'),
                (9, 14, 'd'),
                (9, 140, 'e'),
                (1, 1, 'f'),
                (2, 2, 'g'),
                (4, 4, 'h'),
                (5, 5, 'i'),
                (1, 8, 'j'))

        right = (('start', 'stop', 'value'),
                 (1, 4, 'foo'),
                 (3, 7, 'bar'),
                 (4, 9, 'baz'))

        actual = intervaljoin(left, right,
                              lstart='begin', lstop='end',
                              rstart='start', rstop='stop',
                              include_stop=True)
        expect = (('begin', 'end', 'quux', 'start', 'stop', 'value'),
                  (1, 2, 'a', 1, 4, 'foo'),
                  (2, 4, 'b', 1, 4, 'foo'),
                  (2, 4, 'b', 3, 7, 'bar'),
                  (2, 4, 'b', 4, 9, 'baz'),
                  (2, 5, 'c', 1, 4, 'foo'),
                  (2, 5, 'c', 3, 7, 'bar'),
                  (2, 5, 'c', 4, 9, 'baz'),
                  (9, 14, 'd', 4, 9, 'baz'),
                  (9, 140, 'e', 4, 9, 'baz'),
                  (1, 1, 'f', 1, 4, 'foo'),
                  (2, 2, 'g', 1, 4, 'foo'),
                  (4, 4, 'h', 1, 4, 'foo'),
                  (4, 4, 'h', 3, 7, 'bar'),
                  (4, 4, 'h', 4, 9, 'baz'),
                  (5, 5, 'i', 3, 7, 'bar'),
                  (5, 5, 'i', 4, 9, 'baz'),
                  (1, 8, 'j', 1, 4, 'foo'),
                  (1, 8, 'j', 3, 7, 'bar'),
                  (1, 8, 'j', 4, 9, 'baz'))
        ieq(expect, actual)
        ieq(expect, actual)

    def test_intervaljoin_prefixes():

        left = (('begin', 'end', 'quux'),
                (1, 2, 'a'),
                (2, 4, 'b'),
                (2, 5, 'c'),
                (9, 14, 'd'),
                (9, 140, 'e'),
                (1, 1, 'f'),
                (2, 2, 'g'),
                (4, 4, 'h'),
                (5, 5, 'i'),
                (1, 8, 'j'))

        right = (('start', 'stop', 'value'),
                 (1, 4, 'foo'),
                 (3, 7, 'bar'),
                 (4, 9, 'baz'))

        actual = intervaljoin(left, right,
                              lstart='begin', lstop='end',
                              rstart='start', rstop='stop',
                              lprefix='l_', rprefix='r_')
        expect = (('l_begin', 'l_end', 'l_quux', 'r_start', 'r_stop', 'r_value'),
                  (1, 2, 'a', 1, 4, 'foo'),
                  (2, 4, 'b', 1, 4, 'foo'),
                  (2, 4, 'b', 3, 7, 'bar'),
                  (2, 5, 'c', 1, 4, 'foo'),
                  (2, 5, 'c', 3, 7, 'bar'),
                  (2, 5, 'c', 4, 9, 'baz'),
                  (1, 8, 'j', 1, 4, 'foo'),
                  (1, 8, 'j', 3, 7, 'bar'),
                  (1, 8, 'j', 4, 9, 'baz'))
        ieq(expect, actual)
        ieq(expect, actual)

    def test_intervalleftjoin():

        left = (('begin', 'end', 'quux'),
                (1, 2, 'a'),
                (2, 4, 'b'),
                (2, 5, 'c'),
                (9, 14, 'd'),
                (9, 140, 'e'),
                (1, 1, 'f'),
                (2, 2, 'g'),
                (4, 4, 'h'),
                (5, 5, 'i'),
                (1, 8, 'j'))

        right = (('start', 'stop', 'value'),
                 (1, 4, 'foo'),
                 (3, 7, 'bar'),
                 (4, 9, 'baz'))

        actual = intervalleftjoin(left, right,
                                  lstart='begin', lstop='end',
                                  rstart='start', rstop='stop')
        expect = (('begin', 'end', 'quux', 'start', 'stop', 'value'),
                  (1, 2, 'a', 1, 4, 'foo'),
                  (2, 4, 'b', 1, 4, 'foo'),
                  (2, 4, 'b', 3, 7, 'bar'),
                  (2, 5, 'c', 1, 4, 'foo'),
                  (2, 5, 'c', 3, 7, 'bar'),
                  (2, 5, 'c', 4, 9, 'baz'),
                  (9, 14, 'd', None, None, None),
                  (9, 140, 'e', None, None, None),
                  (1, 1, 'f', None, None, None),
                  (2, 2, 'g', None, None, None),
                  (4, 4, 'h', None, None, None),
                  (5, 5, 'i', None, None, None),
                  (1, 8, 'j', 1, 4, 'foo'),
                  (1, 8, 'j', 3, 7, 'bar'),
                  (1, 8, 'j', 4, 9, 'baz'))
        ieq(expect, actual)
        ieq(expect, actual)

    def test_intervaljoin_faceted():

        left = (('fruit', 'begin', 'end'),
                ('apple', 1, 2),
                ('apple', 2, 4),
                ('apple', 2, 5),
                ('orange', 2, 5),
                ('orange', 9, 14),
                ('orange', 19, 140),
                ('apple', 1, 1),
                ('apple', 2, 2),
                ('apple', 4, 4),
                ('apple', 5, 5),
                ('orange', 5, 5))

        right = (('type', 'start', 'stop', 'value'),
                 ('apple', 1, 4, 'foo'),
                 ('apple', 3, 7, 'bar'),
                 ('orange', 4, 9, 'baz'))

        expect = (('fruit', 'begin', 'end', 'type', 'start', 'stop', 'value'),
                  ('apple', 1, 2, 'apple', 1, 4, 'foo'),
                  ('apple', 2, 4, 'apple', 1, 4, 'foo'),
                  ('apple', 2, 4, 'apple', 3, 7, 'bar'),
                  ('apple', 2, 5, 'apple', 1, 4, 'foo'),
                  ('apple', 2, 5, 'apple', 3, 7, 'bar'),
                  ('orange', 2, 5, 'orange', 4, 9, 'baz'))
        actual = intervaljoin(left, right, lstart='begin', lstop='end',
                              rstart='start', rstop='stop', lkey='fruit',
                              rkey='type')

        ieq(expect, actual)
        ieq(expect, actual)

    def test_intervalleftjoin_faceted():

        left = (('fruit', 'begin', 'end'),
                ('apple', 1, 2),
                ('apple', 2, 4),
                ('apple', 2, 5),
                ('orange', 2, 5),
                ('orange', 9, 14),
                ('orange', 19, 140),
                ('apple', 1, 1),
                ('apple', 2, 2),
                ('apple', 4, 4),
                ('apple', 5, 5),
                ('orange', 5, 5))

        right = (('type', 'start', 'stop', 'value'),
                 ('apple', 1, 4, 'foo'),
                 ('apple', 3, 7, 'bar'),
                 ('orange', 4, 9, 'baz'))

        expect = (('fruit', 'begin', 'end', 'type', 'start', 'stop', 'value'),
                  ('apple', 1, 2, 'apple', 1, 4, 'foo'),
                  ('apple', 2, 4, 'apple', 1, 4, 'foo'),
                  ('apple', 2, 4, 'apple', 3, 7, 'bar'),
                  ('apple', 2, 5, 'apple', 1, 4, 'foo'),
                  ('apple', 2, 5, 'apple', 3, 7, 'bar'),
                  ('orange', 2, 5, 'orange', 4, 9, 'baz'),
                  ('orange', 9, 14, None, None, None, None),
                  ('orange', 19, 140, None, None, None, None),
                  ('apple', 1, 1, None, None, None, None),
                  ('apple', 2, 2, None, None, None, None),
                  ('apple', 4, 4, None, None, None, None),
                  ('apple', 5, 5, None, None, None, None),
                  ('orange', 5, 5, None, None, None, None))

        actual = intervalleftjoin(left, right, lstart='begin', lstop='end',
                                  rstart='start', rstop='stop', lkey='fruit',
                                  rkey='type')

        ieq(expect, actual)
        ieq(expect, actual)

    def test_intervalleftjoin_faceted_rkeymissing():

        left = (('fruit', 'begin', 'end'),
                ('apple', 1, 2),
                ('orange', 5, 5))

        right = (('type', 'start', 'stop', 'value'),
                 ('apple', 1, 4, 'foo'))

        expect = (('fruit', 'begin', 'end', 'type', 'start', 'stop', 'value'),
                  ('apple', 1, 2, 'apple', 1, 4, 'foo'),
                  ('orange', 5, 5, None, None, None, None))

        actual = intervalleftjoin(left, right, lstart='begin', lstop='end',
                                  rstart='start', rstop='stop', lkey='fruit',
                                  rkey='type')

        ieq(expect, actual)
        ieq(expect, actual)

    def test_intervaljoins_faceted_compound():

        left = (('fruit', 'sort', 'begin', 'end'),
                ('apple', 'cox', 1, 2),
                ('apple', 'fuji', 2, 4))
        right = (('type', 'variety', 'start', 'stop', 'value'),
                 ('apple', 'cox', 1, 4, 'foo'),
                 ('apple', 'fuji', 3, 7, 'bar'),
                 ('orange', 'mandarin', 4, 9, 'baz'))

        expect = (('fruit', 'sort', 'begin', 'end', 'type', 'variety', 'start',
                   'stop', 'value'),
                  ('apple', 'cox', 1, 2, 'apple', 'cox', 1, 4, 'foo'),
                  ('apple', 'fuji', 2, 4, 'apple', 'fuji', 3, 7, 'bar'))

        actual = intervaljoin(left, right, lstart='begin', lstop='end',
                              rstart='start', rstop='stop',
                              lkey=('fruit', 'sort'),
                              rkey=('type', 'variety'))
        ieq(expect, actual)
        ieq(expect, actual)

        actual = intervalleftjoin(left, right, lstart='begin', lstop='end',
                                  rstart='start', rstop='stop',
                                  lkey=('fruit', 'sort'),
                                  rkey=('type', 'variety'))
        ieq(expect, actual)
        ieq(expect, actual)

    def test_intervalleftjoin_prefixes():

        left = (('begin', 'end', 'quux'),
                (1, 2, 'a'),
                (2, 4, 'b'),
                (2, 5, 'c'),
                (9, 14, 'd'),
                (9, 140, 'e'),
                (1, 1, 'f'),
                (2, 2, 'g'),
                (4, 4, 'h'),
                (5, 5, 'i'),
                (1, 8, 'j'))

        right = (('start', 'stop', 'value'),
                 (1, 4, 'foo'),
                 (3, 7, 'bar'),
                 (4, 9, 'baz'))

        actual = intervalleftjoin(left, right,
                                  lstart='begin', lstop='end',
                                  rstart='start', rstop='stop',
                                  lprefix='l_', rprefix='r_')
        expect = (('l_begin', 'l_end', 'l_quux', 'r_start', 'r_stop', 'r_value'),
                  (1, 2, 'a', 1, 4, 'foo'),
                  (2, 4, 'b', 1, 4, 'foo'),
                  (2, 4, 'b', 3, 7, 'bar'),
                  (2, 5, 'c', 1, 4, 'foo'),
                  (2, 5, 'c', 3, 7, 'bar'),
                  (2, 5, 'c', 4, 9, 'baz'),
                  (9, 14, 'd', None, None, None),
                  (9, 140, 'e', None, None, None),
                  (1, 1, 'f', None, None, None),
                  (2, 2, 'g', None, None, None),
                  (4, 4, 'h', None, None, None),
                  (5, 5, 'i', None, None, None),
                  (1, 8, 'j', 1, 4, 'foo'),
                  (1, 8, 'j', 3, 7, 'bar'),
                  (1, 8, 'j', 4, 9, 'baz'))
        ieq(expect, actual)
        ieq(expect, actual)

    def test_intervalantijoin():

        left = (('begin', 'end', 'quux'),
                (1, 2, 'a'),
                (2, 4, 'b'),
                (2, 5, 'c'),
                (9, 14, 'd'),
                (9, 140, 'e'),
                (1, 1, 'f'),
                (2, 2, 'g'),
                (4, 4, 'h'),
                (5, 5, 'i'),
                (1, 8, 'j'))

        right = (('start', 'stop', 'value'),
                 (1, 4, 'foo'),
                 (3, 7, 'bar'),
                 (4, 9, 'baz'))

        actual = intervalantijoin(left, right,
                                  lstart='begin', lstop='end',
                                  rstart='start', rstop='stop')
        expect = (('begin', 'end', 'quux'),
                  (9, 14, 'd'),
                  (9, 140, 'e'),
                  (1, 1, 'f'),
                  (2, 2, 'g'),
                  (4, 4, 'h'),
                  (5, 5, 'i'))
        debug(lookall(actual))
        ieq(expect, actual)
        ieq(expect, actual)

    def test_intervalantijoin_include_stop():

        left = (('begin', 'end', 'quux'),
                (1, 2, 'a'),
                (2, 4, 'b'),
                (2, 5, 'c'),
                (9, 14, 'd'),
                (9, 140, 'e'),
                (10, 140, 'e'),
                (1, 1, 'f'),
                (2, 2, 'g'),
                (4, 4, 'h'),
                (5, 5, 'i'),
                (1, 8, 'j'))

        right = (('start', 'stop', 'value'),
                 (1, 4, 'foo'),
                 (3, 7, 'bar'),
                 (4, 9, 'baz'))

        actual = intervalantijoin(left, right,
                                  lstart='begin', lstop='end',
                                  rstart='start', rstop='stop',
                                  include_stop=True)
        expect = (('begin', 'end', 'quux'),
                  (10, 140, 'e'))
        debug(lookall(actual))
        ieq(expect, actual)
        ieq(expect, actual)

    def test_intervalantijoin_faceted():

        left = (('fruit', 'begin', 'end'),
                ('apple', 1, 2),
                ('apple', 2, 4),
                ('apple', 2, 5),
                ('orange', 2, 5),
                ('orange', 9, 14),
                ('orange', 19, 140),
                ('apple', 1, 1),
                ('apple', 2, 2),
                ('apple', 4, 4),
                ('apple', 5, 5),
                ('orange', 5, 5))

        right = (('type', 'start', 'stop', 'value'),
                 ('apple', 1, 4, 'foo'),
                 ('apple', 3, 7, 'bar'),
                 ('orange', 4, 9, 'baz'))

        expect = (('fruit', 'begin', 'end'),
                  ('orange', 9, 14),
                  ('orange', 19, 140),
                  ('apple', 1, 1),
                  ('apple', 2, 2),
                  ('apple', 4, 4),
                  ('apple', 5, 5),
                  ('orange', 5, 5))

        actual = intervalantijoin(left, right, lstart='begin', lstop='end',
                                  rstart='start', rstop='stop', lkey='fruit',
                                  rkey='type')

        ieq(expect, actual)
        ieq(expect, actual)

    def test_intervaljoinvalues_faceted():

        left = (('fruit', 'begin', 'end'),
                ('apple', 1, 2),
                ('apple', 2, 4),
                ('apple', 2, 5),
                ('orange', 2, 5),
                ('orange', 9, 14),
                ('orange', 19, 140),
                ('apple', 1, 1),
                ('apple', 2, 2),
                ('apple', 4, 4),
                ('apple', 5, 5),
                ('orange', 5, 5))

        right = (('type', 'start', 'stop', 'value'),
                 ('apple', 1, 4, 'foo'),
                 ('apple', 3, 7, 'bar'),
                 ('orange', 4, 9, 'baz'))

        expect = (('fruit', 'begin', 'end', 'value'),
                  ('apple', 1, 2, ['foo']),
                  ('apple', 2, 4, ['foo', 'bar']),
                  ('apple', 2, 5, ['foo', 'bar']),
                  ('orange', 2, 5, ['baz']),
                  ('orange', 9, 14, []),
                  ('orange', 19, 140, []),
                  ('apple', 1, 1, []),
                  ('apple', 2, 2, []),
                  ('apple', 4, 4, []),
                  ('apple', 5, 5, []),
                  ('orange', 5, 5, []))

        actual = intervaljoinvalues(left, right, lstart='begin', lstop='end',
                                    rstart='start', rstop='stop', lkey='fruit',
                                    rkey='type', value='value')

        ieq(expect, actual)
        ieq(expect, actual)

    def test_subtract_1():

        left = (('begin', 'end', 'label'),
                (1, 6, 'apple'),
                (3, 6, 'orange'),
                (5, 9, 'banana'))

        right = (('start', 'stop', 'foo'),
                 (3, 4, True))

        expect = (('begin', 'end', 'label'),
                  (1, 3, 'apple'),
                  (4, 6, 'apple'),
                  (4, 6, 'orange'),
                  (5, 9, 'banana'))

        actual = intervalsubtract(left, right,
                                  lstart='begin', lstop='end',
                                  rstart='start', rstop='stop')

        ieq(expect, actual)
        ieq(expect, actual)

    def test_subtract_2():

        left = (('begin', 'end', 'label'),
                (1, 6, 'apple'),
                (3, 6, 'orange'),
                (5, 9, 'banana'))

        right = (('start', 'stop', 'foo'),
                 (3, 4, True),
                 (5, 6, True))

        expect = (('begin', 'end', 'label'),
                  (1, 3, 'apple'),
                  (4, 5, 'apple'),
                  (4, 5, 'orange'),
                  (6, 9, 'banana'))

        actual = intervalsubtract(left, right,
                                  lstart='begin', lstop='end',
                                  rstart='start', rstop='stop')

        ieq(expect, actual)
        ieq(expect, actual)

    def test_subtract_faceted():

        left = (('region', 'begin', 'end', 'label'),
                ('north', 1, 6, 'apple'),
                ('south', 3, 6, 'orange'),
                ('west', 5, 9, 'banana'))

        right = (('place', 'start', 'stop', 'foo'),
                 ('south', 3, 4, True),
                 ('north', 5, 6, True))

        expect = (('region', 'begin', 'end', 'label'),
                  ('north', 1, 5, 'apple'),
                  ('south', 4, 6, 'orange'),
                  ('west', 5, 9, 'banana'))

        actual = intervalsubtract(left, right,
                                  lkey='region', rkey='place',
                                  lstart='begin', lstop='end',
                                  rstart='start', rstop='stop')

        ieq(expect, actual)
        ieq(expect, actual)

    def test_collapse():

        # no facet key
        tbl = (('begin', 'end', 'label'),
               (1, 6, 'apple'),
               (3, 6, 'orange'),
               (5, 9, 'banana'),
               (12, 14, 'banana'),
               (13, 17, 'kiwi'))
        expect = [_Interval(1, 9), _Interval(12, 17)]
        actual = collapsedintervals(tbl, start='begin', stop='end')
        ieq(expect, actual)

        # faceted
        tbl = (('region', 'begin', 'end', 'label'),
               ('north', 1, 6, 'apple'),
               ('north', 3, 6, 'orange'),
               ('north', 5, 9, 'banana'),
               ('south', 12, 14, 'banana'),
               ('south', 13, 17, 'kiwi'))
        expect = [('north', 1, 9), ('south', 12, 17)]
        actual = collapsedintervals(tbl, start='begin', stop='end',
                                    key='region')
        ieq(expect, actual)

    def test_integration():

        left = etl.wrap((('begin', 'end', 'quux'),
                         (1, 2, 'a'),
                         (2, 4, 'b'),
                         (2, 5, 'c'),
                         (9, 14, 'd'),
                         (9, 140, 'e'),
                         (1, 1, 'f'),
                         (2, 2, 'g'),
                         (4, 4, 'h'),
                         (5, 5, 'i'),
                         (1, 8, 'j')))

        right = etl.wrap((('start', 'stop', 'value'),
                          (1, 4, 'foo'),
                          (3, 7, 'bar'),
                          (4, 9, 'baz')))

        actual = left.intervaljoin(right,
                                   lstart='begin', lstop='end',
                                   rstart='start', rstop='stop')
        expect = (('begin', 'end', 'quux', 'start', 'stop', 'value'),
                  (1, 2, 'a', 1, 4, 'foo'),
                  (2, 4, 'b', 1, 4, 'foo'),
                  (2, 4, 'b', 3, 7, 'bar'),
                  (2, 5, 'c', 1, 4, 'foo'),
                  (2, 5, 'c', 3, 7, 'bar'),
                  (2, 5, 'c', 4, 9, 'baz'),
                  (1, 8, 'j', 1, 4, 'foo'),
                  (1, 8, 'j', 3, 7, 'bar'),
                  (1, 8, 'j', 4, 9, 'baz'))
        ieq(expect, actual)
        ieq(expect, actual)
