# Parse SSP-ASCII to pyObjects

from . import pyObjects
from .bytebuffer import *
from .source import no_source
from .ontology import global_ontology

def hex_to_int(ch):
    "Returns None if not a valid hexadecimal character"
    if ch >= '0' and ch <= '9':
        return ord(ch) - ord('0')
    if ch >= 'A' and ch <= 'F':
        return 10 + ord(ch) - ord('A')
    if ch >= 'a' and ch <= 'f':
        return 10 + ord(ch) - ord('a')
    return None

def parse_hex(iter):
    "Parses hex chars into string. '0x' is already consumed."
    blob = ""
    while iter.has_more():
        ch = iter.peek_char()
        val = hex_to_int(ch)
        if val is None:
            break  #Ok to break here
        iter.read_char()  #Consume peeked char
        ch = iter.read_char()
        val2 = hex_to_int(ch)
        if val2 is None:
            raise ParseError("Must have even number of hex digits")
        blob += chr(val * 16 + val2)
    return blob

def numeric_to_pyObj(string, source=no_source):
    "The full string must be used"
    point_ix = string.find('.')
    if point_ix == -1:
        #Not zero, as that is used for numbers on the form "12."
        decimal_count = -1
    else:
        #Decimal number
        return pyObjects.Float(float(string))  #Hack!
        #decimal_count = len(string) - point_ix - 1
        #string = string.replace('.','')
    raw_value = int(string)
    if decimal_count == -1:
        if raw_value >= 0:
            if raw_value < 255:
                return pyObjects.Uint8(raw_value)
            if raw_value < 65535:
                return pyObjects.Uint16(raw_value)
            if raw_value < 2 ** 32 - 1:
                return pyObjects.Uint32(raw_value)
            raise Exception("Integer out of range in %s" % repr(source))
        else:
            if raw_value > -65536:
                return pyObjects.Int16(raw_value)
            if raw_value > -(2**31):
                return pyObjects.Int32(raw_value)
            raise Exception("Integer out of range in %s" % repr(source))
    #Decimal number. TODO: Express as a known fixpoint
    raise Exception()  #Can't reach here, for now


def list_to_pyObj(iter, source=no_source, terminator=None):
    "Returns a Python list of pyObj elements. iter is a StringIterator"
    pyobjs = []
    while iter.has_more():
        pyobjs.append(to_pyObj(iter, source))
        iter.consume_whitespace()
        if iter.has_more():
            ch = iter.peek_char()
            if ch == ',':
                iter.read_char()
                continue
            if terminator is not None and ch == terminator:
                break
            raise source.error("List missing comma")
    return pyobjs

def dict_to_pyObj(iter, source=no_source, keys_are_symbols=False):
    "Returns a Python list of tuples of pyObj elements. iter is a StringIterator"
    pyobjs = []
    iter.consume_whitespace()
    while iter.has_more():
        key = to_pyObj(iter, source)
        if not key.is_atomic_value():
            raise source.error("Dict key must be atomic")
        if keys_are_symbols and not type(key) is pyObjects.Symbol:
            raise source.error("Key must be a symbol")
        iter.consume_whitespace()
        if not iter.consume(':'):
            raise source.error("Dict missing colon")
        value = to_pyObj(iter, source)
        pyobjs.append( (key, value) )
        iter.consume_whitespace()
        if not iter.has_more():
            break
        if not iter.consume(','):
            raise source.error("List missing comma")
        iter.consume_whitespace()
    return pyobjs

def _with_source(obj, source):
    if obj.source is None or obj.source == no_source:
        obj.source = source
    return obj

def to_pyObj(iter, source=no_source, follow_ref=True):
    "<follow_ref> means REF and labels should be replaced by their definitions."
    return _with_source(to_pyObj2(iter, source, follow_ref), source)

def to_pyObj2(iter, source=no_source, follow_ref=True):
    """Returns a pyObject. <iter> is a string or StringIterator
       <follow_ref> means REF and labels should be replaced by their definitions."""
    if type(iter) is not StringIterator:
        iter = StringIterator(iter)
    iter.consume_whitespace()

    #First, check for implied token
    token = None
    ch = iter.peek_char()
    if ch == "{":
        token = "Map"
    elif ch == "(":
        #Could be a tuple, but tuple type must be specified
        raise source.error("Unexpected '('")
    elif ch == "[":
        token = "List"

    if token is None:
        if iter.consume('0x'):
            return pyObjects.Blob(parse_hex(iter))
        if iter.consume('"'):
            string = iter.read_until('"')
            if not iter.has_more():
                raise source.error('Unmatched \'"\'')
            iter.read_char()  #Consume the end '"'
            return pyObjects.String(string)
        num_str = iter.read_numeric()
        if num_str is not None:
            return numeric_to_pyObj(num_str, source)

        token = iter.read_token()
        iter.consume_whitespace()

    bracket_char = None  #'(' or '[' or '{'
    args_str = None
    if iter.consume('('):
        bracket_char = '('
        args_str = iter.read_until(')')
        if not iter.consume(')'):
            raise source.error("Can't parse arguments")
    elif iter.consume('['):
        bracket_char = '['
        args_str = iter.read_until(']')
        if not iter.consume(']'):
            raise source.error("Can't parse array")
    elif iter.consume('{'):
        bracket_char = '{'
        args_str = iter.read_until('}')
        if not iter.consume('}'):
            raise source.error("Can't parse dict")

    if token == 'null':
        assert bracket_char is None  #Arguments make no sense here
        return pyObjects.null
    if token == 'true':
        assert bracket_char is None  #Arguments make no sense here
        return pyObjects.Bool(True)
    if token == 'false':
        assert bracket_char is None  #Arguments make no sense here
        return pyObjects.Bool(False)

    if token.startswith("REF"):
        #TODO: Could be REFxx(...) etc.
        assert bracket_char is None  #Not implemented
        regIx = int(token[3:])
        if follow_ref:
            return ontology.get_by_regIx(regIx)
        return pyObjects.Ref(regIx)

    typeObj : 'SspPyObj' = global_ontology.label_to_registry_entry(token)

    if bracket_char:
        #Use the token as label for the type
        if typeObj is None:
            raise source.error('Parameters to unknown label "%s"' % token)
        return typeObj.from_sspAscii_args(args_str, bracket_char, source)

    if typeObj is not None:
        #Labelled constant/schema or a type.
        #TODO: Should return a REF, unless a basic type or parameterless format
        #TODO: Should forbid references to parameterized formats
        if follow_ref:
            return typeObj
        regIx = typeObj.get_regIx()
        assert regIx
        return pyObjects.Ref(regIx)

    sym = global_ontology.name_to_symbol(token, create=True)
    if sym:
        return sym
    raise source.error('Cannot parse unknown token "%s"' % token)
