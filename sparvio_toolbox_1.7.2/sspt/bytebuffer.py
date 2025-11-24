# Implements memory buffer and iterator,
# without dependencies to SSP

from typing import List
from .source import ParseError

class UnderflowException(Exception):
    pass

#Could use ByteIterator, but it's more efficient to maintain a single byte string
class ByteStack(object):
    def __init__(self, size):
        #In Python 3, this could be a byte array
        self._bytes = "\0" * size
        self.start = size  #Empty at start = point beyond last byte index
    def pop_byte(self):
        if self.start >= len(self._bytes):
            raise UnderflowException()
        byte = self._bytes[self.start]
        self.start += 1
        return byte

#Use string?
class ByteBuffer(object):
    "Corresponds to co_buffer_t"
    pass

import types

def flatten_list(_lst):
    "Makes it convenient to add data to bytebuffer from different data structures, including nested structures"
    if type(_lst) is str:
        return [ord(x) for x in _lst]
    if type(_lst) is int:
        return [ _lst ]
    if type(_lst) is bytearray or type(_lst) is bytes:
        return _lst
    if type(_lst) is not list and \
       type(_lst) is not tuple:
        raise Exception("Unknown element type %s for %s" % (type(_lst), repr(_lst)))
    flat = []
    for item in _lst:
        flat.extend(flatten_list(item))
    return flat

# def list_to_string(_lst):
#     if type(_lst) is types.StringType or type(_lst) is types.UnicodeType:
#         return _lst
#     if type(_lst) is types.IntType:
#         if _lst > 255 or _lst < 0:
#             raise Exception("Element %d out of char range", _lst)
#         return chr(_lst)
#     if type(_lst) is not types.ListType and type(_lst) is not types.TupleType:
#         raise Exception("Unknown element type %s for %s" % (type(_lst), repr(_lst)))
#     return "".join(list_to_string(x) for x in _lst)

import struct

class ByteIterator(object):
    """Reads/writes bytes as integers 0-255"""
    def __init__(self, data=None):
        #For a read iterator, <data> is the remaining data, stored as
        #a list of integers.
        #For a write iterator, self._data is the data written so far.
        if data is None:
            self._data = bytearray()
        else:
            self._data = bytearray(flatten_list(data))
        # Copies of the data for savepoints, with the newest savepoint
        # at the end
        self._locations : List[bytearray] = []

    #########################################
    ## Reading

    def skip(self, size):
        if len(self._data) < size:
            raise UnderflowException()
        self._data = self._data[size:]

    def read_byte(self):
        if len(self._data) == 0:
            raise UnderflowException()
        byte = self._data[0]
        self.skip(1)
        #print 'Read byte %d (%02X)' % (byte, byte)
        return byte

    def read_uint8(self):
        return self.read_byte()

    def read_uint16(self):
        if len(self._data) < 2:
            raise UnderflowException()
        #Little endian
        i = self._data[0] + self._data[1] * 256
        self.skip(2)
        return i

    def read_int16(self):
        x = self.read_uint16()
        if x > 32767:
            return x - 65536
        return x

    def read_uint32(self):
        if len(self._data) < 4:
            raise UnderflowException()
        #Little endian
        #i = self._data[0] + 256 * (self._data[1] + 256 * (self._data[2] + 256 * self._data[3]))
        i = self._data[0] + (self._data[1] << 8) + (self._data[2] << 16) + (self._data[3] << 24)
        self.skip(4)
        return i

    def read_int32(self):
        x = self.read_uint32()
        if x >= 2**31:
            return x - 2**32
        return x

    def read_varuint(self) -> int:
        x = 0
        bits = 0
        while True:
            byte = self.read_uint8()
            x += (byte & 0x7F) << bits
            if byte < 0x80:  # No flag to continue
                return x
            bits += 7

    def read_regIx(self) -> int:
        return self.read_uint8()

    def read_symbol(self) -> int:
        return self.read_varuint()

    def read_float(self):
        if len(self._data) < 4:
            raise UnderflowException()
        _tuple = struct.unpack('f', self._data[:4])
        self.skip(4)
        return _tuple[0]

    def read_size_and_buffer(self):
        "Returns an array of byte values"
        if len(self._data) < 1:
            raise UnderflowException("No size byte")
        size = self.read_uint8()
        if len(self._data) < size:
            raise UnderflowException("read_size_and_buffer specifies %d bytes payload but only %d are left" % (size, len(self._data)))
        buf = self._data[:size]
        self.skip(size)
        return buf

    def read_string(self):
        return ''.join(chr(x) for x in self.read_size_and_buffer())

    def read_id(self):
        return self.read_uint8()  #To be replaced by VARUINT


    #########################################
    ## Writing (to back)

    def write(self, data):
        self._data.extend(flatten_list(data))

    def write_uint8(self, x : int):
        assert x >= 0 and x < 256
        self._data.append(x)

    def write_uint16(self, x : int):
        assert x >= 0 and x < 2**16
        self._data.append(x % 256)
        self._data.append(x >> 8)

    def write_int16(self, x : int):
        self.write(struct.pack('<h', x))

    def write_uint32(self, x : int):
        self.write(struct.pack('<I', x))

    def write_int32(self, x : int):
        self.write(struct.pack('<i', x))

    def write_varuint(self, x : int):
        assert isinstance(x, int) and x >= 0 and x < 2**32
        while x >= 0x80:
            # Write the lowest 7 bits and flag for more data
            lowest = (x & 0x7F) | 0x80
            self._data.append(lowest)
            x >>= 7  #Shift away the 7 lowest bits that we used
        # x is now 7 bits or smaller. Write the final byte
        self._data.append(x)

    def write_float(self, f : float):
        self.write(struct.pack('f', f))

    def write_regIx(self, _regIx : int):
        self.write_uint8(_regIx)

    def write_symbol(self, sym : int):
        self.write_varuint(sym)

    #########################################
    # Stack write (to front)

    def push_uint8(self, x : int):
        assert x >= 0 and x < 256
        #Inefficient but we don't deal with large data.
        #collections.deque would be more efficient
        self._data.insert(0, x)

    def push_regIx(self, _regIx : int):
        self.push_uint8(_regIx)

    #########################################

    def get_int_array(self):
        "For write iterators, returns all written data. For read iterators, returns the yet unread data"
        return self._data

    def get_c_array(self):
        "Returns the full data as an uint8_t array in the C language"
        return "{%s}" % ', '.join(["0x%02x" % x for x in self._data])

    def get_string(self):
        return ''.join([chr(x) for x in self._data])

    def __len__(self):
        "Returns the remaining number of bytes"
        return len(self._data)

    def __repr__(self):
        "For write iterators, returns all written data as string. For read iterators, returns the yet unread data as string"
        return "ByteIterator(b'%s')" % self._data.decode(encoding="ascii")

    #########################################
    # Debugging

    def push_savepoint(self):
        self._locations.append(self._data[:])
    def pop_savepoint(self) -> bytearray:
        "Returns the data consumed since push_location()"
        # Assumes the only changes have been to consume data (from the front)
        saved = self._locations.pop()
        if len(self._data) == 0:
            return saved # All data was removed
        return saved[:-len(self._data)]
    def pop_savepoint_hex(self) -> str:
        "Returns the data consumed since push_location() as a hex string"
        return '0x' + ''.join("%02X" % ch for ch in self.pop_savepoint())


class StringIterator(object):
    "Read from a Python string without copying"
    def __init__(self, ascii : str):
        self._ascii = ascii
        self._next_index = 0
    def has_more(self):
        return self._next_index < len(self._ascii)
    def peek_char(self) -> str:
        assert self.has_more()
        return self._ascii[self._next_index]
    def read_char(self) -> str:
        assert self.has_more()
        ch = self._ascii[self._next_index]
        self._next_index += 1
        return ch
    def consume_whitespace(self):
        while self.has_more() and self.peek_char() in ' \n\r\t':
            self.read_char()
    def consume(self, substring):
        "Returns true if <substring> was next in the iterator"
        _len = len(substring)
        if self._next_index + _len > len(self._ascii):
            return False
        ix = 0
        while ix < _len:
            if self._ascii[self._next_index + ix] != substring[ix]:
                return False
            ix += 1
        self._next_index += _len
        return True
    def read_token(self):
        "Returns a string with as many 'normal' characters as possible"
        self.consume_whitespace()
        start_ix = self._next_index
        while self.has_more():
            ch = self.peek_char()
            if (ch >= 'A' and ch <= 'Z') or (ch >= 'a' and ch <= 'z') or \
               (ch >= '0' and ch <= '9') or ch == '_':
                self.read_char()  #Consume ch
                continue
            break
        end_ix = self._next_index
        return self._ascii[start_ix:end_ix]
    def read_numeric(self):
        "Returns a (consumed) string, or None if a numeric value didn't follow"
        ch = self.peek_char()
        if (ch >= '0' and ch <= '9') or ch == '-' or ch == '.':
            pass
        else:
            return None  #Not numeric
        start_ix = self._next_index
        self.read_char()  #Consume ch
        got_point = (ch == '.')
        while self.has_more():
            ch = self.peek_char()
            if ch == '.':
                if got_point:
                    raise Exception("")
                got_point = True
            elif (ch >= '0' and ch <= '9') or ch == '-':
                pass
            else:
                break
            self.read_char()  #Consume ch
        end_ix = self._next_index
        return self._ascii[start_ix:end_ix]

    def read_until(self, ch):
        "Returns the longest string that doesn't include <ch>, skipping occurences in nested structures. Doesn't consume <ch>."
        start = self._next_index
        try:
            ix = self._get_ix_of(ch, start)
        except IndexError:
            raise source.ParseError("Didn't find '%s' in input \"%s\"" % (ch, self._ascii[start:]))
        self._next_index = ix
        return self._ascii[start:ix]

    def _get_ix_of(self, ch, start):
        "Returns index of the first occurence of <ch> at or after <start>, skipping occurences in nested structures."

        #Don't look for structures in strings
        if ch == '"':
            while True:
                c = self._ascii[start]
                if c == '"':
                    return start
                elif c == '\\':
                    start += 2
                else:
                    start += 1

        while True:
            c = self._ascii[start]
            if c == ch:
                return start
            elif c == '(':
                start = self._get_ix_of(')', start + 1) + 1
            elif c == '[':
                start = self._get_ix_of(']', start + 1) + 1
            elif c == '{':
                start = self._get_ix_of('}', start + 1) + 1
            elif c == '"':
                start = self._get_ix_of('"', start + 1) + 1
            elif c == '\\':
                start += 2  #Skip escaped character
            else:
                start += 1


if __name__ == "__main__":
    i = StringIterator("\t abcABC.123")
    assert i.read_token() == 'abcABC'
    assert i.read_numeric() == '.123'
    for x in [0, 127, 128, 1000, 2**16 - 1, 2**16, 2**32 - 1]:
        b = ByteIterator()
        b.write_varuint(x)
        c = ByteIterator(b.get_int_array())
        recovered = c.read_varuint()
        assert recovered == x
    print('Tests PASSED')
