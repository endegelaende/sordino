"""
jive.applets.slim_browser — SlimBrowser applet package.

Ported from ``share/jive/applets/SlimBrowser/`` in the original jivelite
project.

This package provides the main music browser for Jive/jivelite. It
manages server-driven menu browsing, playlist display, volume popup,
track position scanner, and all transport-control action handling.

Modules:

* ``db`` — Item database for browsing data (sparse chunked storage)
* ``scanner`` — Track position scanner popup
* ``volume`` — Player volume popup handler
* ``slim_browser_meta`` — Meta class for applet registration
* ``slim_browser_applet`` — Full browser applet with action handling

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Python port: 2025
License: BSD-3-Clause
"""

from jive.applets.SlimBrowser.db import DB
from jive.applets.SlimBrowser.scanner import Scanner
from jive.applets.SlimBrowser.SlimBrowserApplet import SlimBrowserApplet
from jive.applets.SlimBrowser.SlimBrowserMeta import SlimBrowserMeta
from jive.applets.SlimBrowser.volume import Volume

__all__ = [
    "DB",
    "Scanner",
    "Volume",
    "SlimBrowserApplet",
    "SlimBrowserMeta",
]
