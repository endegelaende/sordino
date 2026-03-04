"""
jive.applets.ImageViewer.ImageViewerApplet — Image Viewer / Slideshow applet.

Ported from ``share/jive/applets/ImageViewer/ImageViewerApplet.lua``
(~1,590 LOC) in the original jivelite project.

This applet provides a slideshow / image viewer with multiple image
sources (local storage, SD card, USB, HTTP URL list, Flickr, server)
and configurable transitions, delays, ordering, rotation, zoom, and
text overlays.

Features:

* Multiple image sources with pluggable architecture
* Nine transition effects (fade, box-out, top-down, bottom-up,
  left-right, right-left, push-left, push-right, random)
* Configurable slide delay (5s to 60s)
* Sequential or random ordering
* Auto-rotation for portrait/landscape mismatch
* Fullscreen zoom or fit-to-screen
* Optional text overlay with image metadata
* Wallpaper save functionality
* Media browser for local storage
* Remote screensaver support via server push
* Settings UI with radio-button menus for all options

Architecture:

* ``ImageViewerApplet`` — Main applet class extending ``Applet``
* Image sources are separate classes (``ImageSource*``) instantiated
  based on the ``source`` setting
* Custom transition functions for slideshow effects
* Background image loading with retry timers

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

import gc
import math
import os
import random
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Tuple

from jive.applet import Applet
from jive.utils.log import logger

if TYPE_CHECKING:
    from jive.ui.surface import Surface
    from jive.ui.window import Window

__all__ = ["ImageViewerApplet"]

log = logger("applet.ImageViewer")

# Minimum interval between scroll-triggered slide changes (ms)
_MIN_SCROLL_INTERVAL = 750

# Frame rate for transitions (frames per second)
_FRAME_RATE = 30


# ══════════════════════════════════════════════════════════════════════════════
# Transition functions
# ══════════════════════════════════════════════════════════════════════════════


def _get_screen_size() -> Tuple[int, int]:
    """Return (width, height) of the screen."""
    try:
        from jive.ui.framework import framework

        if framework is not None and hasattr(framework, "get_screen_size"):
            return framework.get_screen_size()
    except Exception as exc:
        log.debug("_get_screen_size: framework unavailable: %s", exc)
    return (480, 272)


def _kill_transition() -> None:
    """Kill the current transition animation."""
    try:
        from jive.ui.framework import framework

        if framework is not None and hasattr(framework, "_kill_transition"):
            framework._kill_transition()
    except Exception as exc:
        log.debug("_kill_transition: framework unavailable: %s", exc)


def transition_box_out(old_window: Any, new_window: Any) -> Callable[..., Any]:
    """Transition: reveal new window from center outward (box-out).

    The new window is revealed in a growing rectangle from the center
    of the screen.
    """
    frames = _FRAME_RATE * 2  # 2 seconds
    screen_width, screen_height = _get_screen_size()
    inc_x = screen_width / frames / 2
    inc_y = screen_height / frames / 2
    x = screen_width / 2
    y = screen_height / 2
    state = {"i": 0}

    def _step(widget: Any, surface: Any) -> None:
        i = state["i"]
        adj_x = i * inc_x
        adj_y = i * inc_y

        try:
            from jive.ui.constants import LAYER_CONTENT, LAYER_FRAME

            new_window.draw(surface, LAYER_FRAME)
            old_window.draw(surface, LAYER_CONTENT)

            if hasattr(surface, "set_clip"):
                surface.set_clip(
                    int(x - adj_x), int(y - adj_y), int(adj_x * 2), int(adj_y * 2)
                )
            new_window.draw(surface, LAYER_CONTENT)
        except Exception as exc:
            log.warning("transition_box_out: draw step failed: %s", exc)

        state["i"] += 1
        if state["i"] >= frames:
            _kill_transition()

    return _step


def transition_top_down(old_window: Any, new_window: Any) -> Callable[..., Any]:
    """Transition: reveal new window from top to bottom."""
    frames = _FRAME_RATE * 2
    screen_width, screen_height = _get_screen_size()
    inc_y = screen_height / frames
    state = {"i": 0}

    def _step(widget: Any, surface: Any) -> None:
        i = state["i"]
        adj_y = i * inc_y

        try:
            from jive.ui.constants import LAYER_CONTENT, LAYER_FRAME

            new_window.draw(surface, LAYER_FRAME)
            old_window.draw(surface, LAYER_CONTENT)

            if hasattr(surface, "set_clip"):
                surface.set_clip(0, 0, screen_width, int(adj_y))
            new_window.draw(surface, LAYER_CONTENT)
        except Exception as exc:
            log.warning("transition_top_down: draw step failed: %s", exc)

        state["i"] += 1
        if state["i"] >= frames:
            _kill_transition()

    return _step


def transition_bottom_up(old_window: Any, new_window: Any) -> Callable[..., Any]:
    """Transition: reveal new window from bottom to top."""
    frames = _FRAME_RATE * 2
    screen_width, screen_height = _get_screen_size()
    inc_y = screen_height / frames
    state = {"i": 0}

    def _step(widget: Any, surface: Any) -> None:
        i = state["i"]
        adj_y = i * inc_y

        try:
            from jive.ui.constants import LAYER_CONTENT, LAYER_FRAME

            new_window.draw(surface, LAYER_FRAME)
            old_window.draw(surface, LAYER_CONTENT)

            if hasattr(surface, "set_clip"):
                surface.set_clip(
                    0, int(screen_height - adj_y), screen_width, screen_height
                )
            new_window.draw(surface, LAYER_CONTENT)
        except Exception as exc:
            log.warning("transition_bottom_up: draw step failed: %s", exc)

        state["i"] += 1
        if state["i"] >= frames:
            _kill_transition()

    return _step


def transition_left_right(old_window: Any, new_window: Any) -> Callable[..., Any]:
    """Transition: reveal new window from left to right."""
    frames = _FRAME_RATE * 2
    screen_width, screen_height = _get_screen_size()
    inc_x = screen_width / frames
    state = {"i": 0}

    def _step(widget: Any, surface: Any) -> None:
        i = state["i"]
        adj_x = i * inc_x

        try:
            from jive.ui.constants import LAYER_CONTENT, LAYER_FRAME

            new_window.draw(surface, LAYER_FRAME)
            old_window.draw(surface, LAYER_CONTENT)

            if hasattr(surface, "set_clip"):
                surface.set_clip(0, 0, int(adj_x), screen_height)
            new_window.draw(surface, LAYER_CONTENT)
        except Exception as exc:
            log.warning("transition_left_right: draw step failed: %s", exc)

        state["i"] += 1
        if state["i"] >= frames:
            _kill_transition()

    return _step


def transition_right_left(old_window: Any, new_window: Any) -> Callable[..., Any]:
    """Transition: reveal new window from right to left."""
    frames = _FRAME_RATE * 2
    screen_width, screen_height = _get_screen_size()
    inc_x = screen_width / frames
    state = {"i": 0}

    def _step(widget: Any, surface: Any) -> None:
        i = state["i"]
        adj_x = i * inc_x

        try:
            from jive.ui.constants import LAYER_CONTENT, LAYER_FRAME

            new_window.draw(surface, LAYER_FRAME)
            old_window.draw(surface, LAYER_CONTENT)

            if hasattr(surface, "set_clip"):
                surface.set_clip(
                    int(screen_width - adj_x), 0, screen_width, screen_height
                )
            new_window.draw(surface, LAYER_CONTENT)
        except Exception as exc:
            log.warning("transition_right_left: draw step failed: %s", exc)

        state["i"] += 1
        if state["i"] >= frames:
            _kill_transition()

    return _step


# ══════════════════════════════════════════════════════════════════════════════
# ImageViewerApplet
# ══════════════════════════════════════════════════════════════════════════════


class ImageViewerApplet(Applet):
    """Image Viewer / Slideshow applet.

    Provides a configurable slideshow with multiple image sources,
    transition effects, and settings UI.

    The applet can be launched from the settings menu or activated
    as a screensaver.  Remote screensavers can be pushed by a
    connected server.
    """

    def __init__(self) -> None:
        super().__init__()

        # Image source
        self.img_source: Any = None

        # State
        self.list_check_count: int = 0
        self.image_check_count: int = 0
        self.initialized: bool = False
        self.is_rendering: bool = False
        self.is_screensaver: bool = False
        self.drag_start: int = -1
        self.drag_offset: int = 0
        self.image_error: Optional[str] = None
        self.use_fast_transition: bool = False

        # Timers
        self.next_slide_timer: Any = None
        self.check_foto_timer: Any = None

        # Task reference for background rendering
        self._task: Any = None

        # Windows
        self.window: Optional[Any] = None
        self.init_window: Optional[Any] = None

        # Server data for remote screensavers
        self.server_data: Optional[Dict[str, Any]] = None

        # Scroll dedup
        self.last_scroll_t: Optional[int] = None
        self.last_scroll_dir: Optional[int] = None

        # Available transitions
        self.transitions: List[Callable[..., Any]] = [
            transition_box_out,
            transition_top_down,
            transition_bottom_up,
            transition_left_right,
            transition_right_left,
        ]
        # Add framework transitions if available
        self._add_framework_transitions()

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    def init(self) -> None:
        """Initialize the applet.

        Migrates old rotation settings from string ("yes"/"no"/"auto")
        to boolean, matching the Lua ``init()`` logic.
        """
        super().init()

        settings = self.get_settings()
        if settings is not None:
            rotation = str(settings.get("rotation", "false"))
            device_can_rotate = self._has_device_rotation()
            settings["rotation"] = device_can_rotate and (
                rotation in ("true", "True", "yes", "auto")
            )

    def _add_framework_transitions(self) -> None:
        """Add framework-level transitions to the available list."""
        try:
            from jive.ui.window import (
                transition_fade_in,
                transition_push_left,
                transition_push_right,
            )

            self.transitions.append(transition_fade_in)
            self.transitions.append(transition_push_left)
            self.transitions.append(transition_push_right)
        except (ImportError, AttributeError) as exc:
            log.debug(
                "_add_framework_transitions: window transitions unavailable: %s", exc
            )

    # ------------------------------------------------------------------
    # Image source initialization
    # ------------------------------------------------------------------

    def init_image_source(self, img_source_override: Any = None) -> None:
        """Initialize the image source and reset state.

        Parameters
        ----------
        img_source_override : ImageSource, optional
            A pre-created image source to use instead of creating one
            from settings.
        """
        log.info("init image viewer")

        self.img_source = None
        self.list_check_count = 0
        self.image_check_count = 0
        self.initialized = False
        self.is_rendering = False
        self.drag_start = -1
        self.drag_offset = 0
        self.image_error = None

        self.set_image_source(img_source_override)

    def set_image_source(self, img_source_override: Any = None) -> None:
        """Set the active image source.

        If *img_source_override* is provided, it is used directly.
        Otherwise the source is created based on the ``source`` setting.

        Parameters
        ----------
        img_source_override : ImageSource, optional
            A pre-created image source.
        """
        if img_source_override is not None:
            self.img_source = img_source_override
            return

        settings = self.get_settings() or {}
        src = settings.get("source", "http")

        if src == "storage":
            from jive.applets.ImageViewer.ImageSourceLocalStorage import (
                ImageSourceLocalStorage,
            )

            self.img_source = ImageSourceLocalStorage(self)

        elif src == "usb":
            from jive.applets.ImageViewer.ImageSourceUSB import ImageSourceUSB

            self.img_source = ImageSourceUSB(self)

        elif src == "card":
            from jive.applets.ImageViewer.ImageSourceCard import ImageSourceCard

            self.img_source = ImageSourceCard(self)

        # Flickr is now being served by mysb.com, disable standalone applet
        # elif src == "flickr":
        #     from jive.applets.ImageViewer.ImageSourceFlickr import ImageSourceFlickr
        #     self.img_source = ImageSourceFlickr(self)

        else:
            # Default to web list — it's available on all players
            from jive.applets.ImageViewer.ImageSourceHttp import ImageSourceHttp

            self.img_source = ImageSourceHttp(self)

    # ------------------------------------------------------------------
    # Main menu
    # ------------------------------------------------------------------

    def open_image_viewer(self, *args: Any, **kwargs: Any) -> Any:
        """Open the Image Viewer main menu.

        Provides options to start the slideshow, browse media (if
        local storage is available), and open settings.
        """
        from jive.ui.window import Window

        window = Window("text_list", self.string("IMAGE_VIEWER"))

        try:
            from jive.ui.simplemenu import SimpleMenu

            settings = self.get_settings() or {}
            imgpath = settings.get("card.path", "/media")

            menu = SimpleMenu(
                "menu",
                [
                    {
                        "text": str(self.string("IMAGE_VIEWER_START_SLIDESHOW")),
                        "sound": "WINDOWSHOW",
                        "callback": lambda event=None, menuItem=None: (
                            self.start_slideshow(False)
                        ),
                    },
                    {
                        "text": str(self.string("IMAGE_VIEWER_SETTINGS")),
                        "sound": "WINDOWSHOW",
                        "callback": lambda event=None, menuItem=None: (
                            self.open_settings()
                        ),
                    },
                ],
            )

            # Add browse media option if local storage is available
            if self._has_local_storage():
                menu.insert_item(
                    {
                        "text": str(self.string("IMAGE_VIEWER_BROWSE_MEDIA")),
                        "sound": "WINDOWSHOW",
                        "callback": lambda event=None, menuItem=None: (
                            self.browse_folder(imgpath)
                        ),
                    },
                    0,
                )

            window.add_widget(menu)
        except ImportError:
            log.warn("SimpleMenu widget not available")

        self.tie_and_show_window(window)
        return window

    # Lua-compatible alias
    openImageViewer = open_image_viewer

    # ------------------------------------------------------------------
    # Media browser
    # ------------------------------------------------------------------

    def browse_folder(self, folder: str, title: Optional[str] = None) -> Any:
        """Browse a local folder for images and subdirectories.

        Parameters
        ----------
        folder : str
            The directory path to browse.
        title : str, optional
            Window title; defaults to *folder*.

        Returns
        -------
        Window
            The browser window.
        """
        import re

        from jive.ui.window import Window

        window = Window("text_list", title or folder)

        # Verify validity of the directory
        if not os.path.isdir(folder):
            try:
                from jive.ui.textarea import Textarea

                text = Textarea(
                    "text",
                    str(self.string("IMAGE_VIEWER_INVALID_FOLDER")) + "\n" + folder,
                )
                window.add_widget(text)
            except ImportError as exc:
                log.debug("browse_folder: Textarea widget unavailable: %s", exc)

            self.tie_and_show_window(window)
            return window

        image_pattern = re.compile(r"\.(jpe?g|png|bmp|gif)$", re.IGNORECASE)

        try:
            from jive.ui.simplemenu import SimpleMenu

            menu = SimpleMenu("menu")
            num_items = 0

            entries = sorted(os.listdir(folder))
            for f in entries:
                # Skip hidden files/directories
                if f.startswith("."):
                    continue

                fullpath = os.path.join(folder, f)

                try:
                    if os.path.isdir(fullpath):
                        # Capture f in closure
                        _f = f
                        _fp = fullpath
                        menu.add_item(
                            {
                                "text": _f,
                                "sound": "WINDOWSHOW",
                                "callback": lambda event=None, menuItem=None, fp=_fp, fn=_f: (
                                    self.browse_folder(fp, fn)
                                ),
                            }
                        )
                        num_items += 1

                    elif os.path.isfile(fullpath):
                        if image_pattern.search(fullpath):
                            _f = f
                            _folder = folder
                            menu.add_item(
                                {
                                    "text": _f,
                                    "sound": "WINDOWSHOW",
                                    "style": "item_no_arrow",
                                    "callback": lambda event=None, menuItem=None, fld=_folder, fn=_f: (
                                        self._start_slideshow_from_folder(fld, fn)
                                    ),
                                }
                            )
                            num_items += 1
                except OSError as exc:
                    log.debug("browse_folder: error accessing %s: %s", fullpath, exc)

            if num_items > 0:
                # Add context menu for setting folder as screensaver source
                self._add_folder_context_menu(window, menu, folder)
                window.add_widget(menu)
            else:
                try:
                    from jive.ui.textarea import Textarea

                    window.add_widget(
                        Textarea("text", str(self.string("IMAGE_VIEWER_EMPTY_LIST")))
                    )
                except ImportError as exc:
                    log.debug(
                        "browse_folder: Textarea widget unavailable for empty list: %s",
                        exc,
                    )

        except ImportError:
            log.warn("SimpleMenu widget not available for browse")

        self.tie_and_show_window(window)
        return window

    def _start_slideshow_from_folder(self, folder: str, start_image: str) -> None:
        """Start a slideshow from a specific folder and image."""
        from jive.applets.ImageViewer.ImageSourceLocalStorage import (
            ImageSourceLocalStorage,
        )

        self.start_slideshow(
            False,
            ImageSourceLocalStorage(
                self,
                {
                    "path": folder,
                    "startImage": start_image,
                    "noRecursion": True,
                },
            ),
        )

    def _add_folder_context_menu(self, window: Any, menu: Any, folder: str) -> None:
        """Add a context-menu action for setting the current folder
        as the ImageViewer source folder.

        Mirrors the Lua ``add`` action listener that creates a
        ``ContextMenuWindow`` with a "Use folder" option.
        """
        applet = self

        def _on_add(*_args: Any, **_kw: Any) -> Any:
            try:
                from jive.ui.simplemenu import SimpleMenu
                from jive.ui.window import Window

                path = folder

                # Try to get selected item
                selected_item = None
                if hasattr(menu, "get_selected_item"):
                    selected_item = menu.get_selected_item()
                elif hasattr(menu, "getSelectedItem"):
                    selected_item = menu.getSelectedItem()

                if selected_item is not None:
                    item_text = None
                    if isinstance(selected_item, dict):
                        item_text = selected_item.get("text")
                    elif hasattr(selected_item, "getWidgetValue"):
                        item_text = selected_item.getWidgetValue("text")

                    if item_text:
                        candidate = os.path.join(path, str(item_text))
                        if os.path.isfile(candidate):
                            candidate = path
                        if os.path.isdir(candidate):
                            path = candidate

                if os.path.isdir(path):
                    ctx_window = Window(
                        "text_list",
                        str(applet.string("IMAGE_VIEWER")),
                    )

                    ctx_menu = SimpleMenu(
                        "menu",
                        [
                            {
                                "text": str(
                                    applet.string("IMAGE_VIEWER_CURRENT_FOLDER")
                                )
                                + "\n"
                                + path,
                                "style": "item_info",
                            },
                            {
                                "text": str(applet.string("IMAGE_VIEWER_USE_FOLDER")),
                                "sound": "CLICK",
                                "callback": lambda event=None, menuItem=None, p=path: (
                                    applet._set_folder_as_source(p, ctx_window)
                                ),
                            },
                        ],
                    )

                    ctx_window.add_widget(ctx_menu)
                    ctx_window.show()
            except Exception as exc:
                log.warn("context menu error: %s", exc)

        if hasattr(window, "add_action_listener"):
            window.add_action_listener("add", menu, _on_add)
        elif hasattr(window, "addActionListener"):
            window.addActionListener("add", menu, _on_add)

    def _set_folder_as_source(self, path: str, ctx_window: Any) -> Any:
        """Set *path* as the ImageViewer source folder and hide the
        context window."""
        settings = self.get_settings()
        if settings is not None:
            settings["card.path"] = path
            settings["source"] = "storage"
            self.store_settings()

        if hasattr(ctx_window, "hide"):
            ctx_window.hide()

    # Lua-compatible alias
    browseFolder = browse_folder

    # ------------------------------------------------------------------
    # Screensaver / slideshow lifecycle
    # ------------------------------------------------------------------

    def start_screensaver(self) -> None:
        """Start the Image Viewer as a screensaver.

        Service method called by the ScreenSavers applet.
        """
        log.info("start standard image viewer screensaver")
        self.start_slideshow(True)

    def start_slideshow(
        self,
        is_screensaver: bool = False,
        img_source_override: Any = None,
    ) -> None:
        """Start the slideshow.

        Parameters
        ----------
        is_screensaver : bool
            ``True`` if launched as a screensaver (affects window
            behaviour and available actions).
        img_source_override : ImageSource, optional
            A pre-created image source to use.
        """
        log.info("start image viewer")

        self.init_image_source(img_source_override)
        self.initialized = True
        self.is_screensaver = is_screensaver
        self.show_init_window()
        self.start_slideshow_when_ready()

    def show_init_window(self) -> None:
        """Show the initial loading popup while waiting for images."""
        from jive.ui.window import Window

        popup = Window("black_popup", "")

        if hasattr(popup, "set_auto_hide"):
            popup.set_auto_hide(True)
        if hasattr(popup, "set_show_framework_widgets"):
            popup.set_show_framework_widgets(False)

        # Loading icon
        if self.img_source is not None:
            icon = self.img_source.update_loading_icon()
            if icon is not None:
                popup.add_widget(icon)

        # Loading label
        try:
            from jive.ui.label import Label

            sublabel = Label("subtext", str(self.string("IMAGE_VIEWER_LOADING")))
            popup.add_widget(sublabel)
        except ImportError as exc:
            log.debug("show_init_window: Label widget unavailable: %s", exc)

        self.apply_screensaver_window(popup)

        try:
            from jive.ui.constants import EVENT_KEY_PRESS, EVENT_MOUSE_PRESS

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
            log.warning("show_init_window: failed to add key/mouse listener: %s", exc)

        try:
            from jive.ui.constants import EVENT_WINDOW_POP, EVENT_WINDOW_PUSH

            popup.add_listener(
                EVENT_WINDOW_PUSH | EVENT_WINDOW_POP,
                lambda *_args, **_kw: None,  # type: ignore[arg-type]
            )
        except Exception as exc:
            log.warning(
                "show_init_window: failed to add window push/pop listener: %s", exc
            )

        self.init_window = popup

        try:
            from jive.ui.window import transition_fade_in

            self.tie_and_show_window(popup, transition_fade_in)
        except (ImportError, AttributeError):
            self.tie_and_show_window(popup)

    def start_slideshow_when_ready(self) -> None:
        """Wait for the image list to be ready, then start displaying.

        Uses a polling timer to check readiness up to 50 times
        (10 seconds at 200ms intervals).
        """
        # Stop any existing timer
        if self.next_slide_timer is not None:
            self._stop_timer(self.next_slide_timer)

        if self.img_source is None:
            return

        if not self.img_source.list_ready():
            self.list_check_count += 1

            log.debug("self.list_check_count: %d", self.list_check_count)

            if self.list_check_count >= 50:
                if self.next_slide_timer is not None:
                    self._stop_timer(self.next_slide_timer)
                self.img_source.list_not_ready_error()
                return

            # Try again in a few moments
            log.debug("image list not ready yet...")
            self.next_slide_timer = self._create_timer(
                200, self.start_slideshow_when_ready, once=True
            )
            return

        # Image list is ready
        settings = self.get_settings() or {}
        ordering = settings.get("ordering", "sequential")
        self.img_source.next_image(ordering)
        self.display_slide()

    # ------------------------------------------------------------------
    # Text / info window
    # ------------------------------------------------------------------

    def show_text_window(self) -> None:
        """Show a context menu with image metadata and wallpaper option."""
        try:
            from jive.ui.simplemenu import SimpleMenu
            from jive.ui.window import Window

            window = Window("text_list", str(self.string("IMAGE_VIEWER")))

            menu_items = [
                {
                    "text": str(self.string("IMAGE_VIEWER_SAVE_WALLPAPER")),
                    "sound": "CLICK",
                    "callback": lambda event=None, menuItem=None: self._set_wallpaper(
                        window
                    ),
                },
            ]

            # Add image info lines
            if self.img_source is not None:
                info = self.img_source.get_multiline_text()
                if info:
                    for line in str(info).split("\n"):
                        line = line.strip()
                        if line:
                            menu_items.append(
                                {
                                    "text": line,
                                    "style": "item_no_arrow",
                                }
                            )

            menu = SimpleMenu("menu", menu_items)
            window.add_widget(menu)

            if hasattr(window, "add_action_listener"):
                window.add_action_listener(
                    "back",
                    self,
                    lambda *_args, **_kw: (
                        window.hide() if hasattr(window, "hide") else None
                    ),
                )

            window.show()

        except ImportError:
            log.warn("SimpleMenu widget not available for text window")

    # ------------------------------------------------------------------
    # Wallpaper
    # ------------------------------------------------------------------

    def _set_wallpaper(self, context_window: Any) -> None:
        """Save the current slide as a wallpaper.

        Takes a screenshot of the current window and saves it as a
        BMP file in the user's wallpapers directory.

        Parameters
        ----------
        context_window : Window
            The context menu window to hide after saving.
        """
        if hasattr(context_window, "hide"):
            context_window.hide()

        screen_width, screen_height = _get_screen_size()

        # Determine prefix based on screen resolution
        resolution_prefixes = {
            (320, 240): "bb_",
            (240, 240): "pir_",
            (240, 320): "jive_",
            (480, 272): "fab4_",
            (800, 480): "pcp_",
        }
        prefix = resolution_prefixes.get(
            (screen_width, screen_height),
            self._get_machine() + "_",
        )

        prefix = prefix + str(self.string("IMAGE_VIEWER_SAVED_SLIDE"))

        # Get user directory for wallpapers
        wallpaper_path = self._get_wallpaper_path()
        if wallpaper_path is None:
            log.warn("Cannot determine wallpaper save path")
            return

        timestamp = time.strftime("%Y%m%d%H%M%S")
        filename = "%s %s.bmp" % (prefix, timestamp)
        full_path = os.path.join(wallpaper_path, filename)

        log.info("Taking screenshot: %s", full_path)

        try:
            from jive.ui.surface import Surface

            srf = Surface.new_rgb(screen_width, screen_height)
            if self.window is not None and hasattr(self.window, "draw"):
                from jive.ui.constants import LAYER_ALL

                self.window.draw(srf, LAYER_ALL)
            if hasattr(srf, "save_bmp"):
                srf.save_bmp(full_path)
        except Exception as exc:
            log.warn("Failed to save wallpaper: %s", exc)
            return

        # Set as background
        try:
            from jive.applet_manager import applet_manager

            if applet_manager is not None:
                player = applet_manager.call_service("getCurrentPlayer")
                player_id = None
                if player is not None and hasattr(player, "getId"):
                    player_id = player.getId()
                elif player is not None and hasattr(player, "get_id"):
                    player_id = player.get_id()

                applet_manager.call_service("setBackground", full_path, player_id, True)
        except Exception as exc:
            log.error(
                "_set_wallpaper: failed to set background via service: %s",
                exc,
                exc_info=True,
            )

        # Remove old screenshots — only keep one to save disk space
        try:
            import re

            pattern = re.compile(re.escape(prefix.lower()) + r".*\.bmp$", re.IGNORECASE)
            for img in os.listdir(wallpaper_path):
                if pattern.match(img.lower()) and img.lower() != filename.lower():
                    old_path = os.path.join(wallpaper_path, img)
                    log.warn("removing old saved wallpaper: %s", img)
                    try:
                        os.remove(old_path)
                    except OSError as exc:
                        log.debug(
                            "_set_wallpaper: failed to remove old wallpaper %s: %s",
                            old_path,
                            exc,
                        )
        except OSError as exc:
            log.debug("_set_wallpaper: failed to list wallpaper directory: %s", exc)

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def setup_event_handlers(self, window: Any) -> None:
        """Set up navigation and interaction event handlers on *window*.

        Parameters
        ----------
        window : Window
            The slideshow display window.
        """
        applet = self

        def _next_slide(*_args: Any, **_kw: Any) -> Any:
            if (
                applet.img_source is not None
                and applet.img_source.image_ready()
                and not applet.is_rendering
            ):
                log.debug("request next slide")
                settings = applet.get_settings() or {}
                applet.img_source.next_image(settings.get("ordering", "sequential"))
                applet.display_slide()
            else:
                log.warn("don't show next image - current image isn't even ready yet")

        def _previous_slide(*_args: Any, **_kw: Any) -> Any:
            if (
                applet.img_source is not None
                and applet.img_source.image_ready()
                and not applet.is_rendering
            ):
                log.debug("request prev slide")
                applet.use_fast_transition = True
                settings = applet.get_settings() or {}
                applet.img_source.previous_image(settings.get("ordering", "sequential"))
                applet.display_slide()
            else:
                log.warn("don't show next image - current image isn't even ready yet")

        def _show_text(*_args: Any, **_kw: Any) -> Any:
            applet.show_text_window()

        # Action listeners
        if hasattr(window, "add_action_listener"):
            window.add_action_listener("add", applet, _show_text)
            window.add_action_listener("go", applet, _next_slide)
            window.add_action_listener("up", applet, _next_slide)
            window.add_action_listener("down", applet, _previous_slide)
            window.add_action_listener("back", applet, lambda *_args, **_kw: None)
        elif hasattr(window, "addActionListener"):
            window.addActionListener("add", applet, _show_text)
            window.addActionListener("go", applet, _next_slide)
            window.addActionListener("up", applet, _next_slide)
            window.addActionListener("down", applet, _previous_slide)
            window.addActionListener("back", applet, lambda *_args, **_kw: None)

        # Mouse / touch events
        try:
            from jive.ui.constants import (
                EVENT_MOUSE_DRAG,
                EVENT_MOUSE_HOLD,
                EVENT_MOUSE_PRESS,
                EVENT_SCROLL,
            )

            window.add_listener(
                EVENT_MOUSE_PRESS,
                lambda event=None: applet._on_mouse_press(
                    event, _next_slide, _previous_slide
                ),
            )

            window.add_listener(
                EVENT_MOUSE_HOLD,
                lambda event=None: _show_text(),
            )

            window.add_listener(
                EVENT_MOUSE_DRAG,
                lambda event=None: applet._on_mouse_drag(event),
            )

            window.add_listener(
                EVENT_SCROLL,
                lambda event=None: applet._on_scroll(
                    event, _next_slide, _previous_slide
                ),
            )
        except (ImportError, AttributeError) as exc:
            log.debug(
                "setup_event_handlers: UI constants unavailable for mouse/scroll listeners: %s",
                exc,
            )

    def _on_mouse_press(
        self, event: Any, next_fn: Callable[..., Any], prev_fn: Callable[..., Any]
    ) -> Any:
        """Handle mouse press events for slide navigation."""
        if self.drag_offset > 10 and event is not None:
            try:
                x, y = 0, 0
                if hasattr(event, "get_mouse"):
                    x, y = event.get_mouse()
                elif hasattr(event, "getMouse"):
                    x, y = event.getMouse()

                offset = y - self.drag_start

                log.debug("drag offset: %d", offset)
                if offset > 10:
                    prev_fn()
                elif offset < -10:
                    next_fn()
            except Exception as exc:
                log.warning("_on_mouse_press: drag navigation failed: %s", exc)

            self.drag_start = -1
            self.drag_offset = 0
        else:
            # Simple tap — wake up
            self.close_remote_screensaver()

    def _on_mouse_drag(self, event: Any) -> None:
        """Handle mouse drag events."""
        if self.drag_start < 0 and event is not None:
            try:
                if hasattr(event, "get_mouse"):
                    _, y = event.get_mouse()
                elif hasattr(event, "getMouse"):
                    _, y = event.getMouse()
                else:
                    y = 0
                self.drag_start = y
            except Exception as exc:
                log.warning("_on_mouse_drag: failed to get mouse position: %s", exc)

        self.drag_offset += 1

    def _on_scroll(
        self, event: Any, next_fn: Callable[..., Any], prev_fn: Callable[..., Any]
    ) -> Any:
        """Handle scroll events for slide navigation.

        Debounces rapid scrolling to avoid overwhelming image fetching.
        """
        scroll = 0
        if event is not None:
            try:
                if hasattr(event, "get_scroll"):
                    scroll = event.get_scroll()
                elif hasattr(event, "getScroll"):
                    scroll = event.getScroll()
            except Exception as exc:
                log.warning("_on_scroll: failed to get scroll value: %s", exc)

        direction = 1 if scroll > 0 else -1

        now = self._get_ticks()
        if (
            self.last_scroll_t is None
            or self.last_scroll_t + _MIN_SCROLL_INTERVAL < now
            or self.last_scroll_dir != direction
        ):
            self.last_scroll_t = now
            self.last_scroll_dir = direction
            if scroll > 0:
                return next_fn()
            else:
                return prev_fn()

    # ------------------------------------------------------------------
    # Remote screensaver services
    # ------------------------------------------------------------------

    def register_remote_screensaver(self, server_data: Dict[str, Any]) -> None:
        """Service: register a remote (server-pushed) screensaver.

        Parameters
        ----------
        server_data : dict
            Server connection parameters including ``text``, ``id``,
            ``cmd``, ``playerId``, ``server``, ``appParameters``.
        """
        server_data["isScreensaver"] = True

        try:
            from jive.applet_manager import applet_manager

            if applet_manager is not None:
                applet_manager.call_service(
                    "addScreenSaver",
                    server_data.get("text", "Remote Screensaver"),
                    "ImageViewer",
                    "openRemoteScreensaver",
                    None,
                    None,
                    100,
                    "closeRemoteScreensaver",
                    server_data,
                    server_data.get("id"),
                )
        except Exception as exc:
            log.warn("register_remote_screensaver failed: %s", exc)

    # Lua-compatible alias
    registerRemoteScreensaver = register_remote_screensaver

    def unregister_remote_screensaver(self, ss_id: Any) -> None:
        """Service: unregister a remote screensaver.

        Parameters
        ----------
        ss_id : Any
            The screensaver ID to remove.
        """
        try:
            from jive.applet_manager import applet_manager

            if applet_manager is not None:
                applet_manager.call_service(
                    "removeScreenSaver",
                    "ImageViewer",
                    "openRemoteScreensaver",
                    None,
                    ss_id,
                )
        except Exception as exc:
            log.warn("unregister_remote_screensaver failed: %s", exc)

    # Lua-compatible alias
    unregisterRemoteScreensaver = unregister_remote_screensaver

    def open_remote_screensaver(
        self, force: bool = False, server_data: Optional[Dict[str, Any]] = None
    ) -> None:
        """Service: open a remote screensaver.

        Parameters
        ----------
        force : bool
            Whether to force display even if blocked.
        server_data : dict, optional
            Server connection parameters.
        """
        if server_data is None:
            server_data = {}

        self.server_data = server_data

        from jive.applets.ImageViewer.ImageSourceServer import ImageSourceServer

        is_ss = server_data.get("isScreensaver", False)
        self.start_slideshow(is_ss, ImageSourceServer(self, server_data))

    # Lua-compatible alias
    openRemoteScreensaver = open_remote_screensaver

    def close_remote_screensaver(self) -> None:
        """Service: close the remote screensaver and clean up timers."""
        self._stop_timers()

        if self.init_window is not None:
            if hasattr(self.init_window, "hide"):
                self.init_window.hide()
            self.init_window = None

        if self.window is not None:
            if hasattr(self.window, "hide"):
                self.window.hide()
            self.window = None

    # Lua-compatible alias
    closeRemoteScreensaver = close_remote_screensaver

    # ------------------------------------------------------------------
    # Media manager callbacks
    # ------------------------------------------------------------------

    def mm_image_viewer_menu(self, dev_name: str = "") -> None:
        """Service: start slideshow from a media-manager device.

        Parameters
        ----------
        dev_name : str
            Device sub-path appended to ``card.path``.
        """
        from jive.applets.ImageViewer.ImageSourceLocalStorage import (
            ImageSourceLocalStorage,
        )

        settings = self.get_settings() or {}
        imgpath = settings.get("card.path", "/media")

        log.info("mmImageViewerMenu: %s", imgpath + dev_name)
        self.start_slideshow(
            False, ImageSourceLocalStorage(self, {"path": imgpath + dev_name})
        )

    # Lua-compatible alias
    mmImageViewerMenu = mm_image_viewer_menu

    def mm_image_viewer_browse(self, dev_name: str = "") -> None:
        """Service: browse images from a media-manager device.

        Parameters
        ----------
        dev_name : str
            Device sub-path appended to ``card.path``.
        """
        settings = self.get_settings() or {}
        imgpath = settings.get("card.path", "/media")

        log.info("mmImageViewerBrowse: %s", imgpath + dev_name)
        self.browse_folder(imgpath + dev_name)

    # Lua-compatible alias
    mmImageViewerBrowse = mm_image_viewer_browse

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def free(self) -> bool:
        """Clean up the applet and release all resources."""
        log.info("destructor of image viewer")

        if self._task is not None:
            try:
                if hasattr(self._task, "remove_task"):
                    self._task.remove_task()
            except Exception as exc:
                log.error(
                    "free: failed to remove background task: %s", exc, exc_info=True
                )

        if self.window is not None:
            if hasattr(self.window, "set_allow_screensaver"):
                self.window.set_allow_screensaver(True)

        self._stop_timers()

        if self.img_source is not None:
            self.img_source.free()

        return True

    def _stop_timers(self) -> None:
        """Stop all active timers."""
        if self.next_slide_timer is not None:
            self._stop_timer(self.next_slide_timer)
        if self.check_foto_timer is not None:
            self._stop_timer(self.check_foto_timer)

    # ------------------------------------------------------------------
    # Screensaver window setup
    # ------------------------------------------------------------------

    def apply_screensaver_window(self, window: Any) -> None:
        """Apply screensaver-mode settings to *window*.

        Disables the screensaver on the window and registers it with
        the ScreenSavers manager if available.

        Parameters
        ----------
        window : Window
            The window to configure.
        """
        # Motion listener (if server doesn't allow motion)
        if self.server_data and not self.server_data.get("allowMotion", True):
            try:
                from jive.ui.constants import EVENT_MOTION

                window.add_listener(
                    EVENT_MOTION,
                    lambda *_args, **_kw: (
                        window.hide() if hasattr(window, "hide") else None
                    ),
                )
            except Exception as exc:
                log.warning(
                    "apply_screensaver_window: failed to add motion listener: %s", exc
                )

        if hasattr(window, "set_allow_screensaver"):
            window.set_allow_screensaver(False)

        try:
            from jive.applet_manager import applet_manager

            if applet_manager is not None:
                manager = applet_manager.get_applet_instance("ScreenSavers")
                if manager is not None and hasattr(manager, "screensaver_window"):
                    manager.screensaver_window(
                        window,
                        True,
                        ["add", "go", "up", "down", "back"],
                        None,
                        "ImageViewer",
                    )
                elif manager is not None and hasattr(manager, "screensaverWindow"):
                    manager.screensaverWindow(
                        window,
                        True,
                        ["add", "go", "up", "down", "back"],
                        None,
                        "ImageViewer",
                    )
        except Exception as exc:
            log.error(
                "apply_screensaver_window: failed to register with ScreenSavers manager: %s",
                exc,
                exc_info=True,
            )

    # Lua-compatible alias
    applyScreensaverWindow = apply_screensaver_window

    # ------------------------------------------------------------------
    # Slide display
    # ------------------------------------------------------------------

    def display_slide(self) -> None:
        """Display the current slide.

        If the image is not yet ready, polls at 200ms intervals up to
        50 times.  When the image is ready, renders it in a background
        task.
        """
        if not self.initialized:
            self.init_image_source()
            self.initialized = True

        # Stop check timer
        if self.check_foto_timer is not None:
            self._stop_timer(self.check_foto_timer)

        if (
            self.next_slide_timer is not None
            and hasattr(self.next_slide_timer, "is_running")
            and self.next_slide_timer.is_running()
        ):
            # Restart to give this image its full delay
            self._restart_timer(self.next_slide_timer)

        if self.img_source is None:
            return

        if not self.img_source.image_ready() and self.image_check_count < 50:
            self.image_check_count += 1

            log.debug("image not ready, try again...")

            self.check_foto_timer = self._create_timer(
                200, self.display_slide, once=True
            )
            return

        self.image_check_count = 0

        log.debug("image rendering")
        self.is_rendering = True

        # Stop next slide timer since we have a good image
        if self.next_slide_timer is not None:
            self._stop_timer(self.next_slide_timer)

        # Render the image
        self._render_image()

    def _render_image(self) -> None:
        """Render the current image to a window.

        Handles rotation, scaling, centering, text overlay, and
        transition animation.
        """
        screen_width, screen_height = _get_screen_size()

        settings = self.get_settings() or {}
        rotation = settings.get("rotation", False)
        full_screen = settings.get("fullscreen", False)
        ordering = settings.get("ordering", "sequential")
        textinfo = settings.get("textinfo", False)

        device_landscape = (
            (screen_width / screen_height) > 1 if screen_height > 0 else True
        )

        if self.img_source is None:
            self.is_rendering = False
            return

        image = self.img_source.get_image()
        w, h = 0, 0

        if image is not None:
            try:
                if hasattr(image, "get_size"):
                    w, h = image.get_size()
                elif hasattr(image, "getSize"):
                    w, h = image.getSize()
            except Exception as exc:
                log.warning("_render_image: failed to get image size: %s", exc)

        if image is not None and w > 0 and h > 0:
            self.image_error = None

            if self.img_source.use_auto_zoom():
                image_landscape = (w / h) > 1 if h > 0 else True

                # Determine whether to rotate
                if rotation and device_landscape != image_landscape:
                    try:
                        if hasattr(image, "rotozoom"):
                            image = image.rotozoom(-90, 1, 1)
                            if hasattr(image, "get_size"):
                                w, h = image.get_size()
                            elif hasattr(image, "getSize"):
                                w, h = image.getSize()
                    except Exception as exc:
                        log.warn("rotation failed: %s", exc)

                # Determine scaling factor
                if w > 0 and h > 0:
                    zoom_x = screen_width / w
                    zoom_y = screen_height / h

                    if full_screen:
                        zoom = max(zoom_x, zoom_y)
                    else:
                        zoom = min(zoom_x, zoom_y)

                    # Scale image if needed
                    if zoom != 1:
                        try:
                            if hasattr(image, "rotozoom"):
                                image = image.rotozoom(0, zoom, 1)
                                if hasattr(image, "get_size"):
                                    w, h = image.get_size()
                                elif hasattr(image, "getSize"):
                                    w, h = image.getSize()
                        except Exception as exc:
                            log.warn("zoom failed: %s", exc)

            # Place scaled image centered on a black background
            try:
                from jive.ui.surface import Surface

                tot_img = Surface.new_rgba(screen_width, screen_height)
                if hasattr(tot_img, "filled_rectangle"):
                    tot_img.filled_rectangle(
                        0, 0, screen_width, screen_height, 0x000000FF
                    )
                elif hasattr(tot_img, "filledRectangle"):
                    tot_img.filledRectangle(
                        0, 0, screen_width, screen_height, 0x000000FF
                    )

                x = int(math.floor((screen_width - w) / 2))
                y = int(math.floor((screen_height - h) / 2))

                if hasattr(image, "blit"):
                    image.blit(tot_img, x, y)

                image = tot_img

                # Add text overlay if enabled
                if textinfo:
                    self._draw_text_overlay(image, screen_width, screen_height)

            except Exception as exc:
                log.warn("image compositing failed: %s", exc)

            # Create the display window
            try:
                from jive.ui.icon import Icon
                from jive.ui.window import Window

                window = Window("window")
                window.add_widget(Icon("icon", image))

                if self.is_screensaver:
                    self.apply_screensaver_window(window)
                else:
                    self.setup_event_handlers(window)

                # Replace or show the window
                if self.window is not None:
                    self.tie_window(window)
                    if self.use_fast_transition:
                        try:
                            from jive.ui.window import transition_fade_in

                            transition = transition_fade_in
                        except (ImportError, AttributeError):
                            transition = None
                        self.use_fast_transition = False
                    else:
                        transition = self.get_transition()

                    self.window = window
                    if hasattr(window, "show_instead"):
                        window.show_instead(transition)
                    elif hasattr(window, "showInstead"):
                        window.showInstead(transition)
                    else:
                        window.show(transition)
                else:
                    self.window = window
                    try:
                        from jive.ui.window import transition_fade_in

                        self.tie_and_show_window(window, transition_fade_in)
                    except (ImportError, AttributeError):
                        self.tie_and_show_window(window)

                # No screensavers on the slideshow window
                if hasattr(self.window, "set_allow_screensaver"):
                    self.window.set_allow_screensaver(False)

                # No icon bar
                if hasattr(self.window, "set_show_framework_widgets"):
                    self.window.set_show_framework_widgets(False)

            except Exception as exc:
                log.warn("window creation failed: %s", exc)

        else:
            # Invalid image
            if self.image_error is None and self.img_source is not None:
                self.image_error = str(self.img_source.get_error_message())
                log.error("Invalid image object found: %s", self.image_error)

                try:
                    popup = self.img_source.popup_message(
                        str(self.string("IMAGE_VIEWER_INVALID_IMAGE")),
                        self.image_error,
                    )
                    if popup is not None:
                        delay = settings.get("delay", 10000)
                        if hasattr(popup, "addTimer"):
                            popup.addTimer(
                                delay,
                                lambda: (
                                    popup.hide() if hasattr(popup, "hide") else None
                                ),
                            )
                except Exception as exc:
                    log.warning("_render_image: failed to show error popup: %s", exc)

        # Start timer for next photo
        delay = settings.get("delay", 10000)
        if self.window is not None:
            self.next_slide_timer = self._create_timer(
                delay,
                self._advance_to_next_slide,
                once=True,
                window=self.window,
            )

        log.debug("image rendering done")

        # Free memory
        gc.collect()

        self.is_rendering = False

    def _advance_to_next_slide(self) -> None:
        """Timer callback to advance to the next slide."""
        if self.img_source is not None:
            settings = self.get_settings() or {}
            self.img_source.next_image(settings.get("ordering", "sequential"))
            self.display_slide()

    def _draw_text_overlay(
        self, image: Any, screen_width: int, screen_height: int
    ) -> None:
        """Draw text metadata overlay at the bottom of the image.

        Parameters
        ----------
        image : Surface
            The composited image surface.
        screen_width : int
            Screen width in pixels.
        screen_height : int
            Screen height in pixels.
        """
        if self.img_source is None:
            return

        text_data = self.img_source.get_text()
        if text_data is None:
            return

        # Parse text — it may be a single string or a tuple of up to 3 parts
        txt_left = None
        txt_center = None
        txt_right = None

        if isinstance(text_data, (list, tuple)):
            if len(text_data) >= 1:
                txt_left = text_data[0] if text_data[0] else None
            if len(text_data) >= 2:
                txt_center = text_data[1] if text_data[1] else None
            if len(text_data) >= 3:
                txt_right = text_data[2] if text_data[2] else None
        elif isinstance(text_data, str):
            txt_left = text_data if text_data else None

        if txt_left is None and txt_center is None and txt_right is None:
            return

        try:
            from jive.ui.font import Font
            from jive.ui.surface import Surface

            # Draw background bar
            if hasattr(image, "filled_rectangle"):
                image.filled_rectangle(
                    0, screen_height - 20, screen_width, screen_height, 0x000000FF
                )
            elif hasattr(image, "filledRectangle"):
                image.filledRectangle(
                    0, screen_height - 20, screen_width, screen_height, 0x000000FF
                )

            font_bold = Font.load("fonts/FreeSansBold.ttf", 10)
            font_regular = Font.load("fonts/FreeSans.ttf", 10)

            if txt_left and font_bold:
                txt_srf = Surface.draw_text(font_bold, 0xFFFFFFFF, str(txt_left))
                if txt_srf is not None and hasattr(txt_srf, "blit"):
                    offset = font_bold.offset() if hasattr(font_bold, "offset") else 0
                    txt_srf.blit(image, 5, screen_height - 15 - offset)

            if txt_center and font_regular:
                title_width = (
                    font_regular.width(str(txt_center))
                    if hasattr(font_regular, "width")
                    else 0
                )
                txt_srf = Surface.draw_text(font_regular, 0xFFFFFFFF, str(txt_center))
                if txt_srf is not None and hasattr(txt_srf, "blit"):
                    offset = (
                        font_regular.offset() if hasattr(font_regular, "offset") else 0
                    )
                    txt_srf.blit(
                        image,
                        int((screen_width - title_width) / 2),
                        screen_height - 15 - offset,
                    )

            if txt_right and font_regular:
                title_width = (
                    font_regular.width(str(txt_right))
                    if hasattr(font_regular, "width")
                    else 0
                )
                txt_srf = Surface.draw_text(font_regular, 0xFFFFFFFF, str(txt_right))
                if txt_srf is not None and hasattr(txt_srf, "blit"):
                    offset = (
                        font_regular.offset() if hasattr(font_regular, "offset") else 0
                    )
                    txt_srf.blit(
                        image,
                        screen_width - 5 - title_width,
                        screen_height - 15 - offset,
                    )

        except Exception as exc:
            log.warn("text overlay failed: %s", exc)

    # ------------------------------------------------------------------
    # Settings menu
    # ------------------------------------------------------------------

    def open_settings(self) -> Any:
        """Open the Image Viewer settings menu.

        Provides options for source, source-specific settings, delay,
        ordering, transition, zoom, rotation, and text info.
        """
        log.info("image viewer settings")
        self.init_image_source()

        from jive.ui.window import Window

        window = Window(
            "text_list",
            str(self.string("IMAGE_VIEWER_SETTINGS")),
            "settingstitle",
        )

        settings_menu_items = [
            {
                "text": str(self.string("IMAGE_VIEWER_SOURCE_SETTINGS")),
                "sound": "WINDOWSHOW",
                "callback": lambda event=None, menuItem=None: (
                    self.source_specific_settings(menuItem)
                ),
            },
            {
                "text": str(self.string("IMAGE_VIEWER_DELAY")),
                "sound": "WINDOWSHOW",
                "callback": lambda event=None, menuItem=None: self.define_delay(
                    menuItem
                ),
            },
            {
                "text": str(self.string("IMAGE_VIEWER_ORDERING")),
                "sound": "WINDOWSHOW",
                "callback": lambda event=None, menuItem=None: self.define_ordering(
                    menuItem
                ),
            },
            {
                "text": str(self.string("IMAGE_VIEWER_TRANSITION")),
                "sound": "WINDOWSHOW",
                "callback": lambda event=None, menuItem=None: self.define_transition(
                    menuItem
                ),
            },
            {
                "text": str(self.string("IMAGE_VIEWER_ZOOM")),
                "sound": "WINDOWSHOW",
                "callback": lambda event=None, menuItem=None: self.define_full_screen(
                    menuItem
                ),
            },
            {
                "text": str(self.string("IMAGE_VIEWER_TEXTINFO")),
                "sound": "WINDOWSHOW",
                "callback": lambda event=None, menuItem=None: self.define_text_info(
                    menuItem
                ),
            },
        ]

        # Add rotation option if device supports it
        if self._has_device_rotation():
            settings_menu_items.insert(
                4,
                {
                    "text": str(self.string("IMAGE_VIEWER_ROTATION")),
                    "sound": "WINDOWSHOW",
                    "callback": lambda event=None, menuItem=None: self.define_rotation(
                        menuItem
                    ),
                },
            )

        # Add source selection if local storage is available
        if self._has_local_storage():
            settings_menu_items.insert(
                0,
                {
                    "text": str(self.string("IMAGE_VIEWER_SOURCE")),
                    "sound": "WINDOWSHOW",
                    "callback": lambda event=None, menuItem=None: self.define_source(
                        menuItem
                    ),
                },
            )

        try:
            from jive.ui.simplemenu import SimpleMenu

            window.add_widget(SimpleMenu("menu", settings_menu_items))
        except ImportError:
            log.warn("SimpleMenu not available for settings")

        self.tie_and_show_window(window)
        return window

    # Lua-compatible alias
    openSettings = open_settings

    def source_specific_settings(self, menu_item: Any = None) -> Any:
        """Open source-specific settings window."""
        from jive.ui.window import Window

        title = ""
        if isinstance(menu_item, dict):
            title = menu_item.get("text", "")
        elif menu_item is not None and hasattr(menu_item, "text"):
            title = str(menu_item.text)

        window = Window("window", title)

        if self.img_source is not None:
            window = self.img_source.settings(window)

        self.tie_and_show_window(window)
        return window

    # Lua-compatible alias
    sourceSpecificSettings = source_specific_settings

    # ------------------------------------------------------------------
    # Settings: Ordering
    # ------------------------------------------------------------------

    def define_ordering(self, menu_item: Any = None) -> Any:
        """Show ordering selection (sequential / random)."""
        return self._define_radio_setting(
            menu_item,
            "ordering",
            [
                ("IMAGE_VIEWER_ORDERING_SEQUENTIAL", "sequential"),
                ("IMAGE_VIEWER_ORDERING_RANDOM", "random"),
            ],
            self.set_ordering,
        )

    # Lua-compatible alias
    defineOrdering = define_ordering

    # ------------------------------------------------------------------
    # Settings: Transition
    # ------------------------------------------------------------------

    def define_transition(self, menu_item: Any = None) -> Any:
        """Show transition selection menu."""
        return self._define_radio_setting(
            menu_item,
            "transition",
            [
                ("IMAGE_VIEWER_TRANSITION_RANDOM", "random"),
                ("IMAGE_VIEWER_TRANSITION_FADE", "fade"),
                ("IMAGE_VIEWER_TRANSITION_INSIDE_OUT", "boxout"),
                ("IMAGE_VIEWER_TRANSITION_TOP_DOWN", "topdown"),
                ("IMAGE_VIEWER_TRANSITION_BOTTOM_UP", "bottomup"),
                ("IMAGE_VIEWER_TRANSITION_LEFT_RIGHT", "leftright"),
                ("IMAGE_VIEWER_TRANSITION_RIGHT_LEFT", "rightleft"),
                ("IMAGE_VIEWER_TRANSITION_PUSH_LEFT", "pushleft"),
                ("IMAGE_VIEWER_TRANSITION_PUSH_RIGHT", "pushright"),
            ],
            self.set_transition,
        )

    # Lua-compatible alias
    defineTransition = define_transition

    # ------------------------------------------------------------------
    # Settings: Source
    # ------------------------------------------------------------------

    def define_source(self, menu_item: Any = None) -> Any:
        """Show image source selection menu."""
        settings = self.get_settings() or {}
        source = settings.get("source", "http")

        items = [
            ("IMAGE_VIEWER_SOURCE_HTTP", "http"),
            ("IMAGE_VIEWER_SOURCE_FLICKR", "flickr"),
        ]

        # Add local storage sources if available
        if self._has_sd_card():
            items.insert(0, ("IMAGE_VIEWER_SOURCE_CARD", "card"))

        if self._has_usb():
            items.insert(0, ("IMAGE_VIEWER_SOURCE_USB", "usb"))

        if self._has_local_storage():
            items.insert(0, ("IMAGE_VIEWER_SOURCE_LOCAL_STORAGE", "storage"))

        return self._define_radio_setting(
            menu_item,
            "source",
            items,
            self.set_source,
        )

    # Lua-compatible alias
    defineSource = define_source

    # ------------------------------------------------------------------
    # Settings: Delay
    # ------------------------------------------------------------------

    def define_delay(self, menu_item: Any = None) -> Any:
        """Show slide delay selection menu."""
        return self._define_radio_setting(
            menu_item,
            "delay",
            [
                ("IMAGE_VIEWER_DELAY_5_SEC", 5000),
                ("IMAGE_VIEWER_DELAY_10_SEC", 10000),
                ("IMAGE_VIEWER_DELAY_20_SEC", 20000),
                ("IMAGE_VIEWER_DELAY_30_SEC", 30000),
                ("IMAGE_VIEWER_DELAY_1_MIN", 60000),
            ],
            self.set_delay,
        )

    # Lua-compatible alias
    defineDelay = define_delay

    # ------------------------------------------------------------------
    # Settings: Fullscreen
    # ------------------------------------------------------------------

    def define_full_screen(self, menu_item: Any = None) -> Any:
        """Show zoom mode selection (fit / fill)."""
        return self._define_radio_setting(
            menu_item,
            "fullscreen",
            [
                ("IMAGE_VIEWER_ZOOM_PICTURE", False),
                ("IMAGE_VIEWER_ZOOM_SCREEN", True),
            ],
            self.set_full_screen,
        )

    # Lua-compatible alias
    defineFullScreen = define_full_screen

    # ------------------------------------------------------------------
    # Settings: Rotation
    # ------------------------------------------------------------------

    def define_rotation(self, menu_item: Any = None) -> Any:
        """Show rotation enable/disable selection."""
        return self._define_radio_setting(
            menu_item,
            "rotation",
            [
                ("IMAGE_VIEWER_ROTATION_YES", True),
                ("IMAGE_VIEWER_ROTATION_NO", False),
            ],
            self.set_rotation,
        )

    # Lua-compatible alias
    defineRotation = define_rotation

    # ------------------------------------------------------------------
    # Settings: Text info
    # ------------------------------------------------------------------

    def define_text_info(self, menu_item: Any = None) -> Any:
        """Show text info enable/disable selection."""
        return self._define_radio_setting(
            menu_item,
            "textinfo",
            [
                ("IMAGE_VIEWER_TEXTINFO_YES", True),
                ("IMAGE_VIEWER_TEXTINFO_NO", False),
            ],
            self.set_text_info,
        )

    # Lua-compatible alias
    defineTextInfo = define_text_info

    # ------------------------------------------------------------------
    # Settings helpers (radio-button menus)
    # ------------------------------------------------------------------

    def _define_radio_setting(
        self,
        menu_item: Any,
        setting_key: str,
        options: List[Tuple[str, Any]],
        setter: Callable[..., Any],
    ) -> Any:
        """Create a radio-button settings window.

        Parameters
        ----------
        menu_item : Any
            The menu item dict (used for the window title).
        setting_key : str
            The settings key to read the current value from.
        options : list of (label_token, value) tuples
            The available options.
        setter : callable
            A function ``(value)`` to call when an option is selected.

        Returns
        -------
        Window
            The settings window.
        """
        try:
            from jive.ui.radiobutton import (  # type: ignore[import-not-found]
                RadioButton,
            )
            from jive.ui.radiogroup import RadioGroup  # type: ignore[import-not-found]
            from jive.ui.simplemenu import SimpleMenu
            from jive.ui.window import Window

            settings = self.get_settings() or {}
            current = settings.get(setting_key)

            title = ""
            if isinstance(menu_item, dict):
                title = menu_item.get("text", "")
            elif menu_item is not None and hasattr(menu_item, "text"):
                title = str(menu_item.text)

            window = Window("text_list", title, "settingstitle")
            group = RadioGroup()

            items = []
            for label_token, value in options:
                v = value  # Capture in closure
                items.append(
                    {
                        "text": str(self.string(label_token)),
                        "style": "item_choice",
                        "check": RadioButton(
                            "radio",
                            group,
                            lambda *_args, _v=v: setter(_v),
                            current == v,
                        ),
                    }
                )

            window.add_widget(SimpleMenu("menu", items))
            self.tie_and_show_window(window)
            return window

        except ImportError:
            log.warn("RadioButton/SimpleMenu not available for settings")
            return None

    # ------------------------------------------------------------------
    # Settings setters
    # ------------------------------------------------------------------

    def set_ordering(self, ordering: str) -> None:
        """Set the image ordering mode."""
        settings = self.get_settings()
        if settings is not None:
            settings["ordering"] = ordering
            self.store_settings()

    def set_delay(self, delay: int) -> None:
        """Set the slide delay in milliseconds."""
        settings = self.get_settings()
        if settings is not None:
            settings["delay"] = delay
            self.store_settings()

    def set_source(self, source: str) -> None:
        """Set the image source type and reinitialize."""
        settings = self.get_settings()
        if settings is not None:
            settings["source"] = source
            self.store_settings()
        self.set_image_source()

    def set_transition(self, transition: str) -> None:
        """Set the transition effect."""
        settings = self.get_settings()
        if settings is not None:
            settings["transition"] = transition
            self.store_settings()

    def set_rotation(self, rotation: bool) -> None:
        """Set whether image rotation is enabled."""
        settings = self.get_settings()
        if settings is not None:
            settings["rotation"] = rotation
            self.store_settings()

    def set_full_screen(self, fullscreen: bool) -> None:
        """Set whether fullscreen zoom is enabled."""
        settings = self.get_settings()
        if settings is not None:
            settings["fullscreen"] = fullscreen
            self.store_settings()

    def set_text_info(self, textinfo: bool) -> None:
        """Set whether text info overlay is enabled."""
        settings = self.get_settings()
        if settings is not None:
            settings["textinfo"] = textinfo
            self.store_settings()

    # Lua-compatible aliases
    setOrdering = set_ordering
    setDelay = set_delay
    setSource = set_source
    setTransition = set_transition
    setRotation = set_rotation
    setFullScreen = set_full_screen
    setTextInfo = set_text_info

    # ------------------------------------------------------------------
    # Transition selection
    # ------------------------------------------------------------------

    def get_transition(self) -> Optional[Callable[..., Any]]:
        """Return the transition function for the current setting.

        Returns
        -------
        callable or None
            A transition function, or ``None`` for the default.
        """
        settings = self.get_settings() or {}
        trans = settings.get("transition", "fade")

        if trans == "random":
            if self.transitions:
                return random.choice(self.transitions)
            return None
        elif trans == "boxout":
            return transition_box_out
        elif trans == "topdown":
            return transition_top_down
        elif trans == "bottomup":
            return transition_bottom_up
        elif trans == "leftright":
            return transition_left_right
        elif trans == "rightleft":
            return transition_right_left
        elif trans == "fade":
            try:
                from jive.ui.window import transition_fade_in

                return transition_fade_in
            except (ImportError, AttributeError):
                return None
        elif trans == "pushleft":
            try:
                from jive.ui.window import transition_push_left

                return transition_push_left
            except (ImportError, AttributeError):
                return None
        elif trans == "pushright":
            try:
                from jive.ui.window import transition_push_right

                return transition_push_right
            except (ImportError, AttributeError):
                return None

        return None

    # Lua-compatible alias
    getTransition = get_transition

    # ------------------------------------------------------------------
    # Lua-compatible aliases for lifecycle methods
    # ------------------------------------------------------------------

    startScreensaver = start_screensaver
    startSlideshow = start_slideshow
    showInitWindow = show_init_window
    startSlideshowWhenReady = start_slideshow_when_ready
    showTextWindow = show_text_window
    setupEventHandlers = setup_event_handlers
    displaySlide = display_slide
    initImageSource = init_image_source
    setImageSource = set_image_source

    # ------------------------------------------------------------------
    # System capability helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_system_instance() -> Any:
        """Get the System *instance* from AppletManager or JiveMain.

        In the Lua original, ``System`` is a module-level singleton.
        In Python, the single ``System`` instance is owned by
        ``AppletManager`` (which receives it from ``JiveMain``).
        """
        try:
            from jive.applet_manager import applet_manager as _mgr

            if _mgr is not None and hasattr(_mgr, "system"):
                sys_inst = _mgr.system
                if sys_inst is not None:
                    return sys_inst
        except (ImportError, AttributeError):
            pass

        # Fallback: try JiveMain directly
        try:
            from jive.jive_main import jive_main as _jm

            if _jm is not None and hasattr(_jm, "_system"):
                return _jm._system
        except (ImportError, AttributeError):
            pass

        return None

    @staticmethod
    def _has_device_rotation() -> bool:
        """Check if the device supports image rotation."""
        _sys = ImageViewerApplet._get_system_instance()
        if _sys is not None:
            try:
                return _sys.has_device_rotation()  # type: ignore[no-any-return]
            except Exception as exc:
                log.debug("_has_device_rotation: %s", exc)
        return False

    @staticmethod
    def _has_local_storage() -> bool:
        """Check if the device has local storage."""
        _sys = ImageViewerApplet._get_system_instance()
        if _sys is not None:
            try:
                return _sys.has_local_storage()  # type: ignore[no-any-return]
            except Exception as exc:
                log.debug("_has_local_storage: %s", exc)
        return True  # Default to True for desktop

    @staticmethod
    def _has_sd_card() -> bool:
        """Check if the device has an SD card slot."""
        _sys = ImageViewerApplet._get_system_instance()
        if _sys is not None:
            try:
                return _sys.has_sd_card()  # type: ignore[no-any-return]
            except Exception as exc:
                log.debug("_has_sd_card: %s", exc)
        return False

    @staticmethod
    def _has_usb() -> bool:
        """Check if the device has USB support."""
        _sys = ImageViewerApplet._get_system_instance()
        if _sys is not None:
            try:
                return _sys.has_usb()  # type: ignore[no-any-return]
            except Exception as exc:
                log.debug("_has_usb: %s", exc)
        return False

    @staticmethod
    def _get_machine() -> str:
        """Return the machine type string."""
        _sys = ImageViewerApplet._get_system_instance()
        if _sys is not None:
            try:
                return _sys.get_machine()  # type: ignore[no-any-return]
            except Exception as exc:
                log.debug("_get_machine: %s", exc)
        return "jivelite"

    @staticmethod
    def _get_wallpaper_path() -> Optional[str]:
        """Return the wallpapers directory path, creating it if needed."""
        _sys = ImageViewerApplet._get_system_instance()
        if _sys is not None:
            try:
                user_dir = _sys.get_user_dir()
                if user_dir:
                    wp_path = os.path.join(str(user_dir), "wallpapers")
                    os.makedirs(wp_path, exist_ok=True)
                    return wp_path
            except Exception as exc:
                log.debug("_get_wallpaper_path: %s", exc)
        return None

    # ------------------------------------------------------------------
    # Timer helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _create_timer(
        delay_ms: int,
        callback: Callable[..., Any],
        once: bool = False,
        window: Any = None,
    ) -> Any:
        """Create and start a timer.

        Parameters
        ----------
        delay_ms : int
            Delay in milliseconds.
        callback : callable
            Function to call when the timer fires.
        once : bool
            If ``True``, the timer fires once (one-shot).
        window : Window, optional
            If provided, the timer is added to this window.

        Returns
        -------
        Timer
            The created timer object.
        """
        try:
            from jive.ui.timer import Timer

            timer = Timer(delay_ms, callback, once)
            timer.start()
            return timer
        except ImportError:
            log.warn("Timer not available")
            return None

    @staticmethod
    def _stop_timer(timer: Any) -> None:
        """Stop a timer if it is active."""
        if timer is not None and hasattr(timer, "stop"):
            try:
                timer.stop()
            except Exception as exc:
                log.debug("_stop_timer: failed to stop timer: %s", exc)

    @staticmethod
    def _restart_timer(timer: Any) -> None:
        """Restart a timer if it is active."""
        if timer is not None and hasattr(timer, "restart"):
            try:
                timer.restart()
            except Exception as exc:
                log.debug("_restart_timer: failed to restart timer: %s", exc)

    @staticmethod
    def _get_ticks() -> int:
        """Return the current tick count in milliseconds."""
        try:
            from jive.ui.framework import framework

            if framework is not None and hasattr(framework, "get_ticks"):
                return framework.get_ticks()
        except Exception as exc:
            log.debug("_get_ticks: framework unavailable: %s", exc)
        return int(time.time() * 1000)

    # ------------------------------------------------------------------
    # Display name (for applet manager)
    # ------------------------------------------------------------------

    @staticmethod
    def display_name() -> str:
        """Return the display name for this applet."""
        return "Image Viewer"
