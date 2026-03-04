"""
jive.applets.ScreenSavers — Screensaver manager applet package.

Ported from ``share/jive/applets/ScreenSavers/`` in the original jivelite
project.

This package provides the screensaver management service for Jive:

* Screensaver registration (``addScreenSaver`` / ``removeScreenSaver``)
* Automatic activation based on idle timeout
* Mode-based screensaver selection (when playing, when stopped, when off)
* Settings UI for screensaver selection and timeout configuration
* Power-on overlay window for touch devices

Modules:

* ``ScreenSaversMeta`` — Meta class for applet registration
* ``ScreenSaversApplet`` — Full screensaver manager applet

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Python port: 2025
License: BSD-3-Clause
"""

from jive.applets.ScreenSavers.ScreenSaversApplet import ScreenSaversApplet
from jive.applets.ScreenSavers.ScreenSaversMeta import ScreenSaversMeta

__all__ = [
    "ScreenSaversMeta",
    "ScreenSaversApplet",
]
