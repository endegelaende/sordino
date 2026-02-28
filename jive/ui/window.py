"""
jive.ui.window — Window widget for the Jivelite Python3 port.

Ported from ``share/jive/jive/ui/Window.lua`` and ``src/jive_window.c``
in the original jivelite project.

A Window is a container widget that sits on the Framework's window stack.
It manages:

* **Child widgets** — added via ``add_widget()``, iterated in z-order
* **Focus** — one child widget receives key/scroll events
* **Background** — a ``Tile`` (bgImg) and optional mask tile
* **Layout** — pluggable layout function, default is ``border_layout``
* **Show / hide** — push/pop on the Framework window stack with
  optional transitions
* **Transparency** — a window can be transparent, drawing the window
  beneath it first
* **Transient / auto-hide** — for popup/briefly-shown windows
* **Window events** — ``EVENT_WINDOW_PUSH``, ``EVENT_WINDOW_POP``,
  ``EVENT_WINDOW_ACTIVE``, ``EVENT_WINDOW_INACTIVE``

Transitions
-----------

Transition functions have the signature::

    def transition(old_window, new_window) -> Optional[Callable]:
        ...

They return a per-frame callable ``fn(widget, surface)`` that is called
each frame until it calls ``framework.kill_transition()``.  Returning
``None`` means no animation.

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
    EVENT_ALL_INPUT,
    EVENT_CHAR_PRESS,
    EVENT_CONSUME,
    EVENT_FOCUS_GAINED,
    EVENT_FOCUS_LOST,
    EVENT_HIDE,
    EVENT_KEY_HOLD,
    EVENT_KEY_PRESS,
    EVENT_MOUSE_ALL,
    EVENT_MOUSE_DOWN,
    EVENT_MOUSE_DRAG,
    EVENT_MOUSE_HOLD,
    EVENT_MOUSE_PRESS,
    EVENT_MOUSE_UP,
    EVENT_SCROLL,
    EVENT_SHOW,
    EVENT_UNUSED,
    EVENT_WINDOW_ACTIVE,
    EVENT_WINDOW_INACTIVE,
    EVENT_WINDOW_POP,
    EVENT_WINDOW_PUSH,
    FRAME_RATE_DEFAULT,
    LAYER_ALL,
    LAYER_CONTENT,
    LAYER_CONTENT_OFF_STAGE,
    LAYER_CONTENT_ON_STAGE,
    LAYER_FRAME,
    LAYER_LOWER,
    LAYER_TITLE,
    LAYOUT_CENTER,
    LAYOUT_EAST,
    LAYOUT_NONE,
    LAYOUT_NORTH,
    LAYOUT_SOUTH,
    LAYOUT_WEST,
    WH_NIL,
    XY_NIL,
    Layer,
    Layout,
)
from jive.ui.widget import Widget
from jive.utils.log import logger

if TYPE_CHECKING:
    from jive.ui.event import Event
    from jive.ui.surface import Surface
    from jive.ui.tile import Tile
    from jive.ui.timer import Timer

__all__ = ["Window"]

log = logger("jivelite.ui")

# Duration (ms) for horizontal push transitions
_HORIZONTAL_PUSH_DURATION: int = 500


# ---------------------------------------------------------------------------
# Window class
# ---------------------------------------------------------------------------


class Window(Widget):
    """
    The window widget — a top-level container on the Framework window stack.

    Subclasses ``Widget`` and adds:

    * Child widget list + z-ordered iteration
    * Focus management (one child gets key/scroll events)
    * Show / hide lifecycle with window-stack integration
    * Border-layout and no-layout functions
    * Background and mask tiles (from skin)
    * Transition support (push-left, push-right, fade, bump, popup)
    * Transparency, auto-hide, transient, always-on-top flags
    * Per-window skin override
    """

    def __init__(
        self,
        style: str,
        title: Optional[str] = None,
        title_style: Optional[str] = None,
        window_id: Optional[str] = None,
    ) -> None:
        if not isinstance(style, str):
            raise TypeError(
                f"style parameter must be a string, got {type(style).__name__}"
            )

        super().__init__(style)

        # ---- Window-specific state ----
        self.allow_screensaver: Union[bool, Callable[[], bool]] = True
        self.always_on_top: bool = False
        self.auto_hide: bool = False
        self.show_framework_widgets: bool = True
        self.transparent: bool = False
        self.transient: bool = False
        self.context_menu: bool = False
        self.is_screensaver: bool = False
        self.allow_powersave: Union[bool, Callable[[], bool], None] = None

        self.window_id: Optional[str] = window_id

        # ---- Children ----
        self.widgets: List[Widget] = []
        self.z_widgets: List[Widget] = []
        self.layout_root: bool = True
        self.focus: Optional[Widget] = None
        self.title_widget: Optional[Widget] = None

        # ---- Skin ----
        self.skin_dict: Optional[Dict[str, Any]] = None  # per-window skin override
        self._bg_tile: Optional[Tile] = None
        self._mask_tile: Optional[Tile] = None

        # ---- Layout function ----
        self._skin_layout: Optional[Callable[..., None]] = None

        # ---- Transitions ----
        self._DEFAULT_SHOW_TRANSITION = transition_push_left
        self._DEFAULT_HIDE_TRANSITION = transition_push_right

        # ---- Mouse event focus ----
        self._mouse_event_focus_widget: Optional[Widget] = None

        # ---- Listeners ----
        self._default_action_handles: List[Any] = []
        self._ignore_all_input_handle: Optional[Any] = None
        self._hide_on_all_button_handle: Optional[Any] = None
        self._briefly_handler: Optional[Any] = None
        self._briefly_timer: Optional[Timer] = None

        # ---- Background cache for transitions ----
        self._bg: Optional[Surface] = None

        # ---- Set up title if provided ----
        if title is not None:
            self.set_title(title, title_style)

        # ---- Default back action ----
        handle = self.add_action_listener("back", self, Window._up_action)
        self._default_action_handles.append(handle)

    # ==================================================================
    # Default actions
    # ==================================================================

    def _up_action(self, event: Event) -> int:
        """Default handler for the 'back' action — hide this window."""
        self.play_sound("WINDOWHIDE")
        self.hide()
        return int(EVENT_CONSUME)

    def _bump_action(self, event: Event) -> int:
        """Default 'bump' when an action can't go further."""
        self.play_sound("BUMP")
        self.bump_right()
        return int(EVENT_CONSUME)

    def remove_default_action_listeners(self) -> None:
        """Remove all default action listeners."""
        for handle in self._default_action_handles:
            self.remove_listener(handle)
        self._default_action_handles.clear()

    # ==================================================================
    # Title
    # ==================================================================

    def set_title(self, title: str, title_style: Optional[str] = None) -> None:
        """Set or update the window title text."""
        # Store as simple string for now; full Group/Label title will be
        # implemented when Group and Label are ported (M3).
        self._title_text = title
        self._title_style = title_style

    def get_title(self) -> Optional[str]:
        """Return the title text, or ``None``."""
        return getattr(self, "_title_text", None)

    def get_title_widget(self) -> Optional[Widget]:
        """Return the title widget (Group), or ``None``."""
        return self.title_widget

    # ==================================================================
    # Show / hide  (window-stack integration)
    # ==================================================================

    def show(self, transition: Optional[Callable] = None) -> None:
        """
        Show this window, pushing it onto the window stack.

        *transition* is an optional transition factory; if ``None`` the
        default show transition is used.
        """
        from jive.ui.framework import framework as fw

        stack = fw.window_stack

        # Find insertion index (skip always-on-top windows)
        idx = 0
        while idx < len(stack) and stack[idx].always_on_top:
            idx += 1

        top_window = stack[idx] if idx < len(stack) else None

        if top_window is self:
            return  # already on top

        # Remove from stack if already present
        on_stack = self in stack
        if on_stack:
            stack.remove(self)

        if not on_stack:
            self.dispatch_new_event(int(EVENT_WINDOW_PUSH))

        # Active + visible
        self.dispatch_new_event(int(EVENT_WINDOW_ACTIVE))
        self.dispatch_new_event(int(EVENT_SHOW))

        # Insert into stack
        stack.insert(idx, self)

        if top_window is not None:
            # Start transition
            trans = transition or self._DEFAULT_SHOW_TRANSITION
            if trans is not None:
                fn = _new_transition(trans, top_window, self)
                if fn is not None:
                    fw._start_transition(fn)

            if not self.transparent:
                window: Optional[Window] = top_window  # type: ignore[assignment]
                while window is not None:
                    window.dispatch_new_event(int(EVENT_HIDE))
                    window.dispatch_new_event(int(EVENT_WINDOW_INACTIVE))
                    window = (
                        window.get_lower_window()
                        if getattr(window, "transparent", False)
                        else None
                    )

        # Auto-hide windows below
        while idx + 1 < len(stack) and getattr(stack[idx + 1], "auto_hide", False):
            stack[idx + 1].hide()  # type: ignore[union-attr]

        fw.re_draw(None)

    def show_instead(self, transition: Optional[Callable] = None) -> None:
        """
        Show this window as a replacement for the current top window.
        """
        from jive.ui.framework import framework as fw

        stack = fw.window_stack
        idx = 0
        while idx < len(stack) and stack[idx].always_on_top:
            idx += 1
        top_window = stack[idx] if idx < len(stack) else None

        self.show(transition)
        if top_window is not None and hasattr(top_window, "hide"):
            top_window.hide()  # type: ignore[union-attr]

    def hide(
        self,
        transition: Optional[Callable] = None,
        sound: Optional[str] = None,
    ) -> None:
        """
        Hide this window, removing it from the window stack.

        *transition* is an optional transition factory for the exit
        animation.
        """
        from jive.ui.framework import framework as fw

        stack = fw.window_stack
        was_visible = self.visible

        if self in stack:
            stack.remove(self)

        # Find new top window (skip always-on-top)
        idx = 0
        while idx < len(stack) and stack[idx].always_on_top:
            idx += 1
        top_window = stack[idx] if idx < len(stack) else None

        if was_visible and top_window is not None:
            # Reactivate the new top window
            window: Optional[Window] = top_window  # type: ignore[assignment]
            while window is not None:
                window.dispatch_new_event(int(EVENT_WINDOW_ACTIVE))
                window.dispatch_new_event(int(EVENT_SHOW))
                window = (
                    window.get_lower_window()
                    if getattr(window, "transparent", False)
                    else None
                )

            top_window.re_draw()  # type: ignore[union-attr]

            # Transition
            trans = transition or self._DEFAULT_HIDE_TRANSITION
            if trans is not None:
                fn = _new_transition(trans, self, top_window)
                if fn is not None:
                    fw._start_transition(fn)

        if self.visible:
            self.dispatch_new_event(int(EVENT_HIDE))
            self.dispatch_new_event(int(EVENT_WINDOW_INACTIVE))

        self.dispatch_new_event(int(EVENT_WINDOW_POP))

    def show_briefly(
        self,
        msecs: Optional[int] = None,
        callback: Optional[Callable] = None,
        push_transition: Optional[Callable] = None,
        pop_transition: Optional[Callable] = None,
    ) -> None:
        """
        Show this window briefly for *msecs* milliseconds.

        When the timeout expires or user input is received, the window
        is hidden and *callback* (if any) is called.
        """
        from jive.ui.timer import Timer as TimerCls

        self.transient = True

        if not self.visible and self._briefly_timer is not None:
            self._briefly_timer.stop()
            self._briefly_timer = None

        if self._briefly_timer is not None:
            if msecs is not None:
                self._briefly_timer.set_interval(msecs)
            else:
                self._briefly_timer.restart()
            return
        elif msecs is None:
            return

        if callback is not None:
            self.add_listener([int(EVENT_WINDOW_POP), callback])

        if self._briefly_handler is None:

            def _on_input(event: Event) -> int:
                self.hide(pop_transition, "NONE")
                return int(EVENT_CONSUME)

            mask = (
                int(ACTION)
                | int(EVENT_CHAR_PRESS)
                | int(EVENT_KEY_PRESS)
                | int(EVENT_SCROLL)
                | int(EVENT_MOUSE_PRESS)
                | int(EVENT_MOUSE_HOLD)
                | int(EVENT_MOUSE_DRAG)
            )
            self._briefly_handler = self.add_listener(mask, _on_input)

        def _on_timer() -> None:
            self._briefly_timer = None
            self.hide(pop_transition, "NONE")

        self._briefly_timer = TimerCls(msecs, _on_timer, once=True)
        self._briefly_timer.start()
        self.show(push_transition)

    def hide_all(self) -> None:
        """Hide all windows in the stack."""
        from jive.ui.framework import framework as fw

        for w in list(reversed(fw.window_stack)):
            if hasattr(w, "hide"):
                w.hide()  # type: ignore[union-attr]

    def hide_to_top(self, transition: Optional[Callable] = None) -> None:
        """Hide from this window to the top of the stack."""
        from jive.ui.framework import framework as fw

        stack = fw.window_stack
        for i, w in enumerate(stack):
            if w is self:
                for j in range(i, -1, -1):
                    if hasattr(stack[j], "hide"):
                        stack[j].hide(transition)  # type: ignore[union-attr]
                break

    def move_to_top(self, transition: Optional[Callable] = None) -> None:
        """Move this window to the top of the stack."""
        from jive.ui.framework import framework as fw

        if fw.is_current_window(self):
            return
        self.hide()
        self.show(transition)

    # ==================================================================
    # Window stack queries
    # ==================================================================

    def get_window(self) -> Window:
        """A Window is its own window."""
        return self

    def get_lower_window(self) -> Optional[Window]:
        """
        Return the window beneath this one in the stack, or ``None``.
        """
        from jive.ui.framework import framework as fw

        stack = fw.window_stack
        for i, w in enumerate(stack):
            if w is self and i + 1 < len(stack):
                return stack[i + 1]  # type: ignore[return-value]
        return None

    # ==================================================================
    # Child widget management
    # ==================================================================

    def add_widget(self, widget: Widget) -> None:
        """
        Add *widget* as a child of this window.

        The widget is given focus by default (matching Lua behaviour).
        """
        if not isinstance(widget, Widget):
            raise TypeError("add_widget requires a Widget instance")

        if widget.parent is not None:
            log.warn(
                f"Adding widget {widget!r} to window, "
                f"but it already has a parent {widget.parent!r}"
            )

        self._add_widget(widget)
        self.focus_widget(widget)

    def _add_widget(self, widget: Widget) -> None:
        """Internal add without setting focus."""
        self.widgets.append(widget)
        widget.parent = self
        widget.re_skin()

        if self.is_visible():
            widget.dispatch_new_event(int(EVENT_SHOW))

    def remove_widget(self, widget: Widget) -> None:
        """Remove *widget* from this window."""
        if widget.parent is not self:
            log.warn(
                f"Removing widget {widget!r} from window, "
                f"but it has a different parent {widget.parent!r}"
            )

        if self.is_visible():
            widget.dispatch_new_event(int(EVENT_HIDE))

        widget.parent = None
        if widget in self.widgets:
            self.widgets.remove(widget)

        if self.focus is widget:
            self.focus = None

        self.re_layout()

    # ==================================================================
    # Focus
    # ==================================================================

    def focus_widget(self, widget: Optional[Widget] = None) -> None:
        """
        Set *widget* as the focused child (receives key/scroll events).

        Pass ``None`` to clear focus.
        """
        from jive.ui.event import Event as EventCls

        if self.focus is not None and self.focus is not self.title_widget:
            self.focus._event(EventCls(int(EVENT_FOCUS_LOST)))

        self.focus = widget
        if self.focus is not None:
            self.focus._event(EventCls(int(EVENT_FOCUS_GAINED)))

    # ==================================================================
    # Iteration (z-ordered)
    # ==================================================================

    def iterate(
        self,
        closure: Callable[[Widget], Optional[int]],
        include_hidden: bool = False,
    ) -> int:
        """
        Call *closure(widget)* for each child in z-order.

        Returns the OR of all closure return values.

        If *include_hidden* is ``False`` (default), hidden widgets are
        skipped.
        """
        result = 0
        for widget in self.z_widgets:
            if not include_hidden and widget.is_hidden():
                continue
            r = closure(widget)
            result |= r or 0
        return result

    # ==================================================================
    # Skin
    # ==================================================================

    def _skin(self) -> None:
        """
        Apply skin properties to this window.

        Reads ``bgImg`` and ``maskImg`` tiles, and the ``layout`` function
        from the style system.
        """
        from jive.ui.style import style_rawvalue, style_tile

        # Invalidate style path cache
        if hasattr(self, "_style_path"):
            try:
                del self._style_path  # type: ignore[attr-defined]
            except AttributeError:
                pass

        # Pack (read border/padding from style)
        self._widget_pack()

        # Layout function — default to border_layout
        layout_fn = style_rawvalue(self, "layout", None)
        if layout_fn is not None and callable(layout_fn):
            self._skin_layout = layout_fn
        else:
            self._skin_layout = self.border_layout

        # Background tile
        bg_tile = style_tile(self, "bgImg", None)
        if bg_tile is not self._bg_tile:
            self._bg_tile = bg_tile

        # Mask tile
        mask_tile = style_tile(self, "maskImg", None)
        if mask_tile is not self._mask_tile:
            self._mask_tile = mask_tile

    # ==================================================================
    # Layout
    # ==================================================================

    def _layout(self) -> None:
        """
        Build the z-ordered widget list and run the layout function.
        """
        stable_counter = 1
        self.z_widgets = []

        # Framework widgets first (lower z-order by default)
        if self.show_framework_widgets:
            try:
                from jive.ui.framework import framework as fw

                for gw in fw.get_widgets():
                    if gw is not None:
                        gw._stable_sort_index = stable_counter  # type: ignore[attr-defined]
                        self.z_widgets.append(gw)
                        stable_counter += 1
            except (ImportError, AttributeError):
                pass

        # Window's own children
        for widget in self.widgets:
            if widget is not None:
                widget._stable_sort_index = stable_counter  # type: ignore[attr-defined]
                self.z_widgets.append(widget)
                stable_counter += 1

        # Stable sort by z-order
        self.z_widgets.sort(
            key=lambda w: (
                w.z_order if w.z_order is not None else 0,
                getattr(w, "_stable_sort_index", 0),
            )
        )

        # Run the skin-provided layout function
        if self._skin_layout is not None:
            self._skin_layout()
        else:
            self.border_layout()

    # ==================================================================
    # Drawing
    # ==================================================================

    def draw(self, surface: Surface, layer: int = LAYER_ALL) -> None:
        """
        Draw this window and its children onto *surface*.

        *layer* is a bitmask of layers to draw.
        """
        is_transparent = self.transparent
        is_mask = bool((layer & self._layer) and self._mask_tile is not None)

        if is_transparent or is_mask:
            lower = self.get_lower_window()
            if lower is not None:
                # Draw the window underneath (for transparency)
                if is_transparent and (layer & int(LAYER_LOWER)):
                    lower.draw(surface, int(LAYER_ALL))

                # Draw mask
                if is_mask:
                    bx, by, bw, bh = lower.get_bounds()
                    self._mask_tile.blit(surface, bx, by, bw, bh)  # type: ignore[union-attr]

        # Window background
        if (layer & self._layer) and self._bg_tile is not None:
            bx, by, bw, bh = self.bounds
            self._bg_tile.blit(surface, bx, by, bw, bh)

        # Draw children in z-order
        for widget in self.z_widgets:
            if widget.is_hidden():
                continue
            widget.draw(surface, layer)

    # ==================================================================
    # Event handling
    # ==================================================================

    def _event_handler(self, event: Event) -> int:
        """
        Window-specific event routing.

        Matches the C ``jiveL_window_event_handler``.
        """
        etype = event.get_type()

        # ---- Key / scroll / IR / action → focused widget only ----
        from jive.ui.constants import (
            EVENT_IR_ALL,
            EVENT_KEY_ALL,
            EVENT_KEY_DOWN,
            EVENT_KEY_UP,
            EventType,
        )

        focus_events = (
            int(EVENT_SCROLL) | int(EVENT_KEY_ALL) | int(EVENT_IR_ALL) | int(ACTION)
        )
        if etype & focus_events:
            if self.focus is not None:
                return self.focus._event(event)
            return int(EVENT_UNUSED)

        # ---- Mouse events → widget under cursor ----
        if etype & int(EVENT_MOUSE_ALL):
            return self._dispatch_mouse_event(event)

        # ---- Window lifecycle events → don't forward ----
        window_lifecycle = (
            int(EVENT_WINDOW_ACTIVE)
            | int(EVENT_WINDOW_INACTIVE)
            | int(EVENT_WINDOW_PUSH)
            | int(EVENT_WINDOW_POP)
        )
        if etype & window_lifecycle:
            # WINDOW_ACTIVE: re-parent global widgets
            if etype == int(EVENT_WINDOW_ACTIVE):
                try:
                    from jive.ui.framework import framework as fw

                    for gw in fw.get_widgets():
                        gw.parent = self
                except (ImportError, AttributeError):
                    pass
            return int(EVENT_UNUSED)

        # ---- Show / hide → forward to children ----
        if etype == int(EVENT_SHOW) or etype == int(EVENT_HIDE):
            r = 0
            for widget in self.widgets:
                r |= widget._event(event)
            return r

        # ---- Everything else → all widgets ----
        r = 0
        # Global widgets
        try:
            from jive.ui.framework import framework as fw

            for gw in fw.get_widgets():
                r |= gw._event(event)
        except (ImportError, AttributeError):
            pass

        # Child widgets
        for widget in self.widgets:
            r |= widget._event(event)

        return r

    def _dispatch_mouse_event(self, event: Event) -> int:
        """Route mouse events to the widget under the cursor."""
        etype = event.get_type()
        top_widget: Optional[Widget] = None
        result = 0

        for widget in self.z_widgets:
            if widget.is_hidden():
                continue

            should_dispatch = False
            if self._mouse_event_focus_widget is widget:
                should_dispatch = True
            elif self._mouse_event_focus_widget is None and widget.mouse_inside(event):
                should_dispatch = True

            if should_dispatch:
                r = widget._event(event)
                if r != int(EVENT_UNUSED):
                    if etype == int(EVENT_MOUSE_DOWN):
                        top_widget = widget
                    result |= r

        if top_widget is not None:
            self._mouse_event_focus_widget = top_widget

        if etype == int(EVENT_MOUSE_UP):
            self._mouse_event_focus_widget = None

        return result

    def _event(self, event: Event) -> int:
        """
        Internal event dispatch.

        Calls the window event handler first, then falls back to the
        base Widget._event for listener dispatch.
        """
        etype = event.get_type()
        not_mouse = (etype & int(EVENT_MOUSE_ALL)) == 0

        if not_mouse:
            r = self._event_handler(event)
        else:
            r = self._dispatch_mouse_event(event)

        if not (r & int(EVENT_CONSUME)):
            r = Widget._event(self, event)

        return r

    # ==================================================================
    # check_layout override — handles transparent windows
    # ==================================================================

    def check_layout(self) -> None:
        """
        Check and perform layout if needed, including lower windows
        for transparent window chains.
        """
        if self.transparent:
            lower = self.get_lower_window()
            if lower is not None and hasattr(lower, "check_layout"):
                lower.check_layout()

        super().check_layout()

        # Also check global widgets
        try:
            from jive.ui.framework import framework as fw

            for gw in fw.get_widgets():
                gw.check_layout()
        except (ImportError, AttributeError):
            pass

    # ==================================================================
    # Per-window skin
    # ==================================================================

    def set_skin(self, skin_dict: Optional[Dict[str, Any]]) -> None:
        """Set a per-window skin override dict."""
        self.skin_dict = skin_dict

    def get_skin(self) -> Optional[Dict[str, Any]]:
        """Return the per-window skin, or ``None``."""
        return self.skin_dict

    # Property alias for style.py compatibility
    @property
    def skin(self) -> Optional[Dict[str, Any]]:
        return self.skin_dict

    @skin.setter
    def skin(self, value: Optional[Dict[str, Any]]) -> None:
        self.skin_dict = value

    # ==================================================================
    # Flags
    # ==================================================================

    def set_allow_screensaver(self, value: Union[bool, Callable[[], bool]]) -> None:
        self.allow_screensaver = value

    def get_allow_screensaver(self) -> Union[bool, Callable[[], bool]]:
        return self.allow_screensaver

    def can_activate_screensaver(self) -> bool:
        if self.allow_screensaver is None:
            return True
        if callable(self.allow_screensaver):
            return self.allow_screensaver()
        return bool(self.allow_screensaver)

    def set_always_on_top(self, value: bool) -> None:
        self.always_on_top = value

    def get_always_on_top(self) -> bool:
        return self.always_on_top

    def set_auto_hide(self, enabled: bool) -> None:
        self.auto_hide = enabled

    def set_transient(self, value: bool) -> None:
        self.transient = value

    def get_transient(self) -> bool:
        return self.transient

    def set_show_framework_widgets(self, value: bool) -> None:
        self.show_framework_widgets = value
        self.re_layout()

    def get_show_framework_widgets(self) -> bool:
        return self.show_framework_widgets

    def set_transparent(self, value: bool) -> None:
        self.transparent = value
        self.re_layout()

    def get_transparent(self) -> bool:
        return self.transparent

    def set_context_menu(self, value: bool) -> None:
        self.context_menu = value
        self.re_layout()

    def is_context_menu(self) -> bool:
        return self.context_menu

    def get_window_id(self) -> Optional[str]:
        return self.window_id

    def set_window_id(self, id: str) -> None:
        self.window_id = id

    # ==================================================================
    # Input filtering
    # ==================================================================

    def ignore_all_input_except(
        self,
        excluded_actions: Optional[List[str]] = None,
        ignored_callback: Optional[Callable] = None,
    ) -> None:
        """
        Consume all input events except for the named actions in
        *excluded_actions*.  ``"soft_reset"`` is always excluded.
        """
        if self._ignore_all_input_handle is not None:
            return

        if self._hide_on_all_button_handle is not None:
            self.remove_listener(self._hide_on_all_button_handle)
            self._hide_on_all_button_handle = None

        if excluded_actions is None:
            excluded_actions = []
        if "soft_reset" not in excluded_actions:
            excluded_actions.append("soft_reset")

        def _handler(event: Event) -> int:
            return self._ignore_all_input_listener(
                event, excluded_actions, ignored_callback
            )

        self._ignore_all_input_handle = self.add_listener(
            int(EVENT_ALL_INPUT), _handler
        )

    def _ignore_all_input_listener(
        self,
        event: Event,
        excluded_actions: Optional[List[str]],
        ignored_callback: Optional[Callable],
    ) -> int:
        from jive.ui.framework import framework as fw

        etype = event.get_type()

        if etype == int(ACTION):
            action = event.get_action()
            if excluded_actions:
                for excl in excluded_actions:
                    if action == excl:
                        return int(EVENT_UNUSED)

            if ignored_callback is not None:
                ignored_callback(event)
            return int(EVENT_CONSUME)

        # Try to convert to action
        action_name = fw.convert_input_to_action(event)
        if not action_name:
            return int(EVENT_CONSUME)

        from jive.ui.event import Event as EventCls

        action_event = EventCls(int(ACTION), action=action_name)
        return self._ignore_all_input_listener(
            action_event, excluded_actions, ignored_callback
        )

    def hide_on_all_button_input(self) -> None:
        """Auto-hide this window on any button/mouse input."""
        if self._hide_on_all_button_handle is not None:
            return

        def _handler(event: Event) -> int:
            from jive.ui.framework import framework as fw

            etype = event.get_type()
            if etype == int(ACTION):
                self.play_sound("WINDOWHIDE")
                self.hide()
                return int(EVENT_CONSUME)

            result = fw.convert_input_to_action(event)
            if result == int(EVENT_UNUSED):
                self.play_sound("WINDOWHIDE")
                self.hide()

            return int(EVENT_CONSUME)

        mask = (
            int(ACTION)
            | int(EVENT_KEY_PRESS)
            | int(EVENT_KEY_HOLD)
            | int(EVENT_MOUSE_PRESS)
            | int(EVENT_MOUSE_HOLD)
            | int(EVENT_MOUSE_DRAG)
        )
        self._hide_on_all_button_handle = self.add_listener(mask, _handler)

    # ==================================================================
    # Layout functions
    # ==================================================================

    def no_layout(self) -> None:
        """
        Layout function that does not modify child positions.

        Window size is set from style preferred bounds or screen size.
        """
        from jive.ui.framework import framework as fw

        sw, sh = fw.get_screen_size()
        _wx, _wy, _ww, _wh = self.get_preferred_bounds()
        wlb, wtb, wrb, wbb = self.get_border()

        ww = (_ww or sw) - wlb - wrb
        wh = (_wh or sh) - wtb - wbb
        wx = _wx or 0
        wy = _wy or 0

        self.set_bounds(wx, wy, ww, wh)

    def border_layout(self, fit_window: bool = False) -> None:
        """
        Java-style border layout.

        Widgets are assigned positions via ``style_int("position")``:
        ``LAYOUT_NORTH``, ``LAYOUT_SOUTH``, ``LAYOUT_EAST``,
        ``LAYOUT_WEST``, ``LAYOUT_CENTER``, ``LAYOUT_NONE``.
        """
        from jive.ui.framework import framework as fw
        from jive.ui.style import style_int as _style_int

        sw, sh = fw.get_screen_size()

        _wx, _wy, _ww, _wh = self.get_preferred_bounds()
        wlb, wtb, wrb, wbb = self.get_border()

        ww = (_ww or sw) - wlb - wrb
        wh = (_wh or sh) - wtb - wbb

        # Collect preferred sizes
        max_n = 0
        max_e = 0
        max_s = 0
        max_w = 0
        max_x = 0
        max_y = 0

        def _measure(widget: Widget) -> Optional[int]:
            nonlocal max_n, max_e, max_s, max_w, max_x, max_y

            x, y, w, h = widget.get_preferred_bounds()
            lb, tb, rb, bb = widget.get_border()
            position = _style_int(widget, "position", int(LAYOUT_CENTER))

            if position == int(LAYOUT_NORTH):
                h_total = (h or 0) + tb + bb
                max_n = max(h_total, max_n)
                if w is not None:
                    w_total = w + lb + rb
                    w_total = min(w_total, sw - lb - rb)
                    max_x = max(w_total, max_x)

            elif position == int(LAYOUT_SOUTH):
                h_total = (h or 0) + tb + bb
                max_s = max(h_total, max_s)
                if w is not None:
                    w_total = w + lb + rb
                    w_total = min(w_total, sw - lb - rb)
                    max_x = max(w_total, max_x)

            elif position == int(LAYOUT_EAST):
                w_total = (w or 0) + lb + rb
                w_total = min(w_total, sw - lb - rb)
                max_e = max(w_total, max_e)

            elif position == int(LAYOUT_WEST):
                w_total = (w or 0) + lb + rb
                w_total = min(w_total, sw - lb - rb)
                max_w = max(w_total, max_w)

            elif position == int(LAYOUT_CENTER):
                if w is not None:
                    w_total = w + lb + rb
                    w_total = min(w_total, sw - lb - rb)
                    max_x = max(w_total, max_x)
                if h is not None:
                    h_total = h + tb + bb
                    max_y = max(h_total, max_y)

            return None

        self.iterate(_measure, include_hidden=True)

        # Adjust window bounds to fit content
        if fit_window:
            if _wh is None and max_y > 0:
                wh = wtb + max_n + max_y + max_s + wbb
            if _ww is None and max_x > 0:
                ww = wlb + max_e + max_x + max_w + wrb

        wx = _wx if _wx is not None else (sw - ww) // 2
        wy = _wy if _wy is not None else (sh - wh) // 2

        # Place widgets
        cy = 0

        def _place(widget: Widget) -> Optional[int]:
            nonlocal cy

            x, y, w, h = widget.get_preferred_bounds()
            lb, tb, rb, bb = widget.get_border()
            position = _style_int(widget, "position", int(LAYOUT_CENTER))
            rb_total = rb + lb
            bb_total = bb + tb

            def _max_bounds(
                bx: int, by: int, bw: int, bh: int
            ) -> Tuple[int, int, int, int]:
                return (bx, by, min(ww, bw), min(wh, bh))

            if position == int(LAYOUT_NORTH):
                x = x or 0
                y = y or 0
                w = w or ww
                w = min(ww, w) - rb_total
                widget.set_bounds(*_max_bounds(wx + x + lb, wy + y + tb, w, h or 0))

            elif position == int(LAYOUT_SOUTH):
                x = x or 0
                y = y if y is not None else (wh - max_s)
                w = w or ww
                w = min(ww, w) - rb_total
                widget.set_bounds(*_max_bounds(wx + x + lb, wy + y + tb, w, h or 0))

            elif position == int(LAYOUT_EAST):
                x = x if x is not None else (ww - max_e)
                y = y or 0
                widget.set_bounds(
                    *_max_bounds(
                        wx + x + lb,
                        wy + y + tb,
                        w or 0,
                        wh - bb_total,
                    )
                )

            elif position == int(LAYOUT_WEST):
                x = x or 0
                y = y or 0
                widget.set_bounds(
                    *_max_bounds(
                        wx + x + lb,
                        wy + y + tb,
                        w or 0,
                        wh - bb_total,
                    )
                )

            elif position == int(LAYOUT_CENTER):
                h_val = h or (wh - max_n - max_s)
                h_val = min(wh - max_n - max_s, h_val)
                w_val = w or (ww - max_w - max_e)
                w_val = min(ww - max_w - max_e, w_val) - rb_total

                widget.set_bounds(
                    *_max_bounds(
                        wx + lb,
                        wy + max_n + tb + cy,
                        w_val,
                        h_val,
                    )
                )
                cy += h_val + bb_total

            elif position == int(LAYOUT_NONE):
                widget.set_bounds(
                    *_max_bounds(
                        wx + (x or 0),
                        wy + (y or 0),
                        w or 0,
                        h or 0,
                    )
                )

            return None

        self.iterate(_place, include_hidden=True)

        # Set window bounds
        self.set_bounds(wx, wy, ww, wh)

    # ==================================================================
    # Bump animations
    # ==================================================================

    def bump_left(self) -> None:
        from jive.ui.framework import framework as fw

        fn = _transition_bump_left(self)
        if fn is not None:
            fw._start_transition(fn)

    def bump_right(self) -> None:
        from jive.ui.framework import framework as fw

        fn = _transition_bump_right(self)
        if fn is not None:
            fw._start_transition(fn)

    def bump_up(self) -> None:
        from jive.ui.framework import framework as fw

        fn = _transition_bump_up(self)
        if fn is not None:
            fw._start_transition(fn)

    def bump_down(self) -> None:
        from jive.ui.framework import framework as fw

        fn = _transition_bump_down(self)
        if fn is not None:
            fw._start_transition(fn)

    # ==================================================================
    # Button actions
    # ==================================================================

    def set_button_action(
        self,
        button: str,
        press_action: Optional[str] = None,
        hold_action: Optional[str] = None,
        long_hold_action: Optional[str] = None,
        delayed: bool = False,
    ) -> None:
        """
        Map a hardware/soft-button to named actions.

        In the Lua original this configures the left/right title-bar
        buttons to fire specific actions on press, hold, and long-hold.

        Parameters
        ----------
        button : str
            Button identifier (e.g. ``"lbutton"``, ``"rbutton"``).
        press_action : str or None
            Action name dispatched on short press, or ``None`` to clear.
        hold_action : str or None
            Action name dispatched on hold.
        long_hold_action : str or None
            Action name dispatched on long hold.
        delayed : bool
            If ``True``, delay applying the button action (used to
            avoid accidental activation during rapid navigation).

        Notes
        -----
        This is currently a stub that stores the mapping but does not
        yet wire it to actual button widgets.  Full implementation
        requires the title-bar button widgets (not yet ported).
        """
        if not hasattr(self, "_button_actions"):
            self._button_actions: Dict[str, Any] = {}

        self._button_actions[button] = {
            "press": press_action,
            "hold": hold_action,
            "long_hold": long_hold_action,
            "delayed": delayed,
        }

    setButtonAction = set_button_action

    # ==================================================================
    # Mouse focus
    # ==================================================================

    def set_mouse_event_focus_widget(self, widget: Optional[Widget]) -> None:
        self._mouse_event_focus_widget = widget

    # ==================================================================
    # jive_widget_pack — read common style properties
    # ==================================================================

    def _widget_pack(self) -> None:
        """
        Read the common widget style properties: preferred bounds,
        padding, border, layer, z-order, hidden.

        This mirrors ``jive_widget_pack()`` in ``jive_widget.c``.
        """
        from jive.ui.style import style_insets, style_int

        # Preferred bounds
        sx = style_int(self, "x", XY_NIL)
        sy = style_int(self, "y", XY_NIL)
        sw = style_int(self, "w", WH_NIL)
        sh = style_int(self, "h", WH_NIL)

        self.preferred_bounds[0] = None if sx == XY_NIL else sx
        self.preferred_bounds[1] = None if sy == XY_NIL else sy
        self.preferred_bounds[2] = None if sw == WH_NIL else sw
        self.preferred_bounds[3] = None if sh == WH_NIL else sh

        # Padding & border
        pad = style_insets(self, "padding", [0, 0, 0, 0])
        self.padding[:] = pad[:4] if len(pad) >= 4 else pad + [0] * (4 - len(pad))

        bdr = style_insets(self, "border", [0, 0, 0, 0])
        self.border[:] = bdr[:4] if len(bdr) >= 4 else bdr + [0] * (4 - len(bdr))

        # Layer / z-order / hidden
        self._layer = style_int(self, "layer", int(LAYER_CONTENT))
        self._z_order = style_int(self, "zOrder", 0)
        self._hidden = bool(style_int(self, "hidden", 0))

    # ==================================================================
    # Dunder
    # ==================================================================

    def __repr__(self) -> str:
        title = self.get_title()
        if title:
            return f"Window({self.style!r}, {title!r})"
        return f"Window({self.style!r})"

    def __str__(self) -> str:
        return self.__repr__()


# ======================================================================
# Transition helpers (module-level functions)
# ======================================================================


def _new_transition(
    transition_factory: Callable,
    old_window: Window,
    new_window: Window,
) -> Optional[Callable]:
    """
    Create a transition, wrapping it to handle transparent windows on
    top of the stack (e.g. popups).

    This mirrors the Lua ``_newTransition``.
    """
    fn = transition_factory(old_window, new_window)
    if fn is None:
        return None

    # Collect transparent windows above the transition pair
    from jive.ui.framework import framework as fw

    stack = fw.window_stack
    windows_above: List[Window] = []
    idx = 0
    w = stack[idx] if idx < len(stack) else None
    while (
        w is not None
        and w is not old_window
        and w is not new_window
        and getattr(w, "transparent", False)
    ):
        windows_above.insert(0, w)  # type: ignore[arg-type]
        idx += 1
        w = stack[idx] if idx < len(stack) else None

    if windows_above:

        def _wrapped(widget: Any, surface: Surface) -> None:
            fn(widget, surface)
            for tw in windows_above:
                tw.draw(surface, int(LAYER_CONTENT))

        return _wrapped
    return fn


# ======================================================================
# Transition: no transition
# ======================================================================


def transition_none(old_window: Window, new_window: Window) -> None:
    """No transition — window appears immediately."""
    return None


# ======================================================================
# Transition: bump
# ======================================================================


def _transition_bump_left(window: Window) -> Optional[Callable]:
    frames = [2]

    def _step(widget: Any, surface: Surface) -> None:
        from jive.ui.framework import framework as fw

        x = frames[0] * 3
        if hasattr(widget, "_bg") and widget._bg is not None:
            widget._bg.blit(surface, 0, 0)
        window.draw(surface, int(LAYER_LOWER))
        surface.set_offset(x, 0)
        window.draw(
            surface,
            int(LAYER_CONTENT)
            | int(LAYER_CONTENT_OFF_STAGE)
            | int(LAYER_CONTENT_ON_STAGE)
            | int(LAYER_TITLE),
        )
        surface.set_offset(0, 0)
        window.draw(surface, int(LAYER_FRAME))

        frames[0] -= 1
        if frames[0] == 0:
            fw._kill_transition()

    return _step


def _transition_bump_right(window: Window) -> Optional[Callable]:
    frames = [2]

    def _step(widget: Any, surface: Surface) -> None:
        from jive.ui.framework import framework as fw

        x = frames[0] * 3
        if hasattr(widget, "_bg") and widget._bg is not None:
            widget._bg.blit(surface, 0, 0)
        window.draw(surface, int(LAYER_LOWER))
        surface.set_offset(-x, 0)
        window.draw(
            surface,
            int(LAYER_CONTENT)
            | int(LAYER_CONTENT_OFF_STAGE)
            | int(LAYER_CONTENT_ON_STAGE)
            | int(LAYER_TITLE),
        )
        surface.set_offset(0, 0)
        window.draw(surface, int(LAYER_FRAME))

        frames[0] -= 1
        if frames[0] == 0:
            fw._kill_transition()

    return _step


def _transition_bump_up(window: Window) -> Optional[Callable]:
    frames = [1]
    in_return = [False]

    def _step(widget: Any, surface: Surface) -> None:
        from jive.ui.framework import framework as fw

        y = frames[0] * 3
        window.draw(surface, int(LAYER_FRAME) | int(LAYER_LOWER))
        surface.set_offset(0, -y // 2)
        window.draw(
            surface,
            int(LAYER_CONTENT)
            | int(LAYER_CONTENT_OFF_STAGE)
            | int(LAYER_CONTENT_ON_STAGE)
            | int(LAYER_TITLE),
        )
        surface.set_offset(0, 0)

        if not in_return[0] and frames[0] < 2:
            frames[0] += 1
        else:
            in_return[0] = True
            frames[0] -= 1

        if frames[0] == 0:
            fw._kill_transition()

    return _step


def _transition_bump_down(window: Window) -> Optional[Callable]:
    frames = [1]
    in_return = [False]

    def _step(widget: Any, surface: Surface) -> None:
        from jive.ui.framework import framework as fw

        y = frames[0] * 3
        window.draw(surface, int(LAYER_FRAME) | int(LAYER_LOWER))
        surface.set_offset(0, y // 2)
        window.draw(
            surface,
            int(LAYER_CONTENT)
            | int(LAYER_CONTENT_OFF_STAGE)
            | int(LAYER_CONTENT_ON_STAGE)
            | int(LAYER_TITLE),
        )
        surface.set_offset(0, 0)

        if not in_return[0] and frames[0] < 2:
            frames[0] += 1
        else:
            in_return[0] = True
            frames[0] -= 1

        if frames[0] == 0:
            fw._kill_transition()

    return _step


# ======================================================================
# Transition: push left / right
# ======================================================================


def transition_push_left(old_window: Window, new_window: Window) -> Optional[Callable]:
    """
    Horizontal push-left transition (new window slides in from right).
    """
    return _transition_push_left_impl(old_window, new_window, False)


def transition_push_left_static_title(
    old_window: Window, new_window: Window
) -> Optional[Callable]:
    """Push left with static title bar."""
    return _transition_push_left_impl(old_window, new_window, True)


def _transition_push_left_impl(
    old_window: Window,
    new_window: Window,
    static_title: bool,
) -> Optional[Callable]:
    from jive.ui.framework import framework as fw

    duration = _HORIZONTAL_PUSH_DURATION
    remaining = [duration]
    screen_width = fw.get_screen_size()[0]
    scale = (duration * duration * duration) / max(screen_width, 1)
    start_t = [0]
    count = [0]

    def _step(widget: Any, surface: Surface) -> None:
        if count[0] == 0:
            start_t[0] = fw.get_ticks()
        count[0] += 1

        x = math.ceil(
            screen_width - (remaining[0] * remaining[0] * remaining[0]) / scale
        )

        surface.set_offset(0, 0)
        if hasattr(old_window, "_bg") and old_window._bg is not None:
            old_window._bg.blit(surface, 0, 0)

        if static_title:
            new_window.draw(surface, int(LAYER_LOWER) | int(LAYER_TITLE))
        else:
            new_window.draw(surface, int(LAYER_LOWER))

        surface.set_offset(-x, 0)
        if static_title:
            old_window.draw(
                surface,
                int(LAYER_CONTENT) | int(LAYER_CONTENT_OFF_STAGE),
            )
        else:
            old_window.draw(
                surface,
                int(LAYER_CONTENT) | int(LAYER_CONTENT_OFF_STAGE) | int(LAYER_TITLE),
            )

        surface.set_offset(screen_width - x, 0)
        if static_title:
            new_window.draw(
                surface,
                int(LAYER_CONTENT) | int(LAYER_CONTENT_ON_STAGE),
            )
        else:
            new_window.draw(
                surface,
                int(LAYER_CONTENT) | int(LAYER_CONTENT_ON_STAGE) | int(LAYER_TITLE),
            )

        surface.set_offset(0, 0)
        new_window.draw(surface, int(LAYER_FRAME))

        elapsed = fw.get_ticks() - start_t[0]
        remaining[0] = duration - elapsed

        if remaining[0] <= 0 or x >= screen_width:
            fw._kill_transition()

    return _step


def transition_push_right(old_window: Window, new_window: Window) -> Optional[Callable]:
    """
    Horizontal push-right transition (new window slides in from left).
    """
    return _transition_push_right_impl(old_window, new_window, False)


def transition_push_right_static_title(
    old_window: Window, new_window: Window
) -> Optional[Callable]:
    """Push right with static title bar."""
    return _transition_push_right_impl(old_window, new_window, True)


def _transition_push_right_impl(
    old_window: Window,
    new_window: Window,
    static_title: bool,
) -> Optional[Callable]:
    from jive.ui.framework import framework as fw

    duration = _HORIZONTAL_PUSH_DURATION
    remaining = [duration]
    screen_width = fw.get_screen_size()[0]
    scale = (duration * duration * duration) / max(screen_width, 1)
    start_t = [0]
    count = [0]

    def _step(widget: Any, surface: Surface) -> None:
        if count[0] == 0:
            start_t[0] = fw.get_ticks()
        count[0] += 1

        x = math.ceil(
            screen_width - (remaining[0] * remaining[0] * remaining[0]) / scale
        )

        surface.set_offset(0, 0)
        if hasattr(old_window, "_bg") and old_window._bg is not None:
            old_window._bg.blit(surface, 0, 0)

        if static_title:
            new_window.draw(surface, int(LAYER_LOWER) | int(LAYER_TITLE))
        else:
            new_window.draw(surface, int(LAYER_LOWER))

        surface.set_offset(x, 0)
        if static_title:
            old_window.draw(
                surface,
                int(LAYER_CONTENT) | int(LAYER_CONTENT_OFF_STAGE),
            )
        else:
            old_window.draw(
                surface,
                int(LAYER_CONTENT) | int(LAYER_CONTENT_OFF_STAGE) | int(LAYER_TITLE),
            )

        surface.set_offset(x - screen_width, 0)
        if static_title:
            new_window.draw(
                surface,
                int(LAYER_CONTENT) | int(LAYER_CONTENT_ON_STAGE),
            )
        else:
            new_window.draw(
                surface,
                int(LAYER_CONTENT) | int(LAYER_CONTENT_ON_STAGE) | int(LAYER_TITLE),
            )

        surface.set_offset(0, 0)
        new_window.draw(surface, int(LAYER_FRAME))

        elapsed = fw.get_ticks() - start_t[0]
        remaining[0] = duration - elapsed

        if remaining[0] <= 0 or x >= screen_width:
            fw._kill_transition()

    return _step


# ======================================================================
# Transition: fade in
# ======================================================================


def transition_fade_in(old_window: Window, new_window: Window) -> Optional[Callable]:
    """Fade-in transition (400ms)."""
    return _transition_fade_in_impl(old_window, new_window, 400)


def transition_fade_in_fast(
    old_window: Window, new_window: Window
) -> Optional[Callable]:
    """Fast fade-in transition (100ms)."""
    return _transition_fade_in_impl(old_window, new_window, 100)


def _transition_fade_in_impl(
    old_window: Window,
    new_window: Window,
    duration: int,
) -> Optional[Callable]:
    from jive.ui.framework import framework as fw
    from jive.ui.surface import Surface

    remaining = [duration]
    scale = 255.0 / max(duration, 1)
    start_t = [0]
    count = [0]

    # Capture old window state
    sw, sh = fw.get_screen_size()
    srf = Surface.new_rgb(sw, sh)

    bg = fw.get_background()
    if bg is not None:
        try:
            bg.blit(srf, 0, 0, sw, sh)
        except Exception:
            pass
    old_window.draw(srf, int(LAYER_ALL))

    def _step(widget: Any, surface: Surface) -> None:
        if count[0] == 0:
            start_t[0] = fw.get_ticks()
        count[0] += 1

        alpha = int(math.floor(remaining[0] * scale + 0.5))
        alpha = max(0, min(255, alpha))

        if hasattr(new_window, "_bg") and new_window._bg is not None:
            new_window._bg.blit(surface, 0, 0)
        new_window.draw(surface, int(LAYER_ALL))
        srf.blit_alpha(surface, 0, 0, alpha)

        elapsed = fw.get_ticks() - start_t[0]
        remaining[0] = duration - elapsed

        if remaining[0] <= 0:
            fw._kill_transition()

    return _step


# ======================================================================
# Transition: push popup up / down
# ======================================================================


def transition_push_popup_up(
    old_window: Window, new_window: Window
) -> Optional[Callable]:
    """Push-up transition for popup windows."""
    from jive.ui.framework import framework as fw

    frame_rate = fw.get_frame_rate()
    total_frames = [math.ceil(frame_rate / 6)]
    _, _, _, window_height = new_window.get_bounds()
    if window_height <= 0:
        window_height = 1
    scale = (total_frames[0] * total_frames[0] * total_frames[0]) / window_height

    def _step(widget: Any, surface: Surface) -> None:
        y = int((total_frames[0] * total_frames[0] * total_frames[0]) / scale)

        surface.set_offset(0, 0)
        old_window.draw(surface, int(LAYER_ALL))

        surface.set_offset(0, y)
        new_window.draw(
            surface,
            int(LAYER_CONTENT) | int(LAYER_CONTENT_OFF_STAGE),
        )

        surface.set_offset(0, 0)

        total_frames[0] -= 1
        if total_frames[0] == 0:
            fw._kill_transition()

    return _step


def transition_push_popup_down(
    old_window: Window, new_window: Window
) -> Optional[Callable]:
    """Push-down transition for popup windows."""
    from jive.ui.framework import framework as fw

    frame_rate = fw.get_frame_rate()
    total_frames = [math.ceil(frame_rate / 6)]
    _, _, _, window_height = old_window.get_bounds()
    if window_height <= 0:
        window_height = 1
    scale = (total_frames[0] * total_frames[0] * total_frames[0]) / window_height

    def _step(widget: Any, surface: Surface) -> None:
        y = int((total_frames[0] * total_frames[0] * total_frames[0]) / scale)

        surface.set_offset(0, 0)
        new_window.draw(surface, int(LAYER_ALL))

        surface.set_offset(0, window_height - y)
        old_window.draw(
            surface,
            int(LAYER_CONTENT) | int(LAYER_CONTENT_OFF_STAGE),
        )

        surface.set_offset(0, 0)

        total_frames[0] -= 1
        if total_frames[0] == 0:
            fw._kill_transition()

    return _step
