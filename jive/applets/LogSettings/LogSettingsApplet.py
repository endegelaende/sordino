"""
jive.applets.LogSettings.LogSettingsApplet — Log settings applet.

Ported from ``share/jive/applets/LogSettings/LogSettingsApplet.lua``
in the original jivelite project.

This applet provides a UI for viewing and changing the verbosity level
of log categories at runtime.  It discovers all registered log categories,
displays them in a sorted menu with a Choice widget for each, and
persists changes to a ``logconf.json`` file in the user directory.

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional, Tuple

from jive.applet import Applet
from jive.utils.log import logger

__all__ = ["LogSettingsApplet"]

log = logger("applet.LogSettings")

# Log levels in display order (matching the Lua original)
_LEVELS = ["Debug", "Info", "Warn", "Error", "Off"]

# Map display names to internal level strings
_LEVEL_TO_INTERNAL: Dict[str, str] = {
    "Debug": "debug",
    "Info": "info",
    "Warn": "warn",
    "Error": "error",
    "Off": "error",  # "Off" maps to highest level to suppress output
}

# Map internal level strings to display index (0-based)
_INTERNAL_TO_INDEX: Dict[str, int] = {
    "debug": 0,
    "info": 1,
    "warn": 2,
    "warning": 2,
    "error": 3,
}


class LogSettingsApplet(Applet):
    """Applet that provides a UI for controlling log category verbosity.

    Discovers all registered log categories, displays each with a
    Choice widget showing the current level, and allows the user to
    change levels on-the-fly.  Level changes are persisted when the
    settings window is closed.
    """

    def __init__(self) -> None:
        super().__init__()

    # ------------------------------------------------------------------
    # Public API (called from menu callback)
    # ------------------------------------------------------------------

    def logSettings(self, menu_item: Any = None) -> Any:
        """Open the log settings window.

        Gathers all log categories, builds a menu with Choice widgets,
        and shows the window.  When the window becomes inactive, the
        current log configuration is saved.

        Parameters
        ----------
        menu_item:
            The menu item dict that triggered this call (used for the
            window title).

        Returns
        -------
        The settings Window instance (or ``None`` if UI is unavailable).
        """
        categories = self._gather_log_categories()

        title = "Debug Log"
        if menu_item and isinstance(menu_item, dict):
            title = menu_item.get("text", title)
        elif menu_item and hasattr(menu_item, "text"):
            title = getattr(menu_item, "text", title)

        try:
            from jive.ui.constants import EVENT_WINDOW_INACTIVE
            from jive.ui.simplemenu import SimpleMenu
            from jive.ui.window import Window
        except ImportError as exc:
            log.warn("logSettings: UI modules not available: %s", exc)
            return None

        window = Window("text_list", title, "settingstitle")

        menu = SimpleMenu("menu", categories)

        # Sort alphabetically by text
        if hasattr(menu, "setComparator"):
            menu.setComparator(SimpleMenu.itemComparatorAlpha)
        elif hasattr(menu, "set_comparator"):
            menu.set_comparator(
                getattr(SimpleMenu, "itemComparatorAlpha", None)
                or getattr(SimpleMenu, "item_comparator_alpha", None)
            )

        window.add_widget(menu)

        # Save log configuration when the window is closed
        def _on_inactive(event: Any = None) -> int:
            self._save_logconf()
            from jive.ui.constants import EVENT_UNUSED

            return int(EVENT_UNUSED)

        window.add_listener(int(EVENT_WINDOW_INACTIVE), _on_inactive)

        self.tie_and_show_window(window)
        return window

    # Lua-compatible alias
    log_settings = logSettings

    # ------------------------------------------------------------------
    # Category discovery
    # ------------------------------------------------------------------

    def _gather_log_categories(self) -> List[Dict[str, Any]]:
        """Discover all log categories and build menu items with Choice widgets.

        Returns a list of menu-item dicts suitable for SimpleMenu,
        each containing a ``text`` (category name) and ``check``
        (Choice widget) field.
        """
        from jive.utils.log import _loggers

        result: List[Dict[str, Any]] = []

        for name in sorted(_loggers.keys()):
            cat = _loggers[name]
            current_level = cat.get_level()

            # Find the matching index in _LEVELS
            idx = _INTERNAL_TO_INDEX.get(current_level.lower(), 3)

            # Try to create a Choice widget
            choice_widget = self._make_choice_widget(name, cat, idx)
            if choice_widget is not None:
                result.append(
                    {
                        "text": name,
                        "style": "item_choice",
                        "check": choice_widget,
                    }
                )
            else:
                # Fallback: plain text item showing current level
                result.append(
                    {
                        "text": f"{name} [{current_level}]",
                    }
                )

        return result

    def _make_choice_widget(self, name: str, cat: Any, selected_index: int) -> Any:
        """Create a Choice widget for a log category.

        Parameters
        ----------
        name:
            The category name (for the callback closure).
        cat:
            The JiveLogger instance.
        selected_index:
            The currently selected index in ``_LEVELS`` (0-based).

        Returns
        -------
        A Choice widget, or ``None`` if the Choice class is unavailable.
        """
        try:
            from jive.ui.choice import Choice
        except ImportError:
            return None

        def _on_change(obj: Any, selected: int) -> None:
            """Called when the user changes the choice."""
            if 0 <= selected < len(_LEVELS):
                level_name = _LEVELS[selected]
                log.debug("set %s to %s", name, level_name)
                internal = _LEVEL_TO_INTERNAL.get(level_name, "warn")
                cat.set_level(internal)

        # Choice widget expects 1-based index in Lua, but Python port
        # may use 0-based.  Try both conventions.
        try:
            choice = Choice(
                "choice",
                _LEVELS,
                _on_change,
                selected_index + 1,  # Lua convention: 1-based
            )
        except (TypeError, IndexError):
            try:
                choice = Choice(
                    "choice",
                    _LEVELS,
                    _on_change,
                    selected_index,  # Python convention: 0-based
                )
            except Exception:
                return None

        return choice

    # ------------------------------------------------------------------
    # Configuration persistence
    # ------------------------------------------------------------------

    def _save_logconf(self) -> None:
        """Save the current log configuration to disk.

        The Lua original saves to ``logconf.lua`` using a Lua table
        format.  The Python port saves to ``logconf.json`` in the
        user directory.

        The saved structure is::

            {
                "category": {
                    "net.http": "DEBUG",
                    "ui.framework": "WARN",
                    ...
                }
            }

        Categories at the default level ("OFF" equivalent) are omitted.
        """
        from jive.utils.log import _loggers

        # Load existing configuration (if any)
        conf_path = self._get_logconf_path()
        logconf: Dict[str, Any] = {"category": {}, "appender": {}}

        if conf_path and os.path.isfile(conf_path):
            try:
                with open(conf_path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    logconf = loaded
                    if "category" not in logconf:
                        logconf["category"] = {}
            except Exception as exc:
                log.warn("Error loading logconf: %s", exc)

        # Update category levels
        categories = logconf.get("category", {})
        for name, cat in _loggers.items():
            level = cat.get_level().upper()
            if level == "OFF" or level == "ERROR":
                # Remove from conf (use default)
                categories.pop(name, None)
            else:
                categories[name] = level

        logconf["category"] = categories

        # Save configuration
        if conf_path:
            try:
                conf_dir = os.path.dirname(conf_path)
                if conf_dir and not os.path.isdir(conf_dir):
                    os.makedirs(conf_dir, exist_ok=True)

                # Write atomically (write to temp, then rename)
                tmp_path = conf_path + ".tmp"
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(logconf, f, indent=2, sort_keys=True)
                    f.write("\n")

                # Atomic rename (on POSIX; on Windows this may not be atomic
                # but is still safe enough for config files)
                try:
                    os.replace(tmp_path, conf_path)
                except OSError:
                    # Fallback for platforms where replace fails
                    if os.path.exists(conf_path):
                        os.remove(conf_path)
                    os.rename(tmp_path, conf_path)

                log.debug("Saved log configuration to %s", conf_path)

            except Exception as exc:
                log.warn("Failed to save logconf: %s", exc)

    def _get_logconf_path(self) -> Optional[str]:
        """Return the path for the log configuration file.

        Returns
        -------
        str or None
            The path to ``logconf.json`` in the user directory.
        """
        user_dir: str | None = None
        try:
            from jive.applet_manager import applet_manager as _mgr

            if _mgr is not None and hasattr(_mgr, "system") and _mgr.system is not None:
                user_dir = str(_mgr.system.get_user_dir())
        except Exception as exc:
            log.error("Failed to get user directory from System: %s", exc, exc_info=True)

        if not user_dir:
            user_dir = os.path.expanduser("~/.jivelite")

        return os.path.join(user_dir, "logconf.json")

    @classmethod
    def load_logconf(cls) -> None:
        """Load and apply log configuration from disk (if it exists).

        This is a class method that can be called at startup to restore
        previously saved log levels.  It reads ``logconf.json`` and
        applies the saved levels to all matching categories.
        """
        instance = cls()
        conf_path = instance._get_logconf_path()
        if not conf_path or not os.path.isfile(conf_path):
            return

        try:
            with open(conf_path, "r", encoding="utf-8") as f:
                logconf = json.load(f)

            if not isinstance(logconf, dict):
                return

            categories = logconf.get("category", {})
            if not isinstance(categories, dict):
                return

            from jive.utils.log import _loggers

            for name, level in categories.items():
                if name in _loggers and isinstance(level, str):
                    _loggers[name].set_level(level.lower())
                    log.debug("Restored log level: %s = %s", name, level)

        except Exception as exc:
            log.warn("Failed to load logconf: %s", exc)
