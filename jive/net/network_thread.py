"""
jive.net.network_thread — Network I/O coordinator for the Jivelite Python3 port.

Ported from ``jive/net/NetworkThread.lua`` in the original jivelite project.

The NetworkThread is the central coordinator for all network I/O in
jivelite.  It manages:

* **Read/write socket lists** — sockets registered for select-based
  multiplexing, each associated with a Task that pumps data.
* **Timeout management** — sockets that have been idle too long are
  timed out and their tasks notified.
* **Network activity tracking** — counts active sockets for power
  management / UI indicators (spinning icon, etc.).
* **CPU activity tracking** — similar to network, for audio playback.
* **Subscriber notification** — pub/sub system for network events
  (``cometConnected``, ``cometDisconnected``, ``networkConnected``, etc.).
* **ARP lookups** — resolves MAC addresses for Wake-on-LAN.
* **DNS initialization** — creates the DNS singleton on startup.
* **SqueezeNetwork hostname** — configurable SN endpoint.

In the Lua original, NetworkThread uses LuaSocket's ``socket.select()``
for multiplexing and runs as a Task in the Framework's event loop.
In Python we use the standard library's ``select.select()`` (or
``selectors``) for the same purpose.

The ``task()`` method returns a Task that, when resumed by the
Framework event loop, performs one select cycle: checking which
sockets are ready for reading or writing, pumping their associated
tasks, and managing timeouts.

Convention from the Lua original: methods prefixed with ``t_`` are
conceptually "thread-side" operations.  In this Python port everything
runs cooperatively in the main event loop, but we preserve the naming
convention for traceability back to the Lua source.

Usage::

    from jive.net.network_thread import NetworkThread

    jnt = NetworkThread()

    # Create sockets that use this jnt
    # ...

    # Get the network task for the main event loop
    net_task = jnt.task()
    net_task.add_task()

    # In the Framework event loop, the task will be resumed each tick,
    # performing select-based I/O multiplexing.

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Copyright 2013-2014 Adrian Smith (jivelite amendments)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

import os
import platform
import re
import select
import time
import weakref
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Set,
    Tuple,
    Union,
)

from jive.ui.task import PRIORITY_HIGH, Task
from jive.utils.log import logger

if TYPE_CHECKING:
    import socket as _socket_mod

__all__ = ["NetworkThread"]

log = logger("net.thread")

# Default SqueezeNetwork hostname
_DEFAULT_SN_HOSTNAME = "www.squeezenetwork.com"


class _SocketEntry:
    """
    Internal bookkeeping for a registered socket.

    Tracks the associated Task, the last time the socket was active,
    and the timeout duration.

    Attributes
    ----------
    task : Task
        The Task that pumps this socket.
    last_seen : float
        Timestamp (ms) of the last activity on this socket.
    timeout : int
        Timeout in milliseconds.  0 means no timeout.
    """

    __slots__ = ("task", "last_seen", "timeout")

    def __init__(self, task: Task, last_seen: float, timeout: int) -> None:
        self.task: Task = task
        self.last_seen: float = last_seen
        self.timeout: int = timeout

    def __repr__(self) -> str:
        return f"_SocketEntry(task={self.task.name!r}, timeout={self.timeout}ms)"


class NetworkThread:
    """
    Network I/O coordinator — manages select-based socket multiplexing.

    Mirrors ``jive.net.NetworkThread`` from the Lua original.

    This class is the central hub for all network operations.  Sockets
    register themselves for read or write interest via ``t_add_read()``
    / ``t_add_write()``, and the network task (returned by ``task()``)
    performs ``select()`` each tick to dispatch ready sockets to their
    associated pump Tasks.

    Parameters
    ----------
    (none — the constructor takes no arguments, matching the Lua original)
    """

    __slots__ = (
        "_t_read_socks",
        "_t_read_entries",
        "_t_write_socks",
        "_t_write_entries",
        "_subscribers",
        "_network_active_count",
        "_network_is_active",
        "_network_active_callback",
        "_cpu_active_count",
        "_cpu_is_active",
        "_cpu_active_callback",
        "_sn_hostname",
        "_arp_enabled",
    )

    def __init__(self) -> None:
        # Lists of raw socket objects for select()
        self._t_read_socks: List[Any] = []
        self._t_write_socks: List[Any] = []

        # Mapping from socket object → _SocketEntry for bookkeeping
        self._t_read_entries: Dict[Any, _SocketEntry] = {}
        self._t_write_entries: Dict[Any, _SocketEntry] = {}

        # Subscriber notification system (weak references to subscribers)
        # Maps subscriber object → 1 (presence marker)
        self._subscribers: weakref.WeakValueDictionary[int, Any] = (
            weakref.WeakValueDictionary()
        )

        # Network activity tracking
        self._network_active_count: Dict[Any, int] = {}
        self._network_is_active: bool = False
        self._network_active_callback: Optional[Callable[[bool], None]] = None

        # CPU activity tracking
        self._cpu_active_count: Dict[Any, int] = {}
        self._cpu_is_active: bool = False
        self._cpu_active_callback: Optional[Callable[[bool], None]] = None

        # SqueezeNetwork hostname
        self._sn_hostname: str = _DEFAULT_SN_HOSTNAME

        # ARP enabled flag
        self._arp_enabled: bool = True

        # Initialize DNS singleton
        # Deferred import to avoid circular dependency
        try:
            from jive.net.dns import DNS

            DNS(self)
        except ImportError:
            log.debug("DNS module not available, skipping initialization")

    # ------------------------------------------------------------------
    # Socket registration (add / remove)
    # ------------------------------------------------------------------

    def _get_ticks(self) -> float:
        """
        Get the current time in milliseconds.

        Tries to use Framework.get_ticks() if available, otherwise
        falls back to time.time() * 1000.
        """
        try:
            from jive.ui.framework import framework

            if framework is not None:
                ticks = framework.get_ticks()
                if ticks > 0:
                    return ticks
        except (ImportError, AttributeError):
            pass
        return time.time() * 1000.0

    def t_add_read(
        self,
        sock: Any,
        task: Task,
        timeout: int = 60,
    ) -> None:
        """
        Add a socket to the read-select list with its pump Task.

        If the socket is already registered, the existing Task is
        replaced (the old Task is removed first if different).

        Parameters
        ----------
        sock : socket object
            The socket to monitor for readability.  May be a Python
            ``socket.socket``, a file-descriptor-like object, or any
            object compatible with ``select.select()``.
        task : Task
            The Task to resume when the socket is ready for reading.
        timeout : int
            Timeout in seconds.  0 means no timeout.
            Converted to milliseconds internally.
        """
        if sock is None:
            return

        now = self._get_ticks()
        timeout_ms = timeout * 1000

        if sock in self._t_read_entries:
            entry = self._t_read_entries[sock]
            # Replace task if different
            if entry.task is not None and entry.task is not task:
                entry.task.remove_task()
            entry.task = task
            entry.timeout = timeout_ms
            entry.last_seen = now
        else:
            # New socket — add to list and create entry
            self._t_read_socks.append(sock)
            self._t_read_entries[sock] = _SocketEntry(
                task=task,
                last_seen=now,
                timeout=timeout_ms,
            )

    def t_remove_read(self, sock: Any) -> None:
        """
        Remove a socket from the read-select list.

        Parameters
        ----------
        sock : socket object
            The socket to unregister.
        """
        if sock is None:
            return

        entry = self._t_read_entries.pop(sock, None)
        if entry is not None:
            if entry.task is not None:
                entry.task.remove_task()
            try:
                self._t_read_socks.remove(sock)
            except ValueError:
                pass

    def t_add_write(
        self,
        sock: Any,
        task: Task,
        timeout: int = 60,
    ) -> None:
        """
        Add a socket to the write-select list with its pump Task.

        Parameters
        ----------
        sock : socket object
            The socket to monitor for writability.
        task : Task
            The Task to resume when the socket is ready for writing.
        timeout : int
            Timeout in seconds.  0 means no timeout.
        """
        if sock is None:
            return

        now = self._get_ticks()
        timeout_ms = timeout * 1000

        if sock in self._t_write_entries:
            entry = self._t_write_entries[sock]
            if entry.task is not None and entry.task is not task:
                entry.task.remove_task()
            entry.task = task
            entry.timeout = timeout_ms
            entry.last_seen = now
        else:
            self._t_write_socks.append(sock)
            self._t_write_entries[sock] = _SocketEntry(
                task=task,
                last_seen=now,
                timeout=timeout_ms,
            )

    def t_remove_write(self, sock: Any) -> None:
        """
        Remove a socket from the write-select list.

        Parameters
        ----------
        sock : socket object
            The socket to unregister.
        """
        if sock is None:
            return

        entry = self._t_write_entries.pop(sock, None)
        if entry is not None:
            if entry.task is not None:
                entry.task.remove_task()
            try:
                self._t_write_socks.remove(sock)
            except ValueError:
                pass

    # ------------------------------------------------------------------
    # Select loop
    # ------------------------------------------------------------------

    def _t_timeout(
        self,
        now: float,
        sock_list: List[Any],
        entries: Dict[Any, _SocketEntry],
    ) -> None:
        """
        Check for timed-out sockets and notify their tasks.

        Parameters
        ----------
        now : float
            Current time in milliseconds.
        sock_list : list
            The list of socket objects (read or write).
        entries : dict
            The socket → _SocketEntry mapping.
        """
        # Iterate over a copy to allow mutation during iteration
        for sock in list(sock_list):
            entry = entries.get(sock)
            if entry is None:
                continue

            # Check if timeout has expired (timeout > 0 means enabled)
            if entry.timeout > 0 and (now - entry.last_seen) > entry.timeout:
                log.warn("network thread timeout for %s", entry.task.name)
                entry.task.add_task("inactivity timeout")

    def _t_select(self, timeout_secs: float) -> None:
        """
        Perform one cycle of select-based socket multiplexing.

        Checks which registered sockets are ready for reading or
        writing, updates their last-seen timestamps, and resumes
        their associated Tasks.

        Parameters
        ----------
        timeout_secs : float
            The select timeout in seconds.  If negative, clamped to 0.
        """
        if timeout_secs < 0:
            timeout_secs = 0

        # If no sockets to watch, just sleep briefly
        if not self._t_read_socks and not self._t_write_socks:
            return

        # Filter out any None or closed sockets before select.
        # On Windows, a closed socket may return fileno() == -1 rather
        # than raising an exception, so we check for that explicitly.
        stale_read: List[Any] = []
        read_socks = []
        for s in self._t_read_socks:
            if s is None:
                stale_read.append(s)
                continue
            try:
                fd = s.fileno() if hasattr(s, "fileno") else 0
                if fd < 0:
                    stale_read.append(s)
                else:
                    read_socks.append(s)
            except (OSError, ValueError):
                stale_read.append(s)

        stale_write: List[Any] = []
        write_socks = []
        for s in self._t_write_socks:
            if s is None:
                stale_write.append(s)
                continue
            try:
                fd = s.fileno() if hasattr(s, "fileno") else 0
                if fd < 0:
                    stale_write.append(s)
                else:
                    write_socks.append(s)
            except (OSError, ValueError):
                stale_write.append(s)

        # Remove stale sockets from our tracking lists
        for s in stale_read:
            self.t_remove_read(s)
        for s in stale_write:
            self.t_remove_write(s)

        try:
            r, w, e = select.select(
                read_socks,
                write_socks,
                [],
                timeout_secs,
            )
        except (OSError, ValueError) as exc:
            # Select error — may happen if a socket was closed between
            # our check and the select call
            if str(exc) != "timeout":
                log.error("select error: %s", exc)
            return

        now = self._get_ticks()

        # Process writable sockets
        for sock in w:
            entry = self._t_write_entries.get(sock)
            if entry is not None:
                entry.last_seen = now
                if not entry.task.add_task():
                    # Task refused to add (error state) — remove socket
                    self.t_remove_write(sock)

        # Process readable sockets
        for sock in r:
            entry = self._t_read_entries.get(sock)
            if entry is not None:
                entry.last_seen = now
                if not entry.task.add_task():
                    self.t_remove_read(sock)

        # Check for timeouts
        self._t_timeout(now, self._t_read_socks, self._t_read_entries)
        self._t_timeout(now, self._t_write_socks, self._t_write_entries)

    # ------------------------------------------------------------------
    # Task factory
    # ------------------------------------------------------------------

    def task(self) -> Task:
        """
        Create and return the network Task.

        This Task should be added to the Framework's task scheduler.
        Each time it is resumed, it performs one cycle of select-based
        I/O multiplexing.

        The Task runs at ``PRIORITY_HIGH`` to ensure network I/O is
        processed promptly.

        Returns
        -------
        Task
            A generator-based Task that loops indefinitely, performing
            select and yielding between cycles.
        """
        jnt = self

        def _run(obj: Any, *args: Any) -> Any:
            """Network task main loop — select and yield."""
            log.debug("NetworkThread starting...")

            # Initial timeout comes from args if provided
            timeout = args[0] if args else 100  # default 100ms

            while True:
                timeout_secs = timeout / 1000.0
                if timeout_secs < 0:
                    timeout_secs = 0

                try:
                    jnt._t_select(timeout_secs)
                except Exception as exc:
                    log.error("error in _t_select: %s", exc)

                # Yield True to stay active, receive next timeout
                result = yield True
                if result is not None:
                    timeout = result
                else:
                    timeout = 100

        return Task("networkTask", self, _run, priority=PRIORITY_HIGH)

    # ------------------------------------------------------------------
    # Subscriber notification (pub/sub)
    # ------------------------------------------------------------------

    def subscribe(self, obj: Any) -> None:
        """
        Subscribe an object to receive network notifications.

        The object should implement methods named ``notify_<event>``
        (e.g., ``notify_networkConnected``, ``notify_cometConnected``)
        which will be called when the corresponding event occurs.

        Subscribers are held via weak references so they will be
        automatically garbage-collected when no longer referenced
        elsewhere.

        Parameters
        ----------
        obj : Any
            The subscriber object.
        """
        self._subscribers[id(obj)] = obj

    def unsubscribe(self, obj: Any) -> None:
        """
        Unsubscribe an object from network notifications.

        Parameters
        ----------
        obj : Any
            The subscriber object.
        """
        self._subscribers.pop(id(obj), None)

    def notify(self, event: str, *args: Any) -> None:
        """
        Notify all subscribers of an event.

        Calls ``subscriber.notify_<event>(*args)`` on each subscriber
        that implements the corresponding method.

        Parameters
        ----------
        event : str
            The event name (e.g., ``"cometConnected"``).
        *args : Any
            Arguments to pass to the notification method.
        """
        method_name = f"notify_{event}"

        log.debug(
            "NOTIFY: %s(%s)",
            event,
            ", ".join(str(a) for a in args),
        )

        # Iterate over a snapshot of subscribers (weak refs may expire)
        for obj_id, obj in list(self._subscribers.items()):
            method = getattr(obj, method_name, None)
            if method is not None and callable(method):
                try:
                    method(*args)
                except Exception as exc:
                    log.error("Error running %s: %s", method_name, exc)
                else:
                    applet_name = getattr(
                        getattr(obj, "_entry", None), "appletName", None
                    )
                    if applet_name:
                        log.debug("%s sent to %s", method_name, applet_name)

    # ------------------------------------------------------------------
    # Network activity tracking
    # ------------------------------------------------------------------

    def network_active(self, obj: Any) -> None:
        """
        Notify that a socket/object is actively performing network I/O.

        Used for power management and UI indicators.

        Parameters
        ----------
        obj : Any
            The active object (typically a socket instance).
        """
        self._network_active_count[id(obj)] = 1

        if self._network_active_count and not self._network_is_active:
            if self._network_active_callback is not None:
                try:
                    self._network_active_callback(True)
                except Exception as exc:
                    log.error("network_active callback error: %s", exc)
            self._network_is_active = True

    def network_inactive(self, obj: Any) -> None:
        """
        Notify that a socket/object is no longer performing network I/O.

        Parameters
        ----------
        obj : Any
            The inactive object.
        """
        self._network_active_count.pop(id(obj), None)

        if not self._network_active_count and self._network_is_active:
            if self._network_active_callback is not None:
                try:
                    self._network_active_callback(False)
                except Exception as exc:
                    log.error("network_inactive callback error: %s", exc)
            self._network_is_active = False

    def register_network_active(self, callback: Callable[[bool], None]) -> None:
        """
        Register a callback for network activity state changes.

        The callback is called with ``True`` when network activity
        begins and ``False`` when it ends.

        Parameters
        ----------
        callback : callable
            A function ``callback(is_active: bool)``.
        """
        self._network_active_callback = callback

    # ------------------------------------------------------------------
    # CPU activity tracking
    # ------------------------------------------------------------------

    def cpu_active(self, obj: Any) -> None:
        """
        Notify that an object is actively using the CPU (e.g., audio playback).

        Parameters
        ----------
        obj : Any
            The active object.
        """
        self._cpu_active_count[id(obj)] = 1

        if self._cpu_active_count and not self._cpu_is_active:
            if self._cpu_active_callback is not None:
                try:
                    self._cpu_active_callback(True)
                except Exception as exc:
                    log.error("cpu_active callback error: %s", exc)
            self._cpu_is_active = True

    def cpu_inactive(self, obj: Any) -> None:
        """
        Notify that an object is no longer actively using the CPU.

        Parameters
        ----------
        obj : Any
            The inactive object.
        """
        self._cpu_active_count.pop(id(obj), None)

        if not self._cpu_active_count and self._cpu_is_active:
            if self._cpu_active_callback is not None:
                try:
                    self._cpu_active_callback(False)
                except Exception as exc:
                    log.error("cpu_inactive callback error: %s", exc)
            self._cpu_is_active = False

    def register_cpu_active(self, callback: Callable[[bool], None]) -> None:
        """
        Register a callback for CPU activity state changes.

        Parameters
        ----------
        callback : callable
            A function ``callback(is_active: bool)``.
        """
        self._cpu_active_callback = callback

    # ------------------------------------------------------------------
    # SqueezeNetwork hostname
    # ------------------------------------------------------------------

    def get_sn_hostname(self) -> str:
        """
        Get the hostname used to connect to SqueezeNetwork.

        Returns
        -------
        str
            The SqueezeNetwork hostname.
        """
        return self._sn_hostname

    def set_sn_hostname(self, hostname: str) -> None:
        """
        Set the SqueezeNetwork hostname.

        Used with test.squeezenetwork.com or custom endpoints.

        Parameters
        ----------
        hostname : str
            The new hostname.
        """
        self._sn_hostname = hostname

    # ------------------------------------------------------------------
    # ARP
    # ------------------------------------------------------------------

    def is_arp_enabled(self) -> bool:
        """Return whether ARP lookups are enabled."""
        return self._arp_enabled

    def set_arp_enabled(self, enabled: bool) -> None:
        """Enable or disable ARP lookups."""
        self._arp_enabled = enabled

    def arp(
        self,
        host: str,
        sink: Callable[[Optional[str], Optional[str]], None],
    ) -> None:
        """
        Look up the hardware (MAC) address for a host.

        This is an asynchronous operation — the *sink* function is
        called when the hardware address is known, or with an error.

        Parameters
        ----------
        host : str
            The hostname or IP address to look up.
        sink : callable
            A function ``sink(mac, err=None)`` that receives the MAC
            address as a string (e.g., ``"00:1a:2b:3c:4d:5e"``), or
            ``None`` with an error string.
        """
        log.debug("NetworkThread:arp() enabled: %s", self._arp_enabled)

        if not self._arp_enabled:
            sink(None, "Arp disabled")
            return

        # Build the ARP command
        is_windows = platform.system() == "Windows" or "Windows" in os.environ.get(
            "OS", ""
        )
        if is_windows:
            cmd = f"arp -a {host}"
        else:
            cmd = f"arp {host}"

        log.debug("NetworkThread:arp() cmd: %s", cmd)

        # Use Process to run the command
        from jive.net.process import Process

        arp_output: List[str] = []

        def _arp_sink(
            chunk: Optional[Union[bytes, str]] = None,
            err: Optional[str] = None,
        ) -> None:
            if err:
                sink(None, err)
                return

            if chunk is not None:
                if isinstance(chunk, bytes):
                    chunk = chunk.decode("utf-8", errors="replace")
                arp_output.append(chunk)
            else:
                # EOF — parse the output for a MAC address
                full_output = "".join(arp_output)

                # Match MAC address pattern (xx:xx:xx:xx:xx:xx or xx-xx-xx-xx-xx-xx)
                mac_match = re.search(
                    r"([0-9a-fA-F]{1,2}[:-]"
                    r"[0-9a-fA-F]{1,2}[:-]"
                    r"[0-9a-fA-F]{1,2}[:-]"
                    r"[0-9a-fA-F]{1,2}[:-]"
                    r"[0-9a-fA-F]{1,2}[:-]"
                    r"[0-9a-fA-F]{1,2})",
                    full_output,
                )

                if mac_match:
                    mac = mac_match.group(1)
                    # Normalize separators to ':'
                    mac = mac.replace("-", ":")
                    # Pad single-character elements with leading zero
                    elements = mac.split(":")
                    padded = [e.zfill(2) for e in elements]
                    mac = ":".join(padded)
                    log.debug("NetworkThread:arp() mac: %s", mac)
                    sink(mac)
                else:
                    log.debug("NetworkThread:arp() mac: None")
                    sink(None)

        proc = Process(self, cmd)
        proc.read(_arp_sink)

    # ------------------------------------------------------------------
    # Socket count (for diagnostics)
    # ------------------------------------------------------------------

    @property
    def read_socket_count(self) -> int:
        """Return the number of registered read sockets."""
        return len(self._t_read_socks)

    @property
    def write_socket_count(self) -> int:
        """Return the number of registered write sockets."""
        return len(self._t_write_socks)

    # ------------------------------------------------------------------
    # Representation
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"NetworkThread("
            f"read={len(self._t_read_socks)}, "
            f"write={len(self._t_write_socks)})"
        )

    def __str__(self) -> str:
        return "NetworkThread"
