# IndexedDict is an ObsList where each element has a float key for
# lookup or interpolation

from typing import *
from .observable import *
from abc import ABC, abstractmethod

class SearchCache:
    """Simple structure that can be changed within calls. Keeps track of a
       log index in-between successive forward searches, to avoid
       search a log all the way from the beginning when the
       approximate index of the sought entry is already known.
       A cache is a guide to optimizing searches, not a definitive
       pointer to the next search result; searches should use another
       method to select the matches.
    """
    def __init__(self, lowest_ix=0):
        #The index for the first log entry that can be a match
        self.lowest_ix = lowest_ix
    def copy(self):
        return SearchCache(self.lowest_ix)

EntryData = TypeVar('EntryData')

# Changes access from entry['data'] to entry.data
class Entry(Generic[EntryData]):
    "Data and metadata for an index in an IndexedDict"
    # Using objects with __slots__ saves memory over using a regular dict
    __slots__ = ('key', 'log_ix', 'data')
    key : float
    log_ix : Dict[int, int]
    data : EntryData
    def __init__(self, key : float, data : EntryData,
                 source:Dict[int,int] = None):
        "<source>, if set, tells that this Entry is derived from a specific entry in another IndexedDict."
        self.key = key
        # Mapping from id(IndexedDict) to the index in that dict of this entry
        if source:
            self.log_ix = source
        else:
            self.log_ix = {}
        self.data = data
    def get_ix(self, dic : 'IndexedDict') -> Optional[int]:
        "Returns the index of this entry in IndexedDict <dic>"
        return self.log_ix.get(id(dic), None)
    def copy(self):
        return Entry(self.key, self.data, source=self.log_ix)
    def __str__(self):
        return "Entry(key=%s, data=%s, log_ix=%s)" % \
            (self.key, str(self.data), str(self.log_ix))
    def __repr__(self):
        return self.__str__()

# Also see https://code.activestate.com/recipes/577197-sortedcollection/
class IndexedDict(ObsList[Entry[EntryData]], ABC, Generic[EntryData]):
    """Mix between a list and a dictionary. All keys are float. Each entry
       is assigned an index number based on the ordering of the keys
       (so it's a sorted list). Entries can be looked up from index,
       key or closest matching key.

       An *entry* is a dict for each key, with keys {key, value,
       log_ix}. entry['value'] = value = the user-defined value of the
       key. Entries can be used by multiple IndexedDicts. Entry values
       therefore need to be be immutable.

       The change detection scheme is optimized for appending new data
       and starting over from scratch, and infrequent mutations
       (insert/delete/change of existing entries). Subclasses can
       optionally optimize mutations with extra code.
       The Observable is triggered for any change.

       An IndexedDict where the keys are timestamps is a Log (TimeSeries?).
       An IndexedDict where the values are floats is a DataSeries.
    """

    def __init__(self):
        super().__init__()
        #self.smallest_key = ObsVar()  # Override
        #self.biggest_key = ObsVar()  # Override

    # Possible values for <pick> in call to key_to_entry():
    PICK_EXACT = 0    # Accepts no other value
    PICK_CLOSEST = 1  # Pick the closest in time of earlier or later value
    PICK_LOWER = 2
    PICK_HIGHER = 3    # Pick the oldest entry that's newer than <key>
    @abstractmethod
    def key_to_entry(self, key:float,
                     pick:int = PICK_CLOSEST,
                     predicate : Optional[Callable[[Entry[EntryData]], bool]] = None,
                     cache:Optional[SearchCache] = None) -> Optional[Entry[EntryData]]:
        pass

    #def lookup_key_value(self, ...) -> Tuple[float, Optional[EntryData]]:
    #    entry = self.lookup_entry(...)
    #    if entry is None:
    #        return None
    #    return (entry.key, entry.data)

    def ix_to_key_value(self, ix: int) -> Tuple[float, EntryData]:
        entry = self.ix_to_entry(ix)
        return (entry.key, entry.data)

    #def __enter__(self): # -> ContextManager ?
    #    "Locks the revision; appending will continue to be possible, but mutations from another thread will be blocked until __exit__()."
    #    pass


class SparseIndexedDict(IndexedDict[EntryData], Generic[EntryData]):
    """A mutable IndexedDict that stores the data as a list of
       Entry. Named 'sparse' since RAM is only used for the present
       keys (since any keys may occur, this is irregular data), in
       contrast to pre-allocating all keys with some range and
       interval (regular data).
    """
    class CountObsVar(ObsVar):
        def __init__(self, dic : 'SparseIndexedDict'):
            super().__init__()
            self._dic = dic
        def get(self):
            return len(self._dic._entries)
    def __init__(self):
        super().__init__()
        self._entries : List[Entry[EntryData]] = []
        # Automatically triggered whenever this object is triggered:
        self.count : ObsVar[int] = \
            SparseIndexedDict.CountObsVar(self).trigger_on_observable(self)
        self.revision = BasicObsVar(0)

    def _append_entry(self, entry : Entry[EntryData]):
        """For use by inheriting classes. The caller should also call
           notify_observers() when all entries have been added.
        """
        local_ix = len(self._entries)
        entry.log_ix[id(self)] = local_ix
        self._entries.append(entry)

    def add(self, key : float, data : EntryData):
        "Add a single entry and notify observers (not efficient for batch operations)"
        entry = Entry(key, data)
        if len(self._entries) == 0 or key >= self._entries[-1].key:
            self._append_entry(entry)
        else:
            raise NotImplementedError("Implement insertion")
        self.notify_observers()

    def clear(self):
        raise NotImplementedError("Implement clear()")

    def ix_to_entry(self, ix : int) -> Entry[EntryData]:
        #Negative means indexing from the end, which would probably be
        #confusing to allow and let bugs through
        assert ix >= 0
        return self._entries[ix]

    def all_entries(self) -> Iterable[Entry[EntryData]]:
        "Iterate over all entries"
        return self._entries

    def get(self):
        return self._entries

    def __iter__(self) -> Iterator[Entry[EntryData]]:
        return self._entries.__iter__()

    def ix_to_data(self, ix : int) -> EntryData:
        #Negative means indexing from the end, which would probably be
        #confusing to allow and let bugs through
        assert ix >= 0
        return self._entries[ix].data

    def entry_to_ix(self, entry : Entry[EntryData]) -> Optional[int]:
        return entry.get_ix(self)

    def key_to_entry(self, key:float,
                     pick:int = IndexedDict.PICK_CLOSEST,
                     predicate : Optional[Callable[[Entry[EntryData]], bool]] = None,
                     cache:Optional[SearchCache] = None) -> Optional[Entry[EntryData]]:
        """Looks up entry from key. If there's no exact match, picks an
           entry depending on value of <pick>.
           If a predicate is supplied, it must be true for an entry to
           be considered.  <cache> will be updated with the match, if
           supplied.  Returns an entry or None.
        """
        if len(self._entries) == 0:
            return None
        if predicate is None:
            predicate = lambda entry: True
        if cache is None:
            lowest_ix = 0
            def register(ix):
                return self._entries[ix]  #No registering
        else:
            lowest_ix = cache.lowest_ix
            def register(ix):
                cache.lowest_ix = ix
                return self._entries[ix]
        # TODO: Optimize by binary search (interval halving)
        smaller_ix = None
        later_ix = None
        for ix in range(lowest_ix, len(self._entries)):
            if not predicate(self._entries[ix]):
                continue
            test_ts = self._entries[ix].key
            if test_ts == key:
                #Use exact matches regardless of matching policy
                return register(ix)
            if test_ts < key:
                smaller_ix = ix
                continue
            if test_ts > key:
                later_ix = ix
                break
        if smaller_ix is None and later_ix is None:
            return None
        # Found a smaller or larger value
        if pick == IndexedDict.PICK_EXACT:
            return None  #No exact match found
        if pick == IndexedDict.PICK_LOWER:
            if smaller_ix is None:
                return None
            return register(smaller_ix)
        if pick == IndexedDict.PICK_HIGHER:
            if ix == smaller_ix:
                return None
            return register(ix)
        if pick == IndexedDict.PICK_CLOSEST:
            if smaller_ix is None or ix == smaller_ix:
                # All entries are either earlier or later.
                return register(ix)
            later_diff = self._entries[ix].key - key
            earlier_diff = key - self._entries[smaller_ix].key
            if later_diff < earlier_diff:
                return register(ix)
            return register(smaller_ix)

        raise Exception("Unexpected value for 'pick'")

    def __len__(self):
        return len(self._entries)

    def __getitem__(self, index):
        "Return a value based on index"
        return self._entries[index]

class DataSeries(IndexedDict[float]):
    "The data of each entry is a single numeric value"
    def interpolate(self, key : float) -> Optional[float]:
        "Does a linear interpolation of the value at point <key>"
        pass  #TODO: See ValuesLog.interpolate_value

class LogPrinter:
    "For debug. Simply prints any data added to the log (can actually work for all ObsList)."
    def __init__(self, log : IndexedDict, scheduler : Scheduler,
                 retroactive = False):
        "<retroactive> prints also entries added before creating this LogPrinter"
        super().__init__()
        self._log = log
        if retroactive:
            self._processed_state = ListState()
        else:
            self._processed_state = ListState(log)
        self._log.add_observer((scheduler, self.on_change),
                               initial_notify=retroactive)
    def on_change(self):
        "Bulk process new entries to a Log"
        diff = self._log.update_state(self._processed_state)
        if diff.mutations:
            # Can't revoke printed text...
            print('Changes: ', diff.mutations)
        for entry in self._log.diff_to_entries(diff):
            print(entry)
