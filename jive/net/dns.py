"""
jive.net.dns — Non-blocking DNS resolution.

Ported from ``jive/net/DNS.lua`` in the original jivelite project.

The Lua original implements non-blocking DNS queries using a custom
C-level DNS library (``jive.dns``) that provides an asynchronous
file-descriptor-based API.  Queries are dispatched via the
NetworkThread's select loop, with Tasks yielding while waiting for
results.

In Python we use the standard library's ``socket.getaddrinfo()`` and
``socket.gethostbyaddr()`` for DNS resolution.  Since these are
blocking calls, we wrap them so they can be called from within a
Task context.  For true non-blocking behavior in a production
environment, these could be offloaded to a thread pool — but for
the jivelite use case (infrequent lookups, cooperative scheduling),
synchronous resolution is acceptable and matches the simplicity of
the original.

The DNS class is a singleton (like the Lua original) — only one
instance is created and shared across the application.

Convention from the Lua original: methods prefixed with ``t_`` are
conceptually "thread-side" operations.  In this Python port everything
runs cooperatively in the main event loop, but we preserve the naming
convention for traceability.

Usage::

    from jive.net.dns import DNS

    dns = DNS(jnt)

    # Check if a string is an IP address
    if dns.is_ip("192.168.1.1"):
        print("It's an IP")

    # Resolve hostname to IP (should be called from within a Task)
    ip, hostent = dns.toip("www.example.com")

    # Reverse lookup (should be called from within a Task)
    hostname, hostent = dns.tohostname("192.168.1.1")

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Copyright 2013-2014 Adrian Smith (jivelite amendments)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

import re
import socket as _socket_mod
from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    List,
    Optional,
    Tuple,
    Union,
)

from jive.utils.log import logger

if TYPE_CHECKING:
    from jive.net.network_thread import NetworkThread

__all__ = ["DNS"]

log = logger("net.socket")

# Regex pattern for matching IPv4 addresses
_IPV4_PATTERN = re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$")

# Regex pattern for matching IPv6 addresses (simplified)
_IPV6_PATTERN = re.compile(r"^[0-9a-fA-F:]+$")


class HostEntry:
    """
    A host entry result from DNS resolution.

    Mirrors the ``hostent`` table structure returned by the Lua DNS
    library, containing hostname, aliases, and IP addresses.

    Attributes
    ----------
    name : str
        The canonical hostname.
    aliases : list of str
        Alternative names for the host.
    ip : list of str
        IP addresses associated with the host.
    """

    __slots__ = ("name", "aliases", "ip")

    def __init__(
        self,
        name: str = "",
        aliases: Optional[List[str]] = None,
        ip: Optional[List[str]] = None,
    ) -> None:
        self.name: str = name
        self.aliases: List[str] = aliases if aliases is not None else []
        self.ip: List[str] = ip if ip is not None else []

    def __repr__(self) -> str:
        return f"HostEntry(name={self.name!r}, ip={self.ip!r})"

    def __str__(self) -> str:
        return f"HostEntry {{{self.name}: {', '.join(self.ip)}}}"


class DNS:
    """
    Non-blocking DNS resolution singleton.

    Mirrors ``jive.net.DNS`` from the Lua original.

    This is a singleton class — the first call to ``DNS(jnt)`` creates
    the instance; subsequent calls return the same instance.

    In the Lua original, DNS uses a custom C library (``jive.dns``)
    that provides asynchronous resolution via a socket file descriptor
    that can be added to the select loop.  In Python, we use the
    standard library's synchronous DNS functions (``socket.getaddrinfo``,
    ``socket.gethostbyaddr``), which is acceptable for the cooperative
    scheduling model used by jivelite.

    Parameters
    ----------
    jnt : NetworkThread or None
        The network thread coordinator.  Stored for future use
        but not strictly required for DNS operations in this port.
    """

    # Singleton instance
    _instance: Optional[DNS] = None

    __slots__ = ("jnt",)

    def __new__(cls, jnt: Optional[NetworkThread] = None) -> DNS:
        if cls._instance is not None:
            return cls._instance
        instance = super().__new__(cls)
        cls._instance = instance
        return instance

    def __init__(self, jnt: Optional[NetworkThread] = None) -> None:
        # Only initialize once (singleton)
        if hasattr(self, "jnt"):
            return
        self.jnt: Optional[NetworkThread] = jnt

    @classmethod
    def reset(cls) -> None:
        """
        Reset the singleton instance.

        Primarily useful for testing to ensure a fresh state.
        """
        cls._instance = None

    # ------------------------------------------------------------------
    # IP address detection
    # ------------------------------------------------------------------

    def is_ip(self, address: str) -> bool:
        """
        Check if *address* looks like an IP address (IPv4).

        This is a crude check matching the Lua original's
        ``string.match(address, "%d+%.%d+%.%d+%.%d+")``.

        Parameters
        ----------
        address : str
            The address string to check.

        Returns
        -------
        bool
            ``True`` if *address* matches an IPv4 dotted-decimal pattern.
        """
        if not address:
            return False
        return _IPV4_PATTERN.match(address) is not None

    # ------------------------------------------------------------------
    # Forward resolution (hostname → IP)
    # ------------------------------------------------------------------

    def toip(
        self, address: str
    ) -> Tuple[Optional[str], Optional[Union[HostEntry, str]]]:
        """
        Resolve a hostname to an IP address.

        Mirrors ``socket.dns.toip`` from LuaSocket / ``DNS:toip()``
        from the Lua original.

        In the Lua original this must be called from within a Task
        (it yields while waiting for the DNS response).  In this
        Python port the resolution is synchronous, but the API
        signature is preserved for compatibility.

        Parameters
        ----------
        address : str
            The hostname to resolve, or an IP address (returned as-is).

        Returns
        -------
        tuple of (str or None, HostEntry or str)
            On success: ``(ip_address, HostEntry)``
            On failure: ``(None, error_string)``
        """
        log.debug("DNS:toip(%s)", address)

        # If it's already an IP, return it directly
        if self.is_ip(address):
            hostent = HostEntry(name=address, ip=[address])
            return address, hostent

        try:
            # Use getaddrinfo for forward resolution
            results = _socket_mod.getaddrinfo(
                address,
                None,
                _socket_mod.AF_INET,
                _socket_mod.SOCK_STREAM,
            )

            if not results:
                err = f"DNS resolution failed for {address}"
                log.error(err)
                return None, err

            # Extract unique IP addresses
            ips: List[str] = []
            seen: set[str] = set()
            for family, socktype, proto, canonname, sockaddr in results:
                ip = sockaddr[0]
                if ip not in seen:
                    seen.add(ip)  # type: ignore[arg-type]
                    ips.append(ip)  # type: ignore[arg-type]

            # Try to get canonical name
            canonical = address
            for family, socktype, proto, canonname, sockaddr in results:
                if canonname:
                    canonical = canonname
                    break

            hostent = HostEntry(name=canonical, ip=ips)
            log.debug("DNS:toip(%s) -> %s", address, ips[0])
            return ips[0], hostent

        except _socket_mod.gaierror as exc:
            err = f"DNS resolution failed for {address}: {exc}"
            log.error(err)
            return None, err
        except OSError as exc:
            err = f"DNS error for {address}: {exc}"
            log.error(err)
            return None, err

    # ------------------------------------------------------------------
    # Reverse resolution (IP → hostname)
    # ------------------------------------------------------------------

    def tohostname(
        self, address: str
    ) -> Tuple[Optional[str], Optional[Union[HostEntry, str]]]:
        """
        Resolve an IP address to a hostname (reverse lookup).

        Mirrors ``socket.dns.tohostname`` from LuaSocket /
        ``DNS:tohostname()`` from the Lua original.

        In the Lua original this must be called from within a Task
        (it yields while waiting for the DNS response).  In this
        Python port the resolution is synchronous, but the API
        signature is preserved for compatibility.

        Parameters
        ----------
        address : str
            The IP address to reverse-resolve.

        Returns
        -------
        tuple of (str or None, HostEntry or str)
            On success: ``(hostname, HostEntry)``
            On failure: ``(None, error_string)``
        """
        log.debug("DNS:tohostname(%s)", address)

        try:
            hostname, aliases, ipaddrlist = _socket_mod.gethostbyaddr(address)

            hostent = HostEntry(
                name=hostname,
                aliases=list(aliases) if aliases else [],
                ip=list(ipaddrlist) if ipaddrlist else [address],
            )

            log.debug("DNS:tohostname(%s) -> %s", address, hostname)
            return hostname, hostent

        except _socket_mod.herror as exc:
            err = f"Reverse DNS failed for {address}: {exc}"
            log.error(err)
            return None, err
        except _socket_mod.gaierror as exc:
            err = f"Reverse DNS failed for {address}: {exc}"
            log.error(err)
            return None, err
        except OSError as exc:
            err = f"DNS error for {address}: {exc}"
            log.error(err)
            return None, err

    # ------------------------------------------------------------------
    # Representation
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return "DNS()"

    def __str__(self) -> str:
        return "DNS"
