
import traceback

from . import messages
from sspt import parse
from sspt import bytebuffer

print_raw = False

class Protocol(object):
    "Interface documenting how <protocol> objects are called by SerialDaemon"

    def data_received(self, data):
        """Called by SerialDaemon as soon as one or more bytes have been
           received. A timestamp does therefore not need to be
           included.
        """
        pass  #Override

    def connection_made(self):
        """Called by SerialDaemon when the link becomes available, either at
           start or after a connection_lost() (for example, that the
           serial port can be opened). It doesn't state whether there
           is a component on the other side.
        """
        pass  #Override

    def connection_lost(self):
        """Called by SerialDaemon when the link becomes unavailable after a
           connection_made() (for example, that the serial port
           disappears due to physically disconnecting the serial
           adapter).
        """
        pass  #Override

class LineReader(Protocol):
    "No empty line generated inbetween \r\n and inbetween \n\r"
    def __init__(self, on_line_cb):
        self._on_line_cb = on_line_cb
        self._data = bytearray()
        self._last_char = None

    def data_received(self, data):
        self._data += data
        while True:
            ix = self._data.find(ord('\r'))
            ix2 = self._data.find(ord('\n'))
            if ix == -1 and ix2 == -1:
                break
            if ix == -1 or (ix2 > -1 and ix2 < ix):
                # \n comes first
                line = self._data[:ix2]
                self._data = self._data[ix2+1:]
                if line or self._last_char == '\n':
                    try:
                        s = line.decode(encoding='ascii')
                    except:
                        s = None
                        print('Warning: line is not ASCII')
                    if s:
                        self._on_line_cb(s)
                self._last_char = '\n'
            elif ix2 == -1 or (ix > -1 and ix < ix2):
                # \r comes first
                line = self._data[:ix]
                self._data = self._data[ix+1:]
                if line or self._last_char == '\r':
                    decoded = None
                    try:
                        decoded = line.decode(encoding='ascii')
                    except:
                        print('Warning: Line cannot be decoded')
                    if decoded is not None:
                        self._on_line_cb(decoded)
                self._last_char = '\r'

    def connection_made(self):
        pass

    def connection_lost(self):
        #Discard any buffered data
        self._data = bytearray()


######################################################################

def msg_to_ascii(msg):
    pyObj = messages.message_type.from_pyValue(msg)
    return pyObj.to_sspAscii()

def msg_to_bin(msg, iterator=None):
    pyObj = messages.message_type.from_pyValue(msg)
    if iterator is None:
        iterator = bytebuffer.ByteIterator()
    pyObj.to_impBin(iterator)
    return iterator.get_int_array()


######################################################################

def SspAsciiLineProtocol(LineReader):
    def __init__(self, handle_message_cb):
        LineReader.__init__(self, self.on_line)
        self.handle_message_cb = handle_message_cb

    def on_line(self, line):
        # LineReader has parsed a complete line
        line = line.strip()
        if line == '':
            return
        msg = parse.parse_json(line)
        if msg is None:
            print('Warning: No valid msg ' + repr(line))
            return
        self.handle_message_cb(msg['to'], msg)

    def encode(self, to, msg):
        pyObj = messages.addressed_msg_type.from_pyValue({'to': to, 'msg': msg})
        sspascii = pyObj.to_sspAscii()
        return "\n" + sspascii + "\n"


######################################################################

def hex_to_msg(line):
    "Returns (to, msg). Raises exception if decoding fails."
    line = line.strip()
    line = line.strip('\x00')
    if print_raw:
        print('Got "' + line + '"')
    if line[:2] != '0x':
        raise Exception()
    (bin_msg, remain) = parse.parse_hex(line)
    if remain:
        raise Exception('Syntax error parsing hex', repr(line))
    iterator = bytebuffer.ByteIterator(bin_msg)
    to = iterator.read_id()
    #The rest is the message
    msg = messages.message_type.from_impBin(iterator)
    try:
        msg = msg.to_pyValue()
    except Exception as ex:
        from sspt import pyObjects
        print('framing: Exception in msg.to_pyValue() for msg', msg.to_sspAscii(pyObjects.V_VERBOSE))
        raise ex
    return (to, msg)

class HexLineProtocol(LineReader):
    "SSP-BIN encoded in hexadecimal, with leading 0x and trailing \n."
    def __init__(self, handle_message_cb):
        LineReader.__init__(self, self.on_line)
        self.handle_message_cb = handle_message_cb

    def on_line(self, line):
        # LineReader has parsed a complete line
        line = line.strip()
        if line == '':
            return
        try:
            (to, msg) = hex_to_msg(line)
        except:
            print('Error decoding frame %s' % repr(line))
            #traceback.print_exc()
            return
        self.handle_message_cb(to, msg)

    def encode(self, to, msg):
        iterator = bytebuffer.ByteIterator()
        iterator.write_uint8(to)
        try:
            _bin = msg_to_bin(msg, iterator)
        except:
            print('Exception translating message to SSP-BIN:', msg)
            traceback.print_exc()
            return
        return "\n0x" + "".join("%02x" % x for x in _bin) + "\n"
