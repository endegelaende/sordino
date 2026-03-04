"""
jive.applets.Screenshot.ScreenshotApplet — Screenshot applet.

Ported from ``share/jive/applets/Screenshot/ScreenshotApplet.lua``
in the original jivelite project.

This is a resident applet that:

* Registers a listener for the ``take_screenshot`` action
* On activation, captures the current screen to a BMP file
* Saves to the user directory or ``/tmp`` (if available)
* Shows a brief toast popup with the file path
* Cannot be freed (always resident)

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

from jive.applet import Applet
from jive.utils.log import logger

__all__ = ["ScreenshotApplet"]

log = logger("applet.Screenshot")


class ScreenshotApplet(Applet):
    """Resident applet that captures screenshots on the ``take_screenshot`` action.

    Screenshots are saved as numbered BMP files (``jivelite0001.bmp``,
    ``jivelite0002.bmp``, …) to the user directory or ``/tmp``.
    """

    def __init__(self) -> None:
        super().__init__()
        self.number: int = 1

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def init(self) -> None:
        """Register the ``take_screenshot`` action listener."""
        super().init()
        self.number = 1

        fw = self._get_framework()
        if fw is not None:
            try:
                fw.add_action_listener(
                    "take_screenshot",
                    self._take_screenshot_action,
                )
            except Exception as exc:
                log.warn("Could not register take_screenshot listener: %s", exc)

    def free(self) -> bool:
        """Refuse to be freed — this applet is permanently resident.

        Mirrors the Lua original::

            function free(self)
                -- we cannot be unloaded
                return false
            end
        """
        return False

    # ------------------------------------------------------------------
    # Screenshot action
    # ------------------------------------------------------------------

    def _take_screenshot_action(self, event: Any = None) -> Optional[int]:
        """Take a screenshot and save it as a BMP file.

        The screenshot is saved to the user directory (from
        ``System.getUserDir()``) or ``/tmp`` if that directory exists.
        A brief toast popup is shown to confirm the save.

        Returns ``EVENT_CONSUME`` to consume the event.
        """
        from jive.ui.constants import EVENT_CONSUME

        fw = self._get_framework()
        if fw is None:
            log.warn("_take_screenshot_action: Framework not available")
            return int(EVENT_CONSUME)

        # Play click sound
        try:
            fw.play_sound("CLICK")
        except Exception as exc:
            log.warning("play_sound failed: %s", exc)

        # Determine save path
        path = self._get_save_directory()

        file_path = os.path.join(path, f"jivelite{self.number:04d}.bmp")
        self.number += 1

        log.warn("Taking screenshot %s", file_path)

        try:
            # Get screen dimensions
            sw, sh = fw.get_screen_size()

            from jive.ui.surface import Surface

            # Get the background and top window
            bg = self._get_background(fw)
            window = self._get_top_window(fw)

            # Create a new surface and composite the screen
            srf = Surface.new_rgb(sw, sh)

            if bg is not None:
                try:
                    bg.blit(srf, 0, 0, sw, sh)
                except Exception:
                    try:
                        bg.blit(srf, 0, 0)
                    except Exception as exc:
                        log.warning("bg.blit fallback failed: %s", exc)

            if window is not None:
                try:
                    from jive.ui.constants import (
                        JIVE_LAYER_ALL,  # type: ignore[attr-defined]
                    )

                    window.draw(srf, JIVE_LAYER_ALL)
                except Exception:
                    try:
                        window.draw(srf, 0xFFFFFFFF)
                    except Exception as exc:
                        log.warning("window.draw fallback failed: %s", exc)

            # Save as BMP
            if hasattr(srf, "saveBMP"):
                srf.saveBMP(file_path)
            elif hasattr(srf, "save_bmp"):
                srf.save_bmp(file_path)
            elif hasattr(srf, "_surface"):
                # Direct pygame save fallback
                import pygame

                pygame.image.save(srf._surface, file_path)
            else:
                log.warn("Surface has no save method")
                return int(EVENT_CONSUME)

            # Show toast popup
            self._show_toast(file_path)

        except Exception as exc:
            log.warn("Failed to take screenshot: %s", exc)

        return int(EVENT_CONSUME)

    # ------------------------------------------------------------------
    # Toast popup
    # ------------------------------------------------------------------

    def _show_toast(self, file_path: str) -> None:
        """Show a brief toast popup confirming the screenshot save.

        Parameters
        ----------
        file_path:
            The path where the screenshot was saved.
        """
        try:
            from jive.ui.group import Group
            from jive.ui.label import Label
            from jive.ui.popup import Popup

            popup = Popup("toast_popup")

            text_str = self.string("SCREENSHOT_TAKEN", file_path)
            if text_str == "SCREENSHOT_TAKEN":
                # Fallback if no strings table loaded
                text_str = f"Screenshot saved to\n{file_path}"

            group = Group("group", {"text": Label("text", text_str)})
            popup.add_widget(group)

            # Auto-hide after 5 seconds
            try:
                from jive.ui.timer import Timer

                timer = Timer(
                    5000,
                    lambda: popup.hide(),
                    once=True,
                )
                popup.add_timer(timer) if hasattr(popup, "add_timer") else timer.start()  # type: ignore[call-arg, arg-type]
            except Exception as exc:
                log.warning("toast auto-hide timer setup failed: %s", exc)

            self.tie_and_show_window(popup)

        except Exception as exc:
            log.warn("Could not show screenshot toast: %s", exc)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_save_directory(self) -> str:
        """Determine the directory to save screenshots to.

        Prefers ``/tmp`` if it exists (Linux/macOS), otherwise falls
        back to the user directory from ``System.getUserDir()``.

        Returns
        -------
        str
            The directory path for saving screenshots.
        """
        # Try user directory first
        path = None
        try:
            from jive.applet_manager import applet_manager as _mgr

            if _mgr is not None and hasattr(_mgr, "system") and _mgr.system is not None:
                path = _mgr.system.get_user_dir()
        except Exception as exc:
            log.debug("getUserDir failed: %s", exc)

        if not path:
            path = os.path.expanduser("~")

        # Prefer /tmp if it exists (matches Lua original)
        tmp_dir = "/tmp"
        if os.path.isdir(tmp_dir):
            path = tmp_dir

        return path

    @staticmethod
    def _get_background(fw: Any) -> Any:
        """Get the framework background surface."""
        try:
            if hasattr(fw, "getBackground"):
                return fw.getBackground()
            if hasattr(fw, "get_background"):
                return fw.get_background()
            # Try class method / static attribute
            cls = type(fw)
            if hasattr(cls, "getBackground"):
                return cls.getBackground()
        except Exception as exc:
            log.debug("getBackground failed: %s", exc)
        return None

    @staticmethod
    def _get_top_window(fw: Any) -> Any:
        """Get the topmost window from the window stack."""
        try:
            stack = getattr(fw, "window_stack", None) or getattr(
                fw, "windowStack", None
            )
            if stack and len(stack) > 0:
                return stack[0]
        except Exception as exc:
            log.debug("get_top_window failed: %s", exc)
        return None

    @staticmethod
    def _get_framework() -> Any:
        """Try to obtain the Framework singleton."""
        try:
            from jive.ui.framework import framework

            return framework
        except (ImportError, AttributeError):
            return None
