# KONTEXT.md — Sordino

> **Zweck:** Diese Datei gibt KI-Assistenten (Cursor, Copilot, Claude, etc.)
> den nötigen Kontext, um produktiv am Projekt mitzuarbeiten.
> Wird zu Beginn jeder Session geladen.
>
> **Upstream-Repository:** <https://github.com/ralph-irving/jivelite>

---

## 1. Was ist dieses Projekt?

**Sordino** ist ein Python-3-Port von
[Jivelite](https://github.com/ralph-irving/jivelite) — der Community-UI für den
Lyrion Music Server (ehemals Logitech Media Server / Squeezebox).

- **Name:** Sordino (ital. *Dämpfer* — formt, wie der Klang beim Zuhörer ankommt)
- **Server-Gegenstück:** [Resonance](https://github.com/endegelaende/resonance-server) (LMS-kompatibler Music Server)
- **Paketname:** `sordino` (PyPI)
- **Internes Python-Package:** `jive` (Squeezebox-API-Kompatibilität)
- **Entrypoint:** `sordino` (CLI) → `jive.main:main`

Das Original ist eine C+Lua-Anwendung (SDL + LuaJIT). Sordino ersetzt
sowohl die C-Rendering-Schicht als auch die Lua-UI-Logik durch reines Python
auf Basis von **pygame** (oder pygame-ce).

### Architektur

```
┌──────────────────────────────────────────────┐
│  jive.applets.*   — 33 Python Applets        │  ← NowPlaying, Clock, Skins, …
├──────────────────────────────────────────────┤
│  jive.slim.*      — Slim-Protokoll           │  ← SlimServer, Player, Artwork
├──────────────────────────────────────────────┤
│  jive.net.*       — Netzwerk                 │  ← HTTP, Comet/Bayeux, DNS, Sockets
├──────────────────────────────────────────────┤
│  jive.ui.*        — UI-Widget-Framework      │  ← 37 Module, Rendering
├──────────────────────────────────────────────┤
│  jive.*           — Core                     │  ← JiveMain, AppletManager, …
├──────────────────────────────────────────────┤
│  pygame / pygame-ce                          │  ← SDL 2 Abstraktion
└──────────────────────────────────────────────┘
```

---

## 2. Projektstruktur

```
sordino/
├── jive/                           # Hauptpaket (~93.200 LOC Python)
│   ├── __init__.py
│   ├── applet.py                   # Applet-Basisklasse
│   ├── applet_meta.py              # AppletMeta-Basisklasse
│   ├── applet_manager.py           # Applet-Discovery, Laden, Lifecycle, Services
│   ├── jive_main.py                # JiveMain + NotificationHub + HomeMenuStub
│   ├── iconbar.py                  # Iconbar (Playmode, Repeat, Shuffle)
│   ├── input_to_action_map.py      # Key/IR/Gesture → Action Mappings
│   ├── system.py                   # System-Identität, Capabilities, Search-Paths
│   ├── debug_bridge.py             # Runtime-Diagnose (JIVELITE_DEBUG=1)
│   ├── main.py                     # CLI Entrypoint
│   │
│   ├── ui/                         # UI-Widget-Framework (37 Module)
│   │   ├── framework.py            # Framework-Singleton (Event-Loop, Window-Stack)
│   │   ├── widget.py               # Basis-Widget (Bounds, Style, Listener, Dirty)
│   │   ├── window.py               # Window (Show/Hide, Border-Layout, Transitions)
│   │   ├── menu.py                 # Menu (Items, Scrolling, Navigation)
│   │   ├── simplemenu.py           # SimpleMenu (Text + Icon + Callback)
│   │   ├── style.py                # Style/Skin-Lookup, Caching, Lazy Resolution
│   │   ├── surface.py              # pygame.Surface Wrapper
│   │   ├── label.py, icon.py       # Text- und Bild-Widgets
│   │   ├── group.py                # H/V Container
│   │   └── ...                     # 25+ weitere Module
│   │
│   ├── net/                        # Netzwerk-Layer (16 Module)
│   │   ├── comet.py                # Cometd/Bayeux Protokoll-Client
│   │   ├── socket_http.py          # HTTP Client (State Machine)
│   │   ├── network_thread.py       # Select-basierter I/O + Notification Hub
│   │   └── ...
│   │
│   ├── slim/                       # Slim-Protokoll (4 Module)
│   │   ├── slim_server.py          # SlimServer (Comet, Player-Tracking)
│   │   ├── player.py               # Player (Playback, Playlist, Commands)
│   │   └── ...
│   │
│   ├── utils/                      # Utilities (9 Module)
│   │
│   └── applets/                    # Alle 33 Applets portiert
│       ├── SlimBrowser/            # Music Browser + Volume + Scanner
│       ├── NowPlaying/             # Now-Playing Screen
│       ├── SlimMenus/              # Server-Menü-Integration
│       ├── SlimDiscovery/          # UDP Server/Player Discovery
│       ├── JogglerSkin/            # Joggler Skin (800×480)
│       ├── HDSkin/                 # HD Skin (1080p/720p/VGA)
│       └── ...                     # 27 weitere Applets & Skins
│
├── share/jive/                     # Assets (Fonts, Splash, Strings)
├── assets/                         # App-Icon (SVG, ICO, PNGs)
├── .github/workflows/
│   ├── ci.yml                      # CI (Python 3.10–3.13 × Ubuntu + Windows)
│   └── release.yml                 # Release (PyPI + Frozen Builds + GitHub Release)
├── sordino.spec                    # PyInstaller-Spec für Frozen Builds
├── pyproject.toml                  # Package-Config (setuptools, pygame-ce dep)
├── MANIFEST.in                     # sdist-Inclusions
├── LICENSE                         # BSD-3-Clause
├── CHANGELOG.md                    # Versionshistorie
├── THIRD_PARTY_NOTICES.md          # Lizenzübersicht aller Dependencies
├── KONTEXT.md                      # KI-Kontext (diese Datei)
└── README.md
```

---

## 3. Technische Konventionen

### Naming
- **Python-Methoden:** `snake_case` (kanonisch)
- **Lua-Kompatibilität:** camelCase-Aliase am Ende der Klasse (`onStage = on_stage`)
- **Applet-Dateien:** PascalCase wie im Original (`SlimBrowserApplet.py`)

### Patterns (aus dem Lua-Port)

| Lua-Pattern | Python-Äquivalent |
|---|---|
| `oo.class(Widget)` | `class Foo(Widget):` |
| `self:method()` | `self.method()` |
| `_ENV` / `module(…)` | Reguläres Python-Modul |
| `log:debug(…)` | `log.debug(…)` (stdlib `logging`) |
| Table mit 1-basiertem Index | List mit 0-basiert (aber Menu-API bleibt 1-basiert) |
| `self.player = false` | `self.player = False` (Lua-Konvention beibehalten) |
| Lua `require()` on-demand | Lazy-Import Helper (`_get_applet_manager()` etc.) |

### Notification-System

`NetworkThread.notify(method_name, *args)` ruft `notify_<method_name>()` auf
allen registrierten Subscribern auf. Signaturen müssen exakt stimmen — sonst
`TypeError` zur Laufzeit.

Wichtige Notifications:
- `playerPlaylistChange(player)` — Playlist geändert
- `playerTrackChange(player, now_playing, artwork)` — Track gewechselt
- `playerModeChange(player, mode)` — Play/Pause/Stop
- `playerLoaded(player)` — Player verbunden
- `serverConnected(server)` — Server verbunden

### Style/Skin-System

Skins definieren eine verschachtelte Dict-Struktur. Widgets traversieren
ihren Style-Path (`window → menu → item → label`) und resolven Werte
via `style_value()`, `style_tile()`, `style_font()` etc.

Lazy Refs (`_is_lazy_ref()`) werden beim ersten Zugriff aufgelöst —
z.B. Bild-Pfade zu pygame.Surface.

### Comet/Bayeux (Server-Kommunikation)

Sordino kommuniziert mit dem Server (Resonance/LMS) über das Cometd/Bayeux
Protokoll via HTTP Long-Polling:

1. `/meta/handshake` → Client-ID
2. `/meta/subscribe` → Channels abonnieren
3. `/slim/subscribe` → Status-Subscription (`status -1 10 menu:menu subscribe:600`)
4. Long-Poll-Loop: `/meta/connect` → auf Events warten

Der Server pusht Status-Updates wenn sich Playlist, Playback oder
Player-State ändern. Das `PlayerPlaylistEvent` im Resonance-Server
triggert ein Re-Execute der gespeicherten Status-Query.

---

## 4. Beziehung zu Resonance

| | Server | Client |
|---|---|---|
| **Projekt** | `resonance-server` | `sordino` |
| **Repo** | `github.com/endegelaende/resonance-server` | `github.com/endegelaende/sordino` |
| **PyPI** | `resonance-server` | `sordino` |
| **Internes Package** | `resonance` | `jive` |
| **Beschreibung** | LMS-kompatibler Music Server | JiveLite-kompatible Controller UI |

**Resonance** erzeugt den Klang, **Sordino** formt die Darstellung.

### Kommunikationsprotokoll

```
Sordino (Client)                    Resonance (Server)
     │                                     │
     │── UDP Broadcast (Port 3483) ───────>│  Discovery
     │<── TLV Response ───────────────────│
     │                                     │
     │── POST /cometd [handshake] ────────>│  Bayeux/Comet
     │<── clientId ───────────────────────│
     │                                     │
     │── POST /slim/subscribe ────────────>│  Status-Subscription
     │<── playlist + status data ─────────│
     │                                     │
     │── POST /jsonrpc.js ────────────────>│  Commands
     │   ["playlist", "clear"]             │  (play, pause, browse, etc.)
     │                                     │
     │<── Push via Long-Poll ─────────────│  PlayerPlaylistEvent
     │   (re-executed status query)        │  → Cometd re-execute
```

---

## 5. Entwicklung

### Setup

```bash
git clone https://github.com/endegelaende/sordino.git
cd sordino
python -m venv .venv && .venv\Scripts\activate  # Windows
pip install pygame-ce>=2.5.0
pip install -e ".[dev]"
```

### Starten

```bash
python jive/main.py                    # Normal
python jive/main.py --headless         # SDL Dummy (CI)
JIVELITE_DEBUG=1 python jive/main.py   # Mit Debug Bridge
```

### Tests

```bash
python -m pytest                       # Alle Tests
python -m pytest tests/test_ui.py      # Nur UI
python -m mypy jive/ --strict          # Type-Check
```

### Assets

Fonts, Skin-Images und Applet-Bilder sind direkt im Repo unter `share/jive/`
gebundelt (gleiche BSD-3-Clause-Lizenz wie JiveLite). Kein separater Clone nötig.

Search-Paths (in `jive/system.py`):
1. `sordino/jive/` (enthält `applets/` direkt)
2. `sordino/share/jive/` (Fonts, Skin-Images, Splash, globale Strings)
---

## 6. Bekannte Eigenheiten

- **`self.player = False`** — Lua-Idiom für "kein Player", nicht `None`.
  Wird an vielen Stellen via `if self.player:` geprüft.
- **1-basierte Indizes** — Menu/SimpleMenu API nutzt 1-basierte Indizes
  wie das Lua-Original. Intern 0-basiert.
- **`_assert` war ein No-Op** — In Lua war `_assert()` deaktiviert.
  Harte `assert`-Statements im Python-Code können unerwartet crashen.
  Defensiv programmieren.
- **Debounce-Timing** — Cometd Re-Execute nutzt Debounce-Delays
  (0.3s default, 1.0s stop, 1.5s jump). Bei Playlist-Mutationen
  kann der erste Push noch alte Daten enthalten.