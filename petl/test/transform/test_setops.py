from __future__ import absolute_import, print_function, division


from datetime import datetime


from petl.test.helpers import ieq
from petl.transform.setops import complement, intersection, diff, \
    recordcomplement, recorddiff, hashcomplement, hashintersection
from petl.transform.setops import divide


def _test_complement_1(complement_impl):

    table1 = (('foo', 'bar'),
              ('A', 1),
              ('B', 2),
              ('C', 7))

    table2 = (('foo', 'bar'),
              ('A', 9),
              ('B', 2),
              ('B', 3))

    expectation = (('foo', 'bar'),
                   ('A', 1),
                   ('C', 7))

    result = complement_impl(table1, table2)
    ieq(expectation, result)


def _test_complement_2(complement_impl):

    tablea = (('foo', 'bar', 'baz'),
              ('A', 1, True),
              ('C', 7, False),
              ('B', 2, False),
              ('C', 9, True))

    tableb = (('x', 'y', 'z'),
              ('B', 2, False),
              ('A', 9, False),
              ('B', 3, True),
              ('C', 9, True))

    aminusb = (('foo', 'bar', 'baz'),
               ('A', 1, True),
               ('C', 7, False))

    result = complement_impl(tablea, tableb)
    ieq(aminusb, result)

    bminusa = (('x', 'y', 'z'),
               ('A', 9, False),
               ('B', 3, True))

    result = complement_impl(tableb, tablea)
    ieq(bminusa, result)


def _test_complement_3(complement_impl):

    # make sure we deal with empty tables

    table1 = (('foo', 'bar'),
              ('A', 1),
              ('B', 2))

    table2 = (('foo', 'bar'),)

    expectation = (('foo', 'bar'),
                   ('A', 1),
                   ('B', 2))
    result = complement_impl(table1, table2)
    ieq(expectation, result)
    ieq(expectation, result)

    expectation = (('foo', 'bar'),)
    result = complement_impl(table2, table1)
    ieq(expectation, result)
    ieq(expectation, result)


def _test_complement_4(complement_impl):

    # test behaviour with duplicate rows

    table1 = (('foo', 'bar'),
              ('A', 1),
              ('B', 2),
              ('B', 2),
              ('C', 7))

    table2 = (('foo', 'bar'),
              ('B', 2))

    result = complement_impl(table1, table2)
    expectation = (('foo', 'bar'),
                   ('A', 1),
                   ('B', 2),
                   ('C', 7))
    ieq(expectation, result)
    ieq(expectation, result)

    # strict behaviour
    result = complement_impl(table1, table2, strict=True)
    expectation = (('foo', 'bar'),
                   ('A', 1),
                   ('C', 7))
    ieq(expectation, result)
    ieq(expectation, result)


def _test_complement_none(complement_impl):
    # test behaviour with unsortable types
    now = datetime.now()

    ta = [['a', 'b'], [None, None]]
    tb = [['a', 'b'], [None, now]]

    expectation = (('a', 'b'), (None, None))
    result = complement_impl(ta, tb)
    ieq(expectation, result)

    ta = [['a'], [now], [None]]
    tb = [['a'], [None], [None]]

    expectation = (('a',), (now,))
    result = complement_impl(ta, tb)
    ieq(expectation, result)


def _test_complement(f):
    _test_complement_1(f)
    _test_complement_2(f)
    _test_complement_3(f)
    _test_complement_4(f)
    _test_complement_none(f)


def test_complement():
    _test_complement(complement)


def test_complement_seqtypes():
    # test complement isn't confused by list vs tuple
    ta = [['a', 'b'], ['A', 1], ['B', 2]]
    tb = [('a', 'b'), ('A', 1), ('B', 2)]
    expectation = (('a', 'b'),)
    actual = complement(ta, tb, presorted=True)
    ieq(expectation, actual)


def test_hashcomplement_seqtypes():
    # test complement isn't confused by list vs tuple
    ta = [['a', 'b'], ['A', 1], ['B', 2]]
    tb = [('a', 'b'), ('A', 1), ('B', 2)]
    expectation = (('a', 'b'),)
    actual = hashcomplement(ta, tb)
    ieq(expectation, actual)


def test_diff():

    tablea = (('foo', 'bar', 'baz'),
              ('A', 1, True),
              ('C', 7, False),
              ('B', 2, False),
              ('C', 9, True))

    tableb = (('x', 'y', 'z'),
              ('B', 2, False),
              ('A', 9, False),
              ('B', 3, True),
              ('C', 9, True))

    aminusb = (('foo', 'bar', 'baz'),
               ('A', 1, True),
               ('C', 7, False))

    bminusa = (('x', 'y', 'z'),
               ('A', 9, False),
               ('B', 3, True))

    added, subtracted = diff(tablea, tableb)
    ieq(bminusa, added)
    ieq(aminusb, subtracted)


def test_recordcomplement_1():

    table1 = (('foo', 'bar'),
              ('A', 1),
              ('B', 2),
              ('C', 7))

    table2 = (('bar', 'foo'),
              (9, 'A'),
              (2, 'B'),
              (3, 'B'))

    expectation = (('foo', 'bar'),
                   ('A', 1),
                   ('C', 7))

    result = recordcomplement(table1, table2)
    ieq(expectation, result)


def test_recordcomplement_2():

    tablea = (('foo', 'bar', 'baz'),
              ('A', 1, True),
              ('C', 7, False),
              ('B', 2, False),
              ('C', 9, True))

    tableb = (('bar', 'foo', 'baz'),
              (2, 'B', False),
              (9, 'A', False),
              (3, 'B', True),
              (9, 'C', True))

    aminusb = (('foo', 'bar', 'baz'),
               ('A', 1, True),
               ('C', 7, False))

    result = recordcomplement(tablea, tableb)
    ieq(aminusb, result)

    bminusa = (('bar', 'foo', 'baz'),
               (3, 'B', True),
               (9, 'A', False))

    result = recordcomplement(tableb, tablea)
    ieq(bminusa, result)


def test_recordcomplement_3():

    # make sure we deal with empty tables

    table1 = (('foo', 'bar'),
              ('A', 1),
              ('B', 2))

    table2 = (('bar', 'foo'),)

    expectation = (('foo', 'bar'),
                   ('A', 1),
                   ('B', 2))
    result = recordcomplement(table1, table2)
    ieq(expectation, result)
    ieq(expectation, result)

    expectation = (('bar', 'foo'),)
    result = recordcomplement(table2, table1)
    ieq(expectation, result)
    ieq(expectation, result)


def test_recordcomplement_4():

    # test behaviour with duplicate rows

    table1 = (('foo', 'bar'),
              ('A', 1),
              ('B', 2),
              ('B', 2),
              ('C', 7))

    table2 = (('bar', 'foo'),
              (2, 'B'))

    result = recordcomplement(table1, table2)
    expectation = (('foo', 'bar'),
                   ('A', 1),
                   ('B', 2),
                   ('C', 7))
    ieq(expectation, result)
    ieq(expectation, result)

    # strict behaviour
    result = recordcomplement(table1, table2, strict=True)
    expectation = (('foo', 'bar'),
                   ('A', 1),
                   ('C', 7))
    ieq(expectation, result)
    ieq(expectation, result)


def test_recorddiff():

    tablea = (('foo', 'bar', 'baz'),
              ('A', 1, True),
              ('C', 7, False),
              ('B', 2, False),
              ('C', 9, True))

    tableb = (('bar', 'foo', 'baz'),
              (2, 'B', False),
              (9, 'A', False),
              (3, 'B', True),
              (9, 'C', True))

    aminusb = (('foo', 'bar', 'baz'),
               ('A', 1, True),
               ('C', 7, False))

    bminusa = (('bar', 'foo', 'baz'),
               (3, 'B', True),
               (9, 'A', False))

    added, subtracted = recorddiff(tablea, tableb)
    ieq(aminusb, subtracted)
    ieq(bminusa, added)


def _test_intersection_1(intersection_impl):

    table1 = (('foo', 'bar'),
              ('A', 1),
              ('B', 2),
              ('C', 7))

    table2 = (('foo', 'bar'),
              ('A', 9),
              ('B', 2),
              ('B', 3))

    expectation = (('foo', 'bar'),
                   ('B', 2))

    result = intersection_impl(table1, table2)
    ieq(expectation, result)


def _test_intersection_2(intersection_impl):

    table1 = (('foo', 'bar', 'baz'),
              ('A', 1, True),
              ('C', 7, False),
              ('B', 2, False),
              ('C', 9, True))

    table2 = (('x', 'y', 'z'),
              ('B', 2, False),
              ('A', 9, False),
              ('B', 3, True),
              ('C', 9, True))

    expect = (('foo', 'bar', 'baz'),
              ('B', 2, False),
              ('C', 9, True))

    table3 = intersection_impl(table1, table2)
    ieq(expect, table3)


def _test_intersection_3(intersection_impl):

    # empty table
    table1 = (('foo', 'bar'),
              ('A', 1),
              ('B', 2),
              ('C', 7))

    table2 = (('foo', 'bar'),)

    expectation = (('foo', 'bar'),)
    result = intersection_impl(table1, table2)
    ieq(expectation, result)
    ieq(expectation, result)


def _test_intersection_4(intersection_impl):

    # duplicate rows

    table1 = (('foo', 'bar'),
              ('A', 1),
              ('B', 2),
              ('B', 2),
              ('B', 2),
              ('C', 7))

    table2 = (('foo', 'bar'),
              ('A', 9),
              ('B', 2),
              ('B', 2),
              ('B', 3))

    expectation = (('foo', 'bar'),
                   ('B', 2),
                   ('B', 2))

    result = intersection_impl(table1, table2)
    ieq(expectation, result)
    ieq(expectation, result)


def _test_intersection_empty(intersection_impl):

    table1 = (('foo', 'bar'),
              ('A', 1),
              ('B', 2),
              ('C', 7))
    table2 = (('foo', 'bar'),)
    expectation = (('foo', 'bar'),)
    result = intersection_impl(table1, table2)
    ieq(expectation, result)


def _test_intersection(intersection_impl):
    _test_intersection_1(intersection_impl)
    _test_intersection_2(intersection_impl)
    _test_intersection_3(intersection_impl)
    _test_intersection_4(intersection_impl)
    _test_intersection_empty(intersection_impl)


def test_intersection():
    _test_intersection(intersection)


def test_hashcomplement():
    _test_complement(hashcomplement)


def test_hashintersection():
    _test_intersection(hashintersection)


def test_divide():

    samples = (('sample', 'analyte'),
               ('S1', 'glucose'),
               ('S1', 'lactate'),
               ('S2', 'glucose'),
               ('S3', 'glucose'),
               ('S3', 'lactate'),
               ('S3', 'urea'))
    required = (('analyte',),
                ('glucose',),
                ('lactate',))
    expectation = (('sample',),
                   ('S1',),
                   ('S3',))
    result = divide(samples, required, key='sample')
    ieq(expectation, result)
    ieq(expectation, result)  # check repeatable


def test_divide_multiset():

    # duplicate items in the requirement demand matching multiplicity
    measurements = (('sample', 'control'),
                    ('S1', 'blank'),
                    ('S1', 'blank'),
                    ('S2', 'blank'))
    required = (('control',),
                ('blank',),
                ('blank',))

    # default multiset semantics
    expectation = (('sample',),
                   ('S1',))
    result = divide(measurements, required, key='sample')
    ieq(expectation, result)

    # set semantics ignore multiplicities
    expectation = (('sample',),
                   ('S1',),
                   ('S2',))
    result = divide(measurements, required, key='sample', multiset=False)
    ieq(expectation, result)


def test_divide_composite_keys():

    # composite entity key and composite item key
    table = (('patient', 'visit', 'analyte', 'method'),
             ('P1', 'V1', 'glucose', 'hexokinase'),
             ('P1', 'V1', 'lactate', 'enzymatic'),
             ('P1', 'V2', 'glucose', 'hexokinase'),
             ('P2', 'V1', 'glucose', 'hexokinase'),
             ('P2', 'V1', 'lactate', 'enzymatic'))
    required = (('analyte', 'method'),
                ('glucose', 'hexokinase'),
                ('lactate', 'enzymatic'))
    expectation = (('patient', 'visit'),
                   ('P1', 'V1'),
                   ('P2', 'V1'))
    result = divide(table, required, key=('patient', 'visit'),
                    rkey=('analyte', 'method'))
    ieq(expectation, result)


def test_divide_empty_requirement():

    samples = (('sample', 'analyte'),
               ('S1', 'glucose'),
               ('S2', 'lactate'))
    empty = (('analyte',),)

    # without candidates, entities come from the source table only
    expectation = (('sample',),
                   ('S1',),
                   ('S2',))
    result = divide(samples, empty, key='sample')
    ieq(expectation, result)

    # with candidates, all candidates qualify, even those with no rows
    # in the source table
    candidates = (('sample',),
                  ('S2',),
                  ('S9',))
    expectation = (('sample',),
                   ('S1',),
                   ('S2',),
                   ('S9',))
    result = divide(samples, empty, key='sample', candidates=candidates)
    ieq(expectation, result)


def test_divide_none_values():

    # None is an ordinary value: None matches None, nothing else
    table = (('sample', 'analyte'),
             ('S1', None),
             ('S1', 'glucose'),
             ('S2', 'glucose'))
    required = (('analyte',),
                (None,),
                ('glucose',))
    expectation = (('sample',),
                   ('S1',))
    result = divide(table, required, key='sample')
    ieq(expectation, result)


def test_divide_explain():

    samples = (('sample', 'analyte'),
               ('S1', 'glucose'),
               ('S1', 'lactate'),
               ('S2', 'glucose'),
               ('S3', 'glucose'),
               ('S3', 'lactate'),
               ('S3', 'urea'))
    required = (('analyte',),
                ('lactate',),
                ('lactate',),
                ('urea',))
    expectation = (('sample', 'qualified', 'missing', 'shortfall'),
                   ('S1', False, ['lactate', 'urea'], 2),
                   ('S2', False, ['lactate', 'lactate', 'urea'], 3),
                   ('S3', False, ['lactate'], 1))
    result = divide(samples, required, key='sample', explain=True)
    ieq(expectation, result)

    # candidates with no rows in the source miss everything
    candidates = (('sample',),
                  ('S1',),
                  ('S9',))
    expectation = (('sample', 'qualified', 'missing', 'shortfall'),
                   ('S1', False, ['lactate', 'urea'], 2),
                   ('S2', False, ['lactate', 'lactate', 'urea'], 3),
                   ('S3', False, ['lactate'], 1),
                   ('S9', False, ['lactate', 'lactate', 'urea'], 3))
    result = divide(samples, required, key='sample', candidates=candidates,
                    explain=True)
    ieq(expectation, result)


def test_divide_explain_set_semantics():

    samples = (('sample', 'analyte'),
               ('S1', 'glucose'),
               ('S2', 'glucose'),
               ('S2', 'lactate'))
    required = (('analyte',),
                ('lactate',),
                ('lactate',),
                ('urea',))
    # under set semantics each missing item is reported once
    expectation = (('sample', 'qualified', 'missing', 'shortfall'),
                   ('S1', False, ['lactate', 'urea'], 2),
                   ('S2', False, ['urea'], 1))
    result = divide(samples, required, key='sample', multiset=False,
                    explain=True)
    ieq(expectation, result)


def test_divide_rkey_default_and_subset():

    # rkey defaults to all fields of the requirement table
    samples = (('sample', 'analyte', 'lab'),
               ('S1', 'glucose', 'L1'),
               ('S1', 'glucose', 'L2'),
               ('S2', 'glucose', 'L1'))
    required = (('analyte', 'lab'),
                ('glucose', 'L1'),
                ('glucose', 'L2'))
    expectation = (('sample',),
                   ('S1',))
    result = divide(samples, required, key='sample')
    ieq(expectation, result)

    # an explicit rkey may select a subset of the requirement fields
    required = (('analyte', 'priority'),
                ('glucose', 'routine'))
    expectation = (('sample',),
                   ('S1',),
                   ('S2',))
    result = divide(samples, required, key='sample', rkey='analyte')
    ieq(expectation, result)
