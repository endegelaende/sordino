"""
jive.applets.CustomizeHomeMenu — Home menu customization applet for Jive.

Ported from ``share/jive/applets/CustomizeHomeMenu/`` in the original
jivelite project.

This applet provides:

* Context menu on home menu items for show/hide/reorder
* Settings menu for restoring defaults and hidden items
* Persistent storage of menu item ordering per node

Modules:

* ``CustomizeHomeMenuMeta`` — Meta class that registers the service
  and restores custom node assignments from settings
* ``CustomizeHomeMenuApplet`` — Applet with the customization UI

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Python port: 2025
License: BSD-3-Clause
"""

from jive.applets.CustomizeHomeMenu.CustomizeHomeMenuApplet import (
    CustomizeHomeMenuApplet,
)
from jive.applets.CustomizeHomeMenu.CustomizeHomeMenuMeta import (
    CustomizeHomeMenuMeta,
)

__all__ = [
    "CustomizeHomeMenuMeta",
    "CustomizeHomeMenuApplet",
]
