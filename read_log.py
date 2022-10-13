#!/usr/bin/env python3

# read_log.py: Talks to SA1 that is connected to SKH1, reading out all logs from SKH1

import argparse
import sys
if sys.version_info[0] < 3:
    raise Exception("Must be using Python 3")
    sys.exit(1)
import signal
import math
import os
import time
import traceback
from datetime import datetime, timezone

import connect
import app_ids
from core import remoteobject
from sspt import parse
from sspt import type_hints
from reactive import eventthread
from reactive.observable import SortingScheduler, CalculatedObsVar, immediate_scheduler
from reactive.indexeddict import SparseIndexedDict

from core.gis import log
from core.gis.sparvio_log import SparvioLog
from core.gis.file_writer import FileWriter
from core.gis import csv_logger #txt_logger

parser = argparse.ArgumentParser(description='Talks to SA1 that is connected to SKH1, reading out all logs from SKH1')
connect.add_default_arguments(parser)
parser.add_argument('--slow', action='store_true',
                    help='Slows down transfer, which may solve transfer problems')
parser.add_argument('--retain', action='store_true',
                   help='Avoids clearing the log after reading it')
parser.add_argument('--noread', action='store_true',
                   help='Avoids reading any log files. Just clears or formats the log.')
parser.add_argument('--format', action='store_true',
                    help='Not only clears the log, but formats the whole storage (after any other specified action)')
parser.add_argument('--raw', action='store_true',
                   help='Save a file with the raw data')
parser.add_argument('--dir', type=str, default='',
                    help='The directory to place log files (default is current directory)')

retain = False
do_exit = False
args = None

def signal_handler(signal, frame):
    global do_exit
    do_exit = True
    print('You pressed Ctrl+C!')
    eventthread.stop()
signal.signal(signal.SIGINT, signal_handler)

def print_progress(file_ix, filename, progress : float, bytes):
    "<progress> is between 0 and 1"
    if filename is None:
        filename = "?"
    label = "%d: %s " % (file_ix + 1, filename)
    progress = int(math.floor(progress*50))
    sys.stdout.write('\r' + label + ' [')
    sys.stdout.write('#' * progress)
    sys.stdout.write(' ' * (50-progress))
    sys.stdout.write(']')
    if bytes is not None:
        sys.stdout.write(" %d bytes" % bytes)
    sys.stdout.flush()

def element_to_str(element):
    if element == 'null':
        return ''
    return str(element)

def find_unused_filename(pattern):
    """Returns a filename that doesn't already exist. <pattern> is a path
       and filename, containing '%s' which will be replaced by a
       unique index (or removed).
    """

    directory = os.path.dirname(pattern)
    if directory != '' and not os.path.exists(directory):
        os.makedirs(directory)

    if not os.path.exists(pattern % ''):
        return pattern % ''

    file_ix = 1
    while True:
        if not os.path.exists(pattern % ('_' + str(file_ix))):
            return pattern % ('_' + str(file_ix))
        file_ix += 1

def calc_filename(dir : str,
                  start_time : type_hints.Timestamp, suffix : str) -> str:
    if start_time:
        filename_no_suffix = datetime.fromtimestamp(start_time, timezone.utc).strftime('%Y%m%d_%H%M%S')
        pattern = os.path.join(dir, filename_no_suffix + suffix)
    else:
        pattern = os.path.join(dir, "log" + suffix)
    # TODO: Only find an unused filename once.
    filename = find_unused_filename(pattern)
    return filename

def on_progress(data):
    sys.stdout.write('.')
    sys.stdout.flush()

def read_logs(loggerProxy, batch=1):
    "Returns False if there was any error"
    sessionCount = loggerProxy.get('logGetNumSessions')
    if sessionCount is None:
        print('Could not get logs')
        return False
    if sessionCount == 0:
        print('No logs')
        return True

    print('Reading %d logs' % sessionCount)

    read_ok = True
    for i in range(sessionCount):
        if do_exit:
            break
        (size, lineCount) = loggerProxy.call('logSelectSession', i,
                                         timeout=1, retries=10)
        if lineCount == 'null':
            sys.stdout.write('Size %s bytes. Finding line count' % repr(size))
            sys.stdout.flush()
            lineCount = loggerProxy.call('logLineCount', i, callback=on_progress,
                                     timeout=1, retries=10)
        if type(lineCount) is not int:
            print('Error, lineCount is', type(lineCount), lineCount)
            return False
        if lineCount == 0:
            print('Log %d is empty. Not creating file.' % (i+1))
            continue
        print(lineCount)

        scheduler = SortingScheduler()
        rawlog = SparseIndexedDict()  #TODO: Should be ObsList
        sparviolog = SparvioLog(scheduler=scheduler, source=rawlog)
        csv_filename = CalculatedObsVar(immediate_scheduler,
                                        calc_filename, args.dir,
                                        sparviolog.start_time, "%s.csv")
        if args.raw:
            raw_filename = CalculatedObsVar(scheduler,
                                            lambda csv_filename: csv_filename[:-4] + '_raw.txt',
                                            csv_filename)
            raw_filewriter = FileWriter(scheduler = scheduler,
                                        source = rawlog, path = raw_filename)

        lines_so_far = [0]  #Must have structure to allow access from function

        def on_log_line(line):
            lines_so_far[0] += 1
            rawlog.add(key = lines_so_far[0], data = line)

        tries = 1
        while lines_so_far[0] < lineCount:
            if do_exit:
                break
            try:
                loggerProxy.call('logReadLines',
                             min(batch, lineCount - lines_so_far[0]),
                             callback=on_log_line, timeout=1)
                tries = 1  #Success, reset counter
            except remoteobject.TimeoutException as ex:
                if tries == 5:
                    raise ex
                print('Timeout. Trying again.')
                time.sleep(0.1)
                tries += 1
            except remoteobject.NackException as ex:
                print(ex)
                #if tries == 5:
                #    raise ex
                print('Caught NACK. Next file.')
                time.sleep(0.01)
                #tries += 1
                read_ok = False
                break
            except Exception as ex:
                print(ex)
                print('Caught exception. (Error in log file?) Next file.')
                time.sleep(0.01)
                read_ok = False
                break

            if sparviolog.start_time.get() is None:
                # Try to calculate the start time to get the proper filename
                scheduler.run_to_completion()
            print_progress(i, csv_filename.get(),
                           float(lines_so_far[0]) / lineCount, None)

        scheduler.run_to_completion()
        print_progress(i, csv_filename.get(), 1, None)
        csv_logger.write_snapshot(sparviolog, path=csv_filename.get())
        print()  #Go to next line for the next file

    print('Done reading.')
    return read_ok

def main(args):
    global retain
    try:
        config = connect.get_config("config_noninteractive.py", args)
    except connect.TerminateException:
        # "Normal" early shutdown path
        return

    config['web_hostname'] = None  #Disable web server
    config['influx_host'] = None  #Disable influxdb
    view = connect.launch(config)

    #view = connect.from_argparser(args, dynamic=False)
    #if args.verbose:
    #    remoteobject.print_messages = True

    try:
        # This previously checked for name pattern "SKH1.*" and
        # "S2.*", but that required getting all names with
        # DynamicViewerComponent (not SystemViewComponent), which was
        # unnecessary comm and was error-prone. Instead assume the
        # logger is central. (Could also get 1.componentNames)
        start = time.time()
        while time.time() < start + 4:
            loggerProxy = view.get_proxy(1)
            name = loggerProxy.get("name")
            app = loggerProxy.get("app")
            if app == None:
                time.sleep(0.2)
            else:
                break
        if app != app_ids.deduce_id('S2') and app != app_ids.deduce_id('SKH1'):
            print('Error: SA1 is not connected to SKH1 or S2')
            return

        read_ok = True
        if not args.noread:
            if args.slow:
                batch = 1
            else:
                batch = 10
            try:
                read_ok = read_logs(loggerProxy, batch=batch)
            except:
                print('Exception reading. Not clearing log.')
                print(traceback.print_exc())
                retain = True

        if retain or not read_ok:
            pass
        elif args.format:
            print('Will format (this will take 1.5 minutes)')
            result = loggerProxy.call('logFormat', callback=on_progress)
            if result == 2:
                print('Done')
            else:
                print('No confirmation of formatting:', result)
        else:
            print('Will clear the log')
            result = loggerProxy.call('logClear', callback=on_progress)
            if result == None:
                print('Done')
            else:
                print('Unexpected result of clearing:', result)
    except Exception as ex:
        print('Caught exception:', ex)
        print(traceback.print_exc())


if __name__ == "__main__":
    args = parser.parse_args()
    retain = args.retain
    try:
        main(args)
    except connect.TerminateException:
        pass
    eventthread.stop()
