"""
jive.applets.ImageViewer.ImageViewerMeta — Meta class for ImageViewer.

Ported from ``share/jive/applets/ImageViewer/ImageViewerMeta.lua`` (~80 LOC)
in the original jivelite project.

The Meta class:

* Declares version compatibility (1, 1)
* Provides default settings for delay, rotation, fullscreen, transition,
  ordering, text info, source, card path, and HTTP path
* Registers a menu item under ``settings`` for Image Viewer
* Registers services: ``registerRemoteScreensaver``,
  ``unregisterRemoteScreensaver``, ``openRemoteScreensaver``,
  ``mmImageViewerMenu``, ``mmImageViewerBrowse``
* In ``configure_applet()``, registers the Image Viewer as a screensaver
  via the ``addScreenSaver`` service with weight 90, and registers two
  media-manager menu items

The Lua original::

    function registerApplet(meta)
        jiveMain:addItem(meta:menuItem('appletImageViewer', 'settings',
            "IMAGE_VIEWER",
            function(applet, ...) applet:openImageViewer(...) end,
            58, nil, "hm_appletImageViewer"))

        meta:registerService("registerRemoteScreensaver")
        meta:registerService("unregisterRemoteScreensaver")
        meta:registerService("openRemoteScreensaver")
        meta:registerService("mmImageViewerMenu")
        meta:registerService("mmImageViewerBrowse")
    end

    function configureApplet(self)
        appletManager:callService("addScreenSaver",
            self:string("IMAGE_VIEWER"),
            "ImageViewer",
            "startScreensaver",
            self:string("IMAGE_VIEWER_SETTINGS"),
            "openSettings",
            90,
            "closeRemoteScreensaver"
        )
        ...
    end

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from jive.applet_meta import AppletMeta
from jive.utils.log import logger

__all__ = ["ImageViewerMeta"]

log = logger("applet.ImageViewer")


class ImageViewerMeta(AppletMeta):
    """Meta-information for the ImageViewer applet.

    Registers a settings menu item, five services, and one screensaver
    entry plus two media-manager menu items during the configure phase.
    """

    # ------------------------------------------------------------------
    # Required overrides
    # ------------------------------------------------------------------

    def jive_version(self) -> Tuple[int, int]:
        """Return ``(min_version, max_version)`` of Jive supported."""
        return (1, 1)

    def default_settings(self) -> Optional[Dict[str, Any]]:
        """Return default settings for the ImageViewer applet.

        Mirrors the Lua ``defaultSettings``::

            defaultSetting["delay"] = 10000
            defaultSetting["rotation"] = System:hasDeviceRotation()
            defaultSetting["fullscreen"] = false
            defaultSetting["transition"] = "fade"
            defaultSetting["ordering"] = "sequential"
            defaultSetting["textinfo"] = false
            defaultSetting["source"] = "http"
            defaultSetting["card.path"] = "/media"
            defaultSetting["http.path"] = "http://ralph.irving.sdf.org/..."

        The ``rotation`` default depends on whether the device supports
        rotation; we default to ``False`` since Sordino does not
        typically run on rotation-capable hardware.
        """
        has_rotation = False
        _sys = self._get_system_instance()
        if _sys is not None:
            try:
                has_rotation = _sys.has_device_rotation()
            except Exception as exc:
                log.error(
                    "Failed to check device rotation support: %s", exc, exc_info=True
                )

        http_path = "http://ralph.irving.sdf.org/static/images/imageviewer/sbtouch.lst"

        # Adjust default URL based on machine type (matching Lua logic)
        if _sys is not None:
            try:
                machine = _sys.get_machine()

                if machine == "baby":
                    http_path = "http://ralph.irving.sdf.org/static/images/imageviewer/sbradio.lst"
                elif machine == "jive":
                    http_path = "http://ralph.irving.sdf.org/static/images/imageviewer/sbcontroller.lst"
            except Exception as exc:
                log.error(
                    "Failed to determine machine type for default URL: %s",
                    exc,
                    exc_info=True,
                )

        return {
            "delay": 10000,
            "rotation": has_rotation,
            "fullscreen": False,
            "transition": "fade",
            "ordering": "sequential",
            "textinfo": False,
            "source": "http",
            "card.path": "/media",
            "http.path": http_path,
        }

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

    def register_applet(self) -> None:
        """Register the ImageViewer menu item and services.

        Adds a settings menu item and registers five services that
        other applets can call.
        """
        # Add menu item under settings
        try:
            from jive.jive_main import jive_main

            if jive_main is not None:
                item = self.menu_item(
                    id="appletImageViewer",
                    node="settings",
                    label="IMAGE_VIEWER",
                    closure=lambda applet, menu_item: applet.open_image_viewer(),
                    weight=58,
                    icon_style="hm_appletImageViewer",
                )
                if hasattr(jive_main, "add_item"):
                    jive_main.add_item(item)
                elif hasattr(jive_main, "addItem"):
                    jive_main.addItem(item)
        except (ImportError, AttributeError) as exc:
            log.debug("register_applet: jive_main not available: %s", exc)

        # Register services
        for service_name in (
            "registerRemoteScreensaver",
            "unregisterRemoteScreensaver",
            "openRemoteScreensaver",
            "mmImageViewerMenu",
            "mmImageViewerBrowse",
        ):
            self.register_service(service_name)

    # ------------------------------------------------------------------
    # Cross-applet configuration
    # ------------------------------------------------------------------

    def configure_applet(self) -> None:
        """Register the ImageViewer as a screensaver and add
        media-manager menu items.

        Called after all applets have been registered so the
        ScreenSavers service and media-manager service are available.

        Registers one screensaver:

        =======  ====================  ===================  ======
        Label    Applet                Method               Weight
        =======  ====================  ===================  ======
        IMAGE_VIEWER  ImageViewer      startScreensaver     90
        =======  ====================  ===================  ======

        The screensaver also has:
        - Settings label: IMAGE_VIEWER_SETTINGS
        - Settings method: openSettings
        - Close method: closeRemoteScreensaver
        """
        mgr = self._get_applet_manager()
        if mgr is None:
            log.warn("configure_applet: AppletManager not available")
            return

        # Register screensaver
        label = self.string("IMAGE_VIEWER")
        settings_label = self.string("IMAGE_VIEWER_SETTINGS")

        mgr.call_service(
            "addScreenSaver",
            label,  # display name
            "ImageViewer",  # applet name
            "startScreensaver",  # open method
            settings_label,  # settings label
            "openSettings",  # settings method
            90,  # weight / sort order
            "closeRemoteScreensaver",  # close method
        )

        log.debug(
            "Registered screensaver: %s (ImageViewer.startScreensaver, weight=90)",
            label,
        )

        # Register media-manager menu items
        try:
            mgr.call_service(
                "mmRegisterMenuItem",
                {
                    "serviceMethod": "mmImageViewerMenu",
                    "menuText": self.string("IMAGE_VIEWER_START_SLIDESHOW"),
                },
            )
        except Exception:
            log.debug("mmRegisterMenuItem for slideshow not available")

        try:
            mgr.call_service(
                "mmRegisterMenuItem",
                {
                    "serviceMethod": "mmImageViewerBrowse",
                    "menuText": self.string("IMAGE_VIEWER_BROWSE_IMAGES"),
                },
            )
        except Exception:
            log.debug("mmRegisterMenuItem for browse not available")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_applet_manager() -> Any:
        """Try to obtain the AppletManager singleton."""
        try:
            from jive.applet_manager import applet_manager

            return applet_manager
        except (ImportError, AttributeError):
            return None
