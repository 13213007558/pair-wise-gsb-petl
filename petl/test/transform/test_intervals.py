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
    collapsedintervals, _Interval, intervalantijoin


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

    # endpoint tables covering all thirteen Allen interval algebra
    # relations of a left interval [5, 10) relative to each right interval
    _interval_relations_left = (('lid', 'lstart', 'lstop'),
                       ('L', 5, 10))
    _interval_relations_right = (('rid', 'rstart', 'rstop'),
                        ('R01', 1, 3),
                        ('R02', 3, 5),
                        ('R03', 4, 7),
                        ('R04', 5, 7),
                        ('R05', 6, 8),
                        ('R06', 7, 10),
                        ('R07', 5, 10),
                        ('R08', 5, 12),
                        ('R09', 4, 12),
                        ('R10', 3, 10),
                        ('R11', 8, 12),
                        ('R12', 10, 12),
                        ('R13', 12, 15))
    _interval_relations_all = ('before', 'meets', 'overlaps', 'starts', 'during',
                      'finishes', 'equal', 'after', 'met_by',
                      'overlapped_by', 'started_by', 'contains',
                      'finished_by')
    _interval_relations_expect = (
        ('lid', 'lstart', 'lstop', 'rid', 'rstart', 'rstop', 'relation'),
        ('L', 5, 10, 'R01', 1, 3, 'after'),
        ('L', 5, 10, 'R02', 3, 5, 'met_by'),
        ('L', 5, 10, 'R03', 4, 7, 'overlapped_by'),
        ('L', 5, 10, 'R04', 5, 7, 'started_by'),
        ('L', 5, 10, 'R05', 6, 8, 'contains'),
        ('L', 5, 10, 'R06', 7, 10, 'finished_by'),
        ('L', 5, 10, 'R07', 5, 10, 'equal'),
        ('L', 5, 10, 'R08', 5, 12, 'starts'),
        ('L', 5, 10, 'R09', 4, 12, 'during'),
        ('L', 5, 10, 'R10', 3, 10, 'finishes'),
        ('L', 5, 10, 'R11', 8, 12, 'overlaps'),
        ('L', 5, 10, 'R12', 10, 12, 'meets'),
        ('L', 5, 10, 'R13', 12, 15, 'before'))

    def test_intervaljoin_relations():

        actual = intervaljoin(
            _interval_relations_left,
            _interval_relations_right,
            lstart='lstart', lstop='lstop', rstart='rstart', rstop='rstop',
            relations=_interval_relations_all)
        expect = _interval_relations_expect
        debug(lookall(actual))
        ieq(expect, actual)
        ieq(expect, actual)
        # each pair of intervals matches exactly one relation, so no pair
        # is duplicated even though all relations were selected
        rows = list(actual)[1:]
        eq_(13, len(rows))
        eq_(13, len(set(row[3] for row in rows)))

    def test_intervaljoin_interval_relations_selection():

        left = _interval_relations_left
        right = _interval_relations_right

        # select multiple relations, including adjacent but not
        # intersecting intervals
        actual = intervaljoin(left, right, lstart='lstart', lstop='lstop',
                              rstart='rstart', rstop='rstop',
                              relations=('before', 'meets'))
        expect = (('lid', 'lstart', 'lstop', 'rid', 'rstart', 'rstop',
                   'relation'),
                  ('L', 5, 10, 'R12', 10, 12, 'meets'),
                  ('L', 5, 10, 'R13', 12, 15, 'before'))
        ieq(expect, actual)

        # a single relation may be given as a string
        actual = intervaljoin(left, right, lstart='lstart', lstop='lstop',
                              rstart='rstart', rstop='rstop',
                              relations='during')
        expect = (('lid', 'lstart', 'lstop', 'rid', 'rstart', 'rstop',
                   'relation'),
                  ('L', 5, 10, 'R09', 4, 12, 'during'))
        ieq(expect, actual)

        # the relation output field can be renamed
        actual = intervaljoin(left, right, lstart='lstart', lstop='lstop',
                              rstart='rstart', rstop='rstop',
                              relations='equal', relation_field='rel')
        expect = (('lid', 'lstart', 'lstop', 'rid', 'rstart', 'rstop',
                   'rel'),
                  ('L', 5, 10, 'R07', 5, 10, 'equal'))
        ieq(expect, actual)

    def test_intervaljoin_interval_relations_swapped():

        # swapping the left and right tables yields the inverse relations
        actual = intervaljoin(
            _interval_relations_right,
            _interval_relations_left,
            lstart='rstart', lstop='rstop', rstart='lstart', rstop='lstop',
            relations=_interval_relations_all)
        expect = (
            ('rid', 'rstart', 'rstop', 'lid', 'lstart', 'lstop',
             'relation'),
            ('R01', 1, 3, 'L', 5, 10, 'before'),
            ('R02', 3, 5, 'L', 5, 10, 'meets'),
            ('R03', 4, 7, 'L', 5, 10, 'overlaps'),
            ('R04', 5, 7, 'L', 5, 10, 'starts'),
            ('R05', 6, 8, 'L', 5, 10, 'during'),
            ('R06', 7, 10, 'L', 5, 10, 'finishes'),
            ('R07', 5, 10, 'L', 5, 10, 'equal'),
            ('R08', 5, 12, 'L', 5, 10, 'started_by'),
            ('R09', 4, 12, 'L', 5, 10, 'contains'),
            ('R10', 3, 10, 'L', 5, 10, 'finished_by'),
            ('R11', 8, 12, 'L', 5, 10, 'overlapped_by'),
            ('R12', 10, 12, 'L', 5, 10, 'met_by'),
            ('R13', 12, 15, 'L', 5, 10, 'after'))
        debug(lookall(actual))
        ieq(expect, actual)
        ieq(expect, actual)

    def test_intervaljoin_interval_relations_include_stop():

        left = (('start', 'stop'),
                (1, 2),
                (2, 2))
        right = (('start', 'stop'),
                 (2, 4),
                 (2, 2))

        # by default stop coordinates are excluded, so intervals touching
        # at an endpoint are adjacent but not intersecting, and zero
        # length intervals are empty
        actual = intervaljoin(left, right, relations=('meets', 'overlaps'))
        expect = (('start', 'stop', 'start', 'stop', 'relation'),
                  (1, 2, 2, 4, 'meets'))
        ieq(expect, actual)

        # including stop coordinates, touching intervals share a point,
        # and zero length intervals are treated as single points
        actual = intervaljoin(left, right, relations=('overlaps', 'starts',
                                                      'finished_by',
                                                      'equal'),
                              include_stop=True)
        expect = (('start', 'stop', 'start', 'stop', 'relation'),
                  (1, 2, 2, 4, 'overlaps'),
                  (1, 2, 2, 2, 'finished_by'),
                  (2, 2, 2, 4, 'starts'),
                  (2, 2, 2, 2, 'equal'))
        ieq(expect, actual)

    def test_intervalleftjoin_relations():

        left = (('start', 'stop'),
                (1, 2),
                (2, 2),
                (7, 7),
                (9, 14))
        right = (('start', 'stop'),
                 (2, 4))

        # rows without a match are kept, including empty zero length
        # intervals
        actual = intervalleftjoin(left, right, relations='overlaps')
        expect = (('start', 'stop', 'start', 'stop', 'relation'),
                  (1, 2, None, None, None),
                  (2, 2, None, None, None),
                  (7, 7, None, None, None),
                  (9, 14, None, None, None))
        debug(lookall(actual))
        ieq(expect, actual)
        ieq(expect, actual)

    def test_intervaljoin_interval_relations_faceted_compound():

        left = (('fruit', 'sort', 'begin', 'end'),
                ('apple', 'cox', 1, 5),
                ('apple', 'fuji', 1, 5),
                ('orange', 'mandarin', 1, 5))
        right = (('type', 'variety', 'start', 'stop', 'value'),
                 ('apple', 'cox', 3, 4, 'foo'),
                 ('orange', 'mandarin', 6, 9, 'bar'))

        expect = (('fruit', 'sort', 'begin', 'end', 'type', 'variety',
                   'start', 'stop', 'value', 'relation'),
                  ('apple', 'cox', 1, 5, 'apple', 'cox', 3, 4, 'foo',
                   'contains'),
                  ('orange', 'mandarin', 1, 5, 'orange', 'mandarin', 6, 9,
                   'bar', 'before'))
        actual = intervaljoin(left, right, lstart='begin', lstop='end',
                              rstart='start', rstop='stop',
                              lkey=('fruit', 'sort'),
                              rkey=('type', 'variety'),
                              relations=('before', 'contains'))
        ieq(expect, actual)
        ieq(expect, actual)

        # unmatched facet groups are kept by the left join variant
        actual = intervalleftjoin(left, right, lstart='begin', lstop='end',
                                  rstart='start', rstop='stop',
                                  lkey=('fruit', 'sort'),
                                  rkey=('type', 'variety'),
                                  relations=('before', 'contains'))
        expect = (('fruit', 'sort', 'begin', 'end', 'type', 'variety',
                   'start', 'stop', 'value', 'relation'),
                  ('apple', 'cox', 1, 5, 'apple', 'cox', 3, 4, 'foo',
                   'contains'),
                  ('apple', 'fuji', 1, 5, None, None, None, None, None,
                   None),
                  ('orange', 'mandarin', 1, 5, 'orange', 'mandarin', 6, 9,
                   'bar', 'before'))
        ieq(expect, actual)
        ieq(expect, actual)

    def test_intervalantijoin_relations():

        left = (('start', 'stop'),
                (1, 2),
                (2, 2),
                (7, 7))
        right = (('start', 'stop'),
                 (2, 4))

        actual = intervalantijoin(left, right, relations='meets')
        expect = (('start', 'stop'),
                  (2, 2),
                  (7, 7))
        ieq(expect, actual)
        ieq(expect, actual)

    def test_intervaljoin_interval_relations_invalid():

        left = (('start', 'stop'),
                (1, 2))
        right = (('start', 'stop'),
                 (2, 4))

        # unknown relation names are rejected
        with pytest.raises(ValueError):
            intervaljoin(left, right, relations='bogus')
        with pytest.raises(ValueError):
            intervaljoin(left, right, relations=('meets', 'bogus'))
        with pytest.raises(ValueError):
            intervaljoin(left, right, relations=())

        # intervals with stop before start are invalid
        with pytest.raises(ValueError):
            list(intervaljoin((('start', 'stop'), (5, 2)), right,
                              relations='equal'))
        with pytest.raises(ValueError):
            list(intervaljoin(left, (('start', 'stop'), (4, 2)),
                              relations='equal'))

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
