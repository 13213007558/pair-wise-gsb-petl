from __future__ import absolute_import, print_function, division


from datetime import datetime
import subprocess
import sys

import pytest

from petl.errors import ArgumentError, FieldSelectionError
from petl.test.helpers import ieq
from petl.transform.reshape import melt, recast, transpose, pivot, flatten, \
    unflatten, _MISSING
from petl.transform.regex import split, capture


def test_melt_1():

    table = (('id', 'gender', 'age'),
             (1, 'F', 12),
             (2, 'M', 17),
             (3, 'M', 16))

    expectation = (('id', 'variable', 'value'),
                   (1, 'gender', 'F'),
                   (1, 'age', 12),
                   (2, 'gender', 'M'),
                   (2, 'age', 17),
                   (3, 'gender', 'M'),
                   (3, 'age', 16))

    result = melt(table, key='id')
    ieq(expectation, result)

    # use field index as key
    result = melt(table, key=0)
    ieq(expectation, result)

    result = melt(table, key='id', variablefield='variable', valuefield='value')
    ieq(expectation, result)


def test_melt_2():

    table = (('id', 'time', 'height', 'weight'),
             (1, 11, 66.4, 12.2),
             (2, 16, 53.2, 17.3),
             (3, 12, 34.5, 9.4))

    expectation = (('id', 'time', 'variable', 'value'),
                   (1, 11, 'height', 66.4),
                   (1, 11, 'weight', 12.2),
                   (2, 16, 'height', 53.2),
                   (2, 16, 'weight', 17.3),
                   (3, 12, 'height', 34.5),
                   (3, 12, 'weight', 9.4))
    result = melt(table, key=('id', 'time'))
    ieq(expectation, result)

    expectation = (('id', 'time', 'variable', 'value'),
                   (1, 11, 'height', 66.4),
                   (2, 16, 'height', 53.2),
                   (3, 12, 'height', 34.5))
    result = melt(table, key=('id', 'time'), variables='height')
    print(result)
    ieq(expectation, result)


def test_melt_empty():
    table = (('foo', 'bar', 'baz'),)
    expect = (('foo', 'variable', 'value'),)
    actual = melt(table, key='foo')
    ieq(expect, actual)


def test_melt_headerless():
    table = []
    expect = []
    actual = melt(table, key='foo')
    ieq(expect, actual)


def test_melt_1_shortrow():

    table = (('id', 'gender', 'age'),
             (1, 'F', 12),
             (2, 'M', 17),
             (3, 'M'),
             (4,))

    expectation = (('id', 'variable', 'value'),
                   (1, 'gender', 'F'),
                   (1, 'age', 12),
                   (2, 'gender', 'M'),
                   (2, 'age', 17),
                   (3, 'gender', 'M'))

    result = melt(table, key='id')
    ieq(expectation, result)

    result = melt(table, key='id', variablefield='variable', valuefield='value')
    ieq(expectation, result)


def test_melt_2_shortrow():

    table = (('id', 'time', 'height', 'weight'),
             (1, 11, 66.4, 12.2),
             (2, 16, 53.2, 17.3),
             (3, 12, 34.5),
             (4, 14))

    expectation = (('id', 'time', 'variable', 'value'),
                   (1, 11, 'height', 66.4),
                   (1, 11, 'weight', 12.2),
                   (2, 16, 'height', 53.2),
                   (2, 16, 'weight', 17.3),
                   (3, 12, 'height', 34.5))
    result = melt(table, key=('id', 'time'))
    ieq(expectation, result)

    expectation = (('id', 'time', 'variable', 'value'),
                   (1, 11, 'height', 66.4),
                   (2, 16, 'height', 53.2),
                   (3, 12, 'height', 34.5))
    result = melt(table, key=('id', 'time'), variables='height')
    ieq(expectation, result)


def test_melt_preserve():

    table = (('sample', 'signal', 'signal'),
             ('s1', 1.5, 1.5),
             ('s2', None, None),
             ('s3', 2.0, 2.0))

    expectation = (('sample', 'variable', 'value', 'rowid', 'position'),
                   ('s1', ('signal', 0), 1.5, 0, 1),
                   ('s1', ('signal', 1), 1.5, 0, 2),
                   ('s2', ('signal', 0), None, 1, 1),
                   ('s2', ('signal', 1), None, 1, 2),
                   ('s3', ('signal', 0), 2.0, 2, 1),
                   ('s3', ('signal', 1), 2.0, 2, 2))

    result = melt(table, key='sample', preserve=True)
    ieq(expectation, result)

    # custom field names
    expectation = (('sample', 'var', 'val', 'rid', 'pos'),
                   ('s1', ('signal', 0), 1.5, 0, 1),
                   ('s1', ('signal', 1), 1.5, 0, 2),
                   ('s2', ('signal', 0), None, 1, 1),
                   ('s2', ('signal', 1), None, 1, 2),
                   ('s3', ('signal', 0), 2.0, 2, 1),
                   ('s3', ('signal', 1), 2.0, 2, 2))

    result = melt(table, key='sample', preserve=True, variablefield='var',
                  valuefield='val', rowidfield='rid', positionfield='pos')
    ieq(expectation, result)


def test_melt_preserve_shortrow():

    table = (('sample', 'signal', 'signal'),
             ('s1', 1.5, 1.5),
             ('s2', 2.5),
             ('s3',))

    expectation = (('sample', 'variable', 'value', 'rowid', 'position'),
                   ('s1', ('signal', 0), 1.5, 0, 1),
                   ('s1', ('signal', 1), 1.5, 0, 2),
                   ('s2', ('signal', 0), 2.5, 1, 1),
                   ('s2', ('signal', 1), _MISSING, 1, 2),
                   ('s3', ('signal', 0), _MISSING, 2, 1),
                   ('s3', ('signal', 1), _MISSING, 2, 2))

    result = melt(table, key='sample', preserve=True)
    assert list(expectation) == list(result)


def test_melt_preserve_partial_variables():

    # melt only some of the duplicate fields, keeping the others as key
    table = (('sample', 'signal', 'signal'),
             ('s1', 1.5, 7.5),
             ('s2', 2.5, 8.5))

    expectation = (('sample', 'signal', 'variable', 'value', 'rowid',
                    'position'),
                   ('s1', 1.5, ('signal', 1), 7.5, 0, 2),
                   ('s2', 2.5, ('signal', 1), 8.5, 1, 2))

    result = melt(table, variables=[2], preserve=True)
    ieq(expectation, result)

    # melt the first duplicate field, keeping the second as key
    expectation = (('sample', 'signal', 'variable', 'value', 'rowid',
                    'position'),
                   ('s1', 7.5, ('signal', 0), 1.5, 0, 1),
                   ('s2', 8.5, ('signal', 0), 2.5, 1, 1))

    result = melt(table, key=['sample', 2], variables=[1], preserve=True)
    ieq(expectation, result)


def test_melt_recast_preserve_roundtrip():

    # duplicate field names, identical values in both duplicate fields,
    # empty cells and short rows must all survive the round trip
    table = (('sample', 'signal', 'signal'),
             ('s1', 1.5, 1.5),
             ('s2', None, None),
             ('s3', 2.0, 2.0),
             ('s4', 3.0),
             ('s5',))

    result = recast(melt(table, key='sample', preserve=True), preserve=True)
    assert list(table) == list(result)

    # also works when every field is melted, with interleaved duplicates
    table = (('signal', 'sample', 'signal'),
             (1.5, 's1', 1.5),
             (None, 's2', None),
             (2.0, 's3', 2.0),
             (3.0, 's4'))

    result = recast(melt(table, variables=['signal', 'sample', 'signal'],
                         preserve=True),
                    preserve=True)
    assert list(table) == list(result)


def test_melt_recast_preserve_roundtrip_partial():

    # melt only one of the duplicate fields, keeping the other as key
    table = (('sample', 'signal', 'signal'),
             ('s1', 1.5, 7.5),
             ('s2', None, 8.5),
             ('s3', 3.0))

    result = recast(melt(table, variables=[2], preserve=True), preserve=True)
    assert list(table) == list(result)

    result = recast(melt(table, key=['sample', 2], variables=[1],
                         preserve=True),
                    preserve=True)
    assert list(table) == list(result)


def test_melt_recast_preserve_roundtrip_disk_sort():

    # the missing-cell sentinel must survive rows being buffered to disk
    # when sorting by row identity during recast
    import petl.config

    table = (('sample', 'signal', 'signal'),
             ('s1', 1.5, 1.5),
             ('s2', 2.5),
             ('s3',))

    buffersize = petl.config.sort_buffersize
    try:
        petl.config.sort_buffersize = 2
        result = recast(melt(table, key='sample', preserve=True),
                        preserve=True)
        assert list(table) == list(result)
    finally:
        petl.config.sort_buffersize = buffersize


def test_melt_recast_preserve_custom_fields():

    table = (('sample', 'signal', 'signal'),
             ('s1', 1.5, 1.5),
             ('s2', None, 2.5),
             ('s3',))

    molten = melt(table, key='sample', preserve=True, variablefield='var',
                  valuefield='val', rowidfield='rid', positionfield='pos')
    result = recast(molten, preserve=True, variablefield='var',
                    valuefield='val', rowidfield='rid', positionfield='pos')
    assert list(table) == list(result)


def test_recast_preserve_invalid_fields():

    table = (('sample', 'variable', 'value', 'rowid', 'position'),
             ('s1', ('signal', 0), 1.5, 0, 1))

    with pytest.raises(ArgumentError):
        list(recast(table, preserve=True, variablefield='nope'))
    with pytest.raises(ArgumentError):
        list(recast(table, preserve=True, rowidfield='nope'))
    with pytest.raises(ArgumentError):
        # bookkeeping fields must be distinct
        list(recast(table, preserve=True, rowidfield='position'))
    with pytest.raises(ArgumentError):
        # key cannot be a bookkeeping field
        list(recast(table, preserve=True, key='position'))


def test_recast_1():

    table = (('id', 'variable', 'value'),
             (3, 'age', 16),
             (1, 'gender', 'F'),
             (2, 'gender', 'M'),
             (2, 'age', 17),
             (1, 'age', 12),
             (3, 'gender', 'M'))

    expectation = (('id', 'age', 'gender'),
                   (1, 12, 'F'),
                   (2, 17, 'M'),
                   (3, 16, 'M'))

    # by default lift 'variable' field, hold everything else
    result = recast(table)
    ieq(expectation, result)

    result = recast(table, variablefield='variable')
    ieq(expectation, result)

    result = recast(table, key='id', variablefield='variable')
    ieq(expectation, result)

    result = recast(table, key='id', variablefield='variable',
                    valuefield='value')
    ieq(expectation, result)


def test_recast_2():

    table = (('id', 'variable', 'value'),
             (3, 'age', 16),
             (1, 'gender', 'F'),
             (2, 'gender', 'M'),
             (2, 'age', 17),
             (1, 'age', 12),
             (3, 'gender', 'M'))

    expectation = (('id', 'gender'),
                   (1, 'F'),
                   (2, 'M'),
                   (3, 'M'))

    # can manually pick which variables you want to recast as fields
    # TODO this is awkward
    result = recast(table, key='id', variablefield={'variable': ['gender']})
    ieq(expectation, result)


def test_recast_3():

    table = (('id', 'time', 'variable', 'value'),
             (1, 11, 'weight', 66.4),
             (1, 14, 'weight', 55.2),
             (2, 12, 'weight', 53.2),
             (2, 16, 'weight', 43.3),
             (3, 12, 'weight', 34.5),
             (3, 17, 'weight', 49.4))

    expectation = (('id', 'time', 'weight'),
                   (1, 11, 66.4),
                   (1, 14, 55.2),
                   (2, 12, 53.2),
                   (2, 16, 43.3),
                   (3, 12, 34.5),
                   (3, 17, 49.4))
    result = recast(table)
    ieq(expectation, result)

    # in the absence of an aggregation function, list all values
    expectation = (('id', 'weight'),
                   (1, [66.4, 55.2]),
                   (2, [53.2, 43.3]),
                   (3, [34.5, 49.4]))
    result = recast(table, key='id')
    ieq(expectation, result)

    # max aggregation
    expectation = (('id', 'weight'),
                   (1, 66.4),
                   (2, 53.2),
                   (3, 49.4))
    result = recast(table, key='id', reducers={'weight': max})
    ieq(expectation, result)

    # min aggregation
    expectation = (('id', 'weight'),
                   (1, 55.2),
                   (2, 43.3),
                   (3, 34.5))
    result = recast(table, key='id', reducers={'weight': min})
    ieq(expectation, result)

    # mean aggregation
    expectation = (('id', 'weight'),
                   (1, 60.80),
                   (2, 48.25),
                   (3, 41.95))

    def mean(values):
        return float(sum(values)) / len(values)

    def meanf(precision):
        def f(values):
            v = mean(values)
            v = round(v, precision)
            return v
        return f

    result = recast(table, key='id', reducers={'weight': meanf(precision=2)})
    ieq(expectation, result)


def test_recast4():

    # deal with missing data
    table = (('id', 'variable', 'value'),
             (1, 'gender', 'F'),
             (2, 'age', 17),
             (1, 'age', 12),
             (3, 'gender', 'M'))
    result = recast(table, key='id')
    expect = (('id', 'age', 'gender'),
              (1, 12, 'F'),
              (2, 17, None),
              (3, None, 'M'))
    ieq(expect, result)


def test_recast_empty():
    table = (('foo', 'variable', 'value'),)
    expect = (('foo',),)
    actual = recast(table)
    ieq(expect, actual)


def test_recast_headerless():
    table = []
    expect = []
    actual = recast(table)
    ieq(expect, actual)


def test_recast_date():

    dt = datetime.now().replace
    table = (('id', 'variable', 'value'),
             (dt(hour=3), 'age', 16),
             (dt(hour=1), 'gender', 'F'),
             (dt(hour=2), 'gender', 'M'),
             (dt(hour=2), 'age', 17),
             (dt(hour=1), 'age', 12),
             (dt(hour=3), 'gender', 'M'))

    expectation = (('id', 'age', 'gender'),
                   (dt(hour=1), 12, 'F'),
                   (dt(hour=2), 17, 'M'),
                   (dt(hour=3), 16, 'M'))

    # by default lift 'variable' field, hold everything else
    result = recast(table)
    ieq(expectation, result)

    result = recast(table, variablefield='variable')
    ieq(expectation, result)

    result = recast(table, key='id', variablefield='variable')
    ieq(expectation, result)

    result = recast(table, key='id', variablefield='variable',
                    valuefield='value')
    ieq(expectation, result)


def test_melt_and_capture():

    table = (('id', 'parad0', 'parad1', 'parad2'),
             ('1', '12', '34', '56'),
             ('2', '23', '45', '67'))

    expectation = (('id', 'parasitaemia', 'day'),
                   ('1', '12', '0'),
                   ('1', '34', '1'),
                   ('1', '56', '2'),
                   ('2', '23', '0'),
                   ('2', '45', '1'),
                   ('2', '67', '2'))

    step1 = melt(table, key='id', valuefield='parasitaemia')
    step2 = capture(step1, 'variable', 'parad(\\d+)', ('day',))
    ieq(expectation, step2)


def test_melt_and_split():

    table = (('id', 'parad0', 'parad1', 'parad2', 'tempd0', 'tempd1', 'tempd2'),
             ('1', '12', '34', '56', '37.2', '37.4', '37.9'),
             ('2', '23', '45', '67', '37.1', '37.8', '36.9'))

    expectation = (('id', 'value', 'variable', 'day'),
                   ('1', '12', 'para', '0'),
                   ('1', '34', 'para', '1'),
                   ('1', '56', 'para', '2'),
                   ('1', '37.2', 'temp', '0'),
                   ('1', '37.4', 'temp', '1'),
                   ('1', '37.9', 'temp', '2'),
                   ('2', '23', 'para', '0'),
                   ('2', '45', 'para', '1'),
                   ('2', '67', 'para', '2'),
                   ('2', '37.1', 'temp', '0'),
                   ('2', '37.8', 'temp', '1'),
                   ('2', '36.9', 'temp', '2'))

    step1 = melt(table, key='id')
    step2 = split(step1, 'variable', 'd', ('variable', 'day'))
    ieq(expectation, step2)


def test_transpose():
    table1 = (('id', 'colour'),
              (1, 'blue'),
              (2, 'red'),
              (3, 'purple'),
              (5, 'yellow'),
              (7, 'orange'))
    table2 = transpose(table1)
    expect2 = (('id', 1, 2, 3, 5, 7),
               ('colour', 'blue', 'red', 'purple', 'yellow', 'orange'))
    ieq(expect2, table2)
    ieq(expect2, table2)


def test_transpose_empty():
    table1 = (('id', 'colour'),)
    table2 = transpose(table1)
    expect2 = (('id',),
               ('colour',))
    ieq(expect2, table2)


def test_pivot():

    table1 = (('region', 'gender', 'style', 'units'),
              ('east', 'boy', 'tee', 12),
              ('east', 'boy', 'golf', 14),
              ('east', 'boy', 'fancy', 7),
              ('east', 'girl', 'tee', 3),
              ('east', 'girl', 'golf', 8),
              ('east', 'girl', 'fancy', 18),
              ('west', 'boy', 'tee', 12),
              ('west', 'boy', 'golf', 15),
              ('west', 'boy', 'fancy', 8),
              ('west', 'girl', 'tee', 6),
              ('west', 'girl', 'golf', 16),
              ('west', 'girl', 'fancy', 1))

    table2 = pivot(table1, 'region', 'gender', 'units', sum)
    expect2 = (('region', 'boy', 'girl'),
               ('east', 33, 29),
               ('west', 35, 23))
    ieq(expect2, table2)
    ieq(expect2, table2)


def test_pivot_empty():

    table1 = (('region', 'gender', 'style', 'units'),)
    table2 = pivot(table1, 'region', 'gender', 'units', sum)
    expect2 = (('region',),)
    ieq(expect2, table2)


def test_pivot_headerless():
    table1 = []
    with pytest.raises(FieldSelectionError):
        for i in pivot(table1, 'region', 'gender', 'units', sum):
            pass


def test_flatten():

    table1 = (('foo', 'bar', 'baz'),
              ('A', 1, True),
              ('C', 7, False),
              ('B', 2, False),
              ('C', 9, True))

    expect1 = ('A', 1, True, 'C', 7, False, 'B', 2, False, 'C', 9, True)

    actual1 = flatten(table1)
    ieq(expect1, actual1)
    ieq(expect1, actual1)


def test_flatten_empty():

    table1 = (('foo', 'bar', 'baz'),)
    expect1 = []
    actual1 = flatten(table1)
    ieq(expect1, actual1)


def test_flatten_headerless():
    table1 = []
    expect1 = []
    actual1 = flatten(table1)
    ieq(expect1, actual1)


def test_unflatten():

    table1 = (('lines',),
              ('A',),
              (1,),
              (True,),
              ('C',),
              (7,),
              (False,),
              ('B',),
              (2,),
              (False,),
              ('C',),
              (9,))

    expect1 = (('f0', 'f1', 'f2'),
               ('A', 1, True),
               ('C', 7, False),
               ('B', 2, False),
               ('C', 9, None))

    actual1 = unflatten(table1, 'lines', 3)

    ieq(expect1, actual1)
    ieq(expect1, actual1)


def test_unflatten_2():

    inpt = ('A', 1, True, 'C', 7, False, 'B', 2, False, 'C', 9)

    expect1 = (('f0', 'f1', 'f2'),
               ('A', 1, True),
               ('C', 7, False),
               ('B', 2, False),
               ('C', 9, None))

    actual1 = unflatten(inpt, 3)

    ieq(expect1, actual1)
    ieq(expect1, actual1)


def test_unflatten_empty():

    table1 = (('lines',),)
    expect1 = (('f0', 'f1', 'f2'),)
    actual1 = unflatten(table1, 'lines', 3)
    ieq(expect1, actual1)


@pytest.mark.parametrize('header,kwargs,message', [
    ((), {}, 'invalid value field: value'),
    (('id', 'variable', 'value'), {'valuefield': 'missing'},
     'invalid value field: missing'),
    (('id', 'variable', 'value'), {'key': 'missing'},
     'invalid key field: missing'),
    (('id', 'variable', 'value'), {'variablefield': 'missing'},
     'invalid variable field: missing'),
    (('id', 'variable', 'value'), {'variablefield': {'missing': ['x']}},
     'invalid variable field: missing'),
    (('id', 'variable', 'value'), {'key': ['id', 'value']},
     'value field cannot be a key field'),
    (('id', 'variable', 'value'), {'variablefield': ['variable', 'value']},
     'value field cannot be a variable field'),
])
def test_recast_invalid_fields(header, kwargs, message):
    with pytest.raises(ArgumentError) as exc:
        list(recast([header], **kwargs))
    assert str(exc.value) == 'argument error: ' + message


def test_recast_validation_with_optimization():
    code = """
from petl import empty, recast
from petl.errors import ArgumentError
try:
    list(recast(empty()))
except ArgumentError:
    pass
else:
    raise RuntimeError('recast accepted a missing value field')
"""
    subprocess.check_call([sys.executable, '-O', '-c', code])
