"""
jive.ui.snapshotwindow — Snapshot window for the Jivelite Python3 port.

Ported from ``SnapshotWindow.lua`` in the original jivelite project.

A SnapshotWindow is a :class:`~jive.ui.window.Window` subclass that
captures a snapshot of the current screen contents and displays it as a
static image.  This is used for transitions and overlays where the
previous screen state needs to be preserved as a background.

Key behaviours:

* **Screen capture** — on creation, takes a snapshot of the current
  screen via the Framework's draw method
* **Static draw** — ``draw()`` simply blits the captured snapshot,
  making it very cheap to render
* **Refresh** — ``refresh()`` re-captures the current screen state
* **No framework widgets** — the title bar / button bar is not shown
* **No transitions** — appears instantly; *hide* transition uses fade-in
  (matching the Lua original's ``transitionFadeInFast``)
* **Screensaver allowed** — unlike Popup, the screensaver can still
  activate

Usage::

    snapshot = SnapshotWindow()
    snapshot.show()

    # … later, refresh the captured image …
    snapshot.refresh()

    # … later …
    snapshot.hide()

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

from jive.ui.window import Window, transition_none
from jive.utils.log import logger

if TYPE_CHECKING:
    from jive.ui.surface import Surface as JiveSurface

__all__ = ["SnapshotWindow"]

log = logger("jivelite.ui")


class SnapshotWindow(Window):
    """
    A window that captures and displays a static screen snapshot.

    Extends :class:`Window`.  On construction, the current screen
    contents are captured into an off-screen surface.  The ``draw()``
    method simply blits this captured image, which is very efficient
    for use as a static background during transitions or overlays.

    Parameters
    ----------
    window_id : str or int, optional
        An optional identifier for the window (passed through to
        :class:`Window`).
    """

    def __init__(
        self,
        window_id: Optional[Union[str, int]] = None,
    ) -> None:
        # Use an empty style string — snapshot windows don't need styling
        super().__init__("", "", window_id=window_id)

        # Override default transitions (matching Lua original):
        #   show: no transition (instant)
        #   hide: fade-in-fast (the Lua code sets hide to transitionFadeInFast)
        self._DEFAULT_SHOW_TRANSITION = transition_none
        # For hide, try to use fade_in if available, otherwise no transition
        try:
            from jive.ui.window import transition_fade_in

            self._DEFAULT_HIDE_TRANSITION = transition_fade_in
        except ImportError:
            self._DEFAULT_HIDE_TRANSITION = transition_none

        # Snapshot-specific defaults
        self.set_allow_screensaver(True)
        self.set_show_framework_widgets(False)

        # No button actions
        self._button_actions: dict = {}

        # Capture the current screen
        self._bg: Optional[JiveSurface] = self._capture()

    # ------------------------------------------------------------------
    # Screen capture
    # ------------------------------------------------------------------

    def _capture(self) -> Optional[JiveSurface]:
        """
        Capture the current screen contents into a new RGB surface.

        Returns
        -------
        Surface or None
            A :class:`Surface` containing a copy of the current screen,
            or ``None`` if the Framework is not initialised.
        """
        try:
            from jive.ui.framework import framework as fw
            from jive.ui.surface import Surface

            sw, sh = fw.get_screen_size()
            if sw <= 0 or sh <= 0:
                log.debug("SnapshotWindow._capture: invalid screen size %dx%d", sw, sh)
                return None

            img = Surface.new_rgb(sw, sh)
            fw.draw(img)
            return img
        except Exception:
            log.warning("SnapshotWindow._capture failed", exc_info=True)
            return None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        """
        Re-capture the current screen state.

        Replaces the stored snapshot with a fresh capture of whatever
        is currently being displayed.
        """
        self._bg = self._capture()
        self.re_draw()

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------

    def draw(self, surface: JiveSurface, layer: int = 0) -> None:
        """
        Draw the snapshot window by blitting the captured image.

        Parameters
        ----------
        surface : Surface
            The target surface to draw onto.
        layer : int, optional
            The rendering layer (unused — the snapshot fills all layers).
        """
        if self._bg is not None:
            self._bg.blit(surface, 0, 0)

    # ------------------------------------------------------------------
    # Representation
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        has_bg = self._bg is not None
        return f"SnapshotWindow(captured={has_bg})"

    def __str__(self) -> str:
        return self.__repr__()
