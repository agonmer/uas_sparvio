#!/usr/bin/env python3

# Receive telemetry from RR1/RR2

import sys
import time
import argparse
import traceback
import time
if sys.version_info[0] < 3:
    raise Exception("Must be using Python 3")
    sys.exit(1)

from core import localobject
from reactive import eventthread
from reactive.eventthread import EventThread
import connect

parser = argparse.ArgumentParser(description='Receive telemetry from RR1/RR2. View with Grafana (localhost:3030) or Cesium (localhost:8080).')
connect.add_default_arguments(parser)
parser.add_argument('--server', action='store_true',
                    help='Read Sparvio data over the network (UDP)')
parser.add_argument('--debugwrite', action='store_true',
                    help='Print all messages sent from the program')
try:
    args = parser.parse_args()
except:
    print('Error parsing arguments')
    sys.exit(1)

do_exit = False  #Set to True to make main thread finish

from core.gis.geo_log import DerivedGeoLog
from core.gis.merged_log import MergedValuesLog
from core.gis.txt_logger import TxtLogger
from core import aio
from txt_receiver import Txt

from sspt.bytebuffer import ByteIterator
from core import messages

class Udp(EventThread):
    "Receive SSP packets over UDP (listens as UDP server)"
    def __init__(self, host: str, port: int):
        "<host> is the network interface to bind to. Use '' for all interfaces."
        EventThread.__init__(self, f"Udp({host}, {port})")
        self.host = host
        self.port = port
        from core.localobject import system_log
        self.log = system_log #log.MutableObjectsLog()
        # Record the name of each oid of the remote system, when the
        # remote system reports it
        self.id_to_name : Mapping[Oid, str] = {}

    def start(self):
        self._rx_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._rx_sock.bind((self.host, self.port))
        #Causes receiving to break 5 times per second, so the thread
        #can check _alive
        self._rx_sock.settimeout(0.2)
        return EventThread.start(self)
    def run(self):
        while self._alive:
            try:
                data, addr = self._rx_sock.recvfrom(1024) # Receive max 1024 bytes
                print("Received UDP packet %s from %s" % (repr(data), repr(addr)))
            except socket.timeout:
                continue  #Next iteration will start by checking _alive
            self._data_received(data)

    def _data_received(self, data: bytearray) -> None:
        "For now, just assume that each UDP packet is a full SSP-BIN message"
        self._handle_ssp_line(data)

    def _handle_ssp_line(self, bin_msg):
        # Copied from txt_receiver._handle_ssp_line() and modified

        iterator = bytebuffer.ByteIterator(bin_msg)
        try:
            addr_msg = messages.addressed_msg_type.from_impBin(iterator)
            msg = addr_msg['msg']
        except Exception as ex:
            print("Warning: could not decode", bin_msg)
            print(ex)
            return
        py_msg = msg.to_pyValue()
        if py_msg.get('a', None) != 'rep':
            print('non-report type', py_msg)
            return

        #print(py_msg)
        # It's a report. First, register any name metadata
        for (remote_oid, _map) in py_msg['map'].items():
            if 'name' in _map:
                # An object reports its own name
                self.id_to_name[remote_oid] = _map['name']
            if 'componentNames' in _map:
                # The central reports the names of all components
                names = _map['componentNames']
                for (oid, name) in names.items():
                    self.id_to_name[oid] = name

        # Second, transform the report
        dic : Mapping[str, Mapping[Var, Any]] = {}
        for (remote_oid, _map) in py_msg['map'].items():
            name = self.id_to_name.get(remote_oid,
                                       self.objectId + '_' + str(remote_oid))
            if name not in dic:
                dic[name] = {}
            dic[name].update(_map)

        q = get_best_packet_quality(params)
        if q is not None:
            if not self.objectId in dic:
                dic[self.objectId] = {}
            reception = int(100 * q / 255.)
            dic[self.objectId] = {'reception': reception}

        print(dic)
        self.log.append_data(dic)


def start():
    try:
        config = connect.get_config("config_interactive.py", args)
        # Remove!
        if config['serial_ports']:
            config['serial_ports'][0] += ':rr1,noprobe'
        elif not args.server:
            print('Warning: No serial port for RR1/RR2 is specified')
        config['dynamic'] = True

        connect.launch(config)
        scheduler = eventthread.default_scheduler

        if config['serial_ports']:
            txt = Txt(connect.conns[0])
            log = txt._log
            if args.server:
                print('Error: UDP server and serial ports are not supported simultaneously')
                sys.exit(1)
        elif args.server:
            print('Read data as UDP server')
            udp = Udp('', 8010)  #What address? https://stackoverflow.com/questions/23042485/python-udp-socket-bind-to-the-correct-address
            log = udp.log
        else:
            log = None

        if log:
            merged_log = MergedValuesLog(scheduler, log)
            aio.cesium_measurements = DerivedGeoLog(scheduler, merged_log)

            from datetime import datetime, timezone
            filename = datetime.fromtimestamp(time.time(), timezone.utc).strftime('%Y%m%d_%H%M%S') + '_telemetry.txt'
            txtlogger = TxtLogger(path=filename, log=log)
            print('Logging the telemetry to', filename)

        if 0:  # DEBUG
            f = "../windsond-desktop-git/windsond/static/demo_2015-04-16_0656.sounding"
            from core.gis import windsond_log
            l = windsond_log.WindsondLog(f)
            l.load()
            r = windsond_log.resolve_positions(l)
            for entry in r:
                aio.cesium_measurements.append_data(entry.key, entry.data)
            print('Loaded %d entries' % len(r))

        if args.debugwrite:
            import core.ssplink
            core.ssplink.debug_write = True

        time.sleep(0.1)  #Wait for other printouts to finish

        print('*** SPARVIO ***')
        print('For 3D, go to http://%s:%d/3d.html' % (config['web_hostname'], config['web_port']))
        print('For graphs, go to http://localhost:%d/' % config['grafana_port'])
        print('PRESS CTRL-C TO STOP')
        while not do_exit:
            time.sleep(0.2)

    except connect.TerminateException:
        # "Normal" early shutdown path
        pass
    except:
        # Unexpected exception
        traceback.print_exc()

    stop()


######################################################################
## Global interactive convenience functions

def timestamp_to_hhmmss_sss(timestamp):
    if timestamp is None:
        return ""
    hours = int(timestamp / 3600)
    timestamp -= hours * 3600
    hours = hours % 24
    minutes = int(timestamp / 60)
    timestamp -= minutes * 60
    seconds = int(timestamp)
    millisec = int((timestamp - seconds) * 1000)
    return "%02d:%02d:%02d.%03d" % (hours, minutes, seconds, millisec)


######################################################################

def stop():
    if args.verbose:
        print('Stopping threads')
    eventthread.stop()

def handle_interrupt(signum, frame):
    global do_exit
    if args.verbose:
        print('Do exit')
    do_exit = True
    #stop()
    #sys.exit(0)
import signal
signal.signal(signal.SIGINT, handle_interrupt)

start()
