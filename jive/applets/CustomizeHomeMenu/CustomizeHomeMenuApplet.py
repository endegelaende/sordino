"""
jive.applets.CustomizeHomeMenu.CustomizeHomeMenuApplet — Home menu customization.

Ported from ``share/jive/applets/CustomizeHomeMenu/CustomizeHomeMenuApplet.lua``
in the original jivelite project.

This applet allows users to:

* Show/hide menu items from the home menu
* Reorder menu items (up, down, to top, to bottom)
* Restore individual hidden items
* Restore all defaults

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from jive.applet import Applet
from jive.utils.log import logger

__all__ = ["CustomizeHomeMenuApplet"]

log = logger("applet.CustomizeHomeMenu")


class CustomizeHomeMenuApplet(Applet):
    """Home menu customization applet."""

    def __init__(self) -> None:
        super().__init__()

    # ------------------------------------------------------------------
    # Main settings menu
    # ------------------------------------------------------------------

    def menu(self, menu_item: Any = None) -> None:
        """Show the customization settings menu."""
        log.info("menu")

        try:
            from jive.ui.constants import EVENT_CONSUME
            from jive.ui.simplemenu import SimpleMenu
            from jive.ui.textarea import Textarea
            from jive.ui.window import Window
        except ImportError as exc:
            log.warn("UI modules not available: %s", exc)
            return

        menu = SimpleMenu("menu")

        menu.addItem(
            {
                "text": self.string("GLOBAL_HELP"),
                "callback": lambda: self.helpWindow(),
            }
        )

        menu.addItem(
            {
                "text": self.string("CUSTOMIZE_RESTORE_DEFAULTS"),
                "callback": lambda: self.restoreDefaultsMenu(),
            }
        )

        menu.addItem(
            {
                "text": self.string("RESTORE_HIDDEN_ITEMS"),
                "callback": lambda: self.restoreHiddenItemMenu(),
            }
        )

        help_text = Textarea("help_text", self.string("CUSTOMIZE_HOME_HELP"))
        menu.setHeaderWidget(help_text)  # type: ignore[attr-defined]

        window = Window("text_list", self.string("CUSTOMIZE_HOME"))
        window.add_widget(menu)
        window.show()

    # ------------------------------------------------------------------
    # Help window
    # ------------------------------------------------------------------

    def helpWindow(self) -> None:
        """Show help text."""
        try:
            from jive.ui.textarea import Textarea
            from jive.ui.window import Window
        except ImportError:
            return

        help_text = Textarea(
            "help_text", self.string("CUSTOMIZE_HOME_MORE_HELP")
        )
        window = Window("information", self.string("CUSTOMIZE_HOME"))
        window.add_widget(help_text)
        window.show()

    # Lua-compatible alias
    help_window = helpWindow

    # ------------------------------------------------------------------
    # Context menu on home menu items (service entry point)
    # ------------------------------------------------------------------

    def homeMenuItemContextMenu(self, item: Dict[str, Any]) -> None:
        """Show context menu for a home menu item.

        This is the service entry point registered as
        ``homeMenuItemContextMenu``.
        """
        try:
            from jive.ui.constants import EVENT_CONSUME
            from jive.ui.contextmenuwindow import ContextMenuWindow
            from jive.ui.simplemenu import SimpleMenu
            from jive.ui.window import Window
        except ImportError as exc:
            log.warn("UI modules not available: %s", exc)
            return

        jive_main = self._get_jive_main()
        mgr = self._get_applet_manager()
        if jive_main is None:
            return

        window = ContextMenuWindow(item.get("text", ""))
        menu = SimpleMenu("menu")

        # Cancel item
        menu.addItem(
            {
                "text": self.string("CUSTOMIZE_CANCEL"),
                "sound": "WINDOWHIDE",
                "callback": lambda: (window.hide(), EVENT_CONSUME)[-1],  # type: ignore[func-returns-value]
            }
        )

        settings = self.get_settings()
        if settings is None:
            settings = {"_nodes": {}}
            self.set_settings(settings)

        # Determine the effective item for add/remove operations
        the_item = item
        custom_home_item = None
        hidden_custom_home_item = False

        if item.get("node") != "home":
            hm_id = "hm_" + item.get("id", "")
            custom_home_item = jive_main.get_node_item_by_id(hm_id, "home")
            if custom_home_item is None:
                custom_home_item = jive_main.get_node_item_by_id(
                    hm_id, "hidden"
                )
                if custom_home_item is not None:
                    hidden_custom_home_item = True

        if custom_home_item is not None:
            the_item = custom_home_item

        # Add/Remove/Hide actions
        item_id = item.get("id", "")
        the_item_id = the_item.get("id", "")

        if item.get("noCustom") and item.get("node") == "home":
            menu.addItem(
                {
                    "text": self.string("ITEM_CANNOT_BE_HIDDEN"),
                    "callback": lambda: (window.hide(), EVENT_CONSUME)[-1],  # type: ignore[func-returns-value]
                }
            )
        elif (
            item.get("node") == "home"
            or settings.get(item_id) == "home"
            or (custom_home_item is not None and not hidden_custom_home_item)
        ):
            # Remove from home / hide
            def _remove_from_home(
                _ti: Dict[str, Any] = the_item,
            ) -> int:
                if _ti.get("node") == "home":
                    self._timed_exec(
                        lambda: self._do_set_node_hidden(_ti)
                    )
                else:
                    self._timed_exec(
                        lambda: self._do_remove_from_node(_ti)
                    )
                window.hide()
                return int(EVENT_CONSUME)

            menu.addItem(
                {
                    "text": self.string("REMOVE_FROM_HOME"),
                    "callback": _remove_from_home,
                }
            )
        else:
            # Add to home
            def _add_to_home(
                _ti: Dict[str, Any] = the_item,
            ) -> int:
                settings[_ti.get("id", "")] = "home"
                _ti["node"] = "home"
                home_item = jive_main.add_item_to_node(_ti, "home")
                if home_item is not None:
                    jive_main.item_to_bottom(home_item, "home")
                window.hide()
                self._store_settings("home")

                self._timed_exec(
                    lambda: self._go_home_and_select(
                        _ti.get("id", "")
                    )
                )
                return int(EVENT_CONSUME)

            menu.addItem(
                {
                    "text": self.string("ADD_TO_HOME"),
                    "callback": _add_to_home,
                }
            )

        # Determine current node for reorder operations
        node = "home"
        try:
            from jive.ui.framework import framework

            if (
                framework is not None
                and hasattr(framework, "window_stack")
                and len(framework.window_stack) > 1
            ):
                node = item.get("node", "home")
        except (ImportError, AttributeError) as exc:
            log.warning("homeMenuItemContextMenu: failed to determine node from framework: %s", exc)

        node_menu = jive_main.get_node_menu(node)
        item_idx = 0
        menu_size = 0
        if node_menu is not None:
            if hasattr(node_menu, "getIdIndex"):
                item_idx = node_menu.getIdIndex(item_id) or 0
            elif hasattr(node_menu, "get_id_index"):
                item_idx = node_menu.get_id_index(item_id) or 0
            if hasattr(node_menu, "items"):
                menu_size = len(node_menu.items)

        if item_idx > 1:
            menu.addItem(
                {
                    "text": self.string("MOVE_UP_ONE"),
                    "callback": lambda: self._move_action(
                        window, jive_main.item_up_one, item, node
                    ),
                }
            )

        if item_idx < menu_size:
            menu.addItem(
                {
                    "text": self.string("MOVE_DOWN_ONE"),
                    "callback": lambda: self._move_action(
                        window, jive_main.item_down_one, item, node
                    ),
                }
            )

        if item_idx > 1:
            menu.addItem(
                {
                    "text": self.string("MOVE_TO_TOP"),
                    "callback": lambda: self._move_action(
                        window, jive_main.item_to_top, item, node
                    ),
                }
            )

        if item_idx < menu_size:
            menu.addItem(
                {
                    "text": self.string("MOVE_TO_BOTTOM"),
                    "callback": lambda: self._move_action(
                        window, jive_main.item_to_bottom, item, node
                    ),
                }
            )

        window.add_widget(menu)
        window.show(Window.transitionFadeIn)

    # Lua-compatible alias
    home_menu_item_context_menu = homeMenuItemContextMenu

    # ------------------------------------------------------------------
    # Restore hidden items
    # ------------------------------------------------------------------

    def restoreHiddenItemMenu(self, menu_item: Any = None) -> None:
        """Show menu of hidden items that can be restored."""
        try:
            from jive.ui.constants import EVENT_CONSUME
            from jive.ui.simplemenu import SimpleMenu
            from jive.ui.textarea import Textarea
            from jive.ui.window import Window
        except ImportError:
            return

        jive_main = self._get_jive_main()
        mgr = self._get_applet_manager()
        if jive_main is None:
            return

        settings = self.get_settings()
        if settings is None:
            settings = {"_nodes": {}}
            self.set_settings(settings)

        window = Window("home_menu", self.string("RESTORE_HIDDEN_ITEMS"))
        menu = SimpleMenu("menu")
        menu_table = jive_main.get_menu_table()
        at_least_one = False

        for item_id, item in menu_table.items():
            if settings.get(item_id) == "hidden":
                at_least_one = True
                _item = item  # capture

                def _restore_callback(_it: Dict[str, Any] = _item) -> int:
                    if mgr is not None:
                        mgr.call_service("goHome")
                    self._timed_exec(
                        lambda: self._do_restore_item(_it), 500
                    )
                    return int(EVENT_CONSUME)

                menu.addItem(
                    {
                        "text": item.get("text", item_id),
                        "iconStyle": item.get("iconStyle"),
                        "callback": _restore_callback,
                    }
                )

        help_text = Textarea(
            "help_text", self.string("RESTORE_HIDDEN_ITEMS_HELP")
        )

        if not at_least_one:
            window = Window(
                "text_list", self.string("RESTORE_HIDDEN_ITEMS")
            )
            help_text = Textarea(
                "help_text", self.string("NO_HIDDEN_ITEMS")
            )
            menu.addItem(
                {
                    "text": self.string("CUSTOMIZE_CANCEL"),
                    "callback": lambda: (
                        window.hide(Window.transitionPushRight),  # type: ignore[func-returns-value]
                        EVENT_CONSUME,
                    )[-1],
                }
            )

        menu.setHeaderWidget(help_text)  # type: ignore[attr-defined]
        window.add_widget(menu)
        window.show()

    # Lua-compatible alias
    restore_hidden_item_menu = restoreHiddenItemMenu

    # ------------------------------------------------------------------
    # Restore defaults
    # ------------------------------------------------------------------

    def restoreDefaultsMenu(self, menu_item: Any = None) -> None:
        """Show confirmation menu for restoring all defaults."""
        try:
            from jive.ui.constants import EVENT_CONSUME
            from jive.ui.simplemenu import SimpleMenu
            from jive.ui.textarea import Textarea
            from jive.ui.window import Window
        except ImportError:
            return

        jive_main = self._get_jive_main()
        mgr = self._get_applet_manager()
        if jive_main is None:
            return

        window = Window(
            "help_list",
            self.string("CUSTOMIZE_RESTORE_DEFAULTS"),
            "settingstitle",
        )

        def _cancel() -> int:
            window.hide()
            return int(EVENT_CONSUME)

        def _continue() -> int:
            self._do_restore_defaults(jive_main, mgr)
            return int(EVENT_CONSUME)

        menu = SimpleMenu(
            "menu",
            [
                {
                    "text": self.string("CUSTOMIZE_CANCEL"),
                    "sound": "WINDOWHIDE",
                    "callback": _cancel,
                },
                {
                    "text": self.string("CUSTOMIZE_CONTINUE"),
                    "sound": "WINDOWSHOW",
                    "callback": _continue,
                },
            ],
        )

        menu.setHeaderWidget(  # type: ignore[attr-defined]
            Textarea(
                "help_text",
                self.string("CUSTOMIZE_RESTORE_DEFAULTS_HELP"),
            )
        )
        window.add_widget(menu)
        window.show()

    # Lua-compatible alias
    restore_defaults_menu = restoreDefaultsMenu

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _do_set_node_hidden(self, item: Dict[str, Any]) -> None:
        """Move an item to the 'hidden' node."""
        jive_main = self._get_jive_main()
        if jive_main is not None:
            jive_main.set_node(item, "hidden")
        settings = self.get_settings()
        if settings is not None:
            settings[item.get("id", "")] = "hidden"
        self._store_settings("home")

    def _do_remove_from_node(self, item: Dict[str, Any]) -> None:
        """Remove a custom item from a node."""
        jive_main = self._get_jive_main()
        settings = self.get_settings()
        if settings is not None:
            settings.pop(item.get("id", ""), None)
        if jive_main is not None:
            jive_main.remove_item_from_node(item, "home")
        self._store_settings("home")

    def _do_restore_item(self, item: Dict[str, Any]) -> None:
        """Restore a hidden item to the home menu."""
        jive_main = self._get_jive_main()
        if jive_main is None:
            return

        settings = self.get_settings()
        if settings is not None:
            settings[item.get("id", "")] = "home"
        jive_main.add_item_to_node(item, "home")
        self._store_settings("home")

        # Select the restored item
        home_menu = jive_main.get_node_menu("home")
        if home_menu is not None:
            idx = None
            if hasattr(home_menu, "getIdIndex"):
                idx = home_menu.getIdIndex(item.get("id", ""))
            elif hasattr(home_menu, "get_id_index"):
                idx = home_menu.get_id_index(item.get("id", ""))
            if idx is not None:
                if hasattr(home_menu, "setSelectedIndex"):
                    home_menu.setSelectedIndex(idx)
                elif hasattr(home_menu, "set_selected_index"):
                    home_menu.set_selected_index(idx)

    def _do_restore_defaults(self, jive_main: Any, mgr: Any) -> None:
        """Restore all menu customizations to defaults."""
        try:
            from jive.ui.simplemenu import SimpleMenu
        except ImportError:
            return

        settings = self.get_settings()
        if settings is None:
            return

        keys_to_remove = []
        for item_id, value in settings.items():
            if item_id == "_nodes":
                # Reset node ordering
                if isinstance(value, dict):
                    for node, item_list in value.items():
                        menu = jive_main.get_node_menu(node)
                        if menu is not None:
                            log.info("resorting %s by weight/alpha", node)
                            comparator = getattr(
                                SimpleMenu, "itemComparatorWeightAlpha", None
                            ) or getattr(
                                SimpleMenu,
                                "item_comparator_weight_alpha",
                                None,
                            )
                            if comparator is not None:
                                menu.set_comparator(comparator)
                settings["_nodes"] = {}
            else:
                keys_to_remove.append(item_id)
                # Restore item to its original node
                item = jive_main.get_menu_item(item_id)
                if item is not None:
                    jive_main.set_node(item, item.get("node", "home"))

        for k in keys_to_remove:
            settings.pop(k, None)

        self.store_settings()

        if mgr is not None:
            mgr.call_service("goHome")

    def _go_home_and_select(self, item_id: str) -> None:
        """Navigate home and select a specific item."""
        mgr = self._get_applet_manager()
        jive_main = self._get_jive_main()
        if mgr is not None:
            mgr.call_service("goHome")
        if jive_main is not None:
            home_menu = jive_main.get_node_menu("home")
            if home_menu is not None:
                idx = None
                if hasattr(home_menu, "getIdIndex"):
                    idx = home_menu.getIdIndex(item_id)
                elif hasattr(home_menu, "get_id_index"):
                    idx = home_menu.get_id_index(item_id)
                if idx is not None:
                    if hasattr(home_menu, "setSelectedIndex"):
                        home_menu.setSelectedIndex(idx)
                    elif hasattr(home_menu, "set_selected_index"):
                        home_menu.set_selected_index(idx)

    def _move_action(
        self,
        window: Any,
        move_fn: Callable[..., Any],
        item: Dict[str, Any],
        node: str,
    ) -> int:
        """Execute a move action with delayed execution."""
        from jive.ui.constants import EVENT_CONSUME

        window.hide()
        self._timed_exec(
            lambda: (move_fn(item, node), self._store_settings(node))  # type: ignore[func-returns-value]
        )
        return int(EVENT_CONSUME)

    def _timed_exec(
        self, func: Callable[[], Any], delay: int = 350
    ) -> None:
        """Execute a function after a short delay for visual effect."""
        try:
            from jive.ui.timer import Timer

            timer = Timer(delay, func, True)
            timer.start()
        except ImportError:
            # Fallback: execute immediately
            func()

    def _store_settings(self, node: Optional[str] = None) -> None:
        """Persist the current menu item ordering for a node."""
        if node is None:
            return

        jive_main = self._get_jive_main()
        if jive_main is None:
            return

        node_menu = jive_main.get_node_menu(node)
        if node_menu is None:
            log.error("no menu found for %s", node)
            return

        menu_items: List[str] = []
        if hasattr(node_menu, "items"):
            for item in node_menu.items:
                if isinstance(item, dict):
                    item_id = item.get("id")
                    if item_id is not None:
                        menu_items.append(item_id)

        settings = self.get_settings()
        if settings is None:
            settings = {"_nodes": {}}
            self.set_settings(settings)
        if "_nodes" not in settings:
            settings["_nodes"] = {}

        settings["_nodes"][node] = menu_items
        self.store_settings()

    # ------------------------------------------------------------------
    # Singleton accessors
    # ------------------------------------------------------------------

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

    @staticmethod
    def _get_applet_manager() -> Any:
        try:
            from jive.applet_manager import applet_manager
            return applet_manager
        except (ImportError, AttributeError):
            return None
