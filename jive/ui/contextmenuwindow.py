"""
jive.ui.contextmenuwindow — Context-menu window for the Jivelite Python3 port.

Ported from ``ContextMenuWindow.lua`` in the original jivelite project.

A ContextMenuWindow is a :class:`~jive.ui.window.Window` subclass that
captures a screenshot of the current screen, optionally shades it, and
displays it as a background behind a context menu.  This creates the
visual effect of a modal overlay dimming the previous screen.

Key behaviours:

* **Screenshot capture** — on creation, takes a snapshot of the current
  screen via the Framework's rendering pipeline and stores it as a
  background image.
* **Shading** — by default, applies a semi-transparent dark overlay
  (``0x00000085``) to the captured background to visually dim it.
* **Stacking** — when shown on top of another ContextMenuWindow, reuses
  the parent's background and adds a "back" button action (left button)
  with a push-left transition.
* **Cancel action** — pressing cancel or add hides all context menus.
* **Fast fade-in** — show transition defaults to ``transition_fade_in_fast``;
  hide transition defaults to ``transition_none``.
* **No screensaver** — the screensaver is suppressed while a context
  menu is visible.
* **No framework widgets** — the title bar / button bar is not shown.
* **Draw override** — draws the captured background first (unless a
  transition is active), then draws the window's own widgets on top.

Usage::

    cmw = ContextMenuWindow("My Context Menu")
    cmw.show()

    # … later …
    cmw.hide()

Copyright 2010 Logitech. All Rights Reserved. (original Lua/C code)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Optional,
    Union,
)

from jive.ui.constants import (
    EVENT_CONSUME,
)
from jive.ui.window import (
    Window,
    transition_fade_in_fast,
    transition_none,
    transition_push_left_static_title,
    transition_push_right_static_title,
)
from jive.utils.log import logger

if TYPE_CHECKING:
    from jive.ui.event import Event
    from jive.ui.surface import Surface as JiveSurface

__all__ = ["ContextMenuWindow"]

log = logger("jivelite.ui")


class ContextMenuWindow(Window):
    """
    A context-menu window with a screenshot background overlay.

    Extends :class:`Window` with a captured and shaded background that
    dims the previous screen content, creating a modal overlay effect.

    Parameters
    ----------
    title : str, optional
        An optional title string for the context menu.
    window_id : str or int, optional
        An optional identifier for the window.
    no_shading : bool
        If ``True``, the captured background is not shaded/dimmed.
        Defaults to ``False`` (shading is applied).
    """

    def __init__(
        self,
        title: Optional[str] = None,
        window_id: Optional[str] = None,
        no_shading: bool = False,
    ) -> None:
        # Use "context_menu" as the style key (matching Lua)
        super().__init__("context_menu", title, window_id=window_id)

        # Override default transitions (matching Lua original)
        self._DEFAULT_SHOW_TRANSITION = transition_fade_in_fast
        self._DEFAULT_HIDE_TRANSITION = transition_none

        # Context menu specific flags
        self.set_allow_screensaver(False)
        self.set_show_framework_widgets(False)
        self.set_context_menu(True)

        # Button actions — context menus have no left button action
        # and right button maps to cancel
        self._button_actions: dict[str, Optional[str]] = {
            "lbutton": None,
            "rbutton": "cancel",
        }

        # Register cancel and add actions to dismiss all context menus
        self.add_action_listener("cancel", self, ContextMenuWindow._cancel_action)
        self.add_action_listener("add", self, ContextMenuWindow._cancel_action)

        # Shading option
        self.no_shading: bool = no_shading

        # Whether this is the topmost (root) context menu in a stack
        self.is_top_context_menu: bool = False

        # Capture the current screen as background
        self._bg: Optional[JiveSurface] = self._capture()

    # ------------------------------------------------------------------
    # Action handlers
    # ------------------------------------------------------------------

    @staticmethod
    def _cancel_action(self_or_cls: Any, event: Any = None) -> int:
        """
        Cancel action — hide all context menus.

        This is registered as an action listener, so it receives
        ``(self, event)`` when called through the action dispatch system.
        """
        _hide_context_menus()
        return int(EVENT_CONSUME)

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------

    def draw(self, surface: JiveSurface, layer: int = 0xFF) -> None:
        """
        Draw the context menu window.

        First draws the captured background screenshot (unless a
        transition is currently active, which handles its own drawing),
        then draws the window's own widgets on top.

        Parameters
        ----------
        surface : Surface
            The target surface to draw onto.
        layer : int, optional
            The rendering layer bitmask.
        """
        # Draw snapshot of previous screen (unless transition is active)
        try:
            from jive.ui.framework import framework as fw

            transition_active = fw._transition is not None
        except (ImportError, AttributeError):
            transition_active = False

        if not transition_active and self._bg is not None:
            self._bg.blit(surface, 0, 0)

        # Draw window's own content on top
        super().draw(surface, layer)

    # ------------------------------------------------------------------
    # Show / Hide overrides
    # ------------------------------------------------------------------

    def show(self, transition: Optional[Callable] = None) -> None:
        """
        Show the context menu window.

        If there is already a context menu on top of the window stack,
        this window reuses the existing context menu's background and
        shows with a push-left transition (to allow "back" navigation
        between stacked context menus).

        Otherwise, shows with the default fade-in-fast transition and
        marks this as the top-level context menu.
        """
        top_cm = self._get_top_window_context_menu()

        if top_cm is not None:
            # Stacking on top of an existing context menu
            self._bg = top_cm._bg
            self._button_actions["lbutton"] = "back"
            super().show(transition or transition_push_left_static_title)
        else:
            # First context menu in the stack
            super().show(transition)
            self.is_top_context_menu = True

    def hide(
        self, transition: Optional[Callable] = None, sound: Optional[str] = None
    ) -> None:
        """
        Hide the context menu window.

        If the window below this one in the stack is also a context menu,
        uses a push-right transition.  Otherwise uses the default
        hide transition.
        """
        try:
            from jive.ui.framework import framework as fw

            stack = fw.window_stack

            # Find the first non-always-on-top window index
            idx = 0
            while idx < len(stack) and getattr(stack[idx], "always_on_top", False):
                idx += 1

            # Check if the window below the current top is a context menu
            if (
                idx + 1 < len(stack)
                and hasattr(stack[idx + 1], "is_context_menu")
                and stack[idx + 1].is_context_menu()
            ):
                super().hide(transition or transition_push_right_static_title, sound)
            else:
                super().hide(transition, sound)
        except (ImportError, AttributeError):
            super().hide(transition, sound)

    # ------------------------------------------------------------------
    # Screen capture
    # ------------------------------------------------------------------

    def _capture(self) -> Optional[JiveSurface]:
        """
        Capture the current screen contents and optionally shade them.

        Returns
        -------
        Surface or None
            A shaded (or unshaded) copy of the current screen, or
            ``None`` if the Framework is not initialised.
        """
        try:
            from jive.ui.framework import framework as fw
            from jive.ui.surface import Surface

            sw, sh = fw.get_screen_size()
            if sw <= 0 or sh <= 0:
                log.debug(
                    "ContextMenuWindow._capture: invalid screen size %dx%d", sw, sh
                )
                return None

            img = Surface.new_rgb(sw, sh)

            # Take snapshot of current screen by drawing the top window
            screen = fw.get_screen()
            if screen is not None:
                # Draw background
                if fw._background is not None:
                    try:
                        fw._background.blit(img, 0, 0)
                    except Exception:
                        img.pg.fill((0, 0, 0))
                else:
                    img.pg.fill((0, 0, 0))

                # Draw top window
                if fw.window_stack:
                    top = fw.window_stack[0]
                    top.check_layout()
                    top.draw(img)

                # Draw global widgets
                for gw in fw._global_widgets:
                    gw.check_layout()
                    gw.draw(img)

            # Apply semi-transparent dark shading
            if not self.no_shading:
                # RGBA 0x00000085 = black with ~52% opacity
                # We use filled_rectangle with alpha blending
                img.filled_rectangle(0, 0, sw, sh, 0x00000085)

            return img
        except Exception:
            log.warn("ContextMenuWindow._capture failed")
            return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_top_window_context_menu(self) -> Optional[ContextMenuWindow]:
        """
        Return the topmost non-transient context-menu window in the
        stack, or ``None`` if no context menu is currently showing.
        """
        try:
            from jive.ui.framework import framework as fw

            # Find the first non-always-on-top window
            stack = fw.window_stack
            idx = 0
            while idx < len(stack) and getattr(stack[idx], "always_on_top", False):
                idx += 1

            if idx < len(stack):
                top_window = stack[idx]
                if (
                    hasattr(top_window, "is_context_menu")
                    and top_window.is_context_menu()
                ):
                    return top_window  # type: ignore[return-value]
        except (ImportError, AttributeError):
            pass

        return None

    # ------------------------------------------------------------------
    # Button actions (simplified interface for context menus)
    # ------------------------------------------------------------------

    def set_button_action(self, button: str, action: Optional[str]) -> None:
        """
        Set the action for a named button (e.g. ``"lbutton"``,
        ``"rbutton"``).

        Parameters
        ----------
        button : str
            The button name.
        action : str or None
            The action name, or ``None`` to disable the button.
        """
        self._button_actions[button] = action

    def get_button_action(self, button: str) -> Optional[str]:
        """Return the action mapped to *button*, or ``None``."""
        return self._button_actions.get(button)

    # ------------------------------------------------------------------
    # Representation
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        title = self.get_title()
        title_part = f", title={title!r}" if title else ""
        has_bg = self._bg is not None
        return (
            f"ContextMenuWindow(captured={has_bg}, "
            f"shading={not self.no_shading}{title_part})"
        )

    def __str__(self) -> str:
        return self.__repr__()


# ---------------------------------------------------------------------------
# Module-level helper functions
# ---------------------------------------------------------------------------


def _hide_context_menus() -> None:
    """
    Hide all context-menu windows from the window stack.

    Iterates the stack from top to bottom and hides any window whose
    ``is_context_menu()`` returns ``True``.
    """
    try:
        from jive.ui.framework import framework as fw

        # Collect context menus to hide (iterate a copy since hiding
        # modifies the stack).
        to_hide = [
            w
            for w in list(fw.window_stack)
            if hasattr(w, "is_context_menu") and w.is_context_menu()
        ]

        for w in to_hide:
            w.hide()  # type: ignore[union-attr]
    except (ImportError, AttributeError):
        pass
