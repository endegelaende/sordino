"""
jive.applets.SetupWelcome.SetupWelcomeApplet — First-run setup wizard.

Ported from ``share/jive/applets/SetupWelcome/SetupWelcomeApplet.lua``
in the original jivelite project.

This applet orchestrates the first-run setup flow:

1. Language selection (delegates to ``SetupLanguage.setupShowSetupLanguage``)
2. Skin selection (delegates to ``SelectSkin.selectSkinStartup``)
3. Player selection (delegates to ``SelectPlayer.setupShowSelectPlayer``
   or auto-selects a local player matching the system MAC)

Once setup is complete, the ``setupDone`` flag is persisted so the
wizard is not shown again on subsequent launches.

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

from typing import Any, Optional

from jive.applet import Applet
from jive.utils.log import logger

__all__ = ["SetupWelcomeApplet"]

log = logger("applet.SetupWelcome")

# Window title style used for setup wizard screens
_WELCOME_TITLE_STYLE = "setuptitle"


class SetupWelcomeApplet(Applet):
    """First-run setup wizard applet.

    Orchestrates the setup flow by chaining calls to other applets'
    services:

    1. ``setupShowSetupLanguage`` (from SetupLanguage)
    2. ``selectSkinStartup`` (from SelectSkin)
    3. Mark setup done and navigate to home / select player

    The Lua original uses a chain of closures (``step1 → step2``).
    The Python port mirrors this pattern exactly.
    """

    def __init__(self) -> None:
        super().__init__()

    # ------------------------------------------------------------------
    # Public API — called via the ``setupFirstStartup`` service
    # ------------------------------------------------------------------

    def setupFirstStartup(self) -> None:
        """Launch the first-run setup wizard.

        This is the service entry point registered by
        :class:`SetupWelcomeMeta`.  It kicks off the setup chain:

        1. Show language selection
        2. Show skin selection
        3. Finish setup (persist flag, select player, go home)

        Mirrors the Lua original::

            function setupFirstStartup(self)
                local step1, step2
                step1 = function()
                    appletManager:callService("setupShowSetupLanguage", step2, false)
                end
                step2 = function()
                    appletManager:callService("selectSkinStartup",
                        function() self:setupDone() end)
                end
                step1()
            end
        """
        log.info("Starting first-run setup wizard")

        mgr = self._get_applet_manager()
        if mgr is None:
            log.warn("setupFirstStartup: AppletManager not available — skipping")
            self.setupDone()
            return

        # Build the step chain (closures referencing each other)
        def step2() -> None:
            """Step 2: Skin selection → setupDone."""
            log.info("Setup step 2: skin selection")
            try:
                mgr.call_service("selectSkinStartup", lambda: self.setupDone())
            except Exception as exc:
                log.warn("selectSkinStartup failed: %s — skipping to done", exc)
                self.setupDone()

        def step1() -> None:
            """Step 1: Language selection → step2."""
            log.info("Setup step 1: language selection")
            try:
                mgr.call_service("setupShowSetupLanguage", step2, False)
            except Exception as exc:
                log.warn("setupShowSetupLanguage failed: %s — skipping to step 2", exc)
                step2()

        step1()

    # Lua-compatible alias
    setup_first_startup = setupFirstStartup

    # ------------------------------------------------------------------
    # Setup completion
    # ------------------------------------------------------------------

    def setupDone(self) -> None:
        """Mark first-run setup as complete and navigate home.

        Persists the ``setupDone`` flag, then attempts to auto-select
        a local player (matching the system MAC address).  If no local
        player is found, delegates to the ``setupShowSelectPlayer``
        service.

        Mirrors the Lua original::

            function setupDone(self)
                self:getSettings().setupDone = true
                self:storeSettings()

                local closeTask = Task('closetohome', self,
                    function(self)
                        jiveMain:closeToHome(true, Window.transitionPushLeft)
                    end
                )

                for i, player in Player.iterate() do
                    if player:getId() == System:getMacAddress() then
                        closeTask:addTask()
                        return appletManager:callService("selectPlayer", player)
                    end
                end

                return appletManager:callService("setupShowSelectPlayer",
                    function() closeTask:addTask() end,
                    'setuptitle')
            end
        """
        log.info("Setup complete — persisting settings")

        # Mark setup as done
        settings = self.get_settings()
        if settings is None:
            settings = {}
            self.set_settings(settings)
        settings["setupDone"] = True
        self.store_settings()

        # Try to find and select a local player
        local_player = self._find_local_player()
        mgr = self._get_applet_manager()

        # Close to home
        self._close_to_home()

        if local_player is not None and mgr is not None:
            log.info("Auto-selecting local player: %s", local_player)
            try:
                mgr.call_service("selectPlayer", local_player)
            except Exception as exc:
                log.warn("selectPlayer failed: %s", exc)
            return

        # No local player found — show player selection UI
        if mgr is not None:
            try:
                mgr.call_service(
                    "setupShowSelectPlayer",
                    lambda: self._close_to_home(),
                    _WELCOME_TITLE_STYLE,
                )
            except Exception as exc:
                log.warn("setupShowSelectPlayer failed: %s — going home directly", exc)

    # Lua-compatible alias
    setup_done = setupDone

    # ------------------------------------------------------------------
    # Navigation helpers
    # ------------------------------------------------------------------

    def _close_to_home(self) -> None:
        """Navigate to the home screen, closing all setup windows.

        Attempts to use a Task for cooperative scheduling (matching
        the Lua original), falling back to a direct call.
        """
        jive_main = self._get_jive_main()
        if jive_main is None:
            log.debug("_close_to_home: JiveMain not available")
            return

        # Try with Task (cooperative scheduler) first
        try:
            from jive.ui.task import Task
            from jive.ui.window import Window

            transition = getattr(Window, "transitionPushLeft", None)

            def _do_close(_self: Any = None) -> None:
                try:
                    if hasattr(jive_main, "closeToHome"):
                        jive_main.closeToHome(True, transition)
                    elif hasattr(jive_main, "close_to_home"):
                        jive_main.close_to_home(True, transition)
                    elif hasattr(jive_main, "goHome"):
                        jive_main.goHome()
                    elif hasattr(jive_main, "go_home"):
                        jive_main.go_home()
                except Exception as exc:
                    log.warn("close_to_home failed: %s", exc)

            task = Task("closetohome", self, _do_close)
            if hasattr(task, "addTask"):
                task.addTask()
            elif hasattr(task, "add_task"):
                task.add_task()
            else:
                _do_close()

        except ImportError:
            # No Task available — call directly
            try:
                if hasattr(jive_main, "closeToHome"):
                    jive_main.closeToHome(True)
                elif hasattr(jive_main, "close_to_home"):
                    jive_main.close_to_home(True)
                elif hasattr(jive_main, "goHome"):
                    jive_main.goHome()
                elif hasattr(jive_main, "go_home"):
                    jive_main.go_home()
            except Exception as exc:
                log.warn("close_to_home fallback failed: %s", exc)

    # ------------------------------------------------------------------
    # Player discovery
    # ------------------------------------------------------------------

    def _find_local_player(self) -> Any:
        """Find a local player whose ID matches the system MAC address.

        Iterates over all known Player instances and returns the first
        one whose ``getId()`` matches ``System.getMacAddress()``.

        Returns
        -------
        The matching Player instance, or ``None`` if no match is found.
        """
        mac = self._get_system_mac()
        if not mac:
            return None

        try:
            from jive.slim.player import Player

            if hasattr(Player, "iterate"):
                for player in Player.iterate():
                    player_id = None
                    if hasattr(player, "getId"):
                        player_id = player.getId()  # type: ignore[attr-defined]
                    elif hasattr(player, "get_id"):
                        player_id = player.get_id()  # type: ignore[attr-defined]

                    if player_id and player_id == mac:
                        return player
        except ImportError as exc:
            log.debug("_find_local_player: Player module not available: %s", exc)
        except Exception as exc:
            log.debug("_find_local_player: %s", exc)

        return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_system_mac() -> Optional[str]:
        """Try to get the system MAC address from the System instance."""
        try:
            from jive.applet_manager import applet_manager as _mgr

            if _mgr is not None and hasattr(_mgr, "system") and _mgr.system is not None:
                return _mgr.system.get_mac_address()
        except Exception as exc:
            log.debug("_get_system_mac: failed via applet_manager: %s", exc)

        # Fallback: try JiveMain directly
        try:
            from jive.jive_main import jive_main as _jm

            if _jm is not None and hasattr(_jm, "_system"):
                return _jm._system.get_mac_address()
        except Exception as exc:
            log.debug("_get_system_mac: failed via jive_main: %s", exc)

        return None

    @staticmethod
    def _get_jive_main() -> Any:
        """Try to obtain the JiveMain singleton."""
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
        """Try to obtain the AppletManager singleton."""
        try:
            from jive.applet_manager import applet_manager

            return applet_manager
        except (ImportError, AttributeError):
            return None
