"""
jive.applets.Clock.ClockApplet — Clock screensaver applet.

Ported from ``share/jive/applets/Clock/ClockApplet.lua`` (~3,302 LOC)
in the original jivelite project.

This applet provides multiple clock screensaver modes:

* **Analog** — Traditional analog clock with hour/minute hands rendered
  via rotation on a canvas.
* **Digital** — Large digit display with day/date bar, optional AM/PM,
  and drop-shadow effects. Comes in three variants: normal, black
  background, and transparent background.
* **DotMatrix** — Dot-matrix style digit display for time and date,
  using pre-rendered digit images.
* **WordClock** — English word-based clock ("IT IS NEARLY FIVE PAST
  THREE") with word highlight images on a grid, plus an analog
  fallback for QVGA skins.

Each mode is implemented as a separate inner class (``AnalogClock``,
``DigitalClock``, ``DotMatrixClock``, ``WordClockDisplay``) that
inherits from a common ``ClockBase`` base class.

The applet entry points are the ``open*`` methods called by the
ScreenSavers service:

* ``openAnalogClock()``
* ``openDetailedClock()`` — Digital
* ``openDetailedClockBlack()`` — Digital (Black)
* ``openDetailedClockTransparent()`` — Digital (Transparent)
* ``openStyledClock()`` — Dot Matrix
* ``openWordClock()`` — Word Clock

Skin detection helpers (``_is_joggler_skin``, ``_is_wqvga_skin``,
``_is_hd_skin``) determine which image assets and layout parameters
to use for each screen resolution.

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

import math
import os
import re
import time as _time
from datetime import datetime as _datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

from jive.applet import Applet
from jive.utils.log import logger

__all__ = ["ClockApplet"]

log = logger("applet.Clock")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_JOGGLER_SKIN_ALARM_X = 748
_JOGGLER_SKIN_ALARM_Y = 11

_FONTPATH = "fonts/"
_FONT_NAME = "FreeSans"
_BOLD_PREFIX = "Bold"

# Day-of-month to ordinal word mapping (1-indexed)
_DATE_WORDS: List[str] = [
    "",  # index 0 unused
    "First",
    "Second",
    "Third",
    "Fourth",
    "Fifth",
    "Sixth",
    "Seventh",
    "Eighth",
    "Ninth",
    "Tenth",
    "Eleventh",
    "Twelfth",
    "Thirteenth",
    "Fourteenth",
    "Fifteenth",
    "Sixteenth",
    "Seventeenth",
    "Eighteenth",
    "Nineteenth",
    "Twentieth",
    "Twenty First",
    "Twenty Second",
    "Twenty Third",
    "Twenty Fourth",
    "Twenty Fifth",
    "Twenty Sixth",
    "Twenty Seventh",
    "Twenty Eighth",
    "Twenty Ninth",
    "Thirtieth",
    "Thirty First",
]


# ═══════════════════════════════════════════════════════════════════════════
# Skin helpers
# ═══════════════════════════════════════════════════════════════════════════


def _is_joggler_skin(skin_name: str) -> bool:
    """Return *True* if *skin_name* is a Joggler or PiGrid skin."""
    return bool(re.search(r"PiGridSkin|JogglerSkin", skin_name))


def _is_wqvga_skin(skin_name: str) -> bool:
    """Return *True* if *skin_name* is a WQVGA skin."""
    return skin_name in ("WQVGAsmallSkin", "WQVGAlargeSkin")


def _is_hd_skin(skin_name: str) -> bool:
    """Return *True* if *skin_name* is an HD skin."""
    return bool(re.search(r"HDSkin|HDGridSkin", skin_name))


def _imgpath(skin_name: str) -> str:
    """Return the base image path for the given skin.

    Normalizes skin families so they share asset directories:
    * Joggler / PiGrid → ``JogglerSkin``
    * WQVGA variants → ``WQVGAsmallSkin``
    * HD variants → ``HDSkin``
    """
    if _is_joggler_skin(skin_name):
        skin_name = "JogglerSkin"
    elif _is_wqvga_skin(skin_name):
        skin_name = "WQVGAsmallSkin"
    elif _is_hd_skin(skin_name):
        skin_name = "HDSkin"
    return "applets/" + skin_name + "/images/"


# ═══════════════════════════════════════════════════════════════════════════
# Style inheritance helper (mirrors Lua _uses)
# ═══════════════════════════════════════════════════════════════════════════


def _uses(
    parent: Optional[Dict[str, Any]], overrides: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Create a new style dict that inherits from *parent* with *overrides*.

    Recursively merges nested dicts (like the Lua ``_uses`` helper).
    """
    if parent is None:
        parent = {}
    style: Dict[str, Any] = {}
    style.update(parent)
    if overrides:
        for k, v in overrides.items():
            if isinstance(v, dict) and isinstance(style.get(k), dict):
                style[k] = _uses(style[k], v)
            else:
                style[k] = v
    return style


# ═══════════════════════════════════════════════════════════════════════════
# Time helper — local time as a dict matching Lua os.date("*t")
# ═══════════════════════════════════════════════════════════════════════════


def _local_time() -> Dict[str, int]:
    """Return current local time as a dict with keys matching Lua's
    ``os.date("*t")``: ``hour``, ``min``, ``sec``, ``year``, ``month``,
    ``day``, ``wday`` (0=Sunday .. 6=Saturday).
    """
    now = _datetime.now()
    # Python weekday: Monday=0 .. Sunday=6 → Lua wday: Sunday=1 .. Saturday=7
    # We use 0-based Sunday=0 convention (matching Lua wday-1 in the Lua code)
    py_wd = now.weekday()  # Mon=0 .. Sun=6
    lua_wday = (py_wd + 1) % 7  # Sun=0, Mon=1 .. Sat=6
    return {
        "hour": now.hour,
        "min": now.minute,
        "sec": now.second,
        "year": now.year,
        "month": now.month,
        "day": now.day,
        "wday": lua_wday,
    }


def _get_ampm_string() -> str:
    """Return 'AM' or 'PM' for the current local time."""
    return _time.strftime("%p")


def _get_date_as_words(day: int) -> str:
    """Return the date as words, e.g. ``'Wednesday the Twenty Fifth of March'``.

    Mirrors the Lua ``WordClock:getDateAsWords(day)`` function.
    """
    now = _datetime.now()
    day_name = now.strftime("%A")
    month_name = now.strftime("%B")
    ordinal = _DATE_WORDS[day] if 1 <= day <= 31 else str(day)
    return f"{day_name} the {ordinal} of {month_name}"


# ═══════════════════════════════════════════════════════════════════════════
# Word clock flag computation
# ═══════════════════════════════════════════════════════════════════════════


def _get_word_flags(time_now: Dict[str, int]) -> Dict[str, bool]:
    """Compute which words to highlight on the word clock.

    This is a direct port of the Lua ``WordClock:getwordflags(timenow)``
    function which computes boolean flags for each word position on the
    word-clock grid.

    Parameters
    ----------
    time_now:
        Dict with at least ``hour`` (0-23) and ``min`` (0-59).

    Returns
    -------
    Dict with boolean flags for each word/phrase.
    """
    flags: Dict[str, bool] = {}
    minute = time_now["min"]
    hour = time_now["hour"]

    # --- Five-minute divisions ---
    # Lua uses 1-indexed table; we use 0-indexed list
    def _set_five_0() -> None:
        flags["zero"] = True

    def _set_five_1() -> None:
        flags["five"] = True
        flags["minutes"] = True

    def _set_five_2() -> None:
        flags["ten"] = True
        flags["minutes"] = True

    def _set_five_3() -> None:
        flags["aquarter"] = True

    def _set_five_4() -> None:
        flags["twenty"] = True
        flags["minutes"] = True

    def _set_five_5() -> None:
        flags["twenty"] = True
        flags["five"] = True
        flags["minutes"] = True

    def _set_five_6() -> None:
        flags["half"] = True

    fifths = [
        _set_five_0,  # 0
        _set_five_1,  # 1
        _set_five_2,  # 2
        _set_five_3,  # 3
        _set_five_4,  # 4
        _set_five_5,  # 5
        _set_five_6,  # 6
        _set_five_5,  # 7 (mirror of 5)
        _set_five_4,  # 8 (mirror of 4)
        _set_five_3,  # 9 (mirror of 3)
        _set_five_2,  # 10 (mirror of 2)
        _set_five_1,  # 11 (mirror of 1)
        _set_five_0,  # 12 (mirror of 0)
    ]

    # --- IS, HAS, NEARLY, JUST GONE ---
    remainder = minute % 5
    if remainder == 0:
        flags["is"] = True
        flags["exactly"] = True
    elif remainder in (1, 2):
        flags["has"] = True
        flags["justgone"] = True
    elif remainder in (3, 4):
        flags["is"] = True
        flags["nearly"] = True

    # --- Five-minute division index ---
    # Lua: tmp = math.floor(timenow.min / 5) + 2;
    #      if exactly or justgone then tmp = tmp - 1 end
    #      fifths[tmp]()  -- Lua 1-indexed
    tmp = (minute // 5) + 1  # Python 0-indexed equivalent of Lua +2 then index
    if flags.get("exactly") or flags.get("justgone"):
        tmp -= 1
    if 0 <= tmp < len(fifths):
        fifths[tmp]()

    # --- TO, PAST, O'CLOCK ---
    if (0 <= minute <= 2) or minute in (58, 59):
        flags["oclock"] = True
    elif 3 <= minute <= 32:
        flags["past"] = True
    elif 33 <= minute <= 57:
        flags["to"] = True

    # --- AM / PM ---
    if hour <= 11:
        flags["am"] = True
    else:
        flags["pm"] = True

    # --- Hour word ---
    hour_setters = [
        lambda: flags.update({"htwelve": True}),  # 0 (12 o'clock)
        lambda: flags.update({"hone": True}),  # 1
        lambda: flags.update({"htwo": True}),  # 2
        lambda: flags.update({"hthree": True}),  # 3
        lambda: flags.update({"hfour": True}),  # 4
        lambda: flags.update({"hfive": True}),  # 5
        lambda: flags.update({"hsix": True}),  # 6
        lambda: flags.update({"hseven": True}),  # 7
        lambda: flags.update({"height": True}),  # 8
        lambda: flags.update({"hnine": True}),  # 9
        lambda: flags.update({"hten": True}),  # 10
        lambda: flags.update({"heleven": True}),  # 11
        lambda: flags.update({"htwelve": True}),  # 12
    ]

    hour12 = hour % 12  # 0-based index into hour_setters

    if 0 <= minute <= 32:
        hour_setters[hour12]()
    elif 33 <= minute <= 59:
        idx = hour12 + 1
        if idx < len(hour_setters):
            hour_setters[idx]()

    return flags


def _time_as_text(flags: Dict[str, bool]) -> str:
    """Generate human-readable time text from word flags.

    Mirrors the Lua ``WordClock:timeastext(flags)`` function.
    """
    parts = ["IT"]

    if flags.get("is"):
        parts.append("IS")
    if flags.get("has"):
        parts.append("HAS")
    if flags.get("justgone"):
        parts.append("JUST GONE")
    if flags.get("nearly"):
        parts.append("NEARLY")

    # Minute words
    if flags.get("ten"):
        parts.append("TEN")
    elif flags.get("aquarter"):
        parts.append("A QUARTER")
    elif flags.get("twenty"):
        parts.append("TWENTY")

    if flags.get("five"):
        parts.append("FIVE")
    if flags.get("half"):
        parts.append("HALF")
    if flags.get("past"):
        parts.append("PAST")
    if flags.get("to"):
        parts.append("TO")

    # Hour words
    if flags.get("hone"):
        parts.append("ONE")
    elif flags.get("htwo"):
        parts.append("TWO")
    elif flags.get("hthree"):
        parts.append("THREE")
    elif flags.get("hfour"):
        parts.append("FOUR")
    elif flags.get("hfive"):
        parts.append("FIVE")
    elif flags.get("hsix"):
        parts.append("SIX")
    elif flags.get("hseven"):
        parts.append("SEVEN")
    elif flags.get("height"):
        parts.append("EIGHT")
    elif flags.get("hnine"):
        parts.append("NINE")
    elif flags.get("hten"):
        parts.append("TEN")
    elif flags.get("heleven"):
        parts.append("ELEVEN")
    elif flags.get("htwelve"):
        parts.append("TWELVE")

    if flags.get("oclock"):
        parts.append("O'CLOCK")

    if flags.get("am"):
        parts.append("AM")
    elif flags.get("pm"):
        parts.append("PM")

    return " ".join(parts)


# ═══════════════════════════════════════════════════════════════════════════
# Clock base class
# ═══════════════════════════════════════════════════════════════════════════


class ClockBase:
    """Base class for all clock display modes.

    Mirrors the Lua ``Clock`` class that serves as a superclass for
    ``DotMatrix``, ``Digital``, ``Analog``, and ``WordClock``.
    """

    def __init__(
        self,
        skin: Optional[Dict[str, Any]] = None,
        window_style: str = "Clock",
    ) -> None:
        log.debug("Init ClockBase")
        self.skin = skin or {}
        self.skin_name: str = ""
        self.old_skin_name: Optional[str] = None
        self.imgpath: str = ""

        # Screen dimensions
        self.screen_width: int = 800
        self.screen_height: int = 480
        fw = self._get_framework()
        if fw is not None:
            try:
                self.screen_width, self.screen_height = fw.get_screen_size()
            except Exception as exc:
                log.debug("ClockBase.__init__: failed to get screen size: %s", exc)

        # Player / alarm state
        self.player: Any = None
        self.alarm_set: Optional[bool] = None
        player_cls = self._get_player_class()
        if player_cls is not None:
            try:
                self.player = player_cls.get_local_player()
            except Exception as exc:
                log.debug("ClockBase.__init__: failed to get local player: %s", exc)
        if self.player is not None:
            try:
                self.alarm_set = self.player.get_alarm_state()
            except Exception as exc:
                log.debug("ClockBase.__init__: failed to get alarm state: %s", exc)
                self.alarm_set = None

        # Window
        self.window: Any = None
        Window = self._get_window_class()
        if Window is not None:
            self.window = Window(window_style)
            if skin:
                try:
                    self.window.set_skin(skin)
                    self.window.re_skin()
                except Exception as exc:
                    log.warning("ClockBase.__init__: failed to apply skin to window: %s", exc)
            try:
                self.window.set_show_framework_widgets(False)
            except Exception as exc:
                log.warning("ClockBase.__init__: failed to hide framework widgets: %s", exc)

            # Motion listener to dismiss screensaver
            try:
                from jive.ui.constants import EVENT_CONSUME, EVENT_MOTION

                def _on_motion(event: Any) -> int:
                    if self.window is not None:
                        self.window.hide()
                    return int(EVENT_CONSUME)

                self.window.add_listener(int(EVENT_MOTION), _on_motion)
            except Exception as exc:
                log.warning("ClockBase.__init__: failed to add motion listener: %s", exc)

            # Register window as a screensaver
            mgr = self._get_applet_manager()
            if mgr is not None:
                ss = mgr.get_applet_instance("ScreenSavers")
                if ss is not None and hasattr(ss, "screensaverWindow"):
                    ss.screensaverWindow(self.window, None, None, None, "Clock")

        # Clock format string (used by _tick to detect changes)
        self.clock_format: str = "%H:%M"
        self.clock_format_hour: str = "%H"

    # ------------------------------------------------------------------
    # Notification
    # ------------------------------------------------------------------

    def notify_playerAlarmState(self, player: Any, alarm_set: Any) -> None:
        """Called when alarm state changes on the local player."""
        if player is not None:
            try:
                if not player.is_local():
                    return
            except Exception as exc:
                log.error("notify_playerAlarmState: failed to check player.is_local(): %s", exc, exc_info=True)
        try:
            self.alarm_set = player.get_alarm_state() if player else None
        except Exception as exc:
            log.error("notify_playerAlarmState: failed to get alarm state: %s", exc, exc_info=True)
            self.alarm_set = None
        log.debug("Setting alarm_set to %s", self.alarm_set)
        self.Draw()

    # ------------------------------------------------------------------
    # Time formatting helpers
    # ------------------------------------------------------------------

    def _get_hour(self, t: Dict[str, int]) -> str:
        """Return the hour as a zero-padded 2-digit string.

        Respects ``self.clock_format_hour``: ``'%I'`` for 12-hour,
        ``'%H'`` for 24-hour.
        """
        hour = t["hour"]
        if self.clock_format_hour == "%I":
            hour = hour % 12
            if hour == 0:
                hour = 12
        return self._pad(hour)

    @staticmethod
    def _pad(number: int) -> str:
        """Zero-pad *number* to 2 digits."""
        if number < 10:
            return "0" + str(number)
        return str(number)

    @staticmethod
    def _get_minute(t: Dict[str, int]) -> str:
        """Return the minute as a zero-padded 2-digit string."""
        return ClockBase._pad(t["min"])

    def _get_date(self, t: Dict[str, int]) -> str:
        """Return the date as an 8-char string (MMDDYYYY or DDMMYYYY).

        Depends on ``self.clock_format_date``.
        """
        fmt = getattr(self, "clock_format_date", "%m%d%Y")
        if fmt == "%d%m%Y":
            return self._pad(t["day"]) + self._pad(t["month"]) + str(t["year"])
        else:
            return self._pad(t["month"]) + self._pad(t["day"]) + str(t["year"])

    # ------------------------------------------------------------------
    # Abstract
    # ------------------------------------------------------------------

    def Draw(self) -> None:
        """Redraw the clock display. Override in subclasses."""

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_framework() -> Any:
        try:
            from jive.ui.framework import framework

            return framework
        except (ImportError, AttributeError):
            return None

    @staticmethod
    def _get_window_class() -> Any:
        try:
            from jive.ui.window import Window

            return Window
        except ImportError:
            return None

    @staticmethod
    def _get_player_class() -> Any:
        try:
            from jive.slim.player import Player

            return Player
        except ImportError:
            return None

    @staticmethod
    def _get_applet_manager() -> Any:
        try:
            from jive.applet_manager import applet_manager

            return applet_manager
        except (ImportError, AttributeError):
            return None

    @staticmethod
    def _get_jive_main() -> Any:
        try:
            from jive.jive_main import jive_main

            return jive_main
        except (ImportError, AttributeError) as exc:
            log.debug("ClockBase._get_jive_main: direct import failed: %s", exc)
        try:
            import jive.jive_main as _mod

            return getattr(_mod, "jive_main", None)
        except ImportError:
            return None

    @staticmethod
    def _get_surface_class() -> Any:
        try:
            from jive.ui.surface import Surface

            return Surface
        except ImportError:
            return None

    @staticmethod
    def _get_tile_class() -> Any:
        try:
            from jive.ui.tile import Tile

            return Tile
        except ImportError:
            return None

    @staticmethod
    def _get_font_class() -> Any:
        try:
            from jive.ui.font import Font

            return Font
        except ImportError:
            return None

    @staticmethod
    def _get_icon_class() -> Any:
        try:
            from jive.ui.icon import Icon

            return Icon
        except ImportError:
            return None

    @staticmethod
    def _get_label_class() -> Any:
        try:
            from jive.ui.label import Label

            return Label
        except ImportError:
            return None

    @staticmethod
    def _get_group_class() -> Any:
        try:
            from jive.ui.group import Group

            return Group
        except ImportError:
            return None

    @staticmethod
    def _get_canvas_class() -> Any:
        try:
            from jive.ui.canvas import Canvas

            return Canvas
        except ImportError:
            return None

    @staticmethod
    def _load_font(font_size: int, bold: bool = False) -> Any:
        """Load a font at the given size."""
        Font = ClockBase._get_font_class()
        if Font is None:
            return None
        suffix = _BOLD_PREFIX if bold else ""
        path = f"{_FONTPATH}{_FONT_NAME}{suffix}.ttf"
        try:
            return Font.load(path, font_size)
        except Exception as exc:
            log.debug("ClockBase._load_font: failed to load font %s at size %d: %s", path, font_size, exc)
            return None

    def _load_image(self, filename: str) -> Any:
        """Load an image from this clock's imgpath."""
        Surface = self._get_surface_class()
        if Surface is None:
            return None
        try:
            return Surface.load_image(self.imgpath + filename)
        except Exception as exc:
            log.warn("Failed to load image %s: %s", self.imgpath + filename, exc)
            return None


# ═══════════════════════════════════════════════════════════════════════════
# Dot Matrix Clock
# ═══════════════════════════════════════════════════════════════════════════


class DotMatrixClock(ClockBase):
    """Dot-matrix style clock display.

    Shows time in large dot-matrix digits, date in smaller digits,
    alarm icon, and colon dots.

    Port of Lua ``DotMatrix`` class.
    """

    # Class-level cached skin
    _cached_skin: Optional[Dict[str, Any]] = None
    _cached_skin_name: Optional[str] = None

    def __init__(self, ampm: bool, short_date_format: str) -> None:
        log.debug("Init DotMatrixClock")

        skin_name = self._get_selected_skin()

        if (
            DotMatrixClock._cached_skin is None
            or skin_name != DotMatrixClock._cached_skin_name
        ):
            log.debug("Fetching Dot Matrix clock skin")
            DotMatrixClock._cached_skin_name = skin_name
            DotMatrixClock._cached_skin = self._get_dot_matrix_skin(skin_name)

        skin = DotMatrixClock._cached_skin or {}
        super().__init__(skin, "Clock")

        self.skin_name = skin_name
        self.imgpath = _imgpath(skin_name)
        self.ampm = ampm
        self.show_ampm = ampm

        # Clock format
        if ampm:
            self.clock_format_hour = "%I"
        else:
            self.clock_format_hour = "%H"
        self.clock_format_minute = "%M"

        # Date format based on shortDateFormat
        month_spot = short_date_format.find("m")
        day_spot = short_date_format.find("d")
        if month_spot < 0:
            month_spot = 999
        if day_spot < 0:
            day_spot = 999
        if day_spot < month_spot:
            self.clock_format_date = "%d%m%Y"
        else:
            self.clock_format_date = "%m%d%Y"

        self.clock_format = self.clock_format_hour + ":" + self.clock_format_minute

        # Widget groups for time digits
        self._digit_groups: Dict[str, str] = {}  # group_key -> current style
        Icon = self._get_icon_class()
        Group = self._get_group_class()

        if Icon and Group and self.window:
            # Time digit groups
            for key in ("h1", "h2", "m1", "m2"):
                g = Group(key, {"digit": Icon("icon_dotMatrixDigit0")})
                setattr(self, key, g)
                self.window.add_widget(g)
                self._digit_groups[key] = "icon_dotMatrixDigit0"

            # Dots
            dots = Group("dots", {"dots": Icon("icon_dotMatrixDots")})
            self.window.add_widget(dots)

            # Alarm
            alarm_style = "icon_alarm_on" if self.alarm_set else "icon_alarm_off"
            self.alarm = Group("alarm", {"alarm": Icon(alarm_style)})
            self.window.add_widget(self.alarm)

            # Date digit groups
            for key in ("M1", "M2", "D1", "D2", "Y1", "Y2", "Y3", "Y4"):
                g = Group(key, {"digit": Icon("icon_dotMatrixDate0")})
                setattr(self, key, g)
                self.window.add_widget(g)
                self._digit_groups[key] = "icon_dotMatrixDate0"

            # Date dot separators
            dot1 = Group("dot1", {"dot": Icon("icon_dotMatrixDateDot")})
            dot2 = Group("dot2", {"dot": Icon("icon_dotMatrixDateDot")})
            self.window.add_widget(dot1)
            self.window.add_widget(dot2)

    def Draw(self) -> None:
        """Redraw the dot matrix clock with current time/date."""
        t = _local_time()
        the_hour = self._get_hour(t)
        the_minute = self._get_minute(t)
        the_date = self._get_date(t)

        # Draw hour digits
        self._draw_clock_digit(the_hour[0], "h1")
        self._draw_clock_digit(the_hour[1], "h2")

        # Draw minute digits
        self._draw_clock_digit(the_minute[0], "m1")
        self._draw_clock_digit(the_minute[1], "m2")

        # Draw date digits (8-char date string: MMDDYYYY or DDMMYYYY)
        if len(the_date) >= 8:
            self._draw_date_digit(the_date[0], "M1")
            self._draw_date_digit(the_date[1], "M2")
            self._draw_date_digit(the_date[2], "D1")
            self._draw_date_digit(the_date[3], "D2")
            self._draw_date_digit(the_date[4], "Y1")
            self._draw_date_digit(the_date[5], "Y2")
            self._draw_date_digit(the_date[6], "Y3")
            self._draw_date_digit(the_date[7], "Y4")

        # Update alarm icon
        if hasattr(self, "alarm") and self.alarm is not None:
            try:
                alarm_icon = self.alarm.get_widget("alarm")
                if alarm_icon is not None:
                    style = "icon_alarm_on" if self.alarm_set else "icon_alarm_off"
                    alarm_icon.set_style(style)
            except Exception as exc:
                log.warning("DotMatrixClock.Draw: failed to update alarm icon style: %s", exc)

    def _draw_clock_digit(self, digit: str, group_key: str) -> None:
        """Set the style for a clock digit widget."""
        style = "icon_dotMatrixDigit" + digit
        if digit == "0" and group_key == "h1" and self.ampm:
            style = "icon_dotMatrixDigitNone"
        try:
            group = getattr(self, group_key, None)
            if group is not None:
                widget = group.get_widget("digit")
                if widget is not None:
                    widget.set_style(style)
        except Exception as exc:
            log.warning("DotMatrixClock._draw_clock_digit: failed to set style for %s: %s", group_key, exc)

    def _draw_date_digit(self, digit: str, group_key: str) -> None:
        """Set the style for a date digit widget."""
        style = "icon_dotMatrixDate" + digit
        try:
            group = getattr(self, group_key, None)
            if group is not None:
                widget = group.get_widget("digit")
                if widget is not None:
                    widget.set_style(style)
        except Exception as exc:
            log.warning("DotMatrixClock._draw_date_digit: failed to set style for %s: %s", group_key, exc)

    @classmethod
    def _get_selected_skin(cls) -> str:
        """Get the currently selected skin name."""
        jm = ClockBase._get_jive_main()
        if jm is not None:
            try:
                return jm.get_selected_skin()  # type: ignore[no-any-return]
            except Exception as exc:
                log.warning("DotMatrixClock._get_selected_skin: failed to get skin: %s", exc)
        return "JogglerSkin"

    @classmethod
    def _get_dot_matrix_skin(cls, skin_name: str) -> Dict[str, Any]:
        """Build the dot-matrix clock skin dict for the given skin.

        This is a simplified version that creates the style structure
        used by the widget system. The full Lua implementation has
        pixel-perfect layout for each skin; we produce a compatible
        structure.
        """
        imgpath = _imgpath(skin_name)

        s: Dict[str, Any] = {}

        # Determine screen dimensions for layout
        if _is_joggler_skin(skin_name) or _is_hd_skin(skin_name):
            w, h = 800, 480
        elif _is_wqvga_skin(skin_name):
            w, h = 480, 272
        elif skin_name == "QVGAlandscapeSkin":
            w, h = 320, 240
        elif skin_name == "QVGAportraitSkin":
            w, h = 240, 320
        elif skin_name == "QVGA240squareSkin":
            w, h = 240, 240
        else:
            w, h = 800, 480

        s["Clock"] = {
            "w": w,
            "h": h,
            "skinName": skin_name,
            "imgpath": imgpath,
        }

        return s


# ═══════════════════════════════════════════════════════════════════════════
# Digital Clock
# ═══════════════════════════════════════════════════════════════════════════


class DigitalClock(ClockBase):
    """Digital clock display with large digits, date bar, and optional
    AM/PM indicator.

    Port of Lua ``Digital`` class.
    """

    # Class-level cached skin
    _cached_skin: Optional[Dict[str, Any]] = None
    _cached_skin_name: Optional[str] = None

    def __init__(self, applet: "ClockApplet", ampm: bool) -> None:
        log.debug("Init DigitalClock")

        self.applet = applet
        window_style = getattr(applet, "window_style", "Clock") or "Clock"

        skin_name = self._get_selected_skin()

        if (
            DigitalClock._cached_skin is None
            or skin_name != DigitalClock._cached_skin_name
        ):
            log.debug("Fetching Digital clock skin")
            DigitalClock._cached_skin_name = skin_name
            DigitalClock._cached_skin = self._get_digital_skin(skin_name)

        skin = DigitalClock._cached_skin or {}
        super().__init__(skin, window_style)

        self.skin_name = skin_name
        self.imgpath = _imgpath(skin_name)
        self.show_ampm = ampm
        self.use_ampm = ampm

        if ampm:
            self.clock_format_hour = "%I"
        else:
            self.clock_format_hour = "%H"
        self.clock_format_minute = "%M"
        self.clock_format = self.clock_format_hour + ":" + self.clock_format_minute

        # Create widgets
        Label = self._get_label_class()
        Group = self._get_group_class()
        Icon = self._get_icon_class()

        if Label and Group and Icon and self.window:
            # Time labels
            self.h1_label = Label("h1", "1")
            self.h2_label = Label("h2", "2")
            self.m1_label = Label("m1", "0")
            self.m2_label = Label("m2", "0")
            self.ampm_label = Label("ampm", "")
            self.today_label = Label("today", "")

            # Dots
            dots = Group("dots", {"dots": Icon("icon_digitalDots")})

            # Alarm
            alarm_style = "icon_alarm_on" if self.alarm_set else "icon_alarm_off"
            self.alarm = Group("alarm", {"alarm": Icon(alarm_style)})

            # Date group
            self.date_group = Group(
                "date",
                {
                    "dayofweek": Label("dayofweek", ""),
                    "vdivider1": Icon("icon_digitalClockVDivider"),
                    "dayofmonth": Label("dayofmonth", ""),
                    "vdivider2": Icon("icon_digitalClockVDivider"),
                    "month": Label("month", ""),
                },
            )

            # Shadows
            self.h1_shadow = Group(
                "h1Shadow", {"h1Shadow": Icon("icon_digitalClockDropShadow")}
            )
            self.h2_shadow = Group(
                "h2Shadow", {"h2Shadow": Icon("icon_digitalClockDropShadow")}
            )
            self.m1_shadow = Group(
                "m1Shadow", {"m1Shadow": Icon("icon_digitalClockDropShadow")}
            )
            self.m2_shadow = Group(
                "m2Shadow", {"m2Shadow": Icon("icon_digitalClockDropShadow")}
            )

            # Dividers
            hdivider = Group(
                "horizDivider", {"horizDivider": Icon("icon_digitalClockHDivider")}
            )
            hdivider2 = Group(
                "horizDivider2", {"horizDivider": Icon("icon_digitalClockHDivider")}
            )

            # Add all widgets to window
            self.window.add_widget(self.today_label)
            self.window.add_widget(self.alarm)
            self.window.add_widget(self.h1_label)
            self.window.add_widget(self.h1_shadow)
            self.window.add_widget(self.h2_label)
            self.window.add_widget(self.h2_shadow)
            self.window.add_widget(dots)
            self.window.add_widget(self.m1_label)
            self.window.add_widget(self.m1_shadow)
            self.window.add_widget(self.m2_label)
            self.window.add_widget(self.m2_shadow)
            self.window.add_widget(self.ampm_label)
            self.window.add_widget(hdivider)
            self.window.add_widget(hdivider2)
            self.window.add_widget(self.date_group)

    def Draw(self) -> None:
        """Redraw the digital clock with current time/date."""
        t = _local_time()

        # Day of week string
        day_of_week = str(t["wday"])
        token = "SCREENSAVER_CLOCK_DAY_" + day_of_week
        day_str = self.applet.string(token)

        if hasattr(self, "today_label") and self.today_label is not None:
            try:
                self.today_label.set_value(day_str)
            except Exception as exc:
                log.warning("DigitalClock.Draw: failed to set today_label value: %s", exc)

        if hasattr(self, "date_group") and self.date_group is not None:
            try:
                widget = self.date_group.get_widget("dayofweek")
                if widget is not None:
                    widget.set_value(day_str)
            except Exception as exc:
                log.warning("DigitalClock.Draw: failed to set dayofweek widget: %s", exc)

            # Day of month
            try:
                widget = self.date_group.get_widget("dayofmonth")
                if widget is not None:
                    widget.set_value(str(t["day"]))
            except Exception as exc:
                log.warning("DigitalClock.Draw: failed to set dayofmonth widget: %s", exc)

            # Month string
            month_token = "SCREENSAVER_CLOCK_MONTH_" + self._pad(t["month"])
            month_str = self.applet.string(month_token)
            try:
                widget = self.date_group.get_widget("month")
                if widget is not None:
                    widget.set_value(month_str)
            except Exception as exc:
                log.warning("DigitalClock.Draw: failed to set month widget: %s", exc)

        # Alarm icon
        if hasattr(self, "alarm") and self.alarm is not None:
            try:
                alarm_icon = self.alarm.get_widget("alarm")
                if alarm_icon is not None:
                    style = "icon_alarm_on" if self.alarm_set else "icon_alarm_off"
                    alarm_icon.set_style(style)
            except Exception as exc:
                log.warning("DigitalClock.Draw: failed to update alarm icon style: %s", exc)

        # Time digits
        self._draw_time(t)

    def _draw_time(self, t: Optional[Dict[str, int]] = None) -> None:
        """Draw the time digits and AM/PM indicator."""
        if t is None:
            t = _local_time()

        the_minute = self._get_minute(t)
        the_hour = self._get_hour(t)

        if hasattr(self, "h1_label"):
            if the_hour[0] == "0":
                try:
                    self.h1_label.set_value("")
                    if hasattr(self, "h1_shadow"):
                        w = self.h1_shadow.get_widget("h1Shadow")
                        if w is not None:
                            w.set_style("icon_digitalClockNoShadow")
                except Exception as exc:
                    log.warning("DigitalClock._draw_time: failed to clear h1 digit/shadow: %s", exc)
            else:
                try:
                    self.h1_label.set_value(the_hour[0])
                    if hasattr(self, "h1_shadow"):
                        w = self.h1_shadow.get_widget("h1Shadow")
                        if w is not None:
                            w.set_style("icon_digitalClockDropShadow")
                except Exception as exc:
                    log.warning("DigitalClock._draw_time: failed to set h1 digit/shadow: %s", exc)

            try:
                self.h2_label.set_value(the_hour[1])
            except Exception as exc:
                log.warning("DigitalClock._draw_time: failed to set h2 digit: %s", exc)

        if hasattr(self, "m1_label"):
            try:
                self.m1_label.set_value(the_minute[0])
                self.m2_label.set_value(the_minute[1])
            except Exception as exc:
                log.warning("DigitalClock._draw_time: failed to set minute digits: %s", exc)

        # AM/PM
        if self.use_ampm and hasattr(self, "ampm_label"):
            ampm_str = _get_ampm_string()
            try:
                self.ampm_label.set_value(ampm_str)
            except Exception as exc:
                log.warning("DigitalClock._draw_time: failed to set AM/PM label: %s", exc)

    @classmethod
    def _get_selected_skin(cls) -> str:
        jm = ClockBase._get_jive_main()
        if jm is not None:
            try:
                return jm.get_selected_skin()  # type: ignore[no-any-return]
            except Exception as exc:
                log.warning("DigitalClock._get_selected_skin: failed to get skin: %s", exc)
        return "JogglerSkin"

    @classmethod
    def _get_digital_skin(cls, skin_name: str) -> Dict[str, Any]:
        """Build the digital clock skin dict."""
        imgpath = _imgpath(skin_name)
        s: Dict[str, Any] = {}

        if _is_joggler_skin(skin_name) or _is_hd_skin(skin_name):
            w, h = 800, 480
        elif _is_wqvga_skin(skin_name):
            w, h = 480, 272
        elif skin_name == "QVGAlandscapeSkin":
            w, h = 320, 240
        elif skin_name == "QVGAportraitSkin":
            w, h = 240, 320
        elif skin_name == "QVGA240squareSkin":
            w, h = 240, 240
        else:
            w, h = 800, 480

        s["Clock"] = {
            "w": w,
            "h": h,
            "skinName": skin_name,
            "imgpath": imgpath,
        }
        s["ClockBlack"] = _uses(s["Clock"], {"bgImg": None})
        s["ClockTransparent"] = _uses(s["Clock"], {"bgImg": False})

        return s


# ═══════════════════════════════════════════════════════════════════════════
# Analog Clock
# ═══════════════════════════════════════════════════════════════════════════


class AnalogClock(ClockBase):
    """Analog clock with rotating hour and minute hands on a canvas.

    Port of Lua ``Analog`` class.
    """

    # Class-level cached skin
    _cached_skin: Optional[Dict[str, Any]] = None
    _cached_skin_name: Optional[str] = None

    def __init__(self, applet: "ClockApplet") -> None:
        log.info("Init AnalogClock")

        self.applet = applet
        skin_name = self._get_selected_skin()

        if (
            AnalogClock._cached_skin is None
            or skin_name != AnalogClock._cached_skin_name
        ):
            log.debug("Fetching Analog clock skin")
            AnalogClock._cached_skin_name = skin_name
            AnalogClock._cached_skin = self._get_analog_skin(skin_name)

        skin = AnalogClock._cached_skin or {}
        super().__init__(skin, "Clock")

        self.skin_name = skin_name
        self.imgpath = _imgpath(skin_name)

        # Skin parameters
        self.skin_params = self._get_skin_params(skin_name)

        # Load hand images
        self.pointer_hour = self._load_image(
            self.skin_params.get("hour_hand", "Clocks/Analog/clock_analog_hr_hand.png")
        )
        self.pointer_minute = self._load_image(
            self.skin_params.get(
                "minute_hand", "Clocks/Analog/clock_analog_min_hand.png"
            )
        )
        self.alarm_icon = self._load_image(
            self.skin_params.get("alarm_icon", "Clocks/Analog/icon_alarm_analog.png")
        )

        # Canvas for drawing
        Canvas = self._get_canvas_class()
        if Canvas is not None and self.window is not None:
            self.canvas = Canvas("debug_canvas", lambda screen: self._redraw(screen))
            self.window.add_widget(self.canvas)
        else:
            self.canvas = None

        self.clock_format = "%H:%M"

    def Draw(self) -> None:
        """Trigger a canvas redraw."""
        if self.canvas is not None:
            try:
                self.canvas.re_draw()
            except Exception as exc:
                log.debug("AnalogClock.Draw: failed to redraw canvas: %s", exc)

    def _redraw(self, screen: Any) -> None:
        """Render the analog clock hands on *screen*.

        Port of Lua ``Analog:_reDraw(screen)``.
        """
        t = _local_time()
        m = t["min"]
        h = t["hour"] % 12

        ratio = self.skin_params.get("ratio", 1.0)

        # Hour hand
        hour_angle = (360.0 / 12.0) * (h + m / 60.0)
        if self.pointer_hour is not None:
            try:
                tmp = self.pointer_hour.rotozoom(-hour_angle, ratio, 5)
                fw, fh = tmp.get_size()
                x = int((self.screen_width / 2) - (fw / 2))
                y = int((self.screen_height / 2) - (fh / 2))
                tmp.blit(screen, x, y)
                tmp.release()
            except Exception as exc:
                log.debug("AnalogClock._redraw: failed to draw hour hand: %s", exc)

        # Minute hand
        minute_angle = (360.0 / 60.0) * m
        if self.pointer_minute is not None:
            try:
                tmp = self.pointer_minute.rotozoom(-minute_angle, ratio, 5)
                fw, fh = tmp.get_size()
                x = int((self.screen_width / 2) - (fw / 2))
                y = int((self.screen_height / 2) - (fh / 2))
                tmp.blit(screen, x, y)
                tmp.release()
            except Exception as exc:
                log.debug("AnalogClock._redraw: failed to draw minute hand: %s", exc)

        # Alarm icon
        if self.alarm_set and self.alarm_icon is not None:
            try:
                ax = self.skin_params.get("alarm_x", self.screen_width - 40)
                ay = self.skin_params.get("alarm_y", 15)
                self.alarm_icon.blit(screen, ax, ay)
            except Exception as exc:
                log.debug("AnalogClock._redraw: failed to draw alarm icon: %s", exc)

    @classmethod
    def _get_selected_skin(cls) -> str:
        jm = ClockBase._get_jive_main()
        if jm is not None:
            try:
                return jm.get_selected_skin()  # type: ignore[no-any-return]
            except Exception as exc:
                log.warning("AnalogClock._get_selected_skin: failed to get skin: %s", exc)
        return "JogglerSkin"

    def _get_analog_skin(self, skin_name: str) -> Dict[str, Any]:
        """Build the analog clock skin dict."""
        self.imgpath = _imgpath(skin_name)

        s: Dict[str, Any] = {}
        s["Clock"] = {
            "skinName": skin_name,
            "imgpath": self.imgpath,
        }
        return s

    def _get_skin_params(self, skin_name: str) -> Dict[str, Any]:
        """Return skin-specific parameters for hand images, sizes, etc."""
        params: Dict[str, Any] = {
            "minute_hand": "Clocks/Analog/clock_analog_min_hand.png",
            "hour_hand": "Clocks/Analog/clock_analog_hr_hand.png",
            "alarm_icon": "Clocks/Analog/icon_alarm_analog.png",
            "alarm_x": self.screen_width - 40,
            "alarm_y": 15,
            "ratio": 1.0,
        }

        if _is_wqvga_skin(skin_name):
            params["alarm_y"] = 18
        elif _is_joggler_skin(skin_name) or _is_hd_skin(skin_name):
            params["alarm_x"] = _JOGGLER_SKIN_ALARM_X
            params["alarm_y"] = _JOGGLER_SKIN_ALARM_Y
            params["ratio"] = max(self.screen_width / 800.0, self.screen_height / 480.0)
            if _is_hd_skin(skin_name):
                params["ratio"] *= 1.5

        return params


# ═══════════════════════════════════════════════════════════════════════════
# Word Clock
# ═══════════════════════════════════════════════════════════════════════════


class WordClockDisplay(ClockBase):
    """Word clock display — time as highlighted words on a grid.

    For Joggler/HD/WQVGA skins: shows word images on a background.
    For QVGA skins: falls back to an analog clock with a word-clock
    background and text date.

    Port of Lua ``WordClock`` class.
    """

    # Class-level cached skin
    _cached_skin: Optional[Dict[str, Any]] = None
    _cached_skin_name: Optional[str] = None

    def __init__(self, applet: "ClockApplet") -> None:
        log.debug("Init WordClockDisplay")

        self.applet = applet
        skin_name = self._get_selected_skin()

        if (
            WordClockDisplay._cached_skin is None
            or skin_name != WordClockDisplay._cached_skin_name
        ):
            log.debug("Fetching WordClock skin")
            WordClockDisplay._cached_skin_name = skin_name
            WordClockDisplay._cached_skin = self._get_word_clock_skin(skin_name)

        skin = WordClockDisplay._cached_skin or {}
        super().__init__(skin, "Clock")

        self.skin_name = skin_name
        self.imgpath = _imgpath(skin_name)

        # Skin params
        self.skin_params = self._get_skin_params(skin_name)

        # Load word images for large skins
        self._word_images: Dict[str, Any] = {}
        if (
            _is_joggler_skin(skin_name)
            or _is_wqvga_skin(skin_name)
            or _is_hd_skin(skin_name)
        ):
            word_keys = [
                ("textIt", "pointer_textIt"),
                ("textIs", "pointer_textIs"),
                ("textHas", "pointer_textHas"),
                ("textNearly", "pointer_textNearly"),
                ("textJustgone", "pointer_textJustgone"),
                ("textHalf", "pointer_textHalf"),
                ("textTen", "pointer_textTen"),
                ("textAQuarter", "pointer_textAquarter"),
                ("textTwenty", "pointer_textTwenty"),
                ("textFive", "pointer_textFive"),
                ("textMinutes", "pointer_textMinutes"),
                ("textTo", "pointer_textTo"),
                ("textPast", "pointer_textPast"),
                ("textHourOne", "pointer_textHourOne"),
                ("textHourTwo", "pointer_textHourTwo"),
                ("textHourThree", "pointer_textHourThree"),
                ("textHourFour", "pointer_textHourFour"),
                ("textHourFive", "pointer_textHourFive"),
                ("textHourSix", "pointer_textHourSix"),
                ("textHourSeven", "pointer_textHourSeven"),
                ("textHourEight", "pointer_textHourEight"),
                ("textHourNine", "pointer_textHourNine"),
                ("textHourTen", "pointer_textHourTen"),
                ("textHourEleven", "pointer_textHourEleven"),
                ("textHourTwelve", "pointer_textHourTwelve"),
                ("textOClock", "pointer_textOClock"),
                ("textAM", "pointer_textAM"),
                ("textPM", "pointer_textPM"),
            ]
            Surface = self._get_surface_class()
            if Surface is not None:
                for param_key, attr_name in word_keys:
                    path = self.skin_params.get(param_key)
                    if path:
                        try:
                            img = Surface.load_image(path)
                            self._word_images[attr_name] = img
                        except Exception as exc:
                            log.debug("WordClock.__init__: failed to load word image %s (%s): %s", attr_name, path, exc)
                            self._word_images[attr_name] = None
                    else:
                        self._word_images[attr_name] = None

        elif skin_name in (
            "QVGAlandscapeSkin",
            "QVGAportraitSkin",
            "QVGA240squareSkin",
        ):
            # QVGA: load analog-style hands
            Surface = self._get_surface_class()
            if Surface is not None:
                hour_path = self.skin_params.get("hourHand")
                min_path = self.skin_params.get("minuteHand")
                if hour_path:
                    try:
                        self.pointer_hour = Surface.load_image(hour_path)
                    except Exception as exc:
                        log.debug("WordClock.__init__: failed to load hour hand image %s: %s", hour_path, exc)
                        self.pointer_hour = None
                else:
                    self.pointer_hour = None
                if min_path:
                    try:
                        self.pointer_minute = Surface.load_image(min_path)
                    except Exception as exc:
                        log.debug("WordClock.__init__: failed to load minute hand image %s: %s", min_path, exc)
                        self.pointer_minute = None
                else:
                    self.pointer_minute = None

        # Load alarm icon
        alarm_path = self.skin_params.get("alarmIcon")
        if alarm_path:
            Surface = self._get_surface_class()
            if Surface is not None:
                try:
                    self.word_alarm_icon = Surface.load_image(alarm_path)
                except Exception as exc:
                    log.debug("WordClock.__init__: failed to load alarm icon %s: %s", alarm_path, exc)
                    self.word_alarm_icon = None
            else:
                self.word_alarm_icon = None
        else:
            self.word_alarm_icon = None

        # Text label for date
        Label = self._get_label_class()
        if Label is not None:
            self.textdate = Label("textdate", "")
        else:
            self.textdate = None

        # Canvas for drawing
        Canvas = self._get_canvas_class()
        if Canvas is not None and self.window is not None:
            self.canvas = Canvas("debug_canvas", lambda screen: self._redraw(screen))
            self.window.add_widget(self.canvas)
            if self.textdate is not None:
                self.window.add_widget(self.textdate)
        else:
            self.canvas = None

        self.clock_format = "%H:%M"

    def Draw(self) -> None:
        """Trigger a canvas redraw."""
        log.debug("WordClockDisplay:Draw")
        if self.canvas is not None:
            try:
                self.canvas.re_draw()
            except Exception as exc:
                log.debug("WordClock.Draw: failed to redraw canvas: %s", exc)

    def _redraw(self, screen: Any) -> None:
        """Render the word clock on *screen*.

        For Joggler/WQVGA/HD skins: renders word images at fixed positions.
        For QVGA skins: renders analog-style hands.
        """
        log.debug("WordClockDisplay:_reDraw, skin=%s", self.skin_name)

        if (
            _is_joggler_skin(self.skin_name)
            or _is_wqvga_skin(self.skin_name)
            or _is_hd_skin(self.skin_name)
        ):
            t = _local_time()
            flags = _get_word_flags(t)

            # Get ratio and offsets from skin
            clock_skin = self.skin.get("Clock", {}) if self.skin else {}
            r = clock_skin.get("ratio", 1.0)

            # Zoom factor
            z = r
            if _is_wqvga_skin(self.skin_name):
                z = 1.0

            x_off = clock_skin.get("offsetX", 0)
            y_off = clock_skin.get("offsetY", 0)

            # Blit word images at their grid positions
            # Row 1
            self._blit_word(screen, "pointer_textIt", z, x_off + 20 * r, y_off + 50 * r)
            if flags.get("is"):
                self._blit_word(
                    screen, "pointer_textIs", z, x_off + 86 * r, y_off + 50 * r
                )
            if flags.get("has"):
                self._blit_word(
                    screen, "pointer_textHas", z, x_off + 156 * r, y_off + 50 * r
                )
            if flags.get("nearly"):
                self._blit_word(
                    screen, "pointer_textNearly", z, x_off + 280 * r, y_off + 50 * r
                )
            if flags.get("justgone"):
                self._blit_word(
                    screen, "pointer_textJustgone", z, x_off + 496 * r, y_off + 50 * r
                )

            # Row 2
            if flags.get("half"):
                self._blit_word(
                    screen, "pointer_textHalf", z, x_off + 20 * r, y_off + 108 * r
                )
            if flags.get("ten"):
                self._blit_word(
                    screen, "pointer_textTen", z, x_off + 163 * r, y_off + 108 * r
                )
            if flags.get("aquarter"):
                self._blit_word(
                    screen, "pointer_textAquarter", z, x_off + 274 * r, y_off + 108 * r
                )
            if flags.get("twenty"):
                self._blit_word(
                    screen, "pointer_textTwenty", z, x_off + 579 * r, y_off + 108 * r
                )

            # Row 3
            if flags.get("five"):
                self._blit_word(
                    screen, "pointer_textFive", z, x_off + 20 * r, y_off + 165 * r
                )
            if flags.get("minutes"):
                self._blit_word(
                    screen, "pointer_textMinutes", z, x_off + 169 * r, y_off + 165 * r
                )
            if flags.get("to"):
                self._blit_word(
                    screen, "pointer_textTo", z, x_off + 425 * r, y_off + 165 * r
                )
            if flags.get("past"):
                self._blit_word(
                    screen, "pointer_textPast", z, x_off + 537 * r, y_off + 165 * r
                )
            if flags.get("hsix"):
                self._blit_word(
                    screen, "pointer_textHourSix", z, x_off + 707 * r, y_off + 165 * r
                )

            # Row 4
            if flags.get("hseven"):
                self._blit_word(
                    screen, "pointer_textHourSeven", z, x_off + 20 * r, y_off + 222 * r
                )
            if flags.get("hone"):
                self._blit_word(
                    screen, "pointer_textHourOne", z, x_off + 222 * r, y_off + 222 * r
                )
            if flags.get("htwo"):
                self._blit_word(
                    screen, "pointer_textHourTwo", z, x_off + 363 * r, y_off + 222 * r
                )
            if flags.get("hten"):
                self._blit_word(
                    screen, "pointer_textHourTen", z, x_off + 513 * r, y_off + 222 * r
                )
            if flags.get("hfour"):
                self._blit_word(
                    screen, "pointer_textHourFour", z, x_off + 650 * r, y_off + 222 * r
                )

            # Row 5
            if flags.get("hfive"):
                self._blit_word(
                    screen, "pointer_textHourFive", z, x_off + 20 * r, y_off + 280 * r
                )
            if flags.get("hnine"):
                self._blit_word(
                    screen, "pointer_textHourNine", z, x_off + 193 * r, y_off + 280 * r
                )
            if flags.get("htwelve"):
                self._blit_word(
                    screen,
                    "pointer_textHourTwelve",
                    z,
                    x_off + 371 * r,
                    y_off + 280 * r,
                )
            if flags.get("height"):
                self._blit_word(
                    screen, "pointer_textHourEight", z, x_off + 639 * r, y_off + 280 * r
                )

            # Row 6
            if flags.get("heleven"):
                self._blit_word(
                    screen, "pointer_textHourEleven", z, x_off + 20 * r, y_off + 338 * r
                )
            if flags.get("hthree"):
                self._blit_word(
                    screen, "pointer_textHourThree", z, x_off + 222 * r, y_off + 338 * r
                )
            if flags.get("oclock"):
                self._blit_word(
                    screen, "pointer_textOClock", z, x_off + 398 * r, y_off + 338 * r
                )
            if flags.get("am"):
                self._blit_word(
                    screen, "pointer_textAM", z, x_off + 627 * r, y_off + 338 * r
                )
            if flags.get("pm"):
                self._blit_word(
                    screen, "pointer_textPM", z, x_off + 716 * r, y_off + 338 * r
                )

            # Date text
            day = t["day"]
            date_str = "ON " + _get_date_as_words(day).upper()
            if self.textdate is not None:
                try:
                    self.textdate.set_value(date_str)
                except Exception as exc:
                    log.warning("WordClock._redraw: failed to set date text: %s", exc)

        elif self.skin_name in (
            "QVGAlandscapeSkin",
            "QVGAportraitSkin",
            "QVGA240squareSkin",
        ):
            # QVGA fallback: analog hands
            t = _local_time()
            m = t["min"]
            h = t["hour"] % 12

            pointer_hour = getattr(self, "pointer_hour", None)
            pointer_minute = getattr(self, "pointer_minute", None)

            if pointer_hour is not None:
                try:
                    angle = (360.0 / 12.0) * (h + m / 60.0)
                    tmp = pointer_hour.rotozoom(-angle, 1, 5)
                    fw, fh = tmp.get_size()
                    x = int(self.screen_width / 2 - fw / 2)
                    y = int(self.screen_height / 2 - fh / 2)
                    tmp.blit(screen, x, y)
                    tmp.release()
                except Exception as exc:
                    log.debug("WordClock._redraw: failed to draw QVGA hour hand: %s", exc)

            if pointer_minute is not None:
                try:
                    angle = (360.0 / 60.0) * m
                    tmp = pointer_minute.rotozoom(-angle, 1, 5)
                    fw, fh = tmp.get_size()
                    x = int(self.screen_width / 2 - fw / 2)
                    y = int(self.screen_height / 2 - fh / 2)
                    tmp.blit(screen, x, y)
                    tmp.release()
                except Exception as exc:
                    log.debug("WordClock._redraw: failed to draw QVGA minute hand: %s", exc)

            # Date text
            day = t["day"]
            date_str = _get_date_as_words(day).upper()
            if self.textdate is not None:
                try:
                    self.textdate.set_value(date_str)
                except Exception as exc:
                    log.warning("WordClock._redraw: failed to set QVGA date text: %s", exc)

        # Alarm icon
        if self.alarm_set and self.word_alarm_icon is not None:
            try:
                ax = self.skin_params.get("alarmX", _JOGGLER_SKIN_ALARM_X)
                ay = self.skin_params.get("alarmY", _JOGGLER_SKIN_ALARM_Y)
                self.word_alarm_icon.blit(screen, ax, ay)
            except Exception as exc:
                log.debug("WordClock._redraw: failed to draw alarm icon: %s", exc)

    def _blit_word(
        self, screen: Any, attr_name: str, zoom: float, x: float, y: float
    ) -> None:
        """Blit a word image at position (x, y) with zoom."""
        img = self._word_images.get(attr_name)
        if img is None:
            return
        try:
            if zoom != 1.0:
                tmp = img.zoom(zoom, zoom, 1)
                tmp.blit(screen, int(x), int(y))
            else:
                img.blit(screen, int(x), int(y))
        except Exception as exc:
            log.debug("WordClock._blit_word: failed to blit %s: %s", attr_name, exc)

    @classmethod
    def _get_selected_skin(cls) -> str:
        jm = ClockBase._get_jive_main()
        if jm is not None:
            try:
                return jm.get_selected_skin()  # type: ignore[no-any-return]
            except Exception as exc:
                log.warning("WordClock._get_selected_skin: failed to get skin: %s", exc)
        return "JogglerSkin"

    def _get_word_clock_skin(self, skin_name: str) -> Dict[str, Any]:
        """Build the word clock skin dict."""
        self.skin_name = skin_name
        self.imgpath = _imgpath(skin_name)

        s: Dict[str, Any] = {}

        # HDSkin uses Joggler artwork
        imgpath = self.imgpath.replace("HDSkin", "JogglerSkin")

        if _is_joggler_skin(skin_name) or _is_hd_skin(skin_name):
            fw_cls = self._get_framework()
            sw, sh = 800, 480
            if fw_cls is not None:
                try:
                    sw, sh = fw_cls.get_screen_size()
                except Exception as exc:
                    log.debug("WordClock._get_word_clock_skin: failed to get screen size: %s", exc)
            ratio = min(sw / 800.0, sh / 480.0)

            font_size = int(26 * sh / 480.0)
            s["Clock"] = {
                "textdate": {
                    "x": 0,
                    "y": int(420 * ratio),
                    "w": sw,
                    "font_size": font_size,
                    "align": "bottom",
                    "fg": (0xFF, 0xFF, 0xFF),
                },
                "ratio": ratio,
                "offsetX": 0,
                "offsetY": 0,
            }
        elif _is_wqvga_skin(skin_name):
            s["Clock"] = {
                "textdate": {
                    "x": 0,
                    "y": 244,
                    "w": 480,
                    "font_size": 15,
                    "align": "bottom",
                    "fg": (0xFF, 0xFF, 0xFF),
                },
                "offsetX": 0,
                "ratio": 480.0 / 800.0,
            }
        elif skin_name == "QVGAlandscapeSkin":
            s["Clock"] = {
                "textdate": {
                    "x": 0,
                    "y": 222,
                    "w": 320,
                    "font_size": 10,
                    "align": "bottom",
                    "fg": (0xFF, 0xFF, 0xFF),
                },
            }
        elif skin_name == "QVGAportraitSkin":
            s["Clock"] = {
                "textdate": {
                    "x": 0,
                    "y": 300,
                    "w": 240,
                    "font_size": 8,
                    "align": "bottom",
                    "fg": (0xFF, 0xFF, 0xFF),
                },
            }
        elif skin_name == "QVGA240squareSkin":
            s["Clock"] = {
                "textdate": {
                    "x": 0,
                    "y": 220,
                    "w": 240,
                    "font_size": 18,
                    "align": "bottom",
                    "fg": (0xFF, 0xFF, 0xFF),
                },
            }

        return s

    def _get_skin_params(self, skin_name: str) -> Dict[str, Any]:
        """Return skin-specific parameters for word images, alarms, etc."""
        self.imgpath = _imgpath(skin_name)

        if (
            _is_joggler_skin(skin_name)
            or _is_wqvga_skin(skin_name)
            or _is_hd_skin(skin_name)
        ):
            # HDSkin uses Joggler artwork
            imgpath = self.imgpath.replace("HDSkin", "JogglerSkin")
            wc_path = imgpath + "Clocks/WordClock/"

            params: Dict[str, Any] = {
                "textIt": wc_path + "text-it.png",
                "textIs": wc_path + "text-is.png",
                "textHas": wc_path + "text-has.png",
                "textNearly": wc_path + "text-nearly.png",
                "textJustgone": wc_path + "text-justgone.png",
                "textHalf": wc_path + "text-half.png",
                "textTen": wc_path + "text-ten.png",
                "textAQuarter": wc_path + "text-aquarter.png",
                "textTwenty": wc_path + "text-twenty.png",
                "textFive": wc_path + "text-five.png",
                "textMinutes": wc_path + "text-minutes.png",
                "textTo": wc_path + "text-to.png",
                "textPast": wc_path + "text-past.png",
                "textHourOne": wc_path + "text-hour-one.png",
                "textHourTwo": wc_path + "text-hour-two.png",
                "textHourThree": wc_path + "text-hour-three.png",
                "textHourFour": wc_path + "text-hour-four.png",
                "textHourFive": wc_path + "text-hour-five.png",
                "textHourSix": wc_path + "text-hour-six.png",
                "textHourSeven": wc_path + "text-hour-seven.png",
                "textHourEight": wc_path + "text-hour-eight.png",
                "textHourNine": wc_path + "text-hour-nine.png",
                "textHourTen": wc_path + "text-hour-ten.png",
                "textHourEleven": wc_path + "text-hour-eleven.png",
                "textHourTwelve": wc_path + "text-hour-twelve.png",
                "textOClock": wc_path + "text-oclock.png",
                "textAM": wc_path + "text-am.png",
                "textPM": wc_path + "text-pm.png",
                "alarmIcon": wc_path + "icon_alarm_word.png",
                "alarmX": _JOGGLER_SKIN_ALARM_X,
                "alarmY": _JOGGLER_SKIN_ALARM_Y,
            }

            if _is_wqvga_skin(skin_name):
                params["alarmX"] = 445
                params["alarmY"] = 2

            return params

        elif skin_name in (
            "QVGAlandscapeSkin",
            "QVGAportraitSkin",
            "QVGA240squareSkin",
        ):
            wc_path = self.imgpath + "Clocks/WordClock/"
            alarm_x = 280 if skin_name == "QVGAlandscapeSkin" else 200
            return {
                "minuteHand": wc_path + "clock_word_min_hand.png",
                "hourHand": wc_path + "clock_word_hr_hand.png",
                "alarmIcon": wc_path + "icon_alarm_word.png",
                "alarmX": alarm_x,
                "alarmY": 15,
            }

        return {}


# ═══════════════════════════════════════════════════════════════════════════
# Main Clock Applet
# ═══════════════════════════════════════════════════════════════════════════


class ClockApplet(Applet):
    """Clock screensaver applet.

    Provides multiple clock display modes registered as screensavers:
    Analog, Digital (3 variants), Dot Matrix, and Word Clock.

    The ``open*`` methods are called by the ScreenSavers service when
    a clock screensaver is activated.
    """

    def __init__(self) -> None:
        super().__init__()
        self.clock: Optional[ClockBase] = None
        self.old_time: Optional[str] = None
        self.snapshot: Any = None
        self.window_style: str = "Clock"

    # ------------------------------------------------------------------
    # Public entry points (called by ScreenSavers service)
    # ------------------------------------------------------------------

    def openDetailedClock(self, force: bool = False) -> Optional[bool]:
        """Open the Digital clock screensaver."""
        return self._open_screensaver("Digital", "Clock", force)

    def openDetailedClockBlack(self, force: bool = False) -> Optional[bool]:
        """Open the Digital clock screensaver (black background)."""
        return self._open_screensaver("Digital", "ClockBlack", force)

    def openDetailedClockTransparent(self, force: bool = False) -> Optional[bool]:
        """Open the Digital clock screensaver (transparent background)."""
        return self._open_screensaver("Digital", "ClockTransparent", force)

    def openAnalogClock(self, force: bool = False) -> Optional[bool]:
        """Open the Analog clock screensaver."""
        return self._open_screensaver("Analog", None, force)

    def openStyledClock(self, force: bool = False) -> Optional[bool]:
        """Open the Dot Matrix clock screensaver."""
        return self._open_screensaver("DotMatrix", None, force)

    def openWordClock(self, force: bool = False) -> Optional[bool]:
        """Open the Word Clock screensaver."""
        return self._open_screensaver("WordClock", None, force)

    # ------------------------------------------------------------------
    # Tick (1-second timer)
    # ------------------------------------------------------------------

    def _tick(self) -> None:
        """Called every second by the window timer.

        Only redraws when the formatted time string changes (once per
        minute for most formats).  Uses a SnapshotWindow for smooth
        fade-in transitions.
        """
        if self.clock is None:
            return

        the_time = _time.strftime(self.clock.clock_format)
        if the_time == self.old_time:
            return

        self.old_time = the_time

        # SnapshotWindow transition
        try:
            SnapshotWindow = self._get_snapshot_window_class()
            Window = ClockBase._get_window_class()
            mgr = ClockBase._get_applet_manager()

            if SnapshotWindow is not None and Window is not None:
                if self.snapshot is None:
                    self.snapshot = SnapshotWindow()
                    if mgr is not None:
                        ss = mgr.get_applet_instance("ScreenSavers")
                        if ss is not None and hasattr(ss, "screensaverWindow"):
                            ss.screensaverWindow(
                                self.snapshot, None, None, None, "Clock"
                            )
                else:
                    self.snapshot.refresh()

                transition_none = getattr(Window, "transitionNone", None)
                transition_fade = getattr(Window, "transitionFadeIn", None)

                self.snapshot.replace(self.clock.window)
                self.clock.Draw()
                if self.clock.window is not None:
                    self.clock.window.replace(self.snapshot, transition_fade)
            else:
                # No snapshot — just redraw
                self.clock.Draw()
        except Exception as exc:
            # Fallback: just redraw without transitions
            log.warning("ClockApplet._tick: transition failed, falling back to direct draw: %s", exc)
            try:
                self.clock.Draw()
            except Exception as exc2:
                log.warning("ClockApplet._tick: fallback draw also failed: %s", exc2)

    # ------------------------------------------------------------------
    # Core screensaver opener
    # ------------------------------------------------------------------

    def _open_screensaver(
        self,
        clock_type: str,
        window_style: Optional[str] = None,
        force: bool = False,
    ) -> Optional[bool]:
        """Create and show a clock screensaver of the given *clock_type*.

        Parameters
        ----------
        clock_type:
            One of ``"DotMatrix"``, ``"Digital"``, ``"Analog"``, ``"WordClock"``.
        window_style:
            Window style override (used by Digital variants).
        force:
            If *True*, skip the year sanity check.

        Returns ``True`` on success, ``None`` on failure.
        """
        log.debug("_open_screensaver: type=%s", clock_type)

        # Year sanity check (Lua original skips if year < 2009)
        if not force:
            year = _datetime.now().year
            if year < 2009:
                log.warn(
                    "Device does not seem to have the right time: year=%d",
                    year,
                )
                return None

        # Get date/time settings from the datetime module
        weekstart, hours_str, short_date_format = self._get_datetime_settings()
        ampm = hours_str == "12"

        # Create the clock instance
        if clock_type == "DotMatrix":
            self.clock = DotMatrixClock(ampm, short_date_format)
        elif clock_type == "Digital":
            self.window_style = window_style or "Clock"
            self.clock = DigitalClock(self, ampm)
        elif clock_type == "Analog":
            self.clock = AnalogClock(self)
        elif clock_type == "WordClock":
            self.clock = WordClockDisplay(self)
        else:
            log.error("Unknown clock type: %s", clock_type)
            return None

        # Set up 1-second tick timer
        if self.clock.window is not None:
            try:
                self.clock.window.add_timer(1000, lambda: self._tick())
            except Exception as exc:
                log.error("ClockApplet._open_screensaver: failed to add tick timer: %s", exc, exc_info=True)

        # Initial draw
        self.clock.Draw()

        # Show with fade-in transition
        if self.clock.window is not None:
            try:
                Window = ClockBase._get_window_class()
                transition = (
                    getattr(Window, "transitionFadeIn", None) if Window else None
                )
                self.clock.window.show(transition)
            except Exception as exc:
                log.warning("ClockApplet._open_screensaver: failed to show clock window: %s", exc)

        return True

    # ------------------------------------------------------------------
    # Date/time settings helpers
    # ------------------------------------------------------------------

    def _get_datetime_settings(self) -> Tuple[str, str, str]:
        """Get the current datetime settings from the datetime module.

        Returns (weekstart, hours, short_date_format).
        """
        weekstart = "Sunday"
        hours = "12"
        short_date_format = "%m.%d.%Y"

        dt = self._get_datetime_module()
        if dt is not None:
            try:
                if hasattr(dt, "get_weekstart"):
                    weekstart = dt.get_weekstart() or weekstart
                elif hasattr(dt, "getWeekstart"):
                    weekstart = dt.getWeekstart() or weekstart
            except Exception as exc:
                log.warning("ClockApplet._get_datetime_settings: failed to get weekstart: %s", exc)

            try:
                if hasattr(dt, "get_hours"):
                    hours = dt.get_hours() or hours
                elif hasattr(dt, "getHours"):
                    hours = dt.getHours() or hours
            except Exception as exc:
                log.warning("ClockApplet._get_datetime_settings: failed to get hours format: %s", exc)

            try:
                if hasattr(dt, "get_short_date_format"):
                    short_date_format = dt.get_short_date_format() or short_date_format
                elif hasattr(dt, "getShortDateFormat"):
                    short_date_format = dt.getShortDateFormat() or short_date_format
            except Exception as exc:
                log.warning("ClockApplet._get_datetime_settings: failed to get short date format: %s", exc)

        return weekstart, hours, short_date_format

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
    def _get_snapshot_window_class() -> Any:
        """Try to obtain the SnapshotWindow class."""
        try:
            from jive.ui.snapshot_window import SnapshotWindow  # type: ignore[import-not-found]

            return SnapshotWindow
        except ImportError:
            return None

    def display_name(self) -> str:
        """Return the display name for this applet."""
        return "Clock"
