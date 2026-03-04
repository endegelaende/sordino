"""
jive.applets.ImageViewer.ImageSourceServer — Server-based image source.

Ported from ``share/jive/applets/ImageViewer/ImageSourceServer.lua``
(~230 LOC) in the original jivelite project.

Reads an image list from a Squeezebox Server (Lyrion Music Server) or
mysqueezebox.com, then fetches each image on demand via HTTP.  This
source is used for server-pushed photo streams (e.g. Flickr via the
server's app gallery).

Features:

* Fetches image list from the server via a JSON-RPC request
* Builds image URLs with resize parameters based on screen size
* Handles private-IP detection to skip the image proxy
* Maintains a navigation history for back/forward traversal
* Supports server-provided captions, dates, and owner metadata
* Custom loading icon from the server app's icon
* Error handling for unavailable servers / network issues

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

import math
import re
import threading
from typing import TYPE_CHECKING, Any, Dict, List, Optional
from urllib.parse import quote as url_encode
from urllib.parse import urlparse

from jive.applets.ImageViewer.ImageSource import ImageSource
from jive.utils.log import logger

if TYPE_CHECKING:
    from jive.applet import Applet

__all__ = ["ImageSourceServer"]

log = logger("applet.ImageViewer")

# Maximum number of entries kept in the back-navigation history
_HISTORY_MAX = 30

# Regex patterns for private IP detection (Bug 13937)
_PRIVATE_IP_PATTERNS = [
    re.compile(r"^http://192\.168"),
    re.compile(r"^http://172\.16\."),
    re.compile(r"^http://10\."),
]
_NUMERIC_IP_PATTERN = re.compile(r"^http://\d")


class ImageSourceServer(ImageSource):
    """Image source that reads images from a Squeezebox / Lyrion server.

    The server provides a JSON list of image data (URL, caption, date,
    owner) via a slim-request command.  Images are fetched individually
    as the user navigates through the slideshow.

    Parameters
    ----------
    applet : Applet
        The owning ImageViewerApplet instance.
    server_data : dict
        Server connection parameters:

        * ``cmd`` — The slim-request command to fetch the image list.
        * ``playerId`` — The player ID to scope the request.
        * ``server`` — The ``SlimServer`` instance.
        * ``id`` — A unique identifier for this screensaver.
        * ``text`` — Display name for the screensaver.
        * ``appParameters`` — Optional dict with ``iconId`` for the
          loading icon.
        * ``isScreensaver`` — Whether this is a screensaver instance.
        * ``allowMotion`` — Whether motion events should be ignored.
    """

    def __init__(
        self, applet: "Applet", server_data: Optional[Dict[str, Any]] = None
    ) -> None:
        log.info("initialize ImageSourceServer")
        super().__init__(applet)

        self.img_files: List[Dict[str, Any]] = []
        self.server_data: Dict[str, Any] = server_data or {}

        self.image_data_history: List[Dict[str, Any]] = []
        self.image_data_history_max: int = _HISTORY_MAX

        self.current_image_index: int = 0
        self.current_image_file: Optional[str] = None
        self.current_caption: str = ""
        self.current_caption_multiline: str = ""
        self.error: Optional[str] = None

        self.read_image_list()

    # ------------------------------------------------------------------
    # Image list fetching
    # ------------------------------------------------------------------

    def read_image_list(self) -> None:
        """Fetch the image list from the server.

        Sends a slim-request command to the connected server.  The
        response is expected to contain a ``data.data`` array of image
        data dicts, each with at least an ``image`` key.

        If the server is not connected, shows an error popup and sets
        ``self.error``.
        """
        cmd = self.server_data.get("cmd")
        player_id = self.server_data.get("playerId")
        server = self.server_data.get("server")

        self.lst_ready = False

        if (
            server is not None
            and hasattr(server, "is_connected")
            and server.is_connected()
        ):
            log.debug(
                "readImageList: server: %s  id: %s  playerId: %s",
                server,
                self.server_data.get("id"),
                player_id,
            )

            try:
                if hasattr(server, "request"):
                    server.request(
                        self._img_files_sink(),
                        player_id,
                        cmd,
                    )
            except Exception as exc:
                log.warn("readImageList: request failed: %s", exc)
                self._handle_server_error()
        else:
            self.img_ready = False
            log.warn("readImageList: server %s is not available", server)
            self._handle_server_error()

    def _handle_server_error(self) -> None:
        """Handle a server connection error."""
        self.error = str(self.applet.string("IMAGE_VIEWER_LIST_NOT_READY_SERVER"))
        try:
            settings = (
                self.applet.get_settings()
                if hasattr(self.applet, "get_settings")
                else None
            )
            delay = (settings or {}).get("delay", 10000)

            popup = self.list_not_ready_error()
            if popup is not None and hasattr(popup, "addTimer"):
                popup.addTimer(
                    delay,
                    lambda: popup.hide() if hasattr(popup, "hide") else None,
                )
        except Exception as exc:
            log.error("_handle_server_error: failed to show error popup: %s", exc, exc_info=True)

    def _img_files_sink(self) -> Callable[..., Any]:  # type: ignore[name-defined]
        """Return a callback (sink) for the server image-list response.

        The callback processes the JSON response, filters out entries
        with null images, and populates ``self.img_files``.

        Returns
        -------
        callable
            A function ``(chunk, err)`` suitable for use as a request
            sink.
        """

        def _sink(chunk: Any = None, err: Any = None) -> None:
            if err:
                log.warn("err in sink: %s", err)
                return

            if chunk is not None:
                log.debug("imgFilesSink: received chunk")
                try:
                    data = None
                    if isinstance(chunk, dict):
                        data = chunk.get("data", {}).get("data")
                    elif hasattr(chunk, "data"):
                        inner = chunk.data
                        if isinstance(inner, dict):
                            data = inner.get("data")
                        elif hasattr(inner, "data"):
                            data = inner.data

                    if data is not None:
                        self.img_files = self._cleanse_nil_list_data(data)
                        self.current_image_index = 0
                        self.lst_ready = True
                        log.debug("Image list response count: %d", len(self.img_files))
                    else:
                        log.warn("imgFilesSink: no data.data in response")
                except Exception as exc:
                    log.warn("imgFilesSink: error processing chunk: %s", exc)

        return _sink

    @staticmethod
    def _cleanse_nil_list_data(input_list: List[Any]) -> List[Dict[str, Any]]:
        """Filter out entries with null/None image values.

        Parameters
        ----------
        input_list : list
            Raw list of image data dicts from the server.

        Returns
        -------
        list
            Filtered list with only entries that have a non-null
            ``image`` value.
        """
        output: List[Dict[str, Any]] = []
        for data in input_list:
            if isinstance(data, dict):
                img = data.get("image")
                if img is not None:
                    output.append(data)
            else:
                output.append(data)
        return output

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def next_image(self, ordering: str = "sequential") -> None:
        """Advance to the next image in the server's list.

        If we have exhausted the current list, a new list is fetched
        from the server.  Unlike the base class, the server source
        uses a 1-based index internally (matching Lua conventions)
        that is converted to 0-based for ``request_image``.
        """
        if len(self.img_files) == 0:
            self.read_image_list()
            self.empty_list_error()
            return

        self.current_image_index += 1

        if self.current_image_index <= len(self.img_files):
            image_data = self.img_files[self.current_image_index - 1]
            self.request_image(image_data)
        # else: might exceed if connection is down; keep retrying

        if self.current_image_index >= len(self.img_files):
            # Queue up next list
            self.read_image_list()

    def previous_image(self, ordering: str = "sequential") -> None:
        """Go back to the previous image using the history stack.

        Removes the current entry from history, then fetches the
        previous one.  If history has only one entry, does nothing.
        """
        if len(self.image_data_history) <= 1:
            return

        # Remove current entry
        self.image_data_history.pop()
        # Get previous entry
        image_data = self.image_data_history.pop()
        self.request_image(image_data)

    def _update_image_data_history(self, image_data: Dict[str, Any]) -> None:
        """Add *image_data* to the navigation history.

        Caps the history at ``image_data_history_max`` entries.
        """
        self.image_data_history.append(image_data)
        while len(self.image_data_history) > self.image_data_history_max:
            self.image_data_history.pop(0)

    # ------------------------------------------------------------------
    # Image fetching
    # ------------------------------------------------------------------

    def request_image(self, image_data: Dict[str, Any]) -> None:
        """Fetch the image described by *image_data*.

        Builds the full URL using the server's image proxy or direct
        access (for private IPs / server-relative URLs), applies
        resize parameters, and downloads the image in a background
        thread.

        Parameters
        ----------
        image_data : dict
            Must contain at minimum an ``image`` key with the URL or
            path.  May also contain ``caption``, ``date``, ``owner``.
        """
        log.debug("request new image")
        self.img_ready = False

        url_string = image_data.get("image", "")
        if not url_string:
            self.img_ready = True
            return

        # Determine screen size for resize parameters
        screen_width, screen_height = self._get_screen_size()

        # Build the full URL
        url_string = self._build_image_url(
            url_string, image_data, screen_width, screen_height
        )

        self.current_image_file = url_string

        # Build caption strings
        self._build_captions(image_data)

        log.debug("url: %s", url_string)

        # Fetch the image in a background thread
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
                        self.error = None
                        self._update_image_data_history(image_data)
                    except Exception as exc:
                        self.image = None
                        self.error = str(
                            self.applet.string("IMAGE_VIEWER_HTTP_ERROR_IMAGE")
                        )
                        log.warn("error decoding picture: %s", exc)
                else:
                    self.image = None
                    self.error = str(
                        self.applet.string("IMAGE_VIEWER_HTTP_ERROR_IMAGE")
                    )
                    log.warn("error loading picture: empty response")

            except Exception as exc:
                self.image = None
                self.error = str(self.applet.string("IMAGE_VIEWER_HTTP_ERROR_IMAGE"))
                log.warn("error loading picture: %s", exc)

            self.img_ready = True

        t = threading.Thread(target=_fetch, daemon=True, name="ImageSourceServer-image")
        t.start()

    def _build_image_url(
        self,
        url_string: str,
        image_data: Dict[str, Any],
        screen_width: int,
        screen_height: int,
    ) -> str:
        """Build the full image URL with appropriate resize parameters.

        Handles three cases:

        1. Private IP address — use the raw URL directly.
        2. Server-relative URL — prepend the server's IP:port and add
           resize parameters.
        3. Public URL — route through the SN image proxy with resize
           parameters.

        Parameters
        ----------
        url_string : str
            The raw image URL or path from the server.
        image_data : dict
            The full image data dict (for potential future use).
        screen_width : int
            The display width in pixels.
        screen_height : int
            The display height in pixels.

        Returns
        -------
        str
            The fully-qualified image URL.
        """
        # Bug 13937: if URL references a private IP, don't use imageproxy
        if _NUMERIC_IP_PATTERN.match(url_string):
            for pat in _PRIVATE_IP_PATTERNS:
                if pat.match(url_string):
                    return url_string

        if not url_string.startswith("http://") and not url_string.startswith(
            "https://"
        ):
            # URL is relative to the current server
            settings = (
                self.applet.get_settings()
                if hasattr(self.applet, "get_settings")
                else None
            )
            fullscreen = (settings or {}).get("fullscreen", False)
            rotation = (settings or {}).get("rotation", False)

            resize_params = "_%dx%d" % (screen_width, screen_height)

            if fullscreen:
                resize_params += "_c"
            elif rotation and screen_width < screen_height:
                # If device can rotate (Jive), get the bigger ratio
                resize_params = "_%dx%d_f" % (
                    screen_height,
                    int(math.floor(screen_height * screen_height / screen_width)),
                )

            url_string = url_string.replace("{resizeParams}", resize_params)

            # Prepend server address
            server = self.server_data.get("server")
            if server is not None:
                ip, port = None, None
                if hasattr(server, "get_ip_port"):
                    ip, port = server.get_ip_port()
                elif hasattr(server, "getIpPort"):
                    ip, port = server.getIpPort()

                if ip and port:
                    url_string = "http://%s:%s/%s" % (ip, port, url_string)

        else:
            # Public URL — use SN image proxy for resizing
            sn_hostname = self._get_sn_hostname()
            if sn_hostname:
                url_string = "http://%s/public/imageproxy?w=%d&h=%d&f=&u=%s" % (
                    sn_hostname,
                    screen_width,
                    screen_height,
                    url_encode(url_string),
                )

        return url_string

    def _build_captions(self, image_data: Dict[str, Any]) -> None:
        """Build single-line and multi-line caption strings from
        *image_data*.

        Populates ``self.current_caption`` (dash-separated) and
        ``self.current_caption_multiline`` (newline-separated) from
        the ``caption``, ``date``, and ``owner`` fields.
        """
        text_lines: List[str] = []

        caption = image_data.get("caption", "")
        if caption:
            text_lines.append(str(caption))

        date = image_data.get("date", "")
        if date:
            text_lines.append(str(date))

        owner = image_data.get("owner", "")
        if owner:
            text_lines.append(str(owner))

        self.current_caption = " - ".join(text_lines)
        self.current_caption_multiline = "\n\n".join(text_lines)

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    def get_text(self) -> Optional[str]:
        """Return the single-line caption for the current image."""
        return self.current_caption

    def get_multiline_text(self) -> Optional[str]:
        """Return the multi-line caption for the current image."""
        return self.current_caption_multiline

    def get_error_message(self) -> str:
        """Return the current error message, or a generic HTTP error."""
        return self.error or str(self.applet.string("IMAGE_VIEWER_HTTP_ERROR_IMAGE"))

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    def settings(self, window: Any) -> Any:
        """Return the settings window unchanged.

        Server sources don't have user-configurable settings beyond
        what the server provides.
        """
        return window

    # ------------------------------------------------------------------
    # Loading icon
    # ------------------------------------------------------------------

    def update_loading_icon(self, icon: Any = None) -> Any:
        """Return a loading icon, optionally using the server app's icon.

        If the server data includes an ``appParameters.iconId`` that
        is not a "MyApps" icon, the server's artwork is fetched for
        use as the loading icon.
        """
        try:
            from jive.ui.icon import Icon

            icon = Icon("icon_photo_loading")
        except Exception as exc:
            log.warning("update_loading_icon: failed to create default icon: %s", exc)

        app_params = self.server_data.get("appParameters")
        if app_params and isinstance(app_params, dict):
            icon_id = app_params.get("iconId")
            if icon_id and not re.search(r"MyApps", str(icon_id)):
                server = self.server_data.get("server")
                if server is not None and hasattr(server, "fetch_artwork"):
                    try:
                        from jive.jive_main import jive_main

                        thumb_size = 0
                        if hasattr(jive_main, "get_skin_param"):
                            thumb_size = (
                                jive_main.get_skin_param("POPUP_THUMB_SIZE") or 0  # type: ignore[union-attr]
                            )
                        elif hasattr(jive_main, "getSkinParam"):
                            thumb_size = jive_main.getSkinParam("POPUP_THUMB_SIZE") or 0  # type: ignore[attr-defined]

                        server.fetch_artwork(icon_id, icon, thumb_size, "png")
                    except Exception as exc:
                        log.error("update_loading_icon: failed to fetch server artwork: %s", exc, exc_info=True)

        return icon

    # ------------------------------------------------------------------
    # Error popup
    # ------------------------------------------------------------------

    def list_not_ready_error(self) -> Any:
        """Show an error popup when the server image list is not ready."""
        return self.popup_message(
            self.applet.string("IMAGE_VIEWER_ERROR"),
            self.applet.string("IMAGE_VIEWER_LIST_NOT_READY_SERVER"),
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_screen_size() -> Tuple[int, int]:  # type: ignore[name-defined]
        """Return ``(width, height)`` of the screen.

        Tries to use the Framework singleton; falls back to
        ``(480, 272)`` if unavailable.
        """
        try:
            from jive.ui.framework import framework

            if framework is not None and hasattr(framework, "get_screen_size"):
                return framework.get_screen_size()
        except Exception as exc:
            log.debug("_get_screen_size: framework unavailable: %s", exc)
        return (480, 272)

    @staticmethod
    def _get_sn_hostname() -> Optional[str]:
        """Return the mysqueezebox.com hostname.

        Tries to use the ``jnt`` network singleton; falls back to
        the default hostname.
        """
        try:
            from jive.net.jnt import jnt  # type: ignore[import-not-found]

            if jnt is not None and hasattr(jnt, "get_sn_hostname"):
                return jnt.get_sn_hostname()  # type: ignore[no-any-return]
            elif jnt is not None and hasattr(jnt, "getSNHostname"):
                return jnt.getSNHostname()  # type: ignore[no-any-return]
        except Exception as exc:
            log.debug("_get_sn_hostname: jnt module unavailable: %s", exc)
        return "www.mysqueezebox.com"

    # ------------------------------------------------------------------
    # Lua-compatible camelCase aliases
    # ------------------------------------------------------------------

    readImageList = read_image_list  # type: ignore[assignment]
    nextImage = next_image
    previousImage = previous_image
    requestImage = request_image
    getText = get_text
    getMultilineText = get_multiline_text
    getErrorMessage = get_error_message
    updateLoadingIcon = update_loading_icon
    listNotReadyError = list_not_ready_error
    imgFilesSink = _img_files_sink
