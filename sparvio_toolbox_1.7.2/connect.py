# connect.py: Set up communication with the sparvio modules

import os
import time
import sys
import importlib

from reactive import eventthread
from core import ssplink
from core import systemview
from core import componentbase
from core import serialdaemon
from core import ssplink_udp
from core import framing
from core import localobject
from core import remoteobject

import influxwriter

class TerminateException(Exception):
    "Signifies that connect.py wishes to stop the program in a controlled manner"
    pass

def add_default_arguments(parser):
    parser.add_argument('--port', type=str,
                        help='the serial port where SA1 is connected (ex: COM3 in Windows or /dev/ttyACM0 in Linux)')
    # Possible verbosity levels (not implemented):
    #  1: Print SSP network events
    #  2: Print all received and transmitted messages
    #  3: Print all messages in binary format?
    parser.add_argument('-v', '--verbose',
                        action="count", default=0,
                        help='Increases verbosity of output')
    parser.add_argument('--ports', action='store_true',
                        help="Lists all reasonable values for 'port' and exits")
    parser.add_argument('--local', type=str, metavar='CLASS',
                        action='append', default=[],
                        help='Run simulated modules')
    parser.add_argument('--config', type=str,
                        action='append', default=[],
                        help='Add one or more configuration files')
    parser.add_argument('--udp', type=str, metavar='TXPORT:RXPORT',
                        action='append', default=[],
                        help='Connect over UDP')
    return parser

def wait_for_any_online(conns, timeout=3):
    if len(conns) == 0:
        return None
    start_time = time.time()
    while time.time() < start_time + timeout:
        for conn in conns:
            if conn.is_online():
                return conn
        time.sleep(0.05)
    return None

# 0. Fall-back values
config = {'args': {},
          'serial_ports': [],
          'verbose': 0,
          'rr1_ports': [],
          'local': [],  # Classes for local objects to start
          'udp_ports': [],  # List of pairs of integers
          'grafana_port': None,
          'grafana_auto_launch': False,
          'web_hostname': None,
          'web_port': None,
          'python_run': [],
          'python_eval': []}

def get_config(filename, args):
    # The variables will be placed in this module
    global config
    config['args'] = args
    # 1. Default config.py
    exec(open(filename).read(), config)
    # 2. Extra config files
    for c in args.config:
        if os.path.isfile(c):
            print('Reading config', c)
            exec(open(c).read(), config)
        else:
            print("Error: Can't find config file", c)
            raise TerminateException()
    # 3. User config file?

    # 4. Command line arguments
    if args.ports:
        print("Available options for 'port':")
        import enumerate_serial_ports
        for x in enumerate_serial_ports.enum_ports():
            print('  ' + x)
        if config['serial_ports']:
            print('Defaults: ' + ', '.join(config['serial_ports']))
        raise TerminateException()

    if args.port is not None and args.port not in config['serial_ports']:
        config['serial_ports'] = [args.port] + config['serial_ports']

    if args.verbose:
        config['verbose'] = args.verbose

    for l in args.local:
        config['local'].append(l)
    for pair in args.udp:
        try:
            (tx_port, rx_port) = udp_pair.split(':')
            tx_port = int(tx_port)
            rx_port = int(rx_port)
        except:
            print("Error: Can't parse UDP argument %s" % udp_pair)
            eventthread.stop()
            raise TerminateException()
        config['udp_ports'].append( (tx_port, rx_port) )
    return config


# Place similar to this in the main file:
#def run():
#    "Launch the system in accordance with the settings in <config>"
#    #add_default_arguments()
#    try:
#        config = get_config(args)
#        launch(config)
#    except TerminateException:
#        eventthread.stop()
#        return
#    interactive()
#    stop()

conns = []

def launch(config):
    """Launch the system in accordance with the settings in
       <config>. Returns the visualizer."""
    verbosity = config.get('verbose', 0)
    if verbosity >= 1:
        remoteobject.print_messages = True
        influxwriter.print_messages = True
        componentbase.print_received_messages = True
        localobject.print_local_events = True
        from core import aio
        aio.verbose = True
    if verbosity >= 2:
        import core.ssplink
        core.ssplink.debug_write = True
        remoteobject.print_discarded_lines = True

    for classname_and_init in config['local']:
        if '(' in classname_and_init:
            (classname, init_str) = classname_and_init.split('(',1)
            assert init_str.endswith(')')
            init_str = init_str[:-1]  # Strip trailing ')'
            init = {}
            for arg in init_str.split(','):
                (key,val) = arg.split('=', 1)
                assert key not in init
                init[key] = eval(val)
        else:
            classname = classname_and_init
            init = {}
        parts = classname.split('.')
        try:
            module = importlib.import_module('.'.join(parts[:-1]))
            cls = getattr(module, parts[-1])
        except Exception as ex:
            print('Error: Cannot find class {}'.format(classname))
            print(ex)
            raise TerminateException()
        component = cls(**init)
        component.start()
        component.record_to_log()

    vis = systemview.the_system

    global conns
    conns = []
    links = []
    for port_config in config['serial_ports']:
        baud = 9600  #115200   #Default speed
        probe = True  #Default
        rr1 = False #Default
        if ':' in port_config:
            (port, parts) = port_config.split(':', 1)
            for part in parts.split(','):
                if part.endswith('bps'):
                    baud = int(part[:-3])
                elif part == 'probe':
                    probe = True
                elif part == 'noprobe':
                    probe = False
                elif part == 'rr1' or part == 'rr2':
                    rr1 = True
                else:
                    print('Warning: Ignoring unknown port config ' + part)
        else:
            port = port_config
        if rr1:
            baud = 38400
        # Convenience for Linux (Windows ports start with 'COM')
        if port.startswith('tty'):
            port = '/dev/' + port
        elif port.startswith('ACM'):
            port = '/dev/tty' + port
        elif port.startswith('USB'):
            port = '/dev/tty' + port
        conn = serialdaemon.SerialDaemon(port=port, baud=baud)
        conns.append(conn)

        if rr1:
            from txt_receiver import Txt
            txt = Txt(conn)
        else:
            #link = ssplink.SerialLink(conn, framing.SspAsciiLineProtocol)
            link = ssplink.SerialLink(conn, framing.HexLineProtocol)
            link.probe_automatically = probe
            links.append(link)
            vis.add_link(link)
        conn.start()
    if len(conns) > 0:
        online = wait_for_any_online(conns, 1)
        if not online:
            print('No configured serial port is available. Available:')
            import enumerate_serial_ports
            for x in enumerate_serial_ports.enum_ports():
                print('  ' + x)
            eventthread.stop()
            raise TerminateException()

    for (tx_port, rx_port) in config['udp_ports']:
        link = ssplink_udp.UdpLink(rx_port, tx_port, framing.HexLineProtocol,
                                   link_id = len(links))
        links.append(link)
        vis.add_link(link)
        link.start()

    if config['web_port'] and config['web_hostname']:
        # Launch web server as thread, to enable access via the web
        # interface
        from core.aio import WebClients
        webclients = WebClients(vis._base,
                                hostname=config['web_hostname'],
                                port=int(config['web_port']))
        webclients.start()

    #if len(links) == 0:
    #    print('No links')
    #    eventthread.stop()
    #    raise TerminateException()

    if vis._base.central():
        # If the central is local, init here
        vis._base.central().init_all_local()
    vis.send_all_updates()
    #vis.on_networked()

    for conn in conns:
        conn.start()

    if influxwriter.is_available(config):
        from core.gis import log
        influx = influxwriter.start(config, localobject.system_log)
        #Ugly couplings:
        influx.register_get_component_name(vis.get_component_name)

    global default_thread
    default_thread = eventthread.EventThread(name="default_thread",
                                             scheduler=eventthread.default_scheduler).start()

    # Wait until all components have been added, so they can be
    # referred to straight away
    vis._thread.wait_until_processed()

    if config['python_run']:
        for run_file in config['python_run']:
            if config['verbose']:
                print('Running', run_file)
            try:
                exec(compile(open(run_file).read(), run_file, 'exec'))
            except:
                traceback.print_exc()
                stop()
                sys.exit(1)

    if config['python_eval']:
        for eval_str in config['python_eval']:
            if config['verbose']:
                print('Evaluating', eval_str)
            try:
                print(eval(eval_str))
            except:
                traceback.print_exc()

    if config['grafana_port'] and config['grafana_auto_launch']:
        grafana()

    return vis


######################################################################
## Interfacing

def grafana():
    "Launch Grafana to view real-time data"
    import webbrowser
    port = config['grafana_port']
    database = config['influx_database']
    webbrowser.open("http://127.0.0.1:%d/dashboard/db/%s?refresh=1s&orgId=1" % \
                    (port, database.lower()))


######################################################################
## Functions for interactive session

def interactive(_globals=None):
    try_ptpython = False  #Disabled until the bug where print() doesn't work with ptpython embed(patch_stdout=True)
    try:
        import prompt_toolkit
        #if not prompt_toolkit.__version__.startswith('2.'):
        #    print("ptpython needs prompt_toolkit 2 (installed: %s)" %
        #          prompt_toolkit.__version__)
        #    try_ptpython = False
    except:
        print('No prompt_toolkit. ptpython disabled')
        try_ptpython = False

    try:
        import jedi
        from distutils.version import LooseVersion
        if LooseVersion(jedi.__version__) < LooseVersion('0.11.0'):
            print('Warning: Should upgrade Jedi with "pip install jedi --upgrade"')
    except:
        print('Install jedi for ptpython')
        try_ptpython = False

    embed = None
    if try_ptpython:
        #sys.path.insert(0, "ptpython")
        #from ptpython.repl import embed
        try:
            from ptpython.repl import embed
        except:
            #traceback.print_exc()
            pass

    if embed:
        print('Interactive ptpython: Type "s." to see available Sparvio components. Press Ctrl+D for controlled exit.')
        def configure(repl):
            repl.confirm_exit=False
        if _globals is None:
            _globals = globals()
        embed(_globals, locals(), patch_stdout=True, configure=configure)
    else:
        print('Interactive Python session (without ptpython).')
        print('Type "dir(s)" to see available Sparvio components. Press Ctrl+D for controlled exit.')
        import code
        try:
            code.interact(local=_globals)  #locals())
        except SystemExit:
            pass  # Raised on Windows if calling exit()
