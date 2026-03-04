"""
jive.applets.LogSettings — Log settings applet for Jive.

Ported from ``share/jive/applets/LogSettings/`` in the original jivelite
project.

This applet provides a UI for viewing and changing the verbosity level
of log categories at runtime.  Changes are persisted to ``logconf.lua``
(or a Python equivalent) in the user directory.

Modules:

* ``LogSettingsMeta`` — Meta class that adds the Debug Log menu item
* ``LogSettingsApplet`` — Applet that shows log category controls

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Python port: 2025
License: BSD-3-Clause
"""

from jive.applets.LogSettings.LogSettingsApplet import LogSettingsApplet
from jive.applets.LogSettings.LogSettingsMeta import LogSettingsMeta

__all__ = [
    "LogSettingsMeta",
    "LogSettingsApplet",
]
