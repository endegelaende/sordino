"""
jive.net.process — Subprocess reader for network I/O.

Ported from ``jive/net/Process.lua`` in the original jivelite project.

Process provides a way to run an external command and read its output
asynchronously (cooperatively) using the Task scheduler.  In the Lua
original this uses ``io.popen`` with non-blocking reads via the
NetworkThread's select loop, plus FFI for ``fileno()``.

In Python we use ``subprocess.Popen`` with non-blocking reads.  On
Windows, ``popen`` is blocking in the Lua original too, so we match
that behavior: read all output at once.  On POSIX systems, we use
``selectors`` or simply read in chunks with the Task yielding between
reads.

Convention from the Lua original: methods prefixed with ``t_`` are
conceptually "thread-side" operations.  In this Python port everything
runs cooperatively in the main event loop, but we preserve the naming
convention for traceability.

Usage::

    from jive.net.process import Process

    proc = Process(jnt, "ls -la")
    proc.read(lambda chunk, err=None: print(chunk or err))

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Copyright 2013-2014 Adrian Smith (jivelite amendments)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Optional,
)

from jive.utils.log import logger

if TYPE_CHECKING:
    from jive.net.network_thread import NetworkThread

__all__ = ["Process"]

log = logger("net.socket")

# Buffer size for reading subprocess output
_READ_BUFSIZE = 8096

# Type for a sink function: called with (chunk, err) where chunk is
# bytes/str or None, and err is an error string or None.
ProcessSink = Callable[..., Any]


class Process:
    """
    A subprocess reader that provides cooperative reading.

    Mirrors ``jive.net.Process`` from the Lua original.

    The Process runs an external command and reads its stdout.  The
    results are delivered to a sink callback.

    Parameters
    ----------
    jnt : NetworkThread or None
        The network thread coordinator.  Used for registering
        read tasks in the non-blocking case.  May be ``None``
        for simple synchronous usage.
    prog : str
        The command line to execute (passed to the shell).

    States
    ------
    ``"suspended"`` — created but not yet started
    ``"running"``   — currently reading output
    ``"dead"``      — process completed or errored
    """

    __slots__ = ("jnt", "prog", "_status", "_proc")

    def __init__(
        self,
        jnt: Optional[NetworkThread] = None,
        prog: str = "",
    ) -> None:
        self.jnt: Optional[NetworkThread] = jnt
        self.prog: str = prog
        self._status: str = "suspended"
        self._proc: Optional[subprocess.Popen[bytes]] = None

    @property
    def status(self) -> str:
        """Return the current status of the process."""
        return self._status

    def read(self, sink: ProcessSink) -> None:
        """
        Start reading from the subprocess and deliver output to *sink*.

        The sink is called as:
        - ``sink(chunk)`` for each chunk of data read
        - ``sink(None)`` when EOF is reached (process finished)
        - ``sink(None, err)`` on error

        On Windows, this reads all output synchronously (matching the
        Lua original behavior).  On POSIX systems, reading is also
        done synchronously for simplicity in this port — the Task
        scheduler can be used to make it cooperative if needed.

        Parameters
        ----------
        sink : callable
            A function ``sink(chunk, err=None)`` that receives output
            data.  ``chunk`` is ``bytes`` or ``None`` (EOF).
        """
        try:
            self._proc = subprocess.Popen(
                self.prog,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
        except OSError as exc:
            sink(None, str(exc))
            self._status = "dead"
            return

        self._status = "running"

        is_windows = sys.platform == "win32" or "Windows" in os.environ.get("OS", "")

        if is_windows:
            # Blocking read on Windows (matching Lua original)
            try:
                stdout = self._proc.stdout
                if stdout is not None:
                    chunk = stdout.read()
                    self._proc.wait()
                    if chunk:
                        sink(chunk)
                    sink(None)
                else:
                    sink(None)
            except OSError as exc:
                sink(None, str(exc))

            self._status = "dead"
            return

        # POSIX: read in chunks
        try:
            stdout = self._proc.stdout
            if stdout is None:
                sink(None)
                self._status = "dead"
                return

            while True:
                chunk = stdout.read(_READ_BUFSIZE)
                if not chunk:
                    # EOF
                    sink(None)
                    break
                sink(chunk)

            self._proc.wait()
        except OSError as exc:
            sink(None, str(exc))

        self._status = "dead"

    def getfd(self) -> int:
        """
        Return the file descriptor of the subprocess stdout.

        This is used by the NetworkThread for select-based I/O
        registration.

        Returns
        -------
        int
            The file descriptor number, or -1 if not available.
        """
        if self._proc is not None and self._proc.stdout is not None:
            try:
                return self._proc.stdout.fileno()
            except (OSError, ValueError):
                return -1
        return -1

    def __repr__(self) -> str:
        return f"Process({self.prog!r}, status={self._status!r})"

    def __str__(self) -> str:
        return f"Process {{{self.prog}}}"
