"""
jive.applets.Clock — Clock screensaver applet package.

Ported from ``share/jive/applets/Clock/`` in the original jivelite
project.

This applet provides multiple clock screensaver modes:

* **Analog Clock** — Traditional analog clock with rotating hands
* **Digital Clock** — Large digit display with date bar (normal, black,
  transparent variants)
* **Dot Matrix Clock** — Dot-matrix style digit display
* **Word Clock** — English word-based time display ("IT IS NEARLY
  FIVE PAST THREE")

Each mode is registered as a separate screensaver via the ScreenSavers
service during ``configure_applet()``.

Modules:

* ``ClockMeta`` — Meta class for applet registration
* ``ClockApplet`` — Full clock screensaver applet with all modes

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Python port: 2025
License: BSD-3-Clause
"""

from jive.applets.Clock.ClockApplet import ClockApplet
from jive.applets.Clock.ClockMeta import ClockMeta

__all__ = [
    "ClockMeta",
    "ClockApplet",
]
