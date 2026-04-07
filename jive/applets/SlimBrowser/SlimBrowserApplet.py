"""
jive.applets.slim_browser.slim_browser_applet — SlimBrowser applet.

Ported from ``share/jive/applets/SlimBrowser/SlimBrowserApplet.lua``
(~3953 LOC) in the original jivelite project.

This applet implements the main music browser for Jive/jivelite. It
manages:

* Server-driven menu browsing (hierarchical menus from LMS)
* Playlist display and management
* Volume popup (via Volume helper)
* Track position scanner popup (via Scanner helper)
* Action handling for play/pause/fwd/rew/shuffle/repeat/etc.
* Text input, time input, keyboard entry for server-driven forms
* Context menus
* Connection error handling and reconnection UI
* Global action listeners for transport controls
* Artwork fetching and display

The applet maintains a "step stack" that mirrors the window stack,
where each step represents a browsing destination with its own DB,
menu, window, and sink.

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

import math
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Sequence,
    Tuple,
    Union,
)

from jive.applet import Applet
from jive.applets.SlimBrowser.db import DB
from jive.applets.SlimBrowser.scanner import Scanner
from jive.applets.SlimBrowser.volume import Volume
from jive.utils.log import logger

__all__ = ["SlimBrowserApplet"]

log = logger("applet.SlimBrowser")
logd = logger("applet.SlimBrowser.data")

# ---------------------------------------------------------------------------
# Style mapping tables (from Lua original)
# ---------------------------------------------------------------------------

# Legacy map of menuStyles to windowStyles
_MENU_TO_WINDOW: Dict[str, str] = {
    "album": "icon_list",
    "playlist": "play_list",
}

# Legacy map of item styles to new item style names
_STYLE_MAP: Dict[str, str] = {
    "itemplay": "item_play",
    "itemadd": "item_add",
    "itemNoAction": "item_no_arrow",
    "albumitem": "item",
    "albumitemplay": "item_play",
}

# Map from key codes to action names (for raw key handling)
_KEYCODE_ACTION_NAME: Dict[int, str] = {}

# Map from action strings to internal action names
_ACTION_TO_ACTION_NAME: Dict[str, str] = {
    "go_home_or_now_playing": "home",
    "pause": "pause",
    "stop": "pause-hold",
    "play": "play",
    "set_preset_0": "set-preset-0",
    "set_preset_1": "set-preset-1",
    "set_preset_2": "set-preset-2",
    "set_preset_3": "set-preset-3",
    "set_preset_4": "set-preset-4",
    "set_preset_5": "set-preset-5",
    "set_preset_6": "set-preset-6",
    "set_preset_7": "set-preset-7",
    "set_preset_8": "set-preset-8",
    "set_preset_9": "set-preset-9",
    "create_mix": "play-hold",
    "add": "more",
    "add_end": "add",
    "play_next": "add-hold",
    "go": "go",
    "go_hold": "go-hold",
}

# Map from actionName to item action alias
_ACTION_ALIAS_MAP: Dict[str, str] = {
    "play": "playAction",
    "play-hold": "playHoldAction",
    "add": "addAction",
    "go": "goAction",
}

# Populate keycode action map lazily
_KEYCODE_MAP_INITIALIZED = False


def _init_keycode_map() -> None:
    """Initialise the keycode-to-action-name map from constants."""
    global _KEYCODE_MAP_INITIALIZED, _KEYCODE_ACTION_NAME
    if _KEYCODE_MAP_INITIALIZED:
        return
    _KEYCODE_MAP_INITIALIZED = True

    try:
        from jive.ui.constants import (
            KEY_FWD,
            KEY_REW,
            KEY_VOLUME_DOWN,
            KEY_VOLUME_UP,
        )

        _KEYCODE_ACTION_NAME[KEY_VOLUME_UP] = "volup"
        _KEYCODE_ACTION_NAME[KEY_VOLUME_DOWN] = "voldown"
        _KEYCODE_ACTION_NAME[KEY_FWD] = "fwd"
        _KEYCODE_ACTION_NAME[KEY_REW] = "rew"
    except ImportError as exc:
        log.debug("_init_keycode_map: UI constants not available: %s", exc)


# ---------------------------------------------------------------------------
# Helper: safe dereference
# ---------------------------------------------------------------------------


def _safe_deref(struct: Any, *keys: str) -> Any:
    """Safely dereference a nested dict structure.

    ``_safe_deref(d, "a", "b", "c")`` is equivalent to
    ``d["a"]["b"]["c"]`` but returns ``None`` if any key is missing
    or any intermediate value is not a dict.
    """
    result = struct
    for key in keys:
        if not isinstance(result, dict):
            return None
        result = result.get(key)
        if result is None:
            return None
    return result


# ---------------------------------------------------------------------------
# Helper: stringify JSON request (for browse history)
# ---------------------------------------------------------------------------


def _stringify_json_request(json_action: Optional[Dict[str, Any]]) -> Optional[str]:
    """Turn a JSON action dict into a string for browse history."""
    if json_action is None:
        return None

    parts: List[str] = []

    cmd = json_action.get("cmd")
    if cmd and isinstance(cmd, (list, tuple)):
        for v in cmd:
            parts.append(f" {v}")

    params = json_action.get("params")
    if params and isinstance(params, dict):
        for k in sorted(params.keys()):
            v = params[k]
            if v is not None:
                parts.append(f" {k}:{v}")

    return "".join(parts)


# ---------------------------------------------------------------------------
# Helper: priority assign
# ---------------------------------------------------------------------------


def _priority_assign(key: str, default: Any, *tables: Optional[Dict[str, Any]]) -> Any:
    """Return the first non-None value of ``table[key]`` from the given tables."""
    for table in tables:
        if table is not None and isinstance(table, dict):
            val = table.get(key)
            if val is not None:
                return val
    return default


# ---------------------------------------------------------------------------
# Helper: get new start value for chunked loading
# ---------------------------------------------------------------------------


def _get_new_start_value(index: Optional[int]) -> int:
    """Return the block-aligned start value for a given index."""
    if index is None:
        return 0
    return (index // DB.get_block_size()) * DB.get_block_size()


# ---------------------------------------------------------------------------
# Helper: get time format from SetupDateTime applet
# ---------------------------------------------------------------------------


def _get_time_format() -> str:
    """Return the current time format setting ('12' or '24').

    Loads ``setupDateTimeSettings`` from the applet manager and returns
    the ``hours`` value.  Falls back to ``'12'`` if unavailable.
    """
    try:
        from jive.applet_manager import applet_manager

        if applet_manager is not None:
            settings = applet_manager.call_service("setupDateTimeSettings")
            if settings and isinstance(settings, dict) and settings.get("hours"):
                return str(settings["hours"])
    except (ImportError, AttributeError) as exc:
        log.debug("_get_time_format: setupDateTimeSettings not available: %s", exc)
    return "12"


# ---------------------------------------------------------------------------
# Step dict factory
# ---------------------------------------------------------------------------


def _make_step(
    origin: Optional[Dict[str, Any]] = None,
    window: Any = None,
    menu: Any = None,
    db: Optional[DB] = None,
    sink: Optional[Callable[..., Any]] = None,
    data: Any = None,
    action_modifier: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a new step dict."""
    return {
        "origin": origin,
        "destination": None,
        "window": window,
        "menu": menu,
        "db": db,
        "sink": sink,
        "data": data,
        "cancelled": False,
        "loaded": None,
        "actionModifier": action_modifier or None,
        "commandString": None,
        "lastBrowseIndexUsed": False,
        "jsonAction": None,
        "simpleMenu": None,
        "_isNpChildWindow": False,
    }


# ============================================================================
# SlimBrowserApplet
# ============================================================================


class SlimBrowserApplet(Applet):
    """Browse music and control players.

    This is the main applet that drives the server-driven menu system.
    It manages the step stack, playlist display, volume popup, scanner
    popup, and all transport-control action listeners.
    """

    def __init__(self) -> None:
        super().__init__()

        # The string helper (set in init)
        self._string_fn: Optional[Callable[[str], Any]] = None

        # Current player and server
        self._player: Any = None
        self._server: Any = None

        # Error state
        self._network_error: Any = False
        self._server_error: bool = False
        self._diag_window: Any = False

        # Step stack (path of enlightenment)
        self._step_stack: List[Dict[str, Any]] = []

        # Player key handler reference (for removal)
        self._player_key_handler: Any = None

        # Action listener handles (for removal)
        self._action_listener_handles: Optional[List[Any]] = None

        # Last entered text
        self._last_input: str = ""
        self._input_params: Dict[str, Any] = {}

        # Status step (playlist)
        self._status_step: Any = None
        self._empty_step: Any = None

        # Volume and Scanner helpers
        self.volume: Optional[Volume] = None
        self.scanner: Optional[Scanner] = None

        # Server error window
        self.server_error_window: Any = None

        # Cached volume for fixed-volume handling
        self.cached_volume: Optional[int] = None

        # In-setup flag for SN signup
        self.in_setup: bool = False

    # ==================================================================
    # Initialisation
    # ==================================================================

    def init(self) -> None:
        """Initialise the applet."""
        super().init()

        self._string_fn = lambda token: self.string(token)

        # Subscribe to notifications
        try:
            from jive.jive_main import jive_main as _jm

            if _jm is not None:
                jnt = getattr(_jm, "jnt", None)
                if jnt is not None:
                    jnt.subscribe(self)
        except ImportError as exc:
            log.error("init: failed to subscribe to jnt: %s", exc, exc_info=True)

        # Create Volume and Scanner helpers
        self.volume = Volume(self)
        self.scanner = Scanner(self)

    # ==================================================================
    # String helper
    # ==================================================================

    def _str(self, token: str) -> str:
        """Get a localised string."""
        if self._string_fn is not None:
            result = self._string_fn(token)
            return str(result) if result is not None else token
        return token

    # ==================================================================
    # Step stack management
    # ==================================================================

    def _get_current_step(self) -> Optional[Dict[str, Any]]:
        """Return the current (top) step, or ``None``."""
        if not self._step_stack:
            return None
        return self._step_stack[-1]

    def _push_step(self, step: Dict[str, Any]) -> None:
        """Push a step onto the step stack."""
        # Context menu windows auto-hide, but step/window stack gets out
        # of order unless we close any CM before pushing
        window = step.get("window")
        if window is not None:
            is_cm = False
            if hasattr(window, "isContextMenu"):
                is_cm = window.isContextMenu()
            elif hasattr(window, "is_context_menu"):
                is_cm = window.is_context_menu()
            if not is_cm:
                try:
                    from jive.ui.window import Window

                    Window.hideContextMenus()  # type: ignore[attr-defined]
                except (ImportError, AttributeError) as exc:
                    log.debug("_push_step: hideContextMenus not available: %s", exc)

        # Remove duplicate (like window:hide does)
        if step in self._step_stack:
            self._step_stack.remove(step)

        self._step_stack.append(step)

        if log.isEnabledFor(10):  # DEBUG
            log.debug("Pushed step, stack size: %d", len(self._step_stack))

    def _pop_step(self) -> Optional[Dict[str, Any]]:
        """Pop the top step from the step stack."""
        if not self._step_stack:
            return None
        popped = self._step_stack.pop()
        if log.isEnabledFor(10):
            log.debug("Popped step, stack size: %d", len(self._step_stack))
        return popped

    def _get_parent_step(self) -> Optional[Dict[str, Any]]:
        """Return the parent (second from top) step."""
        if len(self._step_stack) < 2:
            return None
        return self._step_stack[-2]

    def _get_grandparent_step(self) -> Optional[Dict[str, Any]]:
        """Return the grandparent (third from top) step."""
        if len(self._step_stack) < 3:
            return None
        return self._step_stack[-3]

    # ==================================================================
    # Menu item update helper
    # ==================================================================

    def _step_set_menu_items(
        self, step: Dict[str, Any], data: Optional[Dict[str, Any]] = None
    ) -> None:
        """Set items on the step's menu from the DB."""
        menu = step.get("menu")
        db = step.get("db")
        if menu is not None and db is not None:
            result = db.menu_items(data)
            if hasattr(menu, "setItems"):
                menu.setItems(step, *result)
            elif hasattr(menu, "set_items"):
                menu.set_items(step, *result)

    # ==================================================================
    # Step lock handler
    # ==================================================================

    def _step_lock_handler(
        self,
        step: Optional[Dict[str, Any]],
        loaded_callback: Callable[[], None],
        skip_menu_lock: bool = False,
    ) -> None:
        """Set up menu locking and the loaded callback for a step."""
        if step is None:
            return

        current_step = self._get_current_step()

        if current_step is not None and not skip_menu_lock:
            menu = current_step.get("menu")
            if menu is not None and hasattr(menu, "lock"):
                menu.lock(lambda: step.__setitem__("cancelled", True))
            simple_menu = current_step.get("simpleMenu")
            if simple_menu is not None and hasattr(simple_menu, "lock"):
                simple_menu.lock(lambda: step.__setitem__("cancelled", True))

        def _loaded() -> None:
            if current_step is not None:
                menu = current_step.get("menu")
                if menu is not None and hasattr(menu, "unlock"):
                    menu.unlock()
                simple_menu = current_step.get("simpleMenu")
                if simple_menu is not None and hasattr(simple_menu, "unlock"):
                    simple_menu.unlock()
            loaded_callback()

        step["loaded"] = _loaded

    def _push_to_new_window(
        self, step: Dict[str, Any], skip_menu_lock: bool = False
    ) -> None:
        """Push a step, showing its window when data is loaded."""
        self._step_lock_handler(
            step,
            lambda: self._do_push_and_show(step),
            skip_menu_lock,
        )

    def _do_push_and_show(self, step: Dict[str, Any]) -> None:
        """Actually push the step and show the window."""
        self._push_step(step)
        window = step.get("window")
        if window is not None and hasattr(window, "show"):
            window.show()

    # ==================================================================
    # Window spec
    # ==================================================================

    def _new_window_spec(
        self,
        db: Optional[DB],
        item: Dict[str, Any],
        is_context_menu: bool = False,
    ) -> Dict[str, Any]:
        """Create a window spec from DB chunk and item."""
        log.debug("_new_window_spec()")

        b_window = None
        i_window = _safe_deref(item, "window")

        if db is not None:
            chunk = db.chunk()
            b_window = _safe_deref(chunk, "base", "window")

        help_text = _safe_deref(item, "window", "help", "text")

        # Determine style
        menu_style = _priority_assign("menuStyle", "", i_window, b_window)
        window_style = (
            i_window.get("windowStyle") if i_window else None
        ) or _MENU_TO_WINDOW.get(menu_style, "text_list")
        window_id = None
        if b_window:
            window_id = b_window.get("windowId")
        if i_window and window_id is None:
            window_id = i_window.get("windowId")

        # JIVELITE special case: playlist override
        if item.get("type") == "playlist":
            window_style = "play_list"

        return {
            "isContextMenu": is_context_menu,
            "windowId": window_id,
            "windowStyle": window_style,
            "labelTitleStyle": "title",
            "menuStyle": "menu",
            "labelItemStyle": "item",
            "help": help_text,
            "text": _priority_assign("text", item.get("text"), i_window, b_window),
            "icon-id": _priority_assign(
                "icon-id", item.get("icon-id"), i_window, b_window
            ),
            "icon": _priority_assign("icon", item.get("icon"), i_window, b_window),
        }

    # ==================================================================
    # Decide first chunk
    # ==================================================================

    def _decide_first_chunk(
        self, step: Dict[str, Any], json_action: Dict[str, Any]
    ) -> Tuple[int, int]:
        """Figure out the from/qty values for the initial request."""
        qty = DB.get_block_size()

        if self._player is None:
            return (0, qty)

        is_context_menu = False
        window = step.get("window")
        if window is not None:
            if hasattr(window, "isContextMenu"):
                is_context_menu = window.isContextMenu()
            elif hasattr(window, "is_context_menu"):
                is_context_menu = window.is_context_menu()

        command_string = _stringify_json_request(json_action)
        last_browse = None
        if hasattr(self._player, "getLastBrowse"):
            last_browse = self._player.getLastBrowse(command_string)
        elif hasattr(self._player, "get_last_browse"):
            last_browse = self._player.get_last_browse(command_string)

        step["commandString"] = command_string

        from_val = 0

        log.debug("Saving json command to browse history: %s", command_string)

        # Don't save browse history for context menus or searches
        if (
            last_browse is not None
            and not is_context_menu
            and (command_string is None or "search:" not in command_string)
            and (command_string is None or "mode:randomalbums" not in command_string)
        ):
            last_index = None
            if hasattr(self._player, "getLastBrowseIndex"):
                last_index = self._player.getLastBrowseIndex(command_string)
            elif hasattr(self._player, "get_last_browse_index"):
                last_index = self._player.get_last_browse_index(command_string)
            from_val = _get_new_start_value(last_index)
        else:
            last_browse = {"index": 1}
            if hasattr(self._player, "setLastBrowse"):
                self._player.setLastBrowse(command_string, last_browse)
            elif hasattr(self._player, "set_last_browse"):
                self._player.set_last_browse(command_string, last_browse)

        log.debug(
            "lastBrowse index was: %s",
            last_browse.get("index") if last_browse else None,
        )
        step["lastBrowseIndexUsed"] = False

        # Don't use lastBrowse index if position is first element
        last_index = None
        if hasattr(self._player, "getLastBrowseIndex"):
            last_index = self._player.getLastBrowseIndex(command_string)
        elif hasattr(self._player, "get_last_browse_index"):
            last_index = self._player.get_last_browse_index(command_string)

        if last_index == 1:
            if hasattr(self._player, "setLastBrowseIndex"):
                self._player.setLastBrowseIndex(command_string, None)
            elif hasattr(self._player, "set_last_browse_index"):
                self._player.set_last_browse_index(command_string, None)

        return (from_val, qty)

    # ==================================================================
    # Artwork handling
    # ==================================================================

    def _artwork_item(
        self,
        step: Dict[str, Any],
        item: Dict[str, Any],
        group: Any = None,
        menu_accel: bool = False,
    ) -> None:
        """Update a group widget with the artwork for an item."""
        if self._server is None:
            return

        icon = None
        if group is not None and hasattr(group, "getWidget"):
            icon = group.getWidget("icon")
        elif group is not None and hasattr(group, "get_widget"):
            icon = group.get_widget("icon")

        # Determine icon size
        icon_size = 40  # default THUMB_SIZE
        try:
            from jive.jive_main import jive_main as _jm

            if _jm is not None:
                icon_size = _jm.get_skin_param("THUMB_SIZE") or 40
                # Check for playlist style
                if icon is not None and hasattr(icon, "getStyle"):
                    if icon.getStyle() == "icon_no_artwork_playlist":
                        ps = _jm.get_skin_param_or_nil("THUMB_SIZE_PLAYLIST")
                        if ps is not None:
                            icon_size = ps
        except (ImportError, AttributeError) as exc:
            log.debug("_update_artwork: could not get skin THUMB_SIZE: %s", exc)

        icon_id = item.get("icon-id") or item.get("icon")

        if icon_id is not None:
            if menu_accel:
                # Don't load artwork while accelerated
                if hasattr(self._server, "artworkThumbCached"):
                    if not self._server.artworkThumbCached(icon_id, icon_size):
                        if hasattr(self._server, "cancelArtwork") and icon is not None:
                            self._server.cancelArtwork(icon)
                        return
            # Fetch artwork
            if hasattr(self._server, "fetchArtwork") and icon is not None:
                self._server.fetchArtwork(icon_id, icon, icon_size)
        elif (
            item.get("trackType") == "radio"
            and isinstance(item.get("params"), dict)
            and item["params"].get("track_id") is not None
        ):
            track_id = item["params"]["track_id"]
            if menu_accel:
                if hasattr(self._server, "artworkThumbCached"):
                    if not self._server.artworkThumbCached(track_id, icon_size):
                        if hasattr(self._server, "cancelArtwork") and icon is not None:
                            self._server.cancelArtwork(icon)
                        return
            if hasattr(self._server, "fetchArtwork") and icon is not None:
                self._server.fetchArtwork(track_id, icon, icon_size, "png")
        else:
            if hasattr(self._server, "cancelArtwork") and icon is not None:
                self._server.cancelArtwork(icon)

    # ==================================================================
    # Button helpers
    # ==================================================================

    @staticmethod
    def _back_button() -> Any:
        """Create a default back button."""
        try:
            from jive.ui.window import Window

            return Window.createDefaultLeftButton()  # type: ignore[attr-defined]
        except (ImportError, AttributeError):
            return None

    @staticmethod
    def _invisible_button() -> Any:
        """Create an invisible (placeholder) button."""
        try:
            from jive.ui.group import Group
            from jive.ui.icon import Icon

            return Group("button_none", {"icon": Icon("icon")})
        except ImportError:
            return None

    @staticmethod
    def _now_playing_button(absolute: bool = False) -> Any:
        """Create a Now Playing button for the title bar."""
        if not absolute:
            try:
                from jive.ui.window import Window

                return Window.createDefaultRightButton()  # type: ignore[attr-defined]
            except (ImportError, AttributeError):
                return None

        try:
            from jive.ui.button import Button
            from jive.ui.constants import EVENT_CONSUME
            from jive.ui.framework import framework as _fw
            from jive.ui.group import Group
            from jive.ui.icon import Icon

            return Button(
                Group("button_go_now_playing", {"icon": Icon("icon")}),
                lambda: (
                    _fw.pushAction("go_now_playing") if _fw else None,
                    EVENT_CONSUME,
                )[-1],
                lambda: (
                    _fw.pushAction("title_right_hold") if _fw else None,
                    EVENT_CONSUME,
                )[-1],
                lambda: (
                    _fw.pushAction("soft_reset") if _fw else None,
                    EVENT_CONSUME,
                )[-1],
            )
        except ImportError:
            return None

    # ==================================================================
    # Perform JSON action
    # ==================================================================

    def _perform_json_action(
        self,
        json_action: Dict[str, Any],
        from_val: Optional[int],
        qty: Optional[int],
        step: Optional[Dict[str, Any]],
        sink: Optional[Callable[..., Any]],
        item_type: Optional[str] = None,
        cached_response: Any = None,
    ) -> None:
        """Perform a JSON action — send a command to the server."""
        log.debug("_perform_json_action(from=%s, qty=%s)", from_val, qty)

        use_cached = cached_response is not None and isinstance(cached_response, dict)

        cmd_array = json_action.get("cmd")
        if not cmd_array or not isinstance(cmd_array, (list, tuple)):
            log.error("JSON action has no cmd or not of type list")
            return

        # Replace player if needed
        player_id = json_action.get("player")
        if self._player is not None and (player_id is None or str(player_id) == "0"):
            if hasattr(self._player, "getId"):
                player_id = self._player.getId()
            elif hasattr(self._player, "get_id"):
                player_id = self._player.get_id()

        # Process input parameter keys
        new_params: List[str] = []

        input_param_keys = json_action.get("inputParamKeys")
        if input_param_keys and isinstance(input_param_keys, dict):
            for k, v in input_param_keys.items():
                new_params.append(f"{k}:{v}")

        # Process params, looking for __INPUT__ substitution
        params = json_action.get("params")
        if params and isinstance(params, dict):
            new_params = []
            for k, v in params.items():
                if v == "__INPUT__":
                    new_params.append(self._last_input)
                elif v == "__TAGGEDINPUT__":
                    new_params.append(f"{k}:{self._last_input}")
                elif v is not None:
                    new_params.append(f"{k}:{v}")
            # Tell SC to give response including context menu handler
            new_params.append("useContextMenu:1")

        # Build the request
        request: List[Any] = list(cmd_array)

        # Always include from/qty positional params for browse-type
        # commands.  LMS expects these before tagged params; omitting
        # them can cause the server to return zero results.
        if from_val is not None:
            request.append(from_val)
            if qty is not None:
                request.append(qty)
        elif new_params:
            # Default from/qty so the server processes tagged params
            # correctly (matches Lua behaviour where nil inserts are
            # effectively 0 in the JSON-RPC positional array).
            request.append(0)
            request.append(200)

        for p in new_params:
            request.append(p)

        if step is not None:
            step["jsonAction"] = request

        # Handle slideshow type
        if item_type == "slideshow" or (params and params.get("slideshow")):
            request.append("slideshow:1")

            server_data = {
                "id": " ".join(str(x) for x in request),
                "playerId": player_id,
                "cmd": request,
                "server": self._server,
                "allowMotion": True,
            }

            try:
                from jive.applet_manager import applet_manager

                if applet_manager is not None:
                    applet_manager.call_service(
                        "openRemoteScreensaver", True, server_data
                    )
            except (ImportError, AttributeError) as exc:
                log.error(
                    "_perform_json_action: failed to open remote screensaver: %s",
                    exc,
                    exc_info=True,
                )

            current_step = self._get_current_step()
            if current_step is not None:
                menu = current_step.get("menu")
                if menu is not None and hasattr(menu, "unlock"):
                    menu.unlock()
            return

        # Check for network error
        if self._network_error:
            has_tiny_sc = False
            try:
                from jive.system import System

                has_tiny_sc = System.hasTinySC()  # type: ignore[attr-defined]
            except (ImportError, AttributeError) as exc:
                log.debug(
                    "_perform_json_action: System.hasTinySC not available: %s", exc
                )

            sc_running = False
            try:
                from jive.applet_manager import applet_manager

                if applet_manager is not None:
                    sc_running = applet_manager.call_service("isBuiltInSCRunning")
            except (ImportError, AttributeError) as exc:
                log.debug(
                    "_perform_json_action: isBuiltInSCRunning not available: %s", exc
                )

            if not (has_tiny_sc and sc_running):
                log.warn("_networkError is not False, push error window for diags")
                current_step = self._get_current_step()
                try:
                    from jive.applet_manager import applet_manager

                    if applet_manager is not None:
                        self._diag_window = applet_manager.call_service(
                            "networkTroubleshootingMenu", self._network_error
                        )
                        if self._diag_window:
                            if current_step is not None:
                                menu = current_step.get("menu")
                                if menu is not None and hasattr(menu, "unlock"):
                                    menu.unlock()
                            return
                except (ImportError, AttributeError) as exc:
                    log.error(
                        "_perform_json_action: failed to show network troubleshooting menu: %s",
                        exc,
                        exc_info=True,
                    )

        # Send the command
        if not use_cached:
            if self._server is not None and hasattr(self._server, "userRequest"):
                self._server.userRequest(sink, player_id, request)
            else:
                log.error("Cannot send: server=%s", self._server is not None)
        else:
            log.info("using cachedResponse")
            if sink is not None:
                sink(cached_response)

    # ==================================================================
    # Refresh helpers
    # ==================================================================

    def _refresh_json_action(self, step: Dict[str, Any]) -> None:
        """Re-run the JSON request that created a step's menu."""
        if self._player is None:
            return

        json_action = step.get("jsonAction")
        if json_action is None:
            log.warn("No jsonAction request defined for this step")
            return

        player_id = None
        if hasattr(self._player, "getId"):
            player_id = self._player.getId()
        elif hasattr(self._player, "get_id"):
            player_id = self._player.get_id()
        if player_id is None:
            log.warn("no player!")
            return

        sink = step.get("sink")
        if self._server is not None and hasattr(self._server, "userRequest"):
            self._server.userRequest(sink, player_id, json_action)

    def _refresh_me(self, set_selected_index: Optional[int] = None) -> None:
        """Refresh the current step."""
        step = self._get_current_step()
        if step is not None:
            self._refresh_json_action(step)
            if step.get("menu") and set_selected_index is not None:
                menu = step["menu"]
                if hasattr(menu, "setSelectedIndex"):
                    menu.setSelectedIndex(set_selected_index)
                step["lastBrowseIndexUsed"] = set_selected_index

    def _refresh_origin(self, set_selected_index: Optional[int] = None) -> None:
        """Refresh the parent step."""
        step = self._get_parent_step()
        if step is not None:
            self._refresh_json_action(step)
            if step.get("menu") and set_selected_index is not None:
                menu = step["menu"]
                if hasattr(menu, "setSelectedIndex"):
                    menu.setSelectedIndex(set_selected_index)
                step["lastBrowseIndexUsed"] = set_selected_index
            # Bug 16336: remove simpleMenu overlay
            if step.get("window") and step.get("simpleMenu"):
                log.warn("removing simpleMenu overlay when refreshing origin")
                window = step["window"]
                if hasattr(window, "removeWidget"):
                    window.removeWidget(step["simpleMenu"])

    def _refresh_grandparent(self, set_selected_index: Optional[int] = None) -> None:
        """Refresh the grandparent step."""
        step = self._get_grandparent_step()
        if step is not None:
            self._refresh_json_action(step)
            if step.get("menu") and set_selected_index is not None:
                menu = step["menu"]
                if hasattr(menu, "setSelectedIndex"):
                    menu.setSelectedIndex(set_selected_index)
                step["lastBrowseIndexUsed"] = set_selected_index

    # ==================================================================
    # Hide helpers
    # ==================================================================

    def _hide_me(
        self,
        no_refresh: bool = False,
        silent: bool = False,
        set_selected_index: Optional[int] = None,
    ) -> None:
        """Hide the top window and optionally refresh the parent."""
        if not silent:
            try:
                from jive.ui.framework import framework as _fw

                if _fw is not None and hasattr(_fw, "playSound"):
                    _fw.playSound("WINDOWHIDE")
            except ImportError as exc:
                log.debug("_hide_me: framework not available for playSound: %s", exc)

        current = self._get_current_step()
        if current is not None:
            window = current.get("window")
            if window is not None and hasattr(window, "hide"):
                window.hide()

        # Hiding triggers a POP event which calls _pop_step,
        # so the current step is now the parent
        if not no_refresh:
            current = self._get_current_step()
            if current is not None:
                self._refresh_json_action(current)
                if current.get("menu") and set_selected_index is not None:
                    menu = current["menu"]
                    if hasattr(menu, "setSelectedIndex"):
                        menu.setSelectedIndex(set_selected_index)

    def _hide_me_and_my_dad(self, set_selected_index: Optional[int] = None) -> None:
        """Hide the top window and the parent below it."""
        self._hide_me(no_refresh=True)
        self._hide_me(set_selected_index=set_selected_index)

    def _hide_to_x(
        self, window_id: str, set_selected_index: Optional[int] = None
    ) -> None:
        """Hide all windows back to the named window."""
        log.debug("_hide_to_x, x=%s", window_id)

        while True:
            current = self._get_current_step()
            if current is None:
                break
            window = current.get("window")
            if window is None:
                break
            win_id = None
            if hasattr(window, "getWindowId"):
                win_id = window.getWindowId()
            elif hasattr(window, "get_window_id"):
                win_id = window.get_window_id()
            if win_id == window_id:
                break
            log.info("hiding %s", win_id)
            if hasattr(window, "hide"):
                window.hide()

        current = self._get_current_step()
        if current is not None:
            window = current.get("window")
            if window is not None:
                win_id = None
                if hasattr(window, "getWindowId"):
                    win_id = window.getWindowId()
                elif hasattr(window, "get_window_id"):
                    win_id = window.get_window_id()
                if win_id == window_id:
                    log.info("refreshing window: %s", window_id)
                    self._refresh_json_action(current)
                    if current.get("menu") and set_selected_index is not None:
                        menu = current["menu"]
                        if hasattr(menu, "setSelectedIndex"):
                            menu.setSelectedIndex(set_selected_index)

    # ==================================================================
    # Navigation helpers
    # ==================================================================

    def _go_now_playing(
        self,
        transition: Any = None,
        silent: bool = False,
        direct: bool = False,
    ) -> None:
        """Navigate to the Now Playing screen."""
        try:
            from jive.ui.window import Window

            Window.hideContextMenus()  # type: ignore[attr-defined]
        except (ImportError, AttributeError) as exc:
            log.debug("_go_now_playing: hideContextMenus not available: %s", exc)

        # Hide NP child windows on top
        while True:
            current = self._get_current_step()
            if current is None or not current.get("_isNpChildWindow"):
                break
            log.info("Hiding NP child window")
            self._hide_me(no_refresh=True, silent=True)

        if transition is None:
            try:
                from jive.ui.window import Window

                transition = getattr(Window, "transitionPushLeft", None)
            except ImportError as exc:
                log.debug(
                    "_go_now_playing: Window not available for transition: %s", exc
                )

        if not silent:
            try:
                from jive.ui.framework import framework as _fw

                if _fw is not None and hasattr(_fw, "playSound"):
                    _fw.playSound("WINDOWSHOW")
            except ImportError as exc:
                log.debug(
                    "_go_now_playing: framework not available for playSound: %s", exc
                )

        try:
            from jive.applet_manager import applet_manager

            if applet_manager is not None:
                applet_manager.call_service("goNowPlaying", transition, direct)
        except (ImportError, AttributeError) as exc:
            log.error(
                "_go_now_playing: failed to call goNowPlaying service: %s",
                exc,
                exc_info=True,
            )

    def _go_playlist(self, silent: bool = False) -> None:
        """Navigate to the playlist screen."""
        if not silent:
            try:
                from jive.ui.framework import framework as _fw

                if _fw is not None and hasattr(_fw, "playSound"):
                    _fw.playSound("WINDOWSHOW")
            except ImportError as exc:
                log.debug(
                    "_go_playlist: framework not available for playSound: %s", exc
                )
        self.show_playlist()

    def _go_now(self, destination: str, transition: Any = None) -> None:
        """Navigate immediately to a particular destination."""
        if transition is None:
            try:
                from jive.ui.window import Window

                transition = getattr(Window, "transitionPushRight", None)
            except ImportError as exc:
                log.debug("_go_now: Window not available for transition: %s", exc)

        if destination == "nowPlaying":
            self._go_now_playing(transition)
        elif destination == "home":
            self.go_home()
        elif destination == "playlist":
            self._go_playlist()

    # ==================================================================
    # Browse sink
    # ==================================================================

    def _browse_sink(
        self,
        step: Dict[str, Any],
        chunk: Optional[Dict[str, Any]],
        err: Optional[str] = None,
    ) -> None:
        """Sink that processes browsing data for a step."""

        if step.get("cancelled"):
            log.debug("_browse_sink: cancelled — ignoring response")
            return

        # Call loaded callback
        loaded = step.get("loaded")
        if loaded is not None:
            loaded()
            step["loaded"] = None

        if chunk is not None:
            data = chunk.get("result") or chunk.get("data")

            if data is None:
                return

            if data.get("goNow") and step.get("window"):
                self._go_now(data["goNow"])

            # Handle network error
            if data.get("networkerror"):
                window = step.get("window")
                menu = step.get("menu")
                if menu is not None and window is not None:
                    if hasattr(window, "removeWidget"):
                        window.removeWidget(menu)
                if window is not None and hasattr(window, "setTitle"):
                    window.setTitle(
                        self._str("SLIMBROWSER_PROBLEM_CONNECTING"),
                        "settingstitle",
                    )
                return

            # Slider rendering
            if (
                data
                and data.get("count")
                and int(data["count"]) == 1
                and data.get("item_loop")
                and isinstance(data["item_loop"], list)
                and len(data["item_loop"]) > 0
                and data["item_loop"][0].get("slider")
            ):
                menu = step.get("menu")
                if menu is not None and step.get("window"):
                    if hasattr(step["window"], "removeWidget"):
                        step["window"].removeWidget(menu)
                self._render_slider(step, data["item_loop"][0])
                return

            # Empty count
            if (
                step.get("menu")
                and data
                and data.get("count") is not None
                and int(data["count"]) == 0
            ):
                # Handle textarea-only case
                if step.get("window") and data.get("window", {}).get("textarea"):
                    menu = step.get("menu")
                    window = step["window"]
                    if menu is not None and hasattr(window, "removeWidget"):
                        window.removeWidget(menu)
                return

            # Normal menu processing
            if step.get("menu") and data:
                # JIVELITE: override server playlist style
                if step.get("window"):
                    window = step["window"]
                    win_style = None
                    if hasattr(window, "getStyle"):
                        win_style = window.getStyle()
                    if win_style == "play_list":
                        data_window = data.get("window", {})
                        if data_window.get("windowStyle") == "icon_list":
                            log.debug("overriding server playlist window style")
                            data_window["windowStyle"] = "play_list"

                self._step_set_menu_items(step, data)

                # Setup window
                setup_window = _safe_deref(data, "base", "window", "setupWindow")
                if setup_window and step.get("window"):
                    if hasattr(step["window"], "setAllowScreensaver"):
                        step["window"].setAllowScreensaver(False)

                # Window ID
                if data.get("window", {}).get("windowId") and step.get("window"):
                    window = step["window"]
                    wid = data["window"]["windowId"]
                    if hasattr(window, "setWindowId"):
                        window.setWindowId(wid)

                # What's missing?
                db = step.get("db")
                if db is not None and self._player is not None:
                    last_browse_index = None
                    cmd_str = step.get("commandString")
                    if hasattr(self._player, "getLastBrowseIndex"):
                        last_browse_index = self._player.getLastBrowseIndex(cmd_str)
                    elif hasattr(self._player, "get_last_browse_index"):
                        last_browse_index = self._player.get_last_browse_index(cmd_str)

                    missing = db.missing(last_browse_index)
                    if missing is not None:
                        from_val, qty_val = missing
                        step_data = step.get("data")
                        if step_data is not None:
                            self._perform_json_action(
                                step_data,
                                from_val,
                                qty_val,
                                step,
                                step.get("sink"),
                            )
        else:
            if err:
                log.error(err)

    # ==================================================================
    # Render slider
    # ==================================================================

    def _render_slider(self, step: Dict[str, Any], item: Dict[str, Any]) -> None:
        """Render a slider widget for a server-driven slider item."""
        log.debug("_render_slider()")

        window = step.get("window")
        if window is None:
            return

        min_val = int(item.get("min", 0))
        max_val = int(item.get("max", 100))
        adjust = int(item.get("adjust", 0))
        initial = item.get("initial")
        if initial is not None:
            slider_initial = int(initial) + adjust
        else:
            slider_initial = min_val + adjust

        slider_min = min_val + adjust
        slider_max = max_val + adjust

        try:
            from jive.ui.button import Button
            from jive.ui.constants import EVENT_CONSUME, EVENT_SCROLL
            from jive.ui.framework import framework as _fw
            from jive.ui.group import Group
            from jive.ui.icon import Icon
            from jive.ui.slider import Slider
            from jive.ui.textarea import Textarea
        except ImportError:
            log.info("_render_slider: UI not available")
            return

        do_action = _safe_deref(item, "actions", "do")

        def _slider_callback(
            slider_widget: Any, value: int, done: bool = False
        ) -> None:
            if do_action is not None:
                valtag = _safe_deref(item, "actions", "do", "params", "valtag")
                if valtag:
                    item["actions"]["do"]["params"][valtag] = value - adjust
                self._perform_json_action(do_action, None, None, None, None)

        slider = Slider(
            "settings_slider", slider_min, slider_max, slider_initial, _slider_callback
        )

        if item.get("text"):
            text = Textarea("text", item["text"])
            window.addWidget(text)
        if item.get("help"):
            help_widget = Textarea("help_text", item["help"])
            window.addWidget(help_widget)

        slider_style = "settings_slider_group"
        if item.get("sliderIcons") == "volume":
            slider_style = "settings_volume_group"

        def _scroll_down() -> int:
            from jive.ui.event import Event

            e = Event(EVENT_SCROLL, rel=-1)
            if _fw is not None and hasattr(_fw, "dispatchEvent"):
                _fw.dispatchEvent(slider, e)
            return EVENT_CONSUME

        def _scroll_up() -> int:
            from jive.ui.event import Event

            e = Event(EVENT_SCROLL, rel=1)
            if _fw is not None and hasattr(_fw, "dispatchEvent"):
                _fw.dispatchEvent(slider, e)
            return EVENT_CONSUME

        window.addWidget(
            Group(
                slider_style,
                {
                    "div1": Icon("div1"),
                    "div2": Icon("div2"),
                    "down": Button(Icon("down"), _scroll_down),  # type: ignore[dict-item]
                    "slider": slider,
                    "up": Button(Icon("up"), _scroll_up),  # type: ignore[dict-item]
                },
            )
        )

    # ==================================================================
    # Input-in-progress popup
    # ==================================================================

    @staticmethod
    def _input_in_progress(msg: Optional[str] = None) -> None:
        """Show a 'waiting' popup while text-input action completes.

        Mirrors Lua ``_inputInProgress``.
        """
        try:
            from jive.ui.icon import Icon
            from jive.ui.label import Label
            from jive.ui.popup import Popup

            popup = Popup("waiting_popup")
            icon = Icon("icon_connecting")
            popup.addWidget(icon)  # type: ignore[attr-defined]
            if msg:
                label = Label("text", msg)
                popup.addWidget(label)  # type: ignore[attr-defined]
            popup.show()
        except ImportError:
            log.info("_input_in_progress: UI not available, msg=%s", msg)

    # camelCase alias
    _inputInProgress = _input_in_progress

    # ==================================================================
    # Browse input (text input / keyboard for server-driven forms)
    # ==================================================================

    def _browse_input(
        self,
        window: Any,
        item: Dict[str, Any],
        db: DB,
        input_spec: Optional[Dict[str, Any]],
        last: Any = None,
        time_format: Optional[str] = None,
    ) -> bool:
        """Render a text-input / keyboard for SlimBrowser input.

        Mirrors Lua ``_browseInput``.  Creates the appropriate input
        widget (time, IP address, or general text) inside *window* and
        wires up the submit callback to ``_action_handler``.

        Returns ``True`` if the title widget was fully configured.
        """
        title_widget_complete = False

        if input_spec is None:
            log.error("_browse_input: no input spec")
            return False

        # Never allow screensavers in an input window
        if hasattr(window, "setAllowScreensaver"):
            window.setAllowScreensaver(False)
        if input_spec.get("title") and hasattr(window, "setTitle"):
            window.setTitle(input_spec["title"])

        # Title bar buttons
        now_playing_button = None
        if input_spec.get("setupWindow") == 1:
            now_playing_button = self._invisible_button()
        else:
            now_playing_button = self._now_playing_button()

        title_text = None
        if hasattr(window, "getTitle"):
            title_text = window.getTitle()
        if input_spec.get("title"):
            title_text = input_spec["title"]

        if title_text:
            title_widget_complete = True

        try:
            from jive.ui.group import Group
            from jive.ui.label import Label

            new_title_widget = Group(
                "title",
                {
                    "text": Label("text", title_text or ""),
                    "lbutton": self._back_button(),
                    "rbutton": now_playing_button,
                },
            )
            if hasattr(window, "setTitleWidget"):
                window.setTitleWidget(new_title_widget)
        except ImportError:
            log.info("_browse_input: Group/Label not available for title widget")

        # Make sure len is numeric
        input_len = input_spec.get("len")
        if input_len is not None:
            try:
                input_spec["len"] = int(input_len)
            except (TypeError, ValueError):
                input_spec["len"] = 0

        # Default allowedChars
        if not input_spec.get("allowedChars"):
            kb_type = input_spec.get("_kbType", "")
            if kb_type and "email" in kb_type:
                input_spec["allowedChars"] = self._str("ALLOWEDCHARS_EMAIL")
            else:
                input_spec["allowedChars"] = self._str("ALLOWEDCHARS_WITHCAPS")

        v = ""
        initial_text = input_spec.get("initialText")
        input_style = input_spec.get("_inputStyle")

        if initial_text is not None:
            v = str(initial_text)

        # Time input is handled specially
        if input_style == "time":
            log.info(
                "_browse_input: time input requested (stub — full Timeinput not ported)"
            )
            # Time input requires the Timeinput widget which may not be
            # fully available.  Log and return.
            return True

        try:
            from jive.ui.group import Group
            from jive.ui.keyboard import Keyboard
            from jive.ui.textinput import Textinput
        except ImportError:
            log.info("_browse_input: Textinput/Keyboard widgets not available")
            return title_widget_complete

        # Build the input value
        input_value: Any = v
        if input_style == "ip":
            if not initial_text:
                initial_text = ""
            if hasattr(Textinput, "ip_address_value"):
                input_value = Textinput.ip_address_value(initial_text)
            elif hasattr(Textinput, "ipAddressValue"):
                input_value = Textinput.ipAddressValue(initial_text)
        elif input_spec.get("len") and int(input_spec["len"]) > 0:
            if hasattr(Textinput, "text_value"):
                input_value = Textinput.text_value(v, int(input_spec["len"]), 200)
            elif hasattr(Textinput, "textValue"):
                input_value = Textinput.textValue(v, int(input_spec["len"]), 200)

        # Create text input widget
        def _on_text_complete(_ti: Any, value: Any) -> bool:
            self._last_input = str(value)
            item["_inputDone"] = str(value)

            # Show processing popup if requested
            display_popup = _safe_deref(input_spec, "processingPopup")
            display_popup_text = _safe_deref(input_spec, "processingPopup", "text")
            if display_popup:
                self._input_in_progress(display_popup_text)

            # Perform the action
            self._action_handler(None, None, db, 0, None, "go", item)

            # Close the text input if this is a "do" action
            do_action = _safe_deref(item, "actions", "do")
            next_window = item.get("nextWindow")

            if do_action and not next_window:
                if hasattr(window, "playSound"):
                    window.playSound("WINDOWHIDE")
                if hasattr(window, "hide"):
                    window.hide()
            else:
                if hasattr(window, "playSound"):
                    window.playSound("WINDOWSHOW")
            return True

        text_input = Textinput(
            "textinput",
            input_value,
            _on_text_complete,
            input_spec.get("allowedChars"),
        )

        # Keyboard
        kb_type = input_spec.get("_kbType", "qwerty")
        if kb_type == "qwertyLower":
            kb_type = "qwerty"
        keyboard = Keyboard("keyboard", kb_type, text_input)
        backspace = Keyboard.backspace()
        group = Group(
            "keyboard_textinput",
            {"textinput": text_input, "backspace": backspace},
        )

        if hasattr(window, "addWidget"):
            window.addWidget(group)
            window.addWidget(keyboard)
        if hasattr(window, "focusWidget"):
            window.focusWidget(group)

        return title_widget_complete

    # camelCase alias
    _browseInput = _browse_input

    # ==================================================================
    # New destination
    # ==================================================================

    def _new_destination(
        self,
        origin: Optional[Dict[str, Any]],
        item: Optional[Dict[str, Any]],
        window_spec: Dict[str, Any],
        sink_fn: Callable[..., Any],
        data: Any = None,
        container_context_menu: Any = None,
    ) -> Tuple[Dict[str, Any], Callable[..., Any]]:
        """Create a new browsing destination (step + sink)."""
        log.debug("_new_destination()")

        db = DB(window_spec)

        window = None
        try:
            if window_spec.get("isContextMenu"):
                from jive.ui.contextmenuwindow import ContextMenuWindow

                window = ContextMenuWindow("", window_spec.get("windowId"))
            else:
                from jive.ui.window import Window

                window = Window(  # type: ignore[assignment]
                    window_spec.get("windowStyle", "text_list"),
                    None,
                    None,
                    window_spec.get("windowId"),
                )
        except ImportError:
            log.info("_new_destination: UI not available, using stub window")
            window = _WindowStub(window_spec)  # type: ignore[assignment]

        menu = None
        if item is None or not item.get("input") or item.get("_inputDone"):
            # Create a Menu for browsing
            try:
                from jive.ui.menu import Menu

                menu = Menu(
                    db.menu_style(),
                    lambda m, s, w, tri, trs: self._browse_menu_renderer(
                        m, s, w, tri, trs
                    ),
                    lambda m, s, mi, dbi, evt: self._browse_menu_listener(
                        m, s, mi, dbi, evt
                    ),
                    lambda m, s, dbi, dbv: self._browse_menu_available(m, s, dbi, dbv),
                )
            except ImportError:
                menu = _MenuStub(db.menu_style())  # type: ignore[assignment]

            if window is not None and hasattr(window, "addWidget"):
                window.addWidget(menu)

        # Create the step
        step = _make_step(
            origin=origin,
            window=window,
            menu=menu,
            db=db,
            data=data,
        )

        # Set title widget
        if not window_spec.get("isContextMenu") and window is not None:
            text = window_spec.get("text", "")
            if hasattr(window, "setTitle") and text:
                window.setTitle(text)

        # Set up menu items
        if step.get("menu"):
            self._step_set_menu_items(step)

        # Window pop listener
        if window is not None and hasattr(window, "addListener"):
            try:
                from jive.ui.constants import EVENT_WINDOW_POP

                def _on_pop(evt: Any) -> None:
                    if item is not None:
                        item["_inputDone"] = None
                    step["cancelled"] = True
                    log.debug("EVENT_WINDOW_POP called")
                    self._pop_step()

                window.addListener(EVENT_WINDOW_POP, _on_pop)  # type: ignore[arg-type]
            except ImportError as exc:
                log.warning(
                    "_new_destination: EVENT_WINDOW_POP constant not available: %s", exc
                )

        # Create sink closure
        def _sink(chunk: Any, err: Any = None) -> None:
            sink_fn(step, chunk, err)

        step["sink"] = _sink

        return step, _sink

    def _empty_destination(
        self, step: Optional[Dict[str, Any]] = None
    ) -> Tuple[Dict[str, Any], Callable[..., Any]]:
        """Create a no-op destination that handles cancellation and loaded."""
        new_step: Dict[str, Any] = _make_step()

        def _sink(chunk: Any = None, err: Any = None) -> None:
            if new_step.get("cancelled"):
                log.debug("_devnull(): action cancelled")
                return
            loaded = new_step.get("loaded")
            if loaded is not None:
                loaded()
                new_step["loaded"] = None

        new_step["sink"] = _sink
        return new_step, _sink

    # ==================================================================
    # Widget factories for interactive menu items
    # ==================================================================

    def _checkbox_item(self, item: Dict[str, Any], db: DB) -> Any:
        """Return a Checkbox widget for *item*, creating it if needed.

        Mirrors Lua ``_checkboxItem``.  The checkbox fires 'on'/'off'
        actions through ``_action_handler`` when toggled.
        """
        checkbox_flag = item.get("checkbox")
        if checkbox_flag is None:
            return item.get("_jive_button")
        try:
            checkbox_flag = int(checkbox_flag)
        except (TypeError, ValueError):
            return item.get("_jive_button")

        if item.get("_jive_button") is None:
            try:
                from jive.ui.checkbox import Checkbox

                def _cb_callback(_cb: Any, is_selected: bool) -> None:
                    log.debug("checkbox updated: %s", is_selected)
                    if is_selected:
                        log.info("ON: %s", is_selected)
                        self._action_handler(None, None, db, 0, None, "on", item)
                    else:
                        log.info("OFF: %s", is_selected)
                        self._action_handler(None, None, db, 0, None, "off", item)

                item["_jive_button"] = Checkbox(
                    "checkbox",
                    _cb_callback,
                    checkbox_flag == 1,
                )
            except ImportError:
                log.info("_checkbox_item: Checkbox widget not available")
        return item.get("_jive_button")

    # camelCase alias
    _checkboxItem = _checkbox_item

    def _choice_item(self, item: Dict[str, Any], db: DB) -> Any:
        """Return a Choice widget for *item*, creating it if needed.

        Mirrors Lua ``_choiceItem``.  The choice widget fires the
        ``do.choices[index]`` action through ``_action_handler``.
        """
        choice_flag = item.get("selectedIndex")
        if choice_flag is None:
            return item.get("_jive_button")
        try:
            choice_flag = int(choice_flag)
        except (TypeError, ValueError):
            return item.get("_jive_button")

        choice_actions = _safe_deref(item, "actions", "do", "choices")
        if choice_actions is None:
            return item.get("_jive_button")

        if item.get("_jive_button") is None:
            try:
                from jive.ui.choice import Choice

                choice_strings = item.get("choiceStrings", [])

                def _choice_callback(_ch: Any, index: int) -> None:
                    log.info("Choice callback called: %s", index)
                    self._action_handler(None, None, db, 0, None, "do", item, index)

                item["_jive_button"] = Choice(
                    "choice",
                    choice_strings,
                    _choice_callback,
                    choice_flag,
                )
            except ImportError:
                log.info("_choice_item: Choice widget not available")
        return item.get("_jive_button")

    # camelCase alias
    _choiceItem = _choice_item

    def _radio_item(self, item: Dict[str, Any], db: DB) -> Any:
        """Return a RadioButton widget for *item*, creating it if needed.

        Mirrors Lua ``_radioItem``.  The radio button fires the 'do'
        action through ``_action_handler`` when selected.
        """
        radio_flag = item.get("radio")
        if radio_flag is None:
            return item.get("_jive_button")
        try:
            radio_flag = int(radio_flag)
        except (TypeError, ValueError):
            return item.get("_jive_button")

        if item.get("_jive_button") is None:
            try:
                from jive.ui.radio import RadioButton

                radio_group = db.get_radio_group()

                def _radio_callback(*args: Any) -> None:
                    log.info("Radio callback called")
                    self._action_handler(None, None, db, 0, None, "do", item)

                item["_jive_button"] = RadioButton(
                    "radio",
                    radio_group,
                    _radio_callback,
                    radio_flag == 1,
                )
            except ImportError:
                log.info("_radio_item: RadioButton widget not available")
        return item.get("_jive_button")

    # camelCase alias
    _radioItem = _radio_item

    # ==================================================================
    # Browse menu callbacks (renderer, listener, available)
    # ==================================================================

    def _decorated_label(
        self,
        group: Any,
        label_style: str,
        item: Optional[Dict[str, Any]],
        step: Dict[str, Any],
        menu_accel: bool = False,
        show_icons: bool = True,
    ) -> Any:
        """Create or update a Group widget for a menu item.

        Mirrors Lua ``_decoratedLabel`` in SlimBrowserApplet.lua.
        """
        from jive.ui.group import Group
        from jive.ui.icon import Icon
        from jive.ui.label import Label

        db = step.get("db")
        window_style = db.window_style() if db is not None else ""

        # Determine if we should use a Textarea instead of Label
        use_textarea = window_style == "multiline_text_list"

        if group is None:
            if label_style == "title":
                # Title group has back/NP buttons instead of arrow/check
                group = Group(
                    label_style,
                    {
                        "text": Label("text", ""),
                        "icon": Icon("icon"),
                        "lbutton": self._back_button(),
                        "rbutton": self._now_playing_button(),
                    },
                )
            elif use_textarea:
                try:
                    from jive.ui.textarea import Textarea

                    textarea = Textarea("multiline_text", "")
                    if hasattr(textarea, "set_hide_scrollbar"):
                        textarea.set_hide_scrollbar(True)
                    elif hasattr(textarea, "setHideScrollbar"):
                        textarea.setHideScrollbar(True)
                    if hasattr(textarea, "set_is_menu_child"):
                        textarea.set_is_menu_child(True)
                    elif hasattr(textarea, "setIsMenuChild"):
                        textarea.setIsMenuChild(True)
                    group = Group(
                        label_style,
                        {
                            "icon": Icon("icon"),
                            "text": textarea,
                            "arrow": Icon("arrow"),
                            "check": Icon("check"),
                        },
                    )
                except ImportError:
                    # Textarea not available, fall back to Label
                    text_label = Label("text", "")
                    group = Group(
                        label_style,
                        {
                            "text": text_label,
                            "icon": Icon("icon"),
                            "arrow": Icon("arrow"),
                            "check": Icon("check"),
                        },
                    )
            else:
                # Standard item group with text, icon, arrow, check
                text_label = Label("text", "")
                group = Group(
                    label_style,
                    {
                        "text": text_label,
                        "icon": Icon("icon"),
                        "arrow": Icon("arrow"),
                        "check": Icon("check"),
                    },
                )

        # Update the group with item data
        if item is not None:
            # Textarea items get a context-menu action for full text
            if use_textarea:
                try:
                    from jive.ui.constants import EVENT_CONSUME
                except ImportError:
                    EVENT_CONSUME = 0x02  # type: ignore[assignment]

                def _more_action(*_a: Any, **_kw: Any) -> int:
                    try:
                        from jive.ui.contextmenuwindow import ContextMenuWindow
                        from jive.ui.textarea import Textarea as _Ta
                        from jive.ui.window import Window as _W

                        cmw = ContextMenuWindow("")
                        txt = _Ta("multiline_text", item.get("text", ""))
                        if hasattr(cmw, "addWidget"):
                            cmw.addWidget(txt)
                        elif hasattr(cmw, "add_widget"):
                            cmw.add_widget(txt)
                        if hasattr(cmw, "setShowFrameworkWidgets"):
                            cmw.setShowFrameworkWidgets(False)
                        elif hasattr(cmw, "set_show_framework_widgets"):
                            cmw.set_show_framework_widgets(False)
                        if hasattr(cmw, "show"):
                            cmw.show(getattr(_W, "transitionFadeIn", None))
                    except ImportError:
                        pass
                    return EVENT_CONSUME

                if hasattr(group, "addActionListener"):
                    group.addActionListener("add", step, _more_action)
                    group.addActionListener("go", step, _more_action)
                elif hasattr(group, "add_action_listener"):
                    group.add_action_listener("add", step, _more_action)
                    group.add_action_listener("go", step, _more_action)

            text = item.get("text", "")
            try:
                group.set_widget_value("text", text)
            except (KeyError, AttributeError) as exc:
                log.debug("_decorated_label: failed to set text widget value: %s", exc)

            # Determine the icon style based on window type
            icon_style = "icon_no_artwork"
            if window_style == "play_list":
                icon_style = "icon_no_artwork_playlist"

            if show_icons:
                # Set "no artwork" icon unless it's already the right style
                icon_widget = group.get_widget("icon")
                if icon_widget is not None:
                    cur_style = ""
                    if hasattr(icon_widget, "get_style"):
                        cur_style = icon_widget.get_style() or ""
                    elif hasattr(icon_widget, "getStyle"):
                        cur_style = icon_widget.getStyle() or ""
                    if cur_style != icon_style:
                        group.set_widget("icon", Icon(icon_style))

            # Set acceleration key (for fast-scrolling letter jumps)
            accel_key = item.get("textkey")
            if accel_key is None and isinstance(item.get("params"), dict):
                accel_key = item["params"].get("textkey")
            if accel_key is not None and hasattr(group, "set_accel_key"):
                group.set_accel_key(accel_key)
            elif accel_key is not None and hasattr(group, "setAccelKey"):
                group.setAccelKey(accel_key)

            # Handle checkbox / radio / choice items
            if item.get("radio"):
                group._type = "radio"
                group.set_widget("check", self._radio_item(item, db))  # type: ignore[arg-type]
            elif item.get("checkbox"):
                group._type = "checkbox"
                group.set_widget("check", self._checkbox_item(item, db))  # type: ignore[arg-type]
            elif item.get("selectedIndex"):
                group._type = "choice"
                group.set_widget("check", self._choice_item(item, db))  # type: ignore[arg-type]
            else:
                # Clear previous type if any
                if getattr(group, "_type", None):
                    if show_icons:
                        group.set_widget("icon", Icon(icon_style))
                    group._type = None
                # Fetch artwork for this item
                self._artwork_item(step, item, group, menu_accel)

            group.set_style(label_style)
        else:
            # No data yet — clear type and show waiting placeholder
            if getattr(group, "_type", None):
                icon_style = "icon_no_artwork"
                if window_style == "play_list":
                    icon_style = "icon_no_artwork_playlist"
                if show_icons:
                    group.set_widget("icon", Icon(icon_style))
                group._type = None

            try:
                group.set_widget_value("text", "")
            except (KeyError, AttributeError) as exc:
                log.debug(
                    "_decorated_label: failed to clear text widget value: %s", exc
                )
            group.set_style(label_style + "waiting_popup")

        return group

    def _browse_menu_renderer(
        self,
        menu: Any,
        step: Dict[str, Any],
        widgets: Any,
        to_render_indexes: Any,
        to_render_size: int,
    ) -> None:
        """Render menu items for the browsing menu."""
        db = step.get("db")
        if db is None:
            log.warning("_browse_menu_renderer: db is None in step, skipping render")
            return

        label_item_style = db.label_item_style()

        log.debug(
            "_browse_menu_renderer: to_render_size=%d indexes=%s "
            "db.count=%d db.current_index=%d label_item_style=%s "
            "window_style=%s widgets_len=%d",
            to_render_size,
            to_render_indexes[:10]
            if isinstance(to_render_indexes, (list, tuple))
            else to_render_indexes,
            db.count,
            db.current_index,
            label_item_style,
            db.window_style(),
            len(widgets),
        )

        menu_accel = False
        accel_dir = 0
        if hasattr(menu, "isAccelerated"):
            result = menu.isAccelerated()
            if isinstance(result, tuple) and len(result) >= 2:
                menu_accel, accel_dir = result[0], result[1]
            else:
                menu_accel = bool(result)

        if menu_accel and self._server is not None:
            if hasattr(self._server, "cancelAllArtwork"):
                self._server.cancelAllArtwork()

        window_style = db.window_style()
        show_icons = window_style != "text_list"

        for widget_index in range(to_render_size):
            if isinstance(to_render_indexes, (list, tuple)):
                if widget_index >= len(to_render_indexes):
                    continue
                db_index = to_render_indexes[widget_index]
            else:
                db_index = None

            if db_index is not None:
                item_data, current = db.item(db_index)

                style = label_item_style
                if current:
                    style = "albumcurrent"
                elif item_data and item_data.get("style"):
                    style = item_data["style"]

                # Support legacy styles
                if style in _STYLE_MAP:
                    style = _STYLE_MAP[style]
                if item_data and (
                    item_data.get("checkbox")
                    or item_data.get("radio")
                    or item_data.get("selectedIndex")
                ):
                    style = "item_choice"

                # Get or create the widget for this slot
                existing = (
                    widgets[widget_index] if widget_index < len(widgets) else None
                )

                log.debug(
                    "_browse_menu_renderer: widget_index=%d db_index=%d "
                    "style=%s current=%s has_data=%s text=%s",
                    widget_index,
                    db_index,
                    style,
                    current,
                    item_data is not None,
                    (item_data.get("text", "")[:40] if item_data else "N/A"),
                )

                widget = self._decorated_label(
                    existing, style, item_data, step, menu_accel, show_icons
                )
                # Store in widgets list
                if widget_index < len(widgets):
                    widgets[widget_index] = widget
                else:
                    while len(widgets) <= widget_index:
                        widgets.append(None)
                    widgets[widget_index] = widget

        # -- Preload artwork in the direction of scrolling ----------------
        # Matches Lua _browseMenuRenderer L2455-2471:
        #   Fetches artwork for the next screenful of items (without a
        #   widget) so the cache is warm when the user scrolls.
        if menu_accel or to_render_size == 0:
            return

        if isinstance(to_render_indexes, (list, tuple)) and to_render_indexes:
            if accel_dir > 0:
                start_index = (
                    to_render_indexes[to_render_size - 1]
                    if to_render_size <= len(to_render_indexes)
                    else to_render_indexes[-1]
                )
            else:
                first_idx = to_render_indexes[0] if to_render_indexes else 0
                start_index = first_idx - to_render_size

            for db_index in range(start_index, start_index + to_render_size):
                if db_index < 0:
                    continue
                try:
                    item_data, _current = db.item(db_index)
                except Exception:
                    item_data = None
                if item_data:
                    self._artwork_item(step, item_data, None, False)

    def _browse_menu_listener(
        self,
        menu: Any,
        step: Dict[str, Any],
        menu_item: Any,
        db_index: int,
        event: Any,
    ) -> int:
        """Handle events for the browsing menu."""
        db = step.get("db")
        if db is None:
            try:
                from jive.ui.constants import EVENT_UNUSED

                return EVENT_UNUSED
            except ImportError:
                return 0

        try:
            from jive.ui.constants import (
                ACTION,
                EVENT_ACTION,
                EVENT_CONSUME,
                EVENT_FOCUS_GAINED,
                EVENT_FOCUS_LOST,
                EVENT_HIDE,
                EVENT_KEY_HOLD,
                EVENT_KEY_PRESS,
                EVENT_SHOW,
                EVENT_UNUSED,
            )
        except ImportError:
            return 0

        evt_type = 0
        if hasattr(event, "getType"):
            evt_type = event.getType()
        elif hasattr(event, "get_type"):
            evt_type = event.get_type()
        elif hasattr(event, "type"):
            evt_type = event.type

        # Ignore focus and show/hide events
        if evt_type in (
            EVENT_FOCUS_GAINED,
            EVENT_FOCUS_LOST,
            EVENT_HIDE,
            EVENT_SHOW,
        ):
            # Track browse history on focus gained
            if evt_type == EVENT_FOCUS_GAINED and self._player is not None:
                cmd_str = step.get("commandString")
                if hasattr(self._player, "getLastBrowse"):
                    if self._player.getLastBrowse(cmd_str):
                        selected_index = None
                        if step.get("menu") and hasattr(
                            step["menu"], "getSelectedIndex"
                        ):
                            selected_index = step["menu"].getSelectedIndex()
                        if selected_index is not None:
                            if hasattr(self._player, "setLastBrowseIndex"):
                                self._player.setLastBrowseIndex(cmd_str, selected_index)
            return EVENT_UNUSED

        # Ignore events not on the current window
        current = self._get_current_step()
        if current is not None and current.get("menu") is not menu:
            log.error("Ignoring: not visible or step/window stack out of sync")
            return EVENT_UNUSED

        item_data, _ = db.item(db_index)

        # Check for preview action
        if (
            item_data
            and isinstance(item_data.get("actions"), dict)
            and item_data["actions"].get("preview")
        ):
            if evt_type == ACTION:
                action_name = ""
                if hasattr(event, "getAction"):
                    action_name = event.getAction() or ""
                action_name = _ACTION_TO_ACTION_NAME.get(action_name, "")
                if action_name in ("play", "more"):
                    return self._action_handler(
                        menu, menu_item, db, db_index, event, "preview", item_data
                    )

        # Don't handle events for active decoration widgets
        if item_data and item_data.get("_jive_button"):
            return EVENT_UNUSED

        # EVENT_ACTION (go action)
        if evt_type == EVENT_ACTION:
            if item_data is not None:
                # Check for local function
                func = item_data.get("_go")
                if func is not None:
                    if menu_item is not None and hasattr(menu_item, "playSound"):
                        menu_item.playSound("WINDOWSHOW")
                    return func()  # type: ignore[no-any-return]
                return self._action_handler(
                    menu, menu_item, db, db_index, event, "go", item_data
                )

        # ACTION type
        elif evt_type == ACTION:
            action_str = ""
            if hasattr(event, "getAction"):
                action_str = event.getAction() or ""
            elif hasattr(event, "get_action"):
                action_str = event.get_action() or ""
            action_name = _ACTION_TO_ACTION_NAME.get(action_str)  # type: ignore[assignment]
            if action_name is not None:
                return self._action_handler(
                    menu, menu_item, db, db_index, event, action_name, item_data
                )

        # KEY_PRESS
        elif evt_type == EVENT_KEY_PRESS:
            keycode = 0
            if hasattr(event, "getKeycode"):
                keycode = event.getKeycode()
            _init_keycode_map()
            action_name = _KEYCODE_ACTION_NAME.get(keycode)  # type: ignore[assignment]
            if action_name is not None:
                return self._action_handler(
                    menu, menu_item, db, db_index, event, action_name, item_data
                )

        # KEY_HOLD
        elif evt_type == EVENT_KEY_HOLD:
            keycode = 0
            if hasattr(event, "getKeycode"):
                keycode = event.getKeycode()
            _init_keycode_map()
            action_name = _KEYCODE_ACTION_NAME.get(keycode)  # type: ignore[assignment]
            if action_name is not None:
                return self._action_handler(
                    menu,
                    menu_item,
                    db,
                    db_index,
                    event,
                    action_name + "-hold",
                    item_data,
                )

        return EVENT_UNUSED

    def _browse_menu_available(
        self,
        menu: Any,
        step: Dict[str, Any],
        db_index: int,
        db_visible: int,
    ) -> bool:
        """Check if the requested range of items is available."""
        db = step.get("db")
        if db is None:
            return False

        min_index = max(1, db_index)
        max_index = min(db_index + db_visible, db.size())

        item_min, _ = db.item(min_index)
        item_max, _ = db.item(max_index)

        return item_min is not None and item_max is not None

    # ==================================================================
    # Action handler
    # ==================================================================

    def _action_handler(
        self,
        menu: Any,
        menu_item: Any,
        db: DB,
        db_index: int,
        event: Any,
        action_name: str,
        item: Optional[Dict[str, Any]] = None,
        selected_index: Optional[int] = None,
    ) -> int:
        """Sort out the action business: item action, base action, default."""
        log.debug("_action_handler(%s)", action_name)

        try:
            from jive.ui.constants import EVENT_CONSUME, EVENT_UNUSED
        except ImportError:
            EVENT_CONSUME = 0x02  # type: ignore[assignment]
            EVENT_UNUSED = 0x00  # type: ignore[assignment]

        # Some actions work even with no item around
        if item is not None:
            chunk = db.chunk()

            # Handle 'action': 'none'
            if item.get("action") == "none":
                return EVENT_UNUSED

            # Get nextWindow params
            b_next_window = _safe_deref(chunk, "base", "nextWindow")
            i_next_window = item.get("nextWindow")

            # setSelectedIndex
            b_set_index = _safe_deref(chunk, "base", "setSelectedIndex")
            i_set_index = item.get("setSelectedIndex")

            # onClick
            b_on_click = _safe_deref(chunk, "base", "onClick")
            i_on_click = item.get("onClick")
            on_click = i_on_click or b_on_click

            b_action = None
            i_action = None
            on_action = None
            off_action = None
            choice_action = None
            use_next_window = False

            action_handlers_exist = (
                item.get("actions") is not None
                or _safe_deref(chunk, "base", "actions") is not None
            )
            if (
                (i_next_window or b_next_window)
                and not action_handlers_exist
                and action_name == "go"
            ):
                use_next_window = True

            # Handle action aliases
            alias_name = _ACTION_ALIAS_MAP.get(action_name)
            if alias_name is not None:
                alias_action = item.get(alias_name)
                if alias_action is not None:
                    action_name = alias_action
                    log.debug("item action after transform: %s", action_name)

            # Special cases for 'go' action
            if action_name == "go":
                # Hierarchical menu or input
                if item.get("count") or (
                    item.get("input") and not item.get("_inputDone")
                ):
                    log.debug("_action_handler(%s): hierarchical or input", action_name)
                    if menu_item is not None and hasattr(menu_item, "playSound"):
                        menu_item.playSound("WINDOWSHOW")

                    window_spec = self._new_window_spec(db, item)
                    step, sink = self._new_destination(
                        self._get_current_step(),
                        item,
                        window_spec,
                        self._browse_sink,
                    )
                    self._push_to_new_window(step)

                    res = {"result": item}
                    self._browse_sink(step, res)
                    return EVENT_CONSUME

                # Local service call
                local_service = _safe_deref(item, "actions", "go", "localservice")
                if local_service:
                    log.debug("_action_handler calling %s", local_service)
                    if menu_item is not None and hasattr(menu_item, "playSound"):
                        menu_item.playSound("WINDOWSHOW")
                    try:
                        from jive.applet_manager import applet_manager

                        if applet_manager is not None:
                            applet_manager.call_service(
                                local_service, {"text": item.get("text")}
                            )
                    except (ImportError, AttributeError) as exc:
                        log.error(
                            "_action_handler: failed to call local service %s: %s",
                            local_service,
                            exc,
                            exc_info=True,
                        )
                    return EVENT_CONSUME

                # Check for 'do' action (overrides 'go')
                b_action = _safe_deref(chunk, "base", "actions", "do")
                i_action = _safe_deref(item, "actions", "do")
                on_action = _safe_deref(item, "actions", "on")
                off_action = _safe_deref(item, "actions", "off")

            elif action_name == "preview":
                b_action = _safe_deref(chunk, "base", "actions", "preview")
                i_action = _safe_deref(item, "actions", "preview")

            # Determine isContextMenu flag (Lua computes this after
            # action_name aliasing, before the main if-block).
            is_context_menu = _safe_deref(
                item, "actions", action_name, "params", "isContextMenu"
            ) or _safe_deref(
                chunk, "base", "actions", action_name, "window", "isContextMenu"
            )

            choice_action = _safe_deref(item, "actions", "do", "choices")

            # Check for a regular action
            if not (i_action or b_action or on_action or off_action or choice_action):
                b_action = _safe_deref(chunk, "base", "actions", action_name)
                i_action = _safe_deref(item, "actions", action_name)
            elif action_name != "preview":
                action_name = "do"

            # nextWindow on the action
            a_next_window = _safe_deref(
                item, "actions", action_name, "nextWindow"
            ) or _safe_deref(chunk, "base", "actions", action_name, "nextWindow")
            a_set_index = _safe_deref(
                item, "actions", action_name, "setSelectedIndex"
            ) or _safe_deref(chunk, "base", "actions", action_name, "setSelectedIndex")

            next_window = a_next_window or i_next_window or b_next_window

            set_index = a_set_index or i_set_index or b_set_index
            if set_index is not None:
                try:
                    set_index = int(set_index)
                except (TypeError, ValueError):
                    set_index = None

            # Default to 'refresh' with setSelectedIndex
            if set_index is not None and not next_window:
                next_window = "refresh"

            if i_action or b_action or choice_action or next_window:
                json_action = None

                # Choice action
                if choice_action and selected_index is not None:
                    json_action = _safe_deref(
                        item,
                        "actions",
                        action_name,
                        "choices",
                        selected_index,  # type: ignore[arg-type]
                    )
                elif i_action:
                    log.debug("_action_handler(%s): item action", action_name)
                    if isinstance(i_action, dict):
                        json_action = i_action
                elif b_action:
                    log.debug("_action_handler(%s): base action", action_name)
                    if isinstance(b_action, dict):
                        json_action = dict(b_action)  # copy to avoid mutation

                        # Complete from item params
                        param_name = json_action.get("itemsParams")
                        if param_name and isinstance(param_name, str):
                            i_params = item.get(param_name)
                            if i_params and isinstance(i_params, dict):
                                params = json_action.get("params")
                                if params is None:
                                    params = {}
                                    json_action["params"] = params
                                for k, v in i_params.items():
                                    params[k] = v
                            else:
                                log.debug(
                                    "No %s entry in item, no action taken",
                                    param_name,
                                )
                                return EVENT_UNUSED

                # Now we may have found a command
                if json_action is not None or use_next_window:
                    log.debug("_action_handler(%s): json action", action_name)

                    if menu_item is not None and not (
                        next_window and next_window == "home"
                    ):
                        if hasattr(menu_item, "playSound"):
                            menu_item.playSound("WINDOWSHOW")

                    skip_push = False
                    step_new: Optional[Dict[str, Any]] = None
                    sink_new: Optional[Callable[..., Any]] = None
                    from_val: Optional[int] = None
                    qty_val: Optional[int] = None

                    # Handle special nextWindow values
                    if next_window == "nowPlaying":
                        skip_push = True
                        step_new, sink_new = self._empty_destination()
                        self._step_lock_handler(
                            step_new,
                            lambda: self._go_now_playing(None, True, True),
                        )

                    elif next_window == "playlist":
                        self._go_playlist(silent=True)
                    elif next_window == "home":
                        if item.get("serverLinked") and self._server is not None:
                            try:
                                from jive.net.network_thread import jnt  # type: ignore[attr-defined]

                                if jnt is not None:
                                    jnt.notify("serverLinked", self._server, True)
                            except (ImportError, AttributeError) as exc:
                                log.error(
                                    "_action_handler: failed to notify serverLinked: %s",
                                    exc,
                                    exc_info=True,
                                )
                        self.go_home()

                    elif next_window == "parentNoRefresh":
                        self._hide_me(no_refresh=True, set_selected_index=set_index)
                    elif next_window == "parent":
                        self._hide_me(set_selected_index=set_index)
                    elif next_window == "grandparent":
                        current = self._get_current_step()
                        is_cm = False
                        if current and current.get("window"):
                            w = current["window"]
                            if hasattr(w, "isContextMenu"):
                                is_cm = w.isContextMenu()
                        if is_cm:
                            try:
                                from jive.ui.window import Window

                                Window.hideContextMenus()  # type: ignore[attr-defined]
                            except (ImportError, AttributeError) as exc:
                                log.debug(
                                    "_action_handler: hideContextMenus not available: %s",
                                    exc,
                                )
                            self._refresh_me(set_index)
                        else:
                            self._hide_me_and_my_dad(set_index)
                    elif on_click == "refreshGrandparent":
                        self._refresh_grandparent(set_index)
                    elif next_window == "refreshOrigin" or on_click == "refreshOrigin":
                        self._refresh_origin(set_index)
                    elif next_window == "refresh" or on_click == "refreshMe":
                        self._refresh_me(set_index)
                    elif next_window:
                        from_val, qty_val = 0, 200
                        self._hide_to_x(next_window, set_index)

                    elif action_name in ("go", "play-hold"):
                        is_cm = is_context_menu
                        step_new, sink_new = self._new_destination(
                            self._get_current_step(),
                            item,
                            self._new_window_spec(db, item, bool(is_cm)),
                            self._browse_sink,
                            json_action,
                        )
                        if step_new.get("menu"):
                            from_val, qty_val = self._decide_first_chunk(
                                step_new,
                                json_action,  # type: ignore[arg-type]
                            )
                    elif (
                        action_name == "more"
                        or (
                            action_name == "add"
                            and (
                                item.get("addAction") == "more"
                                or _safe_deref(chunk, "base", "addAction") == "more"
                            )
                        )
                        or is_context_menu
                    ):
                        log.debug("Context Menu")
                        # Bug 14061: send command flag to have XMLBrowser
                        # fork CM response off to get playback controls
                        if json_action is not None and isinstance(json_action, dict):
                            params = json_action.get("params")
                            if params and isinstance(params, dict):
                                params["xmlBrowseInterimCM"] = 1
                        is_cm = is_context_menu
                        step_new, sink_new = self._new_destination(
                            self._get_current_step(),
                            item,
                            self._new_window_spec(db, item, bool(is_cm)),
                            self._browse_sink,
                            json_action,
                        )
                        if step_new.get("menu"):
                            from_val, qty_val = self._decide_first_chunk(
                                step_new,
                                json_action,  # type: ignore[arg-type]
                            )

                    if json_action is not None:
                        if not skip_push and step_new is not None:
                            self._push_to_new_window(step_new)
                        self._perform_json_action(
                            json_action,
                            from_val,
                            qty_val,
                            step_new,
                            sink_new,
                        )
                    else:
                        if sink_new is not None:
                            sink_new()
                        elif not next_window:
                            log.warn("No json action and no sink")

                    return EVENT_CONSUME

        # Fallback to built-in actions
        current = self._get_current_step()
        if current is not None and current.get("actionModifier"):
            built_in = action_name + current["actionModifier"]
            func = self._get_default_action(built_in)
            if func is not None:
                log.debug("_action_handler(%s): built-in", built_in)
                return func(menu, menu_item, db, db_index, event, built_in, item)  # type: ignore[no-any-return]

        func = self._get_default_action(action_name)
        if func is not None:
            log.debug("_action_handler(%s): built-in", action_name)
            return func(menu, menu_item, db, db_index, event, action_name, item)  # type: ignore[no-any-return]

        return EVENT_UNUSED

    # ==================================================================
    # Alarm preview window
    # ==================================================================

    def _alarm_preview_window(self, title: str) -> int:
        """Show a preview popup for an alarm sound.

        Mirrors Lua ``_alarmPreviewWindow``.  Displays the alarm title
        and a 'Done' button that stops the preview and hides the window.
        """
        try:
            from jive.ui.constants import EVENT_CONSUME, EVENT_WINDOW_POP
            from jive.ui.group import Group
            from jive.ui.icon import Icon
            from jive.ui.label import Label
            from jive.ui.simplemenu import SimpleMenu
            from jive.ui.window import Window
        except ImportError:
            log.info("_alarm_preview_window: UI not available")
            return 0x02  # EVENT_CONSUME fallback

        window = Window("alarm_popup", self._str("SLIMBROWSER_ALARM_PREVIEW"))
        icon = Icon("icon_alarm")
        label = Label("preview_text", title)
        header_group = Group("alarm_header", {"icon": icon, "time": label})

        def _hide_action(*args: Any) -> int:
            log.warn("hide alarm preview")
            if hasattr(window, "hide"):
                window.hide(getattr(Window, "transitionNone", None))
            return EVENT_CONSUME

        def _window_pop_action(evt: Any = None) -> int:
            log.warn("window goes pop!")
            if self._player is not None and hasattr(self._player, "stopPreview"):
                self._player.stopPreview()
            return EVENT_CONSUME

        menu = SimpleMenu("menu")
        menu.addItem(
            {
                "text": self._str("SLIMBROWSER_DONE"),
                "sound": "WINDOWHIDE",
                "callback": _hide_action,
            }
        )

        if hasattr(window, "ignoreAllInputExcept"):
            window.ignoreAllInputExcept(
                [
                    "go",
                    "back",
                    "go_home",
                    "go_home_or_now_playing",
                    "volume_up",
                    "volume_down",
                    "stop",
                    "pause",
                    "power",
                ]
            )

        if hasattr(window, "addListener"):
            window.addListener(EVENT_WINDOW_POP, _window_pop_action)

        if hasattr(menu, "setHeaderWidget"):
            menu.setHeaderWidget(header_group)

        if hasattr(window, "setButtonAction"):
            window.setButtonAction("rbutton", "cancel")
        if hasattr(window, "addActionListener"):
            window.addActionListener("cancel", window, _hide_action)

        if hasattr(window, "setButtonAction"):
            window.setButtonAction("lbutton", None, None)

        window.addWidget(menu)  # type: ignore[attr-defined]
        if hasattr(window, "setShowFrameworkWidgets"):
            window.setShowFrameworkWidgets(False)
        if hasattr(window, "setAllowScreensaver"):
            window.setAllowScreensaver(False)
        if hasattr(window, "show"):
            window.show(getattr(Window, "transitionFadeIn", None))

        return EVENT_CONSUME

    # camelCase alias
    _alarmPreviewWindow = _alarm_preview_window

    # ==================================================================
    # Default actions
    # ==================================================================

    def _get_default_action(self, action_name: str) -> Optional[Callable[..., Any]]:
        """Return the built-in default action handler, or None."""
        defaults = {
            "play-status": self._default_play_status,
            "go-status": self._default_play_status,
            "add-status": self._default_add_status,
            "add-hold-status": self._default_add_hold_status,
        }
        return defaults.get(action_name)

    def _default_play_status(
        self,
        menu: Any,
        menu_item: Any,
        db: DB,
        db_index: int,
        event: Any,
        action_name: str,
        item: Optional[Dict[str, Any]],
    ) -> int:
        """Default play action for playlist items."""
        try:
            from jive.ui.constants import EVENT_CONSUME
        except ImportError:
            EVENT_CONSUME = 0x02  # type: ignore[assignment]

        if self._player is not None:
            is_paused = False
            if hasattr(self._player, "isPaused"):
                is_paused = self._player.isPaused()
            elif hasattr(self._player, "is_paused"):
                is_paused = self._player.is_paused()

            is_current = False
            if hasattr(self._player, "isCurrent"):
                is_current = self._player.isCurrent(db_index)
            elif hasattr(self._player, "is_current"):
                is_current = self._player.is_current(db_index)

            if is_paused and is_current:
                if hasattr(self._player, "togglePause"):
                    self._player.togglePause()
                elif hasattr(self._player, "toggle_pause"):
                    self._player.toggle_pause()
            else:
                if hasattr(self._player, "playlistJumpIndex"):
                    self._player.playlistJumpIndex(db_index)
                elif hasattr(self._player, "playlist_jump_index"):
                    self._player.playlist_jump_index(db_index)

        return EVENT_CONSUME

    def _default_add_status(
        self,
        menu: Any,
        menu_item: Any,
        db: DB,
        db_index: int,
        event: Any,
        action_name: str,
        item: Optional[Dict[str, Any]],
    ) -> int:
        """Default add (delete) action for playlist items."""
        try:
            from jive.ui.constants import EVENT_CONSUME
        except ImportError:
            EVENT_CONSUME = 0x02  # type: ignore[assignment]

        if self._player is not None:
            if hasattr(self._player, "playlistDeleteIndex"):
                self._player.playlistDeleteIndex(db_index)
            elif hasattr(self._player, "playlist_delete_index"):
                self._player.playlist_delete_index(db_index)
        return EVENT_CONSUME

    def _default_add_hold_status(
        self,
        menu: Any,
        menu_item: Any,
        db: DB,
        db_index: int,
        event: Any,
        action_name: str,
        item: Optional[Dict[str, Any]],
    ) -> int:
        """Default add-hold (zap) action for playlist items."""
        try:
            from jive.ui.constants import EVENT_CONSUME
        except ImportError:
            EVENT_CONSUME = 0x02  # type: ignore[assignment]

        if self._player is not None:
            if hasattr(self._player, "playlistZapIndex"):
                self._player.playlistZapIndex(db_index)
            elif hasattr(self._player, "playlist_zap_index"):
                self._player.playlist_zap_index(db_index)
        return EVENT_CONSUME

    # ==================================================================
    # Menu table navigation helper
    # ==================================================================

    @staticmethod
    def _go_menu_table_item(key: str) -> None:
        """Navigate to a home-menu entry by its key.

        Mirrors Lua ``_goMenuTableItem``.  If the target window is
        already on top, bumps it left; otherwise invokes its callback.
        """
        try:
            from jive.jive_main import jive_main as _jm
            from jive.ui.framework import framework as _fw
            from jive.ui.window import Window

            if _jm is None:
                return
            menu_table = (
                _jm.get_menu_table()
                if hasattr(_jm, "get_menu_table")
                else (_jm.getMenuTable() if hasattr(_jm, "getMenuTable") else None)
            )
            if menu_table is None or key not in menu_table:
                return

            top_window = None
            if hasattr(Window, "getTopNonTransientWindow"):
                top_window = Window.getTopNonTransientWindow()

            if (
                top_window is not None
                and hasattr(top_window, "getWindowId")
                and top_window.getWindowId() == key
            ):
                if _fw is not None and hasattr(_fw, "playSound"):
                    _fw.playSound("BUMP")
                if hasattr(top_window, "bumpLeft"):
                    top_window.bumpLeft()
            else:
                if _fw is not None and hasattr(_fw, "playSound"):
                    _fw.playSound("JUMP")
                entry = menu_table[key]
                callback = (
                    entry.get("callback")
                    if isinstance(entry, dict)
                    else getattr(entry, "callback", None)
                )
                if callback is not None:
                    callback(None, None, True)
        except (ImportError, AttributeError) as exc:
            log.debug("_go_menu_table_item: not available: %s", exc)

    # camelCase alias
    _goMenuTableItem = _go_menu_table_item

    # ==================================================================
    # Global actions
    # ==================================================================

    def _install_action_listeners(self) -> None:
        """Install global action listeners for transport controls."""
        if self._action_listener_handles is not None:
            log.debug(
                "_install_action_listeners: already installed (%d handles)",
                len(self._action_listener_handles),
            )
            return

        self._action_listener_handles = []

        action_map = self._build_global_actions()
        log.info(
            "_install_action_listeners: registering %d global actions: %s",
            len(action_map),
            list(action_map.keys()),
        )

        try:
            from jive.ui.framework import framework as _fw

            if _fw is not None and hasattr(_fw, "addActionListener"):
                for action_str, func in action_map.items():
                    handle = _fw.addActionListener(action_str, self, func, False)
                    if handle is not None:
                        self._action_listener_handles.append(handle)
                        log.debug(
                            "_install_action_listeners: registered %r -> handle=%s",
                            action_str,
                            handle,
                        )
                    else:
                        log.warning(
                            "_install_action_listeners: addActionListener(%r) returned None!",
                            action_str,
                        )
                log.info(
                    "_install_action_listeners: done, %d handles installed",
                    len(self._action_listener_handles),
                )
            else:
                log.warning(
                    "_install_action_listeners: framework=%s, hasattr(addActionListener)=%s",
                    _fw,
                    hasattr(_fw, "addActionListener") if _fw else "N/A",
                )
        except ImportError as exc:
            log.error(
                "_install_action_listeners: framework not available: %s",
                exc,
                exc_info=True,
            )

    def _remove_action_listeners(self) -> None:
        """Remove global action listeners."""
        if self._action_listener_handles is None:
            return

        try:
            from jive.ui.framework import framework as _fw

            if _fw is not None:
                for handle in self._action_listener_handles:
                    if hasattr(_fw, "removeListener"):
                        _fw.removeListener(handle)
        except ImportError as exc:
            log.debug("_remove_action_listeners: framework not available: %s", exc)

        self._action_listener_handles = None

    def _build_global_actions(self) -> Dict[str, Callable[..., Any]]:
        """Build the global action handler map."""
        try:
            from jive.ui.constants import EVENT_CONSUME, EVENT_UNUSED
        except ImportError:
            EVENT_CONSUME = 0x02  # type: ignore[assignment]
            EVENT_UNUSED = 0x00  # type: ignore[assignment]

        def _go_now_playing_action(*args: Any) -> int:
            self._go_now("nowPlaying")
            return EVENT_CONSUME

        def _go_playlist_action(*args: Any) -> int:
            self._go_playlist()
            return EVENT_CONSUME

        def _go_home_action(*args: Any) -> int:
            self._go_now("home")
            return EVENT_CONSUME

        def _play_action(*args: Any) -> int:
            log.info("_play_action: called, player=%s", self._player)
            if self._player is None:
                log.warning("_play_action: no player attached, returning UNUSED")
                return EVENT_UNUSED
            try:
                from jive.ui.framework import framework as _fw

                if _fw is not None and hasattr(_fw, "playSound"):
                    _fw.playSound("PLAYBACK")
            except ImportError as exc:
                log.debug(
                    "_play_action: framework not available for playSound: %s", exc
                )
            playlist_size = 0
            if hasattr(self._player, "getPlaylistSize"):
                playlist_size = self._player.getPlaylistSize() or 0
            elif hasattr(self._player, "get_playlist_size"):
                playlist_size = self._player.get_playlist_size() or 0
            play_mode = ""
            if hasattr(self._player, "getPlayMode"):
                play_mode = self._player.getPlayMode() or ""
            elif hasattr(self._player, "get_play_mode"):
                play_mode = self._player.get_play_mode() or ""

            log.info(
                "_play_action: playlist_size=%s, play_mode=%r", playlist_size, play_mode
            )

            if playlist_size > 0 and play_mode != "play":
                log.info("_play_action: calling player.play()")
                if hasattr(self._player, "play"):
                    self._player.play()
                return EVENT_CONSUME
            log.info(
                "_play_action: NOT starting play (playlist_size=%s, play_mode=%r), returning UNUSED",
                playlist_size,
                play_mode,
            )
            return EVENT_UNUSED

        def _pause_action(*args: Any) -> int:
            log.info("_pause_action: called, player=%s", self._player)
            if self._player is None:
                log.warning("_pause_action: no player attached, returning UNUSED")
                return EVENT_UNUSED
            try:
                from jive.ui.framework import framework as _fw

                if _fw is not None and hasattr(_fw, "playSound"):
                    _fw.playSound("PLAYBACK")
            except ImportError as exc:
                log.debug(
                    "_pause_action: framework not available for playSound: %s", exc
                )
            log.info("_pause_action: calling togglePause()")
            if hasattr(self._player, "togglePause"):
                self._player.togglePause()
            elif hasattr(self._player, "toggle_pause"):
                self._player.toggle_pause()
            return EVENT_CONSUME

        def _stop_action(*args: Any) -> int:
            if self._player is None:
                return EVENT_UNUSED
            try:
                from jive.ui.framework import framework as _fw

                if _fw is not None and hasattr(_fw, "playSound"):
                    _fw.playSound("PLAYBACK")
            except ImportError as exc:
                log.debug(
                    "_stop_action: framework not available for playSound: %s", exc
                )
            if hasattr(self._player, "stop"):
                self._player.stop()
            return EVENT_CONSUME

        def _volume_action(self_ref: Any = None, event: Any = None) -> int:
            if self.volume is not None and event is not None:
                return self.volume.event(event)
            return EVENT_CONSUME

        def _jump_rew_action(*args: Any) -> int:
            if self._player is None:
                return EVENT_UNUSED
            try:
                from jive.ui.framework import framework as _fw

                if _fw is not None and hasattr(_fw, "playSound"):
                    _fw.playSound("PLAYBACK")
            except ImportError as exc:
                log.debug(
                    "_jump_rew_action: framework not available for playSound: %s", exc
                )
            if hasattr(self._player, "rew"):
                self._player.rew()
            return EVENT_CONSUME

        def _jump_fwd_action(*args: Any) -> int:
            if self._player is None:
                return EVENT_UNUSED
            try:
                from jive.ui.framework import framework as _fw

                if _fw is not None and hasattr(_fw, "playSound"):
                    _fw.playSound("PLAYBACK")
            except ImportError as exc:
                log.debug(
                    "_jump_fwd_action: framework not available for playSound: %s", exc
                )
            if hasattr(self._player, "fwd"):
                self._player.fwd()
            return EVENT_CONSUME

        def _scanner_action(self_ref: Any = None, event: Any = None) -> int:
            if self.scanner is not None and event is not None:
                return self.scanner.event(event)
            return EVENT_CONSUME

        def _repeat_toggle(*args: Any) -> int:
            if self._player is not None and hasattr(self._player, "repeatToggle"):
                self._player.repeatToggle()
            return EVENT_CONSUME

        def _shuffle_toggle(*args: Any) -> int:
            if self._player is not None and hasattr(self._player, "shuffleToggle"):
                self._player.shuffleToggle()
            return EVENT_CONSUME

        def _sleep_action(*args: Any) -> int:
            if self._player is not None and hasattr(self._player, "sleepToggle"):
                self._player.sleepToggle()
            return EVENT_CONSUME

        def _home_or_np(*args: Any) -> int:
            try:
                from jive.ui.framework import framework as _fw

                if _fw is not None and hasattr(_fw, "windowStack"):
                    if len(_fw.windowStack) > 1:
                        self._go_now("home")
                    else:
                        self._go_now("nowPlaying")
                    return EVENT_CONSUME
            except ImportError as exc:
                log.debug(
                    "_home_or_np: framework not available for windowStack check: %s",
                    exc,
                )
            self._go_now("home")
            return EVENT_CONSUME

        def _quit_action(*args: Any) -> int:
            try:
                from jive.applet_manager import applet_manager

                if applet_manager is not None:
                    applet_manager.call_service("disconnectPlayer")
            except (ImportError, AttributeError) as exc:
                log.error(
                    "_quit_action: failed to call disconnectPlayer: %s",
                    exc,
                    exc_info=True,
                )
            try:
                from jive.ui.constants import EVENT_QUIT

                return EVENT_CONSUME | EVENT_QUIT
            except ImportError:
                return EVENT_CONSUME

        # --- Shortcut navigation actions (ported from Lua _go*Action) ---

        def _go_search_action(*args: Any) -> int:
            self._go_menu_table_item("globalSearch")
            return EVENT_CONSUME

        def _go_music_library_action(*args: Any) -> int:
            self._go_menu_table_item("_myMusic")
            return EVENT_CONSUME

        def _go_favorites_action(*args: Any) -> int:
            self._go_menu_table_item("favorites")
            return EVENT_CONSUME

        def _go_playlists_action(*args: Any) -> int:
            self._go_menu_table_item("myMusicPlaylists")
            return EVENT_CONSUME

        def _go_alarms_action(*args: Any) -> int:
            self._go_menu_table_item("settingsAlarm")
            return EVENT_CONSUME

        return {
            "go_now_playing": _go_now_playing_action,
            "go_now_playing_or_playlist": _go_now_playing_action,
            "go_playlist": _go_playlist_action,
            "go_home": _go_home_action,
            "go_home_or_now_playing": _home_or_np,
            "play": _play_action,
            "pause": _pause_action,
            "stop": _stop_action,
            "mute": _volume_action,
            "volume_up": _volume_action,
            "volume_down": _volume_action,
            "jump_rew": _jump_rew_action,
            "jump_fwd": _jump_fwd_action,
            "scanner_rew": _scanner_action,
            "scanner_fwd": _scanner_action,
            "repeat_toggle": _repeat_toggle,
            "shuffle_toggle": _shuffle_toggle,
            "sleep": _sleep_action,
            "quit": _quit_action,
            "go_search": _go_search_action,
            "go_music_library": _go_music_library_action,
            "go_favorites": _go_favorites_action,
            "go_playlists": _go_playlists_action,
            "go_alarms": _go_alarms_action,
        }

    def _install_player_key_handler(self) -> None:
        """Install the raw key handler for volume/fwd/rew keys."""
        if self._player_key_handler is not None:
            return

        _init_keycode_map()

        try:
            from jive.ui.constants import (
                EVENT_IR_ALL,
                EVENT_KEY_DOWN,
                EVENT_KEY_HOLD,
                EVENT_KEY_PRESS,
                EVENT_UNUSED,
            )
            from jive.ui.framework import framework as _fw

            if _fw is None or not hasattr(_fw, "addListener"):
                return

            event_mask = (
                EVENT_KEY_DOWN | EVENT_KEY_PRESS | EVENT_KEY_HOLD | EVENT_IR_ALL
            )

            def _key_handler(event: Any) -> int:
                evt_type = 0
                if hasattr(event, "getType"):
                    evt_type = event.getType()

                if evt_type & EVENT_IR_ALL > 0:
                    is_volup = False
                    is_voldown = False
                    if hasattr(event, "isIRCode"):
                        is_volup = event.isIRCode("volup")
                        is_voldown = event.isIRCode("voldown")
                    if is_volup or is_voldown:
                        if self.volume is not None:
                            return self.volume.event(event)
                    return EVENT_UNUSED

                keycode = 0
                if hasattr(event, "getKeycode"):
                    keycode = event.getKeycode()

                action_name = _KEYCODE_ACTION_NAME.get(keycode)
                if action_name is None:
                    return EVENT_UNUSED

                if evt_type == EVENT_KEY_DOWN:
                    action_name = action_name + "-down"
                elif evt_type == EVENT_KEY_HOLD:
                    action_name = action_name + "-hold"

                # Map to global action handler
                handlers = {
                    "volup-down": lambda s, e: (
                        self.volume.event(e) if self.volume else EVENT_UNUSED
                    ),
                    "volup": lambda s, e: (
                        self.volume.event(e) if self.volume else EVENT_UNUSED
                    ),
                    "voldown-down": lambda s, e: (
                        self.volume.event(e) if self.volume else EVENT_UNUSED
                    ),
                    "voldown": lambda s, e: (
                        self.volume.event(e) if self.volume else EVENT_UNUSED
                    ),
                    "rew-hold": lambda s, e: (
                        self.scanner.event(e) if self.scanner else EVENT_UNUSED
                    ),
                    "fwd-hold": lambda s, e: (
                        self.scanner.event(e) if self.scanner else EVENT_UNUSED
                    ),
                    "fwd": lambda s, e: (
                        _fw.playSound("PLAYBACK")
                        if hasattr(_fw, "playSound")
                        else None,
                        self._player.fwd()
                        if self._player and hasattr(self._player, "fwd")
                        else None,
                        2,  # EVENT_CONSUME
                    )[-1],
                    "rew": lambda s, e: (
                        _fw.playSound("PLAYBACK")
                        if hasattr(_fw, "playSound")
                        else None,
                        self._player.rew()
                        if self._player and hasattr(self._player, "rew")
                        else None,
                        2,  # EVENT_CONSUME
                    )[-1],
                }

                func = handlers.get(action_name)
                if func is None:
                    return EVENT_UNUSED
                return func(self, event)  # type: ignore[no-untyped-call]

            self._player_key_handler = _fw.addListener(event_mask, _key_handler, False)
        except ImportError as exc:
            log.error(
                "_install_player_key_handler: framework not available: %s",
                exc,
                exc_info=True,
            )

    def _remove_player_key_handler(self) -> None:
        """Remove the raw key handler."""
        if self._player_key_handler is None:
            return

        try:
            from jive.ui.framework import framework as _fw

            if _fw is not None and hasattr(_fw, "removeListener"):
                _fw.removeListener(self._player_key_handler)
        except ImportError as exc:
            log.debug("_remove_player_key_handler: framework not available: %s", exc)

        self._player_key_handler = None

    # ==================================================================
    # Playlist management
    # ==================================================================

    def _request_status(self) -> None:
        """Request the next chunk of playlist data."""
        step = self._status_step
        if step is None or step.get("db") is None:
            return

        db = step["db"]
        missing = db.missing()
        if missing is not None:
            from_val, qty_val = missing
            if (
                self._server is not None
                and self._player is not None
                and hasattr(self._server, "request")
            ):
                player_id = None
                if hasattr(self._player, "getId"):
                    player_id = self._player.getId()
                elif hasattr(self._player, "get_id"):
                    player_id = self._player.get_id()

                self._server.request(
                    step.get("sink"),
                    player_id,
                    ["status", from_val, qty_val, "menu:menu", "useContextMenu:1"],
                )

    def _status_sink(
        self,
        step: Dict[str, Any],
        chunk: Optional[Dict[str, Any]],
        err: Optional[str] = None,
    ) -> None:
        """Sink for playlist status updates."""
        log.debug("_status_sink()")

        if self._status_step is not None:
            assert step is self._status_step

        data = None
        if chunk is not None:
            data = chunk.get("data")

        if data is not None:
            # Check for valid data
            item_loop = _safe_deref(
                data,
                "item_loop",
                0 if isinstance(_safe_deref(data, "item_loop"), list) else None,  # type: ignore[arg-type]
            )
            if isinstance(data.get("item_loop"), list) and len(data["item_loop"]) == 0:
                return

            if data.get("error"):
                log.info("_status_sink() chunk has error: returning")
                return

            # Skip upgrade messages
            if (
                isinstance(data.get("item_loop"), list)
                and len(data["item_loop"]) > 0
                and data["item_loop"][0].get("text") == "READ ME"
            ):
                log.debug("Not suitable for current playlist")
                return

            self._step_set_menu_items(step, data)
            self._request_status()
        else:
            if err:
                log.error(err)

    def show_empty_playlist(self, token: str) -> Any:
        """Show an empty playlist window."""
        try:
            from jive.ui.simplemenu import SimpleMenu
            from jive.ui.window import Window

            window = Window("play_list", self._str("SLIMBROWSER_PLAYLIST"))
            menu = SimpleMenu("menu")
            menu.addItem({"text": self._str(token), "style": "item_no_arrow"})
            window.addWidget(menu)  # type: ignore[attr-defined]

            if hasattr(window, "setButtonAction"):
                window.setButtonAction("rbutton", None, None)

            self._empty_step = {
                "window": window,
                "_isNpChildWindow": True,
            }

            return window
        except ImportError:
            log.info("show_empty_playlist: UI not available")
            return None

    def show_playlist(self) -> int:
        """Show the current playlist window."""
        log.info(
            "show_playlist: called, player=%s, _status_step=%s",
            self._player,
            "set" if self._status_step is not None else "None",
        )
        try:
            from jive.ui.constants import EVENT_CONSUME, EVENT_UNUSED
        except ImportError:
            EVENT_CONSUME = 0x02  # type: ignore[assignment]
            EVENT_UNUSED = 0x00  # type: ignore[assignment]

        if self._status_step is not None:
            playlist_size = 0
            if self._player is not None and hasattr(self._player, "getPlaylistSize"):
                playlist_size = self._player.getPlaylistSize() or 0
            elif self._player is not None and hasattr(
                self._player, "get_playlist_size"
            ):
                playlist_size = self._player.get_playlist_size() or 0

            log.info("show_playlist: playlist_size=%s", playlist_size)

            if playlist_size == 0 or not playlist_size:
                # Check if empty playlist already shown
                if self._empty_step and self._empty_step.get("window"):
                    pass
                custom = self.show_empty_playlist("SLIMBROWSER_NOTHING")
                if custom is not None and hasattr(custom, "show"):
                    custom.show()
                return EVENT_CONSUME

            # Push the status step
            self._push_step(self._status_step)

            # Select current track
            if playlist_size is not None and playlist_size <= 1:
                menu = self._status_step.get("menu")
                if menu is not None and hasattr(menu, "setSelectedIndex"):
                    menu.setSelectedIndex(1)
            else:
                db = self._status_step.get("db")
                if db is not None:
                    idx = db.playlist_index()
                    if idx is not None:
                        menu = self._status_step.get("menu")
                        if menu is not None and hasattr(menu, "setSelectedIndex"):
                            menu.setSelectedIndex(idx)

            window = self._status_step.get("window")
            if window is not None and hasattr(window, "show"):
                window.show()

            return EVENT_CONSUME

        return EVENT_UNUSED

    # Aliases
    showPlaylist = show_playlist

    def _leave_play_list_action(self) -> int:
        """Action handler for leaving the playlist view.

        Mirrors Lua ``_leavePlayListAction``.  If this window is #2
        on the stack there is no NowPlaying window (e.g. when the
        playlist is empty), so we go home instead.
        """
        try:
            from jive.ui.constants import EVENT_CONSUME
            from jive.ui.framework import framework as _fw

            if _fw is not None and hasattr(_fw, "windowStack"):
                stack_len = len(_fw.windowStack)
                if stack_len == 2:
                    self._go_now("home")
                else:
                    self._go_now("nowPlaying")
            else:
                self._go_now("nowPlaying")
            return EVENT_CONSUME
        except ImportError:
            self._go_now("nowPlaying")
            return 0x02  # EVENT_CONSUME fallback

    # camelCase alias
    _leavePlayListAction = _leave_play_list_action

    def show_track_one(self) -> None:
        """Show track info for track 1."""
        self.show_track(1)

    # Alias
    showTrackOne = show_track_one

    def show_current_track(self) -> None:
        """Show track info for the currently playing track."""
        if self._player is None:
            return
        current_index = 1
        if hasattr(self._player, "getPlaylistCurrentIndex"):
            current_index = self._player.getPlaylistCurrentIndex() or 1
        elif hasattr(self._player, "get_playlist_current_index"):
            current_index = self._player.get_playlist_current_index() or 1
        self.show_track(current_index)

    # Alias
    showCurrentTrack = show_current_track

    def show_track(
        self,
        index: int,
        cached_response: Any = None,
    ) -> None:
        """Show track info for the given 1-based index."""
        use_cached = cached_response is not None and isinstance(cached_response, dict)

        server_index = index - 1
        json_action: Dict[str, Any] = {
            "cmd": ["contextmenu"],
            "itemsParams": "params",
            "window": {"isContextMenu": 1},
            "player": 0,
            "params": {
                "playlist_index": server_index,
                "menu": "track",
                "context": "playlist",
            },
        }

        window_spec: Dict[str, Any] = {
            "isContextMenu": True,
            "menuStyle": "menu",
            "labelItemStyle": "item",
        }

        step, sink = self._new_destination(None, None, window_spec, self._browse_sink)

        if not use_cached:
            window = step.get("window")
            if window is not None and hasattr(window, "addActionListener"):
                try:
                    from jive.ui.constants import EVENT_CONSUME

                    def _back_to_np(*args: Any) -> int:
                        self._go_now_playing()
                        return EVENT_CONSUME

                    window.addActionListener("back", step, _back_to_np)
                except ImportError as exc:
                    log.warning(
                        "show_track: EVENT_CONSUME not available for back action: %s",
                        exc,
                    )
            step["_isNpChildWindow"] = True

        window = step.get("window")
        if window is not None and hasattr(window, "show"):
            window.show()
        self._push_step(step)

        self._perform_json_action(
            json_action, 0, 200, step, sink, None, cached_response
        )

    def set_preset_current_track(self, preset: int) -> None:
        """Set a preset for the currently playing track."""
        key = str(preset)
        current_index = 1
        if self._player is not None:
            if hasattr(self._player, "getPlaylistCurrentIndex"):
                current_index = self._player.getPlaylistCurrentIndex() or 1

        server_index = current_index - 1
        json_action: Dict[str, Any] = {
            "player": 0,
            "cmd": ["jivefavorites", "set_preset"],
            "itemsParams": "params",
            "params": {
                "playlist_index": server_index,
                "key": key,
            },
        }
        self._perform_json_action(json_action, None, None, None, None)

    # Alias
    setPresetCurrentTrack = set_preset_current_track

    def show_cached_track(self, cached_response: Any) -> None:
        """Show a track from a cached response."""
        self.show_track(-1, cached_response)

    # Alias
    showCachedTrack = show_cached_track

    # ==================================================================
    # Public API
    # ==================================================================

    def go_home(self, transition: Any = None) -> None:
        """Navigate to the home screen."""
        try:
            from jive.applet_manager import applet_manager

            if applet_manager is not None:
                applet_manager.call_service("goHome")
        except (ImportError, AttributeError) as exc:
            log.error("go_home: failed to call goHome service: %s", exc, exc_info=True)

    # Alias
    goHome = go_home

    def find_squeeze_network(self) -> Any:
        """Find the SqueezeNetwork server."""
        try:
            from jive.applet_manager import applet_manager

            if applet_manager is not None:
                for mac, server in applet_manager.call_service("iterateSqueezeCenters"):
                    if (
                        hasattr(server, "isSqueezeNetwork")
                        and server.isSqueezeNetwork()
                    ):
                        log.debug("found SN")
                        return server
        except (ImportError, AttributeError, TypeError) as exc:
            log.error(
                "find_squeeze_network: failed to iterate servers: %s",
                exc,
                exc_info=True,
            )
        log.error("SN not found")
        return None

    # Alias
    findSqueezeNetwork = find_squeeze_network

    def browser_json_request(self, server: Any, json_action: Dict[str, Any]) -> None:
        """Execute a JSON request via the browser."""
        if self._player is None:
            try:
                from jive.applet_manager import applet_manager

                if applet_manager is not None:
                    current = applet_manager.call_service("getCurrentPlayer")
                    self._attach_player(current)
            except (ImportError, AttributeError) as exc:
                log.error(
                    "browser_json_request: failed to get current player: %s",
                    exc,
                    exc_info=True,
                )

        self._perform_json_action(json_action, None, None, None, None)

    # Alias
    browserJsonRequest = browser_json_request

    def browser_cancel(self, step: Dict[str, Any]) -> None:
        """Cancel a step."""
        step["cancelled"] = True

    # Alias
    browserCancel = browser_cancel

    def browser_action_request(
        self,
        server: Any,
        v: Dict[str, Any],
        loaded_callback: Optional[Callable[..., Any]] = None,
    ) -> Any:
        """Make an action request via the browser.

        This is the service entry point registered as ``browserActionRequest``.
        It mirrors the Lua ``browserActionRequest`` function.

        Parameters
        ----------
        server:
            The server to use for the request.
        v:
            The item dict containing ``actions`` (with ``do`` and/or ``go``
            sub-keys), optional ``input``, ``nextWindow``, and ``id``.
        loaded_callback:
            Optional callback invoked when the destination step is loaded.
        """
        if self._player is None:
            try:
                from jive.applet_manager import applet_manager

                if applet_manager is not None:
                    current = applet_manager.call_service("getCurrentPlayer")
                    self._attach_player(current)
            except (ImportError, AttributeError) as exc:
                log.error(
                    "browser_action_request: failed to get current player: %s",
                    exc,
                    exc_info=True,
                )

        do_action = _safe_deref(v, "actions", "do")
        go_action = _safe_deref(v, "actions", "go")

        if do_action:
            json_action = v["actions"]["do"]
        elif go_action:
            json_action = v["actions"]["go"]
        else:
            log.debug("browserActionRequest: no action found for %s", v)
            return False

        step: Optional[Dict[str, Any]] = None
        sink: Optional[Callable[..., Any]] = None
        from_val: Optional[int] = None
        qty: Optional[int] = None

        # We need a new window for go actions, or do actions that involve input
        if go_action or (do_action and v.get("input")) or v.get("id") == "playerpower":
            next_window = v.get("nextWindow")
            log.debug("nextWindow: %s", next_window)

            if next_window:
                if loaded_callback:
                    loaded_callback(step)
                if next_window == "home":
                    sink = lambda *a, **kw: self.go_home()
                elif next_window == "playlist":
                    sink = lambda *a, **kw: self._go_playlist()
                elif next_window == "nowPlaying":
                    sink = lambda *a, **kw: self._go_now_playing()
            else:
                if do_action and v.get("id") == "playerpower":
                    step, sink = self._empty_destination(step)
                    if loaded_callback:
                        step["loaded"] = lambda: loaded_callback(step)
                else:
                    step, sink = self._new_destination(
                        None,
                        v,
                        self._new_window_spec(None, v),
                        self._browse_sink,
                        json_action,
                    )

                    if v.get("input"):
                        window = step.get("window")
                        if window is not None and hasattr(window, "show"):
                            window.show()
                        self._push_step(step)
                    else:
                        from_val, qty = self._decide_first_chunk(step, json_action)

                        def _on_loaded(
                            _step: Optional[Dict[str, Any]] = step,
                            _cb: Any = loaded_callback,
                        ) -> None:
                            if _step is None:
                                return
                            last_index = None
                            if self._player is not None:
                                cs = _step.get("commandString")
                                if hasattr(self._player, "getLastBrowseIndex"):
                                    last_index = self._player.getLastBrowseIndex(cs)
                                elif hasattr(self._player, "get_last_browse_index"):
                                    last_index = self._player.get_last_browse_index(cs)

                            if not last_index and _cb:
                                _cb(_step)
                                self._push_step(_step)
                                w = _step.get("window")
                                if w is not None and hasattr(w, "show"):
                                    w.show()
                            elif self._player is not None:
                                self._player.loadedCallback = _cb

                        step["loaded"] = _on_loaded

        if not v.get("input"):
            self._perform_json_action(json_action, from_val, qty, step, sink)

        return step

    # Aliases
    browserActionRequest = browser_action_request

    def squeeze_network_request(
        self,
        request: Any,
        in_setup: bool = False,
        success_callback: Optional[Callable[..., Any]] = None,
    ) -> None:
        """Make a request to SqueezeNetwork.

        This is the service entry point registered as ``squeezeNetworkRequest``.
        It mirrors the Lua ``squeezeNetworkRequest`` function.

        Parameters
        ----------
        request:
            The request to send to SqueezeNetwork.
        in_setup:
            Whether this request is part of the setup flow.
        success_callback:
            Optional callback invoked on successful first request.
        """
        squeezenetwork = self.find_squeeze_network()

        if squeezenetwork is None or request is None:
            return

        self._in_setup = in_setup
        self._server = squeezenetwork

        # Create a window for SN signup
        step, sink = self._new_destination(
            None,
            None,
            {
                "text": self._str("SN_SIGNUP"),
                "menuStyle": "menu",
                "labelItemStyle": "item",
                "windowStyle": "text_list",
                "disableBackButton": True,
            },
            self._browse_sink,
        )

        sink_wrapper = sink
        if success_callback:

            def _wrapped_sink(chunk: Any = None, err: Any = None) -> None:
                sink(chunk, err)
                log.info("Calling successCallback after initial SN request succeeded")
                is_registered = False
                if hasattr(squeezenetwork, "isSpRegisteredWithSn"):
                    is_registered = squeezenetwork.isSpRegisteredWithSn()
                elif hasattr(squeezenetwork, "is_sp_registered_with_sn"):
                    is_registered = squeezenetwork.is_sp_registered_with_sn()
                success_callback(is_registered)

            sink_wrapper = _wrapped_sink

        self._push_to_new_window(step)

        if hasattr(squeezenetwork, "userRequest"):
            squeezenetwork.userRequest(sink_wrapper, None, request)

    # Aliases
    squeezeNetworkRequest = squeeze_network_request

    def get_audio_volume_manager(self) -> Optional[Volume]:
        """Return the Volume manager."""
        return self.volume

    # Alias
    getAudioVolumeManager = get_audio_volume_manager

    # ==================================================================
    # Player notifications
    # ==================================================================

    def notify_playerLoaded(self, player: Any) -> None:
        """Called when the current player changes and menus are loaded."""
        log.debug("notify_playerLoaded(%s)", player)
        self._attach_player(player)

    def notify_playerDelete(self, player: Any) -> None:
        """Called when a player disappears."""
        if self._player != player:
            return
        log.error("Player gone while browsing — going home!")
        self.free()

    def notify_playerPlaylistChange(self, player: Any) -> None:
        """Called when the player's playlist changes.

        Matches Lua SlimBrowserApplet.lua:3681-3724.
        """
        log.debug("notify_playerPlaylistChange")
        if self._player != player:
            return

        if self._status_step is None:
            return

        playlist_size = 0
        if hasattr(self._player, "getPlaylistSize"):
            playlist_size = self._player.getPlaylistSize() or 0

        is_on = True
        if hasattr(self._player, "isPowerOn"):
            is_on = self._player.isPowerOn()

        step = self._status_step
        empty_step = self._empty_step

        # Display 'NOTHING' if the player is on and playlist is empty
        if is_on and playlist_size == 0:
            from jive.ui.window import Window

            # Invalidate DB so stale items are cleared
            db_early = step.get("db")
            if db_early is not None:
                player_status_early = None
                if hasattr(self._player, "getPlayerStatus"):
                    player_status_early = self._player.getPlayerStatus()
                if player_status_early is not None:
                    db_early.update_status(player_status_early)

            custom = self.show_empty_playlist("SLIMBROWSER_NOTHING")
            if custom is not None:
                # Replace existing empty-step window
                if empty_step and empty_step.get("window") is not None:
                    if hasattr(custom, "replace"):
                        custom.replace(empty_step["window"], Window.transitionFadeIn)
                # Replace the playlist step window
                if step.get("window") is not None:
                    if hasattr(custom, "replace"):
                        custom.replace(step["window"], Window.transitionFadeIn)

            try:
                from jive.applet_manager import applet_manager

                if applet_manager is not None:
                    applet_manager.call_service("hideNowPlaying")
            except (ImportError, AttributeError) as exc:
                log.error(
                    "notify_playerPlaylistChange: failed to hide now playing: %s",
                    exc,
                    exc_info=True,
                )
            return

        # Bug 17529: Moving from empty playlist to non-empty —
        # push to NowPlaying and remove the emptyStep window
        elif is_on and playlist_size and empty_step and empty_step.get("window"):
            self._go_now_playing(None, True)
            empty_step["window"].hide()
            self._empty_step = None

        # Update the window
        db = step.get("db")
        if db is not None:
            player_status = None
            if hasattr(self._player, "getPlayerStatus"):
                player_status = self._player.getPlayerStatus()
            if player_status is not None:
                db.update_status(player_status)

            menu = step.get("menu")
            if menu is not None and hasattr(menu, "reLayout"):
                menu.reLayout()

        self._request_status()

    def notify_playerTrackChange(
        self, player: Any, nowplaying: Any, artwork: Any
    ) -> None:
        """Called when the current track changes."""
        log.debug("notify_playerTrackChange")

        if self._player != player:
            return

        if self._status_step is None:
            return

        player_status = None
        if hasattr(self._player, "getPlayerStatus"):
            player_status = self._player.getPlayerStatus()

        db = self._status_step.get("db")
        if db is not None and player_status is not None:
            db.update_status(player_status)
            idx = db.playlist_index()
            menu = self._status_step.get("menu")
            if menu is not None:
                if idx is not None and hasattr(menu, "setSelectedIndex"):
                    menu.setSelectedIndex(idx)
                else:
                    if hasattr(menu, "setSelectedIndex"):
                        menu.setSelectedIndex(1)
                if hasattr(menu, "reLayout"):
                    menu.reLayout()

    # ==================================================================
    # Connection error handling
    # ==================================================================

    def _remove_request_and_unlock(self, server: Any) -> None:
        """Remove pending requests and unlock the current menu.

        Mirrors Lua ``_removeRequestAndUnlock``.
        """
        if server is not None and hasattr(server, "removeAllUserRequests"):
            server.removeAllUserRequests()
        current_step = self._get_current_step()
        if current_step is not None:
            menu = current_step.get("menu")
            if menu is not None and hasattr(menu, "unlock"):
                menu.unlock()

    # camelCase alias
    _removeRequestAndUnlock = _remove_request_and_unlock

    def _network_failure_callback(self, server: Any) -> Callable[..., None]:
        """Return a callback for network failure handling.

        Mirrors Lua ``_networkFailureCallback``.
        """

        def _callback(failure_window: Any) -> None:
            self.server_error_window = failure_window
            if hasattr(failure_window, "addListener"):
                try:
                    from jive.ui.constants import EVENT_WINDOW_POP

                    def _on_pop(evt: Any = None) -> None:
                        self.server_error_window = False
                        self._remove_request_and_unlock(server)

                    failure_window.addListener(EVENT_WINDOW_POP, _on_pop)
                except ImportError:
                    pass

        return _callback

    # camelCase alias
    _networkFailureCallback = _network_failure_callback

    def _problem_connecting_popup(self, server: Any) -> None:
        """Show a popup while attempting to reconnect to the server.

        Mirrors Lua ``_problemConnectingPopup``.  Delegates to the
        applet manager's ``warnOnAnyNetworkFailure`` service.
        """
        log.debug("_problem_connecting_popup")

        def _success_callback() -> None:
            self._problem_connecting_popup_internal(server)

        failure_callback = self._network_failure_callback(server)

        try:
            from jive.applet_manager import applet_manager

            if applet_manager is not None:
                applet_manager.call_service(
                    "warnOnAnyNetworkFailure",
                    _success_callback,
                    failure_callback,
                )
        except (ImportError, AttributeError) as exc:
            log.error(
                "_problem_connecting_popup: warnOnAnyNetworkFailure not available: %s",
                exc,
                exc_info=True,
            )

    # camelCase alias
    _problemConnectingPopup = _problem_connecting_popup

    def _problem_connecting_popup_internal(self, server: Any) -> None:
        """Internal: show a reconnection popup with a timeout.

        Mirrors Lua ``_problemConnectingPopupInternal``.
        """
        log.info("_problem_connecting_popup_internal")

        # Attempt to reconnect (may send WOL)
        if hasattr(server, "wakeOnLan"):
            server.wakeOnLan()
        if hasattr(server, "connect"):
            server.connect()

        try:
            from jive.ui.constants import EVENT_CONSUME
            from jive.ui.icon import Icon
            from jive.ui.label import Label
            from jive.ui.popup import Popup

            popup = Popup("waiting_popup")
            popup.addWidget(Icon("icon_connecting"))  # type: ignore[attr-defined]
            popup.addWidget(Label("text", self._str("SLIMBROWSER_CONNECTING_TO")))  # type: ignore[attr-defined]
            server_name = ""
            if hasattr(server, "getName"):
                server_name = server.getName() or ""
            elif hasattr(server, "get_name"):
                server_name = server.get_name() or ""
            popup.addWidget(Label("subtext", server_name))  # type: ignore[attr-defined]

            if hasattr(popup, "ignoreAllInputExcept"):
                popup.ignoreAllInputExcept(
                    [
                        "back",
                        "go_home",
                        "go_home_or_now_playing",
                        "volume_up",
                        "volume_down",
                        "stop",
                        "pause",
                        "power",
                    ]
                )

            def _cancel_action(*args: Any) -> int:
                log.info("Cancel reconnect window")
                self._remove_request_and_unlock(server)
                self.server_error_window = None
                if hasattr(popup, "hide"):
                    popup.hide()
                return EVENT_CONSUME

            if hasattr(popup, "addActionListener"):
                popup.addActionListener("back", self, _cancel_action)
                popup.addActionListener("go_home", self, _cancel_action)
                popup.addActionListener("go_home_or_now_playing", self, _cancel_action)

            # Timer for timeout / connection failure check
            count = 0

            def _timer_callback() -> None:
                nonlocal count
                count += 1
                connection_failed = False
                if self._player is not None and hasattr(
                    self._player, "hasConnectionFailed"
                ):
                    connection_failed = self._player.hasConnectionFailed()
                if count == 20 or connection_failed:
                    self._problem_connecting(server)

            if hasattr(popup, "addTimer"):
                popup.addTimer(1000, _timer_callback)

            self.server_error_window = popup
            popup.show()
        except ImportError:
            log.info("_problem_connecting_popup_internal: UI not available")

    # camelCase alias
    _problemConnectingPopupInternal = _problem_connecting_popup_internal

    def _problem_connecting(self, server: Any) -> None:
        """Show the full 'problem connecting' menu.

        Mirrors Lua ``_problemConnecting``.  Delegates to the applet
        manager's ``warnOnAnyNetworkFailure`` service.
        """
        log.debug("_problem_connecting")

        def _success_callback() -> None:
            self._problem_connecting_internal(server)

        failure_callback = self._network_failure_callback(server)

        try:
            from jive.applet_manager import applet_manager

            if applet_manager is not None:
                applet_manager.call_service(
                    "warnOnAnyNetworkFailure",
                    _success_callback,
                    failure_callback,
                )
        except (ImportError, AttributeError) as exc:
            log.error(
                "_problem_connecting: warnOnAnyNetworkFailure not available: %s",
                exc,
                exc_info=True,
            )

    # camelCase alias
    _problemConnecting = _problem_connecting

    def _problem_connecting_internal(self, server: Any) -> None:
        """Internal: show the 'Problem Connecting' error window with options.

        Mirrors Lua ``_problemConnectingInternal``.  Provides try-again,
        choose-source, go-home, and choose-player options.
        """
        log.info("_problem_connecting_internal")

        try:
            from jive.ui.constants import EVENT_CONSUME, EVENT_WINDOW_POP
            from jive.ui.simplemenu import SimpleMenu
            from jive.ui.textarea import Textarea
            from jive.ui.window import Window
        except ImportError:
            log.info("_problem_connecting_internal: UI not available")
            return

        window = Window(
            "text_list",
            self._str("SLIMBROWSER_PROBLEM_CONNECTING"),
            "settingstitle",
        )
        menu = SimpleMenu("menu")
        player = self._player

        # Try again
        def _try_again(*args: Any) -> None:
            if hasattr(window, "hide"):
                window.hide()
            self._problem_connecting_popup(server)
            try:
                from jive.applet_manager import applet_manager

                if applet_manager is not None:
                    applet_manager.call_service("setCurrentPlayer", player)
            except (ImportError, AttributeError) as exc:
                log.debug("Could not call setCurrentPlayer: %s", exc)

        menu.addItem(
            {
                "text": self._str("SLIMBROWSER_TRY_AGAIN"),
                "callback": _try_again,
                "sound": "WINDOWSHOW",
            }
        )

        # Go home (when not in setup)
        if not self.in_setup:

            def _go_home_action(*args: Any) -> None:
                self._remove_request_and_unlock(server)
                self.go_home()

            menu.addItem(
                {
                    "text": self._str("SLIMBROWSER_GO_HOME"),
                    "callback": _go_home_action,
                }
            )

        def _cancel_action(*args: Any) -> int:
            self._remove_request_and_unlock(server)
            if hasattr(window, "hide"):
                window.hide()
            return EVENT_CONSUME

        if hasattr(menu, "addActionListener"):
            menu.addActionListener("back", self, _cancel_action)
            menu.addActionListener("go_home", self, _cancel_action)

        server_name = ""
        if self._server is not None:
            if hasattr(self._server, "getName"):
                server_name = self._server.getName() or ""
            elif hasattr(self._server, "get_name"):
                server_name = self._server.get_name() or ""

        if hasattr(menu, "setHeaderWidget"):
            menu.setHeaderWidget(
                Textarea(
                    "help_text",
                    self._str("SLIMBROWSER_PROBLEM_CONNECTING_HELP"),
                )
            )

        window.addWidget(menu)  # type: ignore[attr-defined]

        self.server_error_window = window
        if hasattr(window, "addListener"):

            def _on_pop(evt: Any = None) -> None:
                self.server_error_window = False

            window.addListener(EVENT_WINDOW_POP, _on_pop)  # type: ignore[arg-type]

        window.show()

    # camelCase alias
    _problemConnectingInternal = _problem_connecting_internal

    # ==================================================================
    # Player notifications (continued)
    # ==================================================================

    def notify_serverConnected(self, server: Any) -> None:
        """Called when the server connects."""
        if self._server != server:
            return

        try:
            from jive.iconbar import iconbar  # type: ignore[attr-defined]

            if iconbar is not None:
                iconbar.setServerError("OK")
        except (ImportError, AttributeError) as exc:
            log.debug("notify_serverConnected: iconbar not available: %s", exc)

        # Hide connection error window
        if self.server_error_window:
            window = self.server_error_window
            if hasattr(window, "hide"):
                try:
                    from jive.ui.window import Window

                    window.hide(getattr(Window, "transitionNone", None))
                except ImportError:
                    window.hide()
            self.server_error_window = None

    def notify_serverDisconnected(self, server: Any, num_user_requests: int) -> None:
        """Called when the server disconnects."""
        if self._server != server:
            return

        try:
            from jive.iconbar import iconbar  # type: ignore[attr-defined]

            if iconbar is not None:
                iconbar.setServerError("ERROR")
        except (ImportError, AttributeError) as exc:
            log.debug("notify_serverDisconnected: iconbar not available: %s", exc)

    def notify_networkOrServerNotOK(self, iface: Any = None) -> None:
        """Called when there's a network or server error."""
        log.warn("notify_networkOrServerNotOK()")
        if iface is not None and hasattr(iface, "isNetworkError"):
            if iface.isNetworkError():
                log.warn("this is a network error")
                self._network_error = iface
            else:
                log.warn("this is a server error")
                self._server_error = True
        else:
            self._server_error = True

    def notify_networkAndServerOK(self, iface: Any = None) -> None:
        """Called when network and server are OK again."""
        self._network_error = False
        self._server_error = False
        if self._diag_window:
            if hasattr(self._diag_window, "hide"):
                self._diag_window.hide()
            self._diag_window = False

    def notify_playerDigitalVolumeControl(
        self, player: Any, digital_volume_control: int
    ) -> None:
        """Called when digital volume control setting changes."""
        if player != self._player:
            return

        log.info("notify_playerDigitalVolumeControl: %s", digital_volume_control)

        if digital_volume_control == 0:
            vol = None
            if hasattr(player, "getVolume"):
                vol = player.getVolume()
            self.cached_volume = vol
            log.info("set volume to 100, cached previous: %s", self.cached_volume)

            if hasattr(player, "isLocal") and player.isLocal():
                if hasattr(player, "volumeLocal"):
                    player.volumeLocal(100)
            if hasattr(player, "volume"):
                player.volume(100, True)

        elif self.cached_volume is not None:
            log.info("reset volume to cached level: %s", self.cached_volume)
            if hasattr(player, "isLocal") and player.isLocal():
                if hasattr(player, "volumeLocal"):
                    player.volumeLocal(self.cached_volume)
            if hasattr(player, "volume"):
                player.volume(self.cached_volume, True)

    def notify_playerPower(self, player: Any, power: bool) -> None:
        """Called when player power changes."""
        log.debug("SlimBrowser.notify_playerPower")
        if self._player != player:
            return

        step = self._status_step
        if step is not None and step.get("menu"):
            if power and step.get("window"):
                empty = self._empty_step
                if empty and empty.get("window"):
                    window = step["window"]
                    if hasattr(window, "replace"):
                        try:
                            from jive.ui.window import Window

                            window.replace(
                                empty["window"],
                                getattr(Window, "transitionFadeIn", None),
                            )
                        except ImportError as exc:
                            log.debug(
                                "notify_playerPower: Window not available for transition: %s",
                                exc,
                            )

    def notify_playerModeChange(self, player: Any, mode: Any) -> None:
        """Called when the player mode changes (play/pause/stop).

        BUG 11819: Current Playlist window should always show Current
        Playlist, so this is intentionally a no-op.  The Lua original
        had an empty body as well.
        """
        # Intentionally empty — see BUG 11819 in the Lua original.
        pass

    # ==================================================================
    # Player attachment
    # ==================================================================

    def _attach_player(self, player: Any) -> None:
        """Attach to a new player."""
        if self._player is player:
            return

        log.debug("_attach_player(%s)", player)

        # Free current player
        if self._player is not None:
            log.debug("Freeing current player")
            self.free()

        # Clear errors
        try:
            from jive.iconbar import iconbar  # type: ignore[attr-defined]

            if iconbar is not None:
                iconbar.setServerError("OK")
        except (ImportError, AttributeError) as exc:
            log.debug("_attach_player: iconbar not available: %s", exc)

        # No cached volume for new player
        self.cached_volume = None

        # Update Volume and Scanner helpers
        if self.volume is not None:
            self.volume.set_player(player)
        if self.scanner is not None:
            self.scanner.set_player(player)
        if self.volume is not None:
            self.volume.set_offline(False)

        # Nothing to do without a player or server
        if player is None:
            return

        server = None
        if hasattr(player, "getSlimServer"):
            server = player.getSlimServer()
        elif hasattr(player, "get_slim_server"):
            server = player.get_slim_server()

        if server is None:
            return

        # Assign locals
        self._player = player
        self._server = server

        # Create playlist status step
        window_spec = self._new_window_spec(
            None,
            {
                "text": self._str("SLIMBROWSER_PLAYLIST"),
                "window": {"menuStyle": "playlist"},
            },
        )
        step, sink = self._new_destination(None, None, window_spec, self._status_sink)
        self._status_step = step

        if step.get("window") and hasattr(step["window"], "setAllowScreensaver"):
            step["window"].setAllowScreensaver(False)

        step["actionModifier"] = "-status"
        step["_isNpChildWindow"] = True

        # Start batch and request status
        comet = None
        if hasattr(server, "comet"):
            comet = server.comet

        if comet and hasattr(comet, "startBatch"):
            comet.startBatch()

        if hasattr(player, "onStage"):
            player.onStage()
        elif hasattr(player, "on_stage"):
            player.on_stage()

        self._request_status()

        if comet and hasattr(comet, "endBatch"):
            comet.endBatch()

        self._install_action_listeners()
        self._install_player_key_handler()

    # ==================================================================
    # Free
    # ==================================================================

    def free(self) -> bool:
        """Free resources and disconnect from the player."""
        log.debug("SlimBrowserApplet:free()")

        if self._player is not None:
            if hasattr(self._player, "offStage"):
                self._player.offStage()
            elif hasattr(self._player, "off_stage"):
                self._player.off_stage()

        self._remove_player_key_handler()
        self._remove_action_listeners()

        self._player = None
        self._server = None

        # Walk down the step stack and close
        while True:
            current = self._get_current_step()
            if current is None:
                break
            window = current.get("window")
            if window is not None and hasattr(window, "hide"):
                window.hide()
            # Pop should happen via EVENT_WINDOW_POP, but ensure progress
            if self._get_current_step() is current:
                self._pop_step()

        if self._status_step is not None:
            window = self._status_step.get("window")
            if window is not None and hasattr(window, "hide"):
                window.hide()

        if self._empty_step and self._empty_step.get("window"):
            window = self._empty_step["window"]
            if hasattr(window, "hide"):
                window.hide()
        self._empty_step = None

        return True


# ======================================================================
# Stubs for headless / test mode
# ======================================================================


class _WindowStub:
    """Minimal window stub when UI is not available."""

    def __init__(self, spec: Optional[Dict[str, Any]] = None) -> None:
        self._spec = spec or {}
        self._title = self._spec.get("text", "")
        self._style = self._spec.get("windowStyle", "text_list")
        self._window_id = self._spec.get("windowId")
        self._widgets: List[Any] = []
        self._listeners: List[Any] = []
        self._allow_screensaver = True
        self.brieflyHandler: Any = None

    def show(self, *args: Any) -> None:
        pass

    def hide(self, *args: Any) -> None:
        pass

    def replace(self, *args: Any) -> None:
        pass

    def addWidget(self, widget: Any) -> None:
        self._widgets.append(widget)

    def removeWidget(self, widget: Any) -> None:
        if widget in self._widgets:
            self._widgets.remove(widget)

    def setTitle(self, title: str, *args: Any) -> None:
        self._title = title

    def getTitle(self) -> str:
        return self._title  # type: ignore[no-any-return]

    def setStyle(self, style: str) -> None:
        self._style = style

    def getStyle(self) -> str:
        return self._style  # type: ignore[no-any-return]

    def setWindowId(self, wid: Any) -> None:
        self._window_id = wid

    def getWindowId(self) -> Any:
        return self._window_id

    def setAllowScreensaver(self, allow: bool) -> None:
        self._allow_screensaver = allow

    def canActivateScreensaver(self) -> bool:
        return self._allow_screensaver

    def isContextMenu(self) -> bool:
        return bool(self._spec.get("isContextMenu"))

    def setButtonAction(self, *args: Any) -> None:
        pass

    def addActionListener(self, *args: Any) -> None:
        pass

    def addListener(self, *args: Any) -> None:
        pass

    def setTitleWidget(self, *args: Any) -> None:
        pass

    def getTitleWidget(self) -> Any:
        return None

    def setTitleStyle(self, *args: Any) -> None:
        pass

    def getTitleStyle(self) -> str:
        return "title"

    def setShowFrameworkWidgets(self, *args: Any) -> None:
        pass

    def focusWidget(self, *args: Any) -> None:
        pass

    @staticmethod
    def createDefaultLeftButton() -> Any:
        return None

    @staticmethod
    def createDefaultRightButton() -> Any:
        return None

    def showBriefly(self, *args: Any) -> None:
        pass

    def moveToTop(self) -> None:
        pass

    def bumpLeft(self) -> None:
        pass

    def playSound(self, *args: Any) -> None:
        pass


class _MenuStub:
    """Minimal menu stub when UI is not available."""

    def __init__(self, style: str = "menu") -> None:
        self._style = style
        self._items: List[Any] = []
        self._selected_index: int = 1
        self.numWidgets: int = 0

    def setItems(self, *args: Any) -> None:
        pass

    def set_items(self, *args: Any) -> None:
        pass

    def setSelectedIndex(self, index: int) -> None:
        self._selected_index = index

    def getSelectedIndex(self) -> int:
        return self._selected_index

    def lock(self, *args: Any) -> None:
        pass

    def unlock(self) -> None:
        pass

    def reLayout(self) -> None:
        pass

    def setStyle(self, style: str) -> None:
        self._style = style

    def getStyle(self) -> str:
        return self._style

    def isAccelerated(self) -> Tuple[bool, int]:
        return (False, 0)

    def setDisableVerticalBump(self, *args: Any) -> None:
        pass

    def addItem(self, item: Any) -> None:
        self._items.append(item)

    def removeItem(self, item: Any) -> None:
        if item in self._items:
            self._items.remove(item)

    def _updateWidgets(self) -> None:
        pass

    def _event(self, *args: Any) -> None:
        pass

    def setComparator(self, *args: Any) -> None:
        pass

    def setHeaderWidget(self, *args: Any) -> None:
        pass
