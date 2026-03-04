"""
jive.applets.ImageViewer.ImageSourceUSB — USB disk image source.

Ported from ``share/jive/applets/ImageViewer/ImageSourceUSB.lua``
(~25 LOC) in the original jivelite project.

Extends ``ImageSourceCard`` to scan for images on a USB disk
mounted under ``/media/sd*``.  The only difference from the SD card
source is the mount-point pattern used when searching ``/proc/mounts``.

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from jive.applets.ImageViewer.ImageSourceCard import ImageSourceCard
from jive.utils.log import logger

if TYPE_CHECKING:
    from jive.applet import Applet

__all__ = ["ImageSourceUSB"]

log = logger("applet.ImageViewer")


class ImageSourceUSB(ImageSourceCard):
    """Image source that reads images from a USB disk.

    Discovers the USB disk mount point by scanning ``/proc/mounts``
    for entries matching ``/media/sd*``.

    Parameters
    ----------
    applet : Applet
        The owning ImageViewerApplet instance.
    param_override : dict, optional
        Override parameters forwarded to the parent class.
    """

    def __init__(
        self,
        applet: "Applet",
        param_override: Optional[Dict[str, Any]] = None,  # type: ignore[name-defined]
    ) -> None:
        super().__init__(applet, param_override)

    # ------------------------------------------------------------------
    # Mount-point discovery
    # ------------------------------------------------------------------

    def get_folder(self) -> Optional[str]:
        """Return the USB disk mount point.

        Scans ``/proc/mounts`` for a line matching the pattern
        ``/media/sd*`` and returns the first valid directory found.

        If the caller provided a ``path_override``, that takes
        precedence.
        """
        if self.path_override:
            return self.path_override

        return self._get_folder(r"(/media/sd\w*)")

    # ------------------------------------------------------------------
    # Lua-compatible camelCase aliases
    # ------------------------------------------------------------------

    getFolder = get_folder
