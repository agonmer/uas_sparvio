# A generic framework for running multiple Python threads with event
# queues. Threads are useful to block for I/O without blocking other
# functionality, to postpone actions like GUI updates and disk writes,
# or just serialize access to a shared resource (like a database, file
# or process).
#
# EventThread makes it easy to dispatch method calls to the correct
# thread. Such calls are non-blocking (i.e. posting a job), optionally
# reporting the eventual return value to a callback, but can also be
# made to block the calling thread using blocking_call().
#
# Threads can either run user code that optionally checks for incoming
# events, or be completely reactive and only run when an event is enqueued.
#
# Each thread can have any number of one-shot and recurring timers.
#
# Call eventthread.stop() to ask all threads to exit when the program
# quit, to avoid hanging the program due to some still-running thread.

# Implements observable.Scheduler as a thread

# Needed for Python 3.7 to accept the annotation of weak_cleanup_hooks.
from __future__ import annotations  # Requires Python >= 3.7

import threading
import queue
import traceback
import time
import weakref
from typing import *
from abc import ABC, abstractmethod

import logging
log = logging.getLogger("EventThread")

from .observable import *

verbose = False
debug_stop_function = True

# The 'Protocol' features starting with Python 3.8 would make it
# unnecessary for all classes to inherit HasCleanup, but Anaconda only
# supports Python 3.7.
class HasCleanup(ABC):  #(Protocol)
    @abstractmethod
    def _on_cleanup(self) -> None:
        pass
# TODO: Make thread-safe
weak_cleanup_hooks : weakref.WeakSet[HasCleanup] = weakref.WeakSet() # Objects with method _on_cleanup(). Can't keep just Callables, as weakref doesn't work for bound object methods

######################################################################

def print_verbose(text):
    if verbose:
        print(text)

def print_warning(text):
    print('eventthread WARN: ' + text)


######################################################################
# THREAD

def run_in_thread(fn):
    """Decorator for methods of classes inheriting from EventThread. The
       decorator enqueues all calls to the method for serialized
       execution on the EventThread of the object. The call will
       return at once without a return value, before the decorated
       function is run.
    """
    def run(self, *args, **kwargs):
        #Must prepend self in argument list to preserve the object call
        if threading.current_thread() == self._thread:
            return fn(self, *args, **kwargs)
        else:
            self._thread.call(fn, args=(self,) + args, kwargs=kwargs)
    return run

def run_in_thread_blocking(fn):
    "Decorator for methods of classes inheriting from EventThread. Decorator like run_in_thread, but waits for the result and returns it"
    def run(self, *k, **kw):
        #Must prepend self in argument list to preserve the object call
        if threading.current_thread() == self._thread:
            return fn(self, *args, **kwargs)
        _queue = queue.Queue()
        #Must prepend self in argument list to preserve the object call
        self._thread.call(fn, args=(self,) + k, kwargs=kw, result_queue=_queue)
        result = _queue.get(block=True)
        return result
    return run

def blocking_call(fn, *args, **kwargs):
    #If fn is decorated with run_in_thread, make the call synchronous.
    #Otherwise, just call the function
    #TODO! Check if run_in_thread
    #TODO: timeout?
    _queue = queue.Queue()
    kwargs = kwargs.copy()
    kwargs['result_queue'] = _queue
    fn(*args, **kwargs)
    result = _queue.get(block=True)
    return result

# Call start() to make the thread process jobs until stop() is executed
class SchedulerThread(threading.Thread):
    def __init__(self, scheduler : Scheduler[Callable], name=None):
        if name is None:
            name = self.__class__.__name__
        threading.Thread.__init__(self, name=name)
        self._scheduler = scheduler
        self._external_event = threading.Event()
        self._scheduler.add_observer( (immediate_scheduler,
                                       self._on_job_available) )
        self._stop_when_done = False
        self._alive = True
        #Not actually 'alive' until start() is called, but it's safer
        #to register the thread already here
        with EventThread._alive_threads_lock:
            EventThread._alive_threads.append(self)

    def _on_cleanup(self):
        "Last chance to do something when the application is exiting"
        self.stop(cancel_enqueued_jobs=True)

    #def post_job(self, job):
    #Redefine SimpleScheduler.post_job() instead of observing ourselves?
    def _on_job_available(self):
        "Called from any thread when a job is available"
        #Abort sleep (if the thread was waiting for a job)
        self._external_event.set()

    def stop(self, run_enqueued_jobs=False):
        "If <run_enqueued_jobs> is true, the thread will run all enqueued jobs before stopping (including jobs posted while stopping)."
        self._stop_when_done = True
        if not run_enqueued_jobs:
            self._alive = False
        self._external_event.set()
    def setup(self):
        "Override setup() for any custom initial actions to run in the thread"
        pass  #May be overriden

    def run(self):
        "Don't call from user code! run() runs in the thread."
        self.setup()
        while self._alive:
            job = self._scheduler.pop_job() #TODO: Make thread-safe
            if job is None:
                if self._stop_when_done:
                    break
                # Wait for a job
                # TODO: not thread-safe to do this only after pop_job()
                self._external_event.clear()
                self._external_event.wait()
            else:
                job()
        # Now exiting
        with EventThread._alive_threads_lock:
            EventThread._alive_threads.remove(self)


#Should use Thread by composition, not inheritance.
#Could make a separate version that uses the main thread, blocking any other execution.
class EventThread(threading.Thread):
    "Serializes calls to run on a dedicated thread"
    _alive_threads : List[threading.Thread] = []
    _alive_threads_lock = threading.Lock()
    def __init__(self, name=None, scheduler : Scheduler = None): #name
        if name is None:
            name = self.__class__.__name__
        threading.Thread.__init__(self, name=name)
        self._waiter = threading.Event()
        # True when a Thread is running and should be kept alive:
        self._alive = False
        self._queue : queue.Queue = queue.Queue()
        self._timers : Set['Timer'] = set()
        self._timers_lock = threading.Lock()
        self._thread = self  #So run_in_thread() decorator works for child classes
        self._scheduler = scheduler

    def start(self):
        "Call from any thread"
        if not self._alive:
            self._alive = True
            with EventThread._alive_threads_lock:
                EventThread._alive_threads.append(self)
            threading.Thread.start(self)
        return self

    def stop(self):
        "Call from any thread. Any enqueued calls and timers are discarded. Not blocking -- call join() afterwards to wait for termination. A thread can not be restarted after stop(), due to limitation in threading.Thread."
        print_verbose('stop() thread ' + self.name)
        if not self._alive:
            #print_warning('Dont stop already stopped thread ' + self.name)
            return self
        self._alive = False
        with EventThread._alive_threads_lock:
            EventThread._alive_threads.remove(self)
        self._queue.put(None) #Wake from blocking on queue
        with self._timers_lock:
            timers = self._timers.copy()
        for timer in timers:
            timer.stop()
        with self._timers_lock:
            self._timers = set()
        self._waiter.set()    #Abort sleep, if ongoing
        return self

    #def is_alive(self):
    #    return self._alive

    @run_in_thread
    def stop_when_done(self):
        self.stop()

    def call_later(self, fn, args=[], kwargs={}, done_event=None,
                   result_queue : queue.Queue = None):
        "Run via event queue, even if called from the thread itself"
        self._queue.put({'type': 'call', 'fn': fn,
                         'args': args, 'kwargs': kwargs,
                         'done_event': done_event,
                         'result_queue': result_queue})
        self._waiter.set()    #Abort sleep

    def call(self, fn, args=[], kwargs={}, done_event=None,
             result_queue : queue.Queue = None):
        "Enqueue an asynchronous call to run on the thread."
        if threading.current_thread() == self:
            #We're already the correct thread, so execute at once,
            #blocking until finished
            result = fn(*args, **kwargs)
            if result_queue is not None:
                result_queue.put_nowait(result)
            if done_event is not None:
                done_event.set()
            return

        #print 'thread ' + self.name + ' put on queue ' + repr(self._queue)
        self._queue.put({'type': 'call', 'fn': fn,
                         'args': args, 'kwargs': kwargs,
                         'done_event': done_event,
                         'result_queue': result_queue})
        self._waiter.set()    #Abort sleep

    # Call <fn> on the thread after <max_delay>, ignoring duplicate
    # calls during that period. This is useful to avoid reacting
    # multiple times to changes to an observed variable, for example
    # only updating the GUI with the latest reading once when there
    # are rapid changes. (Can replace BufferedObserver)
    #def call_merged(self, fn, max_delay=0.1):
    #    # Could alternatively wait for some kind of trigger to process calls
    #    pass  #TODO

    @run_in_thread_blocking
    def wait_until_processed(self):
        "The caller will block until all other events have been processed"
        pass

    ######################################################################
    ## Internal methods, call only from the thread itself

    def blocking_call(self, fn, args=[], kwargs={}):
        "Run a function call on the thread, but wait and return the result"
        _queue = queue.Queue()
        self.call(fn, args, kwargs, result_queue=_queue)
        result = _queue.get(block=True)
        return result

    def process_once(self, timeout=0):
        "Call from the thread, if the thread runs an event loop. <timeout> is the max amount of time to wait for an event in case none are enqueued. <timeout> = None waits forever, 0 doesn't block."
        try:
            item = self._queue.get(block=True, timeout=timeout)
        except queue.Empty:
            item = None
        if item:
            self._handle_item(item)
            return True
        else:
            return False

    def process_all(self, timeout=0):
        "Call from the thread. Process all enqueued items, or wait for one item"
        is_first = True
        while True:
            try:
                item = self._queue.get(block=False)
            except queue.Empty:
                #No item was waiting
                if not is_first:
                    return
                if timeout is None or timeout > 0:
                    return self.process_once(timeout)
            is_first = False
            self._handle_item(item)

    def wait_for_event(self, timeout):
        "Call from the thread. Sleep is aborted by message. Returns True is an event caused waiting to be aborted"
        #TODO: Doesn't check if a message is already enqueued
        if not self._alive:
            return False
        self._waiter.clear()
        if self._waiter.wait(timeout):
            #No timeout - so an event is available
            return True
        #Timeout waiting for event
        return False

    def sleep(self, seconds):
        "Call from the thread. Only aborted by request to stop(). Check _alive afterwards"
        #TODO: Raise exception in case of stop?
        end_time = time.time() + seconds
        while True:
            self._waiter.clear()
            self._waiter.wait(end_time - time.time())
            if not self._alive or time.time() >= end_time:
                break

    ######################################################################
    ## Methods only used by the framework

    def _add_timer(self, timer : 'Timer'):
        with self._timers_lock:
            self._timers.add(timer)
    def _remove_timer(self, timer : 'Timer'):
        with self._timers_lock:
            if timer in self._timers:
                self._timers.remove(timer)

    def _handle_item(self, item):
        if item is None:
            return  #Probably marker to quit
        if item['type'] == 'call':
            try:
                #print self.name + ' calling ' + item['fn'].__name__
                result = item['fn'](*item['args'], **item['kwargs'])
            except Exception as ex:
                print_warning('Exception in ' + self.name + ' calling ' + item['fn'].__name__ + " " + repr(item['args']) + repr(item['kwargs']))
                traceback.print_exc()
                #How to handle reporting result? Pass on exception in separate return channel?
                return
            if item['result_queue'] is not None:
                item['result_queue'].put_nowait(result)
            if item['done_event'] is not None:
                item['done_event'].set()
        else:
            print_warning('EventThread unknown item ' + repr(item))

    ######################################################################
    ##  Overridable methods

    def setup(self):
        "Override setup() for any custom initial actions to run in the thread"
        pass  #May be overriden

    def run(self):
        "Don't call from user code! run() runs in the thread. This default implementation blocks to execute incoming calls. Subclasses may override run() for custom loop."
        self.setup()
        if self._scheduler is not None:
            self._run_with_scheduler()
        else:
            self._run_without_scheduler()
        print_verbose(self.name + ' run() exiting')
        self.on_stop()

    def _run_without_scheduler(self):
        while self._alive:
            try:
                item = self._queue.get(block=True, timeout=1)
            except queue.Empty:
                #print self.name + " no queue item, alive=%s" % self._alive
                continue
            self._handle_item(item)

    def _run_with_scheduler(self):
        self._scheduler.add_observer((immediate_scheduler,
                                      self._on_scheduler_job_available))
        while self._alive:
            try:
                item = self._queue.get(block=False)
            except queue.Empty:
                item = None
            if item is None:
                # No item was enqueued, or the item was None to awake
                # the thread. Run an Observable job, or block until an
                # item is available
                job = self._scheduler.pop_job()
                if job is not None:
                    try:
                        job()
                    except Exception as ex:
                        print('Exception in eventthread', self, 'job', job)
                        traceback.print_exc()
                    continue
                try:
                    item = self._queue.get(block=True, timeout=1)
                except queue.Empty:
                    continue
                if item is None:
                    continue
            self._handle_item(item)

    def _on_scheduler_job_available(self):
        # Wake up the thread, if it was blocked waiting for an item
        self._queue.put(None)

    def on_stop(self):
        "The last call on the thread before the thread stops"
        pass  #May be overriden


    ######################################################################
    ## Class methods

    @staticmethod
    def stop_all():
        "Blocks until all EventThreads have terminated"
        while weak_cleanup_hooks:
            hook = weak_cleanup_hooks.pop()
            try:
                hook._on_cleanup()
            except Exception as ex:
                print('Warning: Exception calling weak_cleanup_hook', hook)
                traceback.print_exc()
        #Make copy of the list since stop() modifies it
        with EventThread._alive_threads_lock:
            threads = EventThread._alive_threads[:]
        for thread in threads:
            try:
                thread.stop()
            except:
                pass
        # Block waiting for all threads to actually finish
        if debug_stop_function:
            for thread in threads:
                try:
                    starttime = time.time()
                    while thread.is_alive():
                        thread.join(1)
                        if thread.is_alive():
                            print("Thread {} isn't stopping...".format(thread.name))
                    duration = time.time() - starttime
                except:
                    print('Exception in stop_all() for {}:'.format(thread.name))
                    traceback.print_exc()
                    continue
                if duration > 0.2:
                    print('Thread {} took {:.0f} ms to stop'. \
                        format(thread.name, duration * 1000))
        else:
            for thread in threads:
                try:
                    thread.join()
                except:
                    print('Exception in stop_all():')
                    traceback.print_exc()
                    continue


class TimerObservable(Observable, HasCleanup):
    """Observable that notifies its observers once or with regular
       interval. The methods may be called from any thread."""
    def __init__(self, interval_sec=None, recurring=False,
                 observer : Optional[Observer] = None):
        super().__init__()
        self._interval_sec = interval_sec
        self._recurring = recurring
        self._timer = None
        self._alive = True  #False if the object has been discarded
        weak_cleanup_hooks.add(self)
        if observer:
            self.add_observer(observer)
    def start(self, interval_sec=None, reschedule=True):
        """Call this once or multiple times to start the countdown. If
           <reschedule> is true, the call will restart if a countdown
           is ongoing. Don't forget to call add_observer() first.
        """
        if self._timer:
            # Already running
            if not reschedule:
                return # Ignore repeated start()
            self._timer.cancel()
        if not self._alive:
            self._timer = None
            return
        if interval_sec is None:
            assert self._interval_sec is not None
            interval_sec = self._interval_sec
        self._timer = threading.Timer(interval_sec, self._on_timeout)
        self._timer.start()
    def stop(self):
        if self._timer:
            self._timer.cancel()
            self._timer = None
    def is_active(self):
        return (self._timer != None)
    def _on_cleanup(self):
        "Last chance to do something when the application is exiting"
        self._alive = False
        self.stop()
    def _on_timeout(self):
        if not self._alive:
            return
        if self._recurring:
            self._timer = threading.Timer(self._interval_sec, self._on_timeout)
            self._timer.start()
        self.notify_observers()

# Could be called "ThrottleObservable" or "BufferingObservable"
class CooldownObservable(Observable, HasCleanup):
    """Notifies the observers when trigger() is called, but limits the rate
       of notifications.
    """
    def __init__(self, cooldown_sec, delay_sec = 0, flush_on_exit=False,
                 observer : Optional[Observer] = None):
        """After emitting a notify, never emit another one within
           <cooldown_sec>, unless the the application exits and
           <flush_on_exit> is true.  Notifications are delayed at
           least <delay_sec>, to see if there's a second notification
           that can join up with the first one.
        """
        super().__init__()
        # The object can be in three modes:
        # * Inactive
        # * Countdown - Will notify when the timer elapses
        # * Cooldown - if self._earliest_notify_time is in the future
        self._timer = TimerObservable()
        self._timer.add_observer((immediate_scheduler, self._on_timeout))
        self._delay_sec = delay_sec
        self._cooldown_sec = cooldown_sec
        self._is_triggered = False
        self._earliest_notify_time = time.time() + delay_sec #time.time() units
        self.flush_on_exit = flush_on_exit
        self._alive = True
        if flush_on_exit:
            weak_cleanup_hooks.add(self)
        if observer:
            self.add_observer(observer)
        relations.job_may_trigger(self.trigger, self)

    def trigger(self):
        "A job that eventually notifies the observers of this object"
        # Behavior:
        # * Inactive: Start a <delay_sec> delay to notify
        # * Countdown - Do nothing
        # * Cooldown - Switch to countdown to the end of the cooldown
        if self._is_triggered or not self._alive:
            return  # Already counting down to notify.
        now = time.time()
        delay = self._earliest_notify_time - now
        self._is_triggered = True
        if delay <= 0:
            # Not in cooldown phase
            if self._delay_sec == 0:
                self._earliest_notify_time = now + self._cooldown_sec
                self.notify_observers()
                return
            self._timer.start(self._delay_sec)
        else:
            # In cooldown phase; count down to the end of cooldown
            self._timer.start(delay)

    def flush(self):
        """If scheduled to trigger, trigger now instead. Useful when a batch of
           data is known to have completed loading."""
        self._timer.stop()
        self._on_timeout()

    def _on_timeout(self):
        # Cooldown complete. Will be called from a Timer thread (or from flush()).
        if not self._is_triggered or not self._alive:
            return
        now = time.time()
        self._earliest_notify_time = now + self._cooldown_sec
        self._is_triggered = False
        self.notify_observers()

    def stop(self):
        "Stops this object from doing any more work"
        #Not necessary to call self._timer.remove_observer()
        self._timer.stop()
        self._alive = False
        if self.flush_on_exit and self._is_triggered:
            self._is_triggered = False
            self.notify_observers()  # Abort the countdown

    def _on_cleanup(self):
        self.stop()

    def get_job(self) -> Tuple[Scheduler[Callable], Callable]:
        return (immediate_scheduler, self.trigger)

# TODO: Replace this by TimerObservable?
# TODO: start() shadows the method in EventThread and Thread with the same name but different signature (and different purpose)
class Timer(EventThread):
    """A more capable timer than threading.Timer, posting one or multiple
       function calls to another EventThread. Note that the trigger
       callback will be delayed if the EventThread is busy at the
       time.
    """
    def __init__(self, eventthread : EventThread, callback : Callable, args=[]):
        "When subsequently started, the timer will post <callback> with arguments <args> on <eventthread>"
        EventThread.__init__(self, name='Timer')
        self.eventthread = eventthread
        self.callback = callback
        self.args = args

        # If the timer should trigger. Timers can be activated and
        # deactivated any number of times, while _alive only goes
        # false when destroying the EventThread underlaying the Timer.
        self._activate = False

    def start(self, interval : float, recurring : bool = False,
              reschedule : bool = True) -> 'Timer':
        """Activates the timer. If already active AND <reschedule> is true,
           changes the trigger time. <interval> is in seconds"""
        #Overrides EventThread.start()
        if self._alive:
            if reschedule or (not self._activate):
                self._reconfigure(interval, recurring)
            #If already running and reschedule=False, ignore this start() call
        else:
            self._interval = interval
            self._recurring = recurring
            self._activate = True
            self.eventthread._add_timer(self)
            EventThread.start(self)
        return self

    @run_in_thread
    def cancel(self):
        #Not named stop to avoid overriding stop() which must actually stop the thread
        self._activate = False

    def stop(self):
        self.eventthread._remove_timer(self)
        EventThread.stop(self)

    def is_active(self):
        "Returns True if the timer is scheduled to trigger"
        return self._activate

    @run_in_thread
    def _reconfigure(self, interval, recurring):
        self._interval = interval
        self._recurring = recurring
        self._activate = True

    def run(self):
        while True:
            while self._alive and not self._activate:
                # Wait forever for _reconfigure() or stop()
                self.process_all(timeout=None)
            if not self._alive:
                return
            if self._recurring:
                trigger_time = time.time()
                while self._alive:
                    trigger_time += self._interval
                    delay = trigger_time - time.time()
                    #TODO: Handle negative value -- we couldn't keep up
                    if delay > 0:
                        if self.wait_for_event(delay):
                            break    # Go to process_all()
                    if not self.eventthread._alive:
                        self.stop()  #Die with the target thread
                        return
                    self.eventthread.call(self.callback, args=self.args)
            else:
                if self.wait_for_event(self._interval):
                    pass  # Go to process_all()
                elif self._alive and self.eventthread._alive:
                    self.eventthread.call(self.callback, args=self.args)
                    self._activate = False #Don't trigger again until reactivated

#TODO: Replace by CooldownObservable?
class CooldownTimer(HasCleanup):
    "Tempers how often <callback> is called (on <eventthread>)"
    def __init__(self, eventthread : EventThread, callback : Callable,
                 delay_sec, cooldown_sec, flush_on_exit=False, args=[]):
        "If <flush_on_exit>, if a trigger is pending when the application exits, it will be executed at once."
        self._timer = Timer(eventthread, self._callback)
        self._delay_sec = delay_sec
        self._cooldown_sec = cooldown_sec
        self._is_triggered = False
        self._internal_callback = callback
        self._args = args
        self.flush_on_exit = flush_on_exit
        if flush_on_exit:
            weak_cleanup_hooks.add(self)

    def _on_cleanup(self):
        "Last chance to do something when the application is exiting"
        self._timer.stop()
        # Only runs once; Doesn't support one trigger causing another trigger
        if self.flush_on_exit and self._is_triggered:
            self._is_triggered = False
            self._internal_callback(*self._args)

    def _callback(self):
        if not self._is_triggered:
            return # This was the cooldown period
        # Clear is_triggered before the call, in case the call causes
        # another trigger
        self._is_triggered = False
        self._internal_callback(*self._args)
        self._timer.start(self._cooldown_sec)
    def trigger(self):
        "Eventually posts <callback> to <eventthread>"
        self._is_triggered = True
        # This will not affect an ongoing countdown or cooldown
        self._timer.start(self._delay_sec, reschedule=False)


def stop():
    "Blocks until all EventThreads have terminated"
    EventThread.stop_all()

######################################################################

class CooldownScheduler(Generic[JobType], Scheduler[JobType], HasCleanup):
    """Posts jobs to <scheduler> no earlier than <cooldown_sec> after
       the previous post of the same job. The first job is delayed
       <delay_sec> to merge with any subsequent identical jobs.
    """
    def __init__(self, event_thread : EventThread,
                 scheduler : Scheduler[JobType],
                 delay_sec : float,
                 cooldown_sec : float,
                 flush_on_exit : bool = False):
        self._event_thread = event_thread
        self._scheduler = scheduler
        self.delay_sec = delay_sec
        self.cooldown_sec = cooldown_sec
        self._lock = threading.Lock()
        self._pending_jobs : Set[JobType] = set() #The set of jobs not yet posted to
        #Dic from job to (active) timer for that job
        self._running_timers : Mapping[JobType, Timer] = {}
        if flush_on_exit:
            weak_cleanup_hooks.add(self)

    def _on_cleanup(self):
        "Called on exit if <flush_on_exit> is true"
        for (job, timer) in self._running_timers.items():
            timer.stop()
        for job in self._pending_jobs:
            self._scheduler.post_job(job)

    def _on_timeout(self, job):
        post = False
        with self._lock:
            if job in self._pending_jobs:
                post = True
                self._pending_jobs.remove(job)
        if post:
            # Start cooldown
            self._running_timers[job].start(self.cooldown_sec)
            self._scheduler.post_job(job)
        else:
            # Cooldown finished without any new trigger
            self._running_timers[job].stop()
            del self._running_timers[job]

    def post_job(self, job):
        with self._lock:
            if job in self._pending_jobs:
                return # Already pending to be posted
            # The job is in cooldown or not started
            self._pending_jobs.add(job)
        if job in self._running_timers:
            # The job was in cooldown and will be posted when the
            # cooldown completes
            pass
        else:
            self._running_timers[job] = Timer(self._event_thread,
                                              self._on_timeout, args=[job]).start(self.delay_sec)

    def has_job(self):
        return len(self._pending_jobs) > 0
    def pop_job(self) -> Optional[JobType]:
        # Not expected to be used as the scheduler will actively
        # forward the jobs itself
        raise Exception()


# TODO: Temporary until all files use dependency injection for
# scheduler instead of a global
default_scheduler : Scheduler = SimpleScheduler()

##  Clean up on exit
def _monitor_thread():
    main_thread = threading.main_thread()
    main_thread.join()
    # The daemon thread only reaches here when the main thread has
    # finished, i.e. when the application is exiting.
    stop()
def install_cleanup_hook():
    monitor = threading.Thread(target=_monitor_thread)
    monitor.daemon = True
    monitor.start()


######################################################################

import unittest
class TestEventThread(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.events_lock = threading.Lock()
        self.event_count = 0
    def doAction(self, prefix):
        with self.events_lock:
            self.events.append( (prefix, self.event_count) )
            self.event_count += 1
    def getSquare(self, num):
        return num * num
    def test_call1(self):
        t = EventThread("thread1").start()
        t.call(self.doAction, 'a')
        t.stop_when_done()
        t.join()
        self.assertEqual(self.events, [('a', 0)])
    def test_call2(self):
        t = EventThread("thread2").start()
        t.call(self.doAction, 'a')
        t.call(self.doAction, 'b')
        t.call(self.doAction, 'c')
        t.stop_when_done()
        t.join()
        self.assertEqual(self.events, [('a', 0), ('b', 1), ('c', 2)])
    def test_sync_call(self):
        t = EventThread("thread1").start()
        res = blocking_call(t.call, self.getSquare, [3])
        t.stop().join()
        self.assertEqual(res, 9)
    def test_sync_call2(self):
        t = EventThread("thread1").start()
        res = t.blocking_call(self.getSquare, [3])
        t.stop().join()
        self.assertEqual(res, 9)
    def test_single_timer(self):
        t = EventThread("thread3").start()
        timer = Timer(t, self.doAction, args=['e'])
        timer.start(0.1, recurring=False)
        time.sleep(0.25)
        timer.stop()
        t.stop().join()
        self.assertEqual(self.events, [('e', 0)])
    def test_recurring_timer(self):
        t = EventThread("thread3").start()
        timer = Timer(t, self.doAction, args=['d'])
        timer.start(0.1, recurring=True)
        time.sleep(0.35)
        timer.stop()
        time.sleep(0.2)
        t.stop().join()
        self.assertEqual(self.events, [('d', 0), ('d', 1), ('d', 2)])


if __name__ == '__main__':
    unittest.main()
