from typing import *
from collections import namedtuple
from abc import ABC, abstractmethod
import time

from sspt.type_hints import *
from reactive import eventthread
from reactive.observable import Observable, Scheduler, ObsSet, MutableObsSet, SimpleScheduler, ListState

from reactive import indexeddict
from reactive.indexeddict import *

# 'Log' is a data model designed for real-time data with real-time
# GUI, bulk loading of historic data to review files and replaying of
# historic data by simulating the sequence of events, including
# instantaneous jumping in time.
#
# See readme.rst for a description of the features and properties.


######################################################################
## LOG CLASSES

"""A *log* is defined as a SparseIndexedDict (an IndexedDict[EntryData])
where the keys are Python timestamps (floating point number as seconds
after the Epoch, as returned by time.time()).
The two major types of logs are ValuesLog and ObjectsLog.
"""
Log = indexeddict.SparseIndexedDict


######################################################################

ValuesType = Mapping[Var, Any]

class ValuesLog(Log[ValuesType]):
    """A log where the data is a map from variable name (string) to value
       (native Python, not pyObjects). All variables are assumed to
       belong to <self.object_id>, and is not stored in each
       individual entry (in contrast to ObjectsLog).
    """
    def __init__(self, object_id = 0):
       Log.__init__(self) # Cache the most recent entry for each variable
       self.most_recent_entries : Dict[Var, Entry[ValuesType]] = {}
       # The OID that all entries in this log belongs to. Needed for
       # all_objects() and if combining logs:
       self.object_id = object_id  # Default value 0 means 'invalid value'

    def register_message(self, msg, timestamp : Timestamp):
        "Used as callback for object subscription"
        if msg['a'] != 'rep':
            print('ValuesLog.register_message() ignoring non-report')
            return
        # Error: self.object_id isn't updated when the object changes
        # Oid, such as when the local component is networked:
        if not self.object_id in msg['map']:
            #print('ValuesLog.register_message() our id (%d) not in list (%s)' %
            #      (self.object_id, str(list(msg['map'].keys()))))
            return
        self.append_data(timestamp, msg['map'][self.object_id])

    def append_data(self, timestamp : Timestamp,
                     data: ValuesType, source = None) -> None:
        #TODO: Check that timestamp is higher than most recent data
        entry = Entry(key=timestamp, data=data, source=source)
        self._append_entry(entry)
        for (key, value) in data.items():
            self.most_recent_entries[key] = entry
        self.notify_observers()

    def apply_mutation(self, old_revision : int, new_revision : int,
                       mutation : Mutation):
        raise NotImplementedError("Update self.most_recent_entries")

    def all_objects(self) -> Set[int]:
        "Returns the set of all objectIds present in this log -- which is exactly one"
        return set([self.object_id])

    def all_keys(self) -> Iterable[Var]:
        "The set of all variables that have occurred"
        return self.most_recent_entries.keys()

    #def ix_to_ts_and_values(self, ix : int) -> Tuple[ValuesType, Timestamp]:
    #    return (self._entries[ix].data, self._entries[ix].key)

    def most_recent_value(self, key : Var, default=None) -> Any:
        "Returns the most recent value of <key>"
        if not key in self.most_recent_entries:
            return default
        return self.most_recent_entries[key].data[key]

    def get_key_entry_at_time(self, timestamp : float,
                              key : Var,
                              default : Optional[Entry] = None) \
                              -> Optional[Entry[ValuesType]]:
        """Returns the entry at or as soon before <timestamp> as possible,
           where there's a value for <key>"""
        # Quick check to see if <key> has been encountered at all
        if not key in self.most_recent_entries:
            return default
        def predicate(entry : Entry[ValuesType]) -> bool:
            return key in entry.data
        entry = self.key_to_entry(key = timestamp,
                                  pick = IndexedDict.PICK_LOWER,
                                  predicate = predicate)
        if entry is None:
            return default
        return entry

    def most_recent_value_and_time(self, key : Var, default=None) \
        -> Tuple[Any, Optional[float]]:
        "Returns the value and timestamp"
        if not key in self.most_recent_entries:
            return (default, None)
        return (self.most_recent_entries[key].data[key],
                self.most_recent_entries[key].key)

    get_entry_at_time = indexeddict.SparseIndexedDict.key_to_entry

    def interpolate_value(self, timestamp : float, key: Var,
                          cache : SearchCache = None):
        """Does a linear interpolation of <key> at time <timestamp> from the
           closest known values. <key> must have numerical values. If
           <timestamp> is outside the range of entries, returns the
           closest value without extrapolating the derivate. Returns
           None if no entries match.
        """
        def predicate(entry):
            return key in entry.data
        if cache is None:
            cache = SearchCache()
        # Updates <cache> with the match
        earlier = self.key_to_entry(key=timestamp,
                                    pick=IndexedDict.PICK_LOWER,
                                    predicate=predicate, cache=cache)
        #Don't modify <cache> as future interpolate_value() calls
        #should reuse the cache of the 'earlier' match
        upper_cache = cache.copy()
        later = self.key_to_entry(key=timestamp, pick=IndexedDict.PICK_HIGHER,
                                  predicate=predicate, cache=upper_cache)
        if earlier is None and later is None:
            return None
        if later is None or later == earlier:
            return earlier.data[key]  #type: ignore
        if earlier is None:
            return later.data[key]
        total_t_diff = float(later.key - earlier.key)
        if total_t_diff <= 0:
            return earlier.data[key]
        earlier_t_diff = timestamp - earlier.key
        later_t_diff = later.key - timestamp
        return (earlier_t_diff * later.data[key] +
                later_t_diff * earlier.data[key]) / total_t_diff

    def entries_with_key(self, key : Var,
                         earliest_time : float = 0,
                         latest_time : float = None,
                         cache : Optional[SearchCache] = None) \
                         -> Iterable[Entry[ValuesType]]:
        """Returns an iterator giving all entries with a value for <key>,
           optionally in a limited timespan.
           <cache> will be set to the first match."""
        if cache is None:
            cache = SearchCache()
        def predicate(entry):
            return key in entry.data
        is_first = True
        while True:
            next_entry = self.get_entry_at_time(earliest_time,
                                                pick=IndexedDict.PICK_HIGHER,
                                                predicate=predicate,
                                                cache=cache)
            if next_entry is None:
                return # Ends the iterator
            if latest_time is not None and \
               next_entry.key > latest_time:
                return # Ends the iterator
            if is_first:
                # Do successive searches on a copy, to preserve the
                # location of the first match for the calling <cache>.
                cache = cache.copy()  #type: ignore
                is_first = False
            # The next match must come after the current one
            cache.lowest_ix += 1  #type: ignore
            yield next_entry

    def all_key_values(self, key : Var,
                       earliest_time : float = 0,
                       latest_time : float = None,
                       cache : SearchCache = None):
        """Returns an iterator only with the values of <key>. A time range may
           optionally by specified."""
        if cache is None:
            cache = SearchCache()
        for entry in self.entries_with_key(key, earliest_time,
                                           latest_time, cache):
            yield entry.data[key]

T = TypeVar('T')

class Processor(ABC, Generic[T]):
    """A 'processor' is a subclass that changes or adds one or more
       key-values pairs to a log entry . Used by ProcessedValuesLog.
    """
    def process(self, log : IndexedDict[T],
                entry : Entry[T], mutable : bool) -> Optional[Entry[T]]:
        """If the processor changes the entry, return the new entry. Return
           None if no change is done. If <mutable> is true, change the
           original <entry> instead of making a copy. <log> is the
           original log, without the processor affecting the previous
           entries.  Guaranteed to be called in chronological order
           for all entries.
        """
        pass

# The search cache requires each process() call to use a later entry.
class SlidingWindowProcessor(Processor[ValuesType]):
    """Calculate <target_key> for an entry from all values of <origin_key>
       stretching <window_size_sec> seconds back in time from the
       current entry.
    """
    def __init__(self, origin_key, window_size_sec : float,
                 target_key, target_fn):
        """<target_fn> takes an iterator of <origin_key> values and returns a
           single value."""
        self.origin_key = origin_key
        self.window_size_sec = window_size_sec
        self.target_key = target_key
        self.target_fn = target_fn
        self.search_cache = SearchCache()
        #self.lowest_ix = 0  #Optimization to avoid searching from the beginning
    #To support non-appending log changes:
    #def reset(self):
    #    self.search_cache = SearchCache()
    def process(self, log, entry, mutable : bool):
        if not self.origin_key in entry.data:
            return None   #No update of the watched key
        ts = entry.key
        values = log.all_key_values(key = self.origin_key,
                                    earliest_time = ts - self.window_size_sec,
                                    latest_time = ts,
                                    cache = self.search_cache)
        target_value = self.target_fn(values)
        if not mutable:
            entry = entry.copy()
            entry.data = entry.data.copy()
        entry.data[self.target_key] = target_value
        return entry

# Improvement: Observe the Processors and recalculate this ValuesLog
# whenever a Processor changes, creating a new revision.
class ProcessedValuesLog(ValuesLog):
    """Replicates a ValuesLog, but adds extra key-value pairs by using
       Processors. Note that each Processor will see the entry as
       output from the last Processor.
    """
    def __init__(self, source : ValuesLog, scheduler : Scheduler):
        ValuesLog.__init__(self)
        self._source_log = source
        self._processed_state = ListState()
        source.add_observer((scheduler, self._on_log_changed),
                            initial_notify=True)
        self._processors : List[Processor] = []

    def add_processor(self, processor : Processor):
        assert processor not in self._processors
        self._processors.append(processor)

    def _on_log_changed(self):
        diff = self._source_log.update_state(self._processed_state)
        if diff.is_empty():
            return  # Avoid triggering this Observable
        if diff.mutations:
            # Salvaging previously calculated entries is not supported yet.
            # Recalculate all
            diff = self._processed_state.as_diff()
            # The history is always the same; even the same object
            self._history = self._source_log._history
            self._revision = self._source_log._revision
            self._entries = []
            # Fall through

        # All changes are appended entries
        for entry in self._source_log.diff_to_entries(log_diff):
            copied = False
            for processor in self._processors:
                # If one processor has copied the entry, other
                # processors don't need to (communicated as
                # mutable=True)
                new_entry = processor.process(self._source_log,
                                              entry, mutable=copied)
                if new_entry:
                    copied = True
                    entry = new_entry
            self._append_entry(entry)
        self.notify_observers()

# The type of the data for all ObjectLog entries
ObjectsData = Dict[Oid, Dict[Var, Any]]

class ObjectsLog(Log[ObjectsData], ABC):
    """This is the base class of all log classes where the data of each
       entry is a map from object id to [map from symbol to value].
       (oid -> ( symbol -> Any ) ). Values are native Python values,
       not pyObjects.
    """
    def __init__(self):
        Log.__init__(self)
    get_entry_at_time = indexeddict.SparseIndexedDict.key_to_entry
    @abstractmethod
    def all_objects(self) -> Iterable[Oid]:
        pass
    @abstractmethod
    def get_valueslog(self, objectId : Oid) -> Optional[ValuesLog]:
        pass

class MutableObjectsLog(ObjectsLog):
    """A source where data from multiple objects can be mixed. This
       class is the full log but also creates a ValueLog for each
       encountered object.
    """
    def __init__(self):
        ObjectsLog.__init__(self)
        # Maintain one ValuesLog for each objectId occurring in this log
        self.values_logs : Dict[Oid, ValuesLog] = {}

    def all_objects(self) -> Iterable[Oid]:
        return self.values_logs.keys()

    def get_valueslog(self, objectId : Oid) -> Optional[ValuesLog]:
        return self.values_logs.get(objectId, None)

    def _append_entry(self, entry : Entry[ObjectsData]):
        "<entry> must follow the ObjectsLog data format"
        Log._append_entry(self, entry)
        for (oid, valuemap) in entry.data.items():
            if oid in self.values_logs:
                valueslog = self.values_logs[oid]
            else:
                self.values_logs[oid] = valueslog = ValuesLog(oid)
            # (Could save RAM by using a special ValuesLog
            # implementation that constructs the entry when requested)
            valueslog.append_data(entry.key, data = valuemap,
                                  source={id(self): entry.log_ix[id(self)]})

    def append_data(self, oid_to_valuemap : ObjectsData,
                    timestamp : float = None,
                    source:Dict[int,int] = None):
        if timestamp is None:
            timestamp = time.time()
        entry : Entry[ObjectsData] = Entry(key=timestamp,
                                           data = oid_to_valuemap,
                                           source = source)
        self._append_entry(entry)
        self.notify_observers()

    def register_message(self, msg, timestamp : Timestamp):
        "Used as callback for object subscription"
        if msg['a'] != 'rep':
            print('ObjectsLog.register_message() ignoring non-report')
            return
        self.append_data(msg['map'], timestamp)


class LocalizedLog(ValuesLog):
    """Cleans up reports to guarantee that all reports have lat and lon
       (and alt?). Filters out reports where no lat or lon are
       specified close in time. Lat and lon are simply copied to
       Reports near in time, instead of some more realistic
       interpolation in time.
    """
    def __init__(self, source : ValuesLog, scheduler : Scheduler):
        ValuesLog.__init__(self)
        self._source : ValuesLog = source
        self._last_lat_entry = None
        self._last_lon_entry = None

        #lat and lon are considered non-changing up to this period (in
        #seconds) where there's no more current data, to allow
        #changing the report timestamp
        self._max_delta_time = 5

        #self._last_alt_report = None
        self._processed_state = ListState()
        self._source.add_observer((scheduler, self.on_log_change),
                                  initial_notify=True)

    def on_log_change(self):
        diff = self._source.update_state(self._processed_state)
        if diff.mutations:
            # Some entries changed. Recalculate all of them, for simplicity.
            diff = self._processed_state.as_diff()
            self._last_lat_entry = None
            self._last_lon_entry = None

        # For any report that lacks lat or lon, search for this data
        # in reports with up to <delta_time> time difference.
        # (A more advanced version could interpolate between lat/lon points,
        #  and use spd/wdir for extrapolation)
        any_change = False
        for entry in self._source.diff_to_entries(diff):
            valuemap = entry.data
            if not ('lat' in valuemap or 'lon' in valuemap):
                continue
            ts = entry.key
            #Save new values and clear obsolete values:
            if 'lat' in valuemap:
                self._last_lat_entry = entry
            elif (self._last_lat_entry and
                self._last_lat_entry.key < ts - self._max_delta_time):
                self._last_lat_entry = None
            if 'lon' in valuemap:
                self._last_lon_entry = entry
            elif (self._last_lon_entry and
                self._last_lon_entry.key < ts - self._max_delta_time):
                self._last_lon_entry = None
            if 'lat' in valuemap and 'lon' in valuemap:
                self._append_entry(entry)  #No need to make copy
                any_change = True
                continue

            # Don't modify the original:
            valuemap = valuemap.copy()
            #Fill in missing values or abort if any value can't be filled in:
            if 'lat' in valuemap:
                if 'lon' in valuemap:
                    pass
                elif self._last_lon_entry is not None:
                    valuemap['lon'] = self._last_lon_entry.data['lon']
                else:
                    continue  #Ignore this entry
            if 'lon' in valuemap:
                if 'lat' in valuemap:
                    pass
                elif self._last_lat_entry is not None:
                    valuemap['lat'] = self._last_lat_entry.data['lat']
                else:
                    continue  #Ignore this entry

            new_entry = {'timestamp': ts, 'data': valuemap, 'series_ix': {},
                         'msg': entry}
            self._append_entry(new_entry)
            any_change = True

        if any_change:
            self.notify_observers()


ObjectsOrValuesLog = Union[ObjectsLog, ValuesLog]

# Generalize to CombinedIndexedDict?
class CombinedLog(ObjectsLog):
    """Combines multiple source Logs into one sorted view of the entries
       of all source logs. Does not merge entries with identical
       timestamps.

       What logs to use as sources is stored in an ObsSet. That
       means the same set of logs can be used in multiple places,
       automatically refreshing the CombinedLog and other uses when
       logs are added or removed.
    """
    def __init__(self, scheduler : Scheduler,
                 log_set : Optional[ObsSet[ObjectsOrValuesLog]] = None):
        """<log_set> is an ObsSet of Logs (both ObjectsLog and
           ValuesLog are supported). If None, a new ObsSet is
           created.
        """
        ObjectsLog.__init__(self)
        self._scheduler = scheduler
        #Tells what source state this CombinedLog is updated to, and
        #also which source logs it's observing:
        self._source_logs_state : Dict[ObjectsOrValuesLog, ListState] = {}
        if log_set is None:
            log_set = MutableObsSet()

        self._source_log_set = log_set
        log_set.add_observer((self._scheduler, self._on_log_set_change),
                             initial_notify=True)
        #self._changed_source_logs = set()
        self._change_accumulator : SimpleScheduler[Log] = SimpleScheduler()
        self._change_accumulator.add_observer((scheduler, self._on_log_change))
        #relations.job_may_trigger(self._on_log_set_change, ...

    def _on_log_set_change(self):
        "Called when the ObsSet of source logs changed"
        subscribed_set = set(self._source_logs_state.keys())
        # Logs that this CombinedLog currently observes, but are no longer in
        # self._source_log_set:
        for log in subscribed_set.difference(self._source_log_set.get()):
            log.remove_observer((self._change_accumulator, log))
            del self._source_logs_state[log]
            raise NotImplementedError("TODO: Implement removing log entries from CombinedLog")

        # New logs to observe:
        for log in self._source_log_set.difference(subscribed_set):
            #log.add_observer(self._log_observer, initial_notify=True)
            log.add_observer((self._change_accumulator, log),
                             initial_notify=True)
            self._source_logs_state[log] = ListState()

    def add_source(self, log : Log):
        """Adds the log to the source set.  The set of logs can also be
           changed by calling the ObsSet directly.
        """
        assert isinstance(self._source_log_set, MutableObsSet)
        #Will indirectly invoke _on_log_set_change of this object
        self._source_log_set.add(log)

    def all_objects(self):
        "Returns the set of all objectIds in this Log"
        all = set()
        for log in self._source_log_set:
            all.update(log.all_objects())
        return all

    def get_valueslog(self, objectId : Oid) -> Optional[ValuesLog]:
        # A proper implementation should maybe return a CombinedLog of
        # all logs where objectId occurs. For now, just warn if there
        # are multiple ones.
        found_log = None
        for log in self._source_log_set:
            if objectId in log.all_objects():
                if found_log:
                    print("Warning: CombinedLog.get_valueslog() matches multiple logs")
                found_log = log
        if found_log is None:
            return None
        if isinstance(found_log, ValuesLog):
            return found_log
        return found_log.get_valueslog(objectId)

    def _on_log_change(self):
        "Callback on <scheduler> when any of the source logs have changed"
        changed_logs = self._change_accumulator.pop_all_jobs()
        #logs_and_diffs = []
        for log in changed_logs:
            #diff = log.update_state(self._source_logs_state[log])
            #logs_and_diffs.append( (log, diff) )
            self._update_single_log(log)

        # The above is inefficient when multiple source logs have
        # changed and creates an unnecessary amount of revisions.
        #
        # The best solution would be to start by creating a sorted
        # list of all additions from all logs, then apply that to this
        # CombinedLog as a change() call.

        self.notify_observers()

    def _update_single_log(self, log):
        assert (log in self._source_logs_state)
        diff = log.update_state(self._source_logs_state[log])
        if diff.is_empty():
            return
        # (Could divide the changes into one insertion and one append)
        first_new_entry = log.ix_to_entry(diff.first_new_ix)
        later_entry = self.get_entry_at_time(first_new_entry.key,
                                             pick=IndexedDict.PICK_HIGHER)
        if later_entry is None:
            # No later entry, so just append all new source entries
            for entry in log.diff_to_entries(diff):
                if isinstance(log, ValuesLog):
                    # Convert from ValuesLog to ObjectsLog entry
                    entry = entry.copy()
                    entry.data = {log.object_id: entry.data}
                self._append_entry(entry)
            return

        #if not (later_entry.key >= first_new_entry.key):
        #    print('later_entry', later_entry)
        #    print('first_new_entry', first_new_entry)
        assert (later_entry.key >= first_new_entry.key)

        # There's at least one younger entry already present, so this
        # is an insertion. For simplicity, make a single Mutation
        # event. A more sophisticated solution could generate up to a
        # certain number of Mutations, minimizing the number of existing
        # entries marked as changed.
        first_changed_ix = self.entry_to_ix(later_entry)

        #if not (self.ix_to_entry(first_changed_ix-1).key <=
        #        first_new_entry.key):
        #    # Assertion will fail
        #    print('first_changed_ix', first_changed_ix)
        #    print('first_new_entry', first_new_entry)
        assert (first_changed_ix == 0 or \
                self.ix_to_entry(first_changed_ix-1).key <= \
                first_new_entry.key)

        cache = SearchCache(first_changed_ix)   # Speed up search
        temp_cache = SearchCache(0)  #Avoid making a new copy every iteration
        inserted = 0
        for entry in log.diff_to_entries(diff):
            if isinstance(log, ValuesLog):
                # Convert ValuesLog entry to ObjectsLog entry
                entry = entry.copy()
                entry.data = {log.object_id: entry.data}
            temp_cache.lowest_ix = cache.lowest_ix
            # Insert the entry chronologically
            later_entry = self.get_entry_at_time(entry.key,
                                                 pick=IndexedDict.PICK_HIGHER,
                                                 cache=temp_cache)
            if later_entry is None:
                #TODO: Append all remaining new entries instead
                self._append_entry(entry)
                 #Will cause the next get_entry_at_time() to return
                 #quickly without a match
                cache.lowest_ix = len(self._entries)
                continue

            assert (later_entry.key >= first_new_entry.key)
            # "inserted" corrects indexing until corrected when all
            # entries are inserted
            insert_ix = self.entry_to_ix(later_entry) + inserted
            if insert_ix > 0 and self.ix_to_entry(insert_ix-1).key > \
               entry.key + 0.0001:
                #    print('Entry', entry)
                #    print('later_entry', later_entry)
                #    print('later_entry with corrected ix', self.ix_to_entry(insert_ix))
                #    print('insert_ix', insert_ix)
                #    print('Earlier entry', self.ix_to_entry(insert_ix-1))
                assert (False)
            assert (self.ix_to_entry(insert_ix).key >= entry.key)
            #Inserts <entry> between insert_ix-1 and insert_ix:
            self._entries.insert(insert_ix, entry)
            # The next entry must sort after this one, as the source
            # log is ordered.
            cache.lowest_ix = insert_ix + 1
            inserted += 1

        # Update all indices that may have changed
        for ix in range(first_changed_ix, len(self._entries)):
            self._entries[ix].log_ix[id(self)] = ix

        old_revision = self.revision.get()
        new_revision = self.revision.get() + 1
        new_count = len(self._entries) - first_changed_ix
        old_count = new_count - diff.number_of_new_entries()
        mutation = Mutation(index=first_changed_ix, remove=old_count,
                            insert=new_count)
        assert (old_revision not in self._history)
        self._history[old_revision] = (new_revision, mutation)
        # Make all observers aware of the Mutation
        self.revision.set(new_revision)


######################################################################

# Could also just maintain a list of indices into <source_log>
class ValuesFilterDataSeries(DataSeries):
    "Present a view of the source log with only a single value"
    def __init__(self, scheduler : Scheduler, source_log : ValuesLog, key: str):
        super().__init__()
        self._source_log = source_log
        self._scheduler = scheduler
        self._key = key
        self._processed_state : ListState = ListState()
        self._source_log.add_observer( (scheduler, self._on_source_change) )
        relations.job_may_trigger(self._on_source_change, self)
        #self._entries = []
    def _on_source_change(self):
        diff = self._source_log.update_state(self._processed_state)
        # TODO: Handle mutations
        change = False
        for entry in log.diff_to_entries(diff):
            if self._key in entry.data:
                entry.log_ix[id(self)] = len(self._entries)
                value = entry.data[self._key]
                # Value is not guaranteed to be of EntryData type!
                self._append_entry(Entry(entry.key, value))
                change = True
        if change:
            self.notify_observers()
