from typing import *
from reactive.observable import Scheduler, ListState
from reactive.indexeddict import Entry
from .log import ValuesLog, ObjectsLog

class MergedValuesLog(ValuesLog):
    """Merges the readings of all objects in an ObjectsLog, throwing away
       the information on objects. When a parameter is included in
       multiple objects in one row, the lower objectid is
       prioritized.
    """
    def __init__(self, scheduler : Scheduler, source : ObjectsLog):
        super().__init__()
        self._source = source
        self._source.add_observer((scheduler, self._on_change))
        self._source_state = ListState()

    def _on_change(self):
        diff = self._source.update_state(self._source_state)
        if diff.mutations:
            # Some entries changed. Recalculate all of them, for simplicity.
            self.clear()
            diff = self._source_state.as_diff()

        changed = False
        for entry in self._source.diff_to_entries(diff):
            new_entry = Entry(key = entry.key,
                              data = {},
                              source = entry.log_ix)
            all_keys = set()
            for (oid, _map) in entry.data.items():
                all_keys.update(_map.keys())
            for key in all_keys:
                # Pick the lowest oid that has the key
                for oid in sorted(entry.data.keys()):
                    if key in entry.data[oid]:
                        new_entry.data[key] = entry.data[oid][key]
                        break
            self._append_entry(new_entry)
            changed = True

        if changed:
            self.notify_observers()
