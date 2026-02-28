"""
jive.applets.joggler_skin — JogglerSkin for 800×480 landscape screens.

Ported from ``share/jive/applets/JogglerSkin/`` in the original jivelite
project.

This package provides the main skin used by jivelite on devices with
800×480 or similar landscape screens (Joggler, Raspberry Pi with 7"
display, etc.).  It supports multiple resolution variants:

* 800×480 (default)
* 1024×600
* 1280×800
* 1366×768
* Custom (via ``JL_SCREEN_WIDTH`` / ``JL_SCREEN_HEIGHT`` env vars)

Modules:

* ``joggler_skin_meta`` — Meta class for applet registration
* ``joggler_skin_applet`` — Full skin applet with style definitions

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Copyright 2013-2014 Adrian Smith (jivelite amendments)
Redesigned by Andy Davison (birdslikewires.co.uk)
Python port: 2025
License: BSD-3-Clause
"""

from jive.applets.JogglerSkin.JogglerSkinApplet import JogglerSkinApplet
from jive.applets.JogglerSkin.JogglerSkinMeta import JogglerSkinMeta

__all__ = ["JogglerSkinMeta", "JogglerSkinApplet"]
