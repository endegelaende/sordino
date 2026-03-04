"""
jive.applets.HDSkin.HDSkinApplet --- HDSkin applet.

Ported from ``share/jive/applets/HDSkin/HDSkinApplet.lua``
(~3006 LOC) in the original jivelite project.

This applet implements an HD skin supporting multiple resolutions:
1080p, 720p, 1280x1024, and VGA.  It is a standalone skin that inherits
directly from Applet and builds the complete style table from scratch.

Key implementation notes
------------------------

* Standalone skin — does NOT inherit from QVGAbaseSkin or JogglerSkin.
* Default screen size is 1920x1080 (1080p variant).
* Multiple resolution variants via ``skin_1080p``, ``skin_720p``,
  ``skin_1280_1024``, and ``skin_vga`` methods.
* NowPlaying styles include art+text and spectrum analyzer variants.

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

__all__ = ["HDSkinApplet"]

log = logger("applet.HDSkin")

# ---------------------------------------------------------------------------
# Type alias for style dicts
# ---------------------------------------------------------------------------
Style = Dict[str, Any]

# ---------------------------------------------------------------------------
# Image / font path prefixes (relative to search path)
# ---------------------------------------------------------------------------
_IMGPATH = "applets/HDSkin/images/"
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
    """Return a lazy reference to an image in the HDSkin images dir."""
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
# HDSkinApplet
# ============================================================================

# Default cover art size — changed per resolution variant
_coverSize = 900


class HDSkinApplet(Applet):
    """Skin applet for HD displays (1080p, 720p, 1280x1024, VGA).

    Standalone skin that builds the complete style table from scratch.
    Multiple resolution variants are available via dedicated methods.
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
        """Return skin parameter constants for the HD skin."""
        coverSize = _coverSize
        return {
            "THUMB_SIZE": 72,
            "THUMB_SIZE_MENU": 64,
            "NOWPLAYING_MENU": True,
            "NOWPLAYING_TRACKINFO_LINES": 3,
            "POPUP_THUMB_SIZE": 100,
            "nowPlayingScreenStyles": [
                # every skin needs to start off with a nowplaying style
                {
                    "style": "nowplaying",
                    "artworkSize": f"{coverSize}x{coverSize}",
                    "text": self.string("ART_AND_TEXT"),
                },
                {
                    "style": "nowplaying_spectrum_text",
                    "artworkSize": f"{coverSize}x{coverSize}",
                    "localPlayerOnly": 1,
                    "text": self.string("SPECTRUM_ANALYZER"),
                },
            ],
            "disableTimeInput": True,
        }

    # ------------------------------------------------------------------
    # Main skin method
    # ------------------------------------------------------------------

    def _skin_common(
        self,
        s: Style,
        reload: bool = False,
        use_default_size: bool = False,
        target_width: int = 1920,
        target_height: int = 1080,
    ) -> Style:
        """Populate *s* with the complete HDSkin style table.

        Parameters
        ----------
        s:
            The style dict to populate.
        reload:
            ``True`` when the skin is being reloaded (not first load).
        use_default_size:
            ``True`` to use the default screen size instead of
            querying the framework.
        target_width:
            Target screen width for this variant.
        target_height:
            Target screen height for this variant.

        Returns
        -------
        Style
            The populated style dict *s*.
        """
        screen_width = target_width
        screen_height = target_height

        # Set the display resolution — matches Lua: Framework:setVideoMode(w, h, 0, false)
        try:
            from jive.ui.framework import framework as _fw

            if _fw is not None:
                _fw.set_video_mode(target_width, target_height, 0, False)
                sw, sh = _fw.get_screen_size()
                if sw > 0 and sh > 0:
                    screen_width, screen_height = sw, sh
        except Exception as exc:
            log.warning(
                "HDSkin: failed to set initial video mode (%sx%s): %s",
                target_width,
                target_height,
                exc,
            )

        if use_default_size:
            screen_width = target_width
            screen_height = target_height

        try:
            from jive.ui.framework import framework as _fw

            if _fw is not None:
                try:
                    from jive.jive_main import jive_main as _jm

                    _fw.set_video_mode(
                        screen_width,
                        screen_height,
                        0,
                        _jm.is_fullscreen() if _jm is not None else False,
                    )
                except (ImportError, AttributeError):
                    _fw.set_video_mode(screen_width, screen_height, 0, False)
        except Exception as exc:
            log.warning(
                "HDSkin: failed to set fullscreen video mode (%sx%s): %s",
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
            log.debug("HDSkin: failed to set most_recent_input_type: %s", exc)

        imgpath = _IMGPATH

        # skin suffix — must match the original Lua: 'remote' for HDSkin
        thisSkin = "remote"
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

        # HD uses its own image sub-directory structure

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

        MENU_ITEM_ICON_PADDING = [0, 0, 24, 0]
        MENU_PLAYLISTITEM_TEXT_PADDING = [16, 1, 9, 1]
        MENU_CURRENTALBUM_TEXT_PADDING = [6, 20, 0, 10]
        TEXTAREA_PADDING = [13, 8, 8, 0]

        TEXT_COLOR = [0xE7, 0xE7, 0xE7]
        TEXT_COLOR_BLACK = [0x00, 0x00, 0x00]
        TEXT_SH_COLOR = [0x37, 0x37, 0x37]
        TEXT_COLOR_TEAL = [0, 0xBE, 0xBE]

        SELECT_COLOR = [0xE7, 0xE7, 0xE7]
        SELECT_SH_COLOR: List[int] = []

        # HD skin uses proportionally larger sizes
        scale = screen_height / 480.0  # scale relative to 480p base

        TITLE_HEIGHT = max(55, int(55 * scale))
        TITLE_FONT_SIZE = max(20, int(20 * scale))
        ALBUMMENU_FONT_SIZE = max(18, int(18 * scale))
        ALBUMMENU_SMALL_FONT_SIZE = max(14, int(14 * scale))
        TEXTMENU_FONT_SIZE = max(20, int(20 * scale))
        POPUP_TEXT_SIZE_1 = max(34, int(34 * scale))
        POPUP_TEXT_SIZE_2 = max(26, int(26 * scale))
        TRACK_FONT_SIZE = max(18, int(18 * scale))
        TEXTAREA_FONT_SIZE = max(18, int(18 * scale))
        CENTERED_TEXTAREA_FONT_SIZE = max(28, int(28 * scale))

        CM_MENU_HEIGHT = max(45, int(45 * scale))

        TEXTINPUT_FONT_SIZE = max(20, int(20 * scale))
        TEXTINPUT_SELECTED_FONT_SIZE = max(24, int(24 * scale))

        HELP_FONT_SIZE = max(18, int(18 * scale))
        UPDATE_SUBTEXT_SIZE = max(20, int(20 * scale))

        ITEM_ICON_ALIGN = "center"
        ITEM_LEFT_PADDING = max(12, int(12 * scale))
        THREE_ITEM_HEIGHT = max(72, int(72 * scale))
        FIVE_ITEM_HEIGHT = max(73, int(73 * scale))
        TITLE_BUTTON_WIDTH = max(76, int(76 * scale))

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

        # Top-level selected / pressed / locked (Lua L940-1016)
        s["selected"] = {
            "item": _uses(s["item"], {"bgImg": fiveItemSelectionBox}),
            "item_play": _uses(s["item_play"], {"bgImg": fiveItemSelectionBox}),
            "item_add": _uses(s["item_add"], {"bgImg": fiveItemSelectionBox}),
            "item_checked": _uses(s["item_checked"], {"bgImg": fiveItemSelectionBox}),
            "item_no_arrow": _uses(s["item_no_arrow"], {"bgImg": fiveItemSelectionBox}),
            "item_checked_no_arrow": _uses(
                s["item_checked_no_arrow"], {"bgImg": fiveItemSelectionBox}
            ),
            "item_choice": _uses(s["item_choice"], {"bgImg": fiveItemSelectionBox}),
            "item_info": _uses(s["item_info"], {"bgImg": fiveItemSelectionBox}),
        }

        s["pressed"] = {
            "item": _uses(s["item"], {"bgImg": fiveItemPressedBox}),
            "item_checked": _uses(s["item_checked"], {"bgImg": fiveItemPressedBox}),
            "item_play": _uses(s["item_play"], {"bgImg": fiveItemPressedBox}),
            "item_add": _uses(s["item_add"], {"bgImg": fiveItemPressedBox}),
            "item_no_arrow": _uses(s["item_no_arrow"], {"bgImg": fiveItemPressedBox}),
            "item_checked_no_arrow": _uses(
                s["item_checked_no_arrow"], {"bgImg": fiveItemPressedBox}
            ),
            "item_choice": _uses(s["item_choice"], {"bgImg": fiveItemPressedBox}),
            "item_info": _uses(s["item_info"], {"bgImg": fiveItemPressedBox}),
        }

        s["locked"] = {
            "item": _uses(s["pressed"]["item"], {"arrow": smallSpinny}),
            "item_checked": _uses(s["pressed"]["item_checked"], {"arrow": smallSpinny}),
            "item_play": _uses(s["pressed"]["item_play"], {"arrow": smallSpinny}),
            "item_add": _uses(s["pressed"]["item_add"], {"arrow": smallSpinny}),
            "item_no_arrow": _uses(s["item_no_arrow"], {"arrow": smallSpinny}),
            "item_checked_no_arrow": _uses(
                s["item_checked_no_arrow"], {"arrow": smallSpinny}
            ),
            "item_info": _uses(s["item_info"], {"arrow": smallSpinny}),
        }

        # item_blank (Lua L1018-1026)
        s["item_blank"] = {
            "padding": [],
            "text": {},
            "bgImg": helpTextBackground,
        }
        s["pressed"]["item_blank"] = _uses(s["item_blank"])
        s["selected"]["item_blank"] = _uses(s["item_blank"])

        # text (Lua L1048-1055)
        s["text"] = {
            "w": screen_width,
            "h": WH_FILL,
            "padding": TEXTAREA_PADDING,
            "font": _boldfont(TEXTAREA_FONT_SIZE),
            "fg": TEXT_COLOR,
            "sh": TEXT_SH_COLOR,
            "align": "left",
        }

        # multiline_text (Lua L1057-1065)
        s["multiline_text"] = {
            "w": WH_FILL,
            "padding": [10, 0, 2, 10],
            "font": _font(18),
            "height": 21,
            "fg": [0xE6, 0xE6, 0xE6],
            "sh": [],
            "align": "left",
        }
        s["multiline_popup_text"] = _uses(
            s["multiline_text"],
            {
                "padding": [14, 18, 14, 18],
                "border": [0, 0, 10, 0],
            },
        )

        # Scrollbar
        s["scrollbar"] = {
            "w": 46,
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
            "w": screen_width - 30,
            "padding": [18, 18, 12, 0],
            "font": _font(HELP_FONT_SIZE),
            "lineHeight": 38,
            "fg": TEXT_COLOR,
            "sh": TEXT_SH_COLOR,
            "align": "top-left",
        }

        # ---------------------------------------------------------------
        # SPECIAL WIDGETS (Lua L1088-1152)
        # ---------------------------------------------------------------

        # text input (Lua L1092-1103)
        TEXTINPUT_FONT_SIZE = max(14, int(36 * scale))
        TEXTINPUT_SELECTED_FONT_SIZE = max(18, int(48 * scale))
        s["textinput"] = {
            "h": 72,
            "padding": [12, 0, 12, 0],
            "font": _boldfont(TEXTINPUT_FONT_SIZE),
            "cursorFont": _boldfont(TEXTINPUT_FONT_SIZE),
            "wheelFont": _boldfont(TEXTINPUT_FONT_SIZE),
            "charHeight": TEXTINPUT_SELECTED_FONT_SIZE,
            "fg": TEXT_COLOR_BLACK,
            "charOffsetY": 8,
            "wh": [0x55, 0x55, 0x55],
            "cursorImg": textinputCursor,
        }

        # keyboard (Lua L1105-1118)
        s["keyboard"] = {"hidden": 1}

        s["keyboard_textinput"] = {
            "bgImg": textinputBackground,
            "w": WH_FILL,
            "order": ["textinput", "backspace"],
            "border": 0,
            "textinput": {
                "padding": [16, 0, 0, 4],
            },
        }

        s["button_keyboard_back"] = {
            "img": _load_image("Icons/icon_delete_tch.png"),
            "w": 96,
            "align": "right",
            "padding": [0, 0, 4, 0],
        }

        # time input backgrounds (Lua L1122-1152)
        _timeFirstColumnX12h = 123
        _timeFirstColumnX24h = 164

        s["time_input_background_12h"] = {
            "w": WH_FILL,
            "h": screen_height - TITLE_HEIGHT,
            "position": LAYOUT_NONE,
            "img": _load_image("Multi_Character_Entry/tch_multi_char_bkgrd_3c.png"),
            "x": 0,
            "y": TITLE_HEIGHT,
        }
        s["time_input_background_24h"] = {
            "w": WH_FILL,
            "h": screen_height - TITLE_HEIGHT,
            "position": LAYOUT_NONE,
            "img": _load_image("Multi_Character_Entry/tch_multi_char_bkgrd_2c.png"),
            "x": 0,
            "y": TITLE_HEIGHT,
        }
        s["time_input_menu_box_12h"] = {
            "position": LAYOUT_NONE,
            "img": _load_image("Multi_Character_Entry/menu_box_fixed.png"),
            "w": 220,
            "h": 40,
            "x": 130,
            "y": 140,
        }
        s["time_input_menu_box_24h"] = _uses(
            s["time_input_menu_box_12h"],
            {
                "img": _load_image("UNOFFICIAL/menu_box_fixed_2c.png"),
                "w": 180,
                "x": 167,
            },
        )

        # input_time_12h (Lua L1153-1243)
        _time_item = {
            "bgImg": False,
            "order": ["text"],
            "text": {
                "align": "right",
                "font": _boldfont(30),
                "padding": [2, 4, 8, 0],
                "fg": [0xB3, 0xB3, 0xB3],
                "sh": [],
            },
        }
        _time_selected_item = {
            "item": {
                "order": ["text"],
                "bgImg": False,
                "text": {
                    "font": _boldfont(30),
                    "fg": [0xE6, 0xE6, 0xE6],
                    "sh": [],
                    "align": "right",
                    "padding": [2, 4, 8, 0],
                },
            },
        }

        s["input_time_12h"] = _uses(s["window"])
        s["input_time_12h"]["hour"] = _uses(
            s["menu"],
            {
                "w": 75,
                "h": screen_height,
                "itemHeight": 45,
                "position": LAYOUT_WEST,
                "padding": 0,
                "border": [_timeFirstColumnX12h, TITLE_HEIGHT, 0, 0],
                "item": _uses(_time_item),
                "selected": _uses(_time_selected_item),
                "pressed": _uses(_time_selected_item),
            },
        )
        s["input_time_12h"]["minute"] = _uses(
            s["input_time_12h"]["hour"],
            {"border": [_timeFirstColumnX12h + 75, TITLE_HEIGHT, 0, 0]},
        )
        s["input_time_12h"]["ampm"] = _uses(
            s["input_time_12h"]["hour"],
            {
                "border": [_timeFirstColumnX12h + 75 + 75, TITLE_HEIGHT, 0, 0],
                "item": {
                    "text": {
                        "padding": [0, 2, 8, 0],
                        "font": _boldfont(26),
                    },
                },
                "selected": {
                    "item": {
                        "text": {
                            "padding": [0, 4, 8, 0],
                            "font": _boldfont(26),
                        },
                    },
                },
                "pressed": {
                    "item": {
                        "text": {
                            "padding": [0, 4, 8, 0],
                            "font": _boldfont(26),
                        },
                    },
                },
            },
        )
        s["input_time_12h"]["hourUnselected"] = s["input_time_12h"]["hour"]
        s["input_time_12h"]["minuteUnselected"] = s["input_time_12h"]["minute"]
        s["input_time_12h"]["ampmUnselected"] = s["input_time_12h"]["ampm"]

        s["input_time_24h"] = _uses(
            s["input_time_12h"],
            {
                "hour": {"border": [_timeFirstColumnX24h, TITLE_HEIGHT, 0, 0]},
                "minute": {"border": [_timeFirstColumnX24h + 75, TITLE_HEIGHT, 0, 0]},
                "hourUnselected": {
                    "border": [_timeFirstColumnX24h, TITLE_HEIGHT, 0, 0]
                },
                "minuteUnselected": {
                    "border": [_timeFirstColumnX24h + 75, TITLE_HEIGHT, 0, 0]
                },
            },
        )

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

        # text_list.title — title bar for text lists (Lua L1276-1300)
        s["text_list"]["title"] = _uses(
            s["title"],
            {
                "text": {
                    "line": [
                        {
                            "font": _boldfont(TITLE_FONT_SIZE),
                            "height": 32,
                        },
                        {
                            "font": _font(14),
                            "fg": [0xB3, 0xB3, 0xB3],
                        },
                    ],
                },
            },
        )
        s["text_list"]["title"]["textButton"] = _uses(
            s["text_list"]["title"].get("text", {}),
            {
                "padding": [4, 15, 4, 15],
            },
        )
        s["text_list"]["title"]["pressed"] = {}
        s["text_list"]["title"]["pressed"]["textButton"] = _uses(
            s["text_list"]["title"].get("text", {}),
            {
                "bgImg": pressedTitlebarButtonBox,
                "padding": [4, 15, 4, 15],
            },
        )

        # choose_player — same as text_list (Lua L1302)
        s["choose_player"] = s["text_list"]

        # icon_list — list with icons
        s["icon_list"] = _uses(
            s["text_list"],
            {
                "menu": {
                    "item": {
                        "order": ["icon", "text", "arrow"],
                        "padding": [ITEM_LEFT_PADDING, 0, 0, 0],
                        "text": {
                            "w": WH_FILL,
                            "h": WH_FILL,
                            "align": "left",
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
                            "fg": TEXT_COLOR,
                            "sh": TEXT_SH_COLOR,
                        },
                        "icon": {
                            "h": THUMB_SIZE,
                            "padding": MENU_ITEM_ICON_PADDING,
                            "align": "center",
                        },
                        "arrow": _uses(s["item"]["arrow"]),
                    },
                },
            },
        )

        # Add additional item styles to icon_list.menu (matching Lua mutations)
        s["icon_list"]["menu"]["item_checked"] = _uses(
            s["icon_list"]["menu"]["item"],
            {
                "order": ["icon", "text", "check", "arrow"],
                "check": {
                    "align": ITEM_ICON_ALIGN,
                    "padding": CHECK_PADDING,
                    "img": _load_image("Icons/icon_check_5line.png"),
                },
            },
        )
        s["icon_list"]["menu"]["item_play"] = _uses(
            s["icon_list"]["menu"]["item"],
            {
                "arrow": {"img": False},
            },
        )
        s["icon_list"]["menu"]["albumcurrent"] = _uses(
            s["icon_list"]["menu"]["item_play"],
            {
                "arrow": {
                    "img": _load_image("Icons/icon_nplay_3line_off.png"),
                },
                "text": {"padding": 0},
                "bgImg": fiveItemBox,
            },
        )
        s["icon_list"]["menu"]["item_add"] = _uses(
            s["icon_list"]["menu"]["item"],
            {
                "arrow": addArrow,
            },
        )
        s["icon_list"]["menu"]["item_no_arrow"] = _uses(
            s["icon_list"]["menu"]["item"],
            {
                "order": ["icon", "text"],
            },
        )
        s["icon_list"]["menu"]["item_checked_no_arrow"] = _uses(
            s["icon_list"]["menu"]["item_checked"],
            {
                "order": ["icon", "text", "check"],
            },
        )

        # selected variants for icon_list.menu
        s["icon_list"]["menu"]["selected"] = {
            "item": _uses(
                s["icon_list"]["menu"]["item"],
                {"bgImg": fiveItemSelectionBox},
            ),
            "albumcurrent": _uses(
                s["icon_list"]["menu"]["albumcurrent"],
                {
                    "arrow": {
                        "img": _load_image("Icons/icon_nplay_3line_sel.png"),
                    },
                    "bgImg": fiveItemSelectionBox,
                },
            ),
            "item_checked": _uses(
                s["icon_list"]["menu"]["item_checked"],
                {"bgImg": fiveItemSelectionBox},
            ),
            "item_play": _uses(
                s["icon_list"]["menu"]["item_play"],
                {"bgImg": fiveItemSelectionBox},
            ),
            "item_add": _uses(
                s["icon_list"]["menu"]["item_add"],
                {"bgImg": fiveItemSelectionBox},
            ),
            "item_no_arrow": _uses(
                s["icon_list"]["menu"]["item_no_arrow"],
                {"bgImg": fiveItemSelectionBox},
            ),
            "item_checked_no_arrow": _uses(
                s["icon_list"]["menu"]["item_checked_no_arrow"],
                {"bgImg": fiveItemSelectionBox},
            ),
        }

        # pressed variants for icon_list.menu
        s["icon_list"]["menu"]["pressed"] = {
            "item": _uses(
                s["icon_list"]["menu"]["item"],
                {"bgImg": fiveItemPressedBox},
            ),
            "albumcurrent": _uses(
                s["icon_list"]["menu"]["albumcurrent"],
                {"bgImg": fiveItemSelectionBox},
            ),
            "item_checked": _uses(
                s["icon_list"]["menu"]["item_checked"],
                {"bgImg": fiveItemPressedBox},
            ),
            "item_play": _uses(
                s["icon_list"]["menu"]["item_play"],
                {"bgImg": fiveItemPressedBox},
            ),
            "item_add": _uses(
                s["icon_list"]["menu"]["item_add"],
                {"bgImg": fiveItemPressedBox},
            ),
            "item_no_arrow": _uses(
                s["icon_list"]["menu"]["item_no_arrow"],
                {"bgImg": fiveItemPressedBox},
            ),
            "item_checked_no_arrow": _uses(
                s["icon_list"]["menu"]["item_checked_no_arrow"],
                {"bgImg": fiveItemPressedBox},
            ),
        }

        # locked variants for icon_list.menu
        s["icon_list"]["menu"]["locked"] = {
            "item": _uses(
                s["icon_list"]["menu"]["pressed"]["item"],
                {"arrow": smallSpinny},
            ),
            "item_checked": _uses(
                s["icon_list"]["menu"]["pressed"]["item_checked"],
                {"arrow": smallSpinny},
            ),
            "item_play": _uses(
                s["icon_list"]["menu"]["pressed"]["item_play"],
                {"arrow": smallSpinny},
            ),
            "item_add": _uses(
                s["icon_list"]["menu"]["pressed"]["item_add"],
                {"arrow": smallSpinny},
            ),
            "albumcurrent": _uses(
                s["icon_list"]["menu"]["pressed"]["albumcurrent"],
                {"arrow": smallSpinny},
            ),
        }

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

        # text_only — removes icons (Lua L1256-1273)
        s["text_only"] = _uses(
            s["text_list"],
            {
                "menu": {
                    "item": {"order": ["text", "arrow"]},
                    "selected": {"item": {"order": ["text", "arrow"]}},
                    "pressed": {"item": {"order": ["text", "arrow"]}},
                },
            },
        )

        # input window (Lua L1368-1395)
        s["input"] = _uses(s["window"])
        s["input"]["title"] = _uses(
            s["title"],
            {
                "h": TITLE_HEIGHT - 3,
                "padding": [TITLE_PADDING[0], TITLE_PADDING[1], TITLE_PADDING[2], 7],
                "text": {
                    "font": _boldfont(TITLE_FONT_SIZE),
                },
            },
        )

        # error window (Lua L1596-1599)
        s["error"] = _uses(s.get("help_list", s["text_list"]))

        # help_info (Lua — uses help_list or text_list)
        s["help_info"] = _uses(s.get("help_list", s["text_list"]))

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

        s["icon_no_artwork_playlist"] = _uses(s["icon_no_artwork"])

        # _icon base
        s["_icon"] = _uses(_buttonicon)

        # Connecting / status icons (Lua L2237-2256)
        s["icon_connecting"] = _uses(
            _buttonicon,
            {
                "img": _load_image("Alerts/wifi_connecting.png"),
                "frameRate": 8,
                "frameWidth": 120,
                "h": WH_FILL,
                "padding": [0, 2, 0, 10],
            },
        )
        s["icon_connected"] = _uses(
            _buttonicon,
            {
                "img": _load_image("Alerts/connecting_success_icon.png"),
                "padding": [0, 2, 0, 10],
            },
        )
        s["icon_photo_loading"] = _uses(
            _buttonicon,
            {"img": _load_image("Icons/image_viewer_loading.png")},
        )
        s["icon_software_update"] = _uses(
            _buttonicon,
            {"img": _load_image("IconsResized/icon_firmware_update" + skinSuffix)},
        )
        s["icon_restart"] = _uses(
            _buttonicon,
            {"img": _load_image("IconsResized/icon_restart" + skinSuffix)},
        )
        s["icon_power"] = _uses(
            _buttonicon,
            {"img": _load_image("IconsResized/icon_restart" + skinSuffix)},
        )

        # Popup icons (Lua L2262-2348)
        _popupicon = {
            "padding": [0, 0, 0, 0],
            "border": [22, 18, 0, 0],
            "h": WH_FILL,
            "w": 166,
        }
        s["icon_popup_pause"] = _uses(
            _popupicon, {"img": _load_image("Icons/icon_popup_box_pause.png")}
        )
        s["icon_popup_play"] = _uses(
            _popupicon, {"img": _load_image("Icons/icon_popup_box_play.png")}
        )
        s["icon_popup_fwd"] = _uses(
            _popupicon, {"img": _load_image("Icons/icon_popup_box_fwd.png")}
        )
        s["icon_popup_rew"] = _uses(
            _popupicon, {"img": _load_image("Icons/icon_popup_box_rew.png")}
        )
        s["icon_popup_stop"] = _uses(
            _popupicon, {"img": _load_image("Icons/icon_popup_box_stop.png")}
        )
        s["icon_popup_lineIn"] = _uses(
            _popupicon, {"img": _load_image("IconsResized/icon_linein_134.png")}
        )
        s["icon_popup_volume"] = {
            "img": _load_image("Icons/icon_popup_box_volume_bar.png"),
            "w": WH_FILL,
            "h": 90,
            "align": "center",
            "padding": [0, 5, 0, 5],
        }
        s["icon_popup_mute"] = _uses(
            s["icon_popup_volume"],
            {"img": _load_image("Icons/icon_popup_box_volume_mute.png")},
        )
        s["icon_popup_shuffle0"] = _uses(
            _popupicon,
            {"img": _load_image("Icons/icon_popup_box_shuffle_off.png")},
        )
        s["icon_popup_shuffle1"] = _uses(
            _popupicon,
            {"img": _load_image("Icons/icon_popup_box_shuffle.png")},
        )
        s["icon_popup_shuffle2"] = _uses(
            _popupicon,
            {"img": _load_image("Icons/icon_popup_box_shuffle_album.png")},
        )
        s["icon_popup_repeat0"] = _uses(
            _popupicon,
            {"img": _load_image("Icons/icon_popup_box_repeat_off.png")},
        )
        s["icon_popup_repeat1"] = _uses(
            _popupicon,
            {"img": _load_image("Icons/icon_popup_box_repeat_song.png")},
        )
        s["icon_popup_repeat2"] = _uses(
            _popupicon,
            {"img": _load_image("Icons/icon_popup_box_repeat.png")},
        )

        # Sleep icons (Lua L2332-2348)
        _sleep_icon = {
            "h": WH_FILL,
            "w": WH_FILL,
            "padding": [24, 24, 0, 0],
        }
        s["icon_popup_sleep_15"] = _uses(
            _sleep_icon,
            {"img": _load_image("Icons/icon_popup_box_sleep_15.png")},
        )
        s["icon_popup_sleep_30"] = _uses(
            _sleep_icon,
            {"img": _load_image("Icons/icon_popup_box_sleep_30.png")},
        )
        s["icon_popup_sleep_45"] = _uses(
            _sleep_icon,
            {"img": _load_image("Icons/icon_popup_box_sleep_45.png")},
        )
        s["icon_popup_sleep_60"] = _uses(
            _sleep_icon,
            {"img": _load_image("Icons/icon_popup_box_sleep_60.png")},
        )
        s["icon_popup_sleep_90"] = _uses(
            _sleep_icon,
            {"img": _load_image("Icons/icon_popup_box_sleep_90.png")},
        )
        s["icon_popup_sleep_cancel"] = _uses(
            _sleep_icon,
            {
                "img": _load_image("Icons/icon_popup_box_sleep_off.png"),
                "padding": [24, 34, 0, 0],
            },
        )

        # Misc icons (Lua L2356-2378)
        s["icon_locked"] = _uses(_buttonicon)
        s["icon_alarm"] = {"img": _load_image("Icons/icon_alarm.png")}
        s["icon_art"] = _uses(_buttonicon, {"padding": 0, "img": False})
        s["icon_help"] = _uses(_buttonicon)

        # Player icons (Lua L2380-2410)
        _player_icons = {
            "player_transporter": "icon_transporter",
            "player_squeezebox": "icon_SB1n2",
            "player_squeezebox2": "icon_SB1n2",
            "player_squeezebox3": "icon_SB3",
            "player_boom": "icon_boom",
            "player_slimp3": "icon_slimp3",
            "player_softsqueeze": "icon_softsqueeze",
            "player_controller": "icon_controller",
            "player_receiver": "icon_receiver",
            "player_squeezeplay": "icon_squeezeplay",
            "player_http": "icon_tunein_url",
            "player_baby": "icon_baby",
            "player_fab4": "icon_fab4",
        }
        for pname, picon in _player_icons.items():
            s[pname] = _uses(
                _buttonicon,
                {"img": _load_image("IconsResized/" + picon + skinSuffix)},
            )

        # Wireless indicator icons (Lua L2548-2572)
        _indicator = {"align": "center"}
        s["wirelessLevel1"] = _uses(
            _indicator, {"img": _load_image("Icons/icon_wireless_1.png")}
        )
        s["wirelessLevel2"] = _uses(
            _indicator, {"img": _load_image("Icons/icon_wireless_2.png")}
        )
        s["wirelessLevel3"] = _uses(
            _indicator, {"img": _load_image("Icons/icon_wireless_3.png")}
        )
        s["wirelessLevel4"] = _uses(
            _indicator, {"img": _load_image("Icons/icon_wireless_4.png")}
        )
        s["wirelessDisabled"] = _uses(
            _indicator, {"img": _load_image("Icons/icon_wireless_disabled.png")}
        )
        s["wirelessWaiting"] = _uses(
            _indicator, {"img": _load_image("Icons/icon_wireless_waiting.png")}
        )
        s["wired"] = _uses(_indicator, {"img": _load_image("Icons/icon_ethernet.png")})
        s["wlan"] = _uses(s["wirelessLevel4"])

        # Demo / debug / misc (Lua L2362+)
        s["demo_text"] = _uses(s.get("text", {}))
        s["preview_text"] = _uses(s.get("text", {}))
        s["debug_canvas"] = {"hidden": 1}
        s["power_on_window"] = _uses(s["window"])

        # Region icons (Lua L2190-2197)
        s["region_US"] = _uses(
            _buttonicon,
            {"img": _load_image("IconsResized/icon_region_americas" + skinSuffix)},
        )
        s["region_XX"] = _uses(
            _buttonicon,
            {"img": _load_image("IconsResized/icon_region_other" + skinSuffix)},
        )

        # button_none — invisible button (Lua L2138-2145)
        s["button_none"] = {
            "bgImg": False,
            "w": TITLE_BUTTON_WIDTH - 12,
            "border": [8, 0, 8, 0],
            "padding": 0,
        }

        # Volume min/max buttons (Lua L2159-2169)
        s["button_volume_min"] = {
            "img": _load_image("Icons/icon_toolbar_vol_down.png"),
            "border": [5, 0, 5, 0],
        }
        s["button_volume_max"] = {
            "img": _load_image("Icons/icon_toolbar_vol_up.png"),
            "border": [5, 0, 5, 0],
        }

        # ---------------------------------------------------------------
        # NowPlaying styles
        # ---------------------------------------------------------------
        # Dynamic sizing — matches Lua original exactly:
        #   NP_*_FONT_SIZE = math.floor(72 * screenWidth / 1920)
        #   coverSize = math.floor(min(screenHeight - TITLE_HEIGHT - 20,
        #                               screenWidth/2 - 50) / 10) * 10
        NP_ARTISTALBUM_FONT_SIZE = max(14, int(72 * screen_width / 1920))
        NP_TRACK_FONT_SIZE = max(14, int(72 * screen_width / 1920))

        controlHeight = 66
        controlWidth = 100
        buttonPadding = 0

        coverSize = (
            int(min(screen_height - TITLE_HEIGHT - 20, screen_width / 2 - 50) // 10)
            * 10
        )

        # _tracklayout — absolute positioning, right of cover art
        _track_x = coverSize + int(100 * screen_width / 1920)
        _track_text_w = screen_width - _track_x - int(50 * screen_width / 1920)
        _track_progress_w = screen_width - _track_x - int(250 * screen_width / 1920)
        _track_time_w = int(100 * screen_width / 1920)
        _track_time_font_size = max(9, int(28 * screen_width / 1920 + 0.5))

        # Vertical center of the cover area
        _cover_y = TITLE_HEIGHT + (screen_height - TITLE_HEIGHT - coverSize) / 2

        _tracklayout = {
            "border": [10, 0, 10, 0],
            "position": LAYOUT_NONE,
            "w": WH_FILL,
            "align": "left",
            "lineHeight": NP_TRACK_FONT_SIZE,
            "fg": TEXT_COLOR,
            "x": _track_x,
        }

        _transportControlButton = {
            "w": controlWidth,
            "h": controlHeight,
            "align": "center",
            "padding": buttonPadding,
        }

        _transportControlBorder = _uses(
            _transportControlButton,
            {
                "w": 2,
                "padding": 0,
                "img": touchToolbarKeyDivider,
            },
        )

        # NowPlaying window
        s["nowplaying"] = _uses(
            s["window"],
            {
                "bgImg": blackBackground,
                # Title bar
                "title": _uses(
                    s["title"],
                    {
                        "zOrder": 1,
                        "text": {
                            "font": _boldfont(TITLE_FONT_SIZE),
                        },
                    },
                ),
                # Song metadata — track title
                "nptitle": {
                    "order": ["nptrack"],
                    "position": LAYOUT_NONE,
                    "border": _tracklayout["border"],
                    "x": _tracklayout["x"],
                    "y": int(_cover_y + coverSize * 0 / 6),
                    "h": 90,
                    "nptrack": {
                        "padding": [0, 20, 0, 0],
                        "w": _track_text_w,
                        "align": _tracklayout["align"],
                        "lineHeight": _tracklayout["lineHeight"],
                        "fg": _tracklayout["fg"],
                        "font": _boldfont(NP_TRACK_FONT_SIZE),
                        "sh": TEXT_SH_COLOR,
                    },
                },
                # Artist group (3-line mode)
                "npartistgroup": {
                    "order": ["npartist"],
                    "position": LAYOUT_NONE,
                    "border": _tracklayout["border"],
                    "x": _tracklayout["x"],
                    "y": int(_cover_y + coverSize * 1 / 6),
                    "h": 90,
                    "npartist": {
                        "padding": [0, 20, 0, 0],
                        "w": _track_text_w,
                        "align": _tracklayout["align"],
                        "lineHeight": _tracklayout["lineHeight"],
                        "fg": _tracklayout["fg"],
                        "font": _font(NP_ARTISTALBUM_FONT_SIZE),
                        "sh": TEXT_SH_COLOR,
                    },
                },
                # Album group (3-line mode)
                "npalbumgroup": {
                    "order": ["npalbum"],
                    "position": LAYOUT_NONE,
                    "border": _tracklayout["border"],
                    "x": _tracklayout["x"],
                    "y": int(_cover_y + coverSize * 2 / 6),
                    "h": 90,
                    "npalbum": {
                        "w": _track_text_w,
                        "padding": [0, 20, 0, 0],
                        "align": _tracklayout["align"],
                        "lineHeight": _tracklayout["lineHeight"],
                        "fg": _tracklayout["fg"],
                        "font": _font(NP_ARTISTALBUM_FONT_SIZE),
                        "sh": TEXT_SH_COLOR,
                    },
                },
                # Combined artist+album (2-line mode) — hidden by default
                "npartistalbum": {
                    "hidden": 1,
                },
                # Cover art
                "npartwork": {
                    "w": coverSize,
                    "position": LAYOUT_NONE,
                    "x": int(50 * screen_width / 1920),
                    "y": int(_cover_y),
                    "align": "center",
                    "h": coverSize,
                    "artwork": {
                        "w": coverSize,
                        "h": coverSize,
                        "align": "center",
                        "padding": 0,
                        "img": False,
                    },
                },
                "npvisu": {"hidden": 1},
                # Transport controls (repeat + shuffle)
                "npcontrols": {
                    "order": ["repeatMode", "shuffleMode"],
                    "position": LAYOUT_NONE,
                    "x": int(_track_x + (_track_text_w - 8) / 2 - controlWidth),
                    "y": int(_cover_y + coverSize * 5.5 / 6),
                    "h": controlHeight,
                    "w": WH_FILL,
                    "shuffleMode": _uses(
                        _transportControlButton,
                        {
                            "img": _load_image("Icons/icon_toolbar_shuffle_off.png"),
                        },
                    ),
                    "shuffleOff": _uses(
                        _transportControlButton,
                        {
                            "img": _load_image("Icons/icon_toolbar_shuffle_off.png"),
                        },
                    ),
                    "shuffleSong": _uses(
                        _transportControlButton,
                        {
                            "img": _load_image("Icons/icon_toolbar_shuffle_on.png"),
                        },
                    ),
                    "shuffleAlbum": _uses(
                        _transportControlButton,
                        {
                            "img": _load_image(
                                "Icons/icon_toolbar_shuffle_album_on.png"
                            ),
                        },
                    ),
                    "repeatMode": _uses(
                        _transportControlButton,
                        {
                            "img": _load_image("Icons/icon_toolbar_repeat_off.png"),
                        },
                    ),
                    "repeatOff": _uses(
                        _transportControlButton,
                        {
                            "img": _load_image("Icons/icon_toolbar_repeat_off.png"),
                        },
                    ),
                    "repeatPlaylist": _uses(
                        _transportControlButton,
                        {
                            "img": _load_image("Icons/icon_toolbar_repeat_on.png"),
                        },
                    ),
                    "repeatSong": _uses(
                        _transportControlButton,
                        {
                            "img": _load_image("Icons/icon_toolbar_repeat_song_on.png"),
                        },
                    ),
                    "shuffleDisabled": _uses(
                        _transportControlButton,
                        {
                            "img": _load_image("Icons/icon_toolbar_shuffle_dis.png"),
                        },
                    ),
                    "repeatDisabled": _uses(
                        _transportControlButton,
                        {
                            "img": _load_image("Icons/icon_toolbar_repeat_dis.png"),
                        },
                    ),
                },
                # Progress bar
                "npprogress": {
                    "position": LAYOUT_NONE,
                    "x": _track_x,
                    "y": int(_cover_y + coverSize * 5 / 6),
                    "padding": [0, 10, 0, 0],
                    "order": ["elapsed", "slider", "remain"],
                    "elapsed": {
                        "w": _track_time_w,
                        "align": "left",
                        "padding": [0, 0, 4, 10],
                        "font": _boldfont(_track_time_font_size),
                        "fg": [0xE7, 0xE7, 0xE7],
                        "sh": [0x37, 0x37, 0x37],
                    },
                    "remain": {
                        "w": _track_time_w,
                        "align": "right",
                        "padding": [4, 0, 0, 10],
                        "font": _boldfont(_track_time_font_size),
                        "fg": [0xE7, 0xE7, 0xE7],
                        "sh": [0x37, 0x37, 0x37],
                    },
                    "elapsedSmall": {
                        "w": _track_time_w,
                        "align": "left",
                        "padding": [0, 0, 4, 20],
                        "font": _boldfont(_track_time_font_size),
                        "fg": [0xE7, 0xE7, 0xE7],
                        "sh": [0x37, 0x37, 0x37],
                    },
                    "remainSmall": {
                        "w": _track_time_w,
                        "align": "right",
                        "padding": [4, 0, 0, 20],
                        "font": _boldfont(_track_time_font_size),
                        "fg": [0xE7, 0xE7, 0xE7],
                        "sh": [0x37, 0x37, 0x37],
                    },
                    "npprogressB": {
                        "w": _track_progress_w,
                        "h": 50,
                        "padding": [0, 0, 0, 0],
                        "position": LAYOUT_SOUTH,
                        "horizontal": 1,
                        "bgImg": _songProgressBackground,
                        "img": _songProgressBar,
                    },
                },
                # Special style for when there shouldn't be a progress bar
                # (e.g., internet radio streams)
                "npprogressNB": {
                    "order": ["elapsed"],
                    "position": LAYOUT_NONE,
                    "x": _track_x,
                    "y": int(_cover_y + coverSize * 5 / 6),
                    "elapsed": {
                        "w": _track_time_w,
                        "align": "left",
                        "padding": [0, 0, 4, 10],
                        "font": _boldfont(_track_time_font_size),
                        "fg": [0xE7, 0xE7, 0xE7],
                        "sh": [0x37, 0x37, 0x37],
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

        # Pressed states
        s["nowplaying"]["pressed"] = s["nowplaying"]
        s["nowplaying"]["nptitle"]["pressed"] = _uses(s["nowplaying"]["nptitle"])
        s["nowplaying"]["npalbumgroup"]["pressed"] = _uses(
            s["nowplaying"]["npalbumgroup"]
        )
        s["nowplaying"]["npartistgroup"]["pressed"] = _uses(
            s["nowplaying"]["npartistgroup"]
        )
        s["nowplaying"]["npartwork"]["pressed"] = s["nowplaying"]["npartwork"]
        s["nowplaying"]["npcontrols"]["pressed"] = {"hidden": 1}

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
                "npartwork": {"hidden": 1},
                "npvisu": {
                    "hidden": 0,
                    "position": LAYOUT_WEST,
                    "w": WH_FILL,
                    "align": "center",
                    "border": [0, TITLE_HEIGHT, 0, controlHeight + 20],
                },
            },
        )

        # VU analog meter NowPlaying style
        s["nowplaying_vuanalog_text"] = _uses(
            s["nowplaying_spectrum_text"],
        )

        # Pressed states for variants
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
        s["npprogressB_disabled"] = _uses(
            s.get("npprogressB", {}),
            {
                "img": _songProgressBarDisabled,
            },
        )

        # Visualizer: common container (Lua L2849-2855)
        s["nowplaying_visualizer_common"] = _uses(
            s["nowplaying"],
            {
                "npartwork": {"hidden": 1},
            },
        )

        # ---------------------------------------------------------------
        # Volume / Scanner / Brightness / Settings sliders (Lua L2059-2977)
        # ---------------------------------------------------------------
        s["volume_slider"] = {
            "w": WH_FILL,
            "border": [0, 0, 0, 10],
            "bgImg": _volumeSliderBackground,
            "img": _popupSliderBar,
        }

        s["scanner_slider"] = _uses(
            s["volume_slider"],
            {"img": _volumeSliderBar},
        )

        s["scanner_popup"] = _uses(
            s["popup"],
            {
                "text": {
                    "padding": [8, 4, 8, 0],
                    "font": _boldfont(POPUP_TEXT_SIZE_1),
                    "fg": TEXT_COLOR,
                    "sh": TEXT_SH_COLOR,
                    "align": "center",
                },
            },
        )

        sliderButtonPressed = _tile_image(imgpath + "Buttons/keyboard_button_press.png")

        s["brightness_group"] = {
            "order": ["down", "div1", "slider", "div2", "up"],
            "position": LAYOUT_SOUTH,
            "h": 56,
            "w": WH_FILL,
            "bgImg": sliderBackground,
            "div1": _uses(_transportControlBorder),
            "div2": _uses(_transportControlBorder),
            "down": _uses(
                _transportControlButton,
                {
                    "w": 56,
                    "h": 56,
                    "img": _load_image("Icons/icon_toolbar_brightness_down.png"),
                },
            ),
            "up": _uses(
                _transportControlButton,
                {
                    "w": 56,
                    "h": 56,
                    "img": _load_image("Icons/icon_toolbar_brightness_up.png"),
                },
            ),
        }
        s["brightness_group"]["pressed"] = {
            "down": _uses(
                s["brightness_group"]["down"], {"bgImg": sliderButtonPressed}
            ),
            "up": _uses(s["brightness_group"]["up"], {"bgImg": sliderButtonPressed}),
        }

        s["brightness_slider"] = {
            "w": WH_FILL,
            "border": [5, 12, 5, 0],
            "padding": [6, 0, 6, 0],
            "position": LAYOUT_SOUTH,
            "horizontal": 1,
            "bgImg": _volumeSliderBackground,
            "img": _volumeSliderBar,
            "pillImg": _volumeSliderPill,
        }

        s["settings_slider_group"] = _uses(
            s["brightness_group"],
            {
                "down": {
                    "img": _load_image("Icons/icon_toolbar_minus.png"),
                },
                "up": {
                    "img": _load_image("Icons/icon_toolbar_plus.png"),
                },
            },
        )
        s["settings_slider"] = _uses(s["brightness_slider"])
        s["settings_slider_group"]["pressed"] = {
            "down": _uses(
                s["settings_slider_group"]["down"],
                {
                    "bgImg": sliderButtonPressed,
                    "img": _load_image("Icons/icon_toolbar_minus_dis.png"),
                },
            ),
            "up": _uses(
                s["settings_slider_group"]["up"],
                {
                    "bgImg": sliderButtonPressed,
                    "img": _load_image("Icons/icon_toolbar_plus_dis.png"),
                },
            ),
        }

        s["settings_volume_group"] = _uses(
            s["brightness_group"],
            {
                "down": {
                    "img": _load_image("Icons/icon_toolbar_vol_down.png"),
                },
                "up": {
                    "img": _load_image("Icons/icon_toolbar_vol_up.png"),
                },
            },
        )
        s["settings_volume_group"]["pressed"] = {
            "down": _uses(
                s["settings_volume_group"]["down"],
                {
                    "bgImg": sliderButtonPressed,
                    "img": _load_image("Icons/icon_toolbar_vol_down_dis.png"),
                },
            ),
            "up": _uses(
                s["settings_volume_group"]["up"],
                {
                    "bgImg": sliderButtonPressed,
                    "img": _load_image("Icons/icon_toolbar_vol_up_dis.png"),
                },
            ),
        }

        # ---------------------------------------------------------------
        # Toast popup sub-styles (Lua L1483-1520)
        # ---------------------------------------------------------------
        s["toast_popup_text"] = {
            "w": WH_FILL,
            "h": WH_FILL,
            "padding": [10, 12, 10, 0],
            "font": _font(HELP_FONT_SIZE),
            "lineHeight": HELP_FONT_SIZE + 5,
            "fg": TEXT_COLOR,
            "sh": TEXT_SH_COLOR,
            "align": "top-left",
        }
        s["toast_popup_textarea"] = _uses(s["toast_popup_text"])

        # ---------------------------------------------------------------
        # Black popup (Lua L1535-1545)
        # ---------------------------------------------------------------
        s["black_popup"] = _uses(
            s["popup"],
            {
                "bgImg": False,
            },
        )

        # ---------------------------------------------------------------
        # Alarm styles (Lua L1547-1580)
        # ---------------------------------------------------------------
        s["alarm_header"] = _uses(s["title"])
        s["alarm_popup"] = _uses(s["popup"])

        # ---------------------------------------------------------------
        # Image popup (Lua L1586-1594)
        # ---------------------------------------------------------------
        s["image_popup"] = _uses(s["popup"])

        # ---------------------------------------------------------------
        # Badge styles (Lua L1601-1610)
        # ---------------------------------------------------------------
        _badge = {
            "position": LAYOUT_NONE,
            "zOrder": 99,
        }
        s["badge_none"] = _uses(_badge, {"img": False})
        s["badge_favorite"] = _uses(
            _badge, {"img": _load_image("Icons/icon_badge_fav.png")}
        )
        s["badge_add"] = _uses(_badge, {"img": _load_image("Icons/icon_badge_add.png")})

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
        # Home menu
        # ---------------------------------------------------------------
        s["home_menu"] = _uses(s["text_list"])

        return s

    # ------------------------------------------------------------------
    # free
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Resolution variant methods
    # ------------------------------------------------------------------

    def skin_1080p(
        self,
        s: Style,
        reload: bool = False,
        use_default_size: bool = False,
    ) -> Style:
        """Skin variant for 1080p (1920x1080) displays."""
        global _coverSize
        _coverSize = 900
        return self._skin_common(s, reload, use_default_size, 1920, 1080)

    def skin_720p(
        self,
        s: Style,
        reload: bool = False,
        use_default_size: bool = False,
    ) -> Style:
        """Skin variant for 720p (1280x720) displays."""
        global _coverSize
        _coverSize = 600
        return self._skin_common(s, reload, use_default_size, 1280, 720)

    def skin_1280_1024(
        self,
        s: Style,
        reload: bool = False,
        use_default_size: bool = False,
    ) -> Style:
        """Skin variant for 1280x1024 displays."""
        global _coverSize
        _coverSize = 900
        return self._skin_common(s, reload, use_default_size, 1280, 1024)

    def skin_vga(
        self,
        s: Style,
        reload: bool = False,
        use_default_size: bool = False,
    ) -> Style:
        """Skin variant for VGA (640x480) displays."""
        global _coverSize
        _coverSize = 400
        return self._skin_common(s, reload, use_default_size, 640, 480)

    # Alias: default skin method calls 1080p
    def skin(
        self,
        s: Style,
        reload: bool = False,
        use_default_size: bool = False,
    ) -> Style:
        """Default skin method — delegates to skin_1080p."""
        return self.skin_1080p(s, reload, use_default_size)

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
