"""
jive.applets.WQVGAlargeSkin --- Skin for 480x272 large-print displays.

Ported from ``share/jive/applets/WQVGAlargeSkin/`` in the original
jivelite project.

This package provides a large-print skin used by jivelite on devices
with a 480x272 resolution display.  It is a standalone skin that builds
the complete style table from scratch (does not inherit from
QVGAbaseSkin or JogglerSkin).  It uses larger fonts and fewer items
per screen than WQVGAsmallSkin.

Modules:

* ``WQVGAlargeSkinMeta`` --- Meta class for applet registration
* ``WQVGAlargeSkinApplet`` --- Skin applet with complete style definitions

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Copyright 2013-2014 Adrian Smith (jivelite amendments)
Python port: 2025
License: BSD-3-Clause
"""

from jive.applets.WQVGAlargeSkin.WQVGAlargeSkinApplet import WQVGAlargeSkinApplet
from jive.applets.WQVGAlargeSkin.WQVGAlargeSkinMeta import WQVGAlargeSkinMeta

__all__ = ["WQVGAlargeSkinMeta", "WQVGAlargeSkinApplet"]
