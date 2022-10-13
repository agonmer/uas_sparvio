"Pipeline sink to write an IndexedDict to a file"

import os
from typing import *

from reactive.observable import Scheduler, relations, ObsVar, ListState
from reactive.indexeddict import IndexedDict, SparseIndexedDict
from . import log

class FileWriter:
    def __init__(self, scheduler : Scheduler[Callable],
                 source: IndexedDict, path : ObsVar[Optional[str]],
                 pickle=str):
        "Write all entries of <source> to <path>, expressing all data using <pickle>"
        self._source = source
        self._path = path
        self._source.add_observer( (scheduler, self._on_source_change) )
        self._path.add_observer( (scheduler, self._on_path_change) )
        self._source_state = ListState()  # Processed source state
        self._path_value = self._path.get()  # Current path
        if self._path_value and os.path.exists(self._path_value):
            os.remove(self._path_value)
        self._pickle = pickle
        relations.job_may_post_job(self._on_path_change, self._on_source_change)
        scheduler.post_job(self._on_source_change)

    def _on_source_change(self):
        if not self._path_value:
            return  # The path to write isn't known yet
        diff = self._source.update_state(self._source_state)
        if diff.mutations:
            # Rewrite the file from the start for simplicity
            if os.path.exists(self._path_value):
                os.remove(self._path_value)
            diff = self._source.as_diff()
        with open(self._path_value, 'a') as f:
            for entry in self._source.diff_to_entries(diff):
                if isinstance(entry.key, int):
                    f.write("%d; %s\n" % (entry.key, self._pickle(entry.data)))
                else:
                    f.write("%f; %s\n" % (entry.key, self._pickle(entry.data)))

    def _on_path_change(self):
        new_path = self._path.get()
        if new_path == self._path_value:
            return
        if self._path_value and os.path.exists(self._path_value):
            os.remove(self._path_value)
        self._path_value = new_path
        self._source_state.reset()
        self._on_source_change()

def load_file(path, unpickle=eval) -> SparseIndexedDict:
    """Load an IndexedDict previously saved by a FileWriter. The result is
       a mutable SparseIndexedDict, allowing further changes (which
       might not have been possible with the original source of
       FileWriter.
    """
    dic : SparseIndexedDict = SparseIndexedDict()
    with open(path, 'r') as f:
        for line in f.readlines():
            (key, data) = line.split(';', 1)
            if '.' in key:
                num_key = float(key)
            else:
                num_key = int(key)
            data = unpickle(data)  #Danger!
            dic._append_entry(log.Entry(key=num_key, data=data))
        # No need to notify_observers() as <dic> can't have any observers yet
    return dic
