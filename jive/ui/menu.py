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
    from jive.ui.tile import JiveTile

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

    def __init__(
        self,
        style: str,
        item_listener: Optional[Callable[..., int]] = None,
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
        self._locked: bool = False
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

        # Peer state (from C struct MenuWidget)
        self._font: Optional[Font] = None
        self._fg: int = 0x000000FF
        self._max_height: int = WH_NIL
        self._has_scrollbar: bool = False

        # Scrollbar child widget
        from jive.ui.slider import Scrollbar

        self.scrollbar: Scrollbar = Scrollbar("scrollbar")
        self.scrollbar.parent = self

        # Item listener callback
        self.item_listener: Optional[Callable[..., int]] = item_listener

        # Action listeners
        self.add_action_listener("go", self, Menu._go_action)
        self.add_action_listener("back", self, Menu._back_action)
        self.add_action_listener("page_up", self, Menu._page_up_action)
        self.add_action_listener("page_down", self, Menu._page_down_action)

        # Event listener for scroll, key, mouse, IR
        self.add_listener(
            EVENT_SCROLL
            | EVENT_KEY_PRESS
            | EVENT_MOUSE_ALL
            | EVENT_IR_DOWN
            | EVENT_IR_REPEAT
            | EVENT_FOCUS_GAINED
            | EVENT_FOCUS_LOST,
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

    def set_items(self, items: List[Any]) -> None:
        """
        Replace the entire item list.

        Parameters
        ----------
        items : list
            New list of items.
        """
        self.list = list(items)
        self.list_size = len(self.list)
        self._update_widgets()
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
        except ValueError:
            pass
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
        """Replace *old_item* with *new_item* in the list."""
        for i, item in enumerate(self.list):
            if item is old_item:
                self.list[i] = new_item
                break
        self._update_widgets()
        self.re_draw()

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

    def lock(self, style: Optional[str] = None) -> None:
        """
        Lock the menu, suppressing all input until :meth:`unlock` is
        called.

        This is used to prevent user interaction while a long-running
        operation (e.g. applet loading) is in progress.

        Parameters
        ----------
        style : str, optional
            An optional style override applied while locked (e.g. to
            show a spinner).
        """
        self._locked = True
        self._lock_style = style

    def unlock(self) -> None:
        """
        Unlock the menu, re-enabling input.
        """
        self._locked = False
        self._lock_style = None

    def is_locked(self) -> bool:
        """Return ``True`` if the menu is currently locked."""
        return self._locked

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

        Parameters
        ----------
        index : int
            1-based index to select.
        coerce : bool
            If True, clamp to valid range.
        no_scroll : bool
            If True, do not scroll the list.
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

        self._update_widgets()
        self.re_draw()

    setSelectedIndex = set_selected_index

    def _selected_item_widget(self) -> Optional[Widget]:
        """Return the widget for the currently selected item, or None."""
        if self.selected is not None and self.widgets:
            widget_idx = self.selected - self.top_item
            if 0 <= widget_idx < len(self.widgets):
                return self.widgets[widget_idx]
        if self.widgets:
            return self.widgets[0]
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
        """
        if self.selected is None:
            return

        new_selected = self.selected + scroll
        new_selected = _coerce(new_selected, self.list_size)

        if new_selected != self.selected:
            self.selected = new_selected
            self._scroll_list()
            self._update_widgets()
            if update_scrollbar:
                self._update_scrollbar()
            self.re_draw()

    scrollBy = scroll_by

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
                    temp_list_size
                    - (temp_list_size % self.items_per_line)
                    + self.items_per_line
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
                    self.set_selected_index(
                        self.top_item + self.num_widgets - 2, no_scroll=True
                    )
                self.current_shift_direction = 1
            elif item_shift < 0 and self.current_shift_direction >= 0:
                if self.selected is not None:
                    self.set_selected_index(self.top_item + 1, no_scroll=True)
                self.current_shift_direction = -1

            if (self.is_at_top() and item_shift < 0) or (
                self.is_at_bottom() and item_shift > 0
            ):
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

        Subclasses (SimpleMenu) override this to create/update widgets
        from data items.
        """
        pass  # Base Menu relies on widgets being set directly

    # ------------------------------------------------------------------
    # Action handlers
    # ------------------------------------------------------------------

    def _go_action(self) -> int:
        """Handle the 'go' action — forward to selected item."""
        item = self._selected_item_widget()
        if item is not None:
            from jive.ui.event import Event

            evt = Event(EVENT_ACTION)
            r = item._event(evt)
            if r != EVENT_UNUSED:
                return r
        return EVENT_UNUSED

    def _back_action(self) -> int:
        """Handle the 'back' action — hide the window."""
        window = self.get_window()
        if window is not None:
            window.hide()
            return EVENT_CONSUME
        return EVENT_UNUSED

    def _page_up_action(self) -> int:
        """Scroll up by one page."""
        if self.num_widgets > 0:
            self.scroll_by(-self.num_widgets)
        return EVENT_CONSUME

    def _page_down_action(self) -> int:
        """Scroll down by one page."""
        if self.num_widgets > 0:
            self.scroll_by(self.num_widgets)
        return EVENT_CONSUME

    # ------------------------------------------------------------------
    # Event handling
    # ------------------------------------------------------------------

    def _event_handler(self, event: Event) -> int:
        etype = event.get_type()

        if etype == EVENT_SCROLL:
            self.scroll_by(event.get_scroll())
            return EVENT_CONSUME

        if etype == EVENT_KEY_PRESS:
            keycode = event.get_keycode()

            if keycode == KEY_UP:
                self.scroll_by(-1)
                return EVENT_CONSUME
            elif keycode == KEY_DOWN:
                self.scroll_by(1)
                return EVENT_CONSUME
            elif keycode == KEY_PAGE_UP:
                return self._page_up_action()
            elif keycode == KEY_PAGE_DOWN:
                return self._page_down_action()
            elif keycode == KEY_GO:
                return self._go_action()

            return EVENT_UNUSED

        if etype == EVENT_FOCUS_GAINED:
            if self.selected is None and self.list_size > 0:
                self.selected = 1
            self.re_draw()
            return EVENT_CONSUME

        if etype == EVENT_FOCUS_LOST:
            self.re_draw()
            return EVENT_CONSUME

        if etype in (EVENT_MOUSE_PRESS, EVENT_MOUSE_HOLD, EVENT_MOUSE_MOVE):
            return EVENT_CONSUME

        if etype == EVENT_MOUSE_DOWN:
            self.mouse_state = MOUSE_DOWN
            try:
                x, y = event.get_mouse()[:2]
                bx, by, bw, bh = self.get_bounds()
                self.mouse_down_bounds_x = x - bx
                self.mouse_down_bounds_y = y - by
            except Exception:
                pass
            return EVENT_CONSUME

        if etype == EVENT_MOUSE_UP:
            if self.mouse_state == MOUSE_DOWN:
                # Simple tap — select and activate
                self._select_item_under_pointer()
                r = self._go_action()
                self.mouse_state = MOUSE_COMPLETE
                self.use_pressed_style = False
                self.re_draw()
                return EVENT_CONSUME if r == EVENT_UNUSED else r

            self.mouse_state = MOUSE_COMPLETE
            self.use_pressed_style = False
            self.re_draw()
            return EVENT_CONSUME

        if etype == EVENT_MOUSE_DRAG:
            self.mouse_state = MOUSE_DRAG
            return EVENT_CONSUME

        if etype & EVENT_IR_ALL:
            if hasattr(event, "is_ir_code"):
                if event.is_ir_code("arrow_up"):
                    self.scroll_by(-1)
                    return EVENT_CONSUME
                elif event.is_ir_code("arrow_down"):
                    self.scroll_by(1)
                    return EVENT_CONSUME
            return EVENT_UNUSED

        return EVENT_UNUSED

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
        self._has_scrollbar = (
            not self.hide_scrollbar and self.list_size > self.num_widgets
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

        item_w = (
            (bw - pl - pr - sw) // self.items_per_line if self.items_per_line > 0 else 0
        )

        for widget in self.widgets:
            if hasattr(widget, "set_bounds"):
                widget.set_bounds(x, y, item_w, self.item_height)

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
                    txt_surf = SurfaceClass(txt_surf)
                tw, th = txt_surf.get_size()
                x = (bx + bw - tw) // 2
                y = (by + bh - th) // 2
                surface.blit(txt_surf, x, y)

        # Draw header widget
        if self.header_widget is not None and hasattr(self.header_widget, "draw"):
            self.header_widget.draw(surface, layer)

    # ------------------------------------------------------------------
    # Iterate (jiveL_menu_iterate)
    # ------------------------------------------------------------------

    def iterate(self, closure: Callable[..., Any]) -> None:
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
