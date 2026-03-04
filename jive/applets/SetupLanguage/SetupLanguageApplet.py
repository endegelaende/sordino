"""
jive.applets.SetupLanguage.SetupLanguageApplet — Language selection applet.

Ported from ``share/jive/applets/SetupLanguage/SetupLanguageApplet.lua``
in the original jivelite project.

This applet provides two entry points:

* ``setupShowSetupLanguage(next_callback, help_text)`` — the first-run
  language selection screen used by the SetupWelcome wizard.  The menu
  is not closeable (user must pick a language to proceed).
* ``settingsShow(menu_item)`` — the settings-style language picker
  with radio buttons, accessible from the advanced settings menu.

Both screens list all available locales, allow the user to preview
the language (by temporarily switching strings), and persist the
selection.

Supported locales (matching the Lua original):

    NO (Norsk), SV (Svenska), FI (Suomi), DA (Dansk), DE (Deutsch),
    EN (English), ES (Español), FR (Français), IT (Italiano),
    NL (Nederlands), RU (русский), PL (Polski), CS (Čeština)

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

from jive.applet import Applet
from jive.ui.timer import Timer
from jive.utils.log import logger

__all__ = ["SetupLanguageApplet"]

log = logger("applet.SetupLanguage")

# Locale definitions: code → (display_name, sort_weight)
# Lower weight = higher in list; weight-then-alpha sorting is used.
_LOCALES: Dict[str, Tuple[str, int]] = {
    "NO": ("Norsk", 10),
    "SV": ("Svenska", 10),
    "FI": ("Suomi", 10),
    "DA": ("Dansk", 10),
    "DE": ("Deutsch", 2),
    "EN": ("English", 1),
    "ES": ("Español", 10),
    "FR": ("Français", 4),
    "IT": ("Italiano", 10),
    "NL": ("Nederlands", 3),
    "RU": ("русский", 10),
    "PL": ("Polski", 10),
    "CS": ("Čeština", 10),
}


class SetupLanguageApplet(Applet):
    """Language selection applet.

    Provides the language selection UI for both the first-run wizard
    and the advanced-settings menu.  Locale changes are applied
    globally via the locale subsystem and persisted to applet settings.
    """

    def __init__(self) -> None:
        super().__init__()
        self.window: Any = None
        self.all_strings: Optional[Dict[str, Dict[str, str]]] = None
        self._style_refresh_timer: Optional[Timer] = None

    # ------------------------------------------------------------------
    # First-run setup entry point (service: setupShowSetupLanguage)
    # ------------------------------------------------------------------

    def setupShowSetupLanguage(
        self,
        setup_next: Optional[Callable[[], None]] = None,
        help_text: Any = None,
    ) -> Any:
        """Show the language selection screen for the first-run wizard.

        This is the service entry point called by ``SetupWelcome``
        (or any caller via ``appletManager.callService``).

        Parameters
        ----------
        setup_next:
            Callback to invoke after the user selects a language.
        help_text:
            If not ``False``, show a help text header above the menu.
            Pass ``False`` to suppress the help text.

        Returns
        -------
        The language selection Window, or ``None`` if UI modules are
        unavailable.
        """
        locale_mod = self._get_locale_module()
        current_locale = "EN"
        if locale_mod is not None:
            try:
                current_locale = locale_mod.get_locale()
            except Exception as exc:
                log.error(
                    "setupShowSetupLanguage: failed to get current locale: %s",
                    exc,
                    exc_info=True,
                )

        log.info("locale currently is %s", current_locale)

        # Load all locale strings for this applet's strings.txt
        self._load_all_strings()

        try:
            from jive.ui.constants import EVENT_WINDOW_INACTIVE
            from jive.ui.simplemenu import SimpleMenu
            from jive.ui.window import Window
        except ImportError as exc:
            log.warn("setupShowSetupLanguage: UI modules not available: %s", exc)
            return None

        window = Window(
            "text_list",
            self.string("CHOOSE_LANGUAGE"),
            "setuptitle",
        )

        if hasattr(window, "set_allow_screensaver"):
            window.set_allow_screensaver(False)
        elif hasattr(window, "setAllowScreensaver"):
            window.setAllowScreensaver(False)

        self.window = window

        # Demo listeners (matching Lua original — safe to skip if actions
        # are not registered)
        self._add_demo_listeners(window)

        # Disable left/right buttons during setup
        if hasattr(window, "set_button_action"):
            try:
                window.set_button_action("lbutton", None)
                window.set_button_action("rbutton", None)
            except Exception as exc:
                log.warning(
                    "setupShowSetupLanguage: failed to disable button actions via set_button_action: %s",
                    exc,
                )
        elif hasattr(window, "setButtonAction"):
            try:
                window.setButtonAction("lbutton", None)
                window.setButtonAction("rbutton", None)
            except Exception as exc:
                log.warning(
                    "setupShowSetupLanguage: failed to disable button actions via setButtonAction: %s",
                    exc,
                )

        menu = SimpleMenu("menu")

        available_locales = self._get_available_locales()

        for loc in available_locales:
            if loc not in _LOCALES:
                log.warn("unknown lang %s", loc)
                continue

            display_name, weight = _LOCALES[loc]
            locale_code = loc  # capture for closure

            menu.addItem(
                {
                    "locale": locale_code,
                    "text": display_name,
                    "sound": "WINDOWSHOW",
                    "callback": lambda *_args, lc=locale_code: self.setLang(
                        lc, setup_next
                    ),
                    "focusGained": lambda *_args, lc=locale_code: self._show_lang(lc),
                    "weight": weight,
                }
            )

        # Sort by weight then alpha
        comparator = getattr(SimpleMenu, "itemComparatorWeightAlpha", None) or getattr(
            SimpleMenu, "item_comparator_weight_alpha", None
        )
        if comparator is not None:
            if hasattr(menu, "setComparator"):
                menu.setComparator(comparator)
            elif hasattr(menu, "set_comparator"):
                menu.set_comparator(comparator)

        # Select the current locale in the menu
        self._select_locale_in_menu(menu, current_locale)

        # Add help text header (unless explicitly suppressed)
        if help_text is not False:
            try:
                from jive.ui.textarea import Textarea

                header = Textarea("help_text", self.string("CHOOSE_LANGUAGE_HELP"))
                if hasattr(menu, "setHeaderWidget"):
                    menu.setHeaderWidget(header)
                elif hasattr(menu, "set_header_widget"):
                    menu.set_header_widget(header)
            except ImportError as exc:
                log.debug(
                    "setupShowSetupLanguage: Textarea not available for help text: %s",
                    exc,
                )

        window.add_widget(menu)

        # Store the selected language when the menu is exited
        def _on_inactive(event: Any = None) -> int:
            self._show_lang(None)
            self.store_settings()
            from jive.ui.constants import EVENT_UNUSED

            return int(EVENT_UNUSED)

        window.add_listener(int(EVENT_WINDOW_INACTIVE), _on_inactive)

        # Menu is not closeable during setup (user must select)
        if hasattr(menu, "setCloseable"):
            menu.setCloseable(False)
        elif hasattr(menu, "set_closeable"):
            menu.set_closeable(False)

        self.tie_and_show_window(window)
        return window

    # Lua-compatible alias
    setup_show_setup_language = setupShowSetupLanguage

    # ------------------------------------------------------------------
    # Settings entry point (from advanced settings menu)
    # ------------------------------------------------------------------

    def settingsShow(self, menu_item: Any = None) -> Any:
        """Show the language settings screen with radio buttons.

        This is the entry point for the "Language" menu item in
        advanced settings.

        Parameters
        ----------
        menu_item:
            The menu item dict that triggered this call.

        Returns
        -------
        The settings Window, or ``None`` if UI modules are unavailable.
        """
        locale_mod = self._get_locale_module()
        current_locale = "EN"
        if locale_mod is not None:
            try:
                current_locale = locale_mod.get_locale()
            except Exception as exc:
                log.error(
                    "settingsShow: failed to get current locale: %s", exc, exc_info=True
                )

        log.info("locale currently is %s", current_locale)

        # Load all locale strings for preview
        self._load_all_strings()

        try:
            from jive.ui.constants import EVENT_WINDOW_POP
            from jive.ui.simplemenu import SimpleMenu
            from jive.ui.window import Window
        except ImportError as exc:
            log.warn("settingsShow: UI modules not available: %s", exc)
            return None

        title = self.string("LANGUAGE")
        if menu_item and isinstance(menu_item, dict):
            title = menu_item.get("text", title)

        window = Window("text_list", title, "settingstitle")
        menu = SimpleMenu("menu")

        # Try to use RadioGroup + RadioButton for settings-style UI
        radio_group = self._make_radio_group()

        available_locales = self._get_available_locales()

        for loc in available_locales:
            if loc not in _LOCALES:
                log.warn("unknown lang %s", loc)
                continue

            display_name, weight = _LOCALES[loc]
            locale_code = loc  # capture for closure

            if radio_group is not None:
                button = self._make_radio_button(
                    radio_group,
                    lambda *_args, lc=locale_code: self.setLang(lc),
                    locale_code == current_locale,
                )
                if button is not None:
                    menu.addItem(
                        {
                            "locale": locale_code,
                            "text": display_name,
                            "style": "item_choice",
                            "check": button,
                            "focusGained": lambda *_args, lc=locale_code: (
                                self._show_lang(lc)
                            ),
                            "weight": weight,
                        }
                    )
                    continue

            # Fallback: simple callback item
            menu.addItem(
                {
                    "locale": locale_code,
                    "text": display_name,
                    "sound": "WINDOWSHOW",
                    "callback": lambda *_args, lc=locale_code: self.setLang(lc),
                    "focusGained": lambda *_args, lc=locale_code: self._show_lang(lc),
                    "weight": weight,
                }
            )

        # Sort by weight then alpha
        comparator = getattr(SimpleMenu, "itemComparatorWeightAlpha", None) or getattr(
            SimpleMenu, "item_comparator_weight_alpha", None
        )
        if comparator is not None:
            if hasattr(menu, "setComparator"):
                menu.setComparator(comparator)
            elif hasattr(menu, "set_comparator"):
                menu.set_comparator(comparator)

        # Select the current locale
        self._select_locale_in_menu(menu, current_locale)

        window.add_widget(menu)

        # Store settings when the window is popped
        def _on_pop(event: Any = None) -> int:
            self._show_lang(None)
            self.store_settings()
            from jive.ui.constants import EVENT_UNUSED

            return int(EVENT_UNUSED)

        window.add_listener(int(EVENT_WINDOW_POP), _on_pop)

        self.tie_and_show_window(window)
        return window

    # Lua-compatible alias
    settings_show = settingsShow

    # ------------------------------------------------------------------
    # Language preview and application
    # ------------------------------------------------------------------

    def _show_lang(self, choice: Optional[str]) -> None:
        """Preview a language by temporarily updating the strings table.

        If *choice* is ``None``, restores the persisted locale.

        This mirrors the Lua original which directly modifies the
        applet's ``_stringsTable`` for instant preview without a full
        locale reload.

        Parameters
        ----------
        choice:
            The locale code to preview, or ``None`` to restore default.
        """
        if choice is None:
            settings = self.get_settings()
            choice = settings.get("locale", "EN") if settings else "EN"

        if self.all_strings and self._strings_table is not None:
            locale_strings = self.all_strings.get(choice, {})
            en_strings = self.all_strings.get("EN", {})

            for key in self._strings_table:
                entry = self._strings_table[key]
                # The entry may be a LocalizedString object or a plain value
                new_value = locale_strings.get(key) or en_strings.get(key)
                if new_value is not None:
                    if hasattr(entry, "str"):
                        entry.str = new_value  # type: ignore[union-attr]
                    elif hasattr(entry, "_value"):
                        entry._value = new_value  # type: ignore[attr-defined]

        # Trigger a style refresh to update displayed strings.
        # This MUST be deferred — calling style_changed() synchronously
        # inside an event handler (e.g. focusGained) causes re-skinning
        # of all windows mid-dispatch, which can deadlock or loop.
        # We use a one-shot Timer with 0 ms delay so it fires on the
        # next event-loop iteration, outside the callback stack.
        if self._style_refresh_timer is not None:
            self._style_refresh_timer.stop()

        def _deferred_style_refresh() -> None:
            fw = self._get_framework()
            if fw is not None and hasattr(fw, "style_changed"):
                try:
                    fw.style_changed()
                except Exception as exc:
                    log.warning("_show_lang: deferred style_changed() failed: %s", exc)
            elif fw is not None and hasattr(fw, "styleChanged"):
                try:
                    fw.styleChanged()
                except Exception as exc:
                    log.warning("_show_lang: deferred styleChanged() failed: %s", exc)

        self._style_refresh_timer = Timer(0, _deferred_style_refresh, once=True)
        self._style_refresh_timer.start()

    def setLang(
        self,
        choice: str,
        next_callback: Optional[Callable[[], None]] = None,
    ) -> None:
        """Apply the selected language and optionally proceed to next step.

        Persists the locale choice in settings, applies the locale
        globally, refreshes the UI, and optionally re-requests the
        server menu for the new language.

        Parameters
        ----------
        choice:
            The locale code (e.g. ``"EN"``, ``"DE"``, ``"FR"``).
        next_callback:
            Optional callback to invoke after the locale has been applied.
        """
        log.info("Locale choice set to %s", choice)

        # Preview the language strings immediately (deferred style refresh)
        self._show_lang(choice)

        # Persist in settings
        settings = self.get_settings()
        if settings is None:
            settings = {}
            self.set_settings(settings)
        settings["locale"] = choice

        # Re-request the server menu if connected to a player
        self._refresh_server_menu()

        # Apply the locale globally via a Task (heavy work: full locale
        # reload + style refresh + popup).  The Task runs cooperatively
        # on the next event-loop iteration, avoiding blocking the
        # current event-dispatch stack.
        self._apply_locale(choice, next_callback)

    # Lua-compatible alias
    set_lang = setLang

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _apply_locale(
        self,
        choice: str,
        next_callback: Optional[Callable[[], None]] = None,
    ) -> None:
        """Apply the locale, optionally with a loading popup.

        Attempts to show a spinner popup during locale loading (matching
        the Lua original).  Falls back to synchronous application.
        """
        locale_mod = self._get_locale_module()
        fw = self._get_framework()
        jive_main = self._get_jive_main()

        popup = None
        try:
            from jive.ui.icon import Icon
            from jive.ui.label import Label
            from jive.ui.popup import Popup

            popup = Popup("waiting_popup")
            if hasattr(popup, "set_allow_screensaver"):
                popup.set_allow_screensaver(False)
            elif hasattr(popup, "setAllowScreensaver"):
                popup.setAllowScreensaver(False)
            if hasattr(popup, "set_always_on_top"):
                popup.set_always_on_top(True)
            elif hasattr(popup, "setAlwaysOnTop"):
                popup.setAlwaysOnTop(True)
            if hasattr(popup, "set_auto_hide"):
                popup.set_auto_hide(False)
            elif hasattr(popup, "setAutoHide"):
                popup.setAutoHide(False)
            if hasattr(popup, "ignoreAllInputExcept"):
                popup.ignoreAllInputExcept()
            elif hasattr(popup, "ignore_all_input_except"):
                popup.ignore_all_input_except()

            popup.add_widget(Icon("icon_connecting"))
            loading_text = self.string("LOADING_LANGUAGE")
            if loading_text == "LOADING_LANGUAGE":
                loading_text = "Loading…"
            popup.add_widget(Label("text", loading_text))
            popup.show()
        except (ImportError, Exception) as exc:
            log.debug("Could not show loading popup: %s", exc)
            popup = None

        def _do_apply(obj: Any = None) -> None:
            """Perform the actual locale switch.

            Parameters
            ----------
            obj:
                The object passed by ``Task.resume()`` (the applet
                instance).  Accepted but unused — we capture everything
                we need via closure.
            """
            if locale_mod is not None:
                try:
                    if hasattr(locale_mod, "set_locale"):
                        locale_mod.set_locale(choice, True)
                    elif hasattr(locale_mod, "setLocale"):
                        locale_mod.setLocale(choice, True)
                except Exception as exc:
                    log.warn("Failed to apply locale %s: %s", choice, exc)

            # Refresh main menu nodes
            if jive_main is not None:
                if hasattr(jive_main, "jiveMainNodes"):
                    try:
                        jive_main.jiveMainNodes()
                    except Exception as exc:
                        log.error(
                            "_apply_locale: jiveMainNodes() failed: %s",
                            exc,
                            exc_info=True,
                        )
                elif hasattr(jive_main, "jive_main_nodes"):
                    try:
                        jive_main.jive_main_nodes()
                    except Exception as exc:
                        log.error(
                            "_apply_locale: jive_main_nodes() failed: %s",
                            exc,
                            exc_info=True,
                        )

            # Trigger style change
            if fw is not None:
                if hasattr(fw, "styleChanged"):
                    try:
                        fw.styleChanged()
                    except Exception as exc:
                        log.warning("_apply_locale: styleChanged() failed: %s", exc)
                elif hasattr(fw, "style_changed"):
                    try:
                        fw.style_changed()
                    except Exception as exc:
                        log.warning("_apply_locale: style_changed() failed: %s", exc)

            # Hide popup
            if popup is not None:
                try:
                    popup.hide()
                except Exception as exc:
                    log.warning("_apply_locale: failed to hide loading popup: %s", exc)

            # Invoke next step
            if next_callback is not None:
                try:
                    next_callback()
                except Exception as exc:
                    log.warn("next_callback failed: %s", exc)

        # Try to use a Task for cooperative scheduling
        try:
            from jive.ui.task import Task

            task = Task("setLang", self, _do_apply)
            if hasattr(task, "addTask"):
                task.addTask()
            elif hasattr(task, "add_task"):
                task.add_task()
            else:
                _do_apply()
        except ImportError:
            _do_apply()

    def _refresh_server_menu(self) -> None:
        """Re-request the server menu for the new language.

        If connected to a player and server, sends a ``menu 0 100``
        request to refresh server-driven menu items in the new locale.
        """
        mgr = self._get_applet_manager()
        if mgr is None:
            return

        try:
            player = mgr.call_service("getCurrentPlayer")
            if player is None:
                return

            server = None
            if hasattr(player, "getSlimServer"):
                server = player.getSlimServer()
            elif hasattr(player, "get_slim_server"):
                server = player.get_slim_server()

            if server is None:
                return

            player_id = None
            if hasattr(player, "getId"):
                player_id = player.getId()
            elif hasattr(player, "get_id"):
                player_id = player.get_id()

            if player_id and hasattr(server, "userRequest"):
                server.userRequest(None, player_id, ["menu", 0, 100])
            elif player_id and hasattr(server, "user_request"):
                server.user_request(None, player_id, ["menu", 0, 100])

        except Exception as exc:
            log.debug("_refresh_server_menu: %s", exc)

    def _load_all_strings(self) -> None:
        """Load all locale translations from this applet's strings.txt.

        Uses the locale module's ``load_all_strings()`` to parse the
        strings file and obtain a dict of ``{locale: {token: value}}``.
        """
        locale_mod = self._get_locale_module()
        if locale_mod is None:
            return

        if self._entry is None:
            return

        dirpath = self._entry.get("dirpath", "")
        if not dirpath:
            return

        import os

        strings_path = os.path.join(dirpath, "strings.txt")

        if not os.path.isfile(strings_path):
            log.debug("strings.txt not found at %s", strings_path)
            return

        try:
            if hasattr(locale_mod, "load_all_strings"):
                self.all_strings = locale_mod.load_all_strings(strings_path)
            elif hasattr(locale_mod, "loadAllStrings"):
                self.all_strings = locale_mod.loadAllStrings(strings_path)
            else:
                log.debug("locale module has no load_all_strings method")
        except Exception as exc:
            log.warn("Failed to load all strings: %s", exc)

    def _get_available_locales(self) -> List[str]:
        """Get the list of available locales.

        Uses the locale module's ``get_all_locales()`` if available,
        otherwise falls back to the keys of ``_LOCALES``.
        """
        locale_mod = self._get_locale_module()
        if locale_mod is not None:
            try:
                if hasattr(locale_mod, "get_all_locales"):
                    locales = locale_mod.get_all_locales()
                    if locales:
                        return locales  # type: ignore[no-any-return]
                elif hasattr(locale_mod, "getAllLocales"):
                    locales = locale_mod.getAllLocales()
                    if locales:
                        return locales  # type: ignore[no-any-return]
            except Exception as exc:
                log.error(
                    "_get_available_locales: failed to retrieve locales: %s",
                    exc,
                    exc_info=True,
                )

        return sorted(_LOCALES.keys())

    def _add_demo_listeners(self, window: Any) -> None:
        """Add demo-mode action listeners (matching Lua original).

        These are used on hardware devices (Jive, Baby, Fab4) to
        jump to an in-store demo mode.  Safe to skip on desktop.
        """
        mgr = self._get_applet_manager()
        if mgr is None:
            return

        def _jump_to_demo(event: Any = None) -> None:
            try:
                mgr.call_service("jumpToInStoreDemo")
            except Exception as exc:
                log.error(
                    "_add_demo_listeners: jumpToInStoreDemo service call failed: %s",
                    exc,
                    exc_info=True,
                )

        try:
            if hasattr(window, "add_action_listener"):
                window.add_action_listener("start_demo", self, _jump_to_demo)
            elif hasattr(window, "addActionListener"):
                window.addActionListener("start_demo", self, _jump_to_demo)
        except Exception as exc:
            log.warning(
                "_add_demo_listeners: failed to add start_demo action listener: %s", exc
            )

    @staticmethod
    def _select_locale_in_menu(menu: Any, locale_code: str) -> None:
        """Select the menu item matching *locale_code*."""
        try:
            iterator = None
            if hasattr(menu, "iterator"):
                iterator = menu.iterator()
            elif hasattr(menu, "__iter__"):
                iterator = enumerate(menu, start=1)

            if iterator is not None:
                for i, item in iterator:
                    item_locale = item.get("locale") if isinstance(item, dict) else None
                    if item_locale == locale_code:
                        if hasattr(menu, "setSelectedIndex"):
                            menu.setSelectedIndex(i)
                        elif hasattr(menu, "set_selected_index"):
                            menu.set_selected_index(i)
                        break
        except Exception as exc:
            log.warning(
                "_select_locale_in_menu: failed to select locale '%s': %s",
                locale_code,
                exc,
            )

    @staticmethod
    def _make_radio_group() -> Any:
        """Try to create a RadioGroup widget."""
        try:
            from jive.ui.radio import RadioGroup

            return RadioGroup()
        except ImportError as exc:
            log.debug("_make_radio_group: jive.ui.radio not available: %s", exc)
            return None

    @staticmethod
    def _make_radio_button(
        group: Any,
        callback: Callable[[], None],
        is_selected: bool,
    ) -> Any:
        """Try to create a RadioButton widget."""
        try:
            from jive.ui.radio import RadioButton

            return RadioButton("radio", group, callback, is_selected)
        except ImportError as exc:
            log.debug("_make_radio_button: jive.ui.radio not available: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Singleton accessors
    # ------------------------------------------------------------------

    @staticmethod
    def _get_locale_module() -> Any:
        """Try to obtain the locale module singleton."""
        try:
            from jive.utils.locale import get_locale_instance

            return get_locale_instance()
        except (ImportError, Exception) as exc:
            log.debug("_get_locale_module: get_locale_instance not available: %s", exc)
        try:
            from jive.utils import locale as _mod

            return _mod
        except ImportError as exc:
            log.debug("_get_locale_module: jive.utils.locale not available: %s", exc)
            return None

    @staticmethod
    def _get_framework() -> Any:
        """Try to obtain the Framework singleton."""
        try:
            from jive.ui.framework import framework

            return framework
        except (ImportError, AttributeError):
            return None

    @staticmethod
    def _get_jive_main() -> Any:
        """Try to obtain the JiveMain singleton."""
        try:
            from jive.jive_main import jive_main

            return jive_main
        except (ImportError, AttributeError) as exc:
            log.debug("_get_jive_main: direct import failed: %s", exc)
        try:
            import jive.jive_main as _mod

            return getattr(_mod, "jive_main", None)
        except ImportError as exc:
            log.debug("_get_jive_main: module import failed: %s", exc)
            return None

    @staticmethod
    def _get_applet_manager() -> Any:
        """Try to obtain the AppletManager singleton."""
        try:
            from jive.applet_manager import applet_manager

            return applet_manager
        except (ImportError, AttributeError):
            return None
