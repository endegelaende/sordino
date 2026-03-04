"""
jive.applets.Quit.QuitMeta — Meta class for the Quit applet.

Ported from ``share/jive/applets/Quit/QuitMeta.lua`` in the original jivelite
project.

The Quit applet has no separate ``QuitApplet.py`` — all logic lives here
in ``configure_applet()``, which adds a "Quit" item to the home menu.
When selected, it disconnects the current player and calls
``Framework.quit()``.

The original Lua code skips loading on Squeeze Player control instances
(``jivelite-sp`` or ``--sp-applets``).  The Python port mirrors this
check using ``sys.argv``.

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

import sys
from typing import Any, Optional, Tuple

from jive.applet_meta import AppletMeta
from jive.utils.log import logger

__all__ = ["QuitMeta"]

log = logger("applet.Quit")


class QuitMeta(AppletMeta):
    """Meta-information for the Quit applet.

    Adds a "Quit" menu item to the home menu during the configure phase.
    The menu callback disconnects the player and shuts down the framework.
    """

    # ------------------------------------------------------------------
    # Required overrides
    # ------------------------------------------------------------------

    def jive_version(self) -> Tuple[int, int]:
        return (1, 1)

    def register_applet(self) -> None:
        """Nothing to register — configuration is deferred to
        :meth:`configure_applet`."""

    # ------------------------------------------------------------------
    # Cross-applet configuration
    # ------------------------------------------------------------------

    def configure_applet(self) -> None:
        """Add the Quit item to the home menu.

        Mirrors the Lua original: checks ``sys.argv`` for
        ``jivelite-sp`` or ``--sp-applets`` and skips loading on
        Squeeze Player control instances.
        """
        # Check whether we should skip on SP instances
        load = True
        argv0 = sys.argv[0] if sys.argv else ""
        if "jivelite-sp" in argv0:
            load = False
        for arg in sys.argv[1:]:
            if arg == "--sp-applets":
                load = False

        if not load:
            log.info("Quit applet skipped (SP mode)")
            return

        jive_main = self._get_jive_main()
        if jive_main is None:
            log.warn("configure_applet: JiveMain not available")
            return

        def _quit_callback(event: Any = None, menu_item: Any = None) -> None:
            """Disconnect from player/server and quit."""
            # Disconnect the current player (best-effort)
            mgr = self._get_applet_manager()
            if mgr is not None:
                try:
                    mgr.call_service("disconnectPlayer")
                except Exception as exc:
                    log.error("disconnectPlayer failed: %s", exc, exc_info=True)

            # Shut down the framework
            fw = self._get_framework()
            if fw is not None:
                fw.quit()

        jive_main.add_item(
            {
                "id": "appletQuit",
                "iconStyle": "hm_quit",
                "node": "home",
                "text": self.string("QUIT"),
                "callback": _quit_callback,
                "weight": 1010,
            }
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_jive_main() -> Any:
        """Try to obtain the JiveMain singleton."""
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
