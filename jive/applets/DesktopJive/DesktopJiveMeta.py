"""
jive.applets.DesktopJive.DesktopJiveMeta — Meta class for DesktopJive.

Ported from ``share/jive/applets/DesktopJive/DesktopJiveMeta.lua`` in the
original jivelite project.

This is a meta-only applet (``loadPriority = 1``) that performs early
platform initialization for desktop (Linux / macOS / Windows) targets:

* Generates and persists a random UUID and MAC address
* Initializes :class:`jive.System` with the MAC and UUID
* Sets platform capabilities (powerKey, muteKey, alarmKey, wiredNetworking,
  coreKeys, presetKeys)
* Sets the default screensaver-when-stopped to ``"false:false"``
* Sets the default skin to ``HDSkin-VGA``
* Registers a ``soft_reset`` action listener that navigates home

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

import os
import random
import re
from typing import Any, Dict, Optional, Tuple

from jive.applet_meta import AppletMeta
from jive.utils.log import logger

__all__ = ["DesktopJiveMeta"]

log = logger("applet.DesktopJive")

# This applet must load before most others
LOAD_PRIORITY = 1


class DesktopJiveMeta(AppletMeta):
    """Platform initialization meta for desktop targets.

    Generates / persists a UUID and MAC address, initializes
    :class:`jive.System`, sets capabilities, and registers the
    ``soft_reset`` action listener.
    """

    # ------------------------------------------------------------------
    # Required overrides
    # ------------------------------------------------------------------

    def jive_version(self) -> Tuple[int, int]:
        return (1, 1)

    def default_settings(self) -> Optional[Dict[str, Any]]:
        return {
            "uuid": False,
        }

    def register_applet(self) -> None:
        """Perform early platform initialization.

        This mirrors the Lua ``registerApplet`` which runs at priority 1
        (before most other applets).
        """
        # -- Disable ARP on Windows to avoid OS popups / permission issues
        # (In the Lua original this disables WOL functionality.)
        if "Windows" in (os.environ.get("OS", "")):
            jnt = self._get_jnt()
            if jnt is not None and hasattr(jnt, "setArpEnabled"):
                jnt.setArpEnabled(False)

        settings = self.get_settings()
        if settings is None:
            settings = self.default_settings() or {}
            self._settings = settings

        store = False

        # -- Generate a UUID if we don't have one yet ----------------------
        if not settings.get("uuid"):
            store = True
            parts = []
            for _ in range(16):
                parts.append(f"{random.randint(0, 255):02x}")
            settings["uuid"] = "".join(parts)

        # -- Fix bogus MAC addresses from a legacy bad check ---------------
        mac = settings.get("mac")
        if mac and isinstance(mac, str) and re.search(r"00:04:20", mac):
            settings["mac"] = None
            mac = None

        if not settings.get("mac"):
            mac = self._get_system_mac()
            if mac:
                settings["mac"] = mac
                store = True

        if not settings.get("mac"):
            # Random fallback MAC
            octets = []
            for _ in range(6):
                octets.append(f"{random.randint(0, 255):02x}")
            settings["mac"] = ":".join(octets)
            store = True

        if store:
            log.debug("Mac Address: %s", settings.get("mac"))
            self.store_settings()

        # -- Initialize System with MAC and UUID ---------------------------
        system = self._get_system()
        if system is not None:
            # Set MAC address
            if settings.get("mac"):
                try:
                    if hasattr(system, "set_mac_address"):
                        system.set_mac_address(settings["mac"])
                    elif hasattr(system, "setMacAddress"):
                        system.setMacAddress(settings["mac"])
                except Exception as exc:
                    log.warn("Failed to set MAC address on System: %s", exc)

            # Set UUID
            if settings.get("uuid"):
                try:
                    if hasattr(system, "set_uuid"):
                        system.set_uuid(settings["uuid"])
                    elif hasattr(system, "setUUID"):
                        system.setUUID(settings["uuid"])
                except Exception as exc:
                    log.warn("Failed to set UUID on System: %s", exc)

            # Set platform capabilities
            capabilities = {
                "powerKey": 1,
                "muteKey": 1,
                "alarmKey": 1,
                "wiredNetworking": 1,
                "coreKeys": 1,
                "presetKeys": 1,
            }
            try:
                system.set_capabilities(capabilities)
            except Exception as exc:
                log.error(
                    "register_applet: failed to set_capabilities: %s",
                    exc,
                    exc_info=True,
                )

        # -- Set default screensaver mode for "whenStopped" ----------------
        mgr = self._get_applet_manager()
        if mgr is not None:
            try:
                mgr.add_default_setting("ScreenSavers", "whenStopped", "false:false")
            except (AttributeError, TypeError):
                try:
                    mgr.addDefaultSetting("ScreenSavers", "whenStopped", "false:false")
                except Exception as exc:
                    log.error(
                        "register_applet: failed to set default screensaver setting: %s",
                        exc,
                        exc_info=True,
                    )

        # -- Set the default skin ------------------------------------------
        jive_main = self._get_jive_main()
        if jive_main is not None:
            try:
                jive_main.setDefaultSkin("HDSkin-VGA")
            except AttributeError:
                try:
                    jive_main.set_default_skin("HDSkin-VGA")
                except Exception as exc:
                    log.error(
                        "register_applet: failed to set default skin: %s",
                        exc,
                        exc_info=True,
                    )

        # -- Register soft_reset action listener ---------------------------
        fw = self._get_framework()
        if fw is not None:
            try:
                fw.add_action_listener(
                    "soft_reset",
                    self._soft_reset_action,
                )
            except Exception:
                log.debug(
                    "Could not register soft_reset listener (action may not be registered yet)"
                )

    # ------------------------------------------------------------------
    # Action handlers
    # ------------------------------------------------------------------

    def _soft_reset_action(self, event: Any = None) -> Optional[int]:
        """Handle the ``soft_reset`` action — navigate to home.

        Mirrors the Lua original which simply calls
        ``jiveMain:goHome()``.
        """
        jive_main = self._get_jive_main()
        if jive_main is not None:
            try:
                jive_main.goHome()
            except AttributeError:
                try:
                    jive_main.go_home()
                except Exception as exc:
                    log.warning("_soft_reset_action: failed to navigate home: %s", exc)

        try:
            from jive.ui.constants import EVENT_CONSUME

            return int(EVENT_CONSUME)
        except ImportError:
            return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_system() -> Any:
        """Try to obtain the System *instance* from AppletManager.

        In the Lua original, ``System`` is a module-level singleton.
        In Python, the single ``System`` instance is owned by
        ``AppletManager`` (which receives it from ``JiveMain``).
        """
        try:
            from jive.applet_manager import applet_manager as _mgr

            if _mgr is not None and hasattr(_mgr, "system"):
                sys_inst = _mgr.system
                if sys_inst is not None:
                    return sys_inst
        except (ImportError, AttributeError):
            pass

        # Fallback: try JiveMain directly
        try:
            from jive.jive_main import jive_main as _jm

            if _jm is not None and hasattr(_jm, "_system"):
                return _jm._system
        except (ImportError, AttributeError):
            pass

        return None

    @staticmethod
    def _get_system_mac() -> Optional[str]:
        """Try to get the system MAC address from the System instance."""
        try:
            from jive.applet_manager import applet_manager as _mgr

            if _mgr is not None and hasattr(_mgr, "system"):
                sys_inst = _mgr.system
                if sys_inst is not None:
                    return sys_inst.get_mac_address()  # type: ignore[no-any-return]
        except Exception as exc:
            log.debug("_get_system_mac: failed via applet_manager: %s", exc)

        # Fallback: try JiveMain
        try:
            from jive.jive_main import jive_main as _jm

            if _jm is not None and hasattr(_jm, "_system"):
                return _jm._system.get_mac_address()  # type: ignore[no-any-return]
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
            log.debug("_get_jive_main: jive_main not available: %s", exc)
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

    @staticmethod
    def _get_framework() -> Any:
        """Try to obtain the Framework singleton."""
        try:
            from jive.ui.framework import framework

            return framework
        except (ImportError, AttributeError):
            return None

    @staticmethod
    def _get_jnt() -> Any:
        """Try to obtain the jnt (network thread) singleton."""
        try:
            from jive.jive_main import jive_main as _jm

            if _jm is not None:
                return getattr(_jm, "jnt", None)
        except ImportError as exc:
            log.debug("_get_jnt: jive_main not available: %s", exc)
        return None
