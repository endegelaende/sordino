"""
jive.ui.task — Coroutine-based task scheduler for the Jivelite Python3 port.

Redesigned from ``Task.lua`` in the original jivelite project.

The Lua original uses ``coroutine.create`` / ``coroutine.resume`` /
``coroutine.yield`` to implement cooperative multitasking.  In Python we
redesign this around a lightweight cooperative scheduler that uses
generator-based coroutines (``yield``).  This keeps the same semantics
as the Lua version (priority queues, add/remove/resume, cooperative
yield) without pulling in the full ``asyncio`` event loop — jivelite
already has its own event loop in Framework.

Task priorities (matching the Lua constants)::

    PRIORITY_AUDIO = 1   — highest (streaming audio)
    PRIORITY_HIGH  = 2
    PRIORITY_LOW   = 3   — default

Tasks are stored in three priority-keyed linked lists (implemented as
Python lists for simplicity).  The ``iterator()`` class method yields
tasks in priority order, and ``resume()`` advances the generator by one
step.

Usage::

    from jive.ui.task import Task, PRIORITY_HIGH

    def my_work(obj):
        # do part 1
        yield True      # yield True → keep running next tick
        # do part 2
        yield True
        # done — yield False or return to suspend
        yield False

    task = Task("my_task", my_obj, my_work)
    task.add_task()

    # In the main loop:
    for t in Task.iterator():
        t.resume()

A task function receives ``(obj, *args)`` on first call, and should
``yield True`` to continue or ``yield False`` / ``return`` to suspend.
If the generator raises an exception the task enters the ``"error"``
state and the optional error callback is invoked.

Copyright 2010 Logitech. All Rights Reserved. (original Lua implementation)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

import traceback
from typing import (
    Any,
    Callable,
    Generator,
    Iterator,
    List,
    Optional,
    Sequence,
    Tuple,
    Union,
)

from jive.utils.log import logger

__all__ = [
    "Task",
    "PRIORITY_AUDIO",
    "PRIORITY_HIGH",
    "PRIORITY_LOW",
]

log = logger("jivelite.task")

# ---------------------------------------------------------------------------
# Priority constants (matching Lua original)
# ---------------------------------------------------------------------------

PRIORITY_AUDIO: int = 1
PRIORITY_HIGH: int = 2
PRIORITY_LOW: int = 3

# Number of priority levels (1-based indexing in the Lua original)
_NUM_PRIORITIES: int = 3

# ---------------------------------------------------------------------------
# Module-level task queues — one list per priority level
# ---------------------------------------------------------------------------

# Index 0 is unused (priorities are 1-based); indices 1..3 hold task lists.
_task_queues: List[List[Task]] = [[] for _ in range(_NUM_PRIORITIES + 1)]

# The currently running task (or None for the main thread)
_task_running: Optional[Task] = None

# ---------------------------------------------------------------------------
# Task states
# ---------------------------------------------------------------------------

STATE_SUSPENDED: str = "suspended"
STATE_ACTIVE: str = "active"
STATE_ERROR: str = "error"
STATE_DEAD: str = "dead"


# ---------------------------------------------------------------------------
# Task class
# ---------------------------------------------------------------------------


class Task:
    """
    A cooperative task backed by a Python generator.

    Parameters
    ----------
    name : str
        Human-readable name for debugging / logging.
    obj : Any
        The object passed as the first argument to the task function.
    func : callable
        A **generator function** ``func(obj, *args)`` that ``yield``s
        ``True`` to keep running or ``False`` / returns to suspend.
        Can also be a regular function (will be called once per resume).
    error_func : callable, optional
        Called as ``error_func(obj)`` if the task raises an exception.
    priority : int, optional
        One of ``PRIORITY_AUDIO``, ``PRIORITY_HIGH``, ``PRIORITY_LOW``
        (default: ``PRIORITY_LOW``).
    """

    __slots__ = (
        "name",
        "obj",
        "_func",
        "_error_func",
        "priority",
        "state",
        "_args",
        "_generator",
        "_is_running",
        # Linked-list 'next' for compatibility with iteration patterns
        # (we use Python lists internally, but expose .next for parity)
        "next",
    )

    def __init__(
        self,
        name: str,
        obj: Any = None,
        func: Optional[Callable[..., Any]] = None,
        error_func: Optional[Callable[[Any], None]] = None,
        priority: int = PRIORITY_LOW,
    ) -> None:
        if func is not None and not callable(func):
            raise TypeError(f"func must be callable, got {type(func).__name__}")
        if error_func is not None and not callable(error_func):
            raise TypeError(
                f"error_func must be callable, got {type(error_func).__name__}"
            )
        if priority not in (PRIORITY_AUDIO, PRIORITY_HIGH, PRIORITY_LOW):
            raise ValueError(
                f"priority must be PRIORITY_AUDIO (1), PRIORITY_HIGH (2), "
                f"or PRIORITY_LOW (3), got {priority}"
            )

        self.name: str = name
        self.obj: Any = obj
        self._func: Optional[Callable[..., Any]] = func
        self._error_func: Optional[Callable[[Any], None]] = error_func
        self.priority: int = priority
        self.state: str = STATE_SUSPENDED
        self._args: Tuple[Any, ...] = ()
        self._generator: Optional[Generator[Any, Any, Any]] = None
        self._is_running: bool = False
        self.next: Optional[Task] = None  # Lua compat — not actively used

    # ------------------------------------------------------------------
    # Resume / yield
    # ------------------------------------------------------------------

    def resume(self) -> bool:
        """
        Resume (advance) the task by one step.

        Returns ``True`` if the task is still active (will run again
        next tick), ``False`` if the task has completed or errored.

        Re-entrant calls (e.g. when a callback triggered during resume
        causes the same task to be resumed again) are silently skipped
        and return ``True`` so the task stays queued for the next cycle.
        """
        global _task_running

        # Guard against re-entrant resume — this can happen when a
        # sink callback (fired during this resume) triggers another
        # fetch() → add_task() → resume() on the same generator.
        if self._is_running:
            log.debug("task %s: skipping re-entrant resume", self.name)
            return True

        log.debug("task: %s", self.name)

        self._is_running = True
        _task_running = self

        try:
            # Lazily create the generator on first resume
            if self._generator is None:
                if self._func is None:
                    log.warn("task %s has no function", self.name)
                    self.remove_task()
                    return False

                result = self._func(self.obj, *self._args)

                # Check if the function returned a generator
                if hasattr(result, "__next__"):
                    self._generator = result
                    # Advance to the first yield
                    try:
                        val = next(self._generator)
                    except StopIteration:
                        # Generator finished immediately
                        self.remove_task()
                        return False
                else:
                    # Plain function — ran to completion, check return
                    if result:
                        # Re-create on next resume (one-shot per resume)
                        self._generator = None
                        return True
                    else:
                        self.remove_task()
                        return False
            else:
                # Generator already running — send None (equivalent to
                # coroutine.resume with no extra args)
                try:
                    val = self._generator.send(None)
                except StopIteration:
                    val = None

            # Interpret the yielded value
            if val is None or val is False:
                # Task wants to suspend
                self.remove_task()
                return False
            elif val is True:
                # Task wants to continue
                return True
            else:
                # Any other truthy value means continue
                return True

        except Exception as exc:
            log.error("task error %s: %s", self.name, exc)
            log.error(traceback.format_exc())
            self.remove_task()
            self.state = STATE_ERROR

            if self._error_func is not None:
                try:
                    self._error_func(self.obj)
                except Exception as inner:
                    log.error(
                        "error in task error handler for %s: %s",
                        self.name,
                        inner,
                    )
            return False

        finally:
            self._is_running = False
            _task_running = None

    # ------------------------------------------------------------------
    # Arguments
    # ------------------------------------------------------------------

    def set_args(self, *args: Any) -> None:
        """
        Set the arguments passed to the task function on next resume.

        For generators, these are passed via ``generator.send()`` only
        on the first call (subsequent resumes always send ``None``).
        """
        self._args = args

    # ------------------------------------------------------------------
    # Task queue management
    # ------------------------------------------------------------------

    def add_task(self, *args: Any) -> bool:
        """
        Add this task to the end of its priority queue.

        Returns ``True`` on success, ``False`` if the task is in error
        state.
        """
        log.debug("addTask %s", self.name)

        if self.state == STATE_ERROR:
            log.warn("task %s in error state", self.name)
            return False

        if self.state == STATE_ACTIVE:
            # Already queued
            return True

        self._args = args
        self.state = STATE_ACTIVE
        self._generator = None  # Reset generator for fresh start

        queue = _task_queues[self.priority]
        if self not in queue:
            queue.append(self)

        return True

    def remove_task(self) -> None:
        """Remove this task from its priority queue."""
        log.debug("removeTask %s", self.name)

        self.state = STATE_SUSPENDED

        queue = _task_queues[self.priority]
        try:
            queue.remove(self)
        except ValueError as exc:
            log.debug("remove failed: %s", exc)

    # ------------------------------------------------------------------
    # Class methods (mirror Lua module-level functions)
    # ------------------------------------------------------------------

    @classmethod
    def yield_task(cls, *args: Any) -> Any:
        """
        Cooperative yield from within a task generator.

        This is a no-op when called from outside a generator — in
        generator-based tasks, use ``yield True`` directly instead.

        Provided for API compatibility with the Lua ``Task:yield()``.
        """
        # In generator-based Python, yield is a language keyword.
        # This method exists only for parity; callers should use
        # ``yield True`` / ``yield False`` inside their generator func.
        pass

    @classmethod
    def running(cls) -> Optional[Task]:
        """Return the currently running task, or ``None`` for main."""
        return _task_running

    @classmethod
    def dump(cls) -> None:
        """Log all active tasks across all priority queues."""
        header_printed = False

        for pri in range(1, _NUM_PRIORITIES + 1):
            queue = _task_queues[pri]
            if queue:
                if not header_printed:
                    log.info("Task queue:")
                    header_printed = True
                for task in queue:
                    log.info("%d: %s (%r)", pri, task.name, task)

    @classmethod
    def iterator(cls) -> Iterator[Task]:
        """
        Iterate over all active tasks in priority order.

        It is safe to add or remove tasks while iterating — we snapshot
        each queue before iterating over it.

        Yields tasks from PRIORITY_AUDIO first, then PRIORITY_HIGH,
        then PRIORITY_LOW.
        """
        for pri in range(1, _NUM_PRIORITIES + 1):
            # Snapshot the queue so mutations during iteration are safe
            snapshot = list(_task_queues[pri])
            for task in snapshot:
                # Only yield tasks still in the queue (may have been
                # removed by a previous task's resume in this tick)
                if task.state == STATE_ACTIVE:
                    yield task

    @classmethod
    def clear_all(cls) -> None:
        """
        Remove all tasks from all queues.

        Useful for testing and shutdown.
        """
        for pri in range(1, _NUM_PRIORITIES + 1):
            for task in list(_task_queues[pri]):
                task.state = STATE_SUSPENDED
            _task_queues[pri].clear()

    @classmethod
    def get_queue(cls, priority: int) -> List[Task]:
        """
        Return the task list for *priority* (for testing / inspection).

        Returns a shallow copy.
        """
        if priority < 1 or priority > _NUM_PRIORITIES:
            return []
        return list(_task_queues[priority])

    # ------------------------------------------------------------------
    # Representation
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return f"Task({self.name!r}, state={self.state}, priority={self.priority})"

    def __str__(self) -> str:
        return f"Task({self.name})"
