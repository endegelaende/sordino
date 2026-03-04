"""
jive.applets.SelectSkin.SelectSkinApplet — Skin selection applet.

Ported from ``share/jive/applets/SelectSkin/SelectSkinApplet.lua``
(~306 LOC Lua) in the original jivelite project.

This applet allows the user to select a different skin for the UI.
On hardware devices with touch support, separate skins can be
configured for touch and remote control modes.

Features:

* **Skin selection menu** — lists all registered skins as radio buttons
* **Confirmation dialog** — after selecting a new skin, a 10-second
  timer auto-reverts if the user doesn't confirm the change
* **Touch/remote split** — on touch hardware, separate skin choices
  for touch mode and remote mode
* **Startup hook** — ``selectSkinStartup()`` for setup wizards
* **Service method** — ``getSelectedSkinNameForType()`` returns the
  currently selected skin for a given type

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from jive.applet import Applet
from jive.ui.constants import (
    EVENT_CONSUME,
    EVENT_UNUSED,
    EVENT_WINDOW_POP,
)
from jive.utils.log import logger

__all__ = ["SelectSkinApplet"]

log = logger("applet.SelectSkin")


# ---------------------------------------------------------------------------
# Lazy import helpers (avoid circular imports at module level)
# ---------------------------------------------------------------------------


def _get_applet_manager() -> Any:
    try:
        from jive.applet_manager import applet_manager

        return applet_manager
    except (ImportError, AttributeError):
        return None


def _get_jive_main() -> Any:
    try:
        from jive.jive_main import jive_main

        return jive_main
    except (ImportError, AttributeError) as exc:
        log.debug("_get_jive_main: first import failed: %s", exc)
    try:
        import jive.jive_main as _mod

        return getattr(_mod, "jive_main", None)
    except ImportError:
        return None


def _import_ui_class(module_name: str, class_name: str) -> Any:
    """Dynamically import a UI class to keep top-level imports light."""
    import importlib

    mod = importlib.import_module(f"jive.ui.{module_name}")
    return getattr(mod, class_name)


# Cached UI class accessors (populated on first use) -----------------------

_ui_cache: Dict[str, Any] = {}


def _Window() -> Any:
    if "Window" not in _ui_cache:
        _ui_cache["Window"] = _import_ui_class("window", "Window")
    return _ui_cache["Window"]


def _SimpleMenu() -> Any:
    if "SimpleMenu" not in _ui_cache:
        _ui_cache["SimpleMenu"] = _import_ui_class("simplemenu", "SimpleMenu")
    return _ui_cache["SimpleMenu"]


def _RadioGroup() -> Any:
    if "RadioGroup" not in _ui_cache:
        _ui_cache["RadioGroup"] = _import_ui_class("radio", "RadioGroup")
    return _ui_cache["RadioGroup"]


def _RadioButton() -> Any:
    if "RadioButton" not in _ui_cache:
        _ui_cache["RadioButton"] = _import_ui_class("radio", "RadioButton")
    return _ui_cache["RadioButton"]


def _Timer() -> Any:
    if "Timer" not in _ui_cache:
        _ui_cache["Timer"] = _import_ui_class("timer", "Timer")
    return _ui_cache["Timer"]


def _System() -> Any:
    """Return the System *instance* (not the class).

    In the Lua original, ``System`` is a module-level singleton.
    In Python, the single ``System`` instance is owned by
    ``AppletManager`` (which receives it from ``JiveMain``).
    """
    if "System" not in _ui_cache:
        try:
            from jive.applet_manager import applet_manager as _mgr

            if _mgr is not None and hasattr(_mgr, "system") and _mgr.system is not None:
                _ui_cache["System"] = _mgr.system
            else:
                # Fallback: try JiveMain directly
                from jive.jive_main import jive_main as _jm

                if _jm is not None and hasattr(_jm, "_system"):
                    _ui_cache["System"] = _jm._system
                else:
                    _ui_cache["System"] = None
        except (ImportError, AttributeError):
            _ui_cache["System"] = None
    return _ui_cache["System"]


# ---------------------------------------------------------------------------
# Default skin names per type
# ---------------------------------------------------------------------------

_DEFAULT_SKIN_NAME_FOR_TYPE: Dict[str, str] = {
    "touch": "WQVGAsmallSkin",
    "remote": "WQVGAlargeSkin",
}


# ---------------------------------------------------------------------------
# SelectSkinApplet
# ---------------------------------------------------------------------------


class SelectSkinApplet(Applet):
    """Skin selection applet.

    Provides a UI for choosing the active skin, with a confirmation
    dialog that auto-reverts after 10 seconds if the user does not
    confirm the change.  On touch hardware, separate skins can be
    selected for touch and remote modes.
    """

    def __init__(self) -> None:
        super().__init__()

        # Flag indicating whether the user changed a skin setting
        self.changed: bool = False

    # ==================================================================
    # Lifecycle
    # ==================================================================

    def init(self) -> None:
        """Initialize the applet (called by AppletManager)."""
        super().init()

    def free(self) -> bool:
        """Allow freeing — SelectSkin has no persistent state."""
        return True

    # ==================================================================
    # Service methods
    # ==================================================================

    def getSelectedSkinNameForType(self, skin_type: str) -> str:
        """Return the selected skin name for *skin_type*.

        Falls back to a built-in default if the setting has not been
        saved.

        Parameters
        ----------
        skin_type:
            One of ``"touch"``, ``"remote"``, or ``"skin"``.

        Returns
        -------
        str
            The skin ID string.
        """
        settings = self.get_settings()
        if settings and skin_type in settings:
            return settings[skin_type]  # type: ignore[no-any-return]
        return _DEFAULT_SKIN_NAME_FOR_TYPE.get(skin_type, "QVGAbaseSkin")

    # snake_case alias
    get_selected_skin_name_for_type = getSelectedSkinNameForType

    # ==================================================================
    # Entry point
    # ==================================================================

    def select_skin_entry_point(self, menu_item: Any = None) -> Any:
        """Open the skin selection UI.

        On hardware with touch support, shows a sub-menu for choosing
        between touch and remote skins.  Otherwise, goes directly to
        the skin selection screen.

        Parameters
        ----------
        menu_item:
            The menu item dict that triggered this action.

        Returns
        -------
        Window
            The created window.
        """
        sys_instance = _System()
        has_touch = False
        is_hardware = False
        if sys_instance is not None:
            has_touch = (
                sys_instance.has_touch()
                if hasattr(sys_instance, "has_touch")
                else False
            )
            is_hardware = (
                sys_instance.is_hardware()
                if hasattr(sys_instance, "is_hardware")
                else False
            )

        if has_touch and is_hardware:
            return self._select_skin_touch_entry(menu_item)
        else:
            title = ""
            if menu_item and isinstance(menu_item, dict):
                title = menu_item.get("text", "")
            elif menu_item and hasattr(menu_item, "text"):
                title = menu_item.text

            jive_main = _get_jive_main()
            current_skin = ""
            if jive_main is not None:
                if hasattr(jive_main, "get_selected_skin"):
                    current_skin = jive_main.get_selected_skin() or ""
                elif hasattr(jive_main, "getSelectedSkin"):
                    current_skin = jive_main.getSelectedSkin() or ""

            return self.select_skin(title, "skin", current_skin)

    # Lua alias
    selectSkinEntryPoint = select_skin_entry_point

    def selectSkinStartup(self, setup_next: Optional[Callable[..., Any]] = None) -> Any:
        """Open the skin selection screen during initial setup.

        Parameters
        ----------
        setup_next:
            Optional callback to advance to the next setup step.

        Returns
        -------
        Window
            The created window.
        """
        jive_main = _get_jive_main()
        current_skin = ""
        if jive_main is not None:
            if hasattr(jive_main, "get_selected_skin"):
                current_skin = jive_main.get_selected_skin() or ""
            elif hasattr(jive_main, "getSelectedSkin"):
                current_skin = jive_main.getSelectedSkin() or ""

        return self.select_skin(
            self.string("SELECT_SKIN"), "skin", current_skin, setup_next
        )

    # snake_case alias
    select_skin_startup = selectSkinStartup

    # ==================================================================
    # Touch entry point (sub-menu for touch/remote)
    # ==================================================================

    def _select_skin_touch_entry(self, menu_item: Any = None) -> Any:
        """Show the touch/remote skin type sub-menu."""
        Window = _Window()
        SimpleMenu = _SimpleMenu()

        title = ""
        if menu_item and isinstance(menu_item, dict):
            title = menu_item.get("text", "")
        elif menu_item and hasattr(menu_item, "text"):
            title = menu_item.text

        window = Window("text_list", title, "settingstitle")

        items = [
            {
                "text": self.string("SELECT_SKIN_TOUCH_SKIN"),
                "sound": "WINDOWSHOW",
                "callback": lambda event, mi: self.select_skin(
                    self.string("SELECT_SKIN_TOUCH_SKIN"),
                    "touch",
                    self.getSelectedSkinNameForType("touch"),
                ),
            },
            {
                "text": self.string("SELECT_SKIN_REMOTE_SKIN"),
                "sound": "WINDOWSHOW",
                "callback": lambda event, mi: self.select_skin(
                    self.string("SELECT_SKIN_REMOTE_SKIN"),
                    "remote",
                    self.getSelectedSkinNameForType("remote"),
                ),
            },
        ]

        menu = SimpleMenu("menu", items)
        window.add_widget(menu)

        self.tie_and_show_window(window)
        return window

    # ==================================================================
    # Skin selection screen
    # ==================================================================

    def select_skin(
        self,
        title: Any = "",
        skin_type: str = "skin",
        previously_selected_skin: str = "",
        setup_next: Optional[Callable[..., Any]] = None,
    ) -> Any:
        """Show the skin selection screen.

        Mirrors the Lua original where the RadioButton closure, the
        confirmation dialog, and the ``_on_pop`` handler all live in
        the **same** scope and share a single mutable ``setup_next``
        reference.  This is critical: the confirm dialog's "Keep"
        button consumes ``setup_next`` so that ``_on_pop`` does not
        call it a second time.

        Parameters
        ----------
        title:
            Window title text.
        skin_type:
            One of ``"skin"``, ``"touch"``, or ``"remote"``.
        previously_selected_skin:
            The skin ID that was active before opening this screen.
        setup_next:
            Optional callback for setup wizard flow.

        Returns
        -------
        Window
            The created window.
        """
        Window = _Window()
        SimpleMenu = _SimpleMenu()
        RadioGroup = _RadioGroup()
        RadioButton = _RadioButton()
        Timer = _Timer()

        jive_main = _get_jive_main()
        if jive_main is None:
            log.warn("select_skin: jiveMain not available")
            return None

        window = Window("text_list", str(title), "settingstitle")

        menu = SimpleMenu("menu")
        if hasattr(menu, "set_comparator"):
            comparator = getattr(menu, "item_comparator_alpha", None)
            if comparator is not None:
                menu.set_comparator(comparator)
        elif hasattr(menu, "setComparator"):
            comparator = getattr(menu, "itemComparatorAlpha", None)
            if comparator is not None:
                menu.setComparator(comparator)

        group = RadioGroup()

        # Mutable reference shared by the radio-button closures AND
        # the _on_pop listener.  When the confirm dialog "Keep" action
        # fires setupNext, it sets this to None so that _on_pop does
        # NOT call it again.  This exactly mirrors the Lua original's
        # shared upvalue semantics.
        setup_next_ref: List[Optional[Callable[..., Any]]] = [setup_next]

        mgr = _get_applet_manager()

        # Iterate over registered skins and add radio buttons
        skins_iter = None
        if hasattr(jive_main, "skin_iterator"):
            skins_iter = jive_main.skin_iterator()
        elif hasattr(jive_main, "skinIterator"):
            skins_iter = jive_main.skinIterator()

        if skins_iter is not None:
            for skin_id, name in skins_iter:
                # ----- build the RadioButton closure inline -----
                # This replicates the Lua original where the entire
                # confirm-dialog flow is inside the radio closure.
                def _make_skin_closure(
                    sid: str = skin_id,
                ) -> Callable[..., None]:
                    def _on_radio_selected(*_args: Any) -> None:
                        # Determine the currently active skin type
                        active_skin_type = "skin"
                        if mgr is not None:
                            result = mgr.call_service("getActiveSkinType")
                            if result is not None:
                                active_skin_type = result

                        # Snapshot current skin BEFORE switching
                        current_skin = ""
                        if hasattr(jive_main, "get_selected_skin"):
                            current_skin = jive_main.get_selected_skin() or ""
                        elif hasattr(jive_main, "getSelectedSkin"):
                            current_skin = jive_main.getSelectedSkin() or ""

                        # If the active type matches, switch immediately
                        if active_skin_type == skin_type:
                            if hasattr(jive_main, "set_selected_skin"):
                                jive_main.set_selected_skin(sid)
                            elif hasattr(jive_main, "setSelectedSkin"):
                                jive_main.setSelectedSkin(sid)

                        settings = self.get_settings()
                        if settings is not None:
                            settings[skin_type] = sid
                        self.changed = True

                        # --- Confirmation dialog (inline) ---
                        confirm_group = RadioGroup()
                        confirm_window = Window(
                            "text_list", self.string("CONFIRM_SKIN")
                        )

                        timer_ref: List[Any] = [None]

                        def _revert(*_a: Any) -> None:
                            log.info("revert skin choice")
                            if hasattr(jive_main, "set_selected_skin"):
                                jive_main.set_selected_skin(current_skin)
                            elif hasattr(jive_main, "setSelectedSkin"):
                                jive_main.setSelectedSkin(current_skin)
                            s = self.get_settings()
                            if s is not None:
                                s[skin_type] = current_skin
                            confirm_window.hide()

                        def _keep(*_a: Any) -> None:
                            log.info("keep skin choice")
                            if timer_ref[0] is not None:
                                timer_ref[0].stop()
                            if setup_next_ref[0] is not None:
                                cb = setup_next_ref[0]
                                setup_next_ref[0] = None  # consume!
                                cb()
                            else:
                                confirm_window.hide()

                        def _on_timeout() -> None:
                            log.info("no selection - reverting skin choice")
                            if hasattr(jive_main, "set_selected_skin"):
                                jive_main.set_selected_skin(current_skin)
                            elif hasattr(jive_main, "setSelectedSkin"):
                                jive_main.setSelectedSkin(current_skin)
                            s = self.get_settings()
                            if s is not None:
                                s[skin_type] = current_skin
                            confirm_window.hide()

                        confirm_menu = SimpleMenu(
                            "menu",
                            [
                                {
                                    "text": self.string("REVERT_SKIN"),
                                    "style": "item_choice",
                                    "check": RadioButton(
                                        "radio", confirm_group, _revert, True
                                    ),
                                },
                                {
                                    "text": self.string("KEEP_SKIN"),
                                    "style": "item_choice",
                                    "check": RadioButton(
                                        "radio", confirm_group, _keep, False
                                    ),
                                },
                            ],
                        )

                        timer = Timer(10000, _on_timeout, once=True)
                        timer.start()
                        timer_ref[0] = timer

                        confirm_window.add_widget(confirm_menu)
                        self.tie_and_show_window(confirm_window)

                    return _on_radio_selected

                button = RadioButton(
                    "radio",
                    group,
                    _make_skin_closure(),
                    skin_id == previously_selected_skin,
                )

                menu.add_item(
                    {
                        "text": name,
                        "style": "item_choice",
                        "check": button,
                    }
                )

        window.add_widget(menu)

        def _on_pop(event: Any) -> int:
            if self.changed:
                self.store_settings()
            if setup_next_ref[0] is not None:
                setup_next_ref[0]()
            return int(EVENT_UNUSED)

        window.add_listener(int(EVENT_WINDOW_POP), _on_pop)

        self.tie_and_show_window(window)
        return window

    # Lua alias
    selectSkin = select_skin

    # ==================================================================
    # Repr
    # ==================================================================

    def __repr__(self) -> str:
        settings = self.get_settings() or {}
        skin = settings.get("skin", "?")
        return f"SelectSkinApplet(skin={skin!r}, changed={self.changed})"

    def __str__(self) -> str:
        return self.__repr__()
