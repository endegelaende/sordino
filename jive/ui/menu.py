"""
jive.ui.menu — Menu widget for the Jivelite Python3 port.

Ported from ``Menu.lua`` and ``jive_menu.c`` in the original jivelite project.

A Menu widget displays a scrollable list of item widgets. It supports:

* **Item management** — add, remove, replace items in an ordered list
* **Scrolling** — keyboard, scroll-wheel, IR, and touch/drag scrolling
* **Scrollbar** — integrated scrollbar widget when content overflows
* **Item height** — configurable fixed height for each menu item
* **Grid layout** — optional multi-column grid via ``itemsPerLine``
* **Selection** — selected item tracking with focus/style support
* **Header widget** — optional header widget above menu items
* **Pixel-offset scrolling** — smooth scrolling support via drag/flick
* **Acceleration** — scroll acceleration for IR remote / keyboard

The Menu widget is the base class for SimpleMenu, which provides a
convenience API for simple text+icon+callback items.

Copyright 2010 Logitech. All Rights Reserved. (original Lua/C code)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

import math
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
    ACTION,
    ALIGN_CENTER,
    ALIGN_TOP_LEFT,
    EVENT_ACTION,
    EVENT_ALL,
    EVENT_ALL_INPUT,
    EVENT_CONSUME,
    EVENT_FOCUS_GAINED,
    EVENT_FOCUS_LOST,
    EVENT_HIDE,
    EVENT_IR_ALL,
    EVENT_IR_DOWN,
    EVENT_IR_PRESS,
    EVENT_IR_REPEAT,
    EVENT_KEY_ALL,
    EVENT_KEY_DOWN,
    EVENT_KEY_PRESS,
    EVENT_MOUSE_ALL,
    EVENT_MOUSE_DOWN,
    EVENT_MOUSE_DRAG,
    EVENT_MOUSE_HOLD,
    EVENT_MOUSE_MOVE,
    EVENT_MOUSE_PRESS,
    EVENT_MOUSE_UP,
    EVENT_SCROLL,
    EVENT_SHOW,
    EVENT_UNUSED,
    KEY_BACK,
    KEY_DOWN,
    KEY_FWD,
    KEY_GO,
    KEY_LEFT,
    KEY_PAGE_DOWN,
    KEY_PAGE_UP,
    KEY_PLAY,
    KEY_REW,
    KEY_RIGHT,
    KEY_UP,
    LAYER_ALL,
    LAYER_CONTENT,
    WH_FILL,
    WH_NIL,
    XY_NIL,
)
from jive.ui.widget import Widget
from jive.utils.log import logger

if TYPE_CHECKING:
    from jive.ui.event import Event
    from jive.ui.font import Font
    from jive.ui.surface import Surface
    from jive.ui.tile import JiveTile  # type: ignore[attr-defined]

__all__ = ["Menu"]

log = logger("jivelite.ui")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ITEMS_BEFORE_SCROLL_DEFAULT = 1

# Mouse operation states
MOUSE_COMPLETE = 0
MOUSE_DOWN = 1
MOUSE_SELECTED = 2
MOUSE_DRAG = 3

# Distances for sloppy press / drag detection
MOUSE_QUICK_SLOPPY_PRESS_DISTANCE = 24
MOUSE_QUICK_DRAG_DISTANCE = 35
MOUSE_QUICK_TOUCH_TIME_MS = 120
MOUSE_SLOW_DRAG_DISTANCE = 20


def _coerce(value: int, max_val: int) -> int:
    """Return *value* clamped between 1 and *max_val*."""
    if value < 1:
        return 1
    if value > max_val:
        return max_val
    return value


class Menu(Widget):
    """
    A scrollable menu widget that manages a list of child item widgets.

    Parameters
    ----------
    style : str
        The style key used to look up skin parameters.
    item_listener : callable, optional
        Callback ``(menu, list, item, index, event) -> int`` invoked
        when an event targets a menu item.
    """

    __slots__ = (
        "list",
        "widgets",
        "list_size",
        "num_widgets",
        "item_height",
        "items_per_line",
        "selected",
        "top_item",
        "pixel_offset_y",
        "current_shift_direction",
        "drag_y_since_shift",
        "hide_scrollbar",
        "disable_vertical_bump",
        "_closeable",
        "_locked",
        "_lock_cancel",
        "_lock_time",
        "_lock_style",
        "header_widget",
        "header_widget_height",
        "virtual_item_count",
        "mouse_state",
        "mouse_down_bounds_x",
        "mouse_down_bounds_y",
        "use_pressed_style",
        "_last_selected",
        "_last_selected_index",
        "_font",
        "_fg",
        "_max_height",
        "_has_scrollbar",
        "scrollbar",
        "item_renderer",
        "item_listener",
        "item_available",
    )

    def __init__(
        self,
        style: str,
        item_renderer: Optional[Callable[..., None]] = None,
        item_listener: Optional[Callable[..., int]] = None,
        item_available: Optional[Callable[..., bool]] = None,
    ) -> None:
        if not isinstance(style, str):
            raise TypeError(f"style must be a string, got {type(style).__name__}")

        super().__init__(style)

        # Items
        self.list: List[Any] = []  # the underlying data list
        self.widgets: List[Any] = []  # visible child widgets
        self.list_size: int = 0
        self.num_widgets: int = 0
        self.item_height: int = 20
        self.items_per_line: int = 1

        # Selection / scroll
        self.selected: Optional[int] = None  # 1-based index into list
        self.top_item: int = 1  # 1-based index of first visible item
        self.pixel_offset_y: int = 0
        self.current_shift_direction: int = 0
        self.drag_y_since_shift: int = 0
        self.accel_key: Optional[str] = None
        self.hide_scrollbar: bool = False
        self.disable_vertical_bump: bool = False

        # Closeable flag — when False, the "back" action is suppressed
        self._closeable: bool = True

        # Lock state — when locked, input is suppressed
        # Lua stores cancel callback in self.locked (or true if no callback)
        # and lock time in self.lockedT for timeout escape.
        self._locked: Any = False  # False or cancel callback or True
        self._lock_cancel: Optional[Callable[..., Any]] = None
        self._lock_time: Optional[int] = None  # ticks when locked
        self._lock_style: Optional[str] = None

        # Header widget
        self.header_widget: Optional[Widget] = None
        self.header_widget_height: Optional[int] = None

        # Virtual item count (for header widget offset)
        self.virtual_item_count: int = 0

        # Mouse state
        self.mouse_state: int = MOUSE_COMPLETE
        self.mouse_down_bounds_x: int = 0
        self.mouse_down_bounds_y: int = 0
        self.use_pressed_style: bool = False

        # Selection tracking (for style modifier management)
        self._last_selected: Optional[Widget] = None
        self._last_selected_index: Optional[int] = None

        # Peer state (from C struct MenuWidget)
        self._font: Optional[Font] = None
        self._fg: int = 0x000000FF
        self._max_height: int = WH_NIL
        self._has_scrollbar: bool = False

        # Scrollbar child widget
        from jive.ui.slider import Scrollbar

        self.scrollbar: Scrollbar = Scrollbar("scrollbar")
        self.scrollbar.parent = self

        # Lua-compatible callbacks (itemRenderer, itemListener, itemAvailable)
        self.item_renderer: Optional[Callable[..., None]] = item_renderer
        self.item_listener: Optional[Callable[..., int]] = item_listener
        self.item_available: Optional[Callable[..., bool]] = item_available

        # Single EVENT_ALL listener — matches the Lua original which
        # handles ALL events (KEY_PRESS, ACTION, SCROLL, MOUSE, IR, etc.)
        # in one _eventHandler function.  No separate addActionListener
        # calls are used in the Lua Menu.
        self.add_listener(
            int(EVENT_ALL),
            lambda event: self._event_handler(event),
        )

    # ------------------------------------------------------------------
    # Item management
    # ------------------------------------------------------------------

    def num_items(self) -> int:
        """Return the number of items in the list."""
        return self.list_size

    numItems = num_items

    def get_item(self, index: int) -> Any:
        """
        Return the item at 1-based *index*, or None if out of range.
        """
        if 1 <= index <= self.list_size:
            return self.list[index - 1]
        return None

    getItem = get_item

    def set_items(
        self,
        items: Any,
        list_size: Optional[int] = None,
        min_val: Optional[int] = None,
        max_val: Optional[int] = None,
    ) -> None:
        """
        Replace the item list.

        Supports two calling conventions:

        1. ``set_items(python_list)`` — sets both ``list`` and ``list_size``
           from the list length.
        2. ``set_items(opaque_data, list_size, min, max)`` — Lua-compatible
           form used by SlimBrowser.  ``opaque_data`` is stored as-is
           (e.g. a step dict) and the renderer knows how to interpret it.
        """
        if list_size is not None:
            # Lua-compatible: opaque data + explicit size
            self.list = items
            self.list_size = list_size
        elif isinstance(items, list):
            self.list = list(items)
            self.list_size = len(self.list)
        else:
            self.list = items
            self.list_size = 0

        # Ensure selection is set (Lua defaults selected to 1)
        if self.selected is None and self.list_size > 0:
            self.selected = 1
        elif self.selected is not None and self.list_size > 0:
            if self.selected > self.list_size:
                self.selected = self.list_size

        # Default min/max to cover the full range
        if min_val is None:
            min_val = 1
        if max_val is None:
            max_val = self.list_size

        # Only trigger layout if changed items overlap the visible window
        # (matches Lua setItems which checks topItem/botItem)
        top_item = self.top_item
        bot_item = top_item + max(self.num_widgets, 1) - 1
        if not (max_val < top_item or min_val > bot_item):
            self.re_layout()

    setItems = set_items

    def add_item(self, item: Any) -> None:
        """Append an item to the end of the list."""
        self.list.append(item)
        self.list_size = len(self.list)
        self._update_widgets()
        self.re_layout()

    addItem = add_item

    def insert_item(self, item: Any, index: int) -> None:
        """
        Insert an item at 1-based *index*.

        Parameters
        ----------
        item : any
            The item to insert.
        index : int
            1-based position to insert at.
        """
        idx = max(0, min(index - 1, len(self.list)))
        self.list.insert(idx, item)
        self.list_size = len(self.list)
        self._update_widgets()
        self.re_layout()

    insertItem = insert_item

    def remove_item(self, item: Any) -> None:
        """Remove *item* from the list by identity."""
        try:
            self.list.remove(item)
        except ValueError as exc:
            log.debug("remove failed: %s", exc)
        self.list_size = len(self.list)
        self._update_widgets()
        self.re_layout()

    removeItem = remove_item

    def remove_item_at(self, index: int) -> None:
        """Remove the item at 1-based *index*."""
        idx = index - 1
        if 0 <= idx < len(self.list):
            del self.list[idx]
        self.list_size = len(self.list)
        self._update_widgets()
        self.re_layout()

    removeItemAt = remove_item_at

    def remove_all_items(self) -> None:
        """Remove all items from the list."""
        self.list.clear()
        self.list_size = 0
        self.widgets.clear()
        self.selected = None
        self.top_item = 1
        self.re_layout()

    removeAllItems = remove_all_items

    def replace_item(self, old_item: Any, new_item: Any) -> None:
        """Replace *old_item* with *new_item* in the list.

        Triggers a full re-layout so that widget bounds are recalculated,
        matching the Lua original's use of ``reLayout``.
        """
        for i, item in enumerate(self.list):
            if item is old_item:
                self.list[i] = new_item
                break
        self.re_layout()

    replaceItem = replace_item

    # ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------

    def get_selected_index(self) -> Optional[int]:
        """Return the 1-based index of the selected item, or None."""
        return self.selected

    getSelectedIndex = get_selected_index

    # ------------------------------------------------------------------
    # Closeable / Lock
    # ------------------------------------------------------------------

    def set_closeable(self, closeable: bool) -> None:
        """
        Set whether this menu can be closed via the "back" action.

        When *closeable* is ``False``, the ``back`` action listener is
        suppressed — useful for the home menu which should not be
        dismissed.

        Parameters
        ----------
        closeable : bool
            ``True`` (default) to allow closing, ``False`` to prevent.
        """
        self._closeable = closeable

    setCloseable = set_closeable

    def is_closeable(self) -> bool:
        """Return ``True`` if the menu can be closed."""
        return self._closeable

    isCloseable = is_closeable

    def lock(self, cancel: Any = None) -> None:
        """Lock the menu, suppressing all input until :meth:`unlock`.

        Matches Lua ``Menu:lock(cancel)``.  The *cancel* callback is
        called when the user presses back/home while locked, or after
        the GO_AS_CANCEL_TIME timeout (1500 ms) on a mouse click.

        Parameters
        ----------
        cancel : callable or any, optional
            A callback ``cancel(menu)`` invoked on escape.  If not
            provided, ``True`` is stored so the lock is still truthy.
        """
        self._locked = cancel if cancel is not None else True
        self._lock_cancel = cancel if callable(cancel) else None
        try:
            from jive.ui.framework import framework as fw

            self._lock_time = fw.get_ticks() if fw is not None else None
        except (ImportError, AttributeError):
            self._lock_time = None
        self.re_layout()

    def unlock(self) -> None:
        """Unlock the menu, re-enabling input.

        Matches Lua ``Menu:unlock()``.
        """
        if not self._locked:
            return
        self._locked = False
        self._lock_cancel = None
        self._lock_time = None
        self._lock_style = None
        self.re_layout()

    def is_locked(self) -> bool:
        """Return ``True`` if the menu is currently locked."""
        return bool(self._locked)

    isLocked = is_locked

    def get_selected_item(self) -> Any:
        """Return the currently selected item, or None."""
        if self.selected is not None and 1 <= self.selected <= self.list_size:
            return self.list[self.selected - 1]
        return None

    getSelectedItem = get_selected_item

    def set_selected_index(
        self,
        index: int,
        coerce: bool = True,
        no_scroll: bool = False,
    ) -> None:
        """
        Set the selected item by 1-based *index*.

        Matches the Lua original (Menu.lua ``setSelectedIndex``) which
        calls ``self:reLayout()`` unless *no_scroll* is set.

        Parameters
        ----------
        index : int
            1-based index to select.
        coerce : bool
            If True, clamp to valid range.
        no_scroll : bool
            If True, do not scroll the list and do not re-layout.
        """
        if self.list_size == 0:
            self.selected = None
            return

        if coerce:
            index = _coerce(index, self.list_size)

        if index < 1 or index > self.list_size:
            return

        old = self.selected
        self.selected = index

        if not no_scroll:
            self._scroll_list()
            self._fire_item_focus(old, self.selected)
            # Lua original: self:reLayout()
            self.re_layout()
        else:
            self._fire_item_focus(old, self.selected)
            self.re_draw()

    setSelectedIndex = set_selected_index

    def _selected_item_widget(self) -> Optional[Widget]:
        """Return the widget for the currently selected item, or None."""
        if self.selected is not None and self.widgets:
            widget_idx = self.selected - self.top_item
            if 0 <= widget_idx < len(self.widgets):
                return self.widgets[widget_idx]  # type: ignore[no-any-return]
        if self.widgets:
            return self.widgets[0]  # type: ignore[no-any-return]
        return None

    # ------------------------------------------------------------------
    # Scrolling
    # ------------------------------------------------------------------

    def scroll_by(
        self,
        scroll: int,
        allow_scroll_past: bool = False,
        update_scrollbar: bool = True,
    ) -> None:
        """
        Scroll the menu by *scroll* items.

        Negative values scroll up, positive values scroll down.

        Matches the Lua original (Menu.lua ``scrollBy``) which calls
        ``_scrollList(self)`` followed by ``self:reLayout()``.  The
        ``reLayout`` triggers ``_layout`` → ``_updateWidgets`` so that
        widget positions are recalculated for the new scroll offset.
        """
        if self.selected is None:
            return

        new_selected = self.selected + scroll
        new_selected = _coerce(new_selected, self.list_size)

        if new_selected != self.selected:
            old = self.selected
            self.selected = new_selected
            self._scroll_list()
            self._fire_item_focus(old, self.selected)
            # Lua original calls self:reLayout() here — this triggers
            # _layout() which recalculates num_widgets, calls
            # _update_widgets(), repositions child widget bounds, and
            # updates the scrollbar.  Using re_draw() alone would leave
            # widget bounds stale after the scroll offset changes.
            self.re_layout()

    scrollBy = scroll_by

    def set_header_widget(self, widget: Any) -> None:
        """Set an optional header widget displayed above the menu items."""
        self.header_widget = widget
        if widget is not None:
            widget.parent = self
        self.re_layout()

    setHeaderWidget = set_header_widget

    def _scroll_list(self) -> None:
        """Adjust top_item so that the selected item is visible."""
        if self.selected is None or self.num_widgets == 0:
            return

        # Scroll down
        while (
            self.selected >= self.top_item + self.num_widgets
            and self.top_item + self.num_widgets <= self.list_size
        ):
            self.top_item += self.items_per_line

        # Scroll up
        while self.selected < self.top_item and self.top_item > 1:
            self.top_item -= self.items_per_line

        self.top_item = max(1, self.top_item)

    def _update_scrollbar(self) -> None:
        """Update the scrollbar position based on current state."""
        if self.scrollbar is None:
            return

        temp_offset = self.pixel_offset_y
        temp_list_size = self.list_size

        if self.items_per_line > 1:
            temp_offset *= self.items_per_line
            if temp_list_size % self.items_per_line != 0:
                temp_list_size = (
                    temp_list_size - (temp_list_size % self.items_per_line) + self.items_per_line
                )

        max_val = temp_list_size * self.item_height
        pos = (self.top_item - 1) * self.item_height - temp_offset
        size_val = self.num_widgets * self.item_height

        if size_val + pos > max_val:
            pos = max_val - size_val

        self.scrollbar.set_scrollbar(0, max_val, pos, size_val)

    def set_hide_scrollbar(self, setting: bool) -> None:
        """Control scrollbar visibility."""
        self.hide_scrollbar = setting

    setHideScrollbar = set_hide_scrollbar

    def set_pixel_offset_y(self, value: int) -> None:
        """Set the pixel offset for smooth scrolling."""
        self.pixel_offset_y = value

    def reset_drag_data(self) -> None:
        """Reset drag/pixel-offset state."""
        self.set_pixel_offset_y(0)
        self.drag_y_since_shift = 0

    # ------------------------------------------------------------------
    # Drag support
    # ------------------------------------------------------------------

    def handle_drag(
        self,
        drag_amount_y: int,
        by_item_only: bool = False,
        force_accel: bool = False,
    ) -> None:
        """Handle drag gesture for smooth scrolling."""
        if drag_amount_y == 0 or self.item_height <= 0:
            return

        self.drag_y_since_shift += drag_amount_y

        abs_shift = abs(self.drag_y_since_shift // self.item_height)
        if abs_shift > 0:
            item_shift = self.drag_y_since_shift // self.item_height

            if self.items_per_line > 1:
                item_shift *= self.items_per_line

            self.drag_y_since_shift = self.drag_y_since_shift % self.item_height

            if item_shift > 0 and self.current_shift_direction <= 0:
                if self.selected is not None and self.num_widgets > 0:
                    self.set_selected_index(self.top_item + self.num_widgets - 2, no_scroll=True)
                self.current_shift_direction = 1
            elif item_shift < 0 and self.current_shift_direction >= 0:
                if self.selected is not None:
                    self.set_selected_index(self.top_item + 1, no_scroll=True)
                self.current_shift_direction = -1

            if (self.is_at_top() and item_shift < 0) or (self.is_at_bottom() and item_shift > 0):
                self.reset_drag_data()
                self._update_scrollbar()
            else:
                if (self.top_item + item_shift < 1) or (
                    self.top_item + item_shift + self.num_widgets >= self.list_size + 1
                ):
                    self.reset_drag_data()
                else:
                    if not by_item_only:
                        self.set_pixel_offset_y(-1 * self.drag_y_since_shift)
                    else:
                        self.set_pixel_offset_y(0)

                self.scroll_by(item_shift, True, False)
                self._update_scrollbar()
        else:
            if not by_item_only:
                self.set_pixel_offset_y(-1 * self.drag_y_since_shift)
            self.re_draw()

    def is_at_bottom(self) -> bool:
        """Return True if scrolled to the bottom."""
        if self.num_widgets == 0:
            return True
        return self.top_item + self.num_widgets > self.list_size

    isAtBottom = is_at_bottom

    def is_at_top(self) -> bool:
        """Return True if scrolled to the top."""
        return self.top_item <= 1

    isAtTop = is_at_top

    # ------------------------------------------------------------------
    # Widget update
    # ------------------------------------------------------------------

    def _update_widgets(self) -> None:
        """
        Synchronize the visible widget list with the underlying data.

        When an ``item_renderer`` callback is set (as in Lua's Menu),
        it is called with ``(menu, list, widgets, indexList, indexSize)``
        to create/update the visible widgets.

        Subclasses (SimpleMenu) override this entirely.
        """
        if self.item_renderer is None:
            return

        ipl = self.items_per_line or 1
        index_size = self.num_widgets + ipl  # one extra for smooth scrolling
        min_idx = self.top_item
        max_idx = min(self.top_item + index_size - 1, self.list_size)
        actual_size = max(max_idx - min_idx + 1, 0)

        index_list = list(range(min_idx, max_idx + 1))

        self.item_renderer(self, self.list, self.widgets, index_list, actual_size)

        # Set parent linkage for rendered widgets
        for i in range(actual_size):
            if i < len(self.widgets) and self.widgets[i] is not None:
                self.widgets[i].parent = self

        # Unreference menu widgets out of stage — Lua Menu.lua L1797-1799
        del self.widgets[actual_size:]

        self._apply_selection_style()

        # Update scrollbar position — matches Lua Menu.lua L1847
        self._update_scrollbar()

    def _apply_selection_style(self) -> None:
        """Apply style modifiers to the selected item widget.

        Mirrors Lua ``_updateWidgets`` lines 1801-1826:
        - Clear modifier on previously selected widget
        - Set ``"selected"`` / ``"pressed"`` / ``"locked"`` on the new one
        """
        next_selected = self._selected_item_widget()

        # Clear old selection
        if self._last_selected is not None and self._last_selected is not next_selected:
            if hasattr(self._last_selected, "set_style_modifier"):
                self._last_selected.set_style_modifier(None)

        # Apply modifier to new selection
        if next_selected is not None:
            if self._locked:
                modifier = "locked"
            elif self.use_pressed_style:
                modifier = "pressed"
            else:
                modifier = "selected"
            if hasattr(next_selected, "set_style_modifier"):
                next_selected.set_style_modifier(modifier)

        self._last_selected = next_selected

    # ------------------------------------------------------------------
    # Focus event dispatch on selection change
    # ------------------------------------------------------------------

    def _fire_item_focus(
        self,
        old_index: Optional[int],
        new_index: Optional[int],
    ) -> None:
        """Dispatch ``EVENT_FOCUS_LOST`` / ``EVENT_FOCUS_GAINED`` via the
        item listener when the selected index changes.

        This mirrors the Lua Menu ``_update`` which calls
        ``_itemListener(self, nextSelected, Event(EVENT_FOCUS_GAINED))``
        whenever the selected index changes.
        """
        if old_index == new_index:
            return
        if self.item_listener is None:
            return

        from jive.ui.event import Event

        # Fire FOCUS_LOST on the previously selected item
        if old_index is not None and 1 <= old_index <= self.list_size:
            old_widget = None
            widget_idx = old_index - self.top_item
            if 0 <= widget_idx < len(self.widgets):
                old_widget = self.widgets[widget_idx]
            try:
                self.item_listener(
                    self,
                    self.list,
                    old_widget,
                    old_index,
                    Event(int(EVENT_FOCUS_LOST)),
                )
            except Exception as exc:
                log.warning("item_listener FOCUS_LOST: %s", exc)

        # Fire FOCUS_GAINED on the newly selected item
        if new_index is not None and 1 <= new_index <= self.list_size:
            new_widget = None
            widget_idx = new_index - self.top_item
            if 0 <= widget_idx < len(self.widgets):
                new_widget = self.widgets[widget_idx]
            try:
                self.item_listener(
                    self,
                    self.list,
                    new_widget,
                    new_index,
                    Event(int(EVENT_FOCUS_GAINED)),
                )
            except Exception as exc:
                log.warning("item_listener FOCUS_GAINED: %s", exc)

    # ------------------------------------------------------------------
    # Item listener helper (matches Lua _itemListener)
    # ------------------------------------------------------------------

    def _item_listener(self, item: Any, event: Any) -> int:
        """Forward event to the item listener callback, then to the item widget.

        Matches Lua ``_itemListener(self, item, event)`` which first calls
        ``self.itemListener(self, self.list, item, self.selected, event)``
        and, if that returns EVENT_UNUSED, falls through to ``item:_event(event)``.
        """
        r = int(EVENT_UNUSED)
        if item is None:
            return r

        if self.item_listener is not None:
            try:
                r = self.item_listener(self, self.list, item, self.selected or 1, event)
            except Exception as exc:
                log.error("item_listener error: %s", exc, exc_info=True)
                r = int(EVENT_UNUSED)

        if r == int(EVENT_UNUSED):
            try:
                r = item._event(event)
            except Exception:
                r = int(EVENT_UNUSED)

        return r

    # ------------------------------------------------------------------
    # Action handlers (called from _event_handler)
    # ------------------------------------------------------------------

    def _go_action(self, event: Any = None) -> int:
        """Handle the 'go' action — dispatch EVENT_ACTION to selected item.

        Matches Lua: ``local r = self:dispatchNewEvent(EVENT_ACTION)``
        which sends EVENT_ACTION through _itemListener → item._event.
        """
        from jive.ui.event import Event as Evt

        item = self._selected_item_widget()
        if item is not None:
            action_evt = Evt(int(EVENT_ACTION))
            r = self._item_listener(item, action_evt)
            if r != int(EVENT_UNUSED):
                return r
        # Lua plays BUMP sound and calls bumpRight() here; skipped for now
        return int(EVENT_UNUSED)

    def _back_action(self, event: Any = None) -> int:
        """Handle the 'back' action — hide the window if closeable.

        Matches Lua lines 561-570: checks ``self.closeable`` flag.
        """
        if self._closeable:
            window = self.get_window()
            if window is not None:
                window.hide()
                return int(EVENT_CONSUME)
        # Not closeable — would play BUMP in Lua
        return int(EVENT_CONSUME)

    def _page_up_action(self, event: Any = None) -> int:
        """Scroll up by one page.

        Matches Lua: top item becomes bottom item.
        """
        if self.selected is not None and self.selected > 1:
            self.set_selected_index(self.top_item, coerce=True)
            self.scroll_by(-(self.num_widgets - 2))
        return int(EVENT_CONSUME)

    def _page_down_action(self, event: Any = None) -> int:
        """Scroll down by one page.

        Matches Lua: bottom item becomes top item.
        """
        if self.selected is None or self.selected < self.list_size:
            self.set_selected_index(self.top_item + self.num_widgets - 1, coerce=True)
            self.scroll_by(self.num_widgets - 2)
        return int(EVENT_CONSUME)

    # ------------------------------------------------------------------
    # Event handling — single handler for EVENT_ALL (matches Lua)
    # ------------------------------------------------------------------

    def _event_handler(self, event: Event) -> int:
        """Handle all events, matching the Lua ``_eventHandler``.

        The Lua Menu registers a single ``EVENT_ALL`` listener that handles
        SCROLL, IR, ACTION, KEY_PRESS, MOUSE, FOCUS, SHOW, etc. inline.
        """
        etype = event.get_type()

        # -- SCROLL --
        if etype == int(EVENT_SCROLL):
            if self._locked is None or not self._locked:
                self.scroll_by(event.get_scroll())
            return int(EVENT_CONSUME)

        # -- IR DOWN / REPEAT --
        if etype in (int(EVENT_IR_DOWN), int(EVENT_IR_REPEAT)):
            if hasattr(event, "is_ir_code"):
                if event.is_ir_code("arrow_up") or event.is_ir_code("arrow_down"):
                    if not self._locked:
                        scroll_amount = -1 if event.is_ir_code("arrow_up") else 1
                        self.scroll_by(scroll_amount)
                    return int(EVENT_CONSUME)
            return int(EVENT_UNUSED)

        # -- ACTION (matches Lua lines 475-589) --
        if etype == int(ACTION):
            action = event.get_action()

            # Locked state — only back/go_home can unlock (Lua L478-487)
            if self._locked:
                log.debug("Menu LOCKED, action=%s — consuming", action)
                if action in ("back", "go_home", "go_home_or_now_playing"):
                    # Call cancel callback before unlocking (Lua L481-482)
                    if self._lock_cancel is not None:
                        try:
                            self._lock_cancel()
                        except TypeError:
                            try:
                                self._lock_cancel(self)
                            except Exception:
                                pass
                    self.unlock()
                    return int(EVENT_CONSUME)
                # All other actions consumed while locked
                return int(EVENT_CONSUME)

            # First forward action to selected item via _itemListener
            # (Lua line 497: local r = _itemListener(self, _selectedItem(self), event))
            item = self._selected_item_widget()
            r = self._item_listener(item, event)
            if r != int(EVENT_UNUSED):
                return r

            # Default action handling
            if action == "page_up":
                return self._page_up_action(event)

            elif action == "page_down":
                return self._page_down_action(event)

            elif action == "go":
                return self._go_action(event)

            elif action == "back":
                return self._back_action(event)

            # Unhandled action — pass through
            return int(EVENT_UNUSED)

        # -- KEY_DOWN (immediate response for arrow keys) --
        # React on key-down instead of key-up to eliminate the delay
        # caused by waiting for the key release before scrolling.
        if etype == int(EVENT_KEY_DOWN):
            keycode = event.get_keycode()

            # UP / DOWN — scroll immediately on key-down
            scroll = None
            if keycode == int(KEY_UP):
                scroll = -1 * (self.items_per_line or 1)
            elif keycode == int(KEY_DOWN):
                scroll = 1 * (self.items_per_line or 1)

            if scroll is not None and not self._locked:
                self.scroll_by(scroll)
                return int(EVENT_CONSUME)

            # Don't consume other KEY_DOWN events — let them
            # fall through to KEY_PRESS handling on key-up.
            return int(EVENT_UNUSED)

        # -- KEY_PRESS (matches Lua lines 592-632) --
        if etype == int(EVENT_KEY_PRESS):
            keycode = event.get_keycode()

            # KEY_LEFT / KEY_RIGHT — push back/go actions for single-column menus
            # (Lua lines 597-605)
            if keycode in (int(KEY_LEFT), int(KEY_RIGHT)):
                ipl = self.items_per_line or 1
                if ipl == 1 or (
                    keycode == int(KEY_LEFT) and (self.selected is None or self.selected == 1)
                ):
                    from jive.ui.framework import framework as fw

                    if keycode == int(KEY_LEFT):
                        fw.push_action("back")
                    else:
                        fw.push_action("go")
                    return int(EVENT_CONSUME)
                else:
                    # Grid mode: scroll left/right
                    scroll = -1 if keycode == int(KEY_LEFT) else 1
                    if not self._locked:
                        self.scroll_by(scroll)
                    return int(EVENT_CONSUME)

            # KEY_UP / KEY_DOWN — already handled on KEY_DOWN above,
            # consume here to prevent double-scroll.
            if keycode in (int(KEY_UP), int(KEY_DOWN)):
                return int(EVENT_CONSUME)

            # Forward remaining key presses to selected item (Lua lines 625-631)
            if not self._locked:
                item = self._selected_item_widget()
                r = self._item_listener(item, event)
                if r != int(EVENT_UNUSED):
                    return r

            return int(EVENT_UNUSED)

        # -- FOCUS --
        if etype == int(EVENT_FOCUS_GAINED):
            if self.selected is None and self.list_size > 0:
                self.selected = 1
            self.re_draw()
            return int(EVENT_CONSUME)

        if etype == int(EVENT_FOCUS_LOST):
            self.re_draw()
            return int(EVENT_CONSUME)

        # -- MOUSE events --
        if etype == int(EVENT_MOUSE_HOLD):
            # Lua: long-press in the body area pushes "add" which opens
            # the context menu (mapped to "more" in _ACTION_TO_ACTION_NAME).
            if self.mouse_state == MOUSE_DOWN:
                scrollbar_inside = False
                if self.scrollbar is not None and hasattr(self.scrollbar, "mouse_inside"):
                    scrollbar_inside = self.scrollbar.mouse_inside(event)
                if not scrollbar_inside:
                    from jive.ui.framework import framework as fw

                    if fw is not None:
                        fw.push_action("add")
            return int(EVENT_CONSUME)

        if etype == int(EVENT_MOUSE_PRESS):
            return int(EVENT_CONSUME)

        if etype == int(EVENT_MOUSE_MOVE):
            return int(EVENT_CONSUME)

        if etype == int(EVENT_MOUSE_DOWN):
            self.mouse_state = MOUSE_DOWN
            try:
                x, y = event.get_mouse()[:2]
                bx, by, bw, bh = self.get_bounds()
                self.mouse_down_bounds_x = x - bx
                self.mouse_down_bounds_y = y - by
            except Exception as exc:
                log.warning("mouse_down bounds: %s", exc)
            return int(EVENT_CONSUME)

        if etype == int(EVENT_MOUSE_UP):
            # Lua L918-923: locked timeout escape on mouse click
            if self._locked and self._lock_time is not None:
                try:
                    from jive.ui.framework import framework as fw

                    now = fw.get_ticks() if fw is not None else 0
                    if now > self._lock_time + 1500:  # GO_AS_CANCEL_TIME
                        if self._lock_cancel is not None:
                            try:
                                self._lock_cancel()
                            except TypeError:
                                try:
                                    self._lock_cancel(self)
                                except Exception:
                                    pass
                        self.unlock()
                        return int(EVENT_CONSUME)
                except (ImportError, AttributeError):
                    pass

            if self.mouse_state == MOUSE_DOWN:
                # Simple tap — select and activate
                self._select_item_under_pointer()
                try:
                    r = self._go_action()
                except Exception as exc:
                    log.warn("_go_action error: %s", exc)
                    r = int(EVENT_UNUSED)
                self.mouse_state = MOUSE_COMPLETE
                self.use_pressed_style = False
                self.re_draw()
                return int(EVENT_CONSUME)

            self.mouse_state = MOUSE_COMPLETE
            self.use_pressed_style = False
            self.re_draw()
            return int(EVENT_CONSUME)

        if etype == int(EVENT_MOUSE_DRAG):
            self.mouse_state = MOUSE_DRAG
            return int(EVENT_CONSUME)

        return int(EVENT_UNUSED)

    def _select_item_under_pointer(self) -> bool:
        """Select the menu item under the mouse pointer (from last down)."""
        if self.item_height <= 0:
            return False

        y = self.mouse_down_bounds_y
        i = (y - self.pixel_offset_y) // self.item_height
        item_shift = i

        if self.items_per_line > 1:
            item_shift *= self.items_per_line
            x = self.mouse_down_bounds_x
            bx, by, bw, bh = self.get_bounds()
            if self.items_per_line > 0 and bw > 0:
                col = x // (bw // self.items_per_line)
                item_shift += min(col, self.items_per_line - 1)

        temp_visible = self.num_widgets + 1
        if self.items_per_line > 1:
            temp_visible = self.num_widgets + self.items_per_line

        if 0 <= item_shift < temp_visible:
            selected_index = self.top_item + item_shift
            if selected_index <= self.list_size:
                self.use_pressed_style = True
                self.set_selected_index(selected_index, no_scroll=True)
                return True
        return False

    # ------------------------------------------------------------------
    # Skin (jiveL_menu_skin)
    # ------------------------------------------------------------------

    def re_skin(self) -> None:
        """Reset all menu-specific cached skin state, then call super.

        The C original ``jiveL_menu_skin`` does **not** touch the
        scrollbar — it is re-skinned independently via
        ``style_changed`` → ``_mark_dirty_recursive``.  Calling
        ``scrollbar.re_skin()`` here would eagerly reset the
        scrollbar's cached tiles / preferred_bounds, which is both
        unnecessary and can cause transient blank-scrollbar states
        during skin switches.
        """
        self.item_height = 20
        self._max_height = WH_NIL
        self._font = None
        self._fg = 0x000000FF
        self._has_scrollbar = False
        super().re_skin()

    def _skin(self) -> None:
        from jive.ui.style import (
            style_color,
            style_font,
            style_int,
        )

        self._widget_pack()

        self.item_height = style_int(self, "itemHeight", 20)
        self._max_height = style_int(self, "maxHeight", WH_NIL)

        self.items_per_line = style_int(self, "itemsPerLine", 1)
        if self.items_per_line < 1:
            self.items_per_line = 1

        self._font = style_font(self, "font")

        fg_val, _ = style_color(self, "fg", 0x000000FF)
        self._fg = fg_val

        # Calculate number of visible widgets
        bx, by, bw, bh = self.get_bounds()
        if self.item_height > 0:
            self.num_widgets = (bh // self.item_height) * self.items_per_line
        else:
            self.num_widgets = 0

    # ------------------------------------------------------------------
    # Layout (jiveL_menu_layout)
    # ------------------------------------------------------------------

    def _layout(self) -> None:
        bx, by, bw, bh = self.get_bounds()
        pl, pt, pr, pb = self.get_padding()

        # Number of visible widgets
        if self.item_height > 0:
            self.num_widgets = (bh // self.item_height) * self.items_per_line
        else:
            self.num_widgets = 0

        # Update widget contents
        self._update_widgets()

        # Determine if scrollbar is needed
        self._has_scrollbar = not self.hide_scrollbar and self.list_size > self.num_widgets

        log.debug(
            "Menu._layout: style=%s bounds=(%d,%d,%d,%d) "
            "itemHeight=%d num_widgets=%d list_size=%d top_item=%d selected=%s "
            "hide_scrollbar=%s _has_scrollbar=%s widgets_len=%d",
            self.style,
            bx,
            by,
            bw,
            bh,
            self.item_height,
            self.num_widgets,
            self.list_size,
            self.top_item,
            self.selected,
            self.hide_scrollbar,
            self._has_scrollbar,
            len(self.widgets),
        )

        # Measure scrollbar
        sw = 0
        sh = bh
        sb_left = sb_top = sb_right = sb_bottom = 0

        if self._has_scrollbar and self.scrollbar is not None:
            sb_bounds = self.scrollbar.get_preferred_bounds()
            if sb_bounds[2] is not None and sb_bounds[2] != WH_FILL:
                sw = sb_bounds[2]
            if sb_bounds[3] is not None and sb_bounds[3] != WH_FILL:
                sh = sb_bounds[3]

            sb_border = self.scrollbar.get_border()
            sb_left, sb_top, sb_right, sb_bottom = (
                sb_border[0],
                sb_border[1],
                sb_border[2],
                sb_border[3],
            )

            sw += sb_left + sb_right
            sh += sb_top + sb_bottom

        sx = bx + bw - sw + sb_left
        sy = by + sb_top

        # Measure header widget
        hww = hwh = 0
        hw_left = hw_top = hw_right = hw_bottom = 0

        if self.header_widget is not None:
            hw_bounds = self.header_widget.get_preferred_bounds()
            if hw_bounds[2] is not None and hw_bounds[2] != WH_FILL:
                hww = hw_bounds[2]
            if hw_bounds[3] is not None and hw_bounds[3] != WH_FILL:
                hwh = hw_bounds[3]

            hw_border = self.header_widget.get_border()
            hw_left, hw_top, hw_right, hw_bottom = (
                hw_border[0],
                hw_border[1],
                hw_border[2],
                hw_border[3],
            )

            hww += hw_left + hw_right
            hwh += hw_top + hw_bottom

        hwx = bx + hw_left
        hwy = by + hw_top

        # Position item widgets
        x = bx + pl
        y = by + pt
        num_in_line = 0

        item_w = (bw - pl - pr - sw) // self.items_per_line if self.items_per_line > 0 else 0

        for widget in self.widgets:
            if hasattr(widget, "set_bounds"):
                widget.set_bounds(x, y, item_w, self.item_height)

            # Trigger recursive skin + layout on child widgets (e.g. Group)
            # so that their sub-widgets get ordered and positioned.
            # In the C original this happens automatically via the
            # top-down layout pass; in Python we must call explicitly.
            if hasattr(widget, "_skin"):
                widget._skin()
            if hasattr(widget, "_layout"):
                widget._layout()

            num_in_line += 1
            if num_in_line >= self.items_per_line:
                num_in_line = 0
                x = bx + pl
                y += self.item_height
            else:
                x += item_w

        # Position scrollbar
        if self._has_scrollbar and self.scrollbar is not None:
            self.scrollbar.set_bounds(
                sx,
                sy,
                sw - sb_left - sb_right,
                sh - sb_top - sb_bottom,
            )

        # Position header widget
        if self.header_widget is not None:
            if hasattr(self.header_widget, "set_bounds"):
                self.header_widget.set_bounds(
                    hwx,
                    hwy,
                    hww - hw_left - hw_right,
                    hwh - hw_top - hw_bottom,
                )

    # ------------------------------------------------------------------
    # Draw (jiveL_menu_draw)
    # ------------------------------------------------------------------

    def draw(self, surface: Surface, layer: int = LAYER_ALL) -> None:
        draw_layer = layer & self._layer

        bx, by, bw, bh = self.get_bounds()

        # Clip to widget bounds
        surface.push_clip(bx, by, bw, bh)

        try:
            # Draw item widgets
            for widget in self.widgets:
                if hasattr(widget, "draw"):
                    widget.draw(surface, layer)
        finally:
            surface.pop_clip()

        # Draw scrollbar
        if self._has_scrollbar and self.scrollbar is not None:
            self.scrollbar.draw(surface, layer)

        # Draw acceleration key letter
        if draw_layer and self.accel_key and self._font is not None:
            from jive.ui.surface import Surface as SurfaceClass

            txt_surf = self._font.render(self.accel_key, self._fg)
            if txt_surf is not None:
                if not isinstance(txt_surf, SurfaceClass):
                    txt_surf = SurfaceClass(txt_surf)  # type: ignore[assignment]
                tw, th = txt_surf.get_size()
                x = (bx + bw - tw) // 2
                y = (by + bh - th) // 2
                surface.blit(txt_surf, x, y)  # type: ignore[arg-type]

        # Draw header widget
        if self.header_widget is not None and hasattr(self.header_widget, "draw"):
            self.header_widget.draw(surface, layer)

    # ------------------------------------------------------------------
    # Iterate (jiveL_menu_iterate)
    # ------------------------------------------------------------------

    def iterate(self, closure: Callable[..., Any], include_hidden: bool = False) -> None:
        """Iterate over child widgets (items, scrollbar, header)."""
        for widget in self.widgets:
            closure(widget)

        if self.scrollbar is not None:
            closure(self.scrollbar)

        if self.header_widget is not None:
            closure(self.header_widget)

    # ------------------------------------------------------------------
    # Preferred bounds (jiveL_menu_get_preferred_bounds)
    # ------------------------------------------------------------------

    def get_preferred_bounds(
        self,
    ) -> Tuple[Optional[int], Optional[int], Optional[int], Optional[int]]:
        self.check_skin()

        pb = self.preferred_bounds
        px = pb[0] if pb[0] is not None and pb[0] != XY_NIL else None
        py = pb[1] if pb[1] is not None and pb[1] != XY_NIL else None
        pw = pb[2] if pb[2] is not None and pb[2] != WH_NIL else None

        if self._max_height != WH_NIL:
            # Calculate max height from list size
            if self.items_per_line > 0:
                max_h = (self.list_size * self.item_height) // self.items_per_line
            else:
                max_h = self.list_size * self.item_height
            ph = min(max_h, self._max_height)
        elif pb[3] is not None and pb[3] != WH_NIL:
            ph = pb[3]
        else:
            ph = None

        return (px, py, pw, ph)

    # ------------------------------------------------------------------
    # jive_widget_pack — read common style properties
    # ------------------------------------------------------------------

    def _widget_pack(self) -> None:
        """
        Read common widget style properties: preferred bounds,
        padding, border, layer, z-order, hidden.
        """
        from jive.ui.style import style_insets, style_int

        sx = style_int(self, "x", XY_NIL)
        sy = style_int(self, "y", XY_NIL)
        sw_val = style_int(self, "w", WH_NIL)
        sh_val = style_int(self, "h", WH_NIL)

        self.preferred_bounds[0] = None if sx == XY_NIL else sx
        self.preferred_bounds[1] = None if sy == XY_NIL else sy
        self.preferred_bounds[2] = None if sw_val == WH_NIL else sw_val
        self.preferred_bounds[3] = None if sh_val == WH_NIL else sh_val

        pad = style_insets(self, "padding", [0, 0, 0, 0])
        self.padding[:] = pad[:4] if len(pad) >= 4 else pad + [0] * (4 - len(pad))

        bdr = style_insets(self, "border", [0, 0, 0, 0])
        self.border[:] = bdr[:4] if len(bdr) >= 4 else bdr + [0] * (4 - len(bdr))

        self._layer = style_int(self, "layer", int(LAYER_CONTENT))
        self._z_order = style_int(self, "zOrder", 0)
        self._hidden = bool(style_int(self, "hidden", 0))

    # ------------------------------------------------------------------
    # Representation
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        sel = self.selected or 0
        return f"Menu(items={self.list_size}, selected={sel}, top={self.top_item})"

    def __str__(self) -> str:
        return self.__repr__()
