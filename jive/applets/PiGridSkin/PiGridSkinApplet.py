"""
jive.applets.PiGridSkin.PiGridSkinApplet --- PiGridSkin applet.

Ported from ``share/jive/applets/PiGridSkin/PiGridSkinApplet.lua``
(~640 LOC) in the original jivelite project.

This applet implements an 800x480 resolution skin with a grid layout.
It inherits most of its code from JogglerSkin and overrides icon list
and home menu styles to display items in a grid format.

Key implementation notes
------------------------

* Inherits the complete Joggler skin via
  ``JogglerSkinApplet.skin()``, then applies grid-specific
  overrides (home_menu grid, icon_list grid, icon sizes, etc.).

* Default screen size is 800x480.

* Supports multiple resolution variants:
  - 800x480   (default)
  - 1024x600
  - 1280x800
  - 1366x768
  - Custom    (via JL_SCREEN_WIDTH / JL_SCREEN_HEIGHT env vars)

Version 1.1 (25th January 2017) Michael Herger

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
    Optional,
    Sequence,
    Tuple,
)

from jive.applets.JogglerSkin.JogglerSkinApplet import (
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
    JogglerSkinApplet,
    Style,
    _boldfont,
    _font,
    _uses,
)
from jive.utils.log import logger

__all__ = ["PiGridSkinApplet"]

log = logger("applet.PiGridSkin")

# ---------------------------------------------------------------------------
# Image path prefixes
# ---------------------------------------------------------------------------
_IMGPATH = "applets/PiGridSkin/images/"
_BASE_IMGPATH = "applets/JogglerSkin/images/"
_FONTPATH = "fonts/"
_FONT_NAME = "FreeSans"
_BOLD_PREFIX = "Bold"


# ---------------------------------------------------------------------------
# Lazy image/tile loaders (same pattern as JogglerSkinApplet)
# ---------------------------------------------------------------------------


def _img(path: str) -> Style:
    """Return a lazy-loadable image reference."""
    return {"__type__": "image", "path": path}


def _load_image(file: str) -> Style:
    """Return a lazy reference to an image in the PiGridSkin images dir."""
    return _img(_IMGPATH + file)


def _load_base_image(file: str) -> Style:
    """Return a lazy reference to an image in the JogglerSkin images dir."""
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


def _tile_9patch(paths: Sequence[Optional[str]]) -> Style:
    """Return a lazy-loadable 9-patch tile reference."""
    return {"__type__": "tile_9patch", "paths": list(paths)}


def _fill_color(color: int) -> Style:
    """Return a lazy-loadable fill-colour tile reference."""
    return {"__type__": "tile_fill", "color": color}


# ============================================================================
# PiGridSkinApplet
# ============================================================================


class PiGridSkinApplet(JogglerSkinApplet):
    """Grid skin applet for 800x480 landscape displays (Raspberry Pi, etc.).

    Inherits the complete Joggler skin and overrides styles to provide
    a grid layout for the home menu and icon lists.
    """

    def __init__(self) -> None:
        super().__init__()
        self.images: Style = {}

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
        """Return skin parameter constants for the PiGrid skin.

        Inherits from JogglerSkin but overrides THUMB_SIZE for the grid
        layout.
        """
        params = super().param()

        params["THUMB_SIZE"] = 100
        params["THUMB_SIZE_MENU"] = 100
        params["THUMB_SIZE_LINEAR"] = 40
        params["THUMB_SIZE_PLAYLIST"] = 40

        return params

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
        """Populate *s* with grid-specific style overrides.

        Parameters
        ----------
        s:
            The style dict to populate.
        reload:
            ``True`` when the skin is being reloaded (not first load).
        use_default_size:
            ``True`` to use the default 800x480 screen size instead of
            querying the framework.
        w:
            Optional explicit screen width.
        h:
            Optional explicit screen height.

        Returns
        -------
        Style
            The populated style dict *s*.
        """
        # Almost all styles come directly from JogglerSkinApplet
        JogglerSkinApplet.skin(self, s, reload, use_default_size, w, h)

        screen_width, screen_height = self._get_screen_size()
        if w is not None and h is not None:
            screen_width, screen_height = w, h

        # c is for constants
        c = s["CONSTANTS"]

        # Skin suffix for image loading
        skin_suffix = c.get("skinSuffix", ".png")

        # Grid item selection box (9-patch tile)
        gridItemSelectionBox = _tile_9patch(
            [
                _IMGPATH + "grid_list/button_titlebar.png",
                _IMGPATH + "grid_list/button_titlebar_tl.png",
                _IMGPATH + "grid_list/button_titlebar_t.png",
                _IMGPATH + "grid_list/button_titlebar_tr.png",
                _IMGPATH + "grid_list/button_titlebar_r.png",
                _IMGPATH + "grid_list/button_titlebar_br.png",
                _IMGPATH + "grid_list/button_titlebar_b.png",
                _IMGPATH + "grid_list/button_titlebar_bl.png",
                _IMGPATH + "grid_list/button_titlebar_l.png",
            ]
        )

        THUMB_SIZE_G = self.param()["THUMB_SIZE"]
        THUMB_SIZE_L = self.param().get("THUMB_SIZE_LINEAR", 40)

        # Alternatives for grid view
        ALBUMMENU_FONT_SIZE_G = 18
        ALBUMMENU_SMALL_FONT_SIZE_G = 16
        MENU_ITEM_ICON_PADDING_G = [0, 0, 0, 0]
        GRID_ITEM_HEIGHT = 174  # defined by artwork assets used to "select" items

        ITEMS_PER_LINE = int(screen_width / 160)

        smallSpinny = c.get("smallSpinny", False)

        # --------- DEFAULT WIDGET STYLES ---------
        TITLE_HEIGHT = c.get("TITLE_HEIGHT", 55)
        FIVE_ITEM_HEIGHT = c.get("FIVE_ITEM_HEIGHT", 73)
        s["menu"]["h"] = (
            math.floor((screen_height - TITLE_HEIGHT) / FIVE_ITEM_HEIGHT)
            * FIVE_ITEM_HEIGHT
        )

        # Grid item base style
        itemG = {
            "order": ["icon", "text"],
            "orientation": 1,
            "padding": [8, 4, 8, 0],
            "text": {
                "padding": [0, 2, 0, 4],
                "align": "center",
                "w": WH_FILL,
                "h": WH_FILL,
                "font": _boldfont(28),
                "fg": c.get("TEXT_COLOR", [0xE7, 0xE7, 0xE7]),
                "sh": c.get("TEXT_SH_COLOR", [0x37, 0x37, 0x37]),
            },
            "icon": {
                "padding": MENU_ITEM_ICON_PADDING_G,
                "align": "center",
            },
            "bgImg": False,
        }

        # --------- WINDOW STYLES ---------
        loading_icon = _load_image("IconsResized/icon_loading" + skin_suffix)

        s["home_menu"] = _uses(
            s["text_list"],
            {
                "menu": {
                    "itemHeight": GRID_ITEM_HEIGHT,
                    "itemsPerLine": ITEMS_PER_LINE,
                    "item": _uses(
                        itemG,
                        {
                            "icon": {
                                "img": loading_icon,
                            },
                        },
                    ),
                    "item_play": _uses(
                        itemG,
                        {
                            "icon": {
                                "img": loading_icon,
                            },
                        },
                    ),
                    "item_add": _uses(
                        itemG,
                        {
                            "icon": {
                                "img": loading_icon,
                            },
                        },
                    ),
                    "item_choice": _uses(
                        itemG,
                        {
                            "order": ["icon", "text", "check"],
                            "text": {
                                "padding": [0, 0, 0, 0],
                            },
                            "choice": {
                                "padding": [0, 0, 0, 0],
                                "align": "center",
                                "font": _boldfont(ALBUMMENU_SMALL_FONT_SIZE_G),
                                "fg": c.get("TEXT_COLOR", [0xE7, 0xE7, 0xE7]),
                                "sh": c.get("TEXT_SH_COLOR", [0x37, 0x37, 0x37]),
                            },
                            "icon": {
                                "img": loading_icon,
                            },
                        },
                    ),
                    "pressed": {
                        "item": _uses(
                            itemG,
                            {
                                "icon": {
                                    "img": loading_icon,
                                },
                            },
                        ),
                    },
                    "selected": {
                        "item": _uses(
                            itemG,
                            {
                                "icon": {
                                    "img": loading_icon,
                                },
                                "bgImg": gridItemSelectionBox,
                            },
                        ),
                    },
                    "locked": {
                        "item": _uses(
                            itemG,
                            {
                                "icon": {
                                    "img": loading_icon,
                                },
                            },
                        ),
                    },
                },
            },
        )

        s["home_menu"]["menu"]["item"]["text"]["font"] = _boldfont(
            ALBUMMENU_FONT_SIZE_G
        )

        s["home_menu"]["menu"]["selected"] = {
            "item": _uses(
                s["home_menu"]["menu"]["item"],
                {
                    "bgImg": gridItemSelectionBox,
                },
            ),
            "item_choice": _uses(
                s["home_menu"]["menu"]["item_choice"],
                {
                    "bgImg": gridItemSelectionBox,
                },
            ),
            "item_play": _uses(
                s["home_menu"]["menu"]["item_play"],
                {
                    "bgImg": gridItemSelectionBox,
                },
            ),
            "item_add": _uses(
                s["home_menu"]["menu"]["item_add"],
                {
                    "bgImg": gridItemSelectionBox,
                },
            ),
        }

        s["home_menu"]["menu"]["locked"] = s["home_menu"]["menu"]["selected"]
        s["home_menu"]["menu"]["pressed"] = s["home_menu"]["menu"]["selected"]

        s["home_menu"]["menu"]["item"]["icon_no_artwork"] = {
            "img": loading_icon,
            "h": THUMB_SIZE_G,
            "padding": c.get("MENU_ITEM_ICON_PADDING", [0, 0, 0, 0]),
            "align": "center",
        }
        s["home_menu"]["menu"]["selected"]["item"]["icon_no_artwork"] = s["home_menu"][
            "menu"
        ]["item"]["icon_no_artwork"]
        s["home_menu"]["menu"]["locked"]["item"]["icon_no_artwork"] = s["home_menu"][
            "menu"
        ]["item"]["icon_no_artwork"]

        # icon_list Grid
        s["icon_listG"] = _uses(
            s["window"],
            {
                "menu": {
                    "itemsPerLine": ITEMS_PER_LINE,
                    "itemHeight": GRID_ITEM_HEIGHT,
                    "item": _uses(
                        itemG,
                        {
                            "text": {
                                "font": _font(ALBUMMENU_SMALL_FONT_SIZE_G),
                                "line": [
                                    {
                                        "font": _boldfont(ALBUMMENU_FONT_SIZE_G),
                                        "height": int(ALBUMMENU_FONT_SIZE_G * 1.3),
                                    },
                                    {
                                        "font": _font(ALBUMMENU_SMALL_FONT_SIZE_G),
                                    },
                                ],
                            },
                        },
                    ),
                },
            },
        )

        s["icon_listG"]["menu"]["item_checked"] = _uses(
            s["icon_listG"]["menu"]["item"],
            {
                "order": ["icon", "text", "check", "arrow"],
                "check": {
                    "align": c.get("ITEM_ICON_ALIGN", "center"),
                    "padding": c.get("CHECK_PADDING", [0, 0, 0, 0]),
                },
            },
        )
        s["icon_listG"]["menu"]["item_play"] = _uses(
            s["icon_listG"]["menu"]["item"],
            {
                "arrow": {"img": False},
            },
        )
        s["icon_listG"]["menu"]["albumcurrent"] = _uses(
            s["icon_listG"]["menu"]["item_play"],
            {
                "arrow": {"img": False},
            },
        )
        s["icon_listG"]["menu"]["item_add"] = _uses(
            s["icon_listG"]["menu"]["item"],
            {
                "arrow": c.get("addArrow", {"img": False}),
            },
        )
        s["icon_listG"]["menu"]["item_no_arrow"] = _uses(
            s["icon_listG"]["menu"]["item"],
            {
                "order": ["icon", "text"],
            },
        )
        s["icon_listG"]["menu"]["item_checked_no_arrow"] = _uses(
            s["icon_listG"]["menu"]["item_checked"],
            {
                "order": ["icon", "text", "check"],
            },
        )

        s["icon_listG"]["menu"]["selected"] = {
            "item": _uses(
                s["icon_listG"]["menu"]["item"],
                {"bgImg": gridItemSelectionBox},
            ),
            "albumcurrent": _uses(
                s["icon_listG"]["menu"]["albumcurrent"],
                {"bgImg": gridItemSelectionBox},
            ),
            "item_checked": _uses(
                s["icon_listG"]["menu"]["item_checked"],
                {"bgImg": gridItemSelectionBox},
            ),
            "item_play": _uses(
                s["icon_listG"]["menu"]["item_play"],
                {"bgImg": gridItemSelectionBox},
            ),
            "item_add": _uses(
                s["icon_listG"]["menu"]["item_add"],
                {"bgImg": gridItemSelectionBox},
            ),
            "item_no_arrow": _uses(
                s["icon_listG"]["menu"]["item_no_arrow"],
                {"bgImg": gridItemSelectionBox},
            ),
            "item_checked_no_arrow": _uses(
                s["icon_listG"]["menu"]["item_checked_no_arrow"],
                {"bgImg": gridItemSelectionBox},
            ),
        }

        s["icon_listG"]["menu"]["pressed"] = {
            "item": _uses(
                s["icon_listG"]["menu"]["item"],
                {"bgImg": gridItemSelectionBox},
            ),
            "albumcurrent": _uses(
                s["icon_listG"]["menu"]["albumcurrent"],
                {"bgImg": gridItemSelectionBox},
            ),
            "item_checked": _uses(
                s["icon_listG"]["menu"]["item_checked"],
                {"bgImg": gridItemSelectionBox},
            ),
            "item_play": _uses(
                s["icon_listG"]["menu"]["item_play"],
                {"bgImg": gridItemSelectionBox},
            ),
            "item_add": _uses(
                s["icon_listG"]["menu"]["item_add"],
                {"bgImg": gridItemSelectionBox},
            ),
            "item_no_arrow": _uses(
                s["icon_listG"]["menu"]["item_no_arrow"],
                {"bgImg": gridItemSelectionBox},
            ),
            "item_checked_no_arrow": _uses(
                s["icon_listG"]["menu"]["item_checked_no_arrow"],
                {"bgImg": gridItemSelectionBox},
            ),
        }

        s["icon_listG"]["menu"]["locked"] = {
            "item": _uses(
                s["icon_listG"]["menu"]["pressed"]["item"],
                {"arrow": smallSpinny},
            ),
            "item_checked": _uses(
                s["icon_listG"]["menu"]["pressed"]["item_checked"],
                {"arrow": smallSpinny},
            ),
            "item_play": _uses(
                s["icon_listG"]["menu"]["pressed"]["item_play"],
                {"arrow": smallSpinny},
            ),
            "item_add": _uses(
                s["icon_listG"]["menu"]["pressed"]["item_add"],
                {"arrow": smallSpinny},
            ),
            "albumcurrent": _uses(
                s["icon_listG"]["menu"]["pressed"]["albumcurrent"],
                {"arrow": smallSpinny},
            ),
        }

        # choose player window is exactly the same as text_list on all windows
        # except WQVGAlarge — grid view isn't great for players since player
        # names would be cut off
        s["choose_player"] = _uses(s["icon_list"])

        s["icon_list"] = _uses(s["icon_listG"])

        s["track_list"]["title"]["icon"]["w"] = THUMB_SIZE_L

        _buttonicon = {
            "h": THUMB_SIZE_G,
            "padding": MENU_ITEM_ICON_PADDING_G,
            "align": "center",
            "img": False,
        }

        # Region and misc icons
        s["region_US"] = _uses(
            _buttonicon,
            {"img": _load_image("IconsResized/icon_region_americas" + skin_suffix)},
        )
        s["region_XX"] = _uses(
            _buttonicon,
            {"img": _load_image("IconsResized/icon_region_other" + skin_suffix)},
        )
        s["icon_help"] = _uses(
            _buttonicon,
            {"img": _load_image("IconsResized/icon_help" + skin_suffix)},
        )
        s["wlan"] = _uses(
            _buttonicon,
            {"img": _load_image("IconsResized/icon_wireless" + skin_suffix)},
        )
        s["wired"] = _uses(
            _buttonicon,
            {"img": _load_image("IconsResized/icon_ethernet" + skin_suffix)},
        )

        # --------- ICONS --------
        no_artwork_iconG = _load_image("IconsResized/icon_album_noart" + skin_suffix)
        no_artwork_iconL = _load_image("IconsResized/icon_album_noart" + skin_suffix)

        # Icon for albums with no artwork
        s["icon_no_artwork"] = {
            "img": no_artwork_iconG,
            "h": THUMB_SIZE_G,
            "padding": MENU_ITEM_ICON_PADDING_G,
            "align": "center",
        }

        # Alternative small artwork for playlists
        s["icon_no_artwork_playlist"] = {
            "img": no_artwork_iconL,
            "h": THUMB_SIZE_L,
            "padding": c.get("MENU_ITEM_ICON_PADDING", [0, 0, 0, 0]),
            "align": "center",
        }

        # Misc home menu icons
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
                    "img": _load_image("IconsResized/" + icon_name + skin_suffix),
                },
            )

        # Aliases
        s["hm__myMusic"] = _uses(s["hm_myMusic"])
        s["hm_otherLibrary"] = _uses(
            _buttonicon,
            {
                "img": _load_image("IconsResized/icon_ml_other_library" + skin_suffix),
            },
        )
        s["hm_myMusicSelector"] = _uses(s["hm_myMusic"])

        # Search aliases
        s["hm_myMusicSearchArtists"] = _uses(s["hm_myMusicSearch"])
        s["hm_myMusicSearchAlbums"] = _uses(s["hm_myMusicSearch"])
        s["hm_myMusicSearchSongs"] = _uses(s["hm_myMusicSearch"])
        s["hm_myMusicSearchPlaylists"] = _uses(s["hm_myMusicSearch"])
        s["hm_myMusicSearchRecent"] = _uses(s["hm_myMusicSearch"])
        s["hm_homeSearchRecent"] = _uses(s["hm_myMusicSearch"])
        s["hm_globalSearch"] = _uses(s["hm_myMusicSearch"])

        return s

    # ------------------------------------------------------------------
    # Resolution variant methods
    # ------------------------------------------------------------------

    def skin1024x600(
        self,
        s: Style,
        reload: bool = False,
        use_default_size: bool = False,
    ) -> Style:
        """Skin variant for 1024x600 displays."""
        return self.skin(s, reload, use_default_size, w=1024, h=600)

    def skin1280x800(  # type: ignore[override]
        self,
        s: Style,
        reload: bool = False,
        use_default_size: bool = False,
    ) -> Style:
        """Skin variant for 1280x800 displays."""
        return self.skin(s, reload, use_default_size, w=1280, h=800)

    def skin1366x768(
        self,
        s: Style,
        reload: bool = False,
        use_default_size: bool = False,
    ) -> Style:
        """Skin variant for 1366x768 displays."""
        return self.skin(s, reload, use_default_size, w=1366, h=768)

    def skinCustom(
        self,
        s: Style,
        reload: bool = False,
        use_default_size: bool = False,
    ) -> Style:
        """Skin variant for custom screen sizes (via env vars)."""
        import os

        screen_width = 800
        screen_height = 480
        try:
            screen_width = int(os.environ.get("JL_SCREEN_WIDTH", "800"))
        except (ValueError, TypeError) as exc:
            log.debug("skinCustom: failed to parse JL_SCREEN_WIDTH: %s", exc)
        try:
            screen_height = int(os.environ.get("JL_SCREEN_HEIGHT", "480"))
        except (ValueError, TypeError) as exc:
            log.debug("skinCustom: failed to parse JL_SCREEN_HEIGHT: %s", exc)

        return self.skin(s, reload, use_default_size, w=screen_width, h=screen_height)

    # ------------------------------------------------------------------
    # free
    # ------------------------------------------------------------------

    def free(self) -> bool:
        """Free resources held by the skin applet."""
        try:
            from jive.jive_main import jive_main as _jm

            if _jm is not None:
                _jm.remove_item_by_id("npButtonSelector")
        except (ImportError, AttributeError) as exc:
            log.debug("free: failed to remove npButtonSelector: %s", exc)

        self.images = {}
        self.imageTiles = {}
        self.hTiles = {}
        self.vTiles = {}
        self.tiles = {}
        return True
