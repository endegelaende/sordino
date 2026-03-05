"""
jive.applets.SetupDateTime.SetupDateTimeApplet — Date & Time settings applet.

Ported from ``share/jive/applets/SetupDateTime/SetupDateTimeApplet.lua``
in the original jivelite project.

This applet provides settings screens for:

* **Time Format** — 12h or 24h display
* **Date Format** — long date format selection from available formats
* **Short Date Format** — short date format selection
* **Week Start** — Sunday or Monday

Each setting is persisted and applied globally via the datetime utility
module.  Two services are exposed:

* ``setupDateTimeSettings()`` — returns the current settings dict
* ``setDateTimeDefaultFormats()`` — resets formats to locale-appropriate
  defaults based on language and timezone

The Lua original uses ``squeezeos_bsp`` for timezone detection on
embedded hardware; the Python port falls back gracefully when that
module is not available.

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from jive.applet import Applet
from jive.utils.log import logger

__all__ = ["SetupDateTimeApplet"]

log = logger("applet.SetupDateTime")

_DATETIME_TITLE_STYLE = "settingstitle"


class SetupDateTimeApplet(Applet):
    """Date & Time settings applet.

    Provides the settings UI for time format, date format, short date
    format, and week start day.  All changes are applied immediately
    to the global datetime module and persisted to applet settings.
    """

    def __init__(self) -> None:
        super().__init__()

    # ------------------------------------------------------------------
    # Main settings menu (service entry point from Meta menu item)
    # ------------------------------------------------------------------

    def settingsShow(self, menu_item: Any = None) -> Any:
        """Show the Date & Time settings menu.

        Mirrors the Lua ``settingsShow(self, menuItem)`` method.
        Creates a Window with a SimpleMenu containing entries for
        Time Format, Date Format, Short Date Format, and Week Start.
        """
        Window = self._get_window_class()
        SimpleMenu = self._get_simple_menu_class()

        if Window is None or SimpleMenu is None:
            log.warn("UI classes not available — cannot show settings")
            return None

        title = (
            menu_item.get("text", self.string("DATETIME_TITLE"))
            if isinstance(menu_item, dict)
            else self.string("DATETIME_TITLE")
        )
        window = Window("text_list", title, _DATETIME_TITLE_STYLE)

        menu = SimpleMenu(
            "menu",
            [
                {
                    "text": self.string("DATETIME_TIMEFORMAT"),
                    "sound": "WINDOWSHOW",
                    "callback": lambda event=None, mi=None: self.timeSetting(menu_item),
                },
                {
                    "text": self.string("DATETIME_DATEFORMAT"),
                    "sound": "WINDOWSHOW",
                    "callback": lambda event=None, mi=None: self.dateFormatSetting(menu_item),
                },
                {
                    "text": self.string("DATETIME_SHORTDATEFORMAT"),
                    "sound": "WINDOWSHOW",
                    "callback": lambda event=None, mi=None: self.shortDateFormatSetting(menu_item),
                },
                {
                    "text": self.string("DATETIME_WEEKSTART"),
                    "sound": "WINDOWSHOW",
                    "callback": lambda event=None, mi=None: self.weekstartSetting(menu_item),
                },
            ],
        )

        window.add_widget(menu)

        # Store settings when the window is popped
        EVENT_WINDOW_POP = self._get_event_window_pop()
        if EVENT_WINDOW_POP is not None:
            window.add_listener(EVENT_WINDOW_POP, lambda *_a, **_kw: self.store_settings())

        self.tie_and_show_window(window)
        return window

    # ------------------------------------------------------------------
    # Time Format setting (12h / 24h)
    # ------------------------------------------------------------------

    def timeSetting(self, menu_item: Any = None) -> Any:
        """Show the time format selection screen (12h / 24h).

        Mirrors the Lua ``timeSetting(self, menuItem)`` method.
        """
        Window = self._get_window_class()
        SimpleMenu = self._get_simple_menu_class()
        RadioButton = self._get_radio_button_class()
        RadioGroup = self._get_radio_group_class()

        if Window is None or SimpleMenu is None or RadioButton is None or RadioGroup is None:
            log.warn("UI classes not available — cannot show time setting")
            return None

        title = (
            menu_item.get("text", self.string("DATETIME_TIMEFORMAT"))
            if isinstance(menu_item, dict)
            else self.string("DATETIME_TIMEFORMAT")
        )
        window = Window("text_list", title, _DATETIME_TITLE_STYLE)
        group = RadioGroup()

        settings = self.get_settings() or {}
        current = settings.get("hours", "12")

        menu = SimpleMenu(
            "menu",
            [
                {
                    "text": self.string("DATETIME_TIMEFORMAT_12H"),
                    "style": "item_choice",
                    "check": RadioButton(
                        "radio",
                        group,
                        lambda *_args: self.setHours("12"),
                        current == "12",
                    ),
                },
                {
                    "text": self.string("DATETIME_TIMEFORMAT_24H"),
                    "style": "item_choice",
                    "check": RadioButton(
                        "radio",
                        group,
                        lambda *_args: self.setHours("24"),
                        current == "24",
                    ),
                },
            ],
        )

        window.add_widget(menu)
        self.tie_and_show_window(window)
        return window

    # ------------------------------------------------------------------
    # Date Format setting
    # ------------------------------------------------------------------

    def dateFormatSetting(self, menu_item: Any = None) -> Any:
        """Show the date format selection screen.

        Lists all available long date formats from the datetime module,
        displaying each as the current date formatted with that format.
        """
        Window = self._get_window_class()
        SimpleMenu = self._get_simple_menu_class()
        RadioButton = self._get_radio_button_class()
        RadioGroup = self._get_radio_group_class()

        if Window is None or SimpleMenu is None or RadioButton is None or RadioGroup is None:
            log.warn("UI classes not available — cannot show date format setting")
            return None

        title = (
            menu_item.get("text", self.string("DATETIME_DATEFORMAT"))
            if isinstance(menu_item, dict)
            else self.string("DATETIME_DATEFORMAT")
        )
        window = Window("text_list", title, _DATETIME_TITLE_STYLE)
        group = RadioGroup()

        settings = self.get_settings() or {}
        current = settings.get("dateformat", "%a %d %b %Y")

        dt = self._get_datetime_module()

        menu = SimpleMenu("menu")

        formats = self._get_all_date_formats(dt)
        for fmt in formats:
            display_text = self._get_current_date(dt, fmt)
            menu.add_item(
                {
                    "text": display_text,
                    "style": "item_choice",
                    "check": RadioButton(
                        "radio",
                        group,
                        self._make_date_format_callback(fmt),
                        current == fmt,
                    ),
                }
            )

        window.add_widget(menu)
        self.tie_and_show_window(window)
        return window

    def _make_date_format_callback(self, fmt: str) -> Any:
        """Create a callback for selecting a date format."""

        def _cb(*_args: Any) -> None:
            self.setDateFormat(fmt)

        return _cb

    # ------------------------------------------------------------------
    # Short Date Format setting
    # ------------------------------------------------------------------

    def shortDateFormatSetting(self, menu_item: Any = None) -> Any:
        """Show the short date format selection screen.

        Lists all available short date formats from the datetime module.
        """
        Window = self._get_window_class()
        SimpleMenu = self._get_simple_menu_class()
        RadioButton = self._get_radio_button_class()
        RadioGroup = self._get_radio_group_class()

        if Window is None or SimpleMenu is None or RadioButton is None or RadioGroup is None:
            log.warn("UI classes not available — cannot show short date format setting")
            return None

        title = (
            menu_item.get("text", self.string("DATETIME_SHORTDATEFORMAT"))
            if isinstance(menu_item, dict)
            else self.string("DATETIME_SHORTDATEFORMAT")
        )
        window = Window("text_list", title, _DATETIME_TITLE_STYLE)
        group = RadioGroup()

        settings = self.get_settings() or {}
        current = settings.get("shortdateformat", "%m.%d.%Y")

        dt = self._get_datetime_module()

        menu = SimpleMenu("menu")

        formats = self._get_all_short_date_formats(dt)
        for fmt in formats:
            display_text = self._get_current_date(dt, fmt)
            menu.add_item(
                {
                    "text": display_text,
                    "style": "item_choice",
                    "check": RadioButton(
                        "radio",
                        group,
                        self._make_short_date_format_callback(fmt),
                        current == fmt,
                    ),
                }
            )

        window.add_widget(menu)
        self.tie_and_show_window(window)
        return window

    def _make_short_date_format_callback(self, fmt: str) -> Any:
        """Create a callback for selecting a short date format."""

        def _cb(*_args: Any) -> None:
            self.setShortDateFormat(fmt)

        return _cb

    # ------------------------------------------------------------------
    # Week Start setting (Sunday / Monday)
    # ------------------------------------------------------------------

    def weekstartSetting(self, menu_item: Any = None) -> Any:
        """Show the week start selection screen (Sunday / Monday).

        Mirrors the Lua ``weekstartSetting(self, menuItem)`` method.
        """
        Window = self._get_window_class()
        SimpleMenu = self._get_simple_menu_class()
        RadioButton = self._get_radio_button_class()
        RadioGroup = self._get_radio_group_class()

        if Window is None or SimpleMenu is None or RadioButton is None or RadioGroup is None:
            log.warn("UI classes not available — cannot show weekstart setting")
            return None

        title = (
            menu_item.get("text", self.string("DATETIME_WEEKSTART"))
            if isinstance(menu_item, dict)
            else self.string("DATETIME_WEEKSTART")
        )
        window = Window("text_list", title, _DATETIME_TITLE_STYLE)
        group = RadioGroup()

        settings = self.get_settings() or {}
        current = settings.get("weekstart", "Sunday")

        menu = SimpleMenu(
            "menu",
            [
                {
                    "text": self.string("DATETIME_SUNDAY"),
                    "style": "item_choice",
                    "check": RadioButton(
                        "radio",
                        group,
                        lambda *_args: self.setWeekStart("Sunday"),
                        current == "Sunday",
                    ),
                },
                {
                    "text": self.string("DATETIME_MONDAY"),
                    "style": "item_choice",
                    "check": RadioButton(
                        "radio",
                        group,
                        lambda *_args: self.setWeekStart("Monday"),
                        current == "Monday",
                    ),
                },
            ],
        )

        window.add_widget(menu)
        self.tie_and_show_window(window)
        return window

    # ------------------------------------------------------------------
    # Setting mutators (apply to datetime module + persist)
    # ------------------------------------------------------------------

    def setDateFormat(self, fmt: str) -> None:
        """Set the long date format and persist."""
        settings = self.get_settings()
        if settings is not None:
            settings["dateformat"] = fmt

        dt = self._get_datetime_module()
        if dt is not None:
            if hasattr(dt, "set_date_format"):
                dt.set_date_format(fmt)
            elif hasattr(dt, "setDateFormat"):
                dt.setDateFormat(fmt)

    def setShortDateFormat(self, fmt: str) -> None:
        """Set the short date format and persist."""
        settings = self.get_settings()
        if settings is not None:
            settings["shortdateformat"] = fmt

        dt = self._get_datetime_module()
        if dt is not None:
            if hasattr(dt, "set_short_date_format"):
                dt.set_short_date_format(fmt)
            elif hasattr(dt, "setShortDateFormat"):
                dt.setShortDateFormat(fmt)

    def setWeekStart(self, day: str) -> None:
        """Set the week start day and persist."""
        settings = self.get_settings()
        if settings is not None:
            settings["weekstart"] = day

        dt = self._get_datetime_module()
        if dt is not None:
            if hasattr(dt, "set_weekstart"):
                dt.set_weekstart(day)
            elif hasattr(dt, "setWeekstart"):
                dt.setWeekstart(day)

    def setHours(self, hours: str) -> None:
        """Set the time format (12/24) and persist."""
        settings = self.get_settings()
        if settings is not None:
            settings["hours"] = hours

        dt = self._get_datetime_module()
        if dt is not None:
            if hasattr(dt, "set_hours"):
                dt.set_hours(hours)
            elif hasattr(dt, "setHours"):
                dt.setHours(hours)

    # ------------------------------------------------------------------
    # Service callbacks
    # ------------------------------------------------------------------

    def setupDateTimeSettings(self) -> Optional[Dict[str, Any]]:
        """Service: return the current date/time settings dict.

        Called by other applets via::

            appletManager.callService("setupDateTimeSettings")
        """
        return self.get_settings()

    def setDateTimeDefaultFormats(self) -> None:
        """Service: reset date/time formats to locale-appropriate defaults.

        In the Lua original, this uses ``squeezeos.getTimezone()`` and
        the current locale to determine the best defaults.  The Python
        port attempts the same logic but falls back gracefully.
        """
        tz = self._get_timezone_string()
        lang = self._get_current_locale()

        log.debug(
            "Using language (%s) and timezone (%s) to determine date/time default formats",
            lang,
            tz,
        )

        # Default to 12h display for select English-speaking countries
        # (US, Australia, New Zealand)
        if (
            lang == "EN"
            and tz
            and (tz.startswith("America") or tz.startswith("Australia") or tz.startswith("Pacific"))
        ):
            self.setHours("12")
        else:
            self.setHours("24")

        # Set long date format from localized string, falling back to default
        long_default = str(self.string("DATETIME_LONGDATEFORMAT_DEFAULT"))
        if not long_default or long_default == "DATETIME_LONGDATEFORMAT_DEFAULT":
            long_default = "%a %d %b %Y"
        self.setDateFormat(long_default)

        # Set short date format from localized string, falling back to default
        short_default = str(self.string("DATETIME_SHORTDATEFORMAT_DEFAULT"))
        if not short_default or short_default == "DATETIME_SHORTDATEFORMAT_DEFAULT":
            short_default = "%m.%d.%Y"
        self.setShortDateFormat(short_default)

        # US customers use Monday as week start in the Lua original
        if lang == "EN" and tz and tz.startswith("America"):
            self.setWeekStart("Monday")
        else:
            self.setWeekStart("Sunday")

        self.store_settings()

    # ------------------------------------------------------------------
    # Lua-compatible camelCase aliases
    # ------------------------------------------------------------------

    settings_show = settingsShow
    time_setting = timeSetting
    date_format_setting = dateFormatSetting
    short_date_format_setting = shortDateFormatSetting
    weekstart_setting = weekstartSetting
    set_date_format = setDateFormat
    set_short_date_format = setShortDateFormat
    set_week_start = setWeekStart
    set_hours = setHours
    setup_date_time_settings = setupDateTimeSettings
    set_date_time_default_formats = setDateTimeDefaultFormats

    # ------------------------------------------------------------------
    # Datetime module helpers
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
    def _get_all_date_formats(dt: Any) -> List[str]:
        """Get all available long date formats from the datetime module."""
        if dt is None:
            return ["%a %d %b %Y", "%A, %d %B %Y", "%d %B %Y", "%B %d, %Y"]

        if hasattr(dt, "get_all_date_formats"):
            result = dt.get_all_date_formats()
        elif hasattr(dt, "getAllDateFormats"):
            result = dt.getAllDateFormats()
        else:
            return ["%a %d %b %Y", "%A, %d %B %Y", "%d %B %Y", "%B %d, %Y"]

        # The Lua original returns a table — we expect a dict or list
        if isinstance(result, dict):
            return list(result.values())
        if isinstance(result, (list, tuple)):
            return list(result)
        return ["%a %d %b %Y"]

    @staticmethod
    def _get_all_short_date_formats(dt: Any) -> List[str]:
        """Get all available short date formats from the datetime module."""
        if dt is None:
            return ["%m.%d.%Y", "%d.%m.%Y", "%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y"]

        if hasattr(dt, "get_all_short_date_formats"):
            result = dt.get_all_short_date_formats()
        elif hasattr(dt, "getAllShortDateFormats"):
            result = dt.getAllShortDateFormats()
        else:
            return ["%m.%d.%Y", "%d.%m.%Y", "%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y"]

        if isinstance(result, dict):
            return list(result.values())
        if isinstance(result, (list, tuple)):
            return list(result)
        return ["%m.%d.%Y"]

    @staticmethod
    def _get_current_date(dt: Any, fmt: str) -> str:
        """Format the current date using the given format string."""
        if dt is not None:
            if hasattr(dt, "get_current_date"):
                try:
                    return str(dt.get_current_date(fmt))
                except Exception as exc:
                    log.debug("get_current_date(%s) failed: %s", fmt, exc)
            if hasattr(dt, "getCurrentDate"):
                try:
                    return str(dt.getCurrentDate(fmt))
                except Exception as exc:
                    log.debug("getCurrentDate(%s) failed: %s", fmt, exc)

        # Fallback: use Python's strftime
        import datetime as _dt

        try:
            return _dt.datetime.now().strftime(fmt)
        except Exception:
            return fmt

    @staticmethod
    def _get_timezone_string() -> str:
        """Try to get the current timezone string.

        In the Lua original, ``squeezeos.getTimezone()`` is used.
        Here we try the datetime module, then fall back to an
        empty string.
        """
        try:
            from jive.utils import datetime_utils as dt

            if hasattr(dt, "get_timezone"):
                tz = dt.get_timezone()
                if tz:
                    return str(tz)
        except ImportError as exc:
            log.debug("datetime_utils import failed for timezone: %s", exc)

        # Fallback: try Python's time module
        try:
            import time

            return time.tzname[0] if time.tzname else ""
        except Exception:
            return ""

    @staticmethod
    def _get_current_locale() -> str:
        """Try to get the current locale code (e.g. "EN", "DE")."""
        try:
            from jive.utils.locale import get_locale_instance

            loc = get_locale_instance()
            if hasattr(loc, "get_locale"):
                result = loc.get_locale()
                if result:
                    return str(result)
            if hasattr(loc, "getLocale"):
                result = loc.getLocale()
                if result:
                    return str(result)
        except (ImportError, Exception) as exc:
            log.debug("locale instance not available: %s", exc)
        return "EN"

    # ------------------------------------------------------------------
    # UI class helpers (lazy imports to avoid circular deps)
    # ------------------------------------------------------------------

    @staticmethod
    def _get_window_class() -> Any:
        """Try to obtain the Window class."""
        try:
            from jive.ui.window import Window

            return Window
        except ImportError:
            return None

    @staticmethod
    def _get_simple_menu_class() -> Any:
        """Try to obtain the SimpleMenu class."""
        try:
            from jive.ui.simplemenu import SimpleMenu

            return SimpleMenu
        except ImportError as exc:
            log.debug("simplemenu import failed, trying alternative: %s", exc)
        try:
            from jive.ui.simple_menu import SimpleMenu as _SM  # type: ignore[import-not-found]

            return _SM
        except ImportError:
            return None

    @staticmethod
    def _get_radio_button_class() -> Any:
        """Try to obtain the RadioButton class."""
        try:
            from jive.ui.radio import RadioButton

            return RadioButton
        except ImportError:
            return None

    @staticmethod
    def _get_radio_group_class() -> Any:
        """Try to obtain the RadioGroup class."""
        try:
            from jive.ui.radio import RadioGroup

            return RadioGroup
        except ImportError:
            return None

    @staticmethod
    def _get_event_window_pop() -> Any:
        """Try to obtain the EVENT_WINDOW_POP constant."""
        try:
            from jive.ui.constants import EVENT_WINDOW_POP

            return EVENT_WINDOW_POP
        except ImportError:
            return None
