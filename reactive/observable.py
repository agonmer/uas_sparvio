"""Observer pattern

A Reactive Programming paradigm that makes it easy to keep dependent
data consistent, such as updating the GUI when the data layer changes.

The predefined "Observable variable" classes can interact with custom
classes as building blocks for *active data models* where dependent
calculations are automatically kept up-to-date without repeating
already performed or obsolete calculations.

The mechanism triggers dependent calculations on the correct thread,
merging triggers to avoid multiple triggers of the same
calculation. The system can buffer triggers to avoid too frequent
invokation, for example to write data to disk in chunks.

The usage pattern is:
  1) Change a shared piece of data
  2) Signal that the data is changed, which notifies observers
  3) Each observer figures out how the data has changed (if necessary) and reacts

The observer pattern does not allow notifications to carry any state
that describes the change, as is otherwise common in reactive
programming and event-based programming. Instead, if such data is
necessary, the observer must figure out what has changed, probably by
keeping information on the last processed state and comparing it to
the current state. (If it is expensive to directly detect changes,
such as for an image, the observable can increment a "change counter"
any time a change is made. If all intermediate states are important to
process, add a queue and use the producer/consumer design pattern.)  A
Scheduler acts as an asyncio Event Loop, except identical jobs are
merged and jobs can be prioritized.  Many objects require a
Scheduler. This represents the active aspect of the object; a
"dependency injection" of the behavior of when and how the object
reacts to changes that it observes.  An application can create a
single Scheduler, run all reactive behavior on a separate
SchedulerThread or use separate Schedulers for the data model and GUI,
etc.

Jobs are expected to block their Scheduler until complete. Jobs
should thus be a time-limited reaction to an event.


Terminology
-----------
  Observable = ...
  Job = A unit of work, as understood by a compatible executor. Typically, a Job is a Callable, often a a bound object method named on_change() or similar.
  Scheduler = A policy that determines the order of execution of enqueued Jobs
  Observer = a tuple of Scheduler and a Job.
  Notification = Notifying all observers of an Observable, by posting the
                 associated job to the scheduler for execution
  Trigger = Marking that an Observable "occurred", causing it to
            notify all its observers

  Pipeline = A run-time sequence of dependent Observables that keep
             their values updated using the Observable and Scheduler
             paradigm.

  Derived data = An Observable where the value is calculated from
                 other Observable data, as part of a data pipeline.

  Source data = A term used by derived data for some other
                Observable(s) they calculate their value from.

  Mutable data = An Observable where the value is not derived from
                 other observables; the value can be set through an
                 API, by the user or some independent module

In the names of generic classes, "Observable" is commonly shortened to
"Obs".

Data Pipelines
--------------
A "pipeline" is a series of processing steps for some data, configured
through data structure rather than hardcoded dependencies. This
enables applications to compose their behavior from building blocks,
increasing flexibility and code reuse. One example of pipelining is
the library RxPY (https://github.com/ReactiveX/RxPY)

The Observable data types (ObsVar, ObsList, ObsSet, etc) can be used
to compose pipelines. However, the philosophy of Observable is geared
towards maintaining a data model and supporting batched processing,
and focuses less on the stream aspects (no propagation of errors or
end-of-data condition).

While a data stream can be modelled as a list (ObsList) of all
elements, there's no built-in support for removing data that's no
longer needed. (That could be added as a 'read pointer' that each
observer writes to the observed list. Elements older than all read
pointers can be removed.)

Pipelines often use the terms "source" and "sink" to identify the
start and end points of a data stream. As these concepts aren't
important for this library, the terms are not used.

Example use cases
-----------------

- Populate a data model either from batch loading of data or gradual, real-time data
- Drive a pipeline of data processing steps
- Write new data to disk, but no more often than every 5 seconds
- Update the GUI when the data model changes, but only after all processing steps have completed
- Update calculations and GUI only after batch loading of raw data is complete
- Only recalculate derived values when the parameters actually changed
- Refresh all GUI parts when a sweeping setting such as language is changed, without restarting the application
- Control and synchronize with external instruments

Design patterns
---------------

To make multiple actions easy to trigger at once, use an intermediate
Observable. Example, where ``action1`` and ``action2`` are connected
together to be trigged at the same time:

::

    common_trigger = Observable()
    common_trigger.add_observer( (immediate_scheduler, action1.trigger) )
    common_trigger.add_observer( (immediate_scheduler, action2.trigger) )

    # To trigger all:
    common_trigger.notify_observers()
    # Or set a common trigger source:
    timing = TimerObservable()
    timing.add_observer( (immediate_scheduler,
                          common_trigger.notify_observers) )
    # And to disable all triggers in one step:
    timing.remove_observer( (immediate_scheduler,
                             common_trigger.notify_observers) )

For clarity, <common_trigger> can define a trigger() method instead of
using notify_observers() directly:

class Trigger(Observable):
    "A plumbing object that just forwards any trigger() notification to its observers, optionally using a filter function to stop some notifications"
    def __init__(self, filter : Callable[[], bool] = lambda: True):
        self.filter = filter
        # Help schedulers to run trigger() before running the observers
        self.may_trigger_by_job(self.trigger)
    def trigger(self):
        if self.filter():
            self.notify_observers()

Mutable types
-------------
All Observable objects are *mutable* in the sense that their contents
may change (otherwise there wouldn't be a point in being
observable). However, some values may be set to any value, while other
values are automatically calculated (derived) from some non-public
code. Classes of the former category are then labelled "Mutable", for
example ``MutableObsVar`` and ``MutableMapping``.

Why not just use asyncio?
-------------------------
Asyncio can launch many light-weight threads and execute them in
series or in parallel, but will not merge or sort jobs. Asyncio (and
threads) are suitable for long-lasting operations such as
algorithms, waiting for I/O and processing a sequence of events or data
(message queue) but don't simplify the problem of maintaining
dependencies between different pieces of data.

TODO
----

Implement weak references to remove observers and Observables. See how Django signals handles bound methods (https://docs.djangoproject.com/en/3.1/topics/signals/, https://github.com/django/django/blob/master/django/dispatch/dispatcher.py).

"""

from typing import *
from abc import ABC, abstractmethod
import threading  #for Lock
from collections import namedtuple

######################################################################
# Observable

# Actually the type is Tuple[Scheduler[JobType], JobType]
Observer = Tuple['Scheduler', Any]

ValueType = TypeVar('ValueType')  #Type of a variable wrapped in Observable
SourceType = TypeVar('SourceType')
DerivedType = TypeVar('DerivedType')

class Observable:
    """An Observable can *trigger* to notify its observers. Notifying an
       observer consists of posting a specific job to a specific
       scheduler. Observables may have some lasting state which
       observers can inspect to determine the change, but the
       Observable can also represent a stateless event such as a
       button press.
    """
    def __init__(self):
        self._observers : Set[Observer] = set()

    def add_observer(self, observer : Observer,
                     initial_notify : bool = False):
        """When the observable is updated, Job will be posted for execution by
           the Scheduler specified in the observer.  Multiple
           identical observers are ignored. Multiple notifications to
           the same <observer> may be merged into one call. Observers
           must have the same hash value for these two behaviors to
           work.
        """
        self._observers.add(observer)
        if initial_notify:
            observer[0].post_job(observer[1])
        return self

    def remove_observer(self, observer : Observer):
        try:
            self._observers.remove(observer)
        except KeyError:
            pass  # Ignore if <observer> wasn't observing
        return self
    #def remove_all_observers(self):
    #    self._observers = set()

    def notify_observers(self):
        for (scheduler, observer) in self._observers:
            scheduler.post_job(observer)

    def notify_observers_except(self, exclude : 'Job'):
        for (scheduler, job) in self._observers:
            if job != exclude:
                scheduler.post_job(job)

    # Rename to depends_on()?
    def trigger_on_observable(self, observable : 'Observable'):
        "Creates an dependency that automatically notifies observers of this Observable when <observable> notifies, and uses this to prioritize jobs."
        # trigger_observable_scheduler has special significance to
        # finding relations between jobs and Observables.
        observable.add_observer( (trigger_observable_scheduler, self) )
        return self

    # Rename to depends_on_job()?
    def may_trigger_by_job(self, job : Callable):
        "A hint to Schedulers that <job> may (sometimes or always) call notify_observers() of this Observable, so <job> should be executed before."
        relations.job_may_trigger(job, self)


# This class could maintain a full set of lower priority jobs for each
# job and cooperate with SortingScheduler.
class ObservationRelations:
    """Declarations that certain jobs *may* trigger some Observables and
       other jobs. This suggests to Schedulers to prioritize these
       jobs above the observers of the Observables of the job, as
       those observers may need to be run afterwards anyway.

       Note that it's not required to register relations. For example,
       a PriorityScheduler can instead be used to create order, or
       double execution of some jobs may not matter.

       Only intended for Jobs that are Callables, as non-standard job
       types may have colliding meaning between different Schedulers.

    """
    def __init__(self):
        # Maps from a job to the Observables that the job may trigger
        self.job_triggers : MutableMapping[Callable, Set[Observable]] = {}

        # A job may lead to triggering other jobs (without any
        # Observable in-between)
        self.job_job_triggers : MutableMapping[Callable, Set[Callable]] = {}

    def job_may_trigger(self, job : Callable, observable : Observable):
        """Register that any time <job> is invoked, it may trigger
           <observable>, and hence that <job> should be prioritized
           above all observers of <observable>.
           Users can alternatively call Observable.may_trigger_by_job()
        """
        if job in self.job_triggers:
            self.job_triggers[job].add(observable)
        else:
            self.job_triggers[job] = set([observable])

    def job_may_post_job(self, first_job : Callable, second_job : Callable):
        """Register that one job may trigger another job. This allows
           Schedulers to schedule <first_job> before <second_job> to
           avoid running <second_job> twice."""
        if first_job in self.job_job_triggers:
            self.job_job_triggers[first_job].add(second_job)
        else:
            self.job_job_triggers[first_job] = set([second_job])

    def get_all_lower_prio_from_observable(self, observable : Observable,
                                            all_lower_prio : Set[Callable]):
        """Updates all_lower_prio with all jobs that may be triggered in one
           or multiple steps by <observable>"""
        new_lower_prio : Set[Callable] = set()
        for (scheduler, job) in observable._observers:
            if scheduler == trigger_observable_scheduler:
                # Only Observables may be used as Job here.
                # Warning: No check against circular references; will
                # create infinite loop.
                self.get_all_lower_prio_from_observable(job, all_lower_prio)
            else:
                if job not in all_lower_prio:
                    all_lower_prio.add(job)
                    new_lower_prio.add(job)
        for job in new_lower_prio:
            self.get_all_lower_prio(job, all_lower_prio)

    def get_all_lower_prio(self, job : Callable,
                           all_lower_prio : Set[Callable]):
        "Updates all_lower_prio with all jobs that are prioritized lower than <job>"
        if all_lower_prio is None:
            all_lower_prio = set()
        for second_job in self.job_job_triggers.get(job, set()):
            if second_job in all_lower_prio:
                continue # The job has already been considered
            all_lower_prio.add(second_job)
            self.get_all_lower_prio(second_job, all_lower_prio)
        observables : Set[Observable] = self.job_triggers.get(job, set())
        for observable in observables:
            self.get_all_lower_prio_from_observable(observable, all_lower_prio)

# Singleton (for now)
relations = ObservationRelations()


######################################################################
# Job Schedulers

# Type hint for scheduler jobs.  Jobs can be whatever the Scheduler
# accepts, but need to be hashable for efficient handling and should
# probably be immutable. In most cases, jobs are Callables.
Job = Hashable

JobType = TypeVar('JobType')
InnerJobType = TypeVar('InnerJobType')

class Scheduler(ABC, Generic[JobType], Observable):
    """Collects 'jobs' posted from any thread and chooses which job an
       Executor should execute first. Subclasses define the required
       type of the jobs and the execution strategy. For example,
       schedulers can merge identical jobs. Jobs are commonly Callables
       but can be whatever value the executor supports. (Probably
       hashable and immutable for efficient handling.)
       Notifies when has_job() goes from False to True.
    """
    def __init__(self):
        super().__init__()
    @abstractmethod
    def post_job(self, job : JobType):
        "Called from any thread to schedule <job> for processing by the executor"
        pass
    @abstractmethod
    def pop_job(self) -> Optional[JobType]:
        pass
    @abstractmethod
    def has_job(self) -> bool:
        pass
    def run_to_completion(self):
        "Only call for Scheduler[Callable]"
        while True:
            job = self.pop_job()
            if job is None:
                return
            job()

class _ImmediateScheduler(Scheduler[Callable]):
    """Runs jobs at once. Useful for custom observer behavior and
       debugging. Never notifies its observers."""
    def post_job(self, job : Callable):
        job()
    def pop_job(self) -> Optional[JobType]:
        return None  #No buffering of jobs
    def has_job(self) -> bool:
        return False  #No buffering of jobs
# Only one is ever needed:
immediate_scheduler = _ImmediateScheduler()

class _TriggerObservableScheduler(Scheduler[Observable]):
    """Used to construct observers when an Observable A automatically
       triggers another Observable B, giving the Scheduler a chance to
       prioritize execution of A before B. """
    def post_job(self, job : Observable):
        job.notify_observers()
    def pop_job(self) -> Optional[JobType]:
        return None  #No buffering of jobs
    def has_job(self) -> bool:
        return False  #No buffering of jobs
# Singleton
trigger_observable_scheduler = _TriggerObservableScheduler()

class SimpleScheduler(Generic[JobType], Scheduler[JobType]):
    """Records callable jobs to execute with a first-come-first-serve
       policy. Identical jobs are merged. The class runs on the thread
       where run...() is called. Thread-safe.
    """
    def __init__(self):
        super().__init__()
        self._job_queue : List[JobType] = []
        self._lock = threading.Lock()
    def post_job(self, job : JobType):
        "Schedule a job for execution (invocation)."
        with self._lock:
            notify = not self._job_queue #Notify if the queue becomes non-empty
            if job not in self._job_queue:
                self._job_queue.append(job)
        if notify:
            self.notify_observers()
    def has_job(self) -> bool:
        with self._lock:
            return bool(self._job_queue)
    def pop_job(self) -> Optional[JobType]:
        """Returns the job that should be run first and removes it from the
           queue. Returns None if there's no job."""
        with self._lock:
            if len(self._job_queue) == 0:
                return None  #No job to pop
            return self._job_queue.pop(0)
    def pop_all_jobs(self) -> Iterable[JobType]:
        "Useful for job types that can be accumulated and handled all at once"
        jobs = self._job_queue
        self._job_queue = []
        return jobs

class PriorityScheduler(Generic[JobType], Scheduler[JobType]):
    """At each point, picks a job from the highest prioritized
       sub-scheduler with a ready job."""
    def __init__(self):
        super().__init__()
        # Ordered from high to low priority
        self._schedulers : List[Scheduler[JobType]] = []
    def add_scheduler(self, scheduler : Scheduler[JobType]):
        "Adds a sub-scheduler with lower priority than all previously added schedulers"
        assert scheduler not in self._schedulers
        self._schedulers.append(scheduler)
        # When a subscheduler gains its first job, so does this
        # scheduler (could be extended to only notify if no other
        # subscheduler already had a job ready).
        self.trigger_on_observable(scheduler)
    def has_job(self) -> bool:
        for scheduler in self._schedulers:
            if scheduler.has_job():
                return True
        return False
    def pop_job(self) -> Optional[JobType]:
        for scheduler in self._schedulers:
            job = scheduler.pop_job()
            if job is not None:
                return job
        return None #No sub-scheduler has any job
    def push_job(self, job : JobType):
        raise Exception("Can't push jobs directly to a PriorityScheduler")


class SortingScheduler(Scheduler[Callable], Observable):
    """For each posted job, calculates all jobs that have lower
       priority. Doesn't adjust job priorities if observations are
       changed for jobs already enqueued, but the frequent
       recalcuation of priorities makes the problem negligible.
    """
    # This class only makes sense for jobs that are Callable, as
    # global priority is only defined for Callables.
    def __init__(self):
        # Both of these map from a Job to the set of all Jobs that
        # have lower prio, enqueued or not.
        self._free_jobs : MutableMapping[Callable, Set[Callable]] = {}
        self._maybe_blocked_jobs : MutableMapping[Callable, Set[Callable]] = {}

    def post_job(self, job : Callable):
        # TODO: Use threading.Lock to gain exclusive access to the
        # data structures
        if job in self._free_jobs or job in self._maybe_blocked_jobs:
            return  # Already enqueued; merge the requests
        blocks : Set[Callable] = set()
        relations.get_all_lower_prio(job, blocks)
        is_blocked = False
        jobs_to_block = []
        for (job1, blocks1) in self._free_jobs.items():
            if job in blocks1:
                is_blocked = True
            if job1 in blocks:
                jobs_to_block.append(job1)
        # No need to check if the new job blocks already blocked jobs
        if not is_blocked:
            for blocks1 in self._maybe_blocked_jobs.values():
                if job in blocks1:
                    is_blocked = True
                    break
        if is_blocked:
            self._maybe_blocked_jobs[job] = blocks
        else:
            self._free_jobs[job] = blocks

        for job1 in jobs_to_block:
            self._maybe_blocked_jobs[job1] = self._free_jobs[job1]
            del self._free_jobs[job1]

    def has_job(self) -> bool:
        return bool(self._free_jobs or self._maybe_blocked_jobs)

    def pop_job(self) -> Optional[Callable]:
        if self._free_jobs:
            job = next(iter(self._free_jobs))
            del self._free_jobs[job]
            return job
        if self._maybe_blocked_jobs:
            # Some of these jobs may now be unblockable, after
            # executing all free jobs
            for job in self._maybe_blocked_jobs:
                # Find if other jobs block this one
                is_still_blocked = False
                for (job1, job1_blocks) in self._maybe_blocked_jobs.items():
                    if job1 == job:
                        continue
                    if job in job1_blocks:
                        is_still_blocked = True
                        break
                if not is_still_blocked:
                    del self._maybe_blocked_jobs[job]
                    return job
            # Uh oh, all jobs are still blocked (probably a loop in
            # dependencies). Just pick one.
            print('All %d jobs are blocked: %s' %
                  (len(self._maybe_blocked_jobs),
                   str(self._maybe_blocked_jobs)))
            job = next(iter(self._maybe_blocked_jobs))
            del self._maybe_blocked_jobs[job]
            return job
        # No jobs are enqueued
        return None

    def run_to_completion(self):
        while True:
            job = self.pop_job()
            if job is None:
                return
            job()

    def flush_job(self, job : Callable):
        "If <job> is posted for execution, runs it after all jobs it depends on"
        # This is a crude algorithm that executes jobs on random until
        # <job> is executed. A more efficient solution would find the
        # jobs that <job> depend on, in one or multiple steps, and
        # execute only those jobs. That would require
        # _maybe_blocked_jobs to maintain the set of jobs that block
        # them and not only who they block.
        while True:
            if job in self._free_jobs:
                del self._free_jobs[job]
                job()
                return
            elif job in self._maybe_blocked_jobs:
                job1 = self.pop_job()
                if job1 is None: # Should never happen
                    return
                job1()
            else:
                return


######################################################################
## Variables with single values

# The base concept for all pipelines of a single Python value.
class ObsVar(Observable, ABC, Generic[ValueType]):
    """ObsVar = ObservableVariable. Superclass for objects with a single
       value that can be Observed. Notifies the observers when get()
       changes value. While an Observable can be kept as separate
       object from the observed variable, using this abstraction
       allows pipelining of variables.

       The class uses the name "variable" instead of "value" since the
       value (contents) of a variable can change without becoming
       another variable.
    """
    @abstractmethod
    def get(self) -> ValueType:
        "Returns the current value of this Variable"
        pass
    def __repr__(self) -> str:
        # Default implementation; subclasses are free to override this
        return type(self).__name__ + "(" + repr(self.get()) + ")"

class MutableObsVar(Generic[ValueType], ObsVar[ValueType], ABC):
    @abstractmethod
    def set(self, value : ValueType):
        "Returns the current value of this Variable"
        pass

class BasicObsVar(Generic[ValueType], MutableObsVar[ValueType]):
    """A variable with a singular value, supporting both set() and get()
       and notifying observers.
       Override get() and set() if custom behavior is desired.
    """
    def __init__(self, value : ValueType):
        super().__init__()
        self._value = value
    def get(self) -> ValueType:
        return self._value
    def set(self, value : ValueType):
        "Set the value, (mark it as updated for all observers?) and notify all observers"
        self._value = value
        self.notify_observers()
    def set_if_diff(self, value : ValueType):
        # Use get() and set() here, to support overloading of them
        if self.get() != value:
            self.set(value)

# Example use:
# ObsFn(myobj.method).depends_on(observable)
ReturnType = TypeVar('ReturnType')
FuncType = TypeVar('FuncType', bound=Callable[..., ReturnType])
# Type hints for ObsFn should probably use protocol to express that
# the signature of calling ObsFn is FuncType.
# https://mypy.readthedocs.io/en/stable/protocols.html
# https://github.com/python/mypy/pull/5463
class ObsFn(Generic[FuncType], Observable):
    """An observable function notifies its observers when its external
       dependencies change, which can cause the mapping of the
       function to change. This is useful when supplying functions as
       parameters for later use, for dependency injection.

       Example 1: A function that formats numbers as a user-friendly
       string depends on the configured locale.  If the locale
       changes, all strings derived with the function should be
       recalculated.

       Example 2: A currency converter depends on the exchange rate
       between the particular pair of currencies.
    """
    def __init__(self, fn : FuncType):
        super().__init__()
        self.fn : FuncType = fn
    def __call__(self, *args, **kwargs) -> ReturnType: #Type hints don't support variadic parameters
        return self.fn(*args, **kwargs)
    # TODO: Use the method in Observable directly? But the naming
    # "trigger_on_observable" isn't as clear.
    def depends_on(self, observable : Observable):
        """Register that the value for this function may change when
           <observable> changes (triggers)."""
        self.trigger_on_observable(observable)
        return self

# Example use:
#   sum_var = CalculatedObsVar(scheduler, sum, 10, my_log.entry_count_var)
# TODO: Rename to DerivedObs
class CalculatedObsVar(Generic[DerivedType], ObsVar[DerivedType]):
    """An ObsVar derived from other ObsVars. Compares the new value with
       the old, to avoid notifying observers when the value stays the
       same.
    """
    def __init__(self, scheduler : Scheduler,
                 fn : Callable[..., DerivedType], *args):
        """<fn> is a Callable that accepts argument list *args and returns the
           value of this CalculatedValue. Arguments that are ObsVar
           will be observed and cause the value to be recalculated by
           <scheduler>. The wrapped ObsVar value will be used as
           argument, not the ObsVar itself.
        """
        super().__init__()
        self._scheduler = scheduler
        self._fn = fn
        self._args = args
        for arg in args:
            if isinstance(arg, ObsVar):
                arg.add_observer( (scheduler, self._update) )
        if isinstance(fn, ObsFn):
            fn.add_observer( (scheduler, self._update) )
        relations.job_may_trigger(self._update, self)
        # Initial calculation:
        self._value : DerivedType = self._calculate()
    def get(self) -> DerivedType:
        return self._value
    def _calculate(self) -> DerivedType:
        def calc_arg(arg):
            if isinstance(arg, ObsVar):
                return arg.get()
            else:
                return arg
        return self._fn(*map(calc_arg, self._args))
    def _update(self):
        "Recalculate the value"
        value = self._calculate()
        if self._value != value:
            self._value = value
            self.notify_observers()

class LazyCalculatedObsVar(ObsVar, Generic[DerivedType]):
    """An ObsVar derived from other ObsVars. Only calls the calculating
       function when queried, caching the result until some parameter
       notifies of a change. Calculates its value on a caller's
       thread, hence doesn't need a scheduler. Notifies its observers
       even if the calculation has the same result as before.
    """
    def __init__(self, fn : Callable[..., DerivedType], *args):
        """<fn> is a Callable that accepts argument list *args and returns the
           value of this LazyCalculatedObsVar. Arguments that are
           ObsVar will be observed and cause the value to
           be recalculated.
        """
        super().__init__()
        self._fn = fn
        self._args = args
        self._is_dirty = True
        # Initial calculation will be done when anyone asks
        self._value : Optional[DerivedType] = None
        for arg in args:
            if isinstance(arg, ObsVar):
                arg.add_observer( (immediate_scheduler, self._mark_as_dirty) )
        if isinstance(fn, ObsFn):
            fn.add_observer( (immediate_scheduler, self._mark_as_dirty) )
        relations.job_may_trigger(self._mark_as_dirty, self)
    def get(self) -> Optional[DerivedType]:
        def calc_arg(arg):
            if isinstance(arg, ObsVar):
                return arg.get()
            else:
                return arg
        if self._is_dirty:
            self._value = self._fn(*map(calc_arg, self._args))
            self._is_dirty = False
        return self._value
    def _mark_as_dirty(self):
        if not self._is_dirty:
            self._is_dirty = True
            self.notify_observers()

class WrappedObsVar(Generic[ValueType], ObsVar[ValueType]):
    """An ObsVar that just fetches its get() value somewhere else, without
       allowing set(). The object doesn't discover value changes
       automatically, but notify_observers() has to be called
       manually.
       This is equivalent to creating a subclass of ObsVar.
    """
    def __init__(self, getter : Callable[[], ValueType]):
        super().__init__()
        self._getter = getter
        # This overwrites get(); but get() must still be defined for
        # @abstractmethod to work
        #self.get = getter
    def get(self) -> ValueType:
        return self._getter()
# Example:
# self.id = WrappedObsVar(lambda: self._id)

class SettableWrappedObsVar(Generic[ValueType], MutableObsVar[ValueType]):
    """An ObsVar that uses custom get() and set() functions. The object
       doesn't discover value changes automatically, but
       notify_observers() has to be called manually.
       This is equivalent to creating a subclass of MutableObsVar.
    """
    def __init__(self, getter : Callable[[], ValueType],
                 setter : Callable[[ValueType], None]):
        super().__init__()
        self._getter = getter
        # This overwrites get(); but get() must still be defined for
        # @abstractmethod to work
        #self.get = getter
        self._setter = setter
    def get(self) -> ValueType:
        return self._getter()
    def set(self, value: ValueType):
        self._setter(value)


######################################################################
## ObsList (Observable List)

# See readme.rst for documentation.
class Mutation(NamedTuple):
    """A Mutation describes the operation of removing <remove> elements
       from a list, starting with the element at <index>, followed by
       inserting <insert> elements before <index>.
    """
    index: int
    remove: int
    insert: int
#def apply_mutation_to_ix(old_ix : Optional[int], mutation : Mutation):
#    " ""Returns the new ix for the entry that used to have ix
#       <old_ix>. Returns None if the entry that had index <old_ix> is
#       not present any more in its original form." ""
#    if old_ix is None:
#        return None
#    # TODO: If mutation is discontinuity, return None
#    if old_ix < mutation.index:
#        return old_ix  #old_ix is before the mutation -- not affected
#    if old_ix >= mutation.index + mutation.remove:
#        # old_ix comes after the mutation
#        return old_ix + mutation.insert - mutation.remove
#    # old_ix is part of the mutation; the entry was removed, replaced or modified
#    return None

ElementType = TypeVar('ElementType')

# Actually an ABC (Abstract Base Class)
class ObsList(Generic[ElementType], ObsVar[Sequence[ElementType]],
              Iterable[ElementType]):
    """Mimic a regular Python list interface, with the added ability as
       Observable to let observers know how the list has changed."""
    count : ObsVar[int]
    revision : MutableObsVar[int]  # TODO: Can the public type be non-mutable?
    def __init__(self):
        ObsVar.__init__(self)
        # Key: old revision. Value: tuple (new revision, mutation)
        # TODO: Change to chronological list, to be able to forget the oldest mutations
        self._history : dict[int, Tuple[int, Mutation]] = {}
        self.revision = BasicObsVar(0)

    @abstractmethod
    def __getitem__(self, index) -> ElementType:
        "Return a value based on index"
        pass
    @abstractmethod
    def ix_to_entry(self, ix: int) -> ElementType:
        "Returns the entry at index <ix>, starting from 0"
        pass
    def __bool__(self):
        return self.count.get() > 0
    def get_count(self) -> int:
        return self.count.get()
    def __len__(self) -> int:
        return self.count.get()
    def get_highest_ix(self) -> int:
        "The largest entry index that can be addressed as of now"
        # For now, all indices are present but this can be changed to
        # save RAM
        return self.count.get() - 1

    #@abstractmethod
    #def all_entries(self) -> Iterable[ElementType]:
    #    "Iterate over all entries"
    #    pass

    def register_mutation(self, insertion_ix : int,
                          remove : int, insert : int):
        """Inform the revision system that the entries have (already) been
           mutated according to the arguments."""
        new_revision = self.revision.get() + 1
        self._history[self.revision.get()] = \
            (new_revision, Mutation(insertion_ix, remove, insert))
        self.revision.set(new_revision)
        self.notify_observers()

    def update_state(self, state : 'ListState') -> 'ListDiff':
        "Sets <state> to the current state of the list, returning the difference from the old <state>."
        diff = self.diff(state)
        state.revision = self.revision.get()
        state.entry_count = self.get_count()
        return diff

    def diff_to_entries(self, diff) -> Iterator[ElementType]:
        "Returns an iterator with the entries added in <diff>"
        if diff.mutations:
            raise NotImplementedError()
        if diff.first_new_ix is None:
            return  #raise StopIteration()
        # Copy the range, in case <diff> would change while iterating
        first_new_ix = diff.first_new_ix
        last_new_ix = diff.last_new_ix
        for ix in range(first_new_ix, last_new_ix + 1):
            yield self.ix_to_entry(ix)

    def diff(self, state : 'ListState') -> 'ListDiff':
        "Returns the progression since <state> without modifying <state>"
        diff = ListDiff()
        if state.revision is None:
            # First run
            if self.get_count() != 0:
                diff.first_new_ix = 0
                diff.last_new_ix = self.get_highest_ix()
            return diff
        elif state.revision != self.revision.get():
            # New revision since <state>. Find the sequence of changes.
            seq : List[Mutation] = []
            rev = state.revision
            entry_count = state.entry_count
            while rev != self.revision.get():
                if rev not in self._history:
                    raise NotImplementedError("Implement discontinuity")
                (rev, mutation) = self._history[rev]
                if mutation.index >= entry_count:
                    pass  # The change affects entries unknown by <state>
                else:
                    # TODO: only include the part of the change that
                    # affects indices included in <state>
                    #
                    # TODO: update entry_count somehow
                    seq.append(mutation)
            diff.mutations = seq
            # TODO: Calculate newly appended indices too...
            return diff
        elif state.entry_count > self.get_count():
            assert Exception("ObsList shrank without a revision change")
        elif state.entry_count < self.get_count():
            # Appended entries
            diff.first_new_ix = state.entry_count
            diff.last_new_ix = self.get_highest_ix()
        else:
            # No change. Return empty diff
            pass
        return diff
    def create_retaining_state(self) -> 'ListState':
        """A 'retaining state' is a ListState that communicates back to the
           ObsList to avoid discarding any data newer than the
           ListState. This doesn't make any difference for ObsLists
           with unlimited data storage, but for ObsLists that only
           stores the newest data (like a buffer), older buffered data
           is saved until all retaining states have been updated past
           the data.
        """
        # Returns a ListState for the empty list, so the current data
        # can be processed as an initial diff.
        #
        # Flushing data processed by all observers can be implemented
        # by making the ObsList observe its retaining states. The
        # callback can check the oldest retained entry and flush any
        # older data.
        #
        # The base class doesn't flush any data, so a regular
        # ListState is enough.
        return ListState()

    def __repr__(self) -> str:
        # Override the ObsVar implementation to avoid returning ALL contents of the ObsList
        rev = self.revision.get()
        if rev == 0:
            return type(self).__name__ + "(count=" + repr(self.count.get()) + ")"
        else:
            return type(self).__name__ + "(count=" + repr(self.count.get()) + ",revision=" + str(rev) + ")"


class MutableObsList(ObsList[ElementType], Generic[ElementType]):
    """Concrete implementation of the ObsList interface that uses an
       internal list and automatically generates new revisions for
       mutations. Other ObsList implementations can define
       their own versions of mutability.
    """
    def __init__(self, initial_data : Iterable = []):
        super().__init__()
        # If <initial_data> is a list, list() copies it which avoids
        # sharing of data
        self._list : List[ElementType] = list(initial_data)
        self.count : WrappedObsVar[int] = WrappedObsVar(lambda: len(self._list))
        #self.revision : MutableObsVar[int] = MutableObsVar(0)

    def append(self, element : ElementType):
        self._list.append(element)
        self.count.notify_observers()
        self.notify_observers()
        #TODO: Use this in read_log.py instead of rawlog.add()
    def extend(self, elements : Iterable[ElementType]):
        self._list.extend(elements)
        self.count.notify_observers()
        self.notify_observers()
    def insert(self, i : int, x : ElementType):
        "Insert element <x> before the element with previous index <i>"
        self._list.insert(i, x)
        # At index <i>, change 0 element into 1 element (insert 1 element)
        self.register_mutation(i, 0, 1)
        self.count.notify_observers()

    def insert_multiple(self, ix : int, elements : Iterable[ElementType]):
        # Is there another way to see if any changes were made?
        # (<elements> is declared as Iterable, not Sized)
        len_before = len(self._list)
        self._list[ix:ix] = elements
        len_after = len(self._list)
        if len_after != len_before:
            self.register_mutation(ix, 0, len_after - len_before)
        self.count.notify_observers()

    def get(self) -> List[ElementType]:
        "Don't modify the list, as the changes won't be registered"
        return self._list
    def __getitem__(self, index) -> ElementType:
        return self._list[index]
    def ix_to_entry(self, ix: int) -> ElementType:
        return self._list[ix]
    def __iter__(self):
        return iter(self._list)
    def clear(self):
        size_before = len(self._list)
        self._list = []
        self.register_mutation(0, size_before, 0)
        self.count.notify_observers()

class ListState:
    """Stores the metadata of an ObsList, to later on be able to deduce
       further changes in the form of ListDiff. Doesn't store any of
       the actual data of the ObsList.
    """
    revision : Optional[int]
    entry_count : int
    def __init__(self, lst : Optional[ObsList] = None):
        """If <lst> is specified, initializes the ListState to the current
           state of <lst>, otherwise to a state with no data."""
        if lst is not None:
            self.revision = lst.revision.get()
            self.entry_count = lst.get_count()
        else:
            self.revision = None  # Unknown revision
            self.entry_count = 0
    def as_diff(self) -> 'ListDiff':
        "Returns a ListDiff going from no data to this list state"
        diff = ListDiff()
        diff.first_new_ix = 0
        diff.last_new_ix = self.entry_count - 1
        return diff
    def reset(self):
        self.revision = None  # Unknown revision
        self.entry_count = 0
    def __repr__(self):
        if self.revision is None:
            return "ListState(rev=None, count=%d)" % self.entry_count
        else:
            return "ListState(rev=%d, count=%d)" % \
                (self.revision, self.entry_count)


class ListDiff:
    """The difference between two ObsList states (ListStates). A sequence
       of Mutations and a range of appended indices.
    """
    def __init__(self):
        # A mutation modifies previously existing data contents or
        # indexing (i.e. not only appending entries at the end)
        self.mutations : Sequence[Mutation] = []
        # Appended entries, as referring to the list after
        # self.mutations have been applied:
        self.first_new_ix : Optional[int] = None
        self.last_new_ix : Optional[int] = None
    def is_empty(self) -> bool:
        "An empty Diff means there are no changes"
        return len(self.mutations) == 0 and self.first_new_ix is None
    def is_appended(self) -> bool:
        return (self.first_new_ix is not None)
    def appended_indices(self) -> Iterable[int]:
        "To iterate over the appended list entries directly, use ObsList.diff_to_entries() instead"
        if self.first_new_ix is None or self.last_new_ix is None:
            return iter(())  #Empty iterator
        return range(self.first_new_ix, self.last_new_ix + 1)
    def number_of_new_entries(self) -> int:
        if self.first_new_ix is None or self.last_new_ix is None:
            return 0
        return self.last_new_ix - self.first_new_ix + 1
    def __bool__(self):
        return not self.is_empty()
    def __eq__(self, obj):
        if not isinstance(obj, ListDiff):
            return False
        return (self.mutations == obj.mutations and
                self.first_new_ix == obj.first_new_ix and
                self.last_new_ix == obj.last_new_ix)
    def __repr__(self):
        return 'ListDiff(%s, %s, %s)' % (str(self.mutations),
                                        str(self.first_new_ix),
                                        str(self.last_new_ix))


######################################################################
## ObsSet (Observable Set)

class ObsSet(Generic[ValueType], ObsVar[Set[ValueType]],
             ABC, Iterable[ValueType]):
    """An ObsVar which is an unordered set of elements. Subclasses may or
       may not allow modifying the set directly. Even though ObsSet
       can't be changed directly, subclasses can change the contents,
       so they are not frozenset. Observers should keep a copy of the
       contents to detect and process changes.

       Regular Python sets are mutable and not hashable, but ObsSets
       are objects and are therefore also hashable.
    """
    def __init__(self, initial_contents : Iterable[ValueType] = []):
        super().__init__()
        # Only changed from subclasses
        self._set : Set[ValueType] = set(initial_contents)
    def get(self) -> Set[ValueType]:
        return self._set
    def _add(self, element : ValueType):
        "Internal function for use only by subclasses"
        if element in self._set:
            return
        self._set.add(element)
        self.notify_observers()
    def _remove(self, element : ValueType):
        self._set.remove(element) # May raise KeyError
        self.notify_observers()
    def difference(self, _set : Union[Set, 'ObsSet']) -> Set[ValueType]:
        """Mirror the functionality in regular 'set': Returns the elements in
           this set which are not in <_set>. Returns the current
           state, not a dynamically updated ObsSet.
        """
        if isinstance(_set, ObsVar):
            return self._set.difference(_set.get())
        return self._set.difference(_set)
    def __len__(self) -> int:
        return len(self._set)
    def __iter__(self) -> Iterator[ValueType]:
        "Watch out that the data mustn't change while iterating"
        return iter(self._set)

# TODO: Also add other set operations to MutableObsSet
class MutableObsSet(ObsSet[ValueType], Generic[ValueType]):
    """An observable set that can be directly modified, in contrast to
       calculating the contents as part of a pipeline."""
    def __init__(self, initial_contents : Iterable[ValueType] = []):
        super().__init__(initial_contents)
    def add(self, element : ValueType):
        self._add(element)
    def remove(self, element : ValueType):
        self._remove(element)
    def discard(self, element : ValueType):
        if element not in self._set:
            return
        self._set.discard(element)
        self.notify_observers()
    def update(self, set_to_add : Iterable[ValueType]):
        """Adds all elements in <set_to_add> to this set. For continuous
           updates, use class UnionObsSet instead of MutableObsSet."""
        changed = False
        for element in set_to_add:
            if element not in self._set:
                self._set.add(element)
                changed = True
        if changed:
            self.notify_observers()

class MapObsSet(ObsSet[DerivedType], Generic[SourceType, DerivedType]):
    """Pipeline 'map' for Sets:
       A Set where each member is a transformation on a (possibly
       Observable) element in another ObsSet. This class keeps the
       derived set updated with the members of the source ObsSet.

       If <derive_element_fn> returns None, the element is
       excluded. Hence, the class can act as a filter. Also, this
       means the derived set can not include None.

       The class can be used purely as a callback for elements added
       to the source set by defining side-effects in <derive_element_fn>
       and returning the same source element.

       Multiple source elements must not map to the same derived
       value, as removing elements then would require a more
       time-consuming algorithm to look for the duplicates.
    """
    def __init__(self, scheduler : Scheduler,
                 source: ObsSet[SourceType],
                 derive_element_fn: Callable[[SourceType], Optional[DerivedType]],
                 on_remove_fn: Optional[Callable[[DerivedType], Any]] = None):
        """<derive_element_fn> is run on each element added to <source>. It
           may be an ObsFn. If <derive_element_fn> returns None, the
           element is excluded from this set.

           The optional <on_remove_fn> argument is a function that
           will be run for each *derived* element that is removed, for
           example to unsubscribe to the source element.
           <on_remove_fn> is not run when filtered elements (derived
           value None) are removed from the source set.
        """
        super().__init__()
        self._scheduler = scheduler
        self._source = source
        self._derive_element_fn = derive_element_fn
        self._on_remove_fn = on_remove_fn
        # The elements of the source set that have been processed
        self._processed_elements : Set[SourceType] = set()
        # Track how the source set maps to the derived set
        # Filtered source elements are also included (as derived value None)
        # (This could be exposed as an ObsMap for observing)
        self._source_to_derived : Mapping[SourceType, Optional[DerivedType]] = {}
        source.add_observer((scheduler, self._on_source_set_change),
                            initial_notify = True)
        if isinstance(self._derive_element_fn, ObsFn):
            self._derive_element_fn.add_observer((scheduler,
                                                  self._on_fn_change))
        relations.job_may_trigger(self._on_source_set_change, self)
        relations.job_may_post_job(self._on_fn_change,
                                   self._on_source_set_change)

    def _on_source_set_change(self):
        new = self._source.difference(self._processed_elements)
        removed = self._processed_elements.difference(self._source.get())
        for el in new:
            derived = self._derive_element_fn(el)
            self._source_to_derived[el] = derived
            if derived is not None:
                self._processed_elements.add(el)
                self._add(derived)
        self._processed_elements.difference_update(removed)
        for el in removed:
            derived = self._source_to_derived[el]
            if derived is None:
                continue
            # This might fail if multiple source elements were allowed
            # to map to the same derived element.
            self._remove(derived)
            if self._on_remove_fn:
                self._on_remove_fn(derived)
        # Notifications are already done by the parent ObsSet

    def _on_fn_change(self):
        "Called when the transfer function changes"
        # This simple solution does all calculations again. A more
        # sophisticated solution would compare the new derived set
        # with the old to avoid triggering when the result doesn't
        # change. Either way, the model needs to be in sync with how
        # side-effects are used.
        for (el, derived) in self._source_to_derived.items():
            self.remove(derived)
            if self._on_remove_fn:
                self._on_remove_fn(derived)
        self._processed_elements = set()
        self._source_to_derived = {}
        # Post as a job, to merge with other notifications
        self._scheduler.post_job(self._on_source_set_change)


class UnionObsSet(ObsSet[ValueType], Generic[ValueType]):
    """This set contains the union of the members of some other sets. To
       support adding and removing source sets, the sources are in turn
       expressed as an ObsSet.
    """
    # Python can't have a native set of native sets, but ObsSet of
    # native sets works (as source_sets).
    def __init__(self, scheduler : Scheduler,
                 source_sets: ObsSet[Set[ValueType]]):
        super().__init__()
        self._scheduler = scheduler
        self._source_sets = source_sets
        source_sets.add_observer((scheduler, self._on_sources_changed),
                                 initial_notify = True)
        #self._processed : Mapping[ObsSet[ValueType], Set[ValueType]]
        # Copy of source_sets to keep track of who we observe
        self._observed_sets : Set[ObsSet[Set[ValueType]]] = set()
        relations.job_may_post_job(self._on_sources_changed,
                                   self._on_contents_changed)
        relations.job_may_trigger(self._on_contents_changed, self)
    def _on_sources_changed(self):
        "Callback when at least one source set was added or removed"
        all_sources_now = self._source_sets.get()
        # Added source sets:
        added = all_sources_now.difference(self._observed_sets)
        removed = self._observed_sets.difference(all_sources_now)
        for _set in added:
            _set.add_observer((self._scheduler, self._on_contents_changed))
        # Removed source sets:
        for _set in removed:
            _set.remove_observer((self._scheduler, self._on_contents_changed))
        if added or removed:
            # Copy the set of sources to detect changes in the future
            self._observed_sets = all_sources_now.copy()
            # We're already on scheduler, but merge pending requests
            self._scheduler.post_job(self._on_contents_changed)
    def _on_contents_changed(self):
        "Members of at least one source set changed"
        _set = set()
        for source_set in self._observed_sets:
            _set.update(source_set.get())
        if _set != self._set:
            self._set = _set
            self.notify_observers()
