"""
jive.applets.QVGAlandscapeSkin --- Skin for 320x240 landscape displays.

Ported from ``share/jive/applets/QVGAlandscapeSkin/`` in the original
jivelite project.

This package provides the skin used by jivelite on devices with a
320x240 landscape display, such as the Squeezebox Controller.  It
inherits from QVGAbaseSkin and overrides a small number of styles for
the landscape form factor.

Modules:

* ``QVGAlandscapeSkinMeta`` --- Meta class for applet registration
* ``QVGAlandscapeSkinApplet`` --- Skin applet with style overrides

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Copyright 2013-2014 Adrian Smith (jivelite amendments)
Python port: 2025
License: BSD-3-Clause
"""

from jive.applets.QVGAlandscapeSkin.QVGAlandscapeSkinApplet import (
    QVGAlandscapeSkinApplet,
)
from jive.applets.QVGAlandscapeSkin.QVGAlandscapeSkinMeta import QVGAlandscapeSkinMeta

__all__ = ["QVGAlandscapeSkinMeta", "QVGAlandscapeSkinApplet"]
