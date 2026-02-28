#!/usr/bin/env python3
"""
hello_ui.py — Minimal "Hello World" demo for the Jivelite Python3 port.

Meilenstein M4: Proof of Life — open a window, show a centred label,
auto-close after 5 seconds (or press ESC / close the window).

Usage:
    python examples/hello_ui.py

Requirements:
    pip install pygame-ce   (or pygame>=2.5)
"""

from __future__ import annotations

import os
import sys

# ---------------------------------------------------------------------------
# Ensure the project root is on sys.path so ``jive`` can be imported when
# running this file directly from the ``examples/`` directory.
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_HERE)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------

import pygame
import pygame.font as _pgfont
import pygame.freetype as _pgft

from jive.ui.constants import (
    ALIGN_CENTER,
    EVENT_CONSUME,
    EVENT_KEY_PRESS,
    LAYER_CONTENT,
    LAYOUT_CENTER,
    LAYOUT_NORTH,
    LAYOUT_SOUTH,
)
from jive.ui.font import Font
from jive.ui.framework import framework
from jive.ui.label import Label
from jive.ui.style import skin
from jive.ui.surface import Surface
from jive.ui.tile import Tile
from jive.ui.timer import Timer
from jive.ui.window import Window

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SCREEN_W = 480
SCREEN_H = 272
TITLE = "Jivelite — Hello UI"
AUTO_CLOSE_MS = 5000  # auto-close after 5 seconds (0 = never)
BG_COLOR = 0x1A1A2EFF  # dark navy
FG_COLOR = 0xE0E0FFFF  # soft white-blue
ACCENT_COLOR = 0x16213EFF  # slightly lighter navy for window bg


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_system_font() -> str:
    """Return the path to a usable system TrueType font."""
    _pgfont.init()
    for name in ("arial", "liberationsans", "dejavusans", "freesans", "sans"):
        path = _pgfont.match_font(name)
        if path:
            return path
    # Last resort — pygame default
    default = _pgft.get_default_font()
    if default:
        return default
    raise RuntimeError("No usable TrueType font found on this system")


def _build_skin(font_path: str) -> dict:
    """
    Build a minimal skin dict with styles for ``window`` and ``text``.

    This is the equivalent of a Lua skin file — it tells the style system
    what fonts, colours, padding, background tiles, and alignment to use
    for each widget style key.
    """
    title_font = Font.load(font_path, 28)
    body_font = Font.load(font_path, 18)
    small_font = Font.load(font_path, 13)

    return {
        # -- Window style --------------------------------------------------
        "window": {
            "bgImg": Tile.fill_color(BG_COLOR),
            "layout": None,  # use default border_layout
            "padding": [0, 0, 0, 0],
            "border": [0, 0, 0, 0],
            "layer": int(LAYER_CONTENT),
        },
        # -- Label styles ---------------------------------------------------
        "title": {
            "font": title_font,
            "fg": _color_list(FG_COLOR),
            "align": int(ALIGN_CENTER),
            "padding": [10, 10, 10, 4],
            "position": int(LAYOUT_NORTH),
        },
        "body": {
            "font": body_font,
            "fg": _color_list(FG_COLOR),
            "align": int(ALIGN_CENTER),
            "padding": [10, 2, 10, 2],
            "position": int(LAYOUT_CENTER),
        },
        "footer": {
            "font": small_font,
            "fg": _color_list(0x808090FF),
            "align": int(ALIGN_CENTER),
            "padding": [10, 4, 10, 10],
            "position": int(LAYOUT_SOUTH),
        },
    }


def _color_list(rgba: int) -> list[int]:
    """Convert ``0xRRGGBBAA`` to ``[R, G, B, A]``."""
    return [
        (rgba >> 24) & 0xFF,
        (rgba >> 16) & 0xFF,
        (rgba >> 8) & 0xFF,
        rgba & 0xFF,
    ]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    # 1. Find a font
    font_path = _resolve_system_font()
    print(f"[hello_ui] Using font: {font_path}")

    # 2. Set up the global skin
    skin.data = _build_skin(font_path)

    # 3. Initialise the framework (opens the pygame window)
    framework.init(
        width=SCREEN_W,
        height=SCREEN_H,
        title=TITLE,
        fullscreen=False,
        frame_rate=30,
    )

    # 4. Create a Window
    win = Window("window")

    # 5. Create Labels
    title_label = Label("title", "Hello, Jivelite!")
    body_label = Label("body", "Python3 port — Milestone M4")
    footer_label = Label(
        "footer", f"Auto-close in {AUTO_CLOSE_MS // 1000}s  •  Press ESC to quit"
    )

    # 6. Add widgets to the window
    #    border_layout reads "position" from each widget's style to decide
    #    NORTH / CENTER / SOUTH placement.
    win.add_widget(title_label)
    win.add_widget(body_label)
    win.add_widget(footer_label)

    # 7. ESC key listener — close on ESC
    def _on_key(evt):
        key_code = evt.get_keycode()
        if key_code == pygame.K_ESCAPE:
            framework.stop()
            return int(EVENT_CONSUME)
        return 0

    win.add_listener(int(EVENT_KEY_PRESS), _on_key)

    # 8. Auto-close timer
    if AUTO_CLOSE_MS > 0:

        def _auto_close():
            print("[hello_ui] Auto-close timer fired — shutting down.")
            framework.stop()

        auto_timer = Timer(AUTO_CLOSE_MS, _auto_close, once=True)
        auto_timer.start()

    # 9. Show the window and run
    win.show(transition=None)

    print(f"[hello_ui] Window shown ({SCREEN_W}x{SCREEN_H}).  Running event loop …")
    try:
        framework.run()
    except KeyboardInterrupt:
        pass
    finally:
        framework.quit()
        print("[hello_ui] Done.")


if __name__ == "__main__":
    main()
