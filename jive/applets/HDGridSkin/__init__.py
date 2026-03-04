"""
jive.applets.HDGridSkin --- HD grid skin for 1080p displays.

Ported from ``share/jive/applets/HDGridSkin/`` in the original
jivelite project.

This package provides an HD grid skin used by jivelite on devices with
1080p resolution displays.  It is a standalone skin that builds the
complete style table from scratch (does not inherit from QVGAbaseSkin
or JogglerSkin).  It uses a grid layout for home menu and icon lists
with large thumbnails.

Modules:

* ``HDGridSkinMeta`` --- Meta class for applet registration
* ``HDGridSkinApplet`` --- Skin applet with complete style definitions

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Copyright 2013-2014 Adrian Smith (jivelite amendments)
Python port: 2025
License: BSD-3-Clause
"""

from jive.applets.HDGridSkin.HDGridSkinApplet import HDGridSkinApplet
from jive.applets.HDGridSkin.HDGridSkinMeta import HDGridSkinMeta

__all__ = ["HDGridSkinMeta", "HDGridSkinApplet"]
