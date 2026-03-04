"""
jive.applets.SetupWelcome.SetupWelcomeMeta — Meta class for SetupWelcome.

Ported from ``share/jive/applets/SetupWelcome/SetupWelcomeMeta.lua`` in the
original jivelite project.

The Meta class:

* Declares version compatibility (1, 1)
* Provides default settings (``setupDone: False``)
* Registers the ``setupFirstStartup`` service
* In ``configure_applet()``, checks if setup has been completed; if not,
  calls the ``setupFirstStartup`` service to launch the first-run wizard.

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from jive.applet_meta import AppletMeta
from jive.utils.log import logger

__all__ = ["SetupWelcomeMeta"]

log = logger("applet.SetupWelcome")


class SetupWelcomeMeta(AppletMeta):
    """Meta-information for the SetupWelcome applet.

    Registers the ``setupFirstStartup`` service and triggers the
    first-run setup wizard if setup has not yet been completed.

    The Lua original::

        function defaultSettings(meta)
            return { setupDone = false }
        end

        function registerApplet(meta)
            meta:registerService("setupFirstStartup")
        end

        function configureApplet(meta)
            if not meta:getSettings().setupDone then
                appletManager:callService("setupFirstStartup")
            end
        end
    """

    # ------------------------------------------------------------------
    # Required overrides
    # ------------------------------------------------------------------

    def jive_version(self) -> Tuple[int, int]:
        return (1, 1)

    def default_settings(self) -> Optional[Dict[str, Any]]:
        """Return default settings — setup has not been done yet."""
        return {
            "setupDone": False,
        }

    def register_applet(self) -> None:
        """Register the ``setupFirstStartup`` service.

        This service is provided by :class:`SetupWelcomeApplet` and
        will be resolved on demand when called via the AppletManager.

        Mirrors the Lua original::

            meta:registerService("setupFirstStartup")
        """
        self.register_service("setupFirstStartup")

    # ------------------------------------------------------------------
    # Cross-applet configuration
    # ------------------------------------------------------------------

    def configure_applet(self) -> None:
        """Trigger first-startup setup if it hasn't been completed.

        Called after all applets have been registered.  Checks the
        ``setupDone`` flag in settings — if ``False``, schedules the
        ``setupFirstStartup`` service to run on the *next* event-loop
        tick via a one-shot Timer.

        In the Lua original the call happens synchronously inside
        ``configureApplet``, but the windows that get pushed are only
        processed once the event loop runs.  In the Python port, calling
        the service synchronously during ``__init__`` causes a hang
        because ``Window.show()`` dispatches ``EVENT_WINDOW_INACTIVE``
        to the language-selection window whose listener calls
        ``styleChanged()`` — all before the event loop is running.

        Deferring via a 0 ms one-shot Timer avoids the problem while
        preserving the original first-run behaviour once the event loop
        starts.
        """
        settings = self.get_settings()
        if settings is None:
            settings = self.default_settings() or {}
            self._settings = settings

        setup_done = settings.get("setupDone", False)

        if not setup_done:
            # Only schedule the wizard if the UI framework is initialised.
            # In headless / test mode there is no display, so the wizard
            # would block or fail.
            fw = self._get_framework()
            if fw is None or not getattr(fw, "_initialised", False):
                log.debug(
                    "First startup detected but Framework not initialised "
                    "(headless mode) — skipping setup wizard"
                )
                return

            mgr = self._get_applet_manager()
            if mgr is None:
                log.warn("configure_applet: AppletManager not available")
                return

            # Guard: only launch if the language-selection service that
            # the wizard depends on is actually registered.
            if not getattr(mgr, "has_service", lambda _: False)(
                "setupShowSetupLanguage"
            ):
                log.debug(
                    "First startup detected but setupShowSetupLanguage "
                    "service not available — deferring setup wizard"
                )
                return

            # Schedule the wizard to run on the first event-loop tick
            # rather than synchronously during init.
            log.info("First startup — scheduling setup wizard (deferred)")
            try:
                from jive.ui.timer import Timer

                def _deferred_setup() -> None:
                    try:
                        mgr.call_service("setupFirstStartup")
                    except Exception as exc:
                        log.warn("Failed to call setupFirstStartup: %s", exc)

                _timer = Timer(0, _deferred_setup, once=True)
                _timer.start()
            except ImportError:
                # Timer not available — try synchronous as last resort
                log.info(
                    "Timer not available — calling setupFirstStartup synchronously"
                )
                try:
                    mgr.call_service("setupFirstStartup")
                except Exception as exc:
                    log.warn("Failed to call setupFirstStartup: %s", exc)
        else:
            log.debug("Setup already completed — skipping wizard")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

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
