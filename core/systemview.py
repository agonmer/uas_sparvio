# systemview.py: Builds Python objects that reflect the real-time
# topology and functionality available in a Sparvio system, using a
# local component to interface the system.
#
# Local components use their original LocalObject object, remote
# objects are proxied with 'Remote...' classes to access variables
# and functions seemingly as native Python data.

#import traceback
import re
import time

from . import localobject
from .localobject import LocalComponent, SparvioInterface
from reactive import eventthread
from .ssplink import SSP_INVALID_COMPONENT_ID, SSP_LINK_ID, SSP_CENTRAL_ID
from . import componentbase
from . import remoteobject
from sspt import pyObjects
from sspt.ontology import global_ontology

######################################################################
## Map between a SSP serial connection and system view

class UnknownFacade(object):
    "An objectId used temporarily until we know if it's local or remote"
    pass

the_system = None

class SystemViewComponent(LocalComponent, SparvioInterface):
    "A component that observes the system and creates a local ComponentProxy for every other component"
    def __init__(self, name="view", serial=None, priority=45):
        SparvioInterface.__init__(self)
        LocalComponent.__init__(self, name=name,
                                link_to_central=False, serial=serial)
        #TODO: These variables are all required for all components. Move to common interface?
        self._base.base_priority = priority
        self._variables = \
            {'id': pyObjects.uint8_type,
             'priority': pyObjects.uint8_type,
             'name': pyObjects.string_type,
             'vars': global_ontology.label_to_registry_entry('SymbolList'),
             'funcs': global_ontology.label_to_registry_entry('SymbolList'),
             'events': global_ontology.label_to_registry_entry('SymbolList'),
             'funcSigs': global_ontology.label_to_registry_entry('FuncSigList'),
             # Required for all central components:
             'componentNames': 'TypedMap(Uint8, String)',
             'components': 'TypedList(Uint8)'}
        #Just as a test, expose 'rawTx':
        #self._functions = {'rawTx': (pyObjects.string_type, pyObjects.null) }

        self.proxies = {}  #Map from id to ComponentProxy

        global the_system
        if the_system is not None:
            print("Warning: Redefining the 'the_system' object")
        the_system = self
        self._base.act_as_central()

    def __getattr__(self, attr):
        if attr == 'componentNames':
            if self._base.is_central():
                return self._base.central().get_component_names()
            else:
                return {}
        if attr == 'components':
            if self._base.is_central():
                return self._base.central().get_component_ids()
            else:
                return []
        return LocalComponent.__getattr__(self, attr)

    def _clear_systemview(self):
        self.proxies = {}

        #self._thread
    def on_networked(self):
        super(SystemViewComponent, self).on_networked()
        #print('SystemViewComponent on_networked(id=%d)' % self.id.get())
        self._clear_systemview()
        #Might subscribe to the same component... is that ok?
        proxy = self.get_proxy(SSP_CENTRAL_ID)
        proxy.add_subscriber(['components'], self.on_updated_components_msg,
                             initial_get=True)

    def on_non_networked(self):
        print('SystemViewComponent on_non_networked()')
        self._clear_systemview()
        pass  #TODO

    def get_component_name(self, _id):
        localbase = componentbase.get_by_componentId(_id)
        if localbase:  # Local objects
            return localbase.name
        if _id in self.proxies: # Remote objects
            return self.proxies[_id].name
        return None

    # def name_to_proxy(self, pattern, timeout=0):
    #     start = time.time()
    #     while True:
    #         for proxy in self.proxies.values():
    #             if proxy.name is None:
    #                 continue
    #             if re.match(pattern, proxy.name):
    #                 return proxy
    #         # No match yet
    #         if time.time() - start >= timeout:
    #             return None  # Raise exception instead?
    #         time.sleep(0.1)

    def get_proxy(self, _id, make=True, caching=False):
        "Returns a ComponentProxy. Call from any thread."
        localbase = componentbase.get_by_componentId(_id)
        if localbase:
            return localbase.component._proxy
        if caching:
            assert False  #Remove the 'caching' parameter

        if _id not in self.proxies:
            if make:
                self.proxies[_id] = remoteobject.ComponentProxy(_id, self._base)
            else:
                return None
        return self.proxies[_id]

    def get_central_proxy(self):
        return self.get_proxy(SSP_CENTRAL_ID, make=True)

    def query_for_components(self):
        if self.base.componentId == 0:
            print("Not networked")
            return
        central = self.get_proxy(SSP_CENTRAL_ID)
        components = central.get('components')
        self.on_updated_components(components)

    def on_updated_components_msg(self, msg, timestamp=None):
        if 'components' in msg['map'].get(SSP_CENTRAL_ID,{}):
            self.on_updated_components(msg['map'][SSP_CENTRAL_ID]['components'])

    #@ssp_fn('sendOnLink', [uint8_type, id_type, msgAddr_type], null)
    def sendOnLink(self, linkId, to, msg):
        "A SSP function that sends to a particular link"
        link = self._base.get_link_by_id(linkId)
        link.send(to, msg)

    def on_updated_components(self, components):
        #print('SystemViewComponent on_updated_components', components)
        for componentId in components:
            if componentId == self._base.componentId:
                continue
            self.get_proxy(componentId)  #Create missing proxy objects
        for componentId in self.proxies.keys():
            if componentId in components:
                if not self.proxies[componentId]._known_by_central:
                    self.proxies[componentId]._known_by_central = True
                    #print('Goes online:', componentId)
            else:
                if self.proxies[componentId]._known_by_central:
                    self.proxies[componentId]._known_by_central = False
                    print('Goes offline:', componentId)

    #@ssp_function(uint8_type, null)
    def linkProbe(self, linkId):
        "Try to connect once to any new neighbor at <linkId>"
        self._base.probe_for_neighbor(linkId)

    #self._functions = {'rawTx': (pyObjects.string_type, pyObjects.null) }
    @localobject.ssp_function('String', 'Null')
    def rawTx(self, string):
        print('rawTx: ' + repr(string) + " (type %s)" % type(string))

    def subDef(self, oid : int):
        # Only added to comply with SSP object (sensors)
        pass


##############################
##

class System(object):
    "All components in the system will show up as members, under their name. Components may disappear and reappear without warning depending on physical connection"
    #Local components will use their SparvioObject object, remote
    #components are represented by an instance of instance of
    #RemoteObjectClassFactory.

    #From Python 3.3, this class could be replaced by a types.SimpleNamespace()
    pass

#TODO: Local objects also need to be wrapped, to give synchronous access?
class DynamicViewerComponent(SystemViewComponent):
    "Dynamically exposes all available objects in the system for synchronous access. Remote objects have their variables and functions represented as Python objects that forward any access to the remote object (no caching)."
    def __init__(self, name="visualizer", serial=None, priority=45):
        super(DynamicViewerComponent, self).__init__(name=name, serial=serial,
                                                     priority=priority)

        #hooks: When a particular component name is added, we will
        #subscribe to certain symbols.
        #{mapping from regex for component ASCII name to {mapping from
        #symbol to set of callbacks}} to auto-subscribe:
        self.hooks = {}

        self._system = System()

    def _clear_system(self):
        self._system.__dict__ = {}

    @eventthread.run_in_thread
    def on_networked(self):
        self._clear_system()
        super(DynamicViewerComponent, self).on_networked()

    @eventthread.run_in_thread
    def on_non_networked(self):
        self._clear_system()
        super(DynamicViewerComponent, self).on_non_networked()
        pass  #TODO

    def get_object(self, _id):
        if _id == self.id.get():
            return self
        #TODO: Check for local objects
        proxy = self.get_proxy(_id, make=False)
        if proxy is None:
            return None
        return proxy.x

    @eventthread.run_in_thread
    def on_updated_components(self, components):
        super(DynamicViewerComponent, self).on_updated_components(components)
        #print('DynamicViewerComponent on_updated_components ' + repr(components))
        #Remove missing components
        for (componentId, proxy) in self.proxies.items():
            if proxy.x is None:
                continue
            if componentId in components:
                continue
            #Remove missing components
            self.emit_event('debug', {'text': 'ComponentX goes offline',
                                      'name': proxy.x.name})
            try:
                del self._system.__dict__[proxy.x.name]
            except:
                pass
        #Add new components
        for componentId in components:
            base = componentbase.get_by_componentId(componentId)
            if base:
                #Local components
                self._system.__dict__[base.name] = base.component
                self._add_local_component(base.component._proxy)
                continue
            # Remote components
            if not self.proxies[componentId].x:
                try:
                    self._add_remote_component(componentId)
                except Exception as ex:
                    import traceback
                    traceback.print_exc()
                    print('systemview.py Exception', ex)
            else:
                pass  #TODO: Check systemId when supported

    def matches(self, pattern):
        "Returns a list of the dynamic components whose name matches <pattern>"
        result = []
        for xobj_name in self._system.__dict__.keys():
            if re.match(pattern, xobj_name):
                result.append(self._system.__dict__[xobj_name])
        return result

    def get_by_name(self, pattern, timeout=0):
        """Returns a single dynamic component that matches <pattern>.
           If <timeout> > 0, the call will block for this amount of time waiting
           for a matching component to come online."""
        start = time.time()
        while True:
            matches = self.matches(pattern)
            if len(matches) > 0:
                return matches[0]  # Just return one of the matches
            # No match yet
            if time.time() - start >= timeout:
                return None  # Raise exception instead?
            time.sleep(0.1)

    #def get_by_id(self, _id):
    #    for component in self._system.__dict__:
    #        if component.id == _id:
    #            return component
    #    return None

    def add_hook(self, name_pattern, vars, update_callback=None):
        """When a component with name matching 'name_pattern' is added in the
           system, subscribe to 'var' (ASCII symbol or list of ASCII
           symbols), with update_callback being called when the value
           changes
        """
        if type(vars) is str:
            vars = [vars]
        if name_pattern not in self.hooks:
            self.hooks[name_pattern] = {}
        for var in vars:
            if var not in self.hooks[name_pattern]:
                self.hooks[name_pattern][var] = set()
            self.hooks[name_pattern][var].add(update_callback)

        new_hooks = {_var: [update_callback] for _var in vars}
        #Subscribe to already known components:
        for xobj in self.matches(name_pattern):
            print('HOOKS already from start', name_pattern)
            xobj._proxy.add_subscribers(new_hooks)

    def add_link_component(self, link):
        "Returns X component for a neighbor addressed at link level"
        proxy = self._base.make_link_proxy(link)
        normalized_name = 'link'  #HACK: Only support one link component for now
        classname = normalized_name + 'Class'
        _class = remoteobject.RemoteObjectClassFactory(classname, proxy)
        _obj = _class(normalized_name)  #Create class instance
        proxy.x = _obj
        self._system.__dict__[normalized_name] = _obj
        self.emit_event('traceEvt', 'add_link_component %s' % (normalized_name))
        return _obj

    def _add_remote_component(self, _id):
        "Returns proxy with X component"
        proxy = self.get_proxy(_id, make=True)
        if proxy.x:
            return proxy
        #TODO: If we're central, we already know the name
        name = proxy.get('name')
        proxy.name = name
        if name is None:
            print('Error: Got no name for id %d' % _id)
            return proxy
        if not isinstance(name, str):
            print("Error: Got unexpected 'name' type of %s" % repr(name))
            return proxy
        normalized_name = name.replace('#', '_')
        normalized_name = normalized_name.replace(' ', '_')
        classname = normalized_name + 'Class'
        #TODO: When Sparvio classes are added, reuse the class object
        #Create the class:
        _class = remoteobject.RemoteObjectClassFactory(classname, proxy)
        _obj = _class(normalized_name)  #Create class instance
        proxy.x = _obj
        self._system.__dict__[normalized_name] = _obj
        #Collect all subscriptions that match the name
        hooks = {} #Mapping from symbol to set of callbacks
        for (pattern, new_hooks) in self.hooks.items():
            if not (re.match(pattern, name) or
                    re.match(pattern, normalized_name)):
                continue
            for (sym, callback_set) in new_hooks.items():
                hooks[sym] = hooks.get(sym, set()).update(callback_set)
        if hooks:
            print('Auto-subscribing to %s %s' % (name, str(sym)))
            proxy.add_subscribers(hooks)
        self.emit_event('traceEvt', 'add_remote_component %d %s' % (_id, name))
        return proxy

    def _add_local_component(self, local_proxy):
        "Just checks the hooks"
        name = local_proxy.get('name')
        normalized_name = name.replace('#', '_')
        normalized_name = normalized_name.replace(' ', '_')
        hooks = {} #Mapping from callback to set of symbols
        #Not efficient -- changing the hooks representation to map
        #callback -> symbols would improve
        for (pattern, new_hooks) in self.hooks.items():
            if not (re.match(pattern, name) or
                    re.match(pattern, normalized_name)):
                continue
            for (sym, callback_set) in new_hooks.items():
                for callback in callback_set:
                    local_proxy.add_subscriber([sym], callback,
                                               initial_get=False)

    #def _subscribe(self, _id, vars_to_cbs):
    #    "vars_to_cbs is mapping from ASCII symbol to list of callbacks"
    #    #"var is ASCII symbol or list of ASCII symbols"
    #    self.get_proxy(_id).add_subscribers(vars_to_cbs)

    def _component_goes_offline(self, _id):
        proxy = self.get_proxy(_id, make=False)
        if not proxy or not proxy.x:
            print('Component %s without X goes offline' % proxy.x.name)
            return
        print('Component %s goes offline' % proxy.x.name)
        try:
            del self._system.__dict__[proxy.x.name]
        except:
            pass
