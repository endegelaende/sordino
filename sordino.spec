# -*- mode: python ; coding: utf-8 -*-
# ──────────────────────────────────────────────────────────────────────────────
# sordino.spec — PyInstaller spec file for frozen Sordino builds
#
# Usage:
#   python -m PyInstaller sordino.spec
#
# The frozen build includes:
#   - The full jive package (core, ui, net, slim, utils)
#   - All 33 applets as data files (loaded dynamically via importlib)
#   - Assets from share/jive/ (skin images, fonts, splash, strings)
#   - Applet localisation strings (*/strings.txt)
#   - Wallpaper images
#
# All assets are committed directly in the repository under share/jive/.
# No external checkout or bundling step is required.
# ──────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import os
import sys
from pathlib import Path

block_cipher = None

# ──────────────────────────────────────────────────────────────────────────────
# Paths
# ──────────────────────────────────────────────────────────────────────────────

SPEC_DIR = Path(SPECPATH)  # noqa: F821 — SPECPATH is injected by PyInstaller
JIVE_DIR = SPEC_DIR / "jive"
APPLETS_DIR = JIVE_DIR / "applets"
SHARE_DIR = SPEC_DIR / "share" / "jive"

# ──────────────────────────────────────────────────────────────────────────────
# Collect data files
#
# Applets are loaded at runtime via importlib.util.spec_from_file_location(),
# NOT via normal Python imports.  PyInstaller cannot trace these, so we must
# bundle the entire applets/ tree as data files.  The .py files are included
# as data (not as hidden imports) because the applet manager loads them by
# file path, and they need to be on disk for spec_from_file_location to work.
# ──────────────────────────────────────────────────────────────────────────────

datas: list[tuple[str, str]] = []

# 1. Applet directories — every .py, strings.txt, load_priority.txt, etc.
if APPLETS_DIR.is_dir():
    for applet_dir in sorted(APPLETS_DIR.iterdir()):
        if not applet_dir.is_dir():
            continue
        if applet_dir.name.startswith(".") or applet_dir.name == "__pycache__":
            continue
        for root, _dirs, files in os.walk(applet_dir):
            # Skip __pycache__ subdirectories
            _dirs[:] = [d for d in _dirs if d != "__pycache__"]
            root_path = Path(root)
            rel = root_path.relative_to(SPEC_DIR)
            for f in files:
                if f.endswith((".pyc", ".pyo")):
                    continue
                datas.append((str(root_path / f), str(rel)))

# 2. share/jive/ assets (skin images, fonts, splash, strings)
if SHARE_DIR.is_dir():
    for root, _dirs, files in os.walk(SHARE_DIR):
        _dirs[:] = [d for d in _dirs if d != "__pycache__"]
        root_path = Path(root)
        rel = root_path.relative_to(SPEC_DIR)
        for f in files:
            datas.append((str(root_path / f), str(rel)))

# 3. Wallpaper images
wallpaper_dir = APPLETS_DIR / "SetupWallpaper" / "wallpaper"
# (Already covered by the applets walk above, but listed for clarity.)

# ──────────────────────────────────────────────────────────────────────────────
# Hidden imports
#
# The jive package itself is imported normally, so PyInstaller traces most
# of it.  But some modules are only imported inside functions (lazy imports)
# or behind TYPE_CHECKING guards.  We list them explicitly here.
# ──────────────────────────────────────────────────────────────────────────────

hiddenimports = [
    # Core
    "jive",
    "jive.applet",
    "jive.applet_meta",
    "jive.applet_manager",
    "jive.jive_main",
    "jive.iconbar",
    "jive.input_to_action_map",
    "jive.system",
    "jive.debug_bridge",
    # UI — all 37 modules (many are lazily imported)
    "jive.ui",
    "jive.ui.audio",
    "jive.ui.button",
    "jive.ui.canvas",
    "jive.ui.checkbox",
    "jive.ui.choice",
    "jive.ui.constants",
    "jive.ui.contextmenuwindow",
    "jive.ui.event",
    "jive.ui.flick",
    "jive.ui.font",
    "jive.ui.framework",
    "jive.ui.group",
    "jive.ui.homemenu",
    "jive.ui.icon",
    "jive.ui.irmenuaccel",
    "jive.ui.keyboard",
    "jive.ui.label",
    "jive.ui.menu",
    "jive.ui.numberletteraccel",
    "jive.ui.popup",
    "jive.ui.radio",
    "jive.ui.scrollaccel",
    "jive.ui.scrollwheel",
    "jive.ui.simplemenu",
    "jive.ui.slider",
    "jive.ui.snapshotwindow",
    "jive.ui.stickymenu",
    "jive.ui.style",
    "jive.ui.surface",
    "jive.ui.task",
    "jive.ui.textarea",
    "jive.ui.textinput",
    "jive.ui.tile",
    "jive.ui.timeinput",
    "jive.ui.timer",
    "jive.ui.widget",
    "jive.ui.window",
    # Net
    "jive.net",
    "jive.net.comet",
    "jive.net.comet_request",
    "jive.net.dns",
    "jive.net.http_pool",
    "jive.net.network_thread",
    "jive.net.process",
    "jive.net.request_http",
    "jive.net.request_jsonrpc",
    "jive.net.socket_base",
    "jive.net.socket_http",
    "jive.net.socket_http_queue",
    "jive.net.socket_tcp",
    "jive.net.socket_tcp_server",
    "jive.net.socket_udp",
    "jive.net.wake_on_lan",
    # Slim
    "jive.slim",
    "jive.slim.artwork_cache",
    "jive.slim.local_player",
    "jive.slim.player",
    "jive.slim.slim_server",
    # Utils
    "jive.utils",
    "jive.utils.autotable",
    "jive.utils.datetime_utils",
    "jive.utils.debug",
    "jive.utils.dumper",
    "jive.utils.jsonfilters",
    "jive.utils.locale",
    "jive.utils.log",
    "jive.utils.string_utils",
    "jive.utils.table_utils",
    # pygame-ce submodules that PyInstaller may not trace
    "pygame",
    "pygame.display",
    "pygame.event",
    "pygame.font",
    "pygame.freetype",
    "pygame.image",
    "pygame.key",
    "pygame.mixer",
    "pygame.mouse",
    "pygame.time",
    "pygame.transform",
    "pygame.draw",
    "pygame.surface",
    "pygame.rect",
    "pygame.color",
    "pygame.constants",
    # stdlib modules used dynamically
    "json",
    "email",
    "email.message",
    "http",
    "http.client",
    "importlib",
    "importlib.util",
    "importlib.metadata",
    "uuid",
    "select",
    "socket",
    "struct",
    "threading",
    "logging",
    "logging.handlers",
    "pathlib",
    "platform",
    "tempfile",
]

# ──────────────────────────────────────────────────────────────────────────────
# Analysis
# ──────────────────────────────────────────────────────────────────────────────

a = Analysis(
    [str(JIVE_DIR / "main.py")],
    pathex=[str(SPEC_DIR)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Not needed in frozen builds
        "tkinter",
        "test",
        "unittest",
        "pytest",
        "mypy",
        "ruff",
        "setuptools",
        "pip",
        "distutils",
    ],
    noarchive=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, cipher=block_cipher)

# ──────────────────────────────────────────────────────────────────────────────
# Executable
# ──────────────────────────────────────────────────────────────────────────────

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="sordino",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon=str(SPEC_DIR / "assets" / "sordino.ico") if (SPEC_DIR / "assets" / "sordino.ico").exists() else None,
)

# ──────────────────────────────────────────────────────────────────────────────
# Collect into folder
# ──────────────────────────────────────────────────────────────────────────────

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="sordino",
)
