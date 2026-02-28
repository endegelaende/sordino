"""
jive.applets.qvga_base_skin.qvga_base_skin_applet — QVGAbaseSkin applet.

Ported from ``share/jive/applets/QVGAbaseSkin/QVGAbaseSkinApplet.lua``
(~2468 LOC) in the original jivelite project.

This applet implements the base skin for any 320×240 or 240×320 screen.
It defines the complete style table (fonts, colours, padding, tile assets,
widget layouts, icon-bar styles, NowPlaying styles, etc.) that child
QVGA skins can inherit from.

The ``skin()`` method populates a style dict ``s`` with all widget
styles.  In the Lua original this dict is the global skin table; in
Python it is a plain ``dict`` that is set on the ``StyleDB`` singleton.

Key implementation notes
------------------------

* **_uses(parent, overrides)** — recursive prototype-chain style
  inheritance, mirroring the Lua ``setmetatable(__index)`` trick.
  In Python we deep-merge dicts instead of using metatables.

* **_loadImage / _font / _boldfont** — thin wrappers around
  ``Surface.loadImage`` and ``Font.load``.

* Image paths are relative to the applet's ``images/`` directory and
  are resolved via the Surface search-path mechanism.

* All colour values are ``[R, G, B]`` or ``[R, G, B, A]`` lists
  (matching the Lua ``{0xE7, 0xE7, 0xE7}`` convention).

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
    List,
    Optional,
    Sequence,
    Tuple,
    Union,
)

from jive.applet import Applet
from jive.utils.log import logger

__all__ = ["QVGAbaseSkinApplet"]

log = logger("applet.QVGAbaseSkin")

# ---------------------------------------------------------------------------
# Type alias for style dicts
# ---------------------------------------------------------------------------
Style = Dict[str, Any]

# ---------------------------------------------------------------------------
# Image / font path prefixes (relative to search path)
# ---------------------------------------------------------------------------
_IMGPATH = "applets/QVGAbaseSkin/images/"
_FONTPATH = "fonts/"
_FONT_NAME = "FreeSans"
_BOLD_PREFIX = "Bold"


# ---------------------------------------------------------------------------
# Helper: deep-merge style dicts (Lua _uses equivalent)
# ---------------------------------------------------------------------------


def _uses(parent: Optional[Style], overrides: Optional[Style] = None) -> Style:
    """Create a new style dict that inherits from *parent*.

    This mirrors the Lua helper::

        local function _uses(parent, value)
            setmetatable(style, { __index = parent })
            ...
        end

    In Python we deep-copy the parent and recursively merge *overrides*.
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
# These return *description dicts* rather than actual Surface/Tile/Font
# objects so that tests can run without pygame initialised.  When the
# rendering backend is available the style system resolves these via
# ``style_image``, ``style_tile`` and ``style_font``.
# ---------------------------------------------------------------------------


def _img(path: str) -> Style:
    """Return a lazy-loadable image reference."""
    return {"__type__": "image", "path": path}


def _load_image(file: str) -> Style:
    """Return a lazy reference to an image in the QVGAbaseSkin images dir."""
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


# ---------------------------------------------------------------------------
# Convenience: icon dict builder
# ---------------------------------------------------------------------------


def _icon_dict(x: int, y: int, img_file: str) -> Style:
    """Build an icon style dict (matches Lua ``_icon`` helper)."""
    return {
        "x": x,
        "y": y,
        "img": _load_image(img_file),
        "layer": "LAYER_FRAME",
        "position": "LAYOUT_SOUTH",
    }


# ============================================================================
# Constants (matching Lua ``jive.ui.*`` names used in the skin)
# ============================================================================

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


# ============================================================================
# QVGAbaseSkinApplet
# ============================================================================


class QVGAbaseSkinApplet(Applet):
    """Base skin applet for QVGA (320×240 / 240×320) screens.

    The ``skin()`` method builds and returns a complete style dict that
    mirrors the Lua original.  Child skins can call ``super().skin(s)``
    and then override individual styles.
    """

    def __init__(self) -> None:
        super().__init__()
        self.images: Style = {}

    def init(self) -> None:
        """Initialise the applet (lifecycle hook)."""
        super().init()
        self.images = {}

    # ------------------------------------------------------------------
    # Parameters (overridable by child skins)
    # ------------------------------------------------------------------

    def param(self) -> Style:
        """Return skin parameter constants.

        Child skins override this to change thumb sizes, NowPlaying
        behaviour, etc.
        """
        return {
            "THUMB_SIZE": 41,
            "THUMB_SIZE_MENU": 40,
            "POPUP_THUMB_SIZE": 120,
            "NOWPLAYING_MENU": True,
            # NOWPLAYING_TRACKINFO_LINES: 3 = three-line (touch),
            # 2 = two-line (radio, controller)
            "NOWPLAYING_TRACKINFO_LINES": 2,
            "nowPlayingBrowseArtworkSize": 154,
            "nowPlayingLargeArtworkSize": 240,
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
        """Populate *s* with the complete QVGA base skin style table.

        Parameters
        ----------
        s:
            The style dict to populate (typically an empty ``{}``).
        reload:
            ``True`` when the skin is being reloaded (not first load).
        use_default_size:
            ``True`` to use the default 320×240 screen size instead of
            querying the framework.

        Returns
        -------
        Style
            The populated style dict *s*.
        """
        # Screen dimensions — default to 320×240 for QVGA
        screen_width = 320
        screen_height = 240

        try:
            from jive.ui.framework import framework as _fw

            if _fw is not None and not use_default_size:
                sw, sh = _fw.get_screen_size()
                if sw > 0 and sh > 0:
                    screen_width, screen_height = sw, sh
        except Exception:
            pass

        # Skin suffix for icon variants
        skin_suffix = ".png"

        # Init s.img namespace
        s["img"] = {}

        # ---------------------------------------------------------------
        # Images and Tiles
        # ---------------------------------------------------------------
        s["img"]["iconBackground"] = _tile_vtiles(
            [
                _IMGPATH + "Toolbar/toolbar_highlight.png",
                _IMGPATH + "Toolbar/toolbar.png",
                None,
            ]
        )

        s["img"]["titleBox"] = _tile_vtiles(
            [
                None,
                _IMGPATH + "Titlebar/titlebar.png",
                _IMGPATH + "Titlebar/titlebar_shadow.png",
            ]
        )

        s["img"]["textinputWheel"] = _tile_image(
            _IMGPATH + "Text_Entry/text_bar_vert.png"
        )
        s["img"]["textinputBackground"] = _tile_9patch(
            [
                _IMGPATH + "Text_Entry/text_entry_bkgrd.png",
                _IMGPATH + "Text_Entry/text_entry_bkgrd_tl.png",
                _IMGPATH + "Text_Entry/text_entry_bkgrd_t.png",
                _IMGPATH + "Text_Entry/text_entry_bkgrd_tr.png",
                _IMGPATH + "Text_Entry/text_entry_bkgrd_r.png",
                _IMGPATH + "Text_Entry/text_entry_bkgrd_br.png",
                _IMGPATH + "Text_Entry/text_entry_bkgrd_b.png",
                _IMGPATH + "Text_Entry/text_entry_bkgrd_bl.png",
                _IMGPATH + "Text_Entry/text_entry_bkgrd_l.png",
            ]
        )

        s["img"]["softbuttonBackground"] = _tile_image(
            _IMGPATH + "Text_Entry/soft_key_bkgrd.png"
        )
        s["img"]["softbutton"] = _tile_9patch(
            [
                _IMGPATH + "Text_Entry/soft_key_button.png",
                _IMGPATH + "Text_Entry/soft_key_button_tl.png",
                _IMGPATH + "Text_Entry/soft_key_button_t.png",
                _IMGPATH + "Text_Entry/soft_key_button_tr.png",
                _IMGPATH + "Text_Entry/soft_key_button_r.png",
                _IMGPATH + "Text_Entry/soft_key_button_br.png",
                _IMGPATH + "Text_Entry/soft_key_button_b.png",
                _IMGPATH + "Text_Entry/soft_key_button_bl.png",
                _IMGPATH + "Text_Entry/soft_key_button_l.png",
            ]
        )

        s["img"]["textinputCursor"] = _tile_image(
            _IMGPATH + "Text_Entry/text_bar_vert_fill.png"
        )
        s["img"]["textinputEnterImg"] = _tile_image(
            _IMGPATH + "Icons/selection_right_textentry.png"
        )
        s["img"]["textareaBackground"] = _tile_image(
            _IMGPATH + "Titlebar/tb_dropdwn_bkrgd.png"
        )

        s["img"]["textareaBackgroundBottom"] = _tile_vtiles(
            [
                None,
                _IMGPATH + "Titlebar/tb_dropdwn_bkrgd.png",
                _IMGPATH + "Titlebar/titlebar_shadow.png",
            ]
        )

        s["img"]["pencilLineMenuDivider"] = _tile_9patch(
            [
                None,
                None,
                None,
                None,
                None,
                _IMGPATH + "Menu_Lists/menu_divider_r.png",
                _IMGPATH + "Menu_Lists/menu_divider.png",
                _IMGPATH + "Menu_Lists/menu_divider_l.png",
                None,
            ]
        )

        s["img"]["multiLineSelectionBox"] = _tile_htiles(
            [
                None,
                _IMGPATH + "Menu_Lists/menu_sel_box_82.png",
                _IMGPATH + "Menu_Lists/menu_sel_box_82_r.png",
            ]
        )

        s["img"]["timeInputSelectionBox"] = _tile_image(
            _IMGPATH + "Menu_Lists/menu_box_36.png"
        )
        s["img"]["oneLineItemSelectionBox"] = _tile_htiles(
            [
                None,
                _IMGPATH + "Menu_Lists/menu_sel_box.png",
                _IMGPATH + "Menu_Lists/menu_sel_box_r.png",
            ]
        )

        s["img"]["contextMenuSelectionBox"] = _tile_9patch(
            [
                _IMGPATH + "Popup_Menu/button_cm.png",
                _IMGPATH + "Popup_Menu/button_cm_tl.png",
                _IMGPATH + "Popup_Menu/button_cm_t.png",
                _IMGPATH + "Popup_Menu/button_cm_tr.png",
                _IMGPATH + "Popup_Menu/button_cm_r.png",
                _IMGPATH + "Popup_Menu/button_cm_br.png",
                _IMGPATH + "Popup_Menu/button_cm_b.png",
                _IMGPATH + "Popup_Menu/button_cm_bl.png",
                _IMGPATH + "Popup_Menu/button_cm_l.png",
            ]
        )

        s["img"]["songProgressBackground"] = _tile_htiles(
            [
                _IMGPATH + "Song_Progress_Bar/tb_progress_bkgrd_float_l.png",
                _IMGPATH + "Song_Progress_Bar/tb_progress_bkgrd_float.png",
                _IMGPATH + "Song_Progress_Bar/tb_progress_bkgrd_float_r.png",
            ]
        )

        s["img"]["songProgressBar"] = _tile_htiles(
            [
                _IMGPATH + "Song_Progress_Bar/tb_progress_fill_l.png",
                _IMGPATH + "Song_Progress_Bar/tb_progress_fill.png",
                _IMGPATH + "UNOFFICIAL/tb_progressbar_slider.png",
            ]
        )

        s["img"]["sliderBackground"] = _tile_htiles(
            [
                _IMGPATH + "Song_Progress_Bar/progressbar_bkgrd_l.png",
                _IMGPATH + "Song_Progress_Bar/progressbar_bkgrd.png",
                _IMGPATH + "Song_Progress_Bar/progressbar_bkgrd_r.png",
            ]
        )

        s["img"]["sliderBar"] = _tile_htiles(
            [
                _IMGPATH + "Song_Progress_Bar/rem_sliderbar_fill_l.png",
                _IMGPATH + "Song_Progress_Bar/rem_sliderbar_fill.png",
                _IMGPATH + "Song_Progress_Bar/rem_sliderbar_fill_r.png",
            ]
        )

        s["img"]["volumeBar"] = _tile_htiles(
            [
                _IMGPATH + "Song_Progress_Bar/rem_sliderbar_fill_l.png",
                _IMGPATH + "Song_Progress_Bar/rem_sliderbar_fill.png",
                _IMGPATH + "Song_Progress_Bar/rem_sliderbar_fill_r.png",
            ]
        )

        s["img"]["volumeBackground"] = _tile_htiles(
            [
                _IMGPATH + "Song_Progress_Bar/rem_sliderbar_bkgrd_l.png",
                _IMGPATH + "Song_Progress_Bar/rem_sliderbar_bkgrd.png",
                _IMGPATH + "Song_Progress_Bar/rem_sliderbar_bkgrd_r.png",
            ]
        )

        s["img"]["popupBox"] = _tile_9patch(
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

        s["img"]["contextMenuBox"] = _tile_9patch(
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

        s["img"]["popupMask"] = _fill_color(0x00000085)
        s["img"]["blackBackground"] = _fill_color(0x000000FF)

        # ---------------------------------------------------------------
        # Constants table
        # ---------------------------------------------------------------
        p = self.param()

        c: Style = {
            "THUMB_SIZE": p["THUMB_SIZE"],
            "POPUP_THUMB_SIZE": p["POPUP_THUMB_SIZE"],
            "CHECK_PADDING": [0, 0, 0, 0],
            "MENU_ALBUMITEM_PADDING": [10, 2, 4, 2],
            "MENU_ALBUMITEM_TEXT_PADDING": [8, 4, 0, 4],
            "MENU_PLAYLISTITEM_TEXT_PADDING": [6, 6, 8, 10],
            "HELP_TEXT_PADDING": [10, 10, 5, 8],
            "TEXTAREA_PADDING": [13, 8, 8, 8],
            "MENU_ITEM_ICON_PADDING": [0, 0, 10, 0],
            "SELECTED_MENU_ITEM_ICON_PADDING": [0, 0, 10, 0],
            "TEXT_COLOR": [0xE7, 0xE7, 0xE7],
            "TEXT_COLOR_TEAL": [0, 0xBE, 0xBE],
            "TEXT_COLOR_BLACK": [0x00, 0x00, 0x00],
            "TEXT_SH_COLOR": [0x37, 0x37, 0x37],
            "CM_MENU_HEIGHT": 41,
            "TEXTINPUT_WHEEL_COLOR": [0xB3, 0xB3, 0xB3],
            "TEXTINPUT_WHEEL_SELECTED_COLOR": [0xE6, 0xE6, 0xE6],
            "SELECT_COLOR": [0xE7, 0xE7, 0xE7],
            "SELECT_SH_COLOR": [],
            "TITLE_HEIGHT": 36,
            "TITLE_FONT_SIZE": 18,
            "ALBUMMENU_TITLE_FONT_SIZE": 14,
            "ALBUMMENU_FONT_SIZE": 14,
            "ALBUMMENU_SMALL_FONT_SIZE": 14,
            "ALBUMMENU_SELECTED_FONT_SIZE": 14,
            "ALBUMMENU_SELECTED_SMALL_FONT_SIZE": 14,
            "TEXTMENU_FONT_SIZE": 18,
            "TEXTMENU_SELECTED_FONT_SIZE": 21,
            "POPUP_TEXT_SIZE_1": 22,
            "POPUP_TEXT_SIZE_2": 16,
            "HELP_TEXT_FONT_SIZE": 16,
            "TEXTAREA_FONT_SIZE": 16,
            "TEXTINPUT_FONT_SIZE": 20,
            "TEXTINPUT_SELECTED_FONT_SIZE": 32,
            "HELP_FONT_SIZE": 16,
            "UPDATE_SUBTEXT_SIZE": 16,
            "ICONBAR_FONT": 12,
            "ITEM_ICON_ALIGN": "right",
            "LANDSCAPE_LINE_ITEM_HEIGHT": 45,
            "MULTILINE_LINE_ITEM_HEIGHT": 82,
            "TIME_LINE_ITEM_HEIGHT": 36,
            "PORTRAIT_LINE_ITEM_HEIGHT": 43,
        }
        s["CONSTANTS"] = c

        # ---------------------------------------------------------------
        # Small animated spinny icons
        # ---------------------------------------------------------------
        s["img"]["smallSpinny"] = {
            "img": _load_image("Alerts/wifi_connecting_sm.png"),
            "frameRate": 8,
            "frameWidth": 26,
            "padding": [0, 0, 0, 0],
            "h": WH_FILL,
        }

        s["img"]["playArrow"] = {
            "img": _load_image("Icons/selection_play_sel.png"),
            "h": WH_FILL,
        }
        s["img"]["rightArrowSel"] = {
            "img": _load_image("Icons/selection_right_sel.png"),
            "padding": [0, 0, 0, 0],
            "h": WH_FILL,
            "align": "center",
        }
        s["img"]["rightArrow"] = {
            "img": _load_image("Icons/selection_right_off.png"),
            "padding": [0, 0, 0, 0],
            "h": WH_FILL,
            "align": "center",
        }
        s["img"]["checkMark"] = {
            "align": c["ITEM_ICON_ALIGN"],
            "padding": c["CHECK_PADDING"],
            "img": _load_image("Icons/icon_check_off.png"),
        }
        s["img"]["checkMarkSelected"] = {
            "align": c["ITEM_ICON_ALIGN"],
            "padding": c["CHECK_PADDING"],
            "img": _load_image("Icons/icon_check_sel.png"),
        }

        # ---------------------------------------------------------------
        # DEFAULT WIDGET STYLES
        # ---------------------------------------------------------------

        s["window"] = {
            "w": screen_width,
            "h": screen_height,
        }

        # window with absolute positioning
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
                "maskImg": s["img"]["blackBackground"],
            },
        )

        s["title"] = {
            "h": c["TITLE_HEIGHT"],
            "border": 0,
            "position": LAYOUT_NORTH,
            "bgImg": s["img"]["titleBox"],
            "order": ["text"],
            "text": {
                "w": WH_FILL,
                "h": WH_FILL,
                "padding": [10, 0, 10, 0],
                "align": "left",
                "font": _boldfont(c["TITLE_FONT_SIZE"]),
                "fg": c["SELECT_COLOR"],
                "sh": c["SELECT_SH_COLOR"],
            },
        }

        s["title"]["textButton"] = _uses(
            s["title"]["text"],
            {
                "padding": 0,
            },
        )
        s["title"]["pressed"] = {}
        s["title"]["pressed"]["textButton"] = s["title"]["textButton"]

        s["text_block_black"] = {
            "hidden": 1,
        }

        s["menu"] = {
            "h": screen_height - 60,
            "position": LAYOUT_NORTH,
            "padding": 0,
            "border": [0, 36, 0, 0],
            "itemHeight": c["LANDSCAPE_LINE_ITEM_HEIGHT"],
            "font": _boldfont(80),
            "fg": c["TEXT_COLOR"],
            "sh": c["TEXT_SH_COLOR"],
        }
        s["menu"]["selected"] = {}
        s["menu"]["selected"]["item"] = {}

        s["menu_hidden"] = _uses(
            s["menu"],
            {
                "hidden": 1,
            },
        )

        s["item"] = {
            "order": ["icon", "text", "arrow"],
            "padding": [10, 1, 5, 1],
            "bgImg": s["img"]["pencilLineMenuDivider"],
            "text": {
                "padding": [0, 0, 0, 0],
                "align": "left",
                "w": WH_FILL,
                "h": WH_FILL,
                "font": _boldfont(c["TEXTMENU_FONT_SIZE"]),
                "fg": c["TEXT_COLOR"],
                "sh": c["TEXT_SH_COLOR"],
            },
            "icon": {
                "padding": c["MENU_ITEM_ICON_PADDING"],
                "align": "center",
                "h": c["THUMB_SIZE"],
            },
            "arrow": s["img"]["rightArrow"],
        }

        s["item_play"] = _uses(
            s["item"],
            {
                "arrow": {"img": False},
            },
        )
        s["item_add"] = _uses(s["item"])

        # Checkbox
        s["checkbox"] = {
            "h": WH_FILL,
            "padding": [0, 12, 3, 0],
        }
        s["checkbox"]["img_on"] = _load_image("Icons/checkbox_on.png")
        s["checkbox"]["img_off"] = _load_image("Icons/checkbox_off.png")

        # Radio button
        s["radio"] = {
            "h": WH_FILL,
            "padding": [0, 12, 3, 0],
        }
        s["radio"]["img_on"] = _load_image("Icons/radiobutton_on.png")
        s["radio"]["img_off"] = _load_image("Icons/radiobutton_off.png")

        s["choice"] = {
            "align": "right",
            "font": _boldfont(c["TEXTMENU_FONT_SIZE"]),
            "fg": c["TEXT_COLOR"],
            "sh": c["TEXT_SH_COLOR"],
            "h": WH_FILL,
        }

        s["item_choice"] = _uses(
            s["item"],
            {
                "order": ["icon", "text", "check"],
                "check": {
                    "align": "right",
                    "h": WH_FILL,
                },
            },
        )

        s["item_info"] = _uses(
            s["item"],
            {
                "order": ["text"],
                "padding": c["MENU_ALBUMITEM_PADDING"],
                "text": {
                    "align": "top-left",
                    "w": WH_FILL,
                    "h": WH_FILL,
                    "padding": [0, 4, 0, 4],
                    "font": _font(14),
                    "line": [
                        {"font": _font(14), "height": 16},
                        {"font": _boldfont(18), "height": 18},
                    ],
                },
            },
        )

        s["item_checked"] = _uses(
            s["item"],
            {
                "order": ["icon", "text", "check", "arrow"],
                "check": s["img"]["checkMark"],
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

        # selected menu item
        s["selected"] = {}
        s["selected"]["item"] = _uses(
            s["item"],
            {
                "order": ["icon", "text", "arrow"],
                "text": {
                    "font": _boldfont(c["TEXTMENU_SELECTED_FONT_SIZE"]),
                    "fg": c["SELECT_COLOR"],
                    "sh": c["SELECT_SH_COLOR"],
                },
                "bgImg": s["img"]["oneLineItemSelectionBox"],
                "arrow": s["img"]["rightArrowSel"],
            },
        )
        s["selected"]["item_info"] = _uses(
            s["item_info"],
            {
                "bgImg": s["img"]["oneLineItemSelectionBox"],
                "text": {
                    "line": [
                        {"font": _font(14), "height": 14},
                        {"font": _boldfont(21), "height": 21},
                    ],
                },
            },
        )

        s["selected"]["choice"] = _uses(
            s["choice"],
            {
                "fg": c["SELECT_COLOR"],
                "sh": c["SELECT_SH_COLOR"],
            },
        )
        s["selected"]["item_choice"] = _uses(
            s["selected"]["item"],
            {
                "order": ["icon", "text", "check"],
                "check": {
                    "align": "right",
                    "font": _boldfont(c["TEXTMENU_FONT_SIZE"]),
                    "fg": c["SELECT_COLOR"],
                    "sh": c["SELECT_SH_COLOR"],
                },
                "radio": {
                    "img_on": _load_image("Icons/radiobutton_on_sel.png"),
                    "img_off": _load_image("Icons/radiobutton_off_sel.png"),
                    "padding": [0, 10, 0, 0],
                },
                "checkbox": {
                    "img_on": _load_image("Icons/checkbox_on_sel.png"),
                    "img_off": _load_image("Icons/checkbox_off_sel.png"),
                    "padding": [0, 10, 0, 0],
                },
            },
        )

        s["selected"]["item_play"] = _uses(
            s["selected"]["item"],
            {
                "arrow": {"img": False},
            },
        )
        s["selected"]["item_add"] = _uses(s["selected"]["item"])
        s["selected"]["item_checked"] = _uses(
            s["selected"]["item"],
            {
                "order": ["icon", "text", "check", "arrow"],
                "check": s["img"]["checkMarkSelected"],
            },
        )
        s["selected"]["item_no_arrow"] = _uses(
            s["selected"]["item"],
            {
                "order": ["text"],
            },
        )
        s["selected"]["item_checked_no_arrow"] = _uses(
            s["selected"]["item_checked"],
            {
                "order": ["icon", "text", "check"],
                "check": s["img"]["checkMark"],
            },
        )

        # pressed state — uses same selection box as selected
        # (threeItemPressedBox is not defined in QVGA base, falls
        #  back to None/the selected box)
        three_item_pressed_box = None

        s["pressed"] = {
            "item": _uses(
                s["selected"]["item"],
                {
                    "bgImg": three_item_pressed_box,
                },
            ),
            "item_checked": _uses(
                s["selected"]["item_checked"],
                {
                    "bgImg": three_item_pressed_box,
                },
            ),
            "item_play": _uses(
                s["selected"]["item_play"],
                {
                    "bgImg": three_item_pressed_box,
                },
            ),
            "item_add": _uses(
                s["selected"]["item_add"],
                {
                    "bgImg": three_item_pressed_box,
                },
            ),
            "item_no_arrow": _uses(
                s["selected"]["item_no_arrow"],
                {
                    "bgImg": three_item_pressed_box,
                },
            ),
            "item_checked_no_arrow": _uses(
                s["selected"]["item_checked_no_arrow"],
                {
                    "bgImg": three_item_pressed_box,
                },
            ),
            "item_choice": _uses(
                s["selected"]["item_choice"],
                {
                    "bgImg": three_item_pressed_box,
                },
            ),
        }

        s["locked"] = {
            "item": _uses(
                s["pressed"]["item"],
                {
                    "arrow": s["img"]["smallSpinny"],
                },
            ),
            "item_checked": _uses(
                s["pressed"]["item_checked"],
                {
                    "arrow": s["img"]["smallSpinny"],
                },
            ),
            "item_play": _uses(
                s["pressed"]["item_play"],
                {
                    "arrow": s["img"]["smallSpinny"],
                },
            ),
            "item_add": _uses(
                s["pressed"]["item_add"],
                {
                    "arrow": s["img"]["smallSpinny"],
                },
            ),
            "item_no_arrow": _uses(
                s["pressed"]["item_no_arrow"],
                {
                    "arrow": s["img"]["smallSpinny"],
                },
            ),
            "item_checked_no_arrow": _uses(
                s["pressed"]["item_checked_no_arrow"],
                {
                    "arrow": s["img"]["smallSpinny"],
                },
            ),
        }

        s["item_blank"] = {
            "padding": [],
            "text": {},
            "bgImg": s["img"]["textareaBackground"],
        }
        s["item_blank_bottom"] = _uses(
            s["item_blank"],
            {
                "bgImg": s["img"]["textareaBackgroundBottom"],
            },
        )

        s["pressed"]["item_blank"] = _uses(s["item_blank"])
        s["selected"]["item_blank"] = _uses(s["item_blank"])
        s["pressed"]["item_blank_bottom"] = _uses(s["item_blank_bottom"])
        s["selected"]["item_blank_bottom"] = _uses(s["item_blank_bottom"])

        s["help_text"] = {
            "w": screen_width - 20,
            "padding": c["HELP_TEXT_PADDING"],
            "font": _font(c["HELP_TEXT_FONT_SIZE"]),
            "lineHeight": c["HELP_TEXT_FONT_SIZE"] + 4,
            "fg": c["TEXT_COLOR"],
            "sh": c["TEXT_SH_COLOR"],
            "align": "top-left",
        }

        s["text"] = {
            "w": screen_width,
            "padding": c["TEXTAREA_PADDING"],
            "font": _boldfont(c["TEXTAREA_FONT_SIZE"]),
            "fg": c["TEXT_COLOR"],
            "sh": c["TEXT_SH_COLOR"],
            "align": "left",
        }

        s["multiline_text"] = {
            "w": WH_FILL,
            "padding": [10, 0, 2, 0],
            "lineHeight": 21,
            "font": _font(18),
            "fg": [0xE6, 0xE6, 0xE6],
            "sh": [],
            "align": "left",
            "scrollbar": {
                "h": c["MULTILINE_LINE_ITEM_HEIGHT"] * 2 - 8,
                "border": [0, 4, 20, 0],
            },
        }

        # Slider
        s["slider"] = {
            "border": 5,
            "w": WH_FILL,
            "horizontal": 1,
            "bgImg": s["img"]["volumeBackground"],
            "img": s["img"]["volumeBar"],
        }

        s["slider_group"] = {
            "w": WH_FILL,
            "order": ["slider"],
        }

        s["settings_slider_group"] = {
            "bgImg": s["img"]["textareaBackground"],
            "order": ["slider"],
            "position": LAYOUT_NONE,
            "x": 0,
            "y": screen_height - 24 - 56,
            "h": 56,
            "w": WH_FILL,
        }

        s["settings_slider"] = {
            "w": WH_FILL,
            "border": [10, 23, 10, 0],
            "padding": [0, 0, 0, 0],
            "position": LAYOUT_SOUTH,
            "horizontal": 1,
            "bgImg": s["img"]["volumeBackground"],
            "img": s["img"]["volumeBar"],
        }

        s["volume_slider_group"] = s["slider_group"]

        s["brightness_group"] = s["settings_slider_group"]
        s["brightness_slider"] = s["settings_slider"]

        # ---------------------------------------------------------------
        # SPECIAL WIDGETS
        # ---------------------------------------------------------------

        # text input
        s["textinput"] = {
            "h": WH_FILL,
            "border": [8, 0, 8, 0],
            "padding": [8, 0, 8, 0],
            "align": "center",
            "font": _boldfont(c["TEXTINPUT_FONT_SIZE"]),
            "cursorFont": _boldfont(c["TEXTINPUT_SELECTED_FONT_SIZE"]),
            "wheelFont": _boldfont(24),
            "charHeight": 46,
            "wheelCharHeight": 24,
            "fg": c["TEXT_COLOR_BLACK"],
            "wh": c["TEXTINPUT_WHEEL_COLOR"],
            "bgImg": s["img"]["textinputBackground"],
            "cursorImg": s["img"]["textinputCursor"],
            "enterImg": s["img"]["textinputEnterImg"],
            "wheelImg": s["img"]["textinputWheel"],
            "cursorColor": c["TEXTINPUT_WHEEL_SELECTED_COLOR"],
            "charOffsetY": 13,
            "wheelCharOffsetY": 6,
        }

        # soft buttons
        s["softButtons"] = {
            "order": ["spacer"],
            "position": LAYOUT_SOUTH,
            "h": 51,
            "w": WH_FILL,
            "spacer": {
                "w": WH_FILL,
                "font": _font(10),
                "fg": c["TEXT_COLOR"],
            },
            "bgImg": s["img"]["softbuttonBackground"],
            "padding": [8, 8, 8, 8],
        }

        # ---------------------------------------------------------------
        # WINDOW STYLES
        # ---------------------------------------------------------------

        # text_list is the standard window style
        s["text_list"] = _uses(s["window"])

        # text_only removes icons
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

        # text_list title with multi-line support
        s["text_list"]["title"] = _uses(
            s["title"],
            {
                "text": {
                    "line": [
                        {
                            "font": _boldfont(c["ALBUMMENU_TITLE_FONT_SIZE"] + 5),
                            "height": c["ALBUMMENU_TITLE_FONT_SIZE"] + 6,
                        },
                        {
                            "font": _boldfont(c["ALBUMMENU_TITLE_FONT_SIZE"] - 4),
                            "height": c["ALBUMMENU_TITLE_FONT_SIZE"] - 5,
                        },
                        {
                            "font": _font(1),
                            "height": 1,
                        },
                    ],
                },
            },
        )

        s["text_list"]["title"]["textButton"] = _uses(
            s["text_list"]["title"]["text"],
            {
                "padding": 0,
                "border": 0,
            },
        )
        s["text_list"]["title"]["pressed"] = {}
        s["text_list"]["title"]["pressed"]["textButton"] = s["text_list"]["title"][
            "textButton"
        ]

        # popup "spinny" window
        s["waiting_popup"] = _uses(s["popup"])

        s["waiting_popup"]["text"] = {
            "padding": [0, 29, 0, 0],
            "fg": c["TEXT_COLOR"],
            "sh": c["TEXT_SH_COLOR"],
            "align": "top",
            "position": LAYOUT_NORTH,
            "font": _font(c["POPUP_TEXT_SIZE_1"]),
        }

        s["waiting_popup"]["subtext"] = {
            "padding": [0, 0, 0, 34],
            "font": _boldfont(c["POPUP_TEXT_SIZE_2"]),
            "fg": c["TEXT_COLOR"],
            "sh": c["TEXT_SH_COLOR"],
            "align": "top",
            "position": LAYOUT_SOUTH,
            "w": WH_FILL,
        }

        s["waiting_popup"]["subtext_connected"] = _uses(
            s["waiting_popup"]["subtext"],
            {
                "fg": c["TEXT_COLOR_TEAL"],
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

        # error window
        s["error"] = _uses(s["window"])

        # home_menu
        home_loading_icon = _load_image("IconsResized/icon_loading" + skin_suffix)
        s["home_menu"] = _uses(
            s["window"],
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

        s["home_menu"]["menu"]["item"]["icon_no_artwork"] = {
            "img": home_loading_icon,
            "w": 51,
            "padding": [0, 1, 0, 0],
        }
        s["home_menu"]["menu"]["selected"]["item"]["icon_no_artwork"] = {
            "img": home_loading_icon,
            "w": 51,
            "padding": [0, 1, 0, 0],
        }
        s["home_menu"]["menu"]["locked"]["item"]["icon_no_artwork"] = {
            "img": home_loading_icon,
            "w": 51,
            "padding": [0, 1, 0, 0],
        }
        s["home_menu"]["menu"]["item_play"] = _uses(
            s["home_menu"]["menu"]["item"],
            {
                "arrow": {"img": False},
            },
        )
        s["home_menu"]["menu"]["selected"]["item_play"] = _uses(
            s["home_menu"]["menu"]["selected"]["item"],
            {
                "arrow": {"img": False},
            },
        )
        s["home_menu"]["menu"]["locked"]["item_play"] = _uses(
            s["home_menu"]["menu"]["locked"]["item"],
            {
                "arrow": {"img": False},
            },
        )

        s["help_list"] = _uses(s["text_list"])

        # choose player window
        s["choose_player"] = s["text_list"]

        # ---------------------------------------------------------------
        # Time input
        # ---------------------------------------------------------------
        _time_first_column_x_12h = 65
        _time_first_column_x_24h = 98

        s["time_input_menu_box_12h"] = {"hidden": 1, "img": False}
        s["time_input_menu_box_24h"] = {"hidden": 1, "img": False}

        s["time_input_background_12h"] = {
            "w": WH_FILL,
            "h": screen_height,
            "position": LAYOUT_NONE,
            "img": _load_image("Multi_Character_Entry/land_multi_char_bkgrd_3c.png"),
            "x": 0,
            "y": c["TITLE_HEIGHT"],
        }

        s["time_input_background_24h"] = {
            "w": WH_FILL,
            "h": screen_height,
            "position": LAYOUT_NONE,
            "img": _load_image("Multi_Character_Entry/land_multi_char_bkgrd_2c.png"),
            "x": 0,
            "y": c["TITLE_HEIGHT"],
        }

        # time input 12h
        _time_menu_base: Style = _uses(
            s["menu"],
            {
                "w": 60,
                "h": screen_height - 60,
                "itemHeight": c["TIME_LINE_ITEM_HEIGHT"],
                "position": LAYOUT_WEST,
                "padding": 0,
                "border": [_time_first_column_x_12h, 36, 0, 24],
                "item": {
                    "bgImg": False,
                    "order": ["text"],
                    "text": {
                        "align": "right",
                        "font": _boldfont(21),
                        "padding": [2, 0, 12, 0],
                        "fg": [0xB3, 0xB3, 0xB3],
                        "sh": [],
                    },
                },
                "selected": {
                    "item": {
                        "order": ["text"],
                        "bgImg": s["img"]["timeInputSelectionBox"],
                        "text": {
                            "font": _boldfont(24),
                            "fg": [0xE6, 0xE6, 0xE6],
                            "sh": [],
                            "align": "right",
                            "padding": [2, 0, 10, 0],
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
                "border": [_time_first_column_x_12h + 65, 36, 0, 24],
            },
        )

        s["input_time_12h"]["ampm"] = _uses(
            _time_menu_base,
            {
                "border": [_time_first_column_x_12h + 65 + 65, 36, 0, 24],
                "item": {
                    "text": {
                        "padding": [0, 0, 8, 0],
                        "font": _boldfont(20),
                    },
                },
                "selected": {
                    "item": {
                        "text": {
                            "padding": [0, 0, 8, 0],
                            "font": _boldfont(23),
                        },
                    },
                },
            },
        )

        _unsel_style: Style = {
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
                        "padding": [2, 0, 12, 0],
                    },
                },
            },
        }
        s["input_time_12h"]["hourUnselected"] = _uses(
            s["input_time_12h"]["hour"], _unsel_style
        )
        s["input_time_12h"]["minuteUnselected"] = _uses(
            s["input_time_12h"]["minute"], _unsel_style
        )
        s["input_time_12h"]["ampmUnselected"] = _uses(
            s["input_time_12h"]["ampm"],
            {
                "item": {
                    "text": {
                        "fg": [0x66, 0x66, 0x66],
                        "font": _boldfont(20),
                        "padding": [0, 0, 8, 0],
                    },
                },
                "selected": {
                    "item": {
                        "bgImg": False,
                        "text": {
                            "fg": [0x66, 0x66, 0x66],
                            "font": _boldfont(20),
                            "padding": [0, 0, 8, 0],
                        },
                    },
                },
            },
        )

        # time input 24h
        s["input_time_24h"] = _uses(
            s["input_time_12h"],
            {
                "hour": {"border": [_time_first_column_x_24h, 36, 0, 24]},
                "minute": {
                    "border": [_time_first_column_x_24h + 65, 36, 0, 24],
                },
                "hourUnselected": {
                    "border": [_time_first_column_x_24h, 36, 0, 24],
                },
                "minuteUnselected": {
                    "border": [_time_first_column_x_24h + 65, 36, 0, 24],
                },
            },
        )

        # ---------------------------------------------------------------
        # icon_list window
        # ---------------------------------------------------------------
        s["icon_list"] = _uses(
            s["window"],
            {
                "menu": _uses(
                    s["menu"],
                    {
                        "itemHeight": c["LANDSCAPE_LINE_ITEM_HEIGHT"],
                        "item": {
                            "order": ["icon", "text", "arrow"],
                            "padding": c["MENU_ALBUMITEM_PADDING"],
                            "text": {
                                "align": "top-left",
                                "w": WH_FILL,
                                "h": WH_FILL,
                                "padding": c["MENU_ALBUMITEM_TEXT_PADDING"],
                                "font": _font(c["ALBUMMENU_SMALL_FONT_SIZE"]),
                                "line": [
                                    {"font": _boldfont(18), "height": 20},
                                    {"font": _font(14), "height": 18},
                                ],
                                "fg": c["TEXT_COLOR"],
                                "sh": c["TEXT_SH_COLOR"],
                            },
                            "icon": {
                                "w": c["THUMB_SIZE"],
                                "h": c["THUMB_SIZE"],
                            },
                            "arrow": s["img"]["rightArrow"],
                        },
                    },
                ),
            },
        )

        s["icon_list"]["menu"]["item_checked"] = _uses(
            s["icon_list"]["menu"]["item"],
            {
                "order": ["icon", "text", "check"],
                "check": {
                    "align": c["ITEM_ICON_ALIGN"],
                    "padding": c["CHECK_PADDING"],
                    "img": _load_image("Icons/icon_check_off.png"),
                },
            },
        )

        s["icon_list"]["menu"]["item_play"] = _uses(
            s["icon_list"]["menu"]["item"],
            {
                "arrow": {"img": False},
            },
        )
        s["icon_list"]["menu"]["item_add"] = _uses(s["icon_list"]["menu"]["item"])
        s["icon_list"]["menu"]["item_no_arrow"] = _uses(s["icon_list"]["menu"]["item"])
        s["icon_list"]["menu"]["item_checked_no_arrow"] = _uses(
            s["icon_list"]["menu"]["item_checked"]
        )
        s["icon_list"]["menu"]["albumcurrent"] = _uses(
            s["icon_list"]["menu"]["item"],
            {
                "arrow": {
                    "img": _load_image("Icons/icon_nplay_off.png"),
                },
            },
        )

        # icon_list selected
        s["icon_list"]["menu"]["selected"] = {}
        s["icon_list"]["menu"]["selected"]["item"] = _uses(
            s["icon_list"]["menu"]["item"],
            {
                "order": ["icon", "text", "arrow"],
                "text": {
                    "font": _boldfont(c["TEXTMENU_SELECTED_FONT_SIZE"]),
                    "fg": c["SELECT_COLOR"],
                    "sh": c["SELECT_SH_COLOR"],
                    "line": [
                        {"font": _boldfont(21), "height": 21},
                        {"font": _font(14), "height": 14},
                    ],
                },
                "bgImg": s["img"]["oneLineItemSelectionBox"],
                "arrow": s["img"]["rightArrowSel"],
            },
        )
        s["icon_list"]["menu"]["selected"]["item_checked"] = _uses(
            s["icon_list"]["menu"]["selected"]["item"],
            {
                "order": ["icon", "text", "check", "arrow"],
            },
        )
        s["icon_list"]["menu"]["selected"]["item_play"] = _uses(
            s["icon_list"]["menu"]["selected"]["item"],
            {
                "arrow": {"img": False},
            },
        )
        s["icon_list"]["menu"]["selected"]["albumcurrent"] = _uses(
            s["icon_list"]["menu"]["selected"]["item"],
            {
                "arrow": {
                    "img": _load_image("Icons/icon_nplay_sel.png"),
                },
            },
        )
        s["icon_list"]["menu"]["selected"]["item_add"] = _uses(
            s["icon_list"]["menu"]["selected"]["item"]
        )
        s["icon_list"]["menu"]["selected"]["item_no_arrow"] = _uses(
            s["icon_list"]["menu"]["selected"]["item"],
            {
                "order": ["icon", "text"],
            },
        )
        s["icon_list"]["menu"]["selected"]["item_checked_no_arrow"] = _uses(
            s["icon_list"]["menu"]["selected"]["item"],
            {
                "order": ["icon", "text", "check"],
                "check": s["img"]["checkMark"],
            },
        )

        # icon_list pressed
        s["icon_list"]["menu"]["pressed"] = {
            "item": _uses(
                s["icon_list"]["menu"]["selected"]["item"],
                {
                    "bgImg": three_item_pressed_box,
                },
            ),
            "item_checked": _uses(
                s["icon_list"]["menu"]["selected"]["item_checked"],
                {
                    "bgImg": three_item_pressed_box,
                },
            ),
            "item_play": _uses(
                s["icon_list"]["menu"]["selected"]["item_play"],
                {
                    "bgImg": three_item_pressed_box,
                },
            ),
            "item_add": _uses(
                s["icon_list"]["menu"]["selected"]["item_add"],
                {
                    "bgImg": three_item_pressed_box,
                },
            ),
            "item_no_arrow": _uses(
                s["icon_list"]["menu"]["selected"]["item_no_arrow"],
                {
                    "bgImg": three_item_pressed_box,
                },
            ),
            "item_checked_no_arrow": _uses(
                s["icon_list"]["menu"]["selected"]["item_checked_no_arrow"],
                {
                    "bgImg": three_item_pressed_box,
                },
            ),
            "albumcurrent": _uses(
                s["icon_list"]["menu"]["selected"]["albumcurrent"],
                {
                    "bgImg": three_item_pressed_box,
                },
            ),
        }

        # icon_list locked
        s["icon_list"]["menu"]["locked"] = {
            "item": _uses(
                s["icon_list"]["menu"]["pressed"]["item"],
                {
                    "arrow": s["img"]["smallSpinny"],
                },
            ),
            "item_checked": _uses(
                s["icon_list"]["menu"]["pressed"]["item_checked"],
                {
                    "arrow": s["img"]["smallSpinny"],
                },
            ),
            "item_play": _uses(
                s["icon_list"]["menu"]["pressed"]["item_play"],
                {
                    "arrow": s["img"]["smallSpinny"],
                },
            ),
            "item_add": _uses(
                s["icon_list"]["menu"]["pressed"]["item_add"],
                {
                    "arrow": s["img"]["smallSpinny"],
                },
            ),
            "albumcurrent": _uses(
                s["icon_list"]["menu"]["pressed"]["albumcurrent"],
                {
                    "arrow": s["img"]["smallSpinny"],
                },
            ),
        }

        # ---------------------------------------------------------------
        # multiline_text_list
        # ---------------------------------------------------------------
        s["multiline_text_list"] = _uses(
            s["text_list"],
            {
                "multiline_text": {
                    "w": WH_FILL,
                    "padding": [10, 0, 2, 0],
                    "lineHeight": 21,
                    "font": _font(18),
                    "fg": [0xE6, 0xE6, 0xE6],
                    "sh": [],
                    "align": "left",
                },
            },
        )

        s["multiline_text_list"]["title"] = _uses(
            s["title"],
            {
                "h": 51,
            },
        )

        s["multiline_text_list"]["menu"] = _uses(
            s["menu"],
            {
                "h": screen_height - 75,
                "border": [0, 52, 0, 24],
                "itemHeight": c["MULTILINE_LINE_ITEM_HEIGHT"],
                "scrollbar": {
                    "h": c["MULTILINE_LINE_ITEM_HEIGHT"] * 2 - 8,
                    "border": [0, 4, 0, 4],
                },
                "item": {
                    "order": ["icon", "text", "arrow"],
                    "padding": [10, 13, 2, 8],
                    "text": {
                        "align": "top-left",
                        "w": WH_FILL,
                        "h": WH_FILL,
                        "padding": c["MENU_ALBUMITEM_TEXT_PADDING"],
                        "font": _font(18),
                        "lineHeight": 21,
                        "fg": [0xE6, 0xE6, 0xE6],
                    },
                    "icon": {
                        "w": c["THUMB_SIZE"],
                        "h": c["THUMB_SIZE"],
                        "padding": [0, 10, 10, 0],
                    },
                    "arrow": s["img"]["rightArrow"],
                },
            },
        )

        s["multiline_text_list"]["menu"]["item_no_arrow"] = _uses(
            s["multiline_text_list"]["menu"]["item"]
        )

        s["multiline_text_list"]["menu"]["selected"] = {}
        s["multiline_text_list"]["menu"]["selected"]["item"] = _uses(
            s["multiline_text_list"]["menu"]["item"],
            {
                "bgImg": s["img"]["multiLineSelectionBox"],
                "arrow": s["img"]["rightArrowSel"],
            },
        )
        s["multiline_text_list"]["menu"]["selected"]["item_no_arrow"] = _uses(
            s["multiline_text_list"]["menu"]["selected"]["item"]
        )

        s["multiline_text_list"]["menu"]["pressed"] = _uses(
            s["multiline_text_list"]["menu"]["selected"]
        )
        s["multiline_text_list"]["menu"]["locked"] = _uses(
            s["multiline_text_list"]["menu"]["selected"],
            {
                "item": {
                    "arrow": s["img"]["smallSpinny"],
                },
            },
        )

        # information window
        s["information"] = _uses(s["window"])
        s["information"]["text"] = {
            "font": _font(16),
            "fg": c["TEXT_COLOR"],
            "sh": c["TEXT_SH_COLOR"],
            "padding": [10, 10, 10, 10],
            "lineHeight": 20,
        }

        # help window
        s["help_info"] = _uses(
            s["window"],
            {
                "text": {
                    "font": _font(c["TEXTAREA_FONT_SIZE"]),
                },
            },
        )

        # track_list window
        s["track_list"] = _uses(s["text_list"])
        s["track_list"]["title"] = _uses(
            s["title"],
            {
                "h": 52,
                "order": ["icon", "text"],
                "padding": [10, 0, 0, 0],
                "icon": {
                    "w": 51,
                    "h": WH_FILL,
                },
                "text": {
                    "padding": c["MENU_ALBUMITEM_TEXT_PADDING"],
                    "align": "top-left",
                    "font": _font(c["ALBUMMENU_TITLE_FONT_SIZE"]),
                    "lineHeight": c["ALBUMMENU_TITLE_FONT_SIZE"] + 1,
                    "line": [
                        {
                            "font": _boldfont(c["ALBUMMENU_TITLE_FONT_SIZE"]),
                            "height": c["ALBUMMENU_TITLE_FONT_SIZE"] + 2,
                        },
                        {"font": _font(12), "height": 14},
                    ],
                },
            },
        )
        s["track_list"]["menu"] = _uses(
            s["menu"],
            {
                "itemHeight": 41,
                "h": 164,
                "border": [0, 52, 0, 0],
            },
        )

        # play_list window (identical to icon_list with different text formatting)
        s["play_list"] = _uses(
            s["icon_list"],
            {
                "title": {
                    "order": ["text"],
                },
                "menu": {
                    "item": {
                        "text": {
                            "padding": c["MENU_PLAYLISTITEM_TEXT_PADDING"],
                            "font": _font(c["ALBUMMENU_FONT_SIZE"]),
                            "lineHeight": 16,
                            "line": [
                                {
                                    "font": _boldfont(c["ALBUMMENU_FONT_SIZE"]),
                                    "height": c["ALBUMMENU_FONT_SIZE"] + 3,
                                },
                            ],
                        },
                    },
                },
            },
        )
        s["play_list"]["menu"]["item_checked"] = _uses(
            s["play_list"]["menu"]["item"],
            {
                "order": ["icon", "text", "check", "arrow"],
                "check": {
                    "align": c["ITEM_ICON_ALIGN"],
                    "padding": c["CHECK_PADDING"],
                    "img": _load_image("Icons/icon_check_off.png"),
                },
            },
        )
        s["play_list"]["menu"]["selected"] = {
            "item": _uses(
                s["play_list"]["menu"]["item"],
                {
                    "text": {
                        "fg": c["SELECT_COLOR"],
                        "sh": c["SELECT_SH_COLOR"],
                    },
                    "bgImg": s["img"]["oneLineItemSelectionBox"],
                },
            ),
            "item_checked": _uses(s["play_list"]["menu"]["item_checked"]),
        }
        s["play_list"]["menu"]["pressed"] = {
            "item": _uses(
                s["play_list"]["menu"]["item"],
                {
                    "bgImg": three_item_pressed_box,
                },
            ),
            "item_checked": _uses(
                s["play_list"]["menu"]["item_checked"],
                {
                    "bgImg": three_item_pressed_box,
                },
            ),
        }
        s["play_list"]["menu"]["locked"] = {
            "item": _uses(
                s["play_list"]["menu"]["pressed"]["item"],
                {
                    "arrow": s["img"]["smallSpinny"],
                },
            ),
            "item_checked": _uses(
                s["play_list"]["menu"]["pressed"]["item_checked"],
                {
                    "arrow": s["img"]["smallSpinny"],
                },
            ),
        }

        # ---------------------------------------------------------------
        # Toast popups
        # ---------------------------------------------------------------
        s["toast_popup_textarea"] = {
            "padding": [6, 6, 8, 8],
            "align": "left",
            "w": WH_FILL,
            "h": 135,
            "font": _boldfont(18),
            "lineHeight": 21,
            "fg": c["TEXT_COLOR"],
            "sh": c["TEXT_SH_COLOR"],
            "scrollbar": {"h": 115},
        }

        s["toast_popup"] = {
            "x": 19,
            "y": 46,
            "w": screen_width - 38,
            "h": 145,
            "bgImg": s["img"]["popupBox"],
            "group": {
                "padding": [12, 12, 12, 0],
                "order": ["text"],
                "text": {
                    "padding": [6, 3, 8, 8],
                    "align": "center",
                    "w": WH_FILL,
                    "h": WH_FILL,
                    "font": _font(18),
                    "lineHeight": 17,
                    "line": [
                        {"font": _boldfont(18), "height": 17},
                    ],
                },
            },
        }

        # re-define waiting_popup text (it was defined above but Lua
        # re-defines it at this point in the file)
        s["waiting_popup"]["text"] = {
            "padding": [0, 29, 0, 0],
            "fg": c["TEXT_COLOR"],
            "sh": c["TEXT_SH_COLOR"],
            "align": "top",
            "position": LAYOUT_NORTH,
            "font": _font(c["POPUP_TEXT_SIZE_1"]),
        }
        s["waiting_popup"]["subtext"] = {
            "padding": [0, 0, 0, 34],
            "font": _boldfont(c["POPUP_TEXT_SIZE_2"]),
            "fg": c["TEXT_COLOR"],
            "sh": c["TEXT_SH_COLOR"],
            "align": "top",
            "position": LAYOUT_SOUTH,
            "w": WH_FILL,
        }
        s["waiting_popup"]["subtext_connected"] = _uses(
            s["waiting_popup"]["subtext"],
            {
                "fg": c["TEXT_COLOR_TEAL"],
            },
        )

        # toast_popup_mixed
        s["toast_popup_mixed"] = {
            "x": 19,
            "y": 16,
            "position": LAYOUT_NONE,
            "w": screen_width - 38,
            "h": 214,
            "bgImg": s["img"]["popupBox"],
            "text": {
                "position": LAYOUT_NORTH,
                "padding": [8, 24, 8, 0],
                "align": "top",
                "w": WH_FILL,
                "h": WH_FILL,
                "font": _boldfont(18),
                "fg": c["TEXT_COLOR"],
                "sh": c["TEXT_SH_COLOR"],
            },
            "subtext": {
                "position": LAYOUT_NORTH,
                "padding": [8, 178, 8, 0],
                "align": "top",
                "w": WH_FILL,
                "h": WH_FILL,
                "font": _boldfont(18),
                "fg": c["TEXT_COLOR"],
                "sh": c["TEXT_SH_COLOR"],
            },
        }

        # Badges
        s["_badge"] = {
            "position": LAYOUT_NONE,
            "zOrder": 99,
            "x": screen_width // 2 + 21,
            "w": 34,
            "y": 34,
        }
        s["badge_none"] = _uses(s["_badge"], {"img": False})
        s["badge_favorite"] = _uses(
            s["_badge"],
            {
                "img": _load_image("Icons/icon_badge_fav.png"),
            },
        )
        s["badge_add"] = _uses(
            s["_badge"],
            {
                "img": _load_image("Icons/icon_badge_add.png"),
            },
        )

        # toast without artwork
        s["toast_popup_text"] = _uses(s["toast_popup"])

        # toast popup with icon only
        s["toast_popup_icon"] = _uses(
            s["toast_popup"],
            {
                "w": 132,
                "h": 132,
                "x": 94,
                "y": 54,
                "position": LAYOUT_NONE,
                "group": {
                    "order": ["icon"],
                    "border": [26, 26, 0, 0],
                    "padding": 0,
                    "icon": {
                        "w": WH_FILL,
                        "h": WH_FILL,
                        "align": "center",
                    },
                },
            },
        )

        # ---------------------------------------------------------------
        # Context menu
        # ---------------------------------------------------------------
        s["context_menu"] = {
            "x": 10,
            "y": 10,
            "w": screen_width - 18,
            "h": screen_height - 17,
            "border": 0,
            "padding": 0,
            "bgImg": s["img"]["contextMenuBox"],
            "layer": LAYER_TITLE,
            "title": {
                "layer": LAYER_TITLE,
                "hidden": 1,
                "h": 0,
                "text": {"hidden": 1},
                "bgImg": False,
                "border": 0,
            },
            "multiline_text": {
                "w": WH_FILL,
                "h": screen_height - 27,
                "padding": [14, 18, 14, 18],
                "border": [0, 0, 6, 15],
                "lineHeight": 22,
                "font": _font(18),
                "fg": [0xE6, 0xE6, 0xE6],
                "sh": [],
                "align": "top-left",
                "scrollbar": {
                    "h": screen_height - 47,
                    "border": [0, 10, 2, 10],
                },
            },
            "menu": {
                "h": c["CM_MENU_HEIGHT"] * 5,
                "w": screen_width - 32,
                "x": 7,
                "y": 7,
                "border": 0,
                "itemHeight": c["CM_MENU_HEIGHT"],
                "position": LAYOUT_NORTH,
                "scrollbar": {
                    "h": c["CM_MENU_HEIGHT"] * 5 - 4,
                    "border": [0, 4, 0, 4],
                },
                "item": {
                    "h": c["CM_MENU_HEIGHT"],
                    "order": ["text", "arrow"],
                    "text": {
                        "w": WH_FILL,
                        "h": WH_FILL,
                        "align": "left",
                        "fg": c["TEXT_COLOR"],
                        "sh": c["TEXT_SH_COLOR"],
                        "font": _font(c["ALBUMMENU_SMALL_FONT_SIZE"]),
                        "line": [
                            {"font": _boldfont(18), "height": 20},
                            {"font": _font(14), "height": 18},
                        ],
                    },
                    "arrow": _uses(s["item"]["arrow"]),
                    "bgImg": False,
                },
                "item_no_arrow": {
                    "bgImg": False,
                },
                "selected": {
                    "item": {
                        "bgImg": s["img"]["contextMenuSelectionBox"],
                        "order": ["text", "arrow"],
                        "text": {
                            "w": WH_FILL,
                            "h": WH_FILL,
                            "align": "left",
                            "font": _boldfont(c["TEXTMENU_SELECTED_FONT_SIZE"]),
                            "fg": c["SELECT_COLOR"],
                            "sh": c["SELECT_SH_COLOR"],
                            "padding": [0, 2, 0, 0],
                            "line": [
                                {"font": _boldfont(21), "height": 23},
                                {"font": _font(14), "height": 14},
                            ],
                            "arrow": _uses(s["selected"]["item"]["arrow"]),
                        },
                    },
                },
                "locked": {
                    "item": {
                        "bgImg": s["img"]["contextMenuSelectionBox"],
                    },
                },
            },
        }

        s["context_menu"]["menu"]["item_play"] = _uses(
            s["context_menu"]["menu"]["item"], {"order": ["text"]}
        )
        s["context_menu"]["menu"]["selected"]["item_play"] = _uses(
            s["context_menu"]["menu"]["selected"]["item"], {"order": ["text"]}
        )

        s["context_menu"]["menu"]["item_no_arrow"] = _uses(
            s["context_menu"]["menu"]["item_play"]
        )
        s["context_menu"]["menu"]["selected"]["item_no_arrow"] = _uses(
            s["context_menu"]["menu"]["selected"]["item_play"]
        )

        # ---------------------------------------------------------------
        # Alarm header / popup
        # ---------------------------------------------------------------
        s["alarm_header"] = {
            "w": screen_width - 20,
            "order": ["time"],
            "time": {
                "h": WH_FILL,
                "w": WH_FILL,
            },
        }

        s["alarm_time"] = {
            "w": WH_FILL,
            "fg": c["TEXT_COLOR"],
            "sh": c["TEXT_SH_COLOR"],
            "align": "center",
            "font": _boldfont(92),
        }
        s["preview_text"] = _uses(
            s["alarm_time"],
            {
                "font": _boldfont(c["TITLE_FONT_SIZE"]),
            },
        )

        s["alarm_popup"] = {
            "x": 10,
            "y": 10,
            "w": screen_width - 20,
            "h": screen_height - 17,
            "border": 0,
            "padding": 0,
            "bgImg": s["img"]["contextMenuBox"],
            "maskImg": s["img"]["popupMask"],
            "layer": LAYER_TITLE,
            "title": {"hidden": 1},
            "menu": {
                "h": c["CM_MENU_HEIGHT"] * 5,
                "w": screen_width - 34,
                "x": 7,
                "y": 53,
                "border": 0,
                "itemHeight": c["CM_MENU_HEIGHT"],
                "position": LAYOUT_NORTH,
                "scrollbar": {
                    "h": c["CM_MENU_HEIGHT"] * 5 - 8,
                    "border": [0, 4, 0, 0],
                },
                "item": {
                    "h": c["CM_MENU_HEIGHT"],
                    "order": ["text", "arrow"],
                    "text": {
                        "w": WH_FILL,
                        "h": WH_FILL,
                        "align": "left",
                        "font": _boldfont(c["TEXTMENU_FONT_SIZE"]),
                        "fg": c["TEXT_COLOR"],
                        "sh": c["TEXT_SH_COLOR"],
                    },
                    "arrow": _uses(s["item"]["arrow"]),
                },
                "selected": {
                    "item": {
                        "bgImg": s["img"]["contextMenuSelectionBox"],
                        "order": ["text", "arrow"],
                        "text": {
                            "w": WH_FILL,
                            "h": WH_FILL,
                            "align": "left",
                            "font": _boldfont(c["TEXTMENU_SELECTED_FONT_SIZE"]),
                            "fg": c["TEXT_COLOR"],
                            "sh": c["TEXT_SH_COLOR"],
                        },
                        "arrow": _uses(s["item"]["arrow"]),
                    },
                },
            },
        }

        # slider popup (volume)
        s["slider_popup"] = {
            "x": 19,
            "y": 46,
            "w": screen_width - 38,
            "h": 145,
            "bgImg": s["img"]["popupBox"],
            "heading": {
                "w": WH_FILL,
                "align": "center",
                "padding": [4, 16, 4, 8],
                "font": _boldfont(c["TITLE_FONT_SIZE"]),
                "fg": c["TEXT_COLOR"],
            },
            "slider_group": {
                "w": WH_FILL,
                "align": "center",
                "border": [8, 2, 8, 0],
                "order": ["slider"],
            },
        }

        # scanner popup
        s["scanner_popup"] = _uses(
            s["slider_popup"],
            {
                "y": screen_height // 2 - 34,
                "h": 68,
                "heading": {
                    "padding": [4, 16, 4, 0],
                },
                "slider_group": {
                    "border": [8, 2, 8, 0],
                },
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

        # ---------------------------------------------------------------
        # SLIDERS
        # ---------------------------------------------------------------
        s["volume_slider"] = _uses(
            s["slider"],
            {
                "img": s["img"]["volumeBar"],
                "bgImg": s["img"]["volumeBackground"],
            },
        )

        s["scanner_slider"] = s["volume_slider"]

        # ---------------------------------------------------------------
        # ICONS
        # ---------------------------------------------------------------
        s["_icon"] = {
            "w": WH_FILL,
            "align": "center",
            "position": LAYOUT_CENTER,
            "padding": [0, 25, 0, 5],
        }

        s["icon_no_artwork"] = {
            "img": _load_image("IconsResized/icon_album_noart.png"),
            "w": c["THUMB_SIZE"],
            "h": c["THUMB_SIZE"],
        }

        s["icon_connecting"] = _uses(
            s["_icon"],
            {
                "img": _load_image("Alerts/wifi_connecting.png"),
                "frameRate": 8,
                "frameWidth": 120,
                "padding": [0, 25, 0, 5],
            },
        )

        s["icon_connected"] = _uses(
            s["icon_connecting"],
            {
                "img": _load_image("Alerts/connecting_success_icon.png"),
            },
        )

        s["icon_photo_loading"] = _uses(
            s["_icon"],
            {
                "img": _load_image("Icons/image_viewer_loading.png"),
                "padding": [5, 40, 0, 5],
            },
        )

        s["icon_software_update"] = _uses(
            s["_icon"],
            {
                "img": _load_image("IconsResized/icon_firmware_update.png"),
                "padding": [0, 0, 0, 44],
            },
        )

        s["icon_restart"] = _uses(
            s["_icon"],
            {
                "img": _load_image("IconsResized/icon_restart.png"),
            },
        )

        s["icon_power"] = _uses(
            s["_icon"],
            {
                "img": _load_image("Icons/icon_shut_down.png"),
                "padding": [0, 18, 0, 5],
            },
        )

        s["icon_battery_low"] = _uses(
            s["_icon"],
            {
                "padding": [0, 11, 0, 0],
                "img": _load_image("Icons/icon_popup_box_battery.png"),
            },
        )

        s["icon_locked"] = _uses(
            s["_icon"],
            {
                "img": _load_image("Icons/icon_locked.png"),
            },
        )

        s["icon_art"] = _uses(
            s["_icon"],
            {
                "padding": 0,
                "img": False,
            },
        )

        s["icon_linein"] = _uses(
            s["_icon"],
            {
                "img": _load_image("IconsResized/icon_linein_143.png"),
                "w": WH_FILL,
                "align": "center",
                "padding": [0, 66, 0, 0],
            },
        )

        s["icon_alarm"] = {
            "img": _load_image("Icons/icon_alarm.png"),
        }

        # Popup icons
        _popup_icon: Style = {
            "w": WH_FILL,
            "h": 70,
            "align": "center",
            "padding": 0,
        }

        s["icon_popup_volume"] = _uses(
            _popup_icon,
            {
                "img": _load_image("Icons/icon_popup_box_volume_bar.png"),
            },
        )
        s["icon_popup_mute"] = _uses(
            _popup_icon,
            {
                "img": _load_image("Icons/icon_popup_box_volume_mute.png"),
            },
        )

        _popup_sleep_base: Style = {
            "h": WH_FILL,
            "w": WH_FILL,
            "padding": [0, 8, 0, 0],
        }
        s["icon_popup_sleep_15"] = _uses(
            _popup_sleep_base,
            {
                "img": _load_image("Icons/icon_popup_box_sleep_15.png"),
            },
        )
        s["icon_popup_sleep_30"] = _uses(
            _popup_sleep_base,
            {
                "img": _load_image("Icons/icon_popup_box_sleep_30.png"),
            },
        )
        s["icon_popup_sleep_45"] = _uses(
            _popup_sleep_base,
            {
                "img": _load_image("Icons/icon_popup_box_sleep_45.png"),
            },
        )
        s["icon_popup_sleep_60"] = _uses(
            _popup_sleep_base,
            {
                "img": _load_image("Icons/icon_popup_box_sleep_60.png"),
            },
        )
        s["icon_popup_sleep_90"] = _uses(
            _popup_sleep_base,
            {
                "img": _load_image("Icons/icon_popup_box_sleep_90.png"),
            },
        )
        s["icon_popup_sleep_cancel"] = _uses(
            _popup_sleep_base,
            {
                "img": _load_image("Icons/icon_popup_box_sleep_off.png"),
            },
        )

        s["icon_popup_shuffle0"] = {
            "img": _load_image("Icons/icon_popup_box_shuffle_off.png"),
            "h": WH_FILL,
        }
        s["icon_popup_shuffle1"] = _uses(
            s["icon_popup_shuffle0"],
            {
                "img": _load_image("Icons/icon_popup_box_shuffle.png"),
            },
        )
        s["icon_popup_shuffle2"] = _uses(
            s["icon_popup_shuffle0"],
            {
                "img": _load_image("Icons/icon_popup_box_shuffle_album.png"),
            },
        )

        s["icon_popup_repeat0"] = _uses(
            s["icon_popup_shuffle0"],
            {
                "img": _load_image("Icons/icon_popup_box_repeat_off.png"),
            },
        )
        s["icon_popup_repeat1"] = _uses(
            s["icon_popup_shuffle0"],
            {
                "img": _load_image("Icons/icon_popup_box_repeat_song.png"),
            },
        )
        s["icon_popup_repeat2"] = _uses(
            s["icon_popup_shuffle0"],
            {
                "img": _load_image("Icons/icon_popup_box_repeat.png"),
            },
        )

        # Transport popup icons
        _popup_transport: Style = {
            "padding": [26, 26, 0, 0],
        }
        s["icon_popup_pause"] = _uses(
            _popup_transport,
            {
                "img": _load_image("Icons/icon_popup_box_pause.png"),
            },
        )
        s["icon_popup_play"] = _uses(
            _popup_transport,
            {
                "img": _load_image("Icons/icon_popup_box_play.png"),
            },
        )
        s["icon_popup_fwd"] = _uses(
            _popup_transport,
            {
                "img": _load_image("Icons/icon_popup_box_fwd.png"),
            },
        )
        s["icon_popup_rew"] = _uses(
            _popup_transport,
            {
                "img": _load_image("Icons/icon_popup_box_rew.png"),
            },
        )
        s["icon_popup_stop"] = _uses(
            _popup_transport,
            {
                "img": _load_image("Icons/icon_popup_box_stop.png"),
            },
        )
        s["icon_popup_lineIn"] = _uses(
            _popup_transport,
            {
                "img": _load_image("IconsResized/icon_linein_80.png"),
            },
        )

        # Preset pointers
        s["presetPointer3"] = {
            "w": WH_FILL,
            "h": WH_FILL,
            "position": LAYOUT_NONE,
            "x": 10,
            "y": screen_height - 46,
            "img": _load_image("UNOFFICIAL/preset3.png"),
        }
        s["presetPointer6"] = {
            "w": WH_FILL,
            "h": WH_FILL,
            "position": LAYOUT_NONE,
            "x": screen_width - 100,
            "y": screen_height - 46,
            "img": _load_image("UNOFFICIAL/preset6.png"),
        }

        # ---------------------------------------------------------------
        # Button icons (left of menus)
        # ---------------------------------------------------------------
        _buttonicon: Style = {
            "border": c["MENU_ITEM_ICON_PADDING"],
            "align": "center",
            "h": c["THUMB_SIZE"],
        }
        _selected_buttonicon: Style = {
            "border": c["SELECTED_MENU_ITEM_ICON_PADDING"],
            "align": "center",
            "h": c["THUMB_SIZE"],
        }

        s["region_US"] = _uses(
            _buttonicon,
            {
                "img": _load_image("IconsResized/icon_region_americas" + skin_suffix),
            },
        )
        s["region_XX"] = _uses(
            _buttonicon,
            {
                "img": _load_image("IconsResized/icon_region_other" + skin_suffix),
            },
        )
        s["icon_help"] = _uses(
            _buttonicon,
            {
                "img": _load_image("IconsResized/icon_help" + skin_suffix),
            },
        )

        # Player model icons
        _player_icons = {
            "player_transporter": "icon_transporter.png",
            "player_squeezebox": "icon_SB1n2.png",
            "player_squeezebox2": "icon_SB1n2.png",
            "player_squeezebox3": "icon_SB3.png",
            "player_boom": "icon_boom.png",
            "player_slimp3": "icon_slimp3.png",
            "player_softsqueeze": "icon_softsqueeze.png",
            "player_controller": "icon_controller.png",
            "player_receiver": "icon_receiver.png",
            "player_squeezeplay": "icon_squeezeplay.png",
            "player_fab4": "icon_fab4.png",
            "player_baby": "icon_baby.png",
            "player_http": "icon_tunein_url.png",
        }
        for style_name, icon_file in _player_icons.items():
            s[style_name] = _uses(
                _buttonicon,
                {
                    "img": _load_image("IconsResized/" + icon_file),
                },
            )

        # Home menu icons
        _hm_icons = {
            "hm_appletImageViewer": "icon_image_viewer",
            "hm_appletNowPlaying": "icon_nowplaying",
            "hm_eject": "icon_eject",
            "hm_usbdrive": "icon_device_USB",
            "hm_sdcard": "icon_device_SDcard",
            "hm_settings": "icon_settings",
            "hm_advancedSettings": "icon_settings_adv",
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
            "hm_settingsPlugin": "icon_settings_plugin",
        }
        for style_name, icon_base in _hm_icons.items():
            s[style_name] = _uses(
                _buttonicon,
                {
                    "img": _load_image("IconsResized/" + icon_base + skin_suffix),
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

        # ---------------------------------------------------------------
        # Wireless indicator icons (right of menus)
        # ---------------------------------------------------------------
        _indicator: Style = {
            "align": "right",
            "padding": [0, 0, 3, 0],
        }

        for level in range(5):
            key = f"wirelessLevel{level}"
            s[key] = _uses(
                _indicator,
                {
                    "img": _load_image(f"Icons/icon_wireless_{level}_off.png"),
                },
            )
            s["menu"]["selected"]["item"][key] = _uses(
                s[key],
                {
                    "img": _load_image(f"Icons/icon_wireless_{level}_sel.png"),
                    "padding": 0,
                },
            )

        # ---------------------------------------------------------------
        # ICONBAR
        # ---------------------------------------------------------------
        s["iconbar_icon_width"] = 24

        _iconbar_icon: Style = {
            "h": WH_FILL,
            "w": 24,
            "padding": [0, 3, 0, 0],
            "border": [5, 0, 5, 0],
            "layer": LAYER_FRAME,
            "position": LAYOUT_SOUTH,
        }

        # playmode
        _button_playmode = _uses(
            _iconbar_icon,
            {
                "border": [10, 0, 5, 0],
            },
        )
        s["button_playmode_OFF"] = _uses(_button_playmode, {"img": False})
        s["button_playmode_STOP"] = _uses(
            _button_playmode,
            {
                "img": _load_image("Icons/icon_mode_stop.png"),
            },
        )
        s["button_playmode_PLAY"] = _uses(
            _button_playmode,
            {
                "img": _load_image("Icons/icon_mode_play.png"),
            },
        )
        s["button_playmode_PAUSE"] = _uses(
            _button_playmode,
            {
                "img": _load_image("Icons/icon_mode_pause.png"),
            },
        )

        # repeat
        _button_repeat = _uses(_iconbar_icon)
        s["button_repeat_OFF"] = _uses(_button_repeat, {"img": False})
        s["button_repeat_0"] = _uses(_button_repeat, {"img": False})
        s["button_repeat_1"] = _uses(
            _button_repeat,
            {
                "img": _load_image("Icons/icon_repeat_song.png"),
            },
        )
        s["button_repeat_2"] = _uses(
            _button_repeat,
            {
                "img": _load_image("Icons/icon_repeat_on.png"),
            },
        )

        # shuffle
        _button_shuffle = _uses(_iconbar_icon)
        s["button_shuffle_OFF"] = _uses(_button_shuffle, {"img": False})
        s["button_shuffle_0"] = _uses(_button_shuffle, {"img": False})
        s["button_shuffle_1"] = _uses(
            _button_shuffle,
            {
                "img": _load_image("Icons/icon_shuffle_on.png"),
            },
        )
        s["button_shuffle_2"] = _uses(
            _button_shuffle,
            {
                "img": _load_image("Icons/icon_shuffle_album.png"),
            },
        )

        # alarm
        _button_alarm = _uses(
            _iconbar_icon,
            {
                "w": WH_FILL,
                "border": 0,
                "padding": [0, 2, 0, 0],
                "align": "right",
            },
        )
        s["button_alarm_OFF"] = _uses(_button_alarm, {"img": False})
        s["button_alarm_ON"] = _uses(
            _button_alarm,
            {
                "img": _load_image("Icons/icon_mode_alarm_on.png"),
            },
        )

        # battery
        _button_battery = _uses(
            _iconbar_icon,
            {
                "w": 24,
                "align": "center",
                "border": [5, 0, 5, 0],
            },
        )
        s["button_battery_AC"] = _uses(
            _button_battery,
            {
                "img": _load_image("Icons/icon_battery_AC.png"),
            },
        )
        s["button_battery_CHARGING"] = _uses(
            _button_battery,
            {
                "img": _load_image("Icons/icon_battery_charging.png"),
                "frameRate": 1,
                "frameWidth": 24,
            },
        )
        for level in range(5):
            s[f"button_battery_{level}"] = _uses(
                _button_battery,
                {
                    "img": _load_image(f"Icons/icon_battery_{level}.png"),
                },
            )
        s["button_battery_NONE"] = _uses(_button_battery, {"img": False})

        # sleep
        s["button_sleep_ON"] = _uses(
            _iconbar_icon,
            {
                "img": _load_image("Icons/icon_mode_sleep_on.png"),
            },
        )
        s["button_sleep_OFF"] = _uses(
            s["button_sleep_ON"],
            {
                "img": False,
            },
        )

        # wireless
        _button_wireless = _uses(
            _iconbar_icon,
            {
                "w": 16,
                "border": [5, 0, 10, 0],
            },
        )
        for level in range(1, 5):
            s[f"button_wireless_{level}"] = _uses(
                _button_wireless,
                {
                    "img": _load_image(f"Icons/icon_wireless_{level}.png"),
                },
            )
        s["button_wireless_ERROR"] = _uses(
            _button_wireless,
            {
                "img": _load_image("Icons/icon_wireless_disabled.png"),
            },
        )
        s["button_wireless_SERVERERROR"] = _uses(
            _button_wireless,
            {
                "img": _load_image("Icons/icon_wireless_disabled.png"),
            },
        )
        s["button_wireless_NONE"] = _uses(_button_wireless, {"img": False})

        # ethernet
        s["button_ethernet"] = _uses(
            _button_wireless,
            {
                "img": _load_image("Icons/icon_ethernet.png"),
            },
        )
        s["button_ethernet_ERROR"] = _uses(
            _button_wireless,
            {
                "img": _load_image("Icons/icon_ethernet_disabled.png"),
            },
        )
        s["button_ethernet_SERVERERROR"] = _uses(
            _button_wireless,
            {
                "img": _load_image("Icons/icon_ethernet_disabled.png"),
            },
        )

        # time
        s["button_time"] = {
            "w": WH_FILL,
            "h": 24,
            "align": "center",
            "layer": LAYER_FRAME,
            "position": LAYOUT_SOUTH,
            "fg": c["TEXT_COLOR"],
            "zOrder": 101,
            "font": _boldfont(c["ICONBAR_FONT"]),
        }

        # iconbar group
        s["iconbar_group"] = {
            "x": 0,
            "y": screen_height - 24,
            "w": WH_FILL,
            "h": 24,
            "border": 0,
            "zOrder": 100,
            "bgImg": s["img"]["iconBackground"],
            "layer": LAYER_FRAME,
            "position": LAYOUT_SOUTH,
            "order": [
                "play",
                "repeat_mode",
                "shuffle",
                "alarm",
                "sleep",
                "battery",
                "wireless",
            ],
        }

        # demo text
        s["demo_text"] = {
            "h": 50,
            "font": _boldfont(14),
            "position": LAYOUT_SOUTH,
            "w": screen_width,
            "align": "center",
            "padding": [6, 0, 6, 10],
            "fg": c["TEXT_COLOR"],
            "sh": c["TEXT_SH_COLOR"],
        }

        s["keyboard"] = {"hidden": 1}

        s["debug_canvas"] = {
            "zOrder": 9999,
        }

        return s

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def free(self) -> bool:
        """Free resources held by the skin applet."""
        self.images = {}
        return True
