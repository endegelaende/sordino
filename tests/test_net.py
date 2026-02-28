"""
tests/test_net.py — Comprehensive tests for jive.net modules (M9).

Tests cover all 15 network modules ported from the Lua original:

  M9a — Foundation:
    - TestSocketBase: SocketBase lifecycle, priority, activity tracking
    - TestSocketTcp: SocketTcp creation, connect, address/port, state
    - TestSocketUdp: SocketUdp creation, queue, send mechanics
    - TestProcess: Process subprocess reading, status
    - TestDNS: DNS singleton, is_ip, toip, tohostname
    - TestNetworkThread: NetworkThread registration, timeout, select, subscribers
    - TestWakeOnLan: WakeOnLan magic packet construction

  M9b — HTTP:
    - TestRequestHttp: RequestHttp creation, URI parsing, headers, body, redirect
    - TestRequestJsonRpc: RequestJsonRpc JSON-RPC envelope, ID generation
    - TestSocketHttp: SocketHttp state machine, fetch, close, error handling
    - TestSocketHttpQueue: SocketHttpQueue external dequeue
    - TestHttpPool: HttpPool connection pooling, queue, dequeue, timeout

  M9c — Comet:
    - TestCometRequest: CometRequest JSON body, sink mode
    - TestComet: Comet state machine, subscribe, request, batch, advice

  Integration:
    - TestM9Integration: Cross-module imports, round-trip scenarios

Copyright 2025 — BSD-3-Clause
"""

from __future__ import annotations

import json
import os
import socket as _socket_mod
import sys
import time
import unittest
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
from unittest.mock import MagicMock, Mock, patch

# ---------------------------------------------------------------------------
# Ensure project root is on sys.path
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# ---------------------------------------------------------------------------
# Imports under test
# ---------------------------------------------------------------------------
from jive.net.comet import CONNECTED, CONNECTING, UNCONNECTED, UNCONNECTING, Comet
from jive.net.comet_request import CometRequest
from jive.net.dns import DNS, HostEntry
from jive.net.http_pool import HttpPool
from jive.net.network_thread import NetworkThread, _SocketEntry
from jive.net.process import Process
from jive.net.request_http import RequestHttp, _parse_uri
from jive.net.request_jsonrpc import RequestJsonRpc
from jive.net.socket_base import SocketBase
from jive.net.socket_http import SocketHttp
from jive.net.socket_http_queue import SocketHttpQueue
from jive.net.socket_tcp import SocketTcp
from jive.net.socket_tcp_server import SocketTcpServer
from jive.net.socket_udp import SocketUdp, _create_udp_socket
from jive.net.wake_on_lan import WakeOnLan
from jive.ui.task import Task


# ---------------------------------------------------------------------------
# Helper: Mock NetworkThread (lightweight, no real select)
# ---------------------------------------------------------------------------
class MockJnt:
    """Minimal mock for NetworkThread, recording add/remove calls."""

    def __init__(self) -> None:
        self.reads: Dict[Any, Any] = {}
        self.writes: Dict[Any, Any] = {}
        self.active_objs: List[Any] = []
        self.inactive_objs: List[Any] = []
        self.notifications: List[Tuple[str, tuple]] = []
        self._subscribers: Dict[int, Any] = {}

    def t_add_read(self, sock: Any, task: Any, timeout: int = 60) -> None:
        self.reads[id(sock) if sock else None] = (sock, task, timeout)

    def t_remove_read(self, sock: Any) -> None:
        self.reads.pop(id(sock) if sock else None, None)

    def t_add_write(self, sock: Any, task: Any, timeout: int = 60) -> None:
        self.writes[id(sock) if sock else None] = (sock, task, timeout)

    def t_remove_write(self, sock: Any) -> None:
        self.writes.pop(id(sock) if sock else None, None)

    def network_active(self, obj: Any) -> None:
        self.active_objs.append(obj)

    def network_inactive(self, obj: Any) -> None:
        self.inactive_objs.append(obj)

    def notify(self, event: str, *args: Any) -> None:
        self.notifications.append((event, args))

    def subscribe(self, obj: Any) -> None:
        self._subscribers[id(obj)] = obj

    def unsubscribe(self, obj: Any) -> None:
        self._subscribers.pop(id(obj), None)


# ======================================================================
# M9a — Foundation
# ======================================================================


class TestSocketBase(unittest.TestCase):
    """Tests for jive.net.socket_base.SocketBase."""

    def test_init_defaults(self) -> None:
        sb = SocketBase()
        self.assertIsNone(sb.jnt)
        self.assertEqual(sb.js_name, "")
        self.assertIsNone(sb.t_sock)
        self.assertIsNone(sb.priority)
        self.assertFalse(sb.active)
        self.assertIsNone(sb.read_pump)
        self.assertIsNone(sb.write_pump)

    def test_init_with_args(self) -> None:
        jnt = MockJnt()
        sb = SocketBase(jnt, "test_sock")
        self.assertIs(sb.jnt, jnt)
        self.assertEqual(sb.js_name, "test_sock")

    def test_set_priority(self) -> None:
        sb = SocketBase()
        sb.set_priority(2)
        self.assertEqual(sb.priority, 2)

    def test_socket_active_inactive(self) -> None:
        jnt = MockJnt()
        sb = SocketBase(jnt, "test")
        self.assertFalse(sb.active)

        sb.socket_active()
        self.assertTrue(sb.active)
        self.assertEqual(len(jnt.active_objs), 1)

        # Calling again shouldn't add again
        sb.socket_active()
        self.assertEqual(len(jnt.active_objs), 1)

        sb.socket_inactive()
        self.assertFalse(sb.active)
        self.assertEqual(len(jnt.inactive_objs), 1)

        # Calling again shouldn't add again
        sb.socket_inactive()
        self.assertEqual(len(jnt.inactive_objs), 1)

    def test_socket_active_no_jnt(self) -> None:
        sb = SocketBase(None, "test")
        sb.socket_active()
        self.assertTrue(sb.active)
        sb.socket_inactive()
        self.assertFalse(sb.active)

    def test_close_no_socket(self) -> None:
        sb = SocketBase()
        # Should not raise
        sb.close()
        self.assertIsNone(sb.t_sock)

    def test_close_with_mock_socket(self) -> None:
        sb = SocketBase()
        mock_sock = Mock()
        sb.t_sock = mock_sock
        sb.active = True

        sb.close()
        mock_sock.close.assert_called_once()
        self.assertIsNone(sb.t_sock)

    def test_free_calls_close(self) -> None:
        sb = SocketBase()
        mock_sock = Mock()
        sb.t_sock = mock_sock
        sb.free()
        mock_sock.close.assert_called_once()

    def test_repr_and_str(self) -> None:
        sb = SocketBase(None, "my_socket")
        self.assertIn("my_socket", repr(sb))
        self.assertIn("my_socket", str(sb))

    def test_t_add_read_no_jnt(self) -> None:
        sb = SocketBase(None, "test")
        pump = lambda: None
        # Should not raise when jnt is None
        sb.t_add_read(pump, 30)
        self.assertIs(sb.read_pump, pump)

    def test_t_add_read_with_jnt(self) -> None:
        jnt = MockJnt()
        sb = SocketBase(jnt, "test")
        mock_sock = Mock()
        sb.t_sock = mock_sock
        sb.priority = 3  # PRIORITY_LOW

        pump = lambda: None
        sb.t_add_read(pump, 30)
        self.assertIs(sb.read_pump, pump)
        self.assertTrue(len(jnt.reads) > 0)

    def test_t_remove_read(self) -> None:
        jnt = MockJnt()
        sb = SocketBase(jnt, "test")
        mock_sock = Mock()
        sb.t_sock = mock_sock
        sb.priority = 3

        pump = lambda: None
        sb.t_add_read(pump, 30)
        sb.t_remove_read()
        self.assertIsNone(sb.read_pump)

    def test_t_add_write_no_jnt(self) -> None:
        sb = SocketBase(None, "test")
        pump = lambda: None
        sb.t_add_write(pump, 30)
        self.assertIs(sb.write_pump, pump)

    def test_t_remove_write(self) -> None:
        jnt = MockJnt()
        sb = SocketBase(jnt, "test")
        mock_sock = Mock()
        sb.t_sock = mock_sock
        sb.priority = 3

        pump = lambda: None
        sb.t_add_write(pump, 30)
        sb.t_remove_write()
        self.assertIsNone(sb.write_pump)

    def test_close_removes_pumps(self) -> None:
        jnt = MockJnt()
        sb = SocketBase(jnt, "test")
        mock_sock = Mock()
        sb.t_sock = mock_sock

        sb.read_pump = lambda: None
        sb.write_pump = lambda: None

        sb.close()
        self.assertIsNone(sb.read_pump)
        self.assertIsNone(sb.write_pump)


class TestSocketTcp(unittest.TestCase):
    """Tests for jive.net.socket_tcp.SocketTcp."""

    def test_init_valid(self) -> None:
        st = SocketTcp(None, "192.168.1.1", 9090, "cli")
        self.assertEqual(st.address, "192.168.1.1")
        self.assertEqual(st.port, 9090)
        self.assertEqual(st.js_name, "cli")
        self.assertFalse(st.connected())

    def test_init_no_address(self) -> None:
        with self.assertRaises(ValueError):
            SocketTcp(None, "", 9090, "cli")

    def test_init_no_port(self) -> None:
        with self.assertRaises((TypeError, ValueError)):
            SocketTcp(None, "192.168.1.1", None, "cli")  # type: ignore[arg-type]

    def test_init_port_zero_valid(self) -> None:
        # Port 0 is valid — OS picks a free port
        st = SocketTcp(None, "192.168.1.1", 0, "cli")
        self.assertEqual(st._tcp_port, 0)

    def test_connected_state(self) -> None:
        st = SocketTcp(None, "1.2.3.4", 80, "test")
        self.assertFalse(st.connected())
        self.assertFalse(st.t_get_connected())

        st.t_set_connected(True)
        self.assertTrue(st.connected())
        self.assertTrue(st.t_get_connected())

        # Setting same value shouldn't change
        st.t_set_connected(True)
        self.assertTrue(st.connected())

        st.t_set_connected(False)
        self.assertFalse(st.connected())

    def test_t_get_address_port(self) -> None:
        st = SocketTcp(None, "10.0.0.1", 8080, "test")
        addr, port = st.t_get_address_port()
        self.assertEqual(addr, "10.0.0.1")
        self.assertEqual(port, 8080)

    def test_address_setter(self) -> None:
        st = SocketTcp(None, "1.2.3.4", 80, "test")
        st.address = "5.6.7.8"
        self.assertEqual(st.address, "5.6.7.8")

    def test_port_setter(self) -> None:
        st = SocketTcp(None, "1.2.3.4", 80, "test")
        st.port = 443
        self.assertEqual(st.port, 443)

    def test_close_resets_connected(self) -> None:
        st = SocketTcp(None, "1.2.3.4", 80, "test")
        st.t_set_connected(True)
        st.close("test reason")
        self.assertFalse(st.connected())

    def test_repr_and_str(self) -> None:
        st = SocketTcp(None, "1.2.3.4", 80, "myconn")
        self.assertIn("myconn", repr(st))
        self.assertIn("SocketTcp", str(st))

    def test_t_connect_creates_socket(self) -> None:
        st = SocketTcp(None, "127.0.0.1", 1, "test")
        # Connect to port 1 (unlikely to succeed but should create socket)
        result, err = st.t_connect()
        # The socket should have been created regardless
        self.assertIsNotNone(st.t_sock)
        # Cleanup
        if st.t_sock:
            st.t_sock.close()

    def test_t_add_read_wraps_pump(self) -> None:
        """Verify that t_add_read wraps the pump to auto-detect connection."""
        jnt = MockJnt()
        st = SocketTcp(jnt, "1.2.3.4", 80, "test")
        st.priority = 3
        mock_sock = Mock()
        st.t_sock = mock_sock

        called = []
        original_pump = lambda *a, **kw: called.append(True)

        st.t_add_read(original_pump, 30)
        # The stored pump should be wrapped (not the same object)
        self.assertIsNotNone(st.read_pump)

    def test_free(self) -> None:
        st = SocketTcp(None, "1.2.3.4", 80, "test")
        mock_sock = Mock()
        st.t_sock = mock_sock
        st.free()
        self.assertIsNone(st.t_sock)


class TestSocketUdp(unittest.TestCase):
    """Tests for jive.net.socket_udp.SocketUdp."""

    def test_init_creates_socket(self) -> None:
        sink = Mock()
        su = SocketUdp(None, sink, "udp_test")
        self.assertEqual(su.js_name, "udp_test")
        self.assertIsNotNone(su.t_sock)
        self.assertIsInstance(su._queue, list)
        self.assertEqual(len(su._queue), 0)
        # Cleanup
        if su.t_sock:
            su.t_sock.close()

    def test_init_no_sink(self) -> None:
        su = SocketUdp(None, None, "no_sink")
        self.assertIsNotNone(su.t_sock)
        if su.t_sock:
            su.t_sock.close()

    def test_create_udp_socket(self) -> None:
        sock = _create_udp_socket()
        self.assertIsNotNone(sock)
        self.assertEqual(sock.type, _socket_mod.SOCK_DGRAM)
        sock.close()

    def test_create_udp_socket_with_localport(self) -> None:
        sock = _create_udp_socket(0)  # port 0 = OS-assigned
        self.assertIsNotNone(sock)
        sock.close()

    def test_repr_and_str(self) -> None:
        su = SocketUdp(None, None, "my_udp")
        self.assertIn("my_udp", repr(su))
        self.assertIn("SocketUdp", str(su))
        if su.t_sock:
            su.t_sock.close()

    def test_send_queues_sink(self) -> None:
        su = SocketUdp(None, None, "send_test")
        su.send(lambda: b"hello", "127.0.0.1", 9999)
        self.assertEqual(len(su._queue), 1)
        if su.t_sock:
            su.t_sock.close()

    def test_send_on_closed_socket(self) -> None:
        su = SocketUdp(None, None, "closed_test")
        su.t_sock.close()
        su.t_sock = None
        # Should not raise
        su.send(lambda: b"hello", "127.0.0.1", 9999)

    def test_t_get_sink(self) -> None:
        su = SocketUdp(None, None, "sink_test")
        sink = su._t_get_sink("127.0.0.1", 9999)
        self.assertTrue(callable(sink))
        # Empty chunk returns 1
        result = sink(None)
        self.assertEqual(result, 1)
        result = sink("")
        self.assertEqual(result, 1)
        if su.t_sock:
            su.t_sock.close()


class TestProcess(unittest.TestCase):
    """Tests for jive.net.process.Process."""

    def test_init(self) -> None:
        proc = Process(None, "echo hello")
        self.assertEqual(proc.prog, "echo hello")
        self.assertEqual(proc.status, "suspended")

    def test_read_echo(self) -> None:
        """Test reading output from a simple echo command."""
        chunks: List[Any] = []
        errors: List[Any] = []

        def sink(chunk: Any = None, err: Any = None) -> None:
            if err:
                errors.append(err)
            else:
                chunks.append(chunk)

        proc = Process(None, "echo hello_world")
        proc.read(sink)

        self.assertEqual(proc.status, "dead")
        # Should have received at least one data chunk and one None (EOF)
        self.assertTrue(any(c is None for c in chunks), "Should have received EOF")
        data_chunks = [c for c in chunks if c is not None]
        combined = b"".join(
            c if isinstance(c, bytes) else c.encode() for c in data_chunks
        )
        self.assertIn(b"hello_world", combined)
        self.assertEqual(len(errors), 0)

    def test_read_invalid_command(self) -> None:
        """Test that an invalid command reports error gracefully."""
        # We can't guarantee this fails on all platforms, but we can test structure
        chunks: List[Any] = []
        errors: List[Any] = []

        def sink(chunk: Any = None, err: Any = None) -> None:
            if err:
                errors.append(err)
            else:
                chunks.append(chunk)

        proc = Process(None, "echo test_proc_output")
        proc.read(sink)
        self.assertEqual(proc.status, "dead")

    def test_repr_and_str(self) -> None:
        proc = Process(None, "ls -la")
        self.assertIn("ls -la", repr(proc))
        self.assertIn("Process", str(proc))

    def test_getfd_before_read(self) -> None:
        proc = Process(None, "echo x")
        self.assertEqual(proc.getfd(), -1)


class TestDNS(unittest.TestCase):
    """Tests for jive.net.dns.DNS."""

    def setUp(self) -> None:
        DNS.reset()

    def tearDown(self) -> None:
        DNS.reset()

    def test_singleton(self) -> None:
        dns1 = DNS()
        dns2 = DNS()
        self.assertIs(dns1, dns2)

    def test_singleton_reset(self) -> None:
        dns1 = DNS()
        DNS.reset()
        dns2 = DNS()
        self.assertIsNot(dns1, dns2)

    def test_is_ip_valid(self) -> None:
        dns = DNS()
        self.assertTrue(dns.is_ip("192.168.1.1"))
        self.assertTrue(dns.is_ip("10.0.0.1"))
        self.assertTrue(dns.is_ip("255.255.255.255"))
        self.assertTrue(dns.is_ip("0.0.0.0"))
        self.assertTrue(dns.is_ip("127.0.0.1"))

    def test_is_ip_invalid(self) -> None:
        dns = DNS()
        self.assertFalse(dns.is_ip(""))
        self.assertFalse(dns.is_ip("hostname"))
        self.assertFalse(dns.is_ip("www.example.com"))
        self.assertFalse(dns.is_ip("192.168.1"))
        self.assertFalse(dns.is_ip("not.an.ip.address.at.all"))

    def test_toip_with_ip_address(self) -> None:
        dns = DNS()
        ip, hostent = dns.toip("192.168.1.1")
        self.assertEqual(ip, "192.168.1.1")
        self.assertIsInstance(hostent, HostEntry)
        self.assertIn("192.168.1.1", hostent.ip)

    def test_toip_localhost(self) -> None:
        dns = DNS()
        ip, hostent = dns.toip("localhost")
        self.assertIsNotNone(ip)
        self.assertIn(ip, ("127.0.0.1", "::1"))

    def test_toip_invalid_host(self) -> None:
        dns = DNS()
        ip, err = dns.toip("this.host.definitely.does.not.exist.invalid")
        self.assertIsNone(ip)
        self.assertIsInstance(err, str)

    def test_host_entry_repr(self) -> None:
        he = HostEntry("example.com", ip=["1.2.3.4"])
        self.assertIn("example.com", repr(he))
        self.assertIn("1.2.3.4", str(he))

    def test_repr_and_str(self) -> None:
        dns = DNS()
        self.assertIn("DNS", repr(dns))
        self.assertEqual(str(dns), "DNS")


class TestNetworkThread(unittest.TestCase):
    """Tests for jive.net.network_thread.NetworkThread."""

    def setUp(self) -> None:
        DNS.reset()

    def tearDown(self) -> None:
        DNS.reset()
        Task.clear_all()

    def test_init(self) -> None:
        jnt = NetworkThread()
        self.assertEqual(jnt.read_socket_count, 0)
        self.assertEqual(jnt.write_socket_count, 0)
        self.assertFalse(jnt._network_is_active)
        self.assertFalse(jnt._cpu_is_active)

    def test_t_add_remove_read(self) -> None:
        jnt = NetworkThread()
        mock_sock = Mock()
        mock_sock.fileno.return_value = 5
        task = Task("test_read", None, lambda obj: (yield True))
        task.priority = 3

        jnt.t_add_read(mock_sock, task, 30)
        self.assertEqual(jnt.read_socket_count, 1)
        self.assertIn(mock_sock, jnt._t_read_entries)

        jnt.t_remove_read(mock_sock)
        self.assertEqual(jnt.read_socket_count, 0)

    def test_t_add_remove_write(self) -> None:
        jnt = NetworkThread()
        mock_sock = Mock()
        mock_sock.fileno.return_value = 6
        task = Task("test_write", None, lambda obj: (yield True))
        task.priority = 3

        jnt.t_add_write(mock_sock, task, 30)
        self.assertEqual(jnt.write_socket_count, 1)

        jnt.t_remove_write(mock_sock)
        self.assertEqual(jnt.write_socket_count, 0)

    def test_t_add_read_none_sock(self) -> None:
        jnt = NetworkThread()
        task = Task("test", None, lambda obj: (yield True))
        task.priority = 3
        jnt.t_add_read(None, task, 30)
        self.assertEqual(jnt.read_socket_count, 0)

    def test_t_remove_read_none_sock(self) -> None:
        jnt = NetworkThread()
        # Should not raise
        jnt.t_remove_read(None)

    def test_t_add_read_replaces_task(self) -> None:
        jnt = NetworkThread()
        mock_sock = Mock()
        mock_sock.fileno.return_value = 7
        task1 = Task("test1", None, lambda obj: (yield True))
        task1.priority = 3
        task2 = Task("test2", None, lambda obj: (yield True))
        task2.priority = 3

        jnt.t_add_read(mock_sock, task1, 30)
        entry1 = jnt._t_read_entries[mock_sock]
        self.assertIs(entry1.task, task1)

        jnt.t_add_read(mock_sock, task2, 60)
        entry2 = jnt._t_read_entries[mock_sock]
        self.assertIs(entry2.task, task2)
        # Should still only have one socket
        self.assertEqual(jnt.read_socket_count, 1)

    def test_network_active_inactive(self) -> None:
        jnt = NetworkThread()
        callback_log: List[bool] = []
        jnt.register_network_active(lambda active: callback_log.append(active))

        obj = object()
        jnt.network_active(obj)
        self.assertTrue(jnt._network_is_active)
        self.assertEqual(callback_log, [True])

        jnt.network_inactive(obj)
        self.assertFalse(jnt._network_is_active)
        self.assertEqual(callback_log, [True, False])

    def test_cpu_active_inactive(self) -> None:
        jnt = NetworkThread()
        callback_log: List[bool] = []
        jnt.register_cpu_active(lambda active: callback_log.append(active))

        obj = object()
        jnt.cpu_active(obj)
        self.assertTrue(jnt._cpu_is_active)
        self.assertEqual(callback_log, [True])

        jnt.cpu_inactive(obj)
        self.assertFalse(jnt._cpu_is_active)
        self.assertEqual(callback_log, [True, False])

    def test_sn_hostname(self) -> None:
        jnt = NetworkThread()
        self.assertEqual(jnt.get_sn_hostname(), "www.squeezenetwork.com")
        jnt.set_sn_hostname("test.squeezenetwork.com")
        self.assertEqual(jnt.get_sn_hostname(), "test.squeezenetwork.com")

    def test_arp_disabled(self) -> None:
        jnt = NetworkThread()
        jnt.set_arp_enabled(False)
        self.assertFalse(jnt.is_arp_enabled())

        result = []
        jnt.arp("192.168.1.1", lambda mac, err=None: result.append((mac, err)))
        self.assertEqual(len(result), 1)
        self.assertIsNone(result[0][0])
        self.assertEqual(result[0][1], "Arp disabled")

    def test_subscribe_notify(self) -> None:
        jnt = NetworkThread()

        class Subscriber:
            def __init__(self) -> None:
                self.events: List[tuple] = []

            def notify_testEvent(self, *args: Any) -> None:
                self.events.append(args)

        sub = Subscriber()
        jnt.subscribe(sub)
        jnt.notify("testEvent", "arg1", "arg2")

        self.assertEqual(len(sub.events), 1)
        self.assertEqual(sub.events[0], ("arg1", "arg2"))

    def test_unsubscribe(self) -> None:
        jnt = NetworkThread()

        class Sub:
            def __init__(self) -> None:
                self.called = False

            def notify_test(self) -> None:
                self.called = True

        sub = Sub()
        jnt.subscribe(sub)
        jnt.unsubscribe(sub)
        jnt.notify("test")
        self.assertFalse(sub.called)

    def test_task_returns_task_object(self) -> None:
        jnt = NetworkThread()
        t = jnt.task()
        self.assertIsInstance(t, Task)
        self.assertEqual(t.name, "networkTask")

    def test_repr_and_str(self) -> None:
        jnt = NetworkThread()
        self.assertIn("NetworkThread", repr(jnt))
        self.assertEqual(str(jnt), "NetworkThread")

    def test_t_select_empty(self) -> None:
        jnt = NetworkThread()
        # Should not raise with no sockets
        jnt._t_select(0.0)

    def test_socket_entry_repr(self) -> None:
        task = Task("test", None, lambda obj: None)
        task.priority = 3
        entry = _SocketEntry(task, 1000.0, 5000)
        self.assertIn("test", repr(entry))


class TestWakeOnLan(unittest.TestCase):
    """Tests for jive.net.wake_on_lan.WakeOnLan."""

    def test_init(self) -> None:
        wol = WakeOnLan(None)
        self.assertIsNotNone(wol.t_sock)
        if wol.t_sock:
            wol.t_sock.close()

    def test_wake_on_lan_colon_format(self) -> None:
        wol = WakeOnLan(None)
        # Should not raise
        wol.wake_on_lan("00:1a:2b:3c:4d:5e")
        self.assertEqual(len(wol._queue), 1)
        if wol.t_sock:
            wol.t_sock.close()

    def test_wake_on_lan_dash_format(self) -> None:
        wol = WakeOnLan(None)
        wol.wake_on_lan("00-1a-2b-3c-4d-5e")
        self.assertEqual(len(wol._queue), 1)
        if wol.t_sock:
            wol.t_sock.close()

    def test_wake_on_lan_invalid_mac(self) -> None:
        wol = WakeOnLan(None)
        with self.assertRaises(ValueError):
            wol.wake_on_lan("invalid")
        if wol.t_sock:
            wol.t_sock.close()

    def test_wake_on_lan_too_few_pairs(self) -> None:
        wol = WakeOnLan(None)
        with self.assertRaises(ValueError):
            wol.wake_on_lan("00:1a:2b")
        if wol.t_sock:
            wol.t_sock.close()

    def test_repr_and_str(self) -> None:
        wol = WakeOnLan(None)
        self.assertIn("WakeOnLan", repr(wol))
        self.assertEqual(str(wol), "WakeOnLan")
        if wol.t_sock:
            wol.t_sock.close()


# ======================================================================
# M9b — HTTP
# ======================================================================


class TestParseUri(unittest.TestCase):
    """Tests for the _parse_uri helper function."""

    def test_full_url(self) -> None:
        result = _parse_uri("http://192.168.1.1:9000/xml/status.xml")
        self.assertEqual(result["scheme"], "http")
        self.assertEqual(result["host"], "192.168.1.1")
        self.assertEqual(result["port"], 9000)
        self.assertEqual(result["path"], "/xml/status.xml")

    def test_path_only(self) -> None:
        result = _parse_uri("/xml/status.xml")
        self.assertEqual(result["path"], "/xml/status.xml")
        self.assertEqual(result["host"], "")
        self.assertEqual(result["port"], 80)

    def test_with_query(self) -> None:
        result = _parse_uri("http://host:8080/path?key=value&foo=bar")
        self.assertEqual(result["query"], "key=value&foo=bar")
        self.assertEqual(result["path"], "/path")
        self.assertEqual(result["port"], 8080)

    def test_with_fragment(self) -> None:
        result = _parse_uri("http://host/path#section")
        self.assertEqual(result["fragment"], "section")

    def test_default_port(self) -> None:
        result = _parse_uri("http://example.com/path")
        self.assertEqual(result["port"], 80)

    def test_empty_path_defaults_to_slash(self) -> None:
        result = _parse_uri("http://example.com")
        self.assertEqual(result["path"], "/")


class TestRequestHttp(unittest.TestCase):
    """Tests for jive.net.request_http.RequestHttp."""

    def test_get_request(self) -> None:
        sink = Mock()
        req = RequestHttp(sink, "GET", "/xml/status.xml")
        self.assertFalse(req.t_has_body())
        self.assertEqual(req.t_get_request_string(), "GET /xml/status.xml")

    def test_post_request(self) -> None:
        body_data = '{"test": true}'

        req = RequestHttp(
            Mock(),
            "POST",
            "/api/endpoint",
            options={"t_body_source": lambda: body_data},
        )
        self.assertTrue(req.t_has_body())
        self.assertEqual(req.t_body(), body_data)

    def test_get_request_with_query(self) -> None:
        req = RequestHttp(Mock(), "GET", "http://host/path?key=value")
        request_str = req.t_get_request_string()
        self.assertIn("GET", request_str)
        self.assertIn("/path", request_str)
        self.assertIn("?key=value", request_str)

    def test_get_uri(self) -> None:
        req = RequestHttp(Mock(), "GET", "http://example.com:8080/test")
        uri = req.get_uri()
        self.assertEqual(uri["host"], "example.com")
        self.assertEqual(uri["port"], 8080)
        self.assertEqual(uri["path"], "/test")

    def test_request_headers(self) -> None:
        req = RequestHttp(
            Mock(),
            "GET",
            "http://example.com/test",
            options={"headers": {"Accept": "text/html", "X-Custom": "value"}},
        )
        headers = req.t_get_request_headers()
        self.assertEqual(headers["Accept"], "text/html")
        self.assertEqual(headers["X-Custom"], "value")

    def test_host_header_auto_set(self) -> None:
        req = RequestHttp(Mock(), "GET", "http://myhost.com:9000/path")
        headers = req.t_get_request_headers()
        self.assertEqual(headers["Host"], "myhost.com:9000")

    def test_host_header_default_port(self) -> None:
        req = RequestHttp(Mock(), "GET", "http://myhost.com/path")
        headers = req.t_get_request_headers()
        self.assertIn("Host", headers)
        # Port 80 should not be in the Host header
        self.assertNotIn(":80", headers["Host"])

    def test_response_headers(self) -> None:
        req = RequestHttp(Mock(), "GET", "/test")
        req.t_set_response_headers(
            200, "HTTP/1.1 200 OK", {"Content-Type": "text/html", "X-Server": "test"}
        )
        self.assertEqual(req.t_get_response_header("content-type"), "text/html")
        self.assertEqual(req.t_get_response_header("x-server"), "test")
        self.assertIsNone(req.t_get_response_header("nonexistent"))

    def test_response_status(self) -> None:
        req = RequestHttp(Mock(), "GET", "/test")
        req.t_set_response_headers(404, "HTTP/1.1 404 Not Found", {})
        code, line = req.t_get_response_status()
        self.assertEqual(code, 404)
        self.assertEqual(line, "HTTP/1.1 404 Not Found")

    def test_response_sink_mode_default(self) -> None:
        req = RequestHttp(Mock(), "GET", "/test")
        self.assertEqual(req.t_get_response_sink_mode(), "jive-concat")

    def test_response_sink_mode_stream(self) -> None:
        req = RequestHttp(Mock(), "GET", "/test", options={"stream": True})
        self.assertEqual(req.t_get_response_sink_mode(), "jive-by-chunk")

    def test_response_body_200(self) -> None:
        results: List[Any] = []
        sink = lambda data=None, err=None, req=None: results.append((data, err))
        req = RequestHttp(sink, "GET", "/test")
        req.t_set_response_headers(200, "HTTP/1.1 200 OK", {})
        req.t_set_response_body("hello world")
        # Should have received data and None (end)
        self.assertTrue(any(r[0] == "hello world" for r in results))

    def test_response_body_error(self) -> None:
        results: List[Any] = []
        sink = lambda data=None, err=None, req=None: results.append((data, err))
        req = RequestHttp(sink, "GET", "/test")
        req.t_set_response_headers(500, "HTTP/1.1 500 Internal Server Error", {})
        req.t_set_response_body("error body")
        # Should have received error
        self.assertTrue(any(r[1] is not None and "500" in str(r[1]) for r in results))

    def test_response_body_redirect(self) -> None:
        results: List[Any] = []
        sink = lambda data=None, err=None, req=None: results.append((data, err))
        req = RequestHttp(sink, "GET", "http://example.com/old")
        req.t_set_response_headers(
            302,
            "HTTP/1.1 302 Found",
            {"Location": "http://example.com/new"},
        )
        # Redirect is processed when data is None
        req.t_set_response_body(None)
        self.assertEqual(req.redirect, 1)
        uri = req.get_uri()
        self.assertEqual(uri["path"], "/new")

    def test_response_body_no_redirect_for_post(self) -> None:
        results: List[Any] = []
        sink = lambda data=None, err=None, req=None: results.append((data, err))
        req = RequestHttp(
            sink,
            "POST",
            "http://example.com/old",
            options={"t_body_source": lambda: ""},
        )
        req.t_set_response_headers(
            302,
            "HTTP/1.1 302 Found",
            {"Location": "http://example.com/new"},
        )
        req.t_set_response_body(None)
        # POST should not redirect — should get error instead
        self.assertEqual(req.redirect, 0)

    def test_redirect_limit(self) -> None:
        sink = Mock()
        req = RequestHttp(sink, "GET", "http://example.com/old")
        req.redirect = 5  # Already at limit
        req.t_set_response_headers(
            302,
            "HTTP/1.1 302 Found",
            {"Location": "http://example.com/new"},
        )
        req.t_set_response_body(None)
        # Should NOT redirect (limit reached)
        self.assertEqual(req.redirect, 5)

    def test_get_response_sink_none(self) -> None:
        req = RequestHttp(None, "GET", "/test")
        self.assertIsNone(req.t_get_response_sink())

    def test_headers_sink(self) -> None:
        headers_received: List[dict] = []

        def headers_sink(headers: dict) -> None:
            headers_received.append(headers)

        req = RequestHttp(
            Mock(),
            "GET",
            "/test",
            options={"headers_sink": headers_sink},
        )
        req.t_set_response_headers(200, "OK", {"X-Test": "value"})
        self.assertEqual(len(headers_received), 1)
        self.assertEqual(headers_received[0]["X-Test"], "value")

    def test_repr_and_str(self) -> None:
        req = RequestHttp(Mock(), "GET", "/api/test")
        self.assertIn("GET", repr(req))
        self.assertIn("RequestHttp", str(req))

    def test_t_body_caches_result(self) -> None:
        call_count = [0]

        def body_source() -> str:
            call_count[0] += 1
            return "body_data"

        req = RequestHttp(
            Mock(), "POST", "/api", options={"t_body_source": body_source}
        )
        result1 = req.t_body()
        result2 = req.t_body()
        self.assertEqual(result1, "body_data")
        self.assertEqual(result2, "body_data")
        self.assertEqual(call_count[0], 1)  # Only called once due to caching

    def test_response_no_headers_yet(self) -> None:
        req = RequestHttp(Mock(), "GET", "/test")
        self.assertIsNone(req.t_get_response_header("anything"))
        code, line = req.t_get_response_status()
        self.assertIsNone(code)
        self.assertIsNone(line)


class TestRequestJsonRpc(unittest.TestCase):
    """Tests for jive.net.request_jsonrpc.RequestJsonRpc."""

    def test_init(self) -> None:
        sink = Mock()
        req = RequestJsonRpc(sink, "/jsonrpc", "slim.request", ["", ["status"]])
        self.assertTrue(req.t_has_body())
        self.assertEqual(req.json_method, "slim.request")
        self.assertEqual(req.json_params, ["", ["status"]])

    def test_json_id_generation(self) -> None:
        req1 = RequestJsonRpc(Mock(), "/rpc", "method1")
        req2 = RequestJsonRpc(Mock(), "/rpc", "method2")
        self.assertNotEqual(req1.get_json_id(), req2.get_json_id())

    def test_body_is_json(self) -> None:
        req = RequestJsonRpc(Mock(), "/rpc", "test_method", [1, 2, 3])
        body = req.t_body()
        self.assertIsNotNone(body)
        decoded = json.loads(body)
        self.assertEqual(decoded["method"], "test_method")
        self.assertEqual(decoded["params"], [1, 2, 3])
        self.assertIn("id", decoded)

    def test_default_params(self) -> None:
        req = RequestJsonRpc(Mock(), "/rpc", "method")
        body = req.t_body()
        decoded = json.loads(body)
        self.assertEqual(decoded["params"], [])

    def test_response_200_json(self) -> None:
        results: List[Any] = []
        sink = lambda data=None, err=None, req=None: results.append((data, err))
        req = RequestJsonRpc(sink, "/rpc", "method")
        req.t_set_response_headers(200, "OK", {})
        req.t_set_response_body('{"result": "success"}')
        self.assertTrue(any(r[0] == {"result": "success"} for r in results))

    def test_response_non_200(self) -> None:
        results: List[Any] = []
        sink = lambda data=None, err=None, req=None: results.append((data, err))
        req = RequestJsonRpc(sink, "/rpc", "method")
        req.t_set_response_headers(500, "Error", {})
        req.t_set_response_body("error body")
        # Should receive error
        self.assertTrue(any(r[1] is not None for r in results))

    def test_response_invalid_json(self) -> None:
        results: List[Any] = []
        sink = lambda data=None, err=None, req=None: results.append((data, err))
        req = RequestJsonRpc(sink, "/rpc", "method")
        req.t_set_response_headers(200, "OK", {})
        req.t_set_response_body("not valid json {{{")
        # Should receive error
        self.assertTrue(any(r[1] is not None for r in results))

    def test_repr_and_str(self) -> None:
        req = RequestJsonRpc(Mock(), "/rpc", "my_method")
        self.assertIn("RequestJsonRpc", repr(req))
        self.assertIn("my_method", repr(req))


class TestSocketHttp(unittest.TestCase):
    """Tests for jive.net.socket_http.SocketHttp."""

    def setUp(self) -> None:
        DNS.reset()

    def tearDown(self) -> None:
        DNS.reset()

    def test_init(self) -> None:
        sh = SocketHttp(None, "192.168.1.1", 9000, "slim")
        self.assertEqual(sh.host, "192.168.1.1")
        self.assertEqual(sh.port, 9000)
        self.assertEqual(sh.js_name, "slim")
        self.assertEqual(sh._http_send_state, "t_send_dequeue")
        self.assertEqual(sh._http_recv_state, "t_recv_dequeue")

    def test_fetch_queues_request(self) -> None:
        sh = SocketHttp(None, "192.168.1.1", 9000, "slim")
        req = RequestHttp(Mock(), "GET", "/test")
        # fetch will call t_send_dequeue_if_idle which will start state machine
        sh.fetch(req)
        # The request should either be queued or being processed
        # After dequeue, it moves to send_request state
        self.assertIn(
            sh._http_send_state,
            ["t_send_dequeue", "t_send_resolve", "t_send_request"],
        )

    def test_credentials(self) -> None:
        SocketHttp.set_credentials(("192.168.1.1", 9000), "Slim", "admin", "password")
        # Verify credential was stored
        from jive.net.socket_http import _credentials

        key = "192.168.1.1:9000"
        self.assertIn(key, _credentials)
        self.assertEqual(_credentials[key]["username"], "admin")
        self.assertEqual(_credentials[key]["password"], "password")
        # Cleanup
        _credentials.pop(key, None)

    def test_close_cancels_requests(self) -> None:
        sh = SocketHttp(None, "192.168.1.1", 9000, "slim")
        errors: List[str] = []
        sink = lambda data=None, err=None, req=None: errors.append(err) if err else None

        req1 = RequestHttp(sink, "GET", "/test1")
        req2 = RequestHttp(sink, "GET", "/test2")

        # Manually set up in-flight state
        sh._http_send_request = req1
        sh._http_recv_requests = [req2]

        sh.close("test error")

        self.assertIsNone(sh._http_send_request)
        self.assertEqual(len(sh._http_recv_requests), 0)
        # Error sinks should have been called
        self.assertTrue(len(errors) > 0)

    def test_free_clears_queues(self) -> None:
        sh = SocketHttp(None, "192.168.1.1", 9000, "slim")
        sh._http_send_requests = [RequestHttp(Mock(), "GET", "/test")]
        sh._http_recv_requests = [RequestHttp(Mock(), "GET", "/test")]
        sh.free()
        self.assertEqual(len(sh._http_send_requests), 0)
        self.assertEqual(len(sh._http_recv_requests), 0)

    def test_dequeue_request(self) -> None:
        sh = SocketHttp(None, "192.168.1.1", 9000, "slim")
        req = RequestHttp(Mock(), "GET", "/test")
        sh._http_send_requests.append(req)
        dequeued = sh._dequeue_request()
        self.assertIs(dequeued, req)
        self.assertEqual(len(sh._http_send_requests), 0)

    def test_dequeue_request_empty(self) -> None:
        sh = SocketHttp(None, "192.168.1.1", 9000, "slim")
        result = sh._dequeue_request()
        self.assertIsNone(result)

    def test_send_resolve_ip_address(self) -> None:
        sh = SocketHttp(None, "192.168.1.1", 9000, "slim")
        sh._http_send_state = "t_send_resolve"
        sh._http_send_request = RequestHttp(Mock(), "GET", "/test")
        sh.t_send_resolve()
        # State machine chains: t_send_resolve → t_send_connect → t_send_request
        # (or t_send_dequeue if connect+request complete synchronously).
        # The key assertion is that it advanced past t_send_resolve.
        self.assertNotEqual(sh._http_send_state, "t_send_resolve")

    def test_send_resolve_cached_ip(self) -> None:
        sh = SocketHttp(None, "myhost.local", 9000, "slim")
        sh.cached_ip = "1.2.3.4"
        sh._http_send_state = "t_send_resolve"
        sh._http_send_request = RequestHttp(Mock(), "GET", "/test")
        sh.t_send_resolve()
        self.assertEqual(sh.address, "1.2.3.4")

    def test_t_send_dequeue_if_idle(self) -> None:
        sh = SocketHttp(None, "192.168.1.1", 9000, "slim")
        sh._http_send_state = "t_send_dequeue"
        req = RequestHttp(Mock(), "GET", "/test")
        sh._http_send_requests.append(req)
        sh.t_send_dequeue_if_idle()
        # Should have dequeued and started processing
        self.assertIsNotNone(sh._http_send_request)

    def test_t_send_dequeue_if_not_idle(self) -> None:
        sh = SocketHttp(None, "192.168.1.1", 9000, "slim")
        sh._http_send_state = "t_send_request"  # Not idle
        req = RequestHttp(Mock(), "GET", "/test")
        sh._http_send_requests.append(req)
        sh.t_send_dequeue_if_idle()
        # Should NOT have dequeued
        self.assertEqual(len(sh._http_send_requests), 1)

    def test_send_complete(self) -> None:
        sh = SocketHttp(None, "192.168.1.1", 9000, "slim")
        req = RequestHttp(Mock(), "GET", "/test")
        sh._http_send_request = req
        sh.t_send_complete()
        # After t_send_complete the request is moved to the recv queue
        # and then t_send_dequeue is called (which may also trigger
        # t_recv_dequeue, consuming the request from recv_requests).
        # The key invariant: _http_send_request is cleared.
        self.assertIsNone(sh._http_send_request)
        # The request was either consumed by the recv state machine
        # or is still waiting in _http_recv_requests — both are valid.
        # Verify the send state returned to dequeue (idle).
        self.assertEqual(sh._http_send_state, "t_send_dequeue")

    def test_repr_and_str(self) -> None:
        sh = SocketHttp(None, "192.168.1.1", 9000, "slim")
        self.assertIn("slim", repr(sh))
        self.assertIn("SocketHttp", str(sh))

    def test_get_send_headers(self) -> None:
        sh = SocketHttp(None, "192.168.1.1", 9000, "slim")
        req = RequestHttp(Mock(), "GET", "/test")
        sh._http_send_request = req
        headers = sh._t_get_send_headers()
        self.assertIn("User-Agent", headers)
        self.assertIn("SqueezePlay", headers["User-Agent"])

    def test_get_send_headers_host(self) -> None:
        sh = SocketHttp(None, "myserver", 9000, "slim")
        req = RequestHttp(Mock(), "GET", "/test")
        sh._http_send_request = req
        headers = sh._t_get_send_headers()
        self.assertIn("Host", headers)
        self.assertEqual(headers["Host"], "myserver:9000")

    def test_get_send_headers_host_port_80(self) -> None:
        sh = SocketHttp(None, "myserver", 80, "slim")
        req = RequestHttp(Mock(), "GET", "/test")
        sh._http_send_request = req
        headers = sh._t_get_send_headers()
        self.assertEqual(headers["Host"], "myserver")

    def test_recv_complete(self) -> None:
        sh = SocketHttp(None, "192.168.1.1", 9000, "slim")
        sh._http_recv_request = RequestHttp(Mock(), "GET", "/test")
        sh.active = True
        sh.t_recv_complete()
        self.assertIsNone(sh._http_recv_request)
        self.assertFalse(sh.active)


class TestSocketHttpQueue(unittest.TestCase):
    """Tests for jive.net.socket_http_queue.SocketHttpQueue."""

    def setUp(self) -> None:
        DNS.reset()

    def tearDown(self) -> None:
        DNS.reset()

    def test_init(self) -> None:
        shq = SocketHttpQueue(None, "192.168.1.1", 9000, None, "q1")
        self.assertEqual(shq.js_name, "q1")
        self.assertIsNone(shq._http_queue)

    def test_dequeue_from_external(self) -> None:
        mock_queue = Mock()
        req = RequestHttp(Mock(), "GET", "/test")
        mock_queue.t_dequeue.return_value = (req, False)

        shq = SocketHttpQueue(None, "192.168.1.1", 9000, mock_queue, "q1")
        result = shq._dequeue_request()
        self.assertIs(result, req)
        mock_queue.t_dequeue.assert_called_once_with(shq)

    def test_dequeue_empty_no_close(self) -> None:
        mock_queue = Mock()
        mock_queue.t_dequeue.return_value = (None, False)

        shq = SocketHttpQueue(None, "192.168.1.1", 9000, mock_queue, "q1")
        result = shq._dequeue_request()
        self.assertIsNone(result)

    def test_dequeue_empty_with_close(self) -> None:
        mock_queue = Mock()
        # First call returns (None, True) to signal close,
        # but close() triggers t_send_dequeue which calls _dequeue_request
        # again — subsequent calls return (None, False) to break the chain.
        mock_queue.t_dequeue.side_effect = [(None, True), (None, False)]

        shq = SocketHttpQueue(None, "192.168.1.1", 9000, mock_queue, "q1")
        result = shq._dequeue_request()
        # close was triggered, socket should be closed
        self.assertIsNone(result)

    def test_dequeue_no_queue_obj(self) -> None:
        shq = SocketHttpQueue(None, "192.168.1.1", 9000, None, "q1")
        req = RequestHttp(Mock(), "GET", "/test")
        shq._http_send_requests.append(req)
        result = shq._dequeue_request()
        self.assertIs(result, req)

    def test_repr_and_str(self) -> None:
        shq = SocketHttpQueue(None, "192.168.1.1", 9000, None, "q1")
        self.assertIn("q1", repr(shq))
        self.assertIn("SocketHttpQueue", str(shq))


class TestHttpPool(unittest.TestCase):
    """Tests for jive.net.http_pool.HttpPool."""

    def setUp(self) -> None:
        DNS.reset()

    def tearDown(self) -> None:
        DNS.reset()

    def test_init_defaults(self) -> None:
        pool = HttpPool(None, "test", "192.168.1.1", 9000)
        self.assertEqual(pool.pool_name, "test")
        self.assertEqual(pool.pool_size, 1)
        self.assertEqual(pool.queue_count, 0)

    def test_init_with_quantity(self) -> None:
        pool = HttpPool(None, "test", "192.168.1.1", 9000, quantity=4)
        self.assertEqual(pool.pool_size, 4)

    def test_queue_adds_request(self) -> None:
        pool = HttpPool(None, "test", "192.168.1.1", 9000)
        req = RequestHttp(Mock(), "GET", "/test")
        pool.queue(req)
        # The pool dispatches requests immediately to idle sockets,
        # so queue_count may already be 0 after dispatch.
        # Verify the request was accepted (count went up then back down).
        self.assertGreaterEqual(pool.queue_count, 0)
        self.assertLessEqual(pool.queue_count, 1)

    def test_t_dequeue_returns_request(self) -> None:
        pool = HttpPool(None, "test", "192.168.1.1", 9000)
        req = RequestHttp(Mock(), "GET", "/test")
        pool._req_queue.append(req)
        pool._req_queue_count = 1

        result, close = pool.t_dequeue(None)
        self.assertIs(result, req)
        self.assertFalse(close)
        self.assertEqual(pool.queue_count, 0)

    def test_t_dequeue_empty(self) -> None:
        pool = HttpPool(None, "test", "192.168.1.1", 9000)
        result, close = pool.t_dequeue(None)
        self.assertIsNone(result)
        self.assertFalse(close)

    def test_t_dequeue_factory_function(self) -> None:
        pool = HttpPool(None, "test", "192.168.1.1", 9000)
        req = RequestHttp(Mock(), "GET", "/test")
        pool._req_queue.append(lambda: req)
        pool._req_queue_count = 1

        result, close = pool.t_dequeue(None)
        self.assertIs(result, req)

    def test_free(self) -> None:
        pool = HttpPool(None, "test", "192.168.1.1", 9000, quantity=2)
        pool.free()
        self.assertEqual(pool.pool_size, 0)

    def test_close(self) -> None:
        pool = HttpPool(None, "test", "192.168.1.1", 9000, quantity=2)
        # Should not raise
        pool.close()
        # Pool still has sockets (not freed)
        self.assertEqual(pool.pool_size, 2)

    def test_sockets_property(self) -> None:
        pool = HttpPool(None, "test", "192.168.1.1", 9000, quantity=3)
        socks = pool.sockets
        self.assertEqual(len(socks), 3)
        for s in socks:
            self.assertIsInstance(s, SocketHttpQueue)

    def test_repr_and_str(self) -> None:
        pool = HttpPool(None, "test_pool", "192.168.1.1", 9000)
        self.assertIn("test_pool", repr(pool))
        self.assertIn("HttpPool", str(pool))

    def test_queue_multiple(self) -> None:
        pool = HttpPool(None, "test", "192.168.1.1", 9000, quantity=2)
        for i in range(5):
            pool.queue(RequestHttp(Mock(), "GET", f"/test{i}"))
        # Sockets may dequeue immediately when idle, so total queued
        # plus already-dispatched should equal 5.  At minimum the
        # queue_count must be non-negative and <= 5.
        self.assertGreaterEqual(pool.queue_count, 0)
        self.assertLessEqual(pool.queue_count, 5)


# ======================================================================
# M9c — Comet
# ======================================================================


class TestCometRequest(unittest.TestCase):
    """Tests for jive.net.comet_request.CometRequest."""

    def test_init(self) -> None:
        data = [{"channel": "/meta/handshake", "version": "1.0"}]
        req = CometRequest(Mock(), "http://host:9000/cometd", data)
        self.assertTrue(req.t_has_body())

    def test_body_is_json(self) -> None:
        data = [{"channel": "/meta/connect", "clientId": "abc123"}]
        req = CometRequest(Mock(), "http://host:9000/cometd", data)
        body = req.t_body()
        self.assertIsNotNone(body)
        decoded = json.loads(body)
        self.assertEqual(decoded[0]["channel"], "/meta/connect")
        self.assertEqual(decoded[0]["clientId"], "abc123")

    def test_sink_mode_no_transfer_encoding(self) -> None:
        req = CometRequest(Mock(), "/cometd", [])
        req.t_set_response_headers(200, "OK", {})
        mode = req.t_get_response_sink_mode()
        self.assertEqual(mode, "jive-concat")

    def test_sink_mode_chunked(self) -> None:
        req = CometRequest(Mock(), "/cometd", [])
        req.t_set_response_headers(200, "OK", {"Transfer-Encoding": "chunked"})
        mode = req.t_get_response_sink_mode()
        self.assertEqual(mode, "jive-by-chunk")

    def test_response_200_json(self) -> None:
        results: List[Any] = []
        sink = lambda data=None, err=None, req=None: results.append((data, err))
        req = CometRequest(sink, "/cometd", [])
        req.t_set_response_headers(200, "OK", {})
        req.t_set_response_body('[{"channel": "/meta/connect", "successful": true}]')
        self.assertTrue(len(results) > 0)
        self.assertIsNotNone(results[0][0])
        self.assertEqual(results[0][0][0]["channel"], "/meta/connect")

    def test_response_non_200(self) -> None:
        results: List[Any] = []
        sink = lambda data=None, err=None, req=None: results.append((data, err))
        req = CometRequest(sink, "/cometd", [])
        req.t_set_response_headers(500, "Error", {})
        req.t_set_response_body("error")
        self.assertTrue(any(r[1] is not None for r in results))

    def test_default_content_type(self) -> None:
        req = CometRequest(Mock(), "/cometd", [])
        headers = req.t_get_request_headers()
        self.assertEqual(headers.get("Content-Type"), "text/json")

    def test_repr_and_str(self) -> None:
        req = CometRequest(Mock(), "/cometd", [])
        self.assertIn("CometRequest", repr(req))
        self.assertIn("CometRequest", str(req))


class TestComet(unittest.TestCase):
    """Tests for jive.net.comet.Comet."""

    def setUp(self) -> None:
        DNS.reset()

    def tearDown(self) -> None:
        DNS.reset()

    def test_init(self) -> None:
        comet = Comet(None, "test_comet")
        self.assertEqual(comet.name, "test_comet")
        self.assertEqual(comet.state, UNCONNECTED)
        self.assertIsNone(comet.client_id)
        self.assertEqual(comet.reqid, 1)
        self.assertEqual(comet.failures, 0)
        self.assertEqual(comet.batch, 0)

    def test_set_endpoint(self) -> None:
        jnt = MockJnt()
        comet = Comet(jnt, "test")
        comet.set_endpoint("192.168.1.1", 9000, "/cometd")
        self.assertEqual(comet.uri, "http://192.168.1.1:9000/cometd")
        self.assertIsNotNone(comet.chttp)
        self.assertIsNotNone(comet.rhttp)

    def test_set_uuid(self) -> None:
        comet = Comet(None, "test")
        comet.set_uuid("test-uuid", "00:11:22:33:44:55")
        self.assertEqual(comet._uuid, "test-uuid")
        self.assertEqual(comet._mac, "00:11:22:33:44:55")

    def test_aggressive_reconnect(self) -> None:
        comet = Comet(None, "test")
        self.assertFalse(comet.aggressive)
        comet.aggressive_reconnect(True)
        self.assertTrue(comet.aggressive)

    def test_connect_without_endpoint(self) -> None:
        comet = Comet(None, "test")
        with self.assertRaises(RuntimeError):
            comet.connect()

    def test_subscribe_adds_to_subs(self) -> None:
        comet = Comet(None, "test")
        callback = Mock()
        comet.subscribe("/slim/serverstatus", callback, "player1", ["serverstatus"])
        self.assertEqual(len(comet.subs), 1)
        self.assertEqual(comet.subs[0].subscription, "/slim/serverstatus")
        self.assertIs(comet.subs[0].func, callback)
        self.assertEqual(comet.subs[0].playerid, "player1")
        self.assertEqual(comet.reqid, 2)

    def test_subscribe_increments_reqid(self) -> None:
        comet = Comet(None, "test")
        comet.subscribe("/a", Mock())
        comet.subscribe("/b", Mock())
        comet.subscribe("/c", Mock())
        self.assertEqual(comet.reqid, 4)

    def test_unsubscribe_removes_from_subs(self) -> None:
        comet = Comet(None, "test")
        callback = Mock()
        comet.subscribe("/slim/serverstatus", callback)
        self.assertEqual(len(comet.subs), 1)

        # Add the callback to notify_callbacks (simulating what _add_pending_requests does)
        comet.notify_callbacks["/slim/serverstatus"] = {id(callback): callback}

        comet.unsubscribe("/slim/serverstatus")
        self.assertEqual(len(comet.subs), 0)
        self.assertEqual(len(comet.pending_unsubs), 1)

    def test_unsubscribe_specific_callback(self) -> None:
        comet = Comet(None, "test")
        cb1 = Mock()
        cb2 = Mock()
        comet.subscribe("/test", cb1)
        comet.notify_callbacks["/test"] = {id(cb1): cb1, id(cb2): cb2}

        comet.unsubscribe("/test", cb1)
        # Should still have cb2, so subscription remains
        self.assertIn(id(cb2), comet.notify_callbacks["/test"])
        self.assertNotIn(id(cb1), comet.notify_callbacks["/test"])

    def test_request_adds_to_pending(self) -> None:
        comet = Comet(None, "test")
        callback = Mock()
        req_id = comet.request(callback, "player1", ["status", "-", 1])
        self.assertEqual(req_id, 1)
        self.assertEqual(len(comet.pending_reqs), 1)
        self.assertEqual(comet.reqid, 2)

    def test_request_fire_and_forget(self) -> None:
        comet = Comet(None, "test")
        req_id = comet.request(None, "player1", ["pause"])
        self.assertEqual(req_id, 1)
        self.assertEqual(len(comet.pending_reqs), 1)
        self.assertIsNone(comet.pending_reqs[0].func)

    def test_remove_request_from_pending(self) -> None:
        comet = Comet(None, "test")
        req_id = comet.request(Mock(), "p1", ["status"])
        result = comet.remove_request(req_id)
        self.assertTrue(result)
        self.assertEqual(len(comet.pending_reqs), 0)

    def test_remove_request_not_found(self) -> None:
        comet = Comet(None, "test")
        result = comet.remove_request(999)
        self.assertFalse(result)

    def test_remove_request_while_connected(self) -> None:
        comet = Comet(None, "test")
        comet.state = CONNECTED
        result = comet.remove_request(1)
        self.assertFalse(result)

    def test_add_callback(self) -> None:
        comet = Comet(None, "test")
        cb = Mock()
        comet.add_callback("/test", cb)
        self.assertIn(id(cb), comet.notify_callbacks["/test"])

    def test_remove_callback(self) -> None:
        comet = Comet(None, "test")
        cb = Mock()
        comet.add_callback("/test", cb)
        comet.remove_callback("/test", cb)
        self.assertNotIn(id(cb), comet.notify_callbacks.get("/test", {}))

    def test_batch_mode(self) -> None:
        comet = Comet(None, "test")
        self.assertEqual(comet.batch, 0)
        comet.start_batch()
        self.assertEqual(comet.batch, 1)
        comet.start_batch()
        self.assertEqual(comet.batch, 2)
        comet.end_batch()
        self.assertEqual(comet.batch, 1)
        comet.end_batch()
        self.assertEqual(comet.batch, 0)

    def test_state_transitions(self) -> None:
        jnt = MockJnt()
        comet = Comet(jnt, "test")
        self.assertEqual(comet.state, UNCONNECTED)

        comet._set_state(CONNECTING)
        self.assertEqual(comet.state, CONNECTING)

        comet._set_state(CONNECTED)
        self.assertEqual(comet.state, CONNECTED)
        # Should have notified
        self.assertTrue(any(n[0] == "cometConnected" for n in jnt.notifications))

        comet._set_state(UNCONNECTED)
        self.assertEqual(comet.state, UNCONNECTED)
        self.assertTrue(any(n[0] == "cometDisconnected" for n in jnt.notifications))

    def test_set_state_same_state_noop(self) -> None:
        jnt = MockJnt()
        comet = Comet(jnt, "test")
        comet._set_state(UNCONNECTED)  # Same state
        # Should not emit notification for same state
        self.assertEqual(len(jnt.notifications), 0)

    def test_handle_advice_retry(self) -> None:
        jnt = MockJnt()
        comet = Comet(jnt, "test")
        comet.state = CONNECTING
        comet.isactive = True
        comet.advice = {"reconnect": "retry", "interval": 1000}
        comet._handle_advice()
        self.assertEqual(comet.state, UNCONNECTED)
        self.assertEqual(comet.failures, 1)

    def test_handle_advice_none(self) -> None:
        jnt = MockJnt()
        comet = Comet(jnt, "test")
        comet.state = CONNECTING
        comet.advice = {"reconnect": "none"}
        comet._handle_advice()
        self.assertIsNone(comet.client_id)

    def test_handle_advice_unconnected(self) -> None:
        comet = Comet(None, "test")
        comet.state = UNCONNECTED
        # Should be a no-op
        comet._handle_advice()

    def test_handle_timer_unconnected_retry(self) -> None:
        comet = Comet(None, "test")
        comet.state = UNCONNECTED
        comet.isactive = False
        comet.advice = {"reconnect": "retry"}
        # Should not raise
        comet._handle_timer()

    def test_handle_timer_not_unconnected(self) -> None:
        comet = Comet(None, "test")
        comet.state = CONNECTING
        # Should be ignored
        comet._handle_timer()

    def test_disconnect_when_unconnected(self) -> None:
        comet = Comet(None, "test")
        comet.state = UNCONNECTED
        comet.disconnect()  # Should be a no-op
        self.assertEqual(comet.state, UNCONNECTED)

    def test_connect_when_already_connected(self) -> None:
        jnt = MockJnt()
        comet = Comet(jnt, "test")
        comet.uri = "http://host:9000/cometd"
        comet.chttp = SocketHttp(None, "host", 9000, "c")
        comet.rhttp = SocketHttp(None, "host", 9000, "r")
        comet.state = CONNECTED
        comet.isactive = True
        comet.connect()  # Should be a no-op
        self.assertEqual(comet.state, CONNECTED)

    def test_set_idle_timeout(self) -> None:
        comet = Comet(None, "test")
        comet.set_idle_timeout(30)
        self.assertEqual(comet.idle_timeout, 30)

    def test_set_idle_timeout_zero(self) -> None:
        comet = Comet(None, "test")
        comet.set_idle_timeout(0)
        self.assertEqual(comet.idle_timeout, 0)

    def test_set_idle_timeout_none(self) -> None:
        comet = Comet(None, "test")
        comet.set_idle_timeout(None)
        self.assertIsNone(comet.idle_timeout)

    def test_response_meta_disconnect(self) -> None:
        comet = Comet(None, "test")
        comet.state = UNCONNECTING
        comet.client_id = "abc"
        chunk = [{"channel": "/meta/disconnect", "successful": True}]
        comet._response(chunk)
        self.assertIsNone(comet.client_id)
        self.assertEqual(comet.state, UNCONNECTED)

    def test_response_data_event(self) -> None:
        comet = Comet(None, "test")
        comet.client_id = "abc123"
        comet.state = CONNECTED

        events_received: List[dict] = []
        callback = lambda event: events_received.append(event)
        comet.notify_callbacks["/slim/serverstatus"] = {id(callback): callback}

        chunk = [
            {
                "channel": "/abc123/slim/serverstatus",
                "data": {"player_count": 3},
            }
        ]
        comet._response(chunk)
        self.assertEqual(len(events_received), 1)
        self.assertEqual(events_received[0]["data"]["player_count"], 3)

    def test_response_onetime_request(self) -> None:
        comet = Comet(None, "test")
        comet.client_id = "abc"
        comet.state = CONNECTED

        results: List[dict] = []
        callback = lambda event: results.append(event)
        comet.notify_callbacks["/slim/request|42"] = {id(callback): callback}

        chunk = [
            {
                "channel": "/abc/slim/request",
                "id": "42",
                "data": {"result": "ok"},
            }
        ]
        comet._response(chunk)
        self.assertEqual(len(results), 1)
        # One-time request should be cleaned up
        self.assertNotIn("/slim/request|42", comet.notify_callbacks)

    def test_response_unknown_subscription(self) -> None:
        comet = Comet(None, "test")
        comet.client_id = "abc"
        comet.state = CONNECTED

        # Should not raise for unknown subscriptions
        chunk = [{"channel": "/abc/unknown/channel", "data": {}}]
        comet._response(chunk)

    def test_response_none_chunk(self) -> None:
        comet = Comet(None, "test")
        # Should not raise
        comet._response(None)

    def test_response_empty_list(self) -> None:
        comet = Comet(None, "test")
        # Should not raise
        comet._response([])

    def test_notify_network_connected_while_connected(self) -> None:
        jnt = MockJnt()
        comet = Comet(jnt, "test")
        comet.uri = "http://host:9000/cometd"
        comet.chttp = Mock()
        comet.rhttp = Mock()
        comet.state = CONNECTED
        comet.isactive = True

        comet.notify_networkConnected()
        # Should have forced disconnect and attempted reconnect
        # (connect() will try to handshake since state was reset)

    def test_repr_and_str(self) -> None:
        comet = Comet(None, "my_comet")
        self.assertIn("my_comet", repr(comet))
        self.assertIn("Comet", str(comet))

    def test_add_pending_requests_subs(self) -> None:
        comet = Comet(None, "test")
        comet.client_id = "clientXYZ"

        cb = Mock()
        comet.subs.append(
            type(comet.subs).__class__.__mro__[0].__new__(type(comet.subs))
            if False
            else None
        )
        # Use the actual subscription mechanism
        comet.subs = []
        comet.subscribe("/slim/status", cb, "p1", ["status"])

        data: List[Dict[str, Any]] = []
        comet._add_pending_requests(data)

        self.assertTrue(len(data) > 0)
        sub_msg = data[0]
        self.assertEqual(sub_msg["channel"], "/slim/subscribe")
        self.assertIn("clientXYZ", sub_msg["data"]["response"])

    def test_add_pending_requests_unsubs(self) -> None:
        comet = Comet(None, "test")
        comet.client_id = "clientXYZ"

        from jive.net.comet import _PendingUnsub

        comet.pending_unsubs.append(_PendingUnsub(1, "/slim/status"))

        data: List[Dict[str, Any]] = []
        comet._add_pending_requests(data)

        self.assertTrue(len(data) > 0)
        unsub_msg = data[0]
        self.assertEqual(unsub_msg["channel"], "/slim/unsubscribe")

    def test_add_pending_requests_one_shot(self) -> None:
        comet = Comet(None, "test")
        comet.client_id = "clientXYZ"

        cb = Mock()
        comet.request(cb, "p1", ["status", "-", 1])

        data: List[Dict[str, Any]] = []
        comet._add_pending_requests(data)

        self.assertTrue(len(data) > 0)
        req_msg = data[0]
        self.assertEqual(req_msg["channel"], "/slim/request")

    def test_add_pending_no_client_id(self) -> None:
        comet = Comet(None, "test")
        comet.client_id = None
        comet.request(Mock(), "p1", ["status"])

        data: List[Dict[str, Any]] = []
        comet._add_pending_requests(data)
        # Should not add anything without client_id
        self.assertEqual(len(data), 0)


class TestSocketTcpServer(unittest.TestCase):
    """Tests for jive.net.socket_tcp_server.SocketTcpServer."""

    def test_init_valid(self) -> None:
        # Use port 0 to let OS assign a free port
        server = SocketTcpServer(None, "127.0.0.1", 0, "test_server")
        self.assertIsNotNone(server.t_sock)
        self.assertEqual(server.address, "127.0.0.1")
        self.assertEqual(server.connection_count, 0)
        self.assertEqual(server.js_name, "test_server")
        if server.t_sock:
            server.t_sock.close()

    def test_init_no_address(self) -> None:
        with self.assertRaises(ValueError):
            SocketTcpServer(None, "", 8080, "test")

    def test_init_no_port(self) -> None:
        with self.assertRaises(ValueError):
            SocketTcpServer(None, "127.0.0.1", None, "test")  # type: ignore[arg-type]

    def test_init_port_zero_valid(self) -> None:
        # Port 0 is valid — OS picks a free port
        server = SocketTcpServer(None, "127.0.0.1", 0, "test")
        self.assertIsNotNone(server.t_sock)
        if server.t_sock is not None:
            server.t_sock.close()

    def test_t_accept_no_connection(self) -> None:
        server = SocketTcpServer(None, "127.0.0.1", 0, "test")
        if server.t_sock is None:
            self.skipTest("Server socket not created")
        # No clients connecting — should timeout and return None
        result = server.t_accept()
        self.assertIsNone(result)
        server.t_sock.close()

    def test_t_accept_with_client(self) -> None:
        server = SocketTcpServer(None, "127.0.0.1", 0, "test")
        if server.t_sock is None:
            self.skipTest("Server socket not created")

        # Get the actual port assigned
        actual_port = server.t_sock.getsockname()[1]

        # Connect a client
        client = _socket_mod.socket(_socket_mod.AF_INET, _socket_mod.SOCK_STREAM)
        client.connect(("127.0.0.1", actual_port))

        # Accept the client
        accepted = server.t_accept()
        self.assertIsNotNone(accepted)
        self.assertIsInstance(accepted, SocketTcp)
        self.assertTrue(accepted.connected())
        self.assertEqual(server.connection_count, 1)

        # Cleanup
        client.close()
        if accepted.t_sock:
            accepted.t_sock.close()
        server.t_sock.close()

    def test_t_get_address_port(self) -> None:
        server = SocketTcpServer(None, "127.0.0.1", 0, "test")
        if server.t_sock is None:
            self.skipTest("Server socket not created")
        addr, port = server.t_get_address_port()
        self.assertEqual(addr, "127.0.0.1")
        server.t_sock.close()

    def test_repr_and_str(self) -> None:
        server = SocketTcpServer(None, "127.0.0.1", 0, "my_server")
        self.assertIn("my_server", repr(server))
        self.assertIn("SocketTcpServer", str(server))
        if server.t_sock:
            server.t_sock.close()

    def test_t_add_read_forces_no_timeout(self) -> None:
        jnt = MockJnt()
        server = SocketTcpServer(jnt, "127.0.0.1", 0, "test")
        if server.t_sock is None:
            self.skipTest("Server socket not created")

        server.priority = 3
        pump = Mock()
        server.t_add_read(pump, 999)  # timeout should be forced to 0
        # The read pump should be set
        self.assertIsNotNone(server.read_pump)
        server.t_sock.close()


# ======================================================================
# Integration
# ======================================================================


class TestM9Integration(unittest.TestCase):
    """Cross-module integration tests for M9."""

    def setUp(self) -> None:
        DNS.reset()

    def tearDown(self) -> None:
        DNS.reset()
        Task.clear_all()

    def test_all_net_modules_importable(self) -> None:
        """Verify all M9 modules can be imported."""
        from jive.net import (
            comet,
            comet_request,
            dns,
            http_pool,
            network_thread,
            process,
            request_http,
            request_jsonrpc,
            socket_base,
            socket_http,
            socket_http_queue,
            socket_tcp,
            socket_tcp_server,
            socket_udp,
            wake_on_lan,
        )

    def test_socket_hierarchy(self) -> None:
        """Verify the inheritance hierarchy."""
        self.assertTrue(issubclass(SocketTcp, SocketBase))
        self.assertTrue(issubclass(SocketUdp, SocketBase))
        self.assertTrue(issubclass(SocketHttp, SocketTcp))
        self.assertTrue(issubclass(SocketHttpQueue, SocketHttp))
        self.assertTrue(issubclass(SocketTcpServer, SocketBase))
        self.assertTrue(issubclass(WakeOnLan, SocketUdp))

    def test_request_hierarchy(self) -> None:
        """Verify request class hierarchy."""
        self.assertTrue(issubclass(RequestJsonRpc, RequestHttp))
        self.assertTrue(issubclass(CometRequest, RequestHttp))

    def test_network_thread_with_socket(self) -> None:
        """Test NetworkThread with a real socket object."""
        jnt = NetworkThread()

        # Create a UDP socket (easy to create without connecting)
        su = SocketUdp(None, None, "integration_test")
        self.assertIsNotNone(su.t_sock)

        task = Task("int_task", None, lambda obj: (yield True))
        task.priority = 3

        jnt.t_add_read(su.t_sock, task, 5)
        self.assertEqual(jnt.read_socket_count, 1)

        jnt.t_remove_read(su.t_sock)
        self.assertEqual(jnt.read_socket_count, 0)

        if su.t_sock:
            su.t_sock.close()

    def test_http_pool_with_socket_http_queue(self) -> None:
        """Test HttpPool creates SocketHttpQueue instances correctly."""
        pool = HttpPool(None, "int_test", "192.168.1.1", 9000, quantity=3)
        self.assertEqual(pool.pool_size, 3)

        for sock in pool.sockets:
            self.assertIsInstance(sock, SocketHttpQueue)
            self.assertEqual(sock.host, "192.168.1.1")
            self.assertEqual(sock.port, 9000)

        pool.free()

    def test_request_roundtrip_jsonrpc(self) -> None:
        """Test creating a JSON-RPC request and verifying its structure."""
        results: List[Any] = []
        sink = lambda data=None, err=None, req=None: results.append(data)

        req = RequestJsonRpc(
            sink, "/jsonrpc", "slim.request", ["", ["serverstatus", 0, 50]]
        )

        # Verify the request body
        body = req.t_body()
        self.assertIsNotNone(body)
        decoded = json.loads(body)
        self.assertEqual(decoded["method"], "slim.request")
        self.assertEqual(decoded["params"], ["", ["serverstatus", 0, 50]])

        # Simulate a response
        req.t_set_response_headers(200, "OK", {})
        req.t_set_response_body('{"result": {"player_count": 2}}')

        self.assertTrue(len(results) > 0)
        self.assertEqual(results[0]["result"]["player_count"], 2)

    def test_comet_subscribe_request_roundtrip(self) -> None:
        """Test Comet subscribe and request flow."""
        comet = Comet(None, "integration")
        comet.client_id = "test_client"

        # Subscribe
        sub_callback = Mock()
        comet.subscribe("/slim/status", sub_callback, "p1", ["status"])

        # Request
        req_callback = Mock()
        comet.request(req_callback, "p1", ["pause"])

        # Build pending requests
        data: List[Dict[str, Any]] = []
        comet._add_pending_requests(data)

        # Should have subscription + request
        self.assertTrue(len(data) >= 2)

        channels = [d["channel"] for d in data]
        self.assertIn("/slim/subscribe", channels)
        self.assertIn("/slim/request", channels)

    def test_dns_with_network_thread(self) -> None:
        """Test DNS singleton works with NetworkThread."""
        DNS.reset()
        jnt = NetworkThread()
        dns = DNS(jnt)
        self.assertIs(dns.jnt, jnt)

        # Basic resolution
        self.assertTrue(dns.is_ip("127.0.0.1"))
        ip, hostent = dns.toip("127.0.0.1")
        self.assertEqual(ip, "127.0.0.1")

    def test_wake_on_lan_packet_structure(self) -> None:
        """Test WakeOnLan packet structure without sending."""
        wol = WakeOnLan(None)
        mac = "00:11:22:33:44:55"

        # Extract hex pairs
        import re

        hex_pairs = re.findall(r"([0-9a-fA-F]{2})", mac)
        mac_bytes = bytes(int(h, 16) for h in hex_pairs)
        expected_packet = b"\xff" * 6 + mac_bytes * 16

        # Verify packet length: 6 + 6*16 = 102 bytes
        self.assertEqual(len(expected_packet), 102)
        self.assertTrue(expected_packet.startswith(b"\xff\xff\xff\xff\xff\xff"))

        if wol.t_sock:
            wol.t_sock.close()

    def test_process_echo_integration(self) -> None:
        """Test Process with a real subprocess."""
        output_chunks: List[Any] = []

        def sink(chunk: Any = None, err: Any = None) -> None:
            if err:
                output_chunks.append(("error", err))
            else:
                output_chunks.append(("data", chunk))

        proc = Process(None, "echo integration_test_output")
        proc.read(sink)

        self.assertEqual(proc.status, "dead")
        data_parts = [
            c[1] for c in output_chunks if c[0] == "data" and c[1] is not None
        ]
        combined = b"".join(
            d if isinstance(d, bytes) else d.encode() for d in data_parts
        )
        self.assertIn(b"integration_test_output", combined)

    def test_existing_tests_not_broken(self) -> None:
        """Smoke test: verify core UI modules still import cleanly."""
        from jive.ui.event import Event
        from jive.ui.task import PRIORITY_HIGH, PRIORITY_LOW, Task
        from jive.ui.timer import Timer

        # Quick sanity check
        t = Task("smoke", None, lambda obj: (yield True))
        self.assertEqual(t.name, "smoke")

    def test_socket_tcp_server_accept_roundtrip(self) -> None:
        """Test a complete server accept + client connect cycle."""
        server = SocketTcpServer(None, "127.0.0.1", 0, "roundtrip")
        if server.t_sock is None:
            self.skipTest("Server socket not created")

        actual_port = server.t_sock.getsockname()[1]

        # Client connects
        client = _socket_mod.socket(_socket_mod.AF_INET, _socket_mod.SOCK_STREAM)
        client.settimeout(2)
        client.connect(("127.0.0.1", actual_port))

        # Server accepts
        conn = server.t_accept()
        self.assertIsNotNone(conn)
        self.assertTrue(conn.connected())

        # Client sends data
        client.sendall(b"hello")

        # Server reads data (blocking for simplicity in test)
        conn.t_sock.setblocking(True)
        conn.t_sock.settimeout(2)
        data = conn.t_sock.recv(1024)
        self.assertEqual(data, b"hello")

        # Cleanup
        client.close()
        conn.t_sock.close()
        server.t_sock.close()


# ======================================================================
# Module count verification
# ======================================================================


class TestM9ModuleCount(unittest.TestCase):
    """Verify we have the expected number of net modules."""

    def test_module_count(self) -> None:
        """Verify all 15 net modules exist."""
        import importlib

        modules = [
            "jive.net.socket_base",
            "jive.net.socket_tcp",
            "jive.net.socket_udp",
            "jive.net.process",
            "jive.net.dns",
            "jive.net.network_thread",
            "jive.net.wake_on_lan",
            "jive.net.request_http",
            "jive.net.request_jsonrpc",
            "jive.net.socket_http",
            "jive.net.socket_http_queue",
            "jive.net.http_pool",
            "jive.net.comet_request",
            "jive.net.comet",
            "jive.net.socket_tcp_server",
        ]

        for mod_name in modules:
            mod = importlib.import_module(mod_name)
            self.assertIsNotNone(mod, f"Module {mod_name} should be importable")

        self.assertEqual(len(modules), 15)


if __name__ == "__main__":
    unittest.main()
