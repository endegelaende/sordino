"""
jive.applets.BlankScreenSaver — Display Off / Blank Screen screensaver.

Ported from ``share/jive/applets/BlankScreenSaver/`` in the original jivelite
project.

This applet provides a simple screensaver that blanks the screen
(fills it with black) and optionally disables display updates to
save power.  It registers itself as a screensaver via the
ScreenSavers service.

Modules:

* ``BlankScreenSaverMeta`` — Meta class for applet registration
* ``BlankScreenSaverApplet`` — Blank screen screensaver applet

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Python port: 2025
License: BSD-3-Clause
"""

from jive.applets.BlankScreenSaver.BlankScreenSaverApplet import BlankScreenSaverApplet
from jive.applets.BlankScreenSaver.BlankScreenSaverMeta import BlankScreenSaverMeta

__all__ = [
    "BlankScreenSaverMeta",
    "BlankScreenSaverApplet",
]
