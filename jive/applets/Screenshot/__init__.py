"""
jive.applets.Screenshot — Screenshot applet for Jive.

Ported from ``share/jive/applets/Screenshot/`` in the original jivelite
project.

This applet captures screenshots when the user presses a key combination
(the ``take_screenshot`` action).  Screenshots are saved as BMP files
to the user directory or ``/tmp``.

The applet is resident — once loaded it cannot be freed.

Modules:

* ``ScreenshotMeta`` — Meta class that loads the applet at startup
* ``ScreenshotApplet`` — Resident applet that listens for the screenshot action

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Python port: 2025
License: BSD-3-Clause
"""

from jive.applets.Screenshot.ScreenshotApplet import ScreenshotApplet
from jive.applets.Screenshot.ScreenshotMeta import ScreenshotMeta

__all__ = [
    "ScreenshotMeta",
    "ScreenshotApplet",
]
