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
import connect

parser = argparse.ArgumentParser(description='Receive telemetry from RR1/RR2. View with Grafana (localhost:3030) or Cesium (localhost:8080).')
connect.add_default_arguments(parser)
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

def start():
    try:
        config = connect.get_config("config_interactive.py", args)
        # Remove!
        if config['serial_ports']:
            config['serial_ports'][0] += ':rr1,noprobe'
        else:
            print('Warning: No serial port for RR1/RR2 is specified')
        config['dynamic'] = True

        connect.launch(config)

        if config['serial_ports']:
            txt = Txt(connect.conns[0])
            scheduler = eventthread.default_scheduler
            merged_log = MergedValuesLog(scheduler, txt._log)
            aio.cesium_measurements = DerivedGeoLog(scheduler, merged_log)
        else:
            txt = None

        if 0:  # DEBUG
            f = "../windsond-desktop-git/windsond/static/demo_2015-04-16_0656.sounding"
            from core.gis import windsond_log
            l = windsond_log.WindsondLog(f)
            l.load()
            r = windsond_log.resolve_positions(l)
            for entry in r:
                aio.cesium_measurements.append_data(entry.key, entry.data)
            print('Loaded %d entries' % len(r))

        if txt:
            from datetime import datetime, timezone
            filename = datetime.fromtimestamp(time.time(), timezone.utc).strftime('%Y%m%d_%H%M%S') + '_telemetry.txt'
            txtlogger = TxtLogger(path=filename, log=txt._log)
            print('Logging the telemetry to', filename)

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
