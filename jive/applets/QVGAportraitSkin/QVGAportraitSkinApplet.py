"""
jive.applets.QVGAportraitSkin.QVGAportraitSkinApplet --- QVGAportraitSkin applet.

Ported from ``share/jive/applets/QVGAportraitSkin/QVGAportraitSkinApplet.lua``
(~656 LOC) in the original jivelite project.

This applet implements the skin for a 240x320 portrait display, such as
the Squeezebox Controller in portrait orientation.  It inherits from
QVGAbaseSkinApplet and overrides styles for the portrait form factor.

Key implementation notes
------------------------

* Inherits the complete QVGA base skin via
  ``QVGAbaseSkinApplet.skin()``, then applies portrait-specific
  overrides (scrollbar, progress bar, NowPlaying layout, title bar,
  menu item heights, iconbar, time input, context menu, etc.).

* Default screen size is 240x320.

* NowPlaying styles are adapted for the portrait display with
  artwork positioned to the west side and track info overlaid.

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Copyright 2013-2014 Adrian Smith (jivelite amendments)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

import copy
from typing import (
    Any,
    Dict,
    Optional,
    Sequence,
    Tuple,
)

from jive.applets.QVGAbaseSkin.QVGAbaseSkinApplet import (
    LAYER_CONTENT_ON_STAGE,
    LAYER_FRAME,
    LAYER_TITLE,
    LAYOUT_CENTER,
    LAYOUT_EAST,
    LAYOUT_NONE,
    LAYOUT_NORTH,
    LAYOUT_SOUTH,
    LAYOUT_WEST,
    WH_FILL,
    QVGAbaseSkinApplet,
    Style,
    _boldfont,
    _font,
    _uses,
)
from jive.utils.log import logger

__all__ = ["QVGAportraitSkinApplet"]

log = logger("applet.QVGAportraitSkin")

# ---------------------------------------------------------------------------
# Image path prefixes
# ---------------------------------------------------------------------------
_IMGPATH = "applets/QVGAportraitSkin/images/"
_BASE_IMGPATH = "applets/QVGAbaseSkin/images/"
_FONTPATH = "fonts/"
_FONT_NAME = "FreeSans"
_BOLD_PREFIX = "Bold"


# ---------------------------------------------------------------------------
# Lazy image/tile loaders (same pattern as QVGAbaseSkinApplet)
# ---------------------------------------------------------------------------


def _img(path: str) -> Style:
    """Return a lazy-loadable image reference."""
    return {"__type__": "image", "path": path}


def _load_image(file: str) -> Style:
    """Return a lazy reference to an image in the QVGAportraitSkin images dir."""
    return _img(_IMGPATH + file)


def _load_base_image(file: str) -> Style:
    """Return a lazy reference to an image in the QVGAbaseSkin images dir."""
    return _img(_BASE_IMGPATH + file)


def _tile_image(path: str) -> Style:
    """Return a lazy-loadable single-image tile reference."""
    return {"__type__": "tile_image", "path": path}


def _tile_vtiles(paths: Sequence[Optional[str]]) -> Style:
    """Return a lazy-loadable vertical 3-patch tile reference."""
    return {"__type__": "tile_vtiles", "paths": list(paths)}


def _tile_htiles(paths: Sequence[Optional[str]]) -> Style:
    """Return a lazy-loadable horizontal 3-patch tile reference."""
    return {"__type__": "tile_htiles", "paths": list(paths)}


def _fill_color(color: int) -> Style:
    """Return a lazy-loadable fill-colour tile reference."""
    return {"__type__": "tile_fill", "color": color}


# ============================================================================
# QVGAportraitSkinApplet
# ============================================================================


class QVGAportraitSkinApplet(QVGAbaseSkinApplet):
    """Skin applet for 240x320 portrait displays (Squeezebox Controller, etc.).

    Inherits the complete QVGA base skin and overrides styles specific
    to the portrait form factor.
    """

    def __init__(self) -> None:
        super().__init__()
        self.images: Style = {}

    def init(self) -> None:
        """Initialise the applet (lifecycle hook)."""
        self.images = {}

    # ------------------------------------------------------------------
    # Parameters
    # ------------------------------------------------------------------

    def param(self) -> Style:
        """Return skin parameter constants for the 240x320 portrait skin."""
        return {
            "THUMB_SIZE": 41,
            "THUMB_SIZE_MENU": 40,
            "POPUP_THUMB_SIZE": 120,
            "NOWPLAYING_MENU": True,
            # NOWPLAYING_TRACKINFO_LINES used in assisting scroll behavior
            # animation on NP.
            # 3 is for a three line track, artist, and album (e.g., SBtouch)
            # 2 is for a two line track, artist+album (e.g., SBradio,
            #   SBcontroller)
            "NOWPLAYING_TRACKINFO_LINES": 2,
            "nowPlayingScreenStyles": [
                {
                    "style": "nowplaying",
                    "artworkSize": "240x240",
                    "text": self.string("LARGE_ART"),
                },
                {
                    "style": "nowplaying_small_art",
                    "artworkSize": "200x200",
                    "text": self.string("SMALL_ART"),
                },
            ],
        }

    # ------------------------------------------------------------------
    # Main skin method
    # ------------------------------------------------------------------

    def skin(
        self,
        s: Style,
        reload: bool = False,
        use_default_size: bool = False,
    ) -> Style:
        """Populate *s* with 240x320-portrait-specific style overrides.

        Parameters
        ----------
        s:
            The style dict to populate.
        reload:
            ``True`` when the skin is being reloaded (not first load).
        use_default_size:
            ``True`` to use the default 240x320 screen size instead of
            querying the framework.

        Returns
        -------
        Style
            The populated style dict *s*.
        """
        # Screen dimensions — default to 240x320 for the portrait skin
        screen_width = 240
        screen_height = 320

        # Set the display resolution — matches Lua: Framework:setVideoMode(screenWidth, screenHeight, 16, jiveMain:isFullscreen())
        try:
            from jive.ui.framework import framework as _fw

            if _fw is not None:
                _fw.set_video_mode(240, 320, 0, False)
                sw, sh = _fw.get_screen_size()
                if sw > 0 and sh > 0:
                    screen_width, screen_height = sw, sh
        except Exception as exc:
            log.warning("skin init: failed to query initial video mode: %s", exc)

        if use_default_size or screen_width < 240 or screen_height < 320:
            screen_width = 240
            screen_height = 320

        try:
            from jive.ui.framework import framework as _fw

            if _fw is not None:
                try:
                    from jive.jive_main import jive_main as _jm

                    _fw.set_video_mode(
                        screen_width,
                        screen_height,
                        16,
                        _jm.is_fullscreen() if _jm is not None else False,
                    )
                except (ImportError, AttributeError):
                    _fw.set_video_mode(screen_width, screen_height, 16, False)
        except Exception as exc:
            log.warning("skin init: failed to set video mode: %s", exc)

        # Init lastInputType so selected item style is not shown on skin load
        try:
            from jive.ui.framework import framework as _fw

            if _fw is not None:
                _fw.most_recent_input_type = "scroll"  # type: ignore[attr-defined]
        except Exception as exc:
            log.warning("skin init: failed to set lastInputType on framework: %s", exc)

        # Almost all styles come directly from QVGAbaseSkinApplet
        QVGAbaseSkinApplet.skin(self, s, reload, use_default_size)

        # c is for constants
        c = s["CONSTANTS"]

        # ---------------------------------------------------------------
        # Styles specific to the portrait QVGA skin
        # ---------------------------------------------------------------

        # Scrollbar images
        s["img"]["scrollBackground"] = _tile_vtiles(
            [
                _IMGPATH + "Scroll_Bar/scrollbar_bkgrd_t.png",
                _IMGPATH + "Scroll_Bar/scrollbar_bkgrd.png",
                _IMGPATH + "Scroll_Bar/scrollbar_bkgrd_b.png",
            ]
        )

        s["img"]["scrollBar"] = _tile_vtiles(
            [
                _IMGPATH + "Scroll_Bar/scrollbar_body_t.png",
                _IMGPATH + "Scroll_Bar/scrollbar_body.png",
                _IMGPATH + "Scroll_Bar/scrollbar_body_b.png",
            ]
        )

        # Scrollbar style — portrait uses 6 items and narrower scrollbar
        s["scrollbar"] = {
            "w": 16,
            "h": c["PORTRAIT_LINE_ITEM_HEIGHT"] * 6 - 6,
            "border": [0, 4, 0, 0],
            "horizontal": 0,
            "bgImg": s["img"]["scrollBackground"],
            "img": s["img"]["scrollBar"],
            "layer": LAYER_CONTENT_ON_STAGE,
        }

        # Progress bar images
        s["img"]["progressBackground"] = _tile_image(
            _IMGPATH + "Alerts/alert_progress_bar_bkgrd.png"
        )
        s["img"]["progressBar"] = _tile_htiles(
            [
                None,
                _IMGPATH + "Alerts/alert_progress_bar_body.png",
            ]
        )

        # ---------------------------------------------------------------
        # Misc layout tweaks from base for portrait
        # ---------------------------------------------------------------
        s["title"]["h"] = 38
        s["menu"]["border"] = [0, 38, 0, 0]
        s["icon_software_update"]["padding"] = [0, 22, 0, 0]
        s["icon_connecting"]["padding"] = [0, 52, 0, 0]
        s["icon_connected"]["padding"] = [0, 52, 0, 0]
        s["icon_restart"]["padding"] = [0, 52, 0, 0]
        s["icon_power"]["padding"] = [0, 47, 0, 0]
        s["icon_battery_low"]["padding"] = [0, 42, 0, 0]
        s["waiting_popup"]["text"]["padding"] = [0, 42, 0, 0]
        s["waiting_popup"]["subtext"]["padding"] = [0, 0, 0, 46]
        s["alarm_time"]["font"] = _font(72)

        s["toast_popup_mixed"]["text"]["font"] = _boldfont(14)
        s["toast_popup_mixed"]["subtext"]["font"] = _boldfont(14)

        # Slider popup (volume)
        s["slider_popup"]["x"] = 6
        s["slider_popup"]["y"] = 88
        s["slider_popup"]["w"] = screen_width - 12

        # Titlebar has to be 55px to also have 80px menu items in portrait
        # and have everything fit neatly
        s["multiline_text_list"]["title"]["h"] = 55
        s["multiline_text_list"]["menu"]["border"] = [0, 56, 0, 24]
        s["multiline_text_list"]["menu"]["scrollbar"]["h"] = (
            c["MULTILINE_LINE_ITEM_HEIGHT"] * 3 - 8
        )

        s["menu"]["itemHeight"] = c["PORTRAIT_LINE_ITEM_HEIGHT"]
        s["icon_list"]["menu"]["itemHeight"] = c["PORTRAIT_LINE_ITEM_HEIGHT"]
        # Bug 17104: change the padding in icon_list to 1 px top/bottom
        # (landscape is 2 px top/bottom)
        s["icon_list"]["menu"]["item"]["padding"] = [10, 1, 4, 1]

        # Hide alarm icon on controller status bar, no room
        s["iconbar_group"]["order"] = [
            "play",
            "repeat_mode",
            "shuffle",
            "sleep",
            "battery",
            "wireless",
        ]
        s["button_sleep_ON"]["w"] = WH_FILL
        s["button_sleep_ON"]["align"] = "right"
        s["button_sleep_OFF"]["w"] = WH_FILL
        s["button_sleep_OFF"]["align"] = "right"

        s["track_list"]["menu"]["scrollbar"] = _uses(
            s["scrollbar"],
            {
                "h": 41 * 6 - 8,
            },
        )

        # Track list window needs to be mostly redefined for portrait
        s["track_list"]["title"]["h"] = 50
        s["track_list"]["title"] = _uses(
            s["title"],
            {
                "h": 50,
                "order": ["icon", "text"],
                "padding": [10, 0, 0, 0],
                "icon": {
                    "w": 49,
                    "h": WH_FILL,
                },
                "text": {
                    "align": "top-left",
                    "font": _font(18),
                    "lineHeight": 19,
                    "line": [
                        {
                            "font": _boldfont(18),
                            "height": 20,
                        },
                        {
                            "font": _font(14),
                            "height": 16,
                        },
                    ],
                },
            },
        )
        s["track_list"]["menu"] = _uses(
            s["menu"],
            {
                "itemHeight": 41,
                "h": 6 * 41,
                "border": [0, 50, 0, 0],
            },
        )

        # Time input backgrounds
        s["time_input_background_12h"] = {
            "w": WH_FILL,
            "h": screen_height,
            "position": LAYOUT_NONE,
            "img": _tile_image(
                _BASE_IMGPATH + "Multi_Character_Entry/port_multi_char_bkgrd_3c.png"
            ),
            "x": 0,
            "y": c["TITLE_HEIGHT"],
        }
        s["time_input_background_24h"] = {
            "w": WH_FILL,
            "h": screen_height,
            "position": LAYOUT_NONE,
            "img": _tile_image(
                _BASE_IMGPATH + "Multi_Character_Entry/port_multi_char_bkgrd_2c.png"
            ),
            "x": 0,
            "y": c["TITLE_HEIGHT"],
        }

        # Time input windows
        s["input_time_12h"] = _uses(s["window"])
        s["input_time_12h"]["hour"] = _uses(
            s["menu"],
            {
                "w": 60,
                "h": screen_height - 60,
                "itemHeight": 50,
                "position": LAYOUT_WEST,
                "padding": 0,
                "border": [25, 36, 0, 24],
                "item": {
                    "bgImg": False,
                    "order": ["text"],
                    "text": {
                        "align": "right",
                        "font": _boldfont(21),
                        "padding": [0, 0, 12, 0],
                        "fg": [0xB3, 0xB3, 0xB3],
                    },
                },
                "selected": {
                    "item": {
                        "order": ["text"],
                        "bgImg": _tile_image(
                            _BASE_IMGPATH + "Menu_Lists/menu_box_50.png"
                        ),
                        "text": {
                            "font": _boldfont(24),
                            "fg": [0xE6, 0xE6, 0xE6],
                            "align": "right",
                            "padding": [0, 0, 12, 0],
                        },
                    },
                },
            },
        )
        s["input_time_12h"]["minute"] = _uses(
            s["input_time_12h"]["hour"],
            {
                "border": [25 + 65, 36, 0, 24],
            },
        )
        s["input_time_12h"]["ampm"] = _uses(
            s["input_time_12h"]["hour"],
            {
                "border": [25 + 65 + 65, 36, 0, 24],
                "item": {
                    "text": {
                        "padding": [0, 0, 8, 0],
                    },
                },
                "selected": {
                    "item": {
                        "text": {
                            "padding": [0, 0, 8, 0],
                        },
                    },
                },
            },
        )
        s["input_time_12h"]["hourUnselected"] = _uses(
            s["input_time_12h"]["hour"],
            {
                "item": {
                    "text": {
                        "fg": [0x66, 0x66, 0x66],
                        "font": _boldfont(21),
                    },
                },
                "selected": {
                    "item": {
                        "bgImg": False,
                        "text": {
                            "fg": [0x66, 0x66, 0x66],
                            "font": _boldfont(21),
                        },
                    },
                },
            },
        )
        s["input_time_12h"]["minuteUnselected"] = _uses(
            s["input_time_12h"]["minute"],
            {
                "item": {
                    "text": {
                        "fg": [0x66, 0x66, 0x66],
                        "font": _boldfont(21),
                    },
                },
                "selected": {
                    "item": {
                        "bgImg": False,
                        "text": {
                            "fg": [0x66, 0x66, 0x66],
                            "font": _boldfont(21),
                        },
                    },
                },
            },
        )
        s["input_time_12h"]["ampmUnselected"] = _uses(
            s["input_time_12h"]["ampm"],
            {
                "item": {
                    "text": {
                        "fg": [0x66, 0x66, 0x66],
                        "font": _boldfont(20),
                    },
                },
                "selected": {
                    "item": {
                        "bgImg": False,
                        "text": {
                            "fg": [0x66, 0x66, 0x66],
                            "font": _boldfont(20),
                        },
                    },
                },
            },
        )

        s["input_time_24h"] = _uses(
            s["input_time_12h"],
            {
                "hour": {
                    "border": [58, 36, 0, 24],
                },
                "minute": {
                    "border": [58 + 65, 36, 0, 24],
                },
                "hourUnselected": {
                    "border": [58, 36, 0, 24],
                },
                "minuteUnselected": {
                    "border": [58 + 65, 36, 0, 24],
                },
            },
        )

        # Software update window
        s["update_popup"] = _uses(s["popup"])

        s["update_popup"]["text"] = {
            "w": WH_FILL,
            "h": (c["POPUP_TEXT_SIZE_1"] + 8) * 2,
            "position": LAYOUT_NORTH,
            "border": [0, 28, 0, 0],
            "padding": [12, 0, 12, 0],
            "align": "center",
            "font": _font(c["POPUP_TEXT_SIZE_1"]),
            "lineHeight": c["POPUP_TEXT_SIZE_1"] + 8,
            "fg": c["TEXT_COLOR"],
            "sh": c["TEXT_SH_COLOR"],
        }

        s["update_popup"]["subtext"] = {
            "w": WH_FILL,
            # note this is a hack as the height and padding push
            # the content out of the widget bounding box.
            "h": 30,
            "padding": [0, 0, 0, 36],
            "font": _boldfont(18),
            "fg": c["TEXT_COLOR"],
            "sh": c["TEXT_SH_COLOR"],
            "align": "bottom",
            "position": LAYOUT_SOUTH,
        }

        s["update_popup"]["progress"] = {
            "border": [12, 0, 12, 20],
            "position": LAYOUT_SOUTH,
            "horizontal": 1,
            "bgImg": s["img"]["progressBackground"],
            "img": s["img"]["progressBar"],
        }

        # Toast popup with icon only — position for 240x320
        s["toast_popup_icon"]["x"] = 54
        s["toast_popup_icon"]["y"] = 95

        # Context menu window
        s["context_menu"]["menu"]["h"] = c["CM_MENU_HEIGHT"] * 7
        s["context_menu"]["menu"]["scrollbar"]["h"] = c["CM_MENU_HEIGHT"] * 7 - 6
        s["context_menu"]["menu"]["scrollbar"]["border"] = [0, 4, 0, 4]
        s["context_menu"]["multiline_text"]["lineHeight"] = 21

        # ---------------------------------------------------------------
        # NowPlaying styles
        # ---------------------------------------------------------------

        NP_ARTISTALBUM_FONT_SIZE = 15
        NP_TRACK_FONT_SIZE = 21

        controlHeight = 38
        controlWidth = 45
        volumeBarWidth = 150
        buttonPadding = 0
        NP_TITLE_HEIGHT = 31
        NP_TRACKINFO_RIGHT_PADDING = 8

        _tracklayout = {
            "border": 0,
            "position": LAYOUT_NORTH,
            "w": WH_FILL,
            "align": "left",
            "lineHeight": NP_TRACK_FONT_SIZE,
            "fg": [0xE7, 0xE7, 0xE7],
        }

        _iconbarBorder = [3, 0, 3, 0]
        _playmodeBorder = [6, 0, 3, 0]
        _wirelessBorder = [3, 0, 6, 0]
        _sleepBorder = [6, 0, 3, 0]

        # Iconbar border overrides for portrait — use setdefault to
        # guard against missing keys when the base skin hasn't created
        # all iconbar styles (e.g. in headless / test environments).
        s.setdefault("_button_playmode", {})["border"] = _playmodeBorder
        for k in (
            "button_playmode_OFF",
            "button_playmode_STOP",
            "button_playmode_PLAY",
            "button_playmode_PAUSE",
        ):
            s.setdefault(k, {})["border"] = _playmodeBorder

        s.setdefault("_button_repeat", {})["border"] = _iconbarBorder
        for k in (
            "button_repeat_OFF",
            "button_repeat_0",
            "button_repeat_1",
            "button_repeat_2",
        ):
            s.setdefault(k, {})["border"] = _iconbarBorder

        s.setdefault("_button_shuffle", {})["border"] = _iconbarBorder
        for k in (
            "button_shuffle_OFF",
            "button_shuffle_0",
            "button_shuffle_1",
            "button_shuffle_2",
        ):
            s.setdefault(k, {})["border"] = _iconbarBorder

        s.setdefault("button_sleep_ON", {})["border"] = _sleepBorder
        s.setdefault("button_sleep_OFF", {})["border"] = _sleepBorder

        s.setdefault("_button_battery", {})["border"] = _iconbarBorder
        for k in (
            "button_battery_AC",
            "button_battery_CHARGING",
            "button_battery_0",
            "button_battery_1",
            "button_battery_2",
            "button_battery_3",
            "button_battery_4",
            "button_battery_NONE",
        ):
            s.setdefault(k, {})["border"] = _iconbarBorder

        s.setdefault("_button_wireless", {})["border"] = _wirelessBorder
        for k in (
            "button_wireless_1",
            "button_wireless_2",
            "button_wireless_3",
            "button_wireless_4",
            "button_wireless_ERROR",
            "button_wireless_SERVERERROR",
            "button_wireless_NONE",
        ):
            s.setdefault(k, {})["border"] = _wirelessBorder

        s["nowplaying"] = _uses(
            s["window"],
            {
                "bgImg": _fill_color(0x000000FF),
                "title": {
                    "zOrder": 9,
                    "h": 79,
                    "text": {
                        "hidden": 1,
                    },
                },
                # Song metadata
                "nptitle": {
                    "order": ["nptrack", "xofy"],
                    "border": _tracklayout["border"],
                    "position": _tracklayout["position"],
                    "zOrder": 10,
                    "nptrack": {
                        "w": _tracklayout["w"],
                        "align": _tracklayout["align"],
                        "lineHeight": _tracklayout["lineHeight"],
                        "fg": _tracklayout["fg"],
                        "padding": [10, 10, 2, 0],
                        "font": _boldfont(NP_TRACK_FONT_SIZE),
                    },
                    "xofy": {
                        "w": 48,
                        "align": "right",
                        "fg": _tracklayout["fg"],
                        "padding": [0, 10, NP_TRACKINFO_RIGHT_PADDING, 0],
                        "font": _font(14),
                    },
                    "xofySmall": {
                        "w": 48,
                        "align": "right",
                        "fg": _tracklayout["fg"],
                        "padding": [0, 10, NP_TRACKINFO_RIGHT_PADDING, 0],
                        "font": _font(10),
                    },
                },
                "npartistalbum": {
                    "zOrder": 10,
                    "border": _tracklayout["border"],
                    "position": _tracklayout["position"],
                    "w": _tracklayout["w"],
                    "align": _tracklayout["align"],
                    "lineHeight": _tracklayout["lineHeight"],
                    "fg": [0xB3, 0xB3, 0xB3],
                    "padding": [10, NP_TRACK_FONT_SIZE + 18, 10, 0],
                    "font": _font(NP_ARTISTALBUM_FONT_SIZE),
                },
                "nptrack": {"hidden": 1},
                "npalbumgroup": {"hidden": 1},
                "npartistgroup": {"hidden": 1},
                "npalbum": {"hidden": 1},
                "npartist": {"hidden": 1},
                "npvisu": {"hidden": 1},
                # Cover art
                "npartwork": {
                    "position": LAYOUT_WEST,
                    "zOrder": 1,
                    "w": WH_FILL,
                    "align": "center",
                    "artwork": {
                        "w": WH_FILL,
                        "align": "center",
                        "padding": [0, 79, 0, 0],
                        "img": False,
                    },
                },
                # Transport controls
                "npcontrols": {"hidden": 1},
                # Progress bar
                "npprogress": {
                    "zOrder": 10,
                    "position": LAYOUT_NORTH,
                    "padding": [10, 0, 10, 0],
                    "border": [0, 63, 0, 0],
                    "w": WH_FILL,
                    "order": ["elapsed", "slider", "remain"],
                    "elapsed": {
                        "zOrder": 10,
                        "font": _boldfont(12),
                        "fg": [0xB3, 0xB3, 0xB3],
                    },
                    "remain": {
                        "zOrder": 10,
                        "font": _boldfont(12),
                        "fg": [0xB3, 0xB3, 0xB3],
                    },
                    "elapsedSmall": {
                        "zOrder": 10,
                        "font": _boldfont(9),
                        "fg": [0xB3, 0xB3, 0xB3],
                    },
                    "remainSmall": {
                        "zOrder": 10,
                        "font": _boldfont(9),
                        "fg": [0xB3, 0xB3, 0xB3],
                    },
                    "npprogressB": {
                        "w": WH_FILL,
                        "align": "center",
                        "border": [10, 0, 10, 0],
                        "horizontal": 1,
                        "bgImg": s["img"]["songProgressBackground"],
                        "img": s["img"]["songProgressBar"],
                        "h": 15,
                    },
                },
                # Special style for when there shouldn't be a progress bar
                # (e.g., internet radio streams)
                "npprogressNB": {
                    "zOrder": 10,
                    "position": LAYOUT_NORTH,
                    "padding": [10, 0, 0, 0],
                    "border": [0, 63, 0, 0],
                    "align": "center",
                    "w": WH_FILL,
                    "order": ["elapsed"],
                    "elapsed": {
                        "w": WH_FILL,
                        "align": "left",
                        "font": _boldfont(12),
                        "fg": [0xB3, 0xB3, 0xB3],
                    },
                },
            },
        )

        s["nowplaying"]["npprogressNB"]["elapsedSmall"] = s["nowplaying"][
            "npprogressNB"
        ]["elapsed"]

        s["nowplaying_small_art"] = _uses(
            s["nowplaying"],
            {
                "bgImg": False,
                "npartwork": {
                    "position": LAYOUT_NORTH,
                    "artwork": {
                        "padding": [0, 88, 0, 0],
                    },
                },
            },
        )

        s["nowplaying"]["pressed"] = s["nowplaying"]
        s["nowplaying_small_art"]["pressed"] = s["nowplaying_small_art"]

        # Sliders — disabled progress bar variant
        s["nowplaying"]["npprogress"]["npprogressB_disabled"] = _uses(
            s["nowplaying"]["npprogress"]["npprogressB"]
        )

        s["npvolumeB"] = {"hidden": 1}
        s["npvolumeB_disabled"] = {"hidden": 1}

        # Line in is the same as s.nowplaying but with transparent background
        s["linein"] = _uses(
            s["nowplaying"],
            {
                "bgImg": False,
            },
        )

        return s

    # ------------------------------------------------------------------
    # free
    # ------------------------------------------------------------------

    def free(self) -> bool:
        """Free resources when unloading the skin.

        On desktop (non-hardware) systems the parent module is reloaded
        so that a fresh copy of the base skin is available.
        """
        desktop = True
        try:
            from jive.applet_manager import applet_manager as _mgr

            if _mgr is not None and hasattr(_mgr, "system") and _mgr.system is not None:
                desktop = not _mgr.system.is_hardware()
        except (ImportError, AttributeError, TypeError):
            desktop = True

        if desktop:
            log.warn("reload parent")

        self.images = {}
        return True
