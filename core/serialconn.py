# NOTE: serialconn has been superceded by the more generic
# serialdaemon, but kept here anyway in case it's needed for simple
# experiments.
#
# Under Windows, PySerial 3.4 requires Windows 7 or newer.
import threading
import time
import queue
import sys
import traceback

from typing import Union

try:
    import serial
except:
    print('Missing package: run "pip3 install pyserial"')
    sys.exit(1)

serial_version = serial.__dict__.get('__version__', '?')
if serial_version != '3.4':
    print('Pyserial version', serial_version)

# Globals:
serial_line_objects = []  #List of SerialLineConn
do_exit = False
print_writes = False
print_trace = False
print_extra_trace = False
#data = ''

start_time = time.time()

def log(text, timestamp=None):
    if timestamp is None:
        timestamp = time.time()
    print("%3.3f %s" % (timestamp - start_time, text))


class SerialLineConn(threading.Thread):
    "Line-oriented, threaded serial communication"

    def __init__(self, port='COM14', baud=115200, callback=None, id=None,
                 log_filename=None, buffer=True):
        "callback(conn, timestamp, data) is called on the SerialLineConn thread"
        threading.Thread.__init__(self, name="SerialLineConn(%s)" % port)
        #self.setDaemon(True)
        assert port is not None
        self._port = port
        self.baudrate = baud
        self._callback = callback
        if id:
            self._id = id
        else:
            if port.startswith('/dev/tty'):
                self._id = port[len('/dev/tty'):]
            else:
                self._id = port
        self.log_filename = log_filename
        self.logfile = None

        self._ser = None  # When ser has a value, it's an opened connection
        self.reason = ''  # Valid when an error has occured
        self._alive = False
        self._to_write = None
        self._done_writing = threading.Event() #Will be set every time the thread empties _to_write
        self._ignore = None  #If the next line contains this, it is not reported
        self._is_online = False
        #Callback is called for every received byte, for maximum resposiveness:
        self._single_byte_mode = not buffer
        global serial_line_objects
        serial_line_objects.append(self)

        if (not buffer) and (not callback):
            print('Serialconn warning: Non-buffered mode disabled as no callback is given')

    def _open(self):
        try:
            #inter_byte_timeout may be truncated to 0.1 on POSIX,
            #meaning 0.01 would be changed to 0
            if serial_version == '?' or float(serial_version) < 3:
                self._ser = serial.Serial(port=self._port,
                                          baudrate=self.baudrate,
                                          timeout=0.25, interCharTimeout=0.01,
                                          writeTimeout=1)
            else:
                self._ser = serial.Serial(port=self._port,
                                          baudrate=self.baudrate,
                                          timeout=0.25, inter_byte_timeout=0.01,
                                          write_timeout=1)
        except Exception as ex:
            self.reason = str(ex)
            if print_extra_trace:
                print(self.reason)
            self._ser = None
            return False
        return True

    def is_online(self):
        return self._is_online

    def _close(self):
        if self._ser:
            try:
                self._ser.close()
            except:
                pass
            self._ser = None

    def start(self):
        if self._alive:
            return
        self._alive = True
        threading.Thread.start(self)
        return self

    def stop(self):
        self._alive = False
        #join(self)

    def wait_until_online(self, timeout=3):
        "Returns true if the serial connection is online"
        starttime = time.time()
        while not self._is_online and time.time() < starttime + timeout:
            time.sleep(0.1)
        return self._is_online

    def write(self, data: Union[bytearray, bytes], ignore_echo=False):
        "Writes to the serial port. The data is lost if writing fails"
        if isinstance(data, str):
            data = bytes(data, encoding='ascii')
        assert isinstance(data, bytearray) or isinstance(data, bytes)
        attempts = 0
        self._done_writing.clear()
        start_time = time.time()
        if self._to_write:
            self._done_writing.wait(0.5)  #Wait max 0.5 second for previous write to finish
        if self._to_write:
            log('Previous write timed out')
        if print_writes:
            log('%s: write %s' % (self._id, repr(data)))
        self._to_write = data
        if ignore_echo:
            self._ignore = data
        try:
            #Stop waiting for input to write the output without delay
            self._ser.cancel_read()
        except AttributeError:
            #PySerial before 3.1 didn't have cancel_read()
            pass
        except:
            log('Exception doing self._ser.cancel_read():')
            print(traceback.print_exc())
            pass

    def run(self):
        reported = False
        self._is_online = False
        while (self._alive and not self._open()):
            if not reported and print_trace:
                log('Could not open %s. Will keep trying...' % self._id)
                reported = True
            time.sleep(1)
        if not self._alive:
            #print '%s aborted trying to open' % self._id
            return
        self._is_online = True
        if print_trace:
            print("Opened %s" % self._port)
        if self.log_filename:
            self.logfile = open(self.log_filename, 'a')
            self.logfile.write('Start log\n')
            print('%s opened log file %s' % (self._id, self.log_filename))
        else:
            self.logfile = None
        #global data
        data = ''
        line_time = None
        last_timeout = self._ser.timeout
        #Break up very long lines. SA1 has limited input buffer (but
        #the breaking up doesn't help)
        max_write = 120

        while self._alive:
            if self._ser is None:
                if self._open():
                    print('%s going online' % self._id)
                else:
                    time.sleep(0.2)
                    continue
            if not data:
                if self._to_write:
                    try:
                        firstWrite = self._to_write[:max_write]
                        written = self._ser.write(self._to_write[:max_write])
                        if written < len(firstWrite):
                            print('Failed to write all chars')
                            self._is_online = False
                        else:
                            self._is_online = True
                    except Exception as ex:
                        print("%s couldn't write" % self._id)
                        self._is_online = False
                    if self._is_online:
                        self._to_write = self._to_write[max_write:]
                        if not self._to_write:
                            self._done_writing.set()
                            #This shouldn't be necessary, but try anyway
                            try:
                                self._ser.flush()
                            except:
                                self._is_online = False
                    else:
                        #Error writing. Discard all data to write
                        self._to_write = bytearray()
                        self._done_writing.set()
                if self._to_write:
                    #There's more data to write, so pause only very
                    #briefly to let the first piece of data flush
                    new_timeout = 0.005
                else:
                    new_timeout = 0.25  # 0.01
            else:
                #We already received some data. Give the sender extra
                #time to send the rest of the line
                new_timeout = 0.25 #0.050

            try:
                in_waiting = self._ser.inWaiting()
                if in_waiting > 0:
                    newdata = self._ser.read(in_waiting)
                    self._is_online = True
                else:
                    if new_timeout != last_timeout:
                        #Might fail, if there's some error with the port
                        #Changing timeout may freeze for 30 seconds
                        #under Windows! As workaround, new_timeout is
                        #only changed when doing write in multiple
                        #segments
                        self._ser.timeout = new_timeout
                        last_timeout = new_timeout
                    newdata = self._ser.read(1)
                    #No new data, but no exception so the port is online
                    self._is_online = True
            except:
                newdata = bytes()
                if self._is_online:
                    self._is_online = False
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

            if newdata:
                #No new data
                if data:
                    #Flush reading incomplete line
                    if self.logfile:
                        self.logfile.write(repr(data) + '\n')
                    if self._ignore and self._ignore in data:
                        pass
                    elif self._callback:
                        self._callback(self, line_time, data)
                    self._ignore = None
                    data = bytearray()
                continue

            #Got some new data
            self._is_online = True
            if self._single_byte_mode and self._callback:
                self._callback(self, time.time(), newdata)
                continue

            if not data:
                line_time = time.time()
            for ch in newdata:
                data += ch
                #if len(data) > 200:
                #    print 'WARNING: Long data (%d)' % len(data)
                if ch == b'\n' or ch == b'\r':
                    if self.logfile:
                        self.logfile.write(repr(data))
                    if self._ignore and self._ignore in data:
                        pass
                    elif self._callback:
                        self._callback(self, line_time, data)
                    self._ignore = None
                    data = bytearray()

        if self._is_online:
            if print_trace:
                log('Closing %s' % self._port)
            self._is_online = False
        if self.logfile:
            self.logfile.close()
            self.logfile = None
        self._close()

    def __str__(self):
        return 'SerialLineConn(%s, %s, online=%s)' % (repr(self._port), repr(self._id), str(self.is_online()))
    def __repr__(self):
        return self.__str__()


def signal_handler(signal, frame):
    global do_exit
    print('You pressed Ctrl+C!')
    do_exit = True
    stop()
#signal.signal(signal.SIGINT, signal_handler)

class PrintConsumer(threading.Thread):
    "Receives data from any thread and processes it with a dedicated thread"
    def __init__(self):
        threading.Thread.__init__(self, name="PrintConsumer")
        #self.setDaemon(True)
        self._queue = queue.Queue()
        self._alive = False

    def start(self):
        "Call from any thread"
        self._alive = True
        threading.Thread.start(self)
        return self

    def stop(self):
        "Call from any thread"
        self._alive = False

    def on_new_data(self, _serial, _time, line):
        "Call from any thread"
        self._queue.put({'serial': _serial, 'time': _time, 'line': line})

    def run(self):
        start_time = time.time()
        while self._alive and not do_exit:
            try:
                item = self._queue.get(block=True, timeout=0.2)
            except queue.Empty:
                continue
            #text = item['line'].rstrip().replace('\r\n', '\n').replace('\r', '\n')
            log("%s %s" % (item['serial']._id, repr(text)),
                timestamp=item['time'])
        self._alive = False


def stop():
    global do_exit
    do_exit = True
    global serial_line_objects
    for conn in serial_line_objects:
        conn.stop()
    serial_line_objects = []
