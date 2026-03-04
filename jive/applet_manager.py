"""
jive.applet_manager — Applet discovery, loading, and lifecycle management.

Ported from ``jive/AppletManager.lua`` in the original jivelite project.

The AppletManager discovers applets on disk, loads their meta-information
at startup, and loads/unloads full applet modules on demand.

Applet discovery
~~~~~~~~~~~~~~~~

Applets live in directories named ``applets/<AppletName>/`` on the
search path.  Each applet directory must contain at least a meta module
(``<AppletName>Meta.py`` or ``<AppletName>Meta.lua``).  The manager
scans all search paths for these directories and builds a database of
known applets.

For the Python port, applet modules are regular Python modules:

* ``applets/<AppletName>/<AppletName>Meta.py`` — contains a class
  that extends :class:`AppletMeta`.
* ``applets/<AppletName>/<AppletName>Applet.py`` — contains a class
  that extends :class:`Applet`.
* ``applets/<AppletName>/strings.txt`` — localised string table.
* ``applets/<AppletName>/settings.json`` — persisted settings (JSON).

Boot sequence
~~~~~~~~~~~~~

1. ``discover()`` — find all applet directories.
2. Load each ``*Meta`` module and instantiate it.
3. Call ``meta.jive_version()`` to check compatibility.
4. Call ``meta.register_applet()`` — the meta hooks itself into menus,
   services, screensavers, etc.
5. Call ``meta.configure_applet()`` — cross-applet configuration.
6. Discard the meta objects to save memory.

On-demand loading
~~~~~~~~~~~~~~~~~

When a user selects a menu item (or a service is called), the manager
loads the full ``*Applet`` module, instantiates it, wires up settings
and strings, and calls ``applet.init()``.

Service registry
~~~~~~~~~~~~~~~~

Applets can register named services (e.g. ``"getCurrentPlayer"``) via
their meta or applet instance.  Other code calls
``applet_manager.call_service("getCurrentPlayer")`` which loads the
providing applet on demand and invokes the service method.

Usage::

    from jive.applet_manager import AppletManager, applet_manager

    # At startup (done by JiveMain):
    mgr = AppletManager(system=system, locale=locale)
    mgr.discover()

    # Load an applet on demand:
    applet = mgr.load_applet("NowPlaying")

    # Call a service:
    player = mgr.call_service("getCurrentPlayer")

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Copyright 2013-2014 Adrian Smith (jivelite amendments)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Sequence,
    Set,
    Tuple,
    Union,
)

from jive.utils.log import logger

if TYPE_CHECKING:
    from jive.applet import Applet
    from jive.applet_meta import AppletMeta
    from jive.system import System
    from jive.utils.locale import Locale, StringsTable

__all__ = ["AppletManager", "applet_manager"]

log = logger("jivelite.applets")

# ---------------------------------------------------------------------------
# Module-level singleton — set by AppletManager.__init__
# ---------------------------------------------------------------------------

applet_manager: Optional["AppletManager"] = None

# Sentinel for loop / in-progress detection
_SENTINEL = object()


# ---------------------------------------------------------------------------
# Applet database entry
# ---------------------------------------------------------------------------


def _make_entry(
    applet_name: str,
    dirpath: Path,
    settings_filepath: Path,
    load_priority: int = 100,
) -> Dict[str, Any]:
    """Create an applet database entry dict.

    This mirrors the Lua ``newEntry`` table in ``_saveApplet``.
    """
    return {
        "applet_name": applet_name,
        # File paths
        "dirpath": str(dirpath),
        "basename": str(dirpath / applet_name),
        "settings_filepath": str(settings_filepath),
        # Python module names
        "applet_module": f"applets.{applet_name}.{applet_name}Applet",
        "meta_module": f"applets.{applet_name}.{applet_name}Meta",
        # Logger
        "applet_logger": logger(f"applet.{applet_name}"),
        # Lifecycle state
        "settings": None,  # None = not loaded, dict = loaded
        "strings_table": None,
        "meta_loaded": False,
        "meta_registered": False,
        "meta_configured": False,
        "meta_obj": None,
        "applet_loaded": False,
        "applet_evaluated": False,  # False or Applet instance
        "load_priority": load_priority,
        "default_settings": None,
    }


# ---------------------------------------------------------------------------
# AppletManager
# ---------------------------------------------------------------------------


class AppletManager:
    """Discovers, loads, and manages the lifecycle of applets.

    Parameters
    ----------
    system:
        The :class:`System` instance providing user paths and search paths.
    locale:
        The :class:`Locale` instance for loading ``strings.txt`` files.
    jnt:
        The network thread / notification hub (optional, stored for
        applets that need it).
    allowed_applets:
        If provided, only applets in this set will be loaded.
        Useful for debugging.
    """

    def __init__(
        self,
        system: Optional["System"] = None,
        locale: Optional["Locale"] = None,
        jnt: Any = None,
        allowed_applets: Optional[Set[str]] = None,
    ) -> None:
        global applet_manager

        self._system = system
        self._locale = locale
        self.jnt = jnt
        self._allowed_applets = allowed_applets

        # The applet database: applet_name -> entry dict
        self._applets_db: Dict[str, Dict[str, Any]] = {}

        # Service registry: service_name -> applet_name
        self._services: Dict[str, str] = {}

        # Service closures: service_name -> callable (optional)
        self._service_closures: Dict[str, Callable[..., Any]] = {}

        # Default settings overrides: applet_name -> {setting: value}
        self._default_settings: Dict[str, Dict[str, Any]] = {}

        # User paths
        if system is not None:
            self._user_settings_dir = system.get_settings_dir()
            self._user_applets_dir = system.get_user_applets_dir()
        else:
            self._user_settings_dir = Path.home() / ".jivelite" / "settings"
            self._user_applets_dir = Path.home() / ".jivelite" / "applets"

        # Set the module-level singleton
        applet_manager = self

    # ------------------------------------------------------------------
    # System access
    # ------------------------------------------------------------------

    @property
    def system(self) -> Optional["System"]:
        """Return the :class:`System` instance, or ``None``."""
        return self._system

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def discover(self) -> None:
        """Find and load all applets.

        This is the main boot-time entry point.  It:
        1. Scans search paths for applet directories.
        2. Loads and registers all meta modules.
        3. Configures all registered applets.
        """
        log.debug("AppletManager.discover()")
        self._find_applets()
        self._load_and_register_metas()
        self._eval_metas()

    def _find_applets(self) -> None:
        """Scan search paths for applet directories."""
        log.debug("_find_applets")

        search_paths: List[Path] = []

        # Gather search paths from the system
        if self._system is not None:
            search_paths.extend(self._system.search_paths)
            # Also include the user applets directory
            if self._user_applets_dir.is_dir():
                search_paths.append(self._user_applets_dir.parent)

        # Additionally look at PYTHONPATH / sys.path entries
        for p in sys.path:
            pp = Path(p)
            if pp.is_dir() and pp not in search_paths:
                search_paths.append(pp)

        for base_dir in search_paths:
            applets_dir = base_dir / "applets"
            if not applets_dir.is_dir():
                continue

            log.debug("..scanning %s", applets_dir)

            try:
                entries = sorted(applets_dir.iterdir())
            except OSError as exc:
                log.warn("Cannot scan %s: %s", applets_dir, exc)
                continue

            for entry in entries:
                if not entry.is_dir():
                    continue
                name = entry.name
                if name.startswith(".") or name == "__pycache__":
                    continue

                # Check for meta module — Python or Lua
                meta_py = entry / f"{name}Meta.py"
                meta_lua = entry / f"{name}Meta.lua"
                if meta_py.is_file() or meta_lua.is_file():
                    self._save_applet(name, applets_dir)

    def _save_applet(self, name: str, applets_dir: Path) -> None:
        """Record an applet in the database."""
        log.debug("Found applet %s in %s", name, applets_dir)

        if self._allowed_applets is not None and name not in self._allowed_applets:
            return

        if name in self._applets_db:
            return  # Already known

        dirpath = applets_dir / name
        settings_filepath = self._user_settings_dir / f"{name}.json"
        load_priority = self._get_load_priority(dirpath)

        self._applets_db[name] = _make_entry(
            applet_name=name,
            dirpath=dirpath,
            settings_filepath=settings_filepath,
            load_priority=load_priority,
        )

    # ------------------------------------------------------------------
    # Meta loading
    # ------------------------------------------------------------------

    def _load_and_register_metas(self) -> None:
        """Load and register the meta-information of all applets."""
        log.debug("_load_and_register_metas")

        for entry in self._sorted_applet_db():
            if not entry["meta_loaded"]:
                self._pload_meta(entry)
                if entry["meta_loaded"] and not entry["meta_registered"]:
                    self._pregister_meta(entry)

    def _eval_metas(self) -> None:
        """Configure all registered applets, then discard meta objects."""
        log.debug("_eval_metas")

        for entry in self._sorted_applet_db():
            if (
                entry["meta_loaded"]
                and entry["meta_registered"]
                and not entry["meta_configured"]
            ):
                try:
                    self._configure_meta(entry)
                except Exception as exc:
                    entry["meta_configured"] = False
                    entry["meta_registered"] = False
                    entry["meta_loaded"] = False
                    log.error(
                        "Error configuring meta for %s: %s",
                        entry["applet_name"],
                        exc,
                    )

        # Discard meta objects — they've done their job
        for entry in self._sorted_applet_db():
            entry["meta_obj"] = None
            # Note: we keep strings_table around (unlike Lua which
            # sometimes trashes it) because Python dicts are cheaper
            # and strings may be needed later.

    def _load_meta(self, entry: Dict[str, Any]) -> Any:
        """Load the meta module for an applet entry."""
        applet_name = entry["applet_name"]
        log.debug("_load_meta: %s", applet_name)

        p = entry["meta_loaded"]
        if p is True or (p is not False and p is not None):
            if p is _SENTINEL:
                raise RuntimeError(
                    f"Loop or previous error loading meta '{applet_name}'"
                )
            return p

        # Load locale strings
        self._load_locale_strings(entry)
        # Load settings
        self._load_settings(entry)

        entry["meta_loaded"] = _SENTINEL

        # Try to import the meta module
        meta_class = self._import_meta_class(entry)
        if meta_class is None:
            entry["meta_loaded"] = False
            raise ImportError(f"Cannot import meta for {applet_name}")

        entry["meta_loaded"] = True
        return True

    def _pload_meta(self, entry: Dict[str, Any]) -> Optional[Any]:
        """Protected call to _load_meta."""
        try:
            return self._load_meta(entry)
        except Exception as exc:
            entry["meta_loaded"] = False
            log.error(
                "Error while loading meta for %s: %s",
                entry["applet_name"],
                exc,
            )
            return None

    def _register_meta(self, entry: Dict[str, Any]) -> None:
        """Register an applet's meta (version check + register)."""
        applet_name = entry["applet_name"]
        log.debug("_register_meta: %s", applet_name)

        entry["meta_registered"] = True

        meta_class = self._import_meta_class(entry)
        if meta_class is None:
            raise ImportError(f"Cannot import meta class for {applet_name}")

        # Set up the logger on the class
        meta_class.log = entry["applet_logger"]  # type: ignore[attr-defined]

        # Instantiate the meta
        obj = meta_class()

        # Check version compatibility
        # The original Lua hardcodes ver=1; we keep the same logic.
        ver = 1
        min_v, max_v = obj.jive_version()
        if min_v > ver or max_v < ver:
            raise RuntimeError(f"Incompatible applet {applet_name}")

        # Get default settings from the meta
        entry["default_settings"] = obj.default_settings()

        if entry["settings"] is None:
            entry["settings"] = obj.default_settings()

            # Apply global default overrides
            global_defaults = self._default_settings.get(applet_name)
            if global_defaults:
                if entry["settings"] is None:
                    entry["settings"] = {}
                for k, v in global_defaults.items():
                    log.debug("Setting global default: %s=%s", k, v)
                    entry["settings"][k] = v  # type: ignore[index]
        else:
            entry["settings"] = obj.upgrade_settings(entry["settings"])

        # Wire up the meta object
        obj._entry = entry
        obj._settings = entry["settings"]
        obj._strings_table = entry.get("strings_table")

        entry["meta_obj"] = obj

        # Let the meta hook into menus, services, etc.
        log.info("Registering: %s", applet_name)
        obj.register_applet()

    def _pregister_meta(self, entry: Dict[str, Any]) -> bool:
        """Protected call to _register_meta."""
        if entry["meta_loaded"] and not entry["meta_registered"]:
            try:
                self._register_meta(entry)
                return True
            except Exception as exc:
                entry["meta_configured"] = False
                entry["meta_registered"] = False
                entry["meta_loaded"] = False
                log.error(
                    "Error registering meta for %s: %s",
                    entry["applet_name"],
                    exc,
                )
                return False
        return True

    def _configure_meta(self, entry: Dict[str, Any]) -> None:
        """Call configure_applet() on the meta object."""
        entry["meta_configured"] = True
        if entry["meta_obj"] is not None:
            entry["meta_obj"].configure_applet()

    # ------------------------------------------------------------------
    # Applet loading
    # ------------------------------------------------------------------

    def load_applet(self, applet_name: str) -> Optional["Applet"]:
        """Load an applet by name. Returns an Applet instance or None.

        If the applet is already loaded, returns the existing instance.
        Otherwise loads the module, instantiates the class, wires up
        settings and strings, and calls ``init()``.
        """
        log.debug("load_applet: %s", applet_name)

        entry = self._applets_db.get(applet_name)
        if entry is None:
            log.error("Unknown applet: %s", applet_name)
            return None

        # Already loaded?
        if entry["applet_evaluated"] and entry["applet_evaluated"] is not True:
            return entry["applet_evaluated"]  # type: ignore[no-any-return]

        # Meta processed?
        if not entry["meta_registered"]:
            if not entry["meta_loaded"] and not self._pload_meta(entry):
                return None
            if not self._pregister_meta(entry):
                return None

        # Already loaded? (through meta calling load again)
        if entry["applet_evaluated"] and entry["applet_evaluated"] is not True:
            return entry["applet_evaluated"]  # type: ignore[no-any-return]

        # Load and evaluate the applet
        if self._pload_applet(entry):
            obj = self._peval_applet(entry)
            if obj is not None:
                log.debug("Loaded: %s", applet_name)
            return obj

        return None

    def _load_applet(self, entry: Dict[str, Any]) -> bool:
        """Load the applet module for an entry."""
        applet_name = entry["applet_name"]
        log.debug("_load_applet: %s", applet_name)

        p = entry["applet_loaded"]
        if p:
            if p is _SENTINEL:
                raise RuntimeError(
                    f"Loop or previous error loading applet '{applet_name}'"
                )
            return True

        # Load locale strings (may already be loaded from meta)
        self._load_locale_strings(entry)
        # Load settings (may already be loaded from meta)
        self._load_settings(entry)

        entry["applet_loaded"] = _SENTINEL

        # Try to import the applet module
        applet_class = self._import_applet_class(entry)
        if applet_class is None:
            entry["applet_loaded"] = False
            raise ImportError(f"Cannot import applet for {applet_name}")

        entry["applet_loaded"] = True
        return True

    def _pload_applet(self, entry: Dict[str, Any]) -> bool:
        """Protected call to _load_applet."""
        try:
            return self._load_applet(entry)
        except Exception as exc:
            entry["applet_loaded"] = False
            log.error(
                "Error while loading applet %s: %s",
                entry["applet_name"],
                exc,
            )
            return False

    def _eval_applet(self, entry: Dict[str, Any]) -> "Applet":
        """Instantiate and initialize the applet."""
        applet_name = entry["applet_name"]
        log.debug("_eval_applet: %s", applet_name)

        entry["applet_evaluated"] = True  # Mark as in-progress

        applet_class = self._import_applet_class(entry)
        if applet_class is None:
            raise ImportError(f"Cannot import applet class for {applet_name}")

        applet_class.log = entry["applet_logger"]  # type: ignore[attr-defined]

        obj = applet_class()

        # Wire up the applet
        obj._entry = entry
        obj._settings = entry["settings"]
        obj._default_settings = entry.get("default_settings")
        obj._strings_table = entry.get("strings_table")
        obj.log = entry["applet_logger"]

        obj.init()

        entry["applet_evaluated"] = obj
        return obj  # type: ignore[no-any-return]

    def _peval_applet(self, entry: Dict[str, Any]) -> Optional["Applet"]:
        """Protected call to _eval_applet."""
        try:
            return self._eval_applet(entry)
        except Exception as exc:
            entry["applet_evaluated"] = False
            entry["applet_loaded"] = False
            log.error(
                "Error while evaluating applet %s: %s",
                entry["applet_name"],
                exc,
            )
            return None

    # ------------------------------------------------------------------
    # Applet freeing
    # ------------------------------------------------------------------

    def free_applet(self, applet_name: str) -> None:
        """Free an applet by name, releasing its resources."""
        entry = self._applets_db.get(applet_name)
        if entry is None:
            log.error("Cannot free unknown applet: %s", applet_name)
            return
        self._free_applet_by_entry(entry)

    def _free_applet_by_entry(self, entry: Dict[str, Any]) -> None:
        """Free an applet by its database entry."""
        applet_name = entry["applet_name"]
        log.debug("free_applet: %s", applet_name)

        applet_obj = entry.get("applet_evaluated")
        if applet_obj and applet_obj is not True:
            try:
                should_free = applet_obj.free()
            except Exception as exc:
                log.error("Error in %s.free(): %s", applet_name, exc)
                should_free = True

            if should_free is None:
                log.error("%s.free() returned None", applet_name)
            elif should_free is False:
                # Applet wants to stay loaded
                return

        log.debug("Freeing: %s", applet_name)
        entry["applet_evaluated"] = False
        entry["applet_loaded"] = False

        # Remove the module from sys.modules if present
        mod_name = entry.get("applet_module", "")
        if mod_name and mod_name in sys.modules:
            del sys.modules[mod_name]

    # Alias for internal use (matches Lua naming in Applet.lua callbacks)
    _freeApplet = _free_applet_by_entry

    # ------------------------------------------------------------------
    # Applet queries
    # ------------------------------------------------------------------

    def has_applet(self, applet_name: str) -> bool:
        """Return True if the applet is known (discovered)."""
        return applet_name in self._applets_db

    def get_applet_instance(self, applet_name: str) -> Optional["Applet"]:
        """Return the loaded applet instance, or None if not loaded."""
        entry = self._applets_db.get(applet_name)
        if entry is None:
            return None
        evaluated = entry.get("applet_evaluated")
        if evaluated and evaluated is not True:
            return evaluated  # type: ignore[no-any-return]
        return None

    def get_applet_db(self) -> Dict[str, Dict[str, Any]]:
        """Return the raw applet database (for debugging)."""
        return dict(self._applets_db)

    # ------------------------------------------------------------------
    # Service registry
    # ------------------------------------------------------------------

    def register_service(
        self,
        applet_name: str,
        service: str,
        closure: Optional[Callable[..., Any]] = None,
    ) -> None:
        """Register a named service provided by an applet.

        Parameters
        ----------
        applet_name:
            The name of the applet providing the service.
        service:
            The service name.
        closure:
            Optional callable.  If provided, this callable is invoked
            directly instead of loading the applet and calling a method.
        """
        log.debug("register_service applet_name=%s service=%s", applet_name, service)

        if service in self._services:
            log.warn(
                "WARNING: register_service called for existing service: %s",
                service,
            )

        self._services[service] = applet_name
        if closure is not None:
            self._service_closures[service] = closure

    def has_service(self, service: str) -> bool:
        """Return True if a service is registered."""
        return service in self._services

    def call_service(self, service: str, *args: Any, **kwargs: Any) -> Any:
        """Call a registered service by name.

        The applet providing the service is loaded on demand.
        The method matching the service name is called on the applet
        instance (or the registered closure, if one was provided).

        Returns None if the service is not registered or the applet
        cannot be loaded.
        """
        log.debug("call_service: %s", service)

        applet_name = self._services.get(service)
        if applet_name is None:
            return None

        # Check for a registered closure first
        closure = self._service_closures.get(service)
        if closure is not None:
            return closure(*args, **kwargs)

        # Load the applet on demand
        applet = self.load_applet(applet_name)
        if applet is None:
            return None

        # Call the service method on the applet
        method = getattr(applet, service, None)
        if method is None:
            log.error(
                "Applet %s has no method %s for service",
                applet_name,
                service,
            )
            return None

        return method(*args, **kwargs)

    # ------------------------------------------------------------------
    # Default settings management
    # ------------------------------------------------------------------

    def add_default_setting(
        self, applet_name: str, setting_name: str, setting_value: Any
    ) -> None:
        """Add a global default setting override for an applet."""
        if applet_name not in self._default_settings:
            self._default_settings[applet_name] = {}
        self._default_settings[applet_name][setting_name] = setting_value

    def set_default_settings(self, applet_name: str, settings: Dict[str, Any]) -> None:
        """Set all global default settings for an applet."""
        self._default_settings[applet_name] = dict(settings)

    # ------------------------------------------------------------------
    # Settings persistence
    # ------------------------------------------------------------------

    def _load_settings(self, entry: Dict[str, Any]) -> None:
        """Load persisted settings for an applet entry."""
        if entry["settings"] is not None:
            return  # Already loaded

        applet_name = entry["applet_name"]
        filepath = Path(entry["settings_filepath"])

        log.debug("_load_settings: %s", applet_name)

        # Try JSON format first (our native format)
        if filepath.exists():
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                entry["settings"] = data
                return
            except (json.JSONDecodeError, OSError) as exc:
                log.error("Error reading %s settings: %s", applet_name, exc)

        # Try legacy Lua settings format (.lua extension)
        legacy_lua = filepath.with_suffix(".lua")
        if legacy_lua.exists():
            settings = self._load_lua_settings(legacy_lua, applet_name)
            if settings is not None:
                entry["settings"] = settings
                return

        # Try legacy settings in the applet directory
        legacy_dir = Path(entry["dirpath"]) / "settings.lua"
        if legacy_dir.exists():
            settings = self._load_lua_settings(legacy_dir, applet_name)
            if settings is not None:
                entry["settings"] = settings

    def _store_settings(self, entry: Any) -> None:
        """Persist applet settings to disk as JSON.

        *entry* may be either the full applet-database dict **or** a
        plain applet-name string.  Several applets (SlimDiscovery,
        SlimMenus, ChooseMusicSource) historically pass the name; we
        resolve it to the DB entry here so that settings are actually
        written to disk.
        """
        if isinstance(entry, str):
            resolved = self._applets_db.get(entry)
            if resolved is None:
                log.error("_store_settings: unknown applet %r", entry)
                return
            entry = resolved
        applet_name = entry["applet_name"]
        log.info("store settings: %s", applet_name)

        filepath = entry["settings_filepath"]
        settings = entry.get("settings")
        if settings is None:
            return

        try:
            content = json.dumps(
                settings, indent=2, ensure_ascii=False, default=self._json_default
            )
            if self._system is not None:
                self._system.atomic_write(filepath, content)
            else:
                # Fallback: direct write
                Path(filepath).parent.mkdir(parents=True, exist_ok=True)
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(content)
        except Exception as exc:
            log.error("Error storing settings for %s: %s", applet_name, exc)

    @staticmethod
    def _json_default(obj: Any) -> Any:
        """Custom JSON fallback for non-serializable objects.

        Widget instances, callables, and other non-JSON-safe values can
        end up in settings dicts (e.g. a RadioButton passed as a
        positional argument to a closure).  Instead of crashing
        ``_store_settings`` we skip these values with a warning and
        store ``None``.
        """
        type_name = type(obj).__name__
        log.warning(
            "_store_settings: skipping non-serializable value %s (%r)",
            type_name,
            obj,
        )
        return None

    @staticmethod
    def _load_lua_settings(
        filepath: Path, applet_name: str
    ) -> Optional[Dict[str, Any]]:
        """Attempt to load settings from a Lua-format file.

        The Lua settings files look like::

            settings = { key = value, ... }

        We do a best-effort parse using a simple approach:
        try to extract JSON-like content.  For full Lua table
        parsing, a dedicated parser would be needed.

        Returns None if parsing fails.
        """
        try:
            text = filepath.read_text(encoding="utf-8")
            # Simple heuristic: if it looks like a Lua assignment,
            # try to extract the value part and parse as JSON-ish
            # For now, just return None and let the applet use defaults.
            # Full Lua table parsing is out of scope for this port.
            log.debug(
                "Legacy Lua settings found for %s at %s (not parsed)",
                applet_name,
                filepath,
            )
            return None
        except OSError as exc:
            log.error("Error reading legacy settings for %s: %s", applet_name, exc)
            return None

    # ------------------------------------------------------------------
    # Locale strings
    # ------------------------------------------------------------------

    def _load_locale_strings(self, entry: Dict[str, Any]) -> None:
        """Load the strings.txt file for an applet.

        Searches for ``strings.txt`` in the applet's primary directory
        first, then across all search paths under
        ``applets/<applet_name>/strings.txt``.  This matches the Lua
        original where assets and code can live in different search-path
        roots (e.g. ``jive/applets/X/`` for code vs
        ``share/jive/applets/X/`` for assets).
        """
        if entry.get("strings_table") is not None:
            return  # Already loaded

        applet_name = entry["applet_name"]
        log.debug("_load_locale_strings: %s", applet_name)

        if self._locale is None:
            entry["strings_table"] = None
            return

        # 1. Try the primary applet directory
        strings_file = Path(entry["dirpath"]) / "strings.txt"
        if strings_file.exists():
            try:
                entry["strings_table"] = self._locale.read_strings_file(
                    str(strings_file)
                )
                return
            except Exception as exc:
                log.error("Error loading strings for %s: %s", applet_name, exc)

        # 2. Search all search paths for applets/<name>/strings.txt
        search_paths: List[Path] = []
        if self._system is not None:
            search_paths.extend(self._system.search_paths)

        for base in search_paths:
            candidate = base / "applets" / applet_name / "strings.txt"
            if candidate.exists():
                try:
                    entry["strings_table"] = self._locale.read_strings_file(
                        str(candidate)
                    )
                    log.debug("Loaded strings for %s from %s", applet_name, candidate)
                    return
                except Exception as exc:
                    log.error(
                        "Error loading strings for %s from %s: %s",
                        applet_name,
                        candidate,
                        exc,
                    )

        entry["strings_table"] = None

    # ------------------------------------------------------------------
    # Load priority
    # ------------------------------------------------------------------

    @staticmethod
    def _get_load_priority(applet_dir: Path) -> int:
        """Read the load priority for an applet.

        Looks for a ``loadPriority.lua`` or ``load_priority.txt`` file
        in the applet directory.  Returns 100 (default) if not found.
        """
        # Try Python/text format
        for filename in ("load_priority.txt", "loadPriority.txt"):
            pf = applet_dir / filename
            if pf.exists():
                try:
                    text = pf.read_text(encoding="utf-8").strip()
                    return int(text)
                except (ValueError, OSError) as exc:
                    log.debug("_read_load_priority: could not read %s: %s", pf, exc)

        # Try Lua format: loadPriority = <number>
        lua_file = applet_dir / "loadPriority.lua"
        if lua_file.exists():
            try:
                text = lua_file.read_text(encoding="utf-8")
                for line in text.splitlines():
                    line = line.strip()
                    if line.startswith("loadPriority"):
                        # loadPriority = 50
                        parts = line.split("=", 1)
                        if len(parts) == 2:
                            return int(parts[1].strip())
            except (ValueError, OSError) as exc:
                log.debug("_read_load_priority: could not parse %s: %s", lua_file, exc)

        return 100

    # ------------------------------------------------------------------
    # Module import helpers
    # ------------------------------------------------------------------

    def _import_meta_class(self, entry: Dict[str, Any]) -> Optional[type]:
        """Import and return the Meta class from the applet's meta module."""
        applet_name = entry["applet_name"]
        dirpath = Path(entry["dirpath"])
        meta_file = dirpath / f"{applet_name}Meta.py"

        if not meta_file.is_file():
            return None

        module_name = entry["meta_module"]
        return self._import_class_from_file(
            meta_file, module_name, f"{applet_name}Meta"
        )

    def _import_applet_class(self, entry: Dict[str, Any]) -> Optional[type]:
        """Import and return the Applet class from the applet's module."""
        applet_name = entry["applet_name"]
        dirpath = Path(entry["dirpath"])
        applet_file = dirpath / f"{applet_name}Applet.py"

        if not applet_file.is_file():
            return None

        module_name = entry["applet_module"]
        return self._import_class_from_file(
            applet_file, module_name, f"{applet_name}Applet"
        )

    @staticmethod
    def _import_class_from_file(
        filepath: Path, module_name: str, class_name: str
    ) -> Optional[type]:
        """Import a Python file and extract a class by name.

        Uses importlib to load the module from a file path.  The
        module is registered in ``sys.modules`` so subsequent imports
        reuse the same module object.
        """
        # Check if already imported
        if module_name in sys.modules:
            mod = sys.modules[module_name]
            cls = getattr(mod, class_name, None)
            if cls is not None:
                return cls  # type: ignore[no-any-return]

        try:
            spec = importlib.util.spec_from_file_location(module_name, str(filepath))
            if spec is None or spec.loader is None:
                return None

            mod = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = mod
            spec.loader.exec_module(mod)

            cls = getattr(mod, class_name, None)
            return cls
        except Exception as exc:
            log.error("Error importing %s from %s: %s", class_name, filepath, exc)
            # Clean up partially loaded module
            sys.modules.pop(module_name, None)
            return None

    # ------------------------------------------------------------------
    # Sorting
    # ------------------------------------------------------------------

    def _sorted_applet_db(self) -> List[Dict[str, Any]]:
        """Return applet entries sorted by load priority then name."""
        entries = list(self._applets_db.values())
        entries.sort(key=lambda e: (e["load_priority"], e["applet_name"]))
        return entries

    # ------------------------------------------------------------------
    # Repr
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        n_total = len(self._applets_db)
        n_loaded = sum(
            1
            for e in self._applets_db.values()
            if e["applet_evaluated"] and e["applet_evaluated"] is not True
        )
        n_services = len(self._services)
        return (
            f"AppletManager(applets={n_total}, loaded={n_loaded}, "
            f"services={n_services})"
        )
