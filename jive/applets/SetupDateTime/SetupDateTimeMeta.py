"""
jive.applets.SetupDateTime.SetupDateTimeMeta — Meta class for SetupDateTime.

Ported from ``share/jive/applets/SetupDateTime/SetupDateTimeMeta.lua`` in the
original jivelite project.

The Meta class:

* Declares version compatibility (1, 1)
* Provides default settings (weekstart, dateformat, shortdateformat, hours)
* Initializes the datetime module from persisted settings during registration
* Registers the ``setupDateTimeSettings`` and ``setDateTimeDefaultFormats``
  services
* Adds a "Date & Time" menu item under ``screenSettings``

The Lua original::

    function defaultSettings(meta)
        return {
            weekstart = "Sunday",
            dateformat = "%a %d %b %Y",
            shortdateformat = "%m.%d.%Y",
            hours = "12",
        }
    end

    function registerApplet(meta)
        initDateTimeObject(meta)
        meta:registerService("setupDateTimeSettings")
        meta:registerService("setDateTimeDefaultFormats")
        jiveMain:addItem(meta:menuItem(
            'appletSetupDateTime', 'screenSettings', "DATETIME_TITLE",
            function(applet, ...) applet:settingsShow(...) end
        ))
    end

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from jive.applet_meta import AppletMeta
from jive.utils.log import logger

__all__ = ["SetupDateTimeMeta"]

log = logger("applet.SetupDateTime")


class SetupDateTimeMeta(AppletMeta):
    """Meta-information for the SetupDateTime applet.

    Initializes the datetime subsystem from persisted settings,
    registers the ``setupDateTimeSettings`` and
    ``setDateTimeDefaultFormats`` services, and adds a "Date & Time"
    menu item under ``screenSettings``.
    """

    # ------------------------------------------------------------------
    # Required overrides
    # ------------------------------------------------------------------

    def jive_version(self) -> Tuple[int, int]:
        return (1, 1)

    def default_settings(self) -> Optional[Dict[str, Any]]:
        """Return default settings — matching the Lua original."""
        return {
            "weekstart": "Sunday",
            "dateformat": "%a %d %b %Y",
            "shortdateformat": "%m.%d.%Y",
            "hours": "12",
        }

    def register_applet(self) -> None:
        """Initialize datetime, register services, and add menu item.

        1. Initialize the datetime module from persisted settings so
           that date/time formatting works correctly from the start.
        2. Register the ``setupDateTimeSettings`` service so other
           applets can query the current date/time settings.
        3. Register the ``setDateTimeDefaultFormats`` service so other
           applets can reset date/time formats to locale-appropriate
           defaults.
        4. Add a "Date & Time" menu item under ``screenSettings``.
        """
        # -- Initialize datetime module from settings -------------------
        self._init_datetime_object()

        # -- Register services ------------------------------------------
        self.register_service("setupDateTimeSettings")
        self.register_service("setDateTimeDefaultFormats")

        # -- Add Date & Time menu item under screenSettings -------------
        jive_main = self._get_jive_main()
        if jive_main is not None:
            jive_main.add_item(
                self.menu_item(
                    id="appletSetupDateTime",
                    node="screenSettings",
                    label="DATETIME_TITLE",
                    closure=lambda applet, menu_item: applet.settingsShow(menu_item),
                )
            )
        else:
            log.debug("register_applet: JiveMain not available — menu item not added")

    # ------------------------------------------------------------------
    # Datetime initialization (mirrors Lua initDateTimeObject)
    # ------------------------------------------------------------------

    def _init_datetime_object(self) -> None:
        """Apply persisted settings to the datetime module.

        Mirrors the Lua ``initDateTimeObject(meta)`` function which
        calls ``setWeekstart``, ``setDateFormat``, ``setShortDateFormat``,
        and ``setHours`` on the datetime utility module.
        """
        settings = self.get_settings()
        if settings is None:
            settings = self.default_settings() or {}

        dt = self._get_datetime_module()
        if dt is None:
            log.debug("datetime module not available — skipping init")
            return

        weekstart = settings.get("weekstart", "Sunday")
        dateformat = settings.get("dateformat", "%a %d %b %Y")
        shortdateformat = settings.get("shortdateformat", "%m.%d.%Y")
        hours = settings.get("hours", "12")

        try:
            if hasattr(dt, "set_weekstart"):
                dt.set_weekstart(weekstart)
            elif hasattr(dt, "setWeekstart"):
                dt.setWeekstart(weekstart)
        except Exception as exc:
            log.warn("Failed to set weekstart: %s", exc)

        try:
            if hasattr(dt, "set_date_format"):
                dt.set_date_format(dateformat)
            elif hasattr(dt, "setDateFormat"):
                dt.setDateFormat(dateformat)
        except Exception as exc:
            log.warn("Failed to set date format: %s", exc)

        try:
            if hasattr(dt, "set_short_date_format"):
                dt.set_short_date_format(shortdateformat)
            elif hasattr(dt, "setShortDateFormat"):
                dt.setShortDateFormat(shortdateformat)
        except Exception as exc:
            log.warn("Failed to set short date format: %s", exc)

        try:
            if hasattr(dt, "set_hours"):
                dt.set_hours(hours)
            elif hasattr(dt, "setHours"):
                dt.setHours(hours)
        except Exception as exc:
            log.warn("Failed to set hours: %s", exc)

        log.debug(
            "Datetime initialized: weekstart=%s, dateformat=%s, "
            "shortdateformat=%s, hours=%s",
            weekstart,
            dateformat,
            shortdateformat,
            hours,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_datetime_module() -> Any:
        """Try to obtain the datetime utility module."""
        try:
            from jive.utils import datetime_utils

            return datetime_utils
        except ImportError:
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
