"""
jive.applets.ScreenSavers.ScreenSaversApplet — Screensaver manager applet.

Ported from ``share/jive/applets/ScreenSavers/ScreenSaversApplet.lua``
(~880 LOC Lua) in the original jivelite project.

This applet hooks itself into Jive to provide a screensaver service,
complete with settings.  It manages:

* **Screensaver registration** — other applets register their
  screensavers via the ``addScreenSaver`` / ``removeScreenSaver``
  services.
* **Idle timer** — after a configurable timeout of no user input the
  appropriate screensaver is activated.
* **Mode-based selection** — different screensavers can be configured
  for "when playing", "when stopped", and "when off" modes.
* **Power-on overlay** — on touch devices a transparent overlay
  intercepts input during soft-power-off and shows a power-on window.
* **Settings UI** — radio-button menus for choosing screensavers per
  mode and configuring the idle timeout.

Service methods (called via ``AppletManager.call_service()``):

* ``addScreenSaver(display_name, applet, method, ...)``
* ``removeScreenSaver(applet_name, method, ...)``
* ``restartScreenSaverTimer()``
* ``isScreensaverActive()``
* ``deactivateScreensaver()``
* ``activateScreensaver(is_server_request)``

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

import os
import time
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

from jive.applet import Applet
from jive.ui.constants import (
    ACTION,
    EVENT_CONSUME,
    EVENT_IR_ALL,
    EVENT_KEY_ALL,
    EVENT_KEY_HOLD,
    EVENT_KEY_PRESS,
    EVENT_MOTION,
    EVENT_MOUSE_ALL,
    EVENT_MOUSE_DRAG,
    EVENT_MOUSE_HOLD,
    EVENT_MOUSE_PRESS,
    EVENT_SCROLL,
    EVENT_UNUSED,
    EVENT_WINDOW_INACTIVE,
    EVENT_WINDOW_POP,
    EVENT_WINDOW_PUSH,
)
from jive.utils.log import logger

__all__ = ["ScreenSaversApplet"]

log = logger("applet.ScreenSavers")


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
        log.debug("_get_jive_main: first import failed: %s", exc)
    try:
        import jive.jive_main as _mod

        return getattr(_mod, "jive_main", None)
    except ImportError:
        return None


def _get_framework() -> Any:
    try:
        from jive.ui.framework import framework

        return framework
    except (ImportError, AttributeError):
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


def _Timer() -> Any:
    if "Timer" not in _ui_cache:
        _ui_cache["Timer"] = _import_ui_class("timer", "Timer")
    return _ui_cache["Timer"]


def _SimpleMenu() -> Any:
    if "SimpleMenu" not in _ui_cache:
        _ui_cache["SimpleMenu"] = _import_ui_class("simplemenu", "SimpleMenu")
    return _ui_cache["SimpleMenu"]


def _RadioGroup() -> Any:
    if "RadioGroup" not in _ui_cache:
        _ui_cache["RadioGroup"] = _import_ui_class("radio", "RadioGroup")
    return _ui_cache["RadioGroup"]


def _RadioButton() -> Any:
    if "RadioButton" not in _ui_cache:
        _ui_cache["RadioButton"] = _import_ui_class("radio", "RadioButton")
    return _ui_cache["RadioButton"]


def _Label() -> Any:
    if "Label" not in _ui_cache:
        _ui_cache["Label"] = _import_ui_class("label", "Label")
    return _ui_cache["Label"]


def _Textarea() -> Any:
    if "Textarea" not in _ui_cache:
        _ui_cache["Textarea"] = _import_ui_class("textarea", "Textarea")
    return _ui_cache["Textarea"]


def _System() -> Any:
    """Return the System *instance* (not the class).

    In the Lua original, ``System`` is a module-level singleton.
    In Python, the single ``System`` instance is owned by
    ``AppletManager`` (which receives it from ``JiveMain``).
    """
    if "System" not in _ui_cache:
        try:
            from jive.applet_manager import applet_manager as _mgr

            if _mgr is not None and hasattr(_mgr, "system") and _mgr.system is not None:
                _ui_cache["System"] = _mgr.system
            else:
                # Fallback: try JiveMain directly
                from jive.jive_main import jive_main as _jm

                if _jm is not None and hasattr(_jm, "_system"):
                    _ui_cache["System"] = _jm._system
                else:
                    _ui_cache["System"] = None
        except (ImportError, AttributeError):
            _ui_cache["System"] = None
    return _ui_cache["System"]


def _Player() -> Any:
    if "Player" not in _ui_cache:
        try:
            from jive.slim.player import Player

            _ui_cache["Player"] = Player
        except ImportError:
            _ui_cache["Player"] = None
    return _ui_cache["Player"]


# ---------------------------------------------------------------------------
# Global screensaver-allowed actions (always pass through)
# ---------------------------------------------------------------------------

_GLOBAL_SS_ALLOWED_ACTIONS: Dict[str, int] = {
    "pause": 1,
    "shutdown": 1,
}

# Power-off allowed actions (pass through during soft-power-off overlay)
_POWER_ALLOWED_ACTIONS: Dict[str, Any] = {
    "play_preset_0": 1,
    "play_preset_1": 1,
    "play_preset_2": 1,
    "play_preset_3": 1,
    "play_preset_4": 1,
    "play_preset_5": 1,
    "play_preset_6": 1,
    "play_preset_7": 1,
    "play_preset_8": 1,
    "play_preset_9": 1,
    "play": "pause",
    "shutdown": 1,
}


# ---------------------------------------------------------------------------
# ScreenSaversApplet
# ---------------------------------------------------------------------------


class ScreenSaversApplet(Applet):
    """Screensaver manager applet.

    Manages screensaver registration, idle-timer activation,
    mode-based selection, and settings UI.
    """

    def __init__(self) -> None:
        super().__init__()

        # Registry of all screensavers keyed by "AppletName:method[:additionalKey]"
        self.screensavers: Dict[str, Dict[str, Any]] = {}
        # Settings-linked screensavers (settingsName → screensaver entry)
        self.screensaverSettings: Dict[str, Dict[str, Any]] = {}

        # Active screensaver windows
        self.active: List[Any] = []
        # Name of the currently active screensaver
        self.current: Optional[str] = None
        # Key of the current screensaver being used
        self.currentSS: Optional[str] = None
        # Demo screensaver key (set when previewing)
        self.demoScreensaver: Optional[str] = None
        # Whether any screensaver is currently active
        self.isScreenSaverActive: bool = False

        # Idle timer
        self.timer: Optional[Any] = None
        self.timeout: int = 30000

        # Power-on overlay window
        self.powerOnWindow: Optional[Any] = None

        # Per-screensaver input passthrough flags
        self.scrollAllowed: Optional[bool] = None
        self.ssAllowedActions: Optional[List[str]] = None
        self.mouseAllowed: Optional[bool] = None

        # Default settings from Meta (cached at init time)
        self.defaultSettings: Optional[Dict[str, Any]] = None

        # Framework listener handles (for cleanup)
        self._fw_listener_restart: Optional[Any] = None
        self._fw_listener_close_primary: Optional[Any] = None
        self._fw_listener_close_fallback: Optional[Any] = None

    # ==================================================================
    # Lifecycle
    # ==================================================================

    def init(self) -> None:
        """Initialize the screensaver manager.

        Called by the AppletManager after settings and strings are
        available.
        """
        super().init()

        # Register "None" screensaver (do nothing)
        self.addScreenSaver(
            display_name=self.string("SCREENSAVER_NONE"),
            applet=False,
            method=False,
            settings_name=None,
            settings=None,
            weight=100,
            close_method=None,
            method_param=None,
            additional_key=None,
            mode_exclusions=["whenOff"],
        )

        # Load timeout from settings
        settings = self.get_settings()
        if settings:
            self.timeout = settings.get("timeout", 30000)

        self.defaultSettings = self.get_default_settings()

        # Create idle timer — wait 60s after startup before first activation
        Timer = _Timer()
        self.timer = Timer(60000, lambda: self._activate(), once=True)
        self.timer.start()

        # --- Framework listener: restart timer on user input ---
        fw = _get_framework()
        if fw is not None:
            input_mask = (
                int(ACTION)
                | int(EVENT_SCROLL)
                | int(EVENT_MOUSE_ALL)
                | int(EVENT_MOTION)
                | int(EVENT_IR_ALL)
                | int(EVENT_KEY_ALL)
            )

            def _restart_timer_listener(event: Any) -> int:
                # Restart timer if it is running
                if self.timer is not None:
                    self.timer.set_interval(self.timeout)
                return int(EVENT_UNUSED)

            self._fw_listener_restart = fw.add_listener(
                input_mask, _restart_timer_listener, priority=0
            )

            # --- Primary screensaver close listener (priority -100) ---
            close_mask = (
                int(ACTION)
                | int(EVENT_KEY_PRESS)
                | int(EVENT_KEY_HOLD)
                | int(EVENT_SCROLL)
                | int(EVENT_MOUSE_PRESS)
                | int(EVENT_MOUSE_HOLD)
                | int(EVENT_MOUSE_DRAG)
            )

            def _close_primary_listener(event: Any) -> int:
                # Screensaver is not active
                if len(self.active) == 0:
                    return int(EVENT_UNUSED)

                etype = event.get_type() if hasattr(event, "get_type") else 0

                # If it's a key event that will come back as an action,
                # let it pass through
                if etype & int(EVENT_KEY_ALL):
                    return int(EVENT_UNUSED)

                if etype == int(ACTION):
                    action = (
                        event.get_action() if hasattr(event, "get_action") else None
                    )

                    if action and _GLOBAL_SS_ALLOWED_ACTIONS.get(action):
                        log.debug("Global action allowed to pass through: %s", action)
                        return int(EVENT_UNUSED)

                    if self.ssAllowedActions is not None:
                        if (
                            len(self.ssAllowedActions) == 0
                            or action in self.ssAllowedActions
                        ):
                            log.debug(
                                "'Per window' action allowed to pass through: %s",
                                action,
                            )
                            return int(EVENT_UNUSED)

                if etype == int(EVENT_SCROLL):
                    if self.scrollAllowed:
                        log.debug("'Per window' scroll event allowed to pass through")
                        return int(EVENT_UNUSED)

                if etype in (
                    int(EVENT_MOUSE_PRESS),
                    int(EVENT_MOUSE_HOLD),
                    int(EVENT_MOUSE_DRAG),
                ):
                    if self.mouseAllowed:
                        log.debug("'Per window' mouse event allowed to pass through")
                        return int(EVENT_UNUSED)

                log.debug("Closing screensaver (primary)")

                self.deactivateScreensaver()

                # Handle specific actions after closing
                if etype == int(ACTION):
                    action = (
                        event.get_action() if hasattr(event, "get_action") else None
                    )
                    if action in ("back", "go"):
                        return int(EVENT_CONSUME)

                    if action == "home":
                        mgr = _get_applet_manager()
                        if mgr:
                            mgr.call_service("goHome")
                        return int(EVENT_CONSUME)

                    if action in ("power", "power_on"):
                        fw_inner = _get_framework()
                        if fw_inner:
                            fw_inner.play_sound("SELECT")
                        return int(EVENT_CONSUME)

                return int(EVENT_UNUSED)

            self._fw_listener_close_primary = fw.add_listener(
                close_mask, _close_primary_listener, priority=-100
            )

            # --- Fallback screensaver close listener (priority 100) ---
            fallback_mask = (
                int(ACTION)
                | int(EVENT_SCROLL)
                | int(EVENT_MOUSE_PRESS)
                | int(EVENT_MOUSE_HOLD)
                | int(EVENT_MOUSE_DRAG)
                | int(EVENT_KEY_ALL)
            )

            def _close_fallback_listener(event: Any) -> int:
                self.isScreenSaverActive = False

                if len(self.active) == 0:
                    return int(EVENT_UNUSED)

                log.debug("Closing screensaver (fallback)")

                self.deactivateScreensaver()

                etype = event.get_type() if hasattr(event, "get_type") else 0
                if etype == int(ACTION):
                    action = (
                        event.get_action() if hasattr(event, "get_action") else None
                    )
                    if action == "home":
                        mgr = _get_applet_manager()
                        if mgr:
                            mgr.call_service("goHome")
                        return int(EVENT_CONSUME)

                return int(EVENT_CONSUME)

            self._fw_listener_close_fallback = fw.add_listener(
                fallback_mask, _close_fallback_listener, priority=100
            )

        # Subscribe to notifications
        jnt = self._get_jnt()
        if jnt is not None:
            jnt.subscribe(self)

    def free(self) -> bool:
        """ScreenSavers cannot be freed — always returns ``False``."""
        return False

    # ==================================================================
    # Notification handlers
    # ==================================================================

    def notify_playerModeChange(self, player: Any, mode: Any) -> None:
        """Switch screensavers on a player mode change."""
        if not self.is_soft_power_on():
            return

        old_active = self.active

        if len(old_active) == 0:
            # Screensaver is not active
            return

        self.active = []
        self._activate(None)

        # Close active screensaver(s)
        for window in old_active:
            self._deactivate(window, self.demoScreensaver)

    # Lua alias
    notify_playerModeChange.__name__ = "notify_playerModeChange"

    # ==================================================================
    # Service methods
    # ==================================================================

    def addScreenSaver(
        self,
        display_name: Any = None,
        applet: Any = False,
        method: Any = False,
        settings_name: Optional[str] = None,
        settings: Optional[str] = None,
        weight: Optional[int] = None,
        close_method: Optional[str] = None,
        method_param: Any = None,
        additional_key: Optional[str] = None,
        mode_exclusions: Optional[List[str]] = None,
    ) -> None:
        """Register a screensaver.

        Parameters
        ----------
        display_name:
            Human-readable name for the screensaver in settings menus.
        applet:
            Applet name string, or ``False`` for "none".
        method:
            Method name to call on the applet to activate, or ``False``.
        settings_name:
            If not ``None``, register a settings sub-menu for this
            screensaver.
        settings:
            Method name on the applet for the settings UI.
        weight:
            Sort weight in the settings menu.
        close_method:
            Method name to call on the applet when the screensaver
            is deactivated.
        method_param:
            Additional parameter to pass to the activation method.
        additional_key:
            Extra key component for disambiguation.
        mode_exclusions:
            List of modes (``"whenPlaying"``, ``"whenStopped"``,
            ``"whenOff"``) from which this screensaver should be
            excluded in the settings menu.
        """
        key = self.get_key(applet, method, additional_key)
        self.screensavers[key] = {
            "applet": applet,
            "method": method,
            "displayName": display_name,
            "settings": settings,
            "weight": weight,
            "closeMethod": close_method,
            "methodParam": method_param,
            "modeExclusions": mode_exclusions,
        }

        if settings_name:
            self.screensaverSettings[settings_name] = self.screensavers[key]

    def removeScreenSaver(
        self,
        applet_name: Any = None,
        method: Any = None,
        settings_name: Optional[str] = None,
        additional_key: Optional[str] = None,
    ) -> None:
        """Unregister a screensaver."""
        key = self.get_key(applet_name, method, additional_key)

        if settings_name and settings_name in self.screensaverSettings:
            del self.screensaverSettings[settings_name]

        if key in self.screensavers:
            del self.screensavers[key]

    def restartScreenSaverTimer(self) -> None:
        """Restart the idle timer."""
        if self.timer is not None:
            self.timer.restart()

    def isScreensaverActive(self) -> bool:
        """Return whether a screensaver is currently active."""
        return self.isScreenSaverActive

    def deactivateScreensaver(self) -> None:
        """Close all active screensaver windows."""
        old_active = self.active

        self.isScreenSaverActive = False
        if len(old_active) == 0:
            return

        self.active = []

        for window in old_active:
            self._deactivate(window, self.demoScreensaver)

        if not self.is_soft_power_on():
            jive_main = _get_jive_main()
            if jive_main is not None:
                jive_main.set_soft_power_state("on")

    def activateScreensaver(self, is_server_request: bool = False) -> None:
        """Activate the screensaver for the current mode.

        This is the service method callable via
        ``applet_manager.call_service("activateScreensaver")``.
        """
        self._activate(None, force=False, is_server_request=is_server_request)

    # ==================================================================
    # Screensaver window registration
    # ==================================================================

    def screensaverWindow(
        self,
        window: Any,
        scroll_allowed: Optional[bool] = None,
        ss_allowed_actions: Optional[List[str]] = None,
        mouse_allowed: Optional[bool] = None,
        ss_name: Optional[str] = None,
    ) -> None:
        """Register *window* as a screensaver window.

        This sets up the appropriate listeners on the window so that
        the screensaver manager can track when the window is pushed
        to or popped from the window stack.

        Parameters
        ----------
        window:
            The screensaver window to register.
        scroll_allowed:
            If ``True``, scroll events pass through to the window
            without closing the screensaver.
        ss_allowed_actions:
            List of action names that pass through.  ``None`` means
            no actions pass through; an empty list means *all* actions
            pass through.
        mouse_allowed:
            If ``True``, mouse events pass through to the window.
        ss_name:
            A name for this screensaver instance (stored in
            ``self.current``).
        """
        if ss_name is None:
            ss_name = "unnamedScreenSaver"

        if hasattr(window, "setIsScreensaver"):
            window.setIsScreensaver(True)
        elif hasattr(window, "is_screensaver"):
            window.is_screensaver = True

        self._set_ss_allowed_actions(scroll_allowed, ss_allowed_actions, mouse_allowed)

        applet_self = self  # capture for closures

        # Track when the window is pushed to the stack
        def _on_push(event: Any) -> int:
            log.debug("screensaver opened, active count: %d", len(applet_self.active))
            applet_self.active.append(window)
            applet_self.current = ss_name
            if applet_self.timer is not None:
                applet_self.timer.stop()
            return int(EVENT_UNUSED)

        window.add_listener(int(EVENT_WINDOW_PUSH), _on_push)

        # Track when the window is popped from the stack
        def _on_pop(event: Any) -> int:
            if window in applet_self.active:
                applet_self.active.remove(window)
            applet_self.current = None
            if len(applet_self.active) == 0:
                log.debug("screensaver inactive")
                if applet_self.timer is not None:
                    applet_self.timer.start()
            log.debug("screensaver closed, active count: %d", len(applet_self.active))
            return int(EVENT_UNUSED)

        window.add_listener(int(EVENT_WINDOW_POP), _on_pop)

        # When soft-power is off, restrict input and show power-on overlay
        if not self.is_soft_power_on():
            self._set_ss_allowed_actions(True, [], True)

            window.ignore_all_input_except(
                ["power", "power_on", "power_off"],
                lambda action_event: self._power_action_handler(action_event),
            )

            window.add_listener(
                int(EVENT_MOUSE_PRESS) | int(EVENT_MOUSE_HOLD) | int(EVENT_MOUSE_DRAG),
                lambda event: self._on_ss_mouse_when_off(),
            )

            window.add_listener(
                int(EVENT_SCROLL),
                lambda event: self._on_ss_scroll_when_off(),
            )

        # Override the default window "bump" handling to allow actions
        # to fall through to framework listeners
        log.debug(
            "Overriding the default window action 'bump' handling "
            "to allow action to fall through to framework listeners"
        )
        if hasattr(window, "remove_default_action_listeners"):
            window.remove_default_action_listeners()
        elif hasattr(window, "removeDefaultActionListeners"):
            window.removeDefaultActionListeners()

    # ==================================================================
    # Settings UI
    # ==================================================================

    def open_settings(self, menu_item: Any = None) -> Any:
        """Open the screensaver settings window.

        Shows sub-menus for choosing screensavers per mode and
        configuring the idle timeout.
        """
        SimpleMenu = _SimpleMenu()
        Window = _Window()

        items = [
            {
                "text": self.string("SCREENSAVER_WHEN_PLAYING"),
                "weight": 1,
                "sound": "WINDOWSHOW",
                "callback": lambda event, mi: self.screensaver_setting(
                    mi, "whenPlaying"
                ),
            },
            {
                "text": self.string("SCREENSAVER_WHEN_STOPPED"),
                "weight": 1,
                "sound": "WINDOWSHOW",
                "callback": lambda event, mi: self.screensaver_setting(
                    mi, "whenStopped"
                ),
            },
            {
                "text": self.string("SCREENSAVER_DELAY"),
                "weight": 5,
                "sound": "WINDOWSHOW",
                "callback": lambda event, mi: self.timeout_setting(mi),
            },
        ]

        menu = SimpleMenu("menu", items)

        # Only present "when off" option when a local player is present
        Player = _Player()
        has_local = False
        if Player is not None and hasattr(Player, "getLocalPlayer"):
            has_local = Player.getLocalPlayer() is not None
        elif Player is not None and hasattr(Player, "get_local_player"):
            has_local = Player.get_local_player() is not None

        if has_local:
            menu.add_item(
                {
                    "text": self.string("SCREENSAVER_WHEN_OFF"),
                    "weight": 2,
                    "sound": "WINDOWSHOW",
                    "callback": lambda event, mi: self.screensaver_setting(
                        mi, "whenOff"
                    ),
                }
            )

        if hasattr(menu, "set_comparator"):
            menu.set_comparator(menu.itemComparatorWeightAlpha)
        elif hasattr(menu, "setComparator"):
            menu.setComparator(
                getattr(menu, "itemComparatorWeightAlpha", None)
                or getattr(menu, "item_comparator_weight_alpha", None)
            )

        # Add settings sub-menus from registered screensavers
        mgr = _get_applet_manager()
        for setting_name, screensaver in self.screensaverSettings.items():
            menu.add_item(
                {
                    "text": setting_name,
                    "weight": 3,
                    "sound": "WINDOWSHOW",
                    "callback": lambda event, mi, ss=screensaver: (
                        self._open_ss_settings(ss, mi)
                    ),
                }
            )

        title_text = ""
        if menu_item and isinstance(menu_item, dict):
            title_text = menu_item.get("text", "")
        elif menu_item and hasattr(menu_item, "text"):
            title_text = menu_item.text

        window = Window("text_list", title_text, "settingstitle")
        window.add_widget(menu)

        # Store settings when window closes
        def _on_pop(event: Any) -> int:
            self.store_settings()
            return int(EVENT_UNUSED)

        window.add_listener(int(EVENT_WINDOW_POP), _on_pop)

        self.tie_and_show_window(window)
        return window

    # Lua alias
    openSettings = open_settings

    def screensaver_setting(self, menu_item: Any, mode: str) -> Any:
        """Show the screensaver choice menu for *mode*.

        *mode* is one of ``"whenPlaying"``, ``"whenStopped"``,
        ``"whenOff"``.
        """
        SimpleMenu = _SimpleMenu()
        RadioGroup = _RadioGroup()
        RadioButton = _RadioButton()
        Window = _Window()
        Textarea = _Textarea()

        menu = SimpleMenu("menu")
        if hasattr(menu, "set_comparator"):
            menu.set_comparator(menu.itemComparatorWeightAlpha)
        elif hasattr(menu, "setComparator"):
            menu.setComparator(
                getattr(menu, "itemComparatorWeightAlpha", None)
                or getattr(menu, "item_comparator_weight_alpha", None)
            )

        settings = self.get_settings() or {}
        active_screensaver = settings.get(mode, "")

        group = RadioGroup()

        for key, screensaver in self.screensavers.items():
            # Check mode exclusions
            exclusions = screensaver.get("modeExclusions")
            if exclusions and mode in exclusions:
                continue

            button = RadioButton(
                "radio",
                group,
                lambda *_args, k=key: self.set_screensaver(mode, k),
                key == active_screensaver,
            )

            # Preview handler — pressing play previews the screensaver
            def _test_screensaver(applet_self: Any, k: str = key) -> int:
                self.demoScreensaver = k
                self._activate(k, force=True)
                return int(EVENT_CONSUME)

            if hasattr(button, "add_action_listener"):
                button.add_action_listener("play", self, _test_screensaver)
                button.add_action_listener("add", self, _test_screensaver)
            elif hasattr(button, "addActionListener"):
                button.addActionListener("play", self, _test_screensaver)
                button.addActionListener("add", self, _test_screensaver)

            # Default weight
            weight = screensaver.get("weight")
            if weight is None:
                weight = 100

            menu.add_item(
                {
                    "text": screensaver.get("displayName", key),
                    "style": "item_choice",
                    "check": button,
                    "weight": weight,
                }
            )

        # Help text header
        token = "SCREENSAVER_SELECT_PLAYING_HELP"
        if mode == "whenStopped":
            token = "SCREENSAVER_SELECT_STOPPED_HELP"
        elif mode == "whenOff":
            token = "SCREENSAVER_SELECT_OFF_HELP"

        header = Textarea("help_text", self.string(token))
        if hasattr(menu, "set_header_widget"):
            menu.set_header_widget(header)
        elif hasattr(menu, "setHeaderWidget"):
            menu.setHeaderWidget(header)

        title_text = ""
        if menu_item and isinstance(menu_item, dict):
            title_text = menu_item.get("text", "")
        elif menu_item and hasattr(menu_item, "text"):
            title_text = menu_item.text

        window = Window("text_list", title_text, "settingstitle")
        window.add_widget(menu)

        def _on_pop(event: Any) -> int:
            self.restartScreenSaverTimer()
            self.store_settings()
            return int(EVENT_UNUSED)

        window.add_listener(int(EVENT_WINDOW_POP), _on_pop)

        self.tie_and_show_window(window)
        return window

    # Lua alias
    screensaverSetting = screensaver_setting

    def timeout_setting(self, menu_item: Any = None) -> Any:
        """Show the timeout choice menu."""
        RadioGroup = _RadioGroup()
        RadioButton = _RadioButton()
        SimpleMenu = _SimpleMenu()
        Window = _Window()

        settings = self.get_settings() or {}
        current_timeout = settings.get("timeout", 30000)

        group = RadioGroup()

        timeout_choices = [
            ("DELAY_10_SEC", 10000),
            ("DELAY_20_SEC", 20000),
            ("DELAY_30_SEC", 30000),
            ("DELAY_1_MIN", 60000),
            ("DELAY_2_MIN", 120000),
            ("DELAY_5_MIN", 300000),
            ("DELAY_10_MIN", 600000),
            ("DELAY_30_MIN", 1800000),
        ]

        items = []
        for token, ms in timeout_choices:
            items.append(
                {
                    "text": self.string(token),
                    "style": "item_choice",
                    "check": RadioButton(
                        "radio",
                        group,
                        lambda *_args, t=ms: self.set_timeout(t),
                        current_timeout == ms,
                    ),
                }
            )

        title_text = ""
        if menu_item and isinstance(menu_item, dict):
            title_text = menu_item.get("text", "")
        elif menu_item and hasattr(menu_item, "text"):
            title_text = menu_item.text

        window = Window("text_list", title_text, "settingstitle")
        window.add_widget(SimpleMenu("menu", items))

        def _on_pop(event: Any) -> int:
            self.store_settings()
            return int(EVENT_UNUSED)

        window.add_listener(int(EVENT_WINDOW_POP), _on_pop)

        self.tie_and_show_window(window)
        return window

    # Lua alias
    timeoutSetting = timeout_setting

    # ==================================================================
    # Screensaver / timeout setters
    # ==================================================================

    def set_screensaver(self, mode: str, key: str) -> None:
        """Set the screensaver for *mode* to the screensaver *key*."""
        settings = self.get_settings()
        if settings is not None:
            settings[mode] = key

    # Lua alias
    setScreenSaver = set_screensaver

    def set_timeout(self, timeout: int) -> None:
        """Set the idle timeout in milliseconds."""
        settings = self.get_settings()
        if settings is not None:
            settings["timeout"] = timeout

        self.timeout = timeout
        if self.timer is not None:
            self.timer.set_interval(self.timeout)

    # Lua alias
    setTimeout = set_timeout

    # ==================================================================
    # Key generation
    # ==================================================================

    @staticmethod
    def get_key(
        applet_name: Any,
        method: Any,
        additional_key: Optional[str] = None,
    ) -> str:
        """Build the screensaver registry key.

        Format: ``"appletName:method"`` or
        ``"appletName:method:additionalKey"``.
        """
        key = f"{applet_name}:{method}"
        if additional_key:
            key = f"{key}:{additional_key}"
        return key

    # Lua alias
    getKey = get_key

    # ==================================================================
    # Activation / deactivation
    # ==================================================================

    def _activate(
        self,
        the_screensaver: Optional[str] = None,
        force: bool = False,
        is_server_request: bool = False,
    ) -> None:
        """Activate a screensaver.

        If *the_screensaver* is ``None`` the screensaver configured for
        the current mode is used.

        *force* is set to ``True`` for preview, allowing screensavers
        that might not be shown in certain circumstances to still be
        previewed.
        """
        log.debug("Screensaver activate")

        if the_screensaver is None:
            self.currentSS = self._get_default_screensaver()
        else:
            self.currentSS = the_screensaver

        screensaver = self.screensavers.get(self.currentSS or "")

        # Avoid reactivating BlankScreen when already active (bug #14986)
        if self.isScreensaverActive and self.current == "BlankScreen":  # type: ignore[truthy-function]
            log.warn(
                "BlankScreen SS is currently active and we're trying "
                "to reactivate it. Nothing to activate then, so return"
            )
            return

        # Check if the top window allows screensavers
        fw = _get_framework()
        if fw is not None and fw.window_stack:
            top_window = fw.window_stack[0]
            if (
                hasattr(top_window, "can_activate_screensaver")
                and not top_window.can_activate_screensaver()
                and self.is_soft_power_on()
            ):
                # Set the screensaver to activate 10s after the window
                # is closed
                def _on_inactive(event: Any) -> int:
                    if self.timer is not None and not self.timer.is_running():
                        self.timer.restart(10000)
                    return int(EVENT_UNUSED)

                top_window.add_listener(int(EVENT_WINDOW_INACTIVE), _on_inactive)
                return

        # The "none" choice is "false:false"
        if self.currentSS == "false:false":
            log.warn(
                '"none" is the configured screensaver for %s, so do nothing',
                self._get_mode(),
            )
            return

        # Check the year for clock fallback (bug #15654)
        use_blank_ss = False
        try:
            year = int(time.strftime("%Y"))
            use_blank_ss = (
                year < 2010
                and not force
                and self._get_mode() == "whenOff"
                and not is_server_request
            )
        except (ValueError, OSError) as exc:
            log.debug("Failed to determine year for clock fallback: %s", exc)

        # Fallback to default if screensaver is not available
        if not screensaver or not screensaver.get("applet") or use_blank_ss:
            if use_blank_ss:
                log.warn("Clock is not set properly, so fallback to blank screen SS")
                self.currentSS = "BlankScreen:openScreensaver"
                screensaver = self.screensavers.get(self.currentSS)
            else:
                log.warn(
                    "The configured screensaver method %s is not available. "
                    "Falling back to default from Meta file",
                    self.currentSS,
                )
                if self.defaultSettings:
                    self.currentSS = self.defaultSettings.get(
                        self._get_mode(), "false:false"
                    )
                else:
                    self.currentSS = "false:false"
                screensaver = self.screensavers.get(self.currentSS or "")

        if screensaver and screensaver.get("applet"):
            mgr = _get_applet_manager()
            if mgr is not None:
                instance = mgr.load_applet(screensaver["applet"])
                if instance is not None:
                    method_name = screensaver.get("method", "openScreensaver")
                    method = getattr(instance, method_name, None)
                    if method is not None:
                        result = method(force, screensaver.get("methodParam"))
                        if result is not False:
                            log.info(
                                "activating %s screensaver",
                                screensaver["applet"],
                            )
                    else:
                        log.warn(
                            "Screensaver method %s not found on %s",
                            method_name,
                            screensaver["applet"],
                        )
            self.isScreenSaverActive = True
        else:
            log.info("There is no screensaver applet available for this mode")

    def _deactivate(
        self,
        window: Any,
        the_screensaver: Optional[str] = None,
    ) -> None:
        """Deactivate a screensaver window."""
        log.debug("Screensaver deactivate")

        self._clear_ss_allowed_actions()
        self._close_any_power_on_window()

        if not the_screensaver:
            the_screensaver = self._get_default_screensaver()

        screensaver = self.screensavers.get(the_screensaver or "")

        if screensaver and screensaver.get("applet") and screensaver.get("closeMethod"):
            mgr = _get_applet_manager()
            if mgr is not None:
                instance = mgr.load_applet(screensaver["applet"])
                if instance is not None:
                    close_method = getattr(instance, screensaver["closeMethod"], None)
                    if close_method is not None:
                        close_method(screensaver.get("methodParam"))

        Window = _Window()
        if hasattr(window, "hide"):
            trans = getattr(Window, "transitionNone", None)
            window.hide(trans)

        self.demoScreensaver = None

    # ==================================================================
    # Mode detection
    # ==================================================================

    def _get_mode(self) -> str:
        """Return the current screensaver mode.

        Returns one of ``"whenPlaying"``, ``"whenStopped"``, or
        ``"whenOff"``.
        """
        sys_instance = _System()
        has_soft_power = False
        if sys_instance is not None:
            has_soft_power = (
                sys_instance.has_soft_power()
                if hasattr(sys_instance, "has_soft_power")
                else False
            )

        if not self.is_soft_power_on() and has_soft_power:
            return "whenOff"

        mgr = _get_applet_manager()
        if mgr is not None:
            player = mgr.call_service("getCurrentPlayer")
            if player is not None:
                play_mode = None
                if hasattr(player, "get_play_mode"):
                    play_mode = player.get_play_mode()
                elif hasattr(player, "getPlayMode"):
                    play_mode = player.getPlayMode()
                if play_mode == "play":
                    return "whenPlaying"

        return "whenStopped"

    def _get_default_screensaver(self) -> str:
        """Return the screensaver key for the current mode."""
        ss_mode = self._get_mode()
        settings = self.get_settings() or {}

        if ss_mode == "whenOff":
            ss = self._get_off_screensaver()
            log.debug("whenOff: %s", ss)
        elif ss_mode == "whenPlaying":
            ss = settings.get("whenPlaying", "NowPlaying:openScreensaver")
            log.debug("whenPlaying: %s", ss)
        else:
            ss = settings.get("whenStopped", "Clock:openDetailedClock")
            log.debug("whenStopped: %s", ss)

        return ss or "false:false"

    def _get_off_screensaver(self) -> str:
        """Return the configured 'when off' screensaver key."""
        settings = self.get_settings() or {}
        return settings.get("whenOff", "BlankScreen:openScreensaver")  # type: ignore[no-any-return]

    # ==================================================================
    # Soft power helpers
    # ==================================================================

    def is_soft_power_on(self) -> bool:
        """Return ``True`` if the system's soft power is on."""
        jive_main = _get_jive_main()
        if jive_main is not None:
            state = None
            if hasattr(jive_main, "get_soft_power_state"):
                state = jive_main.get_soft_power_state()
            elif hasattr(jive_main, "getSoftPowerState"):
                state = jive_main.getSoftPowerState()
            return state == "on"
        return True  # Assume on if JiveMain is not available

    # Lua alias
    isSoftPowerOn = is_soft_power_on

    # ==================================================================
    # Power-on window
    # ==================================================================

    def _show_power_on_window(self) -> None:
        """Show a transparent power-on overlay window.

        This window intercepts input during soft-power-off and allows
        only power-related actions through.  It auto-hides after 5
        seconds.
        """
        if self.powerOnWindow:
            return

        # Notify the active screensaver that an overlay is being shown
        ss_key = self.currentSS or self._get_off_screensaver()
        if ss_key:
            screensaver = self.screensavers.get(ss_key)
            if screensaver and screensaver.get("applet"):
                sys_instance = _System()
                has_touch = False
                if sys_instance is not None:
                    has_touch = (
                        sys_instance.has_touch()
                        if hasattr(sys_instance, "has_touch")
                        else False
                    )

                if not has_touch:
                    log.debug("ss: don't use power on window")
                    return

                mgr = _get_applet_manager()
                if mgr is not None:
                    instance = mgr.load_applet(screensaver["applet"])
                    if instance is not None and hasattr(
                        instance, "onOverlayWindowShown"
                    ):
                        instance.onOverlayWindowShown()

        Window = _Window()
        self.powerOnWindow = Window("power_on_window")

        if hasattr(self.powerOnWindow, "set_button_action"):
            self.powerOnWindow.set_button_action("lbutton", "power")
            self.powerOnWindow.set_button_action("rbutton", None)
        elif hasattr(self.powerOnWindow, "setButtonAction"):
            self.powerOnWindow.setButtonAction("lbutton", "power")
            self.powerOnWindow.setButtonAction("rbutton", None)

        self.powerOnWindow.set_transparent(True)
        self.powerOnWindow.set_always_on_top(True)
        self.powerOnWindow.set_allow_screensaver(False)

        self.powerOnWindow.ignore_all_input_except(
            ["power", "power_on", "power_off"],
            lambda action_event: self._power_action_handler(action_event),
        )

        trans = getattr(Window, "transitionNone", None)
        self.powerOnWindow.show(trans)

        # Auto-close after 5 seconds
        Timer = _Timer()
        self.powerOnWindow.add_timer(
            5000,
            lambda: self._close_any_power_on_window(),
        )

    def _close_any_power_on_window(self) -> None:
        """Close the power-on overlay window if it exists."""
        if self.powerOnWindow:
            Window = _Window()
            trans = getattr(Window, "transitionNone", None)
            self.powerOnWindow.hide(trans)
            self.powerOnWindow = None

            # Notify the screensaver that the overlay is hidden
            ss_key = self._get_off_screensaver()
            if ss_key:
                screensaver = self.screensavers.get(ss_key)
                if screensaver and screensaver.get("applet"):
                    mgr = _get_applet_manager()
                    if mgr is not None:
                        instance = mgr.load_applet(screensaver["applet"])
                        if instance is not None and hasattr(
                            instance, "onOverlayWindowHidden"
                        ):
                            instance.onOverlayWindowHidden()

    def _power_action_handler(self, action_event: Any) -> Optional[int]:
        """Handle actions during soft-power-off.

        Allowed actions (play presets, play/pause, shutdown) turn power
        on and forward the action; other input shows the power-on window.
        """
        action = None
        if hasattr(action_event, "get_action"):
            action = action_event.get_action()
        elif hasattr(action_event, "getAction"):
            action = action_event.getAction()

        if action and action in _POWER_ALLOWED_ACTIONS:
            jive_main = _get_jive_main()
            if jive_main is not None:
                jive_main.set_soft_power_state("on")

            translated_action = action
            if _POWER_ALLOWED_ACTIONS[action] != 1:
                translated_action = _POWER_ALLOWED_ACTIONS[action]

            fw = _get_framework()
            if fw is not None:
                fw.push_action(translated_action)
            return None

        # Show the power-on window
        self._show_power_on_window()
        return None

    # ==================================================================
    # SS allowed actions management
    # ==================================================================

    def _set_ss_allowed_actions(
        self,
        scroll_allowed: Optional[bool],
        ss_allowed_actions: Optional[List[str]],
        mouse_allowed: Optional[bool],
    ) -> None:
        """Set the per-screensaver input passthrough flags."""
        self.scrollAllowed = scroll_allowed
        self.ssAllowedActions = ss_allowed_actions
        self.mouseAllowed = mouse_allowed

    def _clear_ss_allowed_actions(self) -> None:
        """Clear the per-screensaver input passthrough flags."""
        self._set_ss_allowed_actions(None, None, None)

    # ==================================================================
    # Mouse/scroll handlers for when-off state
    # ==================================================================

    def _on_ss_mouse_when_off(self) -> int:
        """Handle mouse events on a screensaver when soft-power is off."""
        self._show_power_on_window()
        return int(EVENT_CONSUME)

    def _on_ss_scroll_when_off(self) -> int:
        """Handle scroll events on a screensaver when soft-power is off."""
        self._show_power_on_window()
        return int(EVENT_CONSUME)

    # ==================================================================
    # Settings sub-menu opener
    # ==================================================================

    def _open_ss_settings(self, screensaver: Dict[str, Any], menu_item: Any) -> None:
        """Open the settings UI for a specific screensaver."""
        mgr = _get_applet_manager()
        if (
            mgr is not None
            and screensaver.get("applet")
            and screensaver.get("settings")
        ):
            instance = mgr.load_applet(screensaver["applet"])
            if instance is not None:
                settings_method = getattr(instance, screensaver["settings"], None)
                if settings_method is not None:
                    settings_method(menu_item)

    # ==================================================================
    # Network thread helper
    # ==================================================================

    @staticmethod
    def _get_jnt() -> Any:
        """Try to obtain the NetworkThread singleton."""
        try:
            from jive.jive_main import jive_main as _jm

            if _jm is not None:
                return getattr(_jm, "jnt", None)
        except ImportError as exc:
            log.debug("_get_jnt: jive_main not available: %s", exc)
        return None

    # ==================================================================
    # Repr
    # ==================================================================

    def __repr__(self) -> str:
        n_ss = len(self.screensavers)
        n_active = len(self.active)
        return (
            f"ScreenSaversApplet(screensavers={n_ss}, "
            f"active={n_active}, "
            f"is_active={self.isScreenSaverActive}, "
            f"timeout={self.timeout})"
        )

    def __str__(self) -> str:
        return self.__repr__()
