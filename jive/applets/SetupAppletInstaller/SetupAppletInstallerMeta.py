"""
jive.applets.SetupAppletInstaller.SetupAppletInstallerMeta — Meta class.

Ported from ``share/jive/applets/SetupAppletInstaller/SetupAppletInstallerMeta.lua``
in the original jivelite project.

The Meta class:

* Declares version compatibility (1, 1)
* Provides default settings (``_AUTOUP: False``)
* Registers the ``appletInstallerMenu`` service
* Adds an "Applet Installer" menu item under ``advancedSettings``
* On ``configure_applet()``, checks whether a firmware upgrade occurred
  and, if auto-update is enabled, schedules an automatic reinstall of
  previously-installed 3rd-party applets via a short timer.

The Lua original::

    function defaultSettings(self)
        return { _AUTOUP = false }
    end

    function registerApplet(self)
        self.menu = self:menuItem(
            'appletSetupAppletInstaller', 'advancedSettings',
            self:string("APPLET_INSTALLER"),
            function(applet, ...) applet:appletInstallerMenu(...) end
        )
        jiveMain:addItem(self.menu)
        self:registerService("appletInstallerMenu")
    end

    function configureApplet(self)
        local settings = self:getSettings()
        if settings._AUTOUP and settings._LASTVER
           and settings._LASTVER ~= JIVE_VERSION then
            Timer(5000, function()
                appletManager:callService("appletInstallerMenu",
                    { text = self:string("APPLET_INSTALLER") }, 'auto')
            end, true):start()
        end
        settings._LASTVER = JIVE_VERSION
        self:storeSettings()
    end

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from jive.applet_meta import AppletMeta
from jive.utils.log import logger

__all__ = ["SetupAppletInstallerMeta"]

log = logger("applet.SetupAppletInstaller")

# Sentinel used when the real JIVE_VERSION is unavailable.
_FALLBACK_VERSION = "0.0.0"


class SetupAppletInstallerMeta(AppletMeta):
    """Meta-information for the SetupAppletInstaller applet.

    Registers the ``appletInstallerMenu`` service and optionally
    triggers an automatic reinstall of third-party applets after a
    firmware / application version upgrade.
    """

    # ------------------------------------------------------------------
    # Required overrides
    # ------------------------------------------------------------------

    def jive_version(self) -> Tuple[int, int]:
        return (1, 1)

    def default_settings(self) -> Optional[Dict[str, Any]]:
        """Default settings — auto-update after firmware upgrade off."""
        return {"_AUTOUP": False}

    def register_applet(self) -> None:
        """Register the Applet Installer menu item and service.

        Mirrors the Lua ``registerApplet`` — adds a menu item under
        ``advancedSettings`` and registers the ``appletInstallerMenu``
        service so other code can open the installer programmatically.
        """
        # -- Register service -------------------------------------------
        self.register_service("appletInstallerMenu")

        # -- Add menu item under advancedSettings -----------------------
        jive_main = self._get_jive_main()
        if jive_main is not None:
            menu = self.menu_item(
                id="appletSetupAppletInstaller",
                node="advancedSettings",
                label="APPLET_INSTALLER",
                closure=lambda applet, menu_item: applet.appletInstallerMenu(menu_item),
            )
            jive_main.add_item(menu)
        else:
            log.debug("register_applet: JiveMain not available — menu item not added")

    def configure_applet(self) -> None:
        """Post-registration configuration.

        If auto-update is enabled (``_AUTOUP``) and the application
        version has changed since the last run (``_LASTVER``), schedule
        a 5-second timer that opens the applet installer in ``'auto'``
        mode to reinstall previously-installed third-party applets.

        After the check, the current version is persisted so that the
        auto-reinstall fires only once per upgrade.
        """
        settings = self.get_settings()
        if settings is None:
            settings = self.default_settings() or {}
            self._settings = settings

        jive_version = self._get_jive_version_string()
        auto_up = settings.get("_AUTOUP", False)
        last_ver = settings.get("_LASTVER")

        if auto_up and last_ver and last_ver != jive_version:
            log.info(
                "Version changed (%s -> %s) with _AUTOUP enabled — "
                "scheduling auto-reinstall",
                last_ver,
                jive_version,
            )
            self._schedule_auto_reinstall()

        # Persist the current version
        settings["_LASTVER"] = jive_version
        self.store_settings()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _schedule_auto_reinstall(self) -> None:
        """Schedule a timer to open the applet installer in auto mode.

        Uses a 5-second one-shot timer (matching the Lua original) so
        that servers have time to reconnect before the installer
        queries them.
        """
        Timer = self._get_timer_class()
        if Timer is None:
            log.warn("Timer class not available — cannot schedule auto-reinstall")
            return

        label_text = self.string("APPLET_INSTALLER")

        def _on_timer(*_args: Any, **_kwargs: Any) -> None:
            mgr = self._get_applet_manager()
            if mgr is not None:
                try:
                    mgr.call_service(
                        "appletInstallerMenu",
                        {"text": label_text},
                        "auto",
                    )
                except Exception as exc:
                    log.warn("Auto-reinstall failed: %s", exc)

        try:
            timer = Timer(5000, _on_timer, True)
            timer.start()
        except Exception as exc:
            log.warn("Failed to create auto-reinstall timer: %s", exc)

    @staticmethod
    def _get_jive_version_string() -> str:
        """Return the current JIVE_VERSION string."""
        try:
            from jive.ui.constants import JIVE_VERSION  # type: ignore[attr-defined]

            return str(JIVE_VERSION)
        except (ImportError, AttributeError) as exc:
            log.debug("_get_jive_version_string: constants not available: %s", exc)
        try:
            import jive

            ver = getattr(jive, "JIVE_VERSION", None)
            if ver is not None:
                return str(ver)
        except ImportError as exc:
            log.debug("_get_jive_version_string: jive not importable: %s", exc)
        return _FALLBACK_VERSION

    @staticmethod
    def _get_jive_main() -> Any:
        """Try to obtain the JiveMain singleton."""
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
    def _get_timer_class() -> Any:
        """Try to obtain the Timer class."""
        try:
            from jive.ui.timer import Timer

            return Timer
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
