"""
jive.applets.HttpAuth — HTTP authentication applet for Jive.

Ported from ``share/jive/applets/HttpAuth/`` in the original jivelite
project.

This applet provides:

* Username/password input for password-protected Lyrion Music Server
* Credential storage per server UUID
* Connection monitoring with timeout
* Authentication error handling with retry

Modules:

* ``HttpAuthMeta`` — Meta class that registers the squeezeCenterPassword
  service and restores saved credentials on startup
* ``HttpAuthApplet`` — Applet that provides the authentication UI flow

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Python port: 2025
License: BSD-3-Clause
"""

from jive.applets.HttpAuth.HttpAuthApplet import HttpAuthApplet
from jive.applets.HttpAuth.HttpAuthMeta import HttpAuthMeta

__all__ = [
    "HttpAuthMeta",
    "HttpAuthApplet",
]
