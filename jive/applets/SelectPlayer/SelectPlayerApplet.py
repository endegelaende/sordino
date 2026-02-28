"""
jive.applets.select_player.select_player_applet — SelectPlayer applet.

Ported from ``share/jive/applets/SelectPlayer/SelectPlayerApplet.lua``
(~504 LOC Lua) in the original jivelite project.

SelectPlayer provides the player-selection screen that:

* Displays all available Squeezebox players on the network
* Allows the user to choose which player to control
* Manages the "Choose Player" menu item dynamically based on
  the number of available players
* Handles password-protected server entries
* Supports setup-mode with a ``setupNext`` callback for wizards
* Shows a "Scanning for Players..." popup during initial discovery
* Previews wallpaper for each focused player
* Triggers network configuration or music-source selection when
  a player requires setup

The applet subscribes to player/server notifications and is loaded
as a resident applet (never freed).

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

from jive.applet import Applet
from jive.ui.constants import (
    EVENT_CONSUME,
    EVENT_UNUSED,
    EVENT_WINDOW_ACTIVE,
)
from jive.utils.log import logger

__all__ = ["SelectPlayerApplet"]

log = logger("applet.SelectPlayer")

# ---------------------------------------------------------------------------
# Weight constants for menu ordering
# ---------------------------------------------------------------------------

LOCAL_PLAYER_WEIGHT = 1
PLAYER_WEIGHT = 5
SERVER_WEIGHT = 10
ACTIVATE_WEIGHT = 20

# Valid player models for icon-style lookup
_VALID_MODELS = frozenset(
    {
        "softsqueeze",
        "transporter",
        "squeezebox2",
        "squeezebox3",
        "squeezebox",
        "slimp3",
        "receiver",
        "boom",
        "controller",
        "squeezeplay",
        "http",
        "fab4",
        "baby",
    }
)


# ---------------------------------------------------------------------------
# Lazy import helpers
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
    except (ImportError, AttributeError):
        pass
    try:
        import jive.jive_main as _mod

        return getattr(_mod, "jive_main", None)
    except ImportError:
        return None


def _get_framework() -> Any:
    try:
        from jive.ui.framework import Framework

        return Framework
    except ImportError:
        return None


def _get_jnt() -> Any:
    """Obtain the network-thread coordinator singleton."""
    try:
        from jive.slim.player import jnt

        return jnt
    except (ImportError, AttributeError):
        pass
    return None


def _import_ui_class(module_name: str, class_name: str) -> Any:
    """Dynamically import a UI class."""
    import importlib

    mod = importlib.import_module(f"jive.ui.{module_name}")
    return getattr(mod, class_name)


# Cached UI class accessors
_ui_cache: Dict[str, Any] = {}


def _Window() -> Any:
    if "Window" not in _ui_cache:
        _ui_cache["Window"] = _import_ui_class("window", "Window")
    return _ui_cache["Window"]


def _SimpleMenu() -> Any:
    if "SimpleMenu" not in _ui_cache:
        _ui_cache["SimpleMenu"] = _import_ui_class("simplemenu", "SimpleMenu")
    return _ui_cache["SimpleMenu"]


def _Label() -> Any:
    if "Label" not in _ui_cache:
        _ui_cache["Label"] = _import_ui_class("label", "Label")
    return _ui_cache["Label"]


def _Icon() -> Any:
    if "Icon" not in _ui_cache:
        _ui_cache["Icon"] = _import_ui_class("icon", "Icon")
    return _ui_cache["Icon"]


def _Popup() -> Any:
    if "Popup" not in _ui_cache:
        _ui_cache["Popup"] = _import_ui_class("popup", "Popup")
    return _ui_cache["Popup"]


def _Group() -> Any:
    if "Group" not in _ui_cache:
        _ui_cache["Group"] = _import_ui_class("group", "Group")
    return _ui_cache["Group"]


# ---------------------------------------------------------------------------
# SelectPlayerApplet
# ---------------------------------------------------------------------------


class SelectPlayerApplet(Applet):
    """SelectPlayer applet — lets the user choose which player to control.

    This is a resident applet: it subscribes to player/server
    notifications and dynamically manages the "Choose Player" menu
    item.  It is never freed during normal operation.
    """

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def __init__(self) -> None:
        super().__init__()

        # Menu items indexed by player MAC or server name
        self.playerItem: Dict[str, Dict[str, Any]] = {}
        self.serverItem: Dict[str, Dict[str, Any]] = {}
        self.scanResults: Dict[str, Any] = {}

        # The SimpleMenu widget (created when the screen is shown)
        self.playerMenu: Any = None

        # Currently selected player
        self.selectedPlayer: Any = None

        # The "Choose Player" menu item registered in the home/settings menu
        self.selectPlayerMenuItem: Optional[Dict[str, Any]] = None

        # Setup-mode flag and callback
        self.setupMode: bool = False
        self.setupNext: Optional[Callable[..., Any]] = None

        # Scanning popup
        self.populatingPlayers: Any = False
        self.playersFound: bool = False

        # Wireless interface (optional, only if networking is available)
        self.wireless: Any = None

    def init(self) -> None:
        """Initialise the applet after settings / strings are available."""
        super().init()

        self.playerItem = {}
        self.serverItem = {}
        self.scanResults = {}

        # Try to get a wireless interface
        try:
            from jive.net.networking import Networking  # type: ignore[import-untyped]

            jnt = _get_jnt()
            if jnt is not None:
                self.wireless = Networking.wirelessInterface(jnt)
        except (ImportError, AttributeError):
            self.wireless = None

        # Subscribe to player/server notifications
        jnt = _get_jnt()
        if jnt is not None:
            jnt.subscribe(self)

        self.manage_select_player_menu()

    # ------------------------------------------------------------------
    # Notification handlers
    # ------------------------------------------------------------------

    def notify_playerDelete(self, player: Any) -> None:
        """Handle player deletion notification."""
        mac = self._get_player_id(player)

        self.manage_select_player_menu()

        if self.playerMenu:
            item = self.playerItem.get(mac)
            if item is not None:
                if hasattr(self.playerMenu, "removeItem"):
                    self.playerMenu.removeItem(item)
                del self.playerItem[mac]

            server = self._get_player_server(player)
            if server is not None:
                self._update_server_item(server)

    def notify_playerNew(self, player: Any) -> None:
        """Handle new player notification."""
        self.manage_select_player_menu()

        if self.playerMenu:
            self._add_player_item(player)

            server = self._get_player_server(player)
            if server is not None:
                self._update_server_item(server)

    def notify_playerCurrent(self, player: Any) -> None:
        """Handle current-player change notification."""
        self.selectedPlayer = player
        self.manage_select_player_menu()

    def notify_serverConnected(self, server: Any) -> None:
        """Handle server-connected notification."""
        if not self.playerMenu:
            return

        self._update_server_item(server)

        # Refresh all players on this server
        if hasattr(server, "allPlayers"):
            for player_id, player in server.allPlayers():
                self._refresh_player_item(player)
        elif hasattr(server, "all_players"):
            for player_id, player in server.all_players():
                self._refresh_player_item(player)

        self.manage_select_player_menu()

    def notify_serverDisconnected(self, server: Any) -> None:
        """Handle server-disconnected notification."""
        if not self.playerMenu:
            return

        self._update_server_item(server)

        if hasattr(server, "allPlayers"):
            for player_id, player in server.allPlayers():
                self._refresh_player_item(player)
        elif hasattr(server, "all_players"):
            for player_id, player in server.all_players():
                self._refresh_player_item(player)

        self.manage_select_player_menu()

    # ------------------------------------------------------------------
    # Menu management
    # ------------------------------------------------------------------

    def manage_select_player_menu(self) -> None:
        """Add or remove the "Choose Player" menu item based on player count."""
        mgr = _get_applet_manager()
        jive_main = _get_jive_main()

        num_players = 0
        current_player = None
        if mgr:
            num_players = mgr.call_service("countPlayers") or 0
            current_player = mgr.call_service("getCurrentPlayer")

        should_show = (
            num_players > 1
            or current_player is None
            or (
                current_player is not None
                and hasattr(current_player, "isConnected")
                and not current_player.isConnected()
            )
            or (
                current_player is not None
                and hasattr(current_player, "is_connected")
                and not current_player.is_connected()
            )
        )

        if should_show:
            if self.selectPlayerMenuItem is None and jive_main is not None:
                # Determine node and weight based on device type
                node = "home"
                weight = 103

                try:
                    from jive.system import System

                    sys_inst = System()
                    if sys_inst.has_audio_by_default():
                        node = "settings"
                        weight = 50
                except (ImportError, AttributeError):
                    pass

                menu_item: Dict[str, Any] = {
                    "id": "selectPlayer",
                    "iconStyle": "hm_selectPlayer",
                    "node": node,
                    "text": self.string("SELECT_PLAYER"),
                    "sound": "WINDOWSHOW",
                    "callback": lambda event=None, mi=None: (
                        self.setupShowSelectPlayer()
                    ),
                    "weight": weight,
                }

                if hasattr(jive_main, "add_item"):
                    jive_main.add_item(menu_item)
                elif hasattr(jive_main, "addItem"):
                    jive_main.addItem(menu_item)

                self.selectPlayerMenuItem = menu_item

        elif not should_show:
            if (
                num_players < 2
                and current_player is not None
                and self.selectPlayerMenuItem is not None
            ):
                if jive_main is not None:
                    if hasattr(jive_main, "remove_item_by_id"):
                        jive_main.remove_item_by_id("selectPlayer")
                    elif hasattr(jive_main, "removeItemById"):
                        jive_main.removeItemById("selectPlayer")
                self.selectPlayerMenuItem = None

    # Lua alias
    manageSelectPlayerMenu = manage_select_player_menu

    # ------------------------------------------------------------------
    # Player item management
    # ------------------------------------------------------------------

    def _add_player_item(self, player: Any) -> None:
        """Add a player to the selection menu."""
        mac = self._get_player_id(player)
        if mac is None:
            return

        player_name = self._get_player_name(player)
        player_weight = PLAYER_WEIGHT

        # Don't show players needing network setup on audio-default devices
        try:
            from jive.system import System

            sys_inst = System()
            if sys_inst.has_audio_by_default():
                config = getattr(player, "config", None)
                if config == "needsNetwork":
                    return
        except (ImportError, AttributeError):
            pass

        # Determine player model and icon style
        player_model = None
        if hasattr(player, "get_model"):
            player_model = player.get_model()
        elif hasattr(player, "getModel"):
            player_model = player.getModel()

        if player_model is None:
            # Guess model by MAC address
            if hasattr(player, "mac_to_model"):
                player_model = player.mac_to_model(mac)
            elif hasattr(player, "macToModel"):
                player_model = player.macToModel(mac)

        if player_model not in _VALID_MODELS:
            player_model = "squeezeplay"

        # Local players get higher priority (lower weight)
        is_local = False
        if hasattr(player, "is_local"):
            is_local = player.is_local()
        elif hasattr(player, "isLocal"):
            is_local = player.isLocal()

        if is_local:
            player_weight = LOCAL_PLAYER_WEIGHT

        # Build the menu item
        def _make_callback(p: Any) -> Callable:
            def _cb(event: Any = None, mi: Any = None) -> None:
                log.info("select player item: %s", p)
                if self.select_player(p):
                    log.info("going to setupNext")
                    if self.setupNext:
                        self.setupNext()

            return _cb

        def _make_focus_gained(player_mac: str) -> Callable:
            def _fg(event: Any = None) -> int:
                self._show_wallpaper(player_mac)
                return EVENT_UNUSED

            return _fg

        item: Dict[str, Any] = {
            "id": mac,
            "style": "item",
            "iconStyle": f"player_{player_model}",
            "text": player_name or mac,
            "sound": "WINDOWSHOW",
            "callback": _make_callback(player),
            "focusGained": _make_focus_gained(mac),
            "weight": player_weight,
        }

        # Mark currently selected player
        is_connected = False
        if hasattr(player, "is_connected"):
            is_connected = player.is_connected()
        elif hasattr(player, "isConnected"):
            is_connected = player.isConnected()

        if player is self.selectedPlayer and is_connected:
            item["style"] = "item_checked"

        if self.playerMenu and hasattr(self.playerMenu, "addItem"):
            self.playerMenu.addItem(item)

        self.playerItem[mac] = item

        # If this is the selected player, focus on it
        if self.selectedPlayer is player:
            if self.playerMenu and hasattr(self.playerMenu, "setSelectedItem"):
                self.playerMenu.setSelectedItem(item)

        # Players found — no need for the scanning popup
        self.playersFound = True
        self._hide_populating_players_popup()

    def _refresh_player_item(self, player: Any) -> None:
        """Refresh an existing player item or add/remove as needed."""
        mac = self._get_player_id(player)
        if mac is None:
            return

        is_available = False
        if hasattr(player, "is_available"):
            is_available = player.is_available()
        elif hasattr(player, "isAvailable"):
            is_available = player.isAvailable()

        if is_available:
            item = self.playerItem.get(mac)
            if item is None:
                self._add_player_item(player)
            else:
                if player is self.selectedPlayer:
                    item["style"] = "item_checked"
        else:
            if mac in self.playerItem:
                if self.playerMenu and hasattr(self.playerMenu, "removeItem"):
                    self.playerMenu.removeItem(self.playerItem[mac])
                del self.playerItem[mac]

    def _update_server_item(self, server: Any) -> None:
        """Add or remove password-protected server entries."""
        server_name = None
        if hasattr(server, "get_name"):
            server_name = server.get_name()
        elif hasattr(server, "getName"):
            server_name = server.getName()
        if server_name is None:
            return

        # Check if the server is password-protected
        is_pw_protected = False
        if hasattr(server, "is_password_protected"):
            is_pw_protected = server.is_password_protected()
        elif hasattr(server, "isPasswordProtected"):
            is_pw_protected = server.isPasswordProtected()

        if not is_pw_protected:
            if server_name in self.serverItem:
                if self.playerMenu and hasattr(self.playerMenu, "removeItem"):
                    self.playerMenu.removeItem(self.serverItem[server_name])
                del self.serverItem[server_name]
            return

        def _make_server_callback(srv: Any) -> Callable:
            def _cb(event: Any = None, mi: Any = None) -> None:
                mgr = _get_applet_manager()
                if mgr:
                    mgr.call_service("squeezeCenterPassword", srv, None, None, True)

            return _cb

        item: Dict[str, Any] = {
            "id": server_name,
            "text": server_name,
            "sound": "WINDOWSHOW",
            "callback": _make_server_callback(server),
            "weight": SERVER_WEIGHT,
        }

        if self.playerMenu and hasattr(self.playerMenu, "addItem"):
            self.playerMenu.addItem(item)
        self.serverItem[server_name] = item

    # ------------------------------------------------------------------
    # Wallpaper preview
    # ------------------------------------------------------------------

    def _show_wallpaper(self, player_id: str) -> None:
        """Preview the background wallpaper for the given player."""
        log.debug("previewing wallpaper for %s", player_id)
        mgr = _get_applet_manager()
        if mgr:
            mgr.call_service("showBackground", None, player_id)

    # ------------------------------------------------------------------
    # Show the player-selection screen
    # ------------------------------------------------------------------

    def setupShowSelectPlayer(
        self,
        setup_next: Optional[Callable[..., Any]] = None,
        window_style: Optional[str] = None,
    ) -> Any:
        """Show the player-selection screen.

        Parameters
        ----------
        setup_next:
            Optional callback to invoke after a player is selected
            (used by setup wizards).  If ``None``, the default
            behaviour is to close to home.
        window_style:
            Window style override.  Defaults to ``"settingstitle"``.

        Returns
        -------
        The created Window instance.
        """
        if not window_style:
            window_style = "settingstitle"

        Window = _Window()
        SimpleMenu = _SimpleMenu()
        Framework = _get_framework()

        window = Window(
            "choose_player",
            str(self.string("SELECT_PLAYER")),
            window_style,
        )
        if hasattr(window, "setAllowScreensaver"):
            window.setAllowScreensaver(False)

        menu = SimpleMenu("menu")
        if hasattr(menu, "setComparator") and hasattr(
            SimpleMenu, "itemComparatorWeightAlpha"
        ):
            menu.setComparator(SimpleMenu.itemComparatorWeightAlpha)

        self.playerMenu = menu
        self.setupMode = setup_next is not None

        jive_main = _get_jive_main()

        def _default_setup_next() -> None:
            if jive_main and hasattr(jive_main, "close_to_home"):
                jive_main.close_to_home()
            elif jive_main and hasattr(jive_main, "closeToHome"):
                jive_main.closeToHome()

        self.setupNext = setup_next or _default_setup_next

        # Get current player selection
        mgr = _get_applet_manager()
        if mgr:
            self.selectedPlayer = mgr.call_service("getCurrentPlayer")

        # Populate with existing players
        if mgr:
            players = mgr.call_service("iteratePlayers")
            if players:
                try:
                    for mac, player in players:
                        self._add_player_item(player)
                except TypeError:
                    # iteratePlayers might return a dict
                    if isinstance(players, dict):
                        for mac, player in players.items():
                            self._add_player_item(player)

        # Display password-protected servers
        if mgr:
            servers = mgr.call_service("iterateSqueezeCenters")
            if servers:
                try:
                    for sid, server in servers:
                        self._update_server_item(server)
                except TypeError:
                    if isinstance(servers, dict):
                        for sid, server in servers.items():
                            self._update_server_item(server)

        if hasattr(window, "addWidget"):
            window.addWidget(menu)

        # Periodic scan timer (every 5 seconds)
        if hasattr(window, "addTimer"):

            def _scan_timer_cb() -> None:
                if Framework and hasattr(Framework, "windowStack"):
                    stack = Framework.windowStack
                    if (
                        isinstance(stack, (list, tuple))
                        and stack
                        and stack[0] is not window
                    ):
                        return
                self._scan()

            window.addTimer(5000, _scan_timer_cb)

        # Auto-hide popup after 10 seconds
        if hasattr(window, "addTimer"):
            window.addTimer(10000, lambda: self._hide_populating_players_popup())

        # Scan on window activation
        if hasattr(window, "addListener"):
            window.addListener(
                EVENT_WINDOW_ACTIVE,
                lambda event=None: (self._scan(), EVENT_UNUSED)[-1],
            )

        self.tie_and_show_window(window)

        # Show scanning popup in setup mode
        if self.setupMode:
            self.populatingPlayers = self._show_populating_players_popup()

        return window

    # Lua alias
    setup_show_select_player = setupShowSelectPlayer

    # ------------------------------------------------------------------
    # Scanning popup
    # ------------------------------------------------------------------

    def _hide_populating_players_popup(self) -> None:
        """Hide the 'Scanning for Players' popup if active."""
        if self.populatingPlayers:
            if hasattr(self.populatingPlayers, "hide"):
                self.populatingPlayers.hide()
            self.populatingPlayers = False

    def _show_populating_players_popup(self) -> Any:
        """Show the 'Scanning for Players' popup.

        Returns the popup widget, or ``None`` if not needed.
        """
        if self.populatingPlayers or self.playersFound:
            return None

        Popup = _Popup()
        Icon = _Icon()
        Label = _Label()

        popup = Popup("waiting_popup")
        icon = Icon("icon_connecting")
        label = Label("text", str(self.string("SEARCHING")))

        if hasattr(popup, "addWidget"):
            popup.addWidget(icon)
            popup.addWidget(label)

        if hasattr(popup, "setAlwaysOnTop"):
            popup.setAlwaysOnTop(True)

        if hasattr(popup, "show"):
            popup.show()

        return popup

    # ------------------------------------------------------------------
    # Network scanning
    # ------------------------------------------------------------------

    def _scan(self) -> None:
        """Trigger player and server discovery."""
        mgr = _get_applet_manager()
        if mgr:
            mgr.call_service("discoverPlayers")

    # ------------------------------------------------------------------
    # Player selection
    # ------------------------------------------------------------------

    def select_player(self, player: Any) -> bool:
        """Select a player and set it as current.

        Parameters
        ----------
        player:
            The player to select.

        Returns
        -------
        bool
            ``True`` if the selection is complete and we can proceed
            to the next step.  ``False`` if additional setup
            (network config, music source) is needed first.
        """
        self.selectedPlayer = player

        mgr = _get_applet_manager()
        if mgr:
            mgr.call_service("setCurrentPlayer", player)

        # Check if the player needs network configuration
        needs_net = False
        if hasattr(player, "needs_network_config"):
            needs_net = player.needs_network_config()
        elif hasattr(player, "needsNetworkConfig"):
            needs_net = player.needsNetworkConfig()

        if needs_net:
            log.info("needsNetworkConfig")
            player_id = self._get_player_id(player)
            player_ssid = None
            if hasattr(player, "get_ssid"):
                player_ssid = player.get_ssid()
            elif hasattr(player, "getSSID"):
                player_ssid = player.getSSID()

            def _after_net_setup() -> None:
                if self.setupMode and self.setupNext:
                    self.setupNext()
                elif self._player_needs_music_source(player):
                    if mgr:
                        mgr.call_service("selectMusicSource")

            if mgr:
                mgr.call_service(
                    "startSqueezeboxSetup",
                    player_id,
                    player_ssid,
                    _after_net_setup,
                )
            return False

        # Check if the player needs a music source
        needs_source = self._player_needs_music_source(player)
        if needs_source and not self.setupMode:
            log.info("selectMusicSource")
            if mgr:
                mgr.call_service(
                    "selectMusicSource",
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    True,
                )
            return False

        return True

    # Lua alias
    selectPlayer = select_player

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def free(self) -> bool:
        """Called when the applet is being freed.

        Restores the appropriate wallpaper on exit.
        SelectPlayer is never actually freed (returns ``False``).
        """
        # Restore wallpaper
        if self.selectedPlayer:
            pid = self._get_player_id(self.selectedPlayer)
            if pid:
                self._show_wallpaper(pid)
            else:
                self._show_wallpaper("wallpaper")
        else:
            self._show_wallpaper("wallpaper")

        # Never free this applet
        return False

    # ------------------------------------------------------------------
    # Private helpers — player attribute access (duck-typing)
    # ------------------------------------------------------------------

    @staticmethod
    def _get_player_id(player: Any) -> Optional[str]:
        """Get the player's unique identifier (MAC address)."""
        if player is None:
            return None
        if hasattr(player, "get_id"):
            return player.get_id()
        if hasattr(player, "getId"):
            return player.getId()
        return None

    @staticmethod
    def _get_player_name(player: Any) -> Optional[str]:
        """Get the player's display name."""
        if player is None:
            return None
        if hasattr(player, "get_name"):
            return player.get_name()
        if hasattr(player, "getName"):
            return player.getName()
        return None

    @staticmethod
    def _get_player_server(player: Any) -> Any:
        """Get the player's associated server."""
        if player is None:
            return None
        if hasattr(player, "get_slim_server"):
            return player.get_slim_server()
        if hasattr(player, "getSlimServer"):
            return player.getSlimServer()
        return None

    @staticmethod
    def _player_needs_music_source(player: Any) -> bool:
        """Check if the player needs a music source configured."""
        if player is None:
            return False
        if hasattr(player, "needs_music_source"):
            return player.needs_music_source()
        if hasattr(player, "needsMusicSource"):
            return player.needsMusicSource()
        return False
