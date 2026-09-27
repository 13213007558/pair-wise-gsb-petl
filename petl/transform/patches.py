from __future__ import absolute_import, print_function, division

from tempfile import NamedTemporaryFile

from petl.compat import pickle, next, string_types, text_type
from petl.comparison import Comparable, MISSING
from petl.errors import ArgumentError, PatchConflict
from petl.transform.basics import cut
from petl.transform.sorts import sort, _NamedTempFileDeleteOnGC
from petl.util.base import Table


OPERATION_HEADER = ('operation', 'before', 'after', 'multiplicity',
                    'changes')
RAW_OPERATION_HEADER = ('sort_key', 'operation', 'before', 'after',
                        'multiplicity', 'changes')


class TablePatch(object):

    def __init__(self, key, fields_before, fields_after, canonical_fields,
                 operations):
        self.key = tuple(key)
        self.fields_before = tuple(fields_before)
        self.fields_after = tuple(fields_after)
        self.canonical_fields = tuple(canonical_fields)
        self.operations = operations
        self.fields_added = tuple(
            field for field in fields_after
            if field not in set(_field_names(fields_before)))
        self.fields_removed = tuple(
            field for field in fields_before
            if field not in set(_field_names(fields_after)))

    def apply(self, table, buffersize=None, tempdir=None):
        return applytablediff(self, table, buffersize=buffersize,
                              tempdir=tempdir)

    def __iter__(self):
        return iter(self.operations)


def tablediff(source, target, key, buffersize=None, tempdir=None):
    """Build an applicable patch describing a table multiset difference.

    Unique key values produce field-level updates. If either side contains
    a key more than once, that key is handled using complete-row multisets,
    so matching rows with that key are never inferred as an update. The
    returned patch records each expected row or multiplicity needed before
    application; :func:`applytablediff` raises :class:`PatchConflict` if the
    source table has changed.
    """

    key = _normalise_key(key)
    source = _SinglePassTable(source)
    target = _SinglePassTable(target)
    source_header = source.header_row
    target_header = target.header_row
    _validate_headers(source_header, target_header)
    key = _resolve_key(key, source_header)
    _validate_key_fields(key, target_header)

    canonical_fields = _canonical_fields(key, source_header, target_header)
    source_indices = _field_indices(source_header, canonical_fields)
    target_indices = _field_indices(target_header, canonical_fields)
    sorted_source = sort(_NormalizedTable(source, canonical_fields,
                                          source_indices),
                         buffersize=buffersize, tempdir=tempdir, cache=True)
    sorted_target = sort(_NormalizedTable(target, canonical_fields,
                                          target_indices),
                         buffersize=buffersize, tempdir=tempdir, cache=True)
    duplicate_keys = _spool_duplicate_keys(sorted_source, sorted_target,
                                           len(key), tempdir)
    raw = _RawPatchTable(sorted_source, sorted_target, duplicate_keys,
                         len(key), canonical_fields)
    prepared = sort(raw, key=0, buffersize=buffersize, tempdir=tempdir,
                    cache=True)
    operations = cut(prepared, 'operation', 'before', 'after',
                     'multiplicity', 'changes')
    return TablePatch(key, source_header, target_header, canonical_fields,
                      operations)


Table.tablediff = tablediff
tablepatch = tablediff


def applytablediff(patch, table, buffersize=None, tempdir=None):
    """Apply a patch after checking every expected row and multiplicity.

    Rows are validated while streaming against the sorted source table. If a
    row or multiplicity differs, no silent overwrite is attempted and the
    resulting :class:`PatchConflict` identifies the mismatch.
    """

    if not isinstance(patch, TablePatch):
        raise ArgumentError('patch must be a TablePatch')

    table = _SinglePassTable(table)
    current_header = table.header_row
    _validate_unique_fields(current_header)
    if set(_field_names(current_header)) != set(
            _field_names(patch.fields_before)):
        raise PatchConflict(
            'table fields do not match patch source fields',
            expected=patch.fields_before, actual=tuple(current_header))

    current_indices = _field_indices(current_header, patch.canonical_fields)
    sorted_current = sort(_NormalizedTable(table, patch.canonical_fields,
                                           current_indices),
                          buffersize=buffersize, tempdir=tempdir, cache=True)
    operations = sort(_PreparedOperations(patch.operations), key=0,
                      buffersize=buffersize, tempdir=tempdir, cache=True)
    _validate_application(sorted_current, operations, patch)
    return _AppliedTable(sorted_current, operations, patch)


Table.applytablediff = applytablediff
applypatch = applytablediff
Table.applypatch = applytablediff


class _NormalizedTable(Table):

    def __init__(self, source, fields, indices):
        self.source = source
        self.fields = tuple(fields)
        self.indices = tuple(indices)

    def __iter__(self):
        it = iter(self.source)
        next(it)
        yield self.fields
        for row in it:
            yield tuple(MISSING if index is None or index >= len(row)
                        else row[index] for index in self.indices)


class _SinglePassTable(Table):

    def __init__(self, source):
        iterator = iter(source)
        self.header_row = tuple(next(iterator))
        self._rows = iterator

    def __iter__(self):
        yield self.header_row
        for row in self._rows:
            yield tuple(row)


class _RawPatchTable(Table):

    def __init__(self, source, target, duplicate_keys, key_size, fields):
        self.source = source
        self.target = target
        self.duplicate_keys = duplicate_keys
        self.key_size = key_size
        self.fields = tuple(fields)

    def __iter__(self):
        yield RAW_OPERATION_HEADER
        source_it = _data_iter(self.source)
        target_it = _data_iter(self.target)
        marker_it = _read_spooled_keys(self.duplicate_keys)
        source_row = _next_row(source_it)
        target_row = _next_row(target_it)
        marker_key = _next_row(marker_it)

        while source_row is not None or target_row is not None:
            current_key = _min_key(source_row, target_row, self.key_size)
            while marker_key is not None and _less(marker_key, current_key):
                marker_key = _next_row(marker_it)
            duplicate = marker_key is not None and marker_key == current_key
            if duplicate:
                marker_key = _next_row(marker_it)

            if duplicate:
                state = [source_row, target_row]
                for row in _iter_multiset_group(current_key, state,
                                                 source_it, target_it,
                                                 self.key_size):
                    yield row
                source_row, target_row = state
            else:
                yield self._unique_operation(current_key, source_row,
                                             target_row)
                if _key_equals(source_row, current_key, self.key_size):
                    source_row = _next_row(source_it)
                if _key_equals(target_row, current_key, self.key_size):
                    target_row = _next_row(target_it)

    def _unique_operation(self, current_key, source_row, target_row):
        source_group = [source_row] if _key_equals(
            source_row, current_key, self.key_size) else []
        target_group = [target_row] if _key_equals(
            target_row, current_key, self.key_size) else []
        return _unique_operations(source_group, target_group,
                                  self.fields)[0]


class _PreparedOperations(Table):

    def __init__(self, operations):
        self.operations = operations

    def __iter__(self):
        yield RAW_OPERATION_HEADER
        for operation, before, after, multiplicity, changes in _skip_header(
                iter(self.operations)):
            sort_row = before if before is not None else after
            sort_flag = 0 if before is not None else 1
            yield ((_row_key(sort_row), sort_flag, sort_row),
                   operation, before, after, multiplicity, changes)


class _AppliedTable(Table):

    def __init__(self, current, operations, patch):
        self.current = current
        self.operations = operations
        self.patch = patch

    def __iter__(self):
        current_it = _data_iter(self.current)
        yield self.patch.fields_after
        output_indices = _field_indices(self.patch.canonical_fields,
                                        self.patch.fields_after)
        for raw_operation in _data_iter(self.operations):
            _, operation, before, after, multiplicity, _ = raw_operation
            if operation == 'delete':
                for _ in range(multiplicity):
                    next(current_it)
            elif operation == 'keep':
                for _ in range(multiplicity):
                    yield _project(next(current_it), output_indices)
            elif operation == 'update':
                next(current_it)
                yield _project(after, output_indices)
            elif operation == 'insert':
                for _ in range(multiplicity):
                    yield _project(after, output_indices)
            else:
                raise ArgumentError('unknown patch operation: %s' % operation)


def _validate_application(current, operations, patch):
    current_it = _data_iter(current)
    current_row = _next_row(current_it)

    for raw_operation in _data_iter(operations):
        _, operation, before, _, multiplicity, _ = raw_operation
        if operation == 'insert':
            continue
        if operation not in ('keep', 'update', 'delete'):
            raise ArgumentError('unknown patch operation: %s' % operation)
        for _ in range(multiplicity):
            if current_row is None:
                _raise_missing(before, operation, multiplicity)
            if current_row != before:
                _raise_changed(before, current_row, operation, multiplicity,
                               patch.canonical_fields)
            current_row = _next_row(current_it)

    if current_row is not None:
        _raise_changed(None, current_row, 'unexpected', None,
                       patch.canonical_fields)


def _spool_duplicate_keys(source, target, key_size, tempdir):
    source_it = _data_iter(source)
    target_it = _data_iter(target)
    source_row = _next_row(source_it)
    target_row = _next_row(target_it)
    temporary = NamedTemporaryFile(dir=tempdir, delete=False, mode='wb')
    name = temporary.name

    try:
        while source_row is not None or target_row is not None:
            current_key = _min_key(source_row, target_row, key_size)
            source_count = 0
            target_count = 0
            while _key_equals(source_row, current_key, key_size):
                source_count += 1
                source_row = _next_row(source_it)
            while _key_equals(target_row, current_key, key_size):
                target_count += 1
                target_row = _next_row(target_it)
            if source_count > 1 or target_count > 1:
                pickle.dump(current_key, temporary, protocol=-1)
    finally:
        temporary.close()
    return _NamedTempFileDeleteOnGC(name)


def _read_spooled_keys(spool):
    with open(spool.name, 'rb') as stream:
        try:
            while True:
                yield pickle.load(stream)
        except EOFError:
            return


def _unique_operations(source_group, target_group, fields):
    source_row = source_group[0] if source_group else None
    target_row = target_group[0] if target_group else None
    if source_row is not None and target_row is not None:
        if source_row == target_row:
            operation = 'keep'
        else:
            operation = 'update'
        changes = _changes(source_row, target_row, fields)
        sort_row = source_row
        sort_flag = 0
    elif source_row is not None:
        operation = 'delete'
        changes = {}
        sort_row = source_row
        sort_flag = 0
    else:
        operation = 'insert'
        changes = {}
        sort_row = target_row
        sort_flag = 1
    return [_operation(operation, sort_flag, sort_row, source_row,
                       target_row, 1, changes)]


def _iter_multiset_group(current_key, state, source_it, target_it, key_size):
    source_row = state[0]
    target_row = state[1]
    while _key_equals(source_row, current_key, key_size) or \
            _key_equals(target_row, current_key, key_size):
        source_in_group = _key_equals(source_row, current_key, key_size)
        target_in_group = _key_equals(target_row, current_key, key_size)
        if not target_in_group or (
                source_in_group and _less(source_row, target_row)):
            row = source_row
            count = 1
            source_row = _next_row(source_it)
            while _key_equals(source_row, current_key, key_size) and \
                    source_row == row:
                count += 1
                source_row = _next_row(source_it)
            for operation in _multiset_run(row, count, None, 0):
                yield operation
        elif not source_in_group or _less(target_row, source_row):
            row = target_row
            count = 1
            target_row = _next_row(target_it)
            while _key_equals(target_row, current_key, key_size) and \
                    target_row == row:
                count += 1
                target_row = _next_row(target_it)
            for operation in _multiset_run(None, 0, row, count):
                yield operation
        else:
            row = source_row
            source_count = 1
            source_row = _next_row(source_it)
            while _key_equals(source_row, current_key, key_size) and \
                    source_row == row:
                source_count += 1
                source_row = _next_row(source_it)
            target_count = 1
            target_row = _next_row(target_it)
            while _key_equals(target_row, current_key, key_size) and \
                    target_row == row:
                target_count += 1
                target_row = _next_row(target_it)
            for operation in _multiset_run(row, source_count,
                                            row, target_count):
                yield operation
    state[0] = source_row
    state[1] = target_row


def _multiset_run(source_row, source_count, target_row, target_count):
    row = source_row if source_row is not None else target_row
    common_count = min(source_count, target_count)
    if common_count:
        yield _operation('keep', 0, row, row, row, common_count, {})
    if source_count > target_count:
        yield _operation('delete', 0, row, row, None,
                         source_count - target_count, {})
    elif target_count > source_count:
        yield _operation('insert', 1, row, None, row,
                         target_count - source_count, {})


def _operation(operation, sort_flag, sort_row, before, after, multiplicity,
               changes):
    multiplicity = multiplicity if multiplicity is not None else 1
    return ((_row_key(sort_row), sort_flag, sort_row), operation, before,
            after, multiplicity, changes)


def _changes(before, after, fields):
    changes = {}
    for index, field in enumerate(fields):
        if before[index] != after[index]:
            changes[field] = (before[index], after[index])
    return changes


def _project(row, indices):
    projected = tuple(MISSING if index is None or index >= len(row)
                      else row[index] for index in indices)
    while projected and projected[-1] is MISSING:
        projected = projected[:-1]
    return projected


def _raise_missing(expected, operation, multiplicity):
    raise PatchConflict('target ended before expected row was consumed',
                        operation=operation, expected=expected,
                        multiplicity=multiplicity)


def _raise_changed(expected, actual, operation, multiplicity, fields):
    message = 'target row does not match expected patch value'
    if operation == 'unexpected':
        message = 'unexpected row remains after applying patch'
    elif fields is not None and expected is not None:
        field_changes = []
        for index, field in enumerate(fields):
            old = expected[index]
            new = actual[index] if actual is not None and index < len(actual) \
                else MISSING
            if old != new:
                field_changes.append((field, old, new))
        if field_changes:
            message += ': ' + repr(field_changes)
    raise PatchConflict(message, operation=operation, expected=expected,
                        actual=actual, multiplicity=multiplicity)


def _normalise_key(key):
    if key is None:
        raise ArgumentError('a key field or collection of key fields is '
                            'required')
    if isinstance(key, string_types):
        return (key,)
    if isinstance(key, int):
        return (key,)
    normalised = tuple(key)
    if not normalised:
        raise ArgumentError('key must contain at least one field')
    if len(set(normalised)) != len(normalised):
        raise ArgumentError('key contains duplicate fields')
    return normalised


def _resolve_key(key, header):
    fields = _field_names(header)
    resolved = []
    for field in key:
        if isinstance(field, int):
            if field < 0 or field >= len(fields):
                raise ArgumentError('key field must be present in both '
                                    'tables: %r' % (field,))
            field = fields[field]
        resolved.append(field)
    resolved = tuple(resolved)
    if len(set(resolved)) != len(resolved):
        raise ArgumentError('key contains duplicate fields')
    return resolved


def _validate_key_fields(key, header):
    fields = _field_names(header)
    for field in key:
        if field not in fields:
            raise ArgumentError('key field must be present in both tables: '
                                '%r' % (field,))


def _validate_headers(source_header, target_header):
    _validate_unique_fields(source_header)
    _validate_unique_fields(target_header)


def _validate_unique_fields(header):
    fields = _field_names(header)
    if len(set(fields)) != len(fields):
        raise ArgumentError('duplicate field names are not supported: %r'
                            % (header,))


def _canonical_fields(key, source_header, target_header):
    source_fields = _field_names(source_header)
    target_fields = _field_names(target_header)
    remaining = list(source_fields)
    fields = []
    for field in key:
        fields.append(field)
        remaining.remove(field)
    for field in remaining:
        fields.append(field)
    for field in target_fields:
        if field not in fields:
            fields.append(field)
    return tuple(fields)


def _field_indices(header, fields):
    header_fields = _field_names(header)
    indices = []
    for field in fields:
        try:
            indices.append(header_fields.index(field))
        except ValueError:
            indices.append(None)
    return tuple(indices)




def _data_iter(table):
    iterator = iter(table)
    next(iterator)
    return iterator


def _skip_header(iterator):
    next(iterator)
    return iterator


def _next_row(iterator):
    try:
        return tuple(next(iterator))
    except StopIteration:
        return None


def _row_key(row):
    return tuple(Comparable(value) for value in row)


def _field_names(header):
    return tuple(text_type(field) for field in header)


def _key(row, key_size):
    if row is None:
        return None
    return tuple(row[:key_size])


def _key_equals(row, key, key_size):
    return row is not None and _key(row, key_size) == key


def _less(left, right):
    return Comparable(left) < Comparable(right)


def _min_key(source_row, target_row, key_size):
    source_key = _key(source_row, key_size)
    target_key = _key(target_row, key_size)
    if target_key is None or (source_key is not None and
                              _less(source_key, target_key)):
        return source_key
    return target_key
