"""
jive.applets.LogSettings.LogSettingsMeta — Meta class for LogSettings.

Ported from ``share/jive/applets/LogSettings/LogSettingsMeta.lua`` in the
original jivelite project.

The Meta class:

* Declares version compatibility (1, 1)
* Adds a "Debug Log" menu item under the ``advancedSettings`` node
  that opens the log category settings UI.

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

from typing import Any, Tuple

from jive.applet_meta import AppletMeta
from jive.utils.log import logger

__all__ = ["LogSettingsMeta"]

log = logger("applet.LogSettings")


class LogSettingsMeta(AppletMeta):
    """Meta-information for the LogSettings applet.

    Adds a "Debug Log" (``DEBUG_LOG``) menu item under the
    ``advancedSettings`` node.  When selected, the full
    :class:`LogSettingsApplet` is loaded on demand and its
    ``logSettings()`` method is called.
    """

    # ------------------------------------------------------------------
    # Required overrides
    # ------------------------------------------------------------------

    def jive_version(self) -> Tuple[int, int]:
        return (1, 1)

    def register_applet(self) -> None:
        """Add the Debug Log menu item under advancedSettings.

        Mirrors the Lua original::

            jiveMain:addItem(meta:menuItem(
                'appletLogSettings', 'advancedSettings', 'DEBUG_LOG',
                function(applet, ...) applet:logSettings(...) end
            ))
        """
        jive_main = self._get_jive_main()
        if jive_main is None:
            log.warn("register_applet: JiveMain not available")
            return

        jive_main.add_item(
            self.menu_item(
                id="appletLogSettings",
                node="advancedSettings",
                label="DEBUG_LOG",
                closure=lambda applet, menu_item: applet.logSettings(menu_item),
            )
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
            log.debug("_get_jive_main: jive_main not available: %s", exc)
        try:
            import jive.jive_main as _mod

            return getattr(_mod, "jive_main", None)
        except ImportError:
            return None
