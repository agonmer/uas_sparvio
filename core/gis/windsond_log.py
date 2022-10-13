# WindsondLog: Parse a Windsond .sounding file for a single sonde into a Log
#
# Doesn't yet parse the extra Windsond sampling points into separate log entries.
from typing import *
from .log import ValuesLog
from reactive.indexeddict import Entry

def get_suffix(text, prefix):
    if text.startswith(prefix):
        return text[len(prefix):]
    return None

def un_stringify(string):
    """
    :param string: in format [-][00h]00m00s00
    :return: float
    """

    assert isinstance(string, str)
    if len(string) == 0:
        return 0.0

    if string[0] == '-':
        return -un_stringify(string[1:])

    if 'h' in string:
        (hours, string) = string.split('h', 1)
        hours = int(hours)
    else:
        hours = 0

    if 'm' in string:
        (minutes, string) = string.split('m', 1)
        minutes = int(minutes)
    else:
        minutes = 0

    if 's' not in string:
        raise TypeError('Wrong format of the timestamp')

    (seconds, milliseconds) = string.split('s', 1)
    seconds = int(seconds)
    milliseconds = int(milliseconds)

    return hours * 3600 + minutes * 60 + seconds + milliseconds / 1000.0


class logger_iterator(object):
    def __init__(self, filename):
        self._offset = 0  #Start time since epoch
        self.version = 1  # Default to old version
        self.receiver_version = None  # Default to invalid version
        self.node_id = None
        self.timezone = None  #None = unknown. Seconds east of UTC.
        self.install = None  #None = unknown. String.
        self.lic_id = None  #None = unknown. Integer.
        self.software = None  #None = unknown. Software version. String.
        self.comments = []
        # Consume all starting comments / metadata
        self.log = None

        with open(filename) as f:
            self.log = f.readlines()

        while self.log[0].startswith('#'):
            line = self.log.pop(0)[1:].strip()
            if line.startswith('offset='):
                line = line.lstrip('offset=')
                try:
                    self._offset = float(line.lstrip())
                except:
                    pass
            if line.startswith('timezone='):
                line = line.lstrip('timezone=')
                try:
                    self.timezone = int(line.lstrip())
                except:
                    pass
            elif line.startswith('version='):
                line = line.lstrip('version=')
                try:
                    self.version = int(line.lstrip())
                except:
                    pass
            elif line.startswith('receiver version='):
                self.receiver_version = line[len('receiver version='):]
            elif line.startswith('install='):
                line = line.lstrip('install=')
                parts = line.split()
                if len(parts) > 0:
                    self.install = parts[0]
                if len(parts) > 1:
                    try:
                        self.lic_id = int(parts[1])
                    except:
                        pass
            elif line.startswith('software='):
                line = line.lstrip('software=')
                self.software = line.lstrip()
            elif line.startswith('node_id='):
                line = line.lstrip('node_id=')
                try:
                    self.node_id = int(line.lstrip())
                except:
                    pass

    def start_time(self):
        return self._offset

    def __iter__(self):
        # Destructively iterate. A wrapping file class would be needed to
        # represent a log file more accuratly.
        return self

    def __next__(self):
        while True:
            try:
                line = self.log.pop(0).rstrip()
            except IndexError:
                raise StopIteration
            if line == '':  # An empty line would be '\n'
                raise StopIteration
            try:
                (timestring, data) = line.split(': ', 1)
                if len(timestring) == 0 or timestring[0] == '#' \
                        or len(data) == 0:
                    continue
                if data[0] == '#':
                    # This is a comment
                    self.comments.append(data[1:].strip())
                    continue
                timestamp = un_stringify(timestring)
                timestamp += self._offset
                return timestamp, data #.decode('string_escape')
            except Exception as ex:
                print('Exception', ex)
                raise ex
                #pass
    next = __next__  # for Python 2

def from_text(text):
    "Create a dictionary from the text of a Windsond packet, especially [#MET:...]"
    #Shortest possible message: "[#X]"
    msg = {}
    if len(text) < 4 or text[0] != '[' or text[1] != '#' or text[-1] != ']':
        msg["error"] = 'Malformed data "' + text.encode('string_escape') + '"'
        return msg
    parts = text[2:-1].split(':', 2)
    #msg.type = parts[0]
    if len(parts) > 1:
        for param in parts[1].split(','):
            if '=' not in param:
                # Create new message, to avoid
                # inconsistent set of parameters
                msg = {"error": 'Malformed param "%s"' % param}
                return msg
            key, value = param.split('=', 1)
            msg[key] = value
    if len(parts) == 3:
        msg['data'] = parts[2]

    if 'tei' in msg:
        #Bug in RR1 firmware 2.00-2.02
        if msg['tei'] == "64.00":
            del msg['tei']

    int_params = ["pwr", "gpse", "behlan", "logst", "role", "clk", "resq",
                  "evt", "fwver", "mcnt", "cutalt", "cutpr2", "supmul",
                  "gpa", "galt", "hw", "burn", "ucnt", "tim", "rssi",
                  "ctmr", "net", "twire", "blk", "beep", "gpss", "id",
                  "sid", "r", "rec", "rec0", "rec1", "alt", "pa", "lux",
                  "afc", "afc0", "afc1", "new"]
    for param in int_params:
        if param in msg:
            try:
                msg[param] = int(msg[param])
            except:
                del msg[param]

    types = {'q': lambda x: int(x, 16),
             'q0': lambda x: int(x, 16),
             'q1': lambda x: int(x, 16),
             'su': float,
             'ang': float,
             'spd': float,
             'te': float,
             'tei': float,
             'hu': float}
    # Handled as ASCII instead, since they need processing anyway:
    #'lat': float, 'lon': float, 'latm': float, 'lonm': float,
    #'latd': float, 'lond': float}
    for t in types.keys():
        if t in msg:
            type_fn = types[t]
            try:
                msg[t] = type_fn(msg[t])
            except:
                del msg[t]

    #Workaround for underflow bug in receiver <= 2.03:
    for key in ['te', 'te1', 'te2', 'te3', 'te4', 'te5', 'te6', 'te7']:
        if not key in msg:
            continue
        try:
            te = float(msg[key])
            if te > 400:
                te = te - 655.36
            msg[key] = te
        except:
            pass

    #Workaround for overflow bug in receiver <= 2.05:
    for key in ['ang1', 'ang2', 'ang3', 'ang4', 'ang5']:
        if not key in msg:
            continue
        try:
            ang = float(msg[key])
            if ang < 0:
                ang += 327.68
            msg[key] = ang
        except:
            pass

    # Rename parameters that changed name from Windsond 2 to Sparvio
    for (old, new) in [('te', 'temp'),
                       ('spd', 'wspd'),
                       ('hu', 'rh')]:
        try:
            msg[new] = msg.pop(old)
        except KeyError:
            pass  #The old key didn't exist
    # The wind (source) direction is the opposite of the heading of the balloon
    if 'ang' in msg:
        msg['wdir'] = (msg['ang'] + 180) % 360

    if 'q0' in msg or 'q1' in msg:
        msg['q'] = max(msg.get('q0', 0),
                              msg.get('q1', 0))

    if 'r' in msg or 'q' in msg:
        quality = 0
        if 'r' in msg:
            msg['rssi'] = msg['r'] / 256.0
        else:
            msg['rssi'] = msg['q'] / 256.0
        #Each recovered bit counts 3% against RSSI
        #TODO: Add support for twin radios
        if 'rec' in msg:
            quality = max(0.01, msg['rssi'] - 0.02 * msg['rec'])
        else:
            quality = msg['rssi']
        msg['qu'] = quality

    #Parse text format
    data = msg.get('data', '')
    if len(data) > 3 and data[1] == '(' and data[-1] == ')':
        #Syntax is TYPE '(' PARAMS ')'
        msg['text_type'] = msg['data'][0]
        msg['text_parts'] = msg['data'][2:-1] #parse_coded_params(msg['data'][2:-1])
        msg['has_text'] = True

    return msg


class WindsondLog(ValuesLog):
    "Source that reads a Windsond .sounding file"
    def __init__(self, filename):
        ValuesLog.__init__(self)
        self.filename = filename
        self.offset = None  # Start time
    def load(self):
        it = logger_iterator(self.filename)
        self.object_id = it.node_id

        for (timestamp, text) in it:
            dic = from_text(text)
            if 'id' in dic:
                if dic['id'] == it.node_id:
                    del dic['id']  # Superfluous information
                else:
                    # Could generate log lines for multiple sondes,
                    # but the .sounding format isn't supposed to have
                    # that.
                    print('Warning in file ' + self.filename +
                          ': Unexpected id in line ' + text)
                    continue
            entry = Entry(key=timestamp, data=dic)
            self._append_entry(entry)
        self.notify_observers()
        return self

from .position import Position

def text_to_position(lat_string : str, lon_string : str) -> Optional[Position]:
    "Parses position as encoded in a Windsond 'lat' and 'lon' pair"
    def parseCoord(string):
        "Parses text DDMM(.)MMMM (implicit decimal point) into float D.D"
        if len(string) == 0:
            return None
        if string[0] == '-':
            sign = -1.0
            string = string[1:]
        else:
            sign = 1.0
        if len(string) == 0:
            return None
        elif len(string) < 7:
            string = ('0' * (7 - len(string))) + string
        try:
            degrees = int(string[:-6])
            mins = int(string[-6:]) / 10000.0
        except:
            return None
        return sign * (degrees + mins / 60.0)

    if lat_string == '0' or lon_string == '0':
        #Decimals are always explicit for real position reports
        return None
    lat = parseCoord(lat_string)
    lon = parseCoord(lon_string)
    if lat is None or lon is None:
        return None
    return Position(lat, lon)

# Hack until a "ResolvedWindsondLog" class is written to dynamically
# deduce GPS positions
def resolve_positions(windsondlog : WindsondLog) -> ValuesLog:
    "Calculates a Log where the Windsond encoding of lat/lon is replaced by 'pos'"
    # For now, just filters the already complete positions. Should
    # instead rewrite and use deduce_gps.py.
    deduced = ValuesLog()
    for entry in windsondlog:
        if entry.data.get('new', 1) == 0:
            continue  #Don't include stale GPS positions
        if 'lat' in entry.data and 'lon' in entry.data:
            pos = text_to_position(entry.data['lat'], entry.data['lon'])
            if pos is None:
                continue  #Ignore message with invalidly encoded position
            data = entry.data.copy()
            del data['lat']
            del data['lon']
            data['pos'] = pos
            deduced.append_data(entry.key, data, source=entry.log_ix)
    return deduced
