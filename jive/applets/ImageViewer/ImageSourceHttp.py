"""
jive.applets.ImageViewer.ImageSourceHttp — HTTP URL-list image source.

Ported from ``share/jive/applets/ImageViewer/ImageSourceHttp.lua``
(~165 LOC) in the original jivelite project.

Reads a list of image URLs from a remote text file (one URL per line),
then fetches each image on demand via HTTP.

Features:

* Fetches image list from a configurable URL (``http.path`` setting)
* Parses the response as a newline-delimited list of image URLs
* Downloads each image into a ``Surface`` for display
* Auto-refreshes the URL list when the end is reached
* Settings UI with a text-input keyboard for the list URL
* URL validation: if the current URL is a substring of the default,
  it is assumed to be accidentally truncated and reverted

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any, List, Optional
from urllib.parse import urlparse

from jive.applets.ImageViewer.ImageSource import ImageSource
from jive.utils.log import logger

if TYPE_CHECKING:
    from jive.applet import Applet

__all__ = ["ImageSourceHttp"]

log = logger("applet.ImageViewer")


class ImageSourceHttp(ImageSource):
    """Image source that reads image URLs from a remote text file.

    On construction the image list URL is fetched.  The response is
    parsed as a plain-text list (one URL per line).  Images are then
    fetched individually as the user navigates through the slideshow.

    Parameters
    ----------
    applet : Applet
        The owning ImageViewerApplet instance.
    """

    def __init__(self, applet: "Applet") -> None:
        log.info("initialize ImageSourceHttp")
        super().__init__(applet)

        self._fix_image_list_url()

        self.img_files: List[str] = []
        self.read_image_list()

    # ------------------------------------------------------------------
    # URL list fetching
    # ------------------------------------------------------------------

    def read_image_list(self) -> None:
        """Fetch the image-list URL and parse it into ``img_files``.

        Each non-empty line in the response is treated as an image URL.
        The fetch is performed in a background thread to avoid blocking
        the UI event loop.  On error a popup is shown to the user.
        """
        settings = (
            self.applet.get_settings() if hasattr(self.applet, "get_settings") else None
        )
        url_string = (settings or {}).get(
            "http.path",
            "http://ralph.irving.sdf.org/static/images/imageviewer/sbtouch.lst",
        )

        def _fetch() -> None:
            try:
                import urllib.request

                req = urllib.request.Request(url_string)
                with urllib.request.urlopen(req, timeout=30) as resp:
                    data = resp.read().decode("utf-8", errors="replace")

                for raw_line in data.splitlines():
                    line = raw_line.strip()
                    if line:
                        self.img_files.append(line)
                        log.debug(line)

            except Exception as exc:
                log.warn("error fetching image list: %s", exc)
                try:
                    self.popup_message(
                        self.applet.string("IMAGE_VIEWER_ERROR"),
                        self.applet.string("IMAGE_VIEWER_HTTP_ERROR"),
                    )
                except Exception as exc:
                    log.warning("Failed to show error popup: %s", exc)

            self.lst_ready = True

        t = threading.Thread(target=_fetch, daemon=True, name="ImageSourceHttp-list")
        t.start()

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def next_image(self, ordering: str = "sequential") -> None:
        """Advance to the next image, refreshing the list if needed."""
        super().next_image(ordering)

        # Refresh the URL list when we reach the last item
        if self.current_image >= len(self.img_files) - 1:
            self.read_image_list()

        self._request_image()

    def previous_image(self, ordering: str = "sequential") -> None:
        """Go back to the previous image."""
        super().previous_image(ordering)
        self._request_image()

    # ------------------------------------------------------------------
    # Image fetching
    # ------------------------------------------------------------------

    def _request_image(self) -> None:
        """Fetch the current image from its URL.

        The download is performed in a background thread.  On success
        the image data is loaded into a ``Surface``; on failure
        ``self.image`` is set to ``None``.
        """
        log.debug("request new image")
        self.img_ready = False

        if not (0 <= self.current_image < len(self.img_files)):
            self.img_ready = True
            return

        url_string = self.img_files[self.current_image]
        log.debug("url: %s", url_string)

        def _fetch() -> None:
            try:
                import urllib.request

                req = urllib.request.Request(url_string)
                with urllib.request.urlopen(req, timeout=30) as resp:
                    chunk = resp.read()

                if chunk:
                    try:
                        from jive.ui.surface import Surface

                        self.image = Surface.load_image_data(chunk, len(chunk))
                        log.debug("image ready")
                    except Exception as exc:
                        log.warn("error decoding image: %s", exc)
                        self.image = None
                else:
                    self.image = None
                    log.warn("empty response loading picture")

            except Exception as exc:
                self.image = None
                log.warn("error loading picture: %s", exc)

            self.img_ready = True

        t = threading.Thread(target=_fetch, daemon=True, name="ImageSourceHttp-image")
        t.start()

    # ------------------------------------------------------------------
    # Settings UI
    # ------------------------------------------------------------------

    def settings(self, window: Any) -> Any:
        """Add a text-input keyboard for the image list URL.

        Mirrors the Lua ``settings`` which creates a ``Textinput`` +
        ``Keyboard`` group for the user to enter the URL.
        """
        settings = (
            self.applet.get_settings() if hasattr(self.applet, "get_settings") else None
        )
        imgpath = (settings or {}).get(
            "http.path",
            "http://ralph.irving.sdf.org/static/images/imageviewer/sbtouch.lst",
        )

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
                    s["http.path"] = value
                if hasattr(applet, "store_settings"):
                    applet.store_settings()

                self._fix_image_list_url()

                if hasattr(window, "play_sound"):
                    window.play_sound("WINDOWSHOW")
                if hasattr(window, "hide"):
                    window.hide(
                        Window.transitionPushLeft
                        if hasattr(Window, "transitionPushLeft")
                        else None
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
            "IMAGE_VIEWER_HTTP_PATH",
            "IMAGE_VIEWER_HTTP_PATH_HELP",
        )

        return window

    # ------------------------------------------------------------------
    # URL validation
    # ------------------------------------------------------------------

    def _fix_image_list_url(self) -> None:
        """Revert the image list URL if it was accidentally truncated.

        In an attempt to escape the URL input screen, users sometimes
        accidentally delete part of the default URL.  If the current
        value is a proper substring of the default value, we revert it.

        Mirrors the Lua ``_fixImageListURL``.
        """
        settings = (
            self.applet.get_settings() if hasattr(self.applet, "get_settings") else None
        )
        default_settings = (
            self.applet.get_default_settings()
            if hasattr(self.applet, "get_default_settings")
            else None
        )

        if settings is None or default_settings is None:
            return

        url_string = settings.get("http.path", "")
        default_url = default_settings.get("http.path", "")

        if (
            url_string
            and default_url
            and url_string != default_url
            and url_string in default_url
        ):
            log.warn("Invalid URL: %s", url_string)
            log.warn("Replacing with default value")
            settings["http.path"] = default_url
            if hasattr(self.applet, "store_settings"):
                self.applet.store_settings()

    # ------------------------------------------------------------------
    # Lua-compatible camelCase aliases
    # ------------------------------------------------------------------

    readImageList = read_image_list  # type: ignore[assignment]
    nextImage = next_image
    previousImage = previous_image
    requestImage = _request_image
