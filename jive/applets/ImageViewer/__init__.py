"""
jive.applets.ImageViewer — Image Viewer / Slideshow applet package.

Ported from ``share/jive/applets/ImageViewer/`` in the original jivelite
project.

This applet provides a configurable image viewer and slideshow with
multiple image sources, transition effects, and display options:

* **Local Storage** — Browse and display images from local directories
* **SD Card** — Auto-detect and scan SD card mount points
* **USB Disk** — Auto-detect and scan USB disk mount points
* **HTTP URL List** — Fetch image URLs from a remote text file
* **Flickr** — Browse Flickr photos (obsolete, replaced by server app)
* **Server** — Receive image lists from Lyrion Music Server

Display features:

* Nine transition effects (fade, box-out, directional wipes, push)
* Configurable slide delay (5s–60s)
* Sequential or random ordering
* Auto-rotation for portrait/landscape mismatch
* Fullscreen zoom or fit-to-screen
* Optional text overlay with image metadata
* Wallpaper save functionality

Modules:

* ``ImageViewerMeta`` — Meta class for applet registration
* ``ImageViewerApplet`` — Full image viewer / slideshow applet
* ``ImageSource`` — Base class for all image sources
* ``ImageSourceLocalStorage`` — Local directory image source
* ``ImageSourceCard`` — SD card image source
* ``ImageSourceUSB`` — USB disk image source
* ``ImageSourceHttp`` — HTTP URL-list image source
* ``ImageSourceServer`` — Server-based image source
* ``ImageSourceFlickr`` — Flickr image source (obsolete)

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Python port: 2025
License: BSD-3-Clause
"""

from jive.applets.ImageViewer.ImageViewerApplet import ImageViewerApplet
from jive.applets.ImageViewer.ImageViewerMeta import ImageViewerMeta

__all__ = [
    "ImageViewerMeta",
    "ImageViewerApplet",
]
