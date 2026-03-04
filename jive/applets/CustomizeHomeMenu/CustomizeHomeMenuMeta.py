"""
jive.applets.CustomizeHomeMenu.CustomizeHomeMenuMeta — Meta class.

Ported from ``share/jive/applets/CustomizeHomeMenu/CustomizeHomeMenuMeta.lua``
in the original jivelite project.

The Meta class:

* Declares version compatibility (1, 1)
* Provides default settings with empty ``_nodes`` dict
* Restores custom node assignments from persisted settings
* Registers the ``homeMenuItemContextMenu`` service
* Adds a "Home Menu" item under ``settings``

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from jive.applet_meta import AppletMeta
from jive.utils.log import logger

__all__ = ["CustomizeHomeMenuMeta"]

log = logger("applet.CustomizeHomeMenu")


class CustomizeHomeMenuMeta(AppletMeta):
    """Meta-information for the CustomizeHomeMenu applet."""

    def jive_version(self) -> Tuple[int, int]:
        return (1, 1)

    def default_settings(self) -> Optional[Dict[str, Any]]:
        return {"_nodes": {}}

    def configure_applet(self) -> None:
        """Register service and subscribe to notifications.

        Called after all applets have been registered so that
        cross-applet services are available.
        """
        jnt = self._get_jnt()
        if jnt is not None:
            jnt.subscribe(self)
        self.register_service("homeMenuItemContextMenu")

    def register_applet(self) -> None:
        """Restore custom nodes and add settings menu item."""
        settings = self.get_settings()
        jive_main = self._get_jive_main()

        if settings and jive_main is not None:
            for item_id, node in settings.items():
                if item_id == "_nodes":
                    continue
                if isinstance(node, str):
                    try:
                        jive_main.set_custom_node(item_id, node)
                    except Exception as exc:
                        log.debug(
                            "Failed to restore custom node %s→%s: %s",
                            item_id,
                            node,
                            exc,
                        )

        if jive_main is not None:
            jive_main.add_item(
                self.menu_item(
                    id="appletCustomizeHome",
                    node="settings",
                    label="CUSTOMIZE_HOME",
                    closure=lambda applet, menu_item: applet.menu(menu_item),
                    weight=55,
                    icon_style="hm_appletCustomizeHome",
                )
            )

    def notify_playerLoaded(self, player: Any) -> None:
        """Rank menu items after player data is loaded.

        This ensures the home menu and sub-menus are sorted by rank
        rather than weight/alpha once the server has populated them.
        """
        log.debug("notify_playerLoaded(): %s", player)

        jive_main = self._get_jive_main()
        if jive_main is None:
            return

        try:
            from jive.ui.simplemenu import SimpleMenu
        except ImportError:
            return

        # Rank all nodes
        node_table = jive_main.get_node_table()
        for node in node_table:
            jive_main.rank_menu_items(node)
            menu = jive_main.get_node_menu(node)
            if menu is not None:
                comparator = getattr(
                    SimpleMenu, "itemComparatorRank", None
                ) or getattr(SimpleMenu, "item_comparator_rank", None)
                if comparator is not None:
                    menu.set_comparator(comparator)

        # Apply stored node ordering
        settings = self.get_settings()
        if settings and settings.get("_nodes"):
            for node, item_ids in settings["_nodes"].items():
                if not isinstance(item_ids, list):
                    continue
                for i, item_id in enumerate(item_ids):
                    item = jive_main.get_node_item_by_id(item_id, node)
                    if item is not None:
                        jive_main.set_rank(item, i + 1)
                menu = jive_main.get_node_menu(node)
                if menu is not None:
                    comparator = getattr(
                        SimpleMenu, "itemComparatorRank", None
                    ) or getattr(SimpleMenu, "item_comparator_rank", None)
                    if comparator is not None:
                        menu.set_comparator(comparator)
                jive_main.rank_menu_items(node)
        else:
            # Create _nodes if missing
            if settings is None:
                settings = self.default_settings() or {}
                self._settings = settings
            if "_nodes" not in settings:
                settings["_nodes"] = {}
                self.store_settings()

    # Lua-compatible alias
    notify_player_loaded = notify_playerLoaded

    # ------------------------------------------------------------------
    # Singleton accessors
    # ------------------------------------------------------------------

    @staticmethod
    def _get_jnt() -> Any:
        try:
            from jive.jive_main import jive_main as _jm
            if _jm is not None:
                return getattr(_jm, "jnt", None)
        except ImportError as exc:
            log.debug("_get_jnt: jive_main not importable: %s", exc)
        return None

    @staticmethod
    def _get_jive_main() -> Any:
        try:
            from jive.jive_main import jive_main
            return jive_main
        except (ImportError, AttributeError) as exc:
            log.debug("_get_jive_main: jive_main not available: %s", exc)
        try:
            import jive.jive_main as _mod
            return getattr(_mod, "jive_main", None)
        except ImportError:
            return None
