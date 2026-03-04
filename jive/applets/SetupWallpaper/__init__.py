"""
jive.applets.SetupWallpaper — Wallpaper selection applet for Jive.

Ported from ``share/jive/applets/SetupWallpaper/`` in the original
jivelite project.

This applet provides:

* Selection of local wallpapers (shipped with the applet)
* Downloading and caching of server-provided wallpapers
* Per-player and per-skin wallpaper persistence
* Screen-size aware wallpaper filtering

Modules:

* ``SetupWallpaperMeta`` — Meta class that registers services and
  adds the settings menu item
* ``SetupWallpaperApplet`` — Applet with wallpaper selection UI

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Python port: 2025
License: BSD-3-Clause
"""

from jive.applets.SetupWallpaper.SetupWallpaperApplet import (
    SetupWallpaperApplet,
)
from jive.applets.SetupWallpaper.SetupWallpaperMeta import SetupWallpaperMeta

__all__ = [
    "SetupWallpaperMeta",
    "SetupWallpaperApplet",
]
