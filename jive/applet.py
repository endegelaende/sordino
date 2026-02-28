"""
jive.applet — Base class for all Jive applets.

Ported from ``jive/Applet.lua`` in the original jivelite project.

In Jive, applets are very flexible in the methods they implement; this
class implements a simple framework to manage localization, settings,
and memory management.

Key concepts:

* **init()** — Called after construction to initialize the applet.
  Settings and localized strings are available at this point (but
  NOT in ``__init__``).
* **free()** — Called when the applet is being unloaded.  Return
  ``True`` to allow freeing, ``False`` to stay resident.
* **tieWindow(window)** — Tie a window to this applet.  When all
  tied windows are popped from the window stack, the applet is freed.
* **readdir(path)** — Iterator over files in the applet's directory.
* **settings** — Dict of applet-specific settings that can be persisted.
* **strings** — Localized string table for this applet.
* **registerService(name, callback)** — Register a named service
  that other applets can call via ``AppletManager.call_service()``.

Usage::

    from jive.applet import Applet

    class MyApplet(Applet):
        def init(self):
            super().init()
            # Set up the applet UI here
            self.log.info("MyApplet initialized")

        def free(self):
            # Clean up resources
            return True  # Allow the applet to be freed

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Copyright 2013-2014 Adrian Smith (jivelite amendments)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    Iterator,
    Optional,
    Set,
    Union,
)

from jive.ui.constants import EVENT_WINDOW_POP
from jive.utils.log import logger

if TYPE_CHECKING:
    from jive.applet_manager import AppletManager
    from jive.ui.window import Window
    from jive.utils.locale import StringsTable

__all__ = ["Applet"]

log = logger("jivelite.applets")


class Applet:
    """Base class for all Jive applets.

    Subclasses override :meth:`init` (setup) and optionally
    :meth:`free` (teardown).  The ``__init__`` constructor is
    called by the applet manager — **do not** rely on settings or
    strings being available in ``__init__``; they are set by the
    manager *before* :meth:`init` is called.

    Attributes:
        _entry: The applet database entry dict (set by AppletManager).
        _settings: The applet settings dict (set by AppletManager).
        _default_settings: The default settings from the Meta (set by
            AppletManager).
        _strings_table: The localized StringsTable (set by AppletManager).
        log: A logger instance for this applet (set by AppletManager).
        _tie: Set of windows tied to this applet.
    """

    # Set by the AppletManager before init() is called
    _entry: Optional[Dict[str, Any]] = None
    _settings: Optional[Dict[str, Any]] = None
    _default_settings: Optional[Dict[str, Any]] = None
    _strings_table: Optional["StringsTable"] = None
    log: Any = log  # Overridden per-instance by AppletManager

    def __init__(self) -> None:
        self._tie: Set["Window"] = set()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def init(self) -> None:
        """Called to initialize the applet.

        At this point, settings and localized strings *are* available.
        Override in subclasses to set up the UI, register listeners, etc.
        """

    def free(self) -> bool:
        """Called when the applet will be freed.

        Must make sure all data is unreferenced to allow garbage
        collection.  Return ``True`` to allow freeing, ``False`` to
        keep the applet loaded.

        The default implementation returns ``True``.
        """
        return True

    # ------------------------------------------------------------------
    # Window tying
    # ------------------------------------------------------------------

    def tie_window(self, window: "Window") -> None:
        """Tie *window* to this applet.

        When all tied windows are popped from the window stack, the
        applet is freed via the AppletManager.
        """
        self._tie.add(window)

        applet_ref = self  # prevent closure over ``self`` weakly

        def _on_pop(*_args: Any, **_kwargs: Any) -> None:
            applet_ref._tie.discard(window)
            if not applet_ref._tie and applet_ref._entry is not None:
                # Import locally to avoid circular imports at module level
                from jive.applet_manager import applet_manager as _mgr

                if _mgr is not None:
                    _mgr._free_applet_by_entry(applet_ref._entry)

        window.add_listener(EVENT_WINDOW_POP, _on_pop)

    def tie_and_show_window(self, window: "Window", *args: Any, **kwargs: Any) -> None:
        """Tie *window* to this applet and show it.

        The *args* and *kwargs* are forwarded to ``window.show()``.
        """
        self.tie_window(window)
        window.show(*args, **kwargs)

    # Lua-compatible camelCase aliases
    tieWindow = tie_window
    tieAndShowWindow = tie_and_show_window

    # ------------------------------------------------------------------
    # Directory iteration
    # ------------------------------------------------------------------

    def readdir(self, path: str = "") -> Iterator[str]:
        """Iterate over files in the applet's directory at *path*.

        Yields relative paths (from the search-path root) for each
        file found.  Skips ``"."``, ``".."``, and ``.svn`` entries.

        In the Lua original this uses coroutines to iterate over
        ``package.path``; here we iterate over the actual filesystem
        using the applet's ``dirpath`` from its entry.
        """
        if self._entry is None:
            return

        applet_name = self._entry.get("applet_name", "")
        dir_path = self._entry.get("dirpath")
        if not dir_path:
            return

        target = Path(dir_path) / path
        if not target.is_dir():
            return

        for entry in sorted(target.iterdir()):
            name = entry.name
            if name in (".", "..", ".svn"):
                continue
            # Yield relative path matching Lua convention:
            # "applets/<AppletName>/<path>/<entry>"
            rel = (
                f"applets/{applet_name}/{path}/{name}"
                if path
                else f"applets/{applet_name}/{name}"
            )
            yield rel

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    def set_settings(self, settings: Dict[str, Any]) -> None:
        """Replace the applet settings with *settings*."""
        self._settings = settings

    def get_settings(self) -> Optional[Dict[str, Any]]:
        """Return the current applet settings dict."""
        return self._settings

    def get_default_settings(self) -> Optional[Dict[str, Any]]:
        """Return the default settings from the applet's Meta class."""
        return self._default_settings

    def store_settings(self) -> None:
        """Persist the applet settings to disk.

        Delegates to :meth:`AppletManager._store_settings`.
        """
        if self._entry is not None:
            from jive.applet_manager import applet_manager as _mgr

            if _mgr is not None:
                _mgr._store_settings(self._entry)

    # Lua-compatible camelCase aliases
    setSettings = set_settings
    getSettings = get_settings
    getDefaultSettings = get_default_settings
    storeSettings = store_settings

    # ------------------------------------------------------------------
    # Localization
    # ------------------------------------------------------------------

    def string(self, token: str, *args: Any) -> Any:
        """Return the localized string for *token*.

        If format *args* are given they are substituted into the
        translated string.

        Returns the LocalizedString object if no args, or a formatted
        ``str`` if args are provided.
        """
        if self._strings_table is None:
            # No strings table loaded — return the token itself
            return token
        return self._strings_table.str(token, *args)

    # ------------------------------------------------------------------
    # Service registration
    # ------------------------------------------------------------------

    def register_service(
        self, service: str, closure: Optional[Callable[..., Any]] = None
    ) -> None:
        """Register a named service provided by this applet.

        Parameters
        ----------
        service:
            The service name (e.g. ``"getCurrentPlayer"``).
        closure:
            An optional callable.  If provided, the service will call
            this closure instead of looking up a method of the same
            name on the applet instance.

        In the original Lua code, the closure variant is used by
        ``Applet:registerService`` while the no-closure variant is
        used by ``AppletMeta:registerService``.
        """
        if self._entry is None:
            log.warn("register_service called but applet has no entry: %s", service)
            return

        from jive.applet_manager import applet_manager as _mgr

        if _mgr is not None:
            applet_name = self._entry.get("applet_name") or self._entry.get("name", "")
            _mgr.register_service(applet_name, service, closure)

    # Lua-compatible camelCase alias
    registerService = register_service

    # ------------------------------------------------------------------
    # Repr
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        name = "?"
        if self._entry is not None:
            name = self._entry.get("applet_name", "?")
        cls = type(self).__name__
        return f"{cls}(applet_name={name!r})"

    def __str__(self) -> str:
        return repr(self)
