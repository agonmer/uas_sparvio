
# Local object: Base classes for Sparvio components implemented in the
# local Python environment. Each component has a set of links for
# bi-directional communication with other components in the system.

# Received messages are converted to pyValue before processing. (Will
# this lose essential type information such as struct order?) When
# sending, the message is a Python dict where values may be pyValue or
# pyObj. This is marshalled depending on the link type.

import traceback
import time
from typing import Set

from reactive import eventthread
from reactive.observable import MutableObsSet, BasicObsVar, WrappedObsVar, ObsVar
from sspt import pyObjects
from sspt import constants
from . import ssplink
from .ssplink import SSP_LINK_ID, SSP_CENTRAL_ID, SSP_COMPONENT_MODULUS
from .componentbase import ComponentBase, get_by_componentId
from . import network
from .gis.log import MutableObjectsLog, ValuesLog

SSP_VISUALIZER_ID = SSP_CENTRAL_ID

typecheck_arguments = True
print_local_events = True

all_local_objects : MutableObsSet['LocalObject'] = MutableObsSet()
all_local_object_logs : MutableObsSet['ValuesLog'] = MutableObsSet()

#system_log : CombinedLog = CombinedLog(eventthread.default_scheduler,
#                                       all_local_object_logs)
system_log : MutableObjectsLog = MutableObjectsLog()

"""
UpdatedVariable = Tuple[Any, Var]
class CreateReportScheduler(observable.SimpleScheduler[UpdatedVariable]):
    "Post jobs (object, variable) to this Scheduler to include the variables in a new SSP Report to the subscriber"
    def __init__(self, subscriber_objectId : Oid,
                 send_report_scheduler : eventthread.Scheduler):
        self.subscriber_objectId = subscriber_objectId
        self._send_report_scheduler = send_report_scheduler
    def _generate_report(self):
        # Generate Report to self.subscriber_objectId
        raise NotImplementedException()
        self.pop_all_jobs()
"""

class SparvioInterface(object):
    """An interface is how an object is presented over Sparvio. It
       declares all available variables with types, functions with
       signatures and event types. All these must have a valid
       symbol. Per Sparvio specification, interfaces are immutable
       (can't add, remove or change members while the system is
       running). This is much more strict than Python.

       Interfaces do not specify variable getters, setters etc.
    """
    #These default class attributes are overridden by subclasses:

    def __init__(self):
        #Types of all variables:
        #Map from string (symbol) to pyObj variable type
        self._variables = {}

        #Signatures for all functions:
        #Map from string to tuple (pyObj argument type, pyObj return type)
        self._functions = {}

        #Names of all event types that may be emitted:
        #Array of strings.
        self._events = []

    def _add_variable(self, symbol, _type):
        "<_type> may be string or TypePyObj"
        assert not symbol in self._variables
        if type(_type) is str:
            from sspt.ontology import global_ontology
            _type = global_ontology.label_to_registry_entry(_type)
        self._variables[symbol] = _type


#Class decorator for SparvioInterface classes
def ssp_class(cls):
    #Collects ssp_function() decorators
    from types import FunctionType
    ssp_functions = cls.__dict__.get('_functions', {})
    all_fns = [x for x, y in cls.__dict__.items() if isinstance(y, FunctionType)]
    for fn in all_fns:
        if '_ssp_signature' in fn.__dict__ and fn.__name__ not in ssp_functions:
            #TODO: If args or return type is string, parse to SSP type -- or do it upon first use (when the ontology is loaded)
            ssp_functions[fn.__name__] = fn._ssp_signature
    cls._functions = ssp_functions
    return cls

#Method decorator for SparvioInterface classes
def ssp_function(arg_type, return_type):
    "Registers the method as accessible as SSP function, under the same name. Requires @ssp_class for the Python class. Since this constructs the SSP class at load-time, the class is assumed to not be in the registry"
    if type(arg_type) is str:
        from sspt.ontology import global_ontology
        arg_type = global_ontology.label_to_registry_entry(arg_type)
    if type(return_type) is str:
        from sspt.ontology import global_ontology
        return_type = global_ontology.label_to_registry_entry(return_type)

    def decorator(fn):
        #print('Register fn', fn.__name__, 'with args', arg_type, \
        #      'and return type', return_type)
        fn._ssp_signature = (arg_type, return_type)
        return fn
    return decorator

class LocalObject:
    """Base class for local objects (and local components). Local objects
       use native Python data types.
    """
    _class : SparvioInterface
    def __init__(self, base : ComponentBase, internalId = 0, thread=None):
        "<base> is the ComponentBase for this object (for components) or the enclosing component (for non-component objects)"
        self._base = base
        if isinstance(self, SparvioInterface):
            self._class = self
        else:
            #Default - can change to external Sparvio class
            self._class = SparvioInterface()
        if thread is None:
            #By default, run a separate thread for each object
            if isinstance(self, eventthread.EventThread):
                thread = self
            else:
                thread = eventthread.EventThread(name=base.name + 'Thread')
        self._thread = thread  #The thread that executes this object
        self.internalId = internalId  #Set to non-zero to indicate this is not a component
        self._updated : Set[str] = set()  #Variables that are not reported yet
        self._log : ValuesLog = None  # Initialized if record_to_log() is called

        # Field 'name' is also used in EventThread. Don't change the
        # type of it! This design kludge will be removed with soft_refactor.
        if 'name' not in self.__dict__:
            self.name = ''

        self.id = WrappedObsVar(self.get_objectId)
        self.vars = WrappedObsVar(lambda: list(self._class._variables.keys()))
        self.funcs = WrappedObsVar(lambda: list(self._class._functions.keys()))
        self.funcSigs = WrappedObsVar(lambda: self._class._functions)
        self.events = WrappedObsVar(lambda: self._class._events)

        all_local_objects.add(self)

        self._proxy = LocalProxy(self)

    def get_objectId(self):
        #assert self.componentId != None
        return self._base.componentId + (self.internalId * SSP_COMPONENT_MODULUS)

    def emit_event(self, type, arg):
        self._proxy.emit_event(type, arg)

    def send(self, to, msg):
        #This discards the 'from' object, but that is included in the
        #message if relevant
        self._base.send(to, msg)

    def start(self):
        self._thread.start()
        return self
    def stop(self):
        self._thread.stop()
        return self

    def record_to_log(self):
        if self._log is not None:
            return
        from .gis.log import ValuesLog
        self._log = ValuesLog()
        self._log.object_id = self.get_objectId()  #TODO: May not be initialized
        all_local_object_logs.add(self._log)
        self._proxy.add_subscriber(list(self._class._variables.keys()) + \
                                   self._class._events,
                                   self._log.register_message,
                                   initial_get=False)
        self._proxy.add_subscriber(list(self._class._variables.keys()) + \
                                   self._class._events,
                                   system_log.register_message,
                                   initial_get=False)

    #TODO: Before dispatching to the thread, check if the thread is
    #waiting for this message
    @eventthread.run_in_thread
    def handle_message(self, msg, timestamp = None):
        """This object receives a message addressed to it. Fallback handler
           for common functionality. """
        cmd = msg['a']
        do_reply = ('from' in msg)
        if cmd == 'get' or cmd == 'uget':
            reply_payload = []
            for var in msg['var']:
                try:
                    #This works with both regular fields and with __getattr__()
                    try:
                        pyValue = getattr(self, var)
                    except AttributeError:
                        #No such variable
                        self.emit_event("warning",
                                        {'text': "'Get' variable not known",
                                         'var': var})
                        if do_reply:
                            reply_payload.append(pyObjects.null)
                        continue
                    if callable(pyValue):
                        (arg_type, pyObj_type) = self._class._functions[var]
                        if not arg_type.is_null():
                            self.emit_event("warning",
                                            {'text': "Get of function that requires arguments",
                                             'var': var})
                            continue  #Requires argument
                        pyValue = pyValue()  #Access function as variable
                    elif var in self._class._variables:
                        pyObj_type = self._class._variables[var]
                    else:
                        #Variable not known
                        self.emit_event("warning",
                                        {'text': "'Get' of variable not in interface",
                                         'var': var})
                        continue

                    if do_reply:
                        reply_payload.append(pyObj_type.from_pyValue(pyValue))
                except:
                    traceback.print_exc()

        elif cmd == 'call':
            arg = msg['arg']
            name = msg['sym']
            if name not in self._class._functions:
                reply = {'from': self.get_objectId(), 'a': 'nack',
                         'tk': msg['tk'],
                         'code': constants.COR_UNKNOWN_VARIABLE}
                self.send(msg['from'], reply)
                return

            (arg_type, result_type) = self._class._functions[name]
            #Optional: Test converting to do argument typechecking:
            if typecheck_arguments:
                try:
                    arg_type.from_pyValue(arg)
                except:
                    #Typecheck error
                    self.emit_event("warning",
                                    {'text': "Argument typechecking error",
                                     'msg': msg})
                    if 'tk' in msg:
                        reply = {'from': self.get_objectId(), 'a': 'nack',
                                 'tk': msg['tk'],
                                 'code': constants.COR_ARGUMENT_ERROR}
                        self.send(msg['from'], reply)
                    return
            try:
                #Sketchy way to avoid list when only one parameter
                if (isinstance(arg, list) or isinstance(arg, tuple)) and \
                   len(arg) > 1:
                    pyValue_result = getattr(self, name)(*arg)
                else:
                    pyValue_result = getattr(self, name)(arg)
            except:
                self.emit_event("warning", {'text': "Exception calling",
                                            'cmd': name, 'msg': msg})
                if 'tk' in msg:
                    reply = {'from': self.get_objectId(), 'a': 'nack',
                             'tk': msg['tk'], 'code': constants.COR_FAIL}
                    self.send(msg['from'], reply)
                return

            if do_reply:
                reply_payload = result_type.from_pyValue(pyValue_result)
        elif cmd == 'rep':
            return
        else:
            self.emit_event("warning", {'text': "Unhandled msg type", 'msg': msg})
            return

        if do_reply:
            #print 'Send reply', repr(reply_payload), type(reply_payload)
            reply = {'from': self.get_objectId(), 'a': 'reply', 'b': reply_payload}
            if 'tk' in msg:
                reply['tk'] = msg['tk']
            self.send(msg['from'], reply)

    #@eventthread.run_in_thread
    #def set_value(self, name, value):
    #    "Registers a new value. Doesn't use setter"
    #    self.variables[name]['value'] = value
    #    self._updated.add(name)

    #The platform enables all objects to use these abilities:
    def mark_as_updated(self, *variable_names):
        self._proxy.mark_as_updated(*variable_names)

    #Not actually relevant as a method of LocalObject
    def subscribe(self, objectId, variable_symbol, callback):
        "Makes this object subscribe to a symbol of <objectId>. <callback> must take a message as argument"
        from .systemview import the_system  #Avoid circular import
        the_system.get_proxy(objectId).add_subscriber(variable_symbol, callback)

    def unsubscribe(self, objectId, variable_symbol, callback):
        "Makes this object unsubscribe to a symbol of <objectId>"
        if is_local_object(objectId):
            the_system.get_proxy(objectId).remove_subscriber(variable_symbol, callback)
        else:
            self._base.unsubscribe(objectId, {variable_symbol: callback})

    def unsubscribe_all(self):
        "Makes this object unsubscribe from all previously done subscriptions"
        print('unsubscribe_all() not implemented')
        pass

    def send_all_updates(self):
        "Makes this object send all unreported updates to all listeners"
        self._proxy.send_all_updates()

    def on_networked(self):
        "Called from componentbase when the central has changed"
        if self._log is not None:
            self._log.object_id = self.get_objectId()
        pass  #Override
    def on_non_networked(self):
        "Called from componentbase when connection to a central has been lost"
        pass  #Override

    def varType(self, symbol):
        "Returns the type of variable <symbol> as a pyObject"
        return self._class._variables[symbol]
    def fnSig(self, symbol):
        "Returns the signature (argument types and return type) of variable <symbol> as a pyObject"  #Or return a Python tuple of these?
        return self._class._functions[symbol]

    #Callbacks:
    def on_report(self, msg):
        #We received a report packet. We probably subscribed to these variables
        print('Obj', self.name, 'got report', msg)
        pass


class LocalComponent(LocalObject):
    "A 'top' SSP object, with a unique component ID"
    def __init__(self, name, thread=None, link_to_central=True, serial=None):
        base = ComponentBase(self, name=name, serial=serial)
        super().__init__(base, internalId=0, thread=thread)
        self.name = name
        self._networker = network.Networker(base, eventthread.default_scheduler)
        if link_to_central:
            from .systemview import the_system
            from . import ssplink
            link = ssplink.local_link(self)
            the_system.add_link(link)
    def start(self):
        super(LocalComponent, self).start()
        return self
    def add_link(self, link):
        self._base.add_link(link)
    def is_central(self):
        return self._base.componentId == SSP_CENTRAL_ID
    def __getattr__(self, attr):
        # Common getters
        if attr == 'name':
            return self._base.name
        if attr == 'parent':
            return self._base.parent
        if attr == 'priority':
            return self._base.priority
        if self.is_central():
            if attr == 'components':
                return self._base.central().get_component_ids()
            if attr == 'lookupId':
                return self._base.central().lookupId  #function
        raise AttributeError(attr)
        #LocalObject doesn't have this function
        #return LocalObject.__getattr__(self, attr)


class LocalInternalObject(LocalObject):
    "Superclass for internal objects (= not components)"
    def __init__(self, base, internalId=None, thread=None):
        if internalId is None:
            internalId = base.allocate_internalId(self)
        assert internalId != 0 and internalId != None
        super(LocalInternalObject, self).__init__(base,
                                                  internalId=internalId,
                                                  thread=thread)
        #Name not obligatory?
        #By default use the thread of the component
        pass

######################################################################


#Like remoteobject.ComponentProxy, but for local objects
class LocalProxy(object):
    def __init__(self, localobject):
        self._localobject = localobject

        # Local and remote subscribers to our variables and events
        # Map from string (symbol) to set of callables (local callbacks) or integers (remote objectIds)
        # The callbacks take a message as argument
        self._subscribers = {}

        # For each *remote* object, the subscribed symbols that are
        # marked to report to that object
        self._unreported_variables = {} #Map from objectId to set of strings (symbols)

        # Map from string (symbol) to timestamp when the variable was
        # most recently marked as updated
        self._update_times = {}

    def is_online(self):
        return True

    def get_objectId(self):
        return self._localobject.get_objectId()

    def add_subscriber(self, symbols, report_callback, initial_get=True):
        """Add local callback to be invoked when any of <symbols> of this
           object changes. <report_callback> must take a message as
           argument.
        """
        #print('LocalProxy ' + repr(self._localobject) + ' sub ' + repr(symbols))

        all_vars = self._localobject._class._variables

        for symbol in symbols:
            if (symbol in all_vars or
                symbol in self._localobject._class._events):
                continue
            print(self, 'add_subscriber() to unknown symbol', symbol)

        # Filter out any event types or variables that this object can not emit
        symbols = [symbol for symbol in symbols
                   if (symbol in all_vars or
                       symbol in self._localobject._class._events)]

        for symbol in symbols:
            if symbol in self._subscribers:
                self._subscribers[symbol].add(report_callback)
            else:
                self._subscribers[symbol] = set([report_callback])
        if initial_get:
            supported_symbols = [s for s in symbols if s in all_vars]
            if supported_symbols != []:
                msg = {'a': 'rep', 'map': {self.get_objectId():
                                           {symbol: getattr(self._localobject, symbol)
                                            for symbol in supported_symbols}}}
                if callable(report_callback):
                    report_callback(msg)
                else:
                    self._localobject.send(report_callback, msg)

    def add_subscribers(self, cbs_to_vars):
        "cbs_to_vars is mapping from callback to list of ASCII symbols that will invoke that callback"
        for (callback, symbols) in cbs_to_vars.items():
            self.add_subscriber(symbols, callback)

    def remove_subscriber(self, symbol, callback):
        "Make this object stop sending reports when <symbol> changes. <Callback> is callable() or objectId."
        if not symbol in self._subscribers:
            return
        self._subscribers[symbol].remove(callback)
        if not self._subscribers[symbol]:
            del self._subscribers[symbol]
        if not callable(callback) and callback in self._unreported_variables:
            self._unreported_variables[callback].remove(symbol)

    def get(self, symbol, default=None):
        try:
            value = getattr(self._localobject, symbol)
        except AttributeError:
            return default
        if isinstance(value, ObsVar):
            return value.get()
        return value
    def set(self, symbol, value):
        native_value = pyObjects.to_pyValue(value)
        getattr(self._localobject, symbol).set(native_value)
    def call(self, func_name, arg=None, callback=None, timeout=3, retries=0):
        "Synchronous call from any thread"
        native_arg = pyObjects.to_pyValue(arg)
        return self._localobject._thread.blocking_call(getattr(self._localobject, func_name), args=[arg])

    def emit_event(self, type, arg):
        "Makes this object emit an event to all listeners"
        if print_local_events:
            print(self._localobject._base.name, str(type) + ':', repr(arg))
        #TODO: Insert uTime (time.time()) ?
        msg = {'a': 'rep', 'map': {self.get_objectId(): {type: arg}}}
        if type in self._subscribers:
            subscribers = self._subscribers[type].copy()
        else:
            subscribers = set()
        if '*' in self._subscribers:
            subscribers.update(self._subscribers['*'])
        for subscriber in subscribers:
            if isinstance(subscriber, int):
                self._localobject.send(subscriber, msg)  # Send to Remote object
            else:
                print('emit_event to local object. This path is indeed used!')
                subscriber(msg)  # Send to local object

    def get_report(self, symbol):
        """Returns most recent report that includes the value (with
        timestamp).
        """
        raise Exception("Not implemented")

    def mark_as_updated(self, *symbols):
        """Called by the object itself *after* the variables <symbols> have
           been updated. A Report message is sent to all local
           subscribers. For remote subscribers, an additional
           send_all_updates() needs to be done.
        """
        subscriber_to_symbols = {}
        now = time.time()
        for symbol in symbols:
            self._update_times[symbol] = now
            msg = None

            for subscriber in self._subscribers.get(symbol, []):
                if callable(subscriber):
                    if not subscriber in subscriber_to_symbols:
                        subscriber_to_symbols[subscriber] = set()
                    subscriber_to_symbols[subscriber].add(symbol)
                else:
                    #'subscriber' is a remote objectId
                    if subscriber not in self._unreported_variables:
                        self._unreported_variables[subscriber] = set([symbol])
                    else:
                        self._unreported_variables[subscriber].add(symbol)

        for (subscriber, updated_symbols) in subscriber_to_symbols.items():
            #This is now the intersection of the updated variables and
            #what the subscriber subscribes to. Report all those
            #variables at once.
            msg = {'a': 'rep', 'map': {self.get_objectId():
                                       {symbol: getattr(self._localobject, symbol)
                                        for symbol in updated_symbols}}}
            subscriber(msg, timestamp=now)

    def send_all_updates(self):
        "Makes this object send all unreported updates to all listeners"
        unreported_variables = self._unreported_variables
        self._unreported_variables = {}
        for (listenerId, _vars) in unreported_variables.items():
            values = {var: getattr(self._localobject, var) for var in _vars}
            self._localobject.send(listenerId, {'a': 'rep', 'map':
                                                {self.get_objectId(): values}})

    def on_message(self, msg, timestamp):
        #Invoked when the system object received a message *from* this object
        #Only used for remote objects.
        pass

    def register_report(self, msg, timestamp):
        "The local object has emitted the report <msg>"
        # Local objects register variable updates in another way
        pass
