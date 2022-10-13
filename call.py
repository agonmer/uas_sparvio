#!/usr/bin/env python3

import argparse
import traceback
import time

from core import remoteobject
from reactive import eventthread
from sspt import bytebuffer, ascii, pyObjects  #For parsing to pyObjects
import connect

parser = argparse.ArgumentParser(description='Calls a function of a Sparvio component connected via SA1')
connect.add_default_arguments(parser)

parser.add_argument('object', type=str,
                    help='name of the component, or "*" for the one directly connected to SA1')
parser.add_argument('fn', type=str,
                    help='Name of the function')
parser.add_argument('arg', type=str, nargs='*', default=[],
                    help='Arguments to use (optional).')

def main(args):
    args = parser.parse_args()

    config = connect.get_config("config_noninteractive.py", args)
    view = connect.launch(config)
    time.sleep(1)  #Workaround to give time for the network to connect
    central = view.get_central_proxy()

    if args.object == '*':
        print('Getting closest component')
        try:
            _id = view.get('neig')[0]
        except:
            _id = 0
        #TODO: Probably SA1, so get its neighbor
    else:
        _id = central.call('lookupId', arg=args.object)
    if _id == 0:
        print("Didn't find component %s" % args.object)
        return

    component = view.get_proxy(_id)
    if args.object == '*':
        print('Got closest component', component.get('name'))

    pyObjects.define_builtins()  #May be needed to parse the argument

    if args.arg == []:
        pyObject = None
    else:
        if len(args.arg) == 1:
            arguments = args.arg[0]
        else:
            arguments = '[' + ','.join(args.arg) + ']'
        iter = bytebuffer.StringIterator(arguments)
        try:
            pyObject = ascii.to_pyObj(iter)
        except:
            print('Argument "%s" is not a valid SSP-ASCII expression' % str(arguments))
            return

    try:
        component.call(args.fn, pyObject)
    except remoteobject.NackException as ex:
        print('Could not complete call:', ex)
        return
    except remoteobject.TimeoutException:
        print('Timeout')
        return
    print('Call completed')


if __name__ == "__main__":
    args = parser.parse_args()
    if args.verbose:
        remoteobject.print_messages = True
    try:
        main(args)
    except Exception as ex:
        print('Caught exception:', ex)
        print(traceback.print_exc())

    eventthread.stop()
