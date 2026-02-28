# KONTEXT.md — jivelite-py

> **Zweck:** Diese Datei gibt KI-Assistenten (Cursor, Copilot, Claude, etc.)
> den nötigen Kontext, um produktiv am Projekt mitzuarbeiten.
> Wird zu Beginn jeder Session geladen.
>
> **Upstream-Repository:** <https://github.com/ralph-irving/jivelite>

---

## 1. Was ist dieses Projekt?

**jivelite-py** ist ein Python-3-Port von
[Jivelite](https://github.com/ralph-irving/jivelite) — der Community-UI für den
Lyrion Music Server (ehemals Logitech Media Server / Squeezebox).

- **Upstream:** <https://github.com/ralph-irving/jivelite> (C + Lua, BSD-3-Clause, 225 Commits)
- **Homepage:** <https://sourceforge.net/projects/lmsclients/files/jivelite/>

Das Original besteht aus:
- **C-Rendering-Engine** (`src/jive_*.c`) — SDL-basiert
- **Lua-UI-Schicht** (`share/jive/jive/ui/*.lua`) — Widget-Logik, Skins, Applets
- **Lua-Utilities** (`share/jive/jive/utils/*.lua`)
- **Lua-Netzwerk** (`share/jive/jive/net/*.lua`) — Comet, HTTP, Sockets
- **Lua-Slim-Protokoll** (`share/jive/jive/slim/*.lua`) — Player, Server

Dieses Projekt ersetzt C + Lua durch **reines Python + pygame**.

---

## 2. Projektstruktur

```
jivelite-py/
├── jive/
│   ├── __init__.py
│   ├── ui/                         # UI-Widget-Framework (Kern des Ports)
│   │   ├── __init__.py
│   │   ├── constants.py            # Event-Typen, Key-Codes, Alignment, Layout-Enums
│   │   ├── event.py                # Event-Objekte (scroll, key, mouse, action, …)
│   │   ├── timer.py                # Timer-System (interval / once)
│   │   ├── surface.py              # pygame.Surface-Wrapper (blit, clip, draw)
│   │   ├── font.py                 # TTF-Laden, Metriken, Render-Cache
│   │   ├── widget.py               # Basis-Widget (bounds, style, listeners, dirty flags)
│   │   ├── framework.py            # Framework-Singleton (Event-Loop, Window-Stack)
│   │   ├── tile.py                 # 9-Patch-Tile-System
│   │   ├── style.py                # Style/Skin-Lookup, Caching
│   │   ├── window.py               # Window-Widget (show/hide, border layout, transitions)
│   │   ├── icon.py                 # Icon-Widget (Bild, Animation)
│   │   ├── label.py                # Label-Widget (Text, mehrzeilig, Scrolling, Shadow)
│   │   ├── group.py                # Group-Container (H/V-Layout)
│   │   ├── textarea.py             # Textarea (Wordwrap + Scrolling)
│   │   ├── slider.py               # Slider + Scrollbar
│   │   ├── menu.py                 # Menu-Basis-Widget
│   │   ├── simplemenu.py           # SimpleMenu (Text + Icon + Callback)
│   │   ├── checkbox.py             # Checkbox (extends Icon)
│   │   ├── radio.py                # RadioGroup + RadioButton
│   │   ├── canvas.py               # Canvas (extends Icon, custom render)
│   │   ├── audio.py                # Audio-Effekte (pygame.mixer / Stub)
│   │   ├── popup.py                # Popup-Fenster (extends Window)
│   │   ├── choice.py               # Choice-Selektor (extends Label)
│   │   ├── snapshotwindow.py       # Screenshot-Fenster (extends Window)
│   │   ├── scrollwheel.py          # Scroll-Event-Filter (nicht beschleunigt)
│   │   ├── scrollaccel.py          # Scroll-Event-Filter (beschleunigt)
│   │   ├── stickymenu.py           # StickyMenu (extends SimpleMenu)
│   │   ├── button.py               # Button-State-Machine (press/hold/drag)
│   │   ├── flick.py                # Touch-Gesture Flick Engine
│   │   ├── contextmenuwindow.py    # Context-Menu Window (Screenshot-Overlay)
│   │   ├── task.py                 # Cooperative Task Scheduler (Generator-basiert)
│   │   ├── irmenuaccel.py          # IR-Remote Acceleration
│   │   ├── numberletteraccel.py    # T9-Style Number-Letter Input
│   │   ├── keyboard.py             # On-Screen Keyboard (QWERTY, numeric, hex, email, IP)
│   │   ├── textinput.py            # Text-Input-Widget (Cursor, Scrolling, Value-Types)
│   │   ├── timeinput.py            # Time-Picker-Widget (12h/24h, Scroll-Wheel)
│   │   └── homemenu.py             # HomeMenu (Applet-getriebenes Hauptmenü, Knotenbaum)
│   ├── net/                        # Netzwerk-Schicht (M9 — vollständig portiert)
│   │   ├── __init__.py
│   │   ├── socket_base.py          # Abstrakte Basis-Socket-Klasse
│   │   ├── socket_tcp.py           # TCP-Client-Socket
│   │   ├── socket_udp.py           # UDP-Socket (Broadcast, sendto/recvfrom)
│   │   ├── socket_tcp_server.py    # TCP-Server-Socket (accept)
│   │   ├── process.py              # Subprocess-Reader (popen, non-blocking)
│   │   ├── dns.py                  # Non-blocking DNS-Auflösung
│   │   ├── network_thread.py       # Select-basierter Netzwerk-I/O-Koordinator
│   │   ├── wake_on_lan.py          # Wake-on-LAN Magic-Packet-Sender
│   │   ├── request_http.py         # HTTP-Request-Objekt
│   │   ├── request_jsonrpc.py      # JSON-RPC-Request über HTTP POST
│   │   ├── socket_http.py          # HTTP-Client-Socket (State-Machine)
│   │   ├── socket_http_queue.py    # HTTP-Socket mit externer Request-Queue
│   │   ├── http_pool.py            # Connection-Pool für HTTP-Sockets
│   │   ├── comet_request.py        # Comet/Bayeux HTTP-Request
│   │   └── comet.py                # Cometd/Bayeux Protokoll-Client
│   ├── utils/                      # Utility-Module (vollständig portiert)
│   │   ├── __init__.py
│   │   ├── autotable.py            # Auto-vivifying nested dicts
│   │   ├── datetime_utils.py       # Datum/Zeit-Formatierung
│   │   ├── debug.py                # Debug-/Traceback-Utilities
│   │   ├── dumper.py               # Pretty-Print verschachtelter Strukturen
│   │   ├── jsonfilters.py          # JSON-Filter
│   │   ├── locale.py               # Locale / i18n String-Tabellen
│   │   ├── log.py                  # Logging-Subsystem
│   │   ├── string_utils.py         # String-Hilfsfunktionen
│   │   └── table_utils.py          # Dict-/Tabellen-Utilities
│   └── slim/                       # (Platzhalter — noch nicht portiert)
├── examples/
│   └── hello_ui.py                 # Hello-World-Demo (öffnet Fenster, zeigt Labels)
├── tests/
│   ├── test_ui.py                  # UI-Widget-Tests
│   ├── test_utils.py               # Utility-Tests
│   └── test_net.py                 # Netzwerk-Tests
├── pyproject.toml                  # Build-Config (setuptools)
├── README.md                       # Projektbeschreibung
└── KONTEXT.md                      # ← diese Datei
```

**Quellcode-Umfang:**
- `jive/ui/` — ~20.000 LOC Python (36 Module)
- `jive/net/` — ~4.500 LOC Python (16 Module)
- `jive/utils/` — ~1.500 LOC Python (9 Module)
- `tests/` — ~14.000 LOC Python
- **Gesamt: ~40.000 LOC**

---

## 3. Referenz-Repository (Original)

Das Original-Jivelite liegt als Schwester-Verzeichnis unter `../jivelite/`
(shallow clone von <https://github.com/ralph-irving/jivelite>, Commit `d43a20b`,
alle 3.606 Dateien vollständig vorhanden):

```
../jivelite/
├── src/                    # C-Quellen (jive_widget.c, jive_surface.c, …)
├── share/jive/jive/
│   ├── ui/                 # Lua-UI-Module (Widget.lua, Window.lua, …)
│   ├── utils/              # Lua-Utilities
│   ├── net/                # Lua-Netzwerk
│   └── slim/               # Lua-Slim-Protokoll
├── share/jive/applets/     # Skins + Applets (Lua)
├── share/jive/fonts/       # TTF-Fonts
└── LICENSE                 # BSD-3-Clause
```

**Beim Portieren immer beide Quellen konsultieren:**
1. Die C-Datei (`src/jive_*.c`) — für Rendering-Logik, Layout-Algorithmen
2. Die Lua-Datei (`share/jive/jive/ui/*.lua`) — für Widget-Verhalten, API

Falls das lokale Verzeichnis `../jivelite/` fehlt:
```bash
git clone https://github.com/ralph-irving/jivelite.git ../jivelite
```

---

## 4. Technologie-Stack

| Komponente | Technologie |
|---|---|
| Sprache | Python 3.10+ |
| Grafik | pygame >= 2.5 oder pygame-ce |
| Build | setuptools (pyproject.toml) |
| Tests | pytest >= 7.0 |
| Type-Checking | mypy >= 1.0 (optional) |
| OS | Windows, Linux, macOS |

---

## 5. Konventionen & Stil

### Namensgebung
- **Python-Standard:** `snake_case` für Methoden und Variablen
- **Lua-Kompatibilitäts-Aliase:** Jede `snake_case`-Methode hat einen `camelCase`-Alias
  (z.B. `set_value()` + `setValue()`, `set_selected()` + `setSelected()`)
- Klassen: `PascalCase` (wie im Lua-Original)

### Module
- Jedes Modul hat `from __future__ import annotations`
- Type-Hints durchgängig
- Docstrings auf öffentlichen Klassen und Methoden

### Widget-System
- **Dirty Flags:** `_needs_skin`, `_needs_layout`, `_needs_draw`
- **Style-Lookup:** `style_int()`, `style_color()`, `style_font()`, `style_align()`, etc.
- **Globaler Skin:** `from jive.ui.style import skin` → `skin.data = { … }`
- **Framework-Singleton:** `from jive.ui.framework import framework`

### Event-System
- Events werden mit benannten Parametern konstruiert:
  - `Event(EVENT_SCROLL, rel=amount)`
  - `Event(EVENT_KEY_PRESS, code=keycode)`
  - `Event(EVENT_MOUSE_DOWN, x=x, y=y)`
- Listener geben `EVENT_CONSUME` zurück um Events zu schlucken, oder `0`/`EVENT_UNUSED`

### Style-API (wichtige Signaturen)
```python
style_int(widget, key, default=None)     # → int | None
style_color(widget, key)                 # → (color_tuple, is_set)
style_font(widget, key)                  # 2 Argumente! NICHT 3
style_align(widget, key, default=None)   # → Align-Wert
style_insets(widget, key, default=None)  # → (top, right, bottom, left)
```

---

## 6. C → Lua → Python Zuordnungstabelle

### UI-Module

| C-Datei | Lua-Datei | Python-Modul | Status |
|---|---|---|---|
| `jive_event.c` | `Event.lua` | `jive.ui.event` | ✅ fertig |
| — | `Framework.lua` | `jive.ui.framework` | ✅ fertig |
| — | `Timer.lua` | `jive.ui.timer` | ✅ fertig |
| `jive_surface.c` | `Surface.lua` | `jive.ui.surface` | ✅ fertig |
| `jive_font.c` | `Font.lua` | `jive.ui.font` | ✅ fertig |
| `jive_widget.c` | `Widget.lua` | `jive.ui.widget` | ✅ fertig |
| `jive_style.c` | — | `jive.ui.style` | ✅ fertig |
| — | `Tile.lua` | `jive.ui.tile` | ✅ fertig |
| `jive_window.c` | `Window.lua` | `jive.ui.window` | ✅ fertig |
| `jive_icon.c` | `Icon.lua` | `jive.ui.icon` | ✅ fertig |
| `jive_label.c` | `Label.lua` | `jive.ui.label` | ✅ fertig |
| `jive_group.c` | `Group.lua` | `jive.ui.group` | ✅ fertig |
| `jive_textarea.c` | `Textarea.lua` | `jive.ui.textarea` | ✅ fertig |
| `jive_slider.c` | `Slider.lua` + `Scrollbar.lua` | `jive.ui.slider` | ✅ fertig |
| `jive_menu.c` | `Menu.lua` | `jive.ui.menu` | ✅ fertig |
| — | `SimpleMenu.lua` | `jive.ui.simplemenu` | ✅ fertig |
| — | `Checkbox.lua` | `jive.ui.checkbox` | ✅ fertig |
| — | `RadioButton.lua` + `RadioGroup.lua` | `jive.ui.radio` | ✅ fertig |
| — | `Canvas.lua` | `jive.ui.canvas` | ✅ fertig |
| — | `Audio.lua` | `jive.ui.audio` | ✅ fertig |
| — | `Popup.lua` | `jive.ui.popup` | ✅ fertig |
| — | `Choice.lua` | `jive.ui.choice` | ✅ fertig |
| — | `SnapshotWindow.lua` | `jive.ui.snapshotwindow` | ✅ fertig |
| — | `ScrollWheel.lua` | `jive.ui.scrollwheel` | ✅ fertig |
| — | `ScrollAccel.lua` | `jive.ui.scrollaccel` | ✅ fertig |
| — | `StickyMenu.lua` | `jive.ui.stickymenu` | ✅ fertig |
| — | `Button.lua` | `jive.ui.button` | ✅ fertig |
| — | `Flick.lua` | `jive.ui.flick` | ✅ fertig |
| — | `ContextMenuWindow.lua` | `jive.ui.contextmenuwindow` | ✅ fertig |
| — | `Task.lua` | `jive.ui.task` | ✅ fertig |
| — | `IRMenuAccel.lua` | `jive.ui.irmenuaccel` | ✅ fertig |
| — | `NumberLetterAccel.lua` | `jive.ui.numberletteraccel` | ✅ fertig |
| — | `Keyboard.lua` | `jive.ui.keyboard` | ✅ fertig |
| `jive_textinput.c` | `Textinput.lua` | `jive.ui.textinput` | ✅ fertig |
| — | `Timeinput.lua` | `jive.ui.timeinput` | ✅ fertig |
| — | `HomeMenu.lua` | `jive.ui.homemenu` | ✅ fertig |

### Netzwerk-Module (M9)

| Lua-Datei | Python-Modul | Status |
|---|---|---|
| `net/Socket.lua` | `jive.net.socket_base` | ✅ fertig |
| `net/SocketTcp.lua` | `jive.net.socket_tcp` | ✅ fertig |
| `net/SocketUdp.lua` | `jive.net.socket_udp` | ✅ fertig |
| `net/SocketTcpServer.lua` | `jive.net.socket_tcp_server` | ✅ fertig |
| `net/Process.lua` | `jive.net.process` | ✅ fertig |
| `jive_dns.c` + `net/DNS.lua` | `jive.net.dns` | ✅ fertig |
| `net/NetworkThread.lua` | `jive.net.network_thread` | ✅ fertig |
| `net/WakeOnLan.lua` | `jive.net.wake_on_lan` | ✅ fertig |
| `net/RequestHttp.lua` | `jive.net.request_http` | ✅ fertig |
| `net/RequestJsonRpc.lua` | `jive.net.request_jsonrpc` | ✅ fertig |
| `net/SocketHttp.lua` | `jive.net.socket_http` | ✅ fertig |
| `net/SocketHttpQueue.lua` | `jive.net.socket_http_queue` | ✅ fertig |
| `net/HttpPool.lua` | `jive.net.http_pool` | ✅ fertig |
| `net/CometRequest.lua` | `jive.net.comet_request` | ✅ fertig |
| `net/Comet.lua` | `jive.net.comet` | ✅ fertig |

### Utilities (alle fertig)

| Lua | Python | Status |
|---|---|---|
| `utils/autotable.lua` | `jive.utils.autotable` | ✅ |
| `utils/datetime.lua` | `jive.utils.datetime_utils` | ✅ |
| `utils/debug.lua` | `jive.utils.debug` | ✅ |
| `utils/dumper.lua` | `jive.utils.dumper` | ✅ |
| `utils/jsonfilters.lua` | `jive.utils.jsonfilters` | ✅ |
| `utils/locale.lua` | `jive.utils.locale` | ✅ |
| `utils/log.lua` | `jive.utils.log` | ✅ |
| `utils/string.lua` | `jive.utils.string_utils` | ✅ |
| `utils/table.lua` | `jive.utils.table_utils` | ✅ |
| `utils/coxpcall.lua` | — (nicht nötig, Python hat try/except) | ⏭️ übersprungen |

### Noch offen

| Bereich | Lua / C Dateien | Anmerkungen |
|---|---|---|
| **Slim-Protokoll** | `slim/*.lua` | Player, SlimServer, ArtworkCache |
| **Applet-System** | `Applet.lua`, `AppletManager.lua`, `AppletMeta.lua` | Plugin-Framework |
| **Skins / Applets** | `share/jive/applets/` | Alle Skin-Definitionen und Applets |
| **Visualizer** | `vis.lua`, `src/visualizer/` | Audio-Visualisierung |

---

## 7. Tests

### Ausführen

```bash
# Alle Tests
python -m pytest

# Nur UI
python -m pytest tests/test_ui.py

# Nur Utils
python -m pytest tests/test_utils.py

# Nur Netzwerk
python -m pytest tests/test_net.py

# Mit Coverage
python -m pytest --cov=jive --cov-report=term-missing
```

### Aktuelle Zählung (Stand: Session 74, M9 + HomeMenu abgeschlossen)

| Datei | Tests | Status |
|---|---|---|
| `tests/test_ui.py` | 1130 | ✅ alle grün |
| `tests/test_utils.py` | 327 | ✅ alle grün |
| `tests/test_net.py` | 212 | ✅ alle grün |
| **Gesamt** | **1669** | **✅ alle grün** |

### Test-Klassen in `test_ui.py`

| Klasse | Testet | Anzahl |
|---|---|---|
| `TestConstants` | Event-Typen, Bitmasks, Enums | ~20 |
| `TestEvent` | Event-Konstruktion, Payload | ~30 |
| `TestTimer` | Timer-Lifecycle, Queue, Callbacks | ~20 |
| `TestWidget` | Bounds, Style, Listeners, Dirty Flags | ~50 |
| `TestSurface` | Blit, Clip, Drawing, Image-Loading | ~25 |
| `TestFont` | Load, Metrics, Render, Cache | ~15 |
| `TestFramework` | Init, Window Stack, Actions, Events | ~40 |
| `TestWidgetTimerIntegration` | Timer + Widget Zusammenspiel | ~5 |
| `TestEventConstants` | Bitmask-Matching | ~5 |
| `TestWidgetSubclass` | Custom Widgets, Override | ~5 |
| `TestTile` | Fill-Color, Load, Blit, 9-Patch | ~20 |
| `TestStyle` | Style-Lookup, Caching, Types | ~30 |
| `TestWindow` | Show/Hide, Layout, Transitions | ~50 |
| `TestIcon` | Image, Animation, Preferred Bounds | ~25 |
| `TestLabel` | Text, Multi-Line, Scrolling | ~30 |
| `TestGroup` | H/V-Layout, Children, Mouse | ~30 |
| `TestHelloUI` | End-to-End-Demo-Integration | ~5 |
| `TestTextarea` | Wordwrap, Scrolling, Events | ~30 |
| `TestSlider` | Range, Value, Drag, Events | ~30 |
| `TestScrollbar` | Scrollbar-Subclass | ~12 |
| `TestMenu` | Items, Scrolling, Navigation | ~45 |
| `TestSimpleMenu` | Items, Sort, Callbacks | ~35 |
| `TestCheckbox` | Toggle, Closure, Selected | ~15 |
| `TestRadioGroup` | Group-Verwaltung, Exclusion | ~10 |
| `TestRadioButton` | Construction, Selection, Closure | ~15 |
| `TestM5Integration` | Cross-Widget-Integration | ~10 |
| `TestCanvas` | Canvas-Widget (render, props) | ~10 |
| `TestAudio` | Audio/Sound (stub, lifecycle) | ~18 |
| `TestScrollWheel` | Non-accelerated scroll filter | ~12 |
| `TestScrollAccel` | Accelerated scroll filter | ~10 |
| `TestPopup` | Popup-Window (defaults, repr) | ~14 |
| `TestSnapshotWindow` | Snapshot capture/draw | ~10 |
| `TestChoice` | Cyclic option selector | ~20 |
| `TestStickyMenu` | Sticky scroll resistance | ~16 |
| `TestM6Integration` | M6 Cross-Widget-Integration | ~10 |
| `TestButton` | Mouse-State-Machine (press/hold/drag) | ~25 |
| `TestFlick` | Touch-Gesture Flick Engine | ~30 |
| `TestContextMenuWindow` | Context-Menu Window (screenshot) | ~20 |
| `TestM7Integration` | M7 Cross-Module-Integration | ~10 |
| `TestTask` | Cooperative Task Scheduler | 22 |
| `TestIRMenuAccel` | IR Remote Acceleration | 14 |
| `TestNumberLetterAccel` | T9-Style Number-Letter Input | 15 |
| `TestKeyboard` | On-Screen Keyboard | 21 |
| `TestTextinput` | Text Input Widget | 29 |
| `TestTextinputValueTypes` | Value Type Proxies | 23 |
| `TestTimeinput` | Time Picker Widget | 23 |
| `TestM8Integration` | M8 Cross-Module-Integration | 10 |
| `TestHomeMenu` | HomeMenu (Konstruktion, Items, Nodes, Titel) | ~30 |
| `TestHomeMenuRanking` | Ranking (up/down/top/bottom) | ~10 |
| `TestHomeMenuCustomNodes` | Custom-Node-Overrides, Disable | ~8 |
| `TestHomeMenuLockUnlock` | Menu Lock/Unlock | ~3 |
| `TestHomeMenuIterator` | Iterator über Home-Items | ~3 |
| `TestHomeMenuOpenNode` | openNodeById | ~4 |
| `TestHomeMenuCamelCaseAliases` | camelCase-Aliase | 1 |
| `TestMenuCloseableLock` | Menu.set_closeable / lock / unlock | ~7 |
| `TestSimpleMenuNewComparators` | ComplexWeightAlpha, Rank Komparatoren | ~7 |
| `TestWindowSetButtonAction` | Window.set_button_action | ~3 |
| `TestFrameworkActionTranslation` | Action-to-Action Translation | ~4 |
| `TestUsesHelper` | _uses dict-Merge Helper | ~4 |
| `TestHomeMenuM9Integration` | M9 Cross-Module-Integration | ~5 |

### Test-Klassen in `test_net.py`

| Klasse | Testet | Anzahl |
|---|---|---|
| `TestSocketBase` | Abstrakte Socket-Basis | ~18 |
| `TestSocketTcp` | TCP-Client-Socket | ~16 |
| `TestSocketUdp` | UDP-Socket | ~14 |
| `TestProcess` | Subprocess-Reader | ~10 |
| `TestDNS` | DNS-Auflösung | ~14 |
| `TestNetworkThread` | Select-basierter I/O-Koordinator | ~20 |
| `TestWakeOnLan` | Wake-on-LAN | ~8 |
| `TestRequestHttp` | HTTP-Request-Objekt | ~12 |
| `TestRequestJsonRpc` | JSON-RPC-Request | ~8 |
| `TestSocketHttp` | HTTP-Client-Socket | ~18 |
| `TestSocketHttpQueue` | HTTP-Socket-Queue | ~10 |
| `TestHttpPool` | Connection-Pool | ~10 |
| `TestCometRequest` | Comet/Bayeux Request | ~8 |
| `TestComet` | Cometd-Client | ~12 |
| `TestSocketTcpServer` | TCP-Server-Socket | ~8 |
| `TestM9Integration` | Netzwerk-Integration | ~6 |

### Headless-Testing (CI)

Tests die pygame-Display brauchen setzen intern `SDL_VIDEODRIVER=dummy`.
Falls Tests trotzdem mit "No available video device" fehlschlagen:

```bash
export SDL_VIDEODRIVER=dummy    # Linux / macOS
set SDL_VIDEODRIVER=dummy       # Windows cmd
$env:SDL_VIDEODRIVER="dummy"    # PowerShell
```

---

## 8. Bekannte Stolpersteine (für KI-Sessions)

### API-Signaturen die oft falsch geraten werden

| Falsch ❌ | Richtig ✅ |
|---|---|
| `style_font(self, "font", None)` | `style_font(self, "font")` — nur 2 Argumente |
| `pygame.image.tostring(…)` | `pygame.image.tobytes(…)` — tostring ist deprecated |
| `Event(EVENT_MOUSE_DOWN, mouse=(x,y))` | `Event(EVENT_MOUSE_DOWN, x=x, y=y)` — kein `mouse=` |
| `self._dirty_skin` | `self._needs_skin` — Flags heißen `_needs_*` |
| `Event(EVENT_SCROLL, amount)` | `Event(EVENT_SCROLL, rel=amount)` — benannte Parameter |
| `if not port:` (für Port-Validierung) | `if port is None:` — Port 0 ist gültig (OS wählt) |

### Widget-Initialisierung

- `checkbox.py`: `self.selected` muss mit einem Sentinel initialisiert werden,
  damit `set_selected(False)` im Konstruktor nicht übersprungen wird
- `radio.py`: `self.closure = None` muss **vor** `group.set_selected(self)` gesetzt werden,
  sonst gibt es `AttributeError`

### Style-System

- `skin` ist ein globales Objekt: `from jive.ui.style import skin`
- Tests müssen `skin.data = { … }` setzen oder mocken
- `style_color()` gibt ein Tupel `(color, is_set)` zurück, nicht nur die Farbe
- Style-Keys werden per `style_path()` aufgelöst, mit Prefix-Stripping

### Framework

- `framework` ist ein Singleton: `from jive.ui.framework import framework`
- `framework.init()` muss vor Window-Operationen aufgerufen werden
- `framework.quit()` räumt auf (pygame.quit)
- In Tests: `framework.quit()` im `teardown_method` aufrufen

### Netzwerk (M9)

- `SocketBase.priority` ist initial `None` → wird in `t_add_read`/`t_add_write` auf `PRIORITY_LOW` defaulted
- `Task(priority=...)` validiert strikt: nur `PRIORITY_AUDIO(1)`, `PRIORITY_HIGH(2)`, `PRIORITY_LOW(3)`
- `SocketTcpServer` und `SocketTcp` akzeptieren `port=0` (OS wählt freien Port)
- `HttpPool.queue()` dispatcht sofort an idle Sockets → `queue_count` kann nach `queue()` schon 0 sein
- `SocketHttp` State-Machine kettet Zustände: `t_send_resolve` → `t_send_connect` → `t_send_request` (alles synchron)

### HomeMenu

- `HomeMenu` ist **keine Widget-Subklasse** — es ist ein Manager-Objekt mit einem `window`-Attribut
- Items im Home-Menü werden als **Kopie** hinzugefügt (via `_uses()` Helper)
- `add_node()` erstellt automatisch ein `Window` + `SimpleMenu` für den Knoten
- Komparatoren: `SimpleMenu.itemComparatorComplexWeightAlpha` und `SimpleMenu.itemComparatorRank`
- `set_closeable(False)` auf dem Root-Menü verhindert Schließen via "back"
- `set_button_action()` auf Window ist aktuell ein **Stub** (speichert Mapping, verdrahtet keine Widgets)
- `get_action_to_action_translation()` auf Framework ist ein **Stub** (gibt `None` zurück)

---

## 9. Meilenstein-Historie

| Meilenstein | Inhalt | Sessions | Status |
|---|---|---|---|
| **M1** | Foundation (Event, Timer, Surface, Font, Widget, Framework, Constants) | 1–30 | ✅ fertig |
| **M2** | Tile, Style, Window | 31–45 | ✅ fertig |
| **M3** | Icon, Label, Group | 46–60 | ✅ fertig |
| **M4** | Hello UI Demo + Integration | 61–68 | ✅ fertig |
| **M5** | Textarea, Slider, Menu, SimpleMenu, Checkbox, Radio | 69–71 | ✅ fertig |
| **M6** | Canvas, Audio, Popup, Choice, SnapshotWindow, ScrollWheel, ScrollAccel, StickyMenu | 71 | ✅ fertig |
| **M7** | Button, ContextMenuWindow, Flick | 72 | ✅ fertig |
| **M8** | Task, IRMenuAccel, NumberLetterAccel, Keyboard, Textinput, Timeinput | 73 | ✅ fertig |
| **M9** | Netzwerk (net/*.lua Port) + HomeMenu | 74 | ✅ fertig |
| **M10** | Slim-Protokoll + Applet-System | — | ❌ offen |
| **M11** | Skins + vollständige UI | — | ❌ offen |

---

## 10. Neue Features in Session 74

### HomeMenu (`jive.ui.homemenu`)
- Vollständiger Port von `HomeMenu.lua` (756 LOC Lua → ~1.188 LOC Python)
- Knotenbaum-Management (`add_node`, `add_item`, `add_item_to_node`)
- Ranking / manuelle Umordnung (`item_up_one`, `item_down_one`, `item_to_top`, `item_to_bottom`)
- Custom-Node-Overrides (`set_custom_node`, `set_node`, `disable_item`)
- `close_to_home()` — Window-Stack bis zum Home-Menü schließen
- Lock/Unlock (`lock_item`, `unlock_item`)
- Iterator, `open_node_by_id`, `get_complex_weight`

### Neue SimpleMenu-Komparatoren
- `item_comparator_complex_weight_alpha` — hierarchische Gewichtung (dot-separated Segmente)
- `item_comparator_rank` — manuelle Rank-basierte Sortierung
- Beide als `SimpleMenu.itemComparatorComplexWeightAlpha` / `SimpleMenu.itemComparatorRank` verfügbar

### Neue Menu-Methoden
- `set_closeable(bool)` / `is_closeable()` — "back"-Action unterdrücken
- `lock(style?)` / `unlock()` / `is_locked()` — Input-Sperre

### Neue Window-Methode
- `set_button_action(button, press, hold, long_hold, delayed)` — Button-Action-Mapping (Stub)

### Neue Framework-Methoden
- `get_action_to_action_translation(name)` — Action-Umleitungs-Lookup (Stub)
- `set_action_to_action_translation(source, target)` — Action-Umleitung setzen

### Netzwerk-Bugfixes
- `socket_base.py`: `priority` defaulted auf `PRIORITY_LOW` wenn `None` (statt Crash)
- `socket_tcp.py` / `socket_tcp_server.py`: `port=0` ist jetzt gültig (OS wählt Port)
- 26 fehlschlagende Net-Tests gefixt → alle 212 grün

---

## 11. Nächste Schritte (ab Session 75+)

### Kurzfristig (Post-M9)
- [ ] `hello_ui.py` erweitern — Textinput, Keyboard, Timeinput, HomeMenu in Demo einbauen
- [ ] Type-Checking mit mypy durchführen und Fehler beheben
- [ ] Stubs vervollständigen: `set_button_action` verdrahten, `get_action_to_action_translation` implementieren

### Mittelfristig (M10)
- [ ] Slim-Protokoll portieren (`jive.slim`)
  - [ ] `SlimServer.lua` → `jive.slim.slim_server`
  - [ ] `Player.lua` → `jive.slim.player`
  - [ ] `ArtworkCache.lua` → `jive.slim.artwork_cache`
- [ ] Applet-System portieren
  - [ ] `Applet.lua` → `jive.applet`
  - [ ] `AppletManager.lua` → `jive.applet_manager`
  - [ ] `AppletMeta.lua` → `jive.applet_meta`
- [ ] HomeMenu cm_callback mit echtem AppletManager verdrahten

### Langfristig (M11+)
- [ ] Mindestens einen Skin portieren (z.B. JogglerSkin)
- [ ] Vollständige LMS-Verbindung
- [ ] Visualizer-Support
- [ ] Packaging (pip install, standalone binary)
- [ ] CI/CD-Pipeline

---

## 12. Design-Entscheidungen (Kurzreferenz)

| Lua/C-Konzept | Python-Umsetzung |
|---|---|
| LOOP OOP (`oo.class`) | Python-Klassen mit Vererbung |
| `module(...)` | Standard-Python-Module |
| Lua Metatables (`__index`) | `_uses()` dict-Merge-Helper (für Item-Vererbung) |
| `setmetatable({}, {__index=parent})` | `dict(parent)` + Update |
| Lua Coroutines | Python Generators via `jive.ui.task.Task` |
| LuaSocket | Python `socket` stdlib |
| LTN12 source/sink | Python Callbacks / Generators |
| `socket.select()` | Python `selectors.DefaultSelector` |
| `lfs` (LuaFileSystem) | Python `pathlib` / `os` |
| `mime.b64` | Python `base64.b64encode` |
| `cjson` | Python `json` (via `jive.utils.jsonfilters`) |
| Lua `pairs(t)(t)` (has-entry-check) | Python `bool(dict)` |
| Lua 1-based arrays | Python 1-based indices für Menu/SimpleMenu API |