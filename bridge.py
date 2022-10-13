#!/usr/bin/env python3

# Interactive serial connection to a third-party module, accessed via
# a Sparvio system
# On Linux, exit with Ctrl+D
# On Windows, exit with Ctrl+D <Enter>

import sys
import time
import traceback
import time
import os

if sys.version_info[0] < 3:
    raise Exception("Must be using Python 3")
    sys.exit(1)

from sspt import parse
from reactive import eventthread
from core import ssplink
import connect

import argparse

do_exit = False

def stop():
    print('Stopping threads')
    eventthread.stop()

parser = argparse.ArgumentParser(description='Gives a serial connection to a third-party device connected to a SKD1 and interfaces via SA1. Exit with Ctrl+D.')
connect.add_default_arguments(parser)
parser.add_argument('device', type=str,
                    help='the name of the SSP device to interact with')

def on_event(msg):
    if 'map' not in msg:
        return
    _from = list(msg['map'])[0]
    sys.stdout.write(msg['map'][_from].get('serTxt',''))
    sys.stdout.flush()

def encode_raw_input_linux():
    try:
        a = input()
        encoded = parse.string_to_hex(a + '\r')
        #print('Encoded', type(a), repr(a), 'to', encoded)
    except KeyboardInterrupt:
        encoded = '0x03'  #Send ctrl-c
    except EOFError:
        #On Linux this is ctrl+D
        raise EOFError()
    return encoded

def encode_raw_input_windows():
    #Windows 10 bug raises a spurious EOFError before the KeyboardInterrupt on ctrl-c:
    #https://bugs.python.org/issue26531
    a = ''
    try:
        a = input()
        encoded = parse.string_to_hex(a + '\r')
    except EOFError:
        #On Windows 10, this is ctrl+C
        return '0x03'  #Send ctrl-c
    except KeyboardInterrupt:
        #Doesn't actually happen?!
        print('KeyboardInterrupt')
        return '0x03'  #Send ctrl-c
    if a.strip() == '\x04':  #Ctrl+D
        raise EOFError() #Signal the user wants to quit
    return encoded

if os.name == 'nt':
    encode_raw_input_platform = encode_raw_input_windows
else:
    encode_raw_input_platform = encode_raw_input_linux

#def signal_term_handler(signal, frame):
#  '''Handles KeyboardInterrupts, capturing Ctrl+C in Windows'''
#  #print 'signal_term_handler'
#  pass
#import signal
#signal.signal(signal.SIGINT, signal_term_handler)

def main(args):
    config = connect.get_config("config_noninteractive.py", args)
    view = connect.launch(config)
    #view = connect.from_argparser(args, dynamic=False)
    time.sleep(3)
    central = view.get_proxy(ssplink.SSP_CENTRAL_ID)
    _id = central.call('lookupId', args.device)
    if _id is None or _id == 0:
        print('Could not find component "%s"' % args.device)
        stop()
        return

    device = view.get_proxy(_id)
    device.add_subscriber('serTxt', on_event)
    if os.name == 'nt':
        exit_sequence = "Ctrl+D <enter>"
    else:
        exit_sequence = "Ctrl+D"
    print('Serial bridge started. Type %s to exit. Anything else is forwarded to "%s"' % (exit_sequence, args.device))

    while not do_exit:
        try:
            encoded = encode_raw_input_platform()
        except EOFError:
            print('Stopping')
            break

        if encoded != '':
            try:
                device.call('rawTx', encoded)
            except Exception as ex:
                print('Caught exception', ex)
    stop()

if __name__ == "__main__":
    args = parser.parse_args()
    try:
        main(args)
    except:
        print('Caught exception')
        print(traceback.print_exc())
        stop()
