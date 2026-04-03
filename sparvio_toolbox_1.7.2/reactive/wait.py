
import threading  # For Lock
from typing import *

from .observable import Observable, ObsVar, Observer, immediate_scheduler

######################################################################
## Thread wait

def wait_for(var : ObsVar,
             timeout : float = -1,
             predicate : Optional[Callable[[Any], bool]] = None):
    """If <predicate> is defined, waits for <var> to fulfill <predicate>,
       otherwise waits for <var> to notify its observers. Returns True
       when this happens, or False if it didn't happe in <timeout>
       seconds. If <timeout> is not specified, never timeout. Since
       this thread will be blocked, some other thread must change
       <var>.
       To wait for <var> to become true, use predicate=bool.
    """
    if predicate is not None and predicate(var.get()):
        return
    lock = threading.Lock()
    lock.acquire()
    def on_change():
        if predicate is None or predicate(var.get()):
            lock.release()
    observation = (immediate_scheduler, on_change)
    var.add_observer(observation)
    predicate_was_fulfilled = lock.acquire(blocking=True, timeout=timeout)
    var.remove_observer(observation)
    return predicate_was_fulfilled

def wait_for_true(var : ObsVar, timeout : float = -1):
    return wait_for(var, timeout, bool)

# Needed for more generally supporting Observable, even when wait_for() exists?
def wait_for_notify(observable : Observable, timeout : float = -1):
    """Returns True when <observable> notifies its observers, or False if
       that doesn't happen in <timeout> seconds. If <timeout> is not
       specified, never timeout. Since this thread will be blocked,
       some other thread must trigger <observable>. Useful to wait
       synchronously for variables to be updated.
    """
    lock = threading.Lock()
    lock.acquire()  # Will be released in on_change()
    def on_change():
        lock.release()
    observation = (immediate_scheduler, on_change)
    observable.add_observer(observation)
    got_notification = lock.acquire(blocking=True, timeout=timeout)
    observable.remove_observer(observation)
    return got_notification

def wait_for_any_notify(observables : Iterable[Observable],
                        timeout : float = -1):
    """Like wait_for_notify(), but waits for a notification from any of a
       number of observables.
    """
    lock = threading.Lock()
    lock.acquire()  # Will be released in on_change()
    def on_change():
        lock.release()
    observation = (immediate_scheduler, on_change)
    for observable in observables:
        observable.add_observer(observation)
    got_notification = lock.acquire(blocking=True, timeout=timeout)
    for observable in observables:
        observable.remove_observer(observation)
    return got_notification


######################################################################
# Async wait

import asyncio

#Could be changed to a function, on the pattern of wait_for_notify() and wait_for()
class AsyncObserver:
    "Allows an asyncio task to await some Observable to notify it"
    def __init__(self):
        self._event = asyncio.Event() # Set when this object has been triggered
        self._lock = threading.Lock()
    def get_observer(self) -> Observer:
        "Returns the Observer to use with Observable.add_observer()"
        return (immediate_scheduler, self.trigger)
    def trigger(self):
        "Call from any thread to notify the observer, waking up the asyncio task"
        with self._lock:
            self._event.set()

    async def wait(self, timeout=None, clear=True) -> bool:
        "Returns true immediately if this Observer has already been notified. Otherwise delay until notified and return true. If not notified within <timeout> sec, return false. Raises CancelledError if the task is cancelled while waiting."

        # TODO: asyncio.Event is not thread-safe
        if timeout is not None:
            try:
                await asyncio.wait_for(self._event.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                pass
        else:
            await self._event.wait()

        with self._lock:
            result = self._event.is_set()
            if clear:
                self._event.clear()
        return result
