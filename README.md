# jivelite-py

**Python 3 port of [Jivelite](https://github.com/ralph-irving/jivelite)** — the community
Lyrion Music Server (formerly Logitech Media Server / Squeezebox) control UI.

- **Upstream:** <https://github.com/ralph-irving/jivelite> (C + Lua, BSD-3-Clause)
- **Homepage:** <https://sourceforge.net/projects/lmsclients/files/jivelite/>

Jivelite is a C + Lua application that renders the Squeezebox user interface on
Linux, macOS and Windows.  This project re-implements the Lua UI layer and the
C rendering primitives as a pure-Python package on top of **pygame** (or
pygame-ce).

> **Status: Alpha (v0.2.0)**
> The full UI widget toolkit, networking layer, and HomeMenu are functional and
> tested (1669 tests passing).  Slim protocol, applet hosting, and full LMS
> integration are not yet ported.

---

## Table of Contents

- [Screenshots](#screenshots)
- [Architecture](#architecture)
- [What Has Been Ported](#what-has-been-ported)
- [What Has NOT Been Ported Yet](#what-has-not-been-ported-yet)
- [Requirements](#requirements)
- [Installation](#installation)
- [Quick Start — Hello UI Demo](#quick-start--hello-ui-demo)
- [Running Tests](#running-tests)
- [Project Structure](#project-structure)
- [Porting Guide — Lua → Python Mapping](#porting-guide--lua--python-mapping)
- [Contributing](#contributing)
- [License](#license)

---

## Screenshots

*(coming soon — run `examples/hello_ui.py` to see a live window)*

---

## Architecture

The original Jivelite is a three-layer stack:

```
┌──────────────────────────────────────────────┐
│  Lua UI layer  (share/jive/jive/ui/*.lua)    │  ← widget logic, skins, applets
├──────────────────────────────────────────────┤
│  C rendering   (src/jive_*.c)                │  ← SDL / font / surface / events
├──────────────────────────────────────────────┤
│  SDL 1.2 / SDL 2                             │
└──────────────────────────────────────────────┘
```

**jivelite-py** collapses the top two layers into Python and replaces SDL with
pygame:

```
┌──────────────────────────────────────────────┐
│  jive.ui.*  — Python 3  (this project)       │  ← widget logic + rendering
├──────────────────────────────────────────────┤
│  pygame / pygame-ce                          │  ← SDL 2 abstraction
└──────────────────────────────────────────────┘
```

Every C source file (`jive_widget.c`, `jive_surface.c`, …) and every Lua module
(`Widget.lua`, `Surface.lua`, …) has a 1-to-1 Python counterpart in
`jive/ui/`.

The upstream repository is available at
<https://github.com/ralph-irving/jivelite>.  A local clone (shallow, all files
present) is expected as a sibling directory `../jivelite/` for reference during
development.

---

## What Has Been Ported

### Milestone M1 — Foundation (Phase 2 Core)

| Original (C / Lua) | Python module | Description |
|---|---|---|
| `jive_event.c` / `Event.lua` | `jive.ui.event` | Typed events (key, mouse, scroll, action, …) |
| `Framework.lua` | `jive.ui.framework` | Singleton event loop, window stack, actions |
| `Timer.lua` | `jive.ui.timer` | Interval / one-shot callback timers |
| `jive_surface.c` / `Surface.lua` | `jive.ui.surface` | Pygame surface wrapper, blit, clip, drawing |
| `jive_font.c` / `Font.lua` | `jive.ui.font` | TTF loading, metrics, render cache |
| `jive_widget.c` / `Widget.lua` | `jive.ui.widget` | Base widget (bounds, style, listeners, dirty flags) |
| `jive.h` (constants) | `jive.ui.constants` | Event types, keys, alignment, layout enums |

### Milestone M2 — Tile, Style, Window

| Original | Python module | Description |
|---|---|---|
| `Tile.lua` + C helpers | `jive.ui.tile` | 9-patch tile, fill-color, from-surface |
| `jive_style.c` + Lua skin | `jive.ui.style` | Hierarchical style lookup, caching |
| `jive_window.c` / `Window.lua` | `jive.ui.window` | Window widget, show/hide, border layout, transitions |

### Milestone M3 — Icon, Label, Group

| Original | Python module | Description |
|---|---|---|
| `jive_icon.c` / `Icon.lua` | `jive.ui.icon` | Image display, animation frames |
| `jive_label.c` / `Label.lua` | `jive.ui.label` | Single/multi-line text, scrolling, shadow |
| `jive_group.c` / `Group.lua` | `jive.ui.group` | H/V container, ordered children, mouse routing |

### Milestone M4 — Hello UI Demo

| File | Description |
|---|---|
| `examples/hello_ui.py` | Proof-of-life: opens a window, shows labels, auto-closes |

### Milestone M5 — Further Widgets

| Original | Python module | Description |
|---|---|---|
| `jive_textarea.c` / `Textarea.lua` | `jive.ui.textarea` | Multi-line text with word-wrap and scrolling |
| `jive_slider.c` / `Slider.lua` + `Scrollbar.lua` | `jive.ui.slider` | Slider + Scrollbar (range, value, drag) |
| `jive_menu.c` / `Menu.lua` | `jive.ui.menu` | Base menu (items, scrolling, key/mouse navigation) |
| `SimpleMenu.lua` | `jive.ui.simplemenu` | Convenience menu with text + icon + callback items |
| `Checkbox.lua` | `jive.ui.checkbox` | Toggle checkbox (extends Icon) |
| `RadioButton.lua` + `RadioGroup.lua` | `jive.ui.radio` | Mutual-exclusion radio buttons |

### Milestone M6 — Popup, Canvas, Choice & Scroll Helpers

| Original | Python module | Description |
|---|---|---|
| `Canvas.lua` | `jive.ui.canvas` | Free-drawing widget (extends Icon, custom render function) |
| `Audio.lua` | `jive.ui.audio` | Audio effects / playback (pygame.mixer wrapper / stub) |
| `Popup.lua` | `jive.ui.popup` | Transient popup window (extends Window, auto-hide, transparent) |
| `Choice.lua` | `jive.ui.choice` | Cyclic option selector (extends Label) |
| `SnapshotWindow.lua` | `jive.ui.snapshotwindow` | Screen-capture window (extends Window, static blit) |
| `ScrollWheel.lua` | `jive.ui.scrollwheel` | Non-accelerated scroll event filter |
| `ScrollAccel.lua` | `jive.ui.scrollaccel` | Accelerated scroll event filter (extends ScrollWheel) |
| `StickyMenu.lua` | `jive.ui.stickymenu` | Sticky-scroll menu (extends SimpleMenu, scroll resistance) |

### Milestone M7 — Button, ContextMenu, Flick

| Original | Python module | Description |
|---|---|---|
| `Button.lua` | `jive.ui.button` | Mouse-state-machine for press/hold/drag on widgets |
| `ContextMenuWindow.lua` | `jive.ui.contextmenuwindow` | Context menu overlay with screenshot shading |
| `Flick.lua` | `jive.ui.flick` | Touch gesture / flick engine (afterscroll, deceleration) |

### Milestone M8 — Input Widgets & Task

| Original | Python module | Description |
|---|---|---|
| `Task.lua` | `jive.ui.task` | Cooperative task scheduler (Python generators) |
| `IRMenuAccel.lua` | `jive.ui.irmenuaccel` | IR remote accelerated scroll event filter |
| `NumberLetterAccel.lua` | `jive.ui.numberletteraccel` | T9-style number-to-letter input for IR remotes |
| `Keyboard.lua` | `jive.ui.keyboard` | On-screen keyboard (QWERTY, numeric, hex, email, IP) |
| `Textinput.lua` + `jive_textinput.c` | `jive.ui.textinput` | Text input widget (cursor, char scrolling, value types) |
| `Timeinput.lua` | `jive.ui.timeinput` | Time picker widget (12h/24h scroll-wheel menus) |

### Milestone M9 — Networking & HomeMenu

| Original | Python module | Description |
|---|---|---|
| `net/Socket.lua` | `jive.net.socket_base` | Abstract base socket (open/close, read/write pump) |
| `net/SocketTcp.lua` | `jive.net.socket_tcp` | TCP client socket (connect, send/receive) |
| `net/SocketUdp.lua` | `jive.net.socket_udp` | UDP socket (broadcast, sendto/receivefrom) |
| `net/SocketTcpServer.lua` | `jive.net.socket_tcp_server` | TCP server socket (bind, listen, accept) |
| `net/Process.lua` | `jive.net.process` | Subprocess reader (popen, non-blocking read) |
| `jive_dns.c` + `net/DNS.lua` | `jive.net.dns` | Non-blocking DNS resolution |
| `net/NetworkThread.lua` | `jive.net.network_thread` | Select-based network I/O coordinator |
| `net/WakeOnLan.lua` | `jive.net.wake_on_lan` | Wake-on-LAN magic packet sender |
| `net/RequestHttp.lua` | `jive.net.request_http` | HTTP request object (method, URI, headers, body) |
| `net/RequestJsonRpc.lua` | `jive.net.request_jsonrpc` | JSON-RPC request over HTTP POST |
| `net/SocketHttp.lua` | `jive.net.socket_http` | HTTP client socket (state machine) |
| `net/SocketHttpQueue.lua` | `jive.net.socket_http_queue` | HTTP socket with external request queue |
| `net/HttpPool.lua` | `jive.net.http_pool` | Connection pool managing multiple HTTP sockets |
| `net/CometRequest.lua` | `jive.net.comet_request` | Comet/Bayeux HTTP request (JSON body, chunked) |
| `net/Comet.lua` | `jive.net.comet` | Cometd/Bayeux protocol client (subscribe, long-poll) |
| `HomeMenu.lua` | `jive.ui.homemenu` | Applet-driven home menu (node tree, ranking, custom nodes) |

### Utilities (fully ported)

| Original Lua | Python module | Description |
|---|---|---|
| `utils/autotable.lua` | `jive.utils.autotable` | Auto-vivifying nested dicts |
| `utils/datetime.lua` | `jive.utils.datetime_utils` | Date/time formatting helpers |
| `utils/debug.lua` | `jive.utils.debug` | Debug / traceback utilities |
| `utils/dumper.lua` | `jive.utils.dumper` | Pretty-print nested structures |
| `utils/jsonfilters.lua` | `jive.utils.jsonfilters` | JSON sink/source filters |
| `utils/locale.lua` | `jive.utils.locale` | Locale / i18n string tables |
| `utils/log.lua` | `jive.utils.log` | Logging subsystem |
| `utils/string.lua` | `jive.utils.string_utils` | String helper functions |
| `utils/table.lua` | `jive.utils.table_utils` | Table/dict utilities |

---

## What Has NOT Been Ported Yet

| Area | Lua / C Files | Notes |
|---|---|---|
| **Slim protocol** | `jive/slim/*.lua` | Player, SlimServer, ArtworkCache |
| **Applet system** | `Applet.lua`, `AppletManager.lua`, `AppletMeta.lua` | Plugin framework |
| **Visualizer** | `vis.lua`, `src/visualizer/` | Audio visualization |
| **Skins / Applets** | `share/jive/applets/` | All skin definitions and applets |

---

## Requirements

- **Python 3.10+**
- **pygame >= 2.5** or **pygame-ce >= 2.5**

Optional (development):

- pytest >= 7.0
- pytest-cov >= 4.0
- mypy >= 1.0

---

## Installation

```bash
# Clone the upstream reference (optional, for porting new modules)
git clone https://github.com/ralph-irving/jivelite.git

# Clone / copy the Python port
cd jivelite-py

# Create a virtual environment (recommended)
python -m venv .venv
source .venv/bin/activate      # Linux / macOS
# .venv\Scripts\activate       # Windows

# Install in editable mode with dev dependencies
pip install -e ".[dev]"
```

Or install just the runtime dependency:

```bash
pip install pygame-ce
```

---

## Quick Start — Hello UI Demo

```bash
python examples/hello_ui.py
```

This opens a 480 × 272 pygame window displaying:

- A title label ("Hello, Jivelite!")
- A body label ("Python3 port — Milestone M4")
- A footer label

The window auto-closes after 5 seconds or when you press **ESC**.

### Headless / CI

If you don't have a display (CI, SSH, WSL without GUI):

```bash
export SDL_VIDEODRIVER=dummy
python examples/hello_ui.py
```

---

## Running Tests

```bash
# All tests
python -m pytest

# Verbose with short tracebacks (default via pyproject.toml)
python -m pytest tests/

# Just UI tests
python -m pytest tests/test_ui.py

# Just utility tests
python -m pytest tests/test_utils.py

# With coverage
python -m pytest --cov=jive --cov-report=term-missing
```

### Current Test Count

| Test file | Tests | Status |
|---|---|---|
| `tests/test_ui.py` | 1130 | ✅ all passing |
| `tests/test_utils.py` | 327 | ✅ all passing |
| `tests/test_net.py` | 212 | ✅ all passing |
| **Total** | **1669** | **✅ all passing** |

### Headless Testing

Tests that require a pygame display use `SDL_VIDEODRIVER=dummy` internally.
If tests fail with "No available video device", set the environment variable:

```bash
export SDL_VIDEODRIVER=dummy    # Linux / macOS
set SDL_VIDEODRIVER=dummy       # Windows cmd
$env:SDL_VIDEODRIVER="dummy"    # Windows PowerShell
```

---

## Project Structure

```
jivelite-py/
├── jive/
│   ├── __init__.py
│   ├── ui/                         # UI widget framework
│   │   ├── __init__.py
│   │   ├── constants.py            # Event types, key codes, enums
│   │   ├── event.py                # Event objects
│   │   ├── timer.py                # Timer system
│   │   ├── surface.py              # pygame.Surface wrapper
│   │   ├── font.py                 # Font loading & metrics
│   │   ├── widget.py               # Base Widget class
│   │   ├── framework.py            # Framework singleton
│   │   ├── tile.py                 # 9-patch tile system
│   │   ├── style.py                # Style / skin lookup
│   │   ├── window.py               # Window widget
│   │   ├── icon.py                 # Icon widget
│   │   ├── label.py                # Label widget
│   │   ├── group.py                # Group container
│   │   ├── textarea.py             # Multi-line text with word-wrap
│   │   ├── slider.py               # Slider + Scrollbar
│   │   ├── menu.py                 # Base menu widget
│   │   ├── simplemenu.py           # Convenience text+icon+callback menu
│   │   ├── checkbox.py             # Toggle checkbox
│   │   ├── radio.py                # RadioGroup + RadioButton
│   │   ├── canvas.py               # Free-drawing widget
│   │   ├── audio.py                # Audio effects (pygame.mixer)
│   │   ├── popup.py                # Transient popup window
│   │   ├── choice.py               # Cyclic option selector
│   │   ├── snapshotwindow.py       # Screen-capture window
│   │   ├── scrollwheel.py          # Non-accel scroll filter
│   │   ├── scrollaccel.py          # Accelerated scroll filter
│   │   ├── stickymenu.py           # Sticky-scroll menu
│   │   ├── button.py               # Mouse state machine
│   │   ├── flick.py                # Touch gesture / flick engine
│   │   ├── contextmenuwindow.py    # Context menu overlay
│   │   ├── task.py                 # Cooperative task scheduler
│   │   ├── irmenuaccel.py          # IR remote acceleration
│   │   ├── numberletteraccel.py    # T9-style input handler
│   │   ├── keyboard.py             # On-screen keyboard
│   │   ├── textinput.py            # Text input widget
│   │   ├── timeinput.py            # Time picker widget
│   │   └── homemenu.py             # Applet-driven home menu
│   ├── net/                        # Network layer
│   │   ├── socket_base.py          # Abstract base socket
│   │   ├── socket_tcp.py           # TCP client socket
│   │   ├── socket_udp.py           # UDP socket
│   │   ├── socket_tcp_server.py    # TCP server socket
│   │   ├── process.py              # Subprocess reader
│   │   ├── dns.py                  # DNS resolution
│   │   ├── network_thread.py       # Network I/O coordinator
│   │   ├── wake_on_lan.py          # Wake-on-LAN sender
│   │   ├── request_http.py         # HTTP request object
│   │   ├── request_jsonrpc.py      # JSON-RPC request
│   │   ├── socket_http.py          # HTTP client socket
│   │   ├── socket_http_queue.py    # HTTP socket queue
│   │   ├── http_pool.py            # HTTP connection pool
│   │   ├── comet_request.py        # Comet/Bayeux request
│   │   └── comet.py                # Cometd protocol client
│   ├── utils/                      # Utility modules
│   │   ├── autotable.py
│   │   ├── datetime_utils.py
│   │   ├── debug.py
│   │   ├── dumper.py
│   │   ├── jsonfilters.py
│   │   ├── locale.py
│   │   ├── log.py
│   │   ├── string_utils.py
│   │   └── table_utils.py
│   └── slim/                       # (placeholder — not yet ported)
├── examples/
│   └── hello_ui.py                 # Hello World demo
├── tests/
│   ├── test_ui.py                  # UI widget tests (1130 tests)
│   ├── test_utils.py               # Utility module tests (327 tests)
│   └── test_net.py                 # Network layer tests (212 tests)
└── pyproject.toml                  # Project metadata & build config
```

---

## Porting Guide — Lua → Python Mapping

### General Principles

| Lua pattern | Python equivalent |
|---|---|
| `oo.class(Widget)` | `class Foo(Widget):` |
| `self:method()` | `self.method()` |
| `function obj:method(…)` | `def method(self, …):` |
| `_ENV` / `module(…)` | Regular Python module |
| `coxpcall` / `copcall` | `try` / `except` (native) |
| `log:debug(…)` | `logger.debug(…)` (stdlib `logging`) |
| Table with 1-based index | List with 0-based index |
| `nil` | `None` |
| `type(x) == "function"` | `callable(x)` |

### Style / Skin System

The Lua skin is a nested table loaded from a skin applet.  In Python, the
skin is a nested `dict` set via `skin.data = { … }`.  Style lookups use
the same path-based resolution:

```
widget style "menu_item" → skin["menu"]["item"] (strips prefixes)
```

### Event System

| Lua | Python |
|---|---|
| `Event:new(EVENT_SCROLL, rel)` | `Event(EVENT_SCROLL, rel=amount)` |
| `Event:new(EVENT_KEY_PRESS, code)` | `Event(EVENT_KEY_PRESS, code=key)` |
| `Event:new(EVENT_MOUSE_DOWN, x, y)` | `Event(EVENT_MOUSE_DOWN, x=x, y=y)` |
| `event:getScroll()` | `event.get_scroll()` |
| `event:getKeycode()` | `event.get_keycode()` |

### Widget Dirty Flags

| Lua flag | Python attribute |
|---|---|
| `NEEDS_SKIN` | `_needs_skin` |
| `NEEDS_LAYOUT` | `_needs_layout` |
| `NEEDS_DRAW` | `_needs_draw` |

### C → Python Correspondence

| C source | Python module | Key functions ported |
|---|---|---|
| `jive_widget.c` | `widget.py` | bounds, pack, align, iterate, dispatch |
| `jive_surface.c` | `surface.py` | blit, clip, fill, draw_text, rotozoom |
| `jive_font.c` | `font.py` | load, width, nwidth, height, ascend, render |
| `jive_style.c` | `style.py` | style_path, find_value, style_int, style_color |
| `jive_event.c` | `event.py` | Event construction, payload access |
| `jive_icon.c` | `icon.py` | prepare, layout, draw, animation |
| `jive_label.c` | `label.py` | prepare, layout, draw, word-wrap |
| `jive_group.c` | `group.py` | h/v layout, iterate, preferred_bounds |
| `jive_window.c` | `window.py` | show/hide, border_layout, transitions |
| `jive_menu.c` | `menu.py` | item management, scrolling, layout |
| `jive_slider.c` | `slider.py` | range, value, drag, pill positioning |
| `jive_textarea.c` | `textarea.py` | word-wrap, pixel-offset scrolling |
| — | `canvas.py` | custom render function draw |
| — | `audio.py` | sound loading, playback, effects toggle |
| — | `popup.py` | transient overlay, auto-hide |
| — | `choice.py` | cyclic option selection |
| — | `snapshotwindow.py` | screen capture, static blit |
| — | `scrollwheel.py` | normalised scroll direction |
| — | `scrollaccel.py` | tiered scroll acceleration |
| — | `stickymenu.py` | scroll resistance multiplier |

---

## Contributing

1. **Pick an un-ported module** from the "What Has NOT Been Ported Yet" table
2. Clone the upstream repo if you haven't:
   `git clone https://github.com/ralph-irving/jivelite.git`
3. Study the original Lua file in `jivelite/share/jive/jive/` and the
   corresponding C file in `jivelite/src/`
4. Create the Python module in `jive/` following the existing patterns
5. Add tests in `tests/`
6. Run the full suite: `python -m pytest`

### Code Style

- Python 3.10+ type hints throughout
- `from __future__ import annotations` in every module
- PEP 8 naming (`snake_case` methods), with `camelCase` aliases for Lua API
  compatibility (e.g. `set_value()` + `setValue()`)
- Docstrings on public classes and methods

---

## License

This project is a derivative of the original
[Jivelite](https://github.com/ralph-irving/jivelite) codebase, which carries a
**BSD 3-Clause** license:

> Copyright 2010, Logitech, Inc.  All rights reserved.
>
> Copyright 2013-2014, Adrian Smith (triode1@btinternet).

See the [LICENSE file in the upstream repository](https://github.com/ralph-irving/jivelite/blob/master/LICENSE)
for the full license text.

The Python port follows the same BSD 3-Clause license.