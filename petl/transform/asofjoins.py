from __future__ import absolute_import, division, print_function

import itertools

from petl.comparison import Comparable, comparable_itemgetter
from petl.compat import text_type
from petl.errors import ArgumentError
from petl.transform.basics import addrownumbers, cutout, stack
from petl.transform.sorts import sort
from petl.util.base import Table, asindices, rowgetter


DIRECTIONS = ('backward', 'forward', 'nearest')
_ORDER_FIELD = object()


def _single_index(hdr, field, label):
    indices = asindices(hdr, field)
    if len(indices) != 1:
        raise ArgumentError('%s must refer to exactly one field' % label)
    return indices[0]


def _validate_time_args(time=None, ltime=None, rtime=None):
    if time is not None:
        if ltime is not None or rtime is not None:
            raise ArgumentError(
                'specify either time, or both ltime and rtime'
            )
    elif ltime is None or rtime is None:
        raise ArgumentError(
            'a time field must be specified with time, or both ltime and '
            'rtime'
        )


def _resolve_time(lhdr, rhdr, time=None, ltime=None, rtime=None):
    if time is not None:
        ltime = rtime = time
    return (_single_index(lhdr, ltime, 'ltime'),
            _single_index(rhdr, rtime, 'rtime'))


def _validate_key_args(key=None, lkey=None, rkey=None):
    if key is not None and (lkey is not None or rkey is not None):
        raise ArgumentError(
            'specify either key, or both lkey and rkey, but not both'
        )
    if (lkey is None) != (rkey is None):
        raise ArgumentError('both lkey and rkey must be specified')


def _resolve_keys(lhdr, rhdr, ltime, rtime, key=None, lkey=None,
                  rkey=None):
    if key is not None:
        lkey = rkey = key
    elif lkey is None:
        lflds = list(map(text_type, lhdr))
        rflds = list(map(text_type, rhdr))
        lkey = []
        for li, field in enumerate(lflds):
            if li == ltime:
                continue
            if field in rflds:
                ri = rflds.index(field)
                if ri != rtime:
                    lkey.append(field)
        rkey = list(lkey)

    lindices = asindices(lhdr, lkey)
    rindices = asindices(rhdr, rkey)
    if len(lindices) != len(rindices):
        raise ArgumentError('lkey and rkey must have the same length')
    return lindices, rindices


def _peek_header(table):
    it = iter(table)
    try:
        hdr = next(it)
    except StopIteration:
        return iter(()), []
    return itertools.chain([hdr], it), hdr


def asofjoin(left, right, key=None, lkey=None, rkey=None, time=None,
             ltime=None, rtime=None, direction='backward', tolerance=None,
             allow_exact_matches=True, allow_equal=None, missing=None,
             presorted=False, preserve_left_order=False, buffersize=None,
             tempdir=None, cache=True, lprefix=None, rprefix=None):
    """
    Join each left row to one nearby row in the right table for the same key.

    Product keys may be one or more fields. Time fields are given with
    'time', or separately with 'ltime' and 'rtime'. Supported directions are
    'backward', 'forward' and 'nearest'. For a nearest tie, the backward row
    is chosen.

    Set 'allow_exact_matches' (or its alias 'allow_equal') to False to
    exclude equal times. A match is only returned if its absolute time
    distance is within 'tolerance'. Unmatched left rows are retained, and
    null times never match. Duplicate right rows at the same key and time are
    resolved stably by choosing the first row in sorted order.

    If 'presorted' is True, both inputs must already be ordered by product
    keys and then time, and output is produced incrementally. Otherwise,
    petl's external sort is used. With unsorted input,
    'preserve_left_order=True' restores the original order of left rows.
    """

    if direction not in DIRECTIONS:
        raise ArgumentError(
            "direction must be 'backward', 'forward' or 'nearest'"
        )
    if allow_equal is not None:
        allow_exact_matches = allow_equal
    _validate_time_args(time=time, ltime=ltime, rtime=rtime)
    _validate_key_args(key=key, lkey=lkey, rkey=rkey)
    if tolerance is not None:
        zero = tolerance - tolerance
        if tolerance < zero:
            raise ArgumentError('tolerance must not be negative')
    if presorted and preserve_left_order:
        raise ArgumentError(
            'preserve_left_order is only supported when presorted is False'
        )

    return AsOfJoinView(
        left, right, key=key, lkey=lkey, rkey=rkey, time=time,
        ltime=ltime, rtime=rtime, direction=direction, tolerance=tolerance,
        allow_exact_matches=allow_exact_matches, missing=missing,
        presorted=presorted,
        preserve_left_order=preserve_left_order, buffersize=buffersize,
        tempdir=tempdir, cache=cache, lprefix=lprefix, rprefix=rprefix
    )


Table.asofjoin = asofjoin


class AsOfJoinView(Table):

    def __init__(self, left, right, key=None, lkey=None, rkey=None,
                 time=None, ltime=None, rtime=None, direction='backward',
                 tolerance=None, allow_exact_matches=True, missing=None,
                 presorted=False, preserve_left_order=False, buffersize=None,
                 tempdir=None, cache=True, lprefix=None, rprefix=None):
        self.left = stack(left, missing=missing)
        self.right = stack(right, missing=missing)
        self.key = key
        self.lkey = lkey
        self.rkey = rkey
        self.time = time
        self.ltime = ltime
        self.rtime = rtime
        self.direction = direction
        self.tolerance = tolerance
        self.allow_exact_matches = allow_exact_matches
        self.missing = missing
        self.presorted = presorted
        self.preserve_left_order = preserve_left_order
        self.buffersize = buffersize
        self.tempdir = tempdir
        self._cache = cache
        self.lprefix = lprefix
        self.rprefix = rprefix

    def __iter__(self):
        left, lhdr = _peek_header(self.left)
        right, rhdr = _peek_header(self.right)
        ltind, rtind = _resolve_time(
            lhdr, rhdr, time=self.time, ltime=self.ltime, rtime=self.rtime
        )
        lkind, rkind = _resolve_keys(
            lhdr, rhdr, ltind, rtind, key=self.key, lkey=self.lkey,
            rkey=self.rkey
        )

        if self.presorted:
            return iterasofjoin(
                left, right, lkind, rkind, ltind, rtind,
                direction=self.direction,
                tolerance=self.tolerance,
                allow_exact_matches=self.allow_exact_matches,
                missing=self.missing, lprefix=self.lprefix,
                rprefix=self.rprefix
            )

        ordered_left = left
        sorted_lkey = lkind
        sorted_ltime = ltind
        if self.preserve_left_order:
            ordered_left = addrownumbers(ordered_left, field=_ORDER_FIELD)
            sorted_lkey = [index + 1 for index in lkind]
            sorted_ltime = ltind + 1

        sorted_left = sort(
            ordered_left, sorted_lkey + [sorted_ltime],
            buffersize=self.buffersize, tempdir=self.tempdir,
            cache=self._cache
        )
        sorted_right = sort(
            right, rkind + [rtind],
            buffersize=self.buffersize, tempdir=self.tempdir,
            cache=self._cache
        )
        result = iterasofjoin(
            sorted_left, sorted_right, sorted_lkey, rkind,
            sorted_ltime, rtind, direction=self.direction,
            tolerance=self.tolerance,
            allow_exact_matches=self.allow_exact_matches,
            missing=self.missing, lprefix=self.lprefix,
            rprefix=self.rprefix
        )
        if self.preserve_left_order:
            result = sort(result, 0, buffersize=self.buffersize,
                          tempdir=self.tempdir, cache=self._cache)
            result = cutout(result, 0)
        return iter(result)


class _RightState(object):

    def __init__(self, rows, time_index):
        self.rows = rows
        self.time_index = time_index
        self.previous_row = None
        self.previous_time = None
        self.current_row = None
        self.current_time = None
        self.skipped_row = None
        self.skipped_time = None
        self.exhausted = False
        self._read_current()

    def _read_current(self):
        for row in self.rows:
            time_value = row[self.time_index]
            if time_value is not None:
                self.current_row = row
                self.current_time = time_value
                return
        self.current_row = None
        self.current_time = None
        self.exhausted = True

    def _skip_current_group(self):
        group_time = self.current_time
        while (not self.exhausted and
               Comparable(self.current_time) == Comparable(group_time)):
            self._read_current()

    def advance_to(self, left_time):
        if (self.skipped_row is not None and
                Comparable(self.skipped_time) < Comparable(left_time)):
            self.previous_row = self.skipped_row
            self.previous_time = self.skipped_time
            self.skipped_row = None
            self.skipped_time = None
        while (not self.exhausted and
               Comparable(self.current_time) < Comparable(left_time)):
            self.previous_row = self.current_row
            self.previous_time = self.current_time
            self._skip_current_group()

    def skip_equal(self, left_time):
        if (not self.exhausted and
                Comparable(self.current_time) == Comparable(left_time)):
            self._skip_current_group()

    def backward_candidate(self, left_time, allow_exact_matches):
        self.advance_to(left_time)
        if (not self.exhausted and
                Comparable(self.current_time) == Comparable(left_time)):
            if allow_exact_matches:
                return self.current_row
            return self.previous_row
        return self.previous_row

    def forward_candidate(self, left_time, allow_exact_matches):
        self.advance_to(left_time)
        if (not self.exhausted and
                Comparable(self.current_time) == Comparable(left_time)):
            if allow_exact_matches:
                return self.current_row
            self.skip_equal(left_time)
        if self.exhausted:
            return None
        return self.current_row

    def nearest_candidates(self, left_time, allow_exact_matches):
        self.advance_to(left_time)
        before_row = self.previous_row
        before_time = self.previous_time
        after_row = None
        after_time = None

        if (not self.exhausted and
                Comparable(self.current_time) == Comparable(left_time)):
            if allow_exact_matches:
                before_row = after_row = self.current_row
                before_time = after_time = left_time
            else:
                self.skipped_row = self.current_row
                self.skipped_time = self.current_time
                self._skip_current_group()

        if after_row is None and not self.exhausted:
            after_row = self.current_row
            after_time = self.current_time

        return ((before_row, before_time), (after_row, after_time))


def _within_tolerance(distance, tolerance):
    return tolerance is None or distance <= tolerance


def _select_backward(state, left_time, allow_exact_matches, tolerance):
    row = state.backward_candidate(left_time, allow_exact_matches)
    if row is None:
        return None
    right_time = row[state.time_index]
    if right_time is None or Comparable(right_time) > Comparable(left_time):
        return None
    if not allow_exact_matches and right_time == left_time:
        return None
    distance = left_time - right_time
    if _within_tolerance(distance, tolerance):
        return row
    return None


def _select_forward(state, left_time, allow_exact_matches, tolerance):
    row = state.forward_candidate(left_time, allow_exact_matches)
    if row is None:
        return None
    right_time = row[state.time_index]
    if right_time is None or Comparable(right_time) < Comparable(left_time):
        return None
    if not allow_exact_matches and right_time == left_time:
        return None
    distance = right_time - left_time
    if _within_tolerance(distance, tolerance):
        return row
    return None


def _select_nearest(state, left_time, allow_exact_matches, tolerance):
    before, after = state.nearest_candidates(left_time, allow_exact_matches)
    before_row, before_time = before
    after_row, after_time = after
    candidates = []

    if (before_row is not None and before_time is not None and
            Comparable(before_time) <= Comparable(left_time) and
            (allow_exact_matches or before_time != left_time)):
        candidates.append((left_time - before_time, 0, before_row))
    if (after_row is not None and after_time is not None and
            Comparable(after_time) >= Comparable(left_time) and
            (allow_exact_matches or after_time != left_time)):
        candidates.append((after_time - left_time, 1, after_row))

    if not candidates:
        return None
    distance, _, row = min(candidates, key=lambda item: (item[0], item[1]))
    if _within_tolerance(distance, tolerance):
        return row
    return None


def iterasofjoin(left, right, lkey, rkey, ltime, rtime,
                 direction='backward', tolerance=None,
                 allow_exact_matches=True, missing=None, lprefix=None,
                 rprefix=None):
    lit = iter(left)
    rit = iter(right)
    lhdr = next(lit)
    rhdr = next(rit)

    lkind = asindices(lhdr, lkey)
    rkind = asindices(rhdr, rkey)
    ltime_index = _single_index(lhdr, ltime, 'ltime')
    rtime_index = _single_index(rhdr, rtime, 'rtime')
    if lkind:
        lgetk = comparable_itemgetter(*lkind)
    else:
        lgetk = lambda row: Comparable(())
    if rkind:
        rgetk = comparable_itemgetter(*rkind)
    else:
        rgetk = lambda row: Comparable(())

    rvind = [index for index in range(len(rhdr)) if index not in set(rkind)]
    rgetv = rowgetter(*rvind)

    if lprefix is None:
        outhdr = list(lhdr)
    else:
        outhdr = [text_type(lprefix) + text_type(field) for field in lhdr]
    if rprefix is None:
        outhdr.extend(rgetv(rhdr))
    else:
        outhdr.extend([text_type(rprefix) + text_type(field)
                       for field in rgetv(rhdr)])
    yield tuple(outhdr)

    def output_row(lrow, rrow=None):
        outrow = list(lrow)
        if rrow is None:
            outrow.extend([missing] * len(rvind))
        else:
            outrow.extend(rgetv(rrow))
        return tuple(outrow)

    def process_left_group(lrows, rgroup):
        if rgroup is None:
            for lrow in lrows:
                yield output_row(lrow)
            return

        state = _RightState(iter(rgroup), rtime_index)
        for lrow in lrows:
            left_time = lrow[ltime_index]
            if left_time is None:
                yield output_row(lrow)
                continue

            if direction == 'backward':
                rrow = _select_backward(state, left_time,
                                        allow_exact_matches, tolerance)
            elif direction == 'forward':
                rrow = _select_forward(state, left_time,
                                       allow_exact_matches, tolerance)
            else:
                rrow = _select_nearest(state, left_time,
                                       allow_exact_matches, tolerance)
            yield output_row(lrow, rrow)

    lgroups = itertools.groupby(lit, key=lgetk)
    rgroups = itertools.groupby(rit, key=rgetk)

    try:
        lkey_value, lgroup = next(lgroups)
    except StopIteration:
        return
    try:
        rkey_value, rgroup = next(rgroups)
        have_right = True
    except StopIteration:
        rkey_value = rgroup = None
        have_right = False

    while True:
        if not have_right or lkey_value < rkey_value:
            for row in process_left_group(lgroup, None):
                yield row
            try:
                lkey_value, lgroup = next(lgroups)
            except StopIteration:
                return
        elif lkey_value > rkey_value:
            try:
                rkey_value, rgroup = next(rgroups)
            except StopIteration:
                have_right = False
        else:
            for row in process_left_group(lgroup, rgroup):
                yield row
            try:
                lkey_value, lgroup = next(lgroups)
            except StopIteration:
                return
            try:
                rkey_value, rgroup = next(rgroups)
            except StopIteration:
                have_right = False
