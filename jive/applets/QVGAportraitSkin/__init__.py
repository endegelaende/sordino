"""
jive.applets.QVGAportraitSkin --- Skin for 240x320 portrait displays.

Ported from ``share/jive/applets/QVGAportraitSkin/`` in the original
jivelite project.

This package provides the skin used by jivelite on devices with a
240x320 portrait display, such as the Squeezebox Controller in portrait
orientation.  It inherits from QVGAbaseSkin and overrides styles for
the portrait form factor.

Modules:

* ``QVGAportraitSkinMeta`` --- Meta class for applet registration
* ``QVGAportraitSkinApplet`` --- Skin applet with style overrides

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Copyright 2013-2014 Adrian Smith (jivelite amendments)
Python port: 2025
License: BSD-3-Clause
"""

from jive.applets.QVGAportraitSkin.QVGAportraitSkinApplet import (
    QVGAportraitSkinApplet,
)
from jive.applets.QVGAportraitSkin.QVGAportraitSkinMeta import QVGAportraitSkinMeta

__all__ = ["QVGAportraitSkinMeta", "QVGAportraitSkinApplet"]
