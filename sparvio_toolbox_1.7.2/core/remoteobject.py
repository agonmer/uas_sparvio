# Implement a soft component that tracks the topology of the network,
# and create a local proxy object for all other components in the
# system. Calling a proxy object generates network calls to the remote
# object.
#
# These classes don't model the contents of remote components. That is
# done in dynamic.py.

import time
import queue

from reactive import eventthread
from sspt import pyObjects
from sspt import constants
from .ssplink import SSP_LINK_ID
from .localobject import system_log

##################################################
## Globals

print_messages = False         #Prints received messages
print_discarded_lines = False  #Prints data that wasn't handled as message

start_time = time.time()


##################################################
## Exception types

class TimeoutException(Exception):
    "No reply from a remote object in the allowed timespan"
    def __init__(self, message = None):
        super(TimeoutException, self).__init__(message)

class NackException(Exception):
    "An object failed (or refused) a command"
    def __init__(self, message = None):
        super(NackException, self).__init__(message)

#TODO: Use this again
class NotOnlineException(Exception):
    def __init__(self, message = None):
        super(NotOnlineException, self).__init__(message)


##################################################
##

class ComponentProxy(object):
    """Provides synchronous access to a remote Sparvio component, through
       a local ComponentBase.
    """
    def __init__(self, id, base):
        self._id = id
        self._base = base  #ComponentBase of the local component with contact to the remote component, stored here for sending
        #For threads blocking waiting for a particular ticket:
        #Callbacks for particular symbols:
        self.print_messages = False
        self.name = None  #Not known yet
        self.x = None  #Simulated object
        #print 'Creating ComponentProxy %d' % id
        self._known_by_central = False
        #Local subscribers to the remote object.
        #Map from symbol to set of local callbacks
        self.subscribes_to = {}
        self._log = None  # A ValuesLog. Not implemented yet! See LocalObject.record_to_log()
        self.record_to_log()

    def is_online(self):
        if not self._base.is_link_online(self._id):
            return False
        return self._known_by_central

    def _send(self, msg):
        "Send <msg> to the remote component represented by this object"
        self._base.send(self._id, msg)

    def _send_and_get_reply(self, msg, timeout=1, callback=None):
        """Blocks the calling thread until a reply is returned or <timeout>
           sec elapsed since last ACK. Calls <callback> for every ack
           and for the reply, if specified.
        """
        q = queue.Queue()
        def on_reply(msg, timestamp):
            q.put(msg)
        ticket = self._base.make_ticket_with_callback(on_reply)
        msg['tk'] = ticket
        msg['from'] = self._base.componentId
        self._send(msg)
        # Now block waiting for reply
        while True:
            try:
                msg = q.get(block=True, timeout=timeout)
            except queue.Empty:
                msg = None
                break
            if not (msg and 'a' in msg):
                continue # Ignore invalid message
            if msg['a'] == 'ack':
                data = msg.get('b', None)
                if callback:
                    callback(data)
                continue
            # 'reply' or 'nack'
            break
        if msg and 'a' in msg and msg['a'] == 'reply':
            data = msg.get('b', None)
            if callback:
                callback(data)
        elif msg and 'a' in msg and msg['a'] == 'nack':
            #code = msg.get('code', None)
            #if callback:
            #    callback(data)
            pass
        self._base.remove_ticket(ticket)
        return msg  #Returns None if timeout

    def _handle_reply(self, reply, nested=True):
        "All 'reply' messages have the same pattern. Check for errors."
        if reply is None:
            raise TimeoutException('Timeout waiting for reply from remote object %d' % self._id)
        if reply['a'] == 'nack':
            code = reply.get('code', 0)
            if code == 0:
                raise NackException('Rejected by component')
            else:
                raise NackException('Rejected by component (reason %d %s)' %
                                    (code, constants.ERROR_CODES.get(code, '?')))
        payload = reply.get('b', None)
        if payload is None:
            return None
        if nested:
            if type(payload) is list and len(payload) == 1:
                return payload[0]
            return None
        return payload

    def get_variables(self):
        """Queries the list of available variables.
           Synchronous call from any thread"""
        msg = {'a': 'getVarList'}
        return self._handle_reply(self._send_and_get_reply(msg, timeout=3),
                                  nested=False)

    def get(self, attr, timeout=3):
        "Returns a Sparvio variable value as a Python value. Synchronous call from any thread"
        msg = {'a': 'uget', 'var': [attr]}
        payload = self._handle_reply(self._send_and_get_reply(msg, timeout=timeout),
                                     nested=True)
        if payload == None:
            return None  #Error
        value = pyObjects.to_pyValue(payload)
        if self._log is not None:
            self._log.append_data(timestamp = time.time(), data = {attr: value})
        return value

    def call(self, func_name, arg=None, callback=None, timeout=3, retries=0):
        "Synchronous call from any thread. Waits <timeout> for the first attempt, and for each retry if <retries> > 0."
        msg = {'a': 'call', 'sym': func_name, 'arg': arg}
        _try = 0
        while _try <= retries:
            reply = self._send_and_get_reply(msg, timeout=timeout,
                                             callback=callback)
            if reply is not None:
                break
            if _try == retries:
                raise Exception("No reply")   #Failed all attempts
            _try += 1
        payload = self._handle_reply(reply, nested=False)
        return payload

    def call_oneway(self, func_name, arg=None):
        "Sends a command without request for reply, and without waiting for a reply"
        msg = {'a': 'call', 'sym': func_name, 'arg': arg}
        self._send(msg)

    def set(self, attr, value):
        "Synchronous call from any thread"
        msg = {'a': 'set', 'map': {attr: value}}
        return self._handle_reply(self._send_and_get_reply(msg, timeout=1),
                                  nested=False)

    def set_multi(self, attr_to_values):
        "Synchronous call from any thread. attr_to_values is a dict (symbol string -> value)"
        msg = {'a': 'set', 'map': attr_to_values}
        return self._handle_reply(self._send_and_get_reply(msg, timeout=1),
                                  nested=False)

    def add_subscriber(self, symbols, report_callback, initial_get=True):
        """Subscribe to one or multiple variables or events *from* the remote
           object. When a report is received, report_callback is
           called with the full dict of the report, even if it also
           includes unrelated objects and variables
        symbols: A symbol string or a list of symbol strings
        report_callback: A function with one argument (message)
        """
        if not type(symbols) is list:
            symbols = [symbols]
        for symbol in symbols:
            pyObj = pyObjects.symbol_type.from_pyValue(symbol)
            if pyObj is None:
                raise Exception("No a SSP symbol: " + symbol)
            if not symbol in self.subscribes_to:
                self.subscribes_to[symbol] = set()
            self.subscribes_to[symbol].add(report_callback)
        self._base.subscribe(self._id,
                             {sym: [report_callback] for sym in symbols})

    def add_subscribers(self, symbols_to_callbacks):
        """<symbols_to_callbacks> is mapping from ASCII symbols to list/set of
           callbacks to invoke when a report from the remote
           component contains that symbol
        callback: A function with one argument (message)
        """
        for (symbol, callbacks) in symbols_to_callbacks.items():
            if not symbol in self.subscribes_to:
                self.subscribes_to[symbol] = set()
            self.subscribes_to[symbol].update(callbacks)
        self._base.subscribe(self._id, symbols_to_callbacks)

    def remove_subscriber(self, symbols):
        "Unsubscribe all callbacks from one or multiple previously subscribed variables or events"
        _from = self._base.componentId
        # Since componentbase records each callback, we need to
        # specify what callbacks we use
        symbols_to_callbacks = {}
        for symbol in symbols:
            if not symbol in self.subscribes_to:
                continue
            # Creates a second reference to the set, but it doesn't matter
            symbols_to_callbacks[symbol] = self.subscribes_to[symbol]
            del self.subscribes_to[symbol]
        self._base.unsubscribe(self._id, symbols_to_callbacks)

    def reset(self):
        "Makes the component do a software restart (reboot)"
        self._send({'a': 'reset'})

    def record_to_log(self):
        if self._log is not None:
            return
        from .gis.log import ValuesLog
        self._log = ValuesLog()
        self._log.object_id = self._id
        #from .localobject import system_log
        #system_log.add_source(self._log)

    def register_report(self, msg, timestamp):
        "The remote object has emitted the report <msg>"
        if self._log is not None:
            self._log.register_message(msg, timestamp)
        system_log.append_data({self._id: msg['map'][self._id]}, timestamp)

    def __str__(self):
        return "ComponentProxy(id=%d)" % (self._id)
    def __repr__(self):
        return self.__str__()


######################################################################
## RemoteObjectCache

# TODO: Instead use log.ValuesLog and store as ComponentProxy._log

# Plugins can associate aux data with objects -- for example derived
# parameters associated with historic data (smoothing), window
# handles, etc.
#

# Like RemoteProxy, but persistent subscriptions if the remote object
# restarts, and get() uses cached values
class RemoteObjectCache:
    #Part of SystemCache, for a particular object
    """Objects are never removed but have a "online" property. Objects
       store a reference from each variable to the latest message with
       that variable.
    """
    def __init__(self, system_cache, objectId):
        self.system_cache = system_cache
        self.objectId = objectId
        #Only *local* subscribers. Map from string (symbol) to set of callbacks
        #The callbacks take a message as argument
        self._subscriptions = {}
        self.values = {}  #Map from string (symbol) to native Python value

    #Users can add auxiliary data to objects, for example GUI handles.
    #
    #Subscriptions should be remembered and be applied when components come online
    #Also enqueue requests (asynchronous access)?

    def add_subscriber(self, symbol, callback, initial_get=True):
        "When <symbol> later changes, multiple quick reports may be condensed into one call to <callback>"
        if symbol in self._subscriptions:
            self._subscriptions[symbol].add(callback)
        else:
            self._subscriptions[symbol] = set([callback])
            #TODO: Enqueue subscribe message

    def remove_subscriber(self, symbol, callback):
        if not symbol in self._subscriptions:
            return
        self._subscriptions[symbol].remove(callback)
        if not self._subscriptions[symbol]:
            del self._subscriptions[symbol]  #Empty set, so remove
            #TODO: Enqueue unsubscribe message

    def on_message(self, msg, timestamp):
        "Received a message from the remote object"
        if self.print_messages:
            print('on_message id=%d %s' % (self._id, repr(msg)))
        #Call every callback registered for any of the received
        #symbols, but only call each once
        callbacks = set()
        if msg['a'] == 'rep':
            if 'map' not in msg or self.objectId not in msg['map']:
                print('remoteobject.py: on_message() with unrelated message', msg)
                return
            _map = msg['map'][self.objectId]
            for (sym, value) in _map.items():
                self.values[sym] = value
                callbacks.update(self._subscriptions.get(sym, []))

        for cb in callbacks:
            if cb:
                cb(msg)

    def register_value(self, symbol, value):
        self.values[symbol] = value
        msg = None
        for callback in self._subscriptions.get(symbol, []):
            if msg is None:
                msg = {'a': 'rep', 'map': {self.objectId: {symbol: value}}}
            callback(msg)

    def get_value(self, symbol):
        "Returns most recently cached value"
        return self.system_cache.get_value(self.objectId, symbol)
    def get_report(self, symbol):
        """Returns most recent report that includes the value (with
        timestamp).
        """
        return self.system_cache.get_report(self.objectId, symbol)
    def request_report(self, symbols):
        "Asynchronously request a single report of the value of all symbols of <symbols>, each cancelled if any future report contains that symbol"
        # Can set a flag that the value is desired, with priority when
        # dealing with low-bandwidth links
        raise Exception("Not implemented")


##################################################
##

class LinkProxy(object):
    """Treat link-level neighbors with (almost) the same interface as
       remoteobject, to enable communicating with neighbors without
       the network layer that may change in run-time.
    """
    def __init__(self, link : 'Link', base : 'ComponentBase'):
        self._link = link
        self._base = base  #TODO: Necessary?

    def is_online(self):
        return self._link.is_online()

    def _send(self, msg):
        "Send <msg> to the neighbor represented by this object"
        self._link.send(SSP_LINK_ID, msg)

    def _send_and_get_reply(self, msg, timeout=1, callback=None):
        """Blocks the calling thread until a reply is returned or <timeout>
           sec elapsed since last ACK. Calls <callback> for every ack
           and for the reply, if specified.
        """
        q = queue.Queue()
        def on_reply(msg, timestamp):
            q.put(msg)
        ticket = self._base.make_ticket_with_callback(on_reply)
        msg['tk'] = ticket
        msg['from'] = SSP_LINK_ID
        self._send(msg)
        # Now block waiting for reply
        while True:
            try:
                msg = q.get(block=True, timeout=timeout)
            except queue.Empty:
                msg = None
                break
            if not (msg and 'a' in msg):
                break
            if msg['a'] == 'ack':
                data = msg.get('b', None)
                if callback:
                    callback(data)
                continue
            # 'reply' or 'nack'
            break
        if msg and 'a' in msg and msg['a'] == 'reply':
            data = msg.get('b', None)
            if callback:
                callback(data)
        elif msg and 'a' in msg and msg['a'] == 'nack':
            #code = msg.get('code', None)
            #if callback:
            #    callback(data)
            pass
        self._base.remove_ticket(ticket)
        return msg  #Returns None if timeout

    def handle_message(self, msg, timestamp):
        print('LinkProxy got:', msg, timestamp)

    def _handle_reply(self, reply, nested=True):
        "All 'reply' messages have the same pattern. Check for errors."
        if reply is None:
            raise TimeoutException('Timeout waiting for reply from remote link ' +str(self._link))
        if reply['a'] == 'nack':
            code = reply.get('code', 0)
            if code == 0:
                raise NackException('Rejected by component')
            else:
                raise NackException('Rejected by component (reason %d %s)' %
                                    (code, constants.ERROR_CODES.get(code, '?')))
        payload = reply.get('b', None)
        if payload is None:
            return None
        if nested:
            if type(payload) is list and len(payload) == 1:
                return payload[0]
            return None
        return payload

    def get_variables(self):
        """Queries the list of available variables.
           Synchronous call from any thread"""
        msg = {'a': 'getVarList'}
        return self._handle_reply(self._send_and_get_reply(msg, timeout=3),
                                  nested=False)

    def get(self, attr, timeout=3):
        msg = {'a': 'uget', 'var': [attr]}
        payload = self._handle_reply(self._send_and_get_reply(msg, timeout=timeout),
                                     nested=True)
        if payload == None:
            return None  #Error
        value = pyObjects.to_pyValue(payload)
        return value

    def call(self, func_name, arg=None, callback=None, timeout=3, retries=0):
        "Synchronous call from any thread. Waits <timeout> for the first attempt, and for each retry if <retries> > 0."
        msg = {'a': 'call', 'sym': func_name, 'arg': arg}
        _try = 0
        while _try <= retries:
            reply = self._send_and_get_reply(msg, timeout=timeout,
                                             callback=callback)
            if reply is not None:
                break
            if _try == retries:
                raise Exception("No reply")   #Failed all attempts
            _try += 1
        payload = self._handle_reply(reply, nested=False)
        return payload

    def call_oneway(self, func_name, arg=None):
        "Sends a command without request for reply, and without waiting for a reply"
        msg = {'a': 'call', 'sym': func_name, 'arg': arg}
        self._send(msg)

    def set(self, attr, value, timeout=1):
        "Synchronous call from any thread"
        msg = {'a': 'set', 'map': {attr: value}}
        return self._handle_reply(self._send_and_get_reply(msg, timeout=timeout),
                                  nested=False)


##################################################
##

import inspect

supress_jedi_autocompletion_getter = True

class RemoteVariable(object):
    "Used as property for generated X classes"
    def __init__(self, name):
        self._name = name
    def __get__(self, instance, owner):
        if (supress_jedi_autocompletion_getter and
            inspect.stack()[1][3] == 'getattr_paths'):
            #Called from Jedi autocompletion for no known
            #reason. Don't query the value.
            return None
        return instance._proxy.get(self._name)
    def __set__(self, instance, value):
        return instance._proxy.set(self._name, value)

class RemoteFunction(object):
    def __init__(self, proxy, name, arg_type, return_type):
        self._proxy = proxy
        self._name = name
        self._arg_type = arg_type  #None means unknown argument types
        self._return_type = return_type
        # Dict from parameter to any string :
        if return_type is not None:
            self.__annotations__ = {'return': return_type.to_sspAscii() }
        # help() documentation for the function
        if arg_type is None:
            self.__doc__ = "No information available."
        elif isinstance(arg_type, pyObjects.SspPyObj):
            self.__doc__ = "Arguments: %s" % arg_type.to_sspAscii()
        else:
            print('ERROR: RemoteFunction unexpected arg_type', arg_type)
    def __call__(self, *args):
        if len(args) == 0:
            args = None
        elif len(args) == 1:
            #Current SSP convention is to not embed a single argument as a list
            args = args[0]
        else:
            #list() makes sure to resolve any iterator etc.
            args = list(args)
        if self._arg_type is None:
            #No typechecking.  pyObjects.from_pyValue() will convert
            #to any convenient SSP-BIN type.
            typed_args = args
        else:
            try:
                typed_args = self._arg_type.from_pyValue(args)
            except:
                raise Exception("Arguments to %s don't match type %s" %
                                (self._name, self._arg_type.to_sspAscii()))
        return self._proxy.call(self._name, arg=typed_args)

def RemoteObjectClassFactory(classname, proxy):
    """This function returns a Python class used for one remote Sparvio
       component, populated by the 'remote' variables and functions
       declared by that component.
    """
    def __init__(self, component_name):
        self.name = component_name
        pass
    #def __name__(self):
    #    return self.__class__.__name__
    def __dir__(self):
        #Requires Jedi 0.11 or later to avoid excessive get for all
        #members when running interactive ptpython
        #return []  #Workaround
        return self._members

    try:
        # TODO: Get variable types
        _members = proxy.get_variables()
    except:
        print('Failed to get variables from', classname)
        _members = []
    if 'name' in _members:
        _members.remove('name')  #Special handling: constant set in constructor
    dic = {"__init__": __init__,
           "__name__": classname,
           "__dir__": __dir__,
           "_members": _members,
           "_proxy": proxy}
    for var in _members:
        dic[var] = RemoteVariable(var)
    try:
        func_sigs = proxy.get("funcSigs")
    except AttributeError:
        func_sigs = []
    except NackException:
        #Fallback to just get function names, not signatures:
        print("Failed to get funcSigs from", proxy)
        func_names = proxy.get("funcs")
        func_sigs = {name: (pyObjects.any_type, pyObjects.any_type)
                     for name in func_names}
    if func_sigs is None:
        func_sigs = []
    funcs = []
    for (func, (arg_type, return_type)) in func_sigs.items():
        funcs.append(func)
        dic[func] = RemoteFunction(proxy, func, arg_type, return_type)
    dic["_members"].extend(funcs)  #Add to dir()
    newclass = type(classname, (object,), dic)
    return newclass
