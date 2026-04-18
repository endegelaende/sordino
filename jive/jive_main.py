"""
jive.jive_main — Main Jive application entry point.

Ported from ``jive/JiveMain.lua`` in the original jivelite project.

JiveMain is the top-level application class that:

* Extends :class:`HomeMenu` to provide the root menu tree.
* Bootstraps the Framework, NetworkThread, AppletManager, and Iconbar.
* Registers default menu nodes (home, settings, extras, etc.).
* Manages skin selection and loading.
* Handles soft-power state (on/off).
* Sets up global input event listeners and action handlers.
* Runs the main event loop.

The Lua original creates global singletons ``jiveMain``, ``appletManager``,
``iconbar``, and ``jnt``.  In this Python port, these are module-level
variables that can be imported by applets and other modules::

    from jive.jive_main import jive_main, applet_manager_instance, iconbar_instance

Or accessed via the class::

    JiveMain.instance  # the singleton JiveMain

Usage::

    from jive.jive_main import JiveMain

    # This creates the singleton and runs the event loop:
    JiveMain()

    # Or for testing without the event loop:
    main = JiveMain(run_event_loop=False)

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Copyright 2013-2014 Adrian Smith (jivelite amendments)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

import math
import os
import random
import sys
import time
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    Iterator,
    List,
    Optional,
    Set,
    Tuple,
    Union,
)

from jive.ui.constants import (
    ACTION,
    EVENT_ALL_INPUT,
    EVENT_CHAR_PRESS,
    EVENT_CONSUME,
    EVENT_IR_ALL,
    EVENT_IR_DOWN,
    EVENT_IR_HOLD,
    EVENT_IR_PRESS,
    EVENT_IR_REPEAT,
    EVENT_IR_UP,
    EVENT_KEY_ALL,
    EVENT_KEY_DOWN,
    EVENT_KEY_HOLD,
    EVENT_KEY_PRESS,
    EVENT_KEY_UP,
    EVENT_MOUSE_ALL,
    EVENT_SCROLL,
    EVENT_UNUSED,
    EVENT_WINDOW_RESIZE,
    KEY_FWD,
    KEY_HOME,
    KEY_REW,
    KEY_VOLUME_DOWN,
    KEY_VOLUME_UP,
)
from jive.utils.log import logger

if TYPE_CHECKING:
    from jive.applet_manager import AppletManager
    from jive.iconbar import Iconbar
    from jive.system import System
    from jive.ui.homemenu import HomeMenu
    from jive.utils.locale import Locale, StringsTable

__all__ = [
    "JiveMain",
    "jive_main",
    "applet_manager_instance",
    "iconbar_instance",
    "jnt_instance",
]

log = logger("jivelite")
log_heap = logger("jivelite.heap")

# ---------------------------------------------------------------------------
# Module-level singletons (set during JiveMain.__init__)
# ---------------------------------------------------------------------------

jive_main: Optional["JiveMain"] = None
applet_manager_instance: Optional["AppletManager"] = None
iconbar_instance: Optional["Iconbar"] = None
jnt_instance: Any = None

# ---------------------------------------------------------------------------
# Squeezebox remote IR codes → key codes (fallback handler)
# ---------------------------------------------------------------------------

_IR_CODES: Dict[int, int] = {
    0x7689C03F: KEY_REW,
    0x7689A05F: KEY_FWD,
    0x7689807F: KEY_VOLUME_UP,
    0x768900FF: KEY_VOLUME_DOWN,
}

# Several submenus created by applets (settings, controller settings, extras)
# should not need to have an id passed when creating it.
_id_translations: Dict[str, str] = {}


# ---------------------------------------------------------------------------
# JiveMain
# ---------------------------------------------------------------------------


class JiveMain:
    """Main Jive application — bootstraps the framework and runs the event loop.

    JiveMain extends the HomeMenu concept: it IS the home menu, and also
    owns the Framework, AppletManager, Iconbar, and NetworkThread.

    In the Lua original, ``JiveMain`` inherits from ``HomeMenu``.  In this
    Python port, we use composition instead of inheritance to avoid
    tight coupling to the UI layer during testing.  The HomeMenu is
    accessible as ``self.home_menu``.

    Parameters
    ----------
    run_event_loop:
        If ``True`` (default), the constructor runs the main event loop
        (blocking).  Set to ``False`` for testing or embedding.
    system:
        Optional :class:`System` instance.  If not provided, a default
        one is created.
    locale:
        Optional :class:`Locale` instance.  If not provided, a default
        one is created.
    init_ui:
        If ``True`` (default), initialize the pygame-based UI framework.
        Set to ``False`` for headless / test operation.
    """

    # JIVE_VERSION — matches the Lua global
    JIVE_VERSION: str = "7.8"

    # Singleton
    instance: Optional["JiveMain"] = None

    def __init__(
        self,
        *,
        run_event_loop: bool = True,
        system: Optional["System"] = None,
        locale: Optional["Locale"] = None,
        init_ui: bool = True,
        allowed_applets: Optional[Set[str]] = None,
    ) -> None:
        global jive_main, applet_manager_instance, iconbar_instance, jnt_instance

        log.info("JiveLite version %s", self.JIVE_VERSION)

        # Seed the RNG
        random.seed(time.time())

        # --- System ---
        if system is None:
            from jive.system import System

            system = System()
        self._system = system
        system.init_user_path_dirs()

        # --- Locale ---
        # Use the module-level singleton so that ALL applets (including
        # SetupLanguageMeta/Applet which call get_locale_instance())
        # share the same Locale object — and therefore the same
        # ``_loaded_files`` weak-dict.  Without this, set_locale()
        # called on the singleton would not reload the StringsTable
        # objects that were registered by the AppletManager through a
        # different Locale instance.
        if locale is None:
            from jive.utils.locale import get_locale_instance

            locale = get_locale_instance()
        else:
            # Caller provided an explicit instance — install it as the
            # module-level singleton so that get_locale_instance()
            # returns the same object everywhere.
            import jive.utils.locale as _locale_mod

            _locale_mod._instance = locale
        self._locale = locale

        # --- Global strings (loaded later, after search paths are set) ---
        self._global_strings: Optional["StringsTable"] = None

        # --- Soft power state ---
        self._soft_power_state: str = "on"

        # --- Skin management ---
        self.skins: Dict[str, Tuple[str, str, str]] = {}
        # skins[skin_id] = (applet_name, display_name, method_name)
        self.selected_skin: Optional[str] = None
        self._skin: Any = None  # The loaded skin applet instance
        self._default_skin: Optional[str] = None
        self._fullscreen: bool = False

        # --- Post-on-screen-init callbacks ---
        self._post_on_screen_inits: List[Callable[[], None]] = []

        # --- HomeMenu (composition) ---
        self.home_menu: Optional[Any] = None
        self.window: Optional[Any] = None

        # --- Framework / UI init ---
        self._init_ui = init_ui
        self._framework: Optional[Any] = None

        if init_ui:
            self._init_ui_framework()

        # --- Now that search paths are populated, wire find_file into
        #     the Locale and load global strings ---
        self._setup_locale_find_file()
        self._load_global_strings()

        # --- Network thread ---
        self.jnt: Any = None
        self._init_network_thread()

        # --- AppletManager ---
        from jive.applet_manager import AppletManager

        self._applet_manager = AppletManager(
            system=self._system,
            locale=self._locale,
            jnt=self.jnt,
            allowed_applets=allowed_applets,
        )
        self.applet_manager = self._applet_manager

        # --- Iconbar ---
        from jive.iconbar import Iconbar

        self._iconbar = Iconbar(jnt=self.jnt, use_stubs=not init_ui)

        # --- Set module-level singletons so that applets loaded later
        #     (via configure_applet / reload) can look them up.
        import jive.jive_main as _self_mod

        _self_mod.jive_main = self
        _self_mod.applet_manager_instance = self._applet_manager
        _self_mod.iconbar_instance = self._iconbar
        _self_mod.jnt_instance = self.jnt
        JiveMain.instance = self

        # --- Register input-to-action mappings (must come before home menu
        #     so that action names like "go_home" are registered when
        #     HomeMenu.__init__ calls window.add_action_listener) ---
        self._register_input_mappings()

        # --- Register default action listeners ---
        self._register_action_listeners()

        # --- Create the home menu and register nodes ---
        self._init_home_menu()

        # --- Load applets and skin ---
        if self._init_ui:
            self.reload()

            # Show the home menu window
            if self.window is not None:
                self.window.show()

        # --- Run the event loop ---
        if run_event_loop and self._init_ui:
            self._run_event_loop()

    # ------------------------------------------------------------------
    # Initialization helpers
    # ------------------------------------------------------------------

    def _setup_locale_find_file(self) -> None:
        """Wire the asset search-path resolver into the Locale.

        This must be called after ``_init_ui_framework`` so that the
        search paths populated from ``System.search_paths`` are
        available to ``find_file``.
        """
        try:
            from jive.ui.surface import find_file as _surface_find

            self._locale._find_file = _surface_find
        except ImportError as exc:
            log.debug("_init_find_file: surface find_file not available: %s", exc)

    def _load_global_strings(self) -> None:
        """Load the global strings file."""
        try:
            self._global_strings = self._locale.read_global_strings_file()
            if self._global_strings is not None:
                n = len(self._global_strings._data)
                log.info("Loaded global strings: %d entries", n)
        except Exception as exc:
            log.warn("Could not load global strings: %s", exc)
            self._global_strings = None

    def _init_ui_framework(self) -> None:
        """Initialize the pygame UI framework."""
        # Populate asset search paths from System so that Font.load()
        # and Surface.load_image() can resolve relative paths like
        # "fonts/FreeSans.ttf" or "applets/JogglerSkin/images/...".
        try:
            from jive.ui.font import add_font_search_path
            from jive.ui.surface import add_search_path as add_surface_search_path

            for sp in self._system.search_paths:
                add_font_search_path(sp)
                add_surface_search_path(sp)
        except Exception as exc:
            log.debug("Could not populate asset search paths: %s", exc)

        try:
            from jive.ui.framework import framework

            video_driver = os.environ.get("SDL_VIDEODRIVER", "(system default)")
            log.info("SDL video driver: %s", video_driver)

            framework.init()
            self._framework = framework
        except Exception as exc:
            log.warn("Could not initialize UI framework: %s", exc)
            print(
                f"\nERROR: Could not open display — {exc}\n"
                "\n"
                "Possible fixes:\n"
                "  • If you are using SSH, run from the RPi's local desktop terminal instead.\n"
                "  • Or set DISPLAY=:0  before launching (e.g.  DISPLAY=:0 sordino).\n"
                "  • On Wayland sessions, try:  SDL_VIDEODRIVER=wayland sordino\n"
                "  • For headless/CI use:  sordino --headless\n",
                file=sys.stderr,
            )
            self._init_ui = False

    def _init_network_thread(self) -> None:
        """Initialize the network thread (jnt).

        The network thread provides the notification hub used by
        applets and the Slim protocol layer.
        """
        try:
            from jive.net.network_thread import NetworkThread

            self.jnt = NetworkThread()
        except ImportError:
            # NetworkThread may not be available in test environments.
            # Create a minimal stub.
            self.jnt = _NotificationHub()
            log.debug("Using stub NotificationHub (NetworkThread not available)")

    def _init_home_menu(self) -> None:
        """Create the HomeMenu and register standard menu nodes."""
        title = "HOME"
        if self._global_strings is not None:
            try:
                title = str(self._global_strings.str("HOME"))
            except Exception as exc:
                log.debug("Could not resolve HOME string: %s", exc)

        try:
            from jive.ui.homemenu import HomeMenu

            self.home_menu = HomeMenu(title)
            # The HomeMenu creates its own window
            self.window = getattr(self.home_menu, "window", None)
        except ImportError:
            # HomeMenu not available (headless mode)
            self.home_menu = _HomeMenuStub()
            self.window = None
            log.debug("Using stub HomeMenu (UI not available)")

        # Register the standard menu nodes
        self._register_jive_main_nodes()

    def _register_jive_main_nodes(self, global_strings: Optional[Any] = None) -> None:
        """Register the standard menu tree nodes.

        This can be called after a language change to refresh node labels.
        """
        if global_strings is not None:
            self._global_strings = global_strings
        elif self._global_strings is None:
            self._load_global_strings()

        gs = self._global_strings

        def _str(token: str) -> Any:
            if gs is not None:
                try:
                    return gs.str(token)
                except Exception as exc:
                    log.error("_str: error resolving token %r: %s", token, exc, exc_info=True)
            return token

        hm = self.home_menu
        if hm is None:
            return

        hm.add_node({"id": "hidden", "node": "nowhere"})
        hm.add_node(
            {
                "id": "extras",
                "node": "home",
                "text": _str("EXTRAS"),
                "weight": 50,
                "hiddenWeight": 91,
            }
        )
        hm.add_node(
            {
                "id": "radios",
                "iconStyle": "hm_radio",
                "node": "home",
                "text": _str("INTERNET_RADIO"),
                "weight": 20,
            }
        )
        hm.add_node(
            {
                "id": "_myMusic",
                "iconStyle": "hm_myMusic",
                "node": "hidden",
                "text": _str("MY_MUSIC"),
                "synthetic": True,
                "hiddenWeight": 2,
            }
        )
        hm.add_node(
            {
                "id": "games",
                "node": "extras",
                "text": _str("GAMES"),
                "weight": 70,
            }
        )
        hm.add_node(
            {
                "id": "settings",
                "iconStyle": "hm_settings",
                "node": "home",
                "noCustom": 1,
                "text": _str("SETTINGS"),
                "weight": 1005,
            }
        )
        hm.add_node(
            {
                "id": "advancedSettings",
                "iconStyle": "hm_advancedSettings",
                "node": "settings",
                "text": _str("ADVANCED_SETTINGS"),
                "weight": 105,
                "windowStyle": "text_only",
            }
        )
        hm.add_node(
            {
                "id": "screenSettings",
                "iconStyle": "hm_settingsScreen",
                "node": "settings",
                "text": _str("SCREEN_SETTINGS"),
                "weight": 60,
                "windowStyle": "text_only",
            }
        )
        hm.add_node(
            {
                "id": "screenSettingsNowPlaying",
                "node": "screenSettings",
                "text": _str("NOW_PLAYING"),
                "windowStyle": "text_only",
            }
        )
        hm.add_node(
            {
                "id": "factoryTest",
                "node": "advancedSettings",
                "noCustom": 1,
                "text": _str("FACTORY_TEST"),
                "weight": 120,
                "windowStyle": "text_only",
            }
        )
        hm.add_node(
            {
                "id": "advancedSettingsBetaFeatures",
                "node": "advancedSettings",
                "noCustom": 1,
                "text": _str("BETA_FEATURES"),
                "weight": 100,
                "windowStyle": "text_only",
            }
        )
        hm.add_node(
            {
                "id": "networkSettings",
                "node": "advancedSettings",
                "noCustom": 1,
                "text": _str("NETWORK_NETWORKING"),
                "weight": 100,
                "windowStyle": "text_only",
            }
        )
        hm.add_node(
            {
                "id": "settingsAudio",
                "iconStyle": "hm_settingsAudio",
                "node": "settings",
                "noCustom": 1,
                "text": _str("AUDIO_SETTINGS"),
                "weight": 40,
                "windowStyle": "text_only",
            }
        )
        hm.add_node(
            {
                "id": "settingsBrightness",
                "iconStyle": "hm_settingsBrightness",
                "node": "settings",
                "noCustom": 1,
                "text": _str("BRIGHTNESS_SETTINGS"),
                "weight": 45,
                "windowStyle": "text_only",
            }
        )

    # Lua-compatible camelCase alias
    jiveMainNodes = _register_jive_main_nodes

    # ------------------------------------------------------------------
    # Action listeners
    # ------------------------------------------------------------------

    def _register_action_listeners(self) -> None:
        """Register global action listeners with the Framework."""
        if not self._init_ui or self._framework is None:
            return

        fw = self._framework

        # go_home action
        fw.add_action_listener("go_home", self._go_home_action, priority=10)

        # go_home_or_now_playing — before NowPlaying exists, just go home
        fw.add_action_listener("go_home_or_now_playing", self._go_home_action, priority=10)

        # add — default context menu action
        fw.add_action_listener("add", self._default_context_menu_action, priority=10)

        # factory test mode
        fw.add_action_listener(
            "go_factory_test_mode", self._go_factory_test_mode_action, priority=9999
        )

        # Consume up/down at lowest priority
        fw.add_action_listener("up", lambda *_a, **_kw: EVENT_CONSUME, priority=9999)
        fw.add_action_listener("down", lambda *_a, **_kw: EVENT_CONSUME, priority=9999)

        # Power actions
        fw.add_action_listener("power", self._power_action, priority=10)
        fw.add_action_listener("power_off", self._power_off_action, priority=10)
        fw.add_action_listener("power_on", self._power_on_action, priority=10)

        # Nothing action — just consume
        fw.add_action_listener("nothing", lambda *_a, **_kw: EVENT_CONSUME, priority=10)

    def _register_input_mappings(self) -> None:
        """Register input-to-action mappings with the Framework."""
        if not self._init_ui or self._framework is None:
            return

        try:
            from jive.input_to_action_map import (
                action_action_mappings,
                char_action_mappings,
                gesture_action_mappings,
                ir_action_mappings,
                key_action_mappings,
                unassigned_action_mappings,
            )

            mappings = {
                "char_action_mappings": char_action_mappings,
                "key_action_mappings": key_action_mappings,
                "ir_action_mappings": ir_action_mappings,
                "gesture_action_mappings": gesture_action_mappings,
                "action_action_mappings": action_action_mappings,
                "unassigned_action_mappings": unassigned_action_mappings,
            }

            self._framework.register_actions(mappings)
        except Exception as exc:
            log.warn("Could not register input-to-action mappings: %s", exc)

    # ------------------------------------------------------------------
    # Home navigation
    # ------------------------------------------------------------------

    def go_home(self) -> None:
        """Navigate to the home screen."""
        if self._framework is None:
            return

        window_stack = getattr(self._framework, "window_stack", [])
        if len(window_stack) > 1:
            self._framework.play_sound("JUMP")
            if self.home_menu is not None:
                self.home_menu.close_to_home(True)
        elif len(window_stack) == 1:
            self._framework.play_sound("BUMP")
            window_stack[0].bump_left()

    # Lua-compatible camelCase alias
    goHome = go_home

    def _go_home_action(self, *_args: Any, **_kwargs: Any) -> int:
        """Action handler for go_home."""
        self.go_home()
        return EVENT_CONSUME

    def _default_context_menu_action(self, *_args: Any, **_kwargs: Any) -> int:
        """Default context menu action — just bump."""
        if self._framework is not None:
            if not self._framework.is_most_recent_input("mouse"):
                self._framework.play_sound("BUMP")
                window_stack = getattr(self._framework, "window_stack", [])
                if window_stack:
                    window_stack[0].bump_left()
        return EVENT_CONSUME

    def _go_factory_test_mode_action(self, *_args: Any, **_kwargs: Any) -> int:
        """Action handler for go_factory_test_mode."""
        if self.home_menu is not None:
            menu_table = self.home_menu.get_menu_table()
            key = "factoryTest"
            if key in menu_table and "callback" in menu_table[key]:
                if self._framework is not None:
                    self._framework.play_sound("JUMP")
                menu_table[key]["callback"]()
        return EVENT_CONSUME

    # ------------------------------------------------------------------
    # Player disconnect
    # ------------------------------------------------------------------

    def disconnect_player(self, event: Any = None) -> None:
        """Disconnect the current player and navigate home."""
        if applet_manager_instance is not None:
            applet_manager_instance.call_service("setCurrentPlayer", None)
        self.go_home()

    # Lua-compatible camelCase alias
    disconnectPlayer = disconnect_player

    # ------------------------------------------------------------------
    # Soft power
    # ------------------------------------------------------------------

    def get_soft_power_state(self) -> str:
        """Return the current soft power state: ``"on"`` or ``"off"``."""
        return self._soft_power_state

    # Lua-compatible camelCase alias
    getSoftPowerState = get_soft_power_state

    def set_soft_power_state(self, soft_power_state: str, is_server_request: bool = False) -> None:
        """Set the soft power state.

        Parameters
        ----------
        soft_power_state:
            ``"on"`` or ``"off"``.
        is_server_request:
            If ``True``, the power change was initiated by the server.
        """
        if self._soft_power_state == soft_power_state:
            return

        self._soft_power_state = soft_power_state

        mgr = applet_manager_instance

        if soft_power_state == "off":
            log.info("Turn soft power off")
            current_player = mgr.call_service("getCurrentPlayer") if mgr else None
            if current_player is not None:
                is_connected = getattr(current_player, "is_connected", lambda: False)()
                is_local = getattr(current_player, "is_local", lambda: False)()
                if is_connected or is_local:
                    current_player.set_power(False, None, is_server_request)

            if mgr:
                mgr.call_service("activateScreensaver", is_server_request)

        elif soft_power_state == "on":
            log.info("Turn soft power on")
            current_player = mgr.call_service("getCurrentPlayer") if mgr else None
            if current_player is not None:
                is_connected = getattr(current_player, "is_connected", lambda: False)()
                is_local = getattr(current_player, "is_local", lambda: False)()
                if is_connected or is_local:
                    slim_server = getattr(current_player, "slim_server", None)
                    if slim_server is not None:
                        slim_server.wake_on_lan()
                    current_player.set_power(True, None, is_server_request)

            if mgr:
                mgr.call_service("deactivateScreensaver")
                mgr.call_service("restartScreenSaverTimer")
        else:
            log.error("Unknown desired soft power state: %s", soft_power_state)

    # Lua-compatible camelCase alias
    setSoftPowerState = set_soft_power_state

    def toggle_power(self) -> None:
        """Toggle the soft power state between on and off."""
        if self._soft_power_state == "off":
            self.set_soft_power_state("on")
        elif self._soft_power_state == "on":
            self.set_soft_power_state("off")
        else:
            log.error("Unknown current soft power state: %s", self._soft_power_state)

    # Lua-compatible camelCase alias
    togglePower = toggle_power

    def _power_action(self, *_args: Any, **_kwargs: Any) -> int:
        if self._framework is not None:
            self._framework.play_sound("SELECT")
        self.toggle_power()
        return EVENT_CONSUME

    def _power_off_action(self, *_args: Any, **_kwargs: Any) -> int:
        self.set_soft_power_state("off")
        return EVENT_CONSUME

    def _power_on_action(self, *_args: Any, **_kwargs: Any) -> int:
        self.set_soft_power_state("on")
        return EVENT_CONSUME

    # ------------------------------------------------------------------
    # Skin management
    # ------------------------------------------------------------------

    def register_skin(
        self,
        name: str,
        applet_name: str,
        method: str,
        skin_id: Optional[str] = None,
    ) -> None:
        """Register a skin.

        Parameters
        ----------
        name:
            Human-readable skin display name.
        applet_name:
            The applet that provides this skin.
        method:
            The method name on the applet to call to load the skin.
        skin_id:
            Unique identifier for the skin.  Defaults to *applet_name*.
        """
        if skin_id is None:
            skin_id = applet_name
        log.debug("registerSkin(%s, %s, %s)", name, applet_name, skin_id)
        self.skins[skin_id] = (applet_name, name, method)

    # Lua-compatible camelCase alias
    registerSkin = register_skin

    def skin_iterator(self) -> Iterator[Tuple[str, str]]:
        """Iterate over registered skins.

        Yields ``(skin_id, display_name)`` tuples.
        """
        for skin_id, (applet_name, name, method) in self.skins.items():
            yield skin_id, name

    # Lua-compatible camelCase alias
    skinIterator = skin_iterator

    def get_selected_skin(self) -> Optional[str]:
        """Return the currently selected skin ID."""
        return self.selected_skin

    # Lua-compatible camelCase alias
    getSelectedSkin = get_selected_skin

    def set_selected_skin(self, skin_id: str) -> None:
        """Select and load a skin by ID."""
        log.info("select skin: %s", skin_id)
        old_skin_id = self.selected_skin
        if self._load_skin(skin_id, reload_skin=False, use_default_size=True):
            self.selected_skin = skin_id
            if self.jnt is not None:
                self.jnt.notify("skinSelected")
            # Free the old skin if it's a different applet
            if (
                old_skin_id is not None
                and old_skin_id in self.skins
                and skin_id in self.skins
                and self.skins[old_skin_id][0] != self.skins[skin_id][0]
            ):
                self.free_skin(old_skin_id)

    # Lua-compatible camelCase alias
    setSelectedSkin = set_selected_skin

    def _load_skin(
        self,
        skin_id: str,
        reload_skin: bool = True,
        use_default_size: bool = False,
    ) -> bool:
        """Load a skin by its ID.

        Returns ``True`` on success.
        """
        if skin_id not in self.skins:
            return False

        applet_name, name, method = self.skins[skin_id]

        if applet_manager_instance is None:
            return False

        obj = applet_manager_instance.load_applet(applet_name)
        if obj is None:
            log.error("Cannot load skin %s", applet_name)
            return False

        # Reset the StyleDB singleton and pass its backing dict directly
        # to the skin method — exactly like the Lua original:
        #
        #   jive.ui.style = {}
        #   obj[method](obj, jive.ui.style, reload, useDefaultSize)
        #
        # The skin method populates the dict *in place*.  Because we
        # hand over the same dict object that StyleDB uses internally,
        # style lookups made during skin loading (e.g. from
        # set_video_mode → checkLayout paths) will find the entries
        # that have been written so far, rather than hitting an empty
        # dict.
        try:
            from jive.ui.style import skin as _skin_db

            _skin_db.data = {}  # clears old data + invalidates cache
        except ImportError as exc:
            log.debug("_load_skin: style module not available: %s", exc)

        # Call the skin method — it populates _skin_db.data in place
        skin_method = getattr(obj, method, None)
        if skin_method is None:
            log.error("Skin applet %s has no method %s", applet_name, method)
            return False

        try:
            # Pass the live StyleDB dict so entries are visible
            # immediately as the skin method adds them.
            result = skin_method(
                _skin_db.data,
                reload_skin,
                use_default_size,
            )
            # Some skin methods return a *new* dict instead of (or in
            # addition to) populating the one passed in.  If so, install
            # the returned dict as the new style data.
            if result is not None and isinstance(result, dict) and result is not _skin_db.data:
                _skin_db.data = result
        except Exception as exc:
            log.error("Error loading skin %s: %s", applet_name, exc)
            return False

        # Invalidate the lookup cache — the skin method may have
        # overwritten entries that were cached during loading.
        _skin_db.invalidate()

        self._skin = obj

        if self._framework is not None:
            self._framework.style_changed()

        # Refresh the wallpaper background for the new skin/resolution.
        # The old background was rendered for the previous screen size
        # and must be reloaded so it matches the new dimensions.
        if applet_manager_instance is not None:
            try:
                applet_manager_instance.call_service("setBackground", None)
            except Exception as exc:
                log.debug("_load_skin: setBackground refresh failed: %s", exc)

        return True

    def reload_skin(self, reload_flag: bool = True) -> None:
        """Reload the currently selected skin."""
        if self.selected_skin is not None:
            self._load_skin(self.selected_skin, reload_skin=reload_flag)

    # Lua-compatible camelCase alias
    reloadSkin = reload_skin

    def free_skin(self, skin_id: Optional[str] = None) -> None:
        """Free a skin applet.

        Parameters
        ----------
        skin_id:
            The skin to free.  Defaults to the selected skin.
        """
        if skin_id is None:
            skin_id = self.selected_skin
        if skin_id is None:
            return
        log.info("freeSkin: %s", skin_id)

        if skin_id not in self.skins:
            return
        if applet_manager_instance is not None:
            applet_manager_instance.free_applet(self.skins[skin_id][0])

    # Lua-compatible camelCase alias
    freeSkin = free_skin

    def is_fullscreen(self) -> bool:
        """Return whether the UI is in fullscreen mode."""
        return self._fullscreen

    # Lua-compatible camelCase alias
    isFullscreen = is_fullscreen

    def set_fullscreen(self, fullscreen: bool) -> None:
        """Set fullscreen mode."""
        self._fullscreen = fullscreen

    # Lua-compatible camelCase alias
    setFullscreen = set_fullscreen

    def set_default_skin(self, skin_id: str) -> None:
        """Set the default skin ID."""
        log.debug("setDefaultSkin(%s)", skin_id)
        self._default_skin = skin_id

    # Lua-compatible camelCase alias
    setDefaultSkin = set_default_skin

    def get_default_skin(self) -> str:
        """Return the default skin ID."""
        return self._default_skin or "QVGAportraitSkin"

    # Lua-compatible camelCase alias
    getDefaultSkin = get_default_skin

    def get_skin_param_or_nil(self, key: str) -> Any:
        """Return a skin parameter value, or ``None`` if not found."""
        if self._skin is not None:
            param_method = getattr(self._skin, "param", None)
            if param_method is not None:
                params = param_method()
                if key in params:
                    return params[key]
        return None

    # Lua-compatible camelCase alias
    getSkinParamOrNil = get_skin_param_or_nil

    def get_skin_param(self, key: str) -> Any:
        """Return a skin parameter value.

        Logs an error if the key is not found.
        """
        result = self.get_skin_param_or_nil(key)
        if result is None:
            log.error("No value for skinParam %s found", key)
        return result

    # Lua-compatible camelCase alias
    getSkinParam = get_skin_param

    # ------------------------------------------------------------------
    # Reload (applets + skin)
    # ------------------------------------------------------------------

    def reload(self) -> None:
        """Reload skins and discover applets.

        Resets the style, runs applet discovery, and ensures a skin
        is selected.
        """
        log.debug("reload()")

        # Reset the StyleDB singleton (clear cache, keep the object)
        try:
            from jive.ui.style import skin as _skin_db

            _skin_db.data = {}
        except ImportError as exc:
            log.debug("reload: style module not available: %s", exc)

        # Discover and register applets
        if applet_manager_instance is not None:
            applet_manager_instance.discover()

        # Make sure a skin is selected
        if not self.selected_skin:
            for skin_id in self.skins:
                self.set_selected_skin(skin_id)
                break
            if not self.selected_skin and self.skins:
                log.error("No skin could be selected")

    # ------------------------------------------------------------------
    # Help menu item
    # ------------------------------------------------------------------

    def add_help_menu_item(
        self,
        menu: Any,
        obj: Any,
        callback: Callable[..., Any],
        text_token: Optional[str] = None,
        icon_style: Optional[str] = None,
    ) -> None:
        """Add a 'Help' menu item to *menu* if input is not touch/mouse.

        Parameters
        ----------
        menu:
            The menu widget to add the item to.
        obj:
            The object to pass to the callback.
        callback:
            The function to call when the item is selected.
        text_token:
            The string token for the label.  Defaults to ``"GLOBAL_HELP"``.
        icon_style:
            Optional icon style.  If not specified, uses ``"_BOGUS_"``.
        """
        if not icon_style:
            icon_style = "_BOGUS_"

        if self._framework is not None and self._framework.is_most_recent_input("mouse"):
            return  # Touch/mouse — use help button instead

        label = text_token or "GLOBAL_HELP"
        text = label
        if self._global_strings is not None:
            try:
                text = str(self._global_strings.str(label))
            except Exception as exc:
                log.debug("Could not resolve string %r: %s", label, exc)

        menu.add_item(
            {
                "iconStyle": icon_style,
                "text": text,
                "sound": "WINDOWSHOW",
                "callback": lambda: callback(obj),
                "weight": 100,
            }
        )

    # Lua-compatible camelCase alias
    addHelpMenuItem = add_help_menu_item

    # ------------------------------------------------------------------
    # Post-on-screen init
    # ------------------------------------------------------------------

    def register_post_on_screen_init(self, callback: Callable[[], None]) -> None:
        """Register a callback to run once the screen is visible."""
        self._post_on_screen_inits.append(callback)

    # Lua-compatible camelCase alias
    registerPostOnScreenInit = register_post_on_screen_init

    def perform_post_on_screen_init(self) -> None:
        """Run all registered post-on-screen-init callbacks."""
        if not self._post_on_screen_inits:
            return
        for callback in self._post_on_screen_inits:
            log.info("Calling postOnScreenInits callback")
            try:
                callback()
            except Exception as exc:
                log.error("Error in postOnScreenInit callback: %s", exc)
        self._post_on_screen_inits.clear()

    # Lua-compatible camelCase alias
    performPostOnScreenInit = perform_post_on_screen_init

    # ------------------------------------------------------------------
    # HomeMenu delegation
    # ------------------------------------------------------------------

    def add_node(self, item: Dict[str, Any]) -> None:
        """Add a menu node (delegates to HomeMenu)."""
        if self.home_menu is not None:
            self.home_menu.add_node(item)

    def add_item(self, item: Dict[str, Any]) -> None:
        """Add a menu item (delegates to HomeMenu)."""
        if self.home_menu is not None:
            self.home_menu.add_item(item)

    def remove_item(self, item: Dict[str, Any]) -> None:
        """Remove a menu item (delegates to HomeMenu)."""
        if self.home_menu is not None:
            self.home_menu.remove_item(item)

    def remove_item_by_id(self, item_id: str) -> None:
        """Remove a menu item by its ID (delegates to HomeMenu)."""
        if self.home_menu is not None:
            if hasattr(self.home_menu, "remove_item_by_id"):
                self.home_menu.remove_item_by_id(item_id)
            else:
                # Fallback: look up by id and remove
                table = self.home_menu.get_menu_table()
                if item_id in table:
                    self.home_menu.remove_item(table[item_id])

    def get_menu_table(self) -> Dict[str, Any]:
        """Return the menu table (delegates to HomeMenu)."""
        if self.home_menu is not None:
            return self.home_menu.get_menu_table()  # type: ignore[no-any-return]
        return {}

    def get_node_table(self) -> Dict[str, Any]:
        """Return the node table (delegates to HomeMenu)."""
        if self.home_menu is not None:
            return self.home_menu.get_node_table()  # type: ignore[no-any-return]
        return {}

    def close_to_home(
        self, hide_always_on_top: bool = True, transition: Optional[Any] = None
    ) -> None:
        """Close all windows back to the home screen."""
        if self.home_menu is not None:
            self.home_menu.close_to_home(hide_always_on_top, transition)

    def set_title(self, title: Optional[str]) -> None:
        """Set the home-screen title (e.g. the current player name)."""
        self._title = title
        if self.home_menu is not None and hasattr(self.home_menu, "set_title"):
            self.home_menu.set_title(title)

    def open_node_by_id(self, node_id: str, transition: bool = False) -> None:
        """Open a menu node by its ID.

        In the full UI this navigates to the node's submenu.  In
        headless mode this is recorded but has no visual effect.
        """
        if self.home_menu is not None and hasattr(self.home_menu, "open_node_by_id"):
            self.home_menu.open_node_by_id(node_id, transition)

    def exists(self, item_id: str) -> bool:
        """Return ``True`` if a menu item or node with *item_id* exists."""
        if self.home_menu is not None:
            table = self.home_menu.get_menu_table()
            if item_id in table:
                return True
            if hasattr(self.home_menu, "get_node_table"):
                nodes = self.home_menu.get_node_table()
                if item_id in nodes:
                    return True
        return False

    def lock_item(
        self,
        item: Dict[str, Any],
        cancel_callback: Optional[Callable[[], None]] = None,
    ) -> None:
        """Lock a menu item (prevent re-selection while loading).

        In the full UI this shows a spinner on the item.  In headless
        mode we just record the lock state.
        """
        if self.home_menu is not None and hasattr(self.home_menu, "lock_item"):
            self.home_menu.lock_item(item, cancel_callback)

    def unlock_item(self, item: Dict[str, Any]) -> None:
        """Unlock a previously locked menu item."""
        if self.home_menu is not None and hasattr(self.home_menu, "unlock_item"):
            self.home_menu.unlock_item(item)

    # Lua-compatible camelCase aliases
    addNode = add_node
    addItem = add_item
    removeItem = remove_item
    removeItemById = remove_item_by_id
    getMenuTable = get_menu_table
    getNodeTable = get_node_table
    closeToHome = close_to_home
    setTitle = set_title
    openNodeById = open_node_by_id
    lockItem = lock_item
    unlockItem = unlock_item

    # ------------------------------------------------------------------
    # Event loop
    # ------------------------------------------------------------------

    def _run_event_loop(self) -> None:
        """Run the main framework event loop (blocking)."""
        if self._framework is None:
            log.error("Cannot run event loop: Framework not initialized")
            print(
                "\nERROR: No display available — exiting. "
                "Run 'sordino --headless' for headless mode.\n",
                file=sys.stderr,
            )
            sys.exit(1)

        # Set up the splash timer / handler
        self._framework.set_update_screen(False)

        def _splash_handler(*_args: Any, **_kwargs: Any) -> int:
            self.perform_post_on_screen_init()
            self._framework.set_update_screen(True)  # type: ignore[union-attr]
            return EVENT_UNUSED

        splash_listener = self._framework.add_listener(
            ACTION | EVENT_CHAR_PRESS | EVENT_KEY_ALL | EVENT_SCROLL,
            _splash_handler,
        )

        # Start a 2-second splash timer
        try:
            from jive.ui.timer import Timer

            def _splash_timer_cb() -> None:
                self.perform_post_on_screen_init()
                self._framework.set_update_screen(True)  # type: ignore[union-attr]
                if splash_listener:
                    self._framework.remove_listener(splash_listener)  # type: ignore[union-attr]

            splash_timer = Timer(
                2000,
                _splash_timer_cb,
                once=True,
            )
            splash_timer.start()
        except ImportError:
            # Timer not available — just enable screen immediately
            self._framework.set_update_screen(True)

        # Run the event loop
        from jive.ui.task import Task

        if self.jnt is not None and hasattr(self.jnt, "task"):
            net_task = self.jnt.task()
            net_task.add_task()

        def _pump_tasks() -> None:
            for t in Task.iterator():
                t.resume()

        self._framework.event_loop(_pump_tasks)
        self._framework.quit()

    # ------------------------------------------------------------------
    # Repr
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        n_skins = len(self.skins)
        n_applets = 0
        if applet_manager_instance is not None:
            n_applets = len(applet_manager_instance.get_applet_db())
        return (
            f"JiveMain(version={self.JIVE_VERSION!r}, "
            f"skins={n_skins}, applets={n_applets}, "
            f"power={self._soft_power_state!r}, "
            f"skin={self.selected_skin!r})"
        )

    def __str__(self) -> str:
        return repr(self)


# ---------------------------------------------------------------------------
# Stubs for headless / test operation
# ---------------------------------------------------------------------------


class _NotificationHub:
    """Minimal notification hub stub for when NetworkThread is unavailable.

    Mirrors the real :class:`~jive.net.network_thread.NetworkThread` API:

    * **subscribe / unsubscribe** — register objects that implement
      ``notify_<event>(...)`` methods (the Lua ``jnt:subscribe`` pattern).
    * **notify** — dispatch ``notify_<event>`` calls to all subscribers
      *and* fire any legacy ``add_listener`` callbacks.
    * **add_listener / remove_listener** — register simple callable
      listeners keyed by event name (used by some UI components).
    """

    def __init__(self) -> None:
        self._listeners: Dict[str, List[Callable[..., Any]]] = {}
        # Subscriber registry: id(obj) -> obj  (mirrors NetworkThread)
        self._subscribers: Dict[int, Any] = {}

    # ------------------------------------------------------------------
    # Subscriber API  (matches NetworkThread.subscribe / unsubscribe)
    # ------------------------------------------------------------------

    def subscribe(self, obj: Any) -> None:
        """Subscribe *obj* to receive ``notify_<event>`` calls.

        The object should implement methods named ``notify_<event>``
        (e.g. ``notify_playerNew``, ``notify_serverConnected``).
        """
        self._subscribers[id(obj)] = obj

    def unsubscribe(self, obj: Any) -> None:
        """Unsubscribe *obj* from notifications."""
        self._subscribers.pop(id(obj), None)

    # ------------------------------------------------------------------
    # Notification dispatch
    # ------------------------------------------------------------------

    def notify(self, event_name: str, *args: Any, **kwargs: Any) -> None:
        """Dispatch a notification to subscribers and listeners.

        1. For each subscriber that has a ``notify_<event_name>`` method,
           call it with ``*args``.
        2. For each legacy listener registered via ``add_listener``,
           call it with ``*args, **kwargs``.
        """
        # --- Subscriber dispatch (NetworkThread pattern) ---
        method_name = f"notify_{event_name}"
        for obj_id, obj in list(self._subscribers.items()):
            method = getattr(obj, method_name, None)
            if method is not None and callable(method):
                try:
                    method(*args)
                except Exception as exc:
                    log.error(
                        "Error in subscriber %s.%s: %s",
                        type(obj).__name__,
                        method_name,
                        exc,
                    )

        # --- Legacy listener dispatch ---
        for listener in self._listeners.get(event_name, []):
            try:
                listener(*args, **kwargs)
            except Exception as exc:
                log.error("Error in notification listener %s: %s", event_name, exc)

    # ------------------------------------------------------------------
    # Legacy listener API
    # ------------------------------------------------------------------

    def add_listener(self, event_name: str, callback: Callable[..., Any]) -> None:
        """Register a listener for a notification event."""
        self._listeners.setdefault(event_name, []).append(callback)

    def remove_listener(self, event_name: str, callback: Callable[..., Any]) -> None:
        """Remove a listener for a notification event."""
        listeners = self._listeners.get(event_name, [])
        if callback in listeners:
            listeners.remove(callback)

    # ------------------------------------------------------------------
    # Misc
    # ------------------------------------------------------------------

    def task(self) -> None:
        """Return None — no background task for the stub."""
        return None

    def __repr__(self) -> str:
        n_listeners = sum(len(v) for v in self._listeners.values())
        n_subscribers = len(self._subscribers)
        return f"_NotificationHub(subscribers={n_subscribers}, listeners={n_listeners})"


class _HomeMenuStub:
    """Minimal HomeMenu stub for headless / test operation.

    Stores menu nodes and items in dicts for testing without the
    real UI framework.
    """

    def __init__(self) -> None:
        self._nodes: Dict[str, Dict[str, Any]] = {}
        self._items: Dict[str, Dict[str, Any]] = {}

    def add_node(self, item: Dict[str, Any]) -> None:
        item_id = item.get("id", "")
        if item_id:
            self._nodes[item_id] = item

    def add_item(self, item: Dict[str, Any]) -> None:
        item_id = item.get("id", "")
        if item_id:
            self._items[item_id] = item

    def remove_item(self, item: Dict[str, Any]) -> None:
        item_id = item.get("id", "")
        self._items.pop(item_id, None)

    def remove_item_by_id(self, item_id: str) -> None:
        self._items.pop(item_id, None)

    def get_menu_table(self) -> Dict[str, Any]:
        return dict(self._items)

    def get_node_table(self) -> Dict[str, Any]:
        return dict(self._nodes)

    def close_to_home(
        self, hide_always_on_top: bool = True, transition: Optional[Any] = None
    ) -> None:
        pass

    # Lua-compatible camelCase aliases
    addNode = add_node
    addItem = add_item
    removeItem = remove_item
    removeItemById = remove_item_by_id
    getMenuTable = get_menu_table
    getNodeTable = get_node_table
    closeToHome = close_to_home

    def __repr__(self) -> str:
        return f"_HomeMenuStub(nodes={len(self._nodes)}, items={len(self._items)})"
