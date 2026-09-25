from __future__ import absolute_import, division, print_function

from collections import Counter

from petl.compat import next
from petl.errors import ArgumentError
from petl.util.base import Table, asindices, rowgetter


def divide(source, requirement, entity=None, item=None, ritem=None,
           candidates=None, semantics='multiset', null_equals=True):
    """
    Perform a relational division of the `source` table by the
    `requirement` table, i.e., find all entities in `source` that are
    associated with *every* item required by `requirement`. E.g., given
    samples and the tests performed on them, find the samples that have
    all of a required set of tests::

        >>> import petl as etl
        >>> samples = [['sample', 'test'],
        ...            ['s1', 'glucose'],
        ...            ['s1', 'sodium'],
        ...            ['s1', 'sodium'],
        ...            ['s2', 'glucose'],
        ...            ['s3', 'glucose'],
        ...            ['s3', 'sodium']]
        >>> required = [['test'],
        ...             ['glucose'],
        ...             ['sodium']]
        >>> etl.divide(samples, required, entity='sample', item='test')
        +--------+
        | sample |
        +========+
        | 's1'   |
        +--------+
        | 's3'   |
        +--------+

    The `entity` argument gives the field (or fields, for a compound key)
    in `source` identifying an entity, and `item` gives the field (or
    fields) identifying the associated item. If `item` is not given, all
    fields of `source` not in `entity` are used. The `ritem` argument
    gives the corresponding field (or fields) in `requirement`, defaulting
    to the same field names as `item`. Compound keys are supported for
    both `entity` and `item`/`ritem` by passing a list or tuple of
    fields.

    The `semantics` argument controls how duplicate rows are treated. With
    the default `semantics='multiset'`, duplicate rows in `requirement`
    are significant: if a required item occurs *n* times, an entity must be
    associated with at least *n* occurrences of that item in `source` to
    qualify. With `semantics='set'`, duplicates are ignored on both sides
    and only the presence of each required item matters.

    If the `requirement` table has no data rows, every candidate entity
    qualifies. The set of candidate entities is taken from `source` by
    default, i.e., only entities appearing in `source` are considered.
    Alternatively, an explicit collection of candidate entities can be
    provided via the `candidates` argument, as a table with the entity key
    field(s). This is the only way for entities with no rows at all in
    `source` to appear in the result, e.g.::

        >>> empty_req = [['test']]
        >>> candidates = [['sample'], ['s1'], ['s2'], ['s3'], ['s4']]
        >>> etl.divide(samples, empty_req, entity='sample', item='test',
        ...            candidates=candidates)
        +--------+
        | sample |
        +========+
        | 's1'   |
        +--------+
        | 's2'   |
        +--------+
        | 's3'   |
        +--------+
        | 's4'   |
        +--------+

    The `null_equals` argument controls how `None` values in item keys
    are matched. By default (`null_equals=True`) `None` is treated as an
    ordinary value, so a `None` item in `source` matches a `None` item
    in `requirement`. If `null_equals=False`, any row whose item key
    contains `None` never matches anything and is effectively ignored on
    both sides.

    The result contains one row per qualifying entity, in order of first
    appearance (in `candidates` if given, otherwise in `source`).

    The implementation builds in-memory lookups for both tables and never
    expands the cartesian product of entities and required items, so it
    scales linearly with the size of the input tables.

    See also :func:`petl.transform.division.dividemissing`.

    """

    _check_semantics(semantics)
    return DivideView(source, requirement, entity=entity, item=item,
                      ritem=ritem, candidates=candidates,
                      semantics=semantics, null_equals=null_equals)


Table.divide = divide


def dividemissing(source, requirement, entity=None, item=None, ritem=None,
                  candidates=None, semantics='multiset', null_equals=True):
    """
    Like :func:`petl.transform.division.divide`, but instead of returning
    the qualifying entities, return a row for each required item that an
    entity is missing, together with how many occurrences are missing. Only
    entities that do *not* satisfy the requirement appear in the output.
    E.g.::

        >>> import petl as etl
        >>> samples = [['sample', 'test'],
        ...            ['s1', 'glucose'],
        ...            ['s1', 'sodium'],
        ...            ['s2', 'glucose'],
        ...            ['s2', 'sodium'],
        ...            ['s2', 'sodium']]
        >>> required = [['test'],
        ...             ['glucose'],
        ...             ['sodium'],
        ...             ['sodium']]
        >>> etl.dividemissing(samples, required, entity='sample',
        ...                   item='test')
        +--------+----------+---------+
        | sample | test     | missing |
        +========+==========+=========+
        | 's1'   | 'sodium' |       1 |
        +--------+----------+---------+

    Here `s1` fails the division because `sodium` is required twice
    (multiset semantics, the default) but occurs only once for `s1`, so
    one occurrence is missing. Entity `s2` satisfies the requirement and
    so does not appear.

    All arguments have the same meaning as for
    :func:`petl.transform.division.divide`. With `semantics='set'` the
    `missing` count is always 1, since only presence is checked.

    The output fields are the entity key fields (named as in `source`),
    followed by the item key fields (named as in `source`), followed by a
    `missing` field giving the number of missing occurrences of the
    required item.

    """

    _check_semantics(semantics)
    return DivideMissingView(source, requirement, entity=entity, item=item,
                             ritem=ritem, candidates=candidates,
                             semantics=semantics, null_equals=null_equals)


Table.dividemissing = dividemissing


def _check_semantics(semantics):
    if semantics not in ('set', 'multiset'):
        raise ArgumentError(
            "semantics must be 'set' or 'multiset', got %r" % (semantics,))


def _resolve_indices(shdr, rhdr, entity, item, ritem):
    if entity is None:
        raise ArgumentError('entity key field(s) must be given')
    eind = asindices(shdr, entity)
    if item is None:
        # default to all source fields not part of the entity key
        iind = [i for i in range(len(shdr)) if i not in eind]
        if not iind:
            raise ArgumentError(
                'no item fields: source has no fields outside the entity '
                'key, specify item explicitly')
    else:
        iind = asindices(shdr, item)
    if ritem is None:
        # default to the same field names as the source item fields
        ritem = [shdr[i] for i in iind]
    rind = asindices(rhdr, ritem)
    if len(iind) != len(rind):
        raise ArgumentError(
            'item and ritem must select the same number of fields')
    return eind, iind, rind


def _contains_null(key):
    return any(v is None for v in key)


def _prepare(source, requirement, entity, item, ritem, candidates,
             semantics, null_equals):
    """Build the lookup structures shared by divide and dividemissing.

    Returns a tuple (ehdr, ihdr, universe, have, required) where `ehdr` is
    the entity key header, `ihdr` is the item key header, `universe` is
    the ordered list of candidate entity keys, `have` maps entity keys to
    Counters of item keys, and `required` is a Counter of required item
    keys.
    """

    sit = iter(source)
    shdr = tuple(next(sit))
    rit = iter(requirement)
    rhdr = tuple(next(rit))

    eind, iind, rind = _resolve_indices(shdr, rhdr, entity, item, ritem)
    get_entity = rowgetter(*eind)
    get_item = rowgetter(*iind)
    get_ritem = rowgetter(*rind)

    # build the counter of required items
    required = Counter()
    for rrow in rit:
        k = get_ritem(rrow)
        if not null_equals and _contains_null(k):
            continue
        required[k] += 1
    if semantics == 'set':
        required = Counter(dict.fromkeys(required, 1))

    # build a counter of items per entity, in a single pass over source
    have = dict()
    universe = list()
    for srow in sit:
        ek = get_entity(srow)
        if ek not in have:
            have[ek] = Counter()
            if candidates is None:
                universe.append(ek)
        ik = get_item(srow)
        if not null_equals and _contains_null(ik):
            continue
        have[ek][ik] += 1
    if semantics == 'set':
        have = {ek: Counter(dict.fromkeys(c, 1)) for ek, c in have.items()}

    if candidates is not None:
        # explicit candidate entities define the universe, deduplicated in
        # order of first appearance
        universe = list()
        seen = set()
        cit = iter(candidates)
        chdr = tuple(next(cit))
        cind = asindices(chdr, entity)
        get_candidate = rowgetter(*cind)
        for crow in cit:
            ek = get_candidate(crow)
            if ek not in seen:
                seen.add(ek)
                universe.append(ek)

    ehdr = tuple(shdr[i] for i in eind)
    ihdr = tuple(shdr[i] for i in iind)
    return ehdr, ihdr, universe, have, required


class DivideView(Table):

    def __init__(self, source, requirement, entity=None, item=None,
                 ritem=None, candidates=None, semantics='multiset',
                 null_equals=True):
        self.source = source
        self.requirement = requirement
        self.entity = entity
        self.item = item
        self.ritem = ritem
        self.candidates = candidates
        self.semantics = semantics
        self.null_equals = null_equals

    def __iter__(self):
        ehdr, ihdr, universe, have, required = _prepare(
            self.source, self.requirement, self.entity, self.item,
            self.ritem, self.candidates, self.semantics, self.null_equals)
        yield ehdr
        empty = Counter()
        for ek in universe:
            counts = have.get(ek, empty)
            if all(counts[k] >= n for k, n in required.items()):
                yield ek


class DivideMissingView(Table):

    def __init__(self, source, requirement, entity=None, item=None,
                 ritem=None, candidates=None, semantics='multiset',
                 null_equals=True):
        self.source = source
        self.requirement = requirement
        self.entity = entity
        self.item = item
        self.ritem = ritem
        self.candidates = candidates
        self.semantics = semantics
        self.null_equals = null_equals

    def __iter__(self):
        ehdr, ihdr, universe, have, required = _prepare(
            self.source, self.requirement, self.entity, self.item,
            self.ritem, self.candidates, self.semantics, self.null_equals)
        yield ehdr + ihdr + ('missing',)
        empty = Counter()
        for ek in universe:
            counts = have.get(ek, empty)
            for k, n in required.items():
                deficit = n - counts[k]
                if deficit > 0:
                    yield ek + k + (deficit,)
