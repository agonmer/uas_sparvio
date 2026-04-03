"Handle serial ports"

from reactive import eventthread
import threading
import time
import sys
import traceback

try:
    import serial
except:
    print('Missing package: run "python -m pip install pyserial"')
    sys.exit(1)

serial_version = serial.__dict__.get('__version__', '?')

# Globals:
#print_writes = True
print_trace = True
print_extra_trace = False

start_time = time.time()

def log(text, timestamp=None):
    if timestamp is None:
        timestamp = time.time()
    print("%3.3f %s" % (timestamp - start_time, text))

from serial.tools import list_ports  #type: ignore
def by_serial_number(serial_number : str) -> str:
    "Returns /dev/tty... from device serial number (not all devices have a serial number)"
    for port in list_ports.comports():
        if port.serial_number == serial_number:
            return port.device
    raise Exception()

# Copied from serial.threaded.ReaderThread and modified to not give up
# if the serial connection fails. Instead, multiple connection_made()
# and connection_lost() can be emitted as the serial port comes and
# goes.
class SerialDaemon(eventthread.EventThread):
    """\
    Implement a serial port read loop and dispatch to a Protocol
    instance (like the asyncio.Protocol) but do it with a thread, and
    allow the serial port to come and go.
    """

    def __init__(self, port, protocol=None, baud=115200, id=None):
        """\
        Initialize thread.

        <protocol> is the Protocol packetizer that receives data and
        connect/disconnect events.
        """
        super(SerialDaemon, self).__init__(name="SerialDaemon("+port+")")
        #self.daemon = True
        # Convenience for Linux (Windows ports start with 'COM')
        if port.startswith('id='):
            port = '/dev/serial/by-id/' + port[3:]
        elif port.startswith('ser='):
            port = by_serial_number(port[4:])
        elif port.startswith('tty'):
            port = '/dev/' + port
        elif port.startswith('ACM'):
            port = '/dev/tty' + port
        elif port.startswith('USB'):
            port = '/dev/tty' + port
        self._port = port
        self._serial = None
        self._baudrate = baud
        self.protocol = protocol

        if id:
            self._id = id
        else:
            if port.startswith('/dev/tty'):
                self._id = port[len('/dev/tty'):]
            else:
                self._id = port

        self._lock = threading.Lock()
        self._connection_made_event = threading.Event()

        #True means the serial port was functional last time we tried to use it
        #
        #Start out as False to generate an initial connection_made()
        #callback but not connection_lost()
        self._is_online = False

    def is_online(self):
        return self._is_online

    def on_stop(self):
        self._is_online = False
        if self._serial is None:
            return
        if hasattr(self._serial, 'cancel_read'):
            self._serial.cancel_read()

    def _open(self):
        try:
            #inter_byte_timeout may be truncated to 0.1 on POSIX,
            #meaning 0.01 would be changed to 0
            if serial_version == '?' or float(serial_version) < 3:
                self._serial = serial.Serial(port=self._port,
                                             baudrate=self._baudrate,
                                             timeout=0.25,
                                             interCharTimeout=0.01,
                                             writeTimeout=1)
            else:
                self._serial = serial.Serial(port=self._port,
                                             baudrate=self._baudrate,
                                             timeout=0.25,
                                             inter_byte_timeout=0.01,
                                             write_timeout=1)
        except Exception as ex:
            self.reason = str(ex)
            if print_extra_trace:
                log('Exception in _open(): ' + self.reason)
            self._serial = None
            return False
        return True

    def _close(self):
        if not self._serial:
            return
        with self._lock:
            try:
                self._ser.close()
            except:
                pass
            self._serial = None

    def _set_online(self, is_online):
        if self._is_online == is_online:
            return
        self._is_online = is_online
        try:
            if self.protocol:
                if is_online:
                    self.protocol.connection_made()
                else:
                    self.protocol.connection_lost()
        except:
            log('Protocol exception:')
            log(traceback.print_exc())
        if is_online:
            self._connection_made_event.set()

    def run(self):
        """Reader loop"""
        #Initial open:
        reported = False
        self._is_online = False
        while (self._alive and not self._open()):
            if not reported and print_trace:
                log('Could not open %s. Will keep trying...' % self._id)
                reported = True
            self.sleep(1)
        if not self._alive:
            return
        self._set_online(True)
        if print_trace:
            log("Opened %s" % self._port)

        while self._alive:
            if self._serial is None:
                if self._open():
                    log('%s going online' % self._id)
                else:
                    self.sleep(0.25)
                    continue
            try:
                # read all that is there or wait for one byte (blocking)
                data = self._serial.read(self._serial.in_waiting or 1)
                # Even if we didn't get data, reading didn't raise an exception
                # so consider the serial port online:
                self._set_online(True)
            except serial.SerialException as e:
                error = e
                self._set_online(False)
                if self._is_online:
                    #At teardown, stdout can be removed by now
                    if sys.stdout and print_trace:
                        log('%s going offline' % self._id)

                #If the file is a symlink, such as when assigning a
                #particular device file in Linux, the symlink may
                #change if the device restarts which is not registered
                #by PySerial. Therefore, close the file and try to
                #open again.
                self._close()

                #Avoid frequent polling in case the port was closed and now
                #raises an exception very quickly
                time.sleep(0.05)

                continue

            if data:
                # Separate try-except for calling user code
                try:
                    if self.protocol:
                        self.protocol.data_received(data)
                except Exception as e:
                    log('Protocol exception:')
                    print(traceback.print_exc())
                    error = e

        #Presumably we got here due to explicit request to quit, in
        #which case the protocol isn't interested in receiving a notification.
        self._alive = False
        self._close()
        self.protocol = None

    def write(self, data):
        """Thread safe writing (uses lock). Returns true if write succeeded."""
        if (not isinstance(data, bytes)) and (not isinstance(data, bytearray)):
            data = bytearray(data, encoding='ascii')
        if self._serial is None:
            return False
        with self._lock:
            try:
                self._serial.write(data)
                self._serial.flush()
                self._set_online(True)  #Write succeeded, so we're online
                return True
            except Exception as ex:
                if print_trace:
                    log("%s couldn't write: %s" % (self._id, str(ex)))
                self._set_online(False)
        return False

    def wait_until_online(self, timeout=None):
        """
        Wait until connection is set up. Returns true if connection was made.
        """
        if not self._alive:
            log('wait_until_online() for un-started serial line')
            return False
        result = self._connection_made_event.wait(timeout)
        if not self._alive:
            return False
        return result
        #return (self, self.protocol)

    def __repr__(self):
        if not self.is_alive():
            return "SerialDaemon(%s, baud=%d, is_alive=False)" % (self._id, self._baudrate)
        return "SerialDaemon(%s, baud=%d, is_online=%s)" % (self._id, self._baudrate, self.is_online())

#    These need new logics for the persistent mode of operation:
#    def __enter__(self):
#        """\
#        Enter context handler. May raise RuntimeError in case the connection
#        could not be created.
#        """
#        self.start()
#        self._connection_made_event.wait()
#        if not self._alive:
#            raise RuntimeError('connection_lost already called')
#        return self.protocol
#
#    def __exit__(self, exc_type, exc_val, exc_tb):
#        """Leave context: close port"""
#        self.close()


######################################################################


import unittest
class TestLineReader(unittest.TestCase):
    def on_line(self, line):
        "Called by LineReader"
        self.assertTrue(len(self.lines) < 10)  #Sanity check
        self.lines.append(line)
    def setUp(self):
        self.lines = []
        self.r = LineReader(self)
    def test_no_newline(self):
        self.r.data_received('h')
        self.r.data_received('ello')
        self.assertEqual(self.lines, [])
    def test_1(self):
        self.r.data_received('h')
        self.r.data_received('ello')
        self.r.data_received('\r\n')
        self.assertEqual(self.lines, ['hello'])
    def test_2(self):
        self.r.data_received('h')
        self.r.data_received('ello\r\n')
        self.assertEqual(self.lines, ['hello'])
    def test_3(self):
        self.r.data_received('hello\r\n')
        self.r.data_received('abc\r\n')
        self.assertEqual(self.lines, ['hello', 'abc'])
    def test_4(self):
        self.r.data_received('hello\n')
        self.r.data_received('abc\n')
        self.r.data_received('def')
        self.assertEqual(self.lines, ['hello', 'abc'])
    def test_5(self):
        self.r.data_received('hello\r')
        self.r.data_received('abc\r')
        self.r.data_received('def')
        self.assertEqual(self.lines, ['hello', 'abc'])
    def test_6(self):
        self.r.data_received('hello\r\nabc')
        self.r.data_received('\rde\nfgh')
        self.r.data_received('\n')
        self.assertEqual(self.lines, ['hello', 'abc', 'de', 'fgh'])
    def test_7(self):
        self.r.data_received('hello\n\n')
        self.assertEqual(self.lines, ['hello', ''])

if __name__ == '__main__':
    unittest.main()
