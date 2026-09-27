from __future__ import absolute_import, print_function, division


class DuplicateKeyError(Exception):

    def __init__(self, key):
        self.key = key

    def __str__(self):
        return 'duplicate key: %r' % (self.key,)


class FieldSelectionError(Exception):

    def __init__(self, value):
        self.value = value

    def __str__(self):
        return 'selection is not a field or valid field index: %r' % (self.value,)


class ArgumentError(Exception):

    def __init__(self, message):
        self.message = message

    def __str__(self):
        return 'argument error: %s' % self.message


class PatchConflict(Exception):

    def __init__(self, message, operation=None, expected=None, actual=None,
                 multiplicity=None):
        self.message = message
        self.operation = operation
        self.expected = expected
        self.actual = actual
        self.multiplicity = multiplicity

    def __str__(self):
        parts = [self.message]
        if self.operation is not None:
            parts.append('operation: %r' % self.operation)
        if self.expected is not None:
            parts.append('expected: %r' % (self.expected,))
        if self.actual is not None:
            parts.append('actual: %r' % (self.actual,))
        if self.multiplicity is not None:
            parts.append('multiplicity: %r' % self.multiplicity)
        return '; '.join(parts)
