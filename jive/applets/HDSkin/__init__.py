"""
jive.applets.HDSkin --- HD skin for high-resolution displays.

Ported from ``share/jive/applets/HDSkin/`` in the original
jivelite project.

This package provides an HD skin used by jivelite on devices with
high-resolution displays.  It is a standalone skin that builds the
complete style table from scratch (does not inherit from QVGAbaseSkin
or JogglerSkin).  It supports multiple resolution variants:

* 1080p (1920x1080)
* 720p (1280x720)
* 1280x1024
* VGA (640x480)

Modules:

* ``HDSkinMeta`` --- Meta class for applet registration
* ``HDSkinApplet`` --- Skin applet with complete style definitions

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Copyright 2013-2014 Adrian Smith (jivelite amendments)
Python port: 2025
License: BSD-3-Clause
"""

from jive.applets.HDSkin.HDSkinApplet import HDSkinApplet
from jive.applets.HDSkin.HDSkinMeta import HDSkinMeta

__all__ = ["HDSkinMeta", "HDSkinApplet"]
