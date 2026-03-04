"""
jive.applets.PiGridSkin -- Grid skin for 800x480 landscape screens.

Ported from ``share/jive/applets/PiGridSkin/`` in the original jivelite
project.

This package provides a grid-layout skin that inherits from JogglerSkin.
It overrides icon list and home menu styles to display items in a grid
format.  It supports multiple resolution variants:

* 800x480 (default)
* 1024x600
* 1280x800
* 1366x768
* Custom (via ``JL_SCREEN_WIDTH`` / ``JL_SCREEN_HEIGHT`` env vars)

Modules:

* ``PiGridSkinMeta`` -- Meta class for applet registration
* ``PiGridSkinApplet`` -- Grid skin applet with style definitions

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Copyright 2013-2014 Adrian Smith (jivelite amendments)
Version 1.1 (25th January 2017) Michael Herger
Python port: 2025
License: BSD-3-Clause
"""

from jive.applets.PiGridSkin.PiGridSkinApplet import PiGridSkinApplet
from jive.applets.PiGridSkin.PiGridSkinMeta import PiGridSkinMeta

__all__ = ["PiGridSkinMeta", "PiGridSkinApplet"]
