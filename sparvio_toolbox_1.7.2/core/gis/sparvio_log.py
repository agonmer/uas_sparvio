from reactive.indexeddict import IndexedDict, SparseIndexedDict
from reactive.observable import Scheduler, relations, ListState, BasicObsVar
from sspt.type_hints import *

# For the hack log data format:
from sspt import bytebuffer
from .. import messages
from sspt.ontology import global_ontology

from . import log
from . import timebases
from .log import ObjectsData

ltime_and_msg = global_ontology.get_registry_entry_by_c_name('SSP_GSCHEMA_LTIME_AND_MSG')

# TODO: 'source' should actually be ObsList
class SparvioLog(log.MutableObjectsLog):
    """Parses SSP-BIN messages from an IndexedDict of {'lTime': float,
       'msg': SSP-BIN} as logged by simple_logger.c and calculates UTC
       timestamps. The keys are UTC timestamps.
    """
    def __init__(self, scheduler : Scheduler[Callable], source : IndexedDict):
        "The entries in <source> are Entry with data a dict {'lTime': float, 'msg': SSP-BIN message}"
        super().__init__()
        self._source = source
        self._processed_state = ListState()
        self._timesync = timebases.MultipleTimebases()
        # The time of the first log entry (don't change externally -- should be Wrapped)
        self.start_time : BasicObsVar[Optional[Timestamp]] = BasicObsVar(None)
        relations.job_may_trigger(self._on_source_change, self)
        relations.job_may_trigger(self._on_source_change, self.start_time)
        self._source.add_observer((scheduler, self._on_source_change),
                                  initial_notify = True)

    def _on_source_change(self):
        diff = self._source.update_state(self._processed_state)
        if diff.is_empty():
            return
        for entry in self._source.diff_to_entries(diff):
            self._on_log_line(entry.data)
        self.notify_observers()

    def _on_log_line(self, line):
        if not isinstance(line, dict) or 'msg' not in line:
            print("Warning: Ignoring ill-formed log line ", line)
            return
        lTime = line['lTime']
        bin_msg = line['msg']
        iterator = bytebuffer.ByteIterator(bin_msg)
        try:
            msg = messages.addressed_msg_type.from_impBin(iterator)
        except Exception as ex:
            print("Warning: on_log_line could not decode", bin_msg)
            print(ex)
            #f.write("%u: error decoding %s\n" %
            #        (lTime, parse.bytes_to_hex(bin_msg)))
            return
        if 'msg' in msg:
            msg = msg['msg']
        msg = msg.to_pyValue()
        if msg['a'] != 'rep':
            print('Info: Ignoring non-report', msg['a'])
            return  # Only consider Reports (for now)
        self._timesync.register_report(msg, lTime)
        # Figure out the global timestamp
        timestamp = self._timesync.msg_to_pythonTime(msg, lTime)

        data = msg['map'].copy()
        data['logger'] = {'lLogTime': lTime}
        entry = log.Entry(key=timestamp, data=data)
        self._append_entry(entry)
        if timestamp and self.start_time.get() is None:
            self.start_time.set(timestamp)


class SparvioMessageLog(SparseIndexedDict):
    "Parses SSP-BIN messages to native Python representation. Uses the time of logging as key ('lTime')"
    def __init__(self, scheduler : Scheduler[Callable], source : IndexedDict):
        "The entries in <source> are Entry with data a dict {'lTime': float, 'msg': SSP-BIN message}"
        super().__init__()
        self._source = source
        self._processed_state = ListState()
        relations.job_may_trigger(self._on_source_change, self)
        self._source.add_observer((scheduler, self._on_source_change),
                                  initial_notify = True)

    def _on_source_change(self):
        diff = self._source.update_state(self._processed_state)
        if diff.is_empty():
            return
        if diff.mutations:
            raise NotImplementedError()
        for entry in self._source.diff_to_entries(diff):
            self._on_log_line(entry.data)
        self.notify_observers()

    def _on_log_line(self, line):
        if not isinstance(line, dict) or 'msg' not in line:
            print("Warning: Ignoring ill-formed log line", line)
            return
        lTime = line['lTime']
        bin_msg = line['msg']
        iterator = bytebuffer.ByteIterator(bin_msg)
        try:
            msg = messages.addressed_msg_type.from_impBin(iterator)
        except Exception as ex:
            print("Warning: on_log_line could not decode", bin_msg)
            print(ex)
            #f.write("%u: error decoding %s\n" %
            #        (lTime, parse.bytes_to_hex(bin_msg)))
            return
        if 'msg' in msg:
            msg = msg['msg']
        msg = msg.to_pyValue()
        self.add(key = lTime, data = msg)
