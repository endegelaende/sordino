"""
jive.applets.joggler_skin.joggler_skin_applet — JogglerSkin applet.

Ported from ``share/jive/applets/JogglerSkin/JogglerSkinApplet.lua``
(~3887 LOC) in the original jivelite project.

This applet implements the primary skin for 800×480 landscape displays
(O2 Joggler, Raspberry Pi 7" touchscreen, etc.).  It defines the
complete style table including:

* Menu styles (5-line items, 3-line items, icon lists, playlists)
* Keyboard (touch) styles with 9-patch tile backgrounds
* NowPlaying styles (artwork+text, large art, art only, text only,
  spectrum analyser, VU meter)
* Transport controls (play/pause/rew/fwd/shuffle/repeat/volume)
* Title bar buttons (back, home, now playing, playlist, etc.)
* Context menus, toast popups, slider popups, alarm popups
* Home menu icons, player model icons, wireless indicators
* Multiple resolution variants (800×480, 1024×600, 1280×800, 1366×768,
  custom)
* NowPlaying toolbar button configuration UI

Key implementation notes
------------------------

* **_uses(parent, overrides)** — recursive deep-merge style
  inheritance, mirroring the Lua ``setmetatable(__index)`` trick.

* Image/tile/font references are stored as lazy-loadable description
  dicts (``{"__type__": "image", "path": ...}``) so that tests can
  run without pygame initialised.

* The ``skin()`` method receives width/height parameters and builds
  all styles relative to those dimensions.

* Resolution variants (``skin1024x600``, ``skin1280x800``, etc.) call
  ``skin()`` with specific dimensions and then apply tweaks.

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Copyright 2013-2014 Adrian Smith (jivelite amendments)
Redesigned by Andy Davison (birdslikewires.co.uk)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

import copy
import math
import os
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

__all__ = ["JogglerSkinApplet"]

log = logger("applet.JogglerSkin")

# ---------------------------------------------------------------------------
# Type alias
# ---------------------------------------------------------------------------
Style = Dict[str, Any]

# ---------------------------------------------------------------------------
# Path prefixes
# ---------------------------------------------------------------------------
_IMGPATH = "applets/JogglerSkin/images/"
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

# Toolbar button keys (matching Lua tbButtons table)
TB_BUTTONS = [
    "rew",
    "play",
    "fwd",
    "repeatMode",
    "shuffleMode",
    "volDown",
    "volSlider",
    "volUp",
]


# ---------------------------------------------------------------------------
# Helper: deep-merge style dicts  (Lua _uses equivalent)
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
    """Return a lazy reference to an image in the JogglerSkin images dir."""
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


# ============================================================================
# JogglerSkinApplet
# ============================================================================


class JogglerSkinApplet(Applet):
    """Skin applet for 800×480 landscape displays.

    The ``skin()`` method builds a complete style dict.  Resolution
    variants (``skin1024x600``, etc.) call ``skin()`` with specific
    dimensions and apply tweaks.

    The applet also provides:

    * ``getNowPlayingScreenButtons()`` — return toolbar button settings
    * ``setNowPlayingScreenButtons(button, is_selected)`` — toggle a button
    * ``npButtonSelectorShow()`` — show the button config UI
    * ``buttonSettingsMenuItem()`` — build a menu item for settings
    """

    def __init__(self) -> None:
        super().__init__()
        self.images: Style = {}
        self.imageTiles: Style = {}
        self.hTiles: Style = {}
        self.vTiles: Style = {}
        self.tiles: Style = {}

    def init(self) -> None:
        """Initialise the applet — add settings menu item."""
        super().init()
        self.images = {}
        self.imageTiles = {}
        self.hTiles = {}
        self.vTiles = {}
        self.tiles = {}

        # Add the NP button settings menu item to jiveMain
        try:
            from jive.jive_main import jive_main as _jm

            if _jm is not None:
                _jm.add_item(self.buttonSettingsMenuItem())
        except (ImportError, AttributeError):
            pass

    # ------------------------------------------------------------------
    # Parameters (overridable by child skins)
    # ------------------------------------------------------------------

    def param(self) -> Style:
        """Return skin parameter constants."""
        screen_width, screen_height = self._get_screen_size()
        max_artwork = f"{screen_height}x{screen_height}"
        mid_artwork = f"{screen_height - 180}x{screen_height - 180}"

        return {
            "THUMB_SIZE": 40,
            "THUMB_SIZE_MENU": 40,
            "NOWPLAYING_MENU": False,
            "NOWPLAYING_TRACKINFO_LINES": 3,
            "POPUP_THUMB_SIZE": 120,
            "piCorePlayerStyle": "hm_settings_pcp",
            "nowPlayingScreenStyles": [
                {
                    "style": "nowplaying",
                    "artworkSize": mid_artwork,
                    "text": self.string("ART_AND_TEXT")
                    if self._strings_table
                    else "Art & Text",
                },
                {
                    "style": "nowplaying_large_art",
                    "artworkSize": max_artwork,
                    "titleXofYonly": True,
                    "text": self.string("LARGE_ART_AND_TEXT")
                    if self._strings_table
                    else "Large Art & Text",
                },
                {
                    "style": "nowplaying_art_only",
                    "artworkSize": max_artwork,
                    "suppressTitlebar": 1,
                    "text": self.string("ART_ONLY")
                    if self._strings_table
                    else "Art Only",
                },
                {
                    "style": "nowplaying_text_only",
                    "artworkSize": mid_artwork,
                    "text": self.string("TEXT_ONLY")
                    if self._strings_table
                    else "Text Only",
                },
                {
                    "style": "nowplaying_spectrum_text",
                    "artworkSize": mid_artwork,
                    "localPlayerOnly": 1,
                    "text": self.string("SPECTRUM_ANALYZER")
                    if self._strings_table
                    else "Spectrum Analyzer",
                },
                {
                    "style": "nowplaying_vuanalog_text",
                    "artworkSize": mid_artwork,
                    "localPlayerOnly": 1,
                    "text": self.string("ANALOG_VU_METER")
                    if self._strings_table
                    else "Analog VU Meter",
                },
            ],
        }

    # ------------------------------------------------------------------
    # Helper to get screen size
    # ------------------------------------------------------------------

    @staticmethod
    def _get_screen_size() -> Tuple[int, int]:
        """Return (width, height) from Framework, defaulting to 800×480."""
        try:
            from jive.ui.framework import framework as _fw

            if _fw is not None:
                sw, sh = _fw.get_screen_size()
                if sw > 0 and sh > 0:
                    return sw, sh
        except Exception:
            pass
        return 800, 480

    # ------------------------------------------------------------------
    # Main skin method
    # ------------------------------------------------------------------

    def skin(
        self,
        s: Style,
        reload: bool = False,
        use_default_size: bool = False,
        w: Optional[int] = None,
        h: Optional[int] = None,
    ) -> Style:
        """Populate *s* with the complete JogglerSkin style table.

        Parameters
        ----------
        s : dict
            The style dict to populate (typically ``{}``).
        reload : bool
            True when reloading the skin.
        use_default_size : bool
            True to use default screen size.
        w, h : int or None
            Override screen dimensions.  Defaults to 800×480.

        Returns
        -------
        dict
            The populated style dict *s*.
        """
        if w is None:
            w = 800
        if h is None:
            h = 480

        screen_width = w
        screen_height = h

        # Skin variant suffix
        this_skin = "touch"
        skin_suffix = "_" + this_skin + ".png"

        # ---------------------------------------------------------------
        # Pre-load tile/image references
        # ---------------------------------------------------------------
        input_title_box = _tile_image(_IMGPATH + "Titlebar/titlebar.png")
        back_button = _tile_image(_IMGPATH + "Icons/icon_back_button_tb.png")
        cancel_button = _tile_image(_IMGPATH + "Icons/icon_close_button_tb.png")
        home_button = _tile_image(_IMGPATH + "Icons/icon_home_button_tb.png")
        help_button = _tile_image(_IMGPATH + "Icons/icon_help_button_tb.png")
        power_button = _tile_image(_IMGPATH + "Icons/icon_power_button_tb.png")
        now_playing_button = _tile_image(_IMGPATH + "Icons/icon_nplay_button_tb.png")
        playlist_button = _tile_image(_IMGPATH + "Icons/icon_nplay_list_tb.png")
        more_button = _tile_image(_IMGPATH + "Icons/icon_more_tb.png")
        touch_toolbar_background = _tile_image(
            _IMGPATH + "Touch_Toolbar/toolbar_tch_bkgrd.png"
        )
        slider_background = _tile_image(_IMGPATH + "Touch_Toolbar/toolbar_lrg.png")
        touch_toolbar_key_divider = _tile_image(
            _IMGPATH + "Touch_Toolbar/toolbar_divider.png"
        )
        delete_key_background = _tile_image(
            _IMGPATH + "Buttons/button_delete_text_entry.png"
        )
        delete_key_pressed_background = _tile_image(
            _IMGPATH + "Buttons/button_delete_text_entry_press.png"
        )
        help_text_background = _tile_image(_IMGPATH + "Titlebar/tbar_dropdwn_bkrgd.png")

        black_background = _fill_color(0x000000FF)

        five_item_box = _tile_htiles(
            [
                _IMGPATH + "5_line_lists/tch_5line_divider_l.png",
                _IMGPATH + "5_line_lists/tch_5line_divider.png",
                _IMGPATH + "5_line_lists/tch_5line_divider_r.png",
            ]
        )
        five_item_selection_box = _tile_htiles(
            [
                None,
                _IMGPATH + "5_line_lists/menu_sel_box_5line.png",
                _IMGPATH + "5_line_lists/menu_sel_box_5line_r.png",
            ]
        )
        five_item_pressed_box = _tile_htiles(
            [
                None,
                _IMGPATH + "5_line_lists/menu_sel_box_5line_press.png",
                _IMGPATH + "5_line_lists/menu_sel_box_5line_press_r.png",
            ]
        )

        three_item_selection_box = _tile_htiles(
            [
                _IMGPATH + "3_line_lists/menu_sel_box_3line_l.png",
                _IMGPATH + "3_line_lists/menu_sel_box_3line.png",
                _IMGPATH + "3_line_lists/menu_sel_box_3line_r.png",
            ]
        )
        three_item_pressed_box = _tile_image(
            _IMGPATH + "3_line_lists/menu_sel_box_3item_press.png"
        )

        context_menu_pressed_box = _tile_9patch(
            [
                _IMGPATH + "Popup_Menu/button_cm_press.png",
                _IMGPATH + "Popup_Menu/button_cm_tl_press.png",
                _IMGPATH + "Popup_Menu/button_cm_t_press.png",
                _IMGPATH + "Popup_Menu/button_cm_tr_press.png",
                _IMGPATH + "Popup_Menu/button_cm_r_press.png",
                _IMGPATH + "Popup_Menu/button_cm_br_press.png",
                _IMGPATH + "Popup_Menu/button_cm_b_press.png",
                _IMGPATH + "Popup_Menu/button_cm_bl_press.png",
                _IMGPATH + "Popup_Menu/button_cm_l_press.png",
            ]
        )

        # Keyboard tile definitions
        key_top_left = _tile_9patch(
            [
                _IMGPATH + "Text_Entry/Keyboard_Touch/keyboard_bkgrd.png",
                _IMGPATH + "Text_Entry/Keyboard_Touch/keyboard_bkgrd_tl.png",
                _IMGPATH + "Text_Entry/Keyboard_Touch/keyboard_bkgrd_t.png",
                None,
                None,
                None,
                None,
                None,
                _IMGPATH + "Text_Entry/Keyboard_Touch/keyboard_bkgrd_l.png",
            ]
        )
        key_top_left_pressed = _tile_9patch(
            [
                _IMGPATH + "Buttons/keybrd_n_button_press.png",
                _IMGPATH + "Buttons/keybrd_nw_button_press_tl.png",
                _IMGPATH + "Buttons/keybrd_n_button_press_t.png",
                None,
                None,
                None,
                None,
                None,
                _IMGPATH + "Buttons/keybrd_nw_button_press_l.png",
            ]
        )
        key_top = _tile_9patch(
            [
                _IMGPATH + "Text_Entry/Keyboard_Touch/keyboard_bkgrd.png",
                None,
                _IMGPATH + "Text_Entry/Keyboard_Touch/keyboard_bkgrd_t_wvert.png",
                None,
                None,
                None,
                None,
                None,
                _IMGPATH + "Text_Entry/Keyboard_Touch/keyboard_divider_vert.png",
            ]
        )
        key_top_pressed = _tile_9patch(
            [
                _IMGPATH + "Buttons/keybrd_n_button_press.png",
                None,
                _IMGPATH + "Buttons/keybrd_n_button_press_t.png",
                None,
                None,
                None,
                None,
                None,
                _IMGPATH + "Text_Entry/Keyboard_Touch/keyboard_divider_vert.png",
            ]
        )
        key_top_right = _tile_9patch(
            [
                _IMGPATH + "Text_Entry/Keyboard_Touch/keyboard_bkgrd.png",
                None,
                _IMGPATH + "Text_Entry/Keyboard_Touch/keyboard_bkgrd_t_wvert.png",
                _IMGPATH + "Text_Entry/Keyboard_Touch/keyboard_bkgrd_tr.png",
                _IMGPATH + "Text_Entry/Keyboard_Touch/keyboard_bkgrd_r.png",
                None,
                None,
                None,
                _IMGPATH + "Text_Entry/Keyboard_Touch/keyboard_divider_vert.png",
            ]
        )
        key_top_right_pressed = _tile_9patch(
            [
                _IMGPATH + "Buttons/keybrd_n_button_press.png",
                None,
                _IMGPATH + "Buttons/keybrd_n_button_press_t.png",
                _IMGPATH + "Buttons/keybrd_ne_button_press_tr.png",
                _IMGPATH + "Buttons/keybrd_ne_button_press_r.png",
                None,
                None,
                None,
                _IMGPATH + "Text_Entry/Keyboard_Touch/keyboard_divider_vert.png",
            ]
        )
        key_left = _tile_9patch(
            [
                _IMGPATH + "Text_Entry/Keyboard_Touch/keyboard_bkgrd.png",
                _IMGPATH + "Text_Entry/Keyboard_Touch/keyboardLeftEdge.png",
                _IMGPATH + "Text_Entry/Keyboard_Touch/keyboard_divider_hort.png",
                None,
                None,
                None,
                None,
                None,
                _IMGPATH + "Text_Entry/Keyboard_Touch/keyboard_bkgrd_l.png",
            ]
        )
        key_left_pressed = _tile_9patch(
            [
                _IMGPATH + "Buttons/keyboard_button_press.png",
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                _IMGPATH + "Buttons/keyboard_button_press.png",
            ]
        )
        key_middle = _tile_9patch(
            [
                _IMGPATH + "Text_Entry/Keyboard_Touch/keyboard_bkgrd.png",
                None,
                _IMGPATH + "Text_Entry/Keyboard_Touch/keyboard_divider_hort.png",
                None,
                None,
                None,
                None,
                None,
                _IMGPATH + "Text_Entry/Keyboard_Touch/keyboard_divider_vert.png",
            ]
        )
        key_middle_pressed = _tile_9patch(
            [
                _IMGPATH + "Buttons/keyboard_button_press.png",
                None,
                _IMGPATH + "Text_Entry/Keyboard_Touch/keyboard_divider_hort.png",
                None,
                None,
                None,
                None,
                None,
                _IMGPATH + "Text_Entry/Keyboard_Touch/keyboard_divider_vert.png",
            ]
        )
        slider_button_pressed = _tile_9patch(
            [
                _IMGPATH + "Buttons/keyboard_button_press.png",
                None,
                None,
                _IMGPATH + "Text_Entry/Keyboard_Touch/keyboard_divider_hort.png",
                None,
                None,
                None,
                None,
                _IMGPATH + "Text_Entry/Keyboard_Touch/keyboard_divider_vert.png",
            ]
        )
        key_right = _tile_9patch(
            [
                _IMGPATH + "Text_Entry/Keyboard_Touch/keyboard_bkgrd.png",
                None,
                _IMGPATH + "Text_Entry/Keyboard_Touch/keyboard_divider_hort.png",
                _IMGPATH + "Text_Entry/Keyboard_Touch/keyboardRightEdge.png",
                _IMGPATH + "Text_Entry/Keyboard_Touch/keyboard_bkgrd_r.png",
                None,
                None,
                None,
                _IMGPATH + "Text_Entry/Keyboard_Touch/keyboard_divider_vert.png",
            ]
        )
        key_right_pressed = _tile_9patch(
            [
                _IMGPATH + "Buttons/keyboard_button_press.png",
                None,
                None,
                None,
                _IMGPATH + "Buttons/keyboard_button_press.png",
                None,
                None,
                None,
                None,
            ]
        )
        key_bottom_left = _tile_9patch(
            [
                _IMGPATH + "Text_Entry/Keyboard_Touch/keyboard_bkgrd.png",
                _IMGPATH + "Text_Entry/Keyboard_Touch/keyboardLeftEdge.png",
                _IMGPATH + "Text_Entry/Keyboard_Touch/keyboard_divider_hort.png",
                None,
                None,
                None,
                _IMGPATH + "Text_Entry/Keyboard_Touch/keyboard_bkgrd_b.png",
                _IMGPATH + "Text_Entry/Keyboard_Touch/keyboard_bkgrd_bl.png",
                _IMGPATH + "Text_Entry/Keyboard_Touch/keyboard_bkgrd_l.png",
            ]
        )
        key_bottom_left_pressed = _tile_9patch(
            [
                _IMGPATH + "Buttons/keybrd_s_button_press.png",
                _IMGPATH + "Text_Entry/Keyboard_Touch/keyboardLeftEdge.png",
                _IMGPATH + "Text_Entry/Keyboard_Touch/keyboard_divider_hort.png",
                None,
                None,
                None,
                _IMGPATH + "Buttons/keybrd_s_button_press_b.png",
                _IMGPATH + "Buttons/keybrd_sw_button_press_bl.png",
                _IMGPATH + "Buttons/keybrd_sw_button_press_l.png",
            ]
        )
        key_bottom = _tile_9patch(
            [
                _IMGPATH + "Text_Entry/Keyboard_Touch/keyboard_bkgrd.png",
                None,
                _IMGPATH + "Text_Entry/Keyboard_Touch/keyboard_divider_hort.png",
                None,
                None,
                None,
                _IMGPATH + "Text_Entry/Keyboard_Touch/keyboard_bkgrd_b_wvert.png",
                None,
                _IMGPATH + "Text_Entry/Keyboard_Touch/keyboard_divider_vert.png",
            ]
        )
        key_bottom_pressed = _tile_9patch(
            [
                _IMGPATH + "Buttons/keybrd_s_button_press.png",
                None,
                _IMGPATH + "Text_Entry/Keyboard_Touch/keyboard_divider_hort.png",
                None,
                None,
                None,
                _IMGPATH + "Buttons/keybrd_s_button_press_b.png",
                None,
                _IMGPATH + "Text_Entry/Keyboard_Touch/keyboard_divider_vert.png",
            ]
        )
        key_bottom_right = _tile_9patch(
            [
                _IMGPATH + "Text_Entry/Keyboard_Touch/keyboard_bkgrd.png",
                None,
                _IMGPATH + "Text_Entry/Keyboard_Touch/keyboard_divider_hort.png",
                _IMGPATH + "Text_Entry/Keyboard_Touch/keyboardRightEdge.png",
                _IMGPATH + "Text_Entry/Keyboard_Touch/keyboard_bkgrd_r.png",
                _IMGPATH + "Text_Entry/Keyboard_Touch/keyboard_bkgrd_br.png",
                _IMGPATH + "Text_Entry/Keyboard_Touch/keyboard_bkgrd_b_wvert.png",
                None,
                _IMGPATH + "Text_Entry/Keyboard_Touch/keyboard_divider_vert.png",
            ]
        )
        key_bottom_right_pressed = _tile_9patch(
            [
                _IMGPATH + "Buttons/keybrd_s_button_press.png",
                None,
                _IMGPATH + "Text_Entry/Keyboard_Touch/keyboard_divider_hort.png",
                _IMGPATH + "Text_Entry/Keyboard_Touch/keyboardRightEdge.png",
                _IMGPATH + "Buttons/keybrd_se_button_press_r.png",
                _IMGPATH + "Buttons/keybrd_se_button_press_br.png",
                _IMGPATH + "Buttons/keybrd_s_button_press_b.png",
                None,
                _IMGPATH + "Text_Entry/Keyboard_Touch/keyboard_divider_vert.png",
            ]
        )

        title_box = _tile_9patch(
            [
                _IMGPATH + "Titlebar/titlebar.png",
                None,
                None,
                None,
                None,
                None,
                _IMGPATH + "Titlebar/titlebar_shadow.png",
                None,
                None,
            ]
        )

        textinput_background = _tile_9patch(
            [
                _IMGPATH + "Text_Entry/Keyboard_Touch/titlebar_box.png",
                _IMGPATH + "Text_Entry/Keyboard_Touch/text_entry_titlebar_box_tl.png",
                _IMGPATH + "Text_Entry/Keyboard_Touch/text_entry_titlebar_box_t.png",
                _IMGPATH + "Text_Entry/Keyboard_Touch/text_entry_titlebar_box_tr.png",
                _IMGPATH + "Text_Entry/Keyboard_Touch/text_entry_titlebar_box_r.png",
                _IMGPATH + "Text_Entry/Keyboard_Touch/text_entry_titlebar_box_br.png",
                _IMGPATH + "Text_Entry/Keyboard_Touch/text_entry_titlebar_box_b.png",
                _IMGPATH + "Text_Entry/Keyboard_Touch/text_entry_titlebar_box_bl.png",
                _IMGPATH + "Text_Entry/Keyboard_Touch/text_entry_titlebar_box_l.png",
            ]
        )

        pressed_titlebar_button_box = _tile_9patch(
            [
                _IMGPATH + "Buttons/button_titlebar_press.png",
                _IMGPATH + "Buttons/button_titlebar_tl_press.png",
                _IMGPATH + "Buttons/button_titlebar_t_press.png",
                _IMGPATH + "Buttons/button_titlebar_tr_press.png",
                _IMGPATH + "Buttons/button_titlebar_r_press.png",
                _IMGPATH + "Buttons/button_titlebar_br_press.png",
                _IMGPATH + "Buttons/button_titlebar_b_press.png",
                _IMGPATH + "Buttons/button_titlebar_bl_press.png",
                _IMGPATH + "Buttons/button_titlebar_l_press.png",
            ]
        )

        titlebar_button_box = _tile_9patch(
            [
                _IMGPATH + "Buttons/button_titlebar.png",
                _IMGPATH + "Buttons/button_titlebar_tl.png",
                _IMGPATH + "Buttons/button_titlebar_t.png",
                _IMGPATH + "Buttons/button_titlebar_tr.png",
                _IMGPATH + "Buttons/button_titlebar_r.png",
                _IMGPATH + "Buttons/button_titlebar_br.png",
                _IMGPATH + "Buttons/button_titlebar_b.png",
                _IMGPATH + "Buttons/button_titlebar_bl.png",
                _IMGPATH + "Buttons/button_titlebar_l.png",
            ]
        )

        popup_box = _tile_9patch(
            [
                _IMGPATH + "Popup_Menu/popup_box.png",
                _IMGPATH + "Popup_Menu/popup_box_tl.png",
                _IMGPATH + "Popup_Menu/popup_box_t.png",
                _IMGPATH + "Popup_Menu/popup_box_tr.png",
                _IMGPATH + "Popup_Menu/popup_box_r.png",
                _IMGPATH + "Popup_Menu/popup_box_br.png",
                _IMGPATH + "Popup_Menu/popup_box_b.png",
                _IMGPATH + "Popup_Menu/popup_box_bl.png",
                _IMGPATH + "Popup_Menu/popup_box_l.png",
            ]
        )

        context_menu_box = _tile_9patch(
            [
                _IMGPATH + "Popup_Menu/cm_popup_box.png",
                _IMGPATH + "Popup_Menu/cm_popup_box_tl.png",
                _IMGPATH + "Popup_Menu/cm_popup_box_t.png",
                _IMGPATH + "Popup_Menu/cm_popup_box_tr.png",
                _IMGPATH + "Popup_Menu/cm_popup_box_r.png",
                _IMGPATH + "Popup_Menu/cm_popup_box_br.png",
                _IMGPATH + "Popup_Menu/cm_popup_box_b.png",
                _IMGPATH + "Popup_Menu/cm_popup_box_bl.png",
                _IMGPATH + "Popup_Menu/cm_popup_box_l.png",
            ]
        )

        scroll_background = _tile_vtiles(
            [
                _IMGPATH + "Scroll_Bar/scrollbar_bkgrd_t.png",
                _IMGPATH + "Scroll_Bar/scrollbar_bkgrd.png",
                _IMGPATH + "Scroll_Bar/scrollbar_bkgrd_b.png",
            ]
        )
        scroll_bar = _tile_vtiles(
            [
                _IMGPATH + "Scroll_Bar/scrollbar_body_t.png",
                _IMGPATH + "Scroll_Bar/scrollbar_body.png",
                _IMGPATH + "Scroll_Bar/scrollbar_body_b.png",
            ]
        )

        popup_background = black_background

        textinput_cursor = _tile_image(
            _IMGPATH + "Text_Entry/Keyboard_Touch/tch_cursor.png"
        )

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
        SELECT_SH_COLOR = []

        TITLE_HEIGHT = 65
        TITLE_FONT_SIZE = 20
        TITLEBAR_FONT_SIZE = 28
        ALBUMMENU_FONT_SIZE = 20
        ALBUMMENU_SMALL_FONT_SIZE = 16
        TEXTMENU_FONT_SIZE = 25
        POPUP_TEXT_SIZE_1 = 26
        POPUP_TEXT_SIZE_2 = 26
        TRACK_FONT_SIZE = 18
        TEXTAREA_FONT_SIZE = 18
        CENTERED_TEXTAREA_FONT_SIZE = 28

        CM_MENU_HEIGHT = 45

        TEXTINPUT_FONT_SIZE = 60
        TEXTINPUT_SELECTED_FONT_SIZE = 68

        HELP_FONT_SIZE = 18
        UPDATE_SUBTEXT_SIZE = 20

        ITEM_ICON_ALIGN = "center"
        ITEM_LEFT_PADDING = 12
        THREE_ITEM_HEIGHT = 72
        FIVE_ITEM_HEIGHT = 45
        TITLE_BUTTON_WIDTH = 76

        small_spinny = {
            "img": _load_image("Alerts/wifi_connecting_sm.png"),
            "frameRate": 8,
            "frameWidth": 26,
            "padding": 0,
            "h": WH_FILL,
        }
        large_spinny = {
            "img": _load_image("Alerts/wifi_connecting.png"),
            "position": LAYOUT_CENTER,
            "w": WH_FILL,
            "align": "center",
            "frameRate": 8,
            "frameWidth": 120,
            "padding": [0, 0, 0, 10],
        }
        no_button = {
            "img": False,
            "bgImg": False,
            "w": 0,
        }

        play_arrow = {
            "img": _load_image("Icons/selection_play_3line_on.png"),
        }
        add_arrow = {
            "img": _load_image("Icons/selection_add_3line_on.png"),
        }
        fav_item = {
            "img": _load_image("Icons/icon_toolbar_fav.png"),
        }

        # Progress bars
        _progress_background = _tile_image(
            _IMGPATH + "Alerts/alert_progress_bar_bkgrd.png"
        )
        _progress_bar = _tile_htiles(
            [
                None,
                _IMGPATH + "Alerts/alert_progress_bar_body.png",
            ]
        )

        _song_progress_background = _tile_htiles(
            [
                _IMGPATH + "Song_Progress_Bar/SP_Bar_Touch/tch_progressbar_bkgrd_l.png",
                _IMGPATH + "Song_Progress_Bar/SP_Bar_Touch/tch_progressbar_bkgrd.png",
                _IMGPATH + "Song_Progress_Bar/SP_Bar_Touch/tch_progressbar_bkgrd_r.png",
            ]
        )
        _song_progress_bar = _tile_htiles(
            [
                None,
                None,
                _IMGPATH + "Song_Progress_Bar/SP_Bar_Touch/tch_progressbar_slider.png",
            ]
        )
        _song_progress_bar_disabled = _tile_htiles(
            [
                None,
                None,
                _IMGPATH + "Song_Progress_Bar/SP_Bar_Remote/rem_progressbar_slider.png",
            ]
        )

        _viz_progress_bar = _tile_htiles(
            [
                _IMGPATH + "UNOFFICIAL/viz_progress_fill_l.png",
                _IMGPATH + "UNOFFICIAL/viz_progress_fill.png",
                _IMGPATH + "UNOFFICIAL/viz_progress_fill_r.png",
            ]
        )
        _viz_progress_bar_pill = _tile_image(
            _IMGPATH + "UNOFFICIAL/viz_progress_slider.png"
        )

        _volume_slider_background = _tile_htiles(
            [
                _IMGPATH + "Touch_Toolbar/tch_volumebar_bkgrd_l.png",
                _IMGPATH + "Touch_Toolbar/tch_volumebar_bkgrd.png",
                _IMGPATH + "Touch_Toolbar/tch_volumebar_bkgrd_r.png",
            ]
        )
        _volume_slider_bar = _tile_htiles(
            [
                _IMGPATH + "UNOFFICIAL/tch_volumebar_fill_l.png",
                _IMGPATH + "UNOFFICIAL/tch_volumebar_fill.png",
                _IMGPATH + "UNOFFICIAL/tch_volumebar_fill_r.png",
            ]
        )
        _volume_slider_pill = _tile_image(
            _IMGPATH + "Touch_Toolbar/tch_volume_slider.png"
        )

        _popup_slider_bar = _tile_htiles(
            [
                _IMGPATH + "Touch_Toolbar/tch_volumebar_fill_l.png",
                _IMGPATH + "Touch_Toolbar/tch_volumebar_fill.png",
                _IMGPATH + "Touch_Toolbar/tch_volumebar_fill_r.png",
            ]
        )

        # ===============================================================
        # DEFAULT WIDGET STYLES
        # ===============================================================

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
                "bgImg": popup_background,
            },
        )

        s["title"] = {
            "h": TITLE_HEIGHT,
            "border": 0,
            "position": LAYOUT_NORTH,
            "bgImg": title_box,
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
                "font": _boldfont(TITLEBAR_FONT_SIZE),
                "fg": TEXT_COLOR,
            },
        }

        s["title"]["textButton"] = _uses(
            s["title"]["text"],
            {
                "bgImg": titlebar_button_box,
                "padding": [4, 15, 4, 15],
            },
        )
        s["title"]["pressed"] = {}
        s["title"]["pressed"]["textButton"] = _uses(
            s["title"]["textButton"],
            {
                "bgImg": pressed_titlebar_button_box,
            },
        )

        s["text_block_black"] = {
            "bgImg": black_background,
            "position": LAYOUT_NORTH,
            "h": 300,
            "order": ["text"],
            "text": {
                "w": WH_FILL,
                "h": 300,
                "padding": [10, 160, 10, 0],
                "align": "center",
                "font": _font(120),
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
            "bgImg": five_item_box,
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
                "arrow": add_arrow,
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

        s["item_choice"] = _uses(
            s["item"],
            {
                "order": ["icon", "text", "check"],
                "choice": {
                    "h": WH_FILL,
                    "padding": CHECKBOX_RADIO_PADDING,
                    "align": "right",
                    "font": _boldfont(TEXTMENU_FONT_SIZE),
                    "fg": TEXT_COLOR,
                    "sh": TEXT_SH_COLOR,
                },
            },
        )

        s["item_checked"] = _uses(
            s["item"],
            {
                "order": ["icon", "text", "check", "arrow"],
                "check": {
                    "align": ITEM_ICON_ALIGN,
                    "padding": CHECK_PADDING,
                    "img": _load_image("Icons/icon_check_5line.png"),
                },
            },
        )

        s["item_info"] = _uses(
            s["item"],
            {
                "order": ["text"],
                "padding": [ITEM_LEFT_PADDING, 0, 0, 0],
                "text": {
                    "align": "top-left",
                    "w": WH_FILL,
                    "h": WH_FILL,
                    "padding": [0, 6, 0, 6],
                    "font": _font(14),
                    "line": [
                        {"font": _font(14), "height": 14},
                        {"font": _boldfont(18), "height": 18},
                    ],
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
            s["item"],
            {
                "order": ["icon", "text", "check"],
            },
        )

        # Selected states
        s["selected"] = {
            "item": _uses(s["item"], {"bgImg": five_item_selection_box}),
            "item_play": _uses(s["item_play"], {"bgImg": five_item_selection_box}),
            "item_add": _uses(s["item_add"], {"bgImg": five_item_selection_box}),
            "item_checked": _uses(
                s["item_checked"], {"bgImg": five_item_selection_box}
            ),
            "item_no_arrow": _uses(
                s["item_no_arrow"], {"bgImg": five_item_selection_box}
            ),
            "item_checked_no_arrow": _uses(
                s["item_checked_no_arrow"], {"bgImg": five_item_selection_box}
            ),
            "item_choice": _uses(s["item_choice"], {"bgImg": five_item_selection_box}),
            "item_info": _uses(s["item_info"], {"bgImg": five_item_selection_box}),
        }

        # Pressed states
        s["pressed"] = {
            "item": _uses(s["item"], {"bgImg": five_item_pressed_box}),
            "item_checked": _uses(s["item_checked"], {"bgImg": five_item_pressed_box}),
            "item_play": _uses(s["item_play"], {"bgImg": five_item_pressed_box}),
            "item_add": _uses(s["item_add"], {"bgImg": five_item_pressed_box}),
            "item_no_arrow": _uses(
                s["item_no_arrow"], {"bgImg": five_item_pressed_box}
            ),
            "item_checked_no_arrow": _uses(
                s["item_checked_no_arrow"], {"bgImg": five_item_pressed_box}
            ),
            "item_choice": _uses(s["item_choice"], {"bgImg": five_item_pressed_box}),
            "item_info": _uses(s["item_info"], {"bgImg": five_item_pressed_box}),
        }

        # Locked states (with spinny)
        s["locked"] = {
            "item": _uses(s["pressed"]["item"], {"arrow": small_spinny}),
            "item_checked": _uses(
                s["pressed"]["item_checked"], {"arrow": small_spinny}
            ),
            "item_play": _uses(s["pressed"]["item_play"], {"arrow": small_spinny}),
            "item_add": _uses(s["pressed"]["item_add"], {"arrow": small_spinny}),
            "item_no_arrow": _uses(s["item_no_arrow"], {"arrow": small_spinny}),
            "item_checked_no_arrow": _uses(
                s["item_checked_no_arrow"], {"arrow": small_spinny}
            ),
            "item_info": _uses(s["item_info"], {"arrow": small_spinny}),
        }

        s["item_blank"] = {
            "padding": [],
            "text": {},
            "bgImg": help_text_background,
        }
        s["pressed"]["item_blank"] = _uses(s["item_blank"])
        s["selected"]["item_blank"] = _uses(s["item_blank"])

        s["help_text"] = {
            "w": screen_width - 30,
            "padding": [12, 8, 12, 0],
            "border": 0,
            "font": _font(HELP_FONT_SIZE),
            "lineHeight": 23,
            "fg": TEXT_COLOR,
            "sh": TEXT_SH_COLOR,
            "align": "top-left",
        }

        s["scrollbar"] = {
            "w": 46,
            "border": 0,
            "padding": [0, 0, 0, 0],
            "horizontal": 0,
            "bgImg": scroll_background,
            "img": scroll_bar,
            "layer": LAYER_CONTENT_ON_STAGE,
        }

        s["text"] = {
            "w": screen_width,
            "h": WH_FILL,
            "padding": TEXTAREA_PADDING,
            "font": _boldfont(TEXTAREA_FONT_SIZE),
            "fg": TEXT_COLOR,
            "sh": TEXT_SH_COLOR,
            "align": "left",
        }

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

        s["slider"] = {
            "border": 10,
            "position": LAYOUT_SOUTH,
            "horizontal": 1,
            "bgImg": _progress_background,
            "img": _progress_bar,
        }

        s["slider_group"] = {
            "w": WH_FILL,
            "border": [0, 5, 0, 10],
            "order": ["min", "slider", "max"],
        }

        # ===============================================================
        # SPECIAL WIDGETS
        # ===============================================================

        # text input
        s["textinput"] = {
            "h": 72,
            "padding": [24, 0, 24, 0],
            "font": _boldfont(TEXTINPUT_FONT_SIZE),
            "cursorFont": _boldfont(TEXTINPUT_SELECTED_FONT_SIZE),
            "wheelFont": _boldfont(TEXTINPUT_FONT_SIZE),
            "charHeight": TEXTINPUT_SELECTED_FONT_SIZE,
            "fg": TEXT_COLOR_BLACK,
            "charOffsetY": 32,
            "wh": [0x55, 0x55, 0x55],
            "cursorImg": textinput_cursor,
        }

        # keyboard
        s["keyboard"] = {
            "w": WH_FILL,
            "h": WH_FILL,
            "border": [8, 6, 8, 0],
            "padding": [2, 0, 2, 0],
        }

        s["keyboard_textinput"] = {
            "bgImg": textinput_background,
            "w": WH_FILL,
            "order": ["textinput", "backspace"],
            "border": 0,
            "textinput": {
                "padding": [16, 0, 0, 4],
            },
        }

        s["keyboard"]["key"] = {
            "font": _boldfont(48),
            "fg": [0xDC, 0xDC, 0xDC],
            "align": "center",
            "bgImg": key_middle,
        }

        # Key position variants
        _key_positions = {
            "key_topLeft": key_top_left,
            "key_top": key_top,
            "key_topRight": key_top_right,
            "key_left": key_left,
            "key_middle": key_middle,
            "key_right": key_right,
            "key_bottomLeft": key_bottom_left,
            "key_bottom": key_bottom,
            "key_bottomRight": key_bottom_right,
        }
        for name, bg in _key_positions.items():
            s["keyboard"][name] = _uses(s["keyboard"]["key"], {"bgImg": bg})

        # Small-font key variants
        s["keyboard"]["key_bottom_small"] = _uses(
            s["keyboard"]["key_bottom"], {"font": _boldfont(36)}
        )
        s["keyboard"]["key_bottomRight_small"] = _uses(
            s["keyboard"]["key_bottomRight"],
            {
                "font": _boldfont(36),
                "fg": [0xE7, 0xE7, 0xE7],
            },
        )
        s["keyboard"]["key_bottomLeft_small"] = _uses(
            s["keyboard"]["key_bottomLeft"], {"font": _boldfont(36)}
        )
        s["keyboard"]["key_left_small"] = _uses(
            s["keyboard"]["key_left"], {"font": _boldfont(36)}
        )

        # Spacer variants
        for name, bg in _key_positions.items():
            spacer_name = "spacer_" + name.replace("key_", "")
            s["keyboard"][spacer_name] = _uses(s["keyboard"][name])

        # Shift keys
        s["keyboard"]["shiftOff"] = _uses(
            s["keyboard"]["key_left"],
            {
                "img": _load_image("Icons/icon_shift_off.png"),
                "padding": [1, 0, 0, 0],
            },
        )
        s["keyboard"]["shiftOn"] = _uses(
            s["keyboard"]["key_left"],
            {
                "img": _load_image("Icons/icon_shift_on.png"),
                "padding": [1, 0, 0, 0],
            },
        )

        # Arrow keys
        s["keyboard"]["arrow_left_middle"] = _uses(
            s["keyboard"]["key_middle"],
            {
                "img": _load_image("Icons/icon_arrow_left.png"),
            },
        )
        s["keyboard"]["arrow_right_right"] = _uses(
            s["keyboard"]["key_right"],
            {
                "img": _load_image("Icons/icon_arrow_right.png"),
            },
        )
        s["keyboard"]["arrow_left_bottom"] = _uses(
            s["keyboard"]["key_bottom"],
            {
                "img": _load_image("Icons/icon_arrow_left.png"),
            },
        )
        s["keyboard"]["arrow_right_bottom"] = _uses(
            s["keyboard"]["key_bottom"],
            {
                "img": _load_image("Icons/icon_arrow_right.png"),
            },
        )

        # Done button
        enter_text = self.string("ENTER_SMALL") if self._strings_table else "Enter"
        s["keyboard"]["done"] = {
            "text": _uses(
                s["keyboard"]["key_bottomRight_small"],
                {
                    "text": enter_text,
                    "fg": [0x00, 0xBE, 0xBE],
                    "sh": [],
                    "h": WH_FILL,
                    "padding": [0, 0, 0, 1],
                },
            ),
            "icon": {"hidden": 1},
        }
        s["keyboard"]["doneDisabled"] = _uses(
            s["keyboard"]["done"],
            {
                "text": {"fg": [0x66, 0x66, 0x66]},
            },
        )
        s["keyboard"]["doneSpinny"] = {
            "icon": _uses(
                s["keyboard"]["key_bottomRight"],
                {
                    "bgImg": key_bottom_right,
                    "hidden": 0,
                    "img": _load_image("Alerts/wifi_connecting_sm.png"),
                    "frameRate": 8,
                    "frameWidth": 26,
                    "w": WH_FILL,
                    "h": WH_FILL,
                    "align": "center",
                },
            ),
            "text": {"hidden": 1, "w": 0},
        }

        # Space bar
        spacebar_text = (
            self.string("SPACEBAR_SMALL") if self._strings_table else "Space"
        )
        s["keyboard"]["space"] = _uses(
            s["keyboard"]["key_bottom_small"],
            {
                "bgImg": key_bottom,
                "text": spacebar_text,
            },
        )

        # Pressed keyboard states
        _pressed_key_map = {
            "shiftOff": key_left_pressed,
            "shiftOn": key_left_pressed,
            "done": key_bottom_right_pressed,
            "space": key_bottom_pressed,
            "arrow_right_bottom": key_bottom_pressed,
            "arrow_right_right": key_right_pressed,
            "arrow_left_bottom": key_bottom_pressed,
            "arrow_left_middle": key_middle_pressed,
            "key": key_middle_pressed,
            "key_topLeft": key_top_left_pressed,
            "key_top": key_top_pressed,
            "key_topRight": key_top_right_pressed,
            "key_left": key_left_pressed,
            "key_middle": key_middle_pressed,
            "key_right": key_right_pressed,
            "key_bottomLeft": key_bottom_left_pressed,
            "key_bottom": key_bottom_pressed,
            "key_bottomRight": key_bottom_right_pressed,
            "key_left_small": key_left_pressed,
            "key_bottomLeft_small": key_bottom_left_pressed,
            "key_bottom_small": key_bottom_pressed,
            "key_bottomRight_small": key_bottom_right_pressed,
        }

        s["keyboard"]["pressed"] = {}
        for name, pressed_bg in _pressed_key_map.items():
            src = s["keyboard"].get(name, s["keyboard"]["key"])
            s["keyboard"]["pressed"][name] = _uses(src, {"bgImg": pressed_bg})

        # Disabled keys keep original appearance
        s["keyboard"]["pressed"]["doneDisabled"] = _uses(s["keyboard"]["doneDisabled"])
        s["keyboard"]["pressed"]["doneSpinny"] = _uses(s["keyboard"]["doneSpinny"])

        # Pressed spacers keep original appearance
        for name in _key_positions:
            spacer_name = "spacer_" + name.replace("key_", "")
            s["keyboard"]["pressed"][spacer_name] = _uses(s["keyboard"][spacer_name])

        # ---------------------------------------------------------------
        # Time input
        # ---------------------------------------------------------------
        _time_first_column_x_12h = 218
        _time_first_column_x_24h = 280

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
            "w": 370,
            "h": 80,
            "x": 216,
            "y": 228,
        }
        s["time_input_menu_box_24h"] = _uses(
            s["time_input_menu_box_12h"],
            {
                "w": 242,
                "x": 278,
            },
        )

        _time_menu_base: Style = _uses(
            s["menu"],
            {
                "w": 100,
                "h": screen_height,
                "itemHeight": 80,
                "position": LAYOUT_WEST,
                "padding": 0,
                "border": [_time_first_column_x_12h, TITLE_HEIGHT, 0, 0],
                "item": {
                    "bgImg": False,
                    "order": ["text"],
                    "text": {
                        "align": "right",
                        "font": _boldfont(45),
                        "padding": [2, 4, 8, 0],
                        "fg": [0xB3, 0xB3, 0xB3],
                        "sh": [],
                    },
                },
                "selected": {
                    "item": {
                        "order": ["text"],
                        "bgImg": False,
                        "text": {
                            "font": _boldfont(45),
                            "fg": [0xE6, 0xE6, 0xE6],
                            "sh": [],
                            "align": "right",
                            "padding": [2, 4, 8, 0],
                        },
                    },
                },
                "pressed": {
                    "item": {
                        "order": ["text"],
                        "bgImg": False,
                        "text": {
                            "font": _boldfont(45),
                            "fg": [0xE6, 0xE6, 0xE6],
                            "sh": [],
                            "align": "right",
                            "padding": [2, 4, 8, 0],
                        },
                    },
                },
            },
        )

        s["input_time_12h"] = _uses(s["window"])
        s["input_time_12h"]["hour"] = _time_menu_base
        s["input_time_12h"]["minute"] = _uses(
            _time_menu_base,
            {
                "border": [_time_first_column_x_12h + 125, TITLE_HEIGHT, 0, 0],
            },
        )
        s["input_time_12h"]["ampm"] = _uses(
            _time_menu_base,
            {
                "border": [_time_first_column_x_12h + 125 + 120, TITLE_HEIGHT, 0, 0],
                "item": {"text": {"padding": [0, 2, 8, 0], "font": _boldfont(26)}},
                "selected": {
                    "item": {"text": {"padding": [0, 4, 8, 0], "font": _boldfont(26)}}
                },
                "pressed": {
                    "item": {"text": {"padding": [0, 4, 8, 0], "font": _boldfont(26)}}
                },
            },
        )
        s["input_time_12h"]["hourUnselected"] = s["input_time_12h"]["hour"]
        s["input_time_12h"]["minuteUnselected"] = s["input_time_12h"]["minute"]
        s["input_time_12h"]["ampmUnselected"] = s["input_time_12h"]["ampm"]

        s["input_time_24h"] = _uses(
            s["input_time_12h"],
            {
                "hour": {"border": [_time_first_column_x_24h, TITLE_HEIGHT, 0, 0]},
                "minute": {
                    "border": [_time_first_column_x_24h + 124, TITLE_HEIGHT, 0, 0]
                },
                "hourUnselected": {
                    "border": [_time_first_column_x_24h, TITLE_HEIGHT, 0, 0]
                },
                "minuteUnselected": {
                    "border": [_time_first_column_x_24h + 124, TITLE_HEIGHT, 0, 0]
                },
            },
        )

        # ===============================================================
        # WINDOW STYLES
        # ===============================================================

        s["text_list"] = _uses(s["window"])

        s["text_only"] = _uses(
            s["text_list"],
            {
                "menu": {
                    "item": {"order": ["text", "arrow"]},
                    "selected": {"item": {"order": ["text", "arrow"]}},
                    "pressed": {"item": {"order": ["text", "arrow"]}},
                    "locked": {"item": {"order": ["text", "arrow"]}},
                },
            },
        )

        s["text_list"]["title"] = _uses(
            s["title"],
            {
                "text": {
                    "line": [
                        {"font": _boldfont(TITLEBAR_FONT_SIZE), "height": 32},
                        {"font": _font(14), "fg": [0xB3, 0xB3, 0xB3]},
                    ],
                },
            },
        )
        s["text_list"]["title"]["textButton"] = _uses(
            s["text_list"]["title"]["text"],
            {
                "bgImg": titlebar_button_box,
                "padding": [4, 15, 4, 15],
            },
        )
        s["text_list"]["title"]["pressed"] = {}
        s["text_list"]["title"]["pressed"]["textButton"] = _uses(
            s["text_list"]["title"]["text"],
            {
                "bgImg": pressed_titlebar_button_box,
                "padding": [4, 15, 4, 15],
            },
        )

        s["choose_player"] = s["text_list"]

        s["multiline_text_list"] = _uses(s["text_list"])
        s["multiline_text_list"]["menu"] = _uses(
            s["menu"],
            {
                "itemHeight": THREE_ITEM_HEIGHT,
                "item": {
                    "padding": [10, 8, 0, 8],
                    "bgImg": False,
                    "icon": {"align": "top"},
                },
            },
        )
        s["multiline_text_list"]["menu"]["item_no_arrow"] = _uses(
            s["multiline_text_list"]["menu"]["item"]
        )
        s["multiline_text_list"]["menu"]["selected"] = {}
        s["multiline_text_list"]["menu"]["selected"]["item"] = _uses(
            s["multiline_text_list"]["menu"]["item"],
            {"bgImg": three_item_selection_box},
        )
        s["multiline_text_list"]["menu"]["selected"]["item_no_arrow"] = _uses(
            s["multiline_text_list"]["menu"]["selected"]["item"]
        )
        s["multiline_text_list"]["menu"]["pressed"] = {}
        s["multiline_text_list"]["menu"]["pressed"]["item"] = _uses(
            s["multiline_text_list"]["menu"]["item"],
            {"bgImg": three_item_pressed_box},
        )
        s["multiline_text_list"]["menu"]["pressed"]["item_no_arrow"] = _uses(
            s["multiline_text_list"]["menu"]["pressed"]["item"]
        )

        # waiting popup
        s["waiting_popup"] = _uses(
            s["popup"],
            {
                "text": {
                    "w": WH_FILL,
                    "h": POPUP_TEXT_SIZE_1 + 8,
                    "position": LAYOUT_NORTH,
                    "border": [0, 50, 0, 0],
                    "padding": [15, 0, 15, 0],
                    "align": "center",
                    "font": _font(POPUP_TEXT_SIZE_1),
                    "lineHeight": POPUP_TEXT_SIZE_1 + 8,
                    "fg": TEXT_COLOR,
                    "sh": TEXT_SH_COLOR,
                },
                "subtext": {
                    "w": WH_FILL,
                    "h": 47,
                    "position": LAYOUT_SOUTH,
                    "border": [0, 0, 0, 20],
                    "padding": [15, 0, 15, 0],
                    "align": "top",
                    "font": _boldfont(POPUP_TEXT_SIZE_2),
                    "fg": TEXT_COLOR,
                    "sh": TEXT_SH_COLOR,
                },
            },
        )
        s["waiting_popup"]["subtext_connected"] = _uses(
            s["waiting_popup"]["subtext"],
            {
                "fg": TEXT_COLOR_TEAL,
            },
        )

        s["black_popup"] = _uses(s["waiting_popup"])
        s["black_popup"]["title"] = _uses(
            s["title"],
            {
                "bgImg": False,
                "order": [],
            },
        )

        # input window
        s["input"] = _uses(s["window"])
        s["input"]["title"] = _uses(
            s["title"],
            {
                "bgImg": input_title_box,
            },
        )

        # power on window
        clear_mask = _fill_color(0x00000000)
        s["power_on_window"] = _uses(s["window"])
        s["power_on_window"]["maskImg"] = clear_mask
        s["power_on_window"]["title"] = _uses(
            s["title"],
            {
                "bgImg": False,
            },
        )

        # update popup
        s["update_popup"] = _uses(
            s["popup"],
            {
                "text": {
                    "w": WH_FILL,
                    "h": POPUP_TEXT_SIZE_1 + 8,
                    "position": LAYOUT_NORTH,
                    "border": [0, 34, 0, 2],
                    "padding": [10, 0, 10, 0],
                    "align": "center",
                    "font": _font(POPUP_TEXT_SIZE_1),
                    "lineHeight": POPUP_TEXT_SIZE_1 + 8,
                    "fg": TEXT_COLOR,
                    "sh": TEXT_SH_COLOR,
                },
                "subtext": {
                    "w": WH_FILL,
                    "h": 30,
                    "padding": [0, 0, 0, 28],
                    "font": _boldfont(UPDATE_SUBTEXT_SIZE),
                    "fg": TEXT_COLOR,
                    "sh": TEXT_SH_COLOR,
                    "align": "bottom",
                    "position": LAYOUT_SOUTH,
                },
                "progress": {
                    "border": [15, 7, 15, 17],
                    "position": LAYOUT_SOUTH,
                    "horizontal": 1,
                    "bgImg": _progress_background,
                    "img": _progress_bar,
                },
            },
        )

        # home menu
        home_loading_icon = _load_image("IconsResized/icon_loading" + skin_suffix)
        s["home_menu"] = _uses(
            s["text_list"],
            {
                "menu": {
                    "item": _uses(
                        s["item"],
                        {
                            "icon": {"img": home_loading_icon},
                        },
                    ),
                    "selected": {
                        "item": _uses(
                            s["selected"]["item"],
                            {
                                "icon": {"img": home_loading_icon},
                            },
                        ),
                    },
                    "locked": {
                        "item": _uses(
                            s["locked"]["item"],
                            {
                                "icon": {"img": home_loading_icon},
                            },
                        ),
                    },
                },
            },
        )

        _hm_icon_no_artwork = {
            "img": home_loading_icon,
            "h": THUMB_SIZE,
            "padding": MENU_ITEM_ICON_PADDING,
            "align": "center",
        }
        s["home_menu"]["menu"]["item"]["icon_no_artwork"] = _hm_icon_no_artwork
        s["home_menu"]["menu"]["selected"]["item"]["icon_no_artwork"] = (
            _hm_icon_no_artwork
        )
        s["home_menu"]["menu"]["locked"]["item"]["icon_no_artwork"] = (
            _hm_icon_no_artwork
        )

        # icon_list window
        s["icon_list"] = _uses(
            s["window"],
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
                                {"font": _boldfont(ALBUMMENU_FONT_SIZE), "height": 22},
                                {"font": _font(ALBUMMENU_SMALL_FONT_SIZE)},
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
                "arrow": {"img": _load_image("Icons/icon_nplay_3line_off.png")},
                "text": {"padding": 0},
                "bgImg": five_item_box,
            },
        )
        s["icon_list"]["menu"]["item_add"] = _uses(
            s["icon_list"]["menu"]["item"],
            {
                "arrow": add_arrow,
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

        # icon_list selected
        s["icon_list"]["menu"]["selected"] = {
            "item": _uses(
                s["icon_list"]["menu"]["item"], {"bgImg": five_item_selection_box}
            ),
            "albumcurrent": _uses(
                s["icon_list"]["menu"]["albumcurrent"],
                {
                    "arrow": {"img": _load_image("Icons/icon_nplay_3line_sel.png")},
                    "bgImg": five_item_selection_box,
                },
            ),
            "item_checked": _uses(
                s["icon_list"]["menu"]["item_checked"],
                {"bgImg": five_item_selection_box},
            ),
            "item_play": _uses(
                s["icon_list"]["menu"]["item_play"], {"bgImg": five_item_selection_box}
            ),
            "item_add": _uses(
                s["icon_list"]["menu"]["item_add"], {"bgImg": five_item_selection_box}
            ),
            "item_no_arrow": _uses(
                s["icon_list"]["menu"]["item_no_arrow"],
                {"bgImg": five_item_selection_box},
            ),
            "item_checked_no_arrow": _uses(
                s["icon_list"]["menu"]["item_checked_no_arrow"],
                {"bgImg": five_item_selection_box},
            ),
        }

        # icon_list pressed
        s["icon_list"]["menu"]["pressed"] = {
            "item": _uses(
                s["icon_list"]["menu"]["item"], {"bgImg": five_item_pressed_box}
            ),
            "albumcurrent": _uses(
                s["icon_list"]["menu"]["albumcurrent"],
                {"bgImg": five_item_selection_box},
            ),
            "item_checked": _uses(
                s["icon_list"]["menu"]["item_checked"], {"bgImg": five_item_pressed_box}
            ),
            "item_play": _uses(
                s["icon_list"]["menu"]["item_play"], {"bgImg": five_item_pressed_box}
            ),
            "item_add": _uses(
                s["icon_list"]["menu"]["item_add"], {"bgImg": five_item_pressed_box}
            ),
            "item_no_arrow": _uses(
                s["icon_list"]["menu"]["item_no_arrow"],
                {"bgImg": five_item_pressed_box},
            ),
            "item_checked_no_arrow": _uses(
                s["icon_list"]["menu"]["item_checked_no_arrow"],
                {"bgImg": five_item_pressed_box},
            ),
        }

        # icon_list locked
        s["icon_list"]["menu"]["locked"] = {
            "item": _uses(
                s["icon_list"]["menu"]["pressed"]["item"], {"arrow": small_spinny}
            ),
            "item_checked": _uses(
                s["icon_list"]["menu"]["pressed"]["item_checked"],
                {"arrow": small_spinny},
            ),
            "item_play": _uses(
                s["icon_list"]["menu"]["pressed"]["item_play"], {"arrow": small_spinny}
            ),
            "item_add": _uses(
                s["icon_list"]["menu"]["pressed"]["item_add"], {"arrow": small_spinny}
            ),
            "albumcurrent": _uses(
                s["icon_list"]["menu"]["pressed"]["albumcurrent"],
                {"arrow": small_spinny},
            ),
        }

        # help_list
        s["help_list"] = _uses(s["text_list"])

        # error window
        s["error"] = _uses(s["help_list"])

        # information window
        s["information"] = _uses(s["window"])
        s["information"]["text"] = {
            "font": _font(TEXTAREA_FONT_SIZE),
            "fg": TEXT_COLOR,
            "sh": TEXT_SH_COLOR,
            "padding": [18, 18, 10, 0],
            "lineHeight": 23,
        }

        # help window
        s["help_info"] = _uses(s["information"])

        # track_list
        s["track_list"] = _uses(s["text_list"])
        s["track_list"]["title"] = _uses(
            s["title"],
            {
                "order": ["lbutton", "icon", "text", "rbutton"],
                "icon": {
                    "w": THUMB_SIZE,
                    "h": WH_FILL,
                    "padding": [10, 1, 8, 1],
                },
            },
        )

        # play_list
        s["play_list"] = _uses(s["icon_list"])

        # toast popups
        s["toast_popup_textarea"] = {
            "padding": [20, 20, 20, 20],
            "align": "left",
            "w": WH_FILL,
            "h": WH_FILL,
            "font": _font(POPUP_TEXT_SIZE_1),
            "fg": TEXT_COLOR,
            "sh": TEXT_SH_COLOR,
        }

        s["toast_popup"] = {
            "x": 100,
            "y": screen_height // 4,
            "w": screen_width - 200,
            "h": screen_height // 2,
            "bgImg": popup_box,
            "group": {
                "padding": 10,
                "order": ["icon", "text"],
                "text": {
                    "padding": [10, 12, 12, 12],
                    "align": "top-left",
                    "w": WH_FILL,
                    "h": WH_FILL,
                    "font": _font(HELP_FONT_SIZE),
                    "lineHeight": HELP_FONT_SIZE + 5,
                },
                "icon": {
                    "align": "top-left",
                    "border": [12, 12, 0, 0],
                    "img": _load_image("UNOFFICIAL/menu_album_noartwork_64.png"),
                    "h": WH_FILL,
                    "w": 64,
                },
            },
        }

        s["toast_popup_text"] = _uses(
            s["toast_popup"],
            {
                "group": {
                    "order": ["text"],
                    "text": {
                        "w": WH_FILL,
                        "h": WH_FILL,
                        "align": "top-left",
                        "padding": [10, 12, 12, 12],
                        "fg": TEXT_COLOR,
                        "sh": TEXT_SH_COLOR,
                    },
                },
            },
        )

        s["toast_popup_icon"] = _uses(
            s["toast_popup"],
            {
                "w": 190,
                "h": 178,
                "x": (screen_width - 190) // 2,
                "y": (screen_height - 170) // 2,
                "position": LAYOUT_NONE,
                "group": {
                    "order": ["icon"],
                    "border": [22, 22, 0, 0],
                    "padding": 0,
                    "icon": {
                        "w": WH_FILL,
                        "h": WH_FILL,
                        "align": "center",
                    },
                },
            },
        )

        s["toast_popup_mixed"] = {
            "x": 100,
            "y": (screen_height - 250) // 2,
            "position": LAYOUT_NONE,
            "w": screen_width - 200,
            "h": 250,
            "bgImg": popup_box,
            "text": {
                "position": LAYOUT_NORTH,
                "padding": [8, 24, 8, 0],
                "align": "top",
                "w": WH_FILL,
                "h": WH_FILL,
                "font": _font(POPUP_TEXT_SIZE_1),
                "lineHeight": POPUP_TEXT_SIZE_1 + 5,
                "fg": TEXT_COLOR,
                "sh": TEXT_SH_COLOR,
            },
            "subtext": {
                "position": LAYOUT_NORTH,
                "padding": [8, 203, 8, 0],
                "align": "top",
                "w": WH_FILL,
                "h": WH_FILL,
                "font": _font(POPUP_TEXT_SIZE_2),
                "lineHeight": POPUP_TEXT_SIZE_2 + 5,
                "fg": TEXT_COLOR,
                "sh": TEXT_SH_COLOR,
            },
        }

        # Badges
        popup_thumb = self.param()["POPUP_THUMB_SIZE"]
        s["_badge"] = {
            "position": LAYOUT_NONE,
            "zOrder": 99,
            "x": (screen_width - 200) // 2 + popup_thumb // 2 - 17,
            "w": 34,
            "y": 48,
        }
        s["badge_none"] = _uses(s["_badge"], {"img": False})
        s["badge_favorite"] = _uses(
            s["_badge"], {"img": _load_image("Icons/icon_badge_fav.png")}
        )
        s["badge_add"] = _uses(
            s["_badge"], {"img": _load_image("Icons/icon_badge_add.png")}
        )

        # Context menu
        CM_MENU_ITEM_COUNT = math.floor((screen_height - 32 - 52 - 20) / CM_MENU_HEIGHT)

        s["context_menu"] = {
            "x": 8,
            "y": 16,
            "w": screen_width - 16,
            "h": screen_height - 32,
            "bgImg": context_menu_box,
            "layer": LAYER_TITLE,
            "multiline_text": {
                "w": WH_FILL,
                "h": 172,
                "padding": [18, 2, 14, 18],
                "border": [0, 0, 6, 15],
                "lineHeight": 22,
                "font": _font(18),
                "fg": [0xE6, 0xE6, 0xE6],
                "sh": [],
                "align": "top-left",
                "scrollbar": {
                    "h": 164,
                    "border": [0, 2, 2, 10],
                },
            },
            "title": {
                "layer": LAYER_TITLE,
                "h": 52,
                "padding": [10, 10, 10, 5],
                "bgImg": False,
                "button_cancel": {
                    "layer": LAYER_TITLE,
                    "w": 43,
                    "align": "right",
                },
                "pressed": {
                    "button_cancel": {
                        "bgImg": pressed_titlebar_button_box,
                        "layer": LAYER_TITLE,
                        "w": 43,
                    },
                },
                "text": {
                    "layer": LAYER_TITLE,
                    "w": WH_FILL,
                    "padding": [0, 0, 20, 0],
                    "align": "center",
                    "font": _boldfont(TITLE_FONT_SIZE),
                    "fg": TEXT_COLOR,
                },
            },
            "menu": {
                "h": CM_MENU_HEIGHT * CM_MENU_ITEM_COUNT,
                "border": [7, 0, 7, 0],
                "padding": [0, 0, 0, 100],
                "scrollbar": {"h": CM_MENU_HEIGHT * CM_MENU_ITEM_COUNT},
                "item": {
                    "h": CM_MENU_HEIGHT,
                    "order": ["text", "arrow"],
                    "padding": [ITEM_LEFT_PADDING, 0, 12, 0],
                    "text": {
                        "padding": [0, 4, 0, 0],
                        "w": WH_FILL,
                        "h": WH_FILL,
                        "align": "left",
                        "font": _font(ALBUMMENU_SMALL_FONT_SIZE),
                        "line": [
                            {"font": _boldfont(ALBUMMENU_FONT_SIZE), "height": 22},
                            {"font": _font(ALBUMMENU_SMALL_FONT_SIZE)},
                        ],
                        "fg": TEXT_COLOR,
                        "sh": TEXT_SH_COLOR,
                    },
                    "arrow": _uses(s["item"]["arrow"]),
                },
                "selected": {
                    "item": {
                        "order": ["text", "arrow"],
                        "bgImg": five_item_selection_box,
                        "padding": [ITEM_LEFT_PADDING, 0, 12, 0],
                        "text": {
                            "padding": [0, 4, 0, 0],
                            "w": WH_FILL,
                            "h": WH_FILL,
                            "align": "left",
                            "font": _font(ALBUMMENU_SMALL_FONT_SIZE),
                            "line": [
                                {"font": _boldfont(ALBUMMENU_FONT_SIZE), "height": 22},
                                {"font": _font(ALBUMMENU_SMALL_FONT_SIZE)},
                            ],
                            "fg": TEXT_COLOR,
                            "sh": TEXT_SH_COLOR,
                        },
                        "arrow": _uses(s["item"]["arrow"]),
                    },
                },
            },
        }

        # Context menu item variants
        for variant in ["item_play", "item_insert", "item_add", "item_playall"]:
            arrow_img = play_arrow["img"] if "play" in variant else add_arrow["img"]
            s["context_menu"]["menu"][variant] = _uses(
                s["context_menu"]["menu"]["item"],
                {
                    "arrow": {"img": arrow_img},
                },
            )
            s["context_menu"]["menu"]["selected"][variant] = _uses(
                s["context_menu"]["menu"]["selected"]["item"],
                {"arrow": {"img": arrow_img}},
            )

        s["context_menu"]["menu"]["item_fav"] = _uses(
            s["context_menu"]["menu"]["item"],
            {
                "arrow": {"img": fav_item["img"]},
            },
        )
        s["context_menu"]["menu"]["selected"]["item_fav"] = _uses(
            s["context_menu"]["menu"]["selected"]["item"],
            {"arrow": {"img": fav_item["img"]}},
        )

        s["context_menu"]["menu"]["item_no_arrow"] = _uses(
            s["context_menu"]["menu"]["item"],
            {
                "order": ["text"],
            },
        )
        s["context_menu"]["menu"]["selected"]["item_no_arrow"] = _uses(
            s["context_menu"]["menu"]["selected"]["item"],
            {"order": ["text"]},
        )

        s["context_menu"]["menu"]["pressed"] = _uses(
            s["context_menu"]["menu"]["selected"],
            {
                "item": {"bgImg": context_menu_pressed_box},
            },
        )
        s["context_menu"]["menu"]["locked"] = _uses(
            s["context_menu"]["menu"]["pressed"],
            {
                "item": {"arrow": small_spinny},
            },
        )

        # alarm popup
        s["alarm_header"] = {
            "w": screen_width,
            "order": ["time"],
        }
        s["alarm_time"] = {
            "w": screen_width - 20,
            "fg": TEXT_COLOR,
            "sh": TEXT_SH_COLOR,
            "align": "center",
            "font": _boldfont(62),
        }
        s["preview_text"] = _uses(
            s["alarm_time"],
            {
                "font": _boldfont(TITLE_FONT_SIZE),
            },
        )

        s["alarm_popup"] = {
            "x": 10,
            "y": 10,
            "w": screen_width - 20,
            "h": screen_height - 17,
            "border": 0,
            "padding": 0,
            "bgImg": context_menu_box,
            "layer": LAYER_TITLE,
            "title": {"hidden": 1},
            "menu": {
                "h": CM_MENU_HEIGHT * 5,
                "w": screen_width - 34,
                "x": 7,
                "y": 65,
                "border": 0,
                "itemHeight": CM_MENU_HEIGHT,
                "position": LAYOUT_NORTH,
                "scrollbar": {"h": CM_MENU_HEIGHT * 5 - 8, "border": [0, 4, 0, 0]},
                "item": {
                    "h": CM_MENU_HEIGHT,
                    "order": ["text", "arrow"],
                    "text": {
                        "w": WH_FILL,
                        "h": WH_FILL,
                        "align": "left",
                        "font": _boldfont(TEXTMENU_FONT_SIZE),
                        "fg": TEXT_COLOR,
                        "sh": TEXT_SH_COLOR,
                    },
                    "arrow": _uses(s["item"]["arrow"]),
                },
                "selected": {
                    "item": {
                        "bgImg": five_item_selection_box,
                        "order": ["text", "arrow"],
                        "text": {
                            "w": WH_FILL,
                            "h": WH_FILL,
                            "align": "left",
                            "font": _boldfont(TEXTMENU_FONT_SIZE),
                            "fg": TEXT_COLOR,
                            "sh": TEXT_SH_COLOR,
                        },
                        "arrow": _uses(s["item"]["arrow"]),
                    },
                },
            },
        }

        # slider popup
        s["slider_popup"] = {
            "x": 50,
            "y": screen_height // 2 - 100,
            "w": screen_width - 100,
            "h": 200,
            "bgImg": popup_box,
            "heading": {
                "w": WH_FILL,
                "border": 10,
                "fg": TEXT_COLOR,
                "font": _boldfont(32),
                "padding": [4, 16, 4, 0],
                "align": "center",
                "bgImg": False,
            },
            "slider_group": {
                "w": WH_FILL,
                "align": "center",
                "padding": [10, 0, 10, 0],
                "order": ["slider"],
            },
        }

        s["scanner_popup"] = _uses(
            s["slider_popup"],
            {
                "h": 110,
                "y": screen_height // 2 - 55,
            },
        )

        s["image_popup"] = _uses(
            s["popup"],
            {
                "image": {
                    "w": screen_width,
                    "position": LAYOUT_CENTER,
                    "align": "center",
                    "h": screen_height,
                    "border": 0,
                },
            },
        )

        # ===============================================================
        # SLIDERS
        # ===============================================================

        s["volume_slider"] = {
            "w": WH_FILL,
            "border": [0, 0, 0, 10],
            "bgImg": _volume_slider_background,
            "img": _popup_slider_bar,
        }
        s["scanner_slider"] = _uses(
            s["volume_slider"],
            {
                "img": _volume_slider_bar,
            },
        )

        # ===============================================================
        # BUTTONS
        # ===============================================================

        _button: Style = {
            "bgImg": titlebar_button_box,
            "w": TITLE_BUTTON_WIDTH,
            "h": WH_FILL,
            "border": [8, 0, 8, 0],
            "icon": {
                "w": WH_FILL,
                "h": WH_FILL,
                "hidden": 1,
                "align": "center",
                "img": False,
            },
            "text": {
                "w": WH_FILL,
                "h": WH_FILL,
                "hidden": 1,
                "border": 0,
                "padding": 0,
                "align": "center",
                "font": _font(16),
                "fg": [0xDC, 0xDC, 0xDC],
            },
        }
        _pressed_button = _uses(_button, {"bgImg": pressed_titlebar_button_box})

        # Icon button factory
        def _title_button_icon(name: str, icon: Any) -> None:
            s[name] = _uses(_button)
            s[name]["layer"] = LAYER_TITLE
            s["pressed"][name] = _uses(_pressed_button)

            attr = {
                "hidden": 0,
                "img": icon,
                "layer": LAYER_TITLE,
            }
            s[name]["icon"] = _uses(_button["icon"], attr)
            s[name]["w"] = 65
            s["pressed"][name]["icon"] = _uses(_pressed_button["icon"], attr)
            s["pressed"][name]["w"] = 65

        # Text button factory
        def _title_button_text(name: str, text_str: Any) -> None:
            s[name] = _uses(_button)
            s["pressed"][name] = _uses(_pressed_button)

            attr = {
                "hidden": 0,
                "text": text_str,
            }
            s[name]["text"] = _uses(_button["text"], attr)
            s[name]["w"] = 65
            s["pressed"][name]["text"] = _uses(_pressed_button["text"], attr)
            s["pressed"][name]["w"] = 65

        # Invisible button
        s["button_none"] = _uses(
            _button,
            {
                "bgImg": False,
                "w": TITLE_BUTTON_WIDTH - 12,
            },
        )

        _title_button_icon("button_back", back_button)
        _title_button_icon("button_cancel", cancel_button)
        _title_button_icon("button_go_home", home_button)
        _title_button_icon("button_playlist", playlist_button)
        _title_button_icon("button_more", more_button)
        _title_button_icon("button_go_playlist", playlist_button)
        _title_button_icon("button_go_now_playing", now_playing_button)
        _title_button_icon("button_power", power_button)
        _title_button_icon("button_nothing", None)
        _title_button_icon("button_help", help_button)

        more_help_text = (
            self.string("MORE_HELP") if self._strings_table else "More Help"
        )
        enter_text_btn = self.string("ENTER") if self._strings_table else "Enter"
        _title_button_text("button_more_help", more_help_text)
        _title_button_text("button_finish_operation", enter_text_btn)

        s["button_back"]["padding"] = [2, 0, 0, 2]
        s["button_playlist"]["padding"] = [2, 0, 0, 2]

        s["button_volume_min"] = {
            "img": _load_image("Icons/icon_toolbar_vol_down.png"),
            "border": [5, 0, 5, 0],
        }
        s["button_volume_max"] = {
            "img": _load_image("Icons/icon_toolbar_vol_up.png"),
            "border": [5, 0, 5, 0],
        }

        s["button_keyboard_back"] = {
            "align": "left",
            "w": 96,
            "h": 66,
            "padding": [14, 0, 0, 0],
            "border": [0, 2, 9, 5],
            "img": _load_image("Icons/icon_delete_tch_text_entry.png"),
            "bgImg": delete_key_background,
        }
        s["pressed"]["button_keyboard_back"] = _uses(
            s["button_keyboard_back"],
            {
                "bgImg": delete_key_pressed_background,
            },
        )

        # ===============================================================
        # ICONS
        # ===============================================================

        _buttonicon: Style = {
            "h": THUMB_SIZE,
            "padding": MENU_ITEM_ICON_PADDING,
            "align": "center",
            "img": False,
        }

        s["region_US"] = _uses(
            _buttonicon,
            {"img": _load_image("IconsResized/icon_region_americas" + skin_suffix)},
        )
        s["region_XX"] = _uses(
            _buttonicon,
            {"img": _load_image("IconsResized/icon_region_other" + skin_suffix)},
        )
        s["icon_help"] = _uses(
            _buttonicon, {"img": _load_image("IconsResized/icon_help" + skin_suffix)}
        )
        s["wlan"] = _uses(
            _buttonicon,
            {"img": _load_image("IconsResized/icon_wireless" + skin_suffix)},
        )
        s["wired"] = _uses(
            _buttonicon,
            {"img": _load_image("IconsResized/icon_ethernet" + skin_suffix)},
        )

        _icon_base: Style = {
            "w": WH_FILL,
            "align": "center",
            "position": LAYOUT_CENTER,
            "padding": [0, 0, 0, 10],
        }

        _popupicon: Style = {
            "padding": 0,
            "border": [22, 18, 0, 0],
            "h": WH_FILL,
            "w": 166,
        }

        s["icon_no_artwork"] = {
            "img": _load_image("IconsResized/icon_album_noart" + skin_suffix),
            "h": THUMB_SIZE,
            "padding": MENU_ITEM_ICON_PADDING,
            "align": "center",
        }
        s["icon_no_artwork_playlist"] = _uses(s["icon_no_artwork"])

        s["icon_connecting"] = _uses(
            _icon_base,
            {
                "img": _load_image("Alerts/wifi_connecting.png"),
                "frameRate": 8,
                "frameWidth": 120,
                "padding": [0, 90, 0, 10],
            },
        )
        s["icon_connected"] = _uses(
            _icon_base,
            {
                "img": _load_image("Alerts/connecting_success_icon.png"),
                "padding": [0, 2, 0, 10],
            },
        )
        s["icon_photo_loading"] = _uses(
            _icon_base,
            {
                "img": _load_image("Icons/image_viewer_loading.png"),
            },
        )
        s["icon_software_update"] = _uses(
            _icon_base,
            {
                "img": _load_image("IconsResized/icon_firmware_update" + skin_suffix),
            },
        )
        s["icon_restart"] = _uses(
            _icon_base,
            {
                "img": _load_image("IconsResized/icon_restart" + skin_suffix),
            },
        )

        # Popup icons
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
            {
                "img": _load_image("Icons/icon_popup_box_volume_mute.png"),
            },
        )

        s["icon_popup_shuffle0"] = _uses(
            _popupicon, {"img": _load_image("Icons/icon_popup_box_shuffle_off.png")}
        )
        s["icon_popup_shuffle1"] = _uses(
            _popupicon, {"img": _load_image("Icons/icon_popup_box_shuffle.png")}
        )
        s["icon_popup_shuffle2"] = _uses(
            _popupicon, {"img": _load_image("Icons/icon_popup_box_shuffle_album.png")}
        )
        s["icon_popup_repeat0"] = _uses(
            _popupicon, {"img": _load_image("Icons/icon_popup_box_repeat_off.png")}
        )
        s["icon_popup_repeat1"] = _uses(
            _popupicon, {"img": _load_image("Icons/icon_popup_box_repeat_song.png")}
        )
        s["icon_popup_repeat2"] = _uses(
            _popupicon, {"img": _load_image("Icons/icon_popup_box_repeat.png")}
        )

        _sleep_icon_base = {"h": WH_FILL, "w": WH_FILL, "padding": [24, 24, 0, 0]}
        s["icon_popup_sleep_15"] = _uses(
            _sleep_icon_base, {"img": _load_image("Icons/icon_popup_box_sleep_15.png")}
        )
        s["icon_popup_sleep_30"] = _uses(
            _sleep_icon_base, {"img": _load_image("Icons/icon_popup_box_sleep_30.png")}
        )
        s["icon_popup_sleep_45"] = _uses(
            _sleep_icon_base, {"img": _load_image("Icons/icon_popup_box_sleep_45.png")}
        )
        s["icon_popup_sleep_60"] = _uses(
            _sleep_icon_base, {"img": _load_image("Icons/icon_popup_box_sleep_60.png")}
        )
        s["icon_popup_sleep_90"] = _uses(
            _sleep_icon_base, {"img": _load_image("Icons/icon_popup_box_sleep_90.png")}
        )
        s["icon_popup_sleep_cancel"] = _uses(
            _sleep_icon_base,
            {
                "img": _load_image("Icons/icon_popup_box_sleep_off.png"),
                "padding": [24, 34, 0, 0],
            },
        )

        s["icon_power"] = _uses(
            _icon_base, {"img": _load_image("IconsResized/icon_restart" + skin_suffix)}
        )
        s["icon_locked"] = _uses(_icon_base, {})
        s["icon_alarm"] = {"img": _load_image("Icons/icon_alarm.png")}
        s["icon_art"] = _uses(_icon_base, {"padding": 0, "img": False})

        # Player model icons
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
        for style_name, icon_base_name in _player_icons.items():
            s[style_name] = _uses(
                _buttonicon,
                {
                    "img": _load_image("IconsResized/" + icon_base_name + skin_suffix),
                },
            )

        # Home menu icons
        _hm_icons = {
            "hm_appletImageViewer": "icon_image_viewer",
            "hm_eject": "icon_eject",
            "hm_sdcard": "icon_device_SDcard",
            "hm_usbdrive": "icon_device_USB",
            "hm_appletNowPlaying": "icon_nowplaying",
            "hm_settings": "icon_settings",
            "hm_advancedSettings": "icon_settings_adv",
            "hm_settings_pcp": "icon_settings_pcp",
            "hm_radio": "icon_tunein",
            "hm_radios": "icon_tunein",
            "hm_myApps": "icon_my_apps",
            "hm_myMusic": "icon_mymusic",
            "hm_otherLibrary": "icon_ml_other_library",
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
        for style_name, icon_base_name in _hm_icons.items():
            s[style_name] = _uses(
                _buttonicon,
                {
                    "img": _load_image("IconsResized/" + icon_base_name + skin_suffix),
                },
            )

        # Aliases
        s["hm__myMusic"] = _uses(s["hm_myMusic"])
        s["hm_myMusicSelector"] = _uses(s["hm_myMusic"])
        s["hm_myMusicSearchArtists"] = _uses(s["hm_myMusicSearch"])
        s["hm_myMusicSearchAlbums"] = _uses(s["hm_myMusicSearch"])
        s["hm_myMusicSearchSongs"] = _uses(s["hm_myMusicSearch"])
        s["hm_myMusicSearchPlaylists"] = _uses(s["hm_myMusicSearch"])
        s["hm_myMusicSearchRecent"] = _uses(s["hm_myMusicSearch"])
        s["hm_homeSearchRecent"] = _uses(s["hm_myMusicSearch"])
        s["hm_globalSearch"] = _uses(s["hm_myMusicSearch"])

        # Wireless indicators
        _indicator: Style = {"align": "center"}
        for level in range(1, 5):
            s[f"wirelessLevel{level}"] = _uses(
                _indicator,
                {
                    "img": _load_image(f"Icons/icon_wireless_{level}.png"),
                },
            )

        # ===============================================================
        # ICONBAR (hidden in JogglerSkin — touch toolbar replaces it)
        # ===============================================================

        s["iconbar_group"] = {"hidden": 1}
        s["button_time"] = {"hidden": 1}

        # ===============================================================
        # NOW PLAYING
        # ===============================================================

        NP_ARTISTALBUM_FONT_SIZE = 28
        NP_TRACK_FONT_SIZE = 36

        control_height = 72
        control_width = 76
        volume_bar_width = 240

        _transport_control_button: Style = {
            "w": control_width,
            "h": control_height,
            "align": "center",
            "padding": 0,
        }
        _transport_control_border = _uses(
            _transport_control_button,
            {
                "w": 2,
                "padding": 0,
                "img": touch_toolbar_key_divider,
            },
        )

        s["toolbar_spacer"] = _uses(_transport_control_button, {"w": WH_FILL})

        _tracklayout: Style = {
            "border": [4, 0, 4, 0],
            "position": LAYOUT_NONE,
            "w": WH_FILL,
            "align": "left",
            "lineHeight": NP_TRACK_FONT_SIZE,
            "fg": TEXT_COLOR,
            "x": screen_height - 160 + 5,
        }

        max_artwork = screen_height - 180

        # --- nowplaying (standard: art and text) ---
        s["nowplaying"] = _uses(
            s["window"],
            {
                "title": _uses(
                    s["title"],
                    {
                        "zOrder": 1,
                        "text": {
                            "font": _boldfont(TITLEBAR_FONT_SIZE),
                            "bgImg": titlebar_button_box,
                        },
                        "rbutton": {
                            "font": _font(14),
                            "fg": TEXT_COLOR,
                            "bgImg": titlebar_button_box,
                            "w": TITLE_BUTTON_WIDTH,
                            "padding": [8, 0, 8, 0],
                            "align": "center",
                        },
                    },
                ),
                "nptitle": {
                    "order": ["nptrack"],
                    "position": _tracklayout["position"],
                    "border": _tracklayout["border"],
                    "x": _tracklayout["x"],
                    "y": TITLE_HEIGHT + 65,
                    "h": NP_TRACK_FONT_SIZE,
                    "nptrack": {
                        "w": screen_width - _tracklayout["x"] - 10,
                        "h": WH_FILL,
                        "align": _tracklayout["align"],
                        "lineHeight": _tracklayout["lineHeight"],
                        "fg": _tracklayout["fg"],
                        "font": _boldfont(NP_TRACK_FONT_SIZE),
                        "sh": TEXT_SH_COLOR,
                    },
                },
                "npartistgroup": {
                    "order": ["npartist"],
                    "position": _tracklayout["position"],
                    "border": _tracklayout["border"],
                    "x": _tracklayout["x"],
                    "y": TITLE_HEIGHT + 32 + 32 + 70,
                    "h": 32,
                    "npartist": {
                        "padding": [0, 6, 0, 0],
                        "w": screen_width - _tracklayout["x"] - 10,
                        "align": _tracklayout["align"],
                        "lineHeight": _tracklayout["lineHeight"],
                        "fg": _tracklayout["fg"],
                        "font": _font(NP_ARTISTALBUM_FONT_SIZE),
                        "sh": TEXT_SH_COLOR,
                    },
                },
                "npalbumgroup": {
                    "order": ["npalbum"],
                    "position": _tracklayout["position"],
                    "border": _tracklayout["border"],
                    "x": _tracklayout["x"],
                    "y": TITLE_HEIGHT + 32 + 32 + 32 + 70 + 10,
                    "h": 32,
                    "npalbum": {
                        "w": screen_width - _tracklayout["x"] - 10,
                        "padding": [0, 6, 0, 0],
                        "align": _tracklayout["align"],
                        "lineHeight": _tracklayout["lineHeight"],
                        "fg": _tracklayout["fg"],
                        "font": _font(NP_ARTISTALBUM_FONT_SIZE),
                        "sh": TEXT_SH_COLOR,
                    },
                },
                "npartistalbum": {"hidden": 1},
                "npartwork": {
                    "w": max_artwork,
                    "position": LAYOUT_NONE,
                    "x": 10,
                    "y": TITLE_HEIGHT + 18,
                    "align": "center",
                    "h": max_artwork,
                    "artwork": {
                        "w": max_artwork,
                        "align": "center",
                        "padding": 0,
                        "img": False,
                    },
                },
                "npvisu": {"hidden": 1},
                "npcontrols": {
                    "order": [
                        "rew",
                        "div1",
                        "play",
                        "div2",
                        "fwd",
                        "div3",
                        "repeatMode",
                        "div4",
                        "shuffleMode",
                        "div5",
                        "volDown",
                        "div6",
                        "volSlider",
                        "div7",
                        "volUp",
                    ],
                    "position": LAYOUT_SOUTH,
                    "h": control_height,
                    "w": WH_FILL,
                    "bgImg": touch_toolbar_background,
                    "div1": _uses(_transport_control_border),
                    "div2": _uses(_transport_control_border),
                    "div3": _uses(_transport_control_border),
                    "div4": _uses(_transport_control_border),
                    "div5": _uses(_transport_control_border),
                    "div6": _uses(_transport_control_border),
                    "div7": _uses(_transport_control_border),
                    "rew": _uses(
                        _transport_control_button,
                        {"img": _load_image("Icons/icon_toolbar_rew.png")},
                    ),
                    "play": _uses(
                        _transport_control_button,
                        {"img": _load_image("Icons/icon_toolbar_play.png")},
                    ),
                    "pause": _uses(
                        _transport_control_button,
                        {"img": _load_image("Icons/icon_toolbar_pause.png")},
                    ),
                    "fwd": _uses(
                        _transport_control_button,
                        {"img": _load_image("Icons/icon_toolbar_ffwd.png")},
                    ),
                    "shuffleMode": _uses(
                        _transport_control_button,
                        {"img": _load_image("Icons/icon_toolbar_shuffle_off.png")},
                    ),
                    "shuffleOff": _uses(
                        _transport_control_button,
                        {"img": _load_image("Icons/icon_toolbar_shuffle_off.png")},
                    ),
                    "shuffleSong": _uses(
                        _transport_control_button,
                        {"img": _load_image("Icons/icon_toolbar_shuffle_on.png")},
                    ),
                    "shuffleAlbum": _uses(
                        _transport_control_button,
                        {"img": _load_image("Icons/icon_toolbar_shuffle_album_on.png")},
                    ),
                    "repeatMode": _uses(
                        _transport_control_button,
                        {"img": _load_image("Icons/icon_toolbar_repeat_off.png")},
                    ),
                    "repeatOff": _uses(
                        _transport_control_button,
                        {"img": _load_image("Icons/icon_toolbar_repeat_off.png")},
                    ),
                    "repeatPlaylist": _uses(
                        _transport_control_button,
                        {"img": _load_image("Icons/icon_toolbar_repeat_on.png")},
                    ),
                    "repeatSong": _uses(
                        _transport_control_button,
                        {"img": _load_image("Icons/icon_toolbar_repeat_song_on.png")},
                    ),
                    "volDown": _uses(
                        _transport_control_button,
                        {"img": _load_image("Icons/icon_toolbar_vol_down.png")},
                    ),
                    "volUp": _uses(
                        _transport_control_button,
                        {"img": _load_image("Icons/icon_toolbar_vol_up.png")},
                    ),
                    "thumbsUp": _uses(
                        _transport_control_button,
                        {"img": _load_image("Icons/icon_toolbar_thumbup.png")},
                    ),
                    "thumbsDown": _uses(
                        _transport_control_button,
                        {"img": _load_image("Icons/icon_toolbar_thumbdown.png")},
                    ),
                    "thumbsUpDisabled": _uses(
                        _transport_control_button,
                        {"img": _load_image("Icons/icon_toolbar_thumbup_dis.png")},
                    ),
                    "thumbsDownDisabled": _uses(
                        _transport_control_button,
                        {"img": _load_image("Icons/icon_toolbar_thumbdown_dis.png")},
                    ),
                    "love": _uses(
                        _transport_control_button,
                        {"img": _load_image("Icons/icon_toolbar_love_on.png")},
                    ),
                    "hate": _uses(
                        _transport_control_button,
                        {"img": _load_image("Icons/icon_toolbar_love_off.png")},
                    ),
                    "fwdDisabled": _uses(
                        _transport_control_button,
                        {"img": _load_image("Icons/icon_toolbar_ffwd_dis.png")},
                    ),
                    "rewDisabled": _uses(
                        _transport_control_button,
                        {"img": _load_image("Icons/icon_toolbar_rew_dis.png")},
                    ),
                    "shuffleDisabled": _uses(
                        _transport_control_button,
                        {"img": _load_image("Icons/icon_toolbar_shuffle_dis.png")},
                    ),
                    "repeatDisabled": _uses(
                        _transport_control_button,
                        {"img": _load_image("Icons/icon_toolbar_repeat_dis.png")},
                    ),
                },
                "npprogress": {
                    "position": LAYOUT_NONE,
                    "x": _tracklayout["x"] + 2,
                    "y": screen_height - 160,
                    "padding": [0, 11, 0, 0],
                    "order": ["elapsed", "slider", "remain"],
                    "elapsed": {
                        "w": 60,
                        "align": "left",
                        "padding": [0, 0, 4, 20],
                        "font": _boldfont(18),
                        "fg": [0xE7, 0xE7, 0xE7],
                        "sh": [0x37, 0x37, 0x37],
                    },
                    "remain": {
                        "w": 60,
                        "align": "right",
                        "padding": [4, 0, 0, 20],
                        "font": _boldfont(18),
                        "fg": [0xE7, 0xE7, 0xE7],
                        "sh": [0x37, 0x37, 0x37],
                    },
                    "elapsedSmall": {
                        "w": 60,
                        "align": "left",
                        "padding": [0, 0, 4, 20],
                        "font": _boldfont(14),
                        "fg": [0xE7, 0xE7, 0xE7],
                        "sh": [0x37, 0x37, 0x37],
                    },
                    "remainSmall": {
                        "w": 60,
                        "align": "right",
                        "padding": [4, 0, 0, 20],
                        "font": _boldfont(14),
                        "fg": [0xE7, 0xE7, 0xE7],
                        "sh": [0x37, 0x37, 0x37],
                    },
                    "npprogressB": {
                        "w": screen_width - _tracklayout["x"] - 2 * 80 - 25,
                        "h": 50,
                        "padding": [0, 0, 0, 0],
                        "position": LAYOUT_SOUTH,
                        "horizontal": 1,
                        "bgImg": _song_progress_background,
                        "img": _song_progress_bar,
                    },
                },
                "npprogressNB": {
                    "order": ["elapsed"],
                    "position": LAYOUT_NONE,
                    "x": _tracklayout["x"] + 2,
                    "y": TITLE_HEIGHT + 29 + 26 + 32 + 32 + 23 + 84 + 40,
                    "elapsed": {
                        "w": WH_FILL,
                        "align": "left",
                        "font": _boldfont(18),
                        "fg": [0xE7, 0xE7, 0xE7],
                        "sh": [0x37, 0x37, 0x37],
                    },
                },
            },
        )

        s["nowplaying"]["npprogressNB"]["elapsedSmall"] = s["nowplaying"][
            "npprogressNB"
        ]["elapsed"]

        # Disabled progress bar
        s["nowplaying"]["npprogress"]["npprogressB_disabled"] = _uses(
            s["nowplaying"]["npprogress"]["npprogressB"],
            {"img": _song_progress_bar_disabled},
        )

        # Volume bar for NP
        s["npvolumeB"] = {
            "w": volume_bar_width,
            "border": [5, 20, 5, 0],
            "padding": [6, 0, 6, 0],
            "position": LAYOUT_SOUTH,
            "horizontal": 1,
            "bgImg": _volume_slider_background,
            "img": _volume_slider_bar,
            "pillImg": _volume_slider_pill,
        }
        s["npvolumeB_disabled"] = _uses(s["npvolumeB"], {"pillImg": False})

        # Pressed NP title/controls
        s["nowplaying"]["title"]["pressed"] = _uses(
            s["nowplaying"]["title"],
            {
                "text": {
                    "fg": [0xB3, 0xB3, 0xB3],
                    "sh": [],
                    "bgImg": pressed_titlebar_button_box,
                },
                "lbutton": {"bgImg": pressed_titlebar_button_box},
                "rbutton": {"bgImg": pressed_titlebar_button_box},
            },
        )

        s["nowplaying"]["pressed"] = s["nowplaying"]
        s["nowplaying"]["nptitle"]["pressed"] = _uses(s["nowplaying"]["nptitle"])
        s["nowplaying"]["npalbumgroup"]["pressed"] = _uses(
            s["nowplaying"]["npalbumgroup"]
        )
        s["nowplaying"]["npartistgroup"]["pressed"] = _uses(
            s["nowplaying"]["npartistgroup"]
        )
        s["nowplaying"]["npartwork"]["pressed"] = s["nowplaying"]["npartwork"]

        # Pressed transport controls
        np_controls = s["nowplaying"]["npcontrols"]
        _pressable_controls = [
            "rew",
            "play",
            "pause",
            "fwd",
            "repeatPlaylist",
            "repeatSong",
            "repeatOff",
            "repeatMode",
            "shuffleAlbum",
            "shuffleSong",
            "shuffleMode",
            "shuffleOff",
            "volDown",
            "volUp",
            "thumbsUp",
            "thumbsDown",
            "love",
            "hate",
        ]
        np_controls["pressed"] = {}
        for ctrl in _pressable_controls:
            if ctrl in np_controls:
                np_controls["pressed"][ctrl] = _uses(
                    np_controls[ctrl], {"bgImg": key_middle_pressed}
                )
        # Disabled controls keep their appearance
        for ctrl in [
            "thumbsUpDisabled",
            "thumbsDownDisabled",
            "fwdDisabled",
            "rewDisabled",
            "shuffleDisabled",
            "repeatDisabled",
        ]:
            if ctrl in np_controls:
                np_controls["pressed"][ctrl] = _uses(np_controls[ctrl])

        # --- Build button order from settings ---
        settings = self._get_np_button_settings()
        button_order: List[str] = []
        small_tb_buttons = False
        i = 1
        for v in TB_BUTTONS:
            if settings.get(v, False):
                button_order.append(v)
                i += 1
                if (screen_width <= 800 and i > 5) or (i > 2 and v == "volSlider"):
                    small_tb_buttons = True
                    if screen_width <= 800:
                        break
                button_order.append("div" + str(i))

        npX = screen_height + 15

        # --- nowplaying_large_art ---
        s["nowplaying_large_art"] = _uses(
            s["nowplaying"],
            {
                "bgImg": black_background,
                "title": {
                    "bgImg": False,
                    "text": {
                        "border": [screen_height - 72, 0, 0, 0],
                        "padding": [10, 12, 10, 15],
                        "font": _boldfont(24),
                    },
                    "button_back": {"bgImg": False},
                },
                "nptitle": {
                    "x": npX,
                    "nptrack": {
                        "w": screen_width - npX - 10,
                        "font": _boldfont(int(NP_ARTISTALBUM_FONT_SIZE * 0.9)),
                    },
                },
                "npartistgroup": {
                    "x": npX,
                    "npartist": {
                        "font": _font(int(NP_ARTISTALBUM_FONT_SIZE * 0.9)),
                        "w": screen_width - npX - 10,
                    },
                },
                "npalbumgroup": {
                    "x": npX,
                    "npalbum": {
                        "font": _font(int(NP_ARTISTALBUM_FONT_SIZE * 0.9)),
                        "w": screen_width - npX - 10,
                    },
                },
                "npcontrols": {
                    "order": button_order,
                    "x": screen_height,
                },
                "npprogress": {
                    "x": npX,
                    "elapsed": {"w": 60},
                    "remain": {"w": 60},
                    "npprogressB": {"w": screen_width - npX - 2 * 60 - 15},
                },
                "npprogressNB": {"x": npX},
                "npartwork": {
                    "w": screen_height,
                    "x": 0,
                    "y": 0,
                    "align": "center",
                    "h": WH_FILL,
                    "artwork": {
                        "w": WH_FILL,
                        "h": WH_FILL,
                        "align": "left",
                        "padding": 0,
                        "img": False,
                    },
                },
                "npvisu": {"hidden": 1},
            },
        )

        s["nowplaying_large_art"]["pressed"] = s["nowplaying_large_art"]

        # Handle small toolbar buttons for large art
        if small_tb_buttons:
            small_control_width = control_width - 14
            for ctrl in _pressable_controls + [
                "fwdDisabled",
                "rewDisabled",
                "shuffleDisabled",
                "repeatDisabled",
                "thumbsUpDisabled",
                "thumbsDownDisabled",
            ]:
                if ctrl in s["nowplaying"]["npcontrols"]:
                    s["nowplaying_large_art"]["npcontrols"][ctrl] = _uses(
                        s["nowplaying"]["npcontrols"][ctrl], {"w": small_control_width}
                    )
        else:
            wider_div = _uses(
                _transport_control_border, {"w": 6, "padding": [2, 0, 2, 0]}
            )
            for d in ["div1", "div2", "div3", "div4", "div5", "div6"]:
                s["nowplaying_large_art"]["npcontrols"][d] = wider_div

        # Pressed controls for large art
        la_controls = s["nowplaying_large_art"]["npcontrols"]
        la_controls["pressed"] = {}
        for ctrl in _pressable_controls:
            if ctrl in la_controls:
                la_controls["pressed"][ctrl] = _uses(
                    la_controls[ctrl], {"bgImg": key_middle_pressed}
                )
        for ctrl in [
            "thumbsUpDisabled",
            "thumbsDownDisabled",
            "fwdDisabled",
            "rewDisabled",
            "shuffleDisabled",
            "repeatDisabled",
        ]:
            if ctrl in la_controls:
                la_controls["pressed"][ctrl] = _uses(la_controls[ctrl])

        s["nowplaying_large_art"]["nptitle"]["pressed"] = _uses(
            s["nowplaying_large_art"]["nptitle"]
        )
        s["nowplaying_large_art"]["npalbumgroup"]["pressed"] = _uses(
            s["nowplaying_large_art"]["npalbumgroup"]
        )
        s["nowplaying_large_art"]["npartistgroup"]["pressed"] = _uses(
            s["nowplaying_large_art"]["npartistgroup"]
        )
        s["nowplaying_large_art"]["title"]["pressed"] = _uses(
            s["nowplaying_large_art"]["title"],
            {
                "text": {
                    "fg": [0xB3, 0xB3, 0xB3],
                    "sh": [],
                    "bgImg": pressed_titlebar_button_box,
                },
            },
        )
        s["nowplaying_large_art"]["npprogress"]["npprogressB_disabled"] = _uses(
            s["nowplaying_large_art"]["npprogress"]["npprogressB"],
            {"img": _song_progress_bar_disabled},
        )

        # --- nowplaying_art_only ---
        s["nowplaying_art_only"] = _uses(
            s["nowplaying"],
            {
                "bgImg": black_background,
                "title": {"hidden": 1},
                "nptitle": {"hidden": 1},
                "npcontrols": {"hidden": 1},
                "npprogress": {"hidden": 1},
                "npprogressNB": {"hidden": 1},
                "npartistgroup": {"hidden": 1},
                "npalbumgroup": {"hidden": 1},
                "npartwork": {
                    "w": screen_height,
                    "position": LAYOUT_NONE,
                    "x": (screen_width - screen_height) // 2,
                    "y": 0,
                    "align": "center",
                    "h": screen_height,
                    "artwork": {
                        "w": screen_height,
                        "align": "center",
                        "padding": 0,
                        "img": False,
                    },
                },
                "npvisu": {"hidden": 1},
            },
        )
        s["nowplaying_art_only"]["pressed"] = s["nowplaying_art_only"]

        # --- nowplaying_text_only ---
        s["nowplaying_text_only"] = _uses(
            s["nowplaying"],
            {
                "nptitle": {
                    "x": 40,
                    "y": TITLE_HEIGHT + 50,
                    "nptrack": {"w": screen_width - 140},
                },
                "npartistgroup": {
                    "x": 40,
                    "y": TITLE_HEIGHT + 50 + 65,
                    "npartist": {"w": screen_width - 65},
                },
                "npalbumgroup": {
                    "x": 40,
                    "y": TITLE_HEIGHT + 50 + 60 + 55,
                    "npalbum": {"w": screen_width - 65},
                },
                "npartwork": {"hidden": 1},
                "npvisu": {"hidden": 1},
                "npprogress": {
                    "position": LAYOUT_NONE,
                    "x": 50,
                    "y": screen_height - 160,
                    "padding": [0, 10, 0, 0],
                    "elapsed": {
                        "w": 60,
                        "align": "left",
                        "padding": [0, 0, 4, 20],
                        "font": _boldfont(18),
                        "fg": [0xE7, 0xE7, 0xE7],
                        "sh": [0x37, 0x37, 0x37],
                    },
                    "remain": {
                        "w": 60,
                        "align": "right",
                        "padding": [4, 0, 0, 20],
                        "font": _boldfont(18),
                        "fg": [0xE7, 0xE7, 0xE7],
                        "sh": [0x37, 0x37, 0x37],
                    },
                    "elapsedSmall": {
                        "w": 60,
                        "align": "left",
                        "padding": [0, 0, 4, 20],
                        "font": _boldfont(14),
                        "fg": [0xE7, 0xE7, 0xE7],
                        "sh": [0x37, 0x37, 0x37],
                    },
                    "remainSmall": {
                        "w": 60,
                        "align": "right",
                        "padding": [4, 0, 0, 20],
                        "font": _boldfont(14),
                        "fg": [0xE7, 0xE7, 0xE7],
                        "sh": [0x37, 0x37, 0x37],
                    },
                    "npprogressB": {
                        "w": screen_width - 2 * 50 - 2 * 80,
                        "h": 50,
                        "padding": [0, 0, 0, 0],
                        "position": LAYOUT_SOUTH,
                        "horizontal": 1,
                        "bgImg": _song_progress_background,
                        "img": _song_progress_bar,
                    },
                },
                "npprogressNB": {
                    "x": 720,
                    "y": TITLE_HEIGHT + 55,
                    "padding": [0, 0, 0, 0],
                    "position": LAYOUT_NONE,
                },
            },
        )
        s["nowplaying_text_only"]["npprogress"]["npprogressB_disabled"] = _uses(
            s["nowplaying_text_only"]["npprogress"]["npprogressB"],
            {"img": _song_progress_bar_disabled},
        )
        s["nowplaying_text_only"]["pressed"] = s["nowplaying_text_only"]
        s["nowplaying_text_only"]["nptitle"]["pressed"] = _uses(
            s["nowplaying_text_only"]["nptitle"]
        )
        s["nowplaying_text_only"]["npalbumgroup"]["pressed"] = _uses(
            s["nowplaying_text_only"]["npalbumgroup"]
        )
        s["nowplaying_text_only"]["npartistgroup"]["pressed"] = _uses(
            s["nowplaying_text_only"]["npartistgroup"]
        )

        # --- Visualizer common ---
        s["nowplaying_visualizer_common"] = _uses(
            s["nowplaying"],
            {
                "bgImg": black_background,
                "npartistgroup": {"hidden": 1},
                "npalbumgroup": {"hidden": 1},
                "npartwork": {"hidden": 1},
                "title": _uses(
                    s["title"],
                    {
                        "zOrder": 1,
                        "h": TITLE_HEIGHT,
                        "text": {"padding": [screen_width, 0, 0, 0]},
                    },
                ),
                "nptitle": {
                    "zOrder": 2,
                    "position": LAYOUT_NONE,
                    "x": 80,
                    "y": 0,
                    "h": TITLE_HEIGHT,
                    "border": [0, 0, 0, 0],
                    "padding": [20, 14, 5, 5],
                    "nptrack": {
                        "align": "center",
                        "w": screen_width - 196,
                    },
                },
                "npartistalbum": {
                    "hidden": 0,
                    "zOrder": 2,
                    "position": LAYOUT_NONE,
                    "x": 0,
                    "y": TITLE_HEIGHT,
                    "w": screen_width,
                    "h": 60,
                    "bgImg": title_box,
                    "align": "center",
                    "fg": [0xB3, 0xB3, 0xB3],
                    "padding": [100, 0, 100, 5],
                    "font": _font(NP_ARTISTALBUM_FONT_SIZE),
                },
                "npprogress": {
                    "zOrder": 3,
                    "position": LAYOUT_NONE,
                    "x": 10,
                    "y": TITLE_HEIGHT + 20,
                    "h": 60,
                    "w": screen_width - 30,
                    "elapsed": {"w": 60},
                    "remain": {"w": 60},
                    "elapsedSmall": {"w": 60},
                    "remainSmall": {"w": 60},
                    "npprogressB": {
                        "h": 29,
                        "w": WH_FILL,
                        "zOrder": 10,
                        "padding": [0, 19, 0, 15],
                        "horizontal": 1,
                        "bgImg": False,
                        "img": _viz_progress_bar,
                        "pillImg": _viz_progress_bar_pill,
                    },
                },
                "npprogressNB": {
                    "x": screen_width - 80,
                    "y": TITLE_HEIGHT + 22,
                    "h": 38,
                },
            },
        )
        s["nowplaying_visualizer_common"]["npprogress"]["npprogressB_disabled"] = s[
            "nowplaying_visualizer_common"
        ]["npprogress"]["npprogressB"]

        # --- Spectrum visualizer ---
        viz_top = 2 * TITLE_HEIGHT + 4
        viz_height = 446 - (viz_top + 45)
        s["nowplaying_spectrum_text"] = _uses(
            s["nowplaying_visualizer_common"],
            {
                "npvisu": {
                    "hidden": 0,
                    "position": LAYOUT_NONE,
                    "x": 0,
                    "y": viz_top,
                    "w": 800,
                    "h": viz_height,
                    "border": [0, 0, 0, 0],
                    "padding": [0, 0, 0, 0],
                    "spectrum": {
                        "position": LAYOUT_NONE,
                        "x": 0,
                        "y": viz_top,
                        "w": 800,
                        "h": viz_height,
                        "border": [0, 0, 0, 0],
                        "padding": [0, 0, 0, 0],
                        "bg": [0x00, 0x00, 0x00, 0x00],
                        "barColor": [0x14, 0xBC, 0xBC, 0xFF],
                        "capColor": [0x74, 0x56, 0xA1, 0xFF],
                        "isMono": 0,
                        "capHeight": [4, 4],
                        "capSpace": [4, 4],
                        "channelFlipped": [0, 1],
                        "barsInBin": [2, 2],
                        "barWidth": [1, 1],
                        "barSpace": [3, 3],
                        "binSpace": [6, 6],
                        "clipSubbands": [1, 1],
                    },
                },
            },
        )
        s["nowplaying_spectrum_text"]["pressed"] = s["nowplaying_spectrum_text"]
        s["nowplaying_spectrum_text"]["title"]["pressed"] = _uses(
            s["nowplaying_spectrum_text"]["title"],
            {"text": {"padding": [screen_width, 0, 0, 0]}},
        )

        # --- VU Meter ---
        vu_top = TITLE_HEIGHT + 63
        vu_height = 413 - (TITLE_HEIGHT + 38 + 38)
        s["nowplaying_vuanalog_text"] = _uses(
            s["nowplaying_visualizer_common"],
            {
                "npvisu": {
                    "hidden": 0,
                    "position": LAYOUT_NONE,
                    "x": 0,
                    "y": vu_top,
                    "w": 800,
                    "h": vu_height,
                    "border": [0, 0, 0, 0],
                    "padding": [0, 0, 0, 0],
                    "vumeter_analog": {
                        "position": LAYOUT_NONE,
                        "x": 0,
                        "y": vu_top,
                        "w": 800,
                        "h": vu_height,
                        "border": [0, 0, 0, 0],
                        "padding": [0, 0, 0, 0],
                        "bgImg": _load_image(
                            "UNOFFICIAL/VUMeter/vu_analog_25seq_w.png"
                        ),
                    },
                },
            },
        )
        s["nowplaying_vuanalog_text"]["pressed"] = s["nowplaying_vuanalog_text"]
        s["nowplaying_vuanalog_text"]["title"]["pressed"] = _uses(
            s["nowplaying_vuanalog_text"]["title"],
            {"text": {"padding": [screen_width, 0, 0, 0]}},
        )

        # ===============================================================
        # BRIGHTNESS / SETTINGS SLIDERS
        # ===============================================================

        s["brightness_group"] = {
            "order": ["down", "div1", "slider", "div2", "up"],
            "position": LAYOUT_SOUTH,
            "h": 56,
            "w": WH_FILL,
            "bgImg": slider_background,
            "div1": _uses(_transport_control_border),
            "div2": _uses(_transport_control_border),
            "down": _uses(
                _transport_control_button,
                {
                    "w": 56,
                    "h": 56,
                    "img": _load_image("Icons/icon_toolbar_brightness_down.png"),
                },
            ),
            "up": _uses(
                _transport_control_button,
                {
                    "w": 56,
                    "h": 56,
                    "img": _load_image("Icons/icon_toolbar_brightness_up.png"),
                },
            ),
        }
        s["brightness_group"]["pressed"] = {
            "down": _uses(
                s["brightness_group"]["down"], {"bgImg": slider_button_pressed}
            ),
            "up": _uses(s["brightness_group"]["up"], {"bgImg": slider_button_pressed}),
        }

        s["brightness_slider"] = {
            "w": WH_FILL,
            "border": [5, 12, 5, 0],
            "padding": [6, 0, 6, 0],
            "position": LAYOUT_SOUTH,
            "horizontal": 1,
            "bgImg": _volume_slider_background,
            "img": _volume_slider_bar,
            "pillImg": _volume_slider_pill,
        }

        s["settings_slider_group"] = _uses(
            s["brightness_group"],
            {
                "down": {"img": _load_image("Icons/icon_toolbar_minus.png")},
                "up": {"img": _load_image("Icons/icon_toolbar_plus.png")},
            },
        )
        s["settings_slider"] = _uses(s["brightness_slider"])
        s["settings_slider_group"]["pressed"] = {
            "down": _uses(
                s["settings_slider_group"]["down"],
                {
                    "bgImg": slider_button_pressed,
                    "img": _load_image("Icons/icon_toolbar_minus_dis.png"),
                },
            ),
            "up": _uses(
                s["settings_slider_group"]["up"],
                {
                    "bgImg": slider_button_pressed,
                    "img": _load_image("Icons/icon_toolbar_plus_dis.png"),
                },
            ),
        }

        s["settings_volume_group"] = _uses(
            s["brightness_group"],
            {
                "down": {"img": _load_image("Icons/icon_toolbar_vol_down.png")},
                "up": {"img": _load_image("Icons/icon_toolbar_vol_up.png")},
            },
        )
        s["settings_volume_group"]["pressed"] = {
            "down": _uses(
                s["settings_volume_group"]["down"],
                {
                    "bgImg": slider_button_pressed,
                    "img": _load_image("Icons/icon_toolbar_vol_down_dis.png"),
                },
            ),
            "up": _uses(
                s["settings_volume_group"]["up"],
                {
                    "bgImg": slider_button_pressed,
                    "img": _load_image("Icons/icon_toolbar_vol_up_dis.png"),
                },
            ),
        }

        s["debug_canvas"] = {"zOrder": 9999}

        s["demo_text"] = {
            "font": _boldfont(18),
            "position": LAYOUT_SOUTH,
            "w": screen_width,
            "h": 50,
            "align": "center",
            "padding": [6, 0, 6, 10],
            "fg": TEXT_COLOR,
            "sh": TEXT_SH_COLOR,
        }

        # ===============================================================
        # CONSTANTS (inheritable by child skins)
        # ===============================================================

        s["CONSTANTS"] = {
            "skinSuffix": skin_suffix,
            "fiveItemBox": five_item_box,
            "fiveItemSelectionBox": five_item_selection_box,
            "fiveItemPressedBox": five_item_pressed_box,
            "threeItemSelectionBox": three_item_selection_box,
            "threeItemPressedBox": three_item_pressed_box,
            "smallSpinny": small_spinny,
            "largeSpinny": large_spinny,
            "addArrow": add_arrow,
            "CHECK_PADDING": CHECK_PADDING,
            "MENU_ITEM_ICON_PADDING": MENU_ITEM_ICON_PADDING,
            "TEXT_COLOR": TEXT_COLOR,
            "TEXT_SH_COLOR": TEXT_SH_COLOR,
            "TITLE_HEIGHT": TITLE_HEIGHT,
            "ALBUMMENU_FONT_SIZE": ALBUMMENU_FONT_SIZE,
            "ITEM_ICON_ALIGN": ITEM_ICON_ALIGN,
            "FIVE_ITEM_HEIGHT": FIVE_ITEM_HEIGHT,
            "NP_ARTISTALBUM_FONT_SIZE": NP_ARTISTALBUM_FONT_SIZE,
        }

        return s

    # ==================================================================
    # Resolution variant methods
    # ==================================================================

    def skin1024x600(
        self, s: Style, reload: bool = False, use_default_size: bool = False
    ) -> Style:
        """1024×600 resolution variant."""
        self.skin(s, reload, use_default_size, 1024, 600)

        # Put a space between volume controls and other buttons
        s["nowplaying"]["npcontrols"]["div5"]["w"] = 230
        s["nowplaying"]["npcontrols"]["div5"]["img"] = False

        return s

    def skin1280x800(
        self,
        s: Style,
        reload: bool = False,
        use_default_size: bool = False,
        w: Optional[int] = None,
        h: Optional[int] = None,
    ) -> Style:
        """1280×800 resolution variant."""
        self.skin(s, reload, use_default_size, w or 1280, h or 800)

        c = s["CONSTANTS"]
        font_scale = c["NP_ARTISTALBUM_FONT_SIZE"] * 1.2

        s["nowplaying"]["nptitle"]["nptrack"]["font"] = _boldfont(int(font_scale))
        s["nowplaying"]["npartistgroup"]["npartist"]["font"] = _font(int(font_scale))
        s["nowplaying"]["npalbumgroup"]["npalbum"]["font"] = _font(int(font_scale))

        s["nowplaying_large_art"]["nptitle"]["nptrack"]["font"] = _boldfont(
            int(font_scale)
        )
        s["nowplaying_large_art"]["npartistgroup"]["npartist"]["font"] = _font(
            int(font_scale)
        )
        s["nowplaying_large_art"]["npalbumgroup"]["npalbum"]["font"] = _font(
            int(font_scale)
        )

        # Put a space between volume controls and other buttons
        s["nowplaying"]["npcontrols"]["div5"]["w"] = 490
        s["nowplaying"]["npcontrols"]["div5"]["img"] = False

        return s

    def skin1366x768(
        self, s: Style, reload: bool = False, use_default_size: bool = False
    ) -> Style:
        """1366×768 resolution variant."""
        self.skin(s, reload, use_default_size, 1366, 768)

        # Put a space between volume controls and other buttons
        s["nowplaying"]["npcontrols"]["div5"]["w"] = 568
        s["nowplaying"]["npcontrols"]["div5"]["img"] = False

        return s

    def skinCustom(
        self, s: Style, reload: bool = False, use_default_size: bool = False
    ) -> Style:
        """Custom resolution variant (from environment variables)."""
        screen_width = 800
        screen_height = 480
        try:
            screen_width = int(os.environ.get("JL_SCREEN_WIDTH", "800"))
        except (ValueError, TypeError):
            pass
        try:
            screen_height = int(os.environ.get("JL_SCREEN_HEIGHT", "480"))
        except (ValueError, TypeError):
            pass

        self.skin(s, reload, use_default_size, screen_width, screen_height)

        c = s["CONSTANTS"]

        def _larger_font() -> None:
            font_scale = c["NP_ARTISTALBUM_FONT_SIZE"] * 1.2
            s["nowplaying"]["nptitle"]["nptrack"]["font"] = _boldfont(int(font_scale))
            s["nowplaying"]["npartistgroup"]["npartist"]["font"] = _font(
                int(font_scale)
            )
            s["nowplaying"]["npalbumgroup"]["npalbum"]["font"] = _font(int(font_scale))
            s["nowplaying_large_art"]["nptitle"]["nptrack"]["font"] = _boldfont(
                int(font_scale)
            )
            s["nowplaying_large_art"]["npartistgroup"]["npartist"]["font"] = _font(
                int(font_scale)
            )
            s["nowplaying_large_art"]["npalbumgroup"]["npalbum"]["font"] = _font(
                int(font_scale)
            )

        if screen_width == 1024 and screen_height == 600:
            s["nowplaying"]["npcontrols"]["div5"]["w"] = 230
            s["nowplaying"]["npcontrols"]["div5"]["img"] = False
        elif screen_width == 1280 and screen_height == 800:
            s["nowplaying"]["npcontrols"]["div5"]["w"] = 490
            s["nowplaying"]["npcontrols"]["div5"]["img"] = False
            _larger_font()
        elif screen_width == 1366 and screen_height == 768:
            s["nowplaying"]["npcontrols"]["div5"]["w"] = 568
            s["nowplaying"]["npcontrols"]["div5"]["img"] = False
            _larger_font()

        return s

    # ==================================================================
    # NowPlaying button configuration
    # ==================================================================

    def _get_np_button_settings(self) -> Dict[str, Any]:
        """Get NowPlaying toolbar button settings from applet settings."""
        settings = self.get_settings()
        if settings is None:
            # Return defaults
            return {
                "rew": True,
                "play": True,
                "fwd": True,
                "repeatMode": False,
                "shuffleMode": False,
                "volDown": True,
                "volSlider": False,
                "volUp": True,
            }
        return settings

    def npButtonSelectorShow(self) -> None:
        """Show the NowPlaying button selector window.

        This creates a Window with checkboxes for each toolbar button.
        In headless/test mode this is a no-op.
        """
        # This requires real UI widgets — skip if not available
        try:
            from jive.ui.checkbox import Checkbox
            from jive.ui.simplemenu import SimpleMenu
            from jive.ui.window import Window
        except ImportError:
            log.info("npButtonSelectorShow: UI not available")
            return

        np_buttons_text = (
            self.string("NOW_PLAYING_BUTTONS")
            if self._strings_table
            else "Now Playing Buttons"
        )
        window = Window("text_list", np_buttons_text)
        menu = SimpleMenu("menu")
        settings = self.get_settings() or {}

        for v in TB_BUTTONS:
            btn_token = "NOW_PLAYING_BUTTON_" + v.upper()
            btn_text = self.string(btn_token) if self._strings_table else v

            def _make_callback(button_name: str):
                def _cb(obj: Any, is_selected: bool) -> None:
                    self.setNowPlayingScreenButtons(button_name, is_selected)
                    try:
                        from jive.jive_main import jive_main as _jm

                        if _jm is not None:
                            _jm.reload_skin()
                    except (ImportError, AttributeError):
                        pass

                return _cb

            menu.add_item(
                {
                    "text": btn_text,
                    "style": "item_choice",
                    "check": Checkbox(
                        "checkbox", _make_callback(v), settings.get(v, False)
                    ),
                }
            )

        window.add_widget(menu)
        window.show()

    def setNowPlayingScreenButtons(self, button: str, is_selected: bool) -> None:
        """Set a NowPlaying toolbar button on or off."""
        settings = self.get_settings()
        if settings is None:
            settings = {}
            self.set_settings(settings)
        settings[button] = is_selected
        self.store_settings()

    def getNowPlayingScreenButtons(self) -> Dict[str, Any]:
        """Return the NowPlaying toolbar button settings."""
        return self._get_np_button_settings()

    def buttonSettingsMenuItem(self) -> Dict[str, Any]:
        """Build a menu item for the NP button settings screen."""
        np_buttons_text = (
            self.string("NOW_PLAYING_BUTTONS")
            if self._strings_table
            else "Now Playing Buttons"
        )
        return {
            "id": "npButtonSelector",
            "iconStyle": "hm_advancedSettings",
            "node": "screenSettingsNowPlaying",
            "text": np_buttons_text,
            "sound": "WINDOWSHOW",
            "callback": lambda event=None, menu_item=None: self.npButtonSelectorShow(),
        }

    # ==================================================================
    # Lifecycle
    # ==================================================================

    def free(self) -> bool:
        """Free resources held by the skin applet."""
        try:
            from jive.jive_main import jive_main as _jm

            if _jm is not None:
                _jm.remove_item_by_id("npButtonSelector")
        except (ImportError, AttributeError):
            pass

        self.images = {}
        self.imageTiles = {}
        self.hTiles = {}
        self.vTiles = {}
        self.tiles = {}
        return True
