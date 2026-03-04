"""
jive.applets.SetupAppletInstaller — Applet Installer for Jive.

Ported from ``share/jive/applets/SetupAppletInstaller/`` in the original
jivelite project.

This applet provides:

* A menu for browsing available third-party applets from connected
  SqueezeCenter servers
* Install, update, reinstall, and remove functionality for applets
* SHA1 verification of downloaded applet archives
* Automatic reinstall of previously-installed applets after a
  firmware / application version upgrade (optional, user-configurable)

Modules:

* ``SetupAppletInstallerMeta`` — Meta class that registers the Applet
  Installer menu item and handles auto-reinstall on version upgrade
* ``SetupAppletInstallerApplet`` — Applet that queries servers, presents
  available applets, and handles download/extraction/removal

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Python port: 2025
License: BSD-3-Clause
"""

from jive.applets.SetupAppletInstaller.SetupAppletInstallerApplet import (
    SetupAppletInstallerApplet,
)
from jive.applets.SetupAppletInstaller.SetupAppletInstallerMeta import (
    SetupAppletInstallerMeta,
)

__all__ = [
    "SetupAppletInstallerMeta",
    "SetupAppletInstallerApplet",
]
