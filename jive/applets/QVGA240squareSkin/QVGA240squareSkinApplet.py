"""
jive.applets.QVGA240squareSkin.QVGA240squareSkinApplet --- QVGA240squareSkin applet.

Ported from ``share/jive/applets/QVGA240squareSkin/QVGA240squareSkinApplet.lua``
(~380 LOC) in the original jivelite project.

This applet implements the skin for a 240x240 square display, such as
the Pirate Audio boards for the Raspberry Pi.  It inherits from
QVGAbaseSkinApplet and overrides a small number of styles for the
square form factor.

Key implementation notes
------------------------

* Inherits the complete QVGA base skin via
  ``QVGAbaseSkinApplet.skin()``, then applies square-specific
  overrides (scrollbar, progress bar, NowPlaying layout, etc.).

* Default screen size is 240x240 (instead of the base 320x240).

* NowPlaying styles are simplified for the small square display:
  full-screen artwork with overlaid track info.

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

__all__ = ["QVGA240squareSkinApplet"]

log = logger("applet.QVGA240squareSkin")

# ---------------------------------------------------------------------------
# Image path prefixes
# ---------------------------------------------------------------------------
_IMGPATH = "applets/QVGA240squareSkin/images/"
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
    """Return a lazy reference to an image in the QVGA240squareSkin images dir."""
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
# QVGA240squareSkinApplet
# ============================================================================


class QVGA240squareSkinApplet(QVGAbaseSkinApplet):
    """Skin applet for 240x240 square displays (Pirate Audio, etc.).

    Inherits the complete QVGA base skin and overrides styles specific
    to the square form factor.
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
        """Return skin parameter constants for the 240x240 square skin."""
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
                    "artworkSize": "143x143",
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
        """Populate *s* with 240x240-square-specific style overrides.

        Parameters
        ----------
        s:
            The style dict to populate.
        reload:
            ``True`` when the skin is being reloaded (not first load).
        use_default_size:
            ``True`` to use the default 240x240 screen size instead of
            querying the framework.

        Returns
        -------
        Style
            The populated style dict *s*.
        """
        # Screen dimensions --- default to 240x240 for the square skin
        screen_width = 240
        screen_height = 240

        # Set the display resolution — matches Lua: Framework:setVideoMode(screenWidth, screenHeight, 16, jiveMain:isFullscreen())
        try:
            from jive.ui.framework import framework as _fw

            if _fw is not None:
                _fw.set_video_mode(240, 240, 0, False)
                sw, sh = _fw.get_screen_size()
                if sw > 0 and sh > 0:
                    screen_width, screen_height = sw, sh
        except Exception as exc:
            log.warning("skin init: failed to query initial video mode: %s", exc)

        if use_default_size or screen_width < 240 or screen_height < 240:
            screen_width = 240
            screen_height = 240

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
        # Styles specific to the square QVGA skin
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

        # Scrollbar style
        s["scrollbar"] = {
            "w": 20,
            "h": c["LANDSCAPE_LINE_ITEM_HEIGHT"] * 4 - 8,
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

        # track_list scrollbar override
        s["track_list"]["menu"]["scrollbar"] = _uses(
            s["scrollbar"],
            {
                "h": 41 * 4 - 8,
            },
        )

        # Software update window
        s["update_popup"] = _uses(s["popup"])

        s["update_popup"]["text"] = {
            "w": WH_FILL,
            "h": (c["POPUP_TEXT_SIZE_1"] + 8) * 2,
            "position": LAYOUT_NORTH,
            "border": [0, 14, 0, 0],
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
            "font": _boldfont(c["UPDATE_SUBTEXT_SIZE"]),
            "fg": c["TEXT_COLOR"],
            "sh": c["TEXT_SH_COLOR"],
            "align": "bottom",
            "position": LAYOUT_SOUTH,
        }

        s["update_popup"]["progress"] = {
            "border": [12, 0, 12, 12],
            "position": LAYOUT_SOUTH,
            "horizontal": 1,
            "bgImg": s["img"]["progressBackground"],
            "img": s["img"]["progressBar"],
        }

        # Toast popup with icon only --- position for 240x240
        s["toast_popup_icon"]["x"] = 54
        s["toast_popup_icon"]["y"] = 54

        # ---------------------------------------------------------------
        # NowPlaying styles
        # ---------------------------------------------------------------

        NP_ARTISTALBUM_FONT_SIZE = 18
        NP_TRACK_FONT_SIZE = 21

        controlHeight = 38
        controlWidth = 45
        volumeBarWidth = 150
        buttonPadding = 0
        NP_TITLE_HEIGHT = 31
        NP_TRACKINFO_RIGHT_PADDING = 40

        _tracklayout = {
            "position": LAYOUT_NORTH,
            "w": WH_FILL,
            "align": "left",
            "lineHeight": NP_TRACK_FONT_SIZE,
            "fg": [0xE7, 0xE7, 0xE7],
        }

        s["nowplaying"] = _uses(
            s["window"],
            {
                "bgImg": _fill_color(0x000000FF),
                "title": {
                    "zOrder": 9,
                    "h": 60,
                    "text": {
                        "hidden": 1,
                    },
                },
                # Song metadata
                "nptitle": {
                    "zOrder": 10,
                    "order": ["nptrack", "xofy"],
                    "position": _tracklayout["position"],
                    "nptrack": {
                        "padding": [10, 10, 2, 0],
                        "w": WH_FILL,
                        "align": _tracklayout["align"],
                        "lineHeight": _tracklayout["lineHeight"],
                        "fg": _tracklayout["fg"],
                        "font": _boldfont(NP_TRACK_FONT_SIZE),
                    },
                    "xofy": {
                        "padding": [0, 10, 10, 0],
                        "position": _tracklayout["position"],
                        "w": 50,
                        "align": "right",
                        "fg": _tracklayout["fg"],
                        "font": _font(14),
                    },
                    "xofySmall": {
                        "padding": [0, 10, 10, 0],
                        "position": _tracklayout["position"],
                        "w": 50,
                        "align": "right",
                        "fg": _tracklayout["fg"],
                        "font": _font(10),
                    },
                },
                "npartistalbum": {
                    "zOrder": 10,
                    "position": _tracklayout["position"],
                    "w": _tracklayout["w"],
                    "align": _tracklayout["align"],
                    "lineHeight": _tracklayout["lineHeight"],
                    "fg": [0xB3, 0xB3, 0xB3],
                    "padding": [10, NP_TRACK_FONT_SIZE + 14, 10, 0],
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
                    "position": LAYOUT_NORTH,
                    "w": WH_FILL,
                    "align": "center",
                    "artwork": {
                        "zOrder": 1,
                        "w": WH_FILL,
                        "align": "center",
                        "img": False,
                    },
                },
                # Transport controls
                "npcontrols": {"hidden": 1},
                # Progress bar
                "npprogress": {
                    "zOrder": 10,
                    "position": LAYOUT_NORTH,
                    "padding": [0, 0, 0, 0],
                    "border": [0, 59, 0, 0],
                    "w": WH_FILL,
                    "order": ["slider"],
                    "npprogressB": {
                        "w": screen_width,
                        "align": "center",
                        "horizontal": 1,
                        "bgImg": s["img"]["songProgressBackground"],
                        "img": s["img"]["songProgressBar"],
                        "h": 15,
                        "padding": [0, 0, 0, 15],
                    },
                },
                # Special style for when there shouldn't be a progress bar
                # (e.g., internet radio streams)
                "npprogressNB": {
                    "hidden": 1,
                },
            },
        )

        s["nowplaying"]["npprogress"]["npprogressB_disabled"] = _uses(
            s["nowplaying"]["npprogress"]["npprogressB"]
        )

        # NowPlaying small art variant
        s["nowplaying_small_art"] = _uses(
            s["nowplaying"],
            {
                "title": {
                    "h": 60,
                },
                "bgImg": False,
                "npartwork": {
                    "position": LAYOUT_NORTH,
                    "artwork": {
                        "padding": [0, 66, 0, 0],
                    },
                },
            },
        )

        s["nowplaying"]["pressed"] = s["nowplaying"]
        s["nowplaying_small_art"]["pressed"] = s["nowplaying_small_art"]

        # Line in window is the same as nowplaying but with transparent
        # background
        s["linein"] = _uses(
            s["nowplaying"],
            {
                "bgImg": False,
            },
        )

        # Sliders --- hidden on the square skin
        s["npvolumeB"] = {"hidden": 1}
        s["npvolumeB_disabled"] = {"hidden": 1}

        # Photo loading icon
        s["icon_photo_loading"] = _uses(
            s["_icon"],
            {
                "img": _load_base_image("Icons/image_viewer_loading.png"),
                "padding": [5, 5, 0, 5],
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
