"""
jive.net — Network layer for the Jivelite Python3 port.

Ported from the original Lua networking modules in
``share/jive/jive/net/`` of the jivelite project.

The Lua original uses LuaSocket for TCP/UDP/HTTP operations with a
custom select()-based network thread (NetworkThread) and LTN12
source/sink streaming pipelines.  In Python we use the standard
library's ``socket`` and ``selectors`` modules, replacing LTN12
pipelines with simple callbacks and the cooperative Task scheduler
(generator-based coroutines from ``jive.ui.task``).

Modules (M9):

  Foundation (M9a):
    - socket_base: Abstract base socket (open/close, read/write pump registration)
    - socket_tcp: TCP client socket (connect, send/receive)
    - socket_udp: UDP socket (broadcast, sendto/receivefrom)
    - process: Subprocess reader (popen, non-blocking read via Task)
    - dns: Non-blocking DNS resolution (async hostname lookup)
    - network_thread: Select-based network I/O coordinator (read/write/timeout)
    - wake_on_lan: Wake-on-LAN magic packet sender

  HTTP (M9b):
    - request_http: HTTP request object (method, URI, headers, body, response sink)
    - request_jsonrpc: JSON-RPC request over HTTP POST
    - socket_http: HTTP client socket (state machine: connect/send/receive/pipeline)
    - socket_http_queue: HTTP socket with external request queue
    - http_pool: Connection pool managing multiple HTTP sockets

  Comet (M9c):
    - comet_request: Comet/Bayeux HTTP request (JSON body, chunked response)
    - comet: Cometd/Bayeux protocol client (subscribe, request, long-polling)

  Slim Protocol:
    - (in jive.slim package)

Design decisions:

  - LuaSocket → Python ``socket`` stdlib module
  - LTN12 source/sink → Python callbacks / generator yields
  - ``socket.select()`` → Python ``selectors.DefaultSelector``
  - LOOP OOP → Python classes with inheritance
  - Lua coroutines in network pumps → Python generators via Task
  - ``lfs`` (LuaFileSystem) → Python ``pathlib`` / ``os``
  - ``mime.b64`` → Python ``base64.b64encode``
  - ``cjson`` → Python ``json`` (already ported in jive.utils.jsonfilters)

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Copyright 2013-2014 Adrian Smith (jivelite amendments)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

__all__ = [
    # M9a — Foundation
    "socket_base",
    "socket_tcp",
    "socket_udp",
    "process",
    "dns",
    "network_thread",
    "wake_on_lan",
    "socket_tcp_server",
    # M9b — HTTP
    "request_http",
    "request_jsonrpc",
    "socket_http",
    "socket_http_queue",
    "http_pool",
    # M9c — Comet
    "comet_request",
    "comet",
]
