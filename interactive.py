#!/usr/bin/env python3

# Interactive terminal with real-time access to Sparvio system over
# serial line

import sys
import time
import argparse
import traceback
if sys.version_info[0] < 3:
    raise Exception("Must be using Python 3")
    sys.exit(1)

from core import localobject, remoteobject
from reactive import eventthread
import connect
from core import aio

from core.gis.position import Position

#For convenience for the user:
from sspt.ontology import global_ontology
#global_ontology.add_file('ontology/all.txt')

use_ipython = False

parser = argparse.ArgumentParser(description='Interactive Python terminal with real-time access to Sparvio system over SA1. Exit with Ctrl+D.')
connect.add_default_arguments(parser)
parser.add_argument('--run', type=str, metavar='FILE',
                    action='append', default=[],
                    help='Executes specified Python file on start')
parser.add_argument('--eval', type=str, metavar='EXPR',
                    help='Evaluate Python code on start')
parser.add_argument('--sub', action='store_true',
                    help='Subscribe to default variables')
parser.add_argument('--debugwrite', action='store_true',
                    help='Print all messages sent from the program')
try:
    args = parser.parse_args()
except:
    print('Error parsing arguments')
    sys.exit(1)

s = None
vis = None
usb = None
#system_log = None

def start():
    global vis
    try:
        config = connect.get_config("config_interactive.py", args)

        vis = connect.launch(config)

        vis._base._default_callback = print_msg

        if args.debugwrite:
            import core.ssplink
            core.ssplink.debug_write = True

        for run in args.run:
            with open(run) as f:
                print('Will execute file', run)
                code = compile(f.read(), run, 'exec')
                exec(code, globals())

        global s
        s = vis._system

        global system_log
        system_log = localobject.system_log

        time.sleep(0.1)  #Wait for other printouts to finish

        # Doesn't work; should be postponed until init is done
        #if args.sub:
        #    sub_defaults()

        if use_ipython:
            import IPython
            from traitlets.config import Config
            c = Config()
            c.InteractiveShell.colors = 'Linux' #Doesn't work. "%colors Linux" work.
            c.InteractiveShell.xmode = 'Minimal'
            c.InteractiveShell.confirm_exit = False
            c.TerminalInteractiveShell.colors = 'Linux' #Doesn't work.
            IPython.embed(config=c)
        else:
            connect.interactive(globals())

    except connect.TerminateException:
        # "Normal" early shutdown path
        pass
    except:
        # Unexpected exception
        traceback.print_exc()

    stop()


######################################################################
## Global interactive convenience functions

def by_id(_id):
    "object ID to proxy"
    return vis.get_proxy(_id)

def reset():
    usb.write('\nreset\n')

def vbat_on():
    usb.write('\nvbat on\n')

def vbat_off():
    usb.write('\nvbat off\n')

def all_names():
    components = by_id(1).get("components")
    all = {}
    for c in components:
        try:
            all[c] = by_id(c).get("name")
        except:
            all[c] = "?"
    return all

def sub_defaults(component = None):
    if component is None:
        components = by_id(1).get("components")
    else:
        components = [component]
    from core.systemview import the_system
    myOid = the_system.id.get()
    from sspt import pyObjects
    oidPyObj = pyObjects.RefInstance(global_ontology.label_to_registry_entry('Oid'),
                                     pyObjects.Uint8(myOid))
    for c in components:
        try:
            #defParams = by_id(c).get("defParams")
            #by_id(c).add_subscriber(defParams, print_report)
            by_id(c).call("subDef", oidPyObj)
        except:
            print('Error subscribing to %d' % c)
            continue

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

from core import systemview

def print_report(msg, timestamp = None):
    "<timestamp> is when the message is received. The message may contain a more exact timestamp for the generation time."
    if 'a' not in msg or 'map' not in msg:
        print('Malformed report', msg)
        return
    if msg['a'] != 'rep':
        print('Not a report', msg)
        return
    for (oid, valuemap) in msg['map'].items():
        from_name = systemview.the_system.get_component_name(oid)
        if from_name is None:
            from_name = str(oid)
        # Could treat event types differently
        val = ', '.join(["%s: %s" % (key, str(valuemap[key])) for key in sorted(valuemap.keys())])
        if timestamp:
            ts = timestamp_to_hhmmss_sss(timestamp)
            print("%s %s: %s" % (ts, from_name, val))
        else:
            print("%s: %s" % (from_name, val))

def print_msg(msg, timestamp = None):
    if msg.get('a', None) == 'rep':
        print_report(msg, timestamp)
    else:
        print(timestamp, msg)

def sub_events(oid=None):
        #print(msg)
    if oid is None:
        componentNames = by_id(1).get("componentNames")
    else:
        componentNames = {oid: str(oid)}
    for (c, name) in componentNames.items():
        print('Subscribing to', name)
        # 'sspLinkEvt'
        by_id(c).add_subscriber(['traceEvt', 'errorEvt'], print_msg)

def network():
    vis._base.probe_for_neighbor(0)


######################################################################

def stop():
    if args.verbose:
        print('Stopping threads')
    eventthread.stop()

def hand_inter(signum, frame):
    stop()
    sys.exit(0)
import signal
signal.signal(signal.SIGINT, hand_inter)

import atexit
atexit.register(stop)  #This doesn't work with Ctrl+D.

old_exit = exit
def exit():
    print("Capturing exit()")
    stop()
    old_exit()

#if __name__ == "__main__" and not sys.flags.interactive:
#    print 'Non-interactive session'
#    main(args.port)
#else:

start()
