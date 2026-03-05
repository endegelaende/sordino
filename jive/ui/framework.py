"""
jive.ui.framework — Framework singleton for the Jivelite Python3 port.

Ported from ``jive/ui/Framework.lua`` and ``jive_framework.c`` in the
original jivelite project.

The Framework is the central coordinator of the UI:

* **Screen** — initialises pygame display, manages the video surface
* **Window stack** — push/pop/show/hide windows, transition management
* **Event dispatch** — global listeners, per-widget dispatch, event queue
* **Action registry** — maps input events (keys, IR, gestures) to named
  actions that widgets can listen for
* **Animation** — tracks widgets with active animations, ticks them each frame
* **Timer integration** — runs the Timer queue once per frame
* **Sound** — load/play/enable named WAV sounds

The module exposes a module-level ``framework`` singleton instance.  All
other modules import it as::

    from jive.ui.framework import framework

Copyright 2010 Logitech. All Rights Reserved. (original Lua/C code)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

import math
import time
from collections import deque
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Sequence,
    Set,
    Tuple,
    TypeAlias,
    Union,
)

import pygame

from jive.ui.constants import (
    ACTION,
    ALIGN_CENTER,
    EVENT_ALL,
    EVENT_ALL_INPUT,
    EVENT_CHAR_PRESS,
    EVENT_CONSUME,
    EVENT_FOCUS_GAINED,
    EVENT_FOCUS_LOST,
    EVENT_GESTURE,
    EVENT_HIDE,
    EVENT_IR_ALL,
    EVENT_IR_DOWN,
    EVENT_IR_HOLD,
    EVENT_IR_PRESS,
    EVENT_KEY_ALL,
    EVENT_KEY_DOWN,
    EVENT_KEY_HOLD,
    EVENT_KEY_PRESS,
    EVENT_KEY_UP,
    EVENT_MOUSE_ALL,
    EVENT_MOUSE_DOWN,
    EVENT_MOUSE_DRAG,
    EVENT_MOUSE_HOLD,
    EVENT_MOUSE_MOVE,
    EVENT_MOUSE_PRESS,
    EVENT_MOUSE_UP,
    EVENT_NONE,
    EVENT_QUIT,
    EVENT_SCROLL,
    EVENT_SHOW,
    EVENT_UNUSED,
    EVENT_UPDATE,
    EVENT_VISIBLE_ALL,
    EVENT_WINDOW_ACTIVE,
    EVENT_WINDOW_INACTIVE,
    EVENT_WINDOW_POP,
    EVENT_WINDOW_PUSH,
    EVENT_WINDOW_RESIZE,
    FRAME_RATE_DEFAULT,
    EventStatus,
    EventType,
    Gesture,
    Key,
)
from jive.ui.event import Event
from jive.ui.task import Task
from jive.ui.timer import Timer
from jive.utils.log import logger

if TYPE_CHECKING:
    from jive.ui.surface import Surface
    from jive.ui.widget import Widget

__all__ = ["Framework", "framework"]

log = logger("jivelite.ui")

# ---------------------------------------------------------------------------
# Startup timestamp — shared epoch with event.py / timer.py
# ---------------------------------------------------------------------------

_startup_time_ns: int = time.monotonic_ns()


def _get_ticks() -> int:
    """Return milliseconds since startup."""
    return (time.monotonic_ns() - _startup_time_ns) // 1_000_000


# ---------------------------------------------------------------------------
# Listener handle type (same shape as Widget.ListenerHandle)
# ---------------------------------------------------------------------------

ListenerHandle: TypeAlias = List[Any]

# ---------------------------------------------------------------------------
# Key mapping: pygame key → Jive Key code
# ---------------------------------------------------------------------------

# Maps pygame key constants to Jive hardware key codes.
#
# IMPORTANT: Only true navigation / hardware / media keys belong here.
# Regular printable keys (letters, digits, space) must NOT be listed —
# they produce CHAR_PRESS events instead, which are routed through the
# char_action_mappings table (matching the original C keymap in
# jive_framework.c where only SDLK_LEFT, SDLK_RIGHT, … and
# SDLK_AudioPlay etc. are mapped to JIVE_KEY_* constants).
#
# Previously K_SPACE, K_p, K_s, K_m, K_0..K_9 were mapped here, which
# suppressed CHAR_PRESS and caused wrong actions (e.g. Space → "play"
# instead of "pause").
_PYGAME_KEY_MAP: Dict[int, int] = {
    # Navigation keys (match C keymap exactly)
    pygame.K_RETURN: int(Key.GO),
    pygame.K_KP_ENTER: int(Key.GO),
    pygame.K_ESCAPE: int(Key.BACK),
    pygame.K_BACKSPACE: int(Key.BACK),
    pygame.K_UP: int(Key.UP),
    pygame.K_DOWN: int(Key.DOWN),
    pygame.K_LEFT: int(Key.LEFT),
    pygame.K_RIGHT: int(Key.RIGHT),
    pygame.K_HOME: int(Key.HOME),
    pygame.K_END: int(Key.BACK),
    pygame.K_PAGEUP: int(Key.PAGE_UP),
    pygame.K_PAGEDOWN: int(Key.PAGE_DOWN),
    # Keypad add → ADD (matches C: SDLK_KP_PLUS → JIVE_KEY_ADD)
    pygame.K_KP_PLUS: int(Key.ADD),
    pygame.K_MENU: int(Key.ADD),
    # F-keys → presets (match C keymap)
    pygame.K_F10: int(Key.PRESET_0),
    pygame.K_F1: int(Key.PRESET_1),
    pygame.K_F2: int(Key.PRESET_2),
    pygame.K_F3: int(Key.PRESET_3),
    pygame.K_F4: int(Key.PRESET_4),
    pygame.K_F5: int(Key.PRESET_5),
    pygame.K_F6: int(Key.PRESET_6),
    pygame.K_F7: int(Key.PRESET_7),
    pygame.K_F8: int(Key.PRESET_8),
    pygame.K_F9: int(Key.PRESET_9),
    pygame.K_PRINTSCREEN: int(Key.PRINT),
    pygame.K_SYSREQ: int(Key.PRINT),
    pygame.K_POWER: int(Key.POWER),
}

# Time threshold for key-hold detection (ms)
_KEY_HOLD_TIME: int = 600
_LONG_HOLD_TIME: int = 3500

# Time threshold for mouse-hold detection (ms)
_MOUSE_HOLD_TIME: int = 800


# ---------------------------------------------------------------------------
# Framework class
# ---------------------------------------------------------------------------


class Framework:
    """
    Central UI coordinator — event loop, window stack, global listeners,
    action registry, screen management, animation dispatch.

    Instantiated once as the module-level ``framework`` singleton.
    """

    def __init__(self) -> None:
        # ---- Screen / display ----
        self._screen_surface: Optional[Surface] = None
        self._screen_w: int = 0
        self._screen_h: int = 0
        self._fullscreen: bool = False
        self._background: Optional[Any] = None  # Tile or Surface

        # ---- Window stack ----
        self.window_stack: List[Widget] = []

        # ---- Global widgets (shown on all windows) ----
        self._global_widgets: List[Widget] = []

        # ---- Listeners ----
        self._global_listeners: List[ListenerHandle] = []
        self._unused_listeners: List[ListenerHandle] = []

        # ---- Animations ----
        self._animation_widgets: List[Widget] = []

        # ---- Event queue ----
        self._event_queue: Deque[Event] = deque()  # type: ignore[name-defined]

        # ---- Action registry ----
        self._actions_by_name: Dict[str, int] = {}
        self._actions_by_index: Dict[int, str] = {}
        self._next_action_index: int = 1

        # ---- Key state (for press/hold detection) ----
        self._keys_down: Dict[int, int] = {}  # key_code → ticks when pressed
        self._keys_held: set[int] = set()

        # ---- Mouse state (for press/hold detection) ----
        self._mouse_down_pos: Optional[Tuple[int, int]] = None
        self._mouse_down_ticks: int = 0
        self._mouse_held: bool = False

        # ---- Sound ----
        self._sounds: Dict[str, Any] = {}
        self._sound_enabled: Dict[str, bool] = {}

        # ---- Frame rate ----
        self._frame_rate: int = FRAME_RATE_DEFAULT
        self._clock: Optional[pygame.time.Clock] = None

        # ---- Most recent input type ----
        self._most_recent_input_type: Optional[str] = None

        # ---- Running flag ----
        self._running: bool = False
        self._initialised: bool = False

        # ---- Wakeup callback ----
        self._wakeup_fn: Optional[Callable[[], None]] = None

        # ---- Transition ----
        self._transition: Optional[Callable[..., None]] = None

        # ---- Update screen flag (splash screen gating) ----
        self._update_screen_enabled: bool = True

        # ---- Dirty-screen flag ----
        # When True, the next update_screen() call will redraw.
        # When False, update_screen() skips rendering (nothing changed).
        self._screen_dirty: bool = True

    # ==================================================================
    # Initialisation / Shutdown
    # ==================================================================

    def init(
        self,
        width: int = 480,
        height: int = 272,
        title: str = "Sordino",
        fullscreen: bool = False,
        frame_rate: int = FRAME_RATE_DEFAULT,
    ) -> None:
        """
        Initialise pygame and open the display window.

        Must be called before any other Framework method (except action
        registration which can happen early).
        """
        if self._initialised:
            return

        pygame.init()
        pygame.freetype.init()

        flags = 0
        if fullscreen:
            flags |= pygame.FULLSCREEN

        pg_screen = pygame.display.set_mode((width, height), flags)
        pygame.display.set_caption(title)

        # Replace the default pygame snake icon with our app icon
        self._set_window_icon()

        from jive.ui.surface import Surface

        self._screen_surface = Surface(pg_screen)
        self._screen_w = width
        self._screen_h = height
        self._frame_rate = frame_rate
        self._clock = pygame.time.Clock()

        # Push the frame rate into Widget class attribute
        from jive.ui.widget import Widget

        Widget._frame_rate = frame_rate

        self._initialised = True

        # Register default actions early so that Window constructors can
        # reference actions like "back" without warnings.
        self._register_default_actions()

        # Enable key repeat so holding an arrow key generates repeated
        # KEYDOWN events (200ms initial delay, 50ms repeat interval).
        # Without this, holding a key only fires once then waits 600ms
        # for KEY_HOLD — making menu scrolling feel sluggish.
        pygame.key.set_repeat(200, 50)

        log.info(f"Framework.init: {width}x{height} @ {frame_rate}fps")

    def _set_window_icon(self) -> None:
        """Set the app icon on the pygame window (title bar + taskbar)."""
        import sys
        from pathlib import Path

        pkg_dir = Path(__file__).resolve().parent.parent  # jive/
        meipass = getattr(sys, "_MEIPASS", None)

        candidates = []
        if meipass:
            candidates.append(Path(meipass) / "jive" / "data" / "jive" / "app.png")
            candidates.append(Path(meipass) / "share" / "jive" / "jive" / "app.png")
        candidates.append(pkg_dir / "data" / "jive" / "app.png")
        candidates.append(pkg_dir.parent / "share" / "jive" / "jive" / "app.png")

        for icon_path in candidates:
            if icon_path.is_file():
                try:
                    icon_surface = pygame.image.load(str(icon_path))
                    pygame.display.set_icon(icon_surface)
                    return
                except Exception:
                    pass

    def set_update_screen(self, enabled: bool) -> None:
        """Enable or disable screen updates.

        Used by ``JiveMain`` to suppress rendering during the splash
        screen phase until the user interacts or the splash timer fires.
        """
        self._update_screen_enabled = bool(enabled)

    # Lua-compatible camelCase alias
    setUpdateScreen = set_update_screen

    def stop(self) -> None:
        """Request the event loop to stop after the current frame."""
        self._running = False

    def quit(self) -> None:
        """Shut down the display and pygame."""
        self._running = False
        Timer.clear_all()
        if pygame.get_init():
            pygame.quit()
        self._initialised = False

    # ==================================================================
    # Screen
    # ==================================================================

    def set_video_mode(
        self,
        width: int,
        height: int,
        bpp: int = 0,
        fullscreen: bool = False,
    ) -> None:
        """Resize the display window.

        Called by skin applets (e.g. ``JogglerSkin.skin()``) to set the
        screen resolution before building the style dict.  Mirrors the
        Lua ``Framework:setVideoMode(w, h, bpp, fullscreen)``.
        """
        if width == self._screen_w and height == self._screen_h:
            if fullscreen == getattr(self, "_fullscreen", False):
                return  # nothing to do

        import pygame

        flags = 0
        if fullscreen:
            flags |= pygame.FULLSCREEN

        pg_screen = pygame.display.set_mode((width, height), flags)

        from jive.ui.surface import Surface

        self._screen_surface = Surface(pg_screen)
        self._screen_w = width
        self._screen_h = height
        self._fullscreen = fullscreen

        # Clear the new surface to black immediately to prevent stale
        # frame artifacts (e.g. a thin strip along the right edge when
        # the old surface was smaller than the new one).
        pg_screen.fill((0, 0, 0))

        # Invalidate the style cache — style values (fonts, padding,
        # sizes) computed for the old resolution are stale.
        try:
            from jive.ui.style import skin as _skin_db

            _skin_db.invalidate()
        except (ImportError, AttributeError):
            pass

        # Mark all widgets as needing re-skin and re-layout so they
        # pick up the new screen dimensions on the next check_layout()
        # call (which happens in update_screen()).
        #
        # IMPORTANT: we must NOT call re_skin() here because
        # set_video_mode() is called from inside the skin method
        # (e.g. JogglerSkinApplet.skin()) *before* the new style dict
        # has been installed into the StyleDB.  Calling re_skin() would
        # eagerly clear cached values (preferred_bounds, padding, tiles,
        # images, etc.) and then _skin() would run against an empty
        # style dict, leaving widgets with zero/None values.
        #
        # This matches the C original where set_video_mode() simply
        # bumps ``next_jive_origin++`` and the actual re-skinning
        # happens lazily during the next _draw_screen() loop when
        # checkLayout() → checkSkin() detects the origin mismatch.
        def _mark_dirty_recursive(widget: "Widget") -> None:
            widget._needs_skin = True
            widget._needs_layout = True
            widget._needs_draw = True
            widget.iterate(lambda child: _mark_dirty_recursive(child))

        for w in self.window_stack:
            _mark_dirty_recursive(w)
        for gw in self._global_widgets:
            _mark_dirty_recursive(gw)

        # Force a full redraw on the next update_screen() call.
        self._screen_dirty = True

        log.info(f"set_video_mode: {width}x{height} fullscreen={fullscreen}")

    # Lua-compatible camelCase alias
    setVideoMode = set_video_mode

    def get_screen_size(self) -> Tuple[int, int]:
        """Return ``(width, height)`` of the current display."""
        return self._screen_w, self._screen_h

    def get_screen(self) -> Optional[Surface]:
        """Return the screen ``Surface``, or ``None`` before init."""
        return self._screen_surface

    def get_background(self) -> Optional[Any]:
        """Return the current background image/tile."""
        return self._background

    def set_background(self, bg: Any) -> None:
        """Set the background image/tile.

        If *bg* is a :class:`~jive.ui.tile.Tile` whose underlying image
        is smaller than the current screen, the image is pre-scaled to
        fill the screen so that wallpapers never tile/repeat.
        """
        if bg is not None and self._screen_w > 0 and self._screen_h > 0:
            try:
                from jive.ui.tile import Tile

                if isinstance(bg, Tile) and bg._sdl is not None:
                    iw = bg._sdl.get_width()
                    ih = bg._sdl.get_height()
                    sw, sh = self._screen_w, self._screen_h
                    if (iw, ih) != (sw, sh) and iw > 0 and ih > 0:
                        import pygame

                        bg._sdl = pygame.transform.smoothscale(bg._sdl, (sw, sh))
                        bg._w[0] = sw
                        bg._h[0] = sh
            except (ImportError, AttributeError, Exception) as exc:
                log.warning("wallpaper scaling failed: %s", exc)
        self._background = bg

    # ==================================================================
    # Frame rate
    # ==================================================================

    def get_frame_rate(self) -> int:
        return self._frame_rate

    # ==================================================================
    # Ticks
    # ==================================================================

    @staticmethod
    def get_ticks() -> int:
        """Return milliseconds since startup."""
        return _get_ticks()

    # ==================================================================
    # Window stack
    # ==================================================================

    def push_window(self, window: Widget) -> None:
        """
        Push *window* onto the window stack and make it active.

        The previously active window receives ``EVENT_WINDOW_INACTIVE``.
        """
        # Deactivate current top window
        if self.window_stack:
            old_top = self.window_stack[0]
            old_top._event(Event(int(EVENT_WINDOW_INACTIVE), ticks=_get_ticks()))
            old_top._event(Event(int(EVENT_HIDE), ticks=_get_ticks()))

        self.window_stack.insert(0, window)
        window._event(Event(int(EVENT_WINDOW_PUSH), ticks=_get_ticks()))
        window._event(Event(int(EVENT_SHOW), ticks=_get_ticks()))
        window._event(Event(int(EVENT_WINDOW_ACTIVE), ticks=_get_ticks()))
        self.re_draw(None)

    def pop_window(self, window: Optional[Widget] = None) -> Optional[Widget]:
        """
        Pop *window* from the stack (or the top window if *window* is
        ``None``).  The new top window receives ``EVENT_WINDOW_ACTIVE``.

        Returns the popped window.
        """
        if not self.window_stack:
            return None

        if window is None:
            window = self.window_stack[0]

        if window not in self.window_stack:
            return None

        was_top = self.window_stack[0] is window
        self.window_stack.remove(window)

        window._event(Event(int(EVENT_HIDE), ticks=_get_ticks()))
        window._event(Event(int(EVENT_WINDOW_POP), ticks=_get_ticks()))

        if was_top and self.window_stack:
            new_top = self.window_stack[0]
            new_top._event(Event(int(EVENT_SHOW), ticks=_get_ticks()))
            new_top._event(Event(int(EVENT_WINDOW_ACTIVE), ticks=_get_ticks()))

        self.re_draw(None)
        return window

    def is_current_window(self, window: Widget) -> bool:
        """Return ``True`` if *window* is the topmost window."""
        return bool(self.window_stack) and self.window_stack[0] is window

    def is_window_in_stack(self, window: Widget) -> bool:
        """Return ``True`` if *window* is anywhere in the stack."""
        return window in self.window_stack

    # ==================================================================
    # Global widgets
    # ==================================================================

    def add_widget(self, widget: Widget) -> None:
        """Add a global widget shown on all windows."""
        if widget not in self._global_widgets:
            self._global_widgets.append(widget)
            widget._event(Event(int(EVENT_SHOW), ticks=_get_ticks()))
            self.re_draw(None)

    def remove_widget(self, widget: Widget) -> None:
        """Remove a global widget."""
        if widget in self._global_widgets:
            self._global_widgets.remove(widget)
            widget._event(Event(int(EVENT_HIDE), ticks=_get_ticks()))
            self.re_draw(None)

    def get_widgets(self) -> List[Widget]:
        """Return the list of global widgets."""
        return list(self._global_widgets)

    # ==================================================================
    # Global listeners
    # ==================================================================

    def add_listener(
        self,
        mask: int,
        listener: Callable[[Event], int],
        priority: int = 0,
    ) -> ListenerHandle:
        """
        Add a global event listener.

        Matches the Lua original: negative priority (or default 0 / True)
        → ``globalListeners`` (called **before** widget listeners);
        positive priority → ``unusedListeners`` (called **after** widget
        listeners, only when no widget consumed the event).

        The Lua ``convertInputToAction`` is registered with priority=9999,
        so it ends up in ``unusedListeners`` and only fires when no widget
        has consumed the key event directly.

        Returns a handle for ``remove_listener``.
        """
        handle: ListenerHandle = [mask, listener]
        if priority > 0:
            # Positive priority → unused listeners (after widgets)
            self._unused_listeners.append(handle)
        else:
            # Negative or zero priority → global listeners (before widgets)
            self._global_listeners.insert(0, handle)
        return handle

    def remove_listener(self, handle: ListenerHandle) -> None:
        """Remove a global listener by handle."""
        try:
            self._global_listeners.remove(handle)
        except ValueError as exc:
            log.debug("remove failed: %s", exc)
        try:
            self._unused_listeners.remove(handle)
        except ValueError as exc:
            log.debug("remove failed: %s", exc)

    def add_unused_listener(
        self,
        mask: int,
        listener: Callable[[Event], int],
    ) -> ListenerHandle:
        """
        Add a listener for events that were not consumed by any widget.
        """
        handle: ListenerHandle = [mask, listener]
        self._unused_listeners.insert(0, handle)
        return handle

    def remove_unused_listener(self, handle: ListenerHandle) -> None:
        try:
            self._unused_listeners.remove(handle)
        except ValueError as exc:
            log.debug("remove failed: %s", exc)

    # ==================================================================
    # Event dispatch
    # ==================================================================

    def push_event(self, event: Event) -> None:
        """
        Push an event onto the queue for processing in the next frame.
        Thread-safe (uses a deque).
        """
        self._event_queue.append(event)

    def dispatch_event(self, widget: Optional[Widget], event: Event) -> int:
        """
        Dispatch *event* to *widget*'s listeners.

        If *widget* is ``None`` the event goes to the topmost window.

        Global listeners are checked **first**; if they consume the event
        it is not forwarded to the widget.  If the widget does not consume
        the event, unused listeners are checked.
        """
        etype = event.get_type()

        is_action = bool(etype & int(ACTION))
        action_name: Optional[str] = None
        if is_action:
            try:
                idx = event.get_action_internal()
                action_name = self.get_action_event_name_by_index(idx)
            except (TypeError, AttributeError):
                pass
            log.debug(
                f"dispatch_event: ACTION {action_name!r}, global_listeners={len(self._global_listeners)}, window_stack={len(self.window_stack)}"
            )

        # ---- Global listeners ----
        for handle in self._global_listeners:
            mask, callback = handle[0], handle[1]
            if etype & mask:
                try:
                    r = callback(event)
                    if is_action:
                        log.debug(
                            f"dispatch_event: ACTION {action_name!r} -> global listener mask=0x{mask:08X} returned {r}"
                        )
                    if r and (r & int(EVENT_CONSUME)):
                        return int(r)
                except Exception as exc:
                    log.warn("global listener error: %s", exc)

        # ---- Widget listeners ----
        target = widget
        if target is None and self.window_stack:
            target = self.window_stack[0]

        result = int(EVENT_UNUSED)
        if target is not None:
            result = target._event(event)
            if is_action:
                log.debug(
                    f"dispatch_event: ACTION {action_name!r} -> widget {type(target).__name__!r} returned {result}"
                )

        # ---- Unused listeners (if not consumed) ----
        if not (result & int(EVENT_CONSUME)):
            for handle in self._unused_listeners:
                mask, callback = handle[0], handle[1]
                if etype & mask:
                    try:
                        r = callback(event)
                        if r and (r & int(EVENT_CONSUME)):
                            result |= r
                            break
                    except Exception as exc:
                        log.warn("unused listener error: %s", exc)

        if is_action and not (result & int(EVENT_CONSUME)):
            log.debug(f"dispatch_event: ACTION {action_name!r} was NOT consumed by any listener!")

        return result

    def _process_event_queue(self) -> bool:
        """
        Drain the event queue, dispatching each event.

        Returns ``True`` to keep running, ``False`` on quit.
        """
        # Ensure the top window has valid layout before dispatching
        # events.  Without this, z_widgets may be empty and mouse
        # events silently miss all child widgets.  Matches the Lua
        # original where updateScreen (which runs check_layout) is
        # called before event processing.
        if self.window_stack:
            top = self.window_stack[0]
            if top._needs_skin or top._needs_layout:
                try:
                    top.check_layout()
                except Exception as exc:
                    log.warning("check_layout failed: %s", exc)

        while self._event_queue:
            event = self._event_queue.popleft()

            # Check the event TYPE — pygame.QUIT produces an event with
            # type EVENT_QUIT (0x0002).  This is not a dispatch result;
            # no listener needs to consume it.
            if event.get_type() == int(EVENT_QUIT):
                return False

            r = self.dispatch_event(None, event)
            if r & int(EVENT_QUIT):
                return False
        return True

    # ==================================================================
    # Animation widgets
    # ==================================================================

    def _add_animation_widget(self, widget: Widget) -> None:
        """Register a widget that has active animations."""
        if widget not in self._animation_widgets:
            self._animation_widgets.append(widget)

    def _remove_animation_widget(self, widget: Widget) -> None:
        """Unregister an animation widget (when it has no more animations)."""
        try:
            self._animation_widgets.remove(widget)
        except ValueError as exc:
            log.debug("remove failed: %s", exc)

    def _tick_animations(self) -> None:
        """
        Call animation functions for all registered widgets.

        Each animation has a frame-skip counter; the callback is only
        invoked when the counter reaches zero.
        """
        for widget in list(self._animation_widgets):
            for anim in list(widget.animations):
                # anim = [callback, frame_skip, counter]
                anim[2] -= 1
                if anim[2] <= 0:
                    anim[2] = anim[1]  # reset counter
                    try:
                        anim[0]()
                    except Exception as exc:
                        log.warn("animation error: %s", exc)

    # ==================================================================
    # Screen update
    # ==================================================================

    def re_draw(self, rect: Optional[Tuple[int, int, int, int]] = None) -> None:
        """
        Mark *rect* (or the whole screen if ``None``) for redrawing.

        Sets the global dirty flag so that the next ``update_screen()``
        call performs a full redraw.
        """
        self._screen_dirty = True

    def update_screen(self) -> None:
        """
        Perform one frame of rendering:

        1. Draw background
        2. If a transition is active, run the transition step
        3. Otherwise: check skin/layout on the top window, draw it
        4. Draw global widgets
        5. Flip the display
        """
        if self._screen_surface is None or not self._initialised:
            return

        if not self._update_screen_enabled:
            return

        # Skip rendering when nothing has changed (dirty-flag optimisation).
        # Transitions and animations always force a redraw.
        if not self._screen_dirty and self._transition is None and not self._animation_widgets:
            return

        self._screen_dirty = False

        screen = self._screen_surface

        # Reset offset and clip to full screen before each frame.
        # Matches C ``_draw_screen`` which calls
        # ``jive_surface_set_clip(srf, NULL)`` and always starts with
        # offset (0, 0).
        screen.set_offset(0, 0)
        sw, sh = screen.get_size()
        screen.pg.set_clip(None)

        # Background — fill the entire screen.
        # Matches C: jive_tile_blit(jive_background, srf, 0, 0, screen_w, screen_h)
        if self._background is not None:
            try:
                self._background.blit(screen, 0, 0, sw, sh)
            except Exception:
                screen.pg.fill((0, 0, 0))
        else:
            screen.pg.fill((0, 0, 0))

        # Transition takes over rendering while active
        if self._transition is not None:
            top = self.window_stack[0] if self.window_stack else None
            try:
                self._transition(top, screen)
            except Exception as exc:
                log.warn("transition error: %s", exc)
                self._transition = None
        else:
            # Top window
            if self.window_stack:
                top = self.window_stack[0]
                top.check_layout()
                top.draw(screen)

        # Global widgets
        for gw in self._global_widgets:
            gw.check_layout()
            gw.draw(screen)

        # Flip
        screen.flip()

    # ==================================================================
    # Transitions
    # ==================================================================

    def _start_transition(self, step_fn: Optional[Callable[..., None]]) -> None:
        """
        Start a screen transition.

        *step_fn* is called each frame with ``(widget, surface)`` until
        it calls ``_kill_transition()``.  If *step_fn* is ``None`` the
        current transition is cleared (equivalent to ``_kill_transition``).
        """
        self._transition = step_fn

    def _kill_transition(self) -> None:
        """End the current transition (if any)."""
        self._transition = None

    # ==================================================================
    # Action registry
    # ==================================================================

    def register_action(self, name: str) -> int:
        """
        Register a named action.  Returns the action index.

        If the action is already registered the existing index is returned.
        """
        if name in self._actions_by_name:
            return self._actions_by_name[name]

        idx = self._next_action_index
        self._next_action_index += 1
        self._actions_by_name[name] = idx
        self._actions_by_index[idx] = name
        return idx

    def assert_action_name(self, name: str) -> None:
        """Raise ``ValueError`` if *name* is not a registered action."""
        if name not in self._actions_by_name:
            raise ValueError(f"Unknown action: {name!r}")

    def get_action_event_index_by_name(self, name: str) -> Optional[int]:
        """Return the index for a named action, or ``None``."""
        return self._actions_by_name.get(name)

    def get_action_event_name_by_index(self, index: int) -> Optional[str]:
        """Return the name for an action index, or ``None``."""
        return self._actions_by_index.get(index)

    def push_action(self, name: str) -> None:
        """Create an ACTION event for *name* and push it onto the queue."""
        log.info(f"push_action({name!r})")
        idx = self._actions_by_name.get(name)
        if idx is None:
            idx = self.register_action(name)
        self.push_event(Event(int(ACTION), index=idx))

    def dump_actions(self) -> str:
        """Return a human-readable string of all registered actions."""
        return ", ".join(sorted(self._actions_by_name.keys()))

    def register_actions(self, mappings: Dict[str, Any]) -> None:
        """Register actions from input-to-action mapping tables.

        *mappings* is a dict typically containing:

        * ``char_action_mappings`` — ``{"press": {char: action, ...}}``
        * ``key_action_mappings`` — ``{"press": {code: action, ...}, "hold": {...}}``
        * ``ir_action_mappings`` — ``{"press": {name: action, ...}, "hold": {...}}``
        * ``gesture_action_mappings`` — ``{gesture_code: action, ...}``
        * ``action_action_mappings`` — ``{action: action, ...}``
        * ``unassigned_action_mappings`` — ``[action_name, ...]``

        All action names found in the mappings are registered, and
        key/char/gesture mappings are installed via
        :meth:`map_input_to_action`.
        """
        # --- Unassigned actions (just register the names) ---
        unassigned = mappings.get("unassigned_action_mappings", [])
        for name in unassigned:
            self.register_action(name)

        # --- Action → action mappings (register + store for translation) ---
        action_maps = mappings.get("action_action_mappings", {})
        for src_action, dst_action in action_maps.items():
            self.register_action(src_action)
            self.register_action(dst_action)
            self.set_action_to_action_translation(src_action, dst_action)

        # --- Character → action mappings ---
        char_maps = mappings.get("char_action_mappings", {})
        for sub_type, char_dict in char_maps.items():
            if sub_type == "press":
                for char, action in char_dict.items():
                    self.register_action(action)
                    # Map CHAR_PRESS with the character's ordinal as code
                    code = ord(char) if isinstance(char, str) and len(char) == 1 else 0
                    if code:
                        self.map_input_to_action(int(EVENT_CHAR_PRESS), code, action)

        # --- Key → action mappings ---
        key_maps = mappings.get("key_action_mappings", {})
        for sub_type, key_dict in key_maps.items():
            for key_code, action in key_dict.items():
                self.register_action(action)
                if sub_type == "press":
                    self.map_input_to_action(int(EVENT_KEY_PRESS), int(key_code), action)
                elif sub_type == "hold":
                    self.map_input_to_action(int(EVENT_KEY_HOLD), int(key_code), action)

        # --- Gesture → action mappings ---
        gesture_maps = mappings.get("gesture_action_mappings", {})
        for gesture_code, action in gesture_maps.items():
            self.register_action(action)
            self.map_input_to_action(int(EVENT_GESTURE), int(gesture_code), action)

        # --- IR → action mappings (register names; IR codes are runtime) ---
        ir_maps = mappings.get("ir_action_mappings", {})
        for sub_type, ir_dict in ir_maps.items():
            for _ir_name, action in ir_dict.items():
                self.register_action(action)

    def add_action_listener(
        self,
        action_name: str,
        listener: Callable[..., Any],
        *,
        priority: int = 0,
    ) -> Optional[ListenerHandle]:
        """Register a global listener for a named action.

        This is the Framework-level counterpart to
        :meth:`Widget.add_action_listener`.  Unlike the Widget version
        (which takes ``(name, obj, listener)``), this version takes
        ``(name, listener, *, priority)`` and is intended for use by
        ``JiveMain`` to register top-level action handlers.

        *listener* is called as ``listener(event)`` (or with extra
        ``*args, **kwargs`` which are ignored) and should return an
        event-status int.

        Parameters
        ----------
        action_name:
            The registered action name to listen for.
        listener:
            Callback ``(event) -> int``.
        priority:
            Higher values are checked later.
        """
        # Ensure the action is registered
        self.register_action(action_name)

        def _wrapper(event: Event) -> int:
            # Resolve action name directly via self rather than the module
            # singleton so that this works in tests where the singleton
            # has not been set.
            try:
                idx = event.get_action_internal()
            except TypeError:
                return int(EVENT_UNUSED)
            evt_action = self.get_action_event_name_by_index(idx)
            if evt_action != action_name:
                return int(EVENT_UNUSED)
            result = listener(event)
            return int(result) if result is not None else int(EVENT_CONSUME)

        return self.add_listener(int(ACTION), _wrapper, priority=priority)

    # ==================================================================
    # Input → Action conversion
    # ==================================================================

    # This table maps (event_type, key_code) to action names.
    # Populated by applets / skins; a small default set is built-in.
    _input_to_action_map: Dict[Tuple[int, int], str] = {}

    def map_input_to_action(
        self,
        event_type: int,
        code: int,
        action_name: str,
    ) -> None:
        """
        Map an input event ``(type, code)`` to a named action.

        Example: ``framework.map_input_to_action(EVENT_KEY_PRESS,
        KEY_GO, "go")``
        """
        self.register_action(action_name)
        self._input_to_action_map[(event_type, code)] = action_name

    def convert_input_to_action(self, event: Event) -> int:
        """
        If the input event maps to a registered action, push an ACTION
        event and consume the original.
        """
        etype = event.get_type()
        code = 0
        try:
            if etype & int(EVENT_KEY_ALL):
                code = event.get_keycode()
            elif etype & int(EVENT_CHAR_PRESS):
                code = event.get_unicode()
            elif etype & int(EVENT_IR_ALL):
                code = event.get_ir_code()
            elif etype & int(EVENT_GESTURE):
                code = event.get_gesture()
        except TypeError:
            return int(EVENT_UNUSED)

        action_name = self._input_to_action_map.get((etype, code))
        if action_name is not None:
            log.debug(
                f"convert_input_to_action: etype=0x{etype:08X} code={code} -> action={action_name!r}"
            )
            self.push_action(action_name)
            return int(EVENT_CONSUME)

        log.debug(f"convert_input_to_action: etype=0x{etype:08X} code={code} -> no mapping")
        return int(EVENT_UNUSED)

    # ==================================================================
    # Sound
    # ==================================================================

    def load_sound(self, name: str, file: str, channel: int = 0) -> None:
        """Load a WAV file as a named sound."""
        try:
            snd = pygame.mixer.Sound(file)
            self._sounds[name] = snd
            if name in self._sound_enabled:
                # respect previously set enabled state
                pass
        except Exception as exc:
            log.warn("Failed to load sound '%s': %s", name, exc)

    def enable_sound(self, name: str, enabled: bool) -> None:
        """Enable or disable a named sound."""
        self._sound_enabled[name] = enabled

    def is_sound_enabled(self, name: str) -> bool:
        """Return ``True`` if sound *name* is enabled."""
        return self._sound_enabled.get(name, True)

    # ==================================================================
    # Action-to-action translation
    # ==================================================================

    def get_action_to_action_translation(self, action_name: str) -> Optional[str]:
        """
        Return the translated action name for *action_name*, or ``None``.

        In the Lua original, certain actions can be remapped to other
        actions (e.g. ``"home_title_left_press"`` → ``"power"``).  This
        is used by the HomeMenu to decide whether to delay the left
        button action.

        Currently a stub — returns ``None`` (no translation configured).
        Full implementation requires the settings / preferences system.

        Parameters
        ----------
        action_name : str
            The source action name to look up.

        Returns
        -------
        str or None
            The translated action name, or ``None`` if no translation
            is configured.
        """
        # Look up in the translation table (if one exists)
        table = getattr(self, "_action_translations", None)
        if table is not None:
            val = table.get(action_name)
            return str(val) if val is not None else None
        return None

    getActionToActionTranslation = get_action_to_action_translation

    def set_action_to_action_translation(self, source: str, target: Optional[str]) -> None:
        """
        Set (or clear) a translation from *source* action to *target*.

        Parameters
        ----------
        source : str
            The action name to translate from.
        target : str or None
            The action name to translate to, or ``None`` to remove.
        """
        if not hasattr(self, "_action_translations"):
            self._action_translations: Dict[str, str] = {}

        if target is None:
            self._action_translations.pop(source, None)
        else:
            self._action_translations[source] = target

    setActionToActionTranslation = set_action_to_action_translation

    def play_sound(self, name: str) -> None:
        """Play a named sound if it is loaded and enabled."""
        if not self.is_sound_enabled(name):
            return
        snd = self._sounds.get(name)
        if snd is not None:
            try:
                snd.play()
            except Exception as exc:
                log.warning("play_sound failed: %s", exc)

    def get_sounds(self) -> Dict[str, Any]:
        """Return the dict of loaded sounds."""
        return dict(self._sounds)

    # ==================================================================
    # Most recent input type
    # ==================================================================

    def is_most_recent_input(self, input_type: str) -> bool:
        """
        Check if *input_type* (``"ir"``, ``"key"``, ``"mouse"``,
        ``"scroll"``) was the most recent input given.
        """
        return self._most_recent_input_type == input_type

    # ==================================================================
    # Wakeup
    # ==================================================================

    def register_wakeup(self, wakeup: Callable[[], None]) -> None:
        """Register a power-management wakeup function."""
        self._wakeup_fn = wakeup

    def wakeup(self) -> None:
        """Call the registered wakeup function."""
        if self._wakeup_fn is not None:
            self._wakeup_fn()

    # ==================================================================
    # Style change notification
    # ==================================================================

    def style_changed(self) -> None:
        """
        Notify that style parameters have changed.

        Mirrors the C ``jiveL_style_changed``:
        1. Clear the style lookup cache.
        2. Mark all widgets as needing re-skin / re-layout so they
           pick up the new style values lazily during the next
           ``check_layout()`` → ``check_skin()`` pass.
        3. Force a full redraw.

        The C original bumps ``next_jive_origin++`` and every widget
        detects the mismatch in ``checkSkin`` / ``checkLayout`` and
        re-runs ``_skin()`` / ``_layout()`` from scratch.  We mirror
        this by setting the dirty flags on every widget.

        We do NOT call ``re_skin()`` here because that method eagerly
        clears cached values (preferred_bounds, padding, tiles, images,
        etc.).  While the style dict IS available at this point (unlike
        in ``set_video_mode``), eagerly clearing caches is unnecessary:
        ``_skin()`` / ``_widget_pack()`` will overwrite every cached
        value with the new style data.  Skipping the eager clear also
        avoids transient states where widgets have zeroed-out padding/
        bounds that could confuse concurrent event handling or
        animation ticks that fire between style_changed() and the
        next update_screen().
        """
        # 1. Invalidate the global style cache
        try:
            from jive.ui.style import skin as _skin_db

            _skin_db.invalidate()
        except (ImportError, AttributeError):
            pass

        # 2. Mark every widget in every window as needing re-skin
        def _mark_dirty_recursive(widget: "Widget") -> None:
            widget._needs_skin = True
            widget._needs_layout = True
            widget._needs_draw = True
            # Invalidate cached style path so style_path() recomputes
            # it with the current style/modifier against the new skin.
            widget._style_path = None
            widget.iterate(lambda child: _mark_dirty_recursive(child))

        for w in self.window_stack:
            _mark_dirty_recursive(w)
        for gw in self._global_widgets:
            _mark_dirty_recursive(gw)

        # 3. Force full redraw
        self._screen_dirty = True
        self.re_draw(None)

    # ==================================================================
    # SDL / pygame event translation
    # ==================================================================

    def _translate_pygame_events(self) -> None:
        """
        Read all pending pygame events and translate them into Jive events
        pushed onto our event queue.
        """
        now = _get_ticks()

        for pg_event in pygame.event.get():
            if pg_event.type == pygame.QUIT:
                self.push_event(Event(int(EVENT_QUIT), ticks=now))

            elif pg_event.type == pygame.KEYDOWN:
                self._most_recent_input_type = "key"
                jive_key = _PYGAME_KEY_MAP.get(pg_event.key, 0)
                if jive_key:
                    self._keys_down[jive_key] = now
                    self.push_event(Event(int(EVENT_KEY_DOWN), code=jive_key, ticks=now))
                # Also generate CHAR_PRESS for printable characters, but
                # ONLY when the key does NOT already have a hardware-key
                # mapping.  Keys in _PYGAME_KEY_MAP produce KEY_DOWN /
                # KEY_PRESS / KEY_HOLD events that are routed through
                # key_action_mappings.  Emitting CHAR_PRESS *as well*
                # would cause a second, conflicting action via
                # char_action_mappings.  Regular letter/digit/space keys
                # are intentionally NOT in _PYGAME_KEY_MAP so that they
                # go through char_action_mappings only (matching the
                # original C keymap in jive_framework.c).
                if not jive_key and pg_event.unicode and ord(pg_event.unicode) >= 32:
                    self.push_event(
                        Event(
                            int(EVENT_CHAR_PRESS),
                            unicode=ord(pg_event.unicode),
                            ticks=now,
                        )
                    )

            elif pg_event.type == pygame.KEYUP:
                self._most_recent_input_type = "key"
                jive_key = _PYGAME_KEY_MAP.get(pg_event.key, 0)
                if jive_key:
                    self.push_event(Event(int(EVENT_KEY_UP), code=jive_key, ticks=now))
                    # Generate PRESS or HOLD based on duration
                    down_time = self._keys_down.pop(jive_key, None)
                    if down_time is not None:
                        duration = now - down_time
                        if jive_key in self._keys_held:
                            self._keys_held.discard(jive_key)
                            # HOLD was already sent
                        elif duration < _KEY_HOLD_TIME:
                            self.push_event(
                                Event(
                                    int(EVENT_KEY_PRESS),
                                    code=jive_key,
                                    ticks=now,
                                )
                            )
                        # else: duration >= HOLD but hold not sent yet
                        # (edge case — send press as fallback)
                        else:
                            self.push_event(
                                Event(
                                    int(EVENT_KEY_PRESS),
                                    code=jive_key,
                                    ticks=now,
                                )
                            )

            elif pg_event.type == pygame.MOUSEBUTTONDOWN:
                self._most_recent_input_type = "mouse"
                x, y = pg_event.pos
                if pg_event.button in (4, 5):
                    # Scroll wheel
                    self._most_recent_input_type = "scroll"
                    scroll_rel = -1 if pg_event.button == 4 else 1
                    self.push_event(Event(int(EVENT_SCROLL), rel=scroll_rel, ticks=now))
                else:
                    self._mouse_down_pos = (x, y)
                    self._mouse_down_ticks = now
                    self._mouse_held = False
                    self.push_event(Event(int(EVENT_MOUSE_DOWN), x=x, y=y, ticks=now))

            elif pg_event.type == pygame.MOUSEBUTTONUP:
                self._most_recent_input_type = "mouse"
                x, y = pg_event.pos
                if pg_event.button not in (4, 5):
                    self.push_event(Event(int(EVENT_MOUSE_UP), x=x, y=y, ticks=now))
                    if self._mouse_down_pos is not None:
                        if self._mouse_held:
                            pass
                        else:
                            self.push_event(
                                Event(
                                    int(EVENT_MOUSE_PRESS),
                                    x=x,
                                    y=y,
                                    ticks=now,
                                )
                            )
                    self._mouse_down_pos = None
                    self._mouse_held = False

            elif pg_event.type == pygame.MOUSEMOTION:
                self._most_recent_input_type = "mouse"
                x, y = pg_event.pos
                if pg_event.buttons[0]:
                    self.push_event(Event(int(EVENT_MOUSE_DRAG), x=x, y=y, ticks=now))
                else:
                    self.push_event(Event(int(EVENT_MOUSE_MOVE), x=x, y=y, ticks=now))

            elif pg_event.type == pygame.VIDEORESIZE:
                w, h = pg_event.size
                self._screen_w = w
                self._screen_h = h
                self.push_event(Event(int(EVENT_WINDOW_RESIZE), ticks=now))

        # ---- Synthesise KEY_HOLD for keys that have been down long enough ----
        for jive_key, down_ticks in list(self._keys_down.items()):
            if jive_key not in self._keys_held:
                if now - down_ticks >= _KEY_HOLD_TIME:
                    self._keys_held.add(jive_key)
                    self.push_event(Event(int(EVENT_KEY_HOLD), code=jive_key, ticks=now))

        # ---- Synthesise MOUSE_HOLD ----
        if (
            self._mouse_down_pos is not None
            and not self._mouse_held
            and now - self._mouse_down_ticks >= _MOUSE_HOLD_TIME
        ):
            self._mouse_held = True
            x, y = self._mouse_down_pos
            self.push_event(Event(int(EVENT_MOUSE_HOLD), x=x, y=y, ticks=now))

    # ==================================================================
    # Main event loop
    # ==================================================================

    def event_loop(self, task: Any = None) -> None:
        """
        Main event loop.

        Runs until a ``QUIT`` event is received or ``quit()`` is called.
        Each iteration:

        1. Translate pygame events → Jive events
        2. Run optional *task* callback (e.g. NetworkThread pump)
        3. Process timer queue
        4. Tick animations
        5. Process event queue
        6. Update / draw the screen
        7. Throttle to target frame rate

        Parameters
        ----------
        task:
            Optional callable invoked once per frame (e.g. the
            NetworkThread task that pumps network I/O).
        """
        if not self._initialised:
            raise RuntimeError("Framework.init() must be called before event_loop()")

        # Ensure default actions are registered (idempotent if already
        # done during init()).
        self._register_default_actions()

        # Add the input-to-action converter — priority=9999 routes it to
        # unusedListeners so it runs AFTER widgets (matching Lua original).
        self.add_listener(
            int(EVENT_KEY_ALL) | int(EVENT_CHAR_PRESS) | int(EVENT_IR_ALL) | int(EVENT_GESTURE),
            self.convert_input_to_action,
            priority=9999,
        )

        self._running = True
        framerate_ms = max(1, 1000 // self._frame_rate)

        while self._running:
            now = _get_ticks()

            # 1. Read SDL events → Jive event queue
            self._translate_pygame_events()

            # 2. Optional per-frame task (e.g. network pump).
            #    NOTE: JiveMain passes _pump_tasks here which calls
            #    Task.iterator() — so we do NOT duplicate that in a
            #    separate step.  This matches the Lua original where
            #    the network task is pumped once per frame.
            if task is not None:
                try:
                    task()
                except Exception as exc:
                    log.warn("event_loop task error: %s", exc)

            # 3. Timers
            Timer.run_timers(now)

            # 4. Animations
            self._tick_animations()

            # 5. Process queued events BEFORE drawing so that the
            #    current frame reflects the user's input immediately
            #    (eliminates 1-frame / ~33ms input lag).
            #    Layout is forced for the top window before dispatch
            #    so that z_widgets exist for mouse hit-testing — see
            #    _process_event_queue().
            if not self._process_event_queue():
                self._running = False
                break

            # 6. Draw / layout — now renders the result of events
            #    processed above, so the user sees immediate feedback.
            self.update_screen()

            # 7. Guard: quit() may have been called from a timer/listener
            if not self._running:
                break

            # 8. Throttle
            if self._clock is not None:
                self._clock.tick(self._frame_rate)

    def run(self) -> None:
        """Convenience alias for ``event_loop()``."""
        self.event_loop()

    # ==================================================================
    # Process single frame (for testing / external loop integration)
    # ==================================================================

    def process_one_frame(self) -> bool:
        """
        Process a single frame: events, timers, animations, draw.

        Returns ``True`` to keep running, ``False`` on quit.
        Useful for testing or embedding in an external loop.
        """
        now = _get_ticks()
        self._translate_pygame_events()

        # Run cooperative tasks
        for t in Task.iterator():
            try:
                t.resume()
            except Exception as exc:
                log.warn("task resume error (%s): %s", t.name, exc)

        # Draw / layout FIRST so z_widgets is populated before events
        self.update_screen()
        Timer.run_timers(now)
        self._tick_animations()
        running = self._process_event_queue()
        return running

    # ==================================================================
    # Default action registrations
    # ==================================================================

    def _register_default_actions(self) -> None:
        """Register the standard set of actions (idempotent)."""
        if self._actions_by_name:
            return  # already registered
        default_actions = [
            "go",
            "back",
            "do",
            "play",
            "pause",
            "stop",
            "rew",
            "fwd",
            "rew_scan",
            "fwd_scan",
            "add",
            "mute",
            "volume_up",
            "volume_down",
            "scroll_up",
            "scroll_down",
            "page_up",
            "page_down",
            "home",
            "power",
            "alarm",
            "soft_reset",
            "title_left",
            "title_right",
        ]
        for name in default_actions:
            self.register_action(name)

        # Default key→action mappings
        default_key_maps = [
            (int(EVENT_KEY_PRESS), int(Key.GO), "go"),
            (int(EVENT_KEY_PRESS), int(Key.BACK), "back"),
            (int(EVENT_KEY_PRESS), int(Key.PLAY), "play"),
            (int(EVENT_KEY_PRESS), int(Key.PAUSE), "pause"),
            (int(EVENT_KEY_PRESS), int(Key.STOP), "stop"),
            (int(EVENT_KEY_PRESS), int(Key.REW), "rew"),
            (int(EVENT_KEY_PRESS), int(Key.FWD), "fwd"),
            (int(EVENT_KEY_PRESS), int(Key.ADD), "add"),
            (int(EVENT_KEY_PRESS), int(Key.MUTE), "mute"),
            (int(EVENT_KEY_PRESS), int(Key.VOLUME_UP), "volume_up"),
            (int(EVENT_KEY_PRESS), int(Key.VOLUME_DOWN), "volume_down"),
            (int(EVENT_KEY_PRESS), int(Key.PAGE_UP), "page_up"),
            (int(EVENT_KEY_PRESS), int(Key.PAGE_DOWN), "page_down"),
            (int(EVENT_KEY_PRESS), int(Key.HOME), "home"),
            (int(EVENT_KEY_PRESS), int(Key.POWER), "power"),
            (int(EVENT_KEY_PRESS), int(Key.ALARM), "alarm"),
            (int(EVENT_KEY_HOLD), int(Key.BACK), "soft_reset"),
            # KEY_LEFT / KEY_RIGHT / KEY_UP / KEY_DOWN are NOT mapped to
            # actions on press — Menu._event_handler handles them directly
            # as KEY_PRESS events (matching the Lua original).
            (int(EVENT_KEY_HOLD), int(Key.LEFT), "go_home"),
            (int(EVENT_KEY_HOLD), int(Key.RIGHT), "add"),
        ]
        for etype, code, action in default_key_maps:
            self.map_input_to_action(etype, code, action)

    # ==================================================================
    # Caller info (debug helper)
    # ==================================================================

    @staticmethod
    def caller_to_string() -> str:
        """Return source:line info about the caller (debug helper)."""
        import traceback

        stack = traceback.extract_stack()
        if len(stack) >= 3:
            frame = stack[-3]
            return f"{frame.filename}:{frame.lineno}"
        return "N/A"

    # ==================================================================
    # IR code helpers (stub — IR is rarely used on desktop)
    # ==================================================================

    _ir_code_map: Dict[str, int] = {}

    def register_ir_code(self, name: str, code: int) -> None:
        """Register a named IR code."""
        self._ir_code_map[name] = code

    def is_ir_code(self, button_name: str, ir_code: int) -> bool:
        """Return ``True`` if *ir_code* matches the named button."""
        return self._ir_code_map.get(button_name) == ir_code

    # ==================================================================
    # Lua-compatible camelCase aliases
    # ==================================================================
    # These aliases allow applets ported from Lua to call Framework
    # methods using the original camelCase names (e.g. ``fw.addListener``,
    # ``fw.pushAction``, ``Framework.getTicks``).
    #
    # ``windowStack`` is already defined as a direct attribute
    # (``self.window_stack``) — add a property alias so that code
    # using ``Framework.windowStack`` works.

    @property
    def windowStack(self) -> list[Any]:  # noqa: N802
        """Alias for ``window_stack``."""
        return self.window_stack

    addListener = add_listener
    removeListener = remove_listener
    pushEvent = push_event
    dispatchEvent = dispatch_event
    pushAction = push_action
    getTicks = get_ticks
    playSound = play_sound
    registerAction = register_action
    getActionEventIndexByName = get_action_event_index_by_name
    getActionEventNameByIndex = get_action_event_name_by_index
    isMostRecentInput = is_most_recent_input
    isValidIRCode = is_ir_code
    isWindowInStack = is_window_in_stack
    isCurrentWindow = is_current_window

    def addActionListener(  # noqa: N802
        self,
        action_name: str,
        obj: Any,
        listener: Callable[..., Any],
        priority: Any = 0,
    ) -> Optional[ListenerHandle]:
        """Lua-compatible ``Framework:addActionListener(action, self, func, priority)``.

        The Lua signature passes *obj* (self of the calling applet) and
        *priority* (often ``false`` which means 0 / global).  We wrap
        the *listener* so it receives ``(obj, event)`` — matching the
        Lua calling convention — and delegate to
        :meth:`add_action_listener`.
        """
        # Lua ``false`` maps to Python ``False`` which is int 0.
        int_priority = int(priority) if isinstance(priority, (int, float)) else 0

        def _wrapped(event: Event) -> int:
            result = listener(obj, event)
            return int(result) if result is not None else int(EVENT_CONSUME)

        return self.add_action_listener(action_name, _wrapped, priority=int_priority)

    # ==================================================================
    # Representation
    # ==================================================================

    def __repr__(self) -> str:
        return (
            f"Framework(initialised={self._initialised}, "
            f"windows={len(self.window_stack)}, "
            f"global_widgets={len(self._global_widgets)}, "
            f"actions={len(self._actions_by_name)}, "
            f"screen={self._screen_w}x{self._screen_h})"
        )


# ===========================================================================
# Module-level singleton
# ===========================================================================

framework: Framework = Framework()
