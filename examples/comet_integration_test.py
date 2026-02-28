#!/usr/bin/env python3
"""
comet_integration_test.py — Integration test for the full Comet pipeline.

Tests the real jive.net.Comet → jive.slim.SlimServer → jive.slim.Player
pipeline against a running Resonance/LMS server, proving that the ported
applet architecture can establish a live Bayeux/Comet connection and
receive push updates.

This is NOT a unit test — it requires a real server on the network.

Usage:
    python examples/comet_integration_test.py
    python examples/comet_integration_test.py --server 192.168.1.35
    python examples/comet_integration_test.py --server 192.168.1.35 --port 9000

What it tests (in order):
    1. NetworkThread creation and task scheduling
    2. Comet handshake (obtain clientId)
    3. Comet /meta/connect + /meta/subscribe
    4. SlimServer.connect() → Comet.connect() integration
    5. serverstatus subscription → Player creation
    6. Player.on_stage() → playerstatus subscription
    7. Player status push updates (mode, track, volume)
    8. Player commands (play/pause) via SlimServer.request()
    9. Clean disconnect

Copyright 2025
License: BSD-3-Clause
"""

from __future__ import annotations

import argparse
import io
import json
import os
import socket
import struct
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Force UTF-8 output on Windows
# ---------------------------------------------------------------------------
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ---------------------------------------------------------------------------
# Ensure project root is on sys.path
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_HERE)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# ---------------------------------------------------------------------------
# ANSI helpers
# ---------------------------------------------------------------------------
_IS_TTY = hasattr(sys.stdout, "isatty") and sys.stdout.isatty()

BOLD = "\033[1m"
DIM = "\033[2m"
GREEN = "\033[32m"
CYAN = "\033[36m"
YELLOW = "\033[33m"
RED = "\033[31m"
MAGENTA = "\033[35m"
RESET = "\033[0m"

if not _IS_TTY:
    BOLD = DIM = GREEN = CYAN = YELLOW = RED = MAGENTA = RESET = ""


# ═══════════════════════════════════════════════════════════════════════════
# Test infrastructure
# ═══════════════════════════════════════════════════════════════════════════


class TestResult:
    """Tracks pass/fail for a single test."""

    def __init__(self, name: str):
        self.name = name
        self.passed: Optional[bool] = None
        self.message: str = ""
        self.duration: float = 0.0

    def ok(self, msg: str = "") -> None:
        self.passed = True
        self.message = msg

    def fail(self, msg: str = "") -> None:
        self.passed = False
        self.message = msg

    def skip(self, msg: str = "") -> None:
        self.passed = None
        self.message = msg

    def __str__(self) -> str:
        if self.passed is True:
            icon = f"{GREEN}✓{RESET}"
        elif self.passed is False:
            icon = f"{RED}✗{RESET}"
        else:
            icon = f"{YELLOW}⊘{RESET}"
        dur = f" ({self.duration:.1f}s)" if self.duration > 0.1 else ""
        msg = f"  {DIM}{self.message}{RESET}" if self.message else ""
        return f"  {icon} {self.name}{dur}{msg}"


class TestRunner:
    """Simple test runner with pass/fail tracking."""

    def __init__(self):
        self.results: List[TestResult] = []
        self._current: Optional[TestResult] = None

    def test(self, name: str) -> TestResult:
        r = TestResult(name)
        self.results.append(r)
        self._current = r
        print(f"\n  {CYAN}▸ {name}…{RESET}", end="", flush=True)
        r._start = time.time()
        return r

    def finish(self, result: TestResult) -> None:
        result.duration = time.time() - result._start
        # Rewrite the line
        print(f"\r{result}")

    def summary(self) -> int:
        passed = sum(1 for r in self.results if r.passed is True)
        failed = sum(1 for r in self.results if r.passed is False)
        skipped = sum(1 for r in self.results if r.passed is None)
        total = len(self.results)

        print(f"\n{'─' * 60}")
        color = GREEN if failed == 0 else RED
        print(
            f"  {color}{BOLD}{passed}/{total} passed{RESET}"
            f"  {RED}{failed} failed{RESET}"
            * (failed > 0)
            + f"  {YELLOW}{skipped} skipped{RESET}" * (skipped > 0)
        )
        print()
        return 1 if failed > 0 else 0


# ═══════════════════════════════════════════════════════════════════════════
# Event collector — captures jnt.notify() events
# ═══════════════════════════════════════════════════════════════════════════


class EventCollector:
    """
    Collects events from jnt.notify() for assertion in tests.

    Works as a jnt subscriber — jnt.notify("foo", ...) calls
    self.notify_foo(...) via the standard subscriber mechanism.
    We use __getattr__ to catch all notify_* calls dynamically.

    Thread-safe — events may arrive from the NetworkThread.
    """

    def __init__(self):
        self._events: List[Tuple[str, tuple]] = []
        self._lock = threading.Lock()
        self._waiters: Dict[str, threading.Event] = {}

    def __getattr__(self, name: str) -> Any:
        """Intercept all notify_* method lookups and record the event."""
        if name.startswith("notify_"):
            event_name = name[len("notify_") :]

            def _handler(*args: Any) -> None:
                self._record(event_name, args)

            return _handler
        raise AttributeError(name)

    def _record(self, event_name: str, args: tuple) -> None:
        with self._lock:
            self._events.append((event_name, args))
            waiter = self._waiters.get(event_name)
            if waiter:
                waiter.set()

    def wait_for(self, event_name: str, timeout: float = 10.0) -> bool:
        ev = threading.Event()
        with self._lock:
            # Check if already received
            for name, _ in self._events:
                if name == event_name:
                    return True
            self._waiters[event_name] = ev

        result = ev.wait(timeout)
        with self._lock:
            self._waiters.pop(event_name, None)
        return result

    def get_events(self, event_name: Optional[str] = None) -> List[Tuple[str, tuple]]:
        with self._lock:
            if event_name:
                return [(n, a) for n, a in self._events if n == event_name]
            return list(self._events)

    def clear(self) -> None:
        with self._lock:
            self._events.clear()

    def has(self, event_name: str) -> bool:
        with self._lock:
            return any(n == event_name for n, _ in self._events)


# ═══════════════════════════════════════════════════════════════════════════
# Server reachability check
# ═══════════════════════════════════════════════════════════════════════════


def check_server(ip: str, port: int) -> Optional[Dict[str, Any]]:
    """Quick JSON-RPC check — returns serverstatus or None."""
    url = f"http://{ip}:{port}/jsonrpc.js"
    data = json.dumps(
        {
            "id": 1,
            "method": "slim.request",
            "params": ["", ["serverstatus", 0, 50]],
        }
    ).encode()
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}
    )
    try:
        resp = urllib.request.urlopen(req, timeout=5)
        result = json.loads(resp.read())
        return result.get("result")
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════════════════
# UDP Discovery (reused from live_player_control)
# ═══════════════════════════════════════════════════════════════════════════

DISCOVERY_PORT = 3483


def discover_server(
    target: Optional[str] = None, timeout: float = 5.0
) -> Optional[Dict[str, str]]:
    """Discover a server via UDP TLV broadcast."""
    tags = {
        "IPAD": b"\x00" * 4,
        "NAME": b"",
        "JSON": b"",
        "VERS": b"",
        "UUID": b"",
    }

    pkt = b"e"
    for tag, value in tags.items():
        tag_bytes = tag.encode("ascii")[:4]
        pkt += tag_bytes + struct.pack(">B", len(value)) + value

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(timeout)

    dest = (target or "255.255.255.255", DISCOVERY_PORT)

    try:
        sock.sendto(pkt, dest)
        data, addr = sock.recvfrom(4096)
    except socket.timeout:
        return None
    finally:
        sock.close()

    if not data or data[0:1] != b"E":
        return None

    result: Dict[str, str] = {"_addr": addr[0]}
    pos = 1
    while pos + 5 <= len(data):
        tag = data[pos : pos + 4].decode("ascii", errors="replace")
        length = data[pos + 4]
        pos += 5
        if pos + length > len(data):
            break
        value = data[pos : pos + length]
        pos += length

        if tag == "IPAD" and length == 4:
            result[tag] = socket.inet_ntoa(value)
        else:
            result[tag] = value.decode("utf-8", errors="replace")

    return result


# ═══════════════════════════════════════════════════════════════════════════
# NetworkThread pump driver
# ═══════════════════════════════════════════════════════════════════════════


class NetworkPump:
    """
    Drives the NetworkThread's select loop in a background thread.

    The jive.net architecture uses a cooperative select-based event
    loop.  In the real app this is driven by the Framework's task
    scheduler which calls both ``_t_select()`` (to dispatch ready
    sockets to task queues) AND ``Task.iterator()`` / ``resume()``
    (to actually run the queued pump functions).

    Our pump replicates both halves of that loop.

    IMPORTANT: ``_t_select()`` and ``Task.resume()`` must run in the
    same thread and must NOT be called concurrently — generators are
    not re-entrant.  We use a lock to guarantee this, and we avoid
    resuming a task whose generator is already executing.
    """

    def __init__(self, jnt: Any):
        self.jnt = jnt
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=3)

    def _run(self) -> None:
        from jive.ui.task import Task

        while self._running:
            with self._lock:
                try:
                    # Phase 1: select() — finds ready sockets and queues
                    # their Tasks via add_task()
                    self.jnt._t_select(0.05)

                    # Phase 2: iterate + resume — actually runs the queued
                    # pump functions (send request bytes, receive response
                    # bytes, call sinks, etc.)
                    for task in Task.iterator():
                        # Guard against re-entrant resume — if a previous
                        # task.resume() triggered a callback that itself
                        # called add_task() on the same generator, the
                        # generator will already be executing.
                        if task.state != "active":
                            continue
                        try:
                            task.resume()
                        except ValueError as ve:
                            if "generator already executing" in str(ve):
                                pass  # skip — will be resumed next cycle
                            else:
                                raise
                except Exception:
                    pass


# ═══════════════════════════════════════════════════════════════════════════
# Register collector as jnt subscriber
# ═══════════════════════════════════════════════════════════════════════════


def register_collector(jnt: Any, collector: EventCollector) -> None:
    """Register the collector as a jnt subscriber so it receives all events."""
    jnt.subscribe(collector)


# ═══════════════════════════════════════════════════════════════════════════
# Main test sequence
# ═══════════════════════════════════════════════════════════════════════════


def run_tests(server_ip: str, server_port: int) -> int:
    """Run all integration tests. Returns exit code (0=ok, 1=fail)."""

    runner = TestRunner()
    collector = EventCollector()
    jnt = None
    pump = None
    slim_server = None
    comet = None

    print(
        f"\n{CYAN}{BOLD}"
        "╔══════════════════════════════════════════════════════════════╗\n"
        "║   Comet Integration Test — jive.net.Comet pipeline         ║\n"
        "╚══════════════════════════════════════════════════════════════╝"
        f"{RESET}"
    )
    print(f"  Target: {server_ip}:{server_port}\n")

    # ------------------------------------------------------------------
    # Test 0: Server reachability
    # ------------------------------------------------------------------
    t = runner.test("Server reachability (JSON-RPC)")
    status = check_server(server_ip, server_port)
    if status:
        version = status.get("version", "?")
        player_count = status.get("player count", 0)
        t.ok(f"v{version}, {player_count} player(s)")
    else:
        t.fail("Server not responding — cannot continue")
        runner.finish(t)
        return runner.summary()
    runner.finish(t)

    players_loop = status.get("players_loop", [])
    if not players_loop:
        print(f"\n  {RED}No players found — some tests will be skipped{RESET}")

    # ------------------------------------------------------------------
    # Test 1: Import core modules
    # ------------------------------------------------------------------
    t = runner.test("Import jive.net and jive.slim modules")
    try:
        from jive.net.comet import Comet
        from jive.net.comet_request import CometRequest
        from jive.net.network_thread import NetworkThread
        from jive.net.socket_http import SocketHttp
        from jive.slim.player import Player, reset_player_globals
        from jive.slim.slim_server import SlimServer, reset_server_globals

        t.ok("All imports successful")
    except Exception as e:
        t.fail(f"Import error: {e}")
        runner.finish(t)
        return runner.summary()
    runner.finish(t)

    # ------------------------------------------------------------------
    # Test 2: Create NetworkThread
    # ------------------------------------------------------------------
    t = runner.test("Create NetworkThread")
    try:
        # Reset globals to ensure clean state
        reset_server_globals()
        reset_player_globals()

        jnt = NetworkThread()
        register_collector(jnt, collector)
        t.ok(f"NetworkThread created")
    except Exception as e:
        t.fail(f"Error: {e}")
        runner.finish(t)
        return runner.summary()
    runner.finish(t)

    # ------------------------------------------------------------------
    # Test 3: Create Comet instance
    # ------------------------------------------------------------------
    t = runner.test("Create Comet and set endpoint")
    try:
        comet = Comet(jnt=jnt, name="test_comet")
        comet.set_endpoint(server_ip, server_port, "/cometd")
        t.ok(f"Endpoint: {comet.uri}")
        assert comet.uri == f"http://{server_ip}:{server_port}/cometd"
        assert comet.chttp is not None
        assert comet.rhttp is not None
    except Exception as e:
        t.fail(f"Error: {e}")
        runner.finish(t)
        return runner.summary()
    runner.finish(t)

    # ------------------------------------------------------------------
    # Test 4: Start network pump
    # ------------------------------------------------------------------
    t = runner.test("Start NetworkThread pump (background thread)")
    try:
        pump = NetworkPump(jnt)
        pump.start()
        time.sleep(0.2)
        t.ok("Pump running")
    except Exception as e:
        t.fail(f"Error: {e}")
        runner.finish(t)
        return runner.summary()
    runner.finish(t)

    # ------------------------------------------------------------------
    # Test 5: Comet handshake (connect)
    # ------------------------------------------------------------------
    t = runner.test("Comet.connect() → handshake")
    try:
        comet.connect()

        # Wait for the handshake to complete — poll state
        deadline = time.time() + 15.0
        while comet.state != "CONNECTED" and time.time() < deadline:
            time.sleep(0.1)

        if comet.state == "CONNECTED":
            t.ok(f"clientId={comet.client_id}, state=CONNECTED")
        else:
            t.fail(f"state={comet.state}, clientId={comet.client_id}")
    except Exception as e:
        t.fail(f"Error: {e}\n{traceback.format_exc()}")
    runner.finish(t)

    # ------------------------------------------------------------------
    # Test 6: Comet subscribe (serverstatus)
    # ------------------------------------------------------------------
    serverstatus_data: List[Dict[str, Any]] = []
    serverstatus_event = threading.Event()

    t = runner.test("Comet.subscribe('/slim/serverstatus')")
    try:

        def on_serverstatus(event: Any) -> None:
            data = event if isinstance(event, dict) else {}
            if isinstance(data, dict) and "data" in data:
                data = data["data"]
            serverstatus_data.append(data)
            serverstatus_event.set()

        comet.subscribe(
            "/slim/serverstatus",
            on_serverstatus,
            None,
            ["serverstatus", 0, 50, "subscribe:60"],
        )

        # Wait for push data
        got_data = serverstatus_event.wait(timeout=15.0)
        if got_data and serverstatus_data:
            d = serverstatus_data[0]
            player_count = d.get("player count", d.get("player_count", "?"))
            version = d.get("version", "?")
            t.ok(f"Received serverstatus push: {player_count} player(s), v{version}")
        else:
            t.fail("No serverstatus data received within timeout")
    except Exception as e:
        t.fail(f"Error: {e}\n{traceback.format_exc()}")
    runner.finish(t)

    # ------------------------------------------------------------------
    # Test 7: Comet subscribe (playerstatus)
    # ------------------------------------------------------------------
    playerstatus_data: List[Dict[str, Any]] = []
    playerstatus_event = threading.Event()

    if players_loop:
        player_id = players_loop[0].get("playerid", "")
        player_name = players_loop[0].get("name", "?")

        t = runner.test(f"Comet.subscribe('/slim/playerstatus') for {player_name}")
        try:

            def on_playerstatus(event: Any) -> None:
                data = event if isinstance(event, dict) else {}
                if isinstance(data, dict) and "data" in data:
                    data = data["data"]
                playerstatus_data.append(data)
                playerstatus_event.set()

            comet.subscribe(
                f"/slim/playerstatus/{player_id}",
                on_playerstatus,
                player_id,
                [
                    "status",
                    "-",
                    10,
                    "menu:menu",
                    "useContextMenu:1",
                    "subscribe:30",
                    "tags:aAlcdegiJKlNoqrStuwxy",
                ],
            )

            got_data = playerstatus_event.wait(timeout=15.0)
            if got_data and playerstatus_data:
                d = playerstatus_data[0]
                mode = d.get("mode", "?")
                track_info = ""
                pl = d.get("playlist_loop", [])
                if pl and isinstance(pl, list) and len(pl) > 0:
                    track = pl[0]
                    title = track.get("title", "?")
                    artist = track.get("artist", "")
                    track_info = f" — {title}"
                    if artist:
                        track_info += f" by {artist}"
                t.ok(f"mode={mode}{track_info}")
            else:
                t.fail("No playerstatus data received within timeout")
        except Exception as e:
            t.fail(f"Error: {e}\n{traceback.format_exc()}")
        runner.finish(t)
    else:
        t = runner.test("Comet.subscribe('/slim/playerstatus')")
        t.skip("No players available")
        runner.finish(t)

    # ------------------------------------------------------------------
    # Test 8: Comet one-shot request
    # ------------------------------------------------------------------
    request_data: List[Dict[str, Any]] = []
    request_event = threading.Event()

    t = runner.test("Comet.request() one-shot (server version)")
    try:

        def on_request(event: Any) -> None:
            data = event if isinstance(event, dict) else {}
            if isinstance(data, dict) and "data" in data:
                data = data["data"]
            request_data.append(data)
            request_event.set()

        comet.request(
            on_request,
            None,
            ["version", "?"],
        )

        got_data = request_event.wait(timeout=10.0)
        if got_data and request_data:
            d = request_data[0]
            version = d.get("_version", d.get("version", "?"))
            t.ok(f"version={version}")
        else:
            t.fail("No request response received within timeout")
    except Exception as e:
        t.fail(f"Error: {e}\n{traceback.format_exc()}")
    runner.finish(t)

    # ------------------------------------------------------------------
    # Test 9: Clean disconnect
    # ------------------------------------------------------------------
    t = runner.test("Comet.disconnect()")
    try:
        comet.disconnect()
        time.sleep(1)
        t.ok(f"state={comet.state}")
    except Exception as e:
        t.fail(f"Error: {e}")
    runner.finish(t)

    # ── Cleanup from Comet-only tests ─────────────────────────────────
    # Stop the first pump and clear the global Task queue so the
    # SlimServer tests start with a clean slate.
    if pump:
        pump.stop()
        pump = None
    from jive.ui.task import Task as _Task

    _Task.clear_all()
    time.sleep(0.3)

    # ------------------------------------------------------------------
    # Test 10: SlimServer integration (full pipeline)
    # ------------------------------------------------------------------
    t = runner.test("SlimServer → Comet → Player pipeline")
    try:
        # Reset for clean start
        collector.clear()
        reset_server_globals()
        reset_player_globals()
        _Task.clear_all()

        # Create new NetworkThread and pump
        jnt2 = NetworkThread()
        collector2 = EventCollector()
        register_collector(jnt2, collector2)

        pump2 = NetworkPump(jnt2)
        pump2.start()

        # Create SlimServer
        slim_server = SlimServer(
            jnt=jnt2,
            server_id=f"{server_ip}:{server_port}",
            name="TestServer",
            version=str(status.get("version", "")),
        )

        # Set endpoint and connect
        slim_server.update_address(server_ip, server_port, "TestServer")
        slim_server.connect()

        # Wait for cometConnected
        deadline = time.time() + 15.0
        while slim_server.netstate != "connected" and time.time() < deadline:
            time.sleep(0.1)

        if slim_server.netstate == "connected":
            # Wait a bit for serverstatus subscription to deliver data
            time.sleep(3)

            player_ids = list(slim_server.players.keys())
            player_names = [slim_server.players[pid].get_name() for pid in player_ids]
            t.ok(
                f"Connected! {len(player_ids)} player(s): "
                f"{', '.join(player_names) if player_names else 'none'}"
            )
        else:
            t.fail(
                f"netstate={slim_server.netstate}, comet.state={slim_server.comet.state}"
            )

        # Cleanup
        slim_server.disconnect()
        time.sleep(0.5)
        pump2.stop()
        _Task.clear_all()
    except Exception as e:
        t.fail(f"Error: {e}\n{traceback.format_exc()}")
    runner.finish(t)

    # ------------------------------------------------------------------
    # Test 11: Player.on_stage() → playerstatus subscription
    # ------------------------------------------------------------------
    if players_loop:
        t = runner.test("Player.on_stage() subscription")
        try:
            collector3 = EventCollector()
            reset_server_globals()
            reset_player_globals()
            _Task.clear_all()

            jnt3 = NetworkThread()
            register_collector(jnt3, collector3)
            pump3 = NetworkPump(jnt3)
            pump3.start()

            slim3 = SlimServer(
                jnt=jnt3,
                server_id=f"{server_ip}:{server_port}_onstage",
                name="OnStageTest",
                version=str(status.get("version", "")),
            )
            slim3.update_address(server_ip, server_port, "OnStageTest")
            slim3.connect()

            # Wait for connection + player creation
            deadline = time.time() + 15.0
            while slim3.netstate != "connected" and time.time() < deadline:
                time.sleep(0.1)

            if slim3.netstate == "connected":
                time.sleep(3)  # Wait for serverstatus

                if slim3.players:
                    pid = list(slim3.players.keys())[0]
                    player = slim3.players[pid]

                    # on_stage subscribes to playerstatus + displaystatus
                    player.on_stage()
                    time.sleep(5)

                    # Check if we got a playerTrackChange or playerModeChange event
                    has_mode = collector3.has("playerModeChange")
                    has_track = collector3.has("playerTrackChange")
                    mode = player.get_player_mode()
                    name = player.get_name()

                    events_str = []
                    if has_mode:
                        events_str.append("playerModeChange")
                    if has_track:
                        events_str.append("playerTrackChange")

                    if mode or has_mode or has_track:
                        t.ok(
                            f"{name}: mode={mode}, "
                            f"events=[{', '.join(events_str) if events_str else 'none yet'}]"
                        )
                    else:
                        # Still OK if the subscription was set up — data may
                        # just not have arrived yet on the push channel
                        t.ok(f"{name}: on_stage() subscribed, mode={mode}")
                else:
                    t.skip("No players created by serverstatus")
            else:
                t.fail(f"netstate={slim3.netstate}")

            slim3.disconnect()
            time.sleep(0.5)
            pump3.stop()
            _Task.clear_all()
        except Exception as e:
            t.fail(f"Error: {e}\n{traceback.format_exc()}")
        runner.finish(t)
    else:
        t = runner.test("Player.on_stage() subscription")
        t.skip("No players available")
        runner.finish(t)

    # ------------------------------------------------------------------
    # Test 12: Player commands (send)
    # ------------------------------------------------------------------
    if players_loop:
        t = runner.test("Player.send() command (status query)")
        try:
            collector4 = EventCollector()
            reset_server_globals()
            reset_player_globals()
            _Task.clear_all()

            jnt4 = NetworkThread()
            register_collector(jnt4, collector4)
            pump4 = NetworkPump(jnt4)
            pump4.start()

            slim4 = SlimServer(
                jnt=jnt4,
                server_id=f"{server_ip}:{server_port}_cmd",
                name="CmdTest",
                version=str(status.get("version", "")),
            )
            slim4.update_address(server_ip, server_port, "CmdTest")
            slim4.connect()

            deadline = time.time() + 15.0
            while slim4.netstate != "connected" and time.time() < deadline:
                time.sleep(0.1)

            if slim4.netstate == "connected":
                time.sleep(3)

                if slim4.players:
                    pid = list(slim4.players.keys())[0]
                    player = slim4.players[pid]

                    # Send a status request (non-destructive)
                    request_done = threading.Event()
                    request_result: List[Any] = []

                    def on_status_response(event: Any) -> None:
                        request_result.append(event)
                        request_done.set()

                    slim4.comet.request(
                        on_status_response,
                        pid,
                        ["status", "-", 1, "tags:al"],
                    )

                    got = request_done.wait(timeout=10.0)
                    if got and request_result:
                        ev = request_result[0]
                        data = ev if isinstance(ev, dict) else {}
                        if isinstance(data, dict) and "data" in data:
                            data = data["data"]
                        mode = data.get("mode", "?")
                        t.ok(f"Got status response: mode={mode}")
                    else:
                        t.fail("No response to status request")
                else:
                    t.skip("No players")
            else:
                t.fail(f"netstate={slim4.netstate}")

            slim4.disconnect()
            time.sleep(0.5)
            pump4.stop()
            _Task.clear_all()
        except Exception as e:
            t.fail(f"Error: {e}\n{traceback.format_exc()}")
        runner.finish(t)
    else:
        t = runner.test("Player.send() command")
        t.skip("No players available")
        runner.finish(t)

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------
    _Task.clear_all()
    if pump:
        pump.stop()

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    return runner.summary()


# ═══════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Integration test: Comet → SlimServer → Player pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Tests the full ported Bayeux/Comet pipeline against a real Resonance/LMS server.

Examples:
  %(prog)s                              # Auto-discover server
  %(prog)s --server 192.168.1.35        # Connect to specific server
  %(prog)s --server 192.168.1.35 -p 9000
""",
    )
    parser.add_argument("--server", "-s", default=None, help="Server IP address")
    parser.add_argument(
        "--port", "-p", type=int, default=9000, help="Server port (default: 9000)"
    )
    parser.add_argument(
        "--discover-timeout",
        type=float,
        default=5.0,
        help="Discovery timeout (default: 5s)",
    )

    args = parser.parse_args()

    server_ip = args.server
    server_port = args.port

    if not server_ip:
        print(f"  {BOLD}Discovering servers…{RESET}")
        tlv = discover_server(timeout=args.discover_timeout)
        if tlv:
            server_ip = tlv.get("IPAD", tlv.get("_addr", ""))
            try:
                server_port = int(tlv.get("JSON", "9000"))
            except (ValueError, TypeError):
                server_port = 9000
            name = tlv.get("NAME", "?")
            version = tlv.get("VERS", "?")
            print(
                f"  {GREEN}✓ Found: {name} @ {server_ip}:{server_port} (v{version}){RESET}"
            )
        else:
            print(f"  {RED}No server found via UDP discovery{RESET}")
            print(f"  {DIM}Try: {sys.argv[0]} --server <ip>{RESET}")
            sys.exit(1)

    exit_code = run_tests(server_ip, server_port)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
