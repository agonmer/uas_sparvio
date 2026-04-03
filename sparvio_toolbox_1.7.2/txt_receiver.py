# txt_receiver.py: Uses RR1 or RR2 to receive data from a remote
# Sparvio system using the 'TXT' packet type.

# This is inefficient with bandwidth and limited in expressing data
# types. The format should be replaced by SSP-BIN.

import time
from sspt import parse, bytebuffer
from sspt.type_hints import *
from core import framing, messages
from core.serialdaemon import SerialDaemon
from core.localobject import LocalComponent, LocalObject, SparvioInterface
from core.gis import log

from reactive.eventthread import EventThread

the_txt = None  #DEBUG

class Txt:
    def __init__(self, serial : SerialDaemon):
        global the_txt  #DEBUG
        the_txt = self  #DEBUG
        self.serial = serial
        self.protocol = framing.LineReader(self._on_line)
        self.serial.protocol = self.protocol
        #Whether to broadcast 'annNet' until a device starts to send data
        self.doAnnounce = True
        self._next_internalId = 1
        # Should map between remote component names and internalId, to
        # assign a unique OID for all remote components.
        self.name_to_obj : Mapping[str, LocalObject] = {}

        # Record the name of each oid of the remote system, when the
        # remote system reports it
        self.id_to_name : Mapping[Oid, str] = {}

        #HACK: Needed to record the reception quality, but Txt isn't a SSP object as of now
        self.objectId = 'rr1'

        from core.localobject import system_log
        self._log = system_log #log.MutableObjectsLog()
        #system_log.add_source(self._log)

    def setup(self):
        self.serial.write("\necho 0\n")
        if self.doAnnounce:
            self._timer = eventthread.Timer(self, self._on_timer)
            self._timer.start(5, recurring=True)

    def _on_timer(self):
        if doAnnounce:
            self.serial.write('\nannNet\n')

    def _handle_txt_line(self, line):
        print("Txt:", line)
        (params, text) = get_txt_payload(line)
        if text is None:
            return

        q = get_best_packet_quality(params)

        dic = parse_txt_to_dict(text)
        if dic is None:
            print('txt_receiver no content in', line)
            return
        self.doAnnounce = False
        oid_dic : Mapping[Oid, Mapping[Var, Any]] = {self.objectId: {}}
        if q is not None:
            reception = int(100 * q / 255.)
            oid_dic[self.objectId]['reception'] = reception
        for (name, values) in dic.items():
            if name not in self.name_to_obj:
                self.create_subobject(name)
                values['name'] = name
            # HACK for SKD1 Atlas app that reports 'temp' instead of 'liquidTemp'
            if 'temp' in values:
                values['liquidTemp'] = values['temp']
                del values['temp']
            # An unresolved bug in SKH1 (2019-10-29) may produce
            # coordinates with 0 value. Filter out these. Sorry
            # England, Equador, etc.
            if 'lat' in values and values['lat'] == 0.0:
                print('Ignoring lat = 0')
                del values['lat']
            if 'lon' in values and values['lon'] == 0.0:
                print('Ignoring lon = 0')
                del values['lon']
            oid_dic[self.name_to_obj[name].objectId] = values
        self._log.append_data(oid_dic)
        # TODO: Register the variable values with the objects and
        # generate mark_as_updated() / send_all_updates()

    def _handle_ssp_line(self, line):
        (params, bin_msg) = get_ssp_payload(line)
        if bin_msg is None:
            return

        iterator = bytebuffer.ByteIterator(bin_msg)
        try:
            addr_msg = messages.addressed_msg_type.from_impBin(iterator)
            msg = addr_msg['msg']
        except Exception as ex:
            print("Warning: txt_receiver could not decode", bin_msg)
            print(ex)
            return
        py_msg = msg.to_pyValue()
        if py_msg.get('a', None) != 'rep':
            print('handle_ssp_line other type', py_msg)
            return

        #print(py_msg)
        # It's a report. First, register any name metadata
        for (remote_oid, _map) in py_msg['map'].items():
            if 'name' in _map:
                # An object reports its own name
                self.id_to_name[remote_oid] = _map['name']
            if 'componentNames' in _map:
                # The central reports the names of all components
                names = _map['componentNames']
                for (oid, name) in names.items():
                    self.id_to_name[oid] = name

        # Second, transform the report
        dic : Mapping[str, Mapping[Var, Any]] = {}
        for (remote_oid, _map) in py_msg['map'].items():
            name = self.id_to_name.get(remote_oid,
                                       self.objectId + '_' + str(remote_oid))
            if name not in dic:
                dic[name] = {}
            dic[name].update(_map)

        q = get_best_packet_quality(params)
        if q is not None:
            if not self.objectId in dic:
                dic[self.objectId] = {}
            reception = int(100 * q / 255.)
            dic[self.objectId] = {'reception': reception}

        print(dic)

        self._log.append_data(dic)


    #Called on the serialdaemon thread
    def _on_line(self, line):
        if '[#TXT:' in line:
            self._handle_txt_line(line)
            return
        elif '[#SSP:' in line:
            self._handle_ssp_line(line)
            return

    def create_subobject(self, name):
        if name in self.name_to_obj:
            return
        internalId = self._next_internalId
        self._next_internalId += 1
        self.name_to_obj[name] = LocalObject(self._base, internalId=internalId)
        self.name_to_obj[name].name = name


def get_best_packet_quality(params : Mapping) -> int:
    q = 0
    try:
        q = int(params['q'], 16)
    except:
        pass
    try:
        q0 = int(params['q0'], 16)
        if q0 > q:
            q = q0
    except:
        pass
    try:
        q1 = int(params['q1'], 16)
        if q1 > q:
            q = q1
    except:
        pass
    if q == 0:
        return None
    return q

def get_txt_payload(line):
    """Returns (params, payload)
       In a line "[#TXT:id=1003,seq=2,q=A1:k1:v1,k2:{k3:v3,k4:v4}]", extract:
       params = {"id":"1003", "seq":"2", "q":"A1"}
       payload = "k1:v1,k2:{k3:v3,k4:v4}"
    """
    open_bracket = line.find("[#TXT:")
    if open_bracket == -1:
        return (None, None)
    close_bracket = line.rfind("]")
    if close_bracket == -1 or close_bracket < open_bracket:
        return (None, None)
    packet = line[open_bracket : close_bracket+1]
    text = line[open_bracket+len("[#TXT:"):close_bracket]
    colon = text.find(':')
    if colon == -1:
        return (None, None)
    params = {}
    for item in text[:colon].split(','):
        equal = item.find('=')
        if equal == -1 or len(item) <= equal + 1:
            continue
        params[item[:equal]] = item[equal+1:]

    return (params, text[colon+1:])

def parse_txt_to_dict(text):
    """Parses from string to a dict of dicts, while excluding non-graphable
    variables. Examples:
      "SKS2_3:{rh:38.08}" => {'SKS2_3': {'rh': 38.08}}
      "bat:7.3" => {'SKH1': {'bat': 7.3}}
    """
    exclude_vars = ['components']
    nested_dict = parse.parse_json('{'+text+'}')
    if nested_dict is None:
        print('Discarding', text)
        return None
    dic = {}
    def add(sensor, key, value):
        if not sensor in dic.keys():
            dic[sensor] = {}
        dic[sensor][key] = value
    for (component, _map) in nested_dict.items():
        if type(_map) is not dict:
            #The key is not a component specifier, but variable
            var = component
            if var in exclude_vars:
                continue
            log.create_or_change_dic(dic, 'SKH1', var, _map)
            continue
        for (var, val) in _map.items():
            if var not in exclude_vars:
                log.create_or_change_dic(dic, component, var, val)
    return dic

def get_ssp_payload(line) -> Tuple[Optional[Dict[str,Any]], Optional[bytes]]:
    """From a line on the form [#SSP:q=AF:123ABC], extract a tuple
    (params, payload). Example extracted data for params is {"q":
    175}.
    """
    open_bracket = line.find("[#SSP:")
    if open_bracket == -1:
        return (None, None)
    close_bracket = line.rfind("]")
    if close_bracket == -1 or close_bracket < open_bracket:
        return (None, None)
    packet = line[open_bracket : close_bracket+1]
    text = line[open_bracket+len("[#SSP:"):close_bracket]
    colon = text.find(':')
    if colon == -1:
        return (None, None)
    params = {}
    for item in text[:colon].split(','):
        equal = item.find('=')
        if equal == -1 or len(item) <= equal + 1:
            continue
        params[item[:equal]] = item[equal+1:]

    try:
        payload = parse.parse_hex(text[colon+1:])
    except:
        print('Failed to parse payload "%s"' % text[colon+1:])
        payload = None
    return (params, payload)
