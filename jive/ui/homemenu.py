"""
jive.ui.homemenu — HomeMenu widget for the Jivelite Python3 port.

Ported from ``jive/ui/HomeMenu.lua`` in the original jivelite project.

The HomeMenu is the top-level application menu that manages a tree of
menu nodes.  Applets register themselves into the HomeMenu via
:meth:`add_item` (leaf items) and :meth:`add_node` (sub-menu nodes).

Key concepts:

* **Nodes** — Sub-menus that contain items.  Each node has its own
  :class:`SimpleMenu` and :class:`Window`.  The root node is ``"home"``.
* **Items** — Leaf entries in a node's menu.  Each item is a dict with
  at minimum ``id`` and ``node`` keys.
* **Custom nodes** — Items can be moved to a different node at runtime
  (e.g. by ``CustomizeHomeMenuApplet``), stored in ``custom_nodes``.
* **Ranking** — Items can be manually re-ordered within a node via
  :meth:`item_up_one`, :meth:`item_down_one`, :meth:`item_to_top`,
  :meth:`item_to_bottom`.
* **Weight** — Items are sorted by ``weight`` (lower first), then
  alphabetically.  Items moved to the home node from sub-nodes use
  a complex weight (dot-separated segments).

The HomeMenu window cannot be closed (the ``back`` action bumps
instead of popping).

Usage::

    from jive.ui.homemenu import HomeMenu

    hm = HomeMenu("My Player")

    # Register a sub-menu node
    hm.add_node({
        "id": "settings",
        "node": "home",
        "text": "Settings",
        "weight": 50,
    })

    # Register a menu item
    hm.add_item({
        "id": "settings_audio",
        "node": "settings",
        "text": "Audio Settings",
        "weight": 10,
        "callback": lambda event, item: open_audio_settings(),
    })

    # Show the home menu
    hm.window.show()

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Copyright 2013-2014 Adrian Smith (jivelite amendments)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    Iterator,
    List,
    Optional,
    Tuple,
    Union,
)

from jive.ui.constants import (
    EVENT_CONSUME,
    EVENT_UNUSED,
    EVENT_WINDOW_ACTIVE,
    EVENT_WINDOW_INACTIVE,
)
from jive.ui.icon import Icon
from jive.ui.simplemenu import SimpleMenu
from jive.ui.window import Window
from jive.utils.log import logger
from jive.utils.string_utils import split as str_split

if TYPE_CHECKING:
    from jive.ui.event import Event

__all__ = ["HomeMenu"]

log = logger("jivelite.ui")


# ---------------------------------------------------------------------------
# Type alias for menu-item dicts
# ---------------------------------------------------------------------------

MenuItemDict = Dict[str, Any]


# ---------------------------------------------------------------------------
# Helper: prototype-chain inheritance for item dicts
# ---------------------------------------------------------------------------


def _uses(parent: MenuItemDict, value: Optional[MenuItemDict] = None) -> MenuItemDict:
    """
    Create a new item dict that inherits from *parent*.

    This mirrors the Lua ``_uses`` helper which creates a table with
    ``__index`` pointing to *parent*.  In Python we copy the parent
    dict and overlay *value*.

    Sub-dicts are recursively merged (not replaced).

    Parameters
    ----------
    parent : dict
        The prototype item to inherit from.
    value : dict, optional
        Overrides to apply on top of *parent*.

    Returns
    -------
    dict
        A new dict combining *parent* and *value*.
    """
    item: MenuItemDict = dict(parent)

    for k, v in (value or {}).items():
        if isinstance(v, dict) and isinstance(parent.get(k), dict):
            item[k] = _uses(parent[k], v)
        else:
            item[k] = v

    return item


# ---------------------------------------------------------------------------
# HomeMenu
# ---------------------------------------------------------------------------


class HomeMenu:
    """
    The applet-driven home menu.

    Manages a tree of menu nodes rooted at ``"home"``.  Applets add
    items and nodes via :meth:`add_item` and :meth:`add_node`.

    Parameters
    ----------
    name : str
        The title displayed in the home window's title bar.
    style : str, optional
        Window style key.  Defaults to ``"home_menu"``.
    title_style : str, optional
        Title style key (reserved for future use).
    """

    def __init__(
        self,
        name: str,
        style: Optional[str] = None,
        title_style: Optional[str] = None,
    ) -> None:
        self.window: Window = Window(style or "home_menu", name)
        self.window_title: str = name

        # id → item dict   (all registered items)
        self.menu_table: Dict[str, MenuItemDict] = {}

        # node-id → { "menu": SimpleMenu, "item": item-dict-or-None, "items": {id: item} }
        self.node_table: Dict[str, Dict[str, Any]] = {}

        # id → custom-copy of item (items copied into the home node)
        self.custom_menu_table: Dict[str, MenuItemDict] = {}

        # id → node-id   (custom node overrides)
        self.custom_nodes: Dict[str, str] = {}

        # --- Root "home" node ---
        menu = SimpleMenu("menu")
        menu.set_comparator(SimpleMenu.itemComparatorComplexWeightAlpha)
        menu.set_closeable(False)

        self.window.add_widget(menu)
        self.node_table["home"] = {
            "menu": menu,
            "item": None,
            "items": {},
        }

        # Prevent quitting via "back" — bump instead
        self.window.add_action_listener("back", self, _bump_action)

        # "go_home" scrolls to root if already at home, else lets
        # the standard action handler take over
        self.window.add_action_listener("go_home", self, _home_root_handler)
        self.window.add_action_listener(
            "go_home_or_now_playing", self, _home_root_handler
        )

        # Power button mapping (delayed to avoid accidental activation)
        self.window.set_button_action(
            "lbutton",
            "home_title_left_press",
            "home_title_left_hold",
            "soft_reset",
            delayed=True,
        )

        # EVENT_WINDOW_ACTIVE / INACTIVE listeners for button-action
        # timing.  In the Lua original these manage the lbutton mapping
        # around power-button logic.  Here we replicate the structure
        # but the actual power-management is a no-op until the full
        # applet system is ported.

        home_menu_self = self

        def _on_active(event: Event) -> int:
            from jive.ui.framework import framework as fw

            translation = fw.get_action_to_action_translation("home_title_left_press")
            if translation == "power":
                home_menu_self.window.add_timer(
                    1000,
                    lambda: home_menu_self.window.set_button_action(
                        "lbutton",
                        "home_title_left_press",
                        "home_title_left_hold",
                        "soft_reset",
                        delayed=True,
                    ),
                    once=True,
                )
            else:
                home_menu_self.window.set_button_action(
                    "lbutton",
                    "home_title_left_press",
                    "home_title_left_hold",
                    "soft_reset",
                    delayed=True,
                )
            return int(EVENT_UNUSED)

        def _on_inactive(event: Event) -> int:
            from jive.ui.framework import framework as fw

            translation = fw.get_action_to_action_translation("home_title_left_press")
            if translation == "power":
                home_menu_self.window.set_button_action("lbutton", None)
            return int(EVENT_UNUSED)

        self.window.add_listener(int(EVENT_WINDOW_ACTIVE), _on_active)
        self.window.add_listener(int(EVENT_WINDOW_INACTIVE), _on_inactive)

    # ------------------------------------------------------------------
    # Item accessors
    # ------------------------------------------------------------------

    def get_menu_item(self, item_id: str) -> Optional[MenuItemDict]:
        """Return the item dict for *item_id*, or ``None``."""
        return self.menu_table.get(item_id)

    getMenuItem = get_menu_item

    def get_menu_table(self) -> Dict[str, MenuItemDict]:
        """Return the full menu table (id → item)."""
        return self.menu_table

    getMenuTable = get_menu_table

    def get_node_table(self) -> Dict[str, Dict[str, Any]]:
        """Return the full node table (node-id → entry)."""
        return self.node_table

    getNodeTable = get_node_table

    def get_node_text(self, node: str) -> Optional[str]:
        """
        Return the display text for *node*, or ``None`` if unavailable.
        """
        assert node is not None
        entry = self.node_table.get(node)
        if (
            entry is not None
            and entry.get("item") is not None
            and entry["item"].get("text") is not None
        ):
            return str(entry["item"]["text"])
        return None

    getNodeText = get_node_text

    def exists(self, item_id: str) -> bool:
        """Return ``True`` if *item_id* is registered in the menu table."""
        return item_id in self.menu_table

    def is_menu_item(self, item_id: str) -> bool:
        """
        Return ``True`` if *item_id* is in either the menu table or the
        node table.
        """
        return item_id in self.menu_table or item_id in self.node_table

    isMenuItem = is_menu_item

    # ------------------------------------------------------------------
    # Complex weight
    # ------------------------------------------------------------------

    def get_complex_weight(
        self, item_id: str, item: MenuItemDict
    ) -> Union[int, float, str]:
        """
        Compute a complex (hierarchical) weight for *item*.

        For items directly in the ``"home"`` node, this is simply the
        item's ``weight``.  For items in sub-nodes, the weight is a
        dot-separated string of the parent chain's weights.

        Items in the ``"hidden"`` node use ``hiddenWeight`` if present,
        otherwise default to 100.

        Parameters
        ----------
        item_id : str
            The item's ``id``.
        item : dict
            The item dict (must have a ``weight`` key).

        Returns
        -------
        int, float, or str
            The weight value.  May be a dot-separated string for
            hierarchical weights (e.g. ``"50.10"``).
        """
        entry = self.menu_table.get(item_id)
        if entry is None:
            return item.get("weight", 100)  # type: ignore[no-any-return]

        node = entry.get("node", "home")

        if node == "home":
            return item.get("weight", 100)  # type: ignore[no-any-return]

        if node == "hidden":
            return entry.get("hiddenWeight", 100)  # type: ignore[no-any-return]

        # Recurse up the node chain
        node_item = self.menu_table.get(node)
        if node_item is None:
            log.warn(
                "when trying to analyze %s, its node, %s, is not "
                "currently in the menuTable thus no way to establish "
                "a complex weight for sorting",
                item.get("text", "?"),
                node,
            )
            return item.get("weight", 100)  # type: ignore[no-any-return]

        parent_weight = self.get_complex_weight(node, node_item)
        return f"{parent_weight}.{item.get('weight', 100)}"

    getComplexWeight = get_complex_weight

    # ------------------------------------------------------------------
    # Ranking (manual re-ordering)
    # ------------------------------------------------------------------

    @staticmethod
    def set_rank(item: MenuItemDict, rank: int) -> None:
        """Set the manual rank on *item*."""
        log.debug(
            "setting rank for %s from %s to %s",
            item.get("id", "?"),
            item.get("rank"),
            rank,
        )
        item["rank"] = rank

    setRank = set_rank

    @staticmethod
    def get_weight(item: MenuItemDict) -> Any:
        """Return the weight of *item*."""
        return item.get("weight", 100)

    getWeight = get_weight

    def get_node_menu(self, node: str) -> Optional[SimpleMenu]:
        """
        Return the :class:`SimpleMenu` for *node*, or ``None`` if
        not found.
        """
        entry = self.node_table.get(node)
        if entry is None:
            log.error("no menu object found for %s", node)
            return None
        menu = entry.get("menu")
        if menu is None:
            log.error("no menu object found for %s", node)
            return None
        return menu  # type: ignore[no-any-return]

    getNodeMenu = get_node_menu

    def rank_menu_items(self, node: str) -> None:
        """
        Assign sequential ranks 1..N to all items in *node*'s menu.

        After ranking, the menu's comparator is set to rank-based
        sorting so that items appear in their assigned order.
        """
        if not self.node_table or node not in self.node_table:
            log.error("rankMenuItems not given proper args")
            return

        menu = self.get_node_menu(node)
        if menu is None:
            return

        rank = 1
        for item in list(menu._items):
            self.set_rank(item, rank)
            rank += 1
            log.debug("v.id: %s rank: %s", item.get("id"), rank)

        menu.set_comparator(SimpleMenu.itemComparatorRank)

    rankMenuItems = rank_menu_items

    def item_up_one(self, item: MenuItemDict, node: Optional[str] = None) -> None:
        """Move *item* one position up in *node*'s menu."""
        if node is None:
            node = "home"

        menu = self.get_node_menu(node)
        if menu is None:
            return

        self.rank_menu_items(node)

        for i, v in enumerate(menu._items):
            if v is item:
                rank = i + 1
                if rank == 1:
                    log.info("Item is already at the top")
                else:
                    item_above = menu._items[i - 1]
                    self.set_rank(item_above, rank)
                    self.set_rank(v, rank - 1)
                    menu.set_selected_index(rank - 1)
                    menu.set_comparator(SimpleMenu.itemComparatorRank)
                break

    itemUpOne = item_up_one

    def item_down_one(self, item: MenuItemDict, node: Optional[str] = None) -> None:
        """Move *item* one position down in *node*'s menu."""
        if node is None:
            node = "home"

        menu = self.get_node_menu(node)
        if menu is None:
            return

        self.rank_menu_items(node)

        for i, v in enumerate(menu._items):
            if v is item:
                rank = i + 1
                if rank == len(menu._items):
                    log.info("Item is already at the bottom")
                else:
                    item_below = menu._items[i + 1]
                    self.set_rank(item_below, rank)
                    self.set_rank(v, rank + 1)
                    menu.set_comparator(SimpleMenu.itemComparatorRank)
                    menu.set_selected_index(rank + 1)
                break

    itemDownOne = item_down_one

    def item_to_bottom(self, item: MenuItemDict, node: Optional[str] = None) -> None:
        """Move *item* to the bottom of *node*'s menu."""
        if node is None:
            node = "home"

        menu = self.get_node_menu(node)
        if menu is None:
            return

        self.rank_menu_items(node)

        for i, v in enumerate(menu._items):
            if v is item:
                rank = i + 1
                if rank == len(menu._items):
                    log.info("Item is already at the bottom")
                else:
                    bottom_index = len(menu._items)
                    self.set_rank(v, bottom_index + 1)
                    menu.set_selected_index(bottom_index)
                    menu.set_comparator(SimpleMenu.itemComparatorRank)
                    self.rank_menu_items("home")
                break

    itemToBottom = item_to_bottom

    def item_to_top(self, item: MenuItemDict, node: Optional[str] = None) -> None:
        """Move *item* to the top of *node*'s menu."""
        if node is None:
            node = "home"

        menu = self.get_node_menu(node)
        if menu is None:
            return

        self.rank_menu_items(node)

        for i, v in enumerate(menu._items):
            rank = i + 1
            if v is item:
                if rank == 1:
                    log.info("Item is already at the top")
                else:
                    self.set_rank(v, 1)
            else:
                self.set_rank(v, rank + 1)

        menu.set_selected_index(1)
        menu.set_comparator(SimpleMenu.itemComparatorRank)
        self.rank_menu_items(node)

    itemToTop = item_to_top

    # ------------------------------------------------------------------
    # Title
    # ------------------------------------------------------------------

    def set_title(self, title: Optional[str] = None) -> None:
        """
        Set the window title.  If *title* is ``None``, revert to the
        original title passed to the constructor.
        """
        if title is not None:
            self.window.set_title(title)
        else:
            self.window.set_title(self.window_title)

    setTitle = set_title

    # ------------------------------------------------------------------
    # Custom nodes
    # ------------------------------------------------------------------

    def set_custom_node(self, item_id: str, node: str) -> None:
        """
        Override the node for *item_id*.

        If the item was in ``"home"`` and is moved to ``"hidden"``,
        it is removed from the home menu.  Otherwise it is added to
        the new node.
        """
        if item_id in self.menu_table:
            item = self.menu_table[item_id]
            if item.get("node") == "home" and node == "hidden":
                self.remove_item_from_node(item, "home")
            self.add_item_to_node(item, node)
        self.custom_nodes[item_id] = node

    setCustomNode = set_custom_node

    def set_node(self, item: MenuItemDict, node: str) -> None:
        """
        Move *item* to *node*.

        Removes the item, sets a custom node override, and re-adds it.
        """
        assert item is not None
        assert node is not None

        self.remove_item(item)
        self.set_custom_node(item["id"], node)
        self.add_item(item)

    setNode = set_node

    # ------------------------------------------------------------------
    # Close to home
    # ------------------------------------------------------------------

    def close_to_home(
        self,
        hide_always_on_top: bool = True,
        transition: Optional[Any] = None,
    ) -> None:
        """
        Close all windows to expose the home menu.

        By default, ``alwaysOnTop`` windows are not hidden.  Also
        moves the selection to the first (root) item.

        Parameters
        ----------
        hide_always_on_top : bool
            If ``True``, also hide always-on-top windows.
        transition : callable, optional
            Transition function for the hide animation.
        """
        from jive.ui.framework import framework as fw

        # Move to root item (bug #14066)
        if self.node_table:
            home_menu = self.node_table["home"]["menu"]
            home_menu.set_selected_index(1)

        stack = fw.window_stack

        k = 0  # 0-based index
        for i in range(len(stack)):
            win = stack[i]
            if getattr(win, "always_on_top", False) and hide_always_on_top is not False:
                k = i + 1

            if win is self.window:
                for j in range(i - 1, k - 1, -1):
                    stack[j].hide(transition)
                break

    closeToHome = close_to_home

    # ------------------------------------------------------------------
    # Internal: _change_node
    # ------------------------------------------------------------------

    def _change_node(self, item_id: str, node: str) -> None:
        """
        Move the item identified by *item_id* to *node* if its current
        node differs.
        """
        if item_id in self.menu_table and self.menu_table[item_id].get("node") != node:
            # Remove from previous node's items dict
            if node in self.node_table:
                self.node_table[node]["items"].pop(item_id, None)
            # Change the item's node
            self.menu_table[item_id]["node"] = node
            # Re-add as a node
            self.add_node(self.menu_table[item_id])

    # ------------------------------------------------------------------
    # Add node
    # ------------------------------------------------------------------

    def add_node(self, item: Optional[MenuItemDict]) -> None:
        """
        Register a sub-menu node.

        A node is an item that, when selected, opens a sub-menu
        containing child items.

        The *item* dict should have at least ``id`` and ``node`` keys.
        If ``weight`` is missing, defaults to 100.

        Parameters
        ----------
        item : dict or None
            The node definition.  If ``None`` or missing ``id``/``node``
            keys, the call is a no-op.
        """
        if item is None or "id" not in item or "node" not in item:
            return

        item["isANode"] = 1

        # Context-menu callback (placeholder until AppletManager is ported)
        item["cmCallback"] = lambda: int(EVENT_CONSUME)

        if item.get("weight") is None:
            item["weight"] = 100

        if item.get("iconStyle"):
            item["icon"] = Icon(item["iconStyle"])
        else:
            item["iconStyle"] = "hm_advancedSettings"

        # Update existing node if already registered
        if item["id"] in self.menu_table:
            self.menu_table[item["id"]]["text"] = item.get("text")
            new_node = item.get("node")
            prev_node = self.menu_table[item["id"]].get("node")
            if new_node != prev_node:
                self._change_node(item["id"], new_node)  # type: ignore[arg-type]
            return

        # Create a new window + menu for this node
        if item.get("windowStyle"):
            win = Window(item["windowStyle"], item.get("text", ""))
        else:
            win = Window("home_menu", item.get("text", ""))

        menu_style = "menu"
        if (
            item.get("window") is not None
            and isinstance(item["window"], dict)
            and item["window"].get("menuStyle")
        ):
            menu_style = item["window"]["menuStyle"] + "menu"

        sub_menu = SimpleMenu(menu_style)
        sub_menu.set_comparator(SimpleMenu.itemComparatorWeightAlpha)
        win.add_widget(sub_menu)

        self.node_table[item["id"]] = {
            "menu": sub_menu,
            "item": item,
            "items": {},
        }

        # Default callback: show the node's window
        if item.get("callback") is None:
            node_window = win
            node_item = item

            def _show_node(event: Any = None, menu_item: Any = None) -> None:
                node_window.set_title(str(node_item.get("text", "")))
                node_window.show()

            item["callback"] = _show_node

        if item.get("sound") is None:
            item["sound"] = "WINDOWSHOW"

    addNode = add_node

    # ------------------------------------------------------------------
    # Add item to node
    # ------------------------------------------------------------------

    def add_item_to_node(
        self,
        item: MenuItemDict,
        node: Optional[str] = None,
    ) -> Optional[MenuItemDict]:
        """
        Add *item* to a specific *node*.

        If *node* is not ``None``, it is stored as a custom-node
        override for this item.  If *node* is ``None``, the item's
        own ``node`` key is used.

        When adding to ``"home"``, a copy of the item is created
        (via :func:`_uses`) so that the home menu has its own entry.

        Parameters
        ----------
        item : dict
            The item to add.  Must have an ``id`` key.
        node : str, optional
            Target node.  Defaults to ``item["node"]``.

        Returns
        -------
        dict or None
            The item (or its copy, for ``"home"``), or ``None`` if
            the target node does not exist.
        """
        assert "id" in item

        if node is not None:
            self.custom_nodes[item["id"]] = node
            if item.get("node") != "home" and node == "home":
                complex_weight = self.get_complex_weight(item["id"], item)
                item["weights"] = str_split("%.", str(complex_weight))
        else:
            node = item.get("node", "home")

        assert node is not None

        entry = self.node_table.get(node)
        if entry is None:
            return None

        entry["items"][item["id"]] = item
        entry["menu"].add_item(item)

        # Items in the home menu get special handling — a copy is created
        if node == "home":
            my_item = _uses(item)

            # Override the context-menu callback to use the copy
            my_item["cmCallback"] = lambda: int(EVENT_CONSUME)

            self.custom_menu_table[my_item["id"]] = my_item
            entry["menu"].add_item(my_item)
            entry["items"][my_item["id"]] = my_item
            return my_item

        return item

    addItemToNode = add_item_to_node

    # ------------------------------------------------------------------
    # Add item
    # ------------------------------------------------------------------

    def add_item(self, item: MenuItemDict) -> None:
        """
        Register a leaf item in the menu.

        The item is added to its ``node`` (and optionally to a custom
        node override).  If the item's node has a parent node entry
        that is not yet in the menu table, that parent is also added
        (recursively).

        The *item* dict must have ``id`` and ``node`` keys.  Optional
        keys include ``text``, ``weight``, ``callback``, ``iconStyle``,
        ``sound``, ``extras``.

        Parameters
        ----------
        item : dict
            The item to add.
        """
        assert "id" in item
        assert "node" in item

        # Context-menu callback (placeholder)
        item["cmCallback"] = lambda: int(EVENT_CONSUME)

        if item.get("iconStyle"):
            item["icon"] = Icon(item["iconStyle"])

        if item.get("weight") is None:
            item["weight"] = 100

        # Merge extras into the item dict
        extras = item.get("extras")
        if extras is not None and isinstance(extras, dict):
            for key, val in extras.items():
                item[key] = val
            item.pop("extras", None)

        # Register in the menu table
        self.menu_table[item["id"]] = item

        # Add to custom node if one is configured
        custom_node = self.custom_nodes.get(item["id"])
        if custom_node is not None:
            if custom_node == "hidden" and item.get("node") == "home":
                self.add_item_to_node(item, custom_node)
                self.remove_item_from_node(item, "home")
                return
            elif custom_node == "home":
                self.add_item_to_node(item, custom_node)

        # Add to the item's default node
        self.add_item_to_node(item)

        # Auto-add parent node entry if needed
        node_entry = self.node_table.get(item["node"])

        if node_entry is not None and node_entry.get("item") is not None:
            node_item = node_entry["item"]
            has_item = node_item.get("id") in self.menu_table

            if not has_item:
                # Check if there are any entries in the node's items
                has_entry = bool(node_entry["items"])
                if has_entry:
                    self.add_item(node_item)

    addItem = add_item

    # ------------------------------------------------------------------
    # Check / remove node
    # ------------------------------------------------------------------

    def _check_remove_node(self, node: str) -> None:
        """
        Remove the node's item from the menu table if it has no
        remaining children.
        """
        entry = self.node_table.get(node)
        if entry is None or entry.get("item") is None:
            return

        node_item = entry["item"]
        has_item = node_item.get("id") in self.menu_table

        if has_item:
            has_entry = bool(entry["items"])
            if not has_entry:
                self.remove_item(node_item)

    # ------------------------------------------------------------------
    # Remove item from node
    # ------------------------------------------------------------------

    def remove_item_from_node(
        self,
        item: MenuItemDict,
        node: Optional[str] = None,
    ) -> None:
        """
        Remove *item* from a specific *node*'s menu.

        If *node* is ``None``, the item's own ``node`` key is used.

        For items in the ``"home"`` node that have a custom copy,
        the copy is also removed.

        Parameters
        ----------
        item : dict
            The item to remove.
        node : str, optional
            Target node.  Defaults to ``item["node"]``.
        """
        assert item is not None

        if node is None:
            node = item.get("node")
        assert node is not None

        # If removing from home and there's a custom copy, remove it too
        if node == "home" and item.get("id") in self.custom_menu_table:
            item_id = item["id"]
            entry = self.node_table.get(node)
            if entry is not None:
                idx = entry["menu"].get_item_index_by_id(item_id)
                if idx is not None:
                    found = entry["menu"].get_item(idx)
                    if found is not None:
                        entry["menu"].remove_item(found)

        entry = self.node_table.get(node)
        if entry is not None:
            entry["items"].pop(item.get("id"), None)
            entry["menu"].remove_item(item)
            self._check_remove_node(node)

    removeItemFromNode = remove_item_from_node

    # ------------------------------------------------------------------
    # Remove item
    # ------------------------------------------------------------------

    def remove_item(self, item: MenuItemDict) -> None:
        """
        Remove *item* from the menu entirely.

        Removes from both the item's node and from the ``"home"`` node
        (if co-located there).

        Parameters
        ----------
        item : dict
            The item to remove.
        """
        assert item is not None
        assert "node" in item

        item_id = item.get("id")
        if item_id is not None and item_id in self.menu_table:
            del self.menu_table[item_id]

        self.remove_item_from_node(item)

        # Also remove from home if co-located
        self.remove_item_from_node(item, "home")

    removeItem = remove_item

    # ------------------------------------------------------------------
    # Remove by id
    # ------------------------------------------------------------------

    def remove_item_by_id(self, item_id: str) -> None:
        """Remove the item with *item_id* from the menu."""
        item = self.menu_table.get(item_id)
        if item is not None:
            self.remove_item(item)

    removeItemById = remove_item_by_id

    # ------------------------------------------------------------------
    # Open node
    # ------------------------------------------------------------------

    def open_node_by_id(self, item_id: str, reset_selection: bool = False) -> bool:
        """
        Programmatically open the node identified by *item_id*.

        Parameters
        ----------
        item_id : str
            The node's ``id``.
        reset_selection : bool
            If ``True``, reset the selection to the first item.

        Returns
        -------
        bool
            ``True`` if the node was found and opened, ``False``
            otherwise.
        """
        entry = self.node_table.get(item_id)
        if entry is not None:
            if reset_selection:
                entry["menu"].set_selected_index(1)
            callback = entry.get("item", {})
            if isinstance(callback, dict):
                cb = callback.get("callback")
            else:
                cb = None
            if cb is not None:
                cb()
            return True
        return False

    openNodeById = open_node_by_id

    # ------------------------------------------------------------------
    # Enable / Disable
    # ------------------------------------------------------------------

    def enable_item(self, item: MenuItemDict) -> None:
        """
        Enable a previously disabled item.

        Currently a no-op — placeholder for future implementation.
        """
        pass

    enableItem = enable_item

    def disable_item(self, item: MenuItemDict) -> None:
        """
        Disable *item* by moving it to the ``"hidden"`` node.

        Unlike :meth:`remove_item`, this preserves the item in memory
        so that meta files can continue handling events.

        Parameters
        ----------
        item : dict
            The item to disable.
        """
        assert item is not None
        assert "node" in item

        item_id = item.get("id")
        if item_id is not None and item_id in self.menu_table:
            del self.menu_table[item_id]

        self.remove_item_from_node(item)

        item["node"] = "hidden"
        self.add_item(item)

        # Also remove from home if co-located
        self.remove_item_from_node(item, "home")

    disableItem = disable_item

    def disable_item_by_id(self, item_id: str) -> None:
        """Disable the item with *item_id*."""
        item = self.menu_table.get(item_id)
        if item is not None:
            self.disable_item(item)

    disableItemById = disable_item_by_id

    # ------------------------------------------------------------------
    # Node item lookup
    # ------------------------------------------------------------------

    def get_node_item_by_id(self, item_id: str, node: str) -> Optional[MenuItemDict]:
        """
        Return the item with *item_id* from *node*'s items dict, or
        ``None``.
        """
        entry = self.node_table.get(node)
        if entry is None:
            return None
        return entry.get("items", {}).get(item_id)  # type: ignore[no-any-return]

    getNodeItemById = get_node_item_by_id

    # ------------------------------------------------------------------
    # Lock / Unlock
    # ------------------------------------------------------------------

    def lock_item(self, item: MenuItemDict, *args: Any) -> None:
        """
        Lock the menu containing *item*, preventing user interaction
        (e.g. while an applet is loading).
        """
        custom = self.custom_nodes.get(item.get("id", ""))
        if custom and custom in self.node_table:
            self.node_table[custom]["menu"].lock(*args)
        elif item.get("node") and item["node"] in self.node_table:
            self.node_table[item["node"]]["menu"].lock(*args)

    lockItem = lock_item

    def unlock_item(self, item: MenuItemDict) -> None:
        """
        Unlock the menu containing *item*.
        """
        custom = self.custom_nodes.get(item.get("id", ""))
        if custom and custom in self.node_table:
            self.node_table[custom]["menu"].unlock()
        elif item.get("node") and item["node"] in self.node_table:
            self.node_table[item["node"]]["menu"].unlock()

    unlockItem = unlock_item

    # ------------------------------------------------------------------
    # Iterator
    # ------------------------------------------------------------------

    def iterator(self) -> Iterator[Any]:
        """
        Iterate over items in the home menu.

        Yields each item from the home node's :class:`SimpleMenu`.
        """
        menu = self.node_table.get("home", {}).get("menu")
        if menu is not None:
            yield from menu._items

    # ------------------------------------------------------------------
    # Representation
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"HomeMenu({self.window_title!r}, "
            f"items={len(self.menu_table)}, "
            f"nodes={len(self.node_table)})"
        )

    def __str__(self) -> str:
        return f"HomeMenu({self.window_title!r})"


# ---------------------------------------------------------------------------
# Module-level action handlers (used by the constructor)
# ---------------------------------------------------------------------------


def _bump_action(obj: HomeMenu, event: Any = None) -> int:
    """
    Action handler for ``"back"`` on the home window.

    Plays the bump sound and triggers a bump-left transition instead
    of closing the window.
    """
    obj.window.play_sound("BUMP")
    obj.window.bump_left()
    return int(EVENT_CONSUME)


def _home_root_handler(obj: HomeMenu, event: Any = None) -> int:
    """
    Action handler for ``"go_home"`` / ``"go_home_or_now_playing"``.

    If the home window is already the topmost window and the selection
    is not at the first item, scrolls to the first item.  Otherwise
    returns ``EVENT_UNUSED`` to let the standard handler take over.
    """
    from jive.ui.framework import framework as fw

    stack = fw.window_stack

    if len(stack) == 1:
        home_menu = obj.node_table["home"]["menu"]
        idx = home_menu.get_selected_index()
        if idx is not None and idx > 1:
            fw.play_sound("JUMP")
            home_menu.set_selected_index(1)
            return int(EVENT_CONSUME)

    return int(EVENT_UNUSED)
