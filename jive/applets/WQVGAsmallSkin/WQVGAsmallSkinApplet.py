"""
jive.applets.WQVGAsmallSkin.WQVGAsmallSkinApplet --- WQVGAsmallSkin applet.

Ported from ``share/jive/applets/WQVGAsmallSkin/WQVGAsmallSkinApplet.lua``
(~3492 LOC) in the original jivelite project.

This applet implements a small-print skin for 480x272 resolution displays.
It is a standalone skin that inherits directly from Applet and builds the
complete style table from scratch.

Key implementation notes
------------------------

* Standalone skin — does NOT inherit from QVGAbaseSkin or JogglerSkin.
* Default screen size is 480x272.
* Touch-oriented UI with 5-line item lists and toolbar controls.
* NowPlaying styles include art+text, art-only, text-only,
  spectrum analyzer, and analog VU meter variants.

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Copyright 2013-2014 Adrian Smith (jivelite amendments)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

import copy
import math
from typing import (
    Any,
    Dict,
    List,
    Optional,
    Sequence,
    Tuple,
    Union,
)

from jive.applet import Applet
from jive.utils.log import logger

__all__ = ["WQVGAsmallSkinApplet"]

log = logger("applet.WQVGAsmallSkin")

# ---------------------------------------------------------------------------
# Type alias for style dicts
# ---------------------------------------------------------------------------
Style = Dict[str, Any]

# ---------------------------------------------------------------------------
# Image / font path prefixes (relative to search path)
# ---------------------------------------------------------------------------
_IMGPATH = "applets/WQVGAsmallSkin/images/"
_FONTPATH = "fonts/"
_FONT_NAME = "FreeSans"
_BOLD_PREFIX = "Bold"

# ---------------------------------------------------------------------------
# UI Constants (matching jive.ui.constants values used as strings in styles)
# ---------------------------------------------------------------------------
LAYER_FRAME = "LAYER_FRAME"
LAYER_CONTENT_ON_STAGE = "LAYER_CONTENT_ON_STAGE"
LAYER_TITLE = "LAYER_TITLE"

LAYOUT_NORTH = "LAYOUT_NORTH"
LAYOUT_EAST = "LAYOUT_EAST"
LAYOUT_SOUTH = "LAYOUT_SOUTH"
LAYOUT_WEST = "LAYOUT_WEST"
LAYOUT_CENTER = "LAYOUT_CENTER"
LAYOUT_NONE = "LAYOUT_NONE"

WH_FILL = 65534  # sentinel matching jive.ui.constants.WH_FILL


# ---------------------------------------------------------------------------
# Helper: deep-merge style dicts (Lua _uses equivalent)
# ---------------------------------------------------------------------------


def _uses(parent: Optional[Style], overrides: Optional[Style] = None) -> Style:
    """Create a new style dict that inherits from *parent*.

    Deep-copies *parent* and recursively merges *overrides*.
    """
    if parent is None:
        log.warn("_uses called with None parent")
        parent = {}

    style: Style = copy.deepcopy(parent)

    if overrides is None:
        return style

    for k, v in overrides.items():
        if isinstance(v, dict) and isinstance(style.get(k), dict):
            style[k] = _uses(style[k], v)
        else:
            style[k] = copy.deepcopy(v) if isinstance(v, dict) else v

    return style


# ---------------------------------------------------------------------------
# Lazy image/tile/font loaders
# ---------------------------------------------------------------------------


def _img(path: str) -> Style:
    """Return a lazy-loadable image reference."""
    return {"__type__": "image", "path": path}


def _load_image(file: str) -> Style:
    """Return a lazy reference to an image in the WQVGAsmallSkin images dir."""
    return _img(_IMGPATH + file)


def _tile_image(path: str) -> Style:
    """Return a lazy-loadable single-image tile reference."""
    return {"__type__": "tile_image", "path": path}


def _tile_vtiles(paths: Sequence[Optional[str]]) -> Style:
    """Return a lazy-loadable vertical 3-patch tile reference."""
    return {"__type__": "tile_vtiles", "paths": list(paths)}


def _tile_htiles(paths: Sequence[Optional[str]]) -> Style:
    """Return a lazy-loadable horizontal 3-patch tile reference."""
    return {"__type__": "tile_htiles", "paths": list(paths)}


def _tile_9patch(paths: Sequence[Optional[str]]) -> Style:
    """Return a lazy-loadable 9-patch tile reference."""
    return {"__type__": "tile_9patch", "paths": list(paths)}


def _fill_color(color: int) -> Style:
    """Return a lazy-loadable fill-colour tile reference."""
    return {"__type__": "tile_fill", "color": color}


def _font(size: int) -> Style:
    """Return a lazy-loadable font reference (regular weight)."""
    return {
        "__type__": "font",
        "path": _FONTPATH + _FONT_NAME + ".ttf",
        "size": size,
    }


def _boldfont(size: int) -> Style:
    """Return a lazy-loadable font reference (bold weight)."""
    return {
        "__type__": "font",
        "path": _FONTPATH + _FONT_NAME + _BOLD_PREFIX + ".ttf",
        "size": size,
    }


def _icon_dict(x: int, y: int, img_file: str) -> Style:
    """Build an icon style dict (matches Lua ``_icon`` helper)."""
    return {
        "x": x,
        "y": y,
        "img": _load_image(img_file),
        "layer": LAYER_FRAME,
        "position": LAYOUT_SOUTH,
    }


# ============================================================================
# WQVGAsmallSkinApplet
# ============================================================================


class WQVGAsmallSkinApplet(Applet):
    """Skin applet for 480x272 small-print displays.

    Standalone skin that builds the complete style table from scratch.
    """

    def __init__(self) -> None:
        super().__init__()
        self.images: Style = {}
        self.imageTiles: Style = {}
        self.hTiles: Style = {}
        self.vTiles: Style = {}
        self.tiles: Style = {}

    def init(self) -> None:
        """Initialise the applet (lifecycle hook)."""
        self.images = {}
        self.imageTiles = {}
        self.hTiles = {}
        self.vTiles = {}
        self.tiles = {}

    # ------------------------------------------------------------------
    # Parameters
    # ------------------------------------------------------------------

    def param(self) -> Style:
        """Return skin parameter constants for the 480x272 small-print skin."""
        return {
            "THUMB_SIZE": 40,
            "THUMB_SIZE_MENU": 40,
            "NOWPLAYING_MENU": False,
            "NOWPLAYING_TRACKINFO_LINES": 3,
            "POPUP_THUMB_SIZE": 120,
            "radialClock": {
                "hourTickPath": _IMGPATH + "Clocks/Radial/radial_ticks_hr_on.png",
                "minuteTickPath": _IMGPATH + "Clocks/Radial/radial_ticks_min_on.png",
            },
            "nowPlayingScreenStyles": [
                # every skin needs to start off with a nowplaying style
                {
                    "style": "nowplaying",
                    "artworkSize": "180x180",
                    "text": self.string("ART_AND_TEXT"),
                },
                {
                    "style": "nowplaying_art_only",
                    "artworkSize": "470x262",
                    "suppressTitlebar": 1,
                    "text": self.string("ART_ONLY"),
                },
                {
                    "style": "nowplaying_text_only",
                    "artworkSize": "180x180",
                    "text": self.string("TEXT_ONLY"),
                },
                {
                    "style": "nowplaying_spectrum_text",
                    "artworkSize": "180x180",
                    "localPlayerOnly": 1,
                    "text": self.string("SPECTRUM_ANALYZER"),
                },
                {
                    "style": "nowplaying_vuanalog_text",
                    "artworkSize": "180x180",
                    "localPlayerOnly": 1,
                    "text": self.string("ANALOG_VU_METER"),
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
        """Populate *s* with the complete WQVGAsmallSkin style table.

        Parameters
        ----------
        s:
            The style dict to populate.
        reload:
            ``True`` when the skin is being reloaded (not first load).
        use_default_size:
            ``True`` to use the default 480x272 screen size instead of
            querying the framework.

        Returns
        -------
        Style
            The populated style dict *s*.
        """
        screen_width = 480
        screen_height = 272

        # Set the display resolution — matches Lua: Framework:setVideoMode(480, 272, 0, false)
        try:
            from jive.ui.framework import framework as _fw

            if _fw is not None:
                _fw.set_video_mode(480, 272, 0, False)
                sw, sh = _fw.get_screen_size()
                if sw > 0 and sh > 0:
                    screen_width, screen_height = sw, sh
        except Exception as exc:
            log.warning(
                "WQVGAsmallSkin: failed to set initial video mode (480x272): %s", exc
            )

        if use_default_size:
            screen_width = 480
            screen_height = 272

        try:
            from jive.ui.framework import framework as _fw

            if _fw is not None:
                _fw.set_video_mode(screen_width, screen_height, 0, False)
        except Exception as exc:
            log.warning(
                "WQVGAsmallSkin: failed to set video mode (%sx%s): %s",
                screen_width,
                screen_height,
                exc,
            )

        # Init lastInputType so selected item style is not shown on skin load
        try:
            from jive.ui.framework import framework as _fw

            if _fw is not None:
                _fw.most_recent_input_type = "mouse"  # type: ignore[attr-defined]
        except Exception as exc:
            log.debug("WQVGAsmallSkin: failed to set most_recent_input_type: %s", exc)

        imgpath = _IMGPATH

        # skin suffix
        thisSkin = "touch"
        skinSuffix = "_" + thisSkin + ".png"

        # ---------------------------------------------------------------
        # Image and Tile references
        # ---------------------------------------------------------------
        inputTitleBox = _tile_image(imgpath + "Titlebar/titlebar.png")
        backButton = _tile_image(imgpath + "Icons/icon_back_button_tb.png")
        cancelButton = _tile_image(imgpath + "Icons/icon_close_button_tb.png")
        homeButton = _tile_image(imgpath + "Icons/icon_home_button_tb.png")
        helpButton = _tile_image(imgpath + "Icons/icon_help_button_tb.png")
        powerButton = _tile_image(imgpath + "Icons/icon_power_button_tb.png")
        nowPlayingButton = _tile_image(imgpath + "Icons/icon_nplay_button_tb.png")
        playlistButton = _tile_image(imgpath + "Icons/icon_nplay_list_tb.png")
        moreButton = _tile_image(imgpath + "Icons/icon_more_tb.png")
        touchToolbarBackground = _tile_image(
            imgpath + "Touch_Toolbar/toolbar_tch_bkgrd.png"
        )
        sliderBackground = _tile_image(imgpath + "Touch_Toolbar/toolbar_lrg.png")
        touchToolbarKeyDivider = _tile_image(
            imgpath + "Touch_Toolbar/toolbar_divider.png"
        )
        deleteKeyBackground = _tile_image(
            imgpath + "Buttons/button_delete_text_entry.png"
        )
        deleteKeyPressedBackground = _tile_image(
            imgpath + "Buttons/button_delete_text_entry_press.png"
        )
        helpTextBackground = _tile_image(imgpath + "Titlebar/tbar_dropdwn_bkrgd.png")

        blackBackground = _fill_color(0x000000FF)
        nocturneWallpaper = _tile_image(
            "applets/SetupWallpaper/wallpaper/fab4_nocturne.png"
        )

        fiveItemBox = _tile_htiles(
            [
                imgpath + "5_line_lists/tch_5line_divider_l.png",
                imgpath + "5_line_lists/tch_5line_divider.png",
                imgpath + "5_line_lists/tch_5line_divider_r.png",
            ]
        )
        fiveItemSelectionBox = _tile_htiles(
            [
                None,
                imgpath + "5_line_lists/menu_sel_box_5line.png",
                imgpath + "5_line_lists/menu_sel_box_5line_r.png",
            ]
        )
        fiveItemPressedBox = _tile_htiles(
            [
                None,
                imgpath + "5_line_lists/menu_sel_box_5line_press.png",
                imgpath + "5_line_lists/menu_sel_box_5line_press_r.png",
            ]
        )

        threeItemSelectionBox = _tile_htiles(
            [
                imgpath + "3_line_lists/menu_sel_box_3line_l.png",
                imgpath + "3_line_lists/menu_sel_box_3line.png",
                imgpath + "3_line_lists/menu_sel_box_3line_r.png",
            ]
        )
        threeItemPressedBox = _tile_image(
            imgpath + "3_line_lists/menu_sel_box_3item_press.png"
        )

        contextMenuPressedBox = _tile_9patch(
            [
                imgpath + "Popup_Menu/button_cm_press.png",
                imgpath + "Popup_Menu/button_cm_tl_press.png",
                imgpath + "Popup_Menu/button_cm_t_press.png",
                imgpath + "Popup_Menu/button_cm_tr_press.png",
                imgpath + "Popup_Menu/button_cm_r_press.png",
                imgpath + "Popup_Menu/button_cm_br_press.png",
                imgpath + "Popup_Menu/button_cm_b_press.png",
                imgpath + "Popup_Menu/button_cm_bl_press.png",
                imgpath + "Popup_Menu/button_cm_l_press.png",
            ]
        )

        titleBox = _tile_9patch(
            [
                imgpath + "Titlebar/titlebar.png",
                None,
                None,
                None,
                None,
                None,
                imgpath + "Titlebar/titlebar_shadow.png",
                None,
                None,
            ]
        )

        textinputBackground = _tile_9patch(
            [
                imgpath + "Text_Entry/Keyboard_Touch/titlebar_box.png",
                imgpath + "Text_Entry/Keyboard_Touch/text_entry_titlebar_box_tl.png",
                imgpath + "Text_Entry/Keyboard_Touch/text_entry_titlebar_box_t.png",
                imgpath + "Text_Entry/Keyboard_Touch/text_entry_titlebar_box_tr.png",
                imgpath + "Text_Entry/Keyboard_Touch/text_entry_titlebar_box_r.png",
                imgpath + "Text_Entry/Keyboard_Touch/text_entry_titlebar_box_br.png",
                imgpath + "Text_Entry/Keyboard_Touch/text_entry_titlebar_box_b.png",
                imgpath + "Text_Entry/Keyboard_Touch/text_entry_titlebar_box_bl.png",
                imgpath + "Text_Entry/Keyboard_Touch/text_entry_titlebar_box_l.png",
            ]
        )

        pressedTitlebarButtonBox = _tile_9patch(
            [
                imgpath + "Buttons/button_titlebar_press.png",
                imgpath + "Buttons/button_titlebar_tl_press.png",
                imgpath + "Buttons/button_titlebar_t_press.png",
                imgpath + "Buttons/button_titlebar_tr_press.png",
                imgpath + "Buttons/button_titlebar_r_press.png",
                imgpath + "Buttons/button_titlebar_br_press.png",
                imgpath + "Buttons/button_titlebar_b_press.png",
                imgpath + "Buttons/button_titlebar_bl_press.png",
                imgpath + "Buttons/button_titlebar_l_press.png",
            ]
        )

        titlebarButtonBox = _tile_9patch(
            [
                imgpath + "Buttons/button_titlebar.png",
                imgpath + "Buttons/button_titlebar_tl.png",
                imgpath + "Buttons/button_titlebar_t.png",
                imgpath + "Buttons/button_titlebar_tr.png",
                imgpath + "Buttons/button_titlebar_r.png",
                imgpath + "Buttons/button_titlebar_br.png",
                imgpath + "Buttons/button_titlebar_b.png",
                imgpath + "Buttons/button_titlebar_bl.png",
                imgpath + "Buttons/button_titlebar_l.png",
            ]
        )

        popupBox = _tile_9patch(
            [
                imgpath + "Popup_Menu/popup_box.png",
                imgpath + "Popup_Menu/popup_box_tl.png",
                imgpath + "Popup_Menu/popup_box_t.png",
                imgpath + "Popup_Menu/popup_box_tr.png",
                imgpath + "Popup_Menu/popup_box_r.png",
                imgpath + "Popup_Menu/popup_box_br.png",
                imgpath + "Popup_Menu/popup_box_b.png",
                imgpath + "Popup_Menu/popup_box_bl.png",
                imgpath + "Popup_Menu/popup_box_l.png",
            ]
        )

        contextMenuBox = _tile_9patch(
            [
                imgpath + "Popup_Menu/cm_popup_box.png",
                imgpath + "Popup_Menu/cm_popup_box_tl.png",
                imgpath + "Popup_Menu/cm_popup_box_t.png",
                imgpath + "Popup_Menu/cm_popup_box_tr.png",
                imgpath + "Popup_Menu/cm_popup_box_r.png",
                imgpath + "Popup_Menu/cm_popup_box_br.png",
                imgpath + "Popup_Menu/cm_popup_box_b.png",
                imgpath + "Popup_Menu/cm_popup_box_bl.png",
                imgpath + "Popup_Menu/cm_popup_box_l.png",
            ]
        )

        scrollBackground = _tile_vtiles(
            [
                imgpath + "Scroll_Bar/scrollbar_bkgrd_t.png",
                imgpath + "Scroll_Bar/scrollbar_bkgrd.png",
                imgpath + "Scroll_Bar/scrollbar_bkgrd_b.png",
            ]
        )

        scrollBar = _tile_vtiles(
            [
                imgpath + "Scroll_Bar/scrollbar_body_t.png",
                imgpath + "Scroll_Bar/scrollbar_body.png",
                imgpath + "Scroll_Bar/scrollbar_body_b.png",
            ]
        )

        popupBackground = _fill_color(0x000000FF)

        textinputCursor = _tile_image(
            imgpath + "Text_Entry/Keyboard_Touch/tch_cursor.png"
        )

        # ---------------------------------------------------------------
        # Constants
        # ---------------------------------------------------------------
        THUMB_SIZE = self.param()["THUMB_SIZE"]

        TITLE_PADDING = [0, 15, 0, 15]
        CHECK_PADDING = [2, 0, 6, 0]
        CHECKBOX_RADIO_PADDING = [2, 0, 0, 0]

        MENU_ITEM_ICON_PADDING = [0, 0, 8, 0]
        MENU_PLAYLISTITEM_TEXT_PADDING = [16, 1, 9, 1]
        MENU_CURRENTALBUM_TEXT_PADDING = [6, 20, 0, 10]
        TEXTAREA_PADDING = [13, 8, 8, 0]

        TEXT_COLOR = [0xE7, 0xE7, 0xE7]
        TEXT_COLOR_BLACK = [0x00, 0x00, 0x00]
        TEXT_SH_COLOR = [0x37, 0x37, 0x37]
        TEXT_COLOR_TEAL = [0, 0xBE, 0xBE]

        SELECT_COLOR = [0xE7, 0xE7, 0xE7]
        SELECT_SH_COLOR: List[int] = []

        TITLE_HEIGHT = 47
        TITLE_FONT_SIZE = 20
        ALBUMMENU_FONT_SIZE = 18
        ALBUMMENU_SMALL_FONT_SIZE = 14
        TEXTMENU_FONT_SIZE = 20
        POPUP_TEXT_SIZE_1 = 34
        POPUP_TEXT_SIZE_2 = 26
        TRACK_FONT_SIZE = 18
        TEXTAREA_FONT_SIZE = 18
        CENTERED_TEXTAREA_FONT_SIZE = 28

        CM_MENU_HEIGHT = 45

        TEXTINPUT_FONT_SIZE = 20
        TEXTINPUT_SELECTED_FONT_SIZE = 24

        HELP_FONT_SIZE = 18
        UPDATE_SUBTEXT_SIZE = 20

        ITEM_ICON_ALIGN = "center"
        ITEM_LEFT_PADDING = 12
        THREE_ITEM_HEIGHT = 72
        FIVE_ITEM_HEIGHT = 45
        TITLE_BUTTON_WIDTH = 76

        smallSpinny = {
            "img": _load_image("Alerts/wifi_connecting_sm.png"),
            "frameRate": 8,
            "frameWidth": 26,
            "padding": 0,
            "h": WH_FILL,
        }
        largeSpinny = {
            "img": _load_image("Alerts/wifi_connecting.png"),
            "position": LAYOUT_CENTER,
            "w": WH_FILL,
            "align": "center",
            "frameRate": 8,
            "frameWidth": 120,
            "padding": [0, 0, 0, 10],
        }

        noButton = {"img": False, "bgImg": False, "w": 0}

        playArrow = {
            "img": _load_image("Icons/selection_play_3line_on.png"),
        }
        addArrow = {
            "img": _load_image("Icons/selection_add_3line_on.png"),
        }
        favItem = {
            "img": _load_image("Icons/icon_toolbar_fav.png"),
        }

        # ---------------------------------------------------------------
        # Progress bar references
        # ---------------------------------------------------------------
        _progressBackground = _tile_image(
            imgpath + "Alerts/alert_progress_bar_bkgrd.png"
        )
        _progressBar = _tile_htiles(
            [
                None,
                imgpath + "Alerts/alert_progress_bar_body.png",
            ]
        )

        _songProgressBackground = _tile_htiles(
            [
                imgpath + "Song_Progress_Bar/SP_Bar_Touch/tch_progressbar_bkgrd_l.png",
                imgpath + "Song_Progress_Bar/SP_Bar_Touch/tch_progressbar_bkgrd.png",
                imgpath + "Song_Progress_Bar/SP_Bar_Touch/tch_progressbar_bkgrd_r.png",
            ]
        )
        _songProgressBar = _tile_htiles(
            [
                None,
                None,
                imgpath + "Song_Progress_Bar/SP_Bar_Touch/tch_progressbar_slider.png",
            ]
        )
        _songProgressBarDisabled = _tile_htiles(
            [
                None,
                None,
                imgpath + "Song_Progress_Bar/SP_Bar_Remote/rem_progressbar_slider.png",
            ]
        )

        _volumeSliderBackground = _tile_htiles(
            [
                imgpath + "Touch_Toolbar/tch_volumebar_bkgrd_l.png",
                imgpath + "Touch_Toolbar/tch_volumebar_bkgrd.png",
                imgpath + "Touch_Toolbar/tch_volumebar_bkgrd_r.png",
            ]
        )
        _volumeSliderBar = _tile_htiles(
            [
                imgpath + "UNOFFICIAL/tch_volumebar_fill_l.png",
                imgpath + "UNOFFICIAL/tch_volumebar_fill.png",
                imgpath + "UNOFFICIAL/tch_volumebar_fill_r.png",
            ]
        )
        _volumeSliderPill = _tile_image(imgpath + "Touch_Toolbar/tch_volume_slider.png")
        _popupSliderBar = _tile_htiles(
            [
                imgpath + "Touch_Toolbar/tch_volumebar_fill_l.png",
                imgpath + "Touch_Toolbar/tch_volumebar_fill.png",
                imgpath + "Touch_Toolbar/tch_volumebar_fill_r.png",
            ]
        )

        # ---------------------------------------------------------------
        # Store constants in style dict for child skins
        # ---------------------------------------------------------------
        s["CONSTANTS"] = {
            "THUMB_SIZE": THUMB_SIZE,
            "TITLE_HEIGHT": TITLE_HEIGHT,
            "TITLE_FONT_SIZE": TITLE_FONT_SIZE,
            "ALBUMMENU_FONT_SIZE": ALBUMMENU_FONT_SIZE,
            "ALBUMMENU_SMALL_FONT_SIZE": ALBUMMENU_SMALL_FONT_SIZE,
            "TEXTMENU_FONT_SIZE": TEXTMENU_FONT_SIZE,
            "POPUP_TEXT_SIZE_1": POPUP_TEXT_SIZE_1,
            "POPUP_TEXT_SIZE_2": POPUP_TEXT_SIZE_2,
            "TRACK_FONT_SIZE": TRACK_FONT_SIZE,
            "TEXTAREA_FONT_SIZE": TEXTAREA_FONT_SIZE,
            "CENTERED_TEXTAREA_FONT_SIZE": CENTERED_TEXTAREA_FONT_SIZE,
            "CM_MENU_HEIGHT": CM_MENU_HEIGHT,
            "TEXTINPUT_FONT_SIZE": TEXTINPUT_FONT_SIZE,
            "TEXTINPUT_SELECTED_FONT_SIZE": TEXTINPUT_SELECTED_FONT_SIZE,
            "HELP_FONT_SIZE": HELP_FONT_SIZE,
            "UPDATE_SUBTEXT_SIZE": UPDATE_SUBTEXT_SIZE,
            "ITEM_ICON_ALIGN": ITEM_ICON_ALIGN,
            "ITEM_LEFT_PADDING": ITEM_LEFT_PADDING,
            "THREE_ITEM_HEIGHT": THREE_ITEM_HEIGHT,
            "FIVE_ITEM_HEIGHT": FIVE_ITEM_HEIGHT,
            "TITLE_BUTTON_WIDTH": TITLE_BUTTON_WIDTH,
            "TEXT_COLOR": TEXT_COLOR,
            "TEXT_COLOR_BLACK": TEXT_COLOR_BLACK,
            "TEXT_SH_COLOR": TEXT_SH_COLOR,
            "TEXT_COLOR_TEAL": TEXT_COLOR_TEAL,
            "SELECT_COLOR": SELECT_COLOR,
            "SELECT_SH_COLOR": SELECT_SH_COLOR,
            "TITLE_PADDING": TITLE_PADDING,
            "CHECK_PADDING": CHECK_PADDING,
            "CHECKBOX_RADIO_PADDING": CHECKBOX_RADIO_PADDING,
            "MENU_ITEM_ICON_PADDING": MENU_ITEM_ICON_PADDING,
            "TEXTAREA_PADDING": TEXTAREA_PADDING,
            "skinSuffix": skinSuffix,
            "smallSpinny": smallSpinny,
        }

        # ---------------------------------------------------------------
        # Images dict
        # ---------------------------------------------------------------
        s["img"] = {
            "scrollBackground": scrollBackground,
            "scrollBar": scrollBar,
            "progressBackground": _progressBackground,
            "progressBar": _progressBar,
            "songProgressBackground": _songProgressBackground,
            "songProgressBar": _songProgressBar,
            "songProgressBarDisabled": _songProgressBarDisabled,
            "volumeSliderBackground": _volumeSliderBackground,
            "volumeSliderBar": _volumeSliderBar,
            "volumeSliderPill": _volumeSliderPill,
            "popupSliderBar": _popupSliderBar,
        }

        # ---------------------------------------------------------------
        # DEFAULT WIDGET STYLES
        # ---------------------------------------------------------------

        s["window"] = {
            "w": screen_width,
            "h": screen_height,
        }

        s["absolute"] = _uses(
            s["window"],
            {
                "layout": "noLayout",
            },
        )

        s["popup"] = _uses(
            s["window"],
            {
                "border": [0, 0, 0, 0],
                "bgImg": popupBackground,
            },
        )

        s["title"] = {
            "h": TITLE_HEIGHT,
            "border": 0,
            "position": LAYOUT_NORTH,
            "bgImg": titleBox,
            "padding": [0, 5, 0, 5],
            "order": ["lbutton", "text", "rbutton"],
            "lbutton": {
                "border": [8, 0, 8, 0],
                "h": WH_FILL,
            },
            "rbutton": {
                "border": [8, 0, 8, 0],
                "h": WH_FILL,
            },
            "text": {
                "w": WH_FILL,
                "padding": TITLE_PADDING,
                "align": "center",
                "font": _boldfont(TITLE_FONT_SIZE),
                "fg": TEXT_COLOR,
            },
        }

        s["title"]["textButton"] = _uses(
            s["title"]["text"],
            {
                "bgImg": titlebarButtonBox,
                "padding": [4, 15, 4, 15],
            },
        )
        s["title"]["pressed"] = {}
        s["title"]["pressed"]["textButton"] = _uses(
            s["title"]["textButton"],
            {
                "bgImg": pressedTitlebarButtonBox,
            },
        )

        s["text_block_black"] = {
            "bgImg": _fill_color(0x000000FF),
            "position": LAYOUT_NORTH,
            "h": 100,
            "order": ["text"],
            "text": {
                "w": WH_FILL,
                "h": 100,
                "padding": [10, 160, 10, 0],
                "align": "center",
                "font": _font(100),
                "fg": TEXT_COLOR,
                "sh": TEXT_SH_COLOR,
            },
        }

        s["menu"] = {
            "position": LAYOUT_CENTER,
            "padding": [0, 0, 0, 0],
            "itemHeight": FIVE_ITEM_HEIGHT,
            "fg": [0xBB, 0xBB, 0xBB],
            "font": _boldfont(120),
        }

        s["menu_hidden"] = _uses(
            s["menu"],
            {
                "hidden": 1,
            },
        )

        s["item"] = {
            "order": ["icon", "text", "arrow"],
            "padding": [ITEM_LEFT_PADDING, 0, 8, 0],
            "text": {
                "padding": [0, 0, 2, 0],
                "align": "left",
                "w": WH_FILL,
                "h": WH_FILL,
                "font": _boldfont(TEXTMENU_FONT_SIZE),
                "fg": TEXT_COLOR,
                "sh": TEXT_SH_COLOR,
            },
            "icon": {
                "padding": MENU_ITEM_ICON_PADDING,
                "align": "center",
            },
            "arrow": {
                "align": ITEM_ICON_ALIGN,
                "img": _load_image("Icons/selection_right_5line.png"),
                "padding": [0, 0, 0, 0],
            },
            "bgImg": fiveItemBox,
        }

        s["item_play"] = _uses(
            s["item"],
            {
                "arrow": {"img": False},
            },
        )
        s["item_add"] = _uses(
            s["item"],
            {
                "arrow": addArrow,
            },
        )

        # Checkbox
        s["checkbox"] = {
            "align": "center",
            "padding": CHECKBOX_RADIO_PADDING,
            "h": WH_FILL,
            "img_on": _load_image("Icons/checkbox_on.png"),
            "img_off": _load_image("Icons/checkbox_off.png"),
        }

        # Radio button
        s["radio"] = {
            "align": "center",
            "padding": CHECKBOX_RADIO_PADDING,
            "h": WH_FILL,
            "img_on": _load_image("Icons/radiobutton_on.png"),
            "img_off": _load_image("Icons/radiobutton_off.png"),
        }

        s["item_checked"] = _uses(
            s["item"],
            {
                "order": ["icon", "text", "check", "arrow"],
                "check": {
                    "align": ITEM_ICON_ALIGN,
                    "padding": CHECK_PADDING,
                },
            },
        )

        s["item_info"] = _uses(
            s["item"],
            {
                "order": ["icon", "text", "arrow"],
                "arrow": {
                    "img": _load_image("Icons/icon_info_5line.png"),
                },
            },
        )

        s["item_no_arrow"] = _uses(
            s["item"],
            {
                "order": ["icon", "text"],
            },
        )

        s["item_checked_no_arrow"] = _uses(
            s["item_checked"],
            {
                "order": ["icon", "text", "check"],
            },
        )

        s["item_choice"] = _uses(
            s["item"],
            {
                "order": ["icon", "text", "check"],
                "check": {
                    "align": ITEM_ICON_ALIGN,
                    "padding": CHECK_PADDING,
                    "font": _font(ALBUMMENU_SMALL_FONT_SIZE),
                    "fg": TEXT_COLOR,
                },
            },
        )

        # Scrollbar
        s["scrollbar"] = {
            "w": 42,
            "border": 0,
            "padding": [0, 0, 0, 0],
            "horizontal": 0,
            "bgImg": scrollBackground,
            "img": scrollBar,
            "layer": LAYER_CONTENT_ON_STAGE,
        }

        s["slider"] = {
            "border": [6, 0, 6, 0],
            "position": LAYOUT_SOUTH,
            "horizontal": 1,
            "bgImg": _progressBackground,
            "img": _progressBar,
        }

        s["slider_group"] = {
            "w": WH_FILL,
            "border": [0, 5, 0, 10],
            "order": ["min", "slider", "max"],
        }

        s["textarea"] = {
            "w": screen_width,
            "padding": TEXTAREA_PADDING,
            "font": _font(TEXTAREA_FONT_SIZE),
            "fg": TEXT_COLOR,
            "sh": TEXT_SH_COLOR,
            "align": "left",
        }

        s["help_text"] = {
            "w": screen_width - 20,
            "padding": [10, 10, 10, 10],
            "font": _font(HELP_FONT_SIZE),
            "fg": TEXT_COLOR,
            "lineHeight": HELP_FONT_SIZE + 4,
            "position": LAYOUT_NORTH,
            "align": "left",
        }

        # ---------------------------------------------------------------
        # WINDOW STYLES
        # ---------------------------------------------------------------

        # text_list — basic list with title
        s["text_list"] = _uses(
            s["window"],
            {
                "menu": _uses(
                    s["menu"],
                    {
                        "itemHeight": FIVE_ITEM_HEIGHT,
                        "item": _uses(s["item"]),
                        "item_checked": _uses(s["item_checked"]),
                        "item_play": _uses(s["item_play"]),
                        "item_add": _uses(s["item_add"]),
                        "item_no_arrow": _uses(s["item_no_arrow"]),
                        "item_checked_no_arrow": _uses(s["item_checked_no_arrow"]),
                        "item_choice": _uses(s["item_choice"]),
                        "selected": {
                            "item": _uses(
                                s["item"],
                                {"bgImg": fiveItemSelectionBox},
                            ),
                            "item_checked": _uses(
                                s["item_checked"],
                                {"bgImg": fiveItemSelectionBox},
                            ),
                            "item_play": _uses(
                                s["item_play"],
                                {"bgImg": fiveItemSelectionBox},
                            ),
                            "item_add": _uses(
                                s["item_add"],
                                {"bgImg": fiveItemSelectionBox},
                            ),
                            "item_no_arrow": _uses(
                                s["item_no_arrow"],
                                {"bgImg": fiveItemSelectionBox},
                            ),
                            "item_checked_no_arrow": _uses(
                                s["item_checked_no_arrow"],
                                {"bgImg": fiveItemSelectionBox},
                            ),
                            "item_choice": _uses(
                                s["item_choice"],
                                {"bgImg": fiveItemSelectionBox},
                            ),
                        },
                        "pressed": {
                            "item": _uses(
                                s["item"],
                                {"bgImg": fiveItemPressedBox},
                            ),
                            "item_checked": _uses(
                                s["item_checked"],
                                {"bgImg": fiveItemPressedBox},
                            ),
                            "item_play": _uses(
                                s["item_play"],
                                {"bgImg": fiveItemPressedBox},
                            ),
                            "item_add": _uses(
                                s["item_add"],
                                {"bgImg": fiveItemPressedBox},
                            ),
                        },
                        "locked": {
                            "item": _uses(
                                s["item"],
                                {
                                    "bgImg": fiveItemSelectionBox,
                                    "arrow": smallSpinny,
                                },
                            ),
                            "item_checked": _uses(
                                s["item_checked"],
                                {
                                    "bgImg": fiveItemSelectionBox,
                                    "arrow": smallSpinny,
                                },
                            ),
                        },
                        "scrollbar": _uses(s["scrollbar"]),
                    },
                ),
            },
        )

        # icon_list — list with icons
        s["icon_list"] = _uses(
            s["text_list"],
            {
                "menu": {
                    "item": {
                        "text": {
                            "font": _font(ALBUMMENU_SMALL_FONT_SIZE),
                            "line": [
                                {
                                    "font": _boldfont(ALBUMMENU_FONT_SIZE),
                                    "height": int(ALBUMMENU_FONT_SIZE * 1.3),
                                },
                                {
                                    "font": _font(ALBUMMENU_SMALL_FONT_SIZE),
                                },
                            ],
                        },
                    },
                },
            },
        )

        # track_list
        s["track_list"] = _uses(
            s["text_list"],
            {
                "title": _uses(
                    s["title"],
                    {
                        "order": ["icon", "text"],
                        "icon": {
                            "w": THUMB_SIZE + 10,
                            "h": WH_FILL,
                        },
                        "text": {
                            "align": "top-left",
                            "font": _font(ALBUMMENU_SMALL_FONT_SIZE),
                            "lineHeight": ALBUMMENU_SMALL_FONT_SIZE + 2,
                            "line": [
                                {
                                    "font": _boldfont(ALBUMMENU_FONT_SIZE),
                                    "height": ALBUMMENU_FONT_SIZE + 4,
                                },
                                {
                                    "font": _font(ALBUMMENU_SMALL_FONT_SIZE),
                                    "height": ALBUMMENU_SMALL_FONT_SIZE + 2,
                                },
                            ],
                        },
                    },
                ),
                "menu": {
                    "scrollbar": _uses(
                        s["scrollbar"],
                        {
                            "h": FIVE_ITEM_HEIGHT * 4 - 8,
                        },
                    ),
                },
            },
        )

        # multiline_text_list
        s["multiline_text_list"] = _uses(
            s["text_list"],
            {
                "title": _uses(
                    s["title"],
                    {
                        "h": 55,
                    },
                ),
                "menu": {
                    "itemHeight": THREE_ITEM_HEIGHT,
                    "border": [0, 56, 0, 0],
                    "scrollbar": _uses(
                        s["scrollbar"],
                        {
                            "h": THREE_ITEM_HEIGHT * 3 - 8,
                        },
                    ),
                },
            },
        )

        # Information window
        s["information"] = _uses(s["window"])

        # Help window
        s["help_list"] = _uses(
            s["text_list"],
            {
                "menu": {
                    "item": {
                        "text": {
                            "font": _font(HELP_FONT_SIZE),
                        },
                    },
                },
            },
        )

        # Setup / language selection window
        s["setup_list"] = _uses(s["text_list"])

        # Popup window
        s["waiting_popup"] = _uses(
            s["popup"],
            {
                "text": {
                    "w": WH_FILL,
                    "h": (POPUP_TEXT_SIZE_1 + 8) * 2,
                    "position": LAYOUT_NORTH,
                    "border": [0, 24, 0, 0],
                    "padding": [15, 0, 15, 0],
                    "align": "center",
                    "font": _font(POPUP_TEXT_SIZE_1),
                    "lineHeight": POPUP_TEXT_SIZE_1 + 8,
                    "fg": TEXT_COLOR,
                    "sh": TEXT_SH_COLOR,
                },
                "subtext": {
                    "w": WH_FILL,
                    "h": 30,
                    "padding": [15, 0, 15, 22],
                    "font": _boldfont(UPDATE_SUBTEXT_SIZE),
                    "fg": TEXT_COLOR,
                    "sh": TEXT_SH_COLOR,
                    "align": "bottom",
                    "position": LAYOUT_SOUTH,
                },
                "icon": largeSpinny,
            },
        )

        # playlist same as icon list
        s["play_list"] = _uses(s["icon_list"])

        # Input toast popup
        s["toast_popup"] = _uses(
            s["popup"],
            {
                "x": 5,
                "y": 5,
                "w": screen_width - 10,
                "h": screen_height - 10,
                "bgImg": popupBox,
                "text": {
                    "w": WH_FILL,
                    "padding": [10, 12, 10, 0],
                    "align": "center",
                    "font": _boldfont(TITLE_FONT_SIZE),
                    "fg": TEXT_COLOR,
                },
                "subtext": {
                    "w": WH_FILL,
                    "padding": [10, 0, 10, 0],
                    "align": "center",
                    "font": _font(ALBUMMENU_SMALL_FONT_SIZE),
                    "fg": TEXT_COLOR,
                },
            },
        )

        s["toast_popup_mixed"] = _uses(
            s["toast_popup"],
            {
                "text": {
                    "font": _boldfont(18),
                },
                "subtext": {
                    "font": _boldfont(18),
                },
            },
        )

        s["toast_popup_icon"] = _uses(
            s["popup"],
            {
                "x": 100,
                "y": 56,
                "w": screen_width - 200,
                "h": screen_height - 112,
                "bgImg": popupBox,
                "icon": {
                    "align": "center",
                    "padding": [0, 0, 0, 0],
                },
            },
        )

        # Slider popup (volume)
        s["slider_popup"] = _uses(
            s["popup"],
            {
                "x": 5,
                "y": 15,
                "w": screen_width - 10,
                "h": 90,
                "bgImg": popupBox,
                "title": {
                    "hidden": 1,
                },
                "slider": {
                    "border": [15, 0, 15, 0],
                    "position": LAYOUT_SOUTH,
                    "horizontal": 1,
                    "bgImg": _volumeSliderBackground,
                    "img": _popupSliderBar,
                    "pillImg": _volumeSliderPill,
                },
            },
        )

        # Context menu
        s["context_menu"] = _uses(
            s["popup"],
            {
                "x": 8,
                "y": 14,
                "w": screen_width - 16,
                "h": screen_height - 28,
                "bgImg": contextMenuBox,
                "title": _uses(
                    s["title"],
                    {
                        "bgImg": False,
                        "h": 36,
                    },
                ),
                "menu": _uses(
                    s["menu"],
                    {
                        "h": CM_MENU_HEIGHT * 5,
                        "itemHeight": CM_MENU_HEIGHT,
                        "scrollbar": _uses(
                            s["scrollbar"],
                            {
                                "h": CM_MENU_HEIGHT * 5 - 6,
                                "border": [0, 4, 0, 4],
                            },
                        ),
                        "item": {
                            "order": ["icon", "text", "arrow"],
                            "padding": [6, 2, 6, 0],
                            "text": {
                                "w": WH_FILL,
                                "h": WH_FILL,
                                "align": "left",
                                "font": _boldfont(TEXTMENU_FONT_SIZE - 2),
                                "fg": TEXT_COLOR,
                                "sh": TEXT_SH_COLOR,
                            },
                            "icon": {
                                "align": "center",
                                "padding": [0, 0, 4, 0],
                            },
                            "arrow": {
                                "align": ITEM_ICON_ALIGN,
                                "img": _load_image("Icons/selection_right_5line.png"),
                                "padding": [0, 0, 0, 0],
                            },
                        },
                    },
                ),
                "multiline_text": {
                    "w": WH_FILL,
                    "padding": [14, 18, 14, 18],
                    "font": _font(TEXTAREA_FONT_SIZE),
                    "fg": TEXT_COLOR,
                    "sh": TEXT_SH_COLOR,
                    "align": "left",
                    "scrollbar": {"h": CM_MENU_HEIGHT * 5 - 6},
                    "lineHeight": 21,
                },
            },
        )

        # Alarm time
        s["alarm_time"] = {
            "font": _font(90),
        }

        # Icon popup styles
        s["icon_connecting"] = {
            "img": _load_image("Alerts/wifi_connecting.png"),
            "frameRate": 8,
            "frameWidth": 120,
            "padding": [0, 48, 0, 0],
        }
        s["icon_connected"] = {
            "img": _load_image("Alerts/connecting_success_icon.png"),
            "padding": [0, 48, 0, 0],
        }
        s["icon_restart"] = {
            "img": _load_image("Alerts/connecting_success_icon.png"),
            "padding": [0, 48, 0, 0],
        }
        s["icon_software_update"] = {
            "img": _load_image("Alerts/wifi_connecting.png"),
            "frameRate": 8,
            "frameWidth": 120,
            "padding": [0, 38, 0, 0],
        }
        s["icon_power"] = {
            "img": _load_image("Icons/icon_restart.png"),
            "padding": [0, 25, 0, 0],
        }
        s["icon_battery_low"] = {
            "img": _load_image("Icons/icon_restart.png"),
            "padding": [0, 25, 0, 0],
        }

        # ---------------------------------------------------------------
        # Iconbar styles
        # ---------------------------------------------------------------
        _iconbar_icon = {
            "padding": [0, 0, 0, 0],
            "border": [5, 0, 5, 0],
            "align": "center",
        }

        s["iconbar_group"] = {
            "hidden": 1,
        }

        # time (hidden off screen)
        s["button_time"] = {
            "hidden": 1,
        }

        # Playmode icons
        s["_button_playmode"] = _uses(_iconbar_icon)
        s["button_playmode_OFF"] = _uses(
            s["_button_playmode"],
            {"img": _load_image("Icons/icon_toolbar_play_off.png")},
        )
        s["button_playmode_STOP"] = _uses(
            s["_button_playmode"],
            {"img": _load_image("Icons/icon_toolbar_stop.png")},
        )
        s["button_playmode_PLAY"] = _uses(
            s["_button_playmode"],
            {"img": _load_image("Icons/icon_toolbar_play.png")},
        )
        s["button_playmode_PAUSE"] = _uses(
            s["_button_playmode"],
            {"img": _load_image("Icons/icon_toolbar_pause.png")},
        )

        # Repeat icons
        s["_button_repeat"] = _uses(_iconbar_icon)
        s["button_repeat_OFF"] = _uses(
            s["_button_repeat"],
            {"img": _load_image("Icons/icon_toolbar_repeat_off.png")},
        )
        s["button_repeat_0"] = _uses(
            s["_button_repeat"],
            {"img": _load_image("Icons/icon_toolbar_repeat_off.png")},
        )
        s["button_repeat_1"] = _uses(
            s["_button_repeat"],
            {"img": _load_image("Icons/icon_toolbar_repeat_song.png")},
        )
        s["button_repeat_2"] = _uses(
            s["_button_repeat"],
            {"img": _load_image("Icons/icon_toolbar_repeat.png")},
        )

        # Shuffle icons
        s["_button_shuffle"] = _uses(_iconbar_icon)
        s["button_shuffle_OFF"] = _uses(
            s["_button_shuffle"],
            {"img": _load_image("Icons/icon_toolbar_shuffle_off.png")},
        )
        s["button_shuffle_0"] = _uses(
            s["_button_shuffle"],
            {"img": _load_image("Icons/icon_toolbar_shuffle_off.png")},
        )
        s["button_shuffle_1"] = _uses(
            s["_button_shuffle"],
            {"img": _load_image("Icons/icon_toolbar_shuffle.png")},
        )
        s["button_shuffle_2"] = _uses(
            s["_button_shuffle"],
            {"img": _load_image("Icons/icon_toolbar_shuffle_album.png")},
        )

        # Sleep icons
        s["button_sleep_ON"] = _uses(
            _iconbar_icon,
            {"img": _load_image("Icons/icon_toolbar_sleep.png")},
        )
        s["button_sleep_OFF"] = _uses(
            _iconbar_icon,
            {"img": False},
        )

        # Alarm icons
        s["button_alarm_ON"] = _uses(
            _iconbar_icon,
            {"img": _load_image("Icons/icon_toolbar_alarm.png")},
        )
        s["button_alarm_OFF"] = _uses(
            _iconbar_icon,
            {"img": False},
        )

        # Battery icons
        s["_button_battery"] = _uses(_iconbar_icon)
        s["button_battery_AC"] = _uses(
            s["_button_battery"],
            {"img": _load_image("Icons/icon_toolbar_battery_ac.png")},
        )
        s["button_battery_CHARGING"] = _uses(
            s["_button_battery"],
            {"img": _load_image("Icons/icon_toolbar_battery_charging.png")},
        )
        s["button_battery_0"] = _uses(
            s["_button_battery"],
            {"img": _load_image("Icons/icon_toolbar_battery_0.png")},
        )
        s["button_battery_1"] = _uses(
            s["_button_battery"],
            {"img": _load_image("Icons/icon_toolbar_battery_1.png")},
        )
        s["button_battery_2"] = _uses(
            s["_button_battery"],
            {"img": _load_image("Icons/icon_toolbar_battery_2.png")},
        )
        s["button_battery_3"] = _uses(
            s["_button_battery"],
            {"img": _load_image("Icons/icon_toolbar_battery_3.png")},
        )
        s["button_battery_4"] = _uses(
            s["_button_battery"],
            {"img": _load_image("Icons/icon_toolbar_battery_4.png")},
        )
        s["button_battery_NONE"] = _uses(
            s["_button_battery"],
            {"img": False},
        )

        # Wireless icons
        s["_button_wireless"] = _uses(_iconbar_icon)
        s["button_wireless_1"] = _uses(
            s["_button_wireless"],
            {"img": _load_image("Icons/icon_toolbar_wireless_1.png")},
        )
        s["button_wireless_2"] = _uses(
            s["_button_wireless"],
            {"img": _load_image("Icons/icon_toolbar_wireless_2.png")},
        )
        s["button_wireless_3"] = _uses(
            s["_button_wireless"],
            {"img": _load_image("Icons/icon_toolbar_wireless_3.png")},
        )
        s["button_wireless_4"] = _uses(
            s["_button_wireless"],
            {"img": _load_image("Icons/icon_toolbar_wireless_4.png")},
        )
        s["button_wireless_ERROR"] = _uses(
            s["_button_wireless"],
            {"img": _load_image("Icons/icon_toolbar_wireless_error.png")},
        )
        s["button_wireless_SERVERERROR"] = _uses(
            s["_button_wireless"],
            {"img": _load_image("Icons/icon_toolbar_wireless_error.png")},
        )
        s["button_wireless_NONE"] = _uses(
            s["_button_wireless"],
            {"img": False},
        )

        # ---------------------------------------------------------------
        # Home menu icon styles
        # ---------------------------------------------------------------
        _buttonicon = {
            "h": THUMB_SIZE,
            "padding": MENU_ITEM_ICON_PADDING,
            "align": "center",
            "img": False,
        }

        _hm_icons = {
            "hm_appletImageViewer": "icon_image_viewer",
            "hm_eject": "icon_eject",
            "hm_sdcard": "icon_device_SDcard",
            "hm_usbdrive": "icon_device_USB",
            "hm_appletNowPlaying": "icon_nowplaying",
            "hm_settings": "icon_settings",
            "hm_advancedSettings": "icon_settings_adv",
            "hm_radio": "icon_internet_radio",
            "hm_radios": "icon_internet_radio",
            "hm_myApps": "icon_my_apps",
            "hm_myMusic": "icon_mymusic",
            "hm_favorites": "icon_favorites",
            "hm_settingsAlarm": "icon_alarm",
            "hm_settingsPlayerNameChange": "icon_settings_name",
            "hm_settingsBrightness": "icon_settings_brightness",
            "hm_settingsSync": "icon_sync",
            "hm_selectPlayer": "icon_choose_player",
            "hm_quit": "icon_power_off",
            "hm_playerpower": "icon_power_off",
            "hm_myMusicArtists": "icon_ml_artist",
            "hm_myMusicAlbums": "icon_ml_albums",
            "hm_myMusicGenres": "icon_ml_genres",
            "hm_myMusicYears": "icon_ml_years",
            "hm_myMusicNewMusic": "icon_ml_new_music",
            "hm_myMusicPlaylists": "icon_ml_playlist",
            "hm_myMusicSearch": "icon_ml_search",
            "hm_myMusicMusicFolder": "icon_ml_folder",
            "hm_randomplay": "icon_ml_random",
            "hm_skinTest": "icon_blank",
            "hm_settingsRepeat": "icon_settings_repeat",
            "hm_settingsShuffle": "icon_settings_shuffle",
            "hm_settingsSleep": "icon_settings_sleep",
            "hm_settingsScreen": "icon_settings_screen",
            "hm_appletCustomizeHome": "icon_settings_home",
            "hm_settingsAudio": "icon_settings_audio",
            "hm_linein": "icon_linein",
            "hm_loading": "icon_loading",
            "hm_settingsPlugin": "icon_settings_plugin",
        }

        for style_name, icon_name in _hm_icons.items():
            s[style_name] = _uses(
                _buttonicon,
                {
                    "img": _load_image("IconsResized/" + icon_name + skinSuffix),
                },
            )

        # Aliases
        s["hm__myMusic"] = _uses(s.get("hm_myMusic", _buttonicon))
        s["hm_otherLibrary"] = _uses(
            _buttonicon,
            {
                "img": _load_image("IconsResized/icon_ml_other_library" + skinSuffix),
            },
        )
        s["hm_myMusicSelector"] = _uses(s.get("hm_myMusic", _buttonicon))
        s["hm_myMusicSearchArtists"] = _uses(s.get("hm_myMusicSearch", _buttonicon))
        s["hm_myMusicSearchAlbums"] = _uses(s.get("hm_myMusicSearch", _buttonicon))
        s["hm_myMusicSearchSongs"] = _uses(s.get("hm_myMusicSearch", _buttonicon))
        s["hm_myMusicSearchPlaylists"] = _uses(s.get("hm_myMusicSearch", _buttonicon))
        s["hm_myMusicSearchRecent"] = _uses(s.get("hm_myMusicSearch", _buttonicon))
        s["hm_homeSearchRecent"] = _uses(s.get("hm_myMusicSearch", _buttonicon))
        s["hm_globalSearch"] = _uses(s.get("hm_myMusicSearch", _buttonicon))

        # Icon for albums with no artwork
        s["icon_no_artwork"] = {
            "img": _load_image("IconsResized/icon_album_noart" + skinSuffix),
            "h": THUMB_SIZE,
            "padding": MENU_ITEM_ICON_PADDING,
            "align": "center",
        }

        # _icon base
        s["_icon"] = _uses(_buttonicon)

        # ---------------------------------------------------------------
        # NowPlaying styles
        # ---------------------------------------------------------------
        NP_ARTISTALBUM_FONT_SIZE = 14
        NP_TRACK_FONT_SIZE = 18

        controlHeight = 38
        controlWidth = 45
        volumeBarWidth = 150
        buttonPadding = 0
        NP_TITLE_HEIGHT = 31
        NP_TRACKINFO_RIGHT_PADDING = 40

        _tracklayout = {
            "border": 0,
            "position": LAYOUT_NORTH,
            "w": WH_FILL,
            "align": "left",
            "lineHeight": NP_TRACK_FONT_SIZE,
            "fg": [0xE7, 0xE7, 0xE7],
        }

        # NowPlaying title bar
        s["nowplaying"] = _uses(
            s["window"],
            {
                "bgImg": blackBackground,
                "title": _uses(
                    s["title"],
                    {
                        "zOrder": 9,
                        "h": NP_TITLE_HEIGHT,
                        "bgImg": False,
                        "text": {
                            "hidden": 1,
                        },
                        "icon": {
                            "padding": [0, 1, 5, 3],
                            "align": "left",
                        },
                    },
                ),
                # Song metadata
                "nptitle": {
                    "zOrder": 10,
                    "border": _tracklayout["border"],
                    "position": _tracklayout["position"],
                    "order": ["nptrack", "xofy"],
                    "nptrack": {
                        "w": WH_FILL,
                        "align": _tracklayout["align"],
                        "lineHeight": _tracklayout["lineHeight"],
                        "fg": _tracklayout["fg"],
                        "padding": [10, NP_TITLE_HEIGHT, 2, 0],
                        "font": _boldfont(NP_TRACK_FONT_SIZE),
                    },
                    "xofy": {
                        "w": 50,
                        "align": "right",
                        "fg": _tracklayout["fg"],
                        "padding": [
                            0,
                            NP_TITLE_HEIGHT,
                            NP_TRACKINFO_RIGHT_PADDING,
                            0,
                        ],
                        "font": _font(14),
                    },
                    "xofySmall": {
                        "w": 50,
                        "align": "right",
                        "fg": _tracklayout["fg"],
                        "padding": [
                            0,
                            NP_TITLE_HEIGHT,
                            NP_TRACKINFO_RIGHT_PADDING,
                            0,
                        ],
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
                    "padding": [
                        10,
                        NP_TITLE_HEIGHT + NP_TRACK_FONT_SIZE + 6,
                        NP_TRACKINFO_RIGHT_PADDING,
                        0,
                    ],
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
                        "padding": [0, 0, 0, 0],
                        "img": False,
                    },
                },
                # Transport controls
                "npcontrols": {
                    "order": [
                        "rew",
                        "div1",
                        "play",
                        "div2",
                        "fwd",
                        "div3",
                        "volDown",
                        "volSlider",
                        "volUp",
                        "div5",
                        "repeatMode",
                        "div6",
                        "shuffleMode",
                    ],
                    "position": LAYOUT_SOUTH,
                    "h": controlHeight,
                    "w": WH_FILL,
                    "bgImg": touchToolbarBackground,
                },
                # Progress bar
                "npprogress": {
                    "zOrder": 10,
                    "position": LAYOUT_SOUTH,
                    "padding": [10, 0, 10, controlHeight + 3],
                    "border": [0, 0, 0, 0],
                    "w": WH_FILL,
                    "order": ["elapsed", "slider", "remain"],
                    "elapsed": {
                        "zOrder": 10,
                        "font": _boldfont(9),
                        "fg": [0xB3, 0xB3, 0xB3],
                        "w": 30,
                    },
                    "remain": {
                        "zOrder": 10,
                        "font": _boldfont(9),
                        "fg": [0xB3, 0xB3, 0xB3],
                        "w": 30,
                    },
                    "elapsedSmall": {
                        "zOrder": 10,
                        "font": _boldfont(9),
                        "fg": [0xB3, 0xB3, 0xB3],
                        "w": 30,
                    },
                    "remainSmall": {
                        "zOrder": 10,
                        "font": _boldfont(9),
                        "fg": [0xB3, 0xB3, 0xB3],
                        "w": 30,
                    },
                    "npprogressB": {
                        "w": WH_FILL,
                        "align": "center",
                        "border": [5, 0, 5, 3],
                        "horizontal": 1,
                        "bgImg": _songProgressBackground,
                        "img": _songProgressBar,
                        "h": 15,
                    },
                },
                # Special style for when there shouldn't be a progress bar
                # (e.g., internet radio streams)
                "npprogressNB": {
                    "zOrder": 10,
                    "position": LAYOUT_SOUTH,
                    "padding": [10, 0, 0, controlHeight + 3],
                    "border": [0, 0, 0, 0],
                    "align": "center",
                    "w": WH_FILL,
                    "order": ["elapsed"],
                    "elapsed": {
                        "w": WH_FILL,
                        "align": "left",
                        "font": _boldfont(9),
                        "fg": [0xB3, 0xB3, 0xB3],
                    },
                },
            },
        )

        # Disabled progress bar variant
        s["nowplaying"]["npprogress"]["npprogressB_disabled"] = _uses(
            s["nowplaying"]["npprogress"]["npprogressB"],
            {
                "img": _songProgressBarDisabled,
            },
        )

        s["nowplaying"]["npprogressNB"]["elapsedSmall"] = s["nowplaying"][
            "npprogressNB"
        ]["elapsed"]

        # Art only NowPlaying style
        s["nowplaying_art_only"] = _uses(
            s["nowplaying"],
            {
                "bgImg": blackBackground,
                "title": {"hidden": 1},
                "nptitle": {"hidden": 1},
                "npartistalbum": {"hidden": 1},
                "npcontrols": {"hidden": 1},
                "npprogress": {"hidden": 1},
                "npprogressNB": {"hidden": 1},
                "npartwork": {
                    "position": LAYOUT_CENTER,
                    "artwork": {
                        "w": WH_FILL,
                        "align": "center",
                    },
                },
            },
        )

        # Text only NowPlaying style
        s["nowplaying_text_only"] = _uses(
            s["nowplaying"],
            {
                "npartwork": {"hidden": 1},
            },
        )

        # Spectrum analyzer NowPlaying style
        s["nowplaying_spectrum_text"] = _uses(
            s["nowplaying"],
            {
                "npvisu": {
                    "hidden": 0,
                    "position": LAYOUT_WEST,
                    "w": WH_FILL,
                    "align": "center",
                    "border": [0, NP_TITLE_HEIGHT, 0, controlHeight + 20],
                },
            },
        )

        # VU analog meter NowPlaying style
        s["nowplaying_vuanalog_text"] = _uses(
            s["nowplaying_spectrum_text"],
        )

        # Pressed states
        s["nowplaying"]["pressed"] = s["nowplaying"]
        s["nowplaying_art_only"]["pressed"] = s["nowplaying_art_only"]
        s["nowplaying_text_only"]["pressed"] = s["nowplaying_text_only"]
        s["nowplaying_spectrum_text"]["pressed"] = s["nowplaying_spectrum_text"]
        s["nowplaying_vuanalog_text"]["pressed"] = s["nowplaying_vuanalog_text"]

        # Line in window — same as nowplaying but with transparent background
        s["linein"] = _uses(
            s["nowplaying"],
            {
                "bgImg": False,
            },
        )

        # NP volume/progress bar styles
        s["npvolumeB"] = {
            "border": [5, 0, 5, 0],
            "horizontal": 1,
            "bgImg": _volumeSliderBackground,
            "img": _volumeSliderBar,
            "pillImg": _volumeSliderPill,
        }
        s["npvolumeB_disabled"] = _uses(
            s["npvolumeB"],
            {
                "img": False,
            },
        )

        # ---------------------------------------------------------------
        # Software update popup
        # ---------------------------------------------------------------
        s["update_popup"] = _uses(
            s["popup"],
            {
                "text": {
                    "w": WH_FILL,
                    "h": (POPUP_TEXT_SIZE_1 + 8) * 2,
                    "position": LAYOUT_NORTH,
                    "border": [0, 24, 0, 0],
                    "padding": [15, 0, 15, 0],
                    "align": "center",
                    "font": _font(POPUP_TEXT_SIZE_1),
                    "lineHeight": POPUP_TEXT_SIZE_1 + 8,
                    "fg": TEXT_COLOR,
                    "sh": TEXT_SH_COLOR,
                },
                "subtext": {
                    "w": WH_FILL,
                    "h": 30,
                    "padding": [15, 0, 15, 22],
                    "font": _boldfont(UPDATE_SUBTEXT_SIZE),
                    "fg": TEXT_COLOR,
                    "sh": TEXT_SH_COLOR,
                    "align": "bottom",
                    "position": LAYOUT_SOUTH,
                },
                "progress": {
                    "border": [15, 0, 15, 18],
                    "position": LAYOUT_SOUTH,
                    "horizontal": 1,
                    "bgImg": _progressBackground,
                    "img": _progressBar,
                },
            },
        )

        # ---------------------------------------------------------------
        # Player chooser window — same as text_list
        # ---------------------------------------------------------------
        s["choose_player"] = _uses(s["text_list"])

        # ---------------------------------------------------------------
        # Home menu
        # ---------------------------------------------------------------
        s["home_menu"] = _uses(s["text_list"])

        # ---------------------------------------------------------------
        # Photo loading icon
        # ---------------------------------------------------------------
        s["icon_photo_loading"] = _uses(
            _buttonicon,
            {
                "img": _load_image("Icons/image_viewer_loading.png"),
                "padding": [5, 5, 0, 5],
            },
        )

        return s

    # ------------------------------------------------------------------
    # free
    # ------------------------------------------------------------------

    def free(self) -> bool:
        """Free resources held by the skin applet."""
        self.images = {}
        self.imageTiles = {}
        self.hTiles = {}
        self.vTiles = {}
        self.tiles = {}
        return True
