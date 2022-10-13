#!/usr/bin/env python3

import sys
if sys.version_info[0] < 3:
    raise Exception("Must be using Python 3")
    sys.exit(1)

import argparse
import traceback
import time

from core import remoteobject
from reactive import eventthread
from sspt import bytebuffer, ascii, pyObjects  #For parsing to pyObjects
import connect

parser = argparse.ArgumentParser(description='Sets a variable value for a Sparvio component connected via SA1')
connect.add_default_arguments(parser)

parser.add_argument('object', type=str,
                    help='name of the component, or "*" for the one directly connected to SA1')
parser.add_argument('var', type=str, help='Name of the variable')
parser.add_argument('value', type=str, help='Value to set')

def main():
    args = parser.parse_args()
    config = connect.get_config("config_noninteractive.py", args)
    view = connect.launch(config)

    start_time = time.time()
    if args.object == '*':
        print('Getting closest component')
        time.sleep(1)  # Hack to wait for component to be discovered
        _id = 0
        while time.time() < start_time + 2:
            try:
                _id = view.get('neig')[0]
            except:
                time.sleep(0.1)
            if _id != 0:
                break
        #TODO: Probably SA1, so get its neighbor
    else:
        while time.time() < start_time + 2:
            central = view.get_central_proxy()
            _id = central.call('lookupId', arg=args.object)
            if _id != 0:
                break
            time.sleep(0.1)
    if _id == 0:
        print("Didn't find component %s" % args.object)
        return

    component = view.get_proxy(_id)
    if args.object == '*':
        print('Got closest component', component.get('name'))

    pyObjects.define_builtins()  #May be needed to parse the argument

    iter = bytebuffer.StringIterator(args.value)
    try:
        pyObject = ascii.to_pyObj(iter)
    except:
        print('Value "%s" is not a valid SSP-ASCII expression' % args.value)
        return

    try:
        component.set(args.var, pyObject)
    except remoteobject.NackException as ex:
        print('Could not set:', ex)
        return
    except remoteobject.TimeoutException:
        print('Timeout')
        return
    print('Value of %s is now: %s' % (args.var, component.get(args.var)))


if __name__ == "__main__":
    try:
        main()
    except Exception as ex:
        print('Caught exception:', ex)
        print(traceback.print_exc())

    eventthread.stop()
