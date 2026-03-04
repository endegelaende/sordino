"""
jive.applets.LineIn.LineInApplet — Line-In audio source management.

Ported from ``share/jive/applets/LineIn/LineInApplet.lua`` in the original
jivelite project.

This applet manages the Line In audio source on devices that support it.
It provides:

* A home menu checkbox item to enable/disable line-in
* A NowPlaying-style window when line-in is active
* Play/pause/stop action listeners during line-in capture
* Integration with screensaver and NowPlaying services

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from jive.applet import Applet
from jive.utils.log import logger

__all__ = ["LineInApplet"]

log = logger("applet.LineIn")


class LineInApplet(Applet):
    """Line-In audio source applet."""

    def __init__(self) -> None:
        super().__init__()
        self.checkbox: Any = None
        self.np_window: Any = None
        self.listener_handles: List[Any] = []

    def init(self) -> None:
        super().init()
        jnt = self._get_jnt()
        if jnt is not None:
            jnt.subscribe(self)

    # ------------------------------------------------------------------
    # Service: addLineInMenuItem
    # ------------------------------------------------------------------

    def addLineInMenuItem(self) -> None:
        """Add a Line In checkbox item to the home menu."""
        try:
            from jive.ui.checkbox import Checkbox
        except ImportError as exc:
            log.warn("Checkbox not available: %s", exc)
            return

        jive_main = self._get_jive_main()
        if jive_main is None:
            return

        self.checkbox = Checkbox(
            "checkbox",
            lambda _widget, checked: self.activateLineIn(checked),
        )

        jive_main.add_item(
            {
                "id": "linein",
                "node": "home",
                "text": self.string("LINE_IN"),
                "style": "item_choice",
                "iconStyle": "hm_linein",
                "check": self.checkbox,
                "weight": 50,
            }
        )

    # Lua-compatible alias
    add_line_in_menu_item = addLineInMenuItem

    # ------------------------------------------------------------------
    # Service: activateLineIn
    # ------------------------------------------------------------------

    def activateLineIn(
        self, active: bool, initial_play_mode: Optional[str] = None
    ) -> None:
        """Activate or deactivate line-in.

        Parameters
        ----------
        active:
            True to activate, False to deactivate.
        initial_play_mode:
            Initial capture play mode (default ``"play"``).
        """
        if self.checkbox is None:
            self.addLineInMenuItem()

        if self.checkbox is not None:
            if hasattr(self.checkbox, "setSelected"):
                self.checkbox.setSelected(active)
            elif hasattr(self.checkbox, "set_selected"):
                self.checkbox.set_selected(active)

        if active:
            self._activate_line_in(initial_play_mode)
        else:
            self._deactivate_line_in()

    # Lua-compatible alias
    activate_line_in = activateLineIn

    # ------------------------------------------------------------------
    # Service: isLineInActive
    # ------------------------------------------------------------------

    def isLineInActive(self) -> bool:
        """Return True if line-in is currently active."""
        return self.np_window is not None

    # Lua-compatible alias
    is_line_in_active = isLineInActive

    # ------------------------------------------------------------------
    # Service: getLineInNpWindow
    # ------------------------------------------------------------------

    def getLineInNpWindow(self) -> Any:
        """Return the line-in NowPlaying window, or None."""
        return self.np_window

    # Lua-compatible alias
    get_line_in_np_window = getLineInNpWindow

    # ------------------------------------------------------------------
    # Service: removeLineInMenuItem
    # ------------------------------------------------------------------

    def removeLineInMenuItem(self) -> None:
        """Remove the Line In menu item and deactivate."""
        jive_main = self._get_jive_main()
        if jive_main is not None:
            jive_main.remove_item_by_id("linein")
        self.checkbox = None
        self._deactivate_line_in()

    # Lua-compatible alias
    remove_line_in_menu_item = removeLineInMenuItem

    # ------------------------------------------------------------------
    # Internal activation / deactivation
    # ------------------------------------------------------------------

    def _activate_line_in(self, initial_play_mode: Optional[str] = None) -> None:
        """Start line-in capture."""
        log.info("_activate_line_in")

        player = self._get_local_player()
        if player is None:
            log.warn("No local player available for line-in")
            return

        if hasattr(player, "stop"):
            player.stop(True)
        if hasattr(player, "setCapturePlayMode"):
            player.setCapturePlayMode(initial_play_mode or "play")
        elif hasattr(player, "set_capture_play_mode"):
            player.set_capture_play_mode(initial_play_mode or "play")

        self._add_listeners()
        self.createLineInNowPlaying()

        mgr = self._get_applet_manager()
        if mgr is not None:
            try:
                mgr.call_service("deactivateScreensaver")
            except Exception as exc:
                log.error("deactivateScreensaver service call failed: %s", exc, exc_info=True)
            try:
                mgr.call_service("restartScreenSaverTimer")
            except Exception as exc:
                log.error("restartScreenSaverTimer service call failed: %s", exc, exc_info=True)
            try:
                mgr.call_service("goNowPlaying")
            except Exception as exc:
                log.error("goNowPlaying service call failed: %s", exc, exc_info=True)

    def _deactivate_line_in(self) -> None:
        """Stop line-in capture."""
        log.info("_deactivate_line_in")

        player = self._get_local_player()
        if player is not None:
            if hasattr(player, "setCapturePlayMode"):
                player.setCapturePlayMode(None)
            elif hasattr(player, "set_capture_play_mode"):
                player.set_capture_play_mode(None)

        self._remove_listeners()

        if self.np_window is not None:
            try:
                self.np_window.hide()
            except Exception as exc:
                log.warning("Failed to hide NowPlaying window: %s", exc)
        self.np_window = None

    # ------------------------------------------------------------------
    # Notifications
    # ------------------------------------------------------------------

    def notify_playerModeChange(self, player: Any, mode: Any) -> None:
        """Handle player mode change — deactivate line-in if play starts."""
        local_player = self._get_local_player()
        if local_player is None or local_player is not player:
            return

        if mode == "play" and self.isLineInActive():
            log.info("player mode changed to play, deactivating line in")
            self.activateLineIn(False)

    # Lua-compatible alias
    notify_player_mode_change = notify_playerModeChange

    # ------------------------------------------------------------------
    # Action listeners
    # ------------------------------------------------------------------

    def _add_listeners(self) -> None:
        """Register play/pause/stop action listeners."""
        log.debug("_add_listeners")
        self._remove_listeners()

        fw = self._get_framework()
        if fw is None:
            return

        try:
            from jive.ui.constants import EVENT_CONSUME
        except ImportError:
            return

        def _get_lp() -> Any:
            return self._get_local_player()

        def pause_action(event: Any = None) -> int:
            lp = _get_lp()
            if lp is not None:
                current = None
                if hasattr(lp, "getCapturePlayMode"):
                    current = lp.getCapturePlayMode()
                elif hasattr(lp, "get_capture_play_mode"):
                    current = lp.get_capture_play_mode()

                new_mode = "pause" if current == "play" else "play"
                if hasattr(lp, "setCapturePlayMode"):
                    lp.setCapturePlayMode(new_mode)
                elif hasattr(lp, "set_capture_play_mode"):
                    lp.set_capture_play_mode(new_mode)
            return int(EVENT_CONSUME)

        def stop_action(event: Any = None) -> int:
            lp = _get_lp()
            if lp is not None:
                if hasattr(lp, "setCapturePlayMode"):
                    lp.setCapturePlayMode("pause")
                elif hasattr(lp, "set_capture_play_mode"):
                    lp.set_capture_play_mode("pause")
            return int(EVENT_CONSUME)

        def play_action(event: Any = None) -> int:
            lp = _get_lp()
            if lp is not None:
                if hasattr(lp, "setCapturePlayMode"):
                    lp.setCapturePlayMode("play")
                elif hasattr(lp, "set_capture_play_mode"):
                    lp.set_capture_play_mode("play")
            return int(EVENT_CONSUME)

        def nothing_action(event: Any = None) -> int:
            return int(EVENT_CONSUME)

        def go_now_playing_action(event: Any = None) -> int:
            mgr = self._get_applet_manager()
            if mgr is not None:
                try:
                    mgr.call_service("goNowPlaying")
                except Exception as exc:
                    log.error("goNowPlaying service call failed: %s", exc, exc_info=True)
            return int(EVENT_CONSUME)

        actions = [
            ("mute", pause_action),
            ("pause", pause_action),
            ("stop", stop_action),
            ("play", play_action),
            ("jump_rew", nothing_action),
            ("jump_fwd", nothing_action),
            ("scanner_rew", nothing_action),
            ("scanner_fwd", nothing_action),
            ("go_current_track_info", go_now_playing_action),
            ("go_playlist", go_now_playing_action),
        ]

        for action_name, handler in actions:
            try:
                handle = fw.add_action_listener(action_name, self, handler, 0.5)
                if handle is not None:
                    self.listener_handles.append(handle)
            except Exception as exc:
                log.debug("Failed to add listener for %s: %s", action_name, exc)

    def _remove_listeners(self) -> None:
        """Remove all registered action listeners."""
        log.debug("_remove_listeners")
        fw = self._get_framework()
        if fw is not None:
            for handle in self.listener_handles:
                try:
                    fw.remove_listener(handle)
                except Exception as exc:
                    log.warning("Failed to remove listener %s: %s", handle, exc)
        self.listener_handles = []

    # ------------------------------------------------------------------
    # NowPlaying window
    # ------------------------------------------------------------------

    def createLineInNowPlaying(self) -> None:
        """Create and display the line-in NowPlaying window."""
        log.debug("createLineInNowPlaying")

        try:
            from jive.ui.group import Group
            from jive.ui.icon import Icon
            from jive.ui.label import Label
            from jive.ui.window import Window
        except ImportError as exc:
            log.warn("UI modules not available: %s", exc)
            return

        window = Window("linein")

        title_group = Group(
            "title",
            {
                "lbutton": window.create_default_left_button()  # type: ignore[dict-item]
                if hasattr(window, "create_default_left_button")
                else (
                    window.createDefaultLeftButton()
                    if hasattr(window, "createDefaultLeftButton")
                    else None
                ),
                "text": Label("text", self.string("LINE_IN")),
                "rbutton": None,  # type: ignore[dict-item]
            },
        )

        artwork_group = Group(
            "npartwork",
            {"artwork": Icon("icon_linein")},
        )

        nptrack_group = Group(
            "nptitle",
            {
                "nptrack": Label("nptrack", self.string("LINE_IN")),
                "xofy": None,  # type: ignore[dict-item]
            },
        )

        window.add_widget(title_group)
        window.add_widget(nptrack_group)
        window.add_widget(artwork_group)

        self.np_window = window

    # Lua-compatible alias
    create_line_in_now_playing = createLineInNowPlaying

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def free(self) -> bool:
        """Cannot be freed — resident applet."""
        return False

    # ------------------------------------------------------------------
    # Singleton accessors
    # ------------------------------------------------------------------

    @staticmethod
    def _get_local_player() -> Any:
        try:
            from jive.slim.player import Player

            return Player.get_local_player()
        except (ImportError, AttributeError):
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
            log.debug("_get_jive_main: first import failed: %s", exc)
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
