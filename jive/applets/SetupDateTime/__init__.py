"""
jive.applets.SetupDateTime — Date & Time settings applet for Jive.

Ported from ``share/jive/applets/SetupDateTime/`` in the original jivelite
project.

This applet provides:

* Settings screens for time format (12h/24h), date format, short date
  format, and week start day (Sunday/Monday)
* Persistence of all date/time preferences
* Integration with the datetime utility module for global formatting
* Service ``setupDateTimeSettings`` for querying current settings
* Service ``setDateTimeDefaultFormats`` for resetting to locale defaults

Modules:

* ``SetupDateTimeMeta`` — Meta class that initializes datetime from
  persisted settings and registers the Date & Time menu item
* ``SetupDateTimeApplet`` — Applet that shows date/time settings UI

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Python port: 2025
License: BSD-3-Clause
"""

from jive.applets.SetupDateTime.SetupDateTimeApplet import SetupDateTimeApplet
from jive.applets.SetupDateTime.SetupDateTimeMeta import SetupDateTimeMeta

__all__ = [
    "SetupDateTimeMeta",
    "SetupDateTimeApplet",
]
