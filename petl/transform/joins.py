from __future__ import absolute_import, division, print_function

import itertools
import operator

from petl.comparison import Comparable, comparable_itemgetter
from petl.compat import next, string_types, text_type
from petl.errors import ArgumentError
from petl.transform.basics import addrownumbers, cut, cutout, stack
from petl.transform.dedup import distinct
from petl.transform.sorts import sort
from petl.util.base import Table, asindices, data, header, rowgetter, rowgroupby


_ASOF_ORDER_FIELD = object()


def natural_key(left, right):
    # determine key field or fields
    lhdr = header(left)
    lflds = list(map(str, lhdr))
    rhdr = header(right)
    rflds = list(map(str, rhdr))
    key = [f for f in lflds if f in rflds]
    assert len(key) > 0, 'no fields in common'
    if len(key) == 1:
        key = key[0]  # deal with singletons
    return key


def keys_from_args(left, right, key, lkey, rkey):

    if key is lkey is rkey is None:
        # no keys specified, attempt natural join
        lkey = rkey = natural_key(left, right)
    elif key is not None and lkey is rkey is None:
        # common key specified
        lkey = rkey = key
    elif key is None and lkey is not None and rkey is not None:
        # left and right keys specified
        pass
    else:
        raise ArgumentError(
            'bad key arguments: either specify key, or specify both lkey and '
            'rkey, or provide no key/lkey/rkey arguments at all (natural join)'
        )
    return lkey, rkey


def asof_keys_from_args(left, right, key, lkey, rkey, ltime, rtime):
    lhdr = header(left)
    rhdr = header(right)
    ltime_idx = asindices(lhdr, ltime)[0]
    rtime_idx = asindices(rhdr, rtime)[0]

    if key is lkey is rkey is None:
        lflds = list(map(str, lhdr))
        rflds = list(map(str, rhdr))
        lkey, rkey = [], []
        for i, f in enumerate(lflds):
            if i == ltime_idx or f not in rflds:
                continue
            j = rflds.index(f)
            if j != rtime_idx:
                lkey.append(f)
                rkey.append(f)
    elif key is not None and lkey is rkey is None:
        lkey = [key] if isinstance(key, (string_types, int)) else list(key)
        rkey = list(lkey)
    elif key is None and lkey is not None and rkey is not None:
        lkey = [lkey] if isinstance(lkey, (string_types, int)) else list(lkey)
        rkey = [rkey] if isinstance(rkey, (string_types, int)) else list(rkey)
    else:
        raise ArgumentError(
            'bad key arguments: either specify key, or specify both lkey '
            'and rkey, or provide no key/lkey/rkey arguments at all'
        )

    lkind = asindices(lhdr, lkey) if lkey else []
    rkind = asindices(rhdr, rkey) if rkey else []
    if ltime_idx in lkind or rtime_idx in rkind:
        raise ArgumentError('time field cannot also be used as a product key')
    return lkey, rkey


def join(left, right, key=None, lkey=None, rkey=None, presorted=False,
         buffersize=None, tempdir=None, cache=True, lprefix=None, rprefix=None):
    """
    Perform an equi-join on the given tables. E.g.::

        >>> import petl as etl
        >>> table1 = [['id', 'colour'],
        ...           [1, 'blue'],
        ...           [2, 'red'],
        ...           [3, 'purple']]
        >>> table2 = [['id', 'shape'],
        ...           [1, 'circle'],
        ...           [3, 'square'],
        ...           [4, 'ellipse']]
        >>> table3 = etl.join(table1, table2, key='id')
        >>> table3
        +----+----------+----------+
        | id | colour   | shape    |
        +====+==========+==========+
        |  1 | 'blue'   | 'circle' |
        +----+----------+----------+
        |  3 | 'purple' | 'square' |
        +----+----------+----------+

        >>> # if no key is given, a natural join is tried
        ... table4 = etl.join(table1, table2)
        >>> table4
        +----+----------+----------+
        | id | colour   | shape    |
        +====+==========+==========+
        |  1 | 'blue'   | 'circle' |
        +----+----------+----------+
        |  3 | 'purple' | 'square' |
        +----+----------+----------+

        >>> # note behaviour if the key is not unique in either or both tables
        ... table5 = [['id', 'colour'],
        ...           [1, 'blue'],
        ...           [1, 'red'],
        ...           [2, 'purple']]
        >>> table6 = [['id', 'shape'],
        ...           [1, 'circle'],
        ...           [1, 'square'],
        ...           [2, 'ellipse']]
        >>> table7 = etl.join(table5, table6, key='id')
        >>> table7
        +----+----------+-----------+
        | id | colour   | shape     |
        +====+==========+===========+
        |  1 | 'blue'   | 'circle'  |
        +----+----------+-----------+
        |  1 | 'blue'   | 'square'  |
        +----+----------+-----------+
        |  1 | 'red'    | 'circle'  |
        +----+----------+-----------+
        |  1 | 'red'    | 'square'  |
        +----+----------+-----------+
        |  2 | 'purple' | 'ellipse' |
        +----+----------+-----------+

        >>> # compound keys are supported
        ... table8 = [['id', 'time', 'height'],
        ...           [1, 1, 12.3],
        ...           [1, 2, 34.5],
        ...           [2, 1, 56.7]]
        >>> table9 = [['id', 'time', 'weight'],
        ...           [1, 2, 4.5],
        ...           [2, 1, 6.7],
        ...           [2, 2, 8.9]]
        >>> table10 = etl.join(table8, table9, key=['id', 'time'])
        >>> table10
        +----+------+--------+--------+
        | id | time | height | weight |
        +====+======+========+========+
        |  1 |    2 |   34.5 |    4.5 |
        +----+------+--------+--------+
        |  2 |    1 |   56.7 |    6.7 |
        +----+------+--------+--------+

    If `presorted` is True, it is assumed that the data are already sorted by
    the given key, and the `buffersize`, `tempdir` and `cache` arguments are
    ignored. Otherwise, the data are sorted, see also the discussion of the
    `buffersize`, `tempdir` and `cache` arguments under the
    :func:`petl.transform.sorts.sort` function.

    Left and right tables with different key fields can be handled via the
    `lkey` and `rkey` arguments.

    .. versionchanged:: 1.7.16
        To ensure correct results for tables with uneven rows, tables will be
        squared up before joining to ensure correct results.

    """

    # TODO don't read data twice (occurs if using natural key)
    lkey, rkey = keys_from_args(left, right, key, lkey, rkey)
    return JoinView(left, right, lkey=lkey, rkey=rkey,
                    presorted=presorted, buffersize=buffersize, tempdir=tempdir,
                    cache=cache, lprefix=lprefix, rprefix=rprefix)


Table.join = join


class JoinView(Table):

    def __init__(self, left, right, lkey, rkey,
                 presorted=False, leftouter=False, rightouter=False,
                 missing=None, buffersize=None, tempdir=None, cache=True,
                 lprefix=None, rprefix=None):
        self.lkey = lkey
        self.rkey = rkey
        self.left = stack(left, missing=missing)
        self.right = stack(right, missing=missing)
        if not presorted:
            self.left = sort(self.left, lkey, buffersize=buffersize,
                             tempdir=tempdir, cache=cache)
            self.right = sort(self.right, rkey, buffersize=buffersize,
                              tempdir=tempdir, cache=cache)
        self.leftouter = leftouter
        self.rightouter = rightouter
        self.missing = missing
        self.lprefix = lprefix
        self.rprefix = rprefix

    def __iter__(self):
        return iterjoin(self.left, self.right, self.lkey, self.rkey,
                        leftouter=self.leftouter, rightouter=self.rightouter,
                        missing=self.missing, lprefix=self.lprefix,
                        rprefix=self.rprefix)


def leftjoin(left, right, key=None, lkey=None, rkey=None, missing=None,
             presorted=False, buffersize=None, tempdir=None, cache=True,
             lprefix=None, rprefix=None):
    """
    Perform a left outer join on the given tables. E.g.::

        >>> import petl as etl
        >>> table1 = [['id', 'colour'],
        ...           [1, 'blue'],
        ...           [2, 'red'],
        ...           [3, 'purple']]
        >>> table2 = [['id', 'shape'],
        ...           [1, 'circle'],
        ...           [3, 'square'],
        ...           [4, 'ellipse']]
        >>> table3 = etl.leftjoin(table1, table2, key='id')
        >>> table3
        +----+----------+----------+
        | id | colour   | shape    |
        +====+==========+==========+
        |  1 | 'blue'   | 'circle' |
        +----+----------+----------+
        |  2 | 'red'    | None     |
        +----+----------+----------+
        |  3 | 'purple' | 'square' |
        +----+----------+----------+

    If `presorted` is True, it is assumed that the data are already sorted by
    the given key, and the `buffersize`, `tempdir` and `cache` arguments are
    ignored. Otherwise, the data are sorted, see also the discussion of the
    `buffersize`, `tempdir` and `cache` arguments under the
    :func:`petl.transform.sorts.sort` function.

    Left and right tables with different key fields can be handled via the
    `lkey` and `rkey` arguments.

    .. versionchanged:: 1.7.16
        To ensure correct results for tables with uneven rows, tables will be
        squared up before joining to ensure correct results.

    """

    # TODO don't read data twice (occurs if using natural key)
    lkey, rkey = keys_from_args(left, right, key, lkey, rkey)
    return JoinView(left, right, lkey=lkey, rkey=rkey,
                    presorted=presorted, leftouter=True, rightouter=False,
                    missing=missing, buffersize=buffersize, tempdir=tempdir,
                    cache=cache, lprefix=lprefix, rprefix=rprefix)


Table.leftjoin = leftjoin


def rightjoin(left, right, key=None, lkey=None, rkey=None, missing=None,
              presorted=False, buffersize=None, tempdir=None, cache=True,
              lprefix=None, rprefix=None):
    """
    Perform a right outer join on the given tables. E.g.::

        >>> import petl as etl
        >>> table1 = [['id', 'colour'],
        ...           [1, 'blue'],
        ...           [2, 'red'],
        ...           [3, 'purple']]
        >>> table2 = [['id', 'shape'],
        ...           [1, 'circle'],
        ...           [3, 'square'],
        ...           [4, 'ellipse']]
        >>> table3 = etl.rightjoin(table1, table2, key='id')
        >>> table3
        +----+----------+-----------+
        | id | colour   | shape     |
        +====+==========+===========+
        |  1 | 'blue'   | 'circle'  |
        +----+----------+-----------+
        |  3 | 'purple' | 'square'  |
        +----+----------+-----------+
        |  4 | None     | 'ellipse' |
        +----+----------+-----------+

    If `presorted` is True, it is assumed that the data are already sorted by
    the given key, and the `buffersize`, `tempdir` and `cache` arguments are
    ignored. Otherwise, the data are sorted, see also the discussion of the
    `buffersize`, `tempdir` and `cache` arguments under the
    :func:`petl.transform.sorts.sort` function.

    Left and right tables with different key fields can be handled via the
    `lkey` and `rkey` arguments.

    .. versionchanged:: 1.7.16
        To ensure correct results for tables with uneven rows, tables will be
        squared up before joining to ensure correct results.

    """

    # TODO don't read data twice (occurs if using natural key)
    lkey, rkey = keys_from_args(left, right, key, lkey, rkey)
    return JoinView(left, right, lkey=lkey, rkey=rkey,
                    presorted=presorted, leftouter=False, rightouter=True,
                    missing=missing, buffersize=buffersize,
                    tempdir=tempdir, cache=cache, lprefix=lprefix,
                    rprefix=rprefix)


Table.rightjoin = rightjoin


def outerjoin(left, right, key=None, lkey=None, rkey=None, missing=None,
              presorted=False, buffersize=None, tempdir=None, cache=True,
              lprefix=None, rprefix=None):
    """
    Perform a full outer join on the given tables. E.g.::

        >>> import petl as etl
        >>> table1 = [['id', 'colour'],
        ...           [1, 'blue'],
        ...           [2, 'red'],
        ...           [3, 'purple']]
        >>> table2 = [['id', 'shape'],
        ...           [1, 'circle'],
        ...           [3, 'square'],
        ...           [4, 'ellipse']]
        >>> table3 = etl.outerjoin(table1, table2, key='id')
        >>> table3
        +----+----------+-----------+
        | id | colour   | shape     |
        +====+==========+===========+
        |  1 | 'blue'   | 'circle'  |
        +----+----------+-----------+
        |  2 | 'red'    | None      |
        +----+----------+-----------+
        |  3 | 'purple' | 'square'  |
        +----+----------+-----------+
        |  4 | None     | 'ellipse' |
        +----+----------+-----------+

    If `presorted` is True, it is assumed that the data are already sorted by
    the given key, and the `buffersize`, `tempdir` and `cache` arguments are
    ignored. Otherwise, the data are sorted, see also the discussion of the
    `buffersize`, `tempdir` and `cache` arguments under the
    :func:`petl.transform.sorts.sort` function.

    Left and right tables with different key fields can be handled via the
    `lkey` and `rkey` arguments.

    .. versionchanged:: 1.7.16
        To ensure correct results for tables with uneven rows, tables will be
        squared up before joining to ensure correct results.

    """

    # TODO don't read data twice (occurs if using natural key)
    lkey, rkey = keys_from_args(left, right, key, lkey, rkey)
    return JoinView(left, right, lkey=lkey, rkey=rkey,
                    presorted=presorted, leftouter=True, rightouter=True,
                    missing=missing, buffersize=buffersize, tempdir=tempdir,
                    cache=cache, lprefix=lprefix, rprefix=rprefix)


Table.outerjoin = outerjoin


def iterjoin(left, right, lkey, rkey, leftouter=False, rightouter=False,
             missing=None, lprefix=None, rprefix=None):
    lit = iter(left)
    rit = iter(right)

    lhdr = next(lit)
    rhdr = next(rit)

    # determine indices of the key fields in left and right tables
    lkind = asindices(lhdr, lkey)
    rkind = asindices(rhdr, rkey)

    # construct functions to extract key values from both tables
    lgetk = comparable_itemgetter(*lkind)
    rgetk = comparable_itemgetter(*rkind)

    # determine indices of non-key fields in the right table
    # (in the output, we only include key fields from the left table - we
    # don't want to duplicate fields)
    rvind = [i for i in range(len(rhdr)) if i not in rkind]
    rgetv = rowgetter(*rvind)

    # determine the output fields
    if lprefix is None:
        outhdr = list(lhdr)
    else:
        outhdr = [(text_type(lprefix) + text_type(f)) for f in lhdr]
    if rprefix is None:
        outhdr.extend(rgetv(rhdr))
    else:
        outhdr.extend([(text_type(rprefix) + text_type(f)) for f in rgetv(rhdr)])
    yield tuple(outhdr)

    # define a function to join two groups of rows
    def joinrows(_lrowgrp, _rrowgrp):
        if _rrowgrp is None:
            for lrow in _lrowgrp:
                outrow = list(lrow)  # start with the left row
                # extend with missing values in place of the right row
                outrow.extend([missing] * len(rvind))
                yield tuple(outrow)
        elif _lrowgrp is None:
            for rrow in _rrowgrp:
                # start with missing values in place of the left row
                outrow = [missing] * len(lhdr)
                # set key values
                for li, ri in zip(lkind, rkind):
                    outrow[li] = rrow[ri]
                # extend with non-key values from the right row
                outrow.extend(rgetv(rrow))
                yield tuple(outrow)
        else:
            _rrowgrp = list(_rrowgrp)  # may need to iterate more than once
            for lrow in _lrowgrp:
                for rrow in _rrowgrp:
                    # start with the left row
                    outrow = list(lrow)
                    # extend with non-key values from the right row
                    outrow.extend(rgetv(rrow))
                    yield tuple(outrow)

    # construct group iterators for both tables
    lgit = itertools.groupby(lit, key=lgetk)
    rgit = itertools.groupby(rit, key=rgetk)
    lrowgrp = []
    rrowgrp = []

    # loop until *either* of the iterators is exhausted
    # initialise here to handle empty tables
    lkval, rkval = Comparable(None), Comparable(None)
    try:

        # pick off initial row groups
        lkval, lrowgrp = next(lgit)
        rkval, rrowgrp = next(rgit)

        while True:
            if lkval < rkval:
                if leftouter:
                    for row in joinrows(lrowgrp, None):
                        yield tuple(row)
                # advance left
                lkval, lrowgrp = next(lgit)
            elif lkval > rkval:
                if rightouter:
                    for row in joinrows(None, rrowgrp):
                        yield tuple(row)
                # advance right
                rkval, rrowgrp = next(rgit)
            else:
                for row in joinrows(lrowgrp, rrowgrp):
                    yield tuple(row)
                # advance both
                lkval, lrowgrp = next(lgit)
                rkval, rrowgrp = next(rgit)

    except StopIteration:
        pass

    # make sure any left rows remaining are yielded
    if leftouter:
        if lkval > rkval:
            # yield anything that got left hanging
            for row in joinrows(lrowgrp, None):
                yield tuple(row)
        # yield the rest
        for lkval, lrowgrp in lgit:
            for row in joinrows(lrowgrp, None):
                yield tuple(row)

    # make sure any right rows remaining are yielded
    if rightouter:
        if lkval < rkval:
            # yield anything that got left hanging
            for row in joinrows(None, rrowgrp):
                yield tuple(row)
        # yield the rest
        for rkval, rrowgrp in rgit:
            for row in joinrows(None, rrowgrp):
                yield tuple(row)


def asofjoin(left, right, key=None, lkey=None, rkey=None, time='time',
             ltime=None, rtime=None, direction='backward', tolerance=None,
             inclusive=True, missing=None, presorted=False,
             buffersize=None, tempdir=None, cache=True, preserve_order=False,
             lprefix=None, rprefix=None):
    """
    Join each left row to at most one temporally-nearby right row.

    Product fields are matched exactly, while time fields are matched with
    one of three strategies:

    - ``'backward'``: the latest quote at or before the trade time
    - ``'forward'``: the earliest quote at or after the trade time
    - ``'nearest'``: whichever side has the smaller absolute time distance;
      equal distances are resolved in favour of the backward quote

    Set ``inclusive=False`` to exclude quotes whose time is exactly equal to
    the left time. The equality rule is independent of ``tolerance``, which
    limits the maximum absolute time distance. Unmatched left rows are always
    retained. Rows with a null time never match; in particular, null is not
    treated as zero.

    If ``presorted=True``, both tables are assumed to be sorted ascending by
    their product key fields and then their time field. In that case rows are
    produced incrementally and the right table is scanned without building a
    Cartesian product. Otherwise the tables are sorted using
    :func:`petl.transform.sorts.sort`, including its external sort support.
    Set ``preserve_order=True`` to restore the original order of left rows
    after an unsorted join.

    Equal product and time keys in the right table are resolved stably:
    backward and exact nearest matches use the last equal-time quote, while
    forward matches use the first. Presorted callers must therefore present
    equal-time quotes in their desired order.

    >>> import petl as etl
    >>> trades = [['product', 'time', 'price'],
    ...          ['A', 2, 10],
    ...          ['B', 4, 20]]
    >>> quotes = [['product', 'time', 'quote'],
    ...          ['A', 1, 9],
    ...          ['A', 2, 10],
    ...          ['B', 4, 21]]
    >>> etl.asofjoin(trades, quotes, key='product', time='time').lookall()
    +---------+------+-------+------+-------+
    | product | time | price | time | quote |
    +=========+======+=======+======+=======+
    | 'A'     |    2 |    10 |    2 |    10 |
    +---------+------+-------+------+-------+
    | 'B'     |    4 |    20 |    4 |    21 |
    +---------+------+-------+------+-------+

    """

    if ltime is None:
        ltime = time
    if rtime is None:
        rtime = time
    if direction not in ('backward', 'forward', 'nearest'):
        raise ArgumentError("direction must be 'backward', 'forward' or "
                            "'nearest'")
    if tolerance is not None and tolerance < 0:
        raise ArgumentError('tolerance must not be negative')

    lkey, rkey = asof_keys_from_args(left, right, key, lkey, rkey,
                                     ltime, rtime)
    return AsOfJoinView(
        left, right, lkey=lkey, rkey=rkey, ltime=ltime, rtime=rtime,
        direction=direction, tolerance=tolerance, inclusive=inclusive,
        missing=missing, presorted=presorted, buffersize=buffersize,
        tempdir=tempdir, cache=cache, preserve_order=preserve_order,
        lprefix=lprefix, rprefix=rprefix
    )


Table.asofjoin = asofjoin


class AsOfJoinView(Table):

    def __init__(self, left, right, lkey, rkey, ltime, rtime, direction,
                 tolerance, inclusive, missing, presorted, buffersize,
                 tempdir, cache, preserve_order, lprefix, rprefix):
        left = stack(left, missing=missing)
        right = stack(right, missing=missing)
        if preserve_order:
            left = addrownumbers(left, field=_ASOF_ORDER_FIELD)
        if not presorted:
            left = sort(left, list(lkey) + [ltime], buffersize=buffersize,
                         tempdir=tempdir, cache=cache)
            right = sort(right, list(rkey) + [rtime], buffersize=buffersize,
                          tempdir=tempdir, cache=cache)

        self.left = left
        self.right = right
        self.lkey = lkey
        self.rkey = rkey
        self.ltime = ltime
        self.rtime = rtime
        self.direction = direction
        self.tolerance = tolerance
        self.inclusive = inclusive
        self.missing = missing
        self.preserve_order = preserve_order
        self.buffersize = buffersize
        self.tempdir = tempdir
        self.lprefix = lprefix
        self.rprefix = rprefix

    def __iter__(self):
        result = _AsOfJoinResultView(
            self.left, self.right, lkey=self.lkey, rkey=self.rkey,
            ltime=self.ltime, rtime=self.rtime, direction=self.direction,
            tolerance=self.tolerance, inclusive=self.inclusive,
            missing=self.missing, lprefix=self.lprefix, rprefix=self.rprefix
        )
        if not self.preserve_order:
            return iter(result)

        ordered = sort(result, 0, buffersize=self.buffersize,
                       tempdir=self.tempdir,
                       cache=False)
        return iter(cutout(ordered, 0))


class _AsOfJoinResultView(Table):

    def __init__(self, left, right, lkey, rkey, ltime, rtime, direction,
                 tolerance, inclusive, missing, lprefix, rprefix):
        self.left = left
        self.right = right
        self.lkey = lkey
        self.rkey = rkey
        self.ltime = ltime
        self.rtime = rtime
        self.direction = direction
        self.tolerance = tolerance
        self.inclusive = inclusive
        self.missing = missing
        self.lprefix = lprefix
        self.rprefix = rprefix

    def __iter__(self):
        return iterasofjoin(
            self.left, self.right, lkey=self.lkey, rkey=self.rkey,
            ltime=self.ltime, rtime=self.rtime, direction=self.direction,
            tolerance=self.tolerance, inclusive=self.inclusive,
            missing=self.missing, lprefix=self.lprefix, rprefix=self.rprefix
        )


class _AsOfRightScanner(object):

    def __init__(self, rows, getkey, gettime, key, first, direction,
                 tolerance, inclusive):
        self.rows = rows
        self.getkey = getkey
        self.gettime = gettime
        self.key = key
        self.direction = direction
        self.tolerance = tolerance
        self.inclusive = inclusive
        self.first = first
        self.next_row = None
        self.behind = None
        self.equal_first = None
        self.equal_last = None
        self.equal_target = None
        self.equal_complete = False
        self.ahead = None
        self._advance()

    def _next_same_key(self):
        if self.first is not None:
            row = self.first
            self.first = None
            return row
        while True:
            row = next(self.rows)
            if self.getkey(row) == self.key:
                return row
            self.next_row = row
            raise StopIteration

    def _advance(self):
        self.ahead = self._read_non_null()

    def _read_non_null(self):
        while True:
            try:
                row = self._next_same_key()
            except StopIteration:
                return None
            if self.gettime(row) is not None:
                return row

    def _read_equal_until_future(self):
        self.ahead = None
        while True:
            row = self._read_non_null()
            if row is None or self.gettime(row) != self.equal_target:
                self.ahead = row
                return
            self.equal_last = row

    def seek(self, target):
        if self.equal_last is not None:
            equal_time = self.gettime(self.equal_last)
            if equal_time < target:
                self.behind = self.equal_last
                self.equal_first = None
                self.equal_last = None
                self.equal_target = None
                self.equal_complete = False
            elif equal_time == target:
                if not self.equal_complete:
                    self._read_equal_until_future()
                    self.equal_complete = True
                return

        if self.ahead is not None:
            ahead_time = self.gettime(self.ahead)
            if ahead_time < target:
                self.behind = self.ahead
                self.ahead = None
            elif ahead_time == target:
                self.equal_first = self.ahead
                self.equal_last = self.ahead
                self.equal_target = target
                self._read_equal_until_future()
                self.equal_complete = True
                return
            elif ahead_time > target:
                return

        while self.ahead is None:
            row = self._read_non_null()
            if row is None:
                return
            row_time = self.gettime(row)
            if row_time < target:
                self.behind = row
            elif row_time == target:
                self.equal_first = row
                self.equal_last = row
                self.equal_target = target
                self._read_equal_until_future()
                self.equal_complete = True
                return
            else:
                self.ahead = row
                return

    def match(self, target):
        if self.inclusive:
            backward_row = self.equal_last if self.equal_last is not None else self.behind
            forward_row = self.equal_first if self.equal_first is not None else self.ahead
        else:
            backward_row = self.behind
            forward_row = self.ahead

        if self.direction == 'backward':
            candidate = backward_row
        elif self.direction == 'forward':
            candidate = forward_row
        else:
            candidate = self._nearest(target, backward_row, forward_row)

        if candidate is None:
            return None
        distance = abs(self.gettime(candidate) - target)
        if self.tolerance is not None and distance > self.tolerance:
            return None
        return candidate

    def _nearest(self, target, backward_row, forward_row):
        if backward_row is None:
            return forward_row
        if forward_row is None:
            return backward_row
        backward_distance = target - self.gettime(backward_row)
        forward_distance = self.gettime(forward_row) - target
        if forward_distance < backward_distance:
            return forward_row
        return backward_row


def iterasofjoin(left, right, lkey, rkey, ltime, rtime, direction,
                 tolerance, inclusive, missing=None, lprefix=None,
                 rprefix=None):
    lit = iter(left)
    rit = iter(right)
    lhdr = next(lit)
    rhdr = next(rit)

    lkind = asindices(lhdr, lkey) if lkey else []
    rkind = asindices(rhdr, rkey) if rkey else []
    ltime_idx = asindices(lhdr, ltime)[0]
    rtime_idx = asindices(rhdr, rtime)[0]
    lgetk = comparable_itemgetter(*lkind) if lkind else lambda row: Comparable(())
    rgetk = comparable_itemgetter(*rkind) if rkind else lambda row: Comparable(())
    lgettime = operator.itemgetter(ltime_idx)
    rgettime = operator.itemgetter(rtime_idx)

    rvind = [i for i in range(len(rhdr)) if i not in rkind]
    rgetv = rowgetter(*rvind)

    if lprefix is None:
        outhdr = list(lhdr)
    else:
        outhdr = [(text_type(lprefix) + text_type(f)) for f in lhdr]
    if rprefix is None:
        outhdr.extend(rgetv(rhdr))
    else:
        outhdr.extend([(text_type(rprefix) + text_type(f))
                       for f in rgetv(rhdr)])
    yield tuple(outhdr)

    def unmatched(row):
        return tuple(list(row) + [missing] * len(rvind))

    lgit = itertools.groupby(lit, key=lgetk)

    try:
        lkval, lgroup = next(lgit)
    except StopIteration:
        return
    try:
        rrow = next(rit)
        rkval = rgetk(rrow)
        r_left = False
    except StopIteration:
        r_left = True

    while True:
        if r_left:
            for row in lgroup:
                yield unmatched(row)
            try:
                lkval, lgroup = next(lgit)
                continue
            except StopIteration:
                return
        if lkval < rkval:
            for row in lgroup:
                yield unmatched(row)
            try:
                lkval, lgroup = next(lgit)
            except StopIteration:
                return
        elif lkval > rkval:
            while not r_left and rgetk(rrow) == rkval:
                try:
                    rrow = next(rit)
                except StopIteration:
                    r_left = True
            if not r_left:
                rkval = rgetk(rrow)
        else:
            scanner = _AsOfRightScanner(
                rit, rgetk, rgettime, rkval, rrow, direction, tolerance,
                inclusive
            )
            for row in lgroup:
                target = lgettime(row)
                if target is None:
                    yield unmatched(row)
                    continue
                scanner.seek(target)
                quote = scanner.match(target)
                if quote is None:
                    yield unmatched(row)
                else:
                    yield tuple(list(row) + list(rgetv(quote)))

            try:
                lkval, lgroup = next(lgit)
            except StopIteration:
                return

            if scanner.ahead is not None:
                rrow = scanner.ahead
            elif scanner.next_row is not None:
                rrow = scanner.next_row
            else:
                rrow = None
            r_left = rrow is None

    for _, group in lgit:
        for row in group:
            yield unmatched(row)


def crossjoin(*tables, **kwargs):
    """
    Form the cartesian product of the given tables. E.g.::

        >>> import petl as etl
        >>> table1 = [['id', 'colour'],
        ...           [1, 'blue'],
        ...           [2, 'red']]
        >>> table2 = [['id', 'shape'],
        ...           [1, 'circle'],
        ...           [3, 'square']]
        >>> table3 = etl.crossjoin(table1, table2)
        >>> table3
        +----+--------+----+----------+
        | id | colour | id | shape    |
        +====+========+====+==========+
        |  1 | 'blue' |  1 | 'circle' |
        +----+--------+----+----------+
        |  1 | 'blue' |  3 | 'square' |
        +----+--------+----+----------+
        |  2 | 'red'  |  1 | 'circle' |
        +----+--------+----+----------+
        |  2 | 'red'  |  3 | 'square' |
        +----+--------+----+----------+

    If `prefix` is `True` then field names in the output table header will be
    prefixed by the index of the input table.

    .. versionchanged:: 1.7.16
        To ensure correct results for tables with uneven rows, tables will be
        squared up before joining to ensure correct results.

    """

    return CrossJoinView(*tables, **kwargs)


Table.crossjoin = crossjoin


class CrossJoinView(Table):

    def __init__(self, *sources, **kwargs):
        self.prefix = kwargs.get('prefix', False)
        self.missing = kwargs.get('missing', None)
        self.sources = [stack(source, missing=self.missing) for source in sources]

    def __iter__(self):
        return itercrossjoin(self.sources, self.prefix)


def itercrossjoin(sources, prefix):

    # construct fields
    outhdr = list()
    for i, s in enumerate(sources):
        if prefix:
            # use one-based numbering
            outhdr.extend([text_type(i+1) + '_' + text_type(f) for f in header(s)])
        else:
            outhdr.extend(header(s))
    yield tuple(outhdr)

    datasrcs = [data(src) for src in sources]
    for prod in itertools.product(*datasrcs):
        outrow = list()
        for row in prod:
            outrow.extend(row)
        yield tuple(outrow)


def antijoin(left, right, key=None, lkey=None, rkey=None, presorted=False,
             buffersize=None, tempdir=None, cache=True):
    """
    Return rows from the `left` table where the key value does not occur in
    the `right` table. E.g.::

        >>> import petl as etl
        >>> table1 = [['id', 'colour'],
        ...           [0, 'black'],
        ...           [1, 'blue'],
        ...           [2, 'red'],
        ...           [4, 'yellow'],
        ...           [5, 'white']]
        >>> table2 = [['id', 'shape'],
        ...           [1, 'circle'],
        ...           [3, 'square']]
        >>> table3 = etl.antijoin(table1, table2, key='id')
        >>> table3
        +----+----------+
        | id | colour   |
        +====+==========+
        |  0 | 'black'  |
        +----+----------+
        |  2 | 'red'    |
        +----+----------+
        |  4 | 'yellow' |
        +----+----------+
        |  5 | 'white'  |
        +----+----------+

    If `presorted` is True, it is assumed that the data are already sorted by
    the given key, and the `buffersize`, `tempdir` and `cache` arguments are
    ignored. Otherwise, the data are sorted, see also the discussion of the
    `buffersize`, `tempdir` and `cache` arguments under the
    :func:`petl.transform.sorts.sort` function.

    Left and right tables with different key fields can be handled via the
    `lkey` and `rkey` arguments.

    """

    lkey, rkey = keys_from_args(left, right, key, lkey, rkey)
    return AntiJoinView(left=left, right=right, lkey=lkey, rkey=rkey,
                        presorted=presorted, buffersize=buffersize,
                        tempdir=tempdir, cache=cache)


Table.antijoin = antijoin


class AntiJoinView(Table):

    def __init__(self, left, right, lkey, rkey, presorted=False,
                 buffersize=None, tempdir=None, cache=True):
        if presorted:
            self.left = left
            self.right = right
        else:
            self.left = sort(left, lkey, buffersize=buffersize,
                             tempdir=tempdir, cache=cache)
            self.right = sort(right, rkey, buffersize=buffersize,
                              tempdir=tempdir, cache=cache)
        self.lkey = lkey
        self.rkey = rkey

    def __iter__(self):
        return iterantijoin(self.left, self.right, self.lkey, self.rkey)


def iterantijoin(left, right, lkey, rkey):
    lit = iter(left)
    rit = iter(right)

    lhdr = next(lit)
    rhdr = next(rit)
    yield tuple(lhdr)

    # determine indices of the key fields in left and right tables
    lkind = asindices(lhdr, lkey)
    rkind = asindices(rhdr, rkey)

    # construct functions to extract key values from both tables
    lgetk = comparable_itemgetter(*lkind)
    rgetk = comparable_itemgetter(*rkind)

    # construct group iterators for both tables
    lgit = itertools.groupby(lit, key=lgetk)
    rgit = itertools.groupby(rit, key=rgetk)
    lrowgrp = []

    # loop until *either* of the iterators is exhausted
    lkval, rkval = Comparable(None), Comparable(None)
    try:

        # pick off initial row groups
        lkval, lrowgrp = next(lgit)
        rkval, _ = next(rgit)

        while True:
            if lkval < rkval:
                for row in lrowgrp:
                    yield tuple(row)
                # advance left
                lkval, lrowgrp = next(lgit)
            elif lkval > rkval:
                # advance right
                rkval, _ = next(rgit)
            else:
                # advance both
                lkval, lrowgrp = next(lgit)
                rkval, _ = next(rgit)

    except StopIteration:
        pass

    # any left over?
    if lkval > rkval:
        # yield anything that got left hanging
        for row in lrowgrp:
            yield tuple(row)
    # and the rest...
    for lkval, lrowgrp in lgit:
        for row in lrowgrp:
            yield tuple(row)


def lookupjoin(left, right, key=None, lkey=None, rkey=None, missing=None,
               presorted=False, buffersize=None, tempdir=None, cache=True,
               lprefix=None, rprefix=None):
    """
    Perform a left join, but where the key is not unique in the right-hand
    table, arbitrarily choose the first row and ignore others. E.g.::

        >>> import petl as etl
        >>> table1 = [['id', 'color', 'cost'],
        ...           [1, 'blue', 12],
        ...           [2, 'red', 8],
        ...           [3, 'purple', 4]]
        >>> table2 = [['id', 'shape', 'size'],
        ...           [1, 'circle', 'big'],
        ...           [1, 'circle', 'small'],
        ...           [2, 'square', 'tiny'],
        ...           [2, 'square', 'big'],
        ...           [3, 'ellipse', 'small'],
        ...           [3, 'ellipse', 'tiny']]
        >>> table3 = etl.lookupjoin(table1, table2, key='id')
        >>> table3
        +----+----------+------+-----------+---------+
        | id | color    | cost | shape     | size    |
        +====+==========+======+===========+=========+
        |  1 | 'blue'   |   12 | 'circle'  | 'big'   |
        +----+----------+------+-----------+---------+
        |  2 | 'red'    |    8 | 'square'  | 'tiny'  |
        +----+----------+------+-----------+---------+
        |  3 | 'purple' |    4 | 'ellipse' | 'small' |
        +----+----------+------+-----------+---------+

    See also :func:`petl.transform.joins.leftjoin`.

    .. versionchanged:: 1.7.16
        To ensure correct results for tables with uneven rows, tables will be
        squared up before joining to ensure correct results.

    """

    lkey, rkey = keys_from_args(left, right, key, lkey, rkey)
    return LookupJoinView(left, right, lkey, rkey, presorted=presorted,
                          missing=missing, buffersize=buffersize,
                          tempdir=tempdir, cache=cache,
                          lprefix=lprefix, rprefix=rprefix)


Table.lookupjoin = lookupjoin


class LookupJoinView(Table):

    def __init__(self, left, right, lkey, rkey, presorted=False, missing=None,
                 buffersize=None, tempdir=None, cache=True,
                 lprefix=None, rprefix=None):
        self.left = stack(left, missing=missing)
        self.right = stack(right, missing=missing)
        if not presorted:
            self.left = sort(self.left, lkey, buffersize=buffersize,
                             tempdir=tempdir, cache=cache)
            self.right = sort(self.right, rkey, buffersize=buffersize,
                              tempdir=tempdir, cache=cache)
        self.lkey = lkey
        self.rkey = rkey
        self.missing = missing
        self.lprefix = lprefix
        self.rprefix = rprefix

    def __iter__(self):
        return iterlookupjoin(self.left, self.right, self.lkey, self.rkey,
                              missing=self.missing, lprefix=self.lprefix,
                              rprefix=self.rprefix)


def iterlookupjoin(left, right, lkey, rkey, missing=None, lprefix=None,
                   rprefix=None):
    lit = iter(left)
    rit = iter(right)

    lhdr = next(lit)
    rhdr = next(rit)

    # determine indices of the key fields in left and right tables
    lkind = asindices(lhdr, lkey)
    rkind = asindices(rhdr, rkey)

    # construct functions to extract key values from both tables
    lgetk = comparable_itemgetter(*lkind)
    rgetk = comparable_itemgetter(*rkind)

    # determine indices of non-key fields in the right table
    # (in the output, we only include key fields from the left table - we
    # don't want to duplicate fields)
    rvind = [i for i in range(len(rhdr)) if i not in rkind]
    rgetv = rowgetter(*rvind)

    # determine the output fields
    if lprefix is None:
        outhdr = list(lhdr)
    else:
        outhdr = [(text_type(lprefix) + text_type(f)) for f in lhdr]
    if rprefix is None:
        outhdr.extend(rgetv(rhdr))
    else:
        outhdr.extend([(text_type(rprefix) + text_type(f)) for f in rgetv(rhdr)])
    yield tuple(outhdr)

    # define a function to join two groups of rows
    def joinrows(_lrowgrp, _rrowgrp):
        if _rrowgrp is None:
            for lrow in _lrowgrp:
                outrow = list(lrow)  # start with the left row
                # extend with missing values in place of the right row
                outrow.extend([missing] * len(rvind))
                yield tuple(outrow)
        else:
            rrow = next(iter(_rrowgrp))  # pick first arbitrarily
            for lrow in _lrowgrp:
                # start with the left row
                outrow = list(lrow)
                # extend with non-key values from the right row
                outrow.extend(rgetv(rrow))
                yield tuple(outrow)

    # construct group iterators for both tables
    lgit = itertools.groupby(lit, key=lgetk)
    rgit = itertools.groupby(rit, key=rgetk)
    lrowgrp = []

    # whether lrowgrp holds a group that has been picked off lgit but not yet
    # yielded; tracked explicitly because no key value can stand in for
    # "iterator exhausted" - None is itself a valid key
    lgrp_pending = False

    # loop until *either* of the iterators is exhausted
    try:

        # pick off initial row groups
        lkval, lrowgrp = next(lgit)
        lgrp_pending = True
        rkval, rrowgrp = next(rgit)

        while True:
            if lkval < rkval:
                for row in joinrows(lrowgrp, None):
                    yield tuple(row)
                # advance left
                lgrp_pending = False
                lkval, lrowgrp = next(lgit)
                lgrp_pending = True
            elif lkval > rkval:
                # advance right
                rkval, rrowgrp = next(rgit)
            else:
                for row in joinrows(lrowgrp, rrowgrp):
                    yield tuple(row)
                # advance both
                lgrp_pending = False
                lkval, lrowgrp = next(lgit)
                lgrp_pending = True
                rkval, rrowgrp = next(rgit)

    except StopIteration:
        pass

    # make sure any left rows remaining are yielded
    if lgrp_pending:
        # yield anything that got left hanging
        for row in joinrows(lrowgrp, None):
            yield tuple(row)
    # yield the rest
    for lkval, lrowgrp in lgit:
        for row in joinrows(lrowgrp, None):
            yield tuple(row)


def unjoin(table, value, key=None, autoincrement=(1, 1), presorted=False,
           buffersize=None, tempdir=None, cache=True):
    """
    Split a table into two tables by reversing an inner join. E.g.::

        >>> import petl as etl
        >>> # join key is present in the table
        ... table1 = (('foo', 'bar', 'baz'),
        ...           ('A', 1, 'apple'),
        ...           ('B', 1, 'apple'),
        ...           ('C', 2, 'orange'))
        >>> table2, table3 = etl.unjoin(table1, 'baz', key='bar')
        >>> table2
        +-----+-----+
        | foo | bar |
        +=====+=====+
        | 'A' |   1 |
        +-----+-----+
        | 'B' |   1 |
        +-----+-----+
        | 'C' |   2 |
        +-----+-----+

        >>> table3
        +-----+----------+
        | bar | baz      |
        +=====+==========+
        |   1 | 'apple'  |
        +-----+----------+
        |   2 | 'orange' |
        +-----+----------+

        >>> # an integer join key can also be reconstructed
        ... table4 = (('foo', 'bar'),
        ...           ('A', 'apple'),
        ...           ('B', 'apple'),
        ...           ('C', 'orange'))
        >>> table5, table6 = etl.unjoin(table4, 'bar')
        >>> table5
        +-----+--------+
        | foo | bar_id |
        +=====+========+
        | 'A' |      1 |
        +-----+--------+
        | 'B' |      1 |
        +-----+--------+
        | 'C' |      2 |
        +-----+--------+

        >>> table6
        +----+----------+
        | id | bar      |
        +====+==========+
        |  1 | 'apple'  |
        +----+----------+
        |  2 | 'orange' |
        +----+----------+

    The `autoincrement` parameter controls how an integer join key is
    reconstructed, and should be a tuple of (`start`, `step`).

    """

    if key is None:
        # first sort the table by the value field
        if presorted:
            tbl_sorted = table
        else:
            tbl_sorted = sort(table, value, buffersize=buffersize,
                              tempdir=tempdir, cache=cache)
        # on the left, return the original table but with the value field
        # replaced by an incrementing integer
        left = ConvertToIncrementingCounterView(tbl_sorted, value,
                                                autoincrement)
        # on the right, return a new table with distinct values from the
        # given field
        right = EnumerateDistinctView(tbl_sorted, value, autoincrement)
    else:
        # on the left, return distinct rows from the original table
        # with the value field cut out
        left = distinct(cutout(table, value))
        # on the right, return distinct rows from the original table
        # with all fields but the key and value cut out
        right = distinct(cut(table, key, value))
    return left, right


class ConvertToIncrementingCounterView(Table):

    def __init__(self, tbl, value, autoincrement):
        self.table = tbl
        self.value = value
        self.autoincrement = autoincrement

    def __iter__(self):
        it = iter(self.table)
        hdr = next(it)
        table = itertools.chain([hdr], it)
        value = self.value
        vidx = hdr.index(value)
        outhdr = list(hdr)
        outhdr[vidx] = '%s_id' % value
        yield tuple(outhdr)
        offset, multiplier = self.autoincrement
        for n, (_, group) in enumerate(rowgroupby(table, value)):
            for row in group:
                outrow = list(row)
                outrow[vidx] = (n * multiplier) + offset
                yield tuple(outrow)


Table.unjoin = unjoin


class EnumerateDistinctView(Table):

    def __init__(self, tbl, value, autoincrement):
        self.table = tbl
        self.value = value
        self.autoincrement = autoincrement

    def __iter__(self):
        offset, multiplier = self.autoincrement
        yield ('id', self.value)
        for n, (v, _) in enumerate(rowgroupby(self.table, self.value)):
            yield ((n * multiplier) + offset, v)
