# source.py: References to a line in a source file

class ParseError(Exception):
    pass

class Source(object):
    def __init__(self, filename = "", line_nr = 0):
        self.filename = filename
        self.line_nr = line_nr
    def error(self, text):
        "Generate an Exception for this line"
        return ParseError("%s:%d: %s" % (self.filename, self.line_nr, text))
    def print_warning(self, text):
        print(repr(self) + ": " + text)
    def __repr__(self):
        return "%s:%d" % (self.filename, self.line_nr)

class NoSourceClass(object):
    def error(self, text):
        return ParseError("<unknown>: %s" % text)
    def __repr__(self):
        return "<unknown>"
no_source = NoSourceClass()
