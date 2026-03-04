"""
jive.applets.ImageViewer.ImageSourceCard — SD card image source.

Ported from ``share/jive/applets/ImageViewer/ImageSourceCard.lua``
(~55 LOC) in the original jivelite project.

Extends ``ImageSourceLocalStorage`` to scan for images on an SD card
mounted under ``/media/mmc*``.  The mount point is discovered by
parsing ``/proc/mounts``.

Features:

* Auto-detection of SD card mount point via ``/proc/mounts``
* Falls back to ``/media`` if no mount point is found
* Overrides ``get_folder()`` to locate the SD card path
* Overrides ``settings()`` to pre-populate the path with the
  discovered mount point before delegating to the parent class

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING, Any, Optional

from jive.applets.ImageViewer.ImageSourceLocalStorage import ImageSourceLocalStorage
from jive.utils.log import logger

if TYPE_CHECKING:
    from jive.applet import Applet

__all__ = ["ImageSourceCard"]

log = logger("applet.ImageViewer")


class ImageSourceCard(ImageSourceLocalStorage):
    """Image source that reads images from an SD card.

    Discovers the SD card mount point by scanning ``/proc/mounts``
    for entries matching ``/media/mmc*``.

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
        """Return the SD card mount point, or fall back to settings.

        Scans ``/proc/mounts`` for a line matching the pattern
        ``/media/mmc*`` and returns the first valid directory found.

        If the caller provided a ``path_override``, that takes
        precedence (handled by the parent class).
        """
        if self.path_override:
            return self.path_override

        return self._get_folder(r"(/media/mmc\w*)")

    def _get_folder(self, pattern: str) -> Optional[str]:
        """Scan ``/proc/mounts`` for a mount point matching *pattern*.

        Parameters
        ----------
        pattern : str
            A regex pattern with one capture group for the mount point
            path, e.g. ``r"(/media/mmc\\w*)"``.

        Returns
        -------
        str or None
            The first matching mount point that is a directory, or
            ``None`` if nothing is found.

        Side effects
        ------------
        Updates the applet's ``card.path`` setting when a mount point
        is discovered.
        """
        mounts_path = "/proc/mounts"
        path: Optional[str] = None

        try:
            with open(mounts_path, "r") as mounts:
                compiled = re.compile(pattern)
                for line in mounts:
                    m = compiled.search(line)
                    if m:
                        mount_point = m.group(1)
                        if os.path.isdir(mount_point):
                            log.debug("Mounted drive found at %s", mount_point)
                            settings = (
                                self.applet.get_settings()
                                if hasattr(self.applet, "get_settings")
                                else None
                            )
                            if settings is not None:
                                settings["card.path"] = mount_point
                            path = mount_point
                            break
        except OSError:
            log.error("/proc/mounts could not be opened")
            return None

        return path

    # ------------------------------------------------------------------
    # Settings UI override
    # ------------------------------------------------------------------

    def settings(self, window: Any) -> Any:
        """Pre-populate the card path from the detected mount point,
        then delegate to the parent's settings UI.

        If the user decides to change the path manually, the source
        mode is switched to ``"card"`` with the detected media as
        the default path.
        """
        imgpath = self.get_folder() or "/media"

        settings = (
            self.applet.get_settings() if hasattr(self.applet, "get_settings") else None
        )
        if settings is not None:
            settings["card.path"] = imgpath

        return super().settings(window)

    # ------------------------------------------------------------------
    # Lua-compatible camelCase aliases
    # ------------------------------------------------------------------

    getFolder = get_folder
