"""
jive.applet_meta — Base class for applet meta-information.

Ported from ``jive/AppletMeta.lua`` in the original jivelite project.

AppletMeta is a small class that is loaded at boot to perform:

(a) Versioning verification — ``jive_version()`` returns the min/max
    version of Jive supported by the applet.
(b) Hook the applet into the menu system — ``register_applet()`` adds
    menu items, screensavers, services, etc. so the applet can be
    loaded on demand.

Each applet directory (e.g. ``applets/NowPlaying/``) contains a
``NowPlayingMeta.py`` module with a class that extends ``AppletMeta``.
The ``AppletManager`` loads these meta modules at startup, calls
``jive_version()`` to verify compatibility, then ``register_applet()``
to let the applet hook itself into menus/services.

After registration, the meta object is discarded to save memory.
Only when the user actually activates the applet (via a menu callback)
is the full ``NowPlayingApplet`` module loaded.

Key methods to override:

* ``jive_version()`` — **Required.** Return ``(min_version, max_version)``.
* ``register_applet()`` — **Required.** Register menus, services, etc.
* ``configure_applet()`` — *Optional.* Called after all applets are
  registered, for cross-applet configuration.
* ``default_settings()`` — *Optional.* Return a dict of default settings.
* ``upgrade_settings(settings)`` — *Optional.* Migrate old settings to
  a new format; return the upgraded dict.

Usage::

    from jive.applet_meta import AppletMeta

    class NowPlayingMeta(AppletMeta):
        def jive_version(self):
            return (1, 1)

        def default_settings(self):
            return {"style": "artwork", "transparency": True}

        def register_applet(self):
            self.register_service("go_now_playing")
            jive_main.add_item(self.menu_item(
                id="now_playing",
                node="home",
                label="NOW_PLAYING",
                closure=lambda applet, menu_item: applet.open_screensaver(),
                weight=1,
            ))

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Copyright 2013-2014 Adrian Smith (jivelite amendments)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    Optional,
    Tuple,
    Union,
)

from jive.utils.log import logger

if TYPE_CHECKING:
    from jive.applet_manager import AppletManager
    from jive.utils.locale import StringsTable

__all__ = ["AppletMeta"]

log = logger("jivelite.applets")

# Track the most recently activated menu applet (for dedup logging)
_last_menu_applet: Optional[str] = None


class AppletMeta:
    """Base class for applet meta-information.

    Subclasses **must** override :meth:`jive_version` and
    :meth:`register_applet`.

    Attributes set by the AppletManager before ``register_applet()``
    is called:

    * ``_entry`` — The applet database entry dict.
    * ``_settings`` — The current applet settings dict.
    * ``_strings_table`` — The localized :class:`StringsTable`.
    * ``log`` — A logger instance scoped to this applet.
    """

    # Set by AppletManager before registration
    _entry: Optional[Dict[str, Any]] = None
    _settings: Optional[Dict[str, Any]] = None
    _strings_table: Optional["StringsTable"] = None
    log: Any = log  # Overridden per-instance by AppletManager

    def __init__(self) -> None:
        pass

    # ------------------------------------------------------------------
    # Methods subclasses MUST override
    # ------------------------------------------------------------------

    def jive_version(self) -> Tuple[int, int]:
        """Return ``(min_version, max_version)`` of Jive supported.

        Jive will not load applets incompatible with itself.

        **Required** — the default raises :class:`NotImplementedError`.
        """
        raise NotImplementedError("jive_version() is required")

    def register_applet(self) -> None:
        """Register the applet in the menu system or as a service.

        Called once at startup after version verification.  The meta
        should add menu items, register services, register as a
        screensaver, etc.

        **Required** — the default raises :class:`NotImplementedError`.
        """
        raise NotImplementedError("register_applet() is required")

    # ------------------------------------------------------------------
    # Methods subclasses MAY override
    # ------------------------------------------------------------------

    def configure_applet(self) -> None:
        """Called after *all* applets have been registered.

        Use this for cross-applet configuration (e.g. reading another
        applet's settings, or registering for notifications that other
        applets emit).

        *Optional* — the default is a no-op.
        """

    def default_settings(self) -> Optional[Dict[str, Any]]:
        """Return a dict of default settings, or ``None``.

        Called during registration if no persisted settings exist.
        """
        return None

    def upgrade_settings(self, settings: Dict[str, Any]) -> Dict[str, Any]:
        """Upgrade persisted *settings* to the current format.

        Called during registration when persisted settings already
        exist.  Return the (possibly modified) settings dict.

        The default implementation returns *settings* unchanged.
        """
        return settings

    # ------------------------------------------------------------------
    # Settings access
    # ------------------------------------------------------------------

    def get_settings(self) -> Optional[Dict[str, Any]]:
        """Return the current settings for this applet."""
        return self._settings

    def store_settings(self) -> None:
        """Persist the applet settings to disk.

        Delegates to the AppletManager's ``_store_settings``.
        """
        if self._entry is not None:
            from jive.applet_manager import applet_manager as _mgr

            if _mgr is not None:
                _mgr._store_settings(self._entry)

    # Lua-compatible camelCase aliases
    getSettings = get_settings
    storeSettings = store_settings

    # ------------------------------------------------------------------
    # Localization
    # ------------------------------------------------------------------

    def string(self, token: str, *args: Any) -> Any:
        """Return the localized string for *token*.

        Returns the :class:`LocalizedString` (or formatted ``str``
        if *args* are provided).  Falls back to the raw token string
        if no strings table is loaded.
        """
        if self._strings_table is None:
            return token
        return self._strings_table.str(token, *args)

    # ------------------------------------------------------------------
    # Service registration
    # ------------------------------------------------------------------

    def register_service(self, service: str) -> None:
        """Register a service name provided by this applet.

        When another module calls ``applet_manager.call_service(name)``,
        the applet will be loaded on demand and the method with the
        same name will be called on the applet instance.

        Parameters
        ----------
        service:
            The service name, e.g. ``"getCurrentPlayer"``.
        """
        if self._entry is None:
            log.warn("register_service called but meta has no entry: %s", service)
            return

        from jive.applet_manager import applet_manager as _mgr

        if _mgr is not None:
            applet_name = self._entry.get("applet_name", "")
            _mgr.register_service(applet_name, service)

    # Lua-compatible camelCase alias
    registerService = register_service

    # ------------------------------------------------------------------
    # Menu item helper
    # ------------------------------------------------------------------

    def menu_item(
        self,
        id: str,
        node: str,
        label: str,
        closure: Callable[..., Any],
        weight: Optional[int] = None,
        extras: Optional[Dict[str, Any]] = None,
        icon_style: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Build a menu-item dict for use with ``HomeMenu.add_item()``.

        Parameters
        ----------
        id:
            Unique identifier for the menu item.
        node:
            The node (sub-menu) to place the item in (e.g.
            ``"home"``, ``"settings"``).
        label:
            A string token to be localized via :meth:`string`.
        closure:
            A callable ``(applet_instance, menu_item) -> Any`` that is
            invoked when the menu item is selected.  The applet is
            loaded on demand.
        weight:
            Sort weight (lower = higher in menu).  ``None`` means
            default ordering.
        extras:
            Additional data to attach to the menu item dict.
        icon_style:
            Style name for the menu item icon.  Defaults to
            ``"hm_advancedSettings"`` (matching Lua bug #12510 compat).

        Returns
        -------
        dict
            A menu-item dict suitable for ``HomeMenu.add_item()``.
        """
        global _last_menu_applet

        if not icon_style:
            # Bug #12510 compatibility — default icon style
            icon_style = "hm_advancedSettings"

        applet_name = ""
        if self._entry is not None:
            applet_name = self._entry.get("applet_name", "")

        def _callback(event: Any = None, menu_item_arg: Any = None) -> Any:
            global _last_menu_applet

            if _last_menu_applet != applet_name:
                log.info("entering %s", applet_name)
                _last_menu_applet = applet_name

            from jive.applet_manager import applet_manager as _mgr

            if _mgr is None:
                log.error("AppletManager not available for menu_item callback")
                return None

            applet = _mgr.load_applet(applet_name)
            if applet is None:
                log.error(
                    "Failed to load applet %s for menu_item callback", applet_name
                )
                return None
            return closure(applet, menu_item_arg)

        item: Dict[str, Any] = {
            "id": id,
            "iconStyle": icon_style,
            "node": node,
            "text": self.string(label),
            "sound": "WINDOWSHOW",
            "callback": _callback,
        }

        if weight is not None:
            item["weight"] = weight

        if extras is not None:
            item["extras"] = extras

        return item

    # Lua-compatible camelCase alias
    menuItem = menu_item

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
