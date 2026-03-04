"""
jive.applets.SetupLanguage — Language selection applet for Jive.

Ported from ``share/jive/applets/SetupLanguage/`` in the original jivelite
project.

This applet provides:

* A first-run language selection screen (used by the SetupWelcome wizard)
* A settings menu for changing the language at any time
* Persistence of the selected locale

The applet manages the locale system, loading all available translations
and applying the selected language globally.

Modules:

* ``SetupLanguageMeta`` — Meta class that registers the language menu item
  and initializes the current locale from settings
* ``SetupLanguageApplet`` — Applet that shows language selection UI

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Python port: 2025
License: BSD-3-Clause
"""

from jive.applets.SetupLanguage.SetupLanguageApplet import SetupLanguageApplet
from jive.applets.SetupLanguage.SetupLanguageMeta import SetupLanguageMeta

__all__ = [
    "SetupLanguageMeta",
    "SetupLanguageApplet",
]
