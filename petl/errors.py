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


class SortComparisonError(Exception):

    def __init__(self, field, value, row, other_value, other_row):
        self.field = field
        self.value = value
        self.row = row
        self.other_value = other_value
        self.other_row = other_row

    def __str__(self):
        return ('values are not comparable for field %r: %r (row %r) '
                'and %r (row %r)'
                % (self.field, self.value, self.row,
                   self.other_value, self.other_row))


class ArgumentError(Exception):

    def __init__(self, message):
        self.message = message

    def __str__(self):
        return 'argument error: %s' % self.message
