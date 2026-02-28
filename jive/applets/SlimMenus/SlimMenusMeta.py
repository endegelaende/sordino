"""
applets.SlimMenus.SlimMenusMeta — SlimMenus meta-info.

Ported from ``applets/SlimMenus/SlimMenusMeta.lua`` in the original
jivelite Lua project.

SlimMenus is responsible for managing server-driven home-menu items
pushed from LMS via the ``menustatus`` Comet subscription and the
``menu`` JSON-RPC command.

The meta class registers public services, adds the "My Music" and
"Switch Library" menu items to the home screen, and eagerly loads
the SlimMenus applet (it is a resident applet).

Services registered:

- ``goHome`` — navigate to the home screen
- ``hideConnectingToPlayer`` — dismiss the "connecting" popup
- ``warnOnAnyNetworkFailure`` — check network before an action

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from jive.applet_meta import AppletMeta
from jive.utils.log import logger

log = logger("applet.SlimMenus")

__all__ = ["SlimMenusMeta"]


class SlimMenusMeta(AppletMeta):
    """Meta-info for the SlimMenus applet."""

    # ------------------------------------------------------------------
    # AppletMeta interface
    # ------------------------------------------------------------------

    def jive_version(self) -> tuple[int, int]:
        """Minimum and maximum supported Jive version."""
        return (1, 1)

    # Lua alias
    jiveVersion = jive_version

    def default_settings(self) -> Dict[str, Any]:
        """Return the default settings dict for SlimMenus.

        SlimMenus does not persist any settings of its own in the Lua
        original, so we return an empty dict.
        """
        return {}

    # Lua alias
    defaultSettings = default_settings

    def register_applet(self) -> None:
        """Register services and add home-menu items.

        Mirrors the Lua ``registerApplet`` which:

        1. Registers three services (``goHome``,
           ``hideConnectingToPlayer``, ``warnOnAnyNetworkFailure``).
        2. Adds the "My Music" selector to the home menu.
        3. Adds the "Switch Library" item under ``_myMusic``.
        4. Eagerly loads the SlimMenus applet (resident).
        """

        # ── Services ─────────────────────────────────────────────────
        self.register_service("goHome")
        self.register_service("hideConnectingToPlayer")
        self.register_service("warnOnAnyNetworkFailure")

        # ── Home-menu items ──────────────────────────────────────────
        jive_main = self._get_jive_main()

        if jive_main is not None:
            # "My Music" top-level entry
            my_music_item = self.menu_item(
                "myMusicSelector",
                "home",
                "MENUS_MY_MUSIC",
                lambda applet, *args: applet.myMusicSelector(*args),
                weight=2,
                extras={"id": "hm_myMusicSelector"},
            )
            jive_main.add_item(my_music_item)

            # "Switch Library" under _myMusic node
            other_library_item = self.menu_item(
                "otherLibrary",
                "_myMusic",
                "MENUS_OTHER_LIBRARY",
                lambda applet, *args: applet.otherLibrarySelector(*args),
                weight=100,
                extras={"id": "hm_otherLibrary"},
            )
            jive_main.add_item(other_library_item)

        # ── Eager load (resident applet) ─────────────────────────────
        mgr = self._get_applet_manager()
        if mgr is not None:
            try:
                mgr.load_applet("SlimMenus")
            except Exception as exc:
                log.error("Failed to eagerly load SlimMenus: %s", exc)

    # Lua alias
    registerApplet = register_applet

    # ------------------------------------------------------------------
    # Menu-item builder helper
    # ------------------------------------------------------------------

    def menu_item(
        self,
        item_id: str,
        node: str,
        text_token: str,
        callback: Any = None,
        weight: int = 50,
        extras: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Build a home-menu item dict.

        Parameters
        ----------
        item_id:
            Unique identifier for the menu item.
        node:
            Parent node in the menu tree (e.g. ``"home"``).
        text_token:
            Localisation token.  If a strings table is available
            the token is resolved; otherwise the raw token is used.
        callback:
            Callable ``callback(applet, ...)`` invoked when the user
            selects the item.
        weight:
            Sort weight (lower = higher in the menu).
        extras:
            Additional keys merged into the item dict.

        Returns
        -------
        dict
            A menu-item dict suitable for ``jiveMain.add_item()``.
        """
        # Resolve localised text
        text = text_token
        strings_table = getattr(self, "_strings_table", None)
        if strings_table is not None:
            try:
                resolved = strings_table.str(text_token)
                if resolved:
                    text = resolved
            except Exception:
                pass

        item: Dict[str, Any] = {
            "id": item_id,
            "node": node,
            "text": text,
            "weight": weight,
            "sound": "WINDOWSHOW",
        }

        if callback is not None:
            item["callback"] = callback

        icon_style = f"hm_{item_id}"
        item["iconStyle"] = icon_style

        if extras:
            item.update(extras)

        return item

    # Lua alias
    menuItem = menu_item

    # ------------------------------------------------------------------
    # Accessor helpers
    # ------------------------------------------------------------------

    def _get_applet_manager(self) -> Any:
        """Return the AppletManager, if available."""
        # The meta may have a back-reference set by the manager
        mgr = getattr(self, "_applet_manager", None)
        if mgr is not None:
            return mgr
        try:
            from jive.jive_main import jive_main as _jm

            if _jm is not None:
                return getattr(_jm, "applet_manager", None)
        except ImportError:
            pass
        return None

    def _get_jive_main(self) -> Any:
        """Return the JiveMain singleton, if available."""
        try:
            from jive.jive_main import jive_main as _jm

            return _jm
        except ImportError:
            return None

    def _get_jnt(self) -> Any:
        """Return the notification hub / network thread, if available."""
        try:
            from jive.jive_main import jive_main as _jm

            if _jm is not None:
                return getattr(_jm, "jnt", None)
        except ImportError:
            pass
        return None
