"""
jive.utils.datetime_utils — Date/time formatting and timezone utilities.

Ported from share/jive/jive/utils/datetime.lua

Provides date and time related functionality for the Jivelite application:
- Date format management (long and short formats)
- Time format management (12h / 24h)
- Timezone handling (simple offset-based)
- Week start day configuration
- Seconds-from-midnight (SFM) conversion utilities
- Current time/date formatting with locale-aware day/month names

The original Lua module uses global state for settings (date format,
time format, timezone, weekstart). We replicate this with module-level
state, matching the Lua API where functions take ``self`` as first
argument (which in Python becomes a module-level function that ignores
or uses a sentinel ``self`` parameter for API compatibility).

Usage::

    from jive.utils.datetime_utils import (
        set_hours, get_hours,
        set_date_format, get_date_format,
        get_current_time, get_current_date,
        seconds_from_midnight, time_from_sfm,
        time_table_from_sfm,
        set_weekstart, get_weekstart,
        set_timezone, get_timezone,
        get_all_date_formats,
        is_clock_set,
    )

    set_hours("24")
    print(get_current_time())  # e.g. "14:35"

    set_hours("12")
    print(get_current_time())  # e.g. " 2:35PM"

    sfm = seconds_from_midnight("1430")  # 52200
    print(time_from_sfm(sfm, "24"))      # "14:30"

Copyright 2010 Logitech. All Rights Reserved.
This file is licensed under BSD. Please see the LICENSE file for details.
"""

from __future__ import annotations

import math
import re
import time as _time
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from jive.utils.log import logger

log = logger("jivelite.datetime")

# ─── Global State (matching Lua module-level variables) ───────────────────────

_weekstart: str = "Sunday"
_date_format: str = "%a, %B %d %Y"
_short_date_format: str = "%d.%m.%Y"
_hours: str = "12"
_timezone: str = "GMT"
_time_set: bool = False

# ─── Date Formats ────────────────────────────────────────────────────────────

DATE_FORMATS: List[str] = [
    "%a %d %b %Y",
    "%a %d. %b %Y",
    "%a, %b %d, '%y",
    "%a, %d %b, %Y",
    "%a, %d. %b, %Y",
    "%A %d %B %Y",
    "%A %d. %B %Y",
    "%A, %B %d, %Y",
    "%A, %B. %d, %Y",
    "%d %B %Y",
    "%d. %B %Y",
    "%B %d, %Y",
    "%Y-%m-%d",
    "%Y-%m-%d %A",
    "%Y-%m-%d (%a)",
    "%Y/%m/%d",
    "%Y/%m/%d %A",
    "%Y/%m/%d (%a)",
    "%d-%m-%Y",
    "%d-%m-%y",
    "%d.%m.%Y",
    "%d.%m.%y",
    "%d/%m/%Y",
    "%d/%m/%y",
    "%m-%d-%Y",
    "%m-%d-%y",
    "%m.%d.%Y",
    "%m.%d.%y",
    "%m/%d/%Y",
    "%m/%d/%y",
]

SHORT_DATE_FORMATS: List[str] = [
    "%m.%d.%Y",
    "%d.%m.%Y",
]

# ─── Timezone Definitions ────────────────────────────────────────────────────

TIMEZONES: Dict[str, Dict[str, Any]] = {
    "GMT": {
        "offset": 0,
        "text": "GMT",
    },
    "CET": {
        "offset": 1,
        "text": "Berlin, Zurich",
    },
}

# ─── Localized Day/Month Names ───────────────────────────────────────────────
# The original Lua code loads these from a strings.txt file via the locale
# module.  We provide English defaults here so that datetime works
# standalone without requiring the full locale infrastructure.
# When the locale module is available, get_current_date() will attempt
# to use it for localized names.

_DAY_NAMES: Dict[int, str] = {
    1: "Sunday",
    2: "Monday",
    3: "Tuesday",
    4: "Wednesday",
    5: "Thursday",
    6: "Friday",
    7: "Saturday",
}

_DAY_SHORT_NAMES: Dict[int, str] = {
    1: "Sun",
    2: "Mon",
    3: "Tue",
    4: "Wed",
    5: "Thu",
    6: "Fri",
    7: "Sat",
}

_MONTH_NAMES: Dict[int, str] = {
    1: "January",
    2: "February",
    3: "March",
    4: "April",
    5: "May",
    6: "June",
    7: "July",
    8: "August",
    9: "September",
    10: "October",
    11: "November",
    12: "December",
}

_MONTH_SHORT_NAMES: Dict[int, str] = {
    1: "Jan",
    2: "Feb",
    3: "Mar",
    4: "Apr",
    5: "May",
    6: "Jun",
    7: "Jul",
    8: "Aug",
    9: "Sep",
    10: "Oct",
    11: "Nov",
    12: "Dec",
}


# ─── Date Format Functions ────────────────────────────────────────────────────


def get_all_date_formats(self: Any = None) -> List[str]:
    """
    Return all available date formats.

    Returns a copy of the ``DATE_FORMATS`` list.

    The *self* parameter exists for Lua API compatibility and is ignored.

    Returns:
        List of strftime format strings.

    Examples:
        >>> fmts = get_all_date_formats()
        >>> "%Y-%m-%d" in fmts
        True
        >>> len(fmts) > 10
        True
    """
    return list(DATE_FORMATS)


def get_all_short_date_formats(self: Any = None) -> List[str]:
    """
    Return all available short date formats.

    Returns:
        List of strftime short-format strings.

    Examples:
        >>> fmts = get_all_short_date_formats()
        >>> "%d.%m.%Y" in fmts
        True
    """
    return list(SHORT_DATE_FORMATS)


def set_date_format(self_or_fmt: Any = None, dateformat: Optional[str] = None) -> None:
    """
    Set the default date format.

    Can be called as ``set_date_format(fmt)`` or
    ``set_date_format(self, fmt)`` for Lua API compatibility.

    Args:
        self_or_fmt: Either the format string (when called without self)
                     or a self placeholder (when called with self).
        dateformat: The format string (when self_or_fmt is self).

    Examples:
        >>> set_date_format("%Y-%m-%d")
        >>> get_date_format() == "%Y-%m-%d"
        True
    """
    global _date_format
    fmt = dateformat if dateformat is not None else self_or_fmt
    if fmt is not None:
        _date_format = fmt


def get_date_format(self: Any = None) -> str:
    """
    Return the current default date format.

    Returns:
        The current strftime date format string.

    Examples:
        >>> isinstance(get_date_format(), str)
        True
    """
    return _date_format


def set_short_date_format(
    self_or_fmt: Any = None, dateformat: Optional[str] = None
) -> None:
    """
    Set the default short date format.

    Args:
        self_or_fmt: Format string or self placeholder.
        dateformat: Format string when called with self.

    Examples:
        >>> set_short_date_format("%m.%d.%Y")
        >>> get_short_date_format() == "%m.%d.%Y"
        True
    """
    global _short_date_format
    fmt = dateformat if dateformat is not None else self_or_fmt
    if fmt is not None:
        _short_date_format = fmt


def get_short_date_format(self: Any = None) -> str:
    """
    Return the current default short date format.

    Returns:
        The current strftime short date format string.

    Examples:
        >>> isinstance(get_short_date_format(), str)
        True
    """
    return _short_date_format


# ─── Weekstart ────────────────────────────────────────────────────────────────


def set_weekstart(self_or_day: Any = None, day: Optional[str] = None) -> None:
    """
    Set the first day of the week.

    Valid values are ``"Sunday"`` and ``"Monday"``.

    Args:
        self_or_day: Day string or self placeholder.
        day: Day string when called with self.

    Examples:
        >>> set_weekstart("Monday")
        >>> get_weekstart()
        'Monday'
        >>> set_weekstart("Sunday")
        >>> get_weekstart()
        'Sunday'
    """
    global _weekstart
    d = day if day is not None else self_or_day

    if d is None:
        log.error("setWeekstart() - day is nil")
        return

    if d in ("Sunday", "Monday"):
        _weekstart = d
    else:
        log.error("Invalid Weekstart: ", str(d))


def get_weekstart(self: Any = None) -> str:
    """
    Return the current first day of the week.

    Returns:
        ``"Sunday"`` or ``"Monday"``.

    Examples:
        >>> get_weekstart() in ("Sunday", "Monday")
        True
    """
    return _weekstart


# ─── Hours (12h / 24h) ───────────────────────────────────────────────────────


def set_hours(
    self_or_hours: Any = None, hours: Optional[Union[str, int]] = None
) -> None:
    """
    Set the hour display mode (12h or 24h).

    Accepts string ``"12"``/``"24"`` or integer ``12``/``24``.

    Args:
        self_or_hours: Hours value or self placeholder.
        hours: Hours value when called with self.

    Examples:
        >>> set_hours("24")
        >>> get_hours()
        '24'
        >>> set_hours(12)
        >>> get_hours()
        '12'
    """
    global _hours
    h = hours if hours is not None else self_or_hours

    if isinstance(h, str):
        if h in ("12", "24"):
            _hours = h
        else:
            log.error("datetime:setHours() - hours is not 12 or 24")
    elif isinstance(h, int):
        if h == 12:
            _hours = "12"
        elif h == 24:
            _hours = "24"
        else:
            log.error("datetime:setHours() - hours is not 12 or 24")
    else:
        log.error("Invalid Parameter for datetime:setHours()")


def get_hours(self: Any = None) -> str:
    """
    Return the current hour display mode.

    Returns:
        ``"12"`` or ``"24"``.

    Examples:
        >>> get_hours() in ("12", "24")
        True
    """
    return _hours


# ─── Timezone ─────────────────────────────────────────────────────────────────


def get_timezone(
    self_or_tz: Any = None, timezone: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """
    Look up a timezone by name.

    Args:
        self_or_tz: Timezone name or self placeholder.
        timezone: Timezone name when called with self.

    Returns:
        A dict with ``"offset"`` (hours from GMT) and ``"text"``
        (description), or ``None`` if not found.

    Examples:
        >>> tz = get_timezone("GMT")
        >>> tz is not None
        True
        >>> tz["offset"]
        0
        >>> get_timezone("INVALID") is None
        True
    """
    tz = timezone if timezone is not None else self_or_tz
    return TIMEZONES.get(tz)  # type: ignore[arg-type]


def get_all_timezones(self: Any = None) -> Dict[str, Dict[str, Any]]:
    """
    Return all available timezone definitions.

    Returns:
        A dict mapping timezone name → ``{"offset": int, "text": str}``.

    Examples:
        >>> tzs = get_all_timezones()
        >>> "GMT" in tzs
        True
    """
    return dict(TIMEZONES)


def set_timezone(self_or_tz: Any = None, timezone: Optional[str] = None) -> bool:
    """
    Set the current timezone.

    The timezone must exist in the ``TIMEZONES`` table.

    Args:
        self_or_tz: Timezone name or self placeholder.
        timezone: Timezone name when called with self.

    Returns:
        ``True`` if the timezone was set, ``False`` if invalid.

    Examples:
        >>> set_timezone("CET")
        True
        >>> set_timezone("INVALID")
        False
    """
    global _timezone
    tz = timezone if timezone is not None else self_or_tz

    test_tz = get_timezone(tz)
    if test_tz is None:
        log.error("Set Invalid TimeZone")
        return False
    else:
        _timezone = tz  # type: ignore[assignment]
        return True


# ─── Seconds From Midnight (SFM) ─────────────────────────────────────────────


def seconds_from_midnight(
    self_or_hhmm: Any = None, hhmm: Optional[Union[str, int]] = None
) -> int:
    """
    Convert an HHMM time string to seconds from midnight.

    Supports 24h format (``"1430"`` → 52200) and AM/PM suffixes
    (``"0230p"`` → 52200, ``"1230a"`` → 1800).

    The parsing extracts pairs of two digits for hours and minutes,
    then checks for ``'a'`` or ``'p'`` suffix for AM/PM conversion.

    Args:
        self_or_hhmm: HHMM string/int or self placeholder.
        hhmm: HHMM string/int when called with self.

    Returns:
        Number of seconds from midnight, or 0 if the input is invalid
        (hours > 23 or minutes > 59).

    Examples:
        >>> seconds_from_midnight("0000")
        0
        >>> seconds_from_midnight("0100")
        3600
        >>> seconds_from_midnight("1430")
        52200
        >>> seconds_from_midnight("2359")
        86340
        >>> seconds_from_midnight("0230p")
        52200
        >>> seconds_from_midnight("1200a")
        0
        >>> seconds_from_midnight("1200p")
        43200
        >>> seconds_from_midnight("2500")
        0
    """
    raw = hhmm if hhmm is not None else self_or_hhmm
    raw_str = str(raw)

    # Extract pairs of two digits
    elements = re.findall(r"(\d\d)", raw_str)
    if len(elements) < 2:
        return 0

    hh = int(elements[0])
    mm = int(elements[1])

    # Convert AM/PM to 24h
    if "p" in raw_str.lower():
        if hh != 12:
            hh += 12
    elif "a" in raw_str.lower():
        if hh == 12:
            hh = 0

    # Validate
    if hh > 23 or mm > 59:
        return 0

    return hh * 3600 + mm * 60


def time_table_from_sfm(
    self_or_sfm: Any = None,
    sfm_or_fmt: Any = None,
    fmt: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Convert seconds-from-midnight to a time table.

    Returns a dict with ``"hour"``, ``"minute"``, and ``"ampm"`` keys.
    In 24h format, ``"ampm"`` is ``None``. In 12h format, ``"ampm"``
    is ``"AM"`` or ``"pm"`` (matching the Lua original's casing).

    Args:
        self_or_sfm: SFM value or self placeholder.
        sfm_or_fmt: SFM value or format string (depends on calling convention).
        fmt: Format string (``"12"`` or ``"24"``). Defaults to ``"24"``.

    Returns:
        Dict with ``hour``, ``minute``, ``ampm`` keys.

    Examples:
        >>> time_table_from_sfm(0, "24")
        {'hour': 0, 'minute': 0, 'ampm': None}
        >>> time_table_from_sfm(3600, "24")
        {'hour': 1, 'minute': 0, 'ampm': None}
        >>> time_table_from_sfm(52200, "24")
        {'hour': 14, 'minute': 30, 'ampm': None}
        >>> time_table_from_sfm(52200, "12")
        {'hour': 2, 'minute': 30, 'ampm': 'pm'}
        >>> time_table_from_sfm(3600, "12")
        {'hour': 1, 'minute': 0, 'ampm': 'AM'}
        >>> time_table_from_sfm(-1, "24")
        {'hour': 0, 'minute': 0, 'ampm': None}
        >>> time_table_from_sfm(86400, "12")
        {'hour': 12, 'minute': 0, 'ampm': 'PM'}
    """
    # Resolve the self/sfm/fmt argument overloading
    sfm_val, format_val = _resolve_sfm_args(self_or_sfm, sfm_or_fmt, fmt)

    sfm_int = int(sfm_val)

    if format_val == "24":
        if sfm_int >= 86400 or sfm_int < 0:
            return {"hour": 0, "minute": 0, "ampm": None}

        hours = int(math.floor(sfm_int / 3600))
        minutes = int(math.floor((sfm_int % 3600) / 60))
        return {"hour": hours, "minute": minutes, "ampm": None}
    else:
        # 12h format
        if sfm_int >= 86400 or sfm_int < 0:
            return {"hour": 12, "minute": 0, "ampm": "PM"}

        if sfm_int < 43200:
            ampm = "AM"
        else:
            ampm = "pm"

        hours = int(math.floor(sfm_int / 3600))
        minutes = int(math.floor((sfm_int % 3600) / 60))

        if hours < 1:
            hours = 12
        elif hours > 12:
            hours -= 12

        return {"hour": hours, "minute": minutes, "ampm": ampm}


def time_from_sfm(
    self_or_sfm: Any = None,
    sfm_or_fmt: Any = None,
    fmt: Optional[str] = None,
) -> str:
    """
    Convert seconds-from-midnight to a formatted time string.

    In 24h format: ``"HH:MM"`` (e.g. ``"14:30"``).
    In 12h format: ``"HH:MMa"`` or ``"HH:MMp"`` (e.g. ``"02:30p"``).

    Args:
        self_or_sfm: SFM value or self placeholder.
        sfm_or_fmt: SFM value or format string.
        fmt: Format string (``"12"`` or ``"24"``). Defaults to ``"24"``.

    Returns:
        Formatted time string.

    Examples:
        >>> time_from_sfm(0, "24")
        '00:00'
        >>> time_from_sfm(3600, "24")
        '01:00'
        >>> time_from_sfm(52200, "24")
        '14:30'
        >>> time_from_sfm(52200, "12")
        '02:30p'
        >>> time_from_sfm(3600, "12")
        '01:00a'
        >>> time_from_sfm(-1, "24")
        '00:00'
        >>> time_from_sfm(86400, "24")
        '00:00'
        >>> time_from_sfm(-1, "12")
        '12:00a'
        >>> time_from_sfm(86400, "12")
        '12:00a'
    """
    sfm_val, format_val = _resolve_sfm_args(self_or_sfm, sfm_or_fmt, fmt)

    sfm_int = int(sfm_val)

    if format_val == "24":
        if sfm_int >= 86400 or sfm_int < 0:
            return "00:00"

        hours = int(math.floor(sfm_int / 3600))
        minutes = int(math.floor((sfm_int % 3600) / 60))
        return f"{hours:02d}:{minutes:02d}"
    else:
        # 12h format
        if sfm_int >= 86400 or sfm_int < 0:
            return "12:00a"

        if sfm_int < 43200:
            ampm = "a"
        else:
            ampm = "p"

        hours = int(math.floor(sfm_int / 3600))
        minutes = int(math.floor((sfm_int % 3600) / 60))

        if hours < 1:
            hours = 12
        elif hours > 12:
            hours -= 12

        return f"{hours:02d}:{minutes:02d}{ampm}"


# ─── Clock Status ─────────────────────────────────────────────────────────────


def is_clock_set(self: Any = None) -> bool:
    """
    Check whether the system clock appears to be set correctly.

    Returns ``False`` if the current year is before 2010 (indicating
    the clock has not been set, e.g. on an embedded device without
    RTC battery).

    Returns:
        ``True`` if the clock appears to be set.

    Examples:
        >>> # On any modern system the clock should be set
        >>> is_clock_set()
        True
    """
    now = datetime.now()
    return now.year >= 2010


# ─── Current Time / Date ─────────────────────────────────────────────────────


def get_current_time(self_or_fmt: Any = None, fmt: Optional[str] = None) -> str:
    """
    Return the current time as a formatted string.

    If the system clock is not set (year < 2010), returns an empty string.

    With no format argument, uses the global hours setting:
    - 12h → ``"%I:%M%p"`` (e.g. ``" 2:35PM"``)
    - 24h → ``"%H:%M"`` (e.g. ``"14:35"``)

    Leading zeros in the hour are replaced with a space (matching Lua).

    Args:
        self_or_fmt: Format string or self placeholder.
        fmt: Format string when called with self.

    Returns:
        Formatted time string, or ``""`` if clock is not set.

    Examples:
        >>> t = get_current_time()
        >>> isinstance(t, str)
        True
    """
    global _time_set
    format_str = (
        fmt
        if fmt is not None
        else (self_or_fmt if isinstance(self_or_fmt, str) else None)
    )

    # If time has not been confirmed set, check the clock
    if not _time_set:
        if not is_clock_set():
            return ""
        _time_set = True

    now = datetime.now()

    if format_str:
        result = now.strftime(format_str)
    elif _hours == "12":
        result = now.strftime("%I:%M%p")
    else:
        result = now.strftime("%H:%M")

    # Replace leading 0 with space (matching Lua: string.gsub(str, "^0", " ", 1))
    if result and result[0] == "0":
        result = " " + result[1:]

    return result


def get_current_date(self_or_fmt: Any = None, fmt: Optional[str] = None) -> str:
    """
    Return the current date as a formatted string.

    Uses the global date format by default. Localizes day and month
    names using the built-in English name tables (the Lua original
    loads these from a locale strings file).

    Handles the strftime-like ``%A`` (full day), ``%a`` (short day),
    ``%B`` (full month), ``%b`` (short month) codes with our own
    name tables before passing to ``strftime`` for the remaining codes.

    Args:
        self_or_fmt: Format string or self placeholder.
        fmt: Format string when called with self.

    Returns:
        Formatted date string.

    Examples:
        >>> d = get_current_date()
        >>> isinstance(d, str)
        True
        >>> len(d) > 0
        True
    """
    format_str = (
        fmt
        if fmt is not None
        else (self_or_fmt if isinstance(self_or_fmt, str) else None)
    )

    if format_str is None:
        format_str = _date_format

    now = datetime.now()

    # Lua's os.date("*t").wday: 1=Sunday, 2=Monday, ...
    # Python's weekday(): 0=Monday, ... 6=Sunday
    # Convert Python weekday to Lua wday
    py_weekday = now.weekday()  # 0=Mon, 6=Sun
    lua_wday = (py_weekday + 2) % 7  # Shift: Mon=2, Tue=3, ... Sun=1
    if lua_wday == 0:
        lua_wday = 7  # Shouldn't happen with this formula, but guard

    month = now.month  # 1-12

    # Replace day/month name placeholders with our localized versions
    # We do this BEFORE strftime so that strftime handles the remaining
    # codes (%d, %m, %Y, etc.) correctly.
    # Order matters: %A before %a, %B before %b (longer match first)
    result = format_str
    result = result.replace("%A", _DAY_NAMES.get(lua_wday, "?"))
    result = result.replace("%a", _DAY_SHORT_NAMES.get(lua_wday, "?"))
    result = result.replace("%B", _MONTH_NAMES.get(month, "?"))
    result = result.replace("%b", _MONTH_SHORT_NAMES.get(month, "?"))

    # Now let strftime handle the remaining format codes
    result = now.strftime(result)

    return result


# ─── State Reset (for testing) ───────────────────────────────────────────────


def reset_defaults() -> None:
    """
    Reset all module-level state to defaults.

    This is primarily useful in tests to ensure a clean state between
    test cases. Not part of the original Lua API.

    Examples:
        >>> set_hours("24")
        >>> set_weekstart("Monday")
        >>> reset_defaults()
        >>> get_hours()
        '12'
        >>> get_weekstart()
        'Sunday'
    """
    global _weekstart, _date_format, _short_date_format
    global _hours, _timezone, _time_set
    _weekstart = "Sunday"
    _date_format = "%a, %B %d %Y"
    _short_date_format = "%d.%m.%Y"
    _hours = "12"
    _timezone = "GMT"
    _time_set = False


# ─── Internal Helpers ─────────────────────────────────────────────────────────


def _resolve_sfm_args(
    self_or_sfm: Any,
    sfm_or_fmt: Any,
    fmt: Optional[str],
) -> tuple[int, str]:
    """
    Resolve the overloaded (self, sfm, format) argument pattern.

    The Lua API is ``func(self, sfm, format)`` but in Python we want
    to support both ``func(sfm)`` and ``func(sfm, format)`` calling
    conventions. This helper figures out which argument is the SFM
    value and which is the format string.

    Returns:
        A tuple of (sfm_value: int, format_str: str).
    """
    if fmt is not None:
        # Called as func(self, sfm, fmt) — self_or_sfm is self, sfm_or_fmt is sfm
        return int(sfm_or_fmt), str(fmt)
    elif sfm_or_fmt is not None:
        # Could be func(sfm, fmt) or func(self, sfm)
        # Heuristic: if sfm_or_fmt is "12" or "24", it's a format string
        if isinstance(sfm_or_fmt, str) and sfm_or_fmt in ("12", "24"):
            return int(self_or_sfm), sfm_or_fmt
        else:
            # sfm_or_fmt is the sfm value, no format specified
            return int(self_or_sfm if self_or_sfm is not None else 0), "24"
    else:
        # Only self_or_sfm provided — it's the sfm value
        return int(self_or_sfm if self_or_sfm is not None else 0), "24"
