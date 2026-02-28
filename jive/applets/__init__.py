"""
jive.applets — Built-in applets package for the Jivelite Python3 port.

This package contains the Python ports of the original Lua applets that
ship with jivelite.  Each applet lives in its own sub-package and follows
the standard Applet/AppletMeta pattern:

* ``<package>/<Name>Meta.py`` — Meta class (loaded at startup for
  registration)
* ``<package>/<Name>Applet.py`` — Full applet class (loaded on demand)

Currently ported applets:

* ``qvga_base_skin`` — Base skin for 320×240 / 240×320 screens
  (``QVGAbaseSkinApplet``, ``QVGAbaseSkinMeta``)
* ``joggler_skin`` — 800×480 landscape skin (JogglerSkin) with
  multiple resolution variants
  (``JogglerSkinApplet``, ``JogglerSkinMeta``)

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Python port: 2025
License: BSD-3-Clause
"""
