#! env python3

import asyncio
import weakref
import sys
import json
from typing import List, Optional, Callable

import aiohttp
from aiohttp import WSCloseCode
from aiohttp import web
import jinja2
import aiohttp_jinja2

from reactive import eventthread
from sspt.pyObjects import *
from .localobject import LocalInternalObject, SparvioInterface

# HACK to send data to Cesium 3D visualization
from reactive.observable import ListState
from core.gis.log import ValuesLog
# All entries must have 'lat', 'lon', 'alt' and valid timestamp
# Optional: 'wspd', 'wdir', 'co2', 'rh', 'temp', 'ch4'
cesium_measurements = ValuesLog()
# The path of the drone
# 'lat', 'lon', 'alt', 'heading', and valid timestamp
#cesium_track = ValuesLog()

verbose = False

# Communication with browser client Javascript code is setup by:
# 1) Web server is started
# 2) The client requests a HTML page with the JS code
# 3) The client runs the JS code, which starts a websocket session
# 4) The client JS send a request through the websocket to subscribe
#    to dynamic data
# 5) The client receives dynamic data via websocket and updates the GUI

exclude_vars = ['vars', 'funcSigs']

# if ('vars' in msg['map']) {
#   for (const _var of msg['map']['vars']) {
#     var row = table.insertRow(table.rows.length);
#     var cell = row.insertCell(0);
#     cell.innerHTML = _var;
#     cell = row.insertCell(1);
#     cell.innerHTML = "";
#   }
# }

object_onmessage = """
  if (msg['from'] == {{param_id}}) {
    var table = document.getElementById("{{div_id|safe}}");
    for (const _var in msg['map']) {
      if (msg['map'].hasOwnProperty(_var) && !{{exclude_vars}}.includes(_var)) {
        var div = document.getElementById("{{div_id+'_'}}" + _var);
        div.innerText = JSON.stringify(msg['map'][_var]);
      }
    }
  }
"""
object_onmessage_template = jinja2.Environment(loader=jinja2.BaseLoader).from_string(object_onmessage)

system_functions_template = jinja2.Environment(loader=jinja2.BaseLoader).from_string("""
  //The keys are id (integer). The values are name (string)
  var componentNames = {};
  function updateList() {
    html = "";
    for (const _id in componentNames) {
      if (!componentNames.hasOwnProperty(_id))
        continue;
      var name = componentNames[_id];
      html += `<tr><td>${_id}</td> <td><a href="/obj?id=${_id}">${name}</a></td></tr>\n`;
    }
    var tableBody = document.getElementById("{{div_id|safe}}");
    tableBody.innerHTML = html;
  }
""")

system_onmessage = """
  if (msg['from'] == 1 && 'componentNames' in msg['map']) {
    componentNames = msg['map']['componentNames'];
    updateList();
  }
"""
system_onmessage_template = jinja2.Environment(loader=jinja2.BaseLoader).from_string(system_onmessage)

def simple_system_widget(page, query):
    div_id = 'value'
    tableHeaderRow = "<thead><tr><td><b>ID</b></td><td><b>Name</b></td></tr></thead>"
    page['title'] = "Sparvio live view"
    page['body'] += "<div>Sparvio system components:</div> <table border=1>\n%s\n<tbody id=\"%s\"></tbody></table>" % (tableHeaderRow, div_id)
    # On open, query for the list of variables
    page['onopen'] += "doSend('%s');" % json.dumps({'a': 'sub', 'to': 1, 'sym': 'componentNames'})
    page['functions'] += system_functions_template.render(exclude_vars=exclude_vars, **locals())
    page['onmessage'] += system_onmessage_template.render(exclude_vars=exclude_vars, **locals())

def simple_object_widget(page, query):
    param_id = int(query.get('id', 0))
    div_id = 'value'
    from .systemview import the_system
    name = the_system.get_component_name(param_id)
    if name is None:
        name = "?"
    page['title'] = str(param_id) + " " + name
    vars = the_system.get_proxy(param_id).get('vars')
    table = "<table id='%s' border=1>\n" % div_id
    table += "<tr><td>Variable</td><td>Value</td><td>Live update</td></tr>\n"
    for var in vars:
        if var in exclude_vars:
            continue
        #<label><input type='checkbox' onclick='handleSubscribeClick(this, \"%s\");'>Subscribe</label>
        table += "  <tr><td><a href=\"/var?id=" + str(param_id) + "&var=" + var + "\">" + var + "</a></td><td><div id=\"%s\"></div></td><td><input type='checkbox' onclick='handleSubscribeClick(this, \"%s\");'></td></tr>\n" % (div_id + "_" + var, var)
    table += "</table>\n"
    page['body'] += table

    page['functions'] += """
function handleSubscribeClick(checkbox, symbol) {
  writeToScreen(getTime() + " Clicked " + symbol + ", new value = " + checkbox.checked);
  if (!isConnected) {
    writeToScreen(getTime() + " Ignoring due to not connected");
    return;
  }
  if (checkbox.checked) {
    doSend(JSON.stringify({"a": "sub", "to": %d, "sym": symbol}));
  } else {
    doSend(JSON.stringify({"a": "unsub", "to": %d, "sym": symbol}));
  }
}"""  % (int(param_id), int(param_id))

    page['onmessage'] += object_onmessage_template.render(exclude_vars=exclude_vars, **locals())

def simple_variable_widget(page, query):
    param_id = query.get('id', None)
    param_var = query.get('var', None)
    div_id = 'value'
    page['body'] += "<div id='%s'>VALUE</div>" % div_id
#    page['onopen'] += """
#  var obj = document.getElementById("%s");
#  obj.style.color = 'gray';
#""" % div_id
    page['onopen'] += (
        f"  var obj = document.getElementById('{div_id}');"
        f"  obj.style.color = 'gray';")
    page['onopen'] += "doSend('%s');" % json.dumps({'a': 'sub', 'to': int(param_id), 'sym': param_var})
    page['onmessage'] += """
  if (msg['from'] == %s && '%s' in msg['map']) {
  newValue = msg['map']['%s'];
  var obj = document.getElementById("%s");
  obj.innerText = JSON.stringify(newValue);
  obj.style.color = 'black';
}
""" % (param_id, param_var, param_var, div_id)
    page['onclose'] += """
  var obj = document.getElementById("%s");
  obj.style.color = 'gray';
""" % div_id


@aiohttp_jinja2.template('page_template.html')
async def simple_variable_handler(request):
    page = {"title": "Sparvio", "body": "",
            "functions": "",
            "onopen": "", "onclose": "", "onmessage": ""}
    simple_variable_widget(page, request.rel_url.query)
    return page

@aiohttp_jinja2.template('page_template.html')
async def object_handler(request):
    page = {"title": "Sparvio", "body": "",
            "functions": "",
            "onopen": "", "onclose": "", "onmessage": ""}
    simple_object_widget(page, request.rel_url.query)
    return page

@aiohttp_jinja2.template('page_template.html')
async def system_handler(request):
    page = {"title": "Sparvio", "body": "",
            "functions": "",
            "onopen": "", "onclose": "", "onmessage": ""}
    simple_system_widget(page, request.rel_url.query)
    return page

# Not used:
async def json_handler(request):
    data = {'some': 'data'}
    return web.json_response(data)


from reactive.observable import Scheduler
class WebServer(eventthread.EventThread, Scheduler[Callable]):
    "Runs a aiohttp HTTP server. Can't enqueue events to this EventThread."
    def __init__(self, webclients : 'WebClients',
                 hostname='localhost', port=8080):
        eventthread.EventThread.__init__(self, name='AiohttpThread')
        self.stop_server = None  #Only create when the event loop is set
        self._loop = None  # The event loop for the async web server
        self.app = None # The Application object
        self.hostname = hostname
        self.port = port
        self.webclients = webclients
        # All open websocket connections:
        self.connections : List['WebSocketConnection'] = weakref.WeakSet()

    @aiohttp_jinja2.template('button2.html')
    async def serve_button(self, request):
        return {}
    @aiohttp_jinja2.template('cesium_template.html')
    async def serve_cesium(self, request):
        return {}
    async def _websocket_handler(self, request):
        if verbose:
            print("websocket_handler() enter")
        conn = WebSocketConnection(webclients=self.webclients)
        await conn.serve(request)
        if verbose:
            print('websocket_handler() finishes')
        return conn._socket
    async def _on_shutdown(self, app):
        "Callback run on the event loop when the web Application exits"
        count = len(self.connections)
        if count > 0 and verbose:
            print("Web server closing %d websockets" % count)
        for conn in set(self.connections):
            await conn.close()
    async def _run_app(self):
        "Run on the local event loop"
        # Setup
        self.app = web.Application()
        aiohttp_jinja2.setup(self.app,
                             loader=jinja2.FileSystemLoader('templates'))
        self.app.add_routes([web.get('/var', simple_variable_handler)])
        self.app.add_routes([web.get('/obj', object_handler)])
        self.app.add_routes([web.get('/', system_handler)])
        self.app.add_routes([web.get('/button2.html', self.serve_button)])
        self.app.add_routes([web.get('/ws', self._websocket_handler)])
        self.app.add_routes([web.get('/3d.html', self.serve_cesium)])
        self.app.router.add_static(prefix='/static', path='static')
        self.app.on_shutdown.append(self._on_shutdown)

        # Run
        runner = web.AppRunner(self.app)
        await runner.setup()
        site = web.TCPSite(runner, self.hostname, self.port)
        started = False
        try:
            # Fails if the local TCP port is busy
            await site.start()
            started = True
            print('Started web server on %s port %d' % (self.hostname, self.port))
        except Exception:
            print('Could not start web server on %s port %d' % (self.hostname, self.port))

        if started:
            # wait for finish signal
            await self.stop_server.wait()
            if verbose:
                print('Web server closing down')
            self.stop_server = None
        await runner.cleanup()

    def run(self):
        #Runs a separate asyncio loop on this (separate) thread
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self.stop_server = asyncio.Event()  #Event_ts()
        self._loop.run_until_complete(self._run_app())
        #Or in Python 3.7, simply:
        #  asyncio.run(run())
        self._loop.close()

    def stop(self):
        "Call from any thread"
        # Overrides EventThread.stop() to change implementation
        if self.stop_server:
            self._loop.call_soon_threadsafe(self.stop_server.set)

    async def _send_to_all(self, msg):
        "Called on the event loop"
        for conn in set(self.connections):
            await conn.send_str(msg)

    def send_to_all(self, msg):
        "Call from any thread"
        self._loop.call_soon_threadsafe(self._loop.create_task,
                                        self._send_to_all(msg))

    ## Implement Scheduler
    def post_job(self, job : Callable):
        self._loop.call_soon_threadsafe(job)
    def pop_job(self) -> Optional[Callable]:
        return None  #Can't manually pop jobs as we use the asyncio loop
    def has_job(self) -> bool:
        return False


class WebSocketConnection(LocalInternalObject):
    """Represents a web client in a Sparvio system, each connected by a
       dedicated WebSocket instance. Requests from the WebSocket are
       emitted as emanating from this SSP object. Events and report
       messages received to this object are forwarded to the
       WebSocket.
    """
    # Each connection object will be assigned its own thread to
    # synchronize Sparvio events. WebSocket reception and transmission
    # is done on the web server loop so this class has to bridge the two.
    def __init__(self, webclients : 'WebClients'):
        LocalInternalObject.__init__(self, base=webclients._base)
        self.server = webclients.webserver
        self._socket : Optional[web.WebSocketResponse] = None
        # The part of the list already sent (if subscribed with the "cesium" message)
        self._cesium_state : ListState = ListState()

    async def serve(self, request):
        "Called on the webserver loop. Task that only finishes when the websocket connection is closed"
        # TODO: Define heartbeat=2 to send ping every 2 seconds, expecting 'pong'
        self._socket = web.WebSocketResponse()
        await self._socket.prepare(request)
        if verbose:
            print("WebSocketConnection connected")
        # Only register when the websocket succeeds in opening, as
        # only then does it need to be cleaned up on exit
        self.server.connections.add(self)
        try:
            async for msg in self._socket:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    if msg.data == 'close':
                        await self._socket.close()
                    elif msg.data.startswith("{"):
                        try:
                            json_msg = json.loads(msg.data)
                        except Exception as ex:
                            print("WebSocket error decoding %s: %s" %
                                  (msg.data, ex))
                        else:
                            self._handle_json(json_msg)
                    else:
                        await self._socket.send_str(msg.data + '/answer')
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    print('ws connection closed with exception %s' %
                          self._socket.exception())
                else:
                    print('ws unknown message type', msg.type)
        finally:
            self.server.connections.discard(self)
            self.unsubscribe_all()
            cesium_measurements.remove_observer((self.server,
                                                 self._on_cesium_measurement))

    async def close(self):
        if self._socket.closed:
            if verbose:
                print('close for already non-connected Connection')
            return
        await self._socket.close(code=WSCloseCode.GOING_AWAY,
                            message='Server shutdown')

    async def _send_str(self, msg):
        if self._socket.closed:
            print('_send_str() for non-connected Connection')
            return
        #self._socket.send_bytes(msg)
        #self._socket.send_json(msg)
        await self._socket.send_str(str(msg))

    def _handle_json(self, json_msg):
        "Called on the loop task when <json_msg> is received from the socket"
        if json_msg.get('a', None) == 'sub_cesium':
            if verbose:
                print("Subscribing Cesium!")
            cesium_measurements.add_observer((self.server,
                                              self._on_cesium_measurement),
                                             initial_notify = True)
            return
        if json_msg.get('a', None) in ['sub', 'unsub']:
            objectId = json_msg['to']
            variable_symbols = json_msg['sym']
            if type(variable_symbols) is not list:
                variable_symbols = [variable_symbols]
            if json_msg['a'] == 'sub':
                self.subscribe(objectId, variable_symbols, self.on_report)
            else:
                self.unsubscribe(objectId, variable_symbols, self.on_report)

    def send_to_client(self, msg : str):
        "Call from any thread"
        if self._socket.closed:
            print("Warning: can't send to closed socket")
            return
        loop = self.server._loop
        loop.call_soon_threadsafe(loop.create_task, self._socket.send_str(msg))

    def on_report(self, msg):
        "Receiving a report on behalf of the web client. Call from any thread."
        if self._socket.closed:
            print("Warning: on_report to closed socket")
            return
        msg_json = json.dumps(msg)
        if verbose:
            print('WebSocketConnection forwarding', msg_json)
        self.send_to_client(msg_json)

    def _on_cesium_measurement(self):
        diff = cesium_measurements.update_state(self._cesium_state)
        ignored = 0
        sent = 0
        for entry in cesium_measurements.diff_to_entries(diff):
            try:
                sample = {'ts': "%d" % entry.key,
                          'lat': "%.8f" % entry.data['pos'].lat,
                          'lon': "%.8f" % entry.data['pos'].lon,
                          'alt': "%.2f" % entry.data['alt']}
            except KeyError:
                # At least one of the required parameters is missing.
                ignored += 1
                continue
            any_param = False
            for param in ['temp', 'rh', 'co2', 'ch4']:
                if param in entry.data:
                    sample[param] = str(entry.data[param])
                    any_param = True
            if 'wspd' in entry.data and 'wdir' in entry.data:
                sample['wspd'] = "%.2f" % entry.data['wspd']
                sample['wdir'] = "%.2f" % entry.data['wdir']
                any_param = True
            if not any_param:
                ignored += 1
                continue  #No meaning to include the data point
            data = '{"sample": {%s}}' % ','.join('"'+key+'":'+value for (key,value) in sample.items())
            #{"ts": %d, "lat": %.8f, "lon": %.8f, "alt": %f, "co2": %f}}' % (entry.key, entry.data['pos'].lat, entry.data['pos'].lon, entry.data['alt'], entry.data['rh'])
            if verbose:
                print('To Cesium:', data)
            self.send_to_client(data)
            sent += 1
        #print("Sent %d rows to 3D client and ignored %d rows" % (sent, ignored))


class WebClients(eventthread.EventThread, LocalInternalObject, SparvioInterface):
    "The WebServer and collection of all web client connections"
    def __init__(self, base, hostname='localhost', port=8080):
        name = "web"
        eventthread.EventThread.__init__(self, name=name)
        LocalInternalObject.__init__(self, base, name, thread=self)
        SparvioInterface.__init__(self)
        self._variables = {'connections': list_type}
        self.connections = []
        self.hostname = hostname
        self.port = port
        self.webserver = None
    def setup(self):
        self.webserver = WebServer(self, hostname=self.hostname,
                                   port=self.port).start()


# class WebWidget:
#     "All web widgets inherit from this class"
#     def get_onload_js(self) -> str:
#         "Return the JS code to execute for this component every time the connection to the server comes online"
#         pass

#     def get_body_html(self) -> str:
#         pass
