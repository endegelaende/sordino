"""
jive.applets.select_player — SelectPlayer applet package.

Ported from ``share/jive/applets/SelectPlayer/`` in the original jivelite
project.

This package provides the player selection screen that displays all
available Squeezebox players on the network and allows the user to
choose which player to control.

Modules:

* ``select_player_meta`` — Meta class for applet registration
* ``select_player_applet`` — Full SelectPlayer applet with UI

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Python port: 2025
License: BSD-3-Clause
"""

from jive.applets.SelectPlayer.SelectPlayerApplet import SelectPlayerApplet
from jive.applets.SelectPlayer.SelectPlayerMeta import SelectPlayerMeta

__all__ = [
    "SelectPlayerMeta",
    "SelectPlayerApplet",
]
