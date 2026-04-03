# Component base: Basic functionality for local components

import threading
import time
import inspect
from typing import List
from reactive import eventthread

from .ssplink import SSP_INVALID_COMPONENT_ID, SSP_LINK_ID, SSP_CENTRAL_ID, SSP_COMPONENT_MODULUS
from sspt import constants

print_received_messages = False

def now():
    #Can be replaced, to do simulation
    return time.time()

all_componentbases : List["ComponentBase"] = []

def get_by_componentId(_id):
    for base in all_componentbases:
        if base.componentId == _id:
            return base
    return None

def is_local_object(objectId):
    return get_by_componentId(objectId % SSP_COMPONENT_MODULUS) is not None

class ComponentBase:
    "Data structures to describe the place of the local component in the Sparvio network, and functionality that can run on any thread"
    def __init__(self, component, name="", serial=None):
        all_componentbases.append(self)
        self.component = component
        self._lock = threading.RLock()
        self._link_neighbors = {}  #Direct neighbors: Map from Link to componentId for the direct neighbor
        #self.objects = {}  #Map from objectId to LocalObject that receives the message
        self.links = []  #All known links (ssplink.Link), where index can be used as link id
        self._link_proxies = {} #Map from Link to LinkProxy, for those Links where a LinkProxy has been explicitly requested
        self.routes = {} #For all known components: Map from componentId to Links.
        self.parent = 0
        self.base_priority = 0  #If > 0, we will attempt to be central
        self.priority = 0  #Prio adjusted for run-time network 'weight'
        self.name = name
        self.componentId = 0  #0 = not networked
        #self.default_componentId = 0  #When asking for an initial id, prefer this choice
        self._next_internalId = 1  #Used when auto-assigning internalId to internal objects
        if serial is None:
            #Only guaranteed to work on CPython:
            self.serial = id(self) % 0xFFFFFFFF  #"unique" serial number
        else:
            self.serial = serial

        #Mapping from ticket to callback waiting for that ticket
        #Dict from integer to fn(msg, timestamp)
        self.reply_callbacks = {}
        self._last_ticket = 0
        self._internal_objects = {} #Map from internalId to LocalInternalObject

        self._central : "Central" = None

        #Receive subscription reports going to multiple local listeners
        #(objects), as this local component may be the formal
        #recipient of all subscriptions. That saves constrained
        #devices from sending multiple reports to different objects
        #that reside on the same computer anyway.
        #
        #TODO: This should serve as auto-subscribe; this is the
        #*requested* subscriptions.
        "Registers that this object wishes to subscribe to the variables and event types of <symbol_list> from objectId every time the two become part of the same network"
        #
        #Map source objectId -> (Map symbol -> callback)
        self.obj_to_subscribers = {}

        #Set to the function (signature (msg, timestamp)) to call for
        #any received event or report without a registered (callable)
        #subscriber
        self._default_callback = None

    def allocate_internalId(self, internalObject : "LocalInternalObject"):
        newId = self._next_internalId
        self._next_internalId += 1
        self._internal_objects[newId] = internalObject
        return newId

    def get_link_by_id(self, link_id):
        return self.links[link_id]

    def add_link(self, link):
        with self._lock:
            #neighbor = link.get_direct_neighbor_id()
            #self._link_neighbors[link] = neighbor
            #if neighbor is not None and neighbor != 0:
            #    self.routes[neighbor] = link
            if link not in self._link_neighbors:
                self._link_neighbors[link] = 0
            if link not in self.links:
                self.links.append(link)
        link.on_attached(self)

    def remove_link(self, link):
        with self._lock:
            if link in self._link_neighbors:
                self._link_neighbors.remove(link)
            if link in self.links:
                ix = self.links.index(link)
                self.links[ix] = None  #Don't change other linkId indices

    def register_neighbor(self, link, componentId):
        with self._lock:
            self._link_neighbors[link] = componentId
            self.routes[componentId] = link

    def is_central(self):
        return self.componentId == SSP_CENTRAL_ID

    def parent_link(self):
        with self._lock:
            if self.parent == 0:
                return None
            return self.routes[self.parent]

    def emit_event(self, evtType, evt):
        self.component.emit_event(evtType, evt)

    def error(self, evt):
        self.component.emit_event("linkErrEvt", evt)

    def is_link_online(self, to):
        "Checks if the link used to reach component <to> is online"
        to = to % SSP_COMPONENT_MODULUS
        if not to in self.routes:
            if self.is_central():
                return False  #We're central; we would know the link
            if self.componentId == 0:
                return False  #Not networked
            return True  #Route via central
        return self.routes[to].is_online()

    def make_ticket_with_callback(self, callback):
        "Returns a ticket. When reply/ack/nack messages are received with this ticket, <callback>(msg, timestamp) will be called on the serialconn thread"
        with self._lock:
            #Advance self._last_ticket to unused ticket number
            for i in range(250):
                if self._last_ticket >= 250:
                    self._last_ticket = 1
                else:
                    self._last_ticket += 1
                if self._last_ticket not in self.reply_callbacks:
                    break
            if self._last_ticket in self.reply_callbacks:
                raise Exception("All tickets are occupied")
            self.reply_callbacks[self._last_ticket] = callback
            return self._last_ticket

    def remove_ticket(self, ticket):
        "Frees a ticket to be reused by someone else."
        with self._lock:
            if not ticket in self.reply_callbacks:
                return
            del self.reply_callbacks[ticket]

    def subscribe(self, objectId, symbols_to_callbacks):
        """Make reports and events from remote <objectId> invoke local
           callbacks.  <symbols_to_callbacks> is map from symbol to
           set of callbacks to invoke.  Sends 'subscribe' if
           necessary.
        """
        #Map objectId -> (Map symbol -> callback)
        if len(symbols_to_callbacks) == 0:
            return
        if not objectId in self.obj_to_subscribers:
            self.obj_to_subscribers[objectId] = {}
        subscriptions = self.obj_to_subscribers[objectId]
        new_subscriptions = []
        for (symbol, callbacks) in symbols_to_callbacks.items():
            if not symbol in subscriptions:
                subscriptions[symbol] = set()
                new_subscriptions.append(symbol)
            subscriptions[symbol].update(callbacks)
        if new_subscriptions:
            # This component acts as subscriber to all remote
            # variables, to avoid multiple reports through the same
            # link.
            self.send(objectId, {'a': 'sub', 'sym': new_subscriptions,
                                  'from': self.componentId})

    def unsubscribe(self, objectId, symbols_to_callbacks):
        """Stop calling <callbacks> for <objectId> <symbols>, unsubscribing if
           no other local object listens.
        """
        #Map objectId -> (Map symbol -> callback)
        if not objectId in self.obj_to_subscribers:
            return  #No subscription exists
        subscriptions = self.obj_to_subscribers[objectId]
        unsubscribe_symbols = set()  # Symbols that will have no callbacks
        for (symbol, callbacks) in symbols_to_callbacks.items():
            if not symbol in subscriptions:
                return
            #Removes all elements in 'callbacks' from 'subscriptions'
            subscriptions[symbol].difference_update(callbacks)
            if len(subscriptions[symbol]) == 0:
                del subscriptions[symbol]
                unsubscribe_symbols.add(symbol)
        if unsubscribe_symbols:
            self.send(objectId, {'a': 'unsub', 'sym': list(unsubscribe_symbols),
                                 'from': self.componentId})

    def _get_callbacks(self, objectId, symbols):
        """Returns all callbacks registered as listeners to either one of
           <symbols> from <objectId>"""
        if objectId not in self.obj_to_subscribers:
            return set()
        subscriptions = self.obj_to_subscribers[objectId]
        #Only collect each callback once, even if it subscribes to
        #multiple included symbols
        callbacks = set()
        for symbol in symbols:
            callbacks.update(subscriptions.get(symbol, []))
        return callbacks

    def send(self, to, msg):
        "Send a message <msg> from this component to objectId <to>"
        assert to != SSP_LINK_ID  #Must be sent directly to the Link
        toComponent = to % SSP_COMPONENT_MODULUS
        assert toComponent != SSP_INVALID_COMPONENT_ID
        if toComponent in self.routes:
            self.routes[toComponent].send(to, msg)
            return
        #if to in self.objects:
        #    self.objects[to].handle_message(to, from_link, msg, timestamp)
        if toComponent == self.componentId:
            self.handle_message(self.componentId, self.componentId, msg, now())
            return
        if not self.is_central() and SSP_CENTRAL_ID in self.routes:
            self.routes[SSP_CENTRAL_ID].send(to, msg)
            return
        print('routes', self.routes.keys())
        self.error({'why': 'no route', 'to': to, 'msg': msg})
        if print_received_messages:
            print('Warning: Dropping outgoing message without route:', msg, 'to', to)

    #######################################

    def probe_for_neighbor(self, linkId):
        link = self.get_link_by_id(linkId)
        link.send(SSP_LINK_ID, self.get_our_cinfo(link))

    def get_our_cinfo(self, toLink):
        if toLink == self.parent_link():
            prio = self.base_priority
        else:
            prio = self.priority
        return {'a': 'cinfo', 'ver': constants.SSP_VERSION,
                'id': self.componentId,
                'parent': self.parent, 'magicByte': constants.SSP_MAGIC_BYTE,
                'prio': prio, 'serial': self.serial,
                'profiles': 0, 'vocabulary': 0, 'name': self.name, 'tk': 0}

    def forget_network(self):
        self.emit_event('traceEvt', 'Forget network')
        with self._lock:
            self.parent = 0
            for link in self._link_neighbors.keys():
                self._link_neighbors[link] = 0
        self.on_non_networked()

    def on_networked(self):
        #Could be buffered and handled afterwards, to merge possible
        #duplicate calls during startup
        self.component.on_networked()
        for internalId, internalObject in self._internal_objects.items():
            internalObject.on_networked()
        #TODO: Notify all neighbors except the networking source
        #TODO: Do auto-subscribes

    def on_non_networked(self):
        self.component.on_non_networked()
        for internalId, internalObject in self._internal_objects.items():
            internalObject.on_non_networked()

    #######################################

    def _call_msg_cb(self, callback, msg, timestamp):
        if not callable(callback):
            return False
        if (callback != print and
            'timestamp' in inspect.getfullargspec(callback).args):
            callback(msg, timestamp=timestamp)
        else:
            callback(msg)
        return True

    def handle_message(self, from_link, to, msg, timestamp):
        "First entry point for incoming messages over a link"
        #Called on any thread. Only execute basic actions on this thread.
        if print_received_messages:
            print('Received to=%s: %s' % (to, msg))
        #self.emit_event("gotMsgEvt", {'msg': msg, 'ts': timestamp})
        #to = msg.get('to', None)
        # ROUTING
        if to == SSP_INVALID_COMPONENT_ID:
            print("Warning: Dropping message %s without 'to'" % repr(msg))
            self.error({'why': 'invalid to', 'msg': msg})
            return
        #LOGGING
        cmd = msg['a']
        if cmd == 'rep':
            from .systemview import the_system  #Hack
            for (oid, valuemap) in msg['map'].items():
                proxy = the_system.get_proxy(oid, make=True)
                proxy.register_report(msg, timestamp)

        if (to == self.componentId and
            self.componentId != SSP_INVALID_COMPONENT_ID):
            if cmd == 'cinfo':
                with self._lock:
                    self._handle_net_cinfo(from_link, msg, timestamp)
                return
            if cmd == 'newid':
                with self._lock:
                    self._handle_net_newid(from_link, msg, timestamp)
                return
            if cmd in ['reply', 'ack', 'nack']:
                if 'tk' not in msg:
                    self.error({'why': 'no ticket', 'msg': msg})
                    return
                if msg['tk'] not in self.reply_callbacks:
                    self.error({'why': 'unknown ticket', 'msg': msg})
                    return
                try:
                    self.reply_callbacks[msg['tk']](msg, timestamp)
                except:
                    self.error({'why': 'exception in reply callback', 'msg': msg})
                return
            if cmd == 'getVarList':
                varlist = list(self.component._class._variables.keys())
                self.send(msg['from'], {'a': 'reply', 'tk': msg['tk'],
                                        'from': self.componentId, 'b': varlist})
                return
            #Messages that are passed through to component:
            if cmd == 'rep':
                callbacks = set()  # Collect all callbacks, to avoid multiple calls
                for (from_oid, valuemap) in msg['map'].items():
                    symbols = valuemap.keys()
                    callbacks.update(self._get_callbacks(from_oid, symbols))
                if callbacks:
                    for callback in callbacks:
                        self._call_msg_cb(callback, msg, timestamp)
                else:
                    self._call_msg_cb(self._default_callback, msg, timestamp)
            if self.component is not None:
                self.component.handle_message(msg, timestamp)
            else:
                #Can't emit event -- no component to emit it from!
                #print("Warning: No component for the router, dropping message", msg)
                pass
            return

        #if to in self.objects:
        #    self.objects[to].handle_message(msg, timestamp)
        #    return
        if to == SSP_LINK_ID or to == 'null':  #HACK: LINK_ID 255 is interpreted as NULL
            cmd = msg['a']
            if cmd in ['reply', 'ack', 'nack']:
                if 'tk' not in msg:
                    self.error({'why': 'no ticket', 'msg': msg})
                    return
                if msg['tk'] not in self.reply_callbacks:
                    self.error({'why': 'unknown ticket', 'msg': msg})
                    return
                try:
                    self.reply_callbacks[msg['tk']](msg, timestamp)
                except:
                    self.error({'why': 'exception in reply callback', 'msg': msg})
                return
            if cmd == 'cinfo':
                with self._lock:
                    self._handle_link_cinfo(from_link, msg, timestamp)
                return
            if cmd == 'newid':
                with self._lock:
                    self._handle_link_newid(from_link, msg, timestamp)
                return
            if cmd == 'rep':
                callbacks = set()
                for (from_oid, valuemap) in msg['map'].items():
                    symbols = valuemap.keys()
                    callbacks.update(self._get_callbacks(from_oid, symbols))
                for callback in callbacks:
                    callback(msg)
            if from_link in self._link_proxies:
                self._link_proxies[from_link].handle_message(msg, timestamp)
            #if self.component is not None:
            #    self.component.handle_message(msg, timestamp)
            else:
                #Can't emit event -- no component to emit it from!
                #print("Warning: No component for the router, dropping link message", msg)
                pass
            return
        componentId = to % SSP_COMPONENT_MODULUS
        if componentId in self.routes:
            to_link = self.routes[componentId]
            if to_link == from_link:
                text = "Dropping msg that would be sent back on same link"
                self.error({'fromLink': from_link, 'msg': msg, 'text': text})
                return
            self.emit_event("routeMsgEvt",
                            {'toLink': self.links.index(to_link), 'msg': msg})
            to_link.send(to, msg)  #Forward the message
            return

        parent_link = self.parent_link()
        if parent_link:
            #Route any unknown recipients towards the central (this
            #implies we're not central ourselves)
            if parent_link == from_link:
                text = "Dropping msg with unknown recipient, where msg would be sent back on same link"
                self.error({'link': from_link, 'to': to, 'msg': msg, 'text': text})
                return
            self.emit_event("routeMsgEvt", {'toLink': self.links.index(parent_link), 'why': 'default', 'msg': msg})
            parent_link.send(to, msg)
            return
        self.error({'text': 'Dropping msg due to no route',
                    'to': to, 'msg': msg})
        #print "Warning: No route for message", msg


    #######################################

    #Call with self._lock already acquired
    def _handle_link_cinfo(self, from_link, msg, timestamp):
        #ComponentInfo:
        #Struct{serial:Uint32, id:Uint8, parent:Uint8, prio:Uint8, profiles:Uint8, vocabulary:Uint8, name:String}

        assert msg['a'] == 'cinfo'
        if msg['ver'] != constants.SSP_VERSION:
            self.error({'msg': msg, 'text': "cinfo with wrong VERSION"})
            return
        if msg['magicByte'] != constants.SSP_MAGIC_BYTE:
            self.error({'msg': msg, 'text': "cinfo with wrong MAGIC_BYTE"})
            return
        #tk:Uint8, componentInfo:ComponentInfo

        is_from_parent_link = (from_link == self.parent_link())
        if is_from_parent_link:
            self.forget_network()
            if self.base_priority > 0:
                self.act_as_central()

        if msg['prio'] == self.priority:
            if self.serial != 0 and msg['serial'] == self.serial:
                #This is ourselves!
                print('direct loop')
                self.emit_event('linkEvt', 'direct loop detected')
                return
            if msg['serial'] < self.serial:
                #The other component has lower serial so it takes priority
                self.priority -= 1

        if msg['prio'] > self.priority:
            #We should belong to the new network
            self.forget_network()
            self.routes[msg['id']] = from_link
            #Don't allow anyone with lower authority to assign us an
            #ID (as we wait for the sender to send us a NewId).
            self.priority = msg['prio'] - 1
            self.component.mark_as_updated('priority')
            self.emit_event('linkEvt',
                            'Will be child of %d' % msg['id'])
            from_link.send(SSP_LINK_ID, self.get_our_cinfo(from_link))
            #self.on_networked()
            return

        #The new component has lower prio than us.
        if self.is_central():
            self._central.handle_link_cinfo(from_link, msg, timestamp)
            return

        parent_link = self.parent_link()
        if parent_link:
            #Ask central for a new id, by a network cinfo
            netMsg = msg.copy()
            netMsg['tk'] = self.links.index(parent_link)
            netMsg['from'] = self.componentId
            parent_link.send(SSP_CENTRAL_ID, netMsg)
            return

        #We can't be central. The other component can't be
        #central. We don't have a parent to ask for new id. Drop
        #the message until we're networked again.
        self.error({'msg': msg, 'text': "Ignoring cinfo where none is networked"})
        return

    #Call with self._lock already acquired
    def _handle_link_newid(self, from_link, msg, timestamp):
        parent = msg['tk']
        if parent in [SSP_INVALID_COMPONENT_ID, SSP_LINK_ID] or \
           parent >= SSP_COMPONENT_MODULUS:
            self.error({'text': 'Invalid from', 'msg': msg})

        is_from_parent_link = (from_link == self.parent_link())
        if is_from_parent_link:
            # The component parent (link) gives this component a new
            # id. Either this component was not networked, in case
            # forgot_network() doesn't hurt, or it's the same parent
            # as before, in case they probably forgot that we're
            # already networked so any children need to be networked
            # again, or it's a new component at the parent link, in
            # which case networking needs to restart.
            self.forget_network()
            #if self.base_priority > 0:
            #    self.act_as_central()

        if msg['prio'] < self.priority:
            self.emit_event('linkEvt', {'text': 'Ignoring lower prio',
                                        'msg': msg, 'prio': self.priority})
            return

        if self._central:
            self._central = None
            self.emit_event('traceEvt', 'stop acting as central')

        # Forget all existing routes. This means all networking except
        # the (new) parent has to be re-done.
        self._link_neighbors = {}
        self.routes = {}

        self.componentId = msg['id']
        self.priority = msg['prio']
        if 'name' in msg and len(msg['name']) > 0:
            self.name = msg['name']
            self.component.mark_as_updated('name')
        self.parent = parent
        self._link_neighbors[from_link] = parent
        self.routes[parent] = from_link
        if parent != SSP_CENTRAL_ID:
            self.routes[SSP_CENTRAL_ID] = from_link
        self.component.mark_as_updated('id')
        self.component.mark_as_updated('priority')
        self.component.on_networked()

    #######################################

    #Call with self._lock already acquired
    def _handle_net_cinfo(self, from_link, msg, timestamp):
        if msg['ver'] != constants.SSP_VERSION:
            self.error({'msg': msg, 'text': "cinfo with wrong VERSION"})
            return
        if msg['magicByte'] != constants.SSP_MAGIC_BYTE:
            self.error({'msg': msg, 'text': "cinfo with wrong MAGIC_BYTE"})
            return
        if not self.is_central():
            #Why would anyone send cinfo to someone else than central?
            self.error({'msg': msg, 'text': "ignoring cinfo as we're not central"})
            return
        #We are central and received a net cinfo.

        self._central.handle_net_cinfo(from_link, msg, timestamp)

    #Call with self._lock already acquired
    def _handle_net_newid(self, from_link, msg, timestamp):
        #The only reason to receive a net newid is when we asked for a
        #new id on behalf of a direct neighbor
        try:
            to_link = self.links[msg['tk']]
        except:
            self.error({'msg': msg, 'text': "invalid net newid"})
            return
        _id = msg['id']
        link_msg = {'a': 'newid', 'tk': self.componentId, 'id': _id,
                     'prio': msg['prio'], 'name': msg['name']}
        self.emit_event('linkEvt', {'text': 'converting net newid to link newid',
                                    'msg': msg})
        to_link.send(SSP_LINK_ID, link_msg)
        self.register_neighbor(to_link, _id)

    def make_link_proxy(self, link : 'Link'):
        if not link in self._link_proxies:
            from . import remoteobject
            self._link_proxies[link] = remoteobject.LinkProxy(link, self)
        return self._link_proxies[link]


    #######################################
    # Central
    # (only for the component that is central)

    def central(self) -> "Central":
        return self._central

    def act_as_central(self):
        assert self._central is None
        from . import network
        self._central = network.Central(self)
        self._central.act_as_central()
