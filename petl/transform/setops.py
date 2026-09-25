from __future__ import absolute_import, print_function, division

from collections import Counter
from petl.compat import next
from petl.comparison import Comparable
from petl.util.base import header, Table, asindices
from petl.transform.sorts import sort
from petl.transform.basics import cut


def complement(a, b, presorted=False, buffersize=None, tempdir=None,
               cache=True, strict=False):
    """
    Return rows in `a` that are not in `b`. E.g.::

        >>> import petl as etl
        >>> a = [['foo', 'bar', 'baz'],
        ...      ['A', 1, True],
        ...      ['C', 7, False],
        ...      ['B', 2, False],
        ...      ['C', 9, True]]
        >>> b = [['x', 'y', 'z'],
        ...      ['B', 2, False],
        ...      ['A', 9, False],
        ...      ['B', 3, True],
        ...      ['C', 9, True]]
        >>> aminusb = etl.complement(a, b)
        >>> aminusb
        +-----+-----+-------+
        | foo | bar | baz   |
        +=====+=====+=======+
        | 'A' |   1 | True  |
        +-----+-----+-------+
        | 'C' |   7 | False |
        +-----+-----+-------+

        >>> bminusa = etl.complement(b, a)
        >>> bminusa
        +-----+---+-------+
        | x   | y | z     |
        +=====+===+=======+
        | 'A' | 9 | False |
        +-----+---+-------+
        | 'B' | 3 | True  |
        +-----+---+-------+

    Note that the field names of each table are ignored - rows are simply
    compared following a lexical sort. See also the
    :func:`petl.transform.setops.recordcomplement` function.

    If `presorted` is True, it is assumed that the data are already sorted by
    the given key, and the `buffersize`, `tempdir` and `cache` arguments are
    ignored. Otherwise, the data are sorted, see also the discussion of the
    `buffersize`, `tempdir` and `cache` arguments under the
    :func:`petl.transform.sorts.sort` function.

    Note that the default behaviour is not strictly set-like, because 
    duplicate rows are counted separately, e.g.::
    
        >>> a = [['foo', 'bar'],
        ...      ['A', 1],
        ...      ['B', 2],
        ...      ['B', 2],
        ...      ['C', 7]]
        >>> b = [['foo', 'bar'],
        ...      ['B', 2]]
        >>> aminusb = etl.complement(a, b)
        >>> aminusb
        +-----+-----+
        | foo | bar |
        +=====+=====+
        | 'A' |   1 |
        +-----+-----+
        | 'B' |   2 |
        +-----+-----+
        | 'C' |   7 |
        +-----+-----+

    This behaviour can be changed with the `strict` keyword argument, e.g.::

        >>> aminusb = etl.complement(a, b, strict=True)
        >>> aminusb
        +-----+-----+
        | foo | bar |
        +=====+=====+
        | 'A' |   1 |
        +-----+-----+
        | 'C' |   7 |
        +-----+-----+

    .. versionchanged:: 1.1.0
    
    If `strict` is `True` then strict set-like behaviour is used, i.e., 
    only rows in `a` not found in `b` are returned.

    """

    return ComplementView(a, b, presorted=presorted, buffersize=buffersize,
                          tempdir=tempdir, cache=cache, strict=strict)


Table.complement = complement


class ComplementView(Table):

    def __init__(self, a, b, presorted=False, buffersize=None, tempdir=None,
                 cache=True, strict=False):
        if presorted:
            self.a = a
            self.b = b
        else:
            self.a = sort(a, buffersize=buffersize, tempdir=tempdir,
                          cache=cache)
            self.b = sort(b, buffersize=buffersize, tempdir=tempdir,
                          cache=cache)
        self.strict = strict

    def __iter__(self):
        return itercomplement(self.a, self.b, self.strict)


def itercomplement(ta, tb, strict):
    # coerce rows to tuples to ensure hashable and comparable
    ita = (tuple(row) for row in iter(ta))
    itb = (tuple(row) for row in iter(tb))
    ahdr = tuple(next(ita))
    next(itb)  # ignore b fields
    yield ahdr

    try:
        a = next(ita)
    except StopIteration:
        pass
    else:
        try:
            b = next(itb)
        except StopIteration:
            yield a
            for row in ita:
                yield row
        else:
            # we want the elements in a that are not in b
            while True:
                if b is None or Comparable(a) < Comparable(b):
                    yield a
                    try:
                        a = next(ita)
                    except StopIteration:
                        break
                elif a == b:
                    try:
                        a = next(ita)
                    except StopIteration:
                        break
                    if not strict:
                        try:
                            b = next(itb)
                        except StopIteration:
                            b = None
                else:
                    try:
                        b = next(itb)
                    except StopIteration:
                        b = None


def recordcomplement(a, b, buffersize=None, tempdir=None, cache=True,
                     strict=False):
    """
    Find records in `a` that are not in `b`. E.g.::

        >>> import petl as etl
        >>> a = [['foo', 'bar', 'baz'],
        ...      ['A', 1, True],
        ...      ['C', 7, False],
        ...      ['B', 2, False],
        ...      ['C', 9, True]]
        >>> b = [['bar', 'foo', 'baz'],
        ...      [2, 'B', False],
        ...      [9, 'A', False],
        ...      [3, 'B', True],
        ...      [9, 'C', True]]
        >>> aminusb = etl.recordcomplement(a, b)
        >>> aminusb
        +-----+-----+-------+
        | foo | bar | baz   |
        +=====+=====+=======+
        | 'A' |   1 | True  |
        +-----+-----+-------+
        | 'C' |   7 | False |
        +-----+-----+-------+

        >>> bminusa = etl.recordcomplement(b, a)
        >>> bminusa
        +-----+-----+-------+
        | bar | foo | baz   |
        +=====+=====+=======+
        |   3 | 'B' | True  |
        +-----+-----+-------+
        |   9 | 'A' | False |
        +-----+-----+-------+

    Note that both tables must have the same set of fields, but that the order
    of the fields does not matter. See also the
    :func:`petl.transform.setops.complement` function.

    See also the discussion of the `buffersize`, `tempdir` and `cache` arguments
    under the :func:`petl.transform.sorts.sort` function.

    """

    # TODO possible with only one pass?

    ha = header(a)
    hb = header(b)
    assert set(ha) == set(hb), 'both tables must have the same set of fields'
    # make sure fields are in the same order
    bv = cut(b, *ha)
    return complement(a, bv, buffersize=buffersize, tempdir=tempdir,
                      cache=cache, strict=strict)


Table.recordcomplement = recordcomplement


def diff(a, b, presorted=False, buffersize=None, tempdir=None, cache=True,
         strict=False):
    """
    Find the difference between rows in two tables. Returns a pair of tables.
    E.g.::

        >>> import petl as etl
        >>> a = [['foo', 'bar', 'baz'],
        ...      ['A', 1, True],
        ...      ['C', 7, False],
        ...      ['B', 2, False],
        ...      ['C', 9, True]]
        >>> b = [['x', 'y', 'z'],
        ...      ['B', 2, False],
        ...      ['A', 9, False],
        ...      ['B', 3, True],
        ...      ['C', 9, True]]
        >>> added, subtracted = etl.diff(a, b)
        >>> # rows in b not in a
        ... added
        +-----+---+-------+
        | x   | y | z     |
        +=====+===+=======+
        | 'A' | 9 | False |
        +-----+---+-------+
        | 'B' | 3 | True  |
        +-----+---+-------+

        >>> # rows in a not in b
        ... subtracted
        +-----+-----+-------+
        | foo | bar | baz   |
        +=====+=====+=======+
        | 'A' |   1 | True  |
        +-----+-----+-------+
        | 'C' |   7 | False |
        +-----+-----+-------+

    Convenient shorthand for ``(complement(b, a), complement(a, b))``. See also
    :func:`petl.transform.setops.complement`.

    If `presorted` is True, it is assumed that the data are already sorted by
    the given key, and the `buffersize`, `tempdir` and `cache` arguments are
    ignored. Otherwise, the data are sorted, see also the discussion of the
    `buffersize`, `tempdir` and `cache` arguments under the
    :func:`petl.transform.sorts.sort` function.

    .. versionchanged:: 1.1.0

    If `strict` is `True` then strict set-like behaviour is used.

    """

    if not presorted:
        a = sort(a)
        b = sort(b)
    added = complement(b, a, presorted=True, buffersize=buffersize,
                       tempdir=tempdir, cache=cache, strict=strict)
    subtracted = complement(a, b, presorted=True, buffersize=buffersize,
                            tempdir=tempdir, cache=cache, strict=strict)
    return added, subtracted


Table.diff = diff


def recorddiff(a, b, buffersize=None, tempdir=None, cache=True, strict=False):
    """
    Find the difference between records in two tables. E.g.::

        >>> import petl as etl
        >>> a = [['foo', 'bar', 'baz'],
        ...      ['A', 1, True],
        ...      ['C', 7, False],
        ...      ['B', 2, False],
        ...      ['C', 9, True]]
        >>> b = [['bar', 'foo', 'baz'],
        ...      [2, 'B', False],
        ...      [9, 'A', False],
        ...      [3, 'B', True],
        ...      [9, 'C', True]]
        >>> added, subtracted = etl.recorddiff(a, b)
        >>> added
        +-----+-----+-------+
        | bar | foo | baz   |
        +=====+=====+=======+
        |   3 | 'B' | True  |
        +-----+-----+-------+
        |   9 | 'A' | False |
        +-----+-----+-------+

        >>> subtracted
        +-----+-----+-------+
        | foo | bar | baz   |
        +=====+=====+=======+
        | 'A' |   1 | True  |
        +-----+-----+-------+
        | 'C' |   7 | False |
        +-----+-----+-------+

    Convenient shorthand for
    ``(recordcomplement(b, a), recordcomplement(a, b))``. See also
    :func:`petl.transform.setops.recordcomplement`.

    See also the discussion of the `buffersize`, `tempdir` and `cache`
    arguments under the :func:`petl.transform.sorts.sort` function.

    .. versionchanged:: 1.1.0

    If `strict` is `True` then strict set-like behaviour is used.

    """

    added = recordcomplement(b, a, buffersize=buffersize, tempdir=tempdir,
                             cache=cache, strict=strict)
    subtracted = recordcomplement(a, b, buffersize=buffersize, tempdir=tempdir,
                                  cache=cache, strict=strict)
    return added, subtracted


Table.recorddiff = recorddiff


def intersection(a, b, presorted=False, buffersize=None, tempdir=None,
                 cache=True):
    """
    Return rows in `a` that are also in `b`. E.g.::

        >>> import petl as etl
        >>> table1 = [['foo', 'bar', 'baz'],
        ...           ['A', 1, True],
        ...           ['C', 7, False],
        ...           ['B', 2, False],
        ...           ['C', 9, True]]
        >>> table2 = [['x', 'y', 'z'],
        ...           ['B', 2, False],
        ...           ['A', 9, False],
        ...           ['B', 3, True],
        ...           ['C', 9, True]]
        >>> table3 = etl.intersection(table1, table2)
        >>> table3
        +-----+-----+-------+
        | foo | bar | baz   |
        +=====+=====+=======+
        | 'B' |   2 | False |
        +-----+-----+-------+
        | 'C' |   9 | True  |
        +-----+-----+-------+

    If `presorted` is True, it is assumed that the data are already sorted by
    the given key, and the `buffersize`, `tempdir` and `cache` arguments are
    ignored. Otherwise, the data are sorted, see also the discussion of the
    `buffersize`, `tempdir` and `cache` arguments under the
    :func:`petl.transform.sorts.sort` function.

    """

    return IntersectionView(a, b, presorted=presorted, buffersize=buffersize,
                            tempdir=tempdir, cache=cache)


Table.intersection = intersection


class IntersectionView(Table):

    def __init__(self, a, b, presorted=False, buffersize=None, tempdir=None,
                 cache=True):
        if presorted:
            self.a = a
            self.b = b
        else:
            self.a = sort(a, buffersize=buffersize, tempdir=tempdir,
                          cache=cache)
            self.b = sort(b, buffersize=buffersize, tempdir=tempdir,
                          cache=cache)

    def __iter__(self):
        return iterintersection(self.a, self.b)


def iterintersection(a, b):
    ita = iter(a)
    itb = iter(b)
    ahdr = next(ita)
    next(itb)  # ignore b header
    yield tuple(ahdr)
    try:
        a = tuple(next(ita))
        b = tuple(next(itb))
        while True:
            if Comparable(a) < Comparable(b):
                a = tuple(next(ita))
            elif a == b:
                yield a
                a = tuple(next(ita))
                b = tuple(next(itb))
            else:
                b = tuple(next(itb))
    except StopIteration:
        pass


def hashcomplement(a, b, strict=False):
    """
    Alternative implementation of :func:`petl.transform.setops.complement`,
    where the complement is executed by constructing an in-memory set for all
    rows found in the right hand table, then iterating over rows from the
    left hand table.

    May be faster and/or more resource efficient where the right table is small
    and the left table is large.
    
    .. versionchanged:: 1.1.0
    
    If `strict` is `True` then strict set-like behaviour is used, i.e., 
    only rows in `a` not found in `b` are returned.

    """

    return HashComplementView(a, b, strict=strict)


Table.hashcomplement = hashcomplement


class HashComplementView(Table):

    def __init__(self, a, b, strict=False):
        self.a = a
        self.b = b
        self.strict = strict

    def __iter__(self):
        return iterhashcomplement(self.a, self.b, self.strict)


def iterhashcomplement(a, b, strict):
    ita = iter(a)
    ahdr = next(ita)
    yield tuple(ahdr)
    itb = iter(b)
    next(itb)  # discard b header, assume same as a

    # N.B., need to account for possibility of duplicate rows
    bcnt = Counter(tuple(row) for row in itb)
    for ar in ita:
        t = tuple(ar)
        if bcnt[t] > 0:
            if not strict:
                bcnt[t] -= 1
        else:
            yield t


def hashintersection(a, b):
    """
    Alternative implementation of
    :func:`petl.transform.setops.intersection`, where the intersection
    is executed by constructing an in-memory set for all rows found in the
    right hand table, then iterating over rows from the left hand table.

    May be faster and/or more resource efficient where the right table is small
    and the left table is large.

    """

    return HashIntersectionView(a, b)


Table.hashintersection = hashintersection


class HashIntersectionView(Table):

    def __init__(self, a, b):
        self.a = a
        self.b = b

    def __iter__(self):
        return iterhashintersection(self.a, self.b)


def iterhashintersection(a, b):
    ita = iter(a)
    ahdr = next(ita)
    yield tuple(ahdr)
    itb = iter(b)
    next(itb)  # discard b header, assume same as a

    # N.B., need to account for possibility of duplicate rows
    bcnt = Counter(tuple(row) for row in itb)
    for ar in ita:
        t = tuple(ar)
        if bcnt[t] > 0:
            yield t
            bcnt[t] -= 1


def divide(source, requirement, key, rkey=None, candidates=None,
           multiset=True, explain=False):
    """
    Perform relational division: return the entities in `source` that are
    associated with *all* of the items in `requirement`. E.g., given a
    table recording which detection items were measured for each sample,
    find the samples that have all of the required detection items::

        >>> import petl as etl
        >>> samples = [['sample', 'analyte'],
        ...            ['S1', 'glucose'],
        ...            ['S1', 'lactate'],
        ...            ['S2', 'glucose'],
        ...            ['S3', 'glucose'],
        ...            ['S3', 'lactate'],
        ...            ['S3', 'urea']]
        >>> required = [['analyte'],
        ...             ['glucose'],
        ...             ['lactate']]
        >>> etl.divide(samples, required, key='sample')
        +--------+
        | sample |
        +========+
        | 'S1'   |
        +--------+
        | 'S3'   |
        +--------+

    The `key` argument selects the field (or fields) of `source` that
    identify an entity, and may be a single field or a list/tuple of
    fields for composite entity keys. The `rkey` argument selects the
    field (or fields) identifying a required item; these field names must
    be present in both `source` and `requirement`, and may also be
    composite. If `rkey` is not given, all fields of `requirement` are
    used.

    By default multiset (bag) semantics are used: if the same item
    appears more than once in `requirement`, an entity must be associated
    with that item at least as many times to qualify, e.g.::

        >>> measurements = [['sample', 'control'],
        ...                 ['S1', 'blank'],
        ...                 ['S1', 'blank'],
        ...                 ['S2', 'blank']]
        >>> required = [['control'],
        ...             ['blank'],
        ...             ['blank']]
        >>> etl.divide(measurements, required, key='sample')
        +--------+
        | sample |
        +========+
        | 'S1'   |
        +--------+

    Pass ``multiset=False`` for plain set semantics, where duplicate
    items in `requirement` (and in `source`) are ignored, e.g.::

        >>> etl.divide(measurements, required, key='sample', multiset=False)
        +--------+
        | sample |
        +========+
        | 'S1'   |
        +--------+
        | 'S2'   |
        +--------+

    The set of candidate entities is normally the set of entities
    appearing in `source`. An explicit candidate set can be provided via
    the `candidates` argument, as a table containing the entity key
    fields. This matters when `requirement` is empty: every candidate
    qualifies, including candidates with no rows at all in `source`,
    e.g.::

        >>> empty = [['analyte']]
        >>> candidates = [['sample'], ['S1'], ['S9']]
        >>> etl.divide(samples, empty, key='sample', candidates=candidates)
        +--------+
        | sample |
        +========+
        | 'S1'   |
        +--------+
        | 'S2'   |
        +--------+
        | 'S3'   |
        +--------+
        | 'S9'   |
        +--------+

    Key values are matched by equality, and ``None`` (e.g., from missing
    or empty cells) is treated as an ordinary value: a ``None`` item in
    `requirement` only matches ``None`` items in `source`, and a
    ``None`` entity key is treated like any other entity.

    If `explain` is True, all candidate entities are returned, with
    additional fields describing the outcome: `qualified` is True if the
    entity has all required items, `missing` lists the required items
    the entity lacks (an item appears once per missing occurrence under
    multiset semantics), and `shortfall` is the total number of missing
    occurrences, e.g.::

        >>> required = [['analyte'], ['lactate'], ['lactate'], ['urea']]
        >>> etl.divide(samples, required, key='sample', explain=True)
        +--------+-----------+--------------------------------+-----------+
        | sample | qualified | missing                        | shortfall |
        +========+===========+================================+===========+
        | 'S1'   | False     | ['lactate', 'urea']            |         2 |
        +--------+-----------+--------------------------------+-----------+
        | 'S2'   | False     | ['lactate', 'lactate', 'urea'] |         3 |
        +--------+-----------+--------------------------------+-----------+
        | 'S3'   | False     | ['lactate']                    |         1 |
        +--------+-----------+--------------------------------+-----------+

    The implementation is hash-based: `requirement` is counted once and
    `source` is grouped by entity in a single pass, so the cost grows
    linearly with the input sizes rather than with the cartesian product
    of entities and required items.

    .. versionadded:: 1.7.27

    """

    return DivideView(source, requirement, key, rkey=rkey,
                      candidates=candidates, multiset=multiset,
                      explain=explain)


Table.divide = divide


class DivideView(Table):

    def __init__(self, source, requirement, key, rkey=None, candidates=None,
                 multiset=True, explain=False):
        self.source = source
        self.requirement = requirement
        self.key = key
        self.rkey = rkey
        self.candidates = candidates
        self.multiset = multiset
        self.explain = explain

    def __iter__(self):
        return iterdivide(self.source, self.requirement, self.key,
                          self.rkey, self.candidates, self.multiset,
                          self.explain)


def _rowvalues(row, indices):
    # tolerate ragged rows, treating absent cells as None
    return tuple(row[i] if i < len(row) else None for i in indices)


def iterdivide(source, requirement, key, rkey, candidates, multiset,
               explain):

    # count required items, preserving first-seen order
    rit = iter(requirement)
    rhdr = next(rit)
    if rkey is None:
        rkey = list(rhdr)
    rkind = asindices(rhdr, rkey)
    required = Counter()
    for row in rit:
        required[_rowvalues(row, rkind)] += 1

    # group source items by entity in a single pass
    sit = iter(source)
    shdr = next(sit)
    skind = tuple(asindices(shdr, key))
    sitemind = asindices(shdr, rkey)
    items = dict()
    order = list()
    for row in sit:
        ekey = _rowvalues(row, skind)
        if ekey not in items:
            items[ekey] = list()
            order.append(ekey)
        items[ekey].append(_rowvalues(row, sitemind))

    # add any explicit candidates to the entity universe
    if candidates is not None:
        cit = iter(candidates)
        chdr = next(cit)
        ckind = asindices(chdr, key)
        for row in cit:
            ekey = _rowvalues(row, ckind)
            if ekey not in items:
                items[ekey] = list()
                order.append(ekey)

    keyfields = tuple(shdr[i] for i in skind)
    if explain:
        yield keyfields + ('qualified', 'missing', 'shortfall')
    else:
        yield keyfields

    single_item_field = len(rkind) == 1
    for ekey in order:
        have = Counter(items[ekey])
        if multiset:
            missing = list((required - have).elements())
        else:
            haveset = set(have)
            missing = [item for item in required if item not in haveset]
        qualified = not missing
        if explain:
            if single_item_field:
                missing = [item[0] for item in missing]
            yield ekey + (qualified, missing, len(missing))
        elif qualified:
            yield ekey
