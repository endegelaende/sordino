"""
jive.applets.SelectSkin — SelectSkin applet package.

Ported from ``share/jive/applets/SelectSkin/`` in the original jivelite
project.

This package provides the skin selection screen that displays all
registered skins and allows the user to choose which skin to use.
On hardware devices with touch support, separate skins can be
configured for touch and remote control modes.

Modules:

* ``SelectSkinMeta`` — Meta class for applet registration
* ``SelectSkinApplet`` — Full SelectSkin applet with UI

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Python port: 2025
License: BSD-3-Clause
"""

from jive.applets.SelectSkin.SelectSkinApplet import SelectSkinApplet
from jive.applets.SelectSkin.SelectSkinMeta import SelectSkinMeta

__all__ = [
    "SelectSkinMeta",
    "SelectSkinApplet",
]
