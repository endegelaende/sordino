"""
jive.ui — UI widget framework for the Jivelite Python3 port.

Ported from the original Lua UI modules in share/jive/jive/ui/ and the
C rendering engine in src/ of the jivelite project.

Phase 2 Foundation Modules:
    - constants: Event types, key codes, alignment, layers, layout enums
    - event: Event object with typed payloads (scroll, key, mouse, action, …)
    - timer: Interval-based callback timer with sorted queue
    - surface: pygame.Surface wrapper (blit, clip, drawing primitives, images)
    - font: TTF font loading, rendering, metrics (width, height, ascend, capheight)
    - widget: Base class for all UI widgets (bounds, style, listeners, animations)
    - framework: Singleton coordinator (event loop, window stack, actions, screen)

Phase 2 M2 Modules:
    - tile: 9-patch tiled image system (fill-color, load-image, h/v/9-patch)
    - style: Hierarchical style/skin lookup, caching, type-specific getters
    - window: Window widget (show/hide, window stack, border layout, transitions)

Phase 2 M3 Modules:
    - icon: Image display widget (static/animated, style default, network sink)
    - label: Text display widget (multi-line, scrolling, shadow, priority value)
    - group: Container widget (horizontal/vertical layout, ordered children, mouse routing)

Phase 2 M5 Modules:
    - textarea: Multi-line text display with word-wrapping and scrolling
    - slider: Slider/scrollbar base widget (range, value, drag, pill indicator)
    - menu: Base menu widget (item management, scrolling, scrollbar, layout)
    - simplemenu: Convenience menu with simple text+icon+callback items
    - checkbox: Toggle checkbox widget (extends Icon, img_on/img_off)
    - radio: RadioGroup + RadioButton for mutual-exclusion selection

Phase 2 M6 Modules:
    - canvas: Free-drawing widget (extends Icon, custom render function)
    - audio: Audio effects and playback (pygame.mixer wrapper / stub)
    - popup: Transient popup window (extends Window, auto-hide, transparent)
    - choice: Cyclic option selector widget (extends Label)
    - snapshotwindow: Screen-capture window (extends Window, static blit)
    - scrollwheel: Non-accelerated scroll event filter
    - scrollaccel: Accelerated scroll event filter (extends ScrollWheel)
    - stickymenu: Sticky-scroll menu (extends SimpleMenu, scroll resistance)

Phase 2 M7 Modules:
    - button: Mouse-state-machine for press/hold/drag on widgets
    - flick: Touch-gesture flick engine (afterscroll physics, deceleration)
    - contextmenuwindow: Context-menu window (screenshot overlay, shading)

Phase 2 M8 Modules:
    - task: Cooperative task scheduler (Python generator-based, redesigned from Lua coroutines)
    - irmenuaccel: IR remote accelerated scroll event filter (arrow-key acceleration)
    - numberletteraccel: Number-to-letter (T9-style) input handler for IR remotes
    - keyboard: On-screen keyboard widget (QWERTY, numeric, hex, email, IP layouts)
    - textinput: Text input widget (cursor, char scrolling, value types: text/time/hex/IP)
    - timeinput: Time picker widget (hour/minute/ampm scroll-wheel menus)

Phase 2 M9 Modules:
    - homemenu: Applet-driven home menu (node tree, item ordering, ranking, custom nodes)

Note: coxpcall.lua is NOT ported — Python has native try/except/finally.
      loop.base OOP is NOT ported — Python has native classes.
"""

from __future__ import annotations

__all__ = [
    "constants",
    "event",
    "timer",
    "surface",
    "font",
    "widget",
    "framework",
    "tile",
    "style",
    "window",
    "icon",
    "label",
    "group",
    "textarea",
    "slider",
    "menu",
    "simplemenu",
    "checkbox",
    "radio",
    "canvas",
    "audio",
    "popup",
    "choice",
    "snapshotwindow",
    "scrollwheel",
    "scrollaccel",
    "stickymenu",
    "button",
    "flick",
    "contextmenuwindow",
    "task",
    "irmenuaccel",
    "numberletteraccel",
    "keyboard",
    "textinput",
    "timeinput",
    "homemenu",
]
