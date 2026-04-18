"""
Pytest fixtures for testing the Sordino UI framework without a real display.

Provides:
- ``mock_pygame_display`` — autouse session fixture that initialises pygame
  with the dummy video driver so Surface/display operations work headlessly.
- ``MockSurface`` — lightweight stand-in for ``jive.ui.surface.Surface``.
- ``MockWindow`` — test double that tracks ``check_layout`` / ``draw`` calls.
- ``framework_instance`` — function-scoped fixture yielding a minimally
  configured ``Framework`` with the module-level singleton patched.
- ``make_window`` — factory fixture for creating ``MockWindow`` instances.
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Session-scoped headless pygame bootstrap
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True, scope="session")
def mock_pygame_display() -> Any:
    """Initialise pygame with ``SDL_VIDEODRIVER=dummy`` for the entire session.

    This allows ``pygame.Surface`` and ``pygame.display`` operations to
    succeed without a physical screen.
    """
    os.environ["SDL_VIDEODRIVER"] = "dummy"

    import pygame

    pygame.init()
    # The dummy driver needs a display mode to be set so that convert()
    # and other display-dependent calls work.
    pygame.display.set_mode((800, 480))

    yield

    pygame.quit()


# ---------------------------------------------------------------------------
# MockSurface — minimal Surface stand-in
# ---------------------------------------------------------------------------


class _MockPgSurface:
    """Imitates the subset of ``pygame.Surface`` used by ``update_screen``."""

    def set_clip(self, rect: Any = None) -> None:  # noqa: ARG002
        pass

    def fill(self, color: Any) -> None:  # noqa: ARG002
        pass

    def blit(self, source: Any, dest: Any, area: Any = None) -> None:  # noqa: ARG002
        pass

    def get_size(self) -> tuple[int, int]:
        return (800, 480)


class MockSurface:
    """Lightweight stand-in for ``jive.ui.surface.Surface``.

    Implements the surface methods that ``Framework.update_screen`` calls
    so that rendering can proceed without touching real pixel buffers.
    """

    def __init__(self, width: int = 800, height: int = 480) -> None:
        self._width = width
        self._height = height
        self.pg = _MockPgSurface()
        self.flip_count: int = 0
        self._offset_x: int = 0
        self._offset_y: int = 0

    def set_offset(self, x: int, y: int) -> None:
        self._offset_x = x
        self._offset_y = y

    def get_offset(self) -> tuple[int, int]:
        return self._offset_x, self._offset_y

    def get_size(self) -> tuple[int, int]:
        return self._width, self._height

    def flip(self) -> None:
        self.flip_count += 1

    def blit(self, dst: Any, dx: int, dy: int) -> None:  # noqa: ARG002
        pass

    def fill(self, color: Any) -> None:  # noqa: ARG002
        pass

    def set_clip(self, x: int, y: int, w: int, h: int) -> None:  # noqa: ARG002
        pass


# ---------------------------------------------------------------------------
# MockWindow — test double for Window
# ---------------------------------------------------------------------------


class MockWindow:
    """Test double for ``jive.ui.window.Window``.

    Tracks how many times ``check_layout`` and ``draw`` are called so that
    tests can assert on framework rendering behaviour without needing real
    widgets or skins.
    """

    def __init__(
        self,
        *,
        needs_skin: bool = False,
        needs_layout: bool = False,
    ) -> None:
        # Style / dirty flags (mimic Widget)
        self.style: str = "mock_window"
        self._needs_skin: bool = needs_skin
        self._needs_layout: bool = needs_layout
        self._needs_draw: bool = True

        # Window flags
        self.transparent: bool = False
        self.always_on_top: bool = False
        self.visible: bool = True

        # Geometry
        self.bounds: list[int] = [0, 0, 800, 480]

        # Children (z-sorted list used by Window.draw)
        self.z_widgets: list[Any] = []

        # Call counters
        self.check_layout_count: int = 0
        self.draw_count: int = 0
        self.event_count: int = 0

    def check_layout(self) -> None:
        """Record that layout was checked and clear dirty flags."""
        self.check_layout_count += 1
        self._needs_skin = False
        self._needs_layout = False

    def draw(self, surface: Any, layer: int = 0xFF) -> None:  # noqa: ARG002
        """Record that drawing occurred."""
        self.draw_count += 1

    def _event(self, event: Any) -> int:  # noqa: ARG002
        """Return EVENT_UNUSED (0) for all events."""
        self.event_count += 1
        return 0  # EVENT_UNUSED

    def is_hidden(self) -> bool:
        return not self.visible

    def get_bounds(self) -> list[int]:
        return list(self.bounds)

    def iterate(self, closure: Any) -> None:
        """No children to iterate."""

    def re_skin(self) -> None:
        self._needs_skin = True

    def re_layout(self) -> None:
        self._needs_layout = True

    def re_draw(self) -> None:
        self._needs_draw = True

    def __repr__(self) -> str:
        return f"MockWindow(layout={self.check_layout_count}, draw={self.draw_count})"


# ---------------------------------------------------------------------------
# Framework fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def framework_instance() -> Any:
    """Yield a minimally configured ``Framework`` with the singleton patched.

    Instead of calling ``Framework.init()`` (which sets up a real pygame
    display, loads icons, registers key-repeat, etc.) we create an instance
    and manually set the internal state that ``update_screen`` and other
    methods check:

    - ``_initialised = True``
    - ``_screen_surface`` → a ``MockSurface``
    - ``_screen_w / _screen_h`` → 800 × 480
    - ``_screen_dirty = True``
    - ``_update_screen_enabled = True``

    The module-level ``framework`` singleton in ``jive.ui.framework`` is
    monkey-patched so that code doing
    ``from jive.ui.framework import framework`` picks up the test instance
    (important for ``_mark_screen_dirty`` in ``jive.ui.widget``).
    """
    import jive.ui.framework as fw_module
    from jive.ui.framework import Framework

    old_singleton = fw_module.framework

    fw = Framework()
    fw._initialised = True
    fw._screen_surface = MockSurface()  # type: ignore[assignment]
    fw._screen_w = 800
    fw._screen_h = 480
    fw._screen_dirty = True
    fw._update_screen_enabled = True
    fw._clock = MagicMock()

    # Patch the module-level singleton
    fw_module.framework = fw  # type: ignore[assignment]

    yield fw

    # Restore the original singleton
    fw_module.framework = old_singleton


# ---------------------------------------------------------------------------
# Window factory fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def make_window():
    """Factory fixture that creates ``MockWindow`` instances.

    Usage::

        def test_something(make_window, framework_instance):
            win = make_window(needs_layout=True)
            framework_instance.window_stack.insert(0, win)
            ...
    """

    def _factory(
        *,
        needs_skin: bool = False,
        needs_layout: bool = False,
    ) -> MockWindow:
        return MockWindow(needs_skin=needs_skin, needs_layout=needs_layout)

    return _factory
