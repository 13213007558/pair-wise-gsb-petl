# -*- coding: utf-8 -*-
from __future__ import absolute_import, print_function, division


import logging

import pytest

import petl as etl
from petl.transform.validation import validate, validate_relations
from petl.test.helpers import ieq
from petl.errors import ArgumentError, FieldSelectionError


logger = logging.getLogger(__name__)
debug = logger.debug


def test_constraints():

    constraints = [
        dict(name='C1', field='foo', test=int),
        dict(name='C2', field='bar', test=etl.dateparser('%Y-%m-%d')),
        dict(name='C3', field='baz', assertion=lambda v: v in ['Y', 'N']),
        dict(name='C4', assertion=lambda row: None not in row)
    ]

    table = (('foo', 'bar', 'baz'),
             (1, '2000-01-01', 'Y'),
             ('x', '2010-10-10', 'N'),
             (2, '2000/01/01', 'Y'),
             (3, '2015-12-12', 'x'),
             (4, None, 'N'),
             ('y', '1999-99-99', 'z'))

    expect = (('name', 'row', 'field', 'value', 'error'),
              ('C1', 2, 'foo', 'x', 'ValueError'),
              ('C2', 3, 'bar', '2000/01/01', 'ValueError'),
              ('C3', 4, 'baz', 'x', 'AssertionError'),
              ('C2', 5, 'bar', None, 'AttributeError'),
              ('C4', 5, None, None, 'AssertionError'),
              ('C1', 6, 'foo', 'y', 'ValueError'),
              ('C2', 6, 'bar', '1999-99-99', 'ValueError'),
              ('C3', 6, 'baz', 'z', 'AssertionError'))

    actual = validate(table, constraints)
    debug(actual)

    ieq(expect, actual)
    ieq(expect, actual)


def test_non_optional_constraint_with_missing_field():
    constraints = [
        dict(name='C1', field='foo', test=int),
    ]

    table = (('bar', 'baz'),
             ('1999-99-99', 'z'))

    actual = validate(table, constraints)
    with pytest.raises(FieldSelectionError):
        debug(actual)


def test_optional_constraint_with_missing_field():
    constraints = [
        dict(name='C1', field='foo', test=int, optional=True),
    ]

    table = (('bar', 'baz'),
             ('1999-99-99', 'z'))

    expect = (('name', 'row', 'field', 'value', 'error'),)

    actual = validate(table, constraints)
    debug(actual)

    ieq(expect, actual)


def test_row_length():

    table = (('foo', 'bar', 'baz'),
             (1, '2000-01-01', 'Y'),
             ('x', '2010-10-10'),
             (2, '2000/01/01', 'Y', True))

    expect = (('name', 'row', 'field', 'value', 'error'),
              ('__len__', 2, None, 2, 'AssertionError'),
              ('__len__', 3, None, 4, 'AssertionError'))

    actual = validate(table)
    debug(actual)

    ieq(expect, actual)
    ieq(expect, actual)


def test_header():

    header = ('foo', 'bar', 'baz')

    table = (('foo', 'bar', 'bazzz'),
             (1, '2000-01-01', 'Y'),
             ('x', '2010-10-10', 'N'))

    expect = (('name', 'row', 'field', 'value', 'error'),
              ('__header__', 0, None, None, 'AssertionError'))

    actual = validate(table, header=header)
    debug(actual)

    ieq(expect, actual)
    ieq(expect, actual)

    header = ('foo', 'bar', 'baz', 'quux')

    table = (('foo', 'bar', 'baz'),
             (1, '2000-01-01', 'Y'),
             ('x', '2010-10-10', 'N'))

    expect = (('name', 'row', 'field', 'value', 'error'),
              ('__header__', 0, None, None, 'AssertionError'),
              ('__len__', 1, None, 3, 'AssertionError'),
              ('__len__', 2, None, 3, 'AssertionError'))

    actual = validate(table, header=header)
    debug(actual)

    ieq(expect, actual)
    ieq(expect, actual)


def test_validation_headerless():
    header = ('foo', 'bar', 'baz')
    table = []
    # Expect only a missing header - no exceptions please
    expect = (('name', 'row', 'field', 'value', 'error'),
              ('__header__', 0, None, None, 'AssertionError'))
    actual = validate(table, header=header)
    ieq(expect, actual)
    ieq(expect, actual)


def _relational_tables():
    # two mutually referencing tables, plus a third table with null and
    # duplicate keys
    authors = (("author_id", "name"),
               (1, "Ann"),
               (2, "Bob"))
    books = (("book_id", "author_id"),
             (10, 1),
             (11, 2),
             (12, 99))
    tags = (("tag", "book_id"),
            ("x", 10),
            ("x", 10),
            ("y", None),
            ("z", 77))
    return authors, books, tags


def test_validate_relations_mutual_foreign_keys():
    authors, books, tags = _relational_tables()
    tables = {"authors": authors, "books": books, "tags": tags}
    constraints = [
        dict(name="fk_books_authors", type="foreign_key", table="books",
             fields="author_id", references="authors",
             ref_fields="author_id"),
        dict(name="fk_tags_books", type="foreign_key", table="tags",
             fields="book_id", references="books", ref_fields="book_id"),
    ]
    expect = (("name", "table", "row", "fields", "value",
               "ref_table", "ref_fields", "error"),
              ("fk_books_authors", "books", 3, ("author_id",), (99,),
              "authors", ("author_id",), "ForeignKeyViolation"),
              ("fk_tags_books", "tags", 4, ("book_id",), (77,),
               "books", ("book_id",), "ForeignKeyViolation"))
    actual = validate_relations(tables, constraints)
    debug(actual)
    ieq(expect, actual)
    ieq(expect, actual)


def test_validate_relations_composite_unique():
    table = (("a", "b", "v"),
             (1, "x", 10),
             (1, "x", 20),
             (2, "y", 30),
             (2, "y", 40),
             (2, "y", 50),
             (3, "z", 60))
    constraints = [dict(name="pk", type="unique", table="t",
                        fields=("a", "b"))]
    expect = (("name", "table", "row", "fields", "value",
               "ref_table", "ref_fields", "error"),
              ("pk", "t", 1, ("a", "b"), (1, "x"), None, None,
               "UniqueViolation"),
              ("pk", "t", 2, ("a", "b"), (1, "x"), None, None,
               "UniqueViolation"),
              ("pk", "t", 3, ("a", "b"), (2, "y"), None, None,
               "UniqueViolation"),
              ("pk", "t", 4, ("a", "b"), (2, "y"), None, None,
               "UniqueViolation"),
              ("pk", "t", 5, ("a", "b"), (2, "y"), None, None,
               "UniqueViolation"))
    actual = validate_relations({"t": table}, constraints)
    debug(actual)
    ieq(expect, actual)
    ieq(expect, actual)


def test_validate_relations_target_duplicates_not_masked():
    # duplicate keys in the referenced table must be reported, not masked
    # by arbitrarily matching the first row
    parents = (("p1", "p2"),
               (1, "a"),
               (1, "a"),
               (2, "b"))
    children = (("c1", "c2"),
                (1, "a"),
                (2, "b"))
    constraints = [
        dict(name="fk", type="foreign_key", table="children",
             fields=("c1", "c2"), references="parents",
             ref_fields=("p1", "p2")),
    ]
    expect = (("name", "table", "row", "fields", "value",
               "ref_table", "ref_fields", "error"),
              ("fk", "parents", 1, ("p1", "p2"), (1, "a"), None, None,
               "UniqueViolation"),
              ("fk", "parents", 2, ("p1", "p2"), (1, "a"), None, None,
               "UniqueViolation"))
    actual = validate_relations(
        {"parents": parents, "children": children}, constraints)
    debug(actual)
    ieq(expect, actual)
    ieq(expect, actual)


def test_validate_relations_nulls_ignored_by_default():
    parents = (("p1", "p2"),
               (1, "a"),
               (2, "b"))
    children = (("c1", "c2"),
                (1, "a"),
                (None, "a"),
                (None, None),
                (3, "c"))
    constraints = [
        dict(name="fk", type="foreign_key", table="children",
             fields=("c1", "c2"), references="parents",
             ref_fields=("p1", "p2")),
    ]
    expect = (("name", "table", "row", "fields", "value",
               "ref_table", "ref_fields", "error"),
              ("fk", "children", 4, ("c1", "c2"), (3, "c"),
               "parents", ("p1", "p2"), "ForeignKeyViolation"))
    actual = validate_relations(
        {"parents": parents, "children": children}, constraints)
    debug(actual)
    ieq(expect, actual)
    ieq(expect, actual)


def test_validate_relations_nulls_forbidden():
    parents = (("p1", "p2"),
               (1, "a"),
               (2, "b"))
    children = (("c1", "c2"),
                (1, "a"),
                (None, "a"),
                (None, None),
                (3, "c"))
    constraints = [
        dict(name="fk", type="foreign_key", table="children",
             fields=("c1", "c2"), references="parents",
             ref_fields=("p1", "p2"), nulls="forbid"),
    ]
    expect = (("name", "table", "row", "fields", "value",
               "ref_table", "ref_fields", "error"),
              ("fk", "children", 3, ("c1", "c2"), (None, None),
               "parents", ("p1", "p2"), "NullKeyViolation"),
              ("fk", "children", 2, ("c1", "c2"), (None, "a"),
               "parents", ("p1", "p2"), "NullKeyViolation"),
              ("fk", "children", 4, ("c1", "c2"), (3, "c"),
               "parents", ("p1", "p2"), "ForeignKeyViolation"))
    actual = validate_relations(
        {"parents": parents, "children": children}, constraints)
    debug(actual)
    ieq(expect, actual)
    ieq(expect, actual)


def test_validate_relations_iterator_tables():
    # tables given as one-shot iterators, referenced by more than one
    # constraint, must only be consumed once
    authors, books, tags = _relational_tables()
    tables = [("authors", iter(authors)),
              ("books", iter(books)),
              ("tags", iter(tags))]
    constraints = [
        dict(name="pk_books", type="unique", table="books",
             fields="book_id"),
        dict(name="fk_books_authors", type="foreign_key", table="books",
             fields="author_id", references="authors",
             ref_fields="author_id"),
        dict(name="fk_tags_books", type="foreign_key", table="tags",
             fields="book_id", references="books", ref_fields="book_id"),
    ]
    expect = (("name", "table", "row", "fields", "value",
               "ref_table", "ref_fields", "error"),
              ("fk_books_authors", "books", 3, ("author_id",), (99,),
               "authors", ("author_id",), "ForeignKeyViolation"),
              ("fk_tags_books", "tags", 4, ("book_id",), (77,),
              "books", ("book_id",), "ForeignKeyViolation"))
    actual = validate_relations(tables, constraints)
    ieq(expect, actual)


def test_validate_relations_disk_spill(tmp_path):
    # force the sort to spill to temporary files to exercise the disk
    # backed cache path
    authors, books, tags = _relational_tables()
    tables = {"authors": authors, "books": books, "tags": tags}
    constraints = [
        dict(name="pk_tags", type="unique", table="tags",
             fields=("tag", "book_id")),
        dict(name="fk_books_authors", type="foreign_key", table="books",
             fields="author_id", references="authors",
             ref_fields="author_id"),
        dict(name="fk_tags_books", type="foreign_key", table="tags",
             fields="book_id", references="books", ref_fields="book_id"),
    ]
    expect = (("name", "table", "row", "fields", "value",
               "ref_table", "ref_fields", "error"),
              ("pk_tags", "tags", 1, ("tag", "book_id"), ("x", 10),
               None, None, "UniqueViolation"),
              ("pk_tags", "tags", 2, ("tag", "book_id"), ("x", 10),
               None, None, "UniqueViolation"),
              ("fk_books_authors", "books", 3, ("author_id",), (99,),
               "authors", ("author_id",), "ForeignKeyViolation"),
              ("fk_tags_books", "tags", 4, ("book_id",), (77,),
               "books", ("book_id",), "ForeignKeyViolation"))
    actual = validate_relations(tables, constraints, buffersize=2,
                                tempdir=str(tmp_path))
    debug(actual)
    ieq(expect, actual)
    ieq(expect, actual)


def test_validate_relations_does_not_modify_inputs():
    authors, books, tags = _relational_tables()
    authors = [list(row) for row in authors]
    books = [list(row) for row in books]
    authors_copy = [list(row) for row in authors]
    books_copy = [list(row) for row in books]
    constraints = [
        dict(name="fk", type="foreign_key", table="books",
             fields="author_id", references="authors",
             ref_fields="author_id"),
    ]
    constraints_copy = [dict(c) for c in constraints]
    actual = validate_relations({"authors": authors, "books": books},
                                constraints)
    list(actual)
    assert authors == authors_copy
    assert books == books_copy
    assert constraints == constraints_copy


def test_validate_relations_no_constraints():
    expect = (("name", "table", "row", "fields", "value",
               "ref_table", "ref_fields", "error"),)
    actual = validate_relations({"t": [(1, 2)]}, None)
    ieq(expect, actual)


def test_validate_relations_errors():
    table = (("a",), (1,))
    # unknown table
    with pytest.raises(ArgumentError):
        validate_relations({"t": table},
                           [dict(table="nope", fields="a")])
    # duplicate table name
    with pytest.raises(ArgumentError):
        validate_relations([("t", table), ("t", table)], [])
    # invalid constraint type
    with pytest.raises(ArgumentError):
        validate_relations({"t": table},
                           [dict(table="t", fields="a", type="nope")])
    # missing fields
    with pytest.raises(ArgumentError):
        validate_relations({"t": table}, [dict(table="t")])
    # unknown referenced table
    with pytest.raises(ArgumentError):
        validate_relations({"t": table},
                           [dict(table="t", fields="a",
                                 references="nope")])
    # mismatched field counts
    with pytest.raises(ArgumentError):
        validate_relations(
            {"t": table, "u": table},
            [dict(table="t", fields=("a", "a"), references="u",
                  ref_fields="a")])
    # invalid nulls policy
    with pytest.raises(ArgumentError):
        validate_relations(
            {"t": table, "u": table},
            [dict(table="t", fields="a", references="u",
                  nulls="nope")])
    # unknown field raises on iteration
    problems = validate_relations({"t": table},
                                  [dict(table="t", fields="nope")])
    with pytest.raises(FieldSelectionError):
        list(problems)
