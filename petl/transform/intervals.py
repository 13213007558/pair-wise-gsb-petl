from __future__ import absolute_import, print_function, division


from operator import itemgetter, attrgetter
from petl.compat import text_type


from petl.util.base import asindices, records, Table, values, rowgroupby
from petl.errors import DuplicateKeyError
from petl.transform.basics import addfield
from petl.transform.sorts import sort


def tupletree(table, start='start', stop='stop', value=None):
    """
    Construct an interval tree for the given table, where each node in the tree
    is a row of the table.

    """

    import intervaltree
    tree = intervaltree.IntervalTree()
    it = iter(table)
    hdr = next(it)
    flds = list(map(text_type, hdr))
    assert start in flds, 'start field not recognised'
    assert stop in flds, 'stop field not recognised'
    getstart = itemgetter(flds.index(start))
    getstop = itemgetter(flds.index(stop))
    if value is None:
        getvalue = tuple
    else:
        valueindices = asindices(hdr, value)
        assert len(valueindices) > 0, 'invalid value field specification'
        getvalue = itemgetter(*valueindices)
    for row in it:
        tree.addi(getstart(row), getstop(row), getvalue(row))
    return tree


def facettupletrees(table, key, start='start', stop='stop', value=None):
    """
    Construct faceted interval trees for the given table, where each node in
    the tree is a row of the table.

    """

    import intervaltree
    it = iter(table)
    hdr = next(it)
    flds = list(map(text_type, hdr))
    assert start in flds, 'start field not recognised'
    assert stop in flds, 'stop field not recognised'
    getstart = itemgetter(flds.index(start))
    getstop = itemgetter(flds.index(stop))
    if value is None:
        getvalue = tuple
    else:
        valueindices = asindices(hdr, value)
        assert len(valueindices) > 0, 'invalid value field specification'
        getvalue = itemgetter(*valueindices)
    keyindices = asindices(hdr, key)
    assert len(keyindices) > 0, 'invalid key'
    getkey = itemgetter(*keyindices)

    trees = dict()
    for row in it:
        k = getkey(row)
        if k not in trees:
            trees[k] = intervaltree.IntervalTree()
        trees[k].addi(getstart(row), getstop(row), getvalue(row))
    return trees


def recordtree(table, start='start', stop='stop'):
    """
    Construct an interval tree for the given table, where each node in the
    tree is a row of the table represented as a record object.

    """

    import intervaltree
    getstart = attrgetter(start)
    getstop = attrgetter(stop)
    tree = intervaltree.IntervalTree()
    for rec in records(table):
        tree.addi(getstart(rec), getstop(rec), rec)
    return tree


def facetrecordtrees(table, key, start='start', stop='stop'):
    """
    Construct faceted interval trees for the given table, where each node in 
    the tree is a record.

    """

    import intervaltree
    getstart = attrgetter(start)
    getstop = attrgetter(stop)
    getkey = attrgetter(key)
    trees = dict()
    for rec in records(table):
        k = getkey(rec)
        if k not in trees:
            trees[k] = intervaltree.IntervalTree()
        trees[k].addi(getstart(rec), getstop(rec), rec)
    return trees


def intervallookup(table, start='start', stop='stop', value=None,
                   include_stop=False):
    """
    Construct an interval lookup for the given table. E.g.::

        >>> import petl as etl
        >>> table = [['start', 'stop', 'value'],
        ...          [1, 4, 'foo'],
        ...          [3, 7, 'bar'],
        ...          [4, 9, 'baz']]
        >>> lkp = etl.intervallookup(table, 'start', 'stop')
        >>> lkp.search(0, 1)
        []
        >>> lkp.search(1, 2)
        [(1, 4, 'foo')]
        >>> lkp.search(2, 4)
        [(1, 4, 'foo'), (3, 7, 'bar')]
        >>> lkp.search(2, 5)
        [(1, 4, 'foo'), (3, 7, 'bar'), (4, 9, 'baz')]
        >>> lkp.search(9, 14)
        []
        >>> lkp.search(19, 140)
        []
        >>> lkp.search(0)
        []
        >>> lkp.search(1)
        [(1, 4, 'foo')]
        >>> lkp.search(2)
        [(1, 4, 'foo')]
        >>> lkp.search(4)
        [(3, 7, 'bar'), (4, 9, 'baz')]
        >>> lkp.search(5)
        [(3, 7, 'bar'), (4, 9, 'baz')]

    Note start coordinates are included and stop coordinates are excluded
    from the interval. Use the `include_stop` keyword argument to include the
    upper bound of the interval when finding overlaps.

    Some examples using the `include_stop` and `value` keyword arguments::
    
        >>> import petl as etl
        >>> table = [['start', 'stop', 'value'],
        ...          [1, 4, 'foo'],
        ...          [3, 7, 'bar'],
        ...          [4, 9, 'baz']]
        >>> lkp = etl.intervallookup(table, 'start', 'stop', include_stop=True,
        ...                          value='value')
        >>> lkp.search(0, 1)
        ['foo']
        >>> lkp.search(1, 2)
        ['foo']
        >>> lkp.search(2, 4)
        ['foo', 'bar', 'baz']
        >>> lkp.search(2, 5)
        ['foo', 'bar', 'baz']
        >>> lkp.search(9, 14)
        ['baz']
        >>> lkp.search(19, 140)
        []
        >>> lkp.search(0)
        []
        >>> lkp.search(1)
        ['foo']
        >>> lkp.search(2)
        ['foo']
        >>> lkp.search(4)
        ['foo', 'bar', 'baz']
        >>> lkp.search(5)
        ['bar', 'baz']

    """

    tree = tupletree(table, start=start, stop=stop, value=value)
    return IntervalTreeLookup(tree, include_stop=include_stop)


Table.intervallookup = intervallookup


def _search_tree(tree, start, stop, include_stop):
    if stop is None:
        if include_stop:
            stop = start + 1
            start -= 1
            args = (start, stop)
        else:
            args = (start,)
    else:
        if include_stop:
            stop += 1
            start -= 1
        args = (start, stop)
    if len(args) == 2:
        results = sorted(tree.overlap(*args))
    else:
        results = sorted(tree.at(*args))
    return results


class IntervalTreeLookup(object):
    
    def __init__(self, tree, include_stop=False):
        self.tree = tree
        self.include_stop = include_stop

    def search(self, start, stop=None):
        results = _search_tree(self.tree, start, stop, self.include_stop)
        return [r.data for r in results]

    find = search


def intervallookupone(table, start='start', stop='stop', value=None,
                      include_stop=False, strict=True):
    """
    Construct an interval lookup for the given table, returning at most one
    result for each query. E.g.::

        >>> import petl as etl
        >>> table = [['start', 'stop', 'value'],
        ...          [1, 4, 'foo'],
        ...          [3, 7, 'bar'],
        ...          [4, 9, 'baz']]
        >>> lkp = etl.intervallookupone(table, 'start', 'stop', strict=False)
        >>> lkp.search(0, 1)
        >>> lkp.search(1, 2)
        (1, 4, 'foo')
        >>> lkp.search(2, 4)
        (1, 4, 'foo')
        >>> lkp.search(2, 5)
        (1, 4, 'foo')
        >>> lkp.search(9, 14)
        >>> lkp.search(19, 140)
        >>> lkp.search(0)
        >>> lkp.search(1)
        (1, 4, 'foo')
        >>> lkp.search(2)
        (1, 4, 'foo')
        >>> lkp.search(4)
        (3, 7, 'bar')
        >>> lkp.search(5)
        (3, 7, 'bar')

    If ``strict=True``, queries returning more than one result will
    raise a `DuplicateKeyError`. If ``strict=False`` and there is
    more than one result, the first result is returned.

    Note start coordinates are included and stop coordinates are excluded
    from the interval. Use the `include_stop` keyword argument to include the
    upper bound of the interval when finding overlaps.

    """

    tree = tupletree(table, start=start, stop=stop, value=value)
    return IntervalTreeLookupOne(tree, strict=strict, include_stop=include_stop)


Table.intervallookupone = intervallookupone


class IntervalTreeLookupOne(object):
    
    def __init__(self, tree, strict=True, include_stop=False):
        self.tree = tree
        self.strict = strict
        self.include_stop = include_stop
        
    def search(self, start, stop=None):
        results = _search_tree(self.tree, start, stop, self.include_stop)
        if len(results) == 0:
            return None
        elif len(results) > 1 and self.strict:
            raise DuplicateKeyError((start, stop))
        else:
            return results[0].data

    find = search


def intervalrecordlookup(table, start='start', stop='stop', include_stop=False):
    """
    As :func:`petl.transform.intervals.intervallookup` but return records
    instead of tuples.

    """

    tree = recordtree(table, start=start, stop=stop)
    return IntervalTreeLookup(tree, include_stop=include_stop)


Table.intervalrecordlookup = intervalrecordlookup


def intervalrecordlookupone(table, start='start', stop='stop',
                            include_stop=False, strict=True):
    """
    As :func:`petl.transform.intervals.intervallookupone` but return records
    instead of tuples.

    """

    tree = recordtree(table, start=start, stop=stop)
    return IntervalTreeLookupOne(tree, include_stop=include_stop, strict=strict)


Table.intervalrecordlookupone = intervalrecordlookupone


def facetintervallookup(table, key, start='start', stop='stop',
                        value=None, include_stop=False):
    """

    Construct a faceted interval lookup for the given table. E.g.::

        >>> import petl as etl
        >>> table = (('type', 'start', 'stop', 'value'),
        ...          ('apple', 1, 4, 'foo'),
        ...          ('apple', 3, 7, 'bar'),
        ...          ('orange', 4, 9, 'baz'))
        >>> lkp = etl.facetintervallookup(table, key='type', start='start', stop='stop')
        >>> lkp['apple'].search(1, 2)
        [('apple', 1, 4, 'foo')]
        >>> lkp['apple'].search(2, 4)
        [('apple', 1, 4, 'foo'), ('apple', 3, 7, 'bar')]
        >>> lkp['apple'].search(2, 5)
        [('apple', 1, 4, 'foo'), ('apple', 3, 7, 'bar')]
        >>> lkp['orange'].search(2, 5)
        [('orange', 4, 9, 'baz')]
        >>> lkp['orange'].search(9, 14)
        []
        >>> lkp['orange'].search(19, 140)
        []
        >>> lkp['apple'].search(1)
        [('apple', 1, 4, 'foo')]
        >>> lkp['apple'].search(2)
        [('apple', 1, 4, 'foo')]
        >>> lkp['apple'].search(4)
        [('apple', 3, 7, 'bar')]
        >>> lkp['apple'].search(5)
        [('apple', 3, 7, 'bar')]
        >>> lkp['orange'].search(5)
        [('orange', 4, 9, 'baz')]

    """

    trees = facettupletrees(table, key, start=start, stop=stop, value=value)
    out = dict()
    for k in trees:
        out[k] = IntervalTreeLookup(trees[k], include_stop=include_stop)
    return out


Table.facetintervallookup = facetintervallookup


def facetintervallookupone(table, key, start='start', stop='stop',
                           value=None, include_stop=False, strict=True):
    """
    Construct a faceted interval lookup for the given table, returning at most
    one result for each query.
    
    If ``strict=True``, queries returning more than one result will
    raise a `DuplicateKeyError`. If ``strict=False`` and there is
    more than one result, the first result is returned.

    """
    
    trees = facettupletrees(table, key, start=start, stop=stop, value=value)
    out = dict()
    for k in trees:
        out[k] = IntervalTreeLookupOne(trees[k], include_stop=include_stop,
                                       strict=strict)
    return out


Table.facetintervallookupone = facetintervallookupone


def facetintervalrecordlookup(table, key, start='start', stop='stop',
                              include_stop=False):
    """
    As :func:`petl.transform.intervals.facetintervallookup` but return records.
    
    """

    trees = facetrecordtrees(table, key, start=start, stop=stop)
    out = dict()
    for k in trees:
        out[k] = IntervalTreeLookup(trees[k], include_stop=include_stop)
    return out


Table.facetintervalrecordlookup = facetintervalrecordlookup


def facetintervalrecordlookupone(table, key, start, stop, include_stop=False,
                                 strict=True):
    """
    As :func:`petl.transform.intervals.facetintervallookupone` but return
    records.

    """
    
    trees = facetrecordtrees(table, key, start=start, stop=stop)
    out = dict()
    for k in trees:
        out[k] = IntervalTreeLookupOne(trees[k], include_stop=include_stop,
                                       strict=strict)
    return out


Table.facetintervalrecordlookupone = facetintervalrecordlookupone


# Allen's interval algebra relations (canonical names).
INTERVAL_RELATIONS = (
    'before', 'meets', 'overlaps', 'starts', 'during', 'finishes', 'equals',
    'after', 'met_by', 'overlapped_by', 'started_by', 'contains',
    'finished_by',
)

# Maps each relation to the relation obtained when the left and right
# intervals are exchanged.
INVERSE_INTERVAL_RELATIONS = {
    'before': 'after',
    'meets': 'met_by',
    'overlaps': 'overlapped_by',
    'starts': 'started_by',
    'during': 'contains',
    'finishes': 'finished_by',
    'equals': 'equals',
    'after': 'before',
    'met_by': 'meets',
    'overlapped_by': 'overlaps',
    'started_by': 'starts',
    'contains': 'during',
    'finished_by': 'finishes',
}

_INTERVAL_RELATION_ALIASES = {
    'equal': 'equals',
}


def _normalise_interval_relations(relations):
    if relations is None:
        return None
    if isinstance(relations, text_type):
        relations = (relations,)
    normalised = list()
    for relation in relations:
        relation = _INTERVAL_RELATION_ALIASES.get(relation, relation)
        assert relation in INVERSE_INTERVAL_RELATIONS, \
            'unknown interval relation: %r, expected one of %s' \
            % (relation, ', '.join(INTERVAL_RELATIONS))
        if relation not in normalised:
            normalised.append(relation)
    assert len(normalised) > 0, 'no interval relations given'
    return frozenset(normalised)


def _check_interval(start, stop):
    if start > stop:
        raise ValueError(
            'invalid interval: start (%r) is greater than stop (%r)'
            % (start, stop))


def _classify_interval_relation(astart, astop, bstart, bstop,
                                include_start=True, include_stop=False):
    """
    Classify the Allen's interval algebra relation of interval A relative to
    interval B, respecting the openness of the interval endpoints.

    Returns None if either interval is empty, i.e., a zero-length interval
    (start == stop) where at least one of the endpoints is excluded.

    """
    aempty = astart == astop and not (include_start and include_stop)
    bempty = bstart == bstop and not (include_start and include_stop)
    if aempty or bempty:
        return None
    if astart == bstart:
        if astop == bstop:
            return 'equals'
        elif astop < bstop:
            return 'starts'
        else:
            return 'started_by'
    if astop == bstop:
        if astart > bstart:
            return 'finishes'
        else:
            return 'finished_by'
    if bstart < astart and astop < bstop:
        return 'during'
    if astart < bstart and bstop < astop:
        return 'contains'
    if astart < bstart and bstart < astop and astop < bstop:
        return 'overlaps'
    if bstart < astart and astart < bstop and bstop < astop:
        return 'overlapped_by'
    if astop == bstart:
        # intervals touch at a single point; if both touching endpoints are
        # included the intervals share that point (a degenerate overlap),
        # otherwise they are adjacent but disjoint
        if include_start and include_stop:
            return 'overlaps'
        else:
            return 'meets'
    if bstop == astart:
        if include_start and include_stop:
            return 'overlapped_by'
        else:
            return 'met_by'
    if astop < bstart:
        return 'before'
    if bstop < astart:
        return 'after'
    return None


def intervaljoin(left, right, lstart='start', lstop='stop', rstart='start',
                 rstop='stop', lkey=None, rkey=None, include_stop=False,
                 lprefix=None, rprefix=None, relations=None,
                 relation_field='relation', include_start=True):
    """
    Join two tables by overlapping intervals. E.g.::

        >>> import petl as etl
        >>> left = [['begin', 'end', 'quux'],
        ...         [1, 2, 'a'],
        ...         [2, 4, 'b'],
        ...         [2, 5, 'c'],
        ...         [9, 14, 'd'],
        ...         [1, 1, 'e'],
        ...         [10, 10, 'f']]
        >>> right = [['start', 'stop', 'value'],
        ...          [1, 4, 'foo'],
        ...          [3, 7, 'bar'],
        ...          [4, 9, 'baz']]
        >>> table1 = etl.intervaljoin(left, right,
        ...                           lstart='begin', lstop='end',
        ...                           rstart='start', rstop='stop')
        >>> table1.lookall()
        +-------+-----+------+-------+------+-------+
        | begin | end | quux | start | stop | value |
        +=======+=====+======+=======+======+=======+
        |     1 |   2 | 'a'  |     1 |    4 | 'foo' |
        +-------+-----+------+-------+------+-------+
        |     2 |   4 | 'b'  |     1 |    4 | 'foo' |
        +-------+-----+------+-------+------+-------+
        |     2 |   4 | 'b'  |     3 |    7 | 'bar' |
        +-------+-----+------+-------+------+-------+
        |     2 |   5 | 'c'  |     1 |    4 | 'foo' |
        +-------+-----+------+-------+------+-------+
        |     2 |   5 | 'c'  |     3 |    7 | 'bar' |
        +-------+-----+------+-------+------+-------+
        |     2 |   5 | 'c'  |     4 |    9 | 'baz' |
        +-------+-----+------+-------+------+-------+

        >>> # include stop coordinate in intervals
        ... table2 = etl.intervaljoin(left, right,
        ...                           lstart='begin', lstop='end',
        ...                           rstart='start', rstop='stop',
        ...                           include_stop=True)
        >>> table2.lookall()
        +-------+-----+------+-------+------+-------+
        | begin | end | quux | start | stop | value |
        +=======+=====+======+=======+======+=======+
        |     1 |   2 | 'a'  |     1 |    4 | 'foo' |
        +-------+-----+------+-------+------+-------+
        |     2 |   4 | 'b'  |     1 |    4 | 'foo' |
        +-------+-----+------+-------+------+-------+
        |     2 |   4 | 'b'  |     3 |    7 | 'bar' |
        +-------+-----+------+-------+------+-------+
        |     2 |   4 | 'b'  |     4 |    9 | 'baz' |
        +-------+-----+------+-------+------+-------+
        |     2 |   5 | 'c'  |     1 |    4 | 'foo' |
        +-------+-----+------+-------+------+-------+
        |     2 |   5 | 'c'  |     3 |    7 | 'bar' |
        +-------+-----+------+-------+------+-------+
        |     2 |   5 | 'c'  |     4 |    9 | 'baz' |
        +-------+-----+------+-------+------+-------+
        |     9 |  14 | 'd'  |     4 |    9 | 'baz' |
        +-------+-----+------+-------+------+-------+
        |     1 |   1 | 'e'  |     1 |    4 | 'foo' |
        +-------+-----+------+-------+------+-------+

    Note start coordinates are included and stop coordinates are excluded
    from the interval. Use the `include_stop` keyword argument to include the
    upper bound of the interval when finding overlaps.

    An additional key comparison can be made, e.g.::
    
        >>> import petl as etl
        >>> left = (('fruit', 'begin', 'end'),
        ...         ('apple', 1, 2),
        ...         ('apple', 2, 4),
        ...         ('apple', 2, 5),
        ...         ('orange', 2, 5),
        ...         ('orange', 9, 14),
        ...         ('orange', 19, 140),
        ...         ('apple', 1, 1))
        >>> right = (('type', 'start', 'stop', 'value'),
        ...          ('apple', 1, 4, 'foo'),
        ...          ('apple', 3, 7, 'bar'),
        ...          ('orange', 4, 9, 'baz'))
        >>> table3 = etl.intervaljoin(left, right,
        ...                           lstart='begin', lstop='end', lkey='fruit',
        ...                           rstart='start', rstop='stop', rkey='type')
        >>> table3.lookall()
        +----------+-------+-----+----------+-------+------+-------+
        | fruit    | begin | end | type     | start | stop | value |
        +==========+=======+=====+==========+=======+======+=======+
        | 'apple'  |     1 |   2 | 'apple'  |     1 |    4 | 'foo' |
        +----------+-------+-----+----------+-------+------+-------+
        | 'apple'  |     2 |   4 | 'apple'  |     1 |    4 | 'foo' |
        +----------+-------+-----+----------+-------+------+-------+
        | 'apple'  |     2 |   4 | 'apple'  |     3 |    7 | 'bar' |
        +----------+-------+-----+----------+-------+------+-------+
        | 'apple'  |     2 |   5 | 'apple'  |     1 |    4 | 'foo' |
        +----------+-------+-----+----------+-------+------+-------+
        | 'apple'  |     2 |   5 | 'apple'  |     3 |    7 | 'bar' |
        +----------+-------+-----+----------+-------+------+-------+
        | 'orange' |     2 |   5 | 'orange' |     4 |    9 | 'baz' |
        +----------+-------+-----+----------+-------+------+-------+

    The `relations` keyword argument allows matching rows by any of
    Allen's interval algebra relations instead of plain intersection, e.g.::

        >>> import petl as etl
        >>> left = [['begin', 'end', 'quux'],
        ...         [1, 3, 'a'],
        ...         [3, 5, 'b'],
        ...         [6, 8, 'c'],
        ...         [7, 9, 'd'],
        ...         [9, 11, 'e']]
        >>> right = [['start', 'stop', 'value'],
        ...          [3, 5, 'foo'],
        ...          [6, 9, 'bar']]
        >>> table4 = etl.intervaljoin(left, right,
        ...                           lstart='begin', lstop='end',
        ...                           rstart='start', rstop='stop',
        ...                           relations=('meets', 'equals', 'starts',
        ...                                      'finishes', 'met_by'))
        >>> table4.lookall()
        +-------+-----+------+-------+------+-------+------------+
        | begin | end | quux | start | stop | value | relation   |
        +=======+=====+======+=======+======+=======+============+
        |     1 |   3 | 'a'  |     3 |    5 | 'foo' | 'meets'    |
        +-------+-----+------+-------+------+-------+------------+
        |     3 |   5 | 'b'  |     3 |    5 | 'foo' | 'equals'   |
        +-------+-----+------+-------+------+-------+------------+
        |     6 |   8 | 'c'  |     6 |    9 | 'bar' | 'starts'   |
        +-------+-----+------+-------+------+-------+------------+
        |     7 |   9 | 'd'  |     6 |    9 | 'bar' | 'finishes' |
        +-------+-----+------+-------+------+-------+------------+
        |     9 |  11 | 'e'  |     6 |    9 | 'bar' | 'met_by'   |
        +-------+-----+------+-------+------+-------+------------+

    The following relations are available: 'before', 'meets', 'overlaps',
    'starts', 'during', 'finishes', 'equals' (alias 'equal') and their
    inverses 'after', 'met_by', 'overlapped_by', 'started_by', 'contains',
    'finished_by'. Multiple relations can be given, and each matching pair
    of rows is reported at most once, with the actual relation written to
    an additional output field named by the `relation_field` keyword
    argument (default 'relation'). Exchanging the left and right tables
    yields the corresponding inverse relations.

    When `relations` is given, the `include_start` and `include_stop`
    keyword arguments define whether the start and stop endpoints of the
    intervals are included (closed) or excluded (open), and these determine
    the boundary cases. E.g., with the defaults (start included, stop
    excluded) the intervals [1, 3) and [3, 5) are adjacent but disjoint and
    so satisfy the 'meets' relation, whereas with both endpoints included
    the intervals [1, 3] and [3, 5] share the point 3 and are reported as a
    degenerate 'overlaps' instead.

    A zero-length interval (start == stop) is treated as a single point if
    both endpoints are included, otherwise it is empty and never matches.
    An interval with start > stop is invalid and raises a ValueError.

    """
    
    assert (lkey is None) == (rkey is None), \
        'facet key field must be provided for both or neither table'
    relations = _normalise_interval_relations(relations)
    return IntervalJoinView(left, right, lstart=lstart, lstop=lstop,
                            rstart=rstart, rstop=rstop, lkey=lkey,
                            rkey=rkey, include_stop=include_stop,
                            lprefix=lprefix, rprefix=rprefix,
                            relations=relations, relation_field=relation_field,
                            include_start=include_start)


Table.intervaljoin = intervaljoin


class IntervalJoinView(Table):
    
    def __init__(self, left, right, lstart='start', lstop='stop', 
                 rstart='start', rstop='stop', lkey=None, rkey=None,
                 include_stop=False, lprefix=None, rprefix=None,
                 relations=None, relation_field='relation',
                 include_start=True):
        self.left = left
        self.lstart = lstart
        self.lstop = lstop
        self.lkey = lkey
        self.right = right
        self.rstart = rstart
        self.rstop = rstop
        self.rkey = rkey
        self.include_stop = include_stop
        self.lprefix = lprefix
        self.rprefix = rprefix
        self.relations = relations
        self.relation_field = relation_field
        self.include_start = include_start

    def __iter__(self):
        return iterintervaljoin(
            left=self.left,
            right=self.right,
            lstart=self.lstart,
            lstop=self.lstop,
            rstart=self.rstart,
            rstop=self.rstop,
            lkey=self.lkey,
            rkey=self.rkey,
            include_stop=self.include_stop,
            missing=None,
            lprefix=self.lprefix,
            rprefix=self.rprefix,
            leftouter=False,
            relations=self.relations,
            relation_field=self.relation_field,
            include_start=self.include_start
        )
        

def intervalleftjoin(left, right, lstart='start', lstop='stop', rstart='start',
                     rstop='stop', lkey=None, rkey=None, include_stop=False,
                     missing=None, lprefix=None, rprefix=None, relations=None,
                     relation_field='relation', include_start=True):
    """
    Like :func:`petl.transform.intervals.intervaljoin` but rows from the left 
    table without a match in the right table are also included. E.g.::

        >>> import petl as etl
        >>> left = [['begin', 'end', 'quux'],
        ...         [1, 2, 'a'],
        ...         [2, 4, 'b'],
        ...         [2, 5, 'c'],
        ...         [9, 14, 'd'],
        ...         [1, 1, 'e'],
        ...         [10, 10, 'f']]
        >>> right = [['start', 'stop', 'value'],
        ...          [1, 4, 'foo'],
        ...          [3, 7, 'bar'],
        ...          [4, 9, 'baz']]
        >>> table1 = etl.intervalleftjoin(left, right,
        ...                               lstart='begin', lstop='end',
        ...                               rstart='start', rstop='stop')
        >>> table1.lookall()
        +-------+-----+------+-------+------+-------+
        | begin | end | quux | start | stop | value |
        +=======+=====+======+=======+======+=======+
        |     1 |   2 | 'a'  |     1 |    4 | 'foo' |
        +-------+-----+------+-------+------+-------+
        |     2 |   4 | 'b'  |     1 |    4 | 'foo' |
        +-------+-----+------+-------+------+-------+
        |     2 |   4 | 'b'  |     3 |    7 | 'bar' |
        +-------+-----+------+-------+------+-------+
        |     2 |   5 | 'c'  |     1 |    4 | 'foo' |
        +-------+-----+------+-------+------+-------+
        |     2 |   5 | 'c'  |     3 |    7 | 'bar' |
        +-------+-----+------+-------+------+-------+
        |     2 |   5 | 'c'  |     4 |    9 | 'baz' |
        +-------+-----+------+-------+------+-------+
        |     9 |  14 | 'd'  | None  | None | None  |
        +-------+-----+------+-------+------+-------+
        |     1 |   1 | 'e'  | None  | None | None  |
        +-------+-----+------+-------+------+-------+
        |    10 |  10 | 'f'  | None  | None | None  |
        +-------+-----+------+-------+------+-------+

    Note start coordinates are included and stop coordinates are excluded
    from the interval. Use the `include_stop` keyword argument to include the
    upper bound of the interval when finding overlaps.

    The `relations`, `relation_field` and `include_start` keyword
    arguments are as described for
    :func:`petl.transform.intervals.intervaljoin`. Rows from the left table
    without a matching relation in the right table are included, with the
    `missing` value for the right hand fields and the relation field.

    """
    
    assert (lkey is None) == (rkey is None), \
        'facet key field must be provided for both or neither table'
    relations = _normalise_interval_relations(relations)
    return IntervalLeftJoinView(left, right, lstart=lstart, lstop=lstop,
                                rstart=rstart, rstop=rstop, lkey=lkey,
                                rkey=rkey, include_stop=include_stop,
                                missing=missing, lprefix=lprefix,
                                rprefix=rprefix, relations=relations,
                                relation_field=relation_field,
                                include_start=include_start)


Table.intervalleftjoin = intervalleftjoin


class IntervalLeftJoinView(Table):
    
    def __init__(self, left, right, lstart='start', lstop='stop', 
                 rstart='start', rstop='stop', lkey=None, rkey=None,
                 missing=None, include_stop=False, lprefix=None, rprefix=None,
                 relations=None, relation_field='relation',
                 include_start=True):
        self.left = left
        self.lstart = lstart
        self.lstop = lstop
        self.lkey = lkey
        self.right = right
        self.rstart = rstart
        self.rstop = rstop
        self.rkey = rkey
        self.missing = missing
        self.include_stop = include_stop
        self.lprefix = lprefix
        self.rprefix = rprefix
        self.relations = relations
        self.relation_field = relation_field
        self.include_start = include_start

    def __iter__(self):
        return iterintervaljoin(
            left=self.left,
            right=self.right,
            lstart=self.lstart,
            lstop=self.lstop,
            rstart=self.rstart,
            rstop=self.rstop,
            lkey=self.lkey,
            rkey=self.rkey,
            include_stop=self.include_stop,
            missing=self.missing,
            lprefix=self.lprefix,
            rprefix=self.rprefix,
            leftouter=True,
            relations=self.relations,
            relation_field=self.relation_field,
            include_start=self.include_start
        )
        

def intervalantijoin(left, right, lstart='start', lstop='stop', rstart='start',
                     rstop='stop', lkey=None, rkey=None, include_stop=False,
                     missing=None, relations=None, include_start=True):
    """
    Return rows from the `left` table with no overlapping rows from the `right`
    table.

    Note start coordinates are included and stop coordinates are excluded
    from the interval. Use the `include_stop` keyword argument to include the
    upper bound of the interval when finding overlaps.

    If the `relations` keyword argument is given, rows from the `left`
    table are returned only if no row from the `right` table matches any of
    the given relations. See
    :func:`petl.transform.intervals.intervaljoin` for a description of the
    available relations and the `include_start` keyword argument.

    """

    assert (lkey is None) == (rkey is None), \
        'facet key field must be provided for both or neither table'
    relations = _normalise_interval_relations(relations)
    return IntervalAntiJoinView(left, right, lstart=lstart, lstop=lstop,
                                rstart=rstart, rstop=rstop, lkey=lkey,
                                rkey=rkey, include_stop=include_stop,
                                missing=missing, relations=relations,
                                include_start=include_start)


Table.intervalantijoin = intervalantijoin


class IntervalAntiJoinView(Table):

    def __init__(self, left, right, lstart='start', lstop='stop',
                 rstart='start', rstop='stop', lkey=None, rkey=None,
                 missing=None, include_stop=False, relations=None,
                 include_start=True):
        self.left = left
        self.lstart = lstart
        self.lstop = lstop
        self.lkey = lkey
        self.right = right
        self.rstart = rstart
        self.rstop = rstop
        self.rkey = rkey
        self.missing = missing
        self.include_stop = include_stop
        self.relations = relations
        self.include_start = include_start

    def __iter__(self):
        return iterintervaljoin(
            left=self.left,
            right=self.right,
            lstart=self.lstart,
            lstop=self.lstop,
            rstart=self.rstart,
            rstop=self.rstop,
            lkey=self.lkey,
            rkey=self.rkey,
            include_stop=self.include_stop,
            missing=self.missing,
            lprefix=None,
            rprefix=None,
            leftouter=True,
            anti=True,
            relations=self.relations,
            include_start=self.include_start
        )


def iterintervaljoin(left, right, lstart, lstop, rstart, rstop, lkey,
                     rkey, include_stop, missing, lprefix, rprefix, leftouter,
                     anti=False, relations=None, relation_field='relation',
                     include_start=True):

    # create iterators and obtain fields
    lit = iter(left)
    lhdr = next(lit)
    lflds = list(map(text_type, lhdr))
    rit = iter(right)
    rhdr = next(rit)
    rflds = list(map(text_type, rhdr))

    # check fields via petl.util.asindices (raises FieldSelectionError if spec
    # is not valid)
    asindices(lhdr, lstart)
    asindices(lhdr, lstop)
    if lkey is not None:
        asindices(lhdr, lkey)
    asindices(rhdr, rstart)
    asindices(rhdr, rstop)
    if rkey is not None:
        asindices(rhdr, rkey)

    # determine output fields
    if lprefix is None:
        outhdr = list(lflds)
        if not anti:
            outhdr.extend(rflds)
    else:
        outhdr = list(lprefix + f for f in lflds)
        if not anti:
            outhdr.extend(rprefix + f for f in rflds)
    if relations is not None and not anti:
        outhdr.append(relation_field)
    yield tuple(outhdr)
    
    # create getters for start and stop positions
    getlstart = itemgetter(lflds.index(lstart))
    getlstop = itemgetter(lflds.index(lstop))

    if relations is not None:
        # match by Allen's interval algebra relations, comparing each left
        # row with all right rows in the same facet group
        for row in _iterintervalrelations(
                lit, rit, lflds, rflds, lstart, lstop, rstart, rstop, lkey,
                rkey, include_start, include_stop, missing, leftouter, anti,
                relations):
            yield row
        return

    if rkey is None:
        # build interval lookup for right table
        lookup = intervallookup(right, rstart, rstop, include_stop=include_stop)
        search = lookup.search
        # main loop
        for lrow in lit:
            start = getlstart(lrow)
            stop = getlstop(lrow)
            rrows = search(start, stop)
            if rrows:
                if not anti:
                    for rrow in rrows:
                        outrow = list(lrow)
                        outrow.extend(rrow)
                        yield tuple(outrow)
            elif leftouter:
                outrow = list(lrow)
                if not anti:
                    outrow.extend([missing] * len(rflds))
                yield tuple(outrow)

    else:
        # build interval lookup for right table
        lookup = facetintervallookup(right, key=rkey, start=rstart,
                                     stop=rstop, include_stop=include_stop)
        search = dict()
        for f in lookup:
            search[f] = lookup[f].search
        # getter for facet key values in left table
        getlkey = itemgetter(*asindices(lflds, lkey))
        # main loop
        for lrow in lit:
            lkey = getlkey(lrow)
            start = getlstart(lrow)
            stop = getlstop(lrow)
            
            try:
                rrows = search[lkey](start, stop)
            except KeyError:
                rrows = None
            except AttributeError:
                rrows = None
                
            if rrows:
                if not anti:
                    for rrow in rrows:
                        outrow = list(lrow)
                        outrow.extend(rrow)
                        yield tuple(outrow)
            elif leftouter:
                outrow = list(lrow)
                if not anti:
                    outrow.extend([missing] * len(rflds))
                yield tuple(outrow)


def _iterintervalrelations(lit, rit, lflds, rflds, lstart, lstop, rstart,
                           rstop, lkey, rkey, include_start, include_stop,
                           missing, leftouter, anti, relations):

    # create getters for interval coordinates
    getlstart = itemgetter(lflds.index(lstart))
    getlstop = itemgetter(lflds.index(lstop))
    rstartidx, rstopidx = asindices(rflds, (rstart, rstop))

    # group right rows by facet key, validating intervals
    default = ()
    if rkey is None:
        getrkey = None
        groups = {None: list()}
    else:
        getrkey = itemgetter(*asindices(rflds, rkey))
        groups = dict()
    for rrow in rit:
        _check_interval(rrow[rstartidx], rrow[rstopidx])
        rrow = tuple(rrow)
        if getrkey is None:
            groups[None].append(rrow)
        else:
            groups.setdefault(getrkey(rrow), list()).append(rrow)

    # getter for facet key values in left table
    if lkey is None:
        getlkey = None
    else:
        getlkey = itemgetter(*asindices(lflds, lkey))

    # main loop
    for lrow in lit:
        lstartv = getlstart(lrow)
        lstopv = getlstop(lrow)
        _check_interval(lstartv, lstopv)
        k = getlkey(lrow) if getlkey is not None else None
        matched = False
        for rrow in groups.get(k, default):
            relation = _classify_interval_relation(
                lstartv, lstopv, rrow[rstartidx], rrow[rstopidx],
                include_start=include_start, include_stop=include_stop)
            if relation is not None and relation in relations:
                matched = True
                if not anti:
                    outrow = list(lrow)
                    outrow.extend(rrow)
                    outrow.append(relation)
                    yield tuple(outrow)
        if not matched and leftouter:
            outrow = list(lrow)
            if not anti:
                outrow.extend([missing] * len(rflds))
                outrow.append(missing)
            yield tuple(outrow)


def intervaljoinvalues(left, right, value, lstart='start', lstop='stop',
                       rstart='start', rstop='stop', lkey=None, rkey=None,
                       include_stop=False):
    """
    Convenience function to join the left table with values from a specific 
    field in the right hand table.
    
    Note start coordinates are included and stop coordinates are excluded
    from the interval. Use the `include_stop` keyword argument to include the
    upper bound of the interval when finding overlaps.

    """
    
    assert (lkey is None) == (rkey is None), \
        'facet key field must be provided for both or neither table'
    if lkey is None:
        lkp = intervallookup(right, start=rstart, stop=rstop, value=value,
                             include_stop=include_stop)
        f = lambda row: lkp.search(row[lstart], row[lstop])
    else:
        lkp = facetintervallookup(right, rkey, start=rstart, stop=rstop,
                                  value=value, include_stop=include_stop)
        f = lambda row: lkp[row[lkey]].search(row[lstart], row[lstop])
    return addfield(left, value, f)
        
        
Table.intervaljoinvalues = intervaljoinvalues


def intervalsubtract(left, right, lstart='start', lstop='stop', rstart='start',
                     rstop='stop', lkey=None, rkey=None, include_stop=False):
    """
    Subtract intervals in the right hand table from intervals in the left hand 
    table.
    
    """

    assert (lkey is None) == (rkey is None), \
        'facet key field must be provided for both or neither table'
    return IntervalSubtractView(left, right, lstart=lstart, lstop=lstop,
                                rstart=rstart, rstop=rstop, lkey=lkey,
                                rkey=rkey, include_stop=include_stop)


Table.intervalsubtract = intervalsubtract


class IntervalSubtractView(Table):
    
    def __init__(self, left, right, lstart='start', lstop='stop', 
                 rstart='start', rstop='stop', lkey=None, rkey=None,
                 include_stop=False):
        self.left = left
        self.lstart = lstart
        self.lstop = lstop
        self.lkey = lkey
        self.right = right
        self.rstart = rstart
        self.rstop = rstop
        self.rkey = rkey
        self.include_stop = include_stop

    def __iter__(self):
        return iterintervalsubtract(self.left, self.right, self.lstart,
                                    self.lstop, self.rstart, self.rstop,
                                    self.lkey, self.rkey, self.include_stop)
        

def iterintervalsubtract(left, right, lstart, lstop, rstart, rstop, lkey, rkey,
                         include_stop):

    # create iterators and obtain fields
    lit = iter(left)
    lhdr = next(lit)
    lflds = list(map(text_type, lhdr))
    rit = iter(right)
    rhdr = next(rit)

    # check fields via petl.util.asindices (raises FieldSelectionError if spec
    # is not valid)
    asindices(lhdr, lstart)
    asindices(lhdr, lstop)
    if lkey is not None:
        asindices(lhdr, lkey)
    asindices(rhdr, rstart)
    asindices(rhdr, rstop)
    if rkey is not None:
        asindices(rhdr, rkey)

    # determine output fields
    outhdr = list(lflds)
    yield tuple(outhdr)
    
    # create getters for start and stop positions
    lstartidx, lstopidx = asindices(lhdr, (lstart, lstop))
    getlcoords = itemgetter(lstartidx, lstopidx)
    getrcoords = itemgetter(*asindices(rhdr, (rstart, rstop)))

    if rkey is None:
        # build interval lookup for right table
        lookup = intervallookup(right, rstart, rstop, include_stop=include_stop)
        search = lookup.search
        # main loop
        for lrow in lit:
            start, stop = getlcoords(lrow)
            rrows = search(start, stop)
            if not rrows:
                yield tuple(lrow)
            else:
                rivs = sorted([getrcoords(rrow) for rrow in rrows],
                              key=itemgetter(0))  # sort by start
                for x, y in _subtract(start, stop, rivs):
                    out = list(lrow)
                    out[lstartidx] = x
                    out[lstopidx] = y
                    yield tuple(out)
                
    else:
        # build interval lookup for right table
        lookup = facetintervallookup(right, key=rkey, start=rstart, stop=rstop,
                                     include_stop=include_stop)
        # getter for facet key values in left table
        getlkey = itemgetter(*asindices(lhdr, lkey))
        # main loop
        for lrow in lit:
            lkey = getlkey(lrow)
            start, stop = getlcoords(lrow)
            try:
                rrows = lookup[lkey].search(start, stop)
            except KeyError:
                rrows = None
            except AttributeError:
                rrows = None
            if not rrows:
                yield tuple(lrow)
            else:
                rivs = sorted([getrcoords(rrow) for rrow in rrows],
                              key=itemgetter(0))  # sort by start
                for x, y in _subtract(start, stop, rivs):
                    out = list(lrow)
                    out[lstartidx] = x
                    out[lstopidx] = y
                    yield tuple(out)


from collections import namedtuple
_Interval = namedtuple('Interval', 'start stop')


def collapsedintervals(table, start='start', stop='stop', key=None):
    """
    Utility function to collapse intervals in a table. 
    
    If no facet `key` is given, returns an iterator over `(start, stop)` tuples.
    
    If facet `key` is given, returns an iterator over `(key, start, stop)`
    tuples.
    
    """
    
    if key is None:
        table = sort(table, key=start)
        for iv in _collapse(values(table, (start, stop))):
            yield iv
    else:
        table = sort(table, key=(key, start))
        for k, g in rowgroupby(table, key=key, value=(start, stop)):
            for iv in _collapse(g):
                yield (k,) + iv


Table.collapsedintervals = collapsedintervals


def _collapse(intervals):
    """
    Collapse an iterable of intervals sorted by start coord.
    
    """
    span = None
    for start, stop in intervals:
        if span is None:
            span = _Interval(start, stop)
        elif start <= span.stop < stop:
            span = _Interval(span.start, stop)
        elif start > span.stop:
            yield span
            span = _Interval(start, stop)
    if span is not None:
        yield span
    
    
def _subtract(start, stop, intervals):
    """
    Subtract intervals from a spanning interval.
    
    """
    remainder_start = start
    sub_stop = None
    for sub_start, sub_stop in _collapse(intervals):
        if remainder_start < sub_start:
            yield _Interval(remainder_start, sub_start)
        remainder_start = sub_stop
    if sub_stop is not None and sub_stop < stop:
        yield _Interval(sub_stop, stop)
