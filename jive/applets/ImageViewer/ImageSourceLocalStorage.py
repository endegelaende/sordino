"""
jive.applets.ImageViewer.ImageSourceLocalStorage — Local storage image source.

Ported from ``share/jive/applets/ImageViewer/ImageSourceLocalStorage.lua``
(~175 LOC) in the original jivelite project.

Scans a local directory (recursively) for image files (JPEG, PNG, BMP,
GIF) and serves them as an image source for the Image Viewer applet.

Features:

* Recursive directory scanning with a 1000-image cap
* Supports caller-provided path override and start-image selection
* Optional non-recursive mode (``no_recursion``)
* Settings UI with a text-input keyboard for the folder path
* Loads images from the local filesystem via ``Surface.load_image``

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, List, Optional

from jive.applets.ImageViewer.ImageSource import ImageSource
from jive.utils.log import logger

if TYPE_CHECKING:
    from jive.applet import Applet

__all__ = ["ImageSourceLocalStorage"]

log = logger("applet.ImageViewer")

# Supported image file extensions (case-insensitive)
_IMAGE_PATTERN = re.compile(r"\.(jpe?g|png|bmp|gif)$", re.IGNORECASE)

# Maximum number of images to collect during a scan
_MAX_IMAGES = 1000


class ImageSourceLocalStorage(ImageSource):
    """Image source that reads images from local storage.

    Parameters
    ----------
    applet : Applet
        The owning ImageViewerApplet instance.
    param_override : dict, optional
        Override parameters:

        * ``path`` — Force a specific directory path instead of using
          the applet's ``card.path`` setting.
        * ``startImage`` — Filename of the image to start with.
        * ``noRecursion`` — If truthy, do not recurse into
          subdirectories.
    """

    def __init__(
        self,
        applet: "Applet",
        param_override: Optional[Dict[str, Any]] = None,  # type: ignore[name-defined]
    ) -> None:
        log.debug("initialize ImageSourceLocalStorage")
        super().__init__(applet)

        self.img_files: List[str] = []
        self.scanning: bool = False
        self._task: Any = None

        # Caller-provided overrides
        self.path_override: Optional[str] = None
        self.start_image: Optional[str] = None
        self.no_recursion: bool = False

        if param_override:
            if param_override.get("path"):
                log.debug(
                    "overriding configured image path: %s", param_override["path"]
                )
                self.path_override = param_override["path"]

            if param_override.get("startImage"):
                log.debug(
                    "start slideshow with image: %s", param_override["startImage"]
                )
                self.start_image = param_override["startImage"]

            if param_override.get("noRecursion"):
                log.debug("don't search subfolders")
                self.no_recursion = True

    # ------------------------------------------------------------------
    # Error popup
    # ------------------------------------------------------------------

    def list_not_ready_error(self) -> Any:
        """Show an error popup specific to local-storage sources."""
        return self.popup_message(
            self.applet.string("IMAGE_VIEWER_ERROR"),
            self.applet.string("IMAGE_VIEWER_CARD_ERROR"),
        )

    # ------------------------------------------------------------------
    # Directory scanning
    # ------------------------------------------------------------------

    def scan_folder(self, folder: str) -> None:
        """Scan *folder* for image files.

        Mirrors the Lua ``scanFolder`` which uses a cooperative Task
        to avoid blocking the UI.  In this Python port the scan is
        performed synchronously (but capped at ``_MAX_IMAGES``).

        Directories starting with a dot are skipped.  The scan is
        breadth-first: directories discovered during iteration are
        appended to the work-list and processed in turn.
        """
        if self.scanning:
            return

        self.scanning = True

        try:
            dirs_to_scan: List[str] = [folder]
            dirs_scanned: Set[str] = set()  # type: ignore[name-defined]

            while dirs_to_scan:
                next_folder = dirs_to_scan.pop(0)

                if next_folder in dirs_scanned:
                    continue
                dirs_scanned.add(next_folder)

                try:
                    entries = sorted(os.listdir(next_folder))
                except OSError as exc:
                    log.warn("Cannot list directory %s: %s", next_folder, exc)
                    continue

                for f in entries:
                    # Skip hidden files/directories (dot-prefix)
                    if f.startswith("."):
                        continue

                    fullpath = os.path.join(next_folder, f)

                    try:
                        if os.path.isdir(fullpath):
                            if not self.no_recursion:
                                dirs_to_scan.append(fullpath)

                        elif os.path.isfile(fullpath):
                            if _IMAGE_PATTERN.search(fullpath):
                                self.img_files.append(fullpath)

                                # If a start image was specified, track
                                # its position so we begin there.
                                if self.start_image and self.start_image == f:
                                    self.current_image = len(self.img_files) - 1
                    except OSError as exc:
                        log.debug("Cannot stat %s: %s", fullpath, exc)

                    if len(self.img_files) >= _MAX_IMAGES:
                        log.warn(
                            "we're not going to show more than %d pictures - stop here",
                            _MAX_IMAGES,
                        )
                        break

                if len(self.img_files) >= _MAX_IMAGES:
                    break
        finally:
            self.scanning = False

    # ------------------------------------------------------------------
    # ImageSource overrides
    # ------------------------------------------------------------------

    def read_image_list(self) -> None:
        """Scan the configured folder for images."""
        imgpath = self.get_folder()
        if imgpath is None:
            return

        try:
            if os.path.isdir(imgpath):
                self.scan_folder(imgpath)
        except OSError as exc:
            log.warn("Cannot access path %s: %s", imgpath, exc)

    def get_folder(self) -> Optional[str]:
        """Return the folder path to scan for images.

        Uses the caller-provided ``path_override`` if set, otherwise
        falls back to the applet's ``card.path`` setting.
        """
        if self.path_override:
            return self.path_override

        settings = (
            self.applet.get_settings() if hasattr(self.applet, "get_settings") else None
        )
        if settings and "card.path" in settings:
            return settings["card.path"]  # type: ignore[no-any-return]
        return None

    def get_image(self) -> Any:
        """Load and return the current image from the filesystem."""
        if 0 <= self.current_image < len(self.img_files):
            filepath = self.img_files[self.current_image]
            log.info("Next image in queue: %s", filepath)
            try:
                from jive.ui.surface import Surface

                return Surface.load_image(filepath)
            except Exception as exc:
                log.warn("Failed to load image %s: %s", filepath, exc)
                return None
        return None

    def next_image(self, ordering: str = "sequential") -> None:
        """Advance to the next image and mark as ready."""
        super().next_image(ordering)
        self.img_ready = True

    def previous_image(self, ordering: str = "sequential") -> None:
        """Go back to the previous image and mark as ready."""
        super().previous_image(ordering)
        self.img_ready = True

    def list_ready(self) -> bool:
        """Return ``True`` if we have at least one image."""
        if len(self.img_files) > 0:
            return True

        self.read_image_list()
        return False

    def get_error_message(self) -> str:
        """Return an error message — the current image path or a
        generic directory-not-found string."""
        path = self.get_current_image_path()
        if path:
            return path
        return str(self.applet.string("IMAGE_VIEWER_CARD_NOT_DIRECTORY"))

    # ------------------------------------------------------------------
    # Settings UI
    # ------------------------------------------------------------------

    def settings(self, window: Any) -> Any:
        """Add a text-input keyboard for the image folder path.

        Mirrors the Lua ``settings`` which creates a ``Textinput`` +
        ``Keyboard`` group for the user to enter a directory path.
        """
        settings = (
            self.applet.get_settings() if hasattr(self.applet, "get_settings") else None
        )
        imgpath = (settings or {}).get("card.path", "/media")

        try:
            from jive.ui.group import Group
            from jive.ui.keyboard import Keyboard
            from jive.ui.textinput import Textinput
            from jive.ui.window import Window

            applet = self.applet

            def _on_accept(_widget: Any, value: str) -> bool:
                if len(value) < 4:
                    return False

                log.debug("Input %s", value)
                s = applet.get_settings() if hasattr(applet, "get_settings") else {}
                if s is not None:
                    s["card.path"] = value
                    s["source"] = "storage"
                if hasattr(applet, "store_settings"):
                    applet.store_settings()

                if hasattr(window, "play_sound"):
                    window.play_sound("WINDOWSHOW")
                if hasattr(window, "hide"):
                    window.hide(
                        Window.transitionPushLeft
                        if hasattr(Window, "transitionPushLeft")
                        else None
                    )

                if not os.path.isdir(value):
                    log.warn("Invalid folder name: %s", value)
                    self.popup_message(
                        applet.string("IMAGE_VIEWER_ERROR"),
                        applet.string("IMAGE_VIEWER_CARD_NOT_DIRECTORY"),
                    )

                return True

            textinput = Textinput("textinput", imgpath, _on_accept)
            keyboard = Keyboard("keyboard", "qwerty", textinput)
            backspace = keyboard.backspace()
            group = Group(
                "keyboard_textinput",
                {"textinput": textinput, "backspace": backspace},
            )

            window.add_widget(group)
            window.add_widget(keyboard)
            if hasattr(window, "focus_widget"):
                window.focus_widget(group)

        except ImportError:
            log.warn("Keyboard/Textinput widgets not available for settings UI")

        self._help_action(
            window,
            "IMAGE_VIEWER_CARD_PATH_HELP",
            "IMAGE_VIEWER_CARD_PATH_HELP",
        )

        return window

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def free(self) -> None:
        """Release any background task resources."""
        if self._task is not None:
            try:
                if hasattr(self._task, "remove_task"):
                    self._task.remove_task()
            except Exception as exc:
                log.warning("Failed to remove background task: %s", exc)
            self._task = None

    # ------------------------------------------------------------------
    # Lua-compatible camelCase aliases
    # ------------------------------------------------------------------

    readImageList = read_image_list  # type: ignore[assignment]
    getFolder = get_folder
    getImage = get_image
    nextImage = next_image
    previousImage = previous_image
    listReady = list_ready
    listNotReadyError = list_not_ready_error
    getErrorMessage = get_error_message
    scanFolder = scan_folder
