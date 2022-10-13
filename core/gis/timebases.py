# Timebases: Translate from different timebases to Python time

# The translation is best-effort and can be improved retroactively by
# providing more time synchronization data. (For example, learning how
# lTime has drifted can improve previous timestamps.)

from sspt.type_hints import *
import datetime
from datetime import timezone

def msg_any_oid_to_value(msg, var : Var, default = None):
    _map = msg['map']
    for (oid, valuemap) in _map.items():
        if var in valuemap:
            return valuemap[var]
    return default

#def msg_to_value(msg, oid_var : Tuple[Oid, Var], default = None):
#    (oid, var) = oid_var
#    _map = msg['map']
#    if oid in _map:
#        if var in msg[oid]:
#            return msg[oid][var]
#    return default

class MultipleTimebases:
    "Translates from multiple timebases to UTC time, by assuming the logging time is the same as the sampling time."
    def __init__(self):
        # The values are tuples of (time in this timebase, time of
        # logging in 1.lTime timebase)
        #self.tuples : Dict[Tuple[Oid, Var], Tuple(float, float)] = []
        # The relation between lTime and pythonTime:
        self._lTime_sec : float = None
        self._pythonTime : Timestamp = None
        #self._utcDate = None
        #self._utcMsSinceMidnight : float = None
    def register_report(self, msg, log_time : float):
        # For now, synchronize with logging time, not an more exact
        # sampling timestamp
        utcDate = msg_any_oid_to_value(msg, 'utcDate')
        if utcDate:
            utcMsSinceMidnight = msg_any_oid_to_value(msg, 'utc')
            if utcMsSinceMidnight:
                #self._utcDate = utcDate
                #self._utcMsSinceMidnight = utcMsSinceMidnight
                self._lTime_sec = log_time  #msg_to_value(msg, (1, lTime))

                dt = datetime.datetime(2000 + utcDate['year'],
                                       utcDate['month'],
                                       utcDate['day'], 0, 0, 0,
                                       tzinfo=datetime.timezone.utc)
                timestamp = dt.timestamp()
                timestamp += (utcMsSinceMidnight / 1000.0)
                self._pythonTime = timestamp

    def msg_to_pythonTime(self, msg, log_time : float) -> Optional[float]:
        if self._pythonTime is None or self._lTime_sec is None:
            return None
        return self._pythonTime + (log_time - self._lTime_sec)

# Not used
class MultipleTimebases2:
    """The old code, which tries to sync each device with UTC time -- but
       the problem is that this information is only available for SKH1"""
    def __init__(self):
        self._time_synchronizations : Dict[Oid, timebases.TimeSynchronization] = {}

    def register_report(self, msg, log_time : float):
        # Register time synchronization (if possible)
        for oid in msg['map'].keys():
            if not oid in self._time_synchronizations:
                self._time_synchronizations[oid] = TimeSynchronization(oid)
            self._time_synchronizations[oid].register_report(msg,
                                                             log_time=log_time)

    def msg_to_pythonTime(self, msg, log_time : float) -> Optional[float]:
        # Figure out the global timestamp
        for oid in msg['map'].keys():
            timestamp = self._time_synchronizations[oid].msg_to_pythonTime(msg)
            if timestamp:
                return timestamp  #Use the first deduced timestamp
        return None

# Not used
class TimeSynchronization:
    "Records a relation between a Sparvio Object and global time"
    def __init__(self, objectId):
        self.objectId = objectId
        self.lTime = None  #The systime ticks of the MCU, in millisec
        #What global time <lTime> corresponds to (Unix time in sec)
        self.pythonTime = None

    def register_report(self, msg, log_time : float = None):
        "Creates or updates the relation between timebases if possible"
        if msg['a'] != 'rep':
            return  #Not a report
        if self.objectId not in msg['map']:
            return  #No information on this object
        valuemap = msg['map'][self.objectId]
        lTime = valuemap.get('lTime', None)
        utc = valuemap.get('utc', None)
        date = valuemap.get('utcDate', None)
        if lTime and utc and date:
            dt = datetime.datetime(2000 + date['year'], date['month'],
                                   date['day'], 0, 0, 0,
                                   tzinfo=datetime.timezone.utc)
            timestamp = dt.timestamp()
            timestamp += (utc / 1000.0)
            self.pythonTime = timestamp
            self.lTime = lTime
        # TODO: Could handle utc and utcDate occurring in different messages

    def msg_to_pythonTime(self, msg) -> Optional[float]:
        "Returns None if no relation is established yet"
        if not (self.lTime and self.pythonTime):
            return None  #No sync yet -- no need to look at <msg>
        if not self.objectId in msg['map']:
            return None  #No data for this object
        lTime = msg['map'][self.objectId].get('lTime', None)
        if lTime is None:
            return None  #The algorithm only supports lTime for now
        return self.pythonTime + (lTime - self.lTime) / 1000.

# def lTimeToPythonTime(lTime, log : ValuesLog):
#     "Naive version that uses the most recent synchronization of a particular object"
#     if not 'utc' in log.most_recent_entries:
#         return None  # No fix so far
#     if not 'date' in log.most_recent_entries:
#         return None  # No fix so far
#     utc_entry = log.most_recent_entries['utc']
#     utc = utc_entry['data']['utc']
#     date = log.most_recent_value('date')
#     # utc and date entries must be from the same date.

#     # midnight
#     dt = datetime.datetime(2000 + date.y, date.m, date.d, 0, 0, 0,
#                            tzinfo=datetime.timezone.utc)
#     timestamp = dt.timestamp()
#     timestamp += utc  #This is now the time of utc_entry
#     utc_entry

#     offset = utc_entry['data']['utc'] - utc_entry['timestamp']

#     pass

#log : MutableObjectsLog
#log.values_logs[oid].most_recent_value('lTime')

# TODO: When message type 'update' is changed to 'report', keep track
# of the most recent timestamp of each component in used timebase. The
# goal is to map every entry to a 'unixTime'

# Most recent utcPrim : oid, entry_ix, unixTime
# Most recent date

# Rules:
# * Timebases from any object can be used
# * utcSec and utcPrim need a 'date'
# * utcSec is assumed correct unless a 'utcPrim' correction exists.
# * utcPrim implies utcSec is set at the same point
# * Two (utcPrim, lTime) points assume a lTime linear clock drift in-between
