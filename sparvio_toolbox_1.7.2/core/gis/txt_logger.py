# TxtLogger: Simple saving of an ObjectsLog to file, by writing one
# message per text line

import os

from sspt.type_hints import *
from .log import Log, ObjectsLog
from reactive.eventthread import EventThread, CooldownTimer, immediate_scheduler
from reactive.observable import ListState

class TxtLogger(EventThread):
    "Simple saving of an ObjectsLog to file, by writing one message per text line"
    def __init__(self, path : str, log : ObjectsLog,
                 write_delay_sec : float = 1,
                 write_interval_sec : float = 5):
        EventThread.__init__(self, name="TxtLogger")
        self.path = path
        self.log = log
        # Could use a CooldownScheduler instead
        self._timer = CooldownTimer(self,
                                    self._write,
                                    delay_sec = write_delay_sec,
                                    cooldown_sec = write_interval_sec,
                                    flush_on_exit = True)
        self._processed_log_state = ListState()
        self.log.add_observer( (immediate_scheduler, self._timer.trigger) )

        if os.path.isfile(self.path):
            print('Warning: Appending to already existing file', path)

    def _write(self):
        log_diff = self.log.update_state(self._processed_log_state)
        if log_diff.mutations:
            # If already written entries change, write the whole log
            # from the start
            try:
                os.remove(self.path)
            except:
                pass
            log_diff = self.log.get_state().as_diff()
            # Fall through to the next 'if'

        if log_diff.is_appended():
            with open(self.path, 'a') as f:
                for entry in self.log.diff_to_entries(log_diff):
                    f.write(str(entry))
                    f.write('\n')

    def file_size(self):
        try:
            return os.path.getsize(self.path)
        except:
            return 0
