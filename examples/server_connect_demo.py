#!/usr/bin/env python3
"""
server_connect_demo.py — End-to-end integration demo.

Demonstrates the complete flow:

    1. UDP TLV Discovery  → find servers on the local network
    2. ChooseMusicSource   → select a server from the discovered list
    3. Connecting Popup    → show "connecting to …" state
    4. Player Connection   → connect a (mock) player to the server
    5. JSON-RPC Query      → query the server for status, players, library

This script exercises the ported applet infrastructure end-to-end
without requiring a full pygame UI.  It can optionally start the
Resonance server if it's available next to the project.

Usage:
    python examples/server_connect_demo.py
    python examples/server_connect_demo.py --address 192.168.1.35
    python examples/server_connect_demo.py --start-resonance
    python examples/server_connect_demo.py --skip-discovery --server-ip 192.168.1.35

Requirements:
    - No pygame needed (headless mode)
    - Network access for UDP broadcast + HTTP JSON-RPC

Copyright 2025
License: BSD-3-Clause
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

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
RESET = "\033[0m"

# Disable colours when output is not a terminal
if not sys.stdout.isatty():
    BOLD = DIM = GREEN = CYAN = YELLOW = RED = MAGENTA = RESET = ""


def _banner() -> None:
    print(
        f"\n{CYAN}{BOLD}"
        "╔══════════════════════════════════════════════════════════════╗\n"
        "║   Jivelite-py — Server Connect Demo (End-to-End)           ║\n"
        "║   Discovery → Select → Connect → Query                    ║\n"
        "╚══════════════════════════════════════════════════════════════╝"
        f"{RESET}\n"
    )


def _step(n: int, title: str) -> None:
    print(
        f"\n{MAGENTA}{BOLD}── Step {n}: {title} {'─' * max(1, 48 - len(title))}{RESET}\n"
    )


def _ok(msg: str) -> None:
    print(f"  {GREEN}✓{RESET} {msg}")


def _warn(msg: str) -> None:
    print(f"  {YELLOW}⚠{RESET} {msg}")


def _fail(msg: str) -> None:
    print(f"  {RED}✗{RESET} {msg}")


def _info(msg: str) -> None:
    print(f"  {DIM}{msg}{RESET}")


# ═══════════════════════════════════════════════════════════════════════════
# Step 1 — UDP TLV Discovery
# ═══════════════════════════════════════════════════════════════════════════

DISCOVERY_PORT = 3483
RECV_BUFFER = 4096


class DiscoveredServer:
    """Lightweight container for a discovered server."""

    def __init__(self, address: str, port: int, tlv: Dict[str, str], rtt_ms: float):
        self.address = address
        self.port = port
        self.tlv = tlv
        self.rtt_ms = rtt_ms

    @property
    def name(self) -> str:
        return self.tlv.get("NAME", "Unknown")

    @property
    def ip(self) -> str:
        return self.tlv.get("IPAD", self.address)

    @property
    def json_port(self) -> int:
        try:
            return int(self.tlv.get("JSON", "9000"))
        except (ValueError, TypeError):
            return 9000

    @property
    def version(self) -> str:
        return self.tlv.get("VERS", "?")

    @property
    def uuid(self) -> str:
        return self.tlv.get("UUID", "?")

    def __repr__(self) -> str:
        return f"{self.name} @ {self.ip}:{self.json_port} (v{self.version})"


def _build_discovery_packet() -> bytes:
    """Build TLV discovery request using jivelite-py's own module."""
    try:
        from jive.applets.SlimDiscovery.SlimDiscoveryApplet import (
            _slim_discovery_source,
        )

        return _slim_discovery_source()
    except ImportError:
        # Fallback: build manually
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
    """Parse TLV response using jivelite-py's own module."""
    try:
        from jive.applets.SlimDiscovery.SlimDiscoveryApplet import (
            _parse_tlv_response,
        )

        return _parse_tlv_response(data)
    except ImportError:
        # Fallback: parse manually
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


def discover_servers(
    target: str = "255.255.255.255",
    timeout: float = 5.0,
    bursts: int = 3,
) -> List[DiscoveredServer]:
    """Send UDP discovery broadcasts and collect responses."""
    results: Dict[str, DiscoveredServer] = {}
    packet = _build_discovery_packet()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.settimeout(0.5)

    try:
        sock.bind(("", 0))
    except OSError:
        sock.bind(("0.0.0.0", 0))

    _info(f"Bound to local port {sock.getsockname()[1]}")
    _info(f"Target: {target}:{DISCOVERY_PORT}, timeout: {timeout}s, bursts: {bursts}")

    t0 = time.monotonic()
    burst_n = 0
    next_burst = t0

    try:
        while time.monotonic() - t0 < timeout:
            now = time.monotonic()

            if burst_n < bursts and now >= next_burst:
                burst_n += 1
                _info(f"Sending discovery burst {burst_n}/{bursts}")
                try:
                    sock.sendto(packet, (target, DISCOVERY_PORT))
                except OSError as exc:
                    _warn(f"Send failed: {exc}")
                next_burst = now + 1.0

            try:
                data, addr = sock.recvfrom(RECV_BUFFER)
                rtt = (time.monotonic() - t0) * 1000

                if data and data[0:1] == b"E":
                    tlv = _parse_tlv(data)
                    key = f"{addr[0]}:{addr[1]}"
                    if key not in results:
                        server = DiscoveredServer(addr[0], addr[1], tlv, rtt)
                        results[key] = server
                        _ok(f"Found: {server}")
                        for tag, val in sorted(tlv.items()):
                            _info(f"  {tag}: {val}")
            except socket.timeout:
                continue
            except OSError:
                continue
    finally:
        sock.close()

    return list(results.values())


# ═══════════════════════════════════════════════════════════════════════════
# Step 2 — ChooseMusicSource: server selection
# ═══════════════════════════════════════════════════════════════════════════


class MockPlayer:
    """A mock player for the connection flow."""

    def __init__(
        self,
        player_id: str = "00:04:20:de:mo:01",
        name: str = "DemoPlayer",
    ):
        self._id = player_id
        self._name = name
        self._server: Any = None
        self._connected = False
        self._connection_failed = False

    # --- Player interface (used by ChooseMusicSourceApplet) ---

    def get_id(self) -> str:
        return self._id

    getId = get_id

    def get_name(self) -> str:
        return self._name

    getName = get_name

    def get_model(self) -> str:
        return "squeezeplay"

    getModel = get_model

    def is_local(self) -> bool:
        return True

    isLocal = is_local

    def is_connected(self) -> bool:
        return self._connected

    isConnected = is_connected

    def get_slim_server(self) -> Any:
        return self._server

    getSlimServer = get_slim_server

    def get_play_mode(self) -> str:
        return "stop"

    getPlayMode = get_play_mode

    def get_playlist_size(self) -> int:
        return 0

    getPlaylistSize = get_playlist_size

    def has_connection_failed(self) -> bool:
        return self._connection_failed

    hasConnectionFailed = has_connection_failed

    def connect_to_server(self, server: Any) -> None:
        """Simulate connecting to a server."""
        self._server = server
        self._connected = True
        _ok(f"Player '{self._name}' connected to server")

    connectToServer = connect_to_server

    def disconnect_from_server(self) -> None:
        self._server = None
        self._connected = False

    disconnectFromServer = disconnect_from_server

    def __repr__(self) -> str:
        return f"MockPlayer({self._name!r}, connected={self._connected})"


class MockServer:
    """A mock server created from a discovery result."""

    def __init__(self, disc: DiscoveredServer):
        self._disc = disc
        self._name = disc.name
        self._ip = disc.ip
        self._port = disc.json_port
        self._version = disc.version
        self._uuid = disc.uuid
        self._connected = False

    def get_name(self) -> str:
        return self._name

    getName = get_name

    def get_ip_port(self) -> str:
        return f"{self._ip}:{self._port}"

    getIpPort = get_ip_port

    def get_version(self) -> Optional[str]:
        return self._version

    getVersion = get_version

    def is_compatible(self) -> bool:
        return True

    isCompatible = is_compatible

    def is_squeeze_network(self) -> bool:
        return False

    isSqueezeNetwork = is_squeeze_network

    def is_password_protected(self) -> bool:
        return False

    isPasswordProtected = is_password_protected

    def is_connected(self) -> bool:
        return self._connected

    isConnected = is_connected

    @property
    def upgrade_force(self) -> bool:
        return False

    upgradeForce = upgrade_force

    def __repr__(self) -> str:
        return f"MockServer({self._name!r}, {self.get_ip_port()})"


def select_server_from_list(
    servers: List[DiscoveredServer],
) -> Optional[DiscoveredServer]:
    """Interactive server selection when multiple servers are found."""
    if not servers:
        return None

    if len(servers) == 1:
        _ok(f"Auto-selecting only server: {servers[0]}")
        return servers[0]

    print(f"\n  {BOLD}Available servers:{RESET}")
    for i, s in enumerate(servers, 1):
        print(
            f"    {CYAN}{i}{RESET}. {BOLD}{s.name}{RESET}"
            f"  {DIM}({s.ip}:{s.json_port}, v{s.version}, {s.rtt_ms:.1f}ms){RESET}"
        )

    while True:
        try:
            choice = input(f"\n  Select server [1-{len(servers)}]: ").strip()
            idx = int(choice) - 1
            if 0 <= idx < len(servers):
                _ok(f"Selected: {servers[idx]}")
                return servers[idx]
            _warn(f"Please enter a number between 1 and {len(servers)}")
        except (ValueError, EOFError, KeyboardInterrupt):
            print()
            _warn("Cancelled.")
            return None


def run_choose_music_source_flow(
    mock_server: MockServer,
    mock_player: MockPlayer,
) -> bool:
    """
    Exercise the ChooseMusicSource applet flow with a mock player and
    a real server wrapped in MockServer.

    Returns True if the flow completed successfully.
    """
    try:
        from jive.applets.ChooseMusicSource.ChooseMusicSourceApplet import (
            ChooseMusicSourceApplet,
        )
    except ImportError as exc:
        _fail(f"Could not import ChooseMusicSourceApplet: {exc}")
        return False

    applet = ChooseMusicSourceApplet()
    applet.init()

    callback_result: Dict[str, Any] = {"called": False, "server": None}

    def on_connected(server: Any) -> None:
        callback_result["called"] = True
        callback_result["server"] = server
        _ok(f"playerConnectedCallback fired for: {server}")

    # --- Build server list (simulating _show_music_source_list) ---
    _info("Building server list in ChooseMusicSource…")
    applet.server_list = {}
    applet.server_menu = None  # headless
    applet.player_connected_callback = on_connected

    item_id = mock_server.get_ip_port()
    item = {
        "server": mock_server,
        "text": mock_server.get_name(),
        "sound": "WINDOWSHOW",
        "weight": 1,
    }
    applet.server_list[item_id] = item
    _ok(f"Server list: {len(applet.server_list)} entry — '{mock_server.get_name()}'")

    # --- selectServer → connectPlayerToServer ---
    _info("Calling selectServer()…")

    # Patch _get_applet_manager to provide getCurrentPlayer
    import jive.applets.ChooseMusicSource.ChooseMusicSourceApplet as _cms_mod

    original_get_mgr = _cms_mod._get_applet_manager

    class _FakeManager:
        def call_service(self, name: str, *args: Any, **kwargs: Any) -> Any:
            if name == "getCurrentPlayer":
                return mock_player
            if name == "goHome":
                return None
            if name == "discoverServers":
                return None
            return None

        def has_service(self, name: str) -> bool:
            return name in ("getCurrentPlayer", "goHome", "discoverServers")

        def get_applet_db(self) -> Dict[str, Any]:
            return {}

    fake_mgr = _FakeManager()
    _cms_mod._get_applet_manager = lambda: fake_mgr

    try:
        applet.selectServer(mock_server)
    finally:
        _cms_mod._get_applet_manager = original_get_mgr

    # --- Check connecting popup ---
    if applet.connecting_popup is not None:
        _ok(f"Connecting popup created: {applet.connecting_popup}")
    else:
        _info("No connecting popup (player connected synchronously)")

    # --- Check wait_for_connect ---
    if applet.wait_for_connect is not None:
        wfc = applet.wait_for_connect
        _ok(f"wait_for_connect: player={wfc.get('player')}, server={wfc.get('server')}")
    else:
        _info("wait_for_connect is None (already completed)")

    # --- Simulate serverConnected notification ---
    _info("Simulating serverConnected notification…")
    mock_server._connected = True

    # --- hideConnectingToServer ---
    _info("Calling hideConnectingToServer()…")
    applet.hideConnectingToServer()

    if applet.connecting_popup is None:
        _ok("Connecting popup dismissed")

    if callback_result["called"]:
        _ok(f"Flow completed — callback received server: {callback_result['server']}")
        return True
    else:
        _info("Callback was not fired (player/server mismatch or already handled)")
        # Even without callback, check if player is connected
        if mock_player.is_connected() and mock_player.get_slim_server() is mock_server:
            _ok("Player is connected to server (callback skipped due to state)")
            return True
        return False


# ═══════════════════════════════════════════════════════════════════════════
# Step 3 — JSON-RPC query
# ═══════════════════════════════════════════════════════════════════════════


def jsonrpc_query(
    ip: str,
    port: int,
    method: str = "slim.request",
    params: Optional[List[Any]] = None,
    timeout: float = 10.0,
) -> Optional[Dict[str, Any]]:
    """Send a JSON-RPC request and return the decoded response."""
    if params is None:
        params = ["", ["serverstatus", 0, 50]]

    url = f"http://{ip}:{port}/jsonrpc.js"
    payload = json.dumps(
        {
            "method": method,
            "params": params,
            "id": 1,
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body)
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
        _fail(f"JSON-RPC request failed: {exc}")
        return None


def query_server(ip: str, port: int) -> None:
    """Query the server for status, players, and library counts."""

    # --- serverstatus ---
    _info(f"Querying {ip}:{port} — serverstatus …")
    result = jsonrpc_query(ip, port, params=["", ["serverstatus", 0, 50]])

    if result and "result" in result:
        r = result["result"]
        version = r.get("version", "?")
        uuid = r.get("uuid", "?")
        info_total = r.get("info total albums", r.get("info total songs", "?"))
        player_count = r.get("player count", 0)

        _ok(f"Server version: {version}")
        _ok(f"Server UUID: {uuid}")

        # Player list
        players = r.get("players_loop", [])
        if players:
            _ok(f"Players ({player_count}):")
            for p in players:
                name = p.get("name", "?")
                pid = p.get("playerid", "?")
                model = p.get("model", "?")
                connected = p.get("connected", 0)
                power = p.get("power", 0)
                conn_str = (
                    f"{GREEN}connected{RESET}"
                    if connected
                    else f"{DIM}disconnected{RESET}"
                )
                pwr_str = f"{GREEN}on{RESET}" if power else f"{DIM}off{RESET}"
                print(f"    • {BOLD}{name}{RESET}  {DIM}({pid}){RESET}")
                print(f"      model={model}  {conn_str}  power={pwr_str}")
        else:
            _info(f"No players reported (player count: {player_count})")

        # Library counts
        albums = r.get("info total albums", "?")
        artists = r.get("info total artists", "?")
        songs = r.get("info total songs", "?")
        genres = r.get("info total genres", "?")
        _ok(
            f"Library: {albums} albums, {artists} artists, {songs} songs, {genres} genres"
        )
    else:
        _warn("No result in serverstatus response")

    # --- server version (direct) ---
    _info("Querying server version …")
    v_result = jsonrpc_query(ip, port, params=["", ["version", "?"]])
    if v_result and "result" in v_result:
        ver = v_result["result"].get("_version", v_result["result"])
        _ok(f"Direct version query: {ver}")


# ═══════════════════════════════════════════════════════════════════════════
# Step 4 — Verify jivelite-py applet compatibility
# ═══════════════════════════════════════════════════════════════════════════


def verify_applet_compatibility() -> None:
    """Import and sanity-check all ported applets."""
    applets_checked = 0
    applets_ok = 0

    checks = [
        ("SlimDiscovery", "SlimDiscoveryMeta", "SlimDiscoveryApplet"),
        ("SlimMenus", "SlimMenusMeta", "SlimMenusApplet"),
        ("ChooseMusicSource", "ChooseMusicSourceMeta", "ChooseMusicSourceApplet"),
        ("SlimBrowser", "SlimBrowserMeta", "SlimBrowserApplet"),
        ("SelectPlayer", "SelectPlayerMeta", "SelectPlayerApplet"),
        ("NowPlaying", "NowPlayingMeta", "NowPlayingApplet"),
        ("JogglerSkin", "JogglerSkinMeta", "JogglerSkinApplet"),
        ("QVGAbaseSkin", "QVGAbaseSkinMeta", "QVGAbaseSkinApplet"),
    ]

    for applet_name, meta_cls, applet_cls in checks:
        applets_checked += 1
        try:
            meta_mod = __import__(
                f"jive.applets.{applet_name}.{meta_cls.replace('Applet', '').replace('Meta', '')}Meta",
                fromlist=[meta_cls],
            )
            meta = getattr(meta_mod, meta_cls)()
            jv = meta.jive_version()

            applet_mod = __import__(
                f"jive.applets.{applet_name}.{applet_cls.replace('Applet', '')}Applet",
                fromlist=[applet_cls],
            )
            applet = getattr(applet_mod, applet_cls)()

            _ok(
                f"{applet_name}: Meta={meta_cls} jive_version={jv}, Applet={applet_cls}"
            )
            applets_ok += 1
        except Exception as exc:
            _fail(f"{applet_name}: {exc}")

    if applets_ok == applets_checked:
        _ok(f"All {applets_checked} applets imported and verified")
    else:
        _warn(f"{applets_ok}/{applets_checked} applets OK")


# ═══════════════════════════════════════════════════════════════════════════
# Resonance server management
# ═══════════════════════════════════════════════════════════════════════════


def start_resonance() -> Optional[subprocess.Popen]:
    """Start the Resonance server in background (if available)."""
    resonance_dir = os.path.join(os.path.dirname(_PROJECT_ROOT), "resonance-server")
    if not os.path.isdir(resonance_dir):
        _warn(f"Resonance directory not found: {resonance_dir}")
        return None

    _info(f"Starting Resonance from {resonance_dir} …")
    try:
        proc = subprocess.Popen(
            [sys.executable, "-m", "resonance"],
            cwd=resonance_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            creationflags=(
                subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
            ),
        )
        _info("Waiting 3s for server to start …")
        time.sleep(3)
        if proc.poll() is not None:
            out = proc.stdout.read().decode(errors="replace") if proc.stdout else ""
            _fail(f"Server exited immediately (code {proc.returncode})")
            if out:
                _info(out[:300])
            return None
        _ok(f"Resonance started (PID {proc.pid})")
        return proc
    except Exception as exc:
        _fail(f"Failed to start Resonance: {exc}")
        return None


def stop_resonance(proc: subprocess.Popen) -> None:
    """Stop a Resonance server process."""
    _info(f"Stopping Resonance (PID {proc.pid}) …")
    try:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=3)
        _ok("Resonance stopped")
    except Exception as exc:
        _warn(f"Error stopping Resonance: {exc}")


# ═══════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════


def main() -> None:
    parser = argparse.ArgumentParser(
        description="End-to-end integration demo: Discovery → Select → Connect → Query",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  %(prog)s                                  # broadcast discovery
  %(prog)s --address 192.168.1.35           # unicast to specific IP
  %(prog)s --skip-discovery --server-ip 192.168.1.35 --server-port 9000
  %(prog)s --start-resonance                # start Resonance first
""",
    )
    parser.add_argument(
        "--address",
        default="255.255.255.255",
        help="Broadcast/unicast address for discovery (default: 255.255.255.255)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=5.0,
        help="Discovery timeout in seconds (default: 5)",
    )
    parser.add_argument(
        "--bursts",
        type=int,
        default=3,
        help="Number of discovery bursts (default: 3)",
    )
    parser.add_argument(
        "--start-resonance",
        action="store_true",
        help="Start Resonance server in background first",
    )
    parser.add_argument(
        "--skip-discovery",
        action="store_true",
        help="Skip UDP discovery and use --server-ip/--server-port directly",
    )
    parser.add_argument(
        "--server-ip",
        default=None,
        help="Server IP to use with --skip-discovery",
    )
    parser.add_argument(
        "--server-port",
        type=int,
        default=9000,
        help="Server JSON-RPC port (default: 9000)",
    )
    parser.add_argument(
        "--skip-query",
        action="store_true",
        help="Skip the JSON-RPC query step",
    )
    parser.add_argument(
        "--skip-compat",
        action="store_true",
        help="Skip the applet compatibility check",
    )

    args = parser.parse_args()

    _banner()

    resonance_proc = None
    exit_code = 0

    try:
        # --- Optionally start Resonance ---
        if args.start_resonance:
            resonance_proc = start_resonance()
            if resonance_proc is None:
                _warn("Continuing without Resonance …")

        # ─────────────────────────────────────────────────────────────
        # Step 1: Discovery
        # ─────────────────────────────────────────────────────────────
        selected_disc: Optional[DiscoveredServer] = None

        if args.skip_discovery:
            _step(1, "UDP Discovery (skipped)")
            if not args.server_ip:
                _fail("--skip-discovery requires --server-ip")
                sys.exit(1)
            selected_disc = DiscoveredServer(
                address=args.server_ip,
                port=DISCOVERY_PORT,
                tlv={
                    "NAME": f"Server@{args.server_ip}",
                    "IPAD": args.server_ip,
                    "JSON": str(args.server_port),
                    "VERS": "?",
                },
                rtt_ms=0.0,
            )
            _ok(f"Using provided server: {selected_disc}")
        else:
            _step(1, "UDP TLV Discovery")
            servers = discover_servers(
                target=args.address,
                timeout=args.timeout,
                bursts=args.bursts,
            )

            if not servers:
                _fail("No servers found on the network.")
                _info("Tips:")
                _info("  • Make sure a Lyrion/Resonance server is running")
                _info("  • Try: --address <specific-ip>")
                _info("  • Try: --start-resonance")
                _info("  • Try: --skip-discovery --server-ip <ip>")
                sys.exit(1)

            _ok(f"Discovered {len(servers)} server(s)")
            selected_disc = select_server_from_list(servers)

            if selected_disc is None:
                _warn("No server selected, exiting.")
                sys.exit(0)

        # ─────────────────────────────────────────────────────────────
        # Step 2: ChooseMusicSource flow
        # ─────────────────────────────────────────────────────────────
        _step(2, "ChooseMusicSource → Server Selection")

        mock_server = MockServer(selected_disc)
        mock_player = MockPlayer()

        _info(f"Mock player: {mock_player}")
        _info(f"Mock server: {mock_server}")

        flow_ok = run_choose_music_source_flow(mock_server, mock_player)

        if flow_ok:
            _ok("ChooseMusicSource flow completed successfully")
        else:
            _warn(
                "ChooseMusicSource flow did not complete the callback — "
                "this is OK for direct connections"
            )

        # Verify final state
        if mock_player.is_connected():
            _ok(f"Final state: player connected to {mock_player.get_slim_server()}")
        else:
            _warn("Final state: player not connected")

        # ─────────────────────────────────────────────────────────────
        # Step 3: JSON-RPC query
        # ─────────────────────────────────────────────────────────────
        if not args.skip_query:
            _step(3, "JSON-RPC Server Query")
            query_server(selected_disc.ip, selected_disc.json_port)
        else:
            _step(3, "JSON-RPC Query (skipped)")

        # ─────────────────────────────────────────────────────────────
        # Step 4: Applet compatibility
        # ─────────────────────────────────────────────────────────────
        if not args.skip_compat:
            _step(4, "Applet Compatibility Check")
            verify_applet_compatibility()
        else:
            _step(4, "Applet Compatibility (skipped)")

        # ─────────────────────────────────────────────────────────────
        # Summary
        # ─────────────────────────────────────────────────────────────
        print(
            f"\n{GREEN}{BOLD}"
            "╔══════════════════════════════════════════════════════════════╗\n"
            "║                    Demo Complete ✓                          ║\n"
            "╚══════════════════════════════════════════════════════════════╝"
            f"{RESET}\n"
        )

        print(f"  {BOLD}Summary:{RESET}")
        print(
            f"    Server:  {CYAN}{selected_disc.name}{RESET} @ {selected_disc.ip}:{selected_disc.json_port}"
        )
        print(f"    Version: {selected_disc.version}")
        print(
            f"    Player:  {mock_player.get_name()} → {'connected' if mock_player.is_connected() else 'not connected'}"
        )
        print(
            f"    Flow:    Discovery → Select → Connect → {'Query' if not args.skip_query else 'skipped'}"
        )
        print()

    except KeyboardInterrupt:
        print(f"\n{YELLOW}Interrupted.{RESET}")
        exit_code = 130

    except Exception as exc:
        _fail(f"Unexpected error: {exc}")
        import traceback

        traceback.print_exc()
        exit_code = 1

    finally:
        if resonance_proc is not None:
            stop_resonance(resonance_proc)

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
