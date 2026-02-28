"""
jive.applets.now_playing.now_playing_meta — Meta class for NowPlaying.

Ported from ``share/jive/applets/NowPlaying/NowPlayingMeta.lua`` (~72 LOC)
in the original jivelite project.

NowPlaying is the screen that displays the currently playing track with
artwork, transport controls, progress bar, and volume slider.  Its Meta
class:

* Declares version compatibility (1, 1)
* Provides default settings for scroll behaviour and views
* Registers menu items for scroll mode and NP views settings
* Registers services: ``goNowPlaying``, ``hideNowPlaying``
* Adds NowPlaying as a screensaver via ``addScreenSaver`` service
* Loads the applet immediately (resident applet)

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from jive.applet_meta import AppletMeta
from jive.utils.log import logger

__all__ = ["NowPlayingMeta"]

log = logger("applet.NowPlaying")


class NowPlayingMeta(AppletMeta):
    """Meta-information for the NowPlaying applet.

    Registers screensaver functionality, scroll-mode and NP-views
    settings menu items, and the ``goNowPlaying`` / ``hideNowPlaying``
    services.  NowPlaying is a resident applet that is loaded
    immediately during ``configure_applet()``.
    """

    # ------------------------------------------------------------------
    # Required overrides
    # ------------------------------------------------------------------

    def jive_version(self) -> Tuple[int, int]:
        """Return ``(min_version, max_version)`` of Jive supported."""
        return (1, 1)

    def default_settings(self) -> Optional[Dict[str, Any]]:
        """Return default settings for NowPlaying.

        Settings include:

        * ``scrollText`` — whether to scroll track/artist text (True)
        * ``scrollTextOnce`` — scroll once then stop (False)
        * ``views`` — dict of style → enabled (empty = all enabled)
        """
        return {
            "scrollText": True,
            "scrollTextOnce": False,
            "views": {},
        }

    def register_applet(self) -> None:
        """Register NowPlaying menu items and services.

        Adds two settings menu items under ``screenSettingsNowPlaying``:

        1. **Scroll Mode** — choose default scrolling, scroll-once,
           or no-scroll for track info text.
        2. **Now Playing Views** — choose which NP screen layouts
           (art+text, large art, art only, text only, spectrum, VU)
           are available for cycling.

        Also registers the ``goNowPlaying`` and ``hideNowPlaying``
        services so other applets can navigate to / hide NP.
        """
        jive_main = self._get_jive_main()

        if jive_main is not None:
            # Scroll mode settings menu item
            jive_main.add_item(
                self.menu_item(
                    "appletNowPlayingScrollMode",
                    "screenSettingsNowPlaying",
                    "SCREENSAVER_SCROLLMODE",
                    lambda applet, *args, **kwargs: applet.scroll_settings_show(
                        *args, **kwargs
                    ),
                )
            )

            # NP views settings menu item
            jive_main.add_item(
                self.menu_item(
                    "appletNowPlayingViewsSettings",
                    "screenSettingsNowPlaying",
                    "NOW_PLAYING_VIEWS",
                    lambda applet, *args, **kwargs: applet.npviews_settings_show(
                        *args, **kwargs
                    ),
                )
            )

        # Register services
        self.register_service("goNowPlaying")
        self.register_service("hideNowPlaying")

    def configure_applet(self) -> None:
        """Configure NowPlaying as a screensaver and load it.

        Registers NowPlaying as a screensaver with priority 10 and
        the ``whenOff`` flag, then loads the applet immediately since
        it is a resident applet.
        """
        # Register as a screensaver
        applet_manager = self._get_applet_manager()
        if applet_manager is not None:
            applet_manager.call_service(
                "addScreenSaver",
                str(self.string("SCREENSAVER_NOWPLAYING")),  # display name
                "NowPlaying",  # applet name
                "openScreensaver",  # method name
                None,  # _
                None,  # _
                10,  # priority
                None,  # _
                None,  # _
                None,  # _
                ["whenOff"],  # flags
            )

            # NowPlaying is a resident applet — load immediately
            applet_manager.load_applet("NowPlaying")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_jive_main() -> Any:
        """Try to obtain the JiveMain singleton.

        Returns ``None`` if not yet initialised.
        """
        try:
            from jive.jive_main import jive_main as _jm

            return _jm
        except (ImportError, AttributeError):
            pass

        # Fallback: check for a module-level variable
        try:
            import jive.jive_main as _jm_mod

            return getattr(_jm_mod, "jive_main", None)
        except ImportError:
            return None

    @staticmethod
    def _get_applet_manager() -> Any:
        """Try to obtain the AppletManager singleton.

        Returns ``None`` if not yet initialised.
        """
        try:
            from jive.applet_manager import applet_manager

            return applet_manager
        except (ImportError, AttributeError):
            return None
