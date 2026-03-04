"""
jive.ui.canvas — Canvas widget for the Jivelite Python3 port.

Ported from ``Canvas.lua`` in the original jivelite project.

A Canvas widget provides access to custom drawing on the screen.  It
extends :class:`~jive.ui.icon.Icon` and delegates its ``draw()`` call
to a user-supplied render function.

Usage::

    def my_renderer(surface):
        surface.fill(0xFF0000FF)
        surface.draw_line(0, 0, 100, 100, 0xFFFFFFFF)

    canvas = Canvas("my_canvas", my_renderer)

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
)

from jive.ui.icon import Icon
from jive.utils.log import logger

if TYPE_CHECKING:
    from jive.ui.surface import Surface

__all__ = ["Canvas"]

log = logger("jivelite.ui")


class Canvas(Icon):
    """
    A canvas widget that delegates drawing to a user-supplied function.

    Extends :class:`Icon`.  The *render_func* is called with the target
    :class:`Surface` each time the widget is drawn.

    Parameters
    ----------
    style : str
        The style key used to look up skin parameters.
    render_func : callable
        A function with signature ``render_func(surface)`` that performs
        custom drawing onto the given surface.
    """

    __slots__ = ("_render_func",)

    def __init__(
        self,
        style: str,
        render_func: Callable[[Any], None],
    ) -> None:
        if not isinstance(style, str):
            raise TypeError(f"style must be a string, got {type(style).__name__}")
        if not callable(render_func):
            raise TypeError(
                f"render_func must be callable, got {type(render_func).__name__}"
            )

        super().__init__(style)
        self._render_func: Callable[[Any], None] = render_func

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------

    def draw(self, surface: Surface, layer: int = 0xFF) -> None:
        """
        Draw the canvas by calling the user-supplied render function.

        Parameters
        ----------
        surface : Surface
            The target surface to draw onto.
        layer : int
            Bitmask of layers to draw (default ``0xFF`` = all layers).
        """
        self._render_func(surface)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def render_func(self) -> Callable[[Any], None]:
        """Return the current render function."""
        return self._render_func

    @render_func.setter
    def render_func(self, func: Callable[[Any], None]) -> None:
        """
        Replace the render function.

        Parameters
        ----------
        func : callable
            New render function with signature ``func(surface)``.
        """
        if not callable(func):
            raise TypeError(f"render_func must be callable, got {type(func).__name__}")
        self._render_func = func
        self.re_draw()

    # ------------------------------------------------------------------
    # Representation
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return f"Canvas(style={self.style!r})"

    def __str__(self) -> str:
        return self.__repr__()
