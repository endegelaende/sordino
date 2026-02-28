"""
jive.slim — Slim protocol layer for LMS communication.

This package implements the client-side Slim protocol used by Jivelite
to communicate with Lyrion Music Server (LMS, formerly Logitech Media
Server / SlimServer / SqueezeCenter).

Modules
-------
artwork_cache
    Size-bounded LRU cache for artwork data.
slim_server
    Represents a SlimServer on the network — manages Comet connections,
    player tracking, artwork fetching, and server state.
player
    Represents a Squeezebox player — tracks playback state, playlist,
    volume, and sends commands to the server via Comet/JSON-RPC.
local_player
    Subclass of Player for locally-attached playback (e.g., the device
    running jivelite itself).

Ported from the ``jive/slim/`` directory in the original jivelite
(Lua) project:

* ``ArtworkCache.lua`` → ``artwork_cache.py``
* ``SlimServer.lua``   → ``slim_server.py``
* ``Player.lua``       → ``player.py``
* ``LocalPlayer.lua``  → ``local_player.py``

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Copyright 2013-2014 Adrian Smith (jivelite amendments)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

__all__ = [
    "ArtworkCache",
    "LocalPlayer",
    "Player",
    "SlimServer",
]


def __getattr__(name: str):
    """Lazy imports to avoid circular dependency issues."""
    if name == "ArtworkCache":
        from jive.slim.artwork_cache import ArtworkCache

        return ArtworkCache
    if name == "SlimServer":
        from jive.slim.slim_server import SlimServer

        return SlimServer
    if name == "Player":
        from jive.slim.player import Player

        return Player
    if name == "LocalPlayer":
        from jive.slim.local_player import LocalPlayer

        return LocalPlayer
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
