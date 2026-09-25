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


class NestedRecordError(Exception):

    def __init__(self, line_number, field_path, message):
        self.line_number = line_number
        self.field_path = tuple(field_path)
        self.message = message

    def __str__(self):
        return ('%s (input row %s, field path %r)'
                % (self.message, self.line_number, self.field_path))
