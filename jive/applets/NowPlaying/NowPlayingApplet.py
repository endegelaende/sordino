"""
jive.applets.now_playing.now_playing_applet — NowPlaying screen applet.

Ported from ``share/jive/applets/NowPlaying/NowPlayingApplet.lua``
(~2 012 LOC Lua) in the original jivelite project.

NowPlaying is the screen that displays the currently playing track with:

* Album artwork (fetched from the server)
* Track / artist / album text (with configurable scroll behaviour)
* Transport controls (play/pause, rew, fwd, repeat, shuffle)
* Progress bar with elapsed / remaining time
* Volume slider
* Multiple view styles that can be toggled through
* X-of-Y playlist position indicator

The applet also acts as a screensaver and registers ``goNowPlaying``
and ``hideNowPlaying`` services.

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

import math
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from jive.applet import Applet
from jive.ui.constants import (
    EVENT_CONSUME,
    EVENT_KEY_DOWN,
    EVENT_KEY_PRESS,
    EVENT_SCROLL,
    EVENT_UNUSED,
    EVENT_WINDOW_ACTIVE,
    KEY_LEFT,
    KEY_RIGHT,
    LAYER_ALL,
)
from jive.utils.log import logger

__all__ = ["NowPlayingApplet"]

log = logger("applet.NowPlaying")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MODE_TOKENS: Dict[str, str] = {
    "off": "SCREENSAVER_OFF",
    "play": "SCREENSAVER_NOWPLAYING",
    "pause": "SCREENSAVER_PAUSED",
    "stop": "SCREENSAVER_STOPPED",
}

_REPEAT_MODES: Dict[str, str] = {
    "mode0": "repeatOff",
    "mode1": "repeatSong",
    "mode2": "repeatPlaylist",
}

_SHUFFLE_MODES: Dict[str, str] = {
    "mode0": "shuffleOff",
    "mode1": "shuffleSong",
    "mode2": "shuffleAlbum",
}

_SCROLL_TIMEOUT = 750


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _uses(parent: Dict[str, Any], value: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Create a style dict that inherits from *parent*.

    Works like Lua ``_uses()`` — recursively inherits table keys.
    """
    style: Dict[str, Any] = {}
    # shallow copy parent
    for k, v in parent.items():
        style[k] = v
    if value:
        for k, v in value.items():
            if isinstance(v, dict) and isinstance(style.get(k), dict):
                style[k] = _uses(style[k], v)
            else:
                style[k] = v
    return style


def _seconds_to_string(seconds: Union[int, float]) -> str:
    """Format *seconds* as ``H:MM:SS`` or ``M:SS``."""
    total = int(seconds)
    if total < 0:
        total = 0
    hrs = total // 3600
    mins = (total % 3600) // 60
    secs = total % 60
    if hrs > 0:
        return f"{hrs}:{mins:02d}:{secs:02d}"
    return f"{mins}:{secs:02d}"


# ---------------------------------------------------------------------------
# Lazy import helpers (avoid circular imports at module level)
# ---------------------------------------------------------------------------


def _get_applet_manager() -> Any:
    try:
        from jive.applet_manager import applet_manager

        return applet_manager
    except (ImportError, AttributeError):
        return None


def _get_jive_main() -> Any:
    try:
        from jive.jive_main import jive_main

        return jive_main
    except (ImportError, AttributeError) as exc:
        log.debug("_get_jive_main primary import failed: %s", exc)
    try:
        import jive.jive_main as _mod

        return getattr(_mod, "jive_main", None)
    except ImportError:
        return None


def _get_framework() -> Any:
    try:
        from jive.ui.framework import framework

        return framework
    except ImportError:
        return None


def _import_ui_class(module_name: str, class_name: str) -> Any:
    """Dynamically import a UI class to keep top-level imports light."""
    import importlib

    mod = importlib.import_module(f"jive.ui.{module_name}")
    return getattr(mod, class_name)


# Cached UI class accessors (populated on first use) -----------------------

_ui_cache: Dict[str, Any] = {}


def _Window() -> Any:
    if "Window" not in _ui_cache:
        _ui_cache["Window"] = _import_ui_class("window", "Window")
    return _ui_cache["Window"]


def _SimpleMenu() -> Any:
    if "SimpleMenu" not in _ui_cache:
        _ui_cache["SimpleMenu"] = _import_ui_class("simplemenu", "SimpleMenu")
    return _ui_cache["SimpleMenu"]


def _Label() -> Any:
    if "Label" not in _ui_cache:
        _ui_cache["Label"] = _import_ui_class("label", "Label")
    return _ui_cache["Label"]


def _Icon() -> Any:
    if "Icon" not in _ui_cache:
        _ui_cache["Icon"] = _import_ui_class("icon", "Icon")
    return _ui_cache["Icon"]


def _Button() -> Any:
    if "Button" not in _ui_cache:
        _ui_cache["Button"] = _import_ui_class("button", "Button")
    return _ui_cache["Button"]


def _Group() -> Any:
    if "Group" not in _ui_cache:
        _ui_cache["Group"] = _import_ui_class("group", "Group")
    return _ui_cache["Group"]


def _Slider() -> Any:
    if "Slider" not in _ui_cache:
        _ui_cache["Slider"] = _import_ui_class("slider", "Slider")
    return _ui_cache["Slider"]


def _Checkbox() -> Any:
    if "Checkbox" not in _ui_cache:
        _ui_cache["Checkbox"] = _import_ui_class("checkbox", "Checkbox")
    return _ui_cache["Checkbox"]


def _RadioButton() -> Any:
    if "RadioButton" not in _ui_cache:
        _ui_cache["RadioButton"] = _import_ui_class("radio", "RadioButton")
    return _ui_cache["RadioButton"]


def _RadioGroup() -> Any:
    if "RadioGroup" not in _ui_cache:
        _ui_cache["RadioGroup"] = _import_ui_class("radio", "RadioGroup")
    return _ui_cache["RadioGroup"]


def _Timer() -> Any:
    if "Timer" not in _ui_cache:
        _ui_cache["Timer"] = _import_ui_class("timer", "Timer")
    return _ui_cache["Timer"]


def _Textarea() -> Any:
    if "Textarea" not in _ui_cache:
        _ui_cache["Textarea"] = _import_ui_class("textarea", "Textarea")
    return _ui_cache["Textarea"]


def _Surface() -> Any:
    if "Surface" not in _ui_cache:
        _ui_cache["Surface"] = _import_ui_class("surface", "Surface")
    return _ui_cache["Surface"]


def _SnapshotWindow() -> Any:
    if "SnapshotWindow" not in _ui_cache:
        _ui_cache["SnapshotWindow"] = _import_ui_class("snapshotwindow", "SnapshotWindow")
    return _ui_cache["SnapshotWindow"]


def _Event() -> Any:
    if "Event" not in _ui_cache:
        _ui_cache["Event"] = _import_ui_class("event", "Event")
    return _ui_cache["Event"]


# ---------------------------------------------------------------------------
# Track-change transition (module-level, like Lua _nowPlayingTrackTransition)
# ---------------------------------------------------------------------------


def _now_playing_track_transition(old_window: Any, new_window: Any) -> Any:
    """2-frame alpha-fade transition for track changes.

    Captures the old window into an off-screen surface, then blends it
    over the new window across 2 frames with decreasing alpha.

    Mirrors Lua ``_nowPlayingTrackTransition()`` in
    ``NowPlayingApplet.lua`` L587–614.
    """
    Surface = _Surface()
    Framework = _get_framework()

    frames = [2]
    scale = 255 / 2  # 127.5 per frame

    # Capture old window content into an off-screen surface
    fw = None
    try:
        from jive.ui.framework import framework as _fw

        fw = _fw
    except (ImportError, AttributeError) as exc:
        log.debug("framework import for transition failed: %s", exc)

    sw, sh = (800, 480)
    if fw is not None:
        try:
            sw, sh = fw.get_screen_size()
        except Exception as exc:
            log.warning("get_screen_size failed, using defaults: %s", exc)

    srf = Surface.new_rgb(sw, sh)
    old_window.draw(srf, int(LAYER_ALL))

    def _step(widget: Any, surface: Any) -> None:
        alpha = int(math.floor(((frames[0] - 1) * scale) + 0.5))

        new_window.draw(surface, int(LAYER_ALL))
        srf.blit_alpha(surface, 0, 0, alpha)

        frames[0] -= 1
        if frames[0] == 0:
            if fw is not None:
                fw._kill_transition()

    return _step


# Lua alias
_nowPlayingTrackTransition = _now_playing_track_transition


# ---------------------------------------------------------------------------
# NowPlayingApplet
# ---------------------------------------------------------------------------


class NowPlayingApplet(Applet):
    """NowPlaying screen applet.

    Displays the currently playing track with artwork, text, transport
    controls, progress and volume sliders, and multiple switchable
    view styles.
    """

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def __init__(self) -> None:
        super().__init__()

        # Player reference (``False`` means "no player" in Lua style)
        self.player: Any = False

        # UI widgets (created lazily when the NP window is built)
        self.window: Any = None
        self.windowStyle: Optional[str] = None
        self.selectedStyle: Optional[str] = None
        self.nowPlayingScreenStyles: List[Dict[str, Any]] = []

        # Title bar
        self.titleGroup: Any = None
        self.mainTitle: str = ""
        self.rbutton: str = "playlist"
        self.suppressTitlebar: bool = False

        # Track text labels
        self.trackTitle: Any = None
        self.albumTitle: Any = None
        self.artistTitle: Any = None
        self.artistalbumTitle: Any = None
        self.XofY: Any = None

        # Track groups
        self.nptrackGroup: Any = None
        self.npartistGroup: Any = None
        self.npalbumGroup: Any = None

        # Artwork
        self.artwork: Any = None
        self.artworkGroup: Any = None
        self.preartwork: Any = None

        # Visualizer
        self.visuGroup: Any = None

        # Controls
        self.controlsGroup: Any = None
        self.rewButton: Any = None
        self.fwdButton: Any = None
        self.repeatButton: Any = None
        self.shuffleButton: Any = None

        # Progress
        self.progressSlider: Any = None
        self.progressBarGroup: Any = None
        self.progressNBGroup: Any = None
        self.progressGroup: Any = None

        # Volume
        self.volSlider: Any = None
        self.volumeOld: int = 0
        self.fixedVolumeSet: bool = False
        self.volumeSliderDragInProgress: bool = False
        self.volumeAfterRateLimit: Optional[int] = None
        self.volumeRateLimitTimer: Any = None
        self.lastVolumeSliderAdjustT: int = 0

        # Goto (seek) timer
        self.gotoTimer: Any = None
        self.gotoElapsed: Optional[float] = None

        # Scroll
        self.scrollText: bool = True
        self.scrollTextOnce: bool = False
        self.scrollSwitchTimer: Any = None

        # Scroll wheel NP-style toggling
        self.lastScrollDirection: Optional[int] = None
        self.lastScrollTime: Optional[int] = None
        self.cumulativeScrollTicks: int = 0

        # Track-change snapshot transition
        self.snapshot: Any = None

        # Screensaver flag
        self.isScreensaver: bool = False

        # NowPlaying menu item
        self.nowPlayingItem: bool = False

        # Currently-shown track id (for detecting changes)
        self.nowPlaying: Any = None

        # Show progress bar flag (module-level in Lua)
        self._showProgressBar: bool = True

    def init(self) -> None:  # noqa: D401 — match Lua naming
        """Initialise the applet after settings / strings are available."""
        super().init()

        # Subscribe to player notifications
        jnt = self._get_jnt()
        if jnt is not None:
            jnt.subscribe(self)

        self.player = False
        self.lastVolumeSliderAdjustT = 0
        self.cumulativeScrollTicks = 0

        settings = self.get_settings() or {}
        self.scrollText = settings.get("scrollText", True)
        self.scrollTextOnce = settings.get("scrollTextOnce", False)

    # ------------------------------------------------------------------
    # NP style management
    # ------------------------------------------------------------------

    def getNPStyles(self) -> List[Dict[str, Any]]:
        """Return the audited list of NP screen styles.

        Styles are fetched from the current skin, filtered by player
        locality (visualiser styles require a local player) and user
        settings, and returned as a list of dicts with at least
        ``style``, ``text``, ``enabled``.
        """
        jive_main = _get_jive_main()
        np_skin_styles: List[Dict[str, Any]] = []
        if jive_main is not None:
            param = jive_main.get_skin_param("nowPlayingScreenStyles")
            if param:
                np_skin_styles = list(param)

        audited: List[Dict[str, Any]] = []

        if not self.player:
            return audited

        settings = self.get_settings() or {}
        player_id = self._player_id()

        # Restore selected style from settings
        if not self.selectedStyle and settings.get("selectedStyle"):
            self.selectedStyle = settings["selectedStyle"]

        for entry in np_skin_styles:
            v = dict(entry)  # shallow copy
            if settings.get("views") and v["style"] in settings["views"]:
                v["enabled"] = settings["views"][v["style"]] is not False
            else:
                v["enabled"] = True

            # Non-local player cannot use localPlayerOnly styles
            if not self._player_is_local() and v.get("localPlayerOnly"):
                if v["style"] == self.selectedStyle:
                    self.selectedStyle = None
            else:
                audited.append(v)
                if not self.selectedStyle and v["enabled"]:
                    self.selectedStyle = v["style"]
                elif self.selectedStyle == v["style"] and not v["enabled"]:
                    self.selectedStyle = False  # type: ignore[assignment]

        # Verify selected style is available
        if self.selectedStyle:
            found = any(s["enabled"] and s["style"] == self.selectedStyle for s in audited)
            if not found:
                self.selectedStyle = False  # type: ignore[assignment]

        # Corner case: nothing enabled — enable everything possible
        if not any(s["enabled"] for s in audited):
            log.warn("No enabled NP styles, enabling all possible")
            audited = []
            for entry in np_skin_styles:
                v = dict(entry)
                v["enabled"] = True
                if not self._player_is_local() and v.get("localPlayerOnly"):
                    continue
                audited.append(v)

        # Fallback to first style
        if not self.selectedStyle and audited:
            self.selectedStyle = audited[0]["style"]

        # Persist if changed
        if settings.get("selectedStyle") != self.selectedStyle:
            settings["selectedStyle"] = self.selectedStyle
            self.store_settings()

        # If existing window has a mismatched style, discard it
        if self.window and hasattr(self.window, "getStyle"):
            ws = self.window.getStyle()
            if ws != self.selectedStyle:
                self.window = None

        return audited

    # ------------------------------------------------------------------
    # Settings screens
    # ------------------------------------------------------------------

    def npviews_settings_show(self, *_args: Any, **_kwargs: Any) -> None:
        """Show the NP-views settings screen."""
        Window = _Window()
        Checkbox = _Checkbox()
        SimpleMenu = _SimpleMenu()
        Framework = _get_framework()

        window = Window("text_list", str(self.string("NOW_PLAYING_VIEWS")))
        menu = SimpleMenu("menu")

        np_views = self.getNPStyles()
        settings = self.get_settings() or {}

        if "views" not in settings:
            settings["views"] = {}

        # Seed settings.views if empty
        if not settings["views"]:
            for v in np_views:
                settings["views"][v["style"]] = True
                v["enabled"] = True
            self.store_settings()

        # Ensure any new styles are in settings
        for v in np_views:
            if v["style"] not in settings["views"]:
                settings["views"][v["style"]] = True

        for v in np_views:
            selected = v.get("enabled", True)
            style_key = v["style"]

            def _make_cb(sk: str) -> Callable[..., Any]:
                def _on_check(obj: Any, is_selected: bool) -> None:
                    s = self.get_settings() or {}
                    if is_selected:
                        s.setdefault("views", {})[sk] = True
                    else:
                        views = s.get("views", {})
                        enabled_count = sum(1 for val in views.values() if val)
                        if enabled_count > 1:
                            if self.selectedStyle == sk:
                                self.selectedStyle = None
                                self.window = None
                            views[sk] = False
                        else:
                            log.warn("Minimum one NP view required")
                            if Framework is not None:
                                Framework.playSound("BUMP")
                            if hasattr(window, "bumpLeft"):
                                window.bumpLeft()
                            obj.setSelected(True)
                    self.store_settings()

                return _on_check

            menu.addItem(
                {
                    "text": v.get("text", style_key),
                    "style": "item_choice",
                    "check": Checkbox("checkbox", _make_cb(style_key), selected),
                }
            )

        window.addWidget(menu)
        if hasattr(window, "show"):
            window.show()

    def scroll_settings_show(self, *_args: Any, **_kwargs: Any) -> None:
        """Show the scroll-mode settings screen."""
        Window = _Window()
        RadioBtn = _RadioButton()
        RGroup = _RadioGroup()
        SimpleMenu = _SimpleMenu()

        window = Window("text_list", str(self.string("SCREENSAVER_SCROLLMODE")))
        group = RGroup()

        menu = SimpleMenu(
            "menu",
            [
                {
                    "text": str(self.string("SCREENSAVER_SCROLLMODE_DEFAULT")),
                    "style": "item_choice",
                    "check": RadioBtn(
                        "radio",
                        group,
                        lambda *_a: self.set_scroll_behavior("always"),
                        self.scrollText and not self.scrollTextOnce,
                    ),
                },
                {
                    "text": str(self.string("SCREENSAVER_SCROLLMODE_SCROLLONCE")),
                    "style": "item_choice",
                    "check": RadioBtn(
                        "radio",
                        group,
                        lambda *_a: self.set_scroll_behavior("once"),
                        self.scrollText and self.scrollTextOnce,
                    ),
                },
                {
                    "text": str(self.string("SCREENSAVER_SCROLLMODE_NOSCROLL")),
                    "style": "item_choice",
                    "check": RadioBtn(
                        "radio",
                        group,
                        lambda *_a: self.set_scroll_behavior("never"),
                        not self.scrollText,
                    ),
                },
            ],
        )

        window.addWidget(menu)
        if hasattr(window, "show"):
            window.show()

    def set_scroll_behavior(self, setting: str) -> None:
        """Apply a scroll-mode setting and persist it."""
        if setting == "once":
            self.scrollText = True
            self.scrollTextOnce = True
            self._add_scroll_switch_timer()
        elif setting == "never":
            self.scrollText = False
            self.scrollTextOnce = False
            self.scrollSwitchTimer = None
        else:
            self.scrollText = True
            self.scrollTextOnce = False
            self._add_scroll_switch_timer()

        settings = self.get_settings() or {}
        settings["scrollText"] = self.scrollText
        settings["scrollTextOnce"] = self.scrollTextOnce
        self.store_settings()

    # Lua-compatible alias
    setScrollBehavior = set_scroll_behavior
    scrollSettingsShow = scroll_settings_show
    npviewsSettingsShow = npviews_settings_show

    # ------------------------------------------------------------------
    # Notification handlers
    # ------------------------------------------------------------------

    def notify_playerShuffleModeChange(self, player: Any, shuffle_mode: Any) -> None:
        if player is not self.player:
            return
        log.debug("notify_playerShuffleModeChange: %s", shuffle_mode)
        self._update_shuffle(shuffle_mode)

    def notify_playerDigitalVolumeControl(self, player: Any, dvc: Any) -> None:
        if player is not self.player:
            return
        log.info("notify_playerDigitalVolumeControl: %s", dvc)
        self._set_volume_slider_style()

    def notify_playerRepeatModeChange(self, player: Any, repeat_mode: Any) -> None:
        if player is not self.player:
            return
        log.debug("notify_playerRepeatModeChange: %s", repeat_mode)
        self._update_repeat(repeat_mode)

    def notify_playerTitleStatus(
        self, player: Any, text: str, duration: Optional[int] = None
    ) -> None:
        if player is not self.player:
            return
        log.debug("notify_playerTitleStatus: %s", text)
        self._set_title_status(text, duration)

    def notify_playerPower(self, player: Any, power: Any) -> None:
        if player is not self.player:
            return
        log.debug("notify_playerPower: %s", power)
        mode = self._player_play_mode()
        if not power:
            if self.titleGroup:
                self.change_title_text(self._title_text("off"))
        else:
            if self.titleGroup:
                self.change_title_text(self._title_text(mode))

    def notify_playerTrackChange(self, player: Any, now_playing: Any, artwork: Any) -> None:
        if player is not self.player:
            return
        log.debug("notify_playerTrackChange: %s", now_playing)

        if not self._is_this_player(player):
            return

        self.player = player
        player_status = self._player_status()

        if self._player_playlist_size() == 0 and self.window is not None:
            Window = _Window()
            if hasattr(Window, "getTopNonTransientWindow"):
                top = Window.getTopNonTransientWindow()
                if top is self.window:
                    mgr = _get_applet_manager()
                    if mgr:
                        mgr.call_service("showPlaylist")
                    return

        if self.window is None:
            return

        # Snapshot transition
        SnapshotWindow = _SnapshotWindow()
        if self.snapshot is None:
            self.snapshot = SnapshotWindow()
        else:
            if hasattr(self.snapshot, "refresh"):
                self.snapshot.refresh()

        if hasattr(self.snapshot, "replace"):
            self.snapshot.replace(self.window)
        if hasattr(self.window, "replace"):
            self.window.replace(self.snapshot, _now_playing_track_transition)

        if player_status and player_status.get("item_loop") and self.nowPlaying != now_playing:
            self.nowPlaying = now_playing

        self.replace_np_window()

    def notify_playerPlaylistChange(self, player: Any) -> None:
        if player is not self.player:
            return
        log.debug("notify_playerPlaylistChange")
        self._update_all()

    def notify_playerModeChange(self, player: Any, mode: str) -> None:
        if not self.player:
            return
        log.debug("notify_playerModeChange: %s", mode)
        self._update_mode(mode)

    def notify_playerDelete(self, player: Any) -> None:
        if player is not self.player:
            return
        log.debug("notify_playerDelete: %s", player)
        self.free_and_clear()

    def notify_playerCurrent(self, player: Any) -> None:
        if self.player is not player:
            self.free_and_clear()
        log.debug("notify_playerCurrent: %s", player)

        self.player = player
        self._set_volume_slider_style()

        if not self.player:
            return

        jive_main = _get_jive_main()
        if jive_main is not None:
            np_menu = (
                jive_main.get_skin_param("NOWPLAYING_MENU")
                if hasattr(jive_main, "get_skin_param")
                else None
            )
            if np_menu:
                self.add_now_playing_item()
            else:
                self.remove_now_playing_item()

    def notify_skinSelected(self) -> None:
        log.debug("notify_skinSelected")
        self.notify_playerCurrent(self.player)
        self.nowPlayingScreenStyles = self.getNPStyles()
        if self.window and self.player:
            self.replace_np_window(no_trans=True)

    # ------------------------------------------------------------------
    # Title helpers
    # ------------------------------------------------------------------

    def _title_text(self, token: str) -> str:
        y = self._player_playlist_size()
        title: str
        if token == "play" and y is not None and y > 1:
            x = self._player_playlist_current_index()
            if (
                x is not None
                and x >= 1
                and y > 1
                and not self.get_selected_style_param("suppressXofY")
            ):
                xofy = str(self.string("SCREENSAVER_NOWPLAYING_OF", x, y))
                if self.get_selected_style_param("titleXofYonly"):
                    title = xofy
                else:
                    title = str(self.string(_MODE_TOKENS.get(token, token))) + " • " + xofy
            else:
                title = str(self.string(_MODE_TOKENS.get(token, token)))
        else:
            title = str(self.string(_MODE_TOKENS.get(token, token)))
        self.mainTitle = title
        return self.mainTitle

    def change_title_text(self, title_text: str) -> None:
        if self.titleGroup and hasattr(self.titleGroup, "setWidgetValue"):
            self.titleGroup.setWidgetValue("text", title_text)

    # Lua alias
    changeTitleText = change_title_text

    # ------------------------------------------------------------------
    # Menu item management
    # ------------------------------------------------------------------

    def remove_now_playing_item(self) -> None:
        jive_main = _get_jive_main()
        if jive_main is not None:
            jive_main.remove_item_by_id("appletNowPlaying")
        self.nowPlayingItem = False

    def add_now_playing_item(self) -> None:
        jive_main = _get_jive_main()
        if jive_main is None:
            return
        jive_main.add_item(
            {
                "id": "appletNowPlaying",
                "iconStyle": "hm_appletNowPlaying",
                "node": "home",
                "text": self.string("SCREENSAVER_NOWPLAYING"),
                "sound": "WINDOWSHOW",
                "weight": 1,
                "callback": lambda event=None, mi=None: self.goNowPlaying(
                    _Window().transitionPushLeft
                    if hasattr(_Window(), "transitionPushLeft")
                    else None
                ),
            }
        )
        self.nowPlayingItem = True

    # Lua aliases
    removeNowPlayingItem = remove_now_playing_item
    addNowPlayingItem = add_now_playing_item

    # ------------------------------------------------------------------
    # Selected-style param helper
    # ------------------------------------------------------------------

    def get_selected_style_param(self, param: str) -> Any:
        for v in self.nowPlayingScreenStyles:
            if v.get("style") == self.selectedStyle:
                return v.get(param)
        return None

    # Lua alias
    getSelectedStyleParam = get_selected_style_param

    # ------------------------------------------------------------------
    # Volume
    # ------------------------------------------------------------------

    def _set_volume_slider_style(self) -> None:
        if self.volSlider is None:
            return
        if not self.player:
            return
        use_vol = 1
        if hasattr(self.player, "use_volume_control"):
            use_vol = self.player.use_volume_control()
        elif hasattr(self.player, "useVolumeControl"):
            use_vol = self.player.useVolumeControl()
        if use_vol == 0:
            log.info("disable volume UI in NP")
            if hasattr(self.volSlider, "setStyle"):
                self.volSlider.setStyle("npvolumeB_disabled")
            if hasattr(self.volSlider, "setEnabled"):
                self.volSlider.setEnabled(False)
            if hasattr(self.volSlider, "setValue"):
                self.volSlider.setValue(100)
            self.fixedVolumeSet = True
        else:
            log.info("enable volume UI in NP")
            if hasattr(self.volSlider, "setStyle"):
                self.volSlider.setStyle("npvolumeB")
            if hasattr(self.volSlider, "setEnabled"):
                self.volSlider.setEnabled(True)
            self.fixedVolumeSet = False

    def _update_volume(self) -> None:
        if not self.player:
            return
        volume = self._player_volume()
        if self.volSlider and not self.fixedVolumeSet:
            slider_vol = None
            if hasattr(self.volSlider, "getValue"):
                slider_vol = self.volSlider.getValue()
            if slider_vol != volume:
                log.debug("new volume from player: %s", volume)
                self.volumeOld = volume if volume is not None else 0
                if hasattr(self.volSlider, "setValue"):
                    self.volSlider.setValue(volume if volume is not None else 0)

    def _set_player_volume(self, value: int) -> None:
        Framework = _get_framework()
        if Framework is not None and hasattr(Framework, "getTicks"):
            self.lastVolumeSliderAdjustT = Framework.getTicks()
        if value != self.volumeOld and self.player:
            if hasattr(self.player, "volume"):
                self.player.volume(value, True)
            self.volumeOld = value

    def adjust_volume(self, value: int, use_rate_limit: bool = False) -> None:
        """Adjust player volume with optional rate limiting."""
        Timer = _Timer()
        if self.volumeRateLimitTimer is None:

            def _on_rate_limit_timeout() -> None:
                if not self.player:
                    return
                if self.volumeAfterRateLimit is not None:
                    self._set_player_volume(self.volumeAfterRateLimit)

            self.volumeRateLimitTimer = Timer(100, _on_rate_limit_timeout, True)

        if self.player:
            Framework = _get_framework()
            now = 0
            if Framework is not None and hasattr(Framework, "getTicks"):
                now = Framework.getTicks()
            if not use_rate_limit or now > 350 + self.lastVolumeSliderAdjustT:
                if hasattr(self.volumeRateLimitTimer, "restart"):
                    self.volumeRateLimitTimer.restart()
                self._set_player_volume(value)
                self.volumeAfterRateLimit = None
            else:
                self.volumeAfterRateLimit = value

    # Lua alias
    adjustVolume = adjust_volume

    # ------------------------------------------------------------------
    # Title status (show-briefly messages)
    # ------------------------------------------------------------------

    def _set_title_status(self, text: str, duration: Optional[int] = None) -> None:
        log.debug("_setTitleStatus: %s", text)
        jive_main = _get_jive_main()
        np_trackinfo_lines = 3
        if jive_main is not None and hasattr(jive_main, "get_skin_param"):
            val = jive_main.get_skin_param("NOWPLAYING_TRACKINFO_LINES")
            if val is not None:
                np_trackinfo_lines = int(val)

        msgs = text.split("\n") if text else [""]

        if np_trackinfo_lines == 2 and self.artistalbumTitle:
            if len(msgs) > 1:
                if hasattr(self.artistalbumTitle, "setValue"):
                    self.artistalbumTitle.setValue(msgs[0], duration)
                if len(msgs[1]) > 0 and self.trackTitle and hasattr(self.trackTitle, "setValue"):
                    self.trackTitle.setValue(msgs[1], duration)
            else:
                if self.trackTitle and hasattr(self.trackTitle, "setValue"):
                    self.trackTitle.setValue(msgs[0], duration)
                if hasattr(self.artistalbumTitle, "setValue") and hasattr(
                    self.artistalbumTitle, "getValue"
                ):
                    self.artistalbumTitle.setValue(self.artistalbumTitle.getValue(), duration)
        elif np_trackinfo_lines == 3 and self.titleGroup:
            if len(msgs) == 1:
                if hasattr(self.titleGroup, "setWidgetValue"):
                    self.titleGroup.setWidgetValue("text", msgs[0], duration)
                if self.trackTitle and hasattr(self.trackTitle, "setValue"):
                    val = self.trackTitle.getValue() if hasattr(self.trackTitle, "getValue") else ""
                    self.trackTitle.setValue(val, duration)
                if self.albumTitle and hasattr(self.albumTitle, "setValue"):
                    self.albumTitle.setValue("", duration)
                if self.artistTitle and hasattr(self.artistTitle, "setValue"):
                    self.artistTitle.setValue("", duration)
            elif len(msgs) >= 2:
                if hasattr(self.titleGroup, "setWidgetValue"):
                    self.titleGroup.setWidgetValue("text", msgs[0], duration)
                if self.trackTitle and hasattr(self.trackTitle, "setValue"):
                    self.trackTitle.setValue(msgs[1], duration)
                if self.artistTitle and hasattr(self.artistTitle, "setValue"):
                    self.artistTitle.setValue("", duration)
                if self.albumTitle and hasattr(self.albumTitle, "setValue"):
                    self.albumTitle.setValue("", duration)

    # ------------------------------------------------------------------
    # Update helpers
    # ------------------------------------------------------------------

    def _update_all(self) -> None:
        player_status = self._player_status()
        if not player_status:
            # Volume is independent of player status — always update it
            self._update_volume()
            return

        item_loop = player_status.get("item_loop")
        if item_loop:
            track_info = self._extract_track_info(item_loop[0])

            if (
                player_status.get("remote") == 1
                and isinstance(player_status.get("current_title"), str)
                and isinstance(track_info, str)
            ):
                track_info = track_info + "\n" + player_status["current_title"]

            if self.window:
                self._get_icon(item_loop[0], self.artwork, player_status.get("remote"))
                self._update_track(track_info)
                self._update_progress(player_status)
                self._update_buttons(player_status)
                self._refresh_right_button()
                self._update_playlist()
                self._update_mode(player_status.get("mode", "stop"))

                # preload artwork for next track
                if len(item_loop) > 1:
                    Icon = _Icon()
                    self._get_icon(item_loop[1], Icon("artwork"), player_status.get("remote"))
        else:
            if self.window:
                self._get_icon(None, self.artwork, None)
                self._update_track("\n\n")
                self._update_playlist()

        self._update_volume()

    def _update_buttons(self, player_status: Dict[str, Any]) -> None:
        if not self.player or not self.controlsGroup:
            return

        remote_meta = player_status.get("remoteMeta")
        buttons = remote_meta.get("buttons") if remote_meta else None

        if buttons:
            # Remap rew
            if buttons.get("rew") and int(buttons["rew"]) == 0:
                self._remap_button("rew", "rewDisabled", None)
            elif self.rewButton:
                if hasattr(self.controlsGroup, "setWidget"):
                    self.controlsGroup.setWidget("rew", self.rewButton)

            # Remap fwd
            if buttons.get("fwd") and int(buttons["fwd"]) == 0:
                self._remap_button("fwd", "fwdDisabled", None)
            elif self.fwdButton:
                if hasattr(self.controlsGroup, "setWidget"):
                    self.controlsGroup.setWidget("fwd", self.fwdButton)

            # Remap shuffle
            if buttons.get("shuffle"):
                shuffle_btn = buttons["shuffle"]

                def _make_shuffle_cb(cmd: Any) -> Callable[..., Any]:
                    def _cb() -> int:
                        pid = self._player_id()
                        server = self._player_server()
                        if server and hasattr(server, "userRequest"):
                            server.userRequest(None, pid, cmd)
                        return EVENT_CONSUME

                    return _cb

                self._remap_button(
                    "shuffleMode",
                    shuffle_btn.get("jiveStyle"),
                    _make_shuffle_cb(shuffle_btn.get("command")),
                )

            # Remap repeat
            if buttons.get("repeat"):
                repeat_btn = buttons["repeat"]

                def _make_repeat_cb(cmd: Any) -> Callable[..., Any]:
                    def _cb() -> int:
                        pid = self._player_id()
                        server = self._player_server()
                        if server and hasattr(server, "userRequest"):
                            server.userRequest(None, pid, cmd)
                        return EVENT_CONSUME

                    return _cb

                self._remap_button(
                    "repeatMode",
                    repeat_btn.get("jiveStyle"),
                    _make_repeat_cb(repeat_btn.get("command")),
                )
        else:
            playlist_size = self._player_playlist_size() or 0
            is_remote = self._player_is_remote()

            if playlist_size == 1 and not is_remote:
                elapsed, duration = self._player_track_elapsed()
                if duration:
                    if hasattr(self.controlsGroup, "setWidget") and self.rewButton:
                        self.controlsGroup.setWidget("rew", self.rewButton)
                else:
                    self._remap_button("rew", "rewDisabled", lambda: EVENT_CONSUME)

                self._remap_button("fwd", "fwdDisabled", lambda: EVENT_CONSUME)
                self._remap_button("shuffleMode", "shuffleDisabled", lambda: EVENT_CONSUME)
                if hasattr(self.controlsGroup, "setWidget") and self.repeatButton:
                    self.controlsGroup.setWidget("repeatMode", self.repeatButton)
            else:
                if hasattr(self.controlsGroup, "setWidget"):
                    if self.rewButton:
                        self.controlsGroup.setWidget("rew", self.rewButton)
                    if self.fwdButton:
                        self.controlsGroup.setWidget("fwd", self.fwdButton)
                    if self.shuffleButton:
                        self.controlsGroup.setWidget("shuffleMode", self.shuffleButton)
                    if self.repeatButton:
                        self.controlsGroup.setWidget("repeatMode", self.repeatButton)
                # Bug 15618: explicitly set style of rew and fwd here,
                # since setWidget doesn't appear to be doing the job.
                if hasattr(self.controlsGroup, "getWidget"):
                    rew_w = self.controlsGroup.getWidget("rew")
                    if rew_w and hasattr(rew_w, "setStyle"):
                        rew_w.setStyle("rew")
                    fwd_w = self.controlsGroup.getWidget("fwd")
                    if fwd_w and hasattr(fwd_w, "setStyle"):
                        fwd_w.setStyle("fwd")

    def _refresh_right_button(self) -> None:
        playlist_size = self._player_playlist_size()
        if not playlist_size:
            return
        if playlist_size == 1 and self.rbutton == "playlist":
            if not self.suppressTitlebar and self.titleGroup:
                widget = (
                    self.titleGroup.getWidget("rbutton")
                    if hasattr(self.titleGroup, "getWidget")
                    else None
                )
                if widget and hasattr(widget, "setStyle"):
                    widget.setStyle("button_more")
            self.rbutton = "more"
        elif self.rbutton == "more" and playlist_size > 1:
            if not self.suppressTitlebar and self.titleGroup:
                widget = (
                    self.titleGroup.getWidget("rbutton")
                    if hasattr(self.titleGroup, "getWidget")
                    else None
                )
                if widget and hasattr(widget, "setStyle"):
                    widget.setStyle("button_playlist")
            self.rbutton = "playlist"

    def _remap_button(
        self,
        key: str,
        new_style: Optional[str],
        new_callback: Optional[Callable[..., Any]],
    ) -> None:
        if not self.controlsGroup:
            return
        Icon = _Icon()
        Button = _Button()
        if new_callback is not None:
            # Button installs mouse listeners on the widget but is not
            # itself a Widget.  In Lua, Button:__init() returns the
            # widget; in Python __init__ cannot return a different object.
            new_widget = Icon(key)
            Button(new_widget, new_callback)
            if hasattr(self.controlsGroup, "setWidget"):
                self.controlsGroup.setWidget(key, new_widget)
        widget = (
            self.controlsGroup.getWidget(key) if hasattr(self.controlsGroup, "getWidget") else None
        )
        if widget and new_style and hasattr(widget, "setStyle"):
            widget.setStyle(new_style)

    def _update_playlist(self) -> None:
        x = self._player_playlist_current_index()
        y = self._player_playlist_size()
        xofy = ""
        if x and y and int(x) > 0 and int(y) >= int(x):
            xofy = f"{x}/{y}"

        if self.XofY is None:
            return

        xofy_len = len(xofy)
        xofy_style = self.XofY.getStyle() if hasattr(self.XofY, "getStyle") else "xofy"

        if xofy_len > 5 and xofy_style != "xofySmall":
            if hasattr(self.XofY, "setStyle"):
                self.XofY.setStyle("xofySmall")
        elif xofy_len <= 5 and xofy_style != "xofy":
            if hasattr(self.XofY, "setStyle"):
                self.XofY.setStyle("xofy")

        if hasattr(self.XofY, "setValue"):
            self.XofY.setValue(xofy)
        if hasattr(self.XofY, "animate"):
            self.XofY.animate(True)

    def _update_track(
        self, trackinfo: Union[str, List[str]], pos: Any = None, length: Any = None
    ) -> None:
        if self.trackTitle is None:
            return

        if isinstance(trackinfo, list):
            track_table = trackinfo
        else:
            track_table = trackinfo.split("\n")

        track = track_table[0] if len(track_table) > 0 else ""
        artist = track_table[1] if len(track_table) > 1 else ""
        album = track_table[2] if len(track_table) > 2 else ""

        artistalbum = ""
        if artist and album:
            artistalbum = artist + " • " + album
        elif artist:
            artistalbum = artist
        elif album:
            artistalbum = album

        if self.scrollSwitchTimer and hasattr(self.scrollSwitchTimer, "isRunning"):
            if self.scrollSwitchTimer.isRunning():
                self.scrollSwitchTimer.stop()

        if hasattr(self.trackTitle, "setValue"):
            self.trackTitle.setValue(track)
        if self.albumTitle and hasattr(self.albumTitle, "setValue"):
            self.albumTitle.setValue(album)
        if self.artistTitle and hasattr(self.artistTitle, "setValue"):
            self.artistTitle.setValue(artist)
        if self.artistalbumTitle and hasattr(self.artistalbumTitle, "setValue"):
            self.artistalbumTitle.setValue(artistalbum)

        if self.scrollText:
            if hasattr(self.trackTitle, "animate"):
                self.trackTitle.animate(True)
        else:
            if hasattr(self.trackTitle, "animate"):
                self.trackTitle.animate(False)

        for lbl in (self.artistTitle, self.albumTitle, self.artistalbumTitle):
            if lbl and hasattr(lbl, "animate"):
                lbl.animate(False)

    def _update_progress(self, data: Dict[str, Any]) -> None:
        if not self.player:
            return

        elapsed, duration = self._player_track_elapsed()

        if duration and float(duration) > 0:
            if self.progressSlider and hasattr(self.progressSlider, "setRange"):
                self.progressSlider.setRange(0, float(duration), float(elapsed or 0))
        else:
            if self.progressSlider and hasattr(self.progressSlider, "setRange"):
                self.progressSlider.setRange(0, 100, 0)

        # Swap progress bar / no-bar group as needed
        if duration and not self._showProgressBar:
            if self.window and self.progressNBGroup:
                if hasattr(self.window, "removeWidget"):
                    self.window.removeWidget(self.progressNBGroup)
                if hasattr(self.window, "addWidget"):
                    self.window.addWidget(self.progressBarGroup)
            self.progressGroup = self.progressBarGroup
            self._showProgressBar = True

        if not duration and self._showProgressBar:
            if self.window and self.progressBarGroup:
                if hasattr(self.window, "removeWidget"):
                    self.window.removeWidget(self.progressBarGroup)
                if hasattr(self.window, "addWidget"):
                    self.window.addWidget(self.progressNBGroup)
            self.progressGroup = self.progressNBGroup
            self._showProgressBar = False

        # Update seek-ability
        if self._showProgressBar and self.progressSlider:
            can_seek = False
            if self.player and hasattr(self.player, "is_track_seekable"):
                can_seek = self.player.is_track_seekable()
            elif self.player and hasattr(self.player, "isTrackSeekable"):
                can_seek = self.player.isTrackSeekable()

            if can_seek:
                if hasattr(self.progressSlider, "setEnabled"):
                    self.progressSlider.setEnabled(True)
                if hasattr(self.progressSlider, "setStyle"):
                    self.progressSlider.setStyle("npprogressB")
            else:
                if hasattr(self.progressSlider, "setEnabled"):
                    self.progressSlider.setEnabled(False)
                if hasattr(self.progressSlider, "setStyle"):
                    self.progressSlider.setStyle("npprogressB_disabled")

        self._update_position()

    def _update_position(self) -> None:
        if not self.player:
            return

        # Don't update while waiting to play
        if hasattr(self.player, "is_waiting_to_play") and self.player.is_waiting_to_play():
            return
        if hasattr(self.player, "isWaitingToPlay") and self.player.isWaitingToPlay():
            return

        elapsed, duration = self._player_track_elapsed()

        str_elapsed = ""
        str_remain = ""

        if elapsed is not None:
            e = float(elapsed)
            if duration and float(duration) > 0 and e > float(duration):
                str_elapsed = _seconds_to_string(float(duration))
            else:
                str_elapsed = _seconds_to_string(e)

        if elapsed is not None and float(elapsed) >= 0 and duration and float(duration) > 0:
            d = float(duration)
            e = float(elapsed)
            if e > d:
                str_remain = "-" + _seconds_to_string(0)
            else:
                str_remain = "-" + _seconds_to_string(d - e)

        if self.progressGroup and hasattr(self.progressGroup, "getWidget"):
            elapsed_widget = self.progressGroup.getWidget("elapsed")
            if elapsed_widget:
                el_len = len(str_elapsed)
                el_style = (
                    elapsed_widget.getStyle() if hasattr(elapsed_widget, "getStyle") else "elapsed"
                )
                if el_len > 5 and el_style != "elapsedSmall":
                    if hasattr(elapsed_widget, "setStyle"):
                        elapsed_widget.setStyle("elapsedSmall")
                elif el_len <= 5 and el_style != "elapsed":
                    if hasattr(elapsed_widget, "setStyle"):
                        elapsed_widget.setStyle("elapsed")

            if hasattr(self.progressGroup, "setWidgetValue"):
                self.progressGroup.setWidgetValue("elapsed", str_elapsed)

            if self._showProgressBar:
                remain_widget = self.progressGroup.getWidget("remain")
                if remain_widget:
                    r_len = len(str_remain)
                    r_style = (
                        remain_widget.getStyle() if hasattr(remain_widget, "getStyle") else "remain"
                    )
                    if r_len > 5 and r_style != "remainSmall":
                        if hasattr(remain_widget, "setStyle"):
                            remain_widget.setStyle("remainSmall")
                    elif r_len <= 5 and r_style != "remain":
                        if hasattr(remain_widget, "setStyle"):
                            remain_widget.setStyle("remain")

                if hasattr(self.progressGroup, "setWidgetValue"):
                    self.progressGroup.setWidgetValue("remain", str_remain)

                if self.progressSlider and hasattr(self.progressSlider, "setValue"):
                    if elapsed is not None:
                        self.progressSlider.setValue(float(elapsed))

    def _update_shuffle(self, mode: Any) -> None:
        log.debug("_updateShuffle: %s", mode)
        if self.player:
            ps = self._player_status()
            if (
                ps
                and ps.get("remoteMeta")
                and ps["remoteMeta"].get("buttons")
                and ps["remoteMeta"].get("shuffle")
            ):
                return

        token = f"mode{mode}"
        if token not in _SHUFFLE_MODES:
            log.error("Invalid shuffle mode: %s", token)
            return
        if self.controlsGroup and self.shuffleButton:
            if hasattr(self.shuffleButton, "setStyle"):
                self.shuffleButton.setStyle(_SHUFFLE_MODES[token])

    def _update_repeat(self, mode: Any) -> None:
        log.debug("_updateRepeat: %s", mode)
        if self.player:
            ps = self._player_status()
            if (
                ps
                and ps.get("remoteMeta")
                and ps["remoteMeta"].get("buttons")
                and ps["remoteMeta"].get("repeat")
            ):
                return

        token = f"mode{mode}"
        if token not in _REPEAT_MODES:
            log.error("Invalid repeat mode: %s", token)
            return
        if self.controlsGroup and self.repeatButton:
            if hasattr(self.repeatButton, "setStyle"):
                self.repeatButton.setStyle(_REPEAT_MODES[token])

    def _update_mode(self, mode: str) -> None:
        token = mode
        if token != "play" and self.player:
            power_on = False
            if hasattr(self.player, "is_power_on"):
                power_on = self.player.is_power_on()
            elif hasattr(self.player, "isPowerOn"):
                power_on = self.player.isPowerOn()
            if not power_on:
                token = "off"

        if self.titleGroup:
            self.change_title_text(self._title_text(token))

        if self.controlsGroup and hasattr(self.controlsGroup, "getWidget"):
            play_icon = self.controlsGroup.getWidget("play")
            if play_icon and hasattr(play_icon, "setStyle"):
                if token == "play":
                    play_icon.setStyle("pause")
                else:
                    play_icon.setStyle("play")

    # ------------------------------------------------------------------
    # Artwork
    # ------------------------------------------------------------------

    def _get_icon(self, item: Optional[Dict[str, Any]], icon: Any, remote: Any) -> None:
        if not self.player:
            return
        server = self._player_server()
        artwork_size = self.get_selected_style_param("artworkSize") or 200

        icon_id = None
        if item:
            icon_id = item.get("icon-id") or item.get("icon")

        if icon_id and server and hasattr(server, "fetchArtwork"):
            server.fetchArtwork(icon_id, icon, artwork_size)
        elif (
            item
            and item.get("params")
            and item["params"].get("track_id")
            and server
            and hasattr(server, "fetchArtwork")
        ):
            server.fetchArtwork(item["params"]["track_id"], icon, artwork_size, "png")
        elif icon and hasattr(icon, "setValue"):
            icon.setValue(None)

    # ------------------------------------------------------------------
    # Track info extraction
    # ------------------------------------------------------------------

    def _extract_track_info(self, track: Dict[str, Any]) -> Union[str, List[str]]:
        """Extract track / artist / album from a status item.

        Returns a list ``[track, artist, album]`` if the item has
        structured fields, or a plain text string otherwise.
        """
        if track.get("track"):
            return [
                track.get("track", ""),
                track.get("artist", ""),
                track.get("album", ""),
            ]
        return track.get("text", "\n\n\n")  # type: ignore[no-any-return]

    # ------------------------------------------------------------------
    # Window listeners
    # ------------------------------------------------------------------

    def _install_listeners(self, window: Any) -> None:
        Framework = _get_framework()
        log.info(
            "_install_listeners: window=%s, Framework=%s",
            type(window).__name__ if window else None,
            Framework,
        )

        # Window-active → update all
        if hasattr(window, "addListener"):
            window.addListener(
                EVENT_WINDOW_ACTIVE,
                lambda event=None: (self._update_all(), EVENT_UNUSED)[-1],  # type: ignore[func-returns-value]
            )

        def _show_playlist_action(*_a: Any, **_kw: Any) -> int:
            log.info("NowPlaying._show_playlist_action: called (go action)")
            if hasattr(window, "playSound"):
                window.playSound("WINDOWSHOW")
            playlist_size = self._player_playlist_size() or 0
            log.info(
                "NowPlaying._show_playlist_action: playlist_size=%s, player=%s",
                playlist_size,
                self.player,
            )
            mgr = _get_applet_manager()
            if playlist_size == 1:
                if mgr:
                    log.info("NowPlaying._show_playlist_action: calling showTrackOne")
                    mgr.call_service("showTrackOne")
            else:
                if mgr:
                    log.info("NowPlaying._show_playlist_action: calling showPlaylist")
                    mgr.call_service("showPlaylist")
            return EVENT_CONSUME

        # KEY_DOWN handler for LEFT only — react immediately on key
        # press (not on key release) so that "back" navigation feels
        # instant, matching the approach used by Menu for UP/DOWN.
        #
        # RIGHT is intentionally NOT handled here.  KEY_DOWN events
        # repeat when the key is held (pygame.key.set_repeat) and the
        # repeated "go" actions would be forwarded to the Playlist
        # menu that opens, causing it to activate the selected track
        # and restart playback.  RIGHT is handled on KEY_PRESS (once,
        # on key-up) below — exactly matching the original Lua code.
        if hasattr(window, "addListener"):

            def _key_down(event: Any) -> int:
                kc = event.get_keycode() if hasattr(event, "get_keycode") else None
                if kc == KEY_LEFT:
                    log.debug("NowPlaying._key_down: LEFT → back")
                    if Framework is not None and hasattr(Framework, "push_action"):
                        Framework.push_action("back")
                    return EVENT_CONSUME
                return EVENT_UNUSED

            window.addListener(EVENT_KEY_DOWN, _key_down)

        # KEY_PRESS handler for LEFT (consume to prevent double action)
        # and RIGHT (trigger "go" to show playlist).
        # This matches the original Lua: both LEFT and RIGHT are
        # handled on EVENT_KEY_PRESS.  LEFT is also handled on
        # KEY_DOWN above for instant response; here we just consume it.
        if hasattr(window, "addListener"):

            def _key_press(event: Any) -> int:
                kc = event.get_keycode() if hasattr(event, "get_keycode") else None
                if kc == KEY_LEFT:
                    # Already handled on KEY_DOWN — just consume.
                    return EVENT_CONSUME
                if kc == KEY_RIGHT:
                    log.debug("NowPlaying._key_press: RIGHT → go")
                    if Framework is not None and hasattr(Framework, "push_action"):
                        Framework.push_action("go")
                    return EVENT_CONSUME
                return EVENT_UNUSED

            window.addListener(EVENT_KEY_PRESS, _key_press)

        # Action listeners
        if hasattr(window, "addActionListener"):
            window.addActionListener("go", self, _show_playlist_action)
            log.info("NowPlaying._install_listeners: registered 'go' action listener")
            window.addActionListener(
                "go_home",
                self,
                lambda *_a, **_kw: self._go_home_action(),
            )
            window.addActionListener(
                "go_now_playing",
                self,
                lambda *_a, **_kw: self.toggle_np_screen_style(),
            )
            window.addActionListener(
                "go_now_playing_or_playlist",
                self,
                _show_playlist_action,
            )
            log.info(
                "NowPlaying._install_listeners: registered action listeners: go, go_home, go_now_playing, go_now_playing_or_playlist"
            )

        # Scroll listener for NP-style toggling
        if hasattr(window, "addListener"):

            def _scroll_handler(event: Any) -> int:
                scroll = event.getScroll() if hasattr(event, "getScroll") else 0
                direction = 1 if scroll > 0 else -1
                now = 0
                if Framework is not None and hasattr(Framework, "getTicks"):
                    now = Framework.getTicks()

                if self.lastScrollDirection != direction:
                    self.lastScrollDirection = direction
                    self.lastScrollTime = now
                    self.cumulativeScrollTicks = abs(scroll)
                    return EVENT_CONSUME

                if self.lastScrollTime is not None and self.lastScrollTime + _SCROLL_TIMEOUT < now:
                    self.cumulativeScrollTicks = 0

                self.cumulativeScrollTicks += abs(scroll)

                if self.cumulativeScrollTicks >= 8:
                    if Framework is not None and hasattr(Framework, "pushAction"):
                        Framework.pushAction("go_now_playing")
                    self.cumulativeScrollTicks = 0
                    self.lastScrollDirection = None
                    self.lastScrollTime = None
                else:
                    self.lastScrollTime = now
                    self.lastScrollDirection = direction

                return EVENT_CONSUME

            window.addListener(EVENT_SCROLL, _scroll_handler)

    def _go_home_action(self) -> int:
        mgr = _get_applet_manager()
        if mgr:
            mgr.call_service("goHome")
        return EVENT_CONSUME

    # ------------------------------------------------------------------
    # NP style toggling
    # ------------------------------------------------------------------

    def toggle_np_screen_style(self) -> None:
        """Cycle to the next enabled NP screen style."""
        enabled = [v for v in self.nowPlayingScreenStyles if v.get("enabled")]
        if not enabled:
            return

        for i, v in enumerate(enabled):
            if self.selectedStyle == v["style"]:
                if i == len(enabled) - 1:
                    self.selectedStyle = enabled[0]["style"]
                else:
                    self.selectedStyle = enabled[i + 1]["style"]
                break

        log.debug("NP style → %s", self.selectedStyle)

        if (
            self.window
            and hasattr(self.window, "getStyle")
            and self.window.getStyle() == self.selectedStyle
        ):
            return

        settings = self.get_settings() or {}
        settings["selectedStyle"] = self.selectedStyle
        self.store_settings()

        self.replace_np_window()

    # Lua alias
    toggleNPScreenStyle = toggle_np_screen_style

    # ------------------------------------------------------------------
    # Window replacement
    # ------------------------------------------------------------------

    def replace_np_window(self, no_trans: bool = False) -> None:
        """Rebuild and replace the NP window."""
        log.debug("REPLACING NP WINDOW")
        old_window = self.window
        self.window = self._create_ui()

        ps = self._player_status()
        if self.player and ps:
            self._update_buttons(ps)
            self._update_repeat(ps.get("playlist repeat", 0))
            self._update_shuffle(ps.get("playlist shuffle", 0))

        self._refresh_right_button()

        if old_window and hasattr(self.window, "replace"):
            from jive.ui.window import transition_fade_in, transition_none

            trans = transition_none if no_trans else transition_fade_in
            self.window.replace(old_window, trans)

    # Lua alias
    replaceNPWindow = replace_np_window

    # ------------------------------------------------------------------
    # Create UI
    # ------------------------------------------------------------------

    def _create_title_group(self, window: Any, button_style: str) -> Any:
        """Build the title-bar group with left button, title text, right button."""
        Group = _Group()
        Button = _Button()
        Label = _Label()
        Icon = _Icon()
        Framework = _get_framework()

        def _title_tap() -> int:
            if Framework and hasattr(Framework, "pushAction"):
                Framework.pushAction("go_current_track_info")
            return EVENT_CONSUME

        def _rbutton_tap() -> int:
            if Framework and hasattr(Framework, "pushAction"):
                Framework.pushAction("go")
            return EVENT_CONSUME

        def _rbutton_hold() -> int:
            if Framework and hasattr(Framework, "pushAction"):
                Framework.pushAction("title_right_hold")
            return EVENT_CONSUME

        def _rbutton_long() -> int:
            if Framework and hasattr(Framework, "pushAction"):
                Framework.pushAction("soft_reset")
            return EVENT_CONSUME

        lbutton = (
            window.createDefaultLeftButton() if hasattr(window, "createDefaultLeftButton") else None
        )

        title_group = Group(
            "title",
            {
                "lbutton": lbutton,
                "text": Button(Label("text", self.mainTitle), _title_tap),
                "rbutton": Button(
                    Group(button_style, {"icon": Icon("icon")}),
                    _rbutton_tap,
                    _rbutton_hold,
                    _rbutton_long,
                ),
            },
        )
        return title_group

    def _create_ui(self) -> Any:
        """Build the NP window from scratch and return it."""
        Window = _Window()
        Icon = _Icon()
        Button = _Button()
        Label = _Label()
        Group = _Group()
        Slider = _Slider()
        Timer = _Timer()
        Framework = _get_framework()

        self.windowStyle = self.selectedStyle or "nowplaying"
        window = Window(self.windowStyle)

        player_status = self._player_status()
        if player_status:
            if not player_status.get("duration"):
                self._showProgressBar = False
            else:
                self._showProgressBar = True

        self.mainTitle = self._title_text("play")
        self.titleGroup = self._create_title_group(window, "button_playlist")
        self.rbutton = "playlist"

        # Track labels
        self.trackTitle = Label("nptrack", "")
        self.XofY = Label("xofy", "")
        self.albumTitle = Label("npalbum", "")
        self.artistTitle = Label("npartist", "")
        self.artistalbumTitle = Label("npartistalbum", "")

        # Launch context menu callback
        def _launch_ctx() -> int:
            if Framework and hasattr(Framework, "pushAction"):
                Framework.pushAction("go_now_playing")
            return EVENT_CONSUME

        # Button() installs mouse listeners on the widget — the widget
        # (not the Button) goes into the Group.  In Lua, Button:__init()
        # returns the wrapped widget; in Python __init__ cannot return a
        # different object, so Button is a side-effect-only helper.
        Button(self.trackTitle, _launch_ctx)
        Button(self.albumTitle, _launch_ctx)
        Button(self.artistTitle, _launch_ctx)

        self.nptrackGroup = Group(
            "nptitle",
            {"nptrack": self.trackTitle, "xofy": self.XofY},
        )
        self.npartistGroup = Group("npartistgroup", {"npartist": self.artistTitle})
        self.npalbumGroup = Group("npalbumgroup", {"npalbum": self.albumTitle})

        # Scroll switch timer
        if self.scrollSwitchTimer is None and self.scrollText:
            self._add_scroll_switch_timer()

        # Text-stop callbacks for cycling scroll
        if hasattr(self.trackTitle, "__setattr__"):

            def _track_stop(label: Any) -> None:
                if (
                    self.scrollSwitchTimer
                    and hasattr(self.scrollSwitchTimer, "isRunning")
                    and not self.scrollSwitchTimer.isRunning()
                ):
                    if self.artistalbumTitle and hasattr(self.artistalbumTitle, "animate"):
                        self.artistalbumTitle.animate(True)
                    if self.artistTitle and hasattr(self.artistTitle, "animate"):
                        self.artistTitle.animate(True)
                    if hasattr(self.trackTitle, "animate"):
                        self.trackTitle.animate(False)

            self.trackTitle.textStopCallback = _track_stop

        jive_main = _get_jive_main()
        has_artist_album = False
        if jive_main and hasattr(jive_main, "get_skin_param"):
            has_artist_album = jive_main.get_skin_param("NOWPLAYING_TRACKINFO_LINES") == 2

        if has_artist_album and self.artistalbumTitle:

            def _aa_stop(label: Any) -> None:
                if self.artistalbumTitle and hasattr(self.artistalbumTitle, "animate"):
                    self.artistalbumTitle.animate(False)
                if hasattr(self.trackTitle, "animate"):
                    self.trackTitle.animate(False)
                if (
                    self.scrollSwitchTimer
                    and hasattr(self.scrollSwitchTimer, "isRunning")
                    and not self.scrollSwitchTimer.isRunning()
                    and not self.scrollTextOnce
                ):
                    if hasattr(self.scrollSwitchTimer, "restart"):
                        self.scrollSwitchTimer.restart()

            self.artistalbumTitle.textStopCallback = _aa_stop
        else:
            if self.artistTitle and hasattr(self.artistTitle, "__setattr__"):

                def _artist_stop(label: Any) -> None:
                    if (
                        self.scrollSwitchTimer
                        and hasattr(self.scrollSwitchTimer, "isRunning")
                        and not self.scrollSwitchTimer.isRunning()
                    ):
                        if hasattr(self.trackTitle, "animate"):
                            self.trackTitle.animate(False)
                        if self.artistTitle and hasattr(self.artistTitle, "animate"):
                            self.artistTitle.animate(False)
                        if self.albumTitle and hasattr(self.albumTitle, "animate"):
                            self.albumTitle.animate(True)

                self.artistTitle.textStopCallback = _artist_stop

            if self.albumTitle and hasattr(self.albumTitle, "__setattr__"):

                def _album_stop(label: Any) -> None:
                    if self.artistTitle and hasattr(self.artistTitle, "animate"):
                        self.artistTitle.animate(False)
                    if self.albumTitle and hasattr(self.albumTitle, "animate"):
                        self.albumTitle.animate(False)
                    if hasattr(self.trackTitle, "animate"):
                        self.trackTitle.animate(False)
                    if (
                        self.scrollSwitchTimer
                        and hasattr(self.scrollSwitchTimer, "isRunning")
                        and not self.scrollSwitchTimer.isRunning()
                        and not self.scrollTextOnce
                    ):
                        if hasattr(self.scrollSwitchTimer, "restart"):
                            self.scrollSwitchTimer.restart()

                self.albumTitle.textStopCallback = _album_stop

        # Goto (seek) timer
        if self.gotoTimer is None:

            def _goto_cb() -> None:
                if self.gotoElapsed is not None and self.player:
                    if hasattr(self.player, "goto_time"):
                        self.player.goto_time(self.gotoElapsed)
                    elif hasattr(self.player, "gototime"):
                        self.player.gototime(self.gotoElapsed)
                    self.gotoElapsed = None

            self.gotoTimer = Timer(400, _goto_cb, True)

        # Progress slider
        def _progress_cb(slider: Any, value: Any, done: bool = False) -> None:
            if self.player and hasattr(self.player, "set_waiting_to_play"):
                self.player.set_waiting_to_play(1)
            elif self.player and hasattr(self.player, "setWaitingToPlay"):
                self.player.setWaitingToPlay(1)
            self.gotoElapsed = value
            if self.gotoTimer and hasattr(self.gotoTimer, "restart"):
                self.gotoTimer.restart()

        self.progressSlider = Slider("npprogressB", 0, 100, 0, _progress_cb)

        self.progressBarGroup = Group(
            "npprogress",
            {
                "elapsed": Label("elapsed", ""),
                "slider": self.progressSlider,
                "remain": Label("remain", ""),
            },
        )
        self.progressNBGroup = Group("npprogressNB", {"elapsed": Label("elapsed", "")})

        # Position-update timer
        if hasattr(window, "addTimer"):
            window.addTimer(1000, lambda: self._update_position())

        self.progressGroup = (
            self.progressBarGroup if self._showProgressBar else self.progressNBGroup
        )

        # Artwork
        self.artwork = Icon("artwork")
        self.artworkGroup = Group("npartwork", {"artwork": self.artwork})
        Button(
            self.artworkGroup,
            lambda: (
                Framework.pushAction("go_now_playing")
                if Framework and hasattr(Framework, "pushAction")
                else None,
                EVENT_CONSUME,
            )[-1],
        )

        # Visualizer groups (spectrum / VU) — placeholder; real vis
        # requires the C extension modules.
        self.visuGroup = None
        if self.windowStyle in (
            "nowplaying_spectrum_text",
            "nowplaying_vuanalog_text",
        ):
            # Create a placeholder group; a real skin will inject the
            # actual SpectrumMeter / VUMeter widget.
            self.visuGroup = Group("npvisu", {"visu": Icon("visu_placeholder")})
            Button(
                self.visuGroup,
                lambda: (
                    Framework.pushAction("go_now_playing")
                    if Framework and hasattr(Framework, "pushAction")
                    else None,
                    EVENT_CONSUME,
                )[-1],
            )

        # Transport controls
        # Button() is a side-effect-only helper: it installs mouse
        # listeners on the widget.  The widget (Icon) goes into the
        # Group — not the Button (which is not a Widget subclass).
        play_icon = Icon("play")
        Button(
            play_icon,
            lambda: (
                Framework.pushAction("pause")
                if Framework and hasattr(Framework, "pushAction")
                else None,
                EVENT_CONSUME,
            )[-1],
            lambda: (
                Framework.pushAction("stop")
                if Framework and hasattr(Framework, "pushAction")
                else None,
                EVENT_CONSUME,
            )[-1],
        )
        if player_status and player_status.get("mode") == "play":
            play_icon.setStyle("pause")

        self.repeatButton = Icon("repeatMode")
        Button(
            self.repeatButton,
            lambda: (
                Framework.pushAction("repeat_toggle")
                if Framework and hasattr(Framework, "pushAction")
                else None,
                EVENT_CONSUME,
            )[-1],
        )
        self.shuffleButton = Icon("shuffleMode")
        Button(
            self.shuffleButton,
            lambda: (
                Framework.pushAction("shuffle_toggle")
                if Framework and hasattr(Framework, "pushAction")
                else None,
                EVENT_CONSUME,
            )[-1],
        )

        # Volume slider
        def _vol_drag(slider: Any, value: Any, done: bool = False) -> None:
            if self.fixedVolumeSet:
                return
            self.adjust_volume(int(value), True)
            self.volumeSliderDragInProgress = True

        def _vol_drag_end(slider: Any, value: Any, done: bool = False) -> None:
            if self.fixedVolumeSet:
                return
            self.volumeSliderDragInProgress = False
            self.adjust_volume(int(value), False)

        self.volSlider = Slider("npvolumeB", 0, 100, 0, _vol_drag, _vol_drag_end)
        if hasattr(self.volSlider, "__setattr__"):
            self.volSlider.jumpOnDown = True
            self.volSlider.pillDragOnly = True
            self.volSlider.dragThreshold = 5

        # Preset actions
        if hasattr(window, "addActionListener"):
            window.addActionListener(
                "add",
                self,
                lambda *_a, **_kw: (
                    Framework.pushAction("go_current_track_info")
                    if Framework and hasattr(Framework, "pushAction")
                    else None,
                    EVENT_CONSUME,
                )[-1],
            )
            for i in range(10):
                action_str = f"set_preset_{i}"
                preset_idx = i

                def _make_preset(idx: int) -> Callable[..., Any]:
                    def _cb(*_a: Any, **_kw: Any) -> int:
                        mgr = _get_applet_manager()
                        if mgr:
                            mgr.call_service("setPresetCurrentTrack", idx)
                        return EVENT_CONSUME

                    return _cb

                window.addActionListener(action_str, self, _make_preset(preset_idx))

        # Page-down / page-up → volume scroll
        Event = _Event()
        if hasattr(window, "addActionListener"):
            window.addActionListener(
                "page_down",
                self,
                lambda *_a, **_kw: (
                    Framework.dispatchEvent(self.volSlider, Event(EVENT_SCROLL, rel=1))
                    if Framework and hasattr(Framework, "dispatchEvent")
                    else None,
                    EVENT_CONSUME,
                )[-1],
            )
            window.addActionListener(
                "page_up",
                self,
                lambda *_a, **_kw: (
                    Framework.dispatchEvent(self.volSlider, Event(EVENT_SCROLL, rel=-1))
                    if Framework and hasattr(Framework, "dispatchEvent")
                    else None,
                    EVENT_CONSUME,
                )[-1],
            )

        # Volume update timer on the slider
        if hasattr(self.volSlider, "addTimer"):
            self.volSlider.addTimer(
                1000,
                lambda: self._update_volume() if not self.volumeSliderDragInProgress else None,
            )

        # Rew / Fwd buttons
        self.rewButton = Icon("rew")
        Button(
            self.rewButton,
            lambda: (
                Framework.pushAction("jump_rew")
                if Framework and hasattr(Framework, "pushAction")
                else None,
                EVENT_CONSUME,
            )[-1],
        )
        self.fwdButton = Icon("fwd")
        Button(
            self.fwdButton,
            lambda: (
                Framework.pushAction("jump_fwd")
                if Framework and hasattr(Framework, "pushAction")
                else None,
                EVENT_CONSUME,
            )[-1],
        )

        # Volume down / up buttons for devices with on-screen controls
        def _get_system_instance() -> Any:
            try:
                from jive.applet_manager import applet_manager as _mgr

                if _mgr is not None and hasattr(_mgr, "system") and _mgr.system is not None:
                    return _mgr.system
            except (ImportError, AttributeError):
                pass
            try:
                from jive.jive_main import jive_main as _jm

                if _jm is not None and hasattr(_jm, "_system"):
                    return _jm._system
            except (ImportError, AttributeError):
                pass
            return None

        def _vol_down_cb() -> int:
            if self.fixedVolumeSet:
                sys_inst = _get_system_instance()
                if (
                    sys_inst is not None
                    and hasattr(sys_inst, "has_ir_blaster_capability")
                    and sys_inst.has_ir_blaster_capability()
                ):
                    if self.player and hasattr(self.player, "volume"):
                        self.player.volume(99, True)
            if Framework and hasattr(Framework, "dispatchEvent"):
                Framework.dispatchEvent(self.volSlider, Event(EVENT_SCROLL, rel=-3))
            return EVENT_CONSUME

        def _vol_up_cb() -> int:
            if self.fixedVolumeSet:
                sys_inst = _get_system_instance()
                if (
                    sys_inst is not None
                    and hasattr(sys_inst, "has_ir_blaster_capability")
                    and sys_inst.has_ir_blaster_capability()
                ):
                    if self.player and hasattr(self.player, "volume"):
                        self.player.volume(101, True)
            if Framework and hasattr(Framework, "dispatchEvent"):
                Framework.dispatchEvent(self.volSlider, Event(EVENT_SCROLL, rel=3))
            return EVENT_CONSUME

        _voldown_icon = Icon("volDown")
        Button(_voldown_icon, _vol_down_cb)
        _volup_icon = Icon("volUp")
        Button(_volup_icon, _vol_up_cb)

        self.controlsGroup = Group(
            "npcontrols",
            {
                "div1": Icon("div1"),
                "div2": Icon("div2"),
                "div3": Icon("div3"),
                "div4": Icon("div4"),
                "div5": Icon("div5"),
                "div6": Icon("div6"),
                "div7": Icon("div7"),
                "rew": self.rewButton,
                "play": play_icon,
                "fwd": self.fwdButton,
                "repeatMode": self.repeatButton,
                "shuffleMode": self.shuffleButton,
                "volDown": _voldown_icon,
                "volUp": _volup_icon,
                "volSlider": self.volSlider,
            },
        )

        self.preartwork = Icon("artwork")

        # Add widgets to window
        for w in (
            self.nptrackGroup,
            self.npalbumGroup,
            self.npartistGroup,
            self.artistalbumTitle,
            self.artworkGroup,
        ):
            if w and hasattr(window, "addWidget"):
                window.addWidget(w)

        if self.visuGroup and hasattr(window, "addWidget"):
            window.addWidget(self.visuGroup)

        self._set_volume_slider_style()

        if hasattr(window, "addWidget"):
            window.addWidget(self.controlsGroup)
            window.addWidget(self.progressGroup)

        self.suppressTitlebar = self.get_selected_style_param("suppressTitlebar") or False
        if not self.suppressTitlebar and hasattr(window, "addWidget"):
            window.addWidget(self.titleGroup)

        if hasattr(window, "focusWidget"):
            window.focusWidget(self.nptrackGroup)

        # Register as screensaver window if needed
        if self.isScreensaver:
            mgr = _get_applet_manager()
            if mgr:
                ss_manager = (
                    mgr.get_applet_instance("ScreenSavers")
                    if hasattr(mgr, "get_applet_instance")
                    else None
                )
                if ss_manager and hasattr(ss_manager, "screensaverWindow"):
                    ss_manager.screensaverWindow(window, None, None, None, "NowPlaying")

        self._install_listeners(window)
        return window

    # ------------------------------------------------------------------
    # Service methods
    # ------------------------------------------------------------------

    def goNowPlaying(self, transition: Any = None, direct: bool = False) -> Optional[bool]:
        """Navigate to the NowPlaying screen.

        Registered as the ``goNowPlaying`` service.
        """
        self.transition = transition
        if not self.player:
            mgr = _get_applet_manager()
            if mgr:
                self.player = mgr.call_service("getCurrentPlayer")

        if self.player:
            self.isScreensaver = False
            has_tracks = self._playlist_has_tracks()
            line_in = False
            mgr = _get_applet_manager()
            if mgr:
                line_in = mgr.call_service("isLineInActive") or False

            if has_tracks or line_in:
                self.showNowPlaying(transition, direct)
            else:
                self._delay_now_playing(direct)
                return None
        else:
            return False
        return None

    def _delay_now_playing(self, direct: bool = False) -> None:
        Timer = _Timer()

        def _cb() -> None:
            if self._playlist_has_tracks():
                self.showNowPlaying(self.transition, direct)
            else:
                mgr = _get_applet_manager()
                if mgr:
                    browser = (
                        mgr.get_applet_instance("SlimBrowser")
                        if hasattr(mgr, "get_applet_instance")
                        else None
                    )
                    if browser and hasattr(browser, "show_playlist"):
                        browser.show_playlist()
                    elif browser and hasattr(browser, "showPlaylist"):
                        browser.showPlaylist()

        timer = Timer(1000, _cb, True)
        if hasattr(timer, "start"):
            timer.start()

    def hideNowPlaying(self) -> None:
        """Hide the NowPlaying window.

        Registered as the ``hideNowPlaying`` service.
        """
        log.warn("hideNowPlaying")
        if self.window and hasattr(self.window, "hide"):
            self.window.hide()

    def openScreensaver(self, force: Any = None, method_param: Any = None) -> bool:
        """Open NP as a screensaver (called by ScreenSavers applet)."""
        mgr = _get_applet_manager()
        if mgr:
            mgr.call_service("deactivateScreensaver")
            mgr.call_service("restartScreenSaverTimer")
            mgr.call_service("goNowPlaying")
        return False

    def showNowPlaying(self, transition: Any = None, direct: bool = False) -> None:
        """Build (if needed) and display the NP window."""
        self.nowPlayingScreenStyles = self.getNPStyles()

        if not self.selectedStyle:
            settings = self.get_settings() or {}
            self.selectedStyle = settings.get("selectedStyle", "nowplaying")

        np_window = self.window

        mgr = _get_applet_manager()
        line_in_active = False
        if mgr:
            line_in_active = mgr.call_service("isLineInActive") or False

        if not direct and line_in_active:
            if mgr:
                np_window = mgr.call_service("getLineInNpWindow")

        Framework = _get_framework()
        Window = _Window()

        if np_window is not None and Framework and hasattr(Framework, "isWindowInStack"):
            if Framework.isWindowInStack(np_window):
                log.debug("NP already on stack")
                if hasattr(np_window, "moveToTop"):
                    np_window.moveToTop()
                if mgr:
                    mgr.call_service("restartScreenSaverTimer")
                    if mgr.call_service("isScreensaverActive"):
                        mgr.call_service("deactivateScreensaver")
                    else:
                        return
                return

        if not direct and line_in_active and np_window:
            if hasattr(np_window, "show"):
                np_window.show()
            return

        if not self.player:
            mgr = _get_applet_manager()
            if mgr:
                self.player = mgr.call_service("getCurrentPlayer")

        player_status = self._player_status()

        if not self._playlist_has_tracks():
            self._delay_now_playing()
            return

        if player_status and player_status.get("item_loop"):
            this_track = player_status["item_loop"][0]
        else:
            this_track = None

        if transition is None and hasattr(Window, "transitionFadeIn"):
            transition = Window.transitionFadeIn

        if self.window is None:
            self.window = self._create_ui()

        if mgr:
            self.player = mgr.call_service("getCurrentPlayer")

        if not self.player:
            return

        if this_track:
            track_info = self._extract_track_info(this_track)
            if (
                player_status.get("remote") == 1  # type: ignore[union-attr]
                and isinstance(player_status.get("current_title"), str)  # type: ignore[union-attr]
                and isinstance(track_info, str)
            ):
                track_info = track_info + "\n" + player_status["current_title"]  # type: ignore[index]

            self._get_icon(this_track, self.artwork, player_status.get("remote"))  # type: ignore[union-attr]
            self._update_mode(player_status.get("mode", "stop"))  # type: ignore[union-attr]
            self._update_track(track_info)
            self._update_progress(player_status)  # type: ignore[arg-type]
            self._update_playlist()

            if len(player_status.get("item_loop", [])) > 1:  # type: ignore[union-attr]
                Icon = _Icon()
                self._get_icon(
                    player_status["item_loop"][1],  # type: ignore[index]
                    Icon("artwork"),
                    player_status.get("remote"),  # type: ignore[union-attr]
                )
        else:
            self._get_icon(None, self.artwork, None)
            self._update_track("\n\n\n")
            self._update_mode(player_status.get("mode", "stop") if player_status else "stop")
            self._update_playlist()

        self._update_volume()
        if player_status:
            self._update_repeat(player_status.get("playlist repeat", 0))
            self._update_shuffle(player_status.get("playlist shuffle", 0))

        vol = self._player_volume()
        self.volumeOld = int(vol) if vol is not None else 0

        if self.window and hasattr(self.window, "show"):
            self.window.show(transition)

        self._update_all()

    # ------------------------------------------------------------------
    # Scroll timer helper
    # ------------------------------------------------------------------

    def _add_scroll_switch_timer(self) -> None:
        if self.scrollSwitchTimer is None:
            Timer = _Timer()
            log.debug("Adding scrollSwitchTimer")

            def _cb() -> None:
                if self.trackTitle and hasattr(self.trackTitle, "animate"):
                    self.trackTitle.animate(True)
                for lbl in (
                    self.artistalbumTitle,
                    self.artistTitle,
                    self.albumTitle,
                ):
                    if lbl and hasattr(lbl, "animate"):
                        lbl.animate(False)

            self.scrollSwitchTimer = Timer(3000, _cb, True)

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def free_and_clear(self) -> None:
        """Disconnect from player and clean up."""
        self.player = False
        jive_main = _get_jive_main()
        if jive_main is not None:
            jive_main.remove_item_by_id("appletNowPlaying")
        self.free()

    # Lua alias
    freeAndClear = free_and_clear

    def free(self) -> bool:
        """Free the NP window and allow re-creation on next entry."""
        log.debug("free(): player=%s", self.player)
        if self.window and hasattr(self.window, "hide"):
            self.window.hide()
        # Returning True allows the applet to actually be freed;
        # returning False keeps it resident.  NowPlaying is normally
        # kept resident.
        return True

    # ------------------------------------------------------------------
    # Private player accessors (isolate duck-typing)
    # ------------------------------------------------------------------

    def _player_id(self) -> Optional[str]:
        if not self.player:
            return None
        if hasattr(self.player, "get_id"):
            return self.player.get_id()  # type: ignore[no-any-return]
        if hasattr(self.player, "getId"):
            return self.player.getId()  # type: ignore[no-any-return]
        return None

    def _player_play_mode(self) -> str:
        if not self.player:
            return "stop"
        if hasattr(self.player, "get_play_mode"):
            return self.player.get_play_mode() or "stop"
        if hasattr(self.player, "getPlayMode"):
            return self.player.getPlayMode() or "stop"
        return "stop"

    def _player_status(self) -> Optional[Dict[str, Any]]:
        if not self.player:
            return None
        if hasattr(self.player, "get_player_status"):
            return self.player.get_player_status()  # type: ignore[no-any-return]
        if hasattr(self.player, "getPlayerStatus"):
            return self.player.getPlayerStatus()  # type: ignore[no-any-return]
        return None

    def _player_playlist_size(self) -> Optional[int]:
        if not self.player:
            return None
        if hasattr(self.player, "get_playlist_size"):
            return self.player.get_playlist_size()  # type: ignore[no-any-return]
        if hasattr(self.player, "getPlaylistSize"):
            return self.player.getPlaylistSize()  # type: ignore[no-any-return]
        return None

    def _player_playlist_current_index(self) -> Optional[int]:
        if not self.player:
            return None
        if hasattr(self.player, "get_playlist_current_index"):
            return self.player.get_playlist_current_index()  # type: ignore[no-any-return]
        if hasattr(self.player, "getPlaylistCurrentIndex"):
            return self.player.getPlaylistCurrentIndex()  # type: ignore[no-any-return]
        return None

    def _player_track_elapsed(self) -> Tuple[Optional[float], Optional[float]]:
        if not self.player:
            return (None, None)
        if hasattr(self.player, "get_track_elapsed"):
            return self.player.get_track_elapsed()  # type: ignore[no-any-return]
        if hasattr(self.player, "getTrackElapsed"):
            return self.player.getTrackElapsed()  # type: ignore[no-any-return]
        return (None, None)

    def _player_volume(self) -> Optional[int]:
        if not self.player:
            return None
        if hasattr(self.player, "get_volume"):
            return self.player.get_volume()  # type: ignore[no-any-return]
        if hasattr(self.player, "getVolume"):
            return self.player.getVolume()  # type: ignore[no-any-return]
        return None

    def _player_server(self) -> Any:
        if not self.player:
            return None
        if hasattr(self.player, "get_slim_server"):
            return self.player.get_slim_server()
        if hasattr(self.player, "getSlimServer"):
            return self.player.getSlimServer()
        return None

    def _player_is_local(self) -> bool:
        if not self.player:
            return False
        if hasattr(self.player, "is_local"):
            return self.player.is_local()  # type: ignore[no-any-return]
        if hasattr(self.player, "isLocal"):
            return self.player.isLocal()  # type: ignore[no-any-return]
        return False

    def _player_is_remote(self) -> bool:
        if not self.player:
            return False
        if hasattr(self.player, "is_remote"):
            return self.player.is_remote()  # type: ignore[no-any-return]
        if hasattr(self.player, "isRemote"):
            return self.player.isRemote()  # type: ignore[no-any-return]
        return False

    def _is_this_player(self, player: Any) -> bool:
        """Check whether *player* is the same as ``self.player``."""
        if not self.player or not self._player_id():
            mgr = _get_applet_manager()
            if mgr:
                self.player = mgr.call_service("getCurrentPlayer")

        my_id = self._player_id()
        other_id = None
        if hasattr(player, "get_id"):
            other_id = player.get_id()
        elif hasattr(player, "getId"):
            other_id = player.getId()

        if other_id != my_id:
            log.debug(
                "notification not for this player: got=%s, mine=%s",
                other_id,
                my_id,
            )
            return False
        return True

    def _playlist_has_tracks(self) -> bool:
        if not self.player:
            return False
        size = self._player_playlist_size()
        return size is not None and size > 0

    @staticmethod
    def _get_jnt() -> Any:
        """Obtain the network-thread coordinator singleton."""
        try:
            from jive.jive_main import jive_main as _jm

            if _jm is not None:
                return getattr(_jm, "jnt", None)
        except ImportError as exc:
            log.debug("_get_jnt: jive_main not available: %s", exc)
        return None
