"""
jive.applets.SetupWelcome — First-run setup welcome applet.

Ported from ``share/jive/applets/SetupWelcome/`` in the original jivelite
project.

This applet manages the first-run setup flow:

1. Language selection (delegates to SetupLanguage)
2. Skin selection (delegates to SelectSkin)
3. Player selection (delegates to SelectPlayer / ChooseMusicSource)

Once setup is complete, the ``setupDone`` flag is persisted so the
wizard is not shown again on subsequent launches.

Modules:

* ``SetupWelcomeMeta`` — Meta class that triggers first-startup setup
* ``SetupWelcomeApplet`` — Applet that orchestrates the setup flow

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Python port: 2025
License: BSD-3-Clause
"""

from jive.applets.SetupWelcome.SetupWelcomeApplet import SetupWelcomeApplet
from jive.applets.SetupWelcome.SetupWelcomeMeta import SetupWelcomeMeta

__all__ = [
    "SetupWelcomeMeta",
    "SetupWelcomeApplet",
]
