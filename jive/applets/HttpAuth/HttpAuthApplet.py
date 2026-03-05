"""
jive.applets.HttpAuth.HttpAuthApplet — HTTP authentication applet.

Ported from ``share/jive/applets/HttpAuth/HttpAuthApplet.lua`` in the
original jivelite project.

This applet provides a sequential username/password input flow for
authenticating with a password-protected Lyrion Music Server.

Flow: Username input → Password input → (optional) Connecting popup

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from jive.applet import Applet
from jive.utils.log import logger

__all__ = ["HttpAuthApplet"]

log = logger("applet.HttpAuth")

CONNECT_TIMEOUT = 20


class HttpAuthApplet(Applet):
    """HTTP authentication applet for LMS password protection."""

    def __init__(self) -> None:
        super().__init__()
        self.server: Any = None
        self.setup_next: Optional[Callable[[], Any]] = None
        self.title_style: Optional[str] = None
        self.show_connecting: Optional[bool] = None
        self.username: Optional[str] = None
        self.password: Optional[str] = None
        self.input_windows: Dict[str, Any] = {}
        self.top_window: Any = None
        self.connecting_popup: Any = None

    # ------------------------------------------------------------------
    # Service entry point
    # ------------------------------------------------------------------

    def squeezeCenterPassword(
        self,
        server: Any,
        setup_next: Optional[Callable[[], Any]] = None,
        title_style: Optional[str] = None,
        show_connecting: Optional[bool] = None,
    ) -> None:
        """Start the username/password input flow.

        Parameters
        ----------
        server:
            The SlimServer to authenticate with.
        setup_next:
            Optional callback after successful authentication.
        title_style:
            Optional window title style override.
        show_connecting:
            If True, show a connecting popup after entering credentials.
        """
        self.server = server
        if setup_next is not None:
            self.setup_next = setup_next
        if title_style is not None:
            self.title_style = title_style
        self.show_connecting = show_connecting

        self.input_windows = {}

        self.top_window = self._enter_text_window(
            "username",
            "HTTP_AUTH_USERNAME",
            "HTTP_AUTH_USERNAME_HELP",
            self._enter_password,
        )

    # Lua-compatible alias
    squeeze_center_password = squeezeCenterPassword

    # ------------------------------------------------------------------
    # Input flow
    # ------------------------------------------------------------------

    def _enter_password(self) -> None:
        """Show the password input window."""
        self._enter_text_window(
            "password",
            "HTTP_AUTH_PASSWORD",
            "HTTP_AUTH_PASSWORD_HELP",
            self._enter_done,
        )

    def _enter_done(self) -> None:
        """Store credentials and optionally show connecting popup."""
        realm = ""
        if self.server is not None:
            protected_info = None
            if hasattr(self.server, "isPasswordProtected"):
                protected_info = self.server.isPasswordProtected()
            elif hasattr(self.server, "is_password_protected"):
                protected_info = self.server.is_password_protected()
            if isinstance(protected_info, tuple) and len(protected_info) >= 2:
                realm = protected_info[1] or ""
            elif isinstance(protected_info, str):
                realm = protected_info

        # Store credentials
        settings = self.get_settings()
        if settings is None:
            settings = {}
            self.set_settings(settings)

        server_id = None
        if self.server is not None:
            if hasattr(self.server, "getId"):
                server_id = self.server.getId()
            elif hasattr(self.server, "get_id"):
                server_id = self.server.get_id()
            elif hasattr(self.server, "id"):
                server_id = self.server.id

        if server_id is not None:
            settings[server_id] = {
                "realm": realm,
                "username": self.username or "",
                "password": self.password or "",
            }
            self.store_settings()

        # Set authorization on the server
        if self.server is not None:
            cred = {
                "realm": realm,
                "username": self.username or "",
                "password": self.password or "",
            }
            if hasattr(self.server, "set_credentials"):
                self.server.set_credentials(cred)
            elif hasattr(self.server, "setCredentials"):
                self.server.setCredentials(cred)

        self.username = None
        self.password = None

        if self.show_connecting:
            jnt = self._get_jnt()
            if jnt is not None:
                jnt.subscribe(self)
            self._show_connect_to_server(self.server)
            self._hide_input_windows()
            return

        # Hide the top input window
        if self.top_window is not None:
            try:
                from jive.ui.window import Window

                self.top_window.hide(Window.transitionPushLeft)
            except (ImportError, AttributeError):
                try:
                    self.top_window.hide()
                except Exception as exc:
                    log.warning("failed to hide top input window: %s", exc)

        if self.setup_next is not None:
            self.setup_next()

    # ------------------------------------------------------------------
    # Input windows
    # ------------------------------------------------------------------

    def _hide_input_windows(self) -> None:
        """Hide all input windows."""
        for window in self.input_windows.values():
            try:
                from jive.ui.window import Window

                window.hide(Window.transitionNone)
            except (ImportError, AttributeError):
                try:
                    window.hide()
                except Exception as exc:
                    log.warning("failed to hide input window: %s", exc)

    def _enter_text_window(
        self,
        key: str,
        title: str,
        help_token: str,
        next_fn: Callable[[], None],
    ) -> Any:
        """Create a text input window with keyboard.

        Parameters
        ----------
        key:
            Attribute name to store the entered value (``"username"`` or
            ``"password"``).
        title:
            String token for the window title.
        help_token:
            String token for the help text (currently unused).
        next_fn:
            Callback to invoke when input is confirmed.
        """
        try:
            from jive.ui.group import Group
            from jive.ui.keyboard import Keyboard
            from jive.ui.textinput import Textinput
            from jive.ui.window import Window
        except ImportError as exc:
            log.warn("UI modules not available: %s", exc)
            return None

        window = Window("text_list", self.string(title), self.title_style)

        current_value = getattr(self, key, None) or ""

        def _on_input_done(_widget: Any, value: Any) -> bool:
            setattr(self, key, value)
            window.play_sound("WINDOWSHOW")
            next_fn()
            return True

        text_input = Textinput("textinput", current_value, _on_input_done)

        keyboard = Keyboard("keyboard", "qwerty", text_input)
        backspace = Keyboard.backspace()
        group = Group(
            "keyboard_textinput",
            {"textinput": text_input, "backspace": backspace},
        )

        window.add_widget(group)
        window.add_widget(keyboard)
        window.focus_widget(group)

        self.input_windows[key] = window

        self.tie_and_show_window(window)
        return window

    # ------------------------------------------------------------------
    # Connecting popup
    # ------------------------------------------------------------------

    def _show_connect_to_server(self, server: Any) -> None:
        """Show a 'Connecting to...' popup with timeout."""
        try:
            from jive.ui.icon import Icon
            from jive.ui.label import Label
            from jive.ui.popup import Popup
        except ImportError as exc:
            log.warn("UI modules not available for connecting popup: %s", exc)
            return

        popup = Popup("waiting_popup")
        self.connecting_popup = popup

        popup.add_widget(Icon("icon_connecting"))

        server_name = ""
        if server is not None:
            if hasattr(server, "getName"):
                server_name = server.getName()
            elif hasattr(server, "get_name"):
                server_name = server.get_name()
            elif hasattr(server, "name"):
                server_name = server.name

        popup.add_widget(Label("text", self.string("HTTP_AUTH_CONNECTING_TO")))
        popup.add_widget(Label("subtext", server_name))

        timeout_count = [1]

        def cancel_action(event: Any = None) -> Any:
            timeout_count[0] = 1
            self.show_connecting = None
            popup.hide()
            from jive.ui.constants import EVENT_CONSUME

            return EVENT_CONSUME

        popup.ignore_all_input_except(["back", "go_home"])
        popup.add_action_listener("back", self, cancel_action)
        popup.add_action_listener("go_home", self, cancel_action)

        def _timer_tick() -> None:
            timeout_count[0] += 1
            if timeout_count[0] > CONNECT_TIMEOUT:
                log.warn("Timeout passed, current count: %d", timeout_count[0])
                cancel_action()

        popup.add_timer(1000, _timer_tick)

        self.tie_and_show_window(popup)

    # ------------------------------------------------------------------
    # Notification handlers
    # ------------------------------------------------------------------

    def notify_serverAuthFailed(self, server: Any, failure_count: int = 0) -> None:
        """Handle authentication failure notification."""
        if self.show_connecting and self.server is server and failure_count == 1:
            log.debug("Auth failed for server: %s", server)
            self._http_auth_error_window(server)

    # Lua-compatible alias
    notify_server_auth_failed = notify_serverAuthFailed

    def notify_serverConnected(self, server: Any) -> None:
        """Handle successful server connection."""
        if not self.show_connecting or self.server is not server:
            return
        log.info("notify_serverConnected")
        if self.connecting_popup is not None:
            try:
                self.connecting_popup.hide()
            except Exception as exc:
                log.error(
                    "notify_serverConnected: failed to hide connecting popup: %s",
                    exc,
                    exc_info=True,
                )
        if self.setup_next is not None:
            self.setup_next()

    # Lua-compatible alias
    notify_server_connected = notify_serverConnected

    # ------------------------------------------------------------------
    # Error window
    # ------------------------------------------------------------------

    def _http_auth_error_window(self, server: Any) -> None:
        """Show authentication error window with retry option."""
        try:
            from jive.ui.constants import EVENT_CONSUME
            from jive.ui.simplemenu import SimpleMenu
            from jive.ui.textarea import Textarea
            from jive.ui.window import Window
        except ImportError as exc:
            log.warn("UI modules not available for error window: %s", exc)
            return

        window = Window(
            "help_list",
            self.string("HTTP_AUTH_PASSWORD_WRONG"),
            "setuptitle",
        )

        textarea = Textarea(
            "help_text",
            self.string("HTTP_AUTH_PASSWORD_WRONG_BODY"),
        )

        menu = SimpleMenu("menu")
        window.set_auto_hide(True)

        mgr = self._get_applet_manager()

        def _try_again() -> None:
            if mgr is not None:
                mgr.call_service("squeezeCenterPassword", server, None, None, True)

        menu.addItem(
            {
                "text": self.string("HTTP_AUTH_TRY_AGAIN"),
                "sound": "WINDOWHIDE",
                "callback": _try_again,
            }
        )

        def cancel_action(event: Any = None) -> int:
            window.play_sound("WINDOWHIDE")
            window.hide()
            return int(EVENT_CONSUME)

        menu.add_action_listener("back", self, cancel_action)
        menu.add_action_listener("go_home", self, cancel_action)

        menu.setHeaderWidget(textarea)
        window.add_widget(menu)

        self.tie_and_show_window(window)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def free(self) -> bool:
        """Unsubscribe from notifications and allow freeing."""
        log.debug("Unsubscribing jnt")
        jnt = self._get_jnt()
        if jnt is not None:
            jnt.unsubscribe(self)
        return True

    # ------------------------------------------------------------------
    # Singleton accessors
    # ------------------------------------------------------------------

    @staticmethod
    def _get_jnt() -> Any:
        try:
            from jive.jive_main import jive_main as _jm

            if _jm is not None:
                return getattr(_jm, "jnt", None)
        except ImportError as exc:
            log.debug("_get_jnt: jive_main not available: %s", exc)
        return None

    @staticmethod
    def _get_applet_manager() -> Any:
        try:
            from jive.applet_manager import applet_manager

            return applet_manager
        except (ImportError, AttributeError):
            return None
