"""
jive.applets.qvga_base_skin — Base skin for QVGA (320×240 / 240×320) screens.

Ported from ``share/jive/applets/QVGAbaseSkin/`` in the original jivelite
project.

This package provides the base skin that other QVGA-resolution skins
inherit from.  It defines the foundational style tables (fonts, colours,
padding, images, tile assets, widget layouts) for 320×240 and 240×320
displays.

Modules:

* ``qvga_base_skin_meta`` — Meta class for applet registration
* ``qvga_base_skin_applet`` — Full skin applet with style definitions

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Python port: 2025
License: BSD-3-Clause
"""

from jive.applets.QVGAbaseSkin.QVGAbaseSkinApplet import QVGAbaseSkinApplet
from jive.applets.QVGAbaseSkin.QVGAbaseSkinMeta import QVGAbaseSkinMeta

__all__ = ["QVGAbaseSkinMeta", "QVGAbaseSkinApplet"]
