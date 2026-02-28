"""
jive.applets.now_playing — NowPlaying applet package.

Ported from ``share/jive/applets/NowPlaying/`` in the original jivelite
project.

This package provides the Now Playing screen that displays the currently
playing track with artwork, transport controls, progress bar, volume
slider, and multiple view styles (artwork, spectrum, VU meter, etc.).

Modules:

* ``now_playing_meta`` — Meta class for applet registration
* ``now_playing_applet`` — Full NowPlaying applet with UI and controls

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Python port: 2025
License: BSD-3-Clause
"""

from jive.applets.NowPlaying.NowPlayingApplet import NowPlayingApplet

from jive.applets.NowPlaying.NowPlayingMeta import NowPlayingMeta

__all__ = [
    "NowPlayingMeta",
    "NowPlayingApplet",
]
