"""
jive.applets.Quit — Quit applet for Jive.

Ported from ``share/jive/applets/Quit/`` in the original jivelite project.

This applet adds a "Quit" menu item to the home menu that disconnects
from the current player/server and exits the application.

Note: The original Lua applet has no ``QuitApplet.lua`` — all logic
lives in ``QuitMeta.lua``'s ``configureApplet()`` method, which adds
a home menu item with an inline callback.  The Python port follows
the same pattern.

Modules:

* ``QuitMeta`` — Meta class that registers the Quit menu item

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Python port: 2025
License: BSD-3-Clause
"""

from jive.applets.Quit.QuitMeta import QuitMeta

__all__ = [
    "QuitMeta",
]
