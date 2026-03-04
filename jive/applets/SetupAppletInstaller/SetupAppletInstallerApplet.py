"""
jive.applets.SetupAppletInstaller.SetupAppletInstallerApplet — Applet Installer.

Ported from ``share/jive/applets/SetupAppletInstaller/SetupAppletInstallerApplet.lua``
in the original jivelite project.

This applet allows users to:

* Browse available third-party applets from connected SqueezeCenter servers
* Install, update, reinstall, or remove applets
* Optionally auto-reinstall applets after a firmware/application upgrade

The Lua original downloads zip archives from the server, verifies SHA1
checksums, and extracts them into the user applet directory.  The Python
port replicates this workflow using standard library modules (``zipfile``,
``hashlib``, ``shutil``, ``urllib``/``requests``).

Architecture:

1. ``appletInstallerMenu(menuItem, action)`` — Entry point.  Queries all
   connected (non-SqueezeNetwork) servers for ``jiveapplets``.  Shows a
   loading popup while waiting, then builds a menu of available applets.
2. ``menuSink(server, data)`` — Callback that collects server responses.
   When all responses (or a timeout) are in, builds the UI menu.
3. ``_repoEntry`` / ``_nonRepoEntry`` — Detail screens for individual
   applets (install/update/remove actions).
4. ``action()`` — Performs the actual download/removal in a background
   task, showing a progress popup.
5. ``_remove()`` / ``_download()`` / ``_finished()`` — Sequential steps
   in the install/remove workflow.

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

import hashlib
import io
import os
import re
import shutil
import zipfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from jive.applet import Applet
from jive.utils.log import logger

__all__ = ["SetupAppletInstallerApplet"]

log = logger("applet.SetupAppletInstaller")

# Sentinel used when the real JIVE_VERSION is unavailable.
_FALLBACK_VERSION = "0.0.0"


class SetupAppletInstallerApplet(Applet):
    """Applet installer — browse, install, update and remove 3rd-party applets.

    Queries all connected SqueezeCenter servers for available applets,
    presents a menu, and handles download/extraction/removal.
    """

    def __init__(self) -> None:
        super().__init__()

        # UI state
        self.title: Any = None
        self.window: Any = None
        self.menu: Any = None
        self.popup: Any = None
        self.animatewindow: Any = None
        self.animatelabel: Any = None
        self.appletwindow: Any = None
        self.task: Any = None
        self.timer: Any = None
        self.auto: bool = False

        # Server query state
        self.waitingfor: int = 0
        self.best: Dict[str, Any] = {}
        self.sn: Any = None  # SqueezeNetwork server reference

        # Action state
        self.toremove: Dict[str, Any] = {}
        self.todownload: Dict[str, Any] = {}
        self.inrepos: Dict[str, int] = {}

        # Reinstall / update tracking
        self.reinstall: Optional[Dict[str, Any]] = None
        self.updateall: Optional[Dict[str, Any]] = None

        # Version info
        self.version: str = _FALLBACK_VERSION

        # Applet directory
        self.appletdir: str = ""

    # ------------------------------------------------------------------
    # Main entry point (service: appletInstallerMenu)
    # ------------------------------------------------------------------

    def appletInstallerMenu(self, menu_item: Any = None, action: Any = None) -> Any:
        """Show the applet installer menu.

        Queries connected servers for available applets, shows a
        loading popup, then builds the install/update/remove menu.

        Parameters
        ----------
        menu_item:
            The menu item dict (must contain ``"text"`` for the title).
        action:
            If ``'auto'``, run in automatic reinstall mode (no UI
            interaction required).
        """
        if menu_item is None:
            menu_item = {}

        self.title = self.title or (
            menu_item.get("text", self.string("APPLET_INSTALLER"))
            if isinstance(menu_item, dict)
            else self.string("APPLET_INSTALLER")
        )

        Window = self._get_window_class()
        if Window is not None and self.window is None:
            self.window = Window("text_list", self.title)

        self.auto = action == "auto" if action else False

        # Parse JIVE_VERSION into major.minor.patch
        jive_ver = self._get_jive_version_string()
        match = re.match(r"(\d+)\.(\d+)\.(\d+)", jive_ver)
        if match:
            self.version = f"{match.group(1)}.{match.group(2)}.{match.group(3)}"
        else:
            self.version = jive_ver

        log.info("requesting applets for version: %s", self.version)

        # Find the user applet directory
        system = self._get_system()
        if system is not None:
            user_dir = system.get_user_dir()
            if user_dir:
                self.appletdir = os.path.join(str(user_dir), "applets")
        else:
            self.appletdir = os.path.join(
                os.path.expanduser("~"), ".jivelite", "applets"
            )

        log.info("User Applets Path: %s", self.appletdir)

        # Query all non-SqueezeNetwork servers
        self.waitingfor = 0
        self.best = {}
        self.sn = None
        self.reinstall = None
        self.updateall = None

        mgr = self._get_applet_manager()
        if mgr is not None:
            try:
                servers = mgr.call_service("iterateSqueezeCenters")
                if servers is not None:
                    for server_id, server in (
                        servers.items() if isinstance(servers, dict) else servers
                    ):
                        if self._is_squeeze_network(server):
                            self.sn = server
                        else:
                            self._send_request(server)
                            self.waitingfor += 1
            except Exception as exc:
                log.debug("Failed to iterate servers: %s", exc)

        # Start a timer for server response timeout
        Timer = self._get_timer_class()
        if Timer is not None:
            try:
                self.timer = Timer(
                    10000,
                    lambda *_a, **_kw: self.menuSink(None, None),
                    True,
                )
                self.timer.start()
            except Exception as exc:
                log.debug("Failed to create timeout timer: %s", exc)

        # Show loading popup
        Popup = self._get_popup_class()
        Icon = self._get_icon_class()
        Label = self._get_label_class()

        if Popup is not None:
            self.popup = Popup("waiting_popup")
            if Icon is not None:
                self.popup.add_widget(Icon("icon_connecting"))
            if Label is not None:
                self.popup.add_widget(Label("text", self.string("APPLET_FETCHING")))
            self.tie_and_show_window(self.popup)

        return self.window

    # ------------------------------------------------------------------
    # Server query
    # ------------------------------------------------------------------

    def _send_request(self, server: Any) -> None:
        """Send a ``jiveapplets`` query to a server.

        Mirrors the Lua ``sendRequest`` method.
        """
        log.info("sending query to %s", server)

        system = self._get_system()
        machine = "jive"
        if system is not None:
            machine = system.get_machine()

        def _response_callback(
            chunk: Any = None, err: Any = None, **kwargs: Any
        ) -> None:
            if err:
                log.debug("Server query error: %s", err)
            elif chunk is not None:
                data = chunk.get("data", chunk) if isinstance(chunk, dict) else chunk
                self.menuSink(server, data)

        try:
            if hasattr(server, "userRequest"):
                server.userRequest(
                    _response_callback,
                    None,
                    [
                        "jiveapplets",
                        f"target:{machine}",
                        f"version:{self.version}",
                    ],
                )
            elif hasattr(server, "user_request"):
                server.user_request(
                    _response_callback,
                    None,
                    [
                        "jiveapplets",
                        f"target:{machine}",
                        f"version:{self.version}",
                    ],
                )
        except Exception as exc:
            log.debug("Failed to send request to %s: %s", server, exc)
            self.waitingfor = max(0, self.waitingfor - 1)

    # ------------------------------------------------------------------
    # Response sink — builds the menu when all servers have replied
    # ------------------------------------------------------------------

    def menuSink(self, server: Any, data: Any) -> None:
        """Process a server response or timeout.

        Collects responses, picks the best (most entries), and when
        all responses are in (or timeout fires), builds the UI menu.

        Parameters
        ----------
        server:
            The server that responded, or ``None`` for timeout.
        data:
            The response data dict, or ``None``.
        """
        if server is not None and data is not None:
            count = 0
            if isinstance(data, dict):
                count = int(data.get("count", 0))
            log.info("response received from %s with %d entries", server, count)

            best_count = self.best.get("count")
            if best_count is None or best_count < count:
                self.best = {"server": server, "count": count, "data": data}
            self.waitingfor -= 1
        elif server is None:
            # Timeout
            log.info("timeout waiting for response")
            self.waitingfor = 0

        if self.waitingfor > 0:
            return

        # If no entries and SqueezeNetwork available, try SN
        best_count = self.best.get("count")
        if (best_count is None or best_count == 0) and self.sn is not None:
            log.info("no entries — sending query to SqueezeNetwork")
            self._send_request(self.sn)
            self.sn = None
            self.waitingfor = 1
            if self.timer is not None:
                try:
                    self.timer.restart()
                except Exception as exc:
                    log.warning("menuSink: failed to restart timeout timer: %s", exc)
            return

        # We have the best response — build the menu
        data = self.best.get("data")
        server = self.best.get("server")
        log.info(
            "best received from %s with %d entries",
            server,
            data.get("count", 0) if isinstance(data, dict) else 0,
        )

        # Kill the timer
        if self.timer is not None:
            try:
                self.timer.stop()
            except Exception as exc:
                log.warning("menuSink: failed to stop timeout timer: %s", exc)

        # Build UI menu
        self._build_menu(data, server)

    # ------------------------------------------------------------------
    # Menu builder
    # ------------------------------------------------------------------

    def _build_menu(self, data: Any, server: Any) -> None:
        """Build the applet list menu from server data."""
        SimpleMenu = self._get_simple_menu_class()
        Textarea = self._get_textarea_class()
        Checkbox = self._get_checkbox_class()

        if self.window is not None and self.menu is not None:
            try:
                self.window.remove_widget(self.menu)
            except Exception as exc:
                log.warning("_build_menu: failed to remove old menu widget: %s", exc)

        if SimpleMenu is not None:
            self.menu = SimpleMenu("menu")
            try:
                self.menu.set_comparator(
                    SimpleMenu.itemComparatorWeightAlpha
                    if hasattr(SimpleMenu, "itemComparatorWeightAlpha")
                    else None
                )
            except Exception as exc:
                log.warning("_build_menu: failed to set menu comparator: %s", exc)

            if Textarea is not None:
                try:
                    self.menu.set_header_widget(
                        Textarea("help_text", self.string("APPLET_WARN"))
                    )
                except Exception as exc:
                    log.warning(
                        "_build_menu: failed to set warning header widget: %s", exc
                    )

        self.toremove = {}
        self.todownload = {}
        self.inrepos = {}

        installed = self.get_settings() or {}
        mgr = self._get_applet_manager()

        if data is not None and isinstance(data, dict):
            item_loop = data.get("item_loop", [])
            if isinstance(item_loop, list):
                for entry in item_loop:
                    if not isinstance(entry, dict):
                        continue

                    # Resolve relative URLs
                    if entry.get("relurl") and server is not None:
                        ip, port = self._get_server_ip_port(server)
                        if ip:
                            entry["url"] = f"http://{ip}:{port}{entry['relurl']}"

                    name = entry.get("name", "")
                    self.inrepos[name] = 1

                    status: Optional[str] = None
                    if name in installed and isinstance(installed.get(name), str):
                        has_applet = False
                        if mgr is not None and hasattr(mgr, "has_applet"):
                            has_applet = mgr.has_applet(name)
                        elif mgr is not None and hasattr(mgr, "hasApplet"):
                            has_applet = mgr.hasApplet(name)

                        if not has_applet:
                            if self.reinstall is None:
                                self.reinstall = {}
                            self.reinstall[name] = {
                                "url": entry.get("url", ""),
                                "ver": entry.get("version", ""),
                                "sha": entry.get("sha", ""),
                            }
                            status = "REINSTALL"
                        else:
                            if entry.get("version") == installed[name]:
                                status = "INSTALLED"
                            else:
                                status = "UPDATES"
                                if self.updateall is None:
                                    self.updateall = {}
                                self.updateall[name] = {
                                    "url": entry.get("url", ""),
                                    "ver": entry.get("version", ""),
                                    "sha": entry.get("sha", ""),
                                }

                    title_text = entry.get("title", name)
                    if status:
                        status_str = str(self.string(status))
                        title_text = f"{title_text} ({status_str})"

                    if self.menu is not None:
                        # Capture loop variables
                        _entry = entry
                        _status = status or "INSTALL"
                        self.menu.add_item(
                            {
                                "text": title_text,
                                "sound": "WINDOWSHOW",
                                "callback": lambda ev=None, mi=None, e=_entry, s=_status: (
                                    self._repo_entry(mi, e, s)
                                ),
                                "weight": 2,
                            }
                        )

        # If called from meta at restart in auto mode
        if self.auto:
            if self.reinstall:
                self.toremove = dict(self.reinstall)
                self.todownload = dict(self.reinstall)
                self._action()
            if self.popup is not None:
                try:
                    self.popup.hide()
                except Exception as exc:
                    log.warning(
                        "_build_menu: failed to hide popup in auto mode: %s", exc
                    )
            return

        # Show the window
        if self.window is not None and self.menu is not None:
            self.window.add_widget(self.menu)

        # Add "Reinstall All" if needed
        if self.reinstall and self.menu is not None:
            self.menu.add_item(
                {
                    "text": str(self.string("REINSTALL_ALL")),
                    "sound": "WINDOWSHOW",
                    "callback": lambda ev=None, mi=None: self._do_reinstall_all(),
                    "weight": 1,
                }
            )

        # Add "Update All" if needed
        if self.updateall and self.menu is not None:
            count = len(self.updateall)
            self.menu.add_item(
                {
                    "text": f"{self.string('UPDATE_ALL')} ({count})",
                    "sound": "WINDOWSHOW",
                    "callback": lambda ev=None, mi=None: self._do_update_all(),
                    "weight": 1,
                }
            )

        # Add non-repo installed applets
        if mgr is not None:
            for name, ver in installed.items():
                if name.startswith("_"):
                    # Skip internal settings keys like _AUTOUP, _LASTVER
                    continue
                if not isinstance(ver, str):
                    continue
                has_applet = False
                if hasattr(mgr, "has_applet"):
                    has_applet = mgr.has_applet(name)
                elif hasattr(mgr, "hasApplet"):
                    has_applet = mgr.hasApplet(name)

                if has_applet and name not in self.inrepos:
                    _name = name
                    _ver = ver
                    if self.menu is not None:
                        self.menu.add_item(
                            {
                                "text": name,
                                "sound": "WINDOWSHOW",
                                "callback": lambda ev=None, mi=None, n=_name, v=_ver: (
                                    self._non_repo_entry(mi, n, v)
                                ),
                                "weight": 2,
                            }
                        )

        # Add "no applets found" if empty
        if self.menu is not None:
            num_items = 0
            if hasattr(self.menu, "numItems"):
                num_items = self.menu.numItems()
            elif hasattr(self.menu, "num_items"):
                num_items = self.menu.num_items()
            elif hasattr(self.menu, "items"):
                num_items = len(self.menu.items)

            if num_items == 0:
                self.menu.add_item(
                    {
                        "text": str(self.string("NONE_FOUND")),
                        "iconStyle": "item_no_arrow",
                        "weight": 2,
                    }
                )

        # Add auto-update checkbox
        if self.menu is not None and Checkbox is not None:
            try:

                def _on_autoup(obj: Any = None, is_selected: bool = False) -> None:
                    settings = self.get_settings()
                    if settings is not None:
                        settings["_AUTOUP"] = is_selected
                        self.store_settings()

                self.menu.add_item(
                    {
                        "text": str(self.string("APPLET_AUTOUP")),
                        "style": "item_choice",
                        "check": Checkbox(
                            "checkbox",
                            _on_autoup,
                            bool((self.get_settings() or {}).get("_AUTOUP", False)),
                        ),
                        "weight": 4,
                    }
                )
            except Exception as exc:
                log.debug("Failed to add auto-update checkbox: %s", exc)

        # Show window and hide popup
        if self.window is not None:
            self.tie_and_show_window(self.window)
        if self.popup is not None:
            try:
                self.popup.hide()
            except Exception as exc:
                log.warning("_build_menu: failed to hide loading popup: %s", exc)

    # ------------------------------------------------------------------
    # Detail screens
    # ------------------------------------------------------------------

    def _repo_entry(self, menu_item: Any, entry: Dict[str, Any], status: str) -> Any:
        """Show detail screen for a repository applet.

        Offers install/update/remove options depending on status.
        """
        Window = self._get_window_class()
        SimpleMenu = self._get_simple_menu_class()
        Textarea = self._get_textarea_class()

        if Window is None or SimpleMenu is None:
            return None

        title = entry.get("title", entry.get("name", ""))
        window = Window("text_list", title)
        menu = SimpleMenu("menu")
        window.add_widget(menu)

        # Build description text
        desc = entry.get("desc", title)
        creator = entry.get("creator", "")
        email = entry.get("email", "")
        if creator and email:
            desc = f"{desc}\n{creator} ({email})"
        elif creator or email:
            desc = f"{desc}\n{creator or email}"

        if Textarea is not None:
            try:
                menu.set_header_widget(Textarea("help_text", desc))
            except Exception as exc:
                log.warning(
                    "_repo_entry: failed to set description header widget: %s", exc
                )

        name = entry.get("name", "")
        url = entry.get("url", "")
        version = entry.get("version", "")
        sha = entry.get("sha", "")

        items: List[Dict[str, Any]] = []

        if status == "UPDATES":
            items.append(
                {
                    "text": f"{self.string('UPDATE')} : {version}",
                    "sound": "WINDOWSHOW",
                    "callback": lambda ev=None, mi=None: self._do_action(
                        {name: 1},
                        {name: {"url": url, "ver": version, "sha": sha}},
                    ),
                }
            )

        if status in ("INSTALLED", "UPDATES"):
            current_ver = (self.get_settings() or {}).get(name, "")
            items.append(
                {
                    "text": f"{self.string('REMOVE')} : {current_ver}",
                    "sound": "WINDOWSHOW",
                    "callback": lambda ev=None, mi=None: self._do_action({name: 1}, {}),
                }
            )

        if status in ("INSTALL", "REINSTALL"):
            items.append(
                {
                    "text": f"{self.string(status)} : {version}",
                    "sound": "WINDOWSHOW",
                    "callback": lambda ev=None, mi=None: self._do_action(
                        {name: 1},
                        {name: {"url": url, "ver": version, "sha": sha}},
                    ),
                }
            )

        try:
            menu.set_items(items)
        except Exception:
            for item in items:
                menu.add_item(item)

        self.appletwindow = window
        self.tie_and_show_window(window)
        return window

    def _non_repo_entry(self, menu_item: Any, name: str, ver: str) -> Any:
        """Show detail screen for a non-repository installed applet.

        Only a "Remove" option is available.
        """
        Window = self._get_window_class()
        SimpleMenu = self._get_simple_menu_class()

        if Window is None or SimpleMenu is None:
            return None

        window = Window("text_list", name)
        menu = SimpleMenu("menu")
        window.add_widget(menu)

        menu.add_item(
            {
                "text": f"{self.string('REMOVE')} : {ver}",
                "sound": "WINDOWSHOW",
                "callback": lambda ev=None, mi=None: self._do_action({name: 1}, {}),
            }
        )

        self.appletwindow = window
        self.tie_and_show_window(window)
        return window

    # ------------------------------------------------------------------
    # Batch action helpers
    # ------------------------------------------------------------------

    def _do_reinstall_all(self) -> None:
        """Reinstall all applets that need reinstalling."""
        if self.reinstall:
            self.toremove = dict(self.reinstall)
            self.todownload = dict(self.reinstall)
            self._action()

    def _do_update_all(self) -> None:
        """Update all applets that have updates available."""
        if self.updateall:
            self.toremove = dict(self.updateall)
            self.todownload = dict(self.updateall)
            self._action()

    def _do_action(
        self,
        to_remove: Dict[str, Any],
        to_download: Dict[str, Any],
    ) -> None:
        """Set up removal/download dicts and trigger the action."""
        self.toremove = to_remove
        self.todownload = to_download
        self._action()

    # ------------------------------------------------------------------
    # Action — download/remove with progress popup
    # ------------------------------------------------------------------

    def _action(self) -> None:
        """Perform the download/removal action.

        Shows a progress popup with a connecting animation, then
        runs the removal and download steps.  In the Lua original
        this uses a Task for cooperative multitasking; here we run
        synchronously (or in a thread if Task is available).
        """
        Popup = self._get_popup_class()
        Icon = self._get_icon_class()
        Label = self._get_label_class()

        if Popup is not None:
            self.animatewindow = Popup("waiting_popup")
            if Icon is not None:
                self.animatewindow.add_widget(Icon("icon_connecting"))
            if Label is not None:
                self.animatelabel = Label("text", self.string("DOWNLOADING"))
                self.animatewindow.add_widget(self.animatelabel)
            try:
                self.animatewindow.show()
            except Exception as exc:
                log.warning("_action: failed to show progress popup: %s", exc)

        # Try to use a Task for background execution
        Task = self._get_task_class()
        if Task is not None:
            try:
                self.task = Task(
                    "applet download",
                    self,
                    lambda: self._run_action(),
                )
                self.task.addTask()
                return
            except Exception as exc:
                log.debug("Task creation failed, running synchronously: %s", exc)

        # Fallback: run synchronously
        self._run_action()

    def _run_action(self) -> None:
        """Execute the removal and download steps sequentially."""
        try:
            self._remove()
            self._download()
        except Exception as exc:
            log.warn("Action failed: %s", exc)
        finally:
            self._finished()

    # ------------------------------------------------------------------
    # Remove applets
    # ------------------------------------------------------------------

    def _remove(self) -> None:
        """Remove applet directories for all entries in ``self.toremove``."""
        for applet_name in self.toremove:
            applet_dir = os.path.join(self.appletdir, applet_name)
            self._remove_dir(applet_dir)

    @staticmethod
    def _remove_dir(dir_path: str) -> None:
        """Recursively remove a directory.

        Mirrors the Lua ``_removedir`` function.
        """
        path = Path(dir_path)
        if path.is_dir():
            log.info("removing: %s", dir_path)
            try:
                shutil.rmtree(dir_path)
            except Exception as exc:
                log.warn("Failed to remove directory %s: %s", dir_path, exc)
        else:
            log.info("ignoring non-directory: %s", dir_path)

    # ------------------------------------------------------------------
    # Download applets
    # ------------------------------------------------------------------

    def _download(self) -> None:
        """Download and extract each applet in ``self.todownload``.

        For each applet:
        1. If SHA1 is provided, download once to verify the checksum.
        2. Download again (or use the same data) and extract the zip.
        """
        for applet_name, applet_data in self.todownload.items():
            if not isinstance(applet_data, dict):
                continue

            url = applet_data.get("url", "")
            sha_expected = applet_data.get("sha", "")
            applet_dir = os.path.join(self.appletdir, applet_name)

            log.info(
                "downloading: %s to: %s sha1: %s",
                url,
                applet_dir,
                sha_expected or "(none)",
            )

            if not url:
                log.warn("No URL for applet %s — skipping", applet_name)
                continue

            # Ensure directory exists
            os.makedirs(applet_dir, exist_ok=True)

            try:
                raw_data = self._fetch_url(url)
            except Exception as exc:
                log.warn("Failed to download %s: %s", url, exc)
                continue

            if raw_data is None:
                log.warn("No data received for %s", url)
                continue

            # SHA1 verification
            if sha_expected:
                actual_sha = hashlib.sha1(raw_data).hexdigest()
                if actual_sha != sha_expected:
                    log.warn(
                        "SHA1 mismatch for %s: expected %s, got %s",
                        applet_name,
                        sha_expected,
                        actual_sha,
                    )
                    continue
                else:
                    log.info("SHA1 verified for %s", applet_name)

            # Extract zip
            try:
                self._extract_zip(raw_data, applet_dir)
            except Exception as exc:
                log.warn("Failed to extract %s: %s", applet_name, exc)

    @staticmethod
    def _fetch_url(url: str) -> Optional[bytes]:
        """Fetch the content of a URL and return it as bytes.

        Tries ``urllib.request`` (standard library).
        """
        try:
            import urllib.request

            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read()  # type: ignore[no-any-return]
        except Exception as exc:
            log.warn("urllib fetch failed for %s: %s", url, exc)
            return None

    @staticmethod
    def _extract_zip(data: bytes, target_dir: str) -> None:
        """Extract a zip archive from *data* into *target_dir*.

        Mirrors the Lua zipfilter-based extraction.
        """
        buf = io.BytesIO(data)
        try:
            with zipfile.ZipFile(buf, "r") as zf:
                for info in zf.infolist():
                    # Sanitize path to prevent directory traversal
                    name = info.filename
                    if name.startswith("/") or ".." in name:
                        log.warn("Skipping unsafe zip entry: %s", name)
                        continue

                    target_path = os.path.join(target_dir, name)

                    if info.is_dir():
                        log.info("creating directory: %s", target_path)
                        os.makedirs(target_path, exist_ok=True)
                    else:
                        log.info("extracting file: %s", target_path)
                        # Ensure parent directory exists
                        parent = os.path.dirname(target_path)
                        if parent:
                            os.makedirs(parent, exist_ok=True)
                        with open(target_path, "wb") as fh:
                            fh.write(zf.read(info.filename))
        except zipfile.BadZipFile as exc:
            log.warn("Bad zip file: %s", exc)
            raise

    # ------------------------------------------------------------------
    # Finished — persist settings, show restart message
    # ------------------------------------------------------------------

    def _finished(self) -> None:
        """Called when download/removal is complete.

        Updates persisted settings (removing entries for removed
        applets, adding version entries for downloaded applets),
        hides the progress popup, and shows a restart message.
        """
        settings = self.get_settings()
        if settings is None:
            settings = {}
            self._settings = settings

        # Remove entries for removed applets
        for applet_name in self.toremove:
            if applet_name in settings:
                del settings[applet_name]

        # Add entries for downloaded applets
        for applet_name, applet_data in self.todownload.items():
            if isinstance(applet_data, dict):
                settings[applet_name] = applet_data.get("ver", "")

        self.store_settings()

        # Hide the animation popup
        if self.animatewindow is not None:
            try:
                self.animatewindow.hide()
            except Exception as exc:
                log.warning("_finished: failed to hide animation popup: %s", exc)

        # Hide the applet detail window
        if self.appletwindow is not None:
            try:
                self.appletwindow.hide()
            except Exception as exc:
                log.warning("_finished: failed to hide applet detail window: %s", exc)

        # Replace menu with restart message
        Textarea = self._get_textarea_class()
        if self.window is not None and self.menu is not None:
            try:
                self.window.remove_widget(self.menu)
            except Exception as exc:
                log.warning("_finished: failed to remove menu widget: %s", exc)

            if Textarea is not None:
                try:
                    self.window.add_widget(
                        Textarea("help_text", self.string("RESTART_APP"))
                    )
                except Exception as exc:
                    log.warning(
                        "_finished: failed to add restart message widget: %s", exc
                    )

            # Add a listener to hide the window on any key press
            try:
                from jive.ui.constants import EVENT_ACTION, EVENT_KEY_PRESS

                self.window.add_listener(
                    EVENT_KEY_PRESS | EVENT_ACTION,
                    lambda *_a, **_kw: self.window.hide() if self.window else None,
                )
            except (ImportError, Exception) as exc:
                log.error(
                    "_finished: failed to add key-press listener for restart window: %s",
                    exc,
                    exc_info=True,
                )

    # ------------------------------------------------------------------
    # action alias used internally
    # ------------------------------------------------------------------

    action = _action

    # ------------------------------------------------------------------
    # Lua-compatible camelCase aliases
    # ------------------------------------------------------------------

    applet_installer_menu = appletInstallerMenu
    menu_sink = menuSink
    setup_date_time_settings = None  # Not applicable to this applet

    # ------------------------------------------------------------------
    # Helper: server utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _is_squeeze_network(server: Any) -> bool:
        """Check if a server is SqueezeNetwork."""
        if hasattr(server, "isSqueezeNetwork"):
            return bool(server.isSqueezeNetwork())
        if hasattr(server, "is_squeeze_network"):
            return bool(server.is_squeeze_network())
        return False

    @staticmethod
    def _get_server_ip_port(server: Any) -> Tuple[str, int]:
        """Get the IP and port from a server object."""
        if hasattr(server, "getIpPort"):
            try:
                return server.getIpPort()  # type: ignore[no-any-return]
            except Exception as exc:
                log.error(
                    "_get_server_ip_port: getIpPort() failed: %s", exc, exc_info=True
                )
        if hasattr(server, "get_ip_port"):
            try:
                return server.get_ip_port()  # type: ignore[no-any-return]
            except Exception as exc:
                log.error(
                    "_get_server_ip_port: get_ip_port() failed: %s", exc, exc_info=True
                )
        if hasattr(server, "ip") and hasattr(server, "port"):
            return (str(server.ip), int(server.port))
        return ("", 0)

    # ------------------------------------------------------------------
    # Version helper
    # ------------------------------------------------------------------

    @staticmethod
    def _get_jive_version_string() -> str:
        """Return the current JIVE_VERSION string."""
        try:
            from jive.ui.constants import JIVE_VERSION  # type: ignore[attr-defined]

            return str(JIVE_VERSION)
        except (ImportError, AttributeError) as exc:
            log.debug(
                "_get_jive_version_string: JIVE_VERSION not in ui.constants: %s", exc
            )
        try:
            import jive

            ver = getattr(jive, "JIVE_VERSION", None)
            if ver is not None:
                return str(ver)
        except ImportError as exc:
            log.debug("_get_jive_version_string: jive module not available: %s", exc)
        return _FALLBACK_VERSION

    # ------------------------------------------------------------------
    # Lazy UI class imports (avoid circular dependencies)
    # ------------------------------------------------------------------

    @staticmethod
    def _get_window_class() -> Any:
        try:
            from jive.ui.window import Window

            return Window
        except ImportError:
            return None

    @staticmethod
    def _get_simple_menu_class() -> Any:
        try:
            from jive.ui.simplemenu import SimpleMenu

            return SimpleMenu
        except ImportError as exc:
            log.debug(
                "_get_simple_menu_class: jive.ui.simplemenu not available: %s", exc
            )
        try:
            from jive.ui.simple_menu import (
                SimpleMenu,  # type: ignore[import-not-found, no-redef]
            )

            return SimpleMenu
        except ImportError as exc:
            log.debug(
                "_get_simple_menu_class: jive.ui.simple_menu not available: %s", exc
            )
            return None

    @staticmethod
    def _get_popup_class() -> Any:
        try:
            from jive.ui.popup import Popup

            return Popup
        except ImportError:
            return None

    @staticmethod
    def _get_icon_class() -> Any:
        try:
            from jive.ui.icon import Icon

            return Icon
        except ImportError:
            return None

    @staticmethod
    def _get_label_class() -> Any:
        try:
            from jive.ui.label import Label

            return Label
        except ImportError:
            return None

    @staticmethod
    def _get_textarea_class() -> Any:
        try:
            from jive.ui.textarea import Textarea

            return Textarea
        except ImportError:
            return None

    @staticmethod
    def _get_checkbox_class() -> Any:
        try:
            from jive.ui.checkbox import Checkbox

            return Checkbox
        except ImportError:
            return None

    @staticmethod
    def _get_timer_class() -> Any:
        try:
            from jive.ui.timer import Timer

            return Timer
        except ImportError:
            return None

    @staticmethod
    def _get_task_class() -> Any:
        try:
            from jive.ui.task import Task

            return Task
        except ImportError:
            return None

    @staticmethod
    def _get_system() -> Any:
        """Get the System *instance* from AppletManager.

        In the Lua original, ``System`` is a module-level singleton.
        In Python, the single ``System`` instance is owned by
        ``AppletManager`` (which receives it from ``JiveMain``).
        """
        try:
            from jive.applet_manager import applet_manager as _mgr

            if _mgr is not None and hasattr(_mgr, "system") and _mgr.system is not None:
                return _mgr.system
        except (ImportError, AttributeError):
            pass

        # Fallback: try JiveMain directly
        try:
            from jive.jive_main import jive_main as _jm

            if _jm is not None and hasattr(_jm, "_system"):
                return _jm._system
        except (ImportError, AttributeError):
            pass

        return None

    @staticmethod
    def _get_applet_manager() -> Any:
        try:
            from jive.applet_manager import applet_manager

            return applet_manager
        except (ImportError, AttributeError):
            return None
