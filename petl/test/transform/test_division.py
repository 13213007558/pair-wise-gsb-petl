from __future__ import absolute_import, division, print_function

import pytest

from petl import divide, dividemissing, wrap
from petl.errors import ArgumentError
from petl.test.helpers import ieq


def _samples():
    return (('sample', 'test'),
            ('s1', 'glucose'),
            ('s1', 'sodium'),
            ('s1', 'sodium'),
            ('s2', 'glucose'),
            ('s3', 'glucose'),
            ('s3', 'sodium'))


def test_divide_basic():
    source = _samples()
    requirement = (('test',), ('glucose',), ('sodium',))
    actual = divide(source, requirement, entity='sample', item='test')
    expect = (('sample',), ('s1',), ('s3',))
    ieq(expect, actual)
    ieq(expect, actual)  # check twice


def test_divide_default_item_fields():
    # item defaults to all non-entity fields
    source = _samples()
    requirement = (('test',), ('glucose',), ('sodium',))
    actual = divide(source, requirement, entity='sample')
    expect = (('sample',), ('s1',), ('s3',))
    ieq(expect, actual)


def test_divide_multiset_semantics():
    # s1 has sodium twice, s3 only once
    source = _samples()
    requirement = (('test',), ('glucose',), ('sodium',), ('sodium',))
    actual = divide(source, requirement, entity='sample', item='test')
    expect = (('sample',), ('s1',),)
    ieq(expect, actual)


def test_divide_set_semantics():
    # duplicates in the requirement are ignored under set semantics
    source = _samples()
    requirement = (('test',), ('glucose',), ('sodium',), ('sodium',))
    actual = divide(source, requirement, entity='sample', item='test',
                    semantics='set')
    expect = (('sample',), ('s1',), ('s3',))
    ieq(expect, actual)


def test_divide_compound_entity_key():
    source = (('lab', 'sample', 'test'),
              ('L1', 's1', 'glucose'),
              ('L1', 's1', 'sodium'),
              ('L1', 's2', 'glucose'),
              ('L2', 's1', 'glucose'),
              ('L2', 's1', 'sodium'))
    requirement = (('test',), ('glucose',), ('sodium',))
    actual = divide(source, requirement, entity=('lab', 'sample'),
                    item='test')
    expect = (('lab', 'sample'),
              ('L1', 's1'),
              ('L2', 's1'))
    ieq(expect, actual)


def test_divide_compound_item_key():
    source = (('sample', 'test', 'method'),
              ('s1', 'glucose', 'A'),
              ('s1', 'glucose', 'B'),
              ('s2', 'glucose', 'A'))
    requirement = (('assay', 'method'),
                   ('glucose', 'A'),
                   ('glucose', 'B'))
    actual = divide(source, requirement, entity='sample',
                    item=('test', 'method'), ritem=('assay', 'method'))
    expect = (('sample',), ('s1',),)
    ieq(expect, actual)


def test_divide_empty_requirement_with_candidates():
    source = _samples()
    requirement = (('test',),)
    # s4 has no rows at all in the source table
    candidates = (('sample',), ('s1',), ('s2',), ('s3',), ('s4',), ('s2',))
    actual = divide(source, requirement, entity='sample', item='test',
                    candidates=candidates)
    expect = (('sample',), ('s1',), ('s2',), ('s3',), ('s4',))
    ieq(expect, actual)


def test_divide_empty_requirement_no_candidates():
    source = _samples()
    requirement = (('test',),)
    actual = divide(source, requirement, entity='sample', item='test')
    expect = (('sample',), ('s1',), ('s2',), ('s3',))
    ieq(expect, actual)


def test_divide_candidates_restrict_universe():
    source = _samples()
    requirement = (('test',), ('glucose',), ('sodium',))
    # s3 qualifies but is not a candidate; s4 has no source rows
    candidates = (('sample',), ('s1',), ('s4',))
    actual = divide(source, requirement, entity='sample', item='test',
                    candidates=candidates)
    expect = (('sample',), ('s1',),)
    ieq(expect, actual)


def test_divide_null_equals_default():
    # by default None matches None
    source = (('sample', 'test'),
              ('s1', 'glucose'),
              ('s1', None),
              ('s2', 'glucose'))
    requirement = (('test',), ('glucose',), (None,))
    actual = divide(source, requirement, entity='sample', item='test')
    expect = (('sample',), ('s1',),)
    ieq(expect, actual)


def test_divide_null_not_equals():
    # with null_equals=False, rows with None item keys never match
    source = (('sample', 'test'),
              ('s1', 'glucose'),
              ('s1', None),
              ('s2', 'glucose'))
    requirement = (('test',), ('glucose',), (None,))
    actual = divide(source, requirement, entity='sample', item='test',
                    null_equals=False)
    # the None requirement is dropped, so only glucose is required
    expect = (('sample',), ('s1',), ('s2',))
    ieq(expect, actual)


def test_divide_bad_arguments():
    source = _samples()
    requirement = (('test',), ('glucose',))
    with pytest.raises(ArgumentError):
        divide(source, requirement, entity='sample', item='test',
               semantics='bag')
    with pytest.raises(ArgumentError):
        list(divide(source, requirement, item='test'))


def test_dividemissing_basic():
    source = (('sample', 'test'),
              ('s1', 'glucose'),
              ('s1', 'sodium'),
              ('s2', 'glucose'),
              ('s2', 'sodium'),
              ('s2', 'sodium'))
    requirement = (('test',), ('glucose',), ('sodium',), ('sodium',))
    actual = dividemissing(source, requirement, entity='sample', item='test')
    expect = (('sample', 'test', 'missing'),
              ('s1', 'sodium', 1))
    ieq(expect, actual)
    ieq(expect, actual)  # check twice


def test_dividemissing_set_semantics():
    source = (('sample', 'test'),
              ('s1', 'glucose'),
              ('s2', 'sodium'))
    requirement = (('test',), ('glucose',), ('sodium',), ('sodium',))
    actual = dividemissing(source, requirement, entity='sample', item='test',
                           semantics='set')
    expect = (('sample', 'test', 'missing'),
              ('s1', 'sodium', 1),
              ('s2', 'glucose', 1))
    ieq(expect, actual)


def test_dividemissing_with_candidates():
    source = (('sample', 'test'),
              ('s1', 'glucose'))
    requirement = (('test',), ('glucose',), ('sodium',))
    # s2 has no rows in source, so everything is missing for s2
    candidates = (('sample',), ('s1',), ('s2',))
    actual = dividemissing(source, requirement, entity='sample', item='test',
                           candidates=candidates)
    expect = (('sample', 'test', 'missing'),
              ('s1', 'sodium', 1),
              ('s2', 'glucose', 1),
              ('s2', 'sodium', 1))
    ieq(expect, actual)


def test_dividemissing_compound_keys():
    source = (('lab', 'sample', 'test', 'method'),
              ('L1', 's1', 'glucose', 'A'))
    requirement = (('assay', 'method'),
                   ('glucose', 'A'),
                   ('glucose', 'B'))
    actual = dividemissing(source, requirement, entity=('lab', 'sample'),
                           item=('test', 'method'),
                           ritem=('assay', 'method'))
    expect = (('lab', 'sample', 'test', 'method', 'missing'),
              ('L1', 's1', 'glucose', 'B', 1))
    ieq(expect, actual)


def test_dividemissing_empty_requirement():
    source = _samples()
    requirement = (('test',),)
    actual = dividemissing(source, requirement, entity='sample', item='test')
    expect = (('sample', 'test', 'missing'),)
    ieq(expect, actual)


def test_divide_fluent():
    source = wrap(_samples())
    requirement = (('test',), ('glucose',), ('sodium',))
    actual = source.divide(requirement, entity='sample', item='test')
    expect = (('sample',), ('s1',), ('s3',))
    ieq(expect, actual)
    actual = source.dividemissing(requirement, entity='sample', item='test')
    expect = (('sample', 'test', 'missing'),
              ('s2', 'sodium', 1))
    ieq(expect, actual)
