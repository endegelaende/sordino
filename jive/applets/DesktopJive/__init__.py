"""
jive.applets.DesktopJive — Desktop platform initialization applet.

Ported from ``share/jive/applets/DesktopJive/`` in the original jivelite
project.

This is a meta-only applet (no ``DesktopJiveApplet``).  Its Meta class:

* Generates and persists a random UUID and MAC address for the desktop instance
* Initializes :class:`jive.System` with the MAC and UUID
* Sets platform capabilities (powerKey, muteKey, alarmKey, networking, etc.)
* Sets the default skin to ``HDSkin-VGA``
* Registers a ``soft_reset`` action listener that returns to the home menu
* Has ``loadPriority = 1`` so it runs before most other applets

Modules:

* ``DesktopJiveMeta`` — Meta class for platform initialization

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Python port: 2025
License: BSD-3-Clause
"""

from jive.applets.DesktopJive.DesktopJiveMeta import DesktopJiveMeta

__all__ = [
    "DesktopJiveMeta",
]
