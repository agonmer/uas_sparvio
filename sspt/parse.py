# parse.py: Convert between Python data types (pyValue) and SSP-ASCII

import re

class Definition:
    def __init__(self, num, binary):
        self.num = num
        self.binary = binary
    def __repr__(self):
        return "schemaDef(%d, %s)" % (self.num, repr(self.binary))


def parse_int(string, default=0):
    try:
        i = int(string)
        return i
    except:
        return default

def string_to_hex(string):
    return '0x' + ''.join(['%02x' % ord(x) for x in string])

def bytes_to_hex(b : bytes):
    return '0x' + ''.join(['%02x' % x for x in b])

#TODO: Support all escape characters
#Actually sspAscii_parseAnyPrimitiveFromIterator() doesn't un-escape yet
def escape(string):
    return string.replace('"','\\"').replace("\r", "\\r").replace("\n", "\\n")

def python_to_sspAscii(pythonData):
    if isinstance(pythonData, str):
        if pythonData.startswith('0x'):
            return pythonData  #TODO: Remove this?
        #TODO: Check for symbol
        return '"' + escape(pythonData) + '"'
    if isinstance(pythonData, bytearray) or isinstance(pythonData, bytes):
        return '0x' + ''.join(['{:02X}'.format(b) for b in pythonData])
    if pythonData is None:
        return 'null'
    if type(pythonData) is bool:
        if pythonData:
            return 'true'
        return 'false'
    if type(pythonData) is dict:
        s = '{'
        for (k,v) in list(pythonData.items()):
            if len(s) > 1:
                s += ','
            s += python_to_sspAscii(k) + ":" + python_to_sspAscii(v)
        s += '}'
        return s
    if type(pythonData) is list:
        return "[" + ",".join([python_to_sspAscii(x) for x in pythonData]) + "]"
    #Correctly handles integers and floats
    s = str(pythonData)
    if 'e' in s:
        #Disallow exponential representation
        #TODO: Doesn't handle large values!
        s = "%.12f" % pythonData
    return s

def python_to_sspAscii_symbol(pythonData):
    if isinstance(pythonData, str):
        return escape(pythonData)
    if type(pythonData) is list:
        return "[" + ','.join([python_to_sspAscii_symbol(x) for x in pythonData]) + "]"
    raise Exception

def parse_list(ascii):
    ascii = ascii.lstrip()
    if len(ascii) == 0 or ascii[0] != '[':
        raise Exception()
    ascii = ascii[1:]
    _list = []
    while True:
        ascii = ascii.lstrip()
        if len(ascii) == 0:
            raise Exception()
        if ascii[0] == ']':
            ascii = ascii[1:]
            break
        if ascii[0] == ',':
            raise Exception()

        (element, ascii) = parse_anything(ascii)
        _list.append(element)

        if ascii[0] == ',':
            ascii = ascii[1:]
        elif ascii[0] == ']':
            ascii = ascii[1:]
            break;
        else:
            raise Exception()

    return (_list, ascii)

def parse_object(ascii):
    "The word 'object' as in JSON terminology"
    ascii = ascii.lstrip()
    if len(ascii) == 0 or ascii[0] != '{':
        raise Exception()
    ascii = ascii[1:]
    dic = {}
    while True:
        ascii = ascii.lstrip()
        if len(ascii) == 0:
            raise Exception()
        if ascii[0] == '}':
            ascii = ascii[1:]
            break
        if ascii[0] == ',' or ascii[0] == ':':
            raise Exception()

        (key, ascii) = parse_anything(ascii)
        ascii = ascii.lstrip()
        if len(ascii) == 0 or ascii[0] != ':':
            raise Exception()
        ascii = ascii[1:]  #Remove ':'
        (value, ascii) = parse_anything(ascii)
        dic[key] = value

        if ascii[0] == ',':
            ascii = ascii[1:]
        elif ascii[0] == '}':
            ascii = ascii[1:]
            break;
        else:
            raise Exception()

    return (dic, ascii)

def parse_string(ascii):
    ascii = ascii[1:]  #Remove '"'
    s = ""
    while True:
        if len(ascii) == 0:
            raise Exception()
        if ascii[0] == '\\':
            ascii = ascii[1:]
            if ascii[0] == 'x':
                s += chr(int(ascii[1:3], 16))
                ascii = ascii[3:]
                continue
            #Will raise exception for unexpected escape character
            s += {'t': '\t', 'r': '\r', 'n': '\n',
                  '\\': '\\', '"': '"', "'": "'"}[ascii[0]]
            ascii = ascii[1:]
            continue
        if ascii[0] == '"':
            ascii = ascii[1:]  #Remove '"'
            return (s, ascii)
        s += ascii[0]
        ascii = ascii[1:]

def parse_symbol(ascii):
    "Not just symbol, but also boolean"
    s = ""
    while True:
        if len(ascii) == 0:
            break
        if ascii[0] < '.' or ascii[0] in '{}:;<=>?[]/':
            break
        s += ascii[0]
        ascii = ascii[1:]
    if s == 'true':
        s = True
    elif s == 'false':
        s = False
    #elif s == 'null':
    #    s = None
    return (s, ascii)

def parse_hex(ascii : str) -> bytes:
    "Parses a string on form '0xFF01' to bytes 255 1"
    ascii = ascii.lstrip()
    if ascii[:2] != '0x':
        raise Exception("String '%s' doesn't start with '0x'" % ascii)
    ascii = ascii[2:]  #Remove '0x'
    #Warning: The result will look like a string but is actually binary data
    val = bytearray()
    while True:
        if len(ascii) < 2:
            return (val, ascii)
        try:
            val += bytes([int(ascii[:2], 16)])
        except:
            return (val, ascii)
        ascii = ascii[2:]

def parse_number(ascii):
    num = 0
    sign = 1
    if ascii[0] == '-':
        sign = -1
        ascii = ascii[1:]
    while len(ascii) > 0 and ascii[0] in '0123456789':
        num = num * 10 + int(ascii[0])
        ascii = ascii[1:]
    if len(ascii) == 0 or ascii[0] != '.':
        return (sign * num, ascii)
    ascii = ascii[1:] #Remove '.'
    #Parse decimals
    decimals = 0
    fraction = 10.0
    while len(ascii) > 0 and ascii[0] in '0123456789':
        decimals += int(ascii[0]) / fraction
        fraction *= 10.0
        ascii = ascii[1:]
    return (sign * (num + decimals), ascii)


def parse_anything(ascii):
    "Returns tuple (python_value, remaining_ascii)"
    ascii = ascii.lstrip()
    if len(ascii) == 0:
        raise Exception()
    if ascii[0] == '[':
        return parse_list(ascii)
    if ascii[0] == '{':
        return parse_object(ascii)
    if ascii[0] == '"':
        return parse_string(ascii)
    if ascii.startswith('0x'):
        return parse_hex(ascii)
    if ascii[0] in '0123456789-.':
        return parse_number(ascii)
    if ascii.startswith('schemaDef('):
        ascii = ascii[len("schemaDef("):]
        (num, ascii) = parse_number(ascii)
        ascii = ascii.lstrip()[1:]  #Remove ','
        (binary, ascii) = parse_hex(ascii)
        ascii = ascii.lstrip()[1:]  #Remove ')'
        return (Definition(num, binary), ascii)

    return parse_symbol(ascii)
    #raise Exception('Error parsing "%s"' % ascii)

def parse_json(json):
    if not '{' in json:
        return None
    json = json[json.find('{'):]

    try:
        (dic, rest) = parse_anything(json)
    except:
        #print 'Could not parse %s' % repr(json)
        return None
    return dic

######################################################################
# Unit tests

def test():
    assert parse_anything("123") == (123, '')
    assert parse_anything("123.") == (123, '')
    assert parse_anything("123.2") == (123.2, '')
    assert parse_anything("-123.2") == (-123.2, '')
    assert parse_anything('"a"') == ("a", '')
    assert parse_anything('"a\\nb"') == ("a\nb", '')
    assert parse_anything('"\\x07\\x15\x00"') == ("\x07\x15\x00", '')
    assert parse_anything('"abc def"') == ("abc def", '')
    assert parse_anything('"  a  b  "c') == ("  a  b  ", 'c')
    assert parse_anything("[1]") == ([1], '')
    assert parse_anything("[1, 2]") == ([1, 2], '')
    assert parse_anything("[1, 2]a") == ([1, 2], 'a')
    assert parse_anything("[1, 2, [3,[4]], 5]a") == ([1, 2, [3,[4]], 5], 'a')
    assert parse_anything("{}") == ({}, '')
    assert parse_anything("{}a") == ({}, 'a')
    assert parse_anything("{1:    2}") == ({1:2}, '')
    assert parse_anything("{1:2,3:4}") == ({1:2,3:4}, '')
    assert parse_anything('{1:2,5:["abc", "de", []]}q') == ({1:2,5:["abc", "de", []]}, 'q')
    assert parse_anything("{abc: 2}") == ({'abc':2}, '')
    assert str(parse_anything("schemaDef(123, 0x4142)")) == "(schemaDef(123, 'AB'), '')"
    print('All tests succeeded')

if __name__ == "__main__":
    test()
