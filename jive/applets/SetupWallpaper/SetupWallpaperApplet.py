"""
jive.applets.SetupWallpaper.SetupWallpaperApplet — Wallpaper selection.

Ported from ``share/jive/applets/SetupWallpaper/SetupWallpaperApplet.lua``
in the original jivelite project.

This applet implements selection of the wallpaper for the jive background
image. It includes local wallpapers shipped with jive and supports
downloading wallpapers from the currently attached server.

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from jive.applet import Applet
from jive.utils.log import logger

__all__ = ["SetupWallpaperApplet"]

log = logger("applet.SetupWallpaper")

_FIRMWARE_PREFIX = "applets/SetupWallpaper/wallpaper/"

# Screen-size → filename prefix mapping
_SCREEN_PREFIXES: Dict[Tuple[int, int], str] = {
    (320, 240): "BB_",
    (240, 320): "JIVE_",
    (480, 272): "FAB4_",
    (480, 320): "WAV_",
    (800, 480): "PCP_",
    (240, 240): "PIR_",
}

_IMAGE_SUFFIXES = {"png", "jpg", "gif", "bmp"}


class SetupWallpaperApplet(Applet):
    """Wallpaper selection applet."""

    def __init__(self) -> None:
        super().__init__()
        self.download: Dict[str, Any] = {}
        self.wallpapers: Dict[str, Dict[str, str]] = {}
        self.player: Any = None
        self.player_name: Optional[str] = None
        self.current_player_id: Optional[str] = None
        self.current_wallpaper: Optional[str] = None
        self.server: Any = None
        self.menu_widget: Any = None
        self.group: Any = None
        self.last: Optional[str] = None

    def init(self) -> None:
        super().init()

        jnt = self._get_jnt()
        if jnt is not None:
            jnt.subscribe(self)

        self._download_prefix = self._get_download_prefix()
        log.debug("downloaded wallpapers stored at: %s", self._download_prefix)

        self.download = {}
        self.wallpapers = {}

    # ------------------------------------------------------------------
    # Notifications
    # ------------------------------------------------------------------

    def notify_playerCurrent(self, player: Any) -> None:
        """Called when the current player changes."""
        log.debug("notify_playerCurrent(%s)", player)
        if player is self.player:
            return

        self.player = player
        player_id = None
        if player is not None:
            if hasattr(player, "getId"):
                player_id = player.getId()
            elif hasattr(player, "get_id"):
                player_id = player.get_id()

        if player_id:
            self.setBackground(None, player_id)
        else:
            self.setBackground(None, "wallpaper")

    # Lua-compatible alias
    notify_player_current = notify_playerCurrent

    # ------------------------------------------------------------------
    # Settings UI
    # ------------------------------------------------------------------

    def settingsShow(self, menu_item: Any = None) -> Any:
        """Show wallpaper selection screen."""
        try:
            from jive.ui.constants import EVENT_WINDOW_POP
            from jive.ui.radio import RadioButton, RadioGroup
            from jive.ui.simplemenu import SimpleMenu
            from jive.ui.window import Window
        except ImportError as exc:
            log.warn("UI modules not available: %s", exc)
            return None

        window = Window("text_list", self.string("WALLPAPER"), "settingstitle")

        jive_main = self._get_jive_main()
        mgr = self._get_applet_manager()

        # Determine current player ID
        self.current_player_id = None
        if jive_main is not None:
            if hasattr(jive_main, "getSelectedSkin"):
                self.current_player_id = jive_main.getSelectedSkin()
            elif hasattr(jive_main, "get_selected_skin"):
                self.current_player_id = jive_main.get_selected_skin()

        if self.player is None and mgr is not None:
            try:
                self.player = mgr.call_service("getCurrentPlayer")
            except Exception as exc:
                log.error(
                    "settingsShow: failed to get current player: %s", exc, exc_info=True
                )

        if self.player is not None:
            if hasattr(self.player, "getId"):
                self.current_player_id = self.player.getId()
            elif hasattr(self.player, "get_id"):
                self.current_player_id = self.player.get_id()
            if hasattr(self.player, "getName"):
                self.player_name = self.player.getName()
            elif hasattr(self.player, "get_name"):
                self.player_name = self.player.get_name()

        self.menu_widget = SimpleMenu("menu")
        window.add_widget(self.menu_widget)

        current_wallpaper = None
        settings = self.get_settings()
        if settings and self.current_player_id:
            current_wallpaper = settings.get(self.current_player_id)

        self.server = self._get_current_server()
        self.group = RadioGroup()

        comparator = getattr(SimpleMenu, "itemComparatorWeightAlpha", None) or getattr(
            SimpleMenu, "item_comparator_weight_alpha", None
        )
        if comparator is not None:
            self.menu_widget.set_comparator(comparator)

        # Get screen size for filtering
        screen_width, screen_height = self._get_screen_size()

        # Read local wallpapers from applet directory
        self.wallpapers = {}
        for img_path in self.readdir("wallpaper"):
            self._read_file(img_path, screen_width, screen_height)

        # Read downloaded wallpapers
        if self._download_prefix and os.path.isdir(self._download_prefix):
            for fname in os.listdir(self._download_prefix):
                full_path = os.path.join(self._download_prefix, fname)
                self._read_file(full_path, screen_width, screen_height)

        # Add "Black" (no wallpaper) item
        pid = self.current_player_id

        self.menu_widget.addItem(
            {
                "weight": 1,
                "text": self.string("BLACK"),
                "style": "item_choice",
                "sound": "WINDOWSHOW",
                "check": RadioButton(
                    "radio",
                    self.group,
                    lambda *_args: self.setBackground("black", pid),
                    current_wallpaper == "black",
                ),
                "focusGained": lambda *_args: self.showBackground("black", pid),
            }
        )

        # Add local wallpaper items
        for name, details in self.wallpapers.items():
            token = details.get("token", "")
            title = self.string(token)
            if title == token:
                title = details.get("name", name)

            fullpath = details.get("fullpath", "")
            _fp = fullpath  # capture for closures
            _name = name

            self.menu_widget.addItem(
                {
                    "weight": 1,
                    "text": title,
                    "style": "item_choice",
                    "sound": "WINDOWSHOW",
                    "check": RadioButton(
                        "radio",
                        self.group,
                        lambda *_args, fp=_fp: self.setBackground(fp, pid),
                        current_wallpaper == fullpath or current_wallpaper == name,
                    ),
                    "focusGained": lambda *_args, fp=_fp: self.showBackground(fp, pid),
                }
            )

        # Request server wallpapers
        screen = f"{screen_width}x{screen_height}"
        known_screens = {"800x480", "480x272", "240x320", "320x240", "240x240"}
        if screen not in known_screens:
            screen = None  # type: ignore[assignment]

        if self.server is not None:
            log.debug("found server - requesting wallpapers list %s", screen)
            try:
                args = ["jivewallpapers"]
                if screen:
                    args.append(f"target:{screen}")

                if hasattr(self.server, "userRequest"):
                    self.server.userRequest(
                        lambda chunk, err=None: self._server_sink_cb(chunk, err),
                        False,
                        args,
                    )
                elif hasattr(self.server, "user_request"):
                    self.server.user_request(
                        lambda chunk, err=None: self._server_sink_cb(chunk, err),
                        False,
                        args,
                    )
            except Exception as exc:
                log.debug("Failed to request server wallpapers: %s", exc)

        # Jump to selected item
        if hasattr(self.menu_widget, "getItems"):
            items = self.menu_widget.getItems()
        elif hasattr(self.menu_widget, "get_items"):
            items = self.menu_widget.get_items()
        else:
            items = getattr(self.menu_widget, "items", [])

        for i, item in enumerate(items):
            check = item.get("check") if isinstance(item, dict) else None
            if check is not None and hasattr(check, "isSelected"):
                if check.isSelected():
                    if hasattr(self.menu_widget, "setSelectedIndex"):
                        self.menu_widget.setSelectedIndex(i + 1)
                    elif hasattr(self.menu_widget, "set_selected_index"):
                        self.menu_widget.set_selected_index(i + 1)
                    break

        # Store settings on window close
        def _on_pop(event: Any = None) -> int:
            self.showBackground(None, self.current_player_id)
            self.store_settings()
            self.download = {}
            from jive.ui.constants import EVENT_UNUSED

            return int(EVENT_UNUSED)

        window.add_listener(int(EVENT_WINDOW_POP), _on_pop)

        self.tie_and_show_window(window)
        return window

    # Lua-compatible alias
    settings_show = settingsShow

    # ------------------------------------------------------------------
    # File scanning
    # ------------------------------------------------------------------

    def _read_file(self, img: str, screen_width: int, screen_height: int) -> None:
        """Parse a wallpaper file and add to self.wallpapers if valid."""
        # Split path to get filename
        parts = img.replace("\\", "/").split("/")
        name = parts[-1] if parts else img

        # Split on period to get name and suffix
        dot_parts = name.rsplit(".", 1)
        if len(dot_parts) != 2:
            return

        basename, suffix = dot_parts
        if suffix.lower() not in _IMAGE_SUFFIXES:
            return

        # Get token from the last underscore-separated part
        underscore_parts = basename.split("_")
        string_token = underscore_parts[-1].upper()
        pattern_match = basename.upper()

        # Determine screen-size prefix filter
        pattern = _SCREEN_PREFIXES.get((screen_width, screen_height), "HD_")

        # Skip black (handled as special case) and duplicates
        if (
            name not in self.wallpapers
            and string_token != "BLACK"
            and (not pattern or pattern_match.startswith(pattern))
        ):
            self.wallpapers[name] = {
                "token": string_token,
                "name": underscore_parts[-1],
                "suffix": suffix,
                "fullpath": img,
            }

    @staticmethod
    def _is_img(suffix: str) -> bool:
        """Check if a suffix represents an image format."""
        return suffix.lower() in _IMAGE_SUFFIXES

    # ------------------------------------------------------------------
    # Server wallpapers
    # ------------------------------------------------------------------

    def _get_current_server(self) -> Any:
        """Get the currently connected server."""
        if self.player is not None:
            if hasattr(self.player, "getSlimServer"):
                return self.player.getSlimServer()
            elif hasattr(self.player, "get_slim_server"):
                return self.player.get_slim_server()

        mgr = self._get_applet_manager()
        if mgr is not None:
            try:
                iterator = mgr.call_service("iterateSqueezeCenters")
                if iterator is not None:
                    for _, server in iterator:
                        return server
            except Exception as exc:
                log.error(
                    "_get_current_server: failed to iterate squeeze centers: %s",
                    exc,
                    exc_info=True,
                )

        return None

    def _server_sink_cb(self, chunk: Any, err: Any = None) -> None:
        """Callback for server wallpaper list response."""
        if err:
            log.debug("server wallpaper error: %s", err)
            return
        if chunk is not None:
            data = chunk.get("data", chunk) if isinstance(chunk, dict) else chunk
            if isinstance(data, dict):
                self._server_sink(data)

    def _server_sink(self, data: Dict[str, Any]) -> None:
        """Process server wallpaper list response."""
        try:
            from jive.ui.radio import RadioButton
        except ImportError:
            return

        ip, port = "", 0
        if self.server is not None:
            if hasattr(self.server, "getIpPort"):
                ip, port = self.server.getIpPort()
            elif hasattr(self.server, "get_ip_port"):
                ip, port = self.server.get_ip_port()
            elif hasattr(self.server, "ip"):
                ip = self.server.ip
                port = getattr(self.server, "port", 0)

        current_wallpaper = None
        settings = self.get_settings()
        if settings and self.current_player_id:
            current_wallpaper = settings.get(self.current_player_id)

        item_loop = data.get("item_loop", [])
        pid = self.current_player_id

        for entry in item_loop:
            url = None
            if entry.get("relurl"):
                url = f"http://{ip}:{port}{entry['relurl']}"
            else:
                url = entry.get("url")

            if url is None:
                continue

            log.debug("remote wallpaper: %s %s", entry.get("title"), url)

            _url = url  # capture for closures

            if self.menu_widget is not None and self.group is not None:
                self.menu_widget.addItem(
                    {
                        "weight": 50,
                        "text": entry.get("title", ""),
                        "style": "item_choice",
                        "check": RadioButton(
                            "radio",
                            self.group,
                            lambda *_args, u=_url: self._on_remote_selected(u),
                            current_wallpaper == url,
                        ),
                        "focusGained": lambda *_args, u=_url: self._on_remote_focus(u),
                    }
                )

                if current_wallpaper == url:
                    if hasattr(self.menu_widget, "setSelectedIndex"):
                        num = getattr(self.menu_widget, "numItems", None)
                        if callable(num):
                            self.menu_widget.setSelectedIndex(num() - 1)
                    elif hasattr(self.menu_widget, "num_items"):
                        self.menu_widget.set_selected_index(
                            self.menu_widget.num_items() - 1
                        )

    def _on_remote_selected(self, url: str) -> None:
        """Handle selection of a remote wallpaper."""
        if self.download.get(url):
            self.setBackground(url, self.current_player_id)

    def _on_remote_focus(self, url: str) -> None:
        """Handle focus on a remote wallpaper."""
        cached = self.download.get(url)
        if cached and cached != "fetch" and cached != "fetchset":
            log.debug("using cached: %s", url)
            self.showBackground(url, self.current_player_id)
        else:
            self._fetch_file(
                url,
                lambda is_set: (
                    self.setBackground(url, self.current_player_id)
                    if is_set
                    else self.showBackground(url, self.current_player_id)
                ),
            )

    def _fetch_file(self, url: str, callback: Callable[[bool], None]) -> None:
        """Asynchronously download a wallpaper from the server."""
        self.last = url

        if self.download.get(url):
            log.warn("already fetching %s, not fetching again", url)
            return

        log.debug("fetching background: %s", url)
        self.download[url] = "fetch"

        try:
            from jive.net.request_http import RequestHttp
            from jive.net.socket_http import SocketHttp
        except ImportError as exc:
            log.warn("HTTP modules not available: %s", exc)
            self.download.pop(url, None)
            return

        jnt = self._get_jnt()
        if jnt is None:
            self.download.pop(url, None)
            return

        def _sink(chunk: Any, err: Any = None) -> None:
            if err:
                log.warn("error fetching background: %s", url)
                self.download.pop(url, None)
                return
            state = self.download.get(url)
            if chunk and state in ("fetch", "fetchset"):
                log.debug("fetched background: %s", url)
                self.download[url] = chunk
                if url == self.last:
                    callback(state == "fetchset")

        req = RequestHttp(_sink, "GET", url)
        uri = req.get_uri() if hasattr(req, "get_uri") else req.getURI()  # type: ignore[attr-defined]

        host = getattr(uri, "host", "")
        port_val = getattr(uri, "port", 80)

        http = SocketHttp(jnt, host, port_val, host)
        http.fetch(req)

    # ------------------------------------------------------------------
    # Background display / persistence
    # ------------------------------------------------------------------

    def showBackground(
        self,
        wallpaper: Optional[str] = None,
        player_id: Optional[str] = None,
        force: bool = False,
    ) -> None:
        """Display a wallpaper without persisting the setting."""
        jive_main = self._get_jive_main()

        # Default player ID from skin
        skin_name = None
        if jive_main is not None:
            if hasattr(jive_main, "getSelectedSkin"):
                skin_name = jive_main.getSelectedSkin()
            elif hasattr(jive_main, "get_selected_skin"):
                skin_name = jive_main.get_selected_skin()

        if not player_id:
            player_id = skin_name

        if not wallpaper:
            settings = self.get_settings()
            if settings:
                wallpaper = settings.get(player_id)  # type: ignore[arg-type]
                if not wallpaper and skin_name:
                    wallpaper = settings.get(skin_name)

        if self.current_wallpaper == wallpaper and not force:
            return
        self.current_wallpaper = wallpaper

        srf = None

        if wallpaper and wallpaper in self.download:
            # Image in download cache
            data = self.download[wallpaper]
            if data not in ("fetch", "fetchset"):
                try:
                    from jive.ui.tile import Tile

                    srf = Tile.load_image_data(data, len(data))  # type: ignore[call-arg]
                except (ImportError, Exception) as exc:
                    log.debug("Failed to load cached image: %s", exc)

        elif wallpaper and wallpaper.startswith("http://"):
            # Saved remote image
            if player_id and self._download_prefix:
                safe_id = player_id.replace(":", "-")
                local_path = os.path.join(self._download_prefix, safe_id)
                try:
                    from jive.ui.tile import Tile

                    srf = Tile.load_image(local_path)
                except (ImportError, Exception) as exc:
                    log.debug("Failed to load remote image: %s", exc)

        elif wallpaper and wallpaper != "black":
            # Local wallpaper
            if "/" not in wallpaper and "\\" not in wallpaper:
                wallpaper = _FIRMWARE_PREFIX + wallpaper

            resolved = self._find_file(wallpaper)
            if resolved is not None:
                try:
                    from jive.ui.tile import Tile

                    srf = Tile.load_image(str(resolved))
                except (ImportError, Exception) as exc:
                    log.debug("Failed to load wallpaper: %s", exc)

        # srf = None means no background (black)
        fw = self._get_framework()
        if fw is not None:
            fw.set_background(srf)

    # Lua-compatible alias
    show_background = showBackground

    def setBackground(
        self,
        wallpaper: Optional[str] = None,
        player_id: Optional[str] = None,
        force: bool = False,
    ) -> None:
        """Set and persist the wallpaper setting."""
        jive_main = self._get_jive_main()

        if not player_id:
            if jive_main is not None:
                if hasattr(jive_main, "getSelectedSkin"):
                    player_id = jive_main.getSelectedSkin()
                elif hasattr(jive_main, "get_selected_skin"):
                    player_id = jive_main.get_selected_skin()

        log.debug("setting wallpaper for %s: %s", player_id, wallpaper)

        if wallpaper:
            # Handle downloaded wallpaper
            cached = self.download.get(wallpaper)
            if cached:
                if cached == "fetch":
                    self.download[wallpaper] = "fetchset"
                    return
                elif cached not in ("fetchset",):
                    # Save to disk
                    if player_id and self._download_prefix:
                        safe_id = player_id.replace(":", "-")
                        path = os.path.join(self._download_prefix, safe_id)
                        try:
                            os.makedirs(os.path.dirname(path), exist_ok=True)
                            with open(path, "wb") as fh:
                                log.debug("saving image to %s", path)
                                fh.write(cached)
                        except Exception as exc:
                            log.warn("unable to save image to %s: %s", path, exc)

            settings = self.get_settings()
            if settings is None:
                settings = {}
                self.set_settings(settings)
            if player_id:
                settings[player_id] = wallpaper
            self.store_settings()

        self.showBackground(wallpaper, player_id, force)

    # Lua-compatible alias
    set_background = setBackground

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def free(self) -> bool:
        jnt = self._get_jnt()
        if jnt is not None:
            jnt.unsubscribe(self)
        return True

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_download_prefix() -> str:
        """Get the directory for downloaded wallpapers."""
        try:
            from jive.applet_manager import applet_manager as _mgr

            if _mgr is not None and hasattr(_mgr, "system") and _mgr.system is not None:
                user_dir = _mgr.system.get_user_dir()
                wp_dir = os.path.join(str(user_dir), "wallpapers")
                os.makedirs(wp_dir, exist_ok=True)
                return wp_dir
        except (ImportError, AttributeError, Exception) as exc:
            log.debug(
                "_get_download_prefix: system user dir not available, using fallback: %s",
                exc,
            )

        # Fallback
        home = os.path.expanduser("~")
        wp_dir = os.path.join(home, ".jivelite", "wallpapers")
        os.makedirs(wp_dir, exist_ok=True)
        return wp_dir

    @staticmethod
    def _get_screen_size() -> Tuple[int, int]:
        """Get the current screen size."""
        try:
            from jive.ui.framework import framework

            if framework is not None:
                return framework.get_screen_size()
        except (ImportError, AttributeError) as exc:
            log.debug(
                "_get_screen_size: framework not available, using default: %s", exc
            )
        return (800, 480)  # Default JogglerSkin size

    @staticmethod
    def _find_file(relative_path: str) -> Optional[str]:
        """Find a file using the asset search paths.

        Uses ``jive.ui.surface.find_file`` which consults the search
        paths registered at startup (populated from ``System.search_paths``
        in ``JiveMain._init_ui_framework``).  Falls back to a direct
        ``os.path.isfile`` check.
        """
        try:
            from jive.ui.surface import find_file as _surface_find

            result = _surface_find(relative_path)
            if result is not None:
                return str(result)
        except (ImportError, Exception) as exc:
            log.debug("_find_file: surface find_file not available: %s", exc)
        # Direct check
        if os.path.isfile(relative_path):
            return relative_path
        return None

    @staticmethod
    def _get_jnt() -> Any:
        try:
            from jive.jive_main import jive_main as _jm

            if _jm is not None:
                return getattr(_jm, "jnt", None)
        except ImportError as exc:
            log.debug("_get_jnt: jive_main not available: %s", exc)
        return None

    @staticmethod
    def _get_framework() -> Any:
        try:
            from jive.ui.framework import framework

            return framework
        except (ImportError, AttributeError):
            return None

    @staticmethod
    def _get_jive_main() -> Any:
        try:
            from jive.jive_main import jive_main

            return jive_main
        except (ImportError, AttributeError) as exc:
            log.debug("_get_jive_main: jive_main not available: %s", exc)
        try:
            import jive.jive_main as _mod

            return getattr(_mod, "jive_main", None)
        except ImportError:
            return None

    @staticmethod
    def _get_applet_manager() -> Any:
        try:
            from jive.applet_manager import applet_manager

            return applet_manager
        except (ImportError, AttributeError):
            return None
