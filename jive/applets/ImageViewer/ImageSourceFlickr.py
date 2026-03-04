"""
jive.applets.ImageViewer.ImageSourceFlickr — Flickr image source.

Ported from ``share/jive/applets/ImageViewer/ImageSourceFlickr.lua``
(~350 LOC) in the original jivelite project.

.. note::

   This module is **obsolete** — Flickr integration was replaced by a
   mysqueezebox.com-based app in the original project.  It is ported
   here for completeness and historical fidelity.

Reads image lists from the Flickr API (interestingness, recent, own
photos, contacts, favorites, tagged) and fetches each photo on demand.

Features:

* Multiple Flickr display modes (own, favorites, contacts,
  interesting, recent, tagged)
* Flickr user-ID resolution by email or username
* Tag-based search with comma-separated keywords
* Settings UI with radio-button display mode selector, user-ID input,
  and tag-keyword input
* Photo URL construction from Flickr's farm/server/id/secret scheme

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

import json
import random
import threading
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple
from urllib.parse import quote as url_encode
from urllib.parse import urlencode

from jive.applets.ImageViewer.ImageSource import ImageSource
from jive.utils.log import logger

if TYPE_CHECKING:
    from jive.applet import Applet

__all__ = ["ImageSourceFlickr"]

log = logger("applet.ImageViewer")

# Flickr API key (same as the original Lua source)
_API_KEY = "6505cb025e34a7e9b3f88daa9fa87a04"


class ImageSourceFlickr(ImageSource):
    """Image source that reads images from the Flickr API.

    .. deprecated::
       This source is obsolete — Flickr is now served via
       mysqueezebox.com.  Retained for completeness.

    Parameters
    ----------
    applet : Applet
        The owning ImageViewerApplet instance.
    """

    def __init__(self, applet: "Applet") -> None:
        log.info("initialize ImageSourceFlickr")
        super().__init__(applet)

        self.img_files: List[Dict[str, Any]] = []
        self.photo: Optional[Dict[str, Any]] = None
        self.url: str = ""

        self.read_image_list()

    # ------------------------------------------------------------------
    # Image list fetching
    # ------------------------------------------------------------------

    def read_image_list(self) -> None:
        """Fetch a list of photos from the Flickr API.

        The display mode is determined by the ``flickr.display`` setting:

        * ``"recent"`` — Most recently uploaded public photos
        * ``"contacts"`` — Photos from the user's contacts
        * ``"own"`` — The user's own public photos
        * ``"favorites"`` — The user's public favorites
        * ``"tagged"`` — Photos matching specific tags
        * ``"interesting"`` (default) — Flickr's interestingness list

        The fetch is performed in a background thread.
        """
        settings = (
            self.applet.get_settings() if hasattr(self.applet, "get_settings") else None
        ) or {}

        display_setting = settings.get("flickr.display", "interesting")
        flickr_id = settings.get("flickr.id", "")
        flickr_tags = settings.get("flickr.tags", "")

        method: str
        args: Dict[str, Any]

        if display_setting == "recent":
            method = "flickr.photos.getRecent"
            args = {"per_page": "1", "extras": "owner_name"}
        elif display_setting == "contacts":
            method = "flickr.photos.getContactsPublicPhotos"
            args = {
                "per_page": "100",
                "extras": "owner_name",
                "user_id": flickr_id,
                "include_self": "1",
            }
        elif display_setting == "own":
            method = "flickr.people.getPublicPhotos"
            args = {"per_page": "100", "extras": "owner_name", "user_id": flickr_id}
        elif display_setting == "favorites":
            method = "flickr.favorites.getPublicList"
            args = {"per_page": "100", "extras": "owner_name", "user_id": flickr_id}
        elif display_setting == "tagged":
            method = "flickr.photos.search"
            args = {
                "per_page": "100",
                "extras": "owner_name",
                "tags": url_encode(flickr_tags),
            }
        else:
            # Default: interesting
            method = "flickr.interestingness.getList"
            args = {"per_page": "100", "extras": "owner_name"}

        url = self._flickr_api_url(method, args)
        if url is None:
            return

        def _fetch() -> None:
            try:
                import urllib.request

                req = urllib.request.Request(url)
                with urllib.request.urlopen(req, timeout=30) as resp:
                    data = resp.read().decode("utf-8", errors="replace")

                log.debug("got chunk from Flickr API")
                obj = json.loads(data)

                photos = obj.get("photos", {}).get("photo", [])
                for photo in photos:
                    self.img_files.append(photo)

            except Exception as exc:
                log.warn("error fetching Flickr image list: %s", exc)

            self.lst_ready = True

        t = threading.Thread(target=_fetch, daemon=True, name="ImageSourceFlickr-list")
        t.start()

    # ------------------------------------------------------------------
    # Photo URL construction
    # ------------------------------------------------------------------

    @staticmethod
    def _get_photo_url(photo: Dict[str, Any], size: str = "") -> Tuple[str, int, str]:
        """Build a Flickr static photo URL from photo metadata.

        Parameters
        ----------
        photo : dict
            A Flickr photo dict with ``farm``, ``server``, ``id``,
            ``secret`` keys.
        size : str
            Optional size suffix (e.g. ``"_b"`` for large).

        Returns
        -------
        tuple of (host, port, path)
        """
        server = "farm%s.static.flickr.com" % photo.get("farm", "1")
        path = "/%s/%s_%s%s.jpg" % (
            photo.get("server", ""),
            photo.get("id", ""),
            photo.get("secret", ""),
            size,
        )
        return server, 80, path

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def next_image(self, ordering: str = "sequential") -> None:
        """Advance to the next Flickr image.

        If the image list is empty, re-fetches the list.  Otherwise
        selects the next (or random) image and requests it.
        """
        if len(self.img_files) == 0:
            self.lst_ready = False
            self.img_ready = False
            self.photo = None
            self.read_image_list()
            return

        super().next_image(ordering)
        self._request_image()

    def previous_image(self, ordering: str = "sequential") -> None:
        """Go to a different image (Flickr doesn't support true 'back').

        Delegates to ``next_image`` since Flickr photos are consumed
        from the list (removed on display).
        """
        self.next_image(ordering)

    # ------------------------------------------------------------------
    # Image fetching
    # ------------------------------------------------------------------

    def _request_image(self) -> None:
        """Fetch the current image from Flickr.

        Removes the photo from the list (consumed) and downloads
        the image in a background thread.
        """
        log.debug("request new image")
        self.img_ready = False

        if not (0 <= self.current_image < len(self.img_files)):
            self.img_ready = True
            return

        photo = self.img_files.pop(self.current_image)
        self.photo = photo

        # Adjust current_image if we went past the end after pop
        if self.current_image >= len(self.img_files) and len(self.img_files) > 0:
            self.current_image = len(self.img_files) - 1

        host, port, path = self._get_photo_url(photo)
        self.url = "http://%s:%d%s" % (host, port, path)

        log.info("photo URL: %s", self.url)

        full_url = self.url

        def _fetch() -> None:
            try:
                import urllib.request

                req = urllib.request.Request(full_url)
                with urllib.request.urlopen(req, timeout=30) as resp:
                    chunk = resp.read()

                if chunk:
                    try:
                        from jive.ui.surface import Surface

                        self.image = Surface.load_image_data(chunk, len(chunk))
                        log.debug("image ready")
                    except Exception as exc:
                        log.warn("error decoding Flickr image: %s", exc)
                        self.image = None
                else:
                    log.warn("error loading picture: empty response")
                    self.image = None

            except Exception as exc:
                log.warn("error loading picture: %s", exc)
                self.image = None

            self.img_ready = True

        t = threading.Thread(target=_fetch, daemon=True, name="ImageSourceFlickr-image")
        t.start()

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    def get_text(self) -> Optional[str]:
        """Return descriptive text for the current photo.

        Returns the owner name and title if available.
        """
        if self.photo:
            owner = self.photo.get("ownername", "")
            title = self.photo.get("title", "")
            parts = [p for p in (owner, title) if p]
            return " - ".join(parts) if parts else None
        return None

    def get_current_image_path(self) -> Optional[str]:
        """Return the current photo's URL."""
        return self.url or None

    # ------------------------------------------------------------------
    # Settings UI
    # ------------------------------------------------------------------

    def settings(self, window: Any) -> Any:
        """Add a settings menu with Flickr display mode, user ID, and
        tag keyword options.

        Mirrors the Lua ``settings`` which creates a ``SimpleMenu``
        with three items: Flickr User, Display mode, and Tag Keywords.
        """
        try:
            from jive.ui.simplemenu import SimpleMenu

            applet = self.applet

            menu = SimpleMenu(
                "menu",
                [
                    {
                        "text": str(applet.string("IMAGE_VIEWER_FLICKR_FLICKR_ID")),
                        "sound": "WINDOWSHOW",
                        "callback": lambda event=None, menuItem=None: (
                            self.define_flickr_id(menuItem)
                        ),
                    },
                    {
                        "text": str(applet.string("IMAGE_VIEWER_FLICKR_DISPLAY")),
                        "sound": "WINDOWSHOW",
                        "callback": lambda event=None, menuItem=None: (
                            self.display_setting(menuItem)
                        ),
                    },
                    {
                        "text": str(applet.string("IMAGE_VIEWER_FLICKR_TAGS")),
                        "sound": "WINDOWSHOW",
                        "callback": lambda event=None, menuItem=None: self.define_tags(
                            menuItem
                        ),
                    },
                ],
            )
            window.add_widget(menu)
        except ImportError:
            log.warn("SimpleMenu widget not available for Flickr settings UI")

        return window

    def define_flickr_id(self, menu_item: Any = None) -> Any:
        """Show a text-input window for the Flickr user ID / email.

        After the user enters a value, it is resolved to a Flickr NSID
        via the Flickr API (by email first, then by username).
        """
        try:
            from jive.ui.group import Group
            from jive.ui.keyboard import Keyboard
            from jive.ui.textinput import Textinput
            from jive.ui.window import Window

            applet = self.applet
            window = Window(
                "text_list",
                str(applet.string("IMAGE_VIEWER_FLICKR_FLICKR_ID")),
            )

            settings = (
                applet.get_settings() if hasattr(applet, "get_settings") else {}
            ) or {}
            flickrid = settings.get("flickr.idstring", "")

            def _on_accept(_widget: Any, value: str) -> bool:
                if len(value) < 4:
                    return False

                v = value.replace(" ", "")
                log.debug("Input %s", v)
                self.set_flickr_id_string(v)

                if hasattr(window, "play_sound"):
                    window.play_sound("WINDOWSHOW")
                if hasattr(window, "hide"):
                    window.hide()
                return True

            text_input = Textinput("textinput", flickrid, _on_accept)
            keyboard = Keyboard("keyboard", "qwerty", text_input)
            backspace = keyboard.backspace()
            group = Group(
                "keyboard_textinput",
                {"textinput": text_input, "backspace": backspace},
            )

            window.add_widget(group)
            window.add_widget(keyboard)
            if hasattr(window, "focus_widget"):
                window.focus_widget(group)

            if hasattr(applet, "tie_and_show_window"):
                applet.tie_and_show_window(window)
            elif hasattr(applet, "tieAndShowWindow"):
                applet.tieAndShowWindow(window)

            return window

        except ImportError:
            log.warn("Keyboard/Textinput widgets not available")
            return None

    def define_tags(self, menu_item: Any = None) -> Any:
        """Show a text-input window for Flickr tag keywords."""
        try:
            from jive.ui.group import Group
            from jive.ui.keyboard import Keyboard
            from jive.ui.textinput import Textinput
            from jive.ui.window import Window

            applet = self.applet
            window = Window(
                "text_list",
                str(applet.string("IMAGE_VIEWER_FLICKR_TAGS")),
            )

            settings = (
                applet.get_settings() if hasattr(applet, "get_settings") else {}
            ) or {}
            tags = settings.get("flickr.tags", "")

            def _on_accept(_widget: Any, value: str) -> bool:
                self.set_tags(value)
                if hasattr(window, "play_sound"):
                    window.play_sound("WINDOWSHOW")
                if hasattr(window, "hide"):
                    window.hide()
                return True

            text_input = Textinput("textinput", tags, _on_accept)
            keyboard = Keyboard("keyboard", "qwerty", text_input)
            backspace = keyboard.backspace()
            group = Group(
                "keyboard_textinput",
                {"textinput": text_input, "backspace": backspace},
            )

            window.add_widget(group)
            window.add_widget(keyboard)
            if hasattr(window, "focus_widget"):
                window.focus_widget(group)

            self._help_action(
                window,
                "IMAGE_VIEWER_FLICKR_TAGS",
                "IMAGE_VIEWER_FLICKR_QUERY_TAGS",
            )

            if hasattr(applet, "tie_and_show_window"):
                applet.tie_and_show_window(window)
            elif hasattr(applet, "tieAndShowWindow"):
                applet.tieAndShowWindow(window)

            return window

        except ImportError:
            log.warn("Keyboard/Textinput widgets not available")
            return None

    def display_setting(self, menu_item: Any = None) -> Any:
        """Show a radio-button menu for the Flickr display mode.

        Options: own, favorites, contacts, interesting, recent, tagged.
        """
        try:
            from jive.ui.radio import RadioButton, RadioGroup
            from jive.ui.simplemenu import SimpleMenu
            from jive.ui.window import Window

            applet = self.applet
            group = RadioGroup()

            settings = (
                applet.get_settings() if hasattr(applet, "get_settings") else {}
            ) or {}
            display = settings.get("flickr.display", "interesting")

            title = (
                str(menu_item.get("text", ""))
                if isinstance(menu_item, dict) and menu_item
                else str(applet.string("IMAGE_VIEWER_FLICKR_DISPLAY"))
            )

            window = Window("text_list", title)

            items = [
                (
                    "IMAGE_VIEWER_FLICKR_DISPLAY_OWN",
                    "own",
                ),
                (
                    "IMAGE_VIEWER_FLICKR_DISPLAY_FAVORITES",
                    "favorites",
                ),
                (
                    "IMAGE_VIEWER_FLICKR_DISPLAY_CONTACTS",
                    "contacts",
                ),
                (
                    "IMAGE_VIEWER_FLICKR_DISPLAY_INTERESTING",
                    "interesting",
                ),
                (
                    "IMAGE_VIEWER_FLICKR_DISPLAY_RECENT",
                    "recent",
                ),
                (
                    "IMAGE_VIEWER_FLICKR_DISPLAY_TAGGED",
                    "tagged",
                ),
            ]

            menu_items = []
            for label_token, value in items:
                # Capture value in closure
                v = value
                menu_items.append(
                    {
                        "text": str(applet.string(label_token)),
                        "style": "item_choice",
                        "check": RadioButton(
                            "radio",
                            group,
                            lambda *_args, _v=v: self.set_display(_v),
                            display == v,
                        ),
                    }
                )

            window.add_widget(SimpleMenu("menu", menu_items))

            if hasattr(applet, "tie_and_show_window"):
                applet.tie_and_show_window(window)
            elif hasattr(applet, "tieAndShowWindow"):
                applet.tieAndShowWindow(window)

            return window

        except ImportError:
            log.warn("RadioButton/SimpleMenu widgets not available")
            return None

    # ------------------------------------------------------------------
    # Settings helpers
    # ------------------------------------------------------------------

    def set_display(self, display: str) -> None:
        """Set the Flickr display mode.

        Validates that a Flickr ID is set before allowing modes that
        require one (own, contacts, favorites).

        Parameters
        ----------
        display : str
            One of ``"own"``, ``"favorites"``, ``"contacts"``,
            ``"interesting"``, ``"recent"``, ``"tagged"``.
        """
        settings = (
            self.applet.get_settings() if hasattr(self.applet, "get_settings") else None
        ) or {}

        flickr_id = settings.get("flickr.id", "")

        if not flickr_id and display in ("own", "contacts", "favorites"):
            self.popup_message(
                self.applet.string("IMAGE_VIEWER_FLICKR_ERROR"),
                self.applet.string("IMAGE_VIEWER_FLICKR_INVALID_DISPLAY_OPTION"),
            )
        else:
            settings["flickr.display"] = display
            if hasattr(self.applet, "store_settings"):
                self.applet.store_settings()

    def set_flickr_id_string(self, flickr_id_string: str) -> None:
        """Set the Flickr user ID string and resolve it.

        Stores the raw string, clears the resolved ID, then attempts
        to resolve via email first, then by username.

        Parameters
        ----------
        flickr_id_string : str
            The Flickr username or email address.
        """
        settings = (
            self.applet.get_settings() if hasattr(self.applet, "get_settings") else None
        )
        if settings is not None:
            settings["flickr.idstring"] = flickr_id_string
            settings["flickr.id"] = ""
            if hasattr(self.applet, "store_settings"):
                self.applet.store_settings()

        self.resolve_flickr_id_by_email(flickr_id_string)

    def set_flickr_id(self, flickr_id: str) -> None:
        """Store the resolved Flickr NSID."""
        settings = (
            self.applet.get_settings() if hasattr(self.applet, "get_settings") else None
        )
        if settings is not None:
            settings["flickr.id"] = flickr_id
            if hasattr(self.applet, "store_settings"):
                self.applet.store_settings()

    def set_tags(self, tags: str) -> None:
        """Store the Flickr tag keywords."""
        settings = (
            self.applet.get_settings() if hasattr(self.applet, "get_settings") else None
        )
        if settings is not None:
            settings["flickr.tags"] = tags
            if hasattr(self.applet, "store_settings"):
                self.applet.store_settings()

    # ------------------------------------------------------------------
    # Flickr API helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _flickr_api_url(method: str, args: Dict[str, str]) -> Optional[str]:
        """Build a Flickr REST API URL.

        Parameters
        ----------
        method : str
            The Flickr API method name.
        args : dict
            Additional query parameters.

        Returns
        -------
        str or None
            The full URL, or ``None`` on error.
        """
        params: List[str] = ["method=%s" % method]
        for k, v in args.items():
            params.append("%s=%s" % (k, v))
        params.append("api_key=%s" % _API_KEY)
        params.append("format=json")
        params.append("nojsoncallback=1")

        path = "/services/rest/?" + "&".join(params)
        url = "http://api.flickr.com%s" % path

        log.info("Flickr API URL: %s", url)
        return url

    @staticmethod
    def _flickr_find_by_email_url(search_text: str) -> Optional[str]:
        """Build a Flickr API URL to find a user by email."""
        return ImageSourceFlickr._flickr_api_url(
            "flickr.people.findByEmail",
            {"find_email": search_text},
        )

    @staticmethod
    def _flickr_find_by_username_url(search_text: str) -> Optional[str]:
        """Build a Flickr API URL to find a user by username."""
        return ImageSourceFlickr._flickr_api_url(
            "flickr.people.findByUsername",
            {"username": search_text},
        )

    # ------------------------------------------------------------------
    # Flickr ID resolution
    # ------------------------------------------------------------------

    def resolve_flickr_id_by_email(self, search_text: str) -> bool:
        """Attempt to resolve *search_text* as a Flickr email address.

        If that fails, falls back to resolving by username.

        Parameters
        ----------
        search_text : str
            The email address to look up.

        Returns
        -------
        bool
            Always ``True`` (the resolution is asynchronous).
        """
        url = self._flickr_find_by_email_url(search_text)
        if url is None:
            return False

        log.info("find by email: %s", url)

        def _fetch() -> None:
            try:
                import urllib.request

                req = urllib.request.Request(url)
                with urllib.request.urlopen(req, timeout=30) as resp:
                    data = resp.read().decode("utf-8", errors="replace")

                obj = json.loads(data)
                if obj.get("stat") == "ok":
                    nsid = obj.get("user", {}).get("nsid", "")
                    log.info("flickr id found: %s", nsid)
                    self.set_flickr_id(nsid)
                else:
                    log.warn("search by email failed: %s", search_text)
                    self.resolve_flickr_id_by_username(search_text)

            except Exception as exc:
                log.warn("error resolving Flickr email: %s", exc)
                self.resolve_flickr_id_by_username(search_text)

        t = threading.Thread(target=_fetch, daemon=True, name="FlickrResolveEmail")
        t.start()
        return True

    def resolve_flickr_id_by_username(self, search_text: str) -> bool:
        """Attempt to resolve *search_text* as a Flickr username.

        Parameters
        ----------
        search_text : str
            The username to look up.

        Returns
        -------
        bool
            Always ``True`` (the resolution is asynchronous).
        """
        url = self._flickr_find_by_username_url(search_text)
        if url is None:
            return False

        log.info("find by userid: %s", url)

        def _fetch() -> None:
            try:
                import urllib.request

                req = urllib.request.Request(url)
                with urllib.request.urlopen(req, timeout=30) as resp:
                    data = resp.read().decode("utf-8", errors="replace")

                obj = json.loads(data)
                if obj.get("stat") == "ok":
                    nsid = obj.get("user", {}).get("nsid", "")
                    log.info("flickr id found: %s", nsid)
                    self.set_flickr_id(nsid)
                else:
                    log.warn("search by userid failed")
                    self.popup_message(
                        self.applet.string("IMAGE_VIEWER_FLICKR_ERROR"),
                        self.applet.string("IMAGE_VIEWER_FLICKR_USERID_ERROR"),
                    )

            except Exception as exc:
                log.warn("error resolving Flickr username: %s", exc)

        t = threading.Thread(target=_fetch, daemon=True, name="FlickrResolveUsername")
        t.start()
        return True

    # ------------------------------------------------------------------
    # Lua-compatible camelCase aliases
    # ------------------------------------------------------------------

    readImageList = read_image_list  # type: ignore[assignment]
    nextImage = next_image
    previousImage = previous_image
    requestImage = _request_image
    getText = get_text
    getCurrentImagePath = get_current_image_path
    setDisplay = set_display
    setFlickrIdString = set_flickr_id_string
    setFlickrId = set_flickr_id
    setTags = set_tags
    defineFlickrId = define_flickr_id
    defineTags = define_tags
    displaySetting = display_setting
    resolveFlickrIdByEmail = resolve_flickr_id_by_email
    resolveFlickrIdByUsername = resolve_flickr_id_by_username
