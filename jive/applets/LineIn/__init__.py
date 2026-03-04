"""
jive.applets.LineIn — Line-In audio source applet for Jive.

Ported from ``share/jive/applets/LineIn/`` in the original jivelite project.

This applet manages the Line In audio source on devices that support it.
It provides:

* A home menu checkbox item to enable/disable line-in
* A NowPlaying-style window when line-in is active
* Play/pause/stop action listeners during line-in capture
* Integration with screensaver and NowPlaying services

Modules:

* ``LineInMeta`` — Meta class that registers services and adds menu item
* ``LineInApplet`` — Resident applet with line-in management

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Python port: 2025
License: BSD-3-Clause
"""

from jive.applets.LineIn.LineInApplet import LineInApplet
from jive.applets.LineIn.LineInMeta import LineInMeta

__all__ = [
    "LineInMeta",
    "LineInApplet",
]
