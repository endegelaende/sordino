"""
jive.applets.QVGA240squareSkin --- Skin for 240x240 square displays.

Ported from ``share/jive/applets/QVGA240squareSkin/`` in the original
jivelite project.

This package provides the skin used by jivelite on devices with a
240x240 square display, such as the Pirate Audio boards for the
Raspberry Pi.  It inherits from QVGAbaseSkin and overrides a small
number of styles for the square form factor.

Modules:

* ``QVGA240squareSkinMeta`` --- Meta class for applet registration
* ``QVGA240squareSkinApplet`` --- Skin applet with style overrides

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Copyright 2013-2014 Adrian Smith (jivelite amendments)
Python port: 2025
License: BSD-3-Clause
"""

from jive.applets.QVGA240squareSkin.QVGA240squareSkinApplet import QVGA240squareSkinApplet
from jive.applets.QVGA240squareSkin.QVGA240squareSkinMeta import QVGA240squareSkinMeta

__all__ = ["QVGA240squareSkinMeta", "QVGA240squareSkinApplet"]
