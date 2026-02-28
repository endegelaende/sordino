#!/usr/bin/env python3
"""
live_player_control.py — Real player control via Resonance server.

Establishes a Bayeux/Comet long-poll connection to a Resonance (or LMS)
server and provides:

  1. Live server discovery via UDP TLV
  2. Bayeux handshake → connect → subscribe flow
  3. Subscription to serverstatus (player list) + player status (live updates)
  4. Interactive player commands: play, pause, stop, volume, skip, power
  5. Real-time status display with push updates

This is a standalone asyncio-based implementation that talks directly
to the Resonance /cometd endpoint — proving that the ported jivelite-py
protocol code is compatible with the real server.

Usage:
    python examples/live_player_control.py
    python examples/live_player_control.py --server 192.168.1.35
    python examples/live_player_control.py --server 192.168.1.35 --port 9000

Requirements:
    - Python 3.10+
    - A running Resonance or LMS server with at least one player

Copyright 2025
License: BSD-3-Clause
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import os
import socket
import struct
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Force UTF-8 output on Windows (avoids cp1252 UnicodeEncodeError)
# ---------------------------------------------------------------------------
_IS_TTY = hasattr(sys.stdout, "isatty") and sys.stdout.isatty()

if sys.platform == "win32":
    # Python 3.7+ supports reconfigure() — switch encoding in-place without
    # detaching or replacing the stream, so isatty() etc. keep working.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ---------------------------------------------------------------------------
# Ensure the project root is on sys.path
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_HERE)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


# ═══════════════════════════════════════════════════════════════════════════
# ANSI helpers
# ═══════════════════════════════════════════════════════════════════════════

BOLD = "\033[1m"
DIM = "\033[2m"
GREEN = "\033[32m"
CYAN = "\033[36m"
YELLOW = "\033[33m"
RED = "\033[31m"
MAGENTA = "\033[35m"
BLUE = "\033[34m"
WHITE = "\033[37m"
RESET = "\033[0m"
CLEAR_LINE = "\033[2K\r"
SAVE_CURSOR = "\033[s"
RESTORE_CURSOR = "\033[u"

if not _IS_TTY:
    BOLD = DIM = GREEN = CYAN = YELLOW = RED = MAGENTA = BLUE = WHITE = RESET = ""
    CLEAR_LINE = SAVE_CURSOR = RESTORE_CURSOR = ""


def _banner() -> None:
    print(
        f"\n{CYAN}{BOLD}"
        "╔══════════════════════════════════════════════════════════════╗\n"
        "║   Jivelite-py — Live Player Control                        ║\n"
        "║   Bayeux/Comet → Resonance/LMS                            ║\n"
        "╚══════════════════════════════════════════════════════════════╝"
        f"{RESET}\n"
    )


# ═══════════════════════════════════════════════════════════════════════════
# UDP TLV Discovery
# ═══════════════════════════════════════════════════════════════════════════

DISCOVERY_PORT = 3483


def _build_discovery_packet() -> bytes:
    try:
        from jive.applets.SlimDiscovery.SlimDiscoveryApplet import (
            _slim_discovery_source,
        )

        return _slim_discovery_source()
    except ImportError:
        return b"".join(
            [
                b"e",
                b"IPAD\x00",
                b"NAME\x00",
                b"JSON\x00",
                b"VERS\x00",
                b"UUID\x00",
                b"JVID\x06\x12\x34\x56\x78\x9a\xbc",
            ]
        )


def _parse_tlv(data: bytes) -> Dict[str, str]:
    try:
        from jive.applets.SlimDiscovery.SlimDiscoveryApplet import (
            _parse_tlv_response,
        )

        return _parse_tlv_response(data)
    except ImportError:
        result: Dict[str, str] = {}
        ptr = 1
        while ptr <= len(data) - 5:
            tag = data[ptr : ptr + 4].decode("ascii", errors="replace")
            length = data[ptr + 4]
            value = data[ptr + 5 : ptr + 5 + length]
            ptr += 5 + length
            if tag:
                result[tag] = value.decode("utf-8", errors="replace")
        return result


def discover_server(
    target: str = "255.255.255.255", timeout: float = 4.0
) -> Optional[Dict[str, str]]:
    """Discover a server via UDP broadcast. Returns TLV dict or None."""
    packet = _build_discovery_packet()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.settimeout(0.5)
    try:
        sock.bind(("", 0))
    except OSError:
        sock.bind(("0.0.0.0", 0))

    t0 = time.monotonic()
    burst = 0
    next_burst = t0

    try:
        while time.monotonic() - t0 < timeout:
            now = time.monotonic()
            if burst < 3 and now >= next_burst:
                burst += 1
                try:
                    sock.sendto(packet, (target, DISCOVERY_PORT))
                except OSError:
                    pass
                next_burst = now + 1.0
            try:
                data, addr = sock.recvfrom(4096)
                if data and data[0:1] == b"E":
                    tlv = _parse_tlv(data)
                    tlv["_addr"] = addr[0]
                    return tlv
            except socket.timeout:
                continue
            except OSError:
                continue
    finally:
        sock.close()
    return None


# ═══════════════════════════════════════════════════════════════════════════
# JSON-RPC helper (synchronous, for simple queries)
# ═══════════════════════════════════════════════════════════════════════════


def jsonrpc(
    ip: str, port: int, params: List[Any], timeout: float = 8.0
) -> Optional[Dict[str, Any]]:
    """Synchronous JSON-RPC call. Returns result dict or None."""
    url = f"http://{ip}:{port}/jsonrpc.js"
    payload = json.dumps(
        {
            "method": "slim.request",
            "params": params,
            "id": 1,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════════════════
# Bayeux/Comet Client (synchronous, threaded long-poll)
# ═══════════════════════════════════════════════════════════════════════════


class BayeuxClient:
    """
    A synchronous Bayeux/Comet client that uses HTTP long-polling
    to receive push events from a Resonance/LMS server.

    This implements the same protocol as jivelite-py's Comet class
    but using plain urllib for simplicity and reliability.

    Protocol flow:
        1. POST /cometd  [/meta/handshake]  → get clientId
        2. POST /cometd  [/meta/connect + /meta/subscribe]  → streaming
        3. POST /cometd  [/slim/subscribe]  → subscribe to channels
        4. Long-poll loop: POST /cometd [/meta/connect] → wait for events
    """

    def __init__(self, ip: str, port: int, name: str = "jivelite-py"):
        self.ip = ip
        self.port = port
        self.name = name
        self.base_url = f"http://{ip}:{port}/cometd"
        self.client_id: Optional[str] = None
        self.connected = False
        self._stop = False
        self._reqid = 1
        self._callbacks: Dict[str, Any] = {}  # channel → callback
        self._poll_thread: Optional[threading.Thread] = None
        self._event_queue: List[Dict[str, Any]] = []
        self._lock = threading.Lock()
        self._connect_timeout = 90  # long-poll timeout

    def _post(
        self, messages: List[Dict[str, Any]], timeout: float = 30.0
    ) -> Optional[List[Dict[str, Any]]]:
        """POST messages to /cometd and return decoded JSON response."""
        payload = json.dumps(messages).encode("utf-8")
        req = urllib.request.Request(
            self.base_url,
            data=payload,
            headers={
                "Content-Type": "text/json",
                "Accept": "application/json",
                "User-Agent": "jivelite-py/0.1.0",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8")
                # Handle chunked responses: may contain multiple JSON arrays
                # concatenated together
                return self._parse_response(raw)
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="replace")[:200]
            except Exception:
                pass
            print(f"  {RED}HTTP {e.code}: {body}{RESET}")
            return None
        except (urllib.error.URLError, OSError) as e:
            print(f"  {RED}Connection error: {e}{RESET}")
            return None
        except Exception as e:
            print(f"  {RED}Unexpected error: {e}{RESET}")
            return None

    @staticmethod
    def _parse_response(raw: str) -> List[Dict[str, Any]]:
        """Parse potentially concatenated JSON arrays from a response."""
        raw = raw.strip()
        if not raw:
            return []

        # Try parsing as a single JSON value first
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return parsed
            elif isinstance(parsed, dict):
                return [parsed]
            return []
        except json.JSONDecodeError:
            pass

        # Try parsing concatenated JSON arrays: [...][...][...]
        results: List[Dict[str, Any]] = []
        depth = 0
        start = 0
        for i, ch in enumerate(raw):
            if ch == "[":
                if depth == 0:
                    start = i
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    fragment = raw[start : i + 1]
                    try:
                        parsed = json.loads(fragment)
                        if isinstance(parsed, list):
                            results.extend(parsed)
                    except json.JSONDecodeError:
                        pass
        return results

    def _next_id(self) -> str:
        rid = str(self._reqid)
        self._reqid += 1
        return rid

    # ── Bayeux protocol steps ─────────────────────────────────────────

    def handshake(self) -> bool:
        """Step 1: /meta/handshake → obtain clientId."""
        print(f"  {DIM}Handshake → {self.base_url}{RESET}")
        resp = self._post(
            [
                {
                    "channel": "/meta/handshake",
                    "version": "1.0",
                    "supportedConnectionTypes": ["long-polling"],
                    "ext": {"rev": "jivelite-py/0.1.0"},
                    "id": self._next_id(),
                }
            ]
        )

        if not resp:
            print(f"  {RED}Handshake failed: no response{RESET}")
            return False

        for msg in resp:
            if msg.get("channel") == "/meta/handshake":
                if msg.get("successful"):
                    self.client_id = msg["clientId"]
                    print(f"  {GREEN}✓ clientId: {self.client_id}{RESET}")
                    return True
                else:
                    print(f"  {RED}Handshake rejected: {msg.get('error', '?')}{RESET}")
                    return False

        print(f"  {RED}Handshake: no /meta/handshake in response{RESET}")
        return False

    def connect_bayeux(self) -> bool:
        """Step 2: /meta/subscribe first, then /meta/connect.

        Resonance (like LMS) blocks the /meta/connect request until
        events arrive (long-poll).  So we must subscribe to channels
        *before* starting the long-poll loop, otherwise the connect
        blocks for the full timeout with no data.

        Flow:
          1. POST /meta/subscribe  → register our wildcard channel
          2. Mark ourselves as connected (the handshake already
             established the session; connect is just the long-poll)
        """
        if not self.client_id:
            return False

        # Step 2a: Subscribe to our wildcard channel
        print(f"  {DIM}Subscribe to /{self.client_id}/**{RESET}")
        resp = self._post(
            [
                {
                    "channel": "/meta/subscribe",
                    "clientId": self.client_id,
                    "subscription": f"/{self.client_id}/**",
                    "id": self._next_id(),
                },
            ],
            timeout=10.0,
        )

        ok_subscribe = False
        if resp:
            for msg in resp:
                ch = msg.get("channel", "")
                if ch == "/meta/subscribe" and msg.get("successful"):
                    ok_subscribe = True

        if ok_subscribe:
            print(f"  {GREEN}✓ Subscribed to /{self.client_id}/**{RESET}")
        else:
            print(f"  {YELLOW}⚠ Subscribe response unclear (continuing){RESET}")

        # Mark as connected — the session is valid from the handshake
        self.connected = True
        print(f"  {GREEN}✓ Session established{RESET}")
        return True

    def subscribe_slim(
        self,
        subscription: str,
        player_id: Optional[str],
        request: List[Any],
        callback: Any = None,
    ) -> Optional[str]:
        """
        Step 3: /slim/subscribe → subscribe to LMS-style events.

        The server will execute the request immediately and push the
        result on the response channel.  It will also re-execute the
        request on relevant player events (the LMS subscription model).

        The initial data push typically arrives on the *next*
        ``/meta/connect`` long-poll, not in the subscribe response
        itself.  We therefore call ``_initial_poll()`` after
        subscribing to pick up the first batch of data.

        Returns the response channel, or None on failure.
        """
        if not self.client_id:
            return None

        msg_id = self._next_id()
        # Build the response channel (LMS convention)
        sub_suffix = subscription.lstrip("/").replace("/", "_")
        if player_id:
            safe_pid = player_id.replace(":", "")
            response_channel = f"/{self.client_id}/slim/{sub_suffix}/{safe_pid}"
        else:
            response_channel = f"/{self.client_id}/slim/{sub_suffix}"

        req_data: Dict[str, Any] = {
            "request": [player_id or "", request],
            "response": response_channel,
        }

        print(f"  {DIM}Subscribe: {subscription} → {response_channel}{RESET}")

        # Register callback before the POST so any data in the
        # response is captured
        if callback:
            self._callbacks[response_channel] = callback

        resp = self._post(
            [
                {
                    "channel": "/slim/subscribe",
                    "clientId": self.client_id,
                    "id": msg_id,
                    "data": req_data,
                }
            ],
            timeout=15.0,
        )

        got_subscribe_ok = False
        got_initial_data = False
        if resp:
            for msg in resp:
                ch = msg.get("channel", "")
                if ch == "/slim/subscribe" and msg.get("successful"):
                    got_subscribe_ok = True
                    print(f"  {GREEN}✓ Slim subscribe OK{RESET}")
                # Check for initial data push on the response channel
                # (some servers include the first result in the same response)
                data = msg.get("data")
                if (
                    data
                    and callback
                    and (
                        ch == response_channel
                        or ch.startswith(f"/{self.client_id}/slim/")
                    )
                ):
                    callback(data)
                    got_initial_data = True

        if not got_subscribe_ok:
            print(
                f"  {YELLOW}⚠ Slim subscribe — no explicit OK (may still work){RESET}"
            )

        # The initial data push usually arrives on the next /meta/connect.
        # Do a single short poll to pick it up right away so the caller
        # has the data before returning.
        if not got_initial_data:
            self._initial_poll()

        return response_channel

    def _initial_poll(self) -> None:
        """Do one /meta/connect to receive the first data push after subscribing.

        Resonance (like LMS) queues the subscription result and delivers
        it on the next ``/meta/connect`` long-poll.  This helper issues
        one connect request with a short timeout so the caller gets the
        initial data synchronously before starting the background poll loop.
        """
        if not self.client_id:
            return

        resp = self._post(
            [
                {
                    "channel": "/meta/connect",
                    "clientId": self.client_id,
                    "connectionType": "long-polling",
                    "id": self._next_id(),
                }
            ],
            timeout=15.0,
        )

        if not resp:
            return

        for msg in resp:
            ch = msg.get("channel", "")
            data = msg.get("data")
            if data and self.client_id and ch.startswith(f"/{self.client_id}/"):
                # Dispatch to matching callback
                for pattern, cb in self._callbacks.items():
                    if ch == pattern or ch.startswith(pattern):
                        try:
                            cb(data)
                        except Exception as e:
                            print(f"  {RED}Callback error: {e}{RESET}")
                        break

    def slim_request(
        self,
        player_id: Optional[str],
        request: List[Any],
        callback: Any = None,
    ) -> bool:
        """
        Send a one-shot /slim/request (fire-and-forget or with callback).
        """
        if not self.client_id:
            return False

        msg_id = self._next_id()
        response_channel = f"/{self.client_id}/slim/request/{msg_id}"

        req_data: Dict[str, Any] = {
            "request": [player_id or "", request],
            "response": response_channel,
        }

        resp = self._post(
            [
                {
                    "channel": "/slim/request",
                    "clientId": self.client_id,
                    "id": msg_id,
                    "data": req_data,
                }
            ],
            timeout=15.0,
        )

        if resp and callback:
            for msg in resp:
                data = msg.get("data")
                if data:
                    callback(data)

        return resp is not None

    # ── Long-poll loop ────────────────────────────────────────────────

    def start_polling(self) -> None:
        """Start the long-poll loop in a background thread."""
        if self._poll_thread is not None:
            return
        self._stop = False
        self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._poll_thread.start()

    def stop_polling(self) -> None:
        """Signal the poll loop to stop."""
        self._stop = True
        if self._poll_thread:
            self._poll_thread.join(timeout=5)
            self._poll_thread = None

    def _poll_loop(self) -> None:
        """Background long-poll loop.

        Each iteration sends a /meta/connect request that the server
        holds open until events are available (or until a timeout,
        typically 60 s on the server side).  When the server responds
        we dispatch any data messages to registered callbacks and
        immediately start the next long-poll.
        """
        consecutive_failures = 0
        while not self._stop and self.connected:
            try:
                # The server blocks this request for up to ~60 s.
                # We set our client timeout a bit higher so we don't
                # abort before the server responds.
                resp = self._post(
                    [
                        {
                            "channel": "/meta/connect",
                            "clientId": self.client_id,
                            "connectionType": "long-polling",
                            "id": self._next_id(),
                        }
                    ],
                    timeout=self._connect_timeout,
                )

                if resp is None:
                    consecutive_failures += 1
                    if consecutive_failures > 5:
                        print(f"\n  {RED}Too many poll failures, stopping{RESET}")
                        self.connected = False
                        break
                    backoff = min(2**consecutive_failures, 30)
                    time.sleep(backoff)
                    continue

                consecutive_failures = 0

                for msg in resp:
                    ch = msg.get("channel", "")
                    data = msg.get("data")

                    # Dispatch to registered callbacks by matching
                    # the channel prefix.
                    if data:
                        matched = False
                        with self._lock:
                            for pattern, cb in self._callbacks.items():
                                # Exact match or prefix match
                                # e.g. pattern="/abc123/slim/slim_serverstatus"
                                #      ch     ="/abc123/slim/slim_serverstatus"
                                # or   pattern="/abc123/slim/slim_playerstatus/..."
                                #      ch starts with the prefix
                                if ch == pattern or ch.startswith(pattern):
                                    self._event_queue.append(
                                        {"channel": ch, "data": data, "callback": cb}
                                    )
                                    matched = True
                                    break

                            # Fallback: match by common client-id prefix
                            if (
                                not matched
                                and self.client_id
                                and ch.startswith(f"/{self.client_id}/")
                            ):
                                # Try to find a callback whose pattern
                                # shares the most path segments
                                best_cb = None
                                best_len = 0
                                for pattern, cb in self._callbacks.items():
                                    # Find longest common prefix
                                    common = os.path.commonprefix([ch, pattern])
                                    if len(common) > best_len:
                                        best_len = len(common)
                                        best_cb = cb
                                if best_cb is not None:
                                    self._event_queue.append(
                                        {
                                            "channel": ch,
                                            "data": data,
                                            "callback": best_cb,
                                        }
                                    )

                    # Handle /meta/connect advice
                    if ch == "/meta/connect":
                        advice = msg.get("advice", {})
                        if advice.get("reconnect") == "none":
                            print(f"\n  {YELLOW}Server advised no reconnect{RESET}")
                            self.connected = False
                            break

            except Exception as e:
                if not self._stop:
                    consecutive_failures += 1
                    time.sleep(1)

    def process_events(self) -> int:
        """Process queued events on the main thread. Returns count processed."""
        with self._lock:
            events = list(self._event_queue)
            self._event_queue.clear()

        for evt in events:
            cb = evt.get("callback")
            if cb:
                try:
                    cb(evt["data"])
                except Exception as e:
                    print(f"  {RED}Callback error: {e}{RESET}")

        return len(events)

    def disconnect(self) -> None:
        """Disconnect from the server."""
        self.stop_polling()
        if self.client_id and self.connected:
            try:
                self._post(
                    [
                        {
                            "channel": "/meta/disconnect",
                            "clientId": self.client_id,
                            "id": self._next_id(),
                        }
                    ],
                    timeout=3,
                )
            except Exception:
                pass
        self.connected = False
        self.client_id = None


# ═══════════════════════════════════════════════════════════════════════════
# Player state tracker
# ═══════════════════════════════════════════════════════════════════════════


class PlayerState:
    """Tracks the current state of a player from serverstatus + status pushes."""

    def __init__(self):
        self.player_id: Optional[str] = None
        self.name: str = "?"
        self.model: str = "?"
        self.connected: bool = False
        self.power: bool = False
        self.mode: str = "stop"  # play, pause, stop
        self.volume: int = 0
        self.track: Optional[str] = None
        self.artist: Optional[str] = None
        self.album: Optional[str] = None
        self.artwork_url: Optional[str] = None
        self.duration: float = 0.0
        self.elapsed: float = 0.0
        self.playlist_size: int = 0
        self.playlist_index: int = 0
        self.shuffle: int = 0
        self.repeat: int = 0
        self.remote: bool = False
        self.last_update: float = 0.0

    def update_from_serverstatus(self, info: Dict[str, Any]) -> None:
        """Update from a serverstatus players_loop entry."""
        self.player_id = info.get("playerid", self.player_id)
        self.name = info.get("name", self.name)
        self.model = info.get("model", self.model)
        self.connected = bool(info.get("connected", 0))
        self.power = bool(info.get("power", 0))
        self.last_update = time.time()

    def update_from_status(self, data: Dict[str, Any]) -> None:
        """Update from a player status push (full status blob)."""
        self.mode = data.get("mode", self.mode)
        self.volume = int(data.get("mixer volume", self.volume))
        self.duration = float(data.get("duration", self.duration) or 0)
        self.elapsed = float(data.get("time", self.elapsed) or 0)
        self.playlist_size = int(data.get("playlist_tracks", self.playlist_size) or 0)
        self.playlist_index = int(
            data.get("playlist_cur_index", self.playlist_index) or 0
        )
        self.shuffle = int(data.get("playlist shuffle", self.shuffle) or 0)
        self.repeat = int(data.get("playlist repeat", self.repeat) or 0)
        self.remote = bool(data.get("remote", 0))
        self.power = bool(data.get("power", self.power))

        if "player_name" in data:
            self.name = data["player_name"]
        if "player_connected" in data:
            self.connected = bool(data["player_connected"])

        # Track info from item_loop
        item_loop = data.get("playlist_loop") or data.get("item_loop")
        if item_loop and len(item_loop) > 0:
            item = item_loop[0]
            self.track = item.get("title") or item.get("track") or item.get("text")
            self.artist = item.get("artist")
            self.album = item.get("album")
            artwork_id = (
                item.get("artwork_track_id") or item.get("id") or item.get("icon-id")
            )
            if artwork_id:
                self.artwork_url = str(artwork_id)
        elif data.get("current_title"):
            self.track = data["current_title"]

        self.last_update = time.time()

    def format_status_line(self, server_ip: str = "", server_port: int = 9000) -> str:
        """Format a single-line status display."""
        # Mode icon
        if self.mode == "play":
            mode_icon = f"{GREEN}▶{RESET}"
        elif self.mode == "pause":
            mode_icon = f"{YELLOW}⏸{RESET}"
        else:
            mode_icon = f"{DIM}⏹{RESET}"

        # Power
        pwr = f"{GREEN}ON{RESET}" if self.power else f"{RED}OFF{RESET}"

        # Volume bar
        vol_bar = self._volume_bar(self.volume)

        # Track info
        track_info = ""
        if self.track:
            track_info = f"  {WHITE}{BOLD}{self.track}{RESET}"
            if self.artist:
                track_info += f" — {CYAN}{self.artist}{RESET}"
            if self.album:
                track_info += f" ({DIM}{self.album}{RESET})"

        # Time
        time_str = ""
        if self.duration > 0:
            elapsed_fmt = self._fmt_time(self.elapsed)
            duration_fmt = self._fmt_time(self.duration)
            pct = (
                min(100, self.elapsed / self.duration * 100) if self.duration > 0 else 0
            )
            time_str = f"  {DIM}{elapsed_fmt}/{duration_fmt} ({pct:.0f}%){RESET}"

        # Playlist
        pl_str = ""
        if self.playlist_size > 0:
            pl_str = f"  {DIM}[{self.playlist_index + 1}/{self.playlist_size}]{RESET}"

        return (
            f"  {mode_icon} {pwr}  "
            f"{BOLD}{self.name}{RESET} ({DIM}{self.model}{RESET})"
            f"  vol:{vol_bar}"
            f"{track_info}{time_str}{pl_str}"
        )

    @staticmethod
    def _volume_bar(vol: int, width: int = 10) -> str:
        abs_vol = abs(vol)
        filled = int(abs_vol / 100 * width)
        empty = width - filled
        muted = vol < 0
        color = RED if muted else GREEN
        bar = f"{color}{'█' * filled}{DIM}{'░' * empty}{RESET}"
        label = f"{abs_vol}%" if not muted else f"{abs_vol}%🔇"
        return f"[{bar}] {label}"

    @staticmethod
    def _fmt_time(seconds: float) -> str:
        s = int(seconds)
        m, sec = divmod(s, 60)
        h, m = divmod(m, 60)
        if h > 0:
            return f"{h}:{m:02d}:{sec:02d}"
        return f"{m}:{sec:02d}"


# ═══════════════════════════════════════════════════════════════════════════
# Interactive command handler
# ═══════════════════════════════════════════════════════════════════════════


class PlayerController:
    """
    Interactive controller that sends commands to the server
    via JSON-RPC and receives live status via Bayeux/Comet.
    """

    def __init__(self, ip: str, port: int):
        self.ip = ip
        self.port = port
        self.bayeux: Optional[BayeuxClient] = None
        self.players: Dict[str, PlayerState] = {}
        self.current_player: Optional[str] = None  # player_id
        self.server_version: str = "?"
        self.server_name: str = "?"
        self._running = False
        self._status_response_channel: Optional[str] = None
        self._serverstatus_channel: Optional[str] = None

    # ── Commands ──────────────────────────────────────────────────────

    def send_command(self, player_id: str, cmd: List[Any]) -> bool:
        """Send a command to a player via JSON-RPC."""
        result = jsonrpc(self.ip, self.port, [player_id, cmd])
        return result is not None

    def cmd_play(self) -> None:
        if not self.current_player:
            print(f"  {YELLOW}No player selected{RESET}")
            return
        print(f"  {GREEN}▶ Play{RESET}")
        self.send_command(self.current_player, ["play"])

    def cmd_pause(self) -> None:
        if not self.current_player:
            return
        ps = self.players.get(self.current_player)
        if ps and ps.mode == "pause":
            print(f"  {GREEN}▶ Unpause{RESET}")
            self.send_command(self.current_player, ["pause", "0"])
        else:
            print(f"  {YELLOW}⏸ Pause{RESET}")
            self.send_command(self.current_player, ["pause", "1"])

    def cmd_stop(self) -> None:
        if not self.current_player:
            return
        print(f"  {RED}⏹ Stop{RESET}")
        self.send_command(self.current_player, ["stop"])

    def cmd_next(self) -> None:
        if not self.current_player:
            return
        print(f"  {CYAN}⏭ Next{RESET}")
        self.send_command(self.current_player, ["playlist", "index", "+1"])

    def cmd_prev(self) -> None:
        if not self.current_player:
            return
        print(f"  {CYAN}⏮ Previous{RESET}")
        self.send_command(self.current_player, ["playlist", "index", "-1"])

    def cmd_volume_up(self, step: int = 5) -> None:
        if not self.current_player:
            return
        ps = self.players.get(self.current_player)
        if ps:
            new_vol = min(100, abs(ps.volume) + step)
            print(f"  {GREEN}🔊 Volume → {new_vol}%{RESET}")
            self.send_command(self.current_player, ["mixer", "volume", str(new_vol)])

    def cmd_volume_down(self, step: int = 5) -> None:
        if not self.current_player:
            return
        ps = self.players.get(self.current_player)
        if ps:
            new_vol = max(0, abs(ps.volume) - step)
            print(f"  {YELLOW}🔉 Volume → {new_vol}%{RESET}")
            self.send_command(self.current_player, ["mixer", "volume", str(new_vol)])

    def cmd_volume_set(self, vol: int) -> None:
        if not self.current_player:
            return
        vol = max(0, min(100, vol))
        print(f"  {CYAN}🔊 Volume → {vol}%{RESET}")
        self.send_command(self.current_player, ["mixer", "volume", str(vol)])

    def cmd_power_toggle(self) -> None:
        if not self.current_player:
            return
        ps = self.players.get(self.current_player)
        if ps:
            new_power = "0" if ps.power else "1"
            label = "OFF" if ps.power else "ON"
            color = RED if ps.power else GREEN
            print(f"  {color}⏻ Power {label}{RESET}")
            self.send_command(self.current_player, ["power", new_power])

    def cmd_shuffle(self) -> None:
        if not self.current_player:
            return
        ps = self.players.get(self.current_player)
        if ps:
            new_shuffle = (ps.shuffle + 1) % 3
            labels = ["off", "songs", "albums"]
            print(f"  {MAGENTA}🔀 Shuffle → {labels[new_shuffle]}{RESET}")
            self.send_command(
                self.current_player, ["playlist", "shuffle", str(new_shuffle)]
            )

    def cmd_repeat(self) -> None:
        if not self.current_player:
            return
        ps = self.players.get(self.current_player)
        if ps:
            new_repeat = (ps.repeat + 1) % 3
            labels = ["off", "song", "playlist"]
            print(f"  {MAGENTA}🔁 Repeat → {labels[new_repeat]}{RESET}")
            self.send_command(
                self.current_player, ["playlist", "repeat", str(new_repeat)]
            )

    def cmd_select_player(self, idx: int) -> None:
        pids = list(self.players.keys())
        if 0 <= idx < len(pids):
            self.current_player = pids[idx]
            ps = self.players[self.current_player]
            print(f"  {GREEN}✓ Selected: {ps.name} [{self.current_player}]{RESET}")
            # Re-subscribe to the new player's status
            self._subscribe_player_status()
        else:
            print(f"  {RED}Invalid player index{RESET}")

    def cmd_status(self) -> None:
        """Print current status of all players."""
        print()
        print(
            f"  {BOLD}Server:{RESET} {CYAN}{self.server_name}{RESET} v{self.server_version} @ {self.ip}:{self.port}"
        )
        print()

        if not self.players:
            print(f"  {DIM}No players found{RESET}")
            return

        for i, (pid, ps) in enumerate(self.players.items()):
            marker = f"{GREEN}→{RESET}" if pid == self.current_player else " "
            idx = f"{DIM}[{i}]{RESET}"
            print(f"  {marker} {idx} {ps.format_status_line(self.ip, self.port)}")

        print()

    def cmd_query_status(self) -> None:
        """Force a fresh status query via JSON-RPC."""
        if not self.current_player:
            return
        result = jsonrpc(
            self.ip,
            self.port,
            [
                self.current_player,
                ["status", "-", 10, "tags:aAlcdegiJKlNoqrStuwxy"],
            ],
        )
        if result and "result" in result:
            ps = self.players.get(self.current_player)
            if ps:
                ps.update_from_status(result["result"])
                self.cmd_status()

    # ── Bayeux callbacks ──────────────────────────────────────────────

    def _on_serverstatus(self, data: Dict[str, Any]) -> None:
        """Handle serverstatus subscription push."""
        self.server_version = str(data.get("version", self.server_version))

        players_loop = data.get("players_loop", [])
        seen: set = set()

        for info in players_loop:
            pid = info.get("playerid", "")
            if not pid:
                continue
            seen.add(pid)

            if pid not in self.players:
                self.players[pid] = PlayerState()
                print(f"  {GREEN}+ New player: {info.get('name', '?')} [{pid}]{RESET}")

            self.players[pid].update_from_serverstatus(info)

            # Auto-select first player
            if self.current_player is None and info.get("connected"):
                self.current_player = pid
                print(f"  {GREEN}✓ Auto-selected: {info.get('name', '?')}{RESET}")

        # Remove vanished players
        for pid in list(self.players.keys()):
            if pid not in seen:
                print(
                    f"  {YELLOW}- Player gone: {self.players[pid].name} [{pid}]{RESET}"
                )
                del self.players[pid]
                if self.current_player == pid:
                    self.current_player = None

    def _on_player_status(self, data: Dict[str, Any]) -> None:
        """Handle player status subscription push."""
        if not self.current_player:
            return
        ps = self.players.get(self.current_player)
        if ps:
            old_mode = ps.mode
            old_track = ps.track
            ps.update_from_status(data)

            # Print notable changes
            if ps.mode != old_mode:
                mode_labels = {
                    "play": f"{GREEN}▶ Playing{RESET}",
                    "pause": f"{YELLOW}⏸ Paused{RESET}",
                    "stop": f"{DIM}⏹ Stopped{RESET}",
                }
                print(f"\n  {mode_labels.get(ps.mode, ps.mode)}")

            if ps.track and ps.track != old_track:
                track_line = f"  {WHITE}{BOLD}{ps.track}{RESET}"
                if ps.artist:
                    track_line += f" — {CYAN}{ps.artist}{RESET}"
                if ps.album:
                    track_line += f" ({DIM}{ps.album}{RESET})"
                print(f"\n  🎵 Now playing:")
                print(f"  {track_line}")

    def _subscribe_player_status(self) -> None:
        """Subscribe to the current player's status channel."""
        if not self.bayeux or not self.current_player:
            return

        print(f"  {DIM}Subscribing to player status for {self.current_player}{RESET}")
        self._status_response_channel = self.bayeux.subscribe_slim(
            "/slim/playerstatus",
            self.current_player,
            [
                "status",
                "-",
                10,
                "menu:menu",
                "useContextMenu:1",
                "subscribe:30",
                "tags:aAlcdegiJKlNoqrStuwxy",
            ],
            callback=self._on_player_status,
        )

    # ── Main flow ─────────────────────────────────────────────────────

    def connect(self) -> bool:
        """Connect to the server: discover, handshake, subscribe."""

        # Step 1: Quick JSON-RPC check
        print(f"  {DIM}Checking server at {self.ip}:{self.port}…{RESET}")
        result = jsonrpc(self.ip, self.port, ["", ["serverstatus", 0, 50]])
        if not result or "result" not in result:
            print(f"  {RED}Server not responding to JSON-RPC{RESET}")
            return False

        sr = result["result"]
        self.server_version = sr.get("version", "?")
        self.server_name = sr.get("_name", f"Server@{self.ip}")

        # Try to get server name from the connection
        if self.server_name.startswith("Server@"):
            # Try discovery
            tlv = discover_server(self.ip, timeout=2.0)
            if tlv and "NAME" in tlv:
                self.server_name = tlv["NAME"]

        print(f"  {GREEN}✓ {self.server_name} v{self.server_version}{RESET}")

        # Process initial player list
        self._on_serverstatus(sr)

        # Step 2: Bayeux handshake
        print(f"\n  {BOLD}Establishing Comet connection…{RESET}")
        self.bayeux = BayeuxClient(self.ip, self.port)

        if not self.bayeux.handshake():
            return False

        if not self.bayeux.connect_bayeux():
            return False

        # Step 3: Subscribe to serverstatus
        self._serverstatus_channel = self.bayeux.subscribe_slim(
            "/slim/serverstatus",
            None,
            ["serverstatus", 0, 50, "subscribe:60"],
            callback=self._on_serverstatus,
        )

        # Step 4: Subscribe to current player's status
        if self.current_player:
            self._subscribe_player_status()

        # Step 5: Start long-poll loop
        print(f"\n  {GREEN}{BOLD}✓ Live connection established{RESET}")
        self.bayeux.start_polling()

        return True

    def run_interactive(self) -> None:
        """Run the interactive command loop."""
        self._running = True
        self._print_help()
        self.cmd_status()

        while self._running:
            try:
                # Process any pending Bayeux events
                if self.bayeux:
                    self.bayeux.process_events()

                # Check if connection is still alive
                if self.bayeux and not self.bayeux.connected:
                    print(f"\n  {RED}Connection lost. Attempting reconnect…{RESET}")
                    if not self._reconnect():
                        print(f"  {RED}Reconnect failed. Exiting.{RESET}")
                        break

                # Non-blocking input
                line = self._read_input()
                if line is None:
                    time.sleep(0.1)
                    continue

                self._handle_command(line.strip())

            except KeyboardInterrupt:
                print(f"\n  {YELLOW}Interrupted{RESET}")
                self._running = False
            except EOFError:
                self._running = False

    def _reconnect(self) -> bool:
        """Attempt to reconnect."""
        if self.bayeux:
            self.bayeux.stop_polling()

        for attempt in range(3):
            print(f"  {DIM}Reconnect attempt {attempt + 1}/3…{RESET}")
            time.sleep(2)
            self.bayeux = BayeuxClient(self.ip, self.port)
            if self.bayeux.handshake() and self.bayeux.connect_bayeux():
                self.bayeux.subscribe_slim(
                    "/slim/serverstatus",
                    None,
                    ["serverstatus", 0, 50, "subscribe:60"],
                    callback=self._on_serverstatus,
                )
                if self.current_player:
                    self._subscribe_player_status()
                self.bayeux.start_polling()
                print(f"  {GREEN}✓ Reconnected{RESET}")
                return True

        return False

    # Detect platform once at class level — on Windows, select() does not
    # work on sys.stdin, so we use msvcrt for non-blocking keyboard input.
    _USE_MSVCRT: bool = sys.platform == "win32"

    def _read_input(self) -> Optional[str]:
        """Read input with a timeout (non-blocking on supported platforms)."""
        if self._USE_MSVCRT:
            return self._read_input_windows()
        return self._read_input_unix()

    def _read_input_unix(self) -> Optional[str]:
        """Unix non-blocking input via select()."""
        import select as _sel

        try:
            ready, _, _ = _sel.select([sys.stdin], [], [], 0.1)
            if ready:
                return sys.stdin.readline()
        except (OSError, ValueError, TypeError):
            pass
        return None

    def _read_input_windows(self) -> Optional[str]:
        """Windows-compatible non-blocking input using msvcrt."""
        import msvcrt  # type: ignore[import-not-found]

        if not msvcrt.kbhit():
            time.sleep(0.1)
            return None

        # Accumulate characters until Enter is pressed
        chars: list[str] = []
        while True:
            ch = msvcrt.getwch()
            if ch in ("\r", "\n"):
                # Echo the newline
                sys.stdout.write("\n")
                sys.stdout.flush()
                break
            elif ch == "\x08":  # Backspace
                if chars:
                    chars.pop()
                    # Erase the character on screen
                    sys.stdout.write("\x08 \x08")
                    sys.stdout.flush()
            elif ch == "\x03":  # Ctrl+C
                raise KeyboardInterrupt
            elif ch == "\x1a":  # Ctrl+Z (EOF on Windows)
                raise EOFError
            elif ch in ("\x00", "\xe0"):
                # Extended key (arrow keys, etc.) — consume second byte, ignore
                msvcrt.getwch()
            else:
                chars.append(ch)
                sys.stdout.write(ch)
                sys.stdout.flush()

        if not chars:
            return None
        return "".join(chars)

    def _handle_command(self, cmd: str) -> None:
        """Handle a user command."""
        if not cmd:
            return

        parts = cmd.lower().split()
        c = parts[0]

        if c in ("q", "quit", "exit"):
            self._running = False
        elif c in ("h", "help", "?"):
            self._print_help()
        elif c in ("s", "status"):
            self.cmd_query_status()
        elif c in ("i", "info"):
            self.cmd_status()
        elif c in ("p", "play"):
            self.cmd_play()
        elif c in ("pa", "pause"):
            self.cmd_pause()
        elif c == "stop":
            self.cmd_stop()
        elif c in ("n", "next", ">", ">>"):
            self.cmd_next()
        elif c in ("b", "prev", "back", "<", "<<"):
            self.cmd_prev()
        elif c in ("+", "up"):
            step = int(parts[1]) if len(parts) > 1 else 5
            self.cmd_volume_up(step)
        elif c in ("-", "down"):
            step = int(parts[1]) if len(parts) > 1 else 5
            self.cmd_volume_down(step)
        elif c in ("v", "vol", "volume"):
            if len(parts) > 1:
                try:
                    self.cmd_volume_set(int(parts[1]))
                except ValueError:
                    print(f"  {RED}Usage: vol <0-100>{RESET}")
            else:
                ps = self.players.get(self.current_player or "")
                if ps:
                    print(f"  Volume: {ps._volume_bar(ps.volume, 20)}")
        elif c in ("pw", "power"):
            self.cmd_power_toggle()
        elif c in ("sh", "shuffle"):
            self.cmd_shuffle()
        elif c in ("r", "repeat"):
            self.cmd_repeat()
        elif c in ("pl", "player", "select"):
            if len(parts) > 1:
                try:
                    self.cmd_select_player(int(parts[1]))
                except ValueError:
                    print(f"  {RED}Usage: player <index>{RESET}")
            else:
                self.cmd_status()
        elif c in ("random", "randomplay"):
            genre = parts[1] if len(parts) > 1 else "tracks"
            print(f"  {MAGENTA}🎲 Random play: {genre}{RESET}")
            self.send_command(self.current_player or "", ["randomplay", genre])
        elif c.startswith("playlist"):
            if len(parts) > 1 and parts[1] == "clear":
                print(f"  {RED}Clearing playlist{RESET}")
                self.send_command(self.current_player or "", ["playlist", "clear"])
        elif c == "raw":
            # Send raw command
            if len(parts) > 1:
                raw_cmd = parts[1:]
                print(f"  {DIM}Sending: {raw_cmd}{RESET}")
                self.send_command(self.current_player or "", raw_cmd)
        else:
            print(f"  {YELLOW}Unknown command: {cmd}{RESET}")
            print(f"  {DIM}Type 'help' for available commands{RESET}")

    @staticmethod
    def _print_help() -> None:
        print(f"""
  {BOLD}Commands:{RESET}
    {CYAN}p{RESET} / play          Start playback
    {CYAN}pa{RESET} / pause        Toggle pause
    {CYAN}stop{RESET}              Stop playback
    {CYAN}n{RESET} / next          Next track
    {CYAN}b{RESET} / prev          Previous track
    {CYAN}+{RESET} / up [N]        Volume up (default: 5)
    {CYAN}-{RESET} / down [N]      Volume down (default: 5)
    {CYAN}v{RESET} / vol <0-100>   Set volume
    {CYAN}pw{RESET} / power        Toggle power
    {CYAN}sh{RESET} / shuffle      Cycle shuffle mode
    {CYAN}r{RESET} / repeat        Cycle repeat mode
    {CYAN}pl{RESET} / player <N>   Select player by index
    {CYAN}random{RESET} [genre]    Start random play
    {CYAN}s{RESET} / status        Query fresh status
    {CYAN}i{RESET} / info          Show current state
    {CYAN}raw{RESET} <cmd ...>     Send raw command
    {CYAN}h{RESET} / help          Show this help
    {CYAN}q{RESET} / quit          Exit
""")

    def shutdown(self) -> None:
        """Clean shutdown."""
        print(f"\n  {DIM}Disconnecting…{RESET}")
        if self.bayeux:
            self.bayeux.disconnect()
        print(f"  {GREEN}✓ Done{RESET}")


# ═══════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Live player control via Bayeux/Comet connection to Resonance/LMS",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
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

    _banner()

    # ── Step 1: Find server ───────────────────────────────────────────
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

    # ── Step 2: Connect ───────────────────────────────────────────────
    print(f"\n  {BOLD}Connecting to {server_ip}:{server_port}…{RESET}")
    controller = PlayerController(server_ip, server_port)

    if not controller.connect():
        print(f"\n  {RED}Failed to connect{RESET}")
        sys.exit(1)

    # ── Step 3: Interactive loop ──────────────────────────────────────
    try:
        controller.run_interactive()
    except Exception as e:
        print(f"\n  {RED}Error: {e}{RESET}")
        import traceback

        traceback.print_exc()
    finally:
        controller.shutdown()


if __name__ == "__main__":
    main()
