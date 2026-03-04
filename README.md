<p align="center">
  <img src="share/jive/jive/app.png" alt="Sordino" width="128" height="128" />
</p>

<h1 align="center">Sordino</h1>

<p align="center">
  <strong>A JiveLite-compatible Squeezebox controller UI, rewritten in Python</strong>
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-BSD--3--Clause-blue.svg" alt="License: BSD-3-Clause" /></a>
  <img src="https://img.shields.io/badge/python-3.10%2B-3776ab.svg?logo=python&logoColor=white" alt="Python 3.10+" />
  <img src="https://img.shields.io/badge/pygame--ce-2.5%2B-00cc00.svg" alt="pygame-ce 2.5+" />
  <img src="https://img.shields.io/badge/status-alpha-orange.svg" alt="Status: Alpha" />
</p>

<p align="center">
  A complete Python 3 port of
  <a href="https://github.com/ralph-irving/jivelite">JiveLite</a>
  (C + Lua, BSD-3-Clause) — the community controller UI for the
  <a href="https://lyrion.org/">Lyrion Music Server</a>
  (formerly Logitech Media Server / Squeezebox).
  <br />
  Works with <a href="https://github.com/endegelaende/resonance-server">Resonance</a>,
  Lyrion, and any LMS-compatible server.
</p>

---

> **Disclaimer** — Sordino is a hobby project, **not affiliated with or endorsed by**
> the Lyrion / LMS project or Logitech. It is under active development, **not finished**,
> and will contain bugs. When behavior is unclear, the original JiveLite source code is
> the reference. LLMs are used extensively as a coding partner throughout development.
> Feedback and bug reports are very welcome!

---

## Table of Contents

- [Quick Start](#quick-start)
- [Architecture](#architecture)
- [Features](#features)
- [Installation Details](#installation-details)
- [Distribution](#distribution)
- [First Steps](#first-steps)
- [Project Structure](#project-structure)
- [Type Checking](#type-checking)
- [CI / CD](#ci--cd)
- [Contributing](#contributing)
- [License](#license)
- [Acknowledgments](#acknowledgments)

---

## Quick Start

**Linux / macOS:**

```bash
git clone https://github.com/endegelaende/sordino.git
cd sordino
python3 -m venv .venv
source .venv/bin/activate
pip install pygame-ce>=2.5.0
pip install -e .

# Clone JiveLite for skin images and fonts
cd .. && git clone https://github.com/ralph-irving/jivelite.git && cd sordino

sordino
```

**Windows (PowerShell):**

```powershell
git clone https://github.com/endegelaende/sordino.git
cd sordino
python -m venv .venv
.venv\Scripts\activate
pip install pygame-ce>=2.5.0
pip install -e .

# Clone JiveLite for skin images and fonts
cd .. ; git clone https://github.com/ralph-irving/jivelite.git ; cd sordino

sordino
```

Sordino discovers Lyrion / Resonance servers on the local network automatically
via UDP broadcast on port 3483. If discovery doesn't find your server, it will
appear in the "Choose Music Source" menu once the server is reachable.

→ See [First Steps](#first-steps) for what to do next.

<details>
<summary><strong>Command-line options</strong></summary>

```
usage: sordino [-h] [--headless] [--version]

Sordino — JiveLite-compatible Squeezebox controller UI

options:
  -h, --help   show this help message and exit
  --headless   Run with SDL dummy video driver (no display)
  --version    Print version and exit
```

Set `JIVELITE_DEBUG=1` in the environment for runtime diagnostics via the debug bridge.

</details>

---

## Architecture

The original JiveLite is a three-layer stack: **C** (SDL rendering, font/surface/widget
primitives), **Lua** (UI logic, applets, skins, networking), and **SDL 1.2/2**
(platform abstraction). Sordino replaces the C and Lua layers entirely with
**pure Python**, using **pygame** (or pygame-ce) as the SDL abstraction:

```
Original JiveLite                      Sordino
┌────────────────────┐                 ┌────────────────────────────────────┐
│  Lua UI Logic      │                 │  jive.applets.*   — 33 Applets    │
│  (applets, skins,  │                 ├────────────────────────────────────┤
│   networking)      │    ═══════►     │  jive.slim.*      — Slim Protocol │
├────────────────────┤   Python 3      ├────────────────────────────────────┤
│  C Rendering Layer │    port         │  jive.net.*       — Networking     │
│  (jive_surface.c,  │                 ├────────────────────────────────────┤
│   jive_font.c, …)  │                 │  jive.ui.*        — UI Toolkit    │
├────────────────────┤                 ├────────────────────────────────────┤
│  SDL 1.2           │                 │  pygame / pygame-ce (SDL 2)       │
└────────────────────┘                 └────────────────────────────────────┘
```

Communication with the music server uses the same protocol as the original:

```
Sordino (Client)                    Resonance / LMS (Server)
     │                                     │
     │── UDP Broadcast (Port 3483) ───────►│  Discovery
     │◄── TLV Response ───────────────────│
     │                                     │
     │── POST /cometd [handshake] ────────►│  Bayeux/Cometd
     │◄── clientId ───────────────────────│
     │                                     │
     │── POST /slim/subscribe ────────────►│  Status Subscription
     │◄── playlist + status data ─────────│
     │                                     │
     │── POST /jsonrpc.js ────────────────►│  Commands
     │   ["playlist","play",…]             │  (play, pause, browse, …)
     │                                     │
     │◄── Push via Long-Poll ─────────────│  Live Updates
     │   (re-executed status query)        │
```

---

## Features

### What Has Been Ported

The entire JiveLite codebase has been ported to Python — no C or Lua code remains.

| Area | Modules | Python LOC | Status |
|------|---------|------------|--------|
| UI widget toolkit (`jive/ui/`) | 37 | ~22,100 | ✅ Complete |
| Networking (`jive/net/`) | 16 | ~7,250 | ✅ Complete |
| Slim protocol (`jive/slim/`) | 4 | ~4,040 | ✅ Complete |
| Utilities (`jive/utils/`) | 9 | ~3,560 | ✅ Complete |
| Core (Applet/Manager/Main) | 7 | ~4,370 | ✅ Complete |
| **Applets** | **33** | **~51,900** | **✅ Complete** |
| **Total** | | **~93,200** | |

### Applets

All 33 applets from the original JiveLite have been ported:

- **Core:** SlimBrowser (music browser + volume + scanner), NowPlaying, SlimMenus,
  SlimDiscovery, SelectPlayer, ChooseMusicSource
- **Skins (10):** JogglerSkin (800×480), HDSkin (1080p/720p/VGA), HDGridSkin (1080p grid),
  PiGridSkin (RPi grid), QVGAbaseSkin, QVGAlandscapeSkin, QVGAportraitSkin,
  QVGA240squareSkin, WQVGAlargeSkin, WQVGAsmallSkin
- **Screensavers:** BlankScreenSaver, Clock (Analog/Digital/DotMatrix/WordClock),
  ScreenSavers manager
- **Setup:** SetupWelcome, SetupLanguage, SetupDateTime, SetupWallpaper,
  SetupAppletInstaller, SelectSkin, CustomizeHomeMenu
- **Utilities:** Screenshot, LogSettings, Quit, DesktopJive, HttpAuth, LineIn,
  ImageViewer (7 ImageSource classes)

### Compatibility

- **Servers:** [Resonance](https://github.com/endegelaende/resonance-server),
  [Lyrion Music Server](https://lyrion.org/), any LMS-compatible server
- **Protocol:** Cometd/Bayeux over HTTP long-polling, JSON-RPC, UDP broadcast discovery
- **Python:** 3.10, 3.11, 3.12, 3.13, 3.14
- **Platforms:** Windows, Linux, macOS
- **Rendering:** pygame-ce ≥ 2.5.0 (recommended) or pygame ≥ 2.5.0

---

## Installation Details

### From PyPI (recommended)

```bash
pip install sordino
```

This installs Sordino with **pygame-ce** as the default rendering backend.
The `sordino` command becomes available immediately.

> **Note:** The PyPI package includes skin images and fonts. No additional
> downloads are required for basic functionality.

### From Source (development)

```bash
git clone https://github.com/endegelaende/sordino.git
cd sordino
pip install -e ".[dev]"
```

For development, you also need the **JiveLite** repository as a sibling directory
for skin images and fonts:

```bash
cd ..
git clone https://github.com/ralph-irving/jivelite.git
```

Sordino's search-path system automatically finds assets in `../jivelite/share/jive/`
relative to the project root.

### Python Dependencies

| Package | Purpose | License |
|---------|---------|---------|
| **pygame-ce** ≥ 2.5.0 | SDL2 rendering, input, audio | LGPL-2.1 |

Optional:

| Package | Purpose | Install |
|---------|---------|---------|
| pygame (legacy) | Alternative to pygame-ce | `pip install sordino[pygame-legacy]` |
| PyInstaller ≥ 6.0 | Build frozen executables | `pip install sordino[freeze]` |

Dev:

| Package | Purpose | Install |
|---------|---------|---------|
| pytest, pytest-cov, mypy, ruff | Testing & linting | `pip install sordino[dev]` |

---

## Distribution

Sordino supports three distribution methods, mirroring the original JiveLite approach
(a portable folder with `jivelite.exe` + DLLs) while adding modern Python packaging.

### 1. PyPI — `pip install sordino`

The standard Python way. Installs the `sordino` command, pygame-ce, and all
bundled assets. Requires Python 3.10+ on the target machine.

```bash
pip install sordino
sordino
```

### 2. Portable Executable (PyInstaller)

A self-contained folder with `sordino.exe` (Windows) or `sordino` (Linux/macOS) —
**no Python installation required**. This mirrors the original JiveLite distribution
model: a flat folder you can copy anywhere and double-click to run.

```
Original JiveLite:              Sordino:
┌──────────────────────┐        ┌──────────────────────┐
│ jivelite.exe         │        │ sordino.exe          │
│ SDL.dll, lua.dll, …  │        │ python312.dll, …     │
│ lua/                 │        │ jive/                │
│ fonts/               │        │ share/jive/          │
└──────────────────────┘        └──────────────────────┘
```

```bash
# Prerequisites
pip install -e ".[freeze]"

# Bundle skin assets into jive/data/ (see "Asset Bundling" below)

# Build with the spec file
python -m PyInstaller sordino.spec --noconfirm --clean

# Result: dist/sordino/ contains everything needed to run
dist/sordino/sordino.exe         # Windows
dist/sordino/sordino             # Linux / macOS
```

The `sordino.spec` file handles all data collection automatically — applet
`.py` files, skin images, fonts, localisation strings, and wallpapers.

### 3. GitHub Releases

Pre-built portable executables for Windows, Linux, and macOS are published
as GitHub Release assets on every version tag. Download, extract, and run — no
installation needed.

### Asset Bundling

Skin images (~3,000 files, ~27 MB) come from the upstream JiveLite repository
and are not stored in the Sordino git repo. For distribution builds (wheels and
frozen executables), they must be copied into `jive/data/` first:

```bash
# Requires ../jivelite/ as a sibling directory
mkdir -p jive/data
cp -r ../jivelite/share/jive/fonts   jive/data/fonts
cp -r ../jivelite/share/jive/jive    jive/data/jive
cp -r ../jivelite/share/jive/applets jive/data/applets

# Merge local share/jive assets (overrides)
cp share/jive/fonts/*.ttf  jive/data/fonts/ 2>/dev/null || true
cp share/jive/jive/*.png   jive/data/jive/  2>/dev/null || true
cp share/jive/jive/*.txt   jive/data/jive/  2>/dev/null || true

# Remove bundled assets
# rm -rf jive/data/
```

The `jive/data/` directory is included in wheels via `pyproject.toml` package-data
globs. The release workflow (`release.yml`) performs this bundling automatically.

---

## First Steps

Once Sordino is running:

1. **Server discovery** — Sordino broadcasts UDP packets on port 3483. If a
   Lyrion Music Server or Resonance server is running on the same subnet, it
   appears automatically in the server list.

2. **Select a player** — Choose a connected Squeezebox, Squeezelite, or other
   LMS-compatible player from the player selection menu.

3. **Browse and play** — Navigate your music library, internet radio, or
   favorites. Select a track and press play.

### Headless / CI Mode

All examples and the main application support headless mode:

```bash
sordino --headless

# Or set environment variables directly
export SDL_VIDEODRIVER=dummy    # Linux / macOS
export SDL_AUDIODRIVER=dummy
```

---

## Project Structure

```
sordino/
├── jive/                           # Main package (~93,200 LOC)
│   ├── __init__.py
│   ├── main.py                     # CLI entry point
│   ├── jive_main.py                # JiveMain + NotificationHub
│   ├── applet.py                   # Applet base class
│   ├── applet_meta.py              # AppletMeta base class
│   ├── applet_manager.py           # Applet discovery & lifecycle
│   ├── iconbar.py                  # Playmode / Repeat / Shuffle bar
│   ├── input_to_action_map.py      # Key/IR/Gesture → Action mappings
│   ├── system.py                   # System identity & capabilities
│   ├── debug_bridge.py             # Runtime diagnostics (JIVELITE_DEBUG=1)
│   │
│   ├── ui/                         # UI widget framework (37 modules)
│   │   ├── framework.py            #   Event loop, window stack
│   │   ├── widget.py               #   Base widget
│   │   ├── window.py               #   Window (show/hide, transitions)
│   │   ├── menu.py                 #   Menu (items, scrolling, navigation)
│   │   ├── simplemenu.py           #   SimpleMenu (text + icon + callback)
│   │   ├── style.py                #   Style/skin lookup & caching
│   │   ├── surface.py              #   pygame.Surface wrapper
│   │   ├── font.py                 #   TTF loading & render cache
│   │   ├── tile.py                 #   9-patch tile system
│   │   ├── label.py, icon.py       #   Text and image widgets
│   │   ├── group.py                #   H/V container layout
│   │   ├── keyboard.py             #   On-screen keyboard
│   │   └── ...                     #   25 more modules
│   │
│   ├── net/                        # Networking (16 modules)
│   │   ├── comet.py                #   Cometd/Bayeux protocol client
│   │   ├── socket_http.py          #   HTTP client (state machine)
│   │   ├── network_thread.py       #   Select-based I/O coordinator
│   │   └── ...                     #   13 more modules
│   │
│   ├── slim/                       # Slim protocol (4 modules)
│   │   ├── slim_server.py          #   SlimServer (Comet, player tracking)
│   │   ├── player.py               #   Player (playback, playlist, commands)
│   │   ├── local_player.py         #   LocalPlayer
│   │   └── artwork_cache.py        #   LRU artwork cache
│   │
│   ├── utils/                      # Utilities (9 modules)
│   │
│   └── applets/                    # All 33 applets
│       ├── SlimBrowser/            #   Music browser + volume
│       ├── NowPlaying/             #   Now-playing screen
│       ├── JogglerSkin/            #   Joggler skin (800×480)
│       ├── HDSkin/                 #   HD skin (1080p/720p)
│       └── ...                     #   29 more applets
│
├── share/jive/                     # Assets (fonts, splash, strings)
├── assets/                         # App icon (SVG, ICO, PNGs)
├── .github/workflows/
│   ├── ci.yml                      # CI (test matrix + mypy)
│   └── release.yml                 # Release (PyPI + frozen builds)
│
├── sordino.spec                    # PyInstaller spec for frozen builds
├── pyproject.toml                  # Package configuration
├── MANIFEST.in                     # Source distribution inclusions
├── LICENSE                         # BSD-3-Clause
├── CHANGELOG.md                    # Version history
├── KONTEXT.md                      # AI assistant context
├── THIRD_PARTY_NOTICES.md          # Dependency licenses
└── README.md                       # ← you are here
```

---

## Running the Tests

> **Note:** The test suite is being reworked and not yet included in the repository.
> The CI pipeline currently runs **mypy strict** type-checking and an import smoke test.

```bash
# Type checking (currently the main CI check)
python -m mypy jive/ --strict
```

---

## Type Checking

The entire codebase passes **mypy strict mode**:

```bash
python -m mypy jive/ --strict
```

All functions and methods have full type annotations, including parametrized generics,
`TypeAlias` definitions, and targeted `# type: ignore[...]` comments where Lua-port
dynamic patterns require it.

---

## CI / CD

GitHub Actions runs on every push and pull request:

| Workflow | Trigger | Description |
|----------|---------|-------------|
| **CI** (`ci.yml`) | Push / PR to `main` | Test matrix (Python 3.10–3.13 × Ubuntu + Windows) + mypy strict |
| **Release** (`release.yml`) | Tag `v*` | Build wheel + sdist, frozen executables (Win/Linux/macOS), publish to PyPI, create GitHub Release |

PyPI publishing uses [Trusted Publisher](https://docs.pypi.org/trusted-publishers/)
(OIDC) — no API tokens stored in secrets.

---

## Contributing

Sordino is a hobby project and contributions are welcome!

- **Bug reports** — Open an [issue](https://github.com/endegelaende/sordino/issues)
  with steps to reproduce.
- **Pull requests** — Fork the repo, create a branch, make your changes, and open a PR.

### Code Style

- Python 3.10+ type hints throughout, `from __future__ import annotations` in every module
- PEP 8 naming (`snake_case` methods), with `camelCase` aliases for Lua API compatibility
  (e.g. `set_value()` + `setValue()`)
- Docstrings on public classes and methods
- mypy strict compliance required for all new code
- `mypy jive/ --strict` must pass

### Development Setup

```bash
git clone https://github.com/endegelaende/sordino.git
cd sordino
python -m venv .venv && .venv/bin/activate    # or .venv\Scripts\activate on Windows
pip install pygame-ce>=2.5.0
pip install -e ".[dev]"

# Clone the upstream reference repo (for fonts, images, and Lua sources)
cd .. && git clone https://github.com/ralph-irving/jivelite.git
```

---

## License

[BSD-3-Clause](LICENSE) — same as the original
[JiveLite](https://github.com/ralph-irving/jivelite) project.

> Copyright © 2010, Logitech, Inc. All rights reserved.
> Copyright © 2013–2014, Adrian Smith (triode1@btinternet).
> Copyright © 2025, Sordino Contributors.

See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for licenses of all
dependencies, bundled fonts, and skin assets.

---

## Acknowledgments

A huge thank-you to the Squeezebox community — you keep this wonderful platform alive.

- **[JiveLite](https://github.com/ralph-irving/jivelite)** by Ralph Irving — the
  original C + Lua controller that Sordino is ported from
- **[Lyrion Music Server](https://lyrion.org/)**
  ([GitHub](https://github.com/LMS-Community/slimserver)) — the server that started it all
- **[LMS Community Forums](https://forums.slimdevices.com/)** — for decades of keeping
  Squeezebox alive
- **[Resonance](https://github.com/endegelaende/resonance-server)** — modern
  LMS-compatible music server, Sordino's server counterpart
- **[pygame-ce](https://github.com/pygame-community/pygame-ce)** — the Community Edition
  of pygame that makes the SDL2 rendering possible
- **Logitech** — for creating the Squeezebox platform and open-sourcing the software
- **Adrian Smith** — for maintaining JiveLite and keeping it running on modern systems
- **GWENDESIGN / Felix Mueller** — for the grid layout code
- **justblair** — for the Joggler skin

If you have feedback, ideas, or run into bugs — please
[open an issue](https://github.com/endegelaende/sordino/issues).
Community input is what makes this project better.

---

<p align="center">
  <strong>Resonance</strong> erzeugt den Klang. <strong>Sordino</strong> formt die Darstellung.
</p>