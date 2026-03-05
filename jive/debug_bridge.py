"""
Runtime diagnostics for Sordino.

Automatically detects common porting bugs at runtime by monkey-patching
key functions and classes. All diagnostics are written to a log file
(~/.jivelite/debug.log) AND to the standard logger.

Enable:
    JIVELITE_DEBUG=1 python jive/main.py

Or programmatically:
    from jive.debug_bridge import install
    install()

This module is designed to be **zero-overhead when disabled**. It does
nothing at import time — all patches are applied in install().

Design principles:
    1. Non-invasive: Only monkey-patches, never modifies source files
    2. Reversible: uninstall() removes all patches
    3. Safe: Catches its own exceptions so it never breaks the app
    4. Minimal overhead: Guards around expensive operations
    5. Compatible with Task 05: If Task 05 adds logging to except blocks,
       debug_bridge detects the same issues — they complement each other
"""

from __future__ import annotations

import collections
import functools
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict

# ---------------------------------------------------------------------------
# Module state
# ---------------------------------------------------------------------------
_installed = False
_originals: Dict[str, Any] = {}
_debug_log = logging.getLogger("jivelite.debug_bridge")
_log_file_path = ""


# ---------------------------------------------------------------------------
# Logger setup
# ---------------------------------------------------------------------------


def _setup_debug_logger() -> None:
    """Configure the debug logger to write to ~/.jivelite/debug.log."""
    global _log_file_path

    debug_dir = Path.home() / ".jivelite"
    debug_dir.mkdir(parents=True, exist_ok=True)
    _log_file_path = str(debug_dir / "debug.log")

    handler = logging.FileHandler(_log_file_path, mode="a", encoding="utf-8")
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)-8s %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )

    _debug_log.addHandler(handler)
    _debug_log.setLevel(logging.DEBUG)

    # Also add a stderr handler for ERROR+ so critical issues are visible
    stderr_handler = logging.StreamHandler()
    stderr_handler.setLevel(logging.ERROR)
    stderr_handler.setFormatter(logging.Formatter("DEBUG_BRIDGE %(levelname)s: %(message)s"))
    _debug_log.addHandler(stderr_handler)


# ---------------------------------------------------------------------------
# 1.1 Notification Monitor
# ---------------------------------------------------------------------------


def _patched_notify(original_notify: Any) -> Any:
    """Wrapper around NetworkThread.notify() with full diagnostics."""

    @functools.wraps(original_notify)
    def wrapper(self: Any, event: str, *args: Any) -> None:
        method_name = f"notify_{event}"
        t0 = time.perf_counter()

        subscribers_called = 0
        subscribers_missing = 0
        subscribers_failed = 0

        for _obj_id, obj in list(self._subscribers.items()):
            method = getattr(obj, method_name, None)
            sub_name = type(obj).__name__

            if method is None:
                _debug_log.debug("NOTIFY_MISS: %s has no %s handler", sub_name, method_name)
                subscribers_missing += 1
                continue

            if not callable(method):
                _debug_log.warning(
                    "NOTIFY_NOT_CALLABLE: %s.%s is %r (not callable)",
                    sub_name,
                    method_name,
                    type(method).__name__,
                )
                continue

            try:
                method(*args)
                subscribers_called += 1
            except TypeError as exc:
                import inspect

                try:
                    sig = inspect.signature(method)
                    expected_params: int | str = len(
                        [
                            p
                            for p in sig.parameters.values()
                            if p.default is inspect.Parameter.empty and p.name != "self"
                        ]
                    )
                except (ValueError, TypeError):
                    expected_params = "?"

                _debug_log.error(
                    "NOTIFY_SIGNATURE_MISMATCH: %s.%s — "
                    "got %d args (%s) but handler expects %s params. "
                    "TypeError: %s",
                    sub_name,
                    method_name,
                    len(args),
                    ", ".join(type(a).__name__ for a in args),
                    expected_params,
                    exc,
                    exc_info=True,
                )
                subscribers_failed += 1

            except Exception as exc:
                _debug_log.error(
                    "NOTIFY_HANDLER_ERROR: %s.%s raised %s: %s",
                    sub_name,
                    method_name,
                    type(exc).__name__,
                    exc,
                    exc_info=True,
                )
                subscribers_failed += 1

        elapsed_ms = (time.perf_counter() - t0) * 1000

        if elapsed_ms > 5.0:
            _debug_log.warning(
                "NOTIFY_SLOW: %s took %.1f ms (called=%d, missing=%d, failed=%d)",
                method_name,
                elapsed_ms,
                subscribers_called,
                subscribers_missing,
                subscribers_failed,
            )

        if subscribers_failed > 0:
            _debug_log.error(
                "NOTIFY_SUMMARY: %s — %d/%d subscribers FAILED",
                method_name,
                subscribers_failed,
                subscribers_called + subscribers_failed,
            )

    return wrapper


# ---------------------------------------------------------------------------
# 1.2 Subscription Audit
# ---------------------------------------------------------------------------


def audit_subscriptions() -> None:
    """
    Audit which applets are subscribed and which have orphaned notify_* handlers.

    Call this AFTER all applets have been configured (e.g., via deferred Timer).
    """
    try:
        from jive.jive_main import jive_main as _jm

        if _jm is None or not hasattr(_jm, "jnt"):
            _debug_log.warning("AUDIT_SKIP: jive_main or jnt not available")
            return

        jnt = _jm.jnt
        if jnt is None:
            _debug_log.warning("AUDIT_SKIP: jnt is None")
            return

        # Get all subscribers
        subscribers = set()
        if hasattr(jnt, "_subscribers"):
            for _obj_id, obj in jnt._subscribers.items():
                subscribers.add(id(obj))

        _debug_log.info("AUDIT: %d active subscribers", len(subscribers))

        # Now check all loaded applets
        mgr = getattr(_jm, "_applet_manager", None)
        if mgr is None:
            return

        applet_db = getattr(mgr, "_applets_db", {})

        for name, entry in applet_db.items():
            applet_instance = entry.get("instance")
            if applet_instance is None:
                continue

            # Find all notify_* methods on this applet
            notify_methods = [
                m
                for m in dir(applet_instance)
                if m.startswith("notify_") and callable(getattr(applet_instance, m, None))
            ]

            if not notify_methods:
                continue

            is_subscribed = id(applet_instance) in subscribers

            if notify_methods and not is_subscribed:
                _debug_log.error(
                    "AUDIT_NOT_SUBSCRIBED: %s has %d notify_* handlers "
                    "(%s) but is NOT subscribed! "
                    "Likely broken _get_jnt() — see Pattern A in INSTRUCTION.md",
                    name,
                    len(notify_methods),
                    ", ".join(sorted(notify_methods)[:5]),
                )
            else:
                _debug_log.info(
                    "AUDIT_OK: %s subscribed with %d handlers",
                    name,
                    len(notify_methods),
                )
    except Exception as exc:
        _debug_log.error("AUDIT_ERROR: subscription audit failed: %s", exc, exc_info=True)


# ---------------------------------------------------------------------------
# 1.3 Exception Tracker
# ---------------------------------------------------------------------------


def _install_excepthook() -> Any:
    """Install a global exception hook that logs to debug.log."""
    _original_hook = sys.excepthook

    def _debug_excepthook(exc_type: type, exc_value: BaseException, exc_tb: Any) -> None:
        if exc_type is KeyboardInterrupt:
            _original_hook(exc_type, exc_value, exc_tb)
            return
        _debug_log.critical(
            "UNHANDLED_EXCEPTION: %s: %s",
            exc_type.__name__,
            exc_value,
            exc_info=(exc_type, exc_value, exc_tb),
        )
        _original_hook(exc_type, exc_value, exc_tb)

    sys.excepthook = _debug_excepthook
    return _original_hook


# ---------------------------------------------------------------------------
# 1.4 Style Type Checker
# ---------------------------------------------------------------------------


def _patch_style_functions() -> Dict[str, Any]:
    """Patch style_* functions to log type mismatches."""
    from jive.ui import style as _style_mod

    _orig_tile = _style_mod.style_tile
    _orig_image = _style_mod.style_image
    _orig_font = _style_mod.style_font

    @functools.wraps(_orig_tile)
    def _checked_style_tile(widget: Any, key: str, default: Any = None) -> Any:
        val = _orig_tile(widget, key, default)
        if val is not None and val is not default:
            if not hasattr(val, "blit"):
                _debug_log.warning(
                    "STYLE_TYPE: style_tile(%s, %r) returned %s (expected Tile with .blit)",
                    type(widget).__name__,
                    key,
                    type(val).__name__,
                )
        return val

    @functools.wraps(_orig_image)
    def _checked_style_image(widget: Any, key: str, default: Any = None) -> Any:
        val = _orig_image(widget, key, default)
        if val is not None and val is not default:
            if not hasattr(val, "get_size"):
                _debug_log.warning(
                    "STYLE_TYPE: style_image(%s, %r) returned %s (expected Surface with .get_size)",
                    type(widget).__name__,
                    key,
                    type(val).__name__,
                )
        return val

    @functools.wraps(_orig_font)
    def _checked_style_font(widget: Any, key: str = "font") -> Any:
        val = _orig_font(widget, key)
        if val is not None:
            if isinstance(val, bool):
                _debug_log.warning(
                    "STYLE_TYPE: style_font(%s, %r) returned bool=%s "
                    "(likely 'font = False' in skin — same pattern as "
                    "bgImg = False)",
                    type(widget).__name__,
                    key,
                    val,
                )
            elif not hasattr(val, "render") and not hasattr(val, "size"):
                _debug_log.warning(
                    "STYLE_TYPE: style_font(%s, %r) returned %s (expected Font)",
                    type(widget).__name__,
                    key,
                    type(val).__name__,
                )
        return val

    _style_mod.style_tile = _checked_style_tile
    _style_mod.style_image = _checked_style_image
    _style_mod.style_font = _checked_style_font

    return {
        "style_tile": _orig_tile,
        "style_image": _orig_image,
        "style_font": _orig_font,
    }


# ---------------------------------------------------------------------------
# 1.5 Settings Audit
# ---------------------------------------------------------------------------


def _patch_settings_functions() -> Dict[str, Any]:
    """Patch AppletManager._store_settings and _load_settings for auditing."""
    from jive.applet_manager import AppletManager

    _orig_store = AppletManager._store_settings
    _orig_load = AppletManager._load_settings

    @functools.wraps(_orig_store)
    def _audited_store(self: Any, entry: Any) -> None:
        if isinstance(entry, str):
            _debug_log.warning(
                "SETTINGS_STRING_ARG: _store_settings() called with "
                "string %r instead of dict (Pattern G)",
                entry,
            )
        try:
            _orig_store(self, entry)
            # Log success
            if isinstance(entry, dict):
                name = entry.get("applet_name", "?")
            else:
                name = entry
            _debug_log.info("SETTINGS_STORE: %s — saved", name)
        except Exception as exc:
            _debug_log.error(
                "SETTINGS_STORE_ERROR: _store_settings(%r) failed: %s",
                entry if isinstance(entry, str) else entry.get("applet_name", "?"),
                exc,
                exc_info=True,
            )
            raise

    @functools.wraps(_orig_load)
    def _audited_load(self: Any, entry: Dict[str, Any]) -> None:
        try:
            _orig_load(self, entry)
            name = entry.get("applet_name", "?")
            settings = entry.get("settings")
            if settings is not None:
                keys = list(settings.keys()) if isinstance(settings, dict) else []
                _debug_log.info(
                    "SETTINGS_LOAD: %s — %d keys loaded (%s)",
                    name,
                    len(keys),
                    ", ".join(keys[:5]) + ("..." if len(keys) > 5 else ""),
                )
            else:
                _debug_log.debug(
                    "SETTINGS_LOAD: %s — no settings file found",
                    name,
                )
        except Exception as exc:
            _debug_log.error(
                "SETTINGS_LOAD_ERROR: _load_settings(%r) failed: %s",
                entry.get("applet_name", "?"),
                exc,
                exc_info=True,
            )
            raise

    AppletManager._store_settings = _audited_store  # type: ignore[method-assign]
    AppletManager._load_settings = _audited_load  # type: ignore[method-assign]

    return {
        "_store_settings": _orig_store,
        "_load_settings": _orig_load,
    }


# ---------------------------------------------------------------------------
# 1.6 Performance Timer
# ---------------------------------------------------------------------------


def _patch_update_screen() -> Any:
    """Patch Framework.update_screen() with timing instrumentation."""
    from jive.ui.framework import Framework

    _orig = Framework.update_screen

    _frame_times: collections.deque[float] = collections.deque(maxlen=100)
    _slow_frame_count = 0

    @functools.wraps(_orig)
    def _timed_update_screen(self: Any) -> None:
        nonlocal _slow_frame_count
        t0 = time.perf_counter()
        _orig(self)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        _frame_times.append(elapsed_ms)

        if elapsed_ms > 33.0:
            _slow_frame_count += 1
            if _slow_frame_count <= 10 or _slow_frame_count % 100 == 0:
                avg = sum(_frame_times) / len(_frame_times)
                _debug_log.warning(
                    "PERF_SLOW_FRAME: %.1f ms (avg: %.1f ms, slow frames: %d, target: <=33ms)",
                    elapsed_ms,
                    avg,
                    _slow_frame_count,
                )

    Framework.update_screen = _timed_update_screen  # type: ignore[method-assign]
    return _orig


# ---------------------------------------------------------------------------
# 1.7 install / uninstall / auto_install
# ---------------------------------------------------------------------------


def install() -> None:
    """
    Install all debug diagnostics.

    Safe to call multiple times — second call is a no-op.
    """
    global _installed
    if _installed:
        return

    _setup_debug_logger()

    _debug_log.info("=" * 60)
    _debug_log.info("DEBUG BRIDGE INSTALLED — Sordino runtime diagnostics")
    _debug_log.info("Log file: %s", _log_file_path)
    _debug_log.info("=" * 60)

    # 1. Exception hook
    _originals["excepthook"] = _install_excepthook()
    _debug_log.info("Patched: sys.excepthook")

    # 2. Notification monitor
    try:
        from jive.net.network_thread import NetworkThread

        _originals["notify"] = NetworkThread.notify
        NetworkThread.notify = _patched_notify(NetworkThread.notify)  # type: ignore[method-assign]
        _debug_log.info("Patched: NetworkThread.notify()")
    except ImportError:
        _debug_log.warning("Could not patch NetworkThread.notify — module not loaded")

    # 3. Style type checker
    try:
        style_originals = _patch_style_functions()
        _originals.update(style_originals)
        _debug_log.info("Patched: style_tile, style_image, style_font")
    except ImportError:
        _debug_log.warning("Could not patch style functions — module not loaded")

    # 4. Settings audit
    try:
        settings_originals = _patch_settings_functions()
        _originals.update(settings_originals)
        _debug_log.info("Patched: _store_settings, _load_settings")
    except ImportError:
        _debug_log.warning("Could not patch settings functions — module not loaded")

    # 5. Performance timer
    try:
        _originals["update_screen"] = _patch_update_screen()
        _debug_log.info("Patched: Framework.update_screen()")
    except ImportError:
        _debug_log.warning("Could not patch Framework.update_screen — module not loaded")

    # 6. Subscription audit (deferred — run after applets are loaded)
    try:
        from jive.ui.timer import Timer

        Timer(2000, audit_subscriptions, once=True).start()
        _debug_log.info("Scheduled: subscription audit in 2 seconds")
    except ImportError:
        _debug_log.info("Timer not available — run audit_subscriptions() manually")

    _installed = True


def uninstall() -> None:
    """Remove all debug patches and restore originals."""
    global _installed
    if not _installed:
        return

    # Restore notification monitor
    if "notify" in _originals:
        try:
            from jive.net.network_thread import NetworkThread

            NetworkThread.notify = _originals["notify"]  # type: ignore[method-assign]
        except ImportError:
            _debug_log.debug("NetworkThread not available for restore")

    # Restore excepthook
    if "excepthook" in _originals:
        sys.excepthook = _originals["excepthook"]

    # Restore performance timer
    if "update_screen" in _originals:
        try:
            from jive.ui.framework import Framework

            Framework.update_screen = _originals["update_screen"]  # type: ignore[method-assign]
        except ImportError:
            _debug_log.debug("Framework not available for restore")

    # Restore style functions
    if "style_tile" in _originals:
        try:
            from jive.ui import style as _style_mod

            _style_mod.style_tile = _originals["style_tile"]
            _style_mod.style_image = _originals["style_image"]
            _style_mod.style_font = _originals["style_font"]
        except ImportError:
            _debug_log.debug("style module not available for restore")

    # Restore settings functions
    if "_store_settings" in _originals:
        try:
            from jive.applet_manager import AppletManager

            AppletManager._store_settings = _originals["_store_settings"]  # type: ignore[method-assign]
            AppletManager._load_settings = _originals["_load_settings"]  # type: ignore[method-assign]
        except ImportError:
            _debug_log.debug("AppletManager not available for restore")

    _originals.clear()
    _installed = False
    _debug_log.info("DEBUG BRIDGE UNINSTALLED — all patches removed")


def auto_install() -> None:
    """Install if JIVELITE_DEBUG=1 environment variable is set."""
    if os.environ.get("JIVELITE_DEBUG", "").strip() in ("1", "true", "yes", "on"):
        install()
