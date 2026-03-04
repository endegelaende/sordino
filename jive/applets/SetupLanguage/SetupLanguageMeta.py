"""
jive.applets.SetupLanguage.SetupLanguageMeta — Meta class for SetupLanguage.

Ported from ``share/jive/applets/SetupLanguage/SetupLanguageMeta.lua`` in the
original jivelite project.

The Meta class:

* Declares version compatibility (1, 1)
* Provides default settings (``locale: "EN"``)
* Sets the current locale from persisted settings during registration
* Registers the ``setupShowSetupLanguage`` service
* Adds a "Language" menu item under ``advancedSettings``

The Lua original::

    function defaultSettings(meta)
        return { locale = "EN" }
    end

    function registerApplet(meta)
        locale:setLocale(meta:getSettings().locale)
        meta:registerService("setupShowSetupLanguage")
        jiveMain:addItem(meta:menuItem(
            'appletSetupLanguage', 'advancedSettings', "LANGUAGE",
            function(applet, ...) applet:settingsShow(...) end
        ))
    end

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from jive.applet_meta import AppletMeta
from jive.utils.log import logger

__all__ = ["SetupLanguageMeta"]

log = logger("applet.SetupLanguage")


class SetupLanguageMeta(AppletMeta):
    """Meta-information for the SetupLanguage applet.

    Initializes the locale subsystem from persisted settings, registers
    the ``setupShowSetupLanguage`` service (used by the SetupWelcome
    wizard), and adds a "Language" menu item under ``advancedSettings``
    for changing the language at any time.
    """

    # ------------------------------------------------------------------
    # Required overrides
    # ------------------------------------------------------------------

    def jive_version(self) -> Tuple[int, int]:
        return (1, 1)

    def default_settings(self) -> Optional[Dict[str, Any]]:
        """Return default settings — English locale."""
        return {
            "locale": "EN",
        }

    def register_applet(self) -> None:
        """Initialize locale, register service, and add menu item.

        1. Restore the persisted locale setting so that all UI strings
           are displayed in the user's language from the start.
        2. Register the ``setupShowSetupLanguage`` service so the
           SetupWelcome wizard (or any other caller) can open the
           language selection screen.
        3. Add a "Language" menu item under ``advancedSettings`` that
           opens the settings-style language picker.
        """
        # -- Restore persisted locale -----------------------------------
        settings = self.get_settings()
        if settings is None:
            settings = self.default_settings() or {}
            self._settings = settings

        current_locale = settings.get("locale", "EN")

        locale_mod = self._get_locale_module()
        if locale_mod is not None:
            try:
                if hasattr(locale_mod, "setLocale"):
                    locale_mod.setLocale(current_locale)
                elif hasattr(locale_mod, "set_locale"):
                    locale_mod.set_locale(current_locale)
                log.debug("Restored locale to %s", current_locale)
            except Exception as exc:
                log.warn("Failed to set locale to %s: %s", current_locale, exc)
        else:
            log.debug("Locale module not available — skipping locale restore")

        # -- Register setupShowSetupLanguage service --------------------
        self.register_service("setupShowSetupLanguage")

        # -- Add Language menu item under advancedSettings ---------------
        jive_main = self._get_jive_main()
        if jive_main is not None:
            jive_main.add_item(
                self.menu_item(
                    id="appletSetupLanguage",
                    node="advancedSettings",
                    label="LANGUAGE",
                    closure=lambda applet, menu_item: applet.settingsShow(menu_item),
                )
            )
        else:
            log.debug("register_applet: JiveMain not available — menu item not added")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_locale_module() -> Any:
        """Try to obtain the locale singleton instance."""
        try:
            from jive.utils.locale import get_locale_instance

            return get_locale_instance()
        except (ImportError, Exception) as exc:
            log.debug("_get_locale_module: get_locale_instance not available: %s", exc)
        try:
            from jive.utils import locale as _locale_mod

            return _locale_mod
        except ImportError as exc:
            log.debug("_get_locale_module: locale module not importable: %s", exc)
            return None

    @staticmethod
    def _get_jive_main() -> Any:
        """Try to obtain the JiveMain singleton."""
        try:
            from jive.jive_main import jive_main

            return jive_main
        except (ImportError, AttributeError) as exc:
            log.debug("_get_jive_main: jive_main not available: %s", exc)
        try:
            import jive.jive_main as _mod

            return getattr(_mod, "jive_main", None)
        except ImportError:
            return None
