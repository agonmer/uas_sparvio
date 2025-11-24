# sslink.py: Sparvio link layer implemented for Python
#
# A "link" is a connection to another SSP device (when connected),
# over which SSP messages can be exchanged.

import time
import traceback

from sspt import parse
from sspt import bytebuffer
from . import serialdaemon
from . import messages

SSP_INVALID_COMPONENT_ID = 0
SSP_CENTRAL_ID = 1
SSP_LINK_ID = 255  #Change to 0 ?
SSP_COMPONENT_MODULUS = 128
SSP_BIGGEST_REGULAR_COMPONENT_ID = SSP_COMPONENT_MODULUS - 4

debug_write = False

def now():
    #Can be replaced, to do simulation
    return time.time()

from abc import ABC, abstractmethod

class Link(ABC):
    "A link allows a component to send and receive messages to a direct neighbor component (if connected). A link object is only associated with *one* component."
    def __init__(self, componentbase = None, link_id = None):
        #The local component to receive messages received over this link
        #It can be set later on with on_attached()
        self.componentbase = componentbase
        self.linkId = link_id
        self.probe_automatically = True
    def is_online(self):
        return True  #Default -- override
    @abstractmethod
    def send(self, to, msg):
        "Asynchronously(?) send a message over this link"
        raise Exception("Override!")
    def handle_message(self, to, msg, timestamp):
        self.componentbase.handle_message(self, to, msg, timestamp)

    #def get_direct_neighbor_id(self):
    #    return 0  #Override if the neighbor id is known
    def on_attached(self, componentbase):
        self.componentbase = componentbase  #Override

    def emit_error(self, arg):
        self.emit_event('linkErrEvt', arg)

    def emit_event(self, eventType, arg):
        if self.this_component is None:
            print('Error: link emit_event but no component')
            return
        if not isinstance(arg, dict):
            arg = {'text': arg}
        arg['link'] = self.linkId
        self.this_component.emit_event(eventType, arg)


######################################################################

class LocalLink(Link):
    "Links to another LocalComponent (running in the same Python environment)."
    # No Protocol class is needed, since message can be shared in
    # their pyObject or native Python form.
    def __init__(self, componentbase, link_id = None):
        super(LocalLink, self).__init__(componentbase, link_id=link_id)
        self.other_link = None  #LocalLink. Fill in externally
    def send(self, to, msg):
        if self.other_link is None:
            self.emit_error("LocalLink other link is None")
            return
        self.other_link.handle_message(to, msg, now())
    def get_neighbor(self):
        if not self.other_link:
            return None
        otherbase = self.other_link.componentbase
        if not otherbase:
            return None
        return otherbase.componentId

    def on_attached(self, componentbase):
        self.componentbase = componentbase
        if not self.componentbase.componentId:
            return
        if self.other_link:
            otherbase = self.other_link.componentbase
            if otherbase and otherbase.componentId:
                otherId = otherbase.componentId
                if otherId:
                    #Now connected on both ends to known ids
                    self.componentbase.register_neighbor(self, otherId)
                    otherbase.register_neighbor(self.other_link,
                                                self.componentbase.componentId)
    #def get_direct_neighbor_id(self):
    #    if self.other_link and self.other_link.componentbase:
    #        return self.other_link.componentbase.componentId
    #    return 0

def link_local_components(component1, component2, prefix="local"):
    link1 = LocalLink(component1._base, prefix + "_" + component2.name)
    link2 = LocalLink(component2._base, prefix + "_" + component1.name)
    link1.other_link = link2
    link2.other_link = link1
    component1.add_link(link1)
    component2.add_link(link2)

def local_link(component, prefix="local"):
    link1 = LocalLink(component._base, prefix)
    link2 = LocalLink(None, prefix + "_" + component.name)
    link1.other_link = link2
    link2.other_link = link1
    component.add_link(link1)
    return link2


######################################################################

class SerialLink(Link):
    "A link over a SerialDaemon serial port"
    def __init__(self, daemon, protocol_class, componentbase=None):
        super(SerialLink, self).__init__(componentbase)
        self._daemon = daemon
        self.protocol = protocol_class(self.handle_message)
        self._daemon.protocol = self.protocol # serialdaemon.LineReader(self.on_line)

    def is_online(self):
        return self._daemon.is_online()

    def send(self, to, msg):
        encoded = self.protocol.encode(to, msg)
        if debug_write:
            print('Serial writing %s to %d as %s' % (str(msg), to, repr(encoded)))
        self._daemon.write(encoded)

    def handle_message(self, to, msg, timestamp=None):
        if timestamp is None:
            timestamp = now()
        if self.componentbase is None:
            print('Warning: No componentbase')
            return
        self.componentbase.handle_message(self, to, msg, timestamp)
