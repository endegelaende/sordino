"""
jive.ui.simplemenu — SimpleMenu widget for the Jivelite Python3 port.

Ported from ``SimpleMenu.lua`` in the original jivelite project.

A SimpleMenu widget provides a convenience API on top of :class:`Menu`
for creating menus from simple data items.  Each item is a dict with
optional keys:

* ``text`` — display text (str)
* ``icon`` — an Icon widget to show beside the text
* ``callback`` — ``callback(event, item)`` invoked on item activation
* ``sound`` — sound effect name to play on activation
* ``id`` — unique identifier string for the item
* ``style`` — per-item style override
* ``weight`` — sort weight for ordering
* ``iconStyle`` — style override for the auto-created icon widget
* ``checked`` — for checkbox-style items (bool)

SimpleMenu automatically creates Group widgets wrapping a Label + Icon
for each visible data item, and handles the ``_updateWidgets`` hook
called by the Menu base class during layout.

It also provides:

* **Sorting** — ``set_comparator()`` to sort items alphabetically or
  by a custom comparator function
* **Item lookup** — ``get_index(item)`` and ``find_item_by_id(id)``
* **Batch update** — ``set_items()`` replaces all items at once

Copyright 2010 Logitech. All Rights Reserved. (original Lua/C code)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Sequence,
    Tuple,
    Union,
)

from jive.ui.constants import (
    EVENT_ACTION,
    EVENT_CONSUME,
    EVENT_FOCUS_GAINED,
    EVENT_FOCUS_LOST,
    EVENT_UNUSED,
    LAYER_ALL,
    WH_NIL,
    XY_NIL,
)
from jive.ui.menu import Menu
from jive.utils.log import logger

if TYPE_CHECKING:
    from jive.ui.event import Event
    from jive.ui.surface import Surface
    from jive.ui.widget import Widget

__all__ = ["SimpleMenu"]

log = logger("jivelite.ui")


# ---------------------------------------------------------------------------
# Type alias for a menu-item dict
# ---------------------------------------------------------------------------

# A SimpleMenu item is a dict with string keys.  The most common keys are
# documented in the module docstring above.
MenuItem = Dict[str, Any]


# ---------------------------------------------------------------------------
# Default comparators
# ---------------------------------------------------------------------------


def item_comparator_alpha(a: MenuItem, b: MenuItem) -> int:
    """
    Alphabetical comparator for SimpleMenu items.

    Compares the ``text`` key (case-insensitive).  Items without ``text``
    sort to the end.

    Returns
    -------
    int
        Negative if *a* < *b*, zero if equal, positive if *a* > *b*.
    """
    ta = str(a.get("text", "") or "").lower()
    tb = str(b.get("text", "") or "").lower()
    if ta < tb:
        return -1
    if ta > tb:
        return 1
    return 0


def item_comparator_weight_alpha(a: MenuItem, b: MenuItem) -> int:
    """
    Weight-then-alpha comparator for SimpleMenu items.

    First compares by ``weight`` (lower weight first, default weight is 1),
    then falls back to alphabetical comparison of ``text``.

    Returns
    -------
    int
        Negative if *a* < *b*, zero if equal, positive if *a* > *b*.
    """
    wa = a.get("weight", 1)
    wb = b.get("weight", 1)
    if wa != wb:
        return -1 if wa < wb else 1
    return item_comparator_alpha(a, b)


def item_comparator_complex_weight_alpha(a: MenuItem, b: MenuItem) -> int:
    """
    Complex-weight-then-alpha comparator for SimpleMenu items.

    Compares by ``weights`` (a list of weight segments, as produced by
    :meth:`HomeMenu.get_complex_weight`).  Each segment is compared
    numerically; if all segments are equal the items are compared
    alphabetically.

    Items without ``weights`` fall back to the simple ``weight`` key.

    This comparator is used by the HomeMenu's root menu.

    Returns
    -------
    int
        Negative if *a* < *b*, zero if equal, positive if *a* > *b*.
    """
    aw = a.get("weights")
    bw = b.get("weights")

    if aw is None and bw is None:
        return item_comparator_weight_alpha(a, b)

    # Normalise to lists
    if aw is None:
        aw = [a.get("weight", 100)]
    if bw is None:
        bw = [b.get("weight", 100)]

    # Compare segment by segment
    for sa, sb in zip(aw, bw):
        try:
            va = float(sa)
        except (TypeError, ValueError):
            va = 0.0
        try:
            vb = float(sb)
        except (TypeError, ValueError):
            vb = 0.0
        if va != vb:
            return -1 if va < vb else 1

    # If one list is longer, the shorter one sorts first
    if len(aw) != len(bw):
        return -1 if len(aw) < len(bw) else 1

    return item_comparator_alpha(a, b)


def item_comparator_rank(a: MenuItem, b: MenuItem) -> int:
    """
    Rank-based comparator for SimpleMenu items.

    Compares by the ``rank`` key (lower rank first).  Items without a
    ``rank`` sort to the end (treated as rank ``999999``).

    This comparator is used by the HomeMenu for manually re-ordered
    menus (move up / move down / move to top / move to bottom).

    Returns
    -------
    int
        Negative if *a* < *b*, zero if equal, positive if *a* > *b*.
    """
    ra = a.get("rank", 999999)
    rb = b.get("rank", 999999)
    if ra != rb:
        return -1 if ra < rb else 1
    return 0


# ---------------------------------------------------------------------------
# SimpleMenu widget
# ---------------------------------------------------------------------------


class SimpleMenu(Menu):
    """
    A convenience menu widget that manages items as simple dicts.

    Each item is a dict containing at minimum a ``text`` key.  The
    SimpleMenu automatically creates the necessary Label/Icon/Group
    widgets for display.

    Parameters
    ----------
    style : str
        The style key used to look up skin parameters.
    items : list of dict, optional
        Initial list of item dicts.
    item_listener : callable, optional
        Callback ``(menu, list, item, index, event) -> int`` invoked when
        an event targets a menu item.  If not provided, the default
        listener delegates to each item's ``callback`` key.
    """

    __slots__ = (
        "_items",
        "_comparator",
        "_widget_cache",
        "_default_icons",
        "_default_checks",
        "_default_arrows",
        "_close_callback",
    )

    # Class-level comparators accessible as ``SimpleMenu.itemComparatorAlpha``
    itemComparatorAlpha = staticmethod(item_comparator_alpha)
    itemComparatorWeightAlpha = staticmethod(item_comparator_weight_alpha)
    itemComparatorComplexWeightAlpha = staticmethod(item_comparator_complex_weight_alpha)
    itemComparatorRank = staticmethod(item_comparator_rank)

    def __init__(
        self,
        style: str,
        items: Optional[List[MenuItem]] = None,
        item_listener: Optional[Callable[..., int]] = None,
    ) -> None:
        super().__init__(style, item_listener=item_listener or self._default_item_listener)

        # Item data
        self._items: List[MenuItem] = list(items) if items else []
        self.list = self._items
        self.list_size = len(self._items)

        # Comparator for sorting
        self._comparator: Optional[Callable[[MenuItem, MenuItem], int]] = None

        # Widget cache — maps data-item id (or list index) to created widget
        self._widget_cache: Dict[Any, Widget] = {}

        # Per-slot default sub-widgets (mirrors Lua's menu.icons/checks/arrows)
        self._default_icons: List[Any] = []
        self._default_checks: List[Any] = []
        self._default_arrows: List[Any] = []

        # Close callback
        self._close_callback: Optional[Callable[..., Any]] = None

        # Select first item if available
        if self.list_size > 0:
            self.selected = 1

    # ------------------------------------------------------------------
    # Default item listener
    # ------------------------------------------------------------------

    @staticmethod
    def _default_item_listener(
        menu: "SimpleMenu",
        data_list: List[MenuItem],
        item: Any,
        index: int,
        event: "Event",
    ) -> int:
        """
        Default item listener — dispatches events to item callbacks.

        Matches the Lua ``_itemListener`` in ``SimpleMenu.lua`` (lines 177-203):

        - ``EVENT_ACTION`` type → ``item.callback(event, item)``
        - ``ACTION`` type with action="go" → ``item.callback(event, item)``
          (Menu's ``_event_handler`` forwards ACTION "go" through _item_listener
          before falling to the ``_go_action`` handler)
        - ``ACTION`` type with action="play" and ``isPlayableItem`` → callback
        - ``ACTION`` type with action="add" and ``cmCallback`` → cmCallback
        - ``EVENT_FOCUS_GAINED`` → ``item.focusGained``
        - ``EVENT_FOCUS_LOST`` → ``item.focusLost``
        """
        from jive.ui.constants import ACTION

        if 1 <= index <= len(data_list):
            data_item = data_list[index - 1]
        else:
            return int(EVENT_UNUSED)

        etype = event.get_type() if hasattr(event, "get_type") else getattr(event, "type", 0)

        # --- EVENT_ACTION or ACTION "go" → item.callback ---
        # Lua: if (event:getType() == EVENT_ACTION and item.callback) or
        #         (item.isPlayableItem and event:getType() == ACTION and
        #          event:getAction() == "play") then
        is_event_action = etype == int(EVENT_ACTION)
        is_action_go = (
            etype == int(ACTION) and hasattr(event, "get_action") and event.get_action() == "go"
        )
        is_playable = (
            data_item.get("isPlayableItem")
            and etype == int(ACTION)
            and hasattr(event, "get_action")
            and event.get_action() == "play"
        )

        if (is_event_action or is_action_go or is_playable) and data_item.get("callback"):
            callback = data_item["callback"]
            # Play sound if specified
            sound = data_item.get("sound")
            if sound:
                try:
                    if hasattr(item, "playSound"):
                        item.playSound(sound)
                    elif hasattr(item, "play_sound"):
                        item.play_sound(sound)
                except Exception as exc:
                    log.warning("play_sound callback: %s", exc)

            try:
                try:
                    r = callback(event, data_item)
                except TypeError:
                    r = callback()
                return int(r) if isinstance(r, int) else int(EVENT_CONSUME)
            except Exception:
                import traceback

                log.warn(
                    "SimpleMenu item callback error:\n%s",
                    traceback.format_exc(),
                )
                return int(EVENT_CONSUME)

        # --- ACTION "add" with cmCallback ---
        if (
            etype == int(ACTION)
            and hasattr(event, "get_action")
            and event.get_action() == "add"
            and data_item.get("cmCallback")
        ):
            try:
                r = data_item["cmCallback"](event, data_item)
                return int(r) if isinstance(r, int) else int(EVENT_CONSUME)
            except Exception:
                return int(EVENT_CONSUME)

        # --- EVENT_FOCUS_GAINED → item.focusGained ---
        if etype == int(EVENT_FOCUS_GAINED):
            focus_cb = data_item.get("focusGained")
            if focus_cb is not None:
                try:
                    try:
                        r = focus_cb(event, data_item)
                    except TypeError:
                        r = focus_cb()
                    return int(r) if isinstance(r, int) else int(EVENT_CONSUME)
                except Exception:
                    return int(EVENT_CONSUME)

        # --- EVENT_FOCUS_LOST → item.focusLost ---
        if etype == int(EVENT_FOCUS_LOST):
            focus_cb = data_item.get("focusLost")
            if focus_cb is not None:
                try:
                    try:
                        r = focus_cb(event, data_item)
                    except TypeError:
                        r = focus_cb()
                    return int(r) if isinstance(r, int) else int(EVENT_CONSUME)
                except Exception:
                    return int(EVENT_CONSUME)

        return int(EVENT_UNUSED)

    # ------------------------------------------------------------------
    # Item management (overrides / extensions)
    # ------------------------------------------------------------------

    def set_items(self, items: List[MenuItem]) -> None:  # type: ignore[override]
        """
        Replace all items with *items*.

        Parameters
        ----------
        items : list of dict
            The new item list.
        """
        self._items = list(items)
        self.list = self._items
        self.list_size = len(self._items)
        self._widget_cache.clear()

        if self._comparator is not None:
            self._sort()

        if self.list_size > 0 and (self.selected is None or self.selected > self.list_size):
            self.selected = 1

        self.top_item = 1
        self._update_widgets()
        self.re_layout()

    setItems = set_items  # type: ignore[assignment]

    def add_item(self, item: MenuItem) -> None:
        """Append a single item to the end of the list.

        If an item with the same ``id`` already exists in the list it
        is **replaced** in-place (matching the Lua original's
        ``insertItem`` duplicate-ID semantics).
        """
        # Replace existing item with the same id (Lua: insertItem check)
        item_id = item.get("id") if isinstance(item, dict) else None
        if item_id is not None:
            for i, existing in enumerate(self._items):
                eid = existing.get("id") if isinstance(existing, dict) else None
                if eid == item_id:
                    self._items[i] = item
                    self.list = self._items
                    self.list_size = len(self._items)
                    self._update_widgets()
                    self.re_layout()
                    return

        self._items.append(item)
        self.list = self._items
        self.list_size = len(self._items)

        if self._comparator is not None:
            self._sort()

        if self.selected is None and self.list_size > 0:
            self.selected = 1

        self._update_widgets()
        self.re_layout()

    addItem = add_item

    def insert_item(self, item: MenuItem, index: int) -> None:
        """
        Insert *item* at 1-based *index*.

        If an item with the same ``id`` already exists in the list it
        is **replaced** in-place rather than inserted again (matching
        the Lua original's ``insertItem`` duplicate-ID semantics).

        Parameters
        ----------
        item : dict
            The item to insert.
        index : int
            1-based position.
        """
        # Replace existing item with the same id (Lua: insertItem check)
        item_id = item.get("id") if isinstance(item, dict) else None
        if item_id is not None:
            for i, existing in enumerate(self._items):
                eid = existing.get("id") if isinstance(existing, dict) else None
                if eid == item_id:
                    self._items[i] = item
                    self.list = self._items
                    self.list_size = len(self._items)
                    self._update_widgets()
                    self.re_layout()
                    return

        idx = max(0, min(index - 1, len(self._items)))
        self._items.insert(idx, item)
        self.list = self._items
        self.list_size = len(self._items)

        if self._comparator is not None:
            self._sort()

        if self.selected is None and self.list_size > 0:
            self.selected = 1

        self._update_widgets()
        self.re_layout()

    insertItem = insert_item

    def remove_item(self, item: MenuItem) -> None:
        """Remove *item* from the list by identity."""
        try:
            self._items.remove(item)
        except ValueError as exc:
            log.debug("remove failed: %s", exc)
        self.list = self._items
        self.list_size = len(self._items)

        # Invalidate cached widget for removed item
        item_id = id(item)
        self._widget_cache.pop(item_id, None)

        # Adjust selection
        if self.list_size == 0:
            self.selected = None
        elif self.selected is not None and self.selected > self.list_size:
            self.selected = self.list_size

        self._update_widgets()
        self.re_layout()

    removeItem = remove_item

    def remove_item_at(self, index: int) -> None:
        """Remove the item at 1-based *index*."""
        idx = index - 1
        if 0 <= idx < len(self._items):
            item = self._items[idx]
            self._widget_cache.pop(id(item), None)
            del self._items[idx]

        self.list = self._items
        self.list_size = len(self._items)

        if self.list_size == 0:
            self.selected = None
        elif self.selected is not None and self.selected > self.list_size:
            self.selected = self.list_size

        self._update_widgets()
        self.re_layout()

    removeItemAt = remove_item_at

    def remove_all_items(self) -> None:
        """Remove all items."""
        self._items.clear()
        self.list = self._items
        self.list_size = 0
        self._widget_cache.clear()
        self.widgets.clear()
        self.selected = None
        self.top_item = 1
        self.re_layout()

    removeAllItems = remove_all_items

    def replace_item(self, old_item: MenuItem, new_item: MenuItem) -> None:
        """Replace *old_item* with *new_item* in the list."""
        for i, item in enumerate(self._items):
            if item is old_item:
                self._items[i] = new_item
                self._widget_cache.pop(id(old_item), None)
                break

        self.list = self._items
        self._update_widgets()
        self.re_draw()

    replaceItem = replace_item

    # ------------------------------------------------------------------
    # Item lookup
    # ------------------------------------------------------------------

    def get_index(self, item: MenuItem) -> Optional[int]:
        """
        Return the 1-based index of *item* in the list, or None if not found.
        """
        for i, it in enumerate(self._items):
            if it is item:
                return i + 1
        return None

    getIndex = get_index

    def find_item_by_id(self, item_id: str) -> Optional[MenuItem]:
        """
        Find and return the first item whose ``id`` key matches *item_id*.

        Returns None if no match.
        """
        for item in self._items:
            if item.get("id") == item_id:
                return item
        return None

    findItemById = find_item_by_id

    def get_item_index_by_id(self, item_id: str) -> Optional[int]:
        """
        Return the 1-based index of the first item whose ``id`` matches
        *item_id*, or None.
        """
        for i, item in enumerate(self._items):
            if item.get("id") == item_id:
                return i + 1
        return None

    getItemIndexById = get_item_index_by_id

    # ------------------------------------------------------------------
    # Sorting
    # ------------------------------------------------------------------

    def set_comparator(
        self,
        comparator: Optional[Callable[[MenuItem, MenuItem], int]],
    ) -> None:
        """
        Set a comparator function for sorting items.

        The comparator receives two items and returns a negative int,
        zero, or positive int (like C ``qsort``).

        Pass ``None`` to disable sorting.

        Parameters
        ----------
        comparator : callable or None
            ``(a, b) -> int`` comparator.
        """
        self._comparator = comparator
        if comparator is not None:
            self._sort()
            self._update_widgets()
            self.re_layout()

    setComparator = set_comparator

    def _sort(self) -> None:
        """Sort ``self._items`` using the current comparator."""
        import functools

        if self._comparator is not None:
            self._items.sort(key=functools.cmp_to_key(self._comparator))
            self.list = self._items

    # ------------------------------------------------------------------
    # Close callback
    # ------------------------------------------------------------------

    def set_close_callback(self, callback: Optional[Callable[..., Any]]) -> None:
        """Set a callback invoked when the menu's window is closed."""
        self._close_callback = callback

    setCloseCallback = set_close_callback

    # ------------------------------------------------------------------
    # Widget creation / update (_updateWidgets)
    # ------------------------------------------------------------------

    def _update_widgets(self) -> None:
        """
        Synchronise the visible widget list with the underlying data.

        Mirrors the Lua original's ``_itemRenderer``: every visible item
        is **always** wrapped in a :class:`Group` containing up to four
        sub-widgets:

        * ``text``  — a :class:`Label` (or Textarea for multiline)
        * ``icon``  — the item's icon, or a default ``Icon("icon")``
        * ``check`` — a RadioButton / Checkbox from the item dict,
                       or a default ``Icon("check")``
        * ``arrow`` — an arrow indicator, or a default ``Icon("arrow")``

        Widgets are cached per data-item identity to avoid unnecessary
        re-creation.  On cache hit the sub-widgets are updated in-place
        (text value, icon/check/arrow swapped) exactly like Lua does.
        """
        if self.num_widgets <= 0 or self.list_size == 0:
            self.widgets = []
            return

        from jive.ui.group import Group
        from jive.ui.icon import Icon
        from jive.ui.label import Label

        # Per-slot default widgets (reused across re-layouts like Lua's
        # ``menu.icons[i]``, ``menu.checks[i]``, ``menu.arrows[i]``).
        while len(self._default_icons) < self.num_widgets:
            self._default_icons.append(Icon("icon"))
        while len(self._default_checks) < self.num_widgets:
            self._default_checks.append(Icon("check"))
        while len(self._default_arrows) < self.num_widgets:
            self._default_arrows.append(Icon("arrow"))

        new_widgets: List[Widget] = []

        for offset in range(self.num_widgets):
            data_index = self.top_item + offset  # 1-based
            if data_index < 1 or data_index > self.list_size:
                break

            data_item = self._items[data_index - 1]
            cache_key = id(data_item)

            item_style = data_item.get("style") or "item"
            text = str(data_item.get("text", ""))

            # Resolve icon / check / arrow — fall back to per-slot defaults
            icon = data_item.get("icon") or self._default_icons[offset]
            icon_style = data_item.get("iconStyle") or "icon"
            if hasattr(icon, "set_style"):
                icon.set_style(icon_style)
            elif hasattr(icon, "setStyle"):
                icon.setStyle(icon_style)

            check = data_item.get("check") or self._default_checks[offset]
            arrow = data_item.get("arrow") or self._default_arrows[offset]

            # Check cache — update in place if the Group already exists
            cached = self._widget_cache.get(cache_key)
            if cached is not None and isinstance(cached, Group):
                cached.set_style(item_style)
                # Update text value
                if hasattr(cached, "set_widget_value"):
                    cached.set_widget_value("text", text)
                elif hasattr(cached, "setWidgetValue"):
                    cached.setWidgetValue("text", text)
                # Swap sub-widgets if changed
                if hasattr(cached, "set_widget"):
                    cached.set_widget("icon", icon)
                    cached.set_widget("check", check)
                    cached.set_widget("arrow", arrow)
                elif hasattr(cached, "setWidget"):
                    cached.setWidget("icon", icon)
                    cached.setWidget("check", check)
                    cached.setWidget("arrow", arrow)
                cached.parent = self
                new_widgets.append(cached)
                continue

            # Build a new Group with all four sub-widgets
            label_widget = Label("text", text)
            widgets_dict: Dict[str, Any] = {
                "text": label_widget,
                "icon": icon,
                "check": check,
                "arrow": arrow,
            }
            group = Group(item_style, widgets_dict)
            group.parent = self
            self._widget_cache[cache_key] = group
            new_widgets.append(group)

        self.widgets = new_widgets

        # Apply selected/pressed style modifiers (Lua _updateWidgets L1801-1826)
        self._apply_selection_style()

        # Update scrollbar position — matches Lua Menu.lua L1847
        self._update_scrollbar()

    # ------------------------------------------------------------------
    # Go action override
    # ------------------------------------------------------------------

    def _go_action(self, event: Any = None) -> int:
        """Handle the 'go' action — invoke the selected item's callback.

        SimpleMenu overrides Menu._go_action because SimpleMenu can dispatch
        to item callbacks directly from the data list, without requiring
        visible widget instances (which only exist after _update_widgets
        has run during layout).
        """
        if self.selected is None or self.list_size == 0:
            return int(EVENT_UNUSED)

        if 1 <= self.selected <= self.list_size:
            data_item = self._items[self.selected - 1]

            # Play sound if specified
            sound = data_item.get("sound")
            if sound:
                try:
                    self.play_sound(sound)
                except Exception as exc:
                    log.warning("play_sound callback: %s", exc)

            # Dispatch through item_listener (e.g. _default_item_listener)
            if self.item_listener is not None:
                from jive.ui.event import Event as Evt

                evt = Evt(int(EVENT_ACTION))
                r = self.item_listener(self, self.list, data_item, self.selected, evt)
                if r != int(EVENT_UNUSED):
                    return r

            # Fallback to widget event dispatch
            item_widget = self._selected_item_widget()
            if item_widget is not None:
                from jive.ui.event import Event as Evt

                evt = Evt(int(EVENT_ACTION))
                r = item_widget._event(evt)
                if r != int(EVENT_UNUSED):
                    return r

        return int(EVENT_UNUSED)

    # ------------------------------------------------------------------
    # Representation
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        sel = self.selected or 0
        return f"SimpleMenu(items={self.list_size}, selected={sel}, top={self.top_item})"

    def __str__(self) -> str:
        return self.__repr__()
