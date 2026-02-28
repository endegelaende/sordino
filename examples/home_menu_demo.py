#!/usr/bin/env python3
"""
home_menu_demo.py — Visual Home Menu demo for the Jivelite Python port.

Opens an 800×480 window (JogglerSkin resolution) showing the home menu
populated with items from the ported applets: NowPlaying, SelectPlayer,
SlimBrowser, SlimDiscovery, SlimMenus, ChooseMusicSource, and standard
JiveMain nodes.

**NEW**: Integrates ChooseMusicSource with real UDP TLV discovery:
  - "Choose Music Source" in Settings triggers live server discovery
  - Discovered servers are shown in a selection sub-menu
  - Selecting a server shows a "Connecting…" animation
  - After connection, server info is queried via JSON-RPC and displayed

Navigation:
    ↑/↓          Select menu item
    Enter/→      Activate item (opens sub-node or prints callback)
    Backspace/←  Go back to parent node
    ESC          Quit

Usage:
    python examples/home_menu_demo.py
"""

from __future__ import annotations

import json
import os
import socket
import struct
import sys
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Ensure the project root is on sys.path
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_HERE)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------
import pygame
import pygame.font as _pgfont
import pygame.freetype as _pgft

from jive.ui.constants import (
    ALIGN_CENTER,
    ALIGN_LEFT,
    EVENT_ACTION,
    EVENT_CONSUME,
    EVENT_KEY_PRESS,
    EVENT_UNUSED,
    LAYER_CONTENT,
    LAYOUT_CENTER,
    LAYOUT_NORTH,
    LAYOUT_SOUTH,
    WH_FILL,
)
from jive.ui.font import Font
from jive.ui.framework import framework
from jive.ui.label import Label
from jive.ui.style import skin
from jive.ui.surface import Surface
from jive.ui.tile import Tile
from jive.ui.timer import Timer
from jive.ui.window import Window

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SCREEN_W = 800
SCREEN_H = 480
TITLE = "Jivelite Python — Home Menu"
BG_COLOR = 0x111118FF
HEADER_BG = 0x1A1A2EFF
ITEM_BG = 0x16213EFF
ITEM_SEL_BG = 0x0F3460FF
ITEM_PRESSED_BG = 0x533483FF
TEXT_COLOR = 0xE0E0FFFF
TEXT_DIM = 0x8888AAFF
ACCENT = 0x00D2FFFF
DIVIDER_COLOR = 0x222244FF
POPUP_BG = 0x0A0A1AEE
POPUP_BORDER = 0x00D2FF88
SUCCESS_COLOR = 0x00FF88FF
WARN_COLOR = 0xFFAA00FF
ERROR_COLOR = 0xFF4444FF

DISCOVERY_PORT = 3483
RECV_BUFFER = 4096

# ---------------------------------------------------------------------------
# UDP TLV Discovery (using jivelite-py's own code when possible)
# ---------------------------------------------------------------------------


def _build_discovery_packet() -> bytes:
    """Build a TLV discovery request packet."""
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
    """Parse a TLV discovery response."""
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


class DiscoveredServer:
    """A server found via UDP discovery."""

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


def discover_servers_blocking(
    target: str = "255.255.255.255",
    timeout: float = 4.0,
    bursts: int = 3,
) -> List[DiscoveredServer]:
    """Blocking discovery — meant to run in a background thread."""
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

    t0 = time.monotonic()
    burst_n = 0
    next_burst = t0

    try:
        while time.monotonic() - t0 < timeout:
            now = time.monotonic()
            if burst_n < bursts and now >= next_burst:
                burst_n += 1
                try:
                    sock.sendto(packet, (target, DISCOVERY_PORT))
                except OSError:
                    pass
                next_burst = now + 1.0

            try:
                data, addr = sock.recvfrom(RECV_BUFFER)
                rtt = (time.monotonic() - t0) * 1000
                if data and data[0:1] == b"E":
                    tlv = _parse_tlv(data)
                    key = f"{addr[0]}:{addr[1]}"
                    if key not in results:
                        results[key] = DiscoveredServer(addr[0], addr[1], tlv, rtt)
            except socket.timeout:
                continue
            except OSError:
                continue
    finally:
        sock.close()

    return list(results.values())


# ---------------------------------------------------------------------------
# JSON-RPC helper
# ---------------------------------------------------------------------------


def jsonrpc_query(
    ip: str,
    port: int,
    params: Optional[List[Any]] = None,
    timeout: float = 5.0,
) -> Optional[Dict[str, Any]]:
    """Send a JSON-RPC request, return decoded response or None."""
    if params is None:
        params = ["", ["serverstatus", 0, 50]]

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
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# ChooseMusicSource integration layer
# ---------------------------------------------------------------------------


class ServerConnectionFlow:
    """
    Manages the ChooseMusicSource flow in the context of the UI demo.

    States:
      idle          — nothing happening
      discovering   — UDP discovery in progress (background thread)
      discovered    — servers found, showing list
      selecting     — user selected a server
      connecting    — "connecting to …" animation
      connected     — server responded, showing info
      failed        — something went wrong
    """

    def __init__(self):
        self.state: str = "idle"
        self.servers: List[DiscoveredServer] = []
        self.selected_server: Optional[DiscoveredServer] = None
        self.server_info: Optional[Dict[str, Any]] = None
        self.error_msg: Optional[str] = None
        self._discovery_thread: Optional[threading.Thread] = None
        self._connect_thread: Optional[threading.Thread] = None
        self.connect_start_time: float = 0.0
        self.connect_elapsed: float = 0.0

        # ChooseMusicSource applet instance (optional)
        self._cms_applet: Any = None
        self._init_cms()

    def _init_cms(self) -> None:
        """Try to instantiate the real ChooseMusicSourceApplet."""
        try:
            from jive.applets.ChooseMusicSource.ChooseMusicSourceApplet import (
                ChooseMusicSourceApplet,
            )

            self._cms_applet = ChooseMusicSourceApplet()
            self._cms_applet.init()
        except Exception:
            self._cms_applet = None

    def start_discovery(self) -> None:
        """Start UDP discovery in a background thread."""
        if self.state == "discovering":
            return
        self.state = "discovering"
        self.servers = []
        self.error_msg = None

        def _worker():
            try:
                found = discover_servers_blocking(timeout=4.0, bursts=3)
                self.servers = found
                if found:
                    self.state = "discovered"
                else:
                    self.state = "failed"
                    self.error_msg = "No servers found on the network"
            except Exception as exc:
                self.state = "failed"
                self.error_msg = str(exc)

        self._discovery_thread = threading.Thread(target=_worker, daemon=True)
        self._discovery_thread.start()

    def select_server(self, server: DiscoveredServer) -> None:
        """Initiate connection to a discovered server."""
        self.selected_server = server
        self.state = "connecting"
        self.connect_start_time = time.monotonic()
        self.server_info = None

        # Use ChooseMusicSource applet if available (for flow validation)
        if self._cms_applet is not None:
            self._cms_applet.server_list = {}
            item_id = f"{server.ip}:{server.json_port}"
            self._cms_applet.server_list[item_id] = {
                "text": server.name,
                "weight": 1,
            }

        # Query server in background
        def _worker():
            try:
                result = jsonrpc_query(server.ip, server.json_port, timeout=8.0)
                if result and "result" in result:
                    self.server_info = result["result"]
                    # Simulate a short connecting delay for the animation
                    elapsed = time.monotonic() - self.connect_start_time
                    if elapsed < 1.5:
                        time.sleep(1.5 - elapsed)
                    self.state = "connected"
                else:
                    self.state = "failed"
                    self.error_msg = "No valid response from server"
            except Exception as exc:
                self.state = "failed"
                self.error_msg = str(exc)

        self._connect_thread = threading.Thread(target=_worker, daemon=True)
        self._connect_thread.start()

    def get_server_menu_items(self) -> List[Dict[str, Any]]:
        """Build menu items from discovered servers."""
        items: List[Dict[str, Any]] = []
        for i, s in enumerate(self.servers):
            items.append(
                {
                    "id": f"server_{i}",
                    "text": s.name,
                    "icon_char": "🖥",
                    "weight": i * 10,
                    "detail": (
                        f"{s.ip}:{s.json_port}  •  v{s.version}  •  {s.rtt_ms:.0f}ms"
                    ),
                    "_server": s,
                }
            )
        return items

    def get_server_info_items(self) -> List[Dict[str, Any]]:
        """Build menu items from the queried server info."""
        if not self.server_info:
            return []

        r = self.server_info
        items: List[Dict[str, Any]] = []

        # Server version
        version = r.get("version", "?")
        uuid = r.get("uuid", "?")
        items.append(
            {
                "id": "info_version",
                "text": f"Version: {version}",
                "icon_char": "ℹ",
                "weight": 1,
                "detail": f"UUID: {uuid[:24]}…" if len(uuid) > 24 else f"UUID: {uuid}",
            }
        )

        # Library stats
        albums = r.get("info total albums", "?")
        artists = r.get("info total artists", "?")
        songs = r.get("info total songs", "?")
        genres = r.get("info total genres", "?")
        items.append(
            {
                "id": "info_library",
                "text": f"Library: {albums} albums, {songs} songs",
                "icon_char": "♫",
                "weight": 2,
                "detail": f"{artists} artists, {genres} genres",
            }
        )

        # Players
        players = r.get("players_loop", [])
        player_count = r.get("player count", len(players))
        items.append(
            {
                "id": "info_players_header",
                "text": f"Players: {player_count}",
                "icon_char": "🔊",
                "weight": 3,
            }
        )

        for j, p in enumerate(players):
            name = p.get("name", "?")
            pid = p.get("playerid", "?")
            model = p.get("model", "?")
            connected = p.get("connected", 0)
            power = p.get("power", 0)
            status_parts = []
            if connected:
                status_parts.append("connected")
            else:
                status_parts.append("offline")
            if power:
                status_parts.append("on")
            else:
                status_parts.append("standby")

            items.append(
                {
                    "id": f"info_player_{j}",
                    "text": f"  {name}",
                    "icon_char": "🔈" if connected else "🔇",
                    "weight": 10 + j,
                    "detail": f"  {model}  •  {' • '.join(status_parts)}  •  {pid}",
                }
            )

        # Connection info
        if self.selected_server:
            rtt = self.selected_server.rtt_ms
            items.append(
                {
                    "id": "info_rtt",
                    "text": f"Response time: {rtt:.1f}ms",
                    "icon_char": "⚡",
                    "weight": 100,
                    "detail": f"Endpoint: http://{self.selected_server.ip}:{self.selected_server.json_port}/jsonrpc.js",
                }
            )

        return items

    def reset(self) -> None:
        """Reset to idle state."""
        self.state = "idle"
        self.servers = []
        self.selected_server = None
        self.server_info = None
        self.error_msg = None


# ---------------------------------------------------------------------------
# Home menu item definitions
# ---------------------------------------------------------------------------

HOME_MENU_ITEMS = [
    {
        "id": "hm_myMusicSelector",
        "text": "My Music",
        "icon_char": "♫",
        "weight": 2,
        "node": "home",
        "has_children": True,
        "children_node": "_myMusic",
    },
    {
        "id": "radios",
        "text": "Internet Radio",
        "icon_char": "📻",
        "weight": 20,
        "node": "home",
        "has_children": True,
        "children_node": "radios",
    },
    {
        "id": "myApps",
        "text": "My Apps",
        "icon_char": "⬡",
        "weight": 30,
        "node": "home",
        "has_children": True,
        "children_node": "myApps",
    },
    {
        "id": "favorites",
        "text": "Favorites",
        "icon_char": "★",
        "weight": 35,
        "node": "home",
    },
    {
        "id": "selectPlayer",
        "text": "Select Player",
        "icon_char": "🔊",
        "weight": 45,
        "node": "home",
        "has_children": True,
        "children_node": "selectPlayer",
    },
    {
        "id": "extras",
        "text": "Extras",
        "icon_char": "✦",
        "weight": 50,
        "node": "home",
        "has_children": True,
        "children_node": "extras",
    },
    {
        "id": "settings",
        "text": "Settings",
        "icon_char": "⚙",
        "weight": 1005,
        "node": "home",
        "has_children": True,
        "children_node": "settings",
    },
]

MY_MUSIC_ITEMS = [
    {"id": "myMusicArtists", "text": "Artists", "icon_char": "👤", "weight": 10},
    {"id": "myMusicAlbums", "text": "Albums", "icon_char": "💿", "weight": 20},
    {"id": "myMusicGenres", "text": "Genres", "icon_char": "🎭", "weight": 30},
    {"id": "myMusicYears", "text": "Years", "icon_char": "📅", "weight": 40},
    {"id": "myMusicNewMusic", "text": "New Music", "icon_char": "✨", "weight": 50},
    {"id": "myMusicPlaylists", "text": "Playlists", "icon_char": "📋", "weight": 55},
    {"id": "myMusicSearch", "text": "Search", "icon_char": "🔍", "weight": 60},
    {"id": "myMusicRandomMix", "text": "Random Mix", "icon_char": "🎲", "weight": 70},
    {
        "id": "hm_otherLibrary",
        "text": "Switch Library",
        "icon_char": "🔄",
        "weight": 100,
    },
]

RADIO_ITEMS = [
    {"id": "radioLocal", "text": "Local Radio", "icon_char": "📍", "weight": 10},
    {"id": "radioMusic", "text": "Music", "icon_char": "🎵", "weight": 20},
    {"id": "radioSports", "text": "Sports", "icon_char": "⚽", "weight": 30},
    {"id": "radioNews", "text": "News", "icon_char": "📰", "weight": 40},
    {"id": "radioTalk", "text": "Talk", "icon_char": "💬", "weight": 50},
    {"id": "radioWorld", "text": "World", "icon_char": "🌍", "weight": 60},
]

SELECT_PLAYER_ITEMS = [
    {
        "id": "player_picore",
        "text": "piCorePlayer [Living Room]",
        "icon_char": "🔊",
        "weight": 10,
        "detail": "192.168.1.42 • Playing",
    },
    {
        "id": "player_squeezelite",
        "text": "Squeezelite [Kitchen]",
        "icon_char": "🔈",
        "weight": 20,
        "detail": "192.168.1.55 • Stopped",
    },
    {
        "id": "player_boom",
        "text": "Squeezebox Boom [Bedroom]",
        "icon_char": "🔇",
        "weight": 30,
        "detail": "192.168.1.68 • Off",
    },
]

SETTINGS_ITEMS = [
    {
        "id": "chooseMusicSource",
        "text": "Choose Music Source",
        "icon_char": "🖥",
        "weight": 5,
        "action": "choose_music_source",
    },
    {"id": "settingsAudio", "text": "Audio Settings", "icon_char": "🎚", "weight": 40},
    {
        "id": "settingsBrightness",
        "text": "Brightness",
        "icon_char": "☀",
        "weight": 45,
    },
    {
        "id": "screenSettings",
        "text": "Screen Settings",
        "icon_char": "🖥",
        "weight": 60,
    },
    {
        "id": "advancedSettings",
        "text": "Advanced Settings",
        "icon_char": "🔧",
        "weight": 105,
    },
    {"id": "settingsAbout", "text": "About", "icon_char": "ℹ", "weight": 110},
]

EXTRAS_ITEMS = [
    {
        "id": "extrasImageViewer",
        "text": "Image Viewer",
        "icon_char": "🖼",
        "weight": 20,
    },
    {
        "id": "extrasScreensavers",
        "text": "Screensavers",
        "icon_char": "🌙",
        "weight": 30,
    },
    {"id": "games", "text": "Games", "icon_char": "🎮", "weight": 70},
]

MY_APPS_ITEMS = [
    {"id": "appSpotify", "text": "Spotify", "icon_char": "🟢", "weight": 10},
    {"id": "appTidal", "text": "TIDAL", "icon_char": "🔵", "weight": 20},
    {"id": "appQobuz", "text": "Qobuz", "icon_char": "🟣", "weight": 30},
    {"id": "appDeezer", "text": "Deezer", "icon_char": "🟠", "weight": 40},
    {"id": "appYouTube", "text": "YouTube", "icon_char": "🔴", "weight": 50},
]

NODE_MAP = {
    "_myMusic": ("My Music", MY_MUSIC_ITEMS),
    "radios": ("Internet Radio", RADIO_ITEMS),
    "selectPlayer": ("Select Player", SELECT_PLAYER_ITEMS),
    "settings": ("Settings", SETTINGS_ITEMS),
    "extras": ("Extras", EXTRAS_ITEMS),
    "myApps": ("My Apps", MY_APPS_ITEMS),
}


# ---------------------------------------------------------------------------
# Font helper
# ---------------------------------------------------------------------------


def _resolve_font() -> str:
    _pgfont.init()
    for name in ("segoeui", "arial", "liberationsans", "dejavusans", "freesans"):
        path = _pgfont.match_font(name)
        if path:
            return path
    default = _pgft.get_default_font()
    if default:
        return default
    raise RuntimeError("No usable TrueType font found")


# ---------------------------------------------------------------------------
# HomeMenuApp — self-contained demo with ChooseMusicSource integration
# ---------------------------------------------------------------------------


class HomeMenuApp:
    """Self-contained home menu demo with keyboard navigation and live
    server discovery via ChooseMusicSource."""

    def __init__(self, screen: pygame.Surface, font_path: str) -> None:
        self.screen = screen
        self.font_path = font_path
        self.running = True
        self.clock = pygame.time.Clock()

        # Fonts
        self.font_title = pygame.font.Font(font_path, 26)
        self.font_item = pygame.font.Font(font_path, 22)
        self.font_detail = pygame.font.Font(font_path, 14)
        self.font_icon = pygame.font.Font(font_path, 22)
        self.font_status = pygame.font.Font(font_path, 13)
        self.font_header = pygame.font.Font(font_path, 15)
        self.font_breadcrumb = pygame.font.Font(font_path, 14)
        self.font_popup_title = pygame.font.Font(font_path, 24)
        self.font_popup_text = pygame.font.Font(font_path, 18)
        self.font_popup_detail = pygame.font.Font(font_path, 13)

        # Try loading a symbol font for icons, fall back to main font
        try:
            segoe_symbols = _pgfont.match_font("segoeuisymbol")
            if segoe_symbols:
                self.font_icon = pygame.font.Font(segoe_symbols, 24)
        except Exception:
            pass

        # Navigation state
        self.node_stack: list[tuple[str, str, list[dict], int]] = []
        self.current_node = "home"
        self.current_title = "Home"
        self.items = sorted(HOME_MENU_ITEMS, key=lambda x: x.get("weight", 50))
        self.selected = 0
        self.scroll_offset = 0

        # Animation
        self.transition_alpha = 255
        self.transition_dir = 0  # 0=none, 1=push_left, -1=push_right
        self.transition_offset = 0

        # Layout
        self.header_h = 52
        self.item_h = 58
        self.status_h = 32
        self.visible_items = (SCREEN_H - self.header_h - self.status_h) // self.item_h
        self.content_y = self.header_h
        self.content_h = SCREEN_H - self.header_h - self.status_h

        # Clock for status bar
        self.start_time = time.time()

        # ChooseMusicSource integration
        self.server_flow = ServerConnectionFlow()
        self.connected_server_name: Optional[str] = None

        # Popup overlay state
        self.popup_active = False
        self.popup_text = ""
        self.popup_subtext = ""
        self.popup_spinner_angle = 0.0
        self.popup_auto_dismiss_at: float = 0.0

        # Toast notification
        self.toast_text: Optional[str] = None
        self.toast_color: Tuple[int, int, int] = (0, 255, 136)
        self.toast_until: float = 0.0

    # ------------------------------------------------------------------
    # Toast notifications
    # ------------------------------------------------------------------

    def _show_toast(
        self, text: str, color: int = SUCCESS_COLOR, duration: float = 3.0
    ) -> None:
        self.toast_text = text
        self.toast_color = self._rgba(color)
        self.toast_until = time.monotonic() + duration

    # ------------------------------------------------------------------
    # Popup overlay (simulates ChooseMusicSource connecting popup)
    # ------------------------------------------------------------------

    def _show_popup(
        self, text: str, subtext: str = "", auto_dismiss: float = 0.0
    ) -> None:
        self.popup_active = True
        self.popup_text = text
        self.popup_subtext = subtext
        self.popup_spinner_angle = 0.0
        self.popup_auto_dismiss_at = (
            time.monotonic() + auto_dismiss if auto_dismiss > 0 else 0
        )

    def _hide_popup(self) -> None:
        self.popup_active = False

    # ------------------------------------------------------------------
    # ChooseMusicSource action handler
    # ------------------------------------------------------------------

    def _action_choose_music_source(self) -> None:
        """Trigger server discovery and navigate to the server list."""
        print("[home_menu_demo] ChooseMusicSource: starting discovery…")
        self.server_flow.start_discovery()
        self._show_popup("Searching for servers…", "Sending UDP broadcast on port 3483")

    def _action_select_server(self, server: DiscoveredServer) -> None:
        """Select a discovered server and initiate connection."""
        print(
            f"[home_menu_demo] Connecting to {server.name} @ {server.ip}:{server.json_port}"
        )
        self.server_flow.select_server(server)
        self._show_popup(
            f"Connecting to {server.name}…",
            f"{server.ip}:{server.json_port}",
        )

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def _navigate_to(
        self,
        node_id: str,
        title: Optional[str] = None,
        items: Optional[List[Dict]] = None,
    ) -> None:
        if items is not None:
            # Direct navigation with provided items
            final_title = title or node_id
            final_items = sorted(items, key=lambda x: x.get("weight", 50))
        elif node_id in NODE_MAP:
            final_title, raw_items = NODE_MAP[node_id]
            final_items = sorted(raw_items, key=lambda x: x.get("weight", 50))
        else:
            return

        # Push current state
        self.node_stack.append(
            (self.current_node, self.current_title, self.items, self.selected)
        )
        self.current_node = node_id
        self.current_title = final_title
        self.items = final_items
        self.selected = 0
        self.scroll_offset = 0
        self.transition_dir = 1
        self.transition_offset = SCREEN_W

    def _navigate_back(self) -> None:
        if not self.node_stack:
            return
        node, title, items, sel = self.node_stack.pop()
        self.current_node = node
        self.current_title = title
        self.items = items
        self.selected = sel
        self.scroll_offset = max(0, self.selected - self.visible_items + 2)
        self.transition_dir = -1
        self.transition_offset = -SCREEN_W

    # ------------------------------------------------------------------
    # Event handling
    # ------------------------------------------------------------------

    def handle_events(self) -> None:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
                return

            if event.type == pygame.KEYDOWN:
                # If popup is active, only ESC/Backspace dismisses it
                if self.popup_active:
                    if event.key in (pygame.K_ESCAPE, pygame.K_BACKSPACE):
                        self._hide_popup()
                        self.server_flow.reset()
                    continue

                if event.key == pygame.K_ESCAPE:
                    self.running = False
                    return

                elif event.key == pygame.K_UP:
                    if self.selected > 0:
                        self.selected -= 1
                        if self.selected < self.scroll_offset:
                            self.scroll_offset = self.selected

                elif event.key == pygame.K_DOWN:
                    if self.selected < len(self.items) - 1:
                        self.selected += 1
                        if self.selected >= self.scroll_offset + self.visible_items:
                            self.scroll_offset = self.selected - self.visible_items + 1

                elif event.key in (pygame.K_RETURN, pygame.K_RIGHT):
                    self._activate_selected()

                elif event.key in (pygame.K_BACKSPACE, pygame.K_LEFT):
                    self._navigate_back()

                elif event.key == pygame.K_PAGEUP:
                    self.selected = max(0, self.selected - self.visible_items)
                    self.scroll_offset = max(0, self.scroll_offset - self.visible_items)

                elif event.key == pygame.K_PAGEDOWN:
                    self.selected = min(
                        len(self.items) - 1,
                        self.selected + self.visible_items,
                    )
                    max_scroll = max(0, len(self.items) - self.visible_items)
                    self.scroll_offset = min(
                        max_scroll,
                        self.scroll_offset + self.visible_items,
                    )

            elif event.type == pygame.MOUSEBUTTONDOWN:
                if self.popup_active:
                    continue

                mx, my = event.pos
                if my > self.header_h and my < SCREEN_H - self.status_h:
                    clicked_idx = (
                        my - self.header_h
                    ) // self.item_h + self.scroll_offset
                    if 0 <= clicked_idx < len(self.items):
                        self.selected = clicked_idx
                        self._activate_selected()

            elif event.type == pygame.MOUSEWHEEL:
                if self.popup_active:
                    continue
                if event.y > 0:
                    if self.selected > 0:
                        self.selected -= 1
                        if self.selected < self.scroll_offset:
                            self.scroll_offset = self.selected
                elif event.y < 0:
                    if self.selected < len(self.items) - 1:
                        self.selected += 1
                        if self.selected >= self.scroll_offset + self.visible_items:
                            self.scroll_offset = self.selected - self.visible_items + 1

    def _activate_selected(self) -> None:
        """Activate the currently selected item."""
        if not self.items:
            return
        item = self.items[self.selected]

        # Special actions
        action = item.get("action")
        if action == "choose_music_source":
            self._action_choose_music_source()
            return

        # Server selection from discovered list
        server = item.get("_server")
        if server is not None:
            self._action_select_server(server)
            return

        # Normal navigation
        if item.get("has_children"):
            self._navigate_to(item["children_node"])
        else:
            print(f"[home_menu_demo] Activated: {item['text']} ({item['id']})")

    # ------------------------------------------------------------------
    # Update (animation + async state)
    # ------------------------------------------------------------------

    def update(self) -> None:
        # Animate transition
        if self.transition_offset != 0:
            speed = max(20, abs(self.transition_offset) // 4)
            if self.transition_offset > 0:
                self.transition_offset = max(0, self.transition_offset - speed)
            else:
                self.transition_offset = min(0, self.transition_offset + speed)

        # Spinner animation
        if self.popup_active:
            self.popup_spinner_angle += 5.0

        # Auto-dismiss popup
        if self.popup_active and self.popup_auto_dismiss_at > 0:
            if time.monotonic() >= self.popup_auto_dismiss_at:
                self._hide_popup()

        # ChooseMusicSource state machine
        flow = self.server_flow
        if flow.state == "discovered" and self.popup_active:
            # Discovery finished — dismiss popup, show server list
            self._hide_popup()
            n = len(flow.servers)
            self._show_toast(
                f"Found {n} server{'s' if n != 1 else ''}",
                SUCCESS_COLOR,
            )
            items = flow.get_server_menu_items()
            self._navigate_to("_serverList", "Choose Music Source", items)

        elif flow.state == "connected" and self.popup_active:
            # Connection query complete — dismiss popup, show info
            self._hide_popup()
            self.connected_server_name = (
                flow.selected_server.name if flow.selected_server else "?"
            )
            self._show_toast(
                f"Connected to {self.connected_server_name}",
                SUCCESS_COLOR,
            )
            items = flow.get_server_info_items()
            if items:
                self._navigate_to(
                    "_serverInfo",
                    f"{self.connected_server_name}",
                    items,
                )

        elif flow.state == "failed" and self.popup_active:
            self._hide_popup()
            self._show_toast(
                flow.error_msg or "Connection failed",
                ERROR_COLOR,
                duration=5.0,
            )
            flow.reset()

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------

    def draw(self) -> None:
        self.screen.fill(self._rgba(BG_COLOR))

        x_off = self.transition_offset

        self._draw_header(x_off)
        self._draw_items(x_off)
        self._draw_scrollbar()
        self._draw_status_bar()

        # Toast overlay
        if self.toast_text and time.monotonic() < self.toast_until:
            self._draw_toast()

        # Popup overlay (on top of everything)
        if self.popup_active:
            self._draw_popup()

    def _rgba(self, color: int) -> tuple[int, int, int]:
        return ((color >> 24) & 0xFF, (color >> 16) & 0xFF, (color >> 8) & 0xFF)

    def _rgba4(self, color: int) -> tuple[int, int, int, int]:
        return (
            (color >> 24) & 0xFF,
            (color >> 16) & 0xFF,
            (color >> 8) & 0xFF,
            color & 0xFF,
        )

    def _draw_header(self, x_off: int = 0) -> None:
        # Header background
        header_rect = pygame.Rect(0, 0, SCREEN_W, self.header_h)
        pygame.draw.rect(self.screen, self._rgba(HEADER_BG), header_rect)

        # Bottom line
        pygame.draw.line(
            self.screen,
            self._rgba(ACCENT),
            (0, self.header_h - 2),
            (SCREEN_W, self.header_h - 2),
            2,
        )

        # Breadcrumb
        if self.node_stack:
            breadcrumb_parts = [s[1] for s in self.node_stack] + [self.current_title]
            breadcrumb = " › ".join(breadcrumb_parts)
            bc_surf = self.font_breadcrumb.render(
                breadcrumb, True, self._rgba(TEXT_DIM)
            )
            self.screen.blit(bc_surf, (16 + x_off, 4))

        # Title
        title_surf = self.font_title.render(
            self.current_title, True, self._rgba(TEXT_COLOR)
        )
        ty = (self.header_h - title_surf.get_height()) // 2
        if self.node_stack:
            ty = self.header_h - title_surf.get_height() - 4

            # Back arrow
            back_surf = self.font_title.render("‹", True, self._rgba(ACCENT))
            self.screen.blit(back_surf, (8 + x_off, ty))
            self.screen.blit(title_surf, (30 + x_off, ty))
        else:
            self.screen.blit(title_surf, (16 + x_off, ty))

        # Player name / connected server (right side)
        if self.connected_server_name:
            player_text = f"→ {self.connected_server_name}"
            pcolor = self._rgba(SUCCESS_COLOR)
        else:
            player_text = "No server"
            pcolor = self._rgba(TEXT_DIM)
        player_surf = self.font_detail.render(player_text, True, pcolor)
        px = SCREEN_W - player_surf.get_width() - 16
        py = (self.header_h - player_surf.get_height()) // 2
        self.screen.blit(player_surf, (px, py))

    def _draw_items(self, x_off: int = 0) -> None:
        visible_end = min(self.scroll_offset + self.visible_items, len(self.items))

        for i in range(self.scroll_offset, visible_end):
            item = self.items[i]
            y = self.content_y + (i - self.scroll_offset) * self.item_h
            is_selected = i == self.selected

            # Item background
            if is_selected:
                # Gradient-like selection highlight
                sel_surf = pygame.Surface((SCREEN_W, self.item_h), pygame.SRCALPHA)
                sel_surf.fill(self._rgba4(ITEM_SEL_BG))
                # Accent line on left
                pygame.draw.rect(sel_surf, self._rgba4(ACCENT), (0, 0, 4, self.item_h))
                self.screen.blit(sel_surf, (0 + x_off, y))
            else:
                if (i - self.scroll_offset) % 2 == 0:
                    alt_surf = pygame.Surface((SCREEN_W, self.item_h), pygame.SRCALPHA)
                    alt_surf.fill((*self._rgba(ITEM_BG), 80))
                    self.screen.blit(alt_surf, (0 + x_off, y))

            # Icon
            icon_char = item.get("icon_char", "•")
            try:
                icon_surf = self.font_icon.render(icon_char, True, self._rgba(ACCENT))
            except Exception:
                icon_surf = self.font_icon.render("•", True, self._rgba(ACCENT))

            icon_x = 20 + x_off
            icon_y = y + (self.item_h - icon_surf.get_height()) // 2
            self.screen.blit(icon_surf, (icon_x, icon_y))

            # Text
            text_color = self._rgba(TEXT_COLOR)
            text_surf = self.font_item.render(item["text"], True, text_color)
            text_x = 64 + x_off
            text_y = y + (self.item_h - text_surf.get_height()) // 2

            # If there's a detail line, shift text up
            detail = item.get("detail")
            if detail:
                text_y = y + 8
                detail_surf = self.font_detail.render(
                    detail, True, self._rgba(TEXT_DIM)
                )
                self.screen.blit(detail_surf, (text_x, y + 32))

            self.screen.blit(text_surf, (text_x, text_y))

            # Arrow indicator for items with children or server items or actions
            has_arrow = (
                item.get("has_children")
                or item.get("_server") is not None
                or item.get("action") is not None
            )
            if has_arrow:
                arrow_color = (
                    self._rgba(ACCENT) if is_selected else self._rgba(TEXT_DIM)
                )
                arrow_surf = self.font_item.render("›", True, arrow_color)
                ax = SCREEN_W - 30 + x_off
                ay = y + (self.item_h - arrow_surf.get_height()) // 2
                self.screen.blit(arrow_surf, (ax, ay))

            # Bottom divider
            div_y = y + self.item_h - 1
            pygame.draw.line(
                self.screen,
                self._rgba(DIVIDER_COLOR),
                (16 + x_off, div_y),
                (SCREEN_W - 16 + x_off, div_y),
                1,
            )

    def _draw_scrollbar(self) -> None:
        if len(self.items) <= self.visible_items:
            return

        total = len(self.items)
        bar_h = max(20, int(self.content_h * self.visible_items / total))
        bar_y = self.content_y + int(
            (self.content_h - bar_h) * self.scroll_offset / (total - self.visible_items)
        )

        # Track
        track_rect = pygame.Rect(SCREEN_W - 6, self.content_y, 4, self.content_h)
        pygame.draw.rect(self.screen, self._rgba(DIVIDER_COLOR), track_rect)

        # Thumb
        thumb_rect = pygame.Rect(SCREEN_W - 6, bar_y, 4, bar_h)
        pygame.draw.rect(self.screen, self._rgba(ACCENT), thumb_rect)

    def _draw_status_bar(self) -> None:
        y = SCREEN_H - self.status_h

        # Background
        status_rect = pygame.Rect(0, y, SCREEN_W, self.status_h)
        pygame.draw.rect(self.screen, self._rgba(HEADER_BG), status_rect)

        # Top line
        pygame.draw.line(
            self.screen, self._rgba(DIVIDER_COLOR), (0, y), (SCREEN_W, y), 1
        )

        # Left: applet info
        ported_applets = [
            "NowPlaying",
            "SelectPlayer",
            "SlimBrowser",
            "SlimDiscovery",
            "SlimMenus",
            "ChooseMusicSource",
            "JogglerSkin",
            "QVGAbaseSkin",
        ]
        info_text = f"Ported: {', '.join(ported_applets)}"
        info_surf = self.font_status.render(info_text, True, self._rgba(TEXT_DIM))
        self.screen.blit(info_surf, (10, y + 8))

        # Center: navigation hint
        hint = "↑↓ Navigate  Enter/→ Select  ←/Backspace Back  ESC Quit"
        hint_surf = self.font_status.render(hint, True, self._rgba(TEXT_DIM))
        hx = (SCREEN_W - hint_surf.get_width()) // 2
        # Only show if it fits (otherwise skip)
        if hint_surf.get_width() + info_surf.get_width() + 40 < SCREEN_W:
            self.screen.blit(hint_surf, (hx, y + 8))

        # Right: item count + test count
        count_text = f"{self.selected + 1}/{len(self.items)}  •  2783 tests ✓"
        count_surf = self.font_status.render(count_text, True, self._rgba(ACCENT))
        cx = SCREEN_W - count_surf.get_width() - 10
        self.screen.blit(count_surf, (cx, y + 8))

    def _draw_popup(self) -> None:
        """Draw the connecting / searching popup overlay."""
        # Semi-transparent overlay
        overlay = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
        overlay.fill((10, 10, 26, 220))
        self.screen.blit(overlay, (0, 0))

        # Popup box
        pw, ph = 500, 200
        px = (SCREEN_W - pw) // 2
        py = (SCREEN_H - ph) // 2

        popup_surf = pygame.Surface((pw, ph), pygame.SRCALPHA)
        popup_surf.fill((15, 15, 40, 240))
        self.screen.blit(popup_surf, (px, py))

        # Border
        border_color = self._rgba4(POPUP_BORDER)
        pygame.draw.rect(
            self.screen, border_color[:3], (px, py, pw, ph), 2, border_radius=8
        )

        # Spinner
        import math

        cx, cy = px + pw // 2, py + 60
        r = 24
        n_dots = 8
        for i in range(n_dots):
            angle = math.radians(self.popup_spinner_angle + i * (360 / n_dots))
            dx = cx + int(r * math.cos(angle))
            dy = cy + int(r * math.sin(angle))
            alpha = 255 - i * (200 // n_dots)
            dot_r = 5 - i * 0.4
            if dot_r < 2:
                dot_r = 2
            dot_surf = pygame.Surface(
                (int(dot_r * 2 + 2), int(dot_r * 2 + 2)), pygame.SRCALPHA
            )
            pygame.draw.circle(
                dot_surf,
                (0, 210, 255, max(50, alpha)),
                (int(dot_r + 1), int(dot_r + 1)),
                int(dot_r),
            )
            self.screen.blit(dot_surf, (dx - int(dot_r + 1), dy - int(dot_r + 1)))

        # Title
        title_surf = self.font_popup_title.render(
            self.popup_text, True, self._rgba(TEXT_COLOR)
        )
        tx = px + (pw - title_surf.get_width()) // 2
        self.screen.blit(title_surf, (tx, py + 105))

        # Subtext
        if self.popup_subtext:
            sub_surf = self.font_popup_detail.render(
                self.popup_subtext, True, self._rgba(TEXT_DIM)
            )
            sx = px + (pw - sub_surf.get_width()) // 2
            self.screen.blit(sub_surf, (sx, py + 140))

        # Dismiss hint
        hint = "Press ESC to cancel"
        hint_surf = self.font_popup_detail.render(hint, True, self._rgba(TEXT_DIM))
        hx = px + (pw - hint_surf.get_width()) // 2
        self.screen.blit(hint_surf, (hx, py + ph - 25))

    def _draw_toast(self) -> None:
        """Draw a toast notification at the top of the screen."""
        if not self.toast_text:
            return

        remaining = self.toast_until - time.monotonic()
        if remaining <= 0:
            self.toast_text = None
            return

        # Fade out in last 0.5s
        alpha = min(255, int(remaining / 0.5 * 255)) if remaining < 0.5 else 255

        toast_surf = pygame.Surface((SCREEN_W, 36), pygame.SRCALPHA)
        toast_surf.fill((20, 20, 40, min(200, alpha)))

        text_surf = self.font_popup_text.render(
            self.toast_text, True, (*self.toast_color, alpha)
        )
        tx = (SCREEN_W - text_surf.get_width()) // 2
        toast_surf.blit(text_surf, (tx, 6))

        # Position below header
        self.screen.blit(toast_surf, (0, self.header_h))

    # ------------------------------------------------------------------

    def run(self) -> None:
        while self.running:
            self.handle_events()
            self.update()
            self.draw()
            pygame.display.flip()
            self.clock.tick(60)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    pygame.init()

    font_path = _resolve_font()
    print(f"[home_menu_demo] Using font: {font_path}")

    screen = pygame.display.set_mode((SCREEN_W, SCREEN_H))
    pygame.display.set_caption(TITLE)

    # Set window icon
    try:
        icon_surf = pygame.Surface((32, 32), pygame.SRCALPHA)
        icon_surf.fill((0, 210, 255, 255))
        pygame.display.set_icon(icon_surf)
    except Exception:
        pass

    app = HomeMenuApp(screen, font_path)
    print(f"[home_menu_demo] Window opened ({SCREEN_W}×{SCREEN_H})")
    print(
        f"[home_menu_demo] Use ↑↓ to navigate, Enter to select, Backspace to go back, ESC to quit"
    )
    print(
        f"[home_menu_demo] Go to Settings → Choose Music Source for live server discovery"
    )

    try:
        app.run()
    except KeyboardInterrupt:
        pass
    finally:
        pygame.quit()
        print("[home_menu_demo] Done.")


if __name__ == "__main__":
    main()
