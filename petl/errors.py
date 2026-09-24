from __future__ import absolute_import, print_function, division


class DuplicateKeyError(Exception):

    def __init__(self, key, details=None):
        self.key = key
        self.details = details

    def __str__(self):
        if self.details:
            return 'duplicate key: %r (%s)' % (self.key, self.details)
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
