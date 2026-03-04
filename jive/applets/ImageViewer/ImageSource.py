"""
jive.applets.ImageViewer.ImageSource — Base class for all image sources.

Ported from ``share/jive/applets/ImageViewer/ImageSource.lua`` (~140 LOC)
in the original jivelite project.

ImageSource is the abstract base that every image source (HTTP, local
storage, SD card, USB, Flickr, server) inherits from.  It provides:

* Image list management (``img_files``, ``current_image``)
* Ready-state flags (``img_ready``, ``lst_ready``)
* Navigation helpers (``next_image``, ``previous_image``)
* Error / popup helpers (``popup_message``, ``empty_list_error``,
  ``list_not_ready_error``)
* Stub accessors for image data, text, multiline text, path, count

Subclasses override ``read_image_list()``, ``next_image()``, etc.

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING, Any, List, Optional

from jive.utils.log import logger

if TYPE_CHECKING:
    from jive.applet import Applet
    from jive.ui.surface import Surface
    from jive.ui.window import Window

__all__ = ["ImageSource"]

log = logger("applet.ImageViewer")


class ImageSource:
    """Base class for all Image Viewer image sources.

    Subclasses must override at least ``read_image_list()`` and
    typically ``next_image()`` / ``previous_image()`` as well.

    Attributes
    ----------
    applet : Applet
        The owning ImageViewerApplet instance.
    img_files : list
        List of image file paths / URLs / data dicts.
    img_ready : bool
        ``True`` when the current image has been fetched and is
        ready to display.
    lst_ready : bool
        ``True`` when the image list has been loaded.
    current_image : int
        0-based index into ``img_files`` for the current image.
    image : Surface | None
        The most recently loaded image surface.
    """

    def __init__(self, applet: "Applet") -> None:
        log.info("init of ImageSource base")
        self.applet = applet
        self.img_files: List[Any] = []
        self.img_ready: bool = False
        self.lst_ready: bool = False
        self.current_image: int = 0
        self.image: Optional[Any] = None

    # ------------------------------------------------------------------
    # Popup / error helpers
    # ------------------------------------------------------------------

    def popup_message(self, title: str, msg: str) -> Any:
        """Show a popup window with *title* and *msg*.

        Returns the popup window so callers can attach timers or
        additional listeners.
        """
        from jive.ui.constants import EVENT_KEY_PRESS, EVENT_MOUSE_PRESS
        from jive.ui.window import Window

        popup = Window("text_list", title)

        try:
            from jive.ui.textarea import Textarea

            text = Textarea("text", msg)
            popup.add_widget(text)
        except Exception as exc:
            log.warning("popup_message: failed to create Textarea widget: %s", exc)

        # Apply screensaver window styling if available
        if hasattr(self.applet, "apply_screensaver_window"):
            self.applet.apply_screensaver_window(popup)

        try:
            popup.add_listener(
                EVENT_KEY_PRESS | EVENT_MOUSE_PRESS,
                lambda *_args, **_kw: (  # type: ignore[arg-type]
                    popup.play_sound("WINDOWHIDE")  # type: ignore[func-returns-value]
                    if hasattr(popup, "play_sound")
                    else None,
                    popup.hide() if hasattr(popup, "hide") else None,  # type: ignore[func-returns-value]
                ),
            )
        except Exception as exc:
            log.warning("popup_message: failed to add dismiss listener: %s", exc)

        if hasattr(self.applet, "tie_and_show_window"):
            self.applet.tie_and_show_window(popup)
        elif hasattr(self.applet, "tieAndShowWindow"):
            self.applet.tieAndShowWindow(popup)

        return popup

    def _help_action(
        self,
        window: Any,
        title_text: Optional[str] = None,
        body_text: Optional[str] = None,
        menu: Any = None,
    ) -> None:
        """Attach a help action to *window*.

        Mirrors the Lua ``ImageSource:_helpAction``.
        """
        if title_text is None and body_text is None:
            return

        applet = self.applet

        def _show_help() -> None:
            from jive.ui.window import Window

            hw = Window(
                "help_info",
                applet.string(title_text) if title_text else "",
                "helptitle",
            )
            if hasattr(hw, "set_allow_screensaver"):
                hw.set_allow_screensaver(False)

            try:
                from jive.ui.textarea import Textarea

                ta = Textarea("text", applet.string(body_text) if body_text else "")
                hw.add_widget(ta)
            except Exception as exc:
                log.warning("_help_action: failed to create help Textarea widget: %s", exc)

            if hasattr(applet, "tie_and_show_window"):
                applet.tie_and_show_window(hw)
            elif hasattr(applet, "tieAndShowWindow"):
                applet.tieAndShowWindow(hw)

            if hasattr(hw, "play_sound"):
                hw.play_sound("WINDOWSHOW")

        if hasattr(window, "add_action_listener"):
            window.add_action_listener("help", self, _show_help)
        elif hasattr(window, "addActionListener"):
            window.addActionListener("help", self, _show_help)

        if menu is not None:
            try:
                from jive.jive_main import jive_main

                if hasattr(jive_main, "add_help_menu_item"):
                    jive_main.add_help_menu_item(menu, self, _show_help)  # type: ignore[union-attr]
                elif hasattr(jive_main, "addHelpMenuItem"):
                    jive_main.addHelpMenuItem(menu, self, _show_help)  # type: ignore[attr-defined]
            except Exception as exc:
                log.warning("_help_action: failed to add help menu item: %s", exc)

        if hasattr(window, "set_button_action"):
            window.set_button_action("rbutton", "help")
        elif hasattr(window, "setButtonAction"):
            window.setButtonAction("rbutton", "help")

    # ------------------------------------------------------------------
    # Error convenience methods
    # ------------------------------------------------------------------

    def empty_list_error(self) -> Any:
        """Show an error popup for an empty image list."""
        return self.popup_message(
            self.applet.string("IMAGE_VIEWER_ERROR"),
            self.applet.string("IMAGE_VIEWER_EMPTY_LIST"),
        )

    def list_not_ready_error(self) -> Any:
        """Show an error popup when the image list is not ready."""
        return self.popup_message(
            self.applet.string("IMAGE_VIEWER_ERROR"),
            self.applet.string("IMAGE_VIEWER_LIST_NOT_READY"),
        )

    # ------------------------------------------------------------------
    # State queries
    # ------------------------------------------------------------------

    def image_ready(self) -> bool:
        """Return ``True`` if the current image is loaded and ready."""
        return self.img_ready

    def list_ready(self) -> bool:
        """Return ``True`` if the image list has been loaded."""
        return self.lst_ready

    def use_auto_zoom(self) -> bool:
        """Return ``True`` if the viewer should auto-zoom images.

        Subclasses may override to disable auto-zoom.
        """
        return True

    # ------------------------------------------------------------------
    # Loading icon
    # ------------------------------------------------------------------

    def update_loading_icon(self, icon: Any = None) -> Any:
        """Return an icon widget to show during loading.

        Subclasses may override to show a source-specific icon (e.g.
        Flickr branding).
        """
        try:
            from jive.ui.icon import Icon

            return Icon("icon_photo_loading")
        except Exception as exc:
            log.debug("update_loading_icon: Icon widget unavailable: %s", exc)
            return icon

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def next_image(self, ordering: str = "sequential") -> None:
        """Advance to the next image in the list.

        Parameters
        ----------
        ordering:
            ``"sequential"`` for linear traversal, ``"random"`` for
            random selection.
        """
        if len(self.img_files) == 0:
            self.empty_list_error()
            return

        if ordering == "random":
            self.current_image = random.randint(0, len(self.img_files) - 1)
        else:
            self.current_image += 1
            if self.current_image >= len(self.img_files):
                self.current_image = 0

    def previous_image(self, ordering: str = "sequential") -> None:
        """Go back to the previous image in the list.

        Parameters
        ----------
        ordering:
            ``"sequential"`` for linear traversal, ``"random"`` for
            random selection.
        """
        if len(self.img_files) == 0:
            self.empty_list_error()
            return

        if ordering == "random":
            self.current_image = random.randint(0, len(self.img_files) - 1)
        else:
            self.current_image -= 1
            if self.current_image < 0:
                self.current_image = len(self.img_files) - 1

    # ------------------------------------------------------------------
    # Image accessors
    # ------------------------------------------------------------------

    def get_image(self) -> Optional[Any]:
        """Return the current image surface, or ``None``."""
        return self.image

    def get_text(self) -> Optional[str]:
        """Return single-line descriptive text for the current image."""
        if 0 <= self.current_image < len(self.img_files):
            item = self.img_files[self.current_image]
            if isinstance(item, str):
                return item
            return str(item)
        return None

    def get_multiline_text(self) -> Optional[str]:
        """Return multi-line descriptive text for the current image."""
        return self.get_text()

    def get_current_image_path(self) -> Optional[str]:
        """Return the file path or URL of the current image."""
        if 0 <= self.current_image < len(self.img_files):
            item = self.img_files[self.current_image]
            if isinstance(item, str):
                return item
            return str(item)
        return None

    def get_image_count(self) -> int:
        """Return the number of images in the list."""
        return len(self.img_files)

    def get_error_message(self) -> str:
        """Return an error message string.  Subclasses override."""
        return "unknown"

    # ------------------------------------------------------------------
    # Settings UI
    # ------------------------------------------------------------------

    def settings(self, window: Any) -> Any:
        """Return (or modify) the settings window for this source.

        The default implementation returns *window* unchanged.
        Subclasses override to add source-specific configuration
        widgets.
        """
        return window

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def free(self) -> None:
        """Release resources held by this image source.

        The default implementation is a no-op.
        """

    # ------------------------------------------------------------------
    # Lua-compatible camelCase aliases
    # ------------------------------------------------------------------

    imageReady = image_ready
    listReady = list_ready
    useAutoZoom = use_auto_zoom
    updateLoadingIcon = update_loading_icon
    nextImage = next_image
    previousImage = previous_image
    getImage = get_image
    getText = get_text
    getMultilineText = get_multiline_text
    getCurrentImagePath = get_current_image_path
    getImageCount = get_image_count
    getErrorMessage = get_error_message
    popupMessage = popup_message
    emptyListError = empty_list_error
    listNotReadyError = list_not_ready_error
    readImageList = None  # Subclasses must implement

    def read_image_list(self) -> None:
        """Read / fetch the image list.  Subclasses must override."""
        raise NotImplementedError("Subclasses must implement read_image_list()")
