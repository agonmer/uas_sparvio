#!/usr/bin/env python3

import sys
if sys.version_info[0] < 3:
    raise Exception("Must be using Python 3")
    sys.exit(1)

import argparse
import traceback
import time

import connect
from reactive import eventthread
from sspt.ontology import global_ontology

parser = argparse.ArgumentParser(description='Retrieves or streams variable values from a Sparvio component connected via SA1. Calling without arguments prints a sanity check for all connected modules.')
connect.add_default_arguments(parser)
parser.add_argument('--stream', action='store_true',
                    help="Starts streaming of data")
parser.add_argument('--all', action='store_true',
                    help="If variable is not specified, retrieve all variables instead of just default ones")

parser.add_argument('object', type=str, nargs='?',
                    help='name of the component, or "*" for the one directly connected to SA1')
parser.add_argument('var', type=str, nargs='*',
                    help='names of the variables. If none is given, the default ones are implied')

def on_data(msg):
    "Callback in streaming mode, when a report msg is received"
    if msg['a'] == 'rep':
        for (objectId, valuemap) in msg['map'].items():
            # This ignores which object emitted the data
            print(', '.join(["%s = %s" % (k, str(v)) for (k, v) in valuemap.items()]))
    else:
        print('Unknown message', msg)

def main():
    args = parser.parse_args()
    config = connect.get_config("config_noninteractive.py", args)
    view = connect.launch(config)
    time.sleep(1)  #Workaround to give time for the network to connect
    central = view.get_central_proxy()

    if args.object == None:
        #Print information on all connected modules
        components = central.get('components')
        for _id in components:
            c = view.get_proxy(_id, make=True)
            print('ID:', _id)
            if args.all:
                vars = c.get('vars')
                length = max([len(x) for x in vars])
                for param in vars:
                    padding = ' ' * (length - len(param))
                    try:
                        print('  ' + param + padding + ' = ' + repr(c.get(param)))
                    except:
                        print('Could not get ' + param)
            else:
                print('  serial number:', c.get('serNo'))
                print('  name:', c.get('name'))
                defaultParams = c.get('defParams')
                if defaultParams is None or defaultParams == []:
                    print('  No default parameters')
                else:
                    for param in defaultParams:
                        try:
                            print('  ' + param + ' = ' + repr(c.get(param)))
                        except:
                            print('Could not get ' + param)
        return

    if args.object == '*':
        print('Getting closest component')
        try:
            _id = view.get('neig')[0]
        except:
            _id = 0
    else:
        _id = central.call('lookupId', arg=args.object)
    if _id == 0:
        print("Didn't find component %s" % args.object)
        return

    component = view.get_proxy(_id, make=True)
    if args.object == '*':
        print('Got closest component', component.get('name'))

    if len(args.var) == 0:
        if args.all:
            vars = component.get('vars')
            vars.sort()
        else:
            vars = component.get('defParams')
    else:
        vars = args.var
        for var in vars:
            if global_ontology.name_to_symbol(var) is None:
                print("Error: Can't translate '%s' to symbol" % var)
                return

    if args.stream:
        component.add_subscribers({_var: [on_data] for _var in vars})
        print('PRESS ENTER TO STOP')
        input()
        component.remove_subscriber(vars)
    else:
        if len(vars) > 1:
            length = max([len(x) for x in vars])
            for param in vars:
                padding = ' ' * (length - len(param))
                try:
                    print('  ' + param + padding + ' = ' + \
                          repr(component.get(param)))
                except:
                    print('Could not get ' + param)
        else:
            try:
                print('Value of %s is: %s' % (vars[0], component.get(vars[0])))
            except AttributeError:
                print('No variable named "%s"' % vars[0])


if __name__ == "__main__":
    try:
        main()
    except Exception as ex:
        print('Caught exception:', ex)
        print(traceback.print_exc())

    eventthread.stop()
