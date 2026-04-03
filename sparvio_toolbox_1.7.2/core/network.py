# network.py: Build and maintain the network of components on top of
# the link level

import re

from reactive.observable import Scheduler
from reactive.eventthread import TimerObservable
from .ssplink import SSP_INVALID_COMPONENT_ID, SSP_LINK_ID, SSP_CENTRAL_ID, SSP_COMPONENT_MODULUS, SSP_BIGGEST_REGULAR_COMPONENT_ID
from . import componentbase

def is_valid_component_id(_id):
    return (_id != SSP_INVALID_COMPONENT_ID and
            _id != SSP_LINK_ID and
            _id > 0 and
            _id <= SSP_BIGGEST_REGULAR_COMPONENT_ID)

class Central(object):
    "Mixin used by the ComponentBase of the LocalComponent that is central (if any)"
    def __init__(self, base):
        self._base = base
        #Elements are each a dict with keys name, serial, id
        #self.all_components = []
        self.init_all_local()
    def init_all_local(self):
        "Add all local components to this local central"
        self.all_components = []
        for base in componentbase.all_componentbases:
            self.all_components.append({'id': base.componentId,
                                        'name': base.name,
                                        'serial': base.serial})
        #print '{} init_all_local() {}'.format(self._base.name,
        #                                      repr(self.get_component_ids()))
        self._base.component.mark_as_updated('components')
    def get_component_ids(self):
        ids = []
        for info in self.all_components:
            if info['id']:
                ids.append(info['id'])
        #print 'get_component_ids', ids
        return ids
    def get_component_names(self):
        "Returns map from componentId to name (string), complying with SSP componentNames"
        return {info['id']: info['name'] for info in self.all_components
                if 'id' in info}

    def lookupId(self, string):
        string = str(string)
        for component in self.all_components:
            if string == component['name'] or string == component['serial'] or \
               string == str(component['id']):
                return component['id']
        return SSP_INVALID_COMPONENT_ID
    def key_to_info(self, key, value):
        for info in self.all_components:
            if info[key] == value:
                return info
        return None
    def id_to_info(self, _id):
        return self.key_to_info('id', _id)
    def name_to_info(self, name):
        return self.key_to_info('name', name)
    def serial_to_info(self, serial):
        return self.key_to_info('serial', serial)
    def is_component_registered(self, _id):
        return self.id_to_info(_id) != None
    def error(self, evt):
        self._base.component.emit_event("linkErrEvt", evt)
    def emit_event(self, evtType, evt):
        self._base.emit_event(evtType, evt)

    def _find_free_id(self):
        free_ids = list(range(1, SSP_BIGGEST_REGULAR_COMPONENT_ID))
        for info in self.all_components:
            if info['id'] in free_ids:
                free_ids.remove(info['id'])
        if free_ids == []:
            #Could try again, reusing previously used ("reserved") id
            return None
        return free_ids[0]

    def _name_exists(self, name):
        return self.name_to_info(name) is not None

    def _do_register(self, _id, name, serial):
        #If duplicate name, find free alternative by adding _n for
        #some value of <n>, or changing to another <n> if already on
        #this form:
        if self._name_exists(name):
            old_name = name
            match = re.match("(.*_)[0-9]*", name)
            if match:
                base = match.group(1)
            else:
                base = name + '_'
            for ix in range(1, 200):
                name = base + str(ix)
                if not self._name_exists(name):
                    break  #Found free name
            self.emit_event('traceEvt', 'Change the name %s to %s' % \
                            (old_name, name))
        self.all_components.append({'id': _id, 'name': name, 'serial': serial})

    def register(self, cinfo):
        """Register the component with <cinfo>, reserving an ID for
           it. Returns id.
        """
        _id = None
        suggested_id = cinfo['id']
        # Can we use the suggested ID?
        if is_valid_component_id(suggested_id):
            prev_info = self.id_to_info(suggested_id)
            if prev_info is None:
                #Unknown id
                pass
            elif prev_info['serial'] == cinfo['serial']:
                #We already registered this component
                return suggested_id
            else:
                #Already registered to someone else
                suggested_id = None

        # Do we know of the serial number?
        if cinfo['serial'] != 0:
            prev_info = self.serial_to_info(cinfo['serial'])
            if prev_info:
                # The component is already known with another id
                return prev_info['id']

        if not suggested_id:
            suggested_id = self._find_free_id()
        self._do_register(suggested_id, cinfo['name'], cinfo['serial'])
        return suggested_id

    #####################
    ## Take action

    def act_as_central(self):
        #self.emit_event('traceEvt', 'act as central')
        with self._base._lock:
            assert self._base.base_priority > 0
            self._base.priority = self._base.base_priority
            self._base.componentId = SSP_CENTRAL_ID
        self._base.parent = 0
        self._base.component.mark_as_updated('parent')
        self._base.component.mark_as_updated('priority')
        self._base.component.mark_as_updated('componentId')
        self._base.on_networked()  #We're the single node in the net...

    #Call with self._lock already acquired
    def handle_link_cinfo(self, from_link, msg, timestamp):
        #We're central and someone in the net (possibly a direct
        #neighbor) requests an id
        self._base.priority = min(255, self._base.priority + 1)
        _id = self.register(msg)
        name = self.id_to_info(_id)['name']
        if name == msg['name']:
            name = ''  #No need to return the same name
        newid_msg = {'a': 'newid', 'id': _id,
                     'tk': self._base.componentId,  #parent, = central
                     'prio': self._base.priority, 'name': name}
        self._base.routes[_id] = from_link
        self._base.register_neighbor(from_link, _id)
        self._base.component.mark_as_updated('components')
        from_link.send(SSP_LINK_ID, newid_msg)

    def handle_net_cinfo(self, from_link, msg, timestamp):
        if msg['prio'] > self._base.priority:
            assert False #TODO

        self._base.priority = min(255, self._base.priority + 1)
        _id = self.register(msg)
        name = self.id_to_info(_id)['name']
        if name == msg['name']:
            name = ''  #No need to return the same name
        newid_msg = {'a': 'newid', 'tk': msg['tk'], 'id': _id,
                     'prio': self._base.priority, 'name': name}
        self._base.routes[_id] = from_link
        self._base.component.mark_as_updated('components')
        from_link.send(msg['id'], newid_msg)


######################################################################
# Networker

#Tries to network a component via its available links
#Associated with a LocalComponent -- merge the two?
class Networker:
    def __init__(self, base : componentbase.ComponentBase,
                 scheduler : Scheduler):
        "<base> is the ComponentBase to network"
        self.base = base
        #Check at startup, then every 5 seconds
        self._timer = TimerObservable(observer=(scheduler, self.loop))
        self._timer.start(1)  #Wait for links to connect first
        #if self.base.base_priority > 0:
        #    self.act_as_central()

    def loop(self):
        "Run every 5 seconds to look for new neighbors to network with"
        if self.base.componentId is None:
            ourId = 0
        else:
            assert self.base.componentId < SSP_COMPONENT_MODULUS
            ourId = self.base.componentId
        for (link, neighbor_id) in self.base._link_neighbors.items():
            if not link.probe_automatically:
                continue
            if neighbor_id != 0:
                #TODO: Could implement timeout if no traffic (link.timestamp_of_last_received_msg())
                continue
            #Send link-level CInfo to announce ourselves
            link.send(SSP_LINK_ID, self.base.get_our_cinfo(link))
        self._timer.start(5)

    def emit_event(self, type, arg):
        self.base.emit_event(type, arg)
