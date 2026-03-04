# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.5.0] — 2025-06-14

### 🎉 Initial Public Release

Complete Python 3 port of [JiveLite](https://github.com/ralph-irving/jivelite)
(C + Lua) — the community controller UI for the Lyrion Music Server (formerly
Logitech Media Server / Squeezebox).

### Added

#### Core Framework
- **UI widget toolkit** — 37 modules ported from the C rendering layer and Lua
  UI logic: Widget, Window, Menu, SimpleMenu, Label, Icon, Group, Tile, Style,
  Font, Surface, Framework, Event, Timer, and 23 more.
- **Networking layer** — 16 modules: HTTP client (state machine), Cometd/Bayeux
  protocol client, JSON-RPC, TCP/UDP sockets, DNS, connection pooling, and
  select-based I/O coordinator.
- **Slim protocol** — 4 modules: SlimServer, Player, LocalPlayer, ArtworkCache.
- **Applet system** — Applet base class, AppletMeta, AppletManager with
  discovery, loading, lifecycle management, and service registry.
- **JiveMain** — Main application with NotificationHub, HomeMenu, Iconbar,
  input-to-action mapping, and System identity/capabilities.

#### Applets (all 33 ported)
- **Core:** SlimBrowser, NowPlaying, SlimMenus, SlimDiscovery, SelectPlayer,
  ChooseMusicSource.
- **Skins (10):** JogglerSkin (800×480), HDSkin (1080p/720p/VGA), HDGridSkin
  (1080p grid), PiGridSkin (800×480 grid), QVGAbaseSkin (320×240),
  QVGAlandscapeSkin, QVGAportraitSkin, QVGA240squareSkin, WQVGAlargeSkin,
  WQVGAsmallSkin.
- **Screensavers:** BlankScreenSaver, Clock (Analog/Digital/DotMatrix/WordClock),
  ScreenSavers manager.
- **Setup:** SetupWelcome, SetupLanguage, SetupDateTime, SetupWallpaper,
  SetupAppletInstaller, SelectSkin, CustomizeHomeMenu.
- **Utilities:** Screenshot, LogSettings, Quit, DesktopJive, HttpAuth, LineIn,
  ImageViewer (7 ImageSource classes).

#### Utilities
- 9 utility modules: autotable, datetime, debug, dumper, jsonfilters, locale,
  log, string, table.

#### Testing & Quality
- **4,397 tests** — all passing, zero failures.
- **mypy --strict** — zero errors across 185 source files.
- **~93,200 LOC** production code, **~41,700 LOC** tests.
- End-to-end smoke test (35 checks, 150 frames @ 30 fps).
- Live LMS connection test (41 checks against a real Lyrion Music Server).
- CI pipeline: Python 3.10–3.13 × Ubuntu + Windows.

#### Distribution
- PyPI package (`pip install sordino`) with `sordino` CLI entrypoint.
- Asset bundling — copies JiveLite skin images and fonts into `jive/data/`
  for wheel/sdist distribution (inlined in release workflow).
- Frozen executable builds via PyInstaller (Windows, Linux, macOS) matching
  the original JiveLite distribution model (inlined in release workflow).
- GitHub Actions release workflow with Trusted Publisher (PyPI) and frozen
  executable builds.

#### Documentation
- README with architecture, quick start, installation, and project structure.
- KONTEXT.md for AI assistant context.
- THIRD_PARTY_NOTICES.md with full dependency license audit.
- 9 example scripts (hello_ui, home_menu, smoke_test, now_playing_gui, etc.).

### Compatibility

- **Python:** 3.10, 3.11, 3.12, 3.13, 3.14
- **Platforms:** Windows, Linux, macOS
- **Rendering:** pygame-ce ≥ 2.5.0 (recommended) or pygame ≥ 2.5.0
- **Servers:** Resonance, Lyrion Music Server (LMS), any LMS-compatible server
- **Protocol:** Cometd/Bayeux over HTTP long-polling, JSON-RPC, UDP discovery

---

[0.5.0]: https://github.com/endegelaende/sordino/releases/tag/v0.5.0