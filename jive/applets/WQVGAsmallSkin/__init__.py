"""
jive.applets.WQVGAsmallSkin --- Skin for 480x272 small-print displays.

Ported from ``share/jive/applets/WQVGAsmallSkin/`` in the original
jivelite project.

This package provides a small-print skin used by jivelite on devices
with a 480x272 resolution display.  It is a standalone skin that builds
the complete style table from scratch (does not inherit from
QVGAbaseSkin or JogglerSkin).

Modules:

* ``WQVGAsmallSkinMeta`` --- Meta class for applet registration
* ``WQVGAsmallSkinApplet`` --- Skin applet with complete style definitions

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Copyright 2013-2014 Adrian Smith (jivelite amendments)
Python port: 2025
License: BSD-3-Clause
"""

from jive.applets.WQVGAsmallSkin.WQVGAsmallSkinApplet import WQVGAsmallSkinApplet
from jive.applets.WQVGAsmallSkin.WQVGAsmallSkinMeta import WQVGAsmallSkinMeta

__all__ = ["WQVGAsmallSkinMeta", "WQVGAsmallSkinApplet"]
