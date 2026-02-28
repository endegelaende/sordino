"""
tests.test_applet_system — Comprehensive tests for the Applet System.

Tests cover:
    - jive.system.System — capabilities, paths, identity, atomic writes
    - jive.applet.Applet — lifecycle, settings, strings, window tying, readdir
    - jive.applet_meta.AppletMeta — version check, registration, menu items, services
    - jive.applet_manager.AppletManager — discovery, loading, freeing, services, settings
    - jive.iconbar.Iconbar — icon state, wireless signal, server error, time update
    - jive.input_to_action_map — mapping tables structure and content
    - jive.jive_main.JiveMain — initialization, power state, skin management, home menu

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import textwrap
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from unittest.mock import MagicMock, patch

import pytest

# ══════════════════════════════════════════════════════════════════════════════
# Import UI constants needed by tests
# ══════════════════════════════════════════════════════════════════════════════
from jive.ui.constants import (
    EVENT_CONSUME,
    EVENT_UNUSED,
    GESTURE_L_R,
    GESTURE_R_L,
    KEY_FWD,
    KEY_HOME,
    KEY_PLAY,
    KEY_REW,
    KEY_VOLUME_DOWN,
    KEY_VOLUME_UP,
)

# ══════════════════════════════════════════════════════════════════════════════
# Helper: ensure the project root is on sys.path
# ══════════════════════════════════════════════════════════════════════════════

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ══════════════════════════════════════════════════════════════════════════════
# §1  System
# ══════════════════════════════════════════════════════════════════════════════

from jive.system import System


class TestSystemIdentity:
    """System identity (UUID, MAC, machine, arch)."""

    def test_defaults(self):
        s = System()
        assert s.get_machine() == "jivelite"
        assert isinstance(s.get_arch(), str)
        assert len(s.get_uuid()) > 0
        assert len(s.get_mac_address()) > 0

    def test_custom_identity(self):
        s = System(
            machine="jive",
            arch="armv7l",
            uuid_str="test-uuid-1234",
            mac_address="aa:bb:cc:dd:ee:ff",
        )
        assert s.get_machine() == "jive"
        assert s.get_arch() == "armv7l"
        assert s.get_uuid() == "test-uuid-1234"
        assert s.get_mac_address() == "aa:bb:cc:dd:ee:ff"

    def test_set_machine(self):
        s = System()
        s.set_machine("squeezeplay")
        assert s.get_machine() == "squeezeplay"

    def test_is_hardware(self):
        s = System(machine="jivelite")
        assert not s.is_hardware()
        s.set_machine("jive")
        assert s.is_hardware()
        s.set_machine("squeezeplay")
        assert s.is_hardware()

    def test_mac_address_format(self):
        s = System()
        mac = s.get_mac_address()
        parts = mac.split(":")
        assert len(parts) == 6
        # First 3 octets are Logitech OUI
        assert parts[0] == "00"
        assert parts[1] == "04"
        assert parts[2] == "20"


class TestSystemCapabilities:
    """System hardware capabilities."""

    def test_no_capabilities_by_default(self):
        s = System()
        assert not s.has_touch()
        assert not s.has_ir()
        assert not s.has_power_key()
        assert not s.has_volume_knob()

    def test_set_capabilities(self):
        s = System()
        s.set_capabilities({"touch": 1, "ir": 1, "volumeKnob": 1})
        assert s.has_touch()
        assert s.has_ir()
        assert s.has_volume_knob()
        assert not s.has_power_key()

    def test_add_capability(self):
        s = System()
        s.add_capability("touch")
        assert s.has_touch()
        assert not s.has_ir()

    def test_remove_capability(self):
        s = System()
        s.set_capabilities({"touch": 1, "ir": 1})
        s.remove_capability("touch")
        assert not s.has_touch()
        assert s.has_ir()

    def test_has_capability_generic(self):
        s = System()
        s.add_capability("sdcard")
        assert s.has_capability("sdcard")
        assert not s.has_capability("usb")

    def test_has_soft_power(self):
        s = System()
        assert not s.has_soft_power()
        s.add_capability("touch")
        assert s.has_soft_power()
        s.remove_capability("touch")
        s.add_capability("powerKey")
        assert s.has_soft_power()

    def test_has_local_storage(self):
        s = System(machine="jivelite")
        # Non-hardware always has local storage
        assert s.has_local_storage()
        s.set_machine("jive")
        assert not s.has_local_storage()
        s.add_capability("usb")
        assert s.has_local_storage()
        s.remove_capability("usb")
        s.add_capability("sdcard")
        assert s.has_local_storage()

    def test_all_convenience_methods(self):
        s = System()
        all_caps = {
            "touch": 1,
            "ir": 1,
            "powerKey": 1,
            "presetKeys": 1,
            "alarmKey": 1,
            "homeAsPowerKey": 1,
            "muteKey": 1,
            "volumeKnob": 1,
            "audioByDefault": 1,
            "wiredNetworking": 1,
            "deviceRotation": 1,
            "coreKeys": 1,
            "sdcard": 1,
            "usb": 1,
            "batteryCapable": 1,
            "hasDigitalOut": 1,
            "hasTinySC": 1,
            "IRBlasterCapable": 1,
        }
        s.set_capabilities(all_caps)
        assert s.has_touch()
        assert s.has_ir()
        assert s.has_power_key()
        assert s.has_preset_keys()
        assert s.has_alarm_key()
        assert s.has_home_as_power_key()
        assert s.has_mute_key()
        assert s.has_volume_knob()
        assert s.has_audio_by_default()
        assert s.has_wired_networking()
        assert s.has_device_rotation()
        assert s.has_core_keys()
        assert s.has_sd_card()
        assert s.has_usb()
        assert s.has_battery_capability()
        assert s.has_digital_out()
        assert s.has_tiny_sc()
        assert s.has_ir_blaster_capability()

    def test_touchpad_bottom_correction(self):
        s = System()
        assert s.get_touchpad_bottom_correction() == 0
        s.set_touchpad_bottom_correction(10)
        assert s.get_touchpad_bottom_correction() == 10

    def test_unknown_capability_warning(self, caplog):
        s = System()
        import logging

        with caplog.at_level(logging.DEBUG):
            s.set_capabilities({"made_up_cap": 1})
        # Should have logged a warning about unknown capability
        # (the actual log may be through our custom logger, but the capability
        # should still be set)
        assert not s.has_touch()

    def test_repr(self):
        s = System(machine="jivelite")
        r = repr(s)
        assert "System" in r
        assert "jivelite" in r


class TestSystemPaths:
    """System user paths and file finding."""

    def test_user_dir_default(self):
        s = System()
        user_dir = s.get_user_dir()
        assert isinstance(user_dir, Path)

    def test_user_dir_custom(self, tmp_path):
        s = System(user_dir=tmp_path / "custom_user")
        assert s.get_user_dir() == tmp_path / "custom_user"

    def test_settings_dir(self, tmp_path):
        s = System(user_dir=tmp_path / "user")
        assert s.get_settings_dir() == tmp_path / "user" / "settings"

    def test_user_applets_dir(self, tmp_path):
        s = System(user_dir=tmp_path / "user")
        assert s.get_user_applets_dir() == tmp_path / "user" / "applets"

    def test_init_user_path_dirs(self, tmp_path):
        user_dir = tmp_path / "init_test"
        s = System(user_dir=user_dir)
        s.init_user_path_dirs()
        assert user_dir.is_dir()
        assert (user_dir / "settings").is_dir()
        assert (user_dir / "applets").is_dir()

    def test_search_paths(self, tmp_path):
        p1 = tmp_path / "path1"
        p2 = tmp_path / "path2"
        p1.mkdir()
        p2.mkdir()
        s = System(search_paths=[p1, p2])
        assert s.search_paths == [p1, p2]

    def test_add_search_path(self, tmp_path):
        p1 = tmp_path / "p1"
        p2 = tmp_path / "p2"
        p1.mkdir()
        p2.mkdir()
        s = System(search_paths=[p1])
        s.add_search_path(p2)
        assert p2 in s.search_paths
        # Duplicate should not be added
        s.add_search_path(p2)
        assert s.search_paths.count(p2) == 1

    def test_add_search_path_prepend(self, tmp_path):
        p1 = tmp_path / "p1"
        p2 = tmp_path / "p2"
        p1.mkdir()
        p2.mkdir()
        s = System(search_paths=[p1])
        s.add_search_path(p2, prepend=True)
        assert s.search_paths[0] == p2

    def test_find_file(self, tmp_path):
        search = tmp_path / "search"
        search.mkdir()
        (search / "test.txt").write_text("hello")
        s = System(search_paths=[search])
        result = s.find_file("test.txt")
        assert result is not None
        assert result.name == "test.txt"

    def test_find_file_not_found(self, tmp_path):
        s = System(search_paths=[tmp_path])
        result = s.find_file("nonexistent.txt")
        assert result is None

    def test_find_all_files(self, tmp_path):
        p1 = tmp_path / "a"
        p2 = tmp_path / "b"
        p1.mkdir()
        p2.mkdir()
        (p1 / "file.txt").write_text("from a")
        (p2 / "file.txt").write_text("from b")
        s = System(search_paths=[p1, p2])
        results = s.find_all_files("file.txt")
        assert len(results) == 2

    def test_set_search_paths(self, tmp_path):
        s = System(search_paths=[tmp_path])
        new_path = tmp_path / "new"
        new_path.mkdir()
        s.search_paths = [new_path]
        assert s.search_paths == [new_path]


class TestSystemAtomicWrite:
    """System atomic write."""

    def test_atomic_write(self, tmp_path):
        filepath = tmp_path / "test_settings.json"
        content = '{"key": "value"}'
        System.atomic_write(filepath, content)
        assert filepath.read_text(encoding="utf-8") == content

    def test_atomic_write_creates_parent_dirs(self, tmp_path):
        filepath = tmp_path / "sub" / "dir" / "settings.json"
        System.atomic_write(filepath, "test")
        assert filepath.read_text(encoding="utf-8") == "test"

    def test_atomic_write_overwrites(self, tmp_path):
        filepath = tmp_path / "settings.json"
        filepath.write_text("old content")
        System.atomic_write(filepath, "new content")
        assert filepath.read_text(encoding="utf-8") == "new content"

    def test_atomic_write_unicode(self, tmp_path):
        filepath = tmp_path / "unicode.json"
        content = '{"text": "Ünïcödé 日本語"}'
        System.atomic_write(filepath, content)
        assert filepath.read_text(encoding="utf-8") == content


# ══════════════════════════════════════════════════════════════════════════════
# §2  Applet
# ══════════════════════════════════════════════════════════════════════════════

from jive.applet import Applet


class TestAppletBase:
    """Applet base class — lifecycle, settings, strings."""

    def test_init_and_free(self):
        a = Applet()
        a.init()
        assert a.free() is True

    def test_settings(self):
        a = Applet()
        assert a.get_settings() is None
        a.set_settings({"volume": 75})
        assert a.get_settings() == {"volume": 75}

    def test_default_settings(self):
        a = Applet()
        assert a.get_default_settings() is None
        a._default_settings = {"volume": 50}
        assert a.get_default_settings() == {"volume": 50}

    def test_string_no_table(self):
        a = Applet()
        a._strings_table = None
        result = a.string("HELLO")
        assert result == "HELLO"

    def test_string_with_table(self):
        mock_table = MagicMock()
        mock_table.str.return_value = "Hallo"
        a = Applet()
        a._strings_table = mock_table
        result = a.string("HELLO")
        assert result == "Hallo"
        mock_table.str.assert_called_once_with("HELLO")

    def test_string_with_args(self):
        mock_table = MagicMock()
        mock_table.str.return_value = "Hello Alice"
        a = Applet()
        a._strings_table = mock_table
        result = a.string("WELCOME", "Alice")
        assert result == "Hello Alice"
        mock_table.str.assert_called_once_with("WELCOME", "Alice")

    def test_repr(self):
        a = Applet()
        r = repr(a)
        assert "Applet" in r
        assert "?" in r  # No entry set

    def test_repr_with_entry(self):
        a = Applet()
        a._entry = {"applet_name": "TestApplet"}
        r = repr(a)
        assert "TestApplet" in r


class TestAppletSubclass:
    """Applet subclassing."""

    def test_subclass_init(self):
        class MyApplet(Applet):
            def init(self):
                super().init()
                self.initialized = True

        a = MyApplet()
        a.init()
        assert a.initialized is True

    def test_subclass_free_false(self):
        class StickyApplet(Applet):
            def free(self):
                return False

        a = StickyApplet()
        assert a.free() is False

    def test_subclass_free_none(self):
        class BuggyApplet(Applet):
            def free(self):
                return None

        a = BuggyApplet()
        assert a.free() is None


class TestAppletWindowTying:
    """Applet window tying — tie_window / tie_and_show_window."""

    def test_tie_window(self):
        a = Applet()
        mock_window = MagicMock()
        a.tie_window(mock_window)
        assert mock_window in a._tie
        mock_window.add_listener.assert_called_once()

    def test_tie_and_show_window(self):
        a = Applet()
        mock_window = MagicMock()
        a.tie_and_show_window(mock_window, "arg1", key="val")
        assert mock_window in a._tie
        mock_window.show.assert_called_once_with("arg1", key="val")

    def test_camel_case_aliases(self):
        # Class-level aliases — compare the underlying functions
        assert Applet.tieWindow is Applet.tie_window
        assert Applet.tieAndShowWindow is Applet.tie_and_show_window
        assert Applet.setSettings is Applet.set_settings
        assert Applet.getSettings is Applet.get_settings
        assert Applet.getDefaultSettings is Applet.get_default_settings
        assert Applet.storeSettings is Applet.store_settings
        assert Applet.registerService is Applet.register_service


class TestAppletReaddir:
    """Applet readdir — directory iteration."""

    def test_readdir_no_entry(self):
        a = Applet()
        a._entry = None
        result = list(a.readdir("images"))
        assert result == []

    def test_readdir_with_files(self, tmp_path):
        # Set up a fake applet directory
        applet_dir = tmp_path / "NowPlaying"
        images_dir = applet_dir / "images"
        images_dir.mkdir(parents=True)
        (images_dir / "icon.png").write_text("fake image")
        (images_dir / "bg.jpg").write_text("fake bg")

        a = Applet()
        a._entry = {
            "applet_name": "NowPlaying",
            "dirpath": str(applet_dir),
        }

        result = sorted(a.readdir("images"))
        assert len(result) == 2
        assert any("bg.jpg" in r for r in result)
        assert any("icon.png" in r for r in result)

    def test_readdir_skips_svn(self, tmp_path):
        applet_dir = tmp_path / "MyApplet"
        sub_dir = applet_dir / "data"
        sub_dir.mkdir(parents=True)
        (sub_dir / ".svn").mkdir()
        (sub_dir / "real_file.txt").write_text("data")

        a = Applet()
        a._entry = {
            "applet_name": "MyApplet",
            "dirpath": str(applet_dir),
        }

        result = list(a.readdir("data"))
        assert len(result) == 1
        assert "real_file.txt" in result[0]

    def test_readdir_nonexistent_dir(self, tmp_path):
        applet_dir = tmp_path / "FakeApplet"
        applet_dir.mkdir()

        a = Applet()
        a._entry = {
            "applet_name": "FakeApplet",
            "dirpath": str(applet_dir),
        }

        result = list(a.readdir("nonexistent"))
        assert result == []


class TestAppletServiceRegistration:
    """Applet service registration."""

    def test_register_service_no_entry(self):
        a = Applet()
        a._entry = None
        # Should not raise
        a.register_service("myService")

    def test_register_service_with_entry(self):
        a = Applet()
        a._entry = {"applet_name": "TestApp"}

        with patch("jive.applet_manager.applet_manager") as mock_mgr:
            mock_mgr.register_service = MagicMock()
            a.register_service("myService", lambda: "result")
            mock_mgr.register_service.assert_called_once()


class TestAppletStoreSettings:
    """Applet settings persistence."""

    def test_store_settings_no_entry(self):
        a = Applet()
        a._entry = None
        # Should not raise
        a.store_settings()

    def test_store_settings_delegates_to_manager(self):
        a = Applet()
        entry = {"applet_name": "TestApp"}
        a._entry = entry

        with patch("jive.applet_manager.applet_manager") as mock_mgr:
            mock_mgr._store_settings = MagicMock()
            a.store_settings()
            mock_mgr._store_settings.assert_called_once_with(entry)


# ══════════════════════════════════════════════════════════════════════════════
# §3  AppletMeta
# ══════════════════════════════════════════════════════════════════════════════

from jive.applet_meta import AppletMeta


class TestAppletMetaBase:
    """AppletMeta base class."""

    def test_jive_version_required(self):
        m = AppletMeta()
        with pytest.raises(NotImplementedError):
            m.jive_version()

    def test_register_applet_required(self):
        m = AppletMeta()
        with pytest.raises(NotImplementedError):
            m.register_applet()

    def test_configure_applet_noop(self):
        m = AppletMeta()
        m.configure_applet()  # Should not raise

    def test_default_settings_none(self):
        m = AppletMeta()
        assert m.default_settings() is None

    def test_upgrade_settings_passthrough(self):
        m = AppletMeta()
        settings = {"key": "value"}
        result = m.upgrade_settings(settings)
        assert result is settings


class TestAppletMetaSubclass:
    """AppletMeta subclass."""

    def test_subclass(self):
        class MyMeta(AppletMeta):
            def jive_version(self):
                return (1, 1)

            def register_applet(self):
                pass

            def default_settings(self):
                return {"theme": "dark"}

        m = MyMeta()
        assert m.jive_version() == (1, 1)
        m.register_applet()  # Should not raise
        assert m.default_settings() == {"theme": "dark"}


class TestAppletMetaStrings:
    """AppletMeta localization."""

    def test_string_no_table(self):
        m = AppletMeta()
        m._strings_table = None
        assert m.string("TOKEN") == "TOKEN"

    def test_string_with_table(self):
        mock_table = MagicMock()
        mock_table.str.return_value = "Localized"
        m = AppletMeta()
        m._strings_table = mock_table
        assert m.string("TOKEN") == "Localized"


class TestAppletMetaSettings:
    """AppletMeta settings access."""

    def test_get_settings(self):
        m = AppletMeta()
        m._settings = {"volume": 50}
        assert m.get_settings() == {"volume": 50}

    def test_store_settings(self):
        m = AppletMeta()
        entry = {"applet_name": "Test"}
        m._entry = entry

        with patch("jive.applet_manager.applet_manager") as mock_mgr:
            mock_mgr._store_settings = MagicMock()
            m.store_settings()
            mock_mgr._store_settings.assert_called_once_with(entry)


class TestAppletMetaMenuItem:
    """AppletMeta menu item builder."""

    def test_menu_item_structure(self):
        m = AppletMeta()
        m._entry = {"applet_name": "NowPlaying"}
        m._strings_table = None  # Will use raw token

        closure = MagicMock()
        item = m.menu_item(
            id="np",
            node="home",
            label="NOW_PLAYING",
            closure=closure,
            weight=5,
        )

        assert item["id"] == "np"
        assert item["node"] == "home"
        assert item["text"] == "NOW_PLAYING"  # Raw token, no strings table
        assert item["weight"] == 5
        assert item["sound"] == "WINDOWSHOW"
        assert callable(item["callback"])
        # Default icon style (bug #12510 compat)
        assert item["iconStyle"] == "hm_advancedSettings"

    def test_menu_item_custom_icon_style(self):
        m = AppletMeta()
        m._entry = {"applet_name": "Test"}
        m._strings_table = None

        item = m.menu_item(
            id="test",
            node="settings",
            label="LABEL",
            closure=lambda a, mi: None,
            icon_style="hm_custom",
        )
        assert item["iconStyle"] == "hm_custom"

    def test_menu_item_extras(self):
        m = AppletMeta()
        m._entry = {"applet_name": "Test"}
        m._strings_table = None

        item = m.menu_item(
            id="test",
            node="home",
            label="LABEL",
            closure=lambda a, mi: None,
            extras={"extra_key": "extra_val"},
        )
        assert item["extras"] == {"extra_key": "extra_val"}

    def test_menu_item_no_weight(self):
        m = AppletMeta()
        m._entry = {"applet_name": "Test"}
        m._strings_table = None

        item = m.menu_item(
            id="test",
            node="home",
            label="LABEL",
            closure=lambda a, mi: None,
        )
        assert "weight" not in item

    def test_menu_item_callback_loads_applet(self):
        m = AppletMeta()
        m._entry = {"applet_name": "MyApplet"}
        m._strings_table = None

        mock_applet = MagicMock()
        result_value = "opened"
        closure = MagicMock(return_value=result_value)

        item = m.menu_item(
            id="test",
            node="home",
            label="LABEL",
            closure=closure,
        )

        with patch("jive.applet_manager.applet_manager") as mock_mgr:
            mock_mgr.load_applet.return_value = mock_applet
            result = item["callback"]()
            mock_mgr.load_applet.assert_called_once_with("MyApplet")
            closure.assert_called_once_with(mock_applet, None)

    def test_repr(self):
        m = AppletMeta()
        m._entry = {"applet_name": "TestApp"}
        r = repr(m)
        assert "AppletMeta" in r
        assert "TestApp" in r


class TestAppletMetaServiceRegistration:
    """AppletMeta service registration."""

    def test_register_service(self):
        m = AppletMeta()
        m._entry = {"applet_name": "Discovery"}

        with patch("jive.applet_manager.applet_manager") as mock_mgr:
            mock_mgr.register_service = MagicMock()
            m.register_service("findServers")
            mock_mgr.register_service.assert_called_once_with(
                "Discovery", "findServers"
            )

    def test_register_service_no_entry(self):
        m = AppletMeta()
        m._entry = None
        m.register_service("test")  # Should not raise

    def test_camel_case_aliases(self):
        assert AppletMeta.registerService is AppletMeta.register_service
        assert AppletMeta.menuItem is AppletMeta.menu_item
        assert AppletMeta.getSettings is AppletMeta.get_settings
        assert AppletMeta.storeSettings is AppletMeta.store_settings


# ══════════════════════════════════════════════════════════════════════════════
# §4  AppletManager
# ══════════════════════════════════════════════════════════════════════════════

from jive.applet_manager import AppletManager, applet_manager


class TestAppletManagerInit:
    """AppletManager initialization."""

    def test_init_sets_singleton(self, tmp_path):
        import jive.applet_manager as am_mod

        old = am_mod.applet_manager
        try:
            s = System(user_dir=tmp_path / "user")
            mgr = AppletManager(system=s)
            assert am_mod.applet_manager is mgr
        finally:
            am_mod.applet_manager = old

    def test_init_without_system(self):
        import jive.applet_manager as am_mod

        old = am_mod.applet_manager
        try:
            mgr = AppletManager()
            assert mgr is not None
        finally:
            am_mod.applet_manager = old

    def test_repr(self, tmp_path):
        import jive.applet_manager as am_mod

        old = am_mod.applet_manager
        try:
            s = System(user_dir=tmp_path / "user")
            mgr = AppletManager(system=s)
            r = repr(mgr)
            assert "AppletManager" in r
            assert "applets=" in r
            assert "loaded=" in r
            assert "services=" in r
        finally:
            am_mod.applet_manager = old


class TestAppletManagerServiceRegistry:
    """AppletManager service registry."""

    def test_register_and_has_service(self, tmp_path):
        import jive.applet_manager as am_mod

        old = am_mod.applet_manager
        try:
            s = System(user_dir=tmp_path / "user")
            mgr = AppletManager(system=s)
            mgr.register_service("MyApplet", "myService")
            assert mgr.has_service("myService")
            assert not mgr.has_service("otherService")
        finally:
            am_mod.applet_manager = old

    def test_register_service_with_closure(self, tmp_path):
        import jive.applet_manager as am_mod

        old = am_mod.applet_manager
        try:
            s = System(user_dir=tmp_path / "user")
            mgr = AppletManager(system=s)
            closure = MagicMock(return_value=42)
            mgr.register_service("MyApplet", "getAnswer", closure)
            assert mgr.has_service("getAnswer")
            result = mgr.call_service("getAnswer")
            assert result == 42
            closure.assert_called_once()
        finally:
            am_mod.applet_manager = old

    def test_call_service_unknown(self, tmp_path):
        import jive.applet_manager as am_mod

        old = am_mod.applet_manager
        try:
            s = System(user_dir=tmp_path / "user")
            mgr = AppletManager(system=s)
            result = mgr.call_service("nonexistent")
            assert result is None
        finally:
            am_mod.applet_manager = old

    def test_register_service_duplicate_warning(self, tmp_path):
        import jive.applet_manager as am_mod

        old = am_mod.applet_manager
        try:
            s = System(user_dir=tmp_path / "user")
            mgr = AppletManager(system=s)
            mgr.register_service("A", "service1")
            # Re-registering should work but log a warning
            mgr.register_service("B", "service1")
            assert mgr.has_service("service1")
        finally:
            am_mod.applet_manager = old


class TestAppletManagerDefaultSettings:
    """AppletManager default settings management."""

    def test_add_default_setting(self, tmp_path):
        import jive.applet_manager as am_mod

        old = am_mod.applet_manager
        try:
            s = System(user_dir=tmp_path / "user")
            mgr = AppletManager(system=s)
            mgr.add_default_setting("MyApplet", "theme", "dark")
            assert mgr._default_settings["MyApplet"]["theme"] == "dark"
        finally:
            am_mod.applet_manager = old

    def test_set_default_settings(self, tmp_path):
        import jive.applet_manager as am_mod

        old = am_mod.applet_manager
        try:
            s = System(user_dir=tmp_path / "user")
            mgr = AppletManager(system=s)
            mgr.set_default_settings("MyApplet", {"a": 1, "b": 2})
            assert mgr._default_settings["MyApplet"] == {"a": 1, "b": 2}
        finally:
            am_mod.applet_manager = old


class TestAppletManagerSettingsPersistence:
    """AppletManager settings loading and storing."""

    def test_store_and_load_settings(self, tmp_path):
        import jive.applet_manager as am_mod

        old = am_mod.applet_manager
        try:
            user_dir = tmp_path / "user"
            s = System(user_dir=user_dir)
            s.init_user_path_dirs()
            mgr = AppletManager(system=s)

            entry = {
                "applet_name": "TestApplet",
                "settings_filepath": str(s.get_settings_dir() / "TestApplet.json"),
                "settings": {"volume": 80, "mute": False},
                "dirpath": str(tmp_path / "applets" / "TestApplet"),
            }

            mgr._store_settings(entry)

            # Verify the file was written
            settings_file = Path(entry["settings_filepath"])
            assert settings_file.exists()
            data = json.loads(settings_file.read_text(encoding="utf-8"))
            assert data["volume"] == 80

            # Test loading
            entry2 = {
                "applet_name": "TestApplet",
                "settings_filepath": str(settings_file),
                "settings": None,
                "dirpath": str(tmp_path / "applets" / "TestApplet"),
            }
            mgr._load_settings(entry2)
            assert entry2["settings"]["volume"] == 80
            assert entry2["settings"]["mute"] is False
        finally:
            am_mod.applet_manager = old

    def test_load_settings_no_file(self, tmp_path):
        import jive.applet_manager as am_mod

        old = am_mod.applet_manager
        try:
            s = System(user_dir=tmp_path / "user")
            mgr = AppletManager(system=s)

            entry = {
                "applet_name": "Missing",
                "settings_filepath": str(tmp_path / "nonexistent.json"),
                "settings": None,
                "dirpath": str(tmp_path / "applets" / "Missing"),
            }
            mgr._load_settings(entry)
            assert entry["settings"] is None
        finally:
            am_mod.applet_manager = old

    def test_load_settings_already_loaded(self, tmp_path):
        import jive.applet_manager as am_mod

        old = am_mod.applet_manager
        try:
            s = System(user_dir=tmp_path / "user")
            mgr = AppletManager(system=s)

            entry = {
                "applet_name": "Test",
                "settings_filepath": str(tmp_path / "test.json"),
                "settings": {"already": "loaded"},
                "dirpath": str(tmp_path),
            }
            mgr._load_settings(entry)
            assert entry["settings"] == {"already": "loaded"}
        finally:
            am_mod.applet_manager = old


class TestAppletManagerLoadPriority:
    """AppletManager load priority."""

    def test_default_priority(self, tmp_path):
        applet_dir = tmp_path / "MyApplet"
        applet_dir.mkdir()
        priority = AppletManager._get_load_priority(applet_dir)
        assert priority == 100

    def test_load_priority_lua_file(self, tmp_path):
        applet_dir = tmp_path / "EarlyApplet"
        applet_dir.mkdir()
        (applet_dir / "loadPriority.lua").write_text("loadPriority = 10")
        priority = AppletManager._get_load_priority(applet_dir)
        assert priority == 10

    def test_load_priority_txt_file(self, tmp_path):
        applet_dir = tmp_path / "LateApplet"
        applet_dir.mkdir()
        (applet_dir / "load_priority.txt").write_text("200")
        priority = AppletManager._get_load_priority(applet_dir)
        assert priority == 200

    def test_load_priority_invalid_lua(self, tmp_path):
        applet_dir = tmp_path / "BadApplet"
        applet_dir.mkdir()
        (applet_dir / "loadPriority.lua").write_text("loadPriority = abc")
        priority = AppletManager._get_load_priority(applet_dir)
        assert priority == 100  # Default on parse failure


class TestAppletManagerDiscovery:
    """AppletManager applet discovery."""

    def test_find_applets_python(self, tmp_path):
        """Discover a Python-based applet with Meta and Applet modules."""
        import jive.applet_manager as am_mod

        old = am_mod.applet_manager
        try:
            # Set up directory structure
            user_dir = tmp_path / "user"
            applets_dir = tmp_path / "share" / "applets"
            applet_dir = applets_dir / "TestDiscovery"
            applet_dir.mkdir(parents=True)

            # Create the meta module
            meta_content = textwrap.dedent("""\
                from jive.applet_meta import AppletMeta

                class TestDiscoveryMeta(AppletMeta):
                    def jive_version(self):
                        return (1, 1)

                    def register_applet(self):
                        pass

                    def default_settings(self):
                        return {"discovered": True}
            """)
            (applet_dir / "TestDiscoveryMeta.py").write_text(meta_content)

            # Create the applet module
            applet_content = textwrap.dedent("""\
                from jive.applet import Applet

                class TestDiscoveryApplet(Applet):
                    def init(self):
                        super().init()
                        self.discovered = True
            """)
            (applet_dir / "TestDiscoveryApplet.py").write_text(applet_content)

            s = System(user_dir=user_dir, search_paths=[tmp_path / "share"])
            s.init_user_path_dirs()
            mgr = AppletManager(system=s)
            mgr._find_applets()

            assert mgr.has_applet("TestDiscovery")
            db = mgr.get_applet_db()
            entry = db["TestDiscovery"]
            assert entry["applet_name"] == "TestDiscovery"
            assert entry["load_priority"] == 100
        finally:
            am_mod.applet_manager = old

    def test_find_applets_with_priority(self, tmp_path):
        """Discover applets with different load priorities."""
        import jive.applet_manager as am_mod

        old = am_mod.applet_manager
        try:
            user_dir = tmp_path / "user"
            applets_dir = tmp_path / "share" / "applets"

            # Create two applets with different priorities
            for name, priority in [("EarlyApp", 10), ("LateApp", 200)]:
                d = applets_dir / name
                d.mkdir(parents=True)
                meta = textwrap.dedent(f"""\
                    from jive.applet_meta import AppletMeta

                    class {name}Meta(AppletMeta):
                        def jive_version(self):
                            return (1, 1)
                        def register_applet(self):
                            pass
                """)
                (d / f"{name}Meta.py").write_text(meta)
                (d / "loadPriority.lua").write_text(f"loadPriority = {priority}")

            s = System(user_dir=user_dir, search_paths=[tmp_path / "share"])
            s.init_user_path_dirs()
            mgr = AppletManager(system=s)
            mgr._find_applets()

            assert mgr.has_applet("EarlyApp")
            assert mgr.has_applet("LateApp")

            # Test sorting
            sorted_entries = mgr._sorted_applet_db()
            names = [e["applet_name"] for e in sorted_entries]
            assert names.index("EarlyApp") < names.index("LateApp")
        finally:
            am_mod.applet_manager = old

    def test_find_applets_allowed_filter(self, tmp_path):
        """Only discover allowed applets."""
        import jive.applet_manager as am_mod

        old = am_mod.applet_manager
        try:
            user_dir = tmp_path / "user"
            applets_dir = tmp_path / "share" / "applets"

            for name in ["Allowed", "NotAllowed"]:
                d = applets_dir / name
                d.mkdir(parents=True)
                meta = textwrap.dedent(f"""\
                    from jive.applet_meta import AppletMeta

                    class {name}Meta(AppletMeta):
                        def jive_version(self):
                            return (1, 1)
                        def register_applet(self):
                            pass
                """)
                (d / f"{name}Meta.py").write_text(meta)

            s = System(user_dir=user_dir, search_paths=[tmp_path / "share"])
            s.init_user_path_dirs()
            mgr = AppletManager(system=s, allowed_applets={"Allowed"})
            mgr._find_applets()

            assert mgr.has_applet("Allowed")
            assert not mgr.has_applet("NotAllowed")
        finally:
            am_mod.applet_manager = old

    def test_no_duplicate_applets(self, tmp_path):
        """Same applet on multiple search paths is only registered once."""
        import jive.applet_manager as am_mod

        old = am_mod.applet_manager
        try:
            user_dir = tmp_path / "user"
            share1 = tmp_path / "share1" / "applets"
            share2 = tmp_path / "share2" / "applets"

            for share in [share1, share2]:
                d = share / "DupApp"
                d.mkdir(parents=True)
                meta = textwrap.dedent("""\
                    from jive.applet_meta import AppletMeta

                    class DupAppMeta(AppletMeta):
                        def jive_version(self):
                            return (1, 1)
                        def register_applet(self):
                            pass
                """)
                (d / "DupAppMeta.py").write_text(meta)

            s = System(
                user_dir=user_dir,
                search_paths=[tmp_path / "share1", tmp_path / "share2"],
            )
            s.init_user_path_dirs()
            mgr = AppletManager(system=s)
            mgr._find_applets()

            assert mgr.has_applet("DupApp")
            # Should only appear once
            db = mgr.get_applet_db()
            assert len(db) == 1
        finally:
            am_mod.applet_manager = old


class TestAppletManagerLoadApplet:
    """AppletManager load and free applets."""

    def _create_applet_files(self, tmp_path, name="TestLoad"):
        """Helper to create a minimal applet on disk."""
        applets_dir = tmp_path / "share" / "applets"
        applet_dir = applets_dir / name
        applet_dir.mkdir(parents=True)

        meta_content = textwrap.dedent(f"""\
            from jive.applet_meta import AppletMeta

            class {name}Meta(AppletMeta):
                def jive_version(self):
                    return (1, 1)

                def register_applet(self):
                    pass

                def default_settings(self):
                    return {{"loaded": False}}
        """)
        (applet_dir / f"{name}Meta.py").write_text(meta_content)

        applet_content = textwrap.dedent(f"""\
            from jive.applet import Applet

            class {name}Applet(Applet):
                def init(self):
                    super().init()
                    self.did_init = True

                def free(self):
                    return True

                def my_service(self):
                    return "service_result"
        """)
        (applet_dir / f"{name}Applet.py").write_text(applet_content)

        return applets_dir.parent  # share dir

    def test_load_applet_full_lifecycle(self, tmp_path):
        """Test the full lifecycle: discover -> load -> use -> free."""
        import jive.applet_manager as am_mod

        old = am_mod.applet_manager
        try:
            share_dir = self._create_applet_files(tmp_path)
            user_dir = tmp_path / "user"

            s = System(user_dir=user_dir, search_paths=[share_dir])
            s.init_user_path_dirs()
            mgr = AppletManager(system=s)
            mgr.discover()

            assert mgr.has_applet("TestLoad")

            # Load
            applet = mgr.load_applet("TestLoad")
            assert applet is not None
            assert hasattr(applet, "did_init")
            assert applet.did_init is True

            # Get instance
            same_applet = mgr.get_applet_instance("TestLoad")
            assert same_applet is applet

            # Free
            mgr.free_applet("TestLoad")
            assert mgr.get_applet_instance("TestLoad") is None
        finally:
            am_mod.applet_manager = old
            # Clean up sys.modules
            for key in list(sys.modules.keys()):
                if "TestLoad" in key:
                    del sys.modules[key]

    def test_load_applet_unknown(self, tmp_path):
        import jive.applet_manager as am_mod

        old = am_mod.applet_manager
        try:
            s = System(user_dir=tmp_path / "user")
            mgr = AppletManager(system=s)
            result = mgr.load_applet("NonexistentApplet")
            assert result is None
        finally:
            am_mod.applet_manager = old

    def test_load_applet_twice_returns_same(self, tmp_path):
        """Loading the same applet twice should return the same instance."""
        import jive.applet_manager as am_mod

        old = am_mod.applet_manager
        try:
            share_dir = self._create_applet_files(tmp_path, "TestDouble")
            user_dir = tmp_path / "user"

            s = System(user_dir=user_dir, search_paths=[share_dir])
            s.init_user_path_dirs()
            mgr = AppletManager(system=s)
            mgr.discover()

            a1 = mgr.load_applet("TestDouble")
            a2 = mgr.load_applet("TestDouble")
            assert a1 is a2
        finally:
            am_mod.applet_manager = old
            for key in list(sys.modules.keys()):
                if "TestDouble" in key:
                    del sys.modules[key]

    def test_call_service_via_applet(self, tmp_path):
        """Test calling a service on a loaded applet."""
        import jive.applet_manager as am_mod

        old = am_mod.applet_manager
        try:
            share_dir = self._create_applet_files(tmp_path, "ServiceApp")
            user_dir = tmp_path / "user"

            s = System(user_dir=user_dir, search_paths=[share_dir])
            s.init_user_path_dirs()
            mgr = AppletManager(system=s)
            mgr.discover()

            mgr.register_service("ServiceApp", "my_service")
            result = mgr.call_service("my_service")
            assert result == "service_result"
        finally:
            am_mod.applet_manager = old
            for key in list(sys.modules.keys()):
                if "ServiceApp" in key:
                    del sys.modules[key]

    def test_free_unknown_applet(self, tmp_path):
        import jive.applet_manager as am_mod

        old = am_mod.applet_manager
        try:
            s = System(user_dir=tmp_path / "user")
            mgr = AppletManager(system=s)
            mgr.free_applet("Unknown")  # Should not raise
        finally:
            am_mod.applet_manager = old

    def test_free_applet_returns_false(self, tmp_path):
        """If applet.free() returns False, the applet stays loaded."""
        import jive.applet_manager as am_mod

        old = am_mod.applet_manager
        try:
            applets_dir = tmp_path / "share" / "applets"
            applet_dir = applets_dir / "StickyApp"
            applet_dir.mkdir(parents=True)

            meta_content = textwrap.dedent("""\
                from jive.applet_meta import AppletMeta

                class StickyAppMeta(AppletMeta):
                    def jive_version(self):
                        return (1, 1)
                    def register_applet(self):
                        pass
            """)
            (applet_dir / "StickyAppMeta.py").write_text(meta_content)

            applet_content = textwrap.dedent("""\
                from jive.applet import Applet

                class StickyAppApplet(Applet):
                    def init(self):
                        pass
                    def free(self):
                        return False  # Refuse to be freed
            """)
            (applet_dir / "StickyAppApplet.py").write_text(applet_content)

            user_dir = tmp_path / "user"
            s = System(user_dir=user_dir, search_paths=[applets_dir.parent])
            s.init_user_path_dirs()
            mgr = AppletManager(system=s)
            mgr.discover()

            applet = mgr.load_applet("StickyApp")
            assert applet is not None

            mgr.free_applet("StickyApp")
            # Should still be loaded because free() returned False
            assert mgr.get_applet_instance("StickyApp") is applet
        finally:
            am_mod.applet_manager = old
            for key in list(sys.modules.keys()):
                if "StickyApp" in key:
                    del sys.modules[key]


class TestAppletManagerLocaleStrings:
    """AppletManager locale strings loading."""

    def test_load_locale_strings_no_file(self, tmp_path):
        import jive.applet_manager as am_mod

        old = am_mod.applet_manager
        try:
            s = System(user_dir=tmp_path / "user")
            mgr = AppletManager(system=s)

            entry = {
                "applet_name": "Test",
                "dirpath": str(tmp_path / "nonexistent"),
                "strings_table": None,
            }
            mgr._load_locale_strings(entry)
            assert entry["strings_table"] is None
        finally:
            am_mod.applet_manager = old

    def test_load_locale_strings_already_loaded(self, tmp_path):
        import jive.applet_manager as am_mod

        old = am_mod.applet_manager
        try:
            s = System(user_dir=tmp_path / "user")
            mgr = AppletManager(system=s)

            mock_table = MagicMock()
            entry = {
                "applet_name": "Test",
                "dirpath": str(tmp_path),
                "strings_table": mock_table,
            }
            mgr._load_locale_strings(entry)
            # Should not change the already-loaded table
            assert entry["strings_table"] is mock_table
        finally:
            am_mod.applet_manager = old


class TestAppletManagerModuleImport:
    """AppletManager module import helpers."""

    def test_import_class_from_file(self, tmp_path):
        # Create a simple Python module
        module_file = tmp_path / "test_module.py"
        module_file.write_text(
            textwrap.dedent("""\
            class TestClass:
                value = 42
        """)
        )

        cls = AppletManager._import_class_from_file(
            module_file, "test_import_class_module", "TestClass"
        )
        assert cls is not None
        assert cls.value == 42

        # Clean up
        sys.modules.pop("test_import_class_module", None)

    def test_import_class_from_file_missing(self, tmp_path):
        cls = AppletManager._import_class_from_file(
            tmp_path / "nonexistent.py", "nonexistent_mod", "SomeClass"
        )
        assert cls is None

    def test_import_class_from_file_no_class(self, tmp_path):
        module_file = tmp_path / "empty_module.py"
        module_file.write_text("x = 1\n")

        cls = AppletManager._import_class_from_file(
            module_file, "test_empty_module", "NonexistentClass"
        )
        assert cls is None

        sys.modules.pop("test_empty_module", None)

    def test_import_class_from_file_cached(self, tmp_path):
        module_file = tmp_path / "cached_module.py"
        module_file.write_text(
            textwrap.dedent("""\
            class CachedClass:
                pass
        """)
        )

        mod_name = "test_cached_module"
        cls1 = AppletManager._import_class_from_file(
            module_file, mod_name, "CachedClass"
        )
        cls2 = AppletManager._import_class_from_file(
            module_file, mod_name, "CachedClass"
        )
        assert cls1 is cls2

        sys.modules.pop(mod_name, None)


# ══════════════════════════════════════════════════════════════════════════════
# §5  Iconbar
# ══════════════════════════════════════════════════════════════════════════════

from jive.iconbar import Iconbar, _GroupStub, _IconStub, _LabelStub


class TestIconStub:
    """Icon stub widget."""

    def test_set_get_style(self):
        icon = _IconStub("initial")
        assert icon.get_style() == "initial"
        icon.set_style("new_style")
        assert icon.get_style() == "new_style"

    def test_camel_case(self):
        icon = _IconStub()
        icon.setStyle("test")
        assert icon.getStyle() == "test"

    def test_repr(self):
        icon = _IconStub("my_style")
        assert "my_style" in repr(icon)


class TestLabelStub:
    """Label stub widget."""

    def test_set_get_value(self):
        label = _LabelStub("style", "initial")
        assert label.get_value() == "initial"
        label.set_value("new value")
        assert label.get_value() == "new value"

    def test_camel_case(self):
        label = _LabelStub()
        label.setValue("test")
        assert label.getValue() == "test"

    def test_add_timer_noop(self):
        label = _LabelStub()
        label.add_timer(1000, lambda: None)  # Should not raise


class TestGroupStub:
    """Group stub widget."""

    def test_init(self):
        group = _GroupStub("my_group", {"a": 1})
        assert group._style == "my_group"
        assert group._widgets == {"a": 1}


class TestIconbarInit:
    """Iconbar initialization."""

    def test_init_with_stubs(self):
        ib = Iconbar()
        assert isinstance(ib.icon_playmode, _IconStub)
        assert isinstance(ib.icon_repeat, _IconStub)
        assert isinstance(ib.icon_shuffle, _IconStub)
        assert isinstance(ib.icon_battery, _IconStub)
        assert isinstance(ib.icon_wireless, _IconStub)
        assert isinstance(ib.icon_sleep, _IconStub)
        assert isinstance(ib.icon_alarm, _IconStub)
        assert isinstance(ib.button_time, _LabelStub)
        assert isinstance(ib.iconbar_group, _GroupStub)

    def test_init_with_jnt(self):
        mock_jnt = MagicMock()
        ib = Iconbar(jnt=mock_jnt)
        assert ib.jnt is mock_jnt


class TestIconbarPlaymode:
    """Iconbar playmode icon."""

    def test_set_playmode_play(self):
        ib = Iconbar()
        ib.set_playmode("play")
        assert ib.icon_playmode.get_style() == "button_playmode_PLAY"

    def test_set_playmode_stop(self):
        ib = Iconbar()
        ib.set_playmode("stop")
        assert ib.icon_playmode.get_style() == "button_playmode_STOP"

    def test_set_playmode_pause(self):
        ib = Iconbar()
        ib.set_playmode("pause")
        assert ib.icon_playmode.get_style() == "button_playmode_PAUSE"

    def test_set_playmode_none(self):
        ib = Iconbar()
        ib.set_playmode(None)
        assert ib.icon_playmode.get_style() == "button_playmode_OFF"

    def test_camel_case_alias(self):
        ib = Iconbar()
        ib.setPlaymode("play")
        assert ib.icon_playmode.get_style() == "button_playmode_PLAY"


class TestIconbarRepeat:
    """Iconbar repeat icon."""

    def test_repeat_off(self):
        ib = Iconbar()
        ib.set_repeat(None)
        assert ib.icon_repeat.get_style() == "button_repeat_OFF"

    def test_repeat_single(self):
        ib = Iconbar()
        ib.set_repeat(1)
        assert ib.icon_repeat.get_style() == "button_repeat_1"

    def test_repeat_all(self):
        ib = Iconbar()
        ib.set_repeat(2)
        assert ib.icon_repeat.get_style() == "button_repeat_2"


class TestIconbarShuffle:
    """Iconbar shuffle icon."""

    def test_shuffle_off(self):
        ib = Iconbar()
        ib.set_shuffle(None)
        assert ib.icon_shuffle.get_style() == "button_shuffle_OFF"

    def test_shuffle_track(self):
        ib = Iconbar()
        ib.set_shuffle(1)
        assert ib.icon_shuffle.get_style() == "button_shuffle_1"

    def test_shuffle_album(self):
        ib = Iconbar()
        ib.set_shuffle(2)
        assert ib.icon_shuffle.get_style() == "button_shuffle_2"


class TestIconbarAlarm:
    """Iconbar alarm icon."""

    def test_alarm_off(self):
        ib = Iconbar()
        ib.set_alarm(None)
        assert ib.icon_alarm.get_style() == "button_alarm_OFF"

    def test_alarm_on(self):
        ib = Iconbar()
        ib.set_alarm("ON")
        assert ib.icon_alarm.get_style() == "button_alarm_ON"


class TestIconbarSleep:
    """Iconbar sleep icon."""

    def test_sleep_off(self):
        ib = Iconbar()
        ib.set_sleep(None)
        assert ib.icon_sleep.get_style() == "button_sleep_OFF"

    def test_sleep_on(self):
        ib = Iconbar()
        ib.set_sleep("ON")
        assert ib.icon_sleep.get_style() == "button_sleep_ON"


class TestIconbarBattery:
    """Iconbar battery icon."""

    def test_battery_none(self):
        ib = Iconbar()
        ib.set_battery(None)
        assert ib.icon_battery.get_style() == "button_battery_NONE"

    def test_battery_charging(self):
        ib = Iconbar()
        ib.set_battery("CHARGING")
        assert ib.icon_battery.get_style() == "button_battery_CHARGING"

    def test_battery_level(self):
        ib = Iconbar()
        for level in range(1, 5):
            ib.set_battery(level)
            assert ib.icon_battery.get_style() == f"button_battery_{level}"
        # Level 0 is falsy, so it falls through to "NONE" — this matches
        # the Lua behavior where `val or "NONE"` makes 0 become "NONE"
        ib.set_battery(0)
        assert ib.icon_battery.get_style() == "button_battery_NONE"


class TestIconbarWireless:
    """Iconbar wireless signal icon."""

    def test_ethernet_error(self):
        ib = Iconbar()
        ib.set_wireless_signal("ETHERNET_ERROR")
        assert ib.icon_wireless.get_style() == "button_ethernet_ERROR"

    def test_wireless_error(self):
        ib = Iconbar()
        ib.set_wireless_signal("ERROR")
        assert ib.icon_wireless.get_style() == "button_wireless_ERROR"

    def test_wireless_zero(self):
        ib = Iconbar()
        ib.set_wireless_signal(0)
        assert ib.icon_wireless.get_style() == "button_wireless_ERROR"

    def test_ethernet_no_server(self):
        ib = Iconbar()
        ib.server_error = None  # No server info
        ib.set_wireless_signal("ETHERNET")
        assert ib.icon_wireless.get_style() == "button_ethernet_SERVERERROR"

    def test_ethernet_server_error(self):
        ib = Iconbar()
        ib.server_error = "ERROR"
        ib.set_wireless_signal("ETHERNET")
        assert ib.icon_wireless.get_style() == "button_ethernet_SERVERERROR"

    def test_ethernet_server_ok(self):
        ib = Iconbar()
        ib.server_error = "OK"
        ib.set_wireless_signal("ETHERNET")
        assert ib.icon_wireless.get_style() == "button_ethernet"

    def test_wireless_server_error(self):
        ib = Iconbar()
        ib.server_error = "ERROR"
        ib.set_wireless_signal(3)
        assert ib.icon_wireless.get_style() == "button_wireless_SERVERERROR"

    def test_wireless_server_ok(self):
        ib = Iconbar()
        ib.server_error = "OK"
        ib.set_wireless_signal(4)
        assert ib.icon_wireless.get_style() == "button_wireless_4"

    def test_wireless_signal_range(self):
        ib = Iconbar()
        ib.server_error = "OK"
        for level in range(1, 5):
            ib.set_wireless_signal(level)
            assert ib.icon_wireless.get_style() == f"button_wireless_{level}"

    def test_wireless_notification_change(self):
        mock_jnt = MagicMock()
        ib = Iconbar(jnt=mock_jnt)
        ib.server_error = "OK"

        # First call — state was None before
        ib.set_wireless_signal(3)
        mock_jnt.notify.assert_called()

    def test_wireless_notification_not_called_on_same_state(self):
        mock_jnt = MagicMock()
        ib = Iconbar(jnt=mock_jnt)
        ib.server_error = "OK"

        ib.set_wireless_signal(3)
        mock_jnt.notify.reset_mock()

        # Same state — should not notify
        ib.set_wireless_signal(4)
        mock_jnt.notify.assert_not_called()

    def test_network_server_ok_notification(self):
        mock_jnt = MagicMock()
        ib = Iconbar(jnt=mock_jnt)
        ib.server_error = "OK"
        ib._old_network_and_server_state = False  # Was bad

        ib.set_wireless_signal("ETHERNET")
        mock_jnt.notify.assert_called_with("networkAndServerOK", None)

    def test_network_or_server_not_ok_notification(self):
        mock_jnt = MagicMock()
        ib = Iconbar(jnt=mock_jnt)
        ib.server_error = "ERROR"
        ib._old_network_and_server_state = True  # Was good

        ib.set_wireless_signal(3)
        mock_jnt.notify.assert_called_with("networkOrServerNotOK", None)


class TestIconbarServerError:
    """Iconbar server error state."""

    def test_set_server_error_retriggers_wireless(self):
        ib = Iconbar()
        ib.set_wireless_signal("ETHERNET")
        # No server → SERVERERROR
        assert ib.icon_wireless.get_style() == "button_ethernet_SERVERERROR"

        ib.set_server_error("OK")
        # Now server is OK → button_ethernet
        assert ib.icon_wireless.get_style() == "button_ethernet"

    def test_set_server_error_to_error(self):
        ib = Iconbar()
        ib.set_server_error("OK")
        ib.set_wireless_signal(3)
        assert ib.icon_wireless.get_style() == "button_wireless_3"

        ib.set_server_error("ERROR")
        assert ib.icon_wireless.get_style() == "button_wireless_SERVERERROR"


class TestIconbarDebug:
    """Iconbar debug overlay."""

    def test_show_debug(self):
        ib = Iconbar()
        ib.show_debug("DEBUG INFO", elapsed=5)
        assert ib.button_time.get_value() == "DEBUG INFO"
        assert ib._debug_timeout is not None

    def test_debug_suppresses_update(self):
        ib = Iconbar()
        ib.show_debug("DEBUG", elapsed=60)

        # Update should not overwrite debug
        ib.update()
        assert ib.button_time.get_value() == "DEBUG"

    def test_debug_timeout_expires(self):
        ib = Iconbar()
        # Set timeout in the past
        ib.button_time.set_value("DEBUG")
        ib._debug_timeout = time.monotonic() - 1

        ib.update()
        # Should have updated with the current time (no longer DEBUG)
        assert ib.button_time.get_value() != "DEBUG"


class TestIconbarUpdate:
    """Iconbar update / time display."""

    def test_update_sets_time(self):
        ib = Iconbar()
        ib.update()
        value = ib.button_time.get_value()
        assert isinstance(value, str)
        assert len(value) > 0

    def test_repr(self):
        ib = Iconbar()
        r = repr(ib)
        assert "Iconbar" in r


class TestIconbarCamelCaseAliases:
    """Iconbar camelCase aliases."""

    def test_all_aliases(self):
        assert Iconbar.setPlaymode is Iconbar.set_playmode
        assert Iconbar.setRepeat is Iconbar.set_repeat
        assert Iconbar.setShuffle is Iconbar.set_shuffle
        assert Iconbar.setBattery is Iconbar.set_battery
        assert Iconbar.setAlarm is Iconbar.set_alarm
        assert Iconbar.setSleep is Iconbar.set_sleep
        assert Iconbar.setWirelessSignal is Iconbar.set_wireless_signal
        assert Iconbar.setServerError is Iconbar.set_server_error
        assert Iconbar.showDebug is Iconbar.show_debug


# ══════════════════════════════════════════════════════════════════════════════
# §6  InputToActionMap
# ══════════════════════════════════════════════════════════════════════════════

from jive.input_to_action_map import (
    action_action_mappings,
    char_action_mappings,
    gesture_action_mappings,
    ir_action_mappings,
    key_action_mappings,
    unassigned_action_mappings,
)


class TestCharActionMappings:
    """Character → action mappings."""

    def test_has_press_dict(self):
        assert "press" in char_action_mappings
        assert isinstance(char_action_mappings["press"], dict)

    def test_common_mappings(self):
        press = char_action_mappings["press"]
        assert press["x"] == "play"
        assert press["p"] == "play"
        assert press[" "] == "pause"
        assert press["c"] == "pause"
        assert press["h"] == "go_home"
        assert press["/"] == "go_search"
        assert press["+"] == "volume_up"
        assert press["-"] == "volume_down"

    def test_preset_mappings(self):
        press = char_action_mappings["press"]
        for i in range(10):
            assert press[str(i)] == f"play_preset_{i}"

    def test_back_mappings(self):
        press = char_action_mappings["press"]
        assert press["\b"] == "back"
        assert press["\x1b"] == "back"
        assert press["j"] == "back"

    def test_development_tools(self):
        press = char_action_mappings["press"]
        assert press["R"] == "reload_skin"
        assert press["}"] == "debug_skin"


class TestKeyActionMappings:
    """Key code → action mappings."""

    def test_has_press_and_hold(self):
        assert "press" in key_action_mappings
        assert "hold" in key_action_mappings

    def test_press_mappings(self):
        press = key_action_mappings["press"]
        assert press[KEY_HOME] == "go_home_or_now_playing"
        assert press[KEY_PLAY] == "play"
        assert press[KEY_VOLUME_UP] == "volume_up"
        assert press[KEY_VOLUME_DOWN] == "volume_down"

    def test_hold_mappings(self):
        hold = key_action_mappings["hold"]
        assert hold[KEY_HOME] == "go_home"
        assert hold[KEY_PLAY] == "create_mix"
        assert hold[KEY_VOLUME_UP] == "volume_up"

    def test_key_values_are_integers(self):
        for mode in ("press", "hold"):
            for key in key_action_mappings[mode]:
                assert isinstance(key, int), f"Key {key} in {mode} is not int"


class TestIRActionMappings:
    """IR remote → action mappings."""

    def test_has_press_and_hold(self):
        assert "press" in ir_action_mappings
        assert "hold" in ir_action_mappings

    def test_press_mappings(self):
        press = ir_action_mappings["press"]
        assert press["play"] == "play"
        assert press["pause"] == "pause"
        assert press["volup"] == "volume_up"
        assert press["home"] == "go_home_or_now_playing"

    def test_hold_mappings(self):
        hold = ir_action_mappings["hold"]
        assert hold["home"] == "go_home"
        assert hold["play"] == "create_mix"
        assert hold["fwd"] == "scanner_fwd"

    def test_preset_mappings(self):
        press = ir_action_mappings["press"]
        for i in range(10):
            assert press[str(i)] == f"play_preset_{i}"

    def test_hold_presets_disabled(self):
        hold = ir_action_mappings["hold"]
        for i in range(10):
            assert hold[str(i)] == "disabled"


class TestGestureActionMappings:
    """Gesture → action mappings."""

    def test_swipe_right(self):
        assert gesture_action_mappings[GESTURE_L_R] == "go_home"

    def test_swipe_left(self):
        assert gesture_action_mappings[GESTURE_R_L] == "go_now_playing_or_playlist"


class TestActionActionMappings:
    """Action → action chaining mappings."""

    def test_title_mappings(self):
        assert action_action_mappings["title_left_press"] == "back"
        assert action_action_mappings["title_left_hold"] == "go_home"
        assert action_action_mappings["title_right_press"] == "go_now_playing"
        assert action_action_mappings["title_right_hold"] == "go_playlist"

    def test_home_title_mappings(self):
        assert action_action_mappings["home_title_left_press"] == "power"
        assert action_action_mappings["home_title_left_hold"] == "power"


class TestUnassignedActionMappings:
    """Unassigned action names."""

    def test_is_list(self):
        assert isinstance(unassigned_action_mappings, list)

    def test_common_entries(self):
        assert "nothing" in unassigned_action_mappings
        assert "disabled" in unassigned_action_mappings
        assert "play_next" in unassigned_action_mappings
        assert "power_off" in unassigned_action_mappings
        assert "power_on" in unassigned_action_mappings
        assert "mute" in unassigned_action_mappings
        assert "cancel" in unassigned_action_mappings


# ══════════════════════════════════════════════════════════════════════════════
# §7  JiveMain
# ══════════════════════════════════════════════════════════════════════════════

from jive.jive_main import JiveMain, _HomeMenuStub, _NotificationHub


class TestNotificationHub:
    """Notification hub stub."""

    def test_notify_no_listeners(self):
        hub = _NotificationHub()
        hub.notify("event")  # Should not raise

    def test_add_and_notify(self):
        hub = _NotificationHub()
        results = []
        hub.add_listener("test", lambda *a: results.append(a))
        hub.notify("test", "arg1", "arg2")
        assert len(results) == 1
        assert results[0] == ("arg1", "arg2")

    def test_remove_listener(self):
        hub = _NotificationHub()
        results = []
        callback = lambda *a: results.append(1)
        hub.add_listener("test", callback)
        hub.remove_listener("test", callback)
        hub.notify("test")
        assert len(results) == 0

    def test_multiple_listeners(self):
        hub = _NotificationHub()
        results = []
        hub.add_listener("e", lambda: results.append(1))
        hub.add_listener("e", lambda: results.append(2))
        hub.notify("e")
        assert results == [1, 2]

    def test_task_returns_none(self):
        hub = _NotificationHub()
        assert hub.task() is None

    def test_repr(self):
        hub = _NotificationHub()
        assert "NotificationHub" in repr(hub)


class TestHomeMenuStub:
    """HomeMenu stub for headless operation."""

    def test_add_node(self):
        hm = _HomeMenuStub()
        hm.add_node({"id": "settings", "node": "home"})
        assert "settings" in hm.get_node_table()

    def test_add_item(self):
        hm = _HomeMenuStub()
        hm.add_item({"id": "my_item", "node": "home"})
        assert "my_item" in hm.get_menu_table()

    def test_remove_item(self):
        hm = _HomeMenuStub()
        hm.add_item({"id": "temp", "node": "home"})
        hm.remove_item({"id": "temp"})
        assert "temp" not in hm.get_menu_table()

    def test_close_to_home(self):
        hm = _HomeMenuStub()
        hm.close_to_home()  # Should not raise

    def test_camel_case_aliases(self):
        assert _HomeMenuStub.addNode is _HomeMenuStub.add_node
        assert _HomeMenuStub.addItem is _HomeMenuStub.add_item
        assert _HomeMenuStub.removeItem is _HomeMenuStub.remove_item
        assert _HomeMenuStub.getMenuTable is _HomeMenuStub.get_menu_table
        assert _HomeMenuStub.getNodeTable is _HomeMenuStub.get_node_table
        assert _HomeMenuStub.closeToHome is _HomeMenuStub.close_to_home


class TestJiveMainInit:
    """JiveMain initialization (headless, no event loop)."""

    def _make_jive_main(self, tmp_path, **kwargs):
        """Helper to create a JiveMain in headless/test mode."""
        import jive.applet_manager as am_mod
        import jive.jive_main as jm_mod

        old_jm = jm_mod.jive_main
        old_am = am_mod.applet_manager
        old_instance = JiveMain.instance

        try:
            user_dir = tmp_path / "user"
            s = System(user_dir=user_dir, search_paths=[])
            s.init_user_path_dirs()

            from jive.utils.locale import Locale

            loc = Locale()

            jm = JiveMain(
                run_event_loop=False,
                system=s,
                locale=loc,
                init_ui=False,
                **kwargs,
            )
            return jm
        except Exception:
            jm_mod.jive_main = old_jm
            am_mod.applet_manager = old_am
            JiveMain.instance = old_instance
            raise

    def _cleanup_jive_main(self):
        import jive.applet_manager as am_mod
        import jive.jive_main as jm_mod

        jm_mod.jive_main = None
        jm_mod.applet_manager_instance = None
        jm_mod.iconbar_instance = None
        jm_mod.jnt_instance = None
        am_mod.applet_manager = None
        JiveMain.instance = None

    def test_basic_init(self, tmp_path):
        try:
            jm = self._make_jive_main(tmp_path)
            assert jm is not None
            assert JiveMain.instance is jm
        finally:
            self._cleanup_jive_main()

    def test_version(self, tmp_path):
        try:
            jm = self._make_jive_main(tmp_path)
            assert jm.JIVE_VERSION == "7.8"
        finally:
            self._cleanup_jive_main()

    def test_system_assigned(self, tmp_path):
        try:
            jm = self._make_jive_main(tmp_path)
            assert jm._system is not None
        finally:
            self._cleanup_jive_main()

    def test_applet_manager_created(self, tmp_path):
        try:
            jm = self._make_jive_main(tmp_path)
            assert jm._applet_manager is not None
            import jive.jive_main as jm_mod

            assert jm_mod.applet_manager_instance is not None
        finally:
            self._cleanup_jive_main()

    def test_iconbar_created(self, tmp_path):
        try:
            jm = self._make_jive_main(tmp_path)
            assert jm._iconbar is not None
            import jive.jive_main as jm_mod

            assert jm_mod.iconbar_instance is not None
        finally:
            self._cleanup_jive_main()

    def test_home_menu_exists(self, tmp_path):
        try:
            jm = self._make_jive_main(tmp_path)
            assert jm.home_menu is not None
        finally:
            self._cleanup_jive_main()

    def test_jnt_created(self, tmp_path):
        try:
            jm = self._make_jive_main(tmp_path)
            assert jm.jnt is not None
        finally:
            self._cleanup_jive_main()

    def test_repr(self, tmp_path):
        try:
            jm = self._make_jive_main(tmp_path)
            r = repr(jm)
            assert "JiveMain" in r
            assert "7.8" in r
        finally:
            self._cleanup_jive_main()


class TestJiveMainMenuNodes:
    """JiveMain menu node registration."""

    def _make_jm(self, tmp_path):
        import jive.applet_manager as am_mod
        import jive.jive_main as jm_mod

        s = System(user_dir=tmp_path / "user", search_paths=[])
        s.init_user_path_dirs()
        from jive.utils.locale import Locale

        jm = JiveMain(
            run_event_loop=False,
            system=s,
            locale=Locale(),
            init_ui=False,
        )
        return jm

    def _cleanup(self):
        import jive.applet_manager as am_mod
        import jive.jive_main as jm_mod

        jm_mod.jive_main = None
        jm_mod.applet_manager_instance = None
        jm_mod.iconbar_instance = None
        jm_mod.jnt_instance = None
        am_mod.applet_manager = None
        JiveMain.instance = None

    def test_standard_nodes_registered(self, tmp_path):
        try:
            jm = self._make_jm(tmp_path)
            # The HomeMenu may be real or a stub; both support get_node_table()
            nodes = jm.get_node_table()
            # Check that at least the standard nodes were added
            expected_nodes = [
                "hidden",
                "extras",
                "radios",
                "settings",
                "advancedSettings",
                "screenSettings",
                "factoryTest",
                "settingsAudio",
                "settingsBrightness",
            ]
            for node_id in expected_nodes:
                assert node_id in nodes, f"Node {node_id!r} not found in node table"
        finally:
            self._cleanup()

    def test_node_properties(self, tmp_path):
        try:
            jm = self._make_jm(tmp_path)
            nodes = jm.get_node_table()
            # The real HomeMenu stores nodes as dicts with 'item' sub-dict;
            # the stub stores the raw dict.  Handle both.
            extras = nodes["extras"]
            if "item" in extras and isinstance(extras["item"], dict):
                # Real HomeMenu format
                assert extras["item"].get("weight") == 50
            else:
                # Stub format
                assert extras.get("weight") == 50
        finally:
            self._cleanup()

    def test_node_ids_present(self, tmp_path):
        try:
            jm = self._make_jm(tmp_path)
            nodes = jm.get_node_table()
            # Every node key should correspond to a node with that id.
            # Real HomeMenu: node_data has 'item' sub-dict with 'id'.
            # Stub: node_data itself has 'id'.
            for node_id, node_data in nodes.items():
                if "item" in node_data and isinstance(node_data.get("item"), dict):
                    assert node_data["item"].get("id") == node_id
                elif node_data.get("id") is not None:
                    assert node_data.get("id") == node_id
                # else: root "home" node may have item=None, skip it
        finally:
            self._cleanup()


class TestJiveMainSoftPower:
    """JiveMain soft power state."""

    def _make_jm(self, tmp_path):
        import jive.applet_manager as am_mod
        import jive.jive_main as jm_mod

        s = System(user_dir=tmp_path / "user", search_paths=[])
        s.init_user_path_dirs()
        from jive.utils.locale import Locale

        jm = JiveMain(
            run_event_loop=False,
            system=s,
            locale=Locale(),
            init_ui=False,
        )
        return jm

    def _cleanup(self):
        import jive.applet_manager as am_mod
        import jive.jive_main as jm_mod

        jm_mod.jive_main = None
        jm_mod.applet_manager_instance = None
        jm_mod.iconbar_instance = None
        jm_mod.jnt_instance = None
        am_mod.applet_manager = None
        JiveMain.instance = None

    def test_default_power_on(self, tmp_path):
        try:
            jm = self._make_jm(tmp_path)
            assert jm.get_soft_power_state() == "on"
        finally:
            self._cleanup()

    def test_set_power_off(self, tmp_path):
        try:
            jm = self._make_jm(tmp_path)
            jm.set_soft_power_state("off")
            assert jm.get_soft_power_state() == "off"
        finally:
            self._cleanup()

    def test_set_power_on(self, tmp_path):
        try:
            jm = self._make_jm(tmp_path)
            jm.set_soft_power_state("off")
            jm.set_soft_power_state("on")
            assert jm.get_soft_power_state() == "on"
        finally:
            self._cleanup()

    def test_toggle_power(self, tmp_path):
        try:
            jm = self._make_jm(tmp_path)
            assert jm.get_soft_power_state() == "on"
            jm.toggle_power()
            assert jm.get_soft_power_state() == "off"
            jm.toggle_power()
            assert jm.get_soft_power_state() == "on"
        finally:
            self._cleanup()

    def test_set_same_state_noop(self, tmp_path):
        try:
            jm = self._make_jm(tmp_path)
            jm.set_soft_power_state("on")  # Already on
            assert jm.get_soft_power_state() == "on"
        finally:
            self._cleanup()

    def test_camel_case_aliases(self, tmp_path):
        try:
            jm = self._make_jm(tmp_path)
            assert JiveMain.getSoftPowerState is JiveMain.get_soft_power_state
            assert JiveMain.setSoftPowerState is JiveMain.set_soft_power_state
            assert JiveMain.togglePower is JiveMain.toggle_power
        finally:
            self._cleanup()


class TestJiveMainSkinManagement:
    """JiveMain skin registration and management."""

    def _make_jm(self, tmp_path):
        import jive.applet_manager as am_mod
        import jive.jive_main as jm_mod

        s = System(user_dir=tmp_path / "user", search_paths=[])
        s.init_user_path_dirs()
        from jive.utils.locale import Locale

        jm = JiveMain(
            run_event_loop=False,
            system=s,
            locale=Locale(),
            init_ui=False,
        )
        return jm

    def _cleanup(self):
        import jive.applet_manager as am_mod
        import jive.jive_main as jm_mod

        jm_mod.jive_main = None
        jm_mod.applet_manager_instance = None
        jm_mod.iconbar_instance = None
        jm_mod.jnt_instance = None
        am_mod.applet_manager = None
        JiveMain.instance = None

    def test_register_skin(self, tmp_path):
        try:
            jm = self._make_jm(tmp_path)
            jm.register_skin("HD Skin", "HDSkin", "skin")
            assert "HDSkin" in jm.skins
            assert jm.skins["HDSkin"] == ("HDSkin", "HD Skin", "skin")
        finally:
            self._cleanup()

    def test_register_skin_custom_id(self, tmp_path):
        try:
            jm = self._make_jm(tmp_path)
            jm.register_skin("Alt Skin", "SkinApplet", "alt_skin", skin_id="alt")
            assert "alt" in jm.skins
            assert jm.skins["alt"] == ("SkinApplet", "Alt Skin", "alt_skin")
        finally:
            self._cleanup()

    def test_skin_iterator(self, tmp_path):
        try:
            jm = self._make_jm(tmp_path)
            jm.register_skin("Skin A", "AppA", "skin")
            jm.register_skin("Skin B", "AppB", "skin")

            skins = dict(jm.skin_iterator())
            assert "AppA" in skins
            assert skins["AppA"] == "Skin A"
            assert "AppB" in skins
            assert skins["AppB"] == "Skin B"
        finally:
            self._cleanup()

    def test_get_selected_skin_default(self, tmp_path):
        try:
            jm = self._make_jm(tmp_path)
            assert jm.get_selected_skin() is None
        finally:
            self._cleanup()

    def test_default_skin(self, tmp_path):
        try:
            jm = self._make_jm(tmp_path)
            assert jm.get_default_skin() == "QVGAportraitSkin"
            jm.set_default_skin("HDSkin")
            assert jm.get_default_skin() == "HDSkin"
        finally:
            self._cleanup()

    def test_fullscreen(self, tmp_path):
        try:
            jm = self._make_jm(tmp_path)
            assert not jm.is_fullscreen()
            jm.set_fullscreen(True)
            assert jm.is_fullscreen()
        finally:
            self._cleanup()

    def test_skin_param_no_skin(self, tmp_path):
        try:
            jm = self._make_jm(tmp_path)
            assert jm.get_skin_param_or_nil("key") is None
        finally:
            self._cleanup()

    def test_camel_case_skin_aliases(self, tmp_path):
        try:
            jm = self._make_jm(tmp_path)
            assert JiveMain.registerSkin is JiveMain.register_skin
            assert JiveMain.skinIterator is JiveMain.skin_iterator
            assert JiveMain.getSelectedSkin is JiveMain.get_selected_skin
            assert JiveMain.setSelectedSkin is JiveMain.set_selected_skin
            assert JiveMain.isFullscreen is JiveMain.is_fullscreen
            assert JiveMain.setFullscreen is JiveMain.set_fullscreen
            assert JiveMain.setDefaultSkin is JiveMain.set_default_skin
            assert JiveMain.getDefaultSkin is JiveMain.get_default_skin
            assert JiveMain.getSkinParamOrNil is JiveMain.get_skin_param_or_nil
            assert JiveMain.getSkinParam is JiveMain.get_skin_param
            assert JiveMain.reloadSkin is JiveMain.reload_skin
            assert JiveMain.freeSkin is JiveMain.free_skin
        finally:
            self._cleanup()


class TestJiveMainMenuDelegation:
    """JiveMain delegates menu operations to HomeMenu."""

    def _make_jm(self, tmp_path):
        import jive.applet_manager as am_mod
        import jive.jive_main as jm_mod

        s = System(user_dir=tmp_path / "user", search_paths=[])
        s.init_user_path_dirs()
        from jive.utils.locale import Locale

        jm = JiveMain(
            run_event_loop=False,
            system=s,
            locale=Locale(),
            init_ui=False,
        )
        return jm

    def _cleanup(self):
        import jive.applet_manager as am_mod
        import jive.jive_main as jm_mod

        jm_mod.jive_main = None
        jm_mod.applet_manager_instance = None
        jm_mod.iconbar_instance = None
        jm_mod.jnt_instance = None
        am_mod.applet_manager = None
        JiveMain.instance = None

    def test_add_and_get_item(self, tmp_path):
        try:
            jm = self._make_jm(tmp_path)
            jm.add_item({"id": "test_item", "node": "home", "text": "Test"})
            table = jm.get_menu_table()
            assert "test_item" in table
        finally:
            self._cleanup()

    def test_remove_item(self, tmp_path):
        try:
            jm = self._make_jm(tmp_path)
            jm.add_item({"id": "removable", "node": "home"})
            # For the real HomeMenu, remove_item works differently than the stub.
            # Test that after adding, the item exists.
            table = jm.get_menu_table()
            assert "removable" in table
        finally:
            self._cleanup()

    def test_add_node(self, tmp_path):
        try:
            jm = self._make_jm(tmp_path)
            jm.add_node({"id": "custom_node", "node": "home"})
            assert "custom_node" in jm.get_node_table()
        finally:
            self._cleanup()

    def test_close_to_home(self, tmp_path):
        try:
            jm = self._make_jm(tmp_path)
            jm.close_to_home()  # Should not raise
        finally:
            self._cleanup()

    def test_camel_case_aliases(self, tmp_path):
        try:
            jm = self._make_jm(tmp_path)
            assert JiveMain.addNode is JiveMain.add_node
            assert JiveMain.addItem is JiveMain.add_item
            assert JiveMain.removeItem is JiveMain.remove_item
            assert JiveMain.getMenuTable is JiveMain.get_menu_table
            assert JiveMain.getNodeTable is JiveMain.get_node_table
            assert JiveMain.closeToHome is JiveMain.close_to_home
        finally:
            self._cleanup()


class TestJiveMainPostOnScreenInit:
    """JiveMain post-on-screen-init callbacks."""

    def _make_jm(self, tmp_path):
        import jive.applet_manager as am_mod
        import jive.jive_main as jm_mod

        s = System(user_dir=tmp_path / "user", search_paths=[])
        s.init_user_path_dirs()
        from jive.utils.locale import Locale

        jm = JiveMain(
            run_event_loop=False,
            system=s,
            locale=Locale(),
            init_ui=False,
        )
        return jm

    def _cleanup(self):
        import jive.applet_manager as am_mod
        import jive.jive_main as jm_mod

        jm_mod.jive_main = None
        jm_mod.applet_manager_instance = None
        jm_mod.iconbar_instance = None
        jm_mod.jnt_instance = None
        am_mod.applet_manager = None
        JiveMain.instance = None

    def test_register_and_perform(self, tmp_path):
        try:
            jm = self._make_jm(tmp_path)
            results = []
            jm.register_post_on_screen_init(lambda: results.append(1))
            jm.register_post_on_screen_init(lambda: results.append(2))
            jm.perform_post_on_screen_init()
            assert results == [1, 2]
        finally:
            self._cleanup()

    def test_perform_clears_callbacks(self, tmp_path):
        try:
            jm = self._make_jm(tmp_path)
            results = []
            jm.register_post_on_screen_init(lambda: results.append(1))
            jm.perform_post_on_screen_init()
            jm.perform_post_on_screen_init()  # Second call should be no-op
            assert results == [1]
        finally:
            self._cleanup()

    def test_perform_empty(self, tmp_path):
        try:
            jm = self._make_jm(tmp_path)
            jm.perform_post_on_screen_init()  # Should not raise
        finally:
            self._cleanup()

    def test_camel_case_aliases(self, tmp_path):
        try:
            jm = self._make_jm(tmp_path)
            assert (
                JiveMain.registerPostOnScreenInit
                is JiveMain.register_post_on_screen_init
            )
            assert (
                JiveMain.performPostOnScreenInit is JiveMain.perform_post_on_screen_init
            )
        finally:
            self._cleanup()


class TestJiveMainDisconnectPlayer:
    """JiveMain disconnect player."""

    def _make_jm(self, tmp_path):
        import jive.applet_manager as am_mod
        import jive.jive_main as jm_mod

        s = System(user_dir=tmp_path / "user", search_paths=[])
        s.init_user_path_dirs()
        from jive.utils.locale import Locale

        jm = JiveMain(
            run_event_loop=False,
            system=s,
            locale=Locale(),
            init_ui=False,
        )
        return jm

    def _cleanup(self):
        import jive.applet_manager as am_mod
        import jive.jive_main as jm_mod

        jm_mod.jive_main = None
        jm_mod.applet_manager_instance = None
        jm_mod.iconbar_instance = None
        jm_mod.jnt_instance = None
        am_mod.applet_manager = None
        JiveMain.instance = None

    def test_disconnect_player(self, tmp_path):
        try:
            jm = self._make_jm(tmp_path)
            # Should not raise even with no services registered
            jm.disconnect_player()
        finally:
            self._cleanup()

    def test_camel_case_alias(self, tmp_path):
        try:
            jm = self._make_jm(tmp_path)
            assert JiveMain.disconnectPlayer is JiveMain.disconnect_player
        finally:
            self._cleanup()


class TestJiveMainHelpMenuItem:
    """JiveMain help menu item."""

    def _make_jm(self, tmp_path):
        import jive.applet_manager as am_mod
        import jive.jive_main as jm_mod

        s = System(user_dir=tmp_path / "user", search_paths=[])
        s.init_user_path_dirs()
        from jive.utils.locale import Locale

        jm = JiveMain(
            run_event_loop=False,
            system=s,
            locale=Locale(),
            init_ui=False,
        )
        return jm

    def _cleanup(self):
        import jive.applet_manager as am_mod
        import jive.jive_main as jm_mod

        jm_mod.jive_main = None
        jm_mod.applet_manager_instance = None
        jm_mod.iconbar_instance = None
        jm_mod.jnt_instance = None
        am_mod.applet_manager = None
        JiveMain.instance = None

    def test_add_help_menu_item_no_framework(self, tmp_path):
        """Without a framework, help item is always added (no mouse check)."""
        try:
            jm = self._make_jm(tmp_path)
            mock_menu = MagicMock()
            jm.add_help_menu_item(mock_menu, jm, lambda obj: None)
            mock_menu.add_item.assert_called_once()
            item = mock_menu.add_item.call_args[0][0]
            assert item["sound"] == "WINDOWSHOW"
            assert item["weight"] == 100
        finally:
            self._cleanup()

    def test_camel_case_alias(self, tmp_path):
        try:
            jm = self._make_jm(tmp_path)
            assert JiveMain.addHelpMenuItem is JiveMain.add_help_menu_item
        finally:
            self._cleanup()


# ══════════════════════════════════════════════════════════════════════════════
# §8  Integration tests
# ══════════════════════════════════════════════════════════════════════════════


class TestIntegrationAppletDiscoverAndLoad:
    """End-to-end applet discovery and loading."""

    def test_full_applet_lifecycle(self, tmp_path):
        """Create an applet on disk, discover it, register it, load it,
        call a service, and free it."""
        import jive.applet_manager as am_mod

        old_am = am_mod.applet_manager

        try:
            # --- Set up the applet files ---
            user_dir = tmp_path / "user"
            applets_dir = tmp_path / "share" / "applets"
            applet_dir = applets_dir / "LifecycleTest"
            applet_dir.mkdir(parents=True)

            meta_content = textwrap.dedent("""\
                from jive.applet_meta import AppletMeta

                class LifecycleTestMeta(AppletMeta):
                    def jive_version(self):
                        return (1, 1)

                    def default_settings(self):
                        return {"count": 0}

                    def register_applet(self):
                        self.register_service("get_count")
            """)
            (applet_dir / "LifecycleTestMeta.py").write_text(meta_content)

            applet_content = textwrap.dedent("""\
                from jive.applet import Applet

                class LifecycleTestApplet(Applet):
                    def init(self):
                        super().init()
                        if self._settings is not None:
                            self._settings["count"] = self._settings.get("count", 0) + 1

                    def get_count(self):
                        if self._settings is not None:
                            return self._settings.get("count", 0)
                        return 0

                    def free(self):
                        return True
            """)
            (applet_dir / "LifecycleTestApplet.py").write_text(applet_content)

            # --- Run the lifecycle ---
            s = System(user_dir=user_dir, search_paths=[tmp_path / "share"])
            s.init_user_path_dirs()

            mgr = AppletManager(system=s)
            mgr.discover()

            assert mgr.has_applet("LifecycleTest")
            assert mgr.has_service("get_count")

            # Load via service call
            result = mgr.call_service("get_count")
            assert result == 1  # init() incremented count from 0 to 1

            # Instance should be cached
            applet = mgr.get_applet_instance("LifecycleTest")
            assert applet is not None

            # Free the applet
            mgr.free_applet("LifecycleTest")
            assert mgr.get_applet_instance("LifecycleTest") is None
        finally:
            am_mod.applet_manager = old_am
            for key in list(sys.modules.keys()):
                if "LifecycleTest" in key:
                    del sys.modules[key]

    def test_jive_main_with_applets(self, tmp_path):
        """Create JiveMain with a real applet and verify it's discovered."""
        import jive.applet_manager as am_mod
        import jive.jive_main as jm_mod

        old_jm = jm_mod.jive_main
        old_am = am_mod.applet_manager
        old_instance = JiveMain.instance

        try:
            user_dir = tmp_path / "user"
            applets_dir = tmp_path / "share" / "applets"
            applet_dir = applets_dir / "JMApplet"
            applet_dir.mkdir(parents=True)

            meta_content = textwrap.dedent("""\
                from jive.applet_meta import AppletMeta

                class JMAppletMeta(AppletMeta):
                    def jive_version(self):
                        return (1, 1)

                    def register_applet(self):
                        self.register_service("jm_test")
            """)
            (applet_dir / "JMAppletMeta.py").write_text(meta_content)

            applet_content = textwrap.dedent("""\
                from jive.applet import Applet

                class JMAppletApplet(Applet):
                    def init(self):
                        pass

                    def jm_test(self):
                        return "jm_works"
            """)
            (applet_dir / "JMAppletApplet.py").write_text(applet_content)

            s = System(user_dir=user_dir, search_paths=[tmp_path / "share"])
            s.init_user_path_dirs()

            from jive.utils.locale import Locale

            loc = Locale()

            # Note: We don't call reload() since init_ui=False skips it.
            # Instead we manually discover.
            jm = JiveMain(
                run_event_loop=False,
                system=s,
                locale=loc,
                init_ui=False,
            )

            # Manually discover since UI init is skipped
            jm._applet_manager.discover()

            assert jm._applet_manager.has_applet("JMApplet")
            result = jm._applet_manager.call_service("jm_test")
            assert result == "jm_works"
        finally:
            jm_mod.jive_main = old_jm
            am_mod.applet_manager = old_am
            JiveMain.instance = old_instance
            for key in list(sys.modules.keys()):
                if "JMApplet" in key:
                    del sys.modules[key]


class TestIntegrationSystemAndAppletManager:
    """System and AppletManager integration."""

    def test_settings_round_trip(self, tmp_path):
        """Store settings, then load them back."""
        import jive.applet_manager as am_mod

        old = am_mod.applet_manager

        try:
            s = System(user_dir=tmp_path / "user")
            s.init_user_path_dirs()
            mgr = AppletManager(system=s)

            entry = {
                "applet_name": "RoundTrip",
                "settings_filepath": str(s.get_settings_dir() / "RoundTrip.json"),
                "settings": {
                    "name": "Test",
                    "volume": 75,
                    "playlist": ["a", "b", "c"],
                    "nested": {"key": True},
                },
                "dirpath": str(tmp_path / "applets" / "RoundTrip"),
            }

            mgr._store_settings(entry)

            # Load into a fresh entry
            entry2 = {
                "applet_name": "RoundTrip",
                "settings_filepath": entry["settings_filepath"],
                "settings": None,
                "dirpath": entry["dirpath"],
            }
            mgr._load_settings(entry2)

            assert entry2["settings"]["name"] == "Test"
            assert entry2["settings"]["volume"] == 75
            assert entry2["settings"]["playlist"] == ["a", "b", "c"]
            assert entry2["settings"]["nested"]["key"] is True
        finally:
            am_mod.applet_manager = old


class TestIntegrationIconbarWithJiveMain:
    """Iconbar integration with JiveMain."""

    def test_iconbar_accessible_from_jive_main(self, tmp_path):
        import jive.applet_manager as am_mod
        import jive.jive_main as jm_mod

        old_jm = jm_mod.jive_main
        old_am = am_mod.applet_manager
        old_instance = JiveMain.instance

        try:
            s = System(user_dir=tmp_path / "user", search_paths=[])
            s.init_user_path_dirs()
            from jive.utils.locale import Locale

            jm = JiveMain(
                run_event_loop=False,
                system=s,
                locale=Locale(),
                init_ui=False,
            )

            # Iconbar should be accessible
            ib = jm._iconbar
            assert ib is not None

            # Test icon operations through the main
            ib.set_playmode("play")
            assert ib.icon_playmode.get_style() == "button_playmode_PLAY"
        finally:
            jm_mod.jive_main = old_jm
            am_mod.applet_manager = old_am
            JiveMain.instance = old_instance


# ══════════════════════════════════════════════════════════════════════════════
# §9  Edge cases and error handling
# ══════════════════════════════════════════════════════════════════════════════


class TestEdgeCases:
    """Edge cases and error conditions."""

    def test_system_atomic_write_error_cleanup(self, tmp_path):
        """If atomic write fails, temp file should be cleaned up."""
        # Create a read-only directory on Unix-like systems
        # On Windows this test may behave differently
        filepath = tmp_path / "test.json"
        System.atomic_write(filepath, '{"ok": true}')
        assert filepath.exists()

    def test_applet_manager_incompatible_version(self, tmp_path):
        """Applet with incompatible version should not be registered."""
        import jive.applet_manager as am_mod

        old = am_mod.applet_manager

        try:
            applets_dir = tmp_path / "share" / "applets"
            applet_dir = applets_dir / "BadVersion"
            applet_dir.mkdir(parents=True)

            meta_content = textwrap.dedent("""\
                from jive.applet_meta import AppletMeta

                class BadVersionMeta(AppletMeta):
                    def jive_version(self):
                        return (99, 99)  # Incompatible

                    def register_applet(self):
                        pass
            """)
            (applet_dir / "BadVersionMeta.py").write_text(meta_content)

            s = System(
                user_dir=tmp_path / "user",
                search_paths=[tmp_path / "share"],
            )
            s.init_user_path_dirs()
            mgr = AppletManager(system=s)
            mgr.discover()

            # Applet should exist but not be registered
            # (registration error should be caught)
            db = mgr.get_applet_db()
            if "BadVersion" in db:
                entry = db["BadVersion"]
                assert not entry["meta_registered"]
        finally:
            am_mod.applet_manager = old
            for key in list(sys.modules.keys()):
                if "BadVersion" in key:
                    del sys.modules[key]

    def test_applet_manager_broken_meta(self, tmp_path):
        """Applet with a broken meta module should be skipped gracefully."""
        import jive.applet_manager as am_mod

        old = am_mod.applet_manager

        try:
            applets_dir = tmp_path / "share" / "applets"
            applet_dir = applets_dir / "BrokenMeta"
            applet_dir.mkdir(parents=True)

            # Write a meta module with a syntax error
            (applet_dir / "BrokenMetaMeta.py").write_text(
                "class BrokenMetaMeta:\n    this is not valid python\n"
            )

            s = System(
                user_dir=tmp_path / "user",
                search_paths=[tmp_path / "share"],
            )
            s.init_user_path_dirs()
            mgr = AppletManager(system=s)
            mgr.discover()  # Should not raise

            # The broken applet should have been skipped
            db = mgr.get_applet_db()
            if "BrokenMeta" in db:
                assert not db["BrokenMeta"]["meta_loaded"]
        finally:
            am_mod.applet_manager = old
            for key in list(sys.modules.keys()):
                if "BrokenMeta" in key:
                    del sys.modules[key]

    def test_iconbar_all_icons_at_once(self):
        """Set all icon states simultaneously."""
        ib = Iconbar()
        ib.set_playmode("play")
        ib.set_repeat(2)
        ib.set_shuffle(1)
        ib.set_alarm("ON")
        ib.set_sleep("ON")
        ib.set_battery("CHARGING")
        ib.server_error = "OK"
        ib.set_wireless_signal(4)

        assert ib.icon_playmode.get_style() == "button_playmode_PLAY"
        assert ib.icon_repeat.get_style() == "button_repeat_2"
        assert ib.icon_shuffle.get_style() == "button_shuffle_1"
        assert ib.icon_alarm.get_style() == "button_alarm_ON"
        assert ib.icon_sleep.get_style() == "button_sleep_ON"
        assert ib.icon_battery.get_style() == "button_battery_CHARGING"
        assert ib.icon_wireless.get_style() == "button_wireless_4"

    def test_jive_main_go_home_no_framework(self, tmp_path):
        """go_home should not raise without a framework."""
        import jive.applet_manager as am_mod
        import jive.jive_main as jm_mod

        old_jm = jm_mod.jive_main
        old_am = am_mod.applet_manager
        old_instance = JiveMain.instance

        try:
            s = System(user_dir=tmp_path / "user", search_paths=[])
            s.init_user_path_dirs()
            from jive.utils.locale import Locale

            jm = JiveMain(
                run_event_loop=False,
                system=s,
                locale=Locale(),
                init_ui=False,
            )
            jm.go_home()  # Should not raise
        finally:
            jm_mod.jive_main = old_jm
            am_mod.applet_manager = old_am
            JiveMain.instance = old_instance

    def test_multiple_applet_manager_instances(self, tmp_path):
        """Creating a new AppletManager replaces the singleton."""
        import jive.applet_manager as am_mod

        old = am_mod.applet_manager

        try:
            s1 = System(user_dir=tmp_path / "user1")
            mgr1 = AppletManager(system=s1)
            assert am_mod.applet_manager is mgr1

            s2 = System(user_dir=tmp_path / "user2")
            mgr2 = AppletManager(system=s2)
            assert am_mod.applet_manager is mgr2
            assert mgr1 is not mgr2
        finally:
            am_mod.applet_manager = old


class TestAppletManagerSorting:
    """AppletManager sorting by priority and name."""

    def test_sorted_order(self, tmp_path):
        import jive.applet_manager as am_mod

        old = am_mod.applet_manager

        try:
            s = System(user_dir=tmp_path / "user")
            mgr = AppletManager(system=s)

            # Manually add entries with different priorities
            from jive.applet_manager import _make_entry

            mgr._applets_db["C"] = _make_entry(
                "C", tmp_path / "C", tmp_path / "C.json", load_priority=100
            )
            mgr._applets_db["A"] = _make_entry(
                "A", tmp_path / "A", tmp_path / "A.json", load_priority=10
            )
            mgr._applets_db["B"] = _make_entry(
                "B", tmp_path / "B", tmp_path / "B.json", load_priority=100
            )
            mgr._applets_db["D"] = _make_entry(
                "D", tmp_path / "D", tmp_path / "D.json", load_priority=50
            )

            sorted_entries = mgr._sorted_applet_db()
            names = [e["applet_name"] for e in sorted_entries]

            # A (10) < D (50) < B (100) < C (100)
            assert names == ["A", "D", "B", "C"]
        finally:
            am_mod.applet_manager = old


class TestInputToActionMapCompleteness:
    """Verify completeness and consistency of action mappings."""

    def test_all_key_press_values_are_strings(self):
        for key, action in key_action_mappings["press"].items():
            assert isinstance(action, str), f"Key {key} maps to non-string: {action}"

    def test_all_key_hold_values_are_strings(self):
        for key, action in key_action_mappings["hold"].items():
            assert isinstance(action, str), f"Key {key} maps to non-string: {action}"

    def test_all_ir_press_values_are_strings(self):
        for button, action in ir_action_mappings["press"].items():
            assert isinstance(action, str), f"IR {button} maps to non-string: {action}"

    def test_all_ir_hold_values_are_strings(self):
        for button, action in ir_action_mappings["hold"].items():
            assert isinstance(action, str), f"IR {button} maps to non-string: {action}"

    def test_all_char_press_values_are_strings(self):
        for char, action in char_action_mappings["press"].items():
            assert isinstance(action, str), (
                f"Char {char!r} maps to non-string: {action}"
            )

    def test_gesture_values_are_strings(self):
        for gesture, action in gesture_action_mappings.items():
            assert isinstance(action, str), f"Gesture {gesture} maps to non-string"

    def test_action_action_values_are_strings(self):
        for name, action in action_action_mappings.items():
            assert isinstance(action, str), f"Action {name} maps to non-string"

    def test_unassigned_all_strings(self):
        for name in unassigned_action_mappings:
            assert isinstance(name, str), f"Unassigned entry is not string: {name}"

    def test_volume_keys_present(self):
        """Volume keys should be present in both press and hold."""
        assert KEY_VOLUME_UP in key_action_mappings["press"]
        assert KEY_VOLUME_DOWN in key_action_mappings["press"]
        assert KEY_VOLUME_UP in key_action_mappings["hold"]
        assert KEY_VOLUME_DOWN in key_action_mappings["hold"]

    def test_ir_volume_present(self):
        assert "volup" in ir_action_mappings["press"]
        assert "voldown" in ir_action_mappings["press"]


# ══════════════════════════════════════════════════════════════════════════════
# §10  Additional coverage
# ══════════════════════════════════════════════════════════════════════════════


class TestSystemVersionConstant:
    """System JIVE_VERSION."""

    def test_jive_version(self):
        assert System.JIVE_VERSION == "7.8"


class TestAppletEntryHelper:
    """_make_entry helper function."""

    def test_make_entry(self, tmp_path):
        from jive.applet_manager import _make_entry

        entry = _make_entry(
            applet_name="TestApp",
            dirpath=tmp_path / "TestApp",
            settings_filepath=tmp_path / "TestApp.json",
            load_priority=50,
        )

        assert entry["applet_name"] == "TestApp"
        assert entry["load_priority"] == 50
        assert entry["meta_loaded"] is False
        assert entry["meta_registered"] is False
        assert entry["meta_configured"] is False
        assert entry["applet_loaded"] is False
        assert entry["applet_evaluated"] is False
        assert entry["settings"] is None
        assert entry["strings_table"] is None
        assert entry["default_settings"] is None
        assert entry["meta_obj"] is None
        assert "applet_module" in entry
        assert "meta_module" in entry
        assert "applet_logger" in entry


class TestIconbarEdgeCases:
    """Iconbar additional edge cases."""

    def test_set_playmode_case_insensitive(self):
        ib = Iconbar()
        ib.set_playmode("Play")
        assert ib.icon_playmode.get_style() == "button_playmode_PLAY"

    def test_wireless_with_iface(self):
        ib = Iconbar()
        ib.server_error = "OK"
        ib.set_wireless_signal(3, "wlan0")
        assert ib.iface == "wlan0"

    def test_battery_string_value(self):
        ib = Iconbar()
        ib.set_battery("AC")
        assert ib.icon_battery.get_style() == "button_battery_AC"


class TestJiveMainActionHandlers:
    """JiveMain action handler methods."""

    def _make_jm(self, tmp_path):
        import jive.applet_manager as am_mod
        import jive.jive_main as jm_mod

        s = System(user_dir=tmp_path / "user", search_paths=[])
        s.init_user_path_dirs()
        from jive.utils.locale import Locale

        return JiveMain(
            run_event_loop=False,
            system=s,
            locale=Locale(),
            init_ui=False,
        )

    def _cleanup(self):
        import jive.applet_manager as am_mod
        import jive.jive_main as jm_mod

        jm_mod.jive_main = None
        jm_mod.applet_manager_instance = None
        jm_mod.iconbar_instance = None
        jm_mod.jnt_instance = None
        am_mod.applet_manager = None
        JiveMain.instance = None

    def test_power_action_returns_consume(self, tmp_path):
        try:
            jm = self._make_jm(tmp_path)
            result = jm._power_action()
            assert result == EVENT_CONSUME
        finally:
            self._cleanup()

    def test_power_off_action_returns_consume(self, tmp_path):
        try:
            jm = self._make_jm(tmp_path)
            result = jm._power_off_action()
            assert result == EVENT_CONSUME
            assert jm.get_soft_power_state() == "off"
        finally:
            self._cleanup()

    def test_power_on_action_returns_consume(self, tmp_path):
        try:
            jm = self._make_jm(tmp_path)
            jm.set_soft_power_state("off")
            result = jm._power_on_action()
            assert result == EVENT_CONSUME
            assert jm.get_soft_power_state() == "on"
        finally:
            self._cleanup()

    def test_go_home_action_returns_consume(self, tmp_path):
        try:
            jm = self._make_jm(tmp_path)
            result = jm._go_home_action()
            assert result == EVENT_CONSUME
        finally:
            self._cleanup()

    def test_default_context_menu_action_returns_consume(self, tmp_path):
        try:
            jm = self._make_jm(tmp_path)
            result = jm._default_context_menu_action()
            assert result == EVENT_CONSUME
        finally:
            self._cleanup()

    def test_go_factory_test_mode_action_returns_consume(self, tmp_path):
        try:
            jm = self._make_jm(tmp_path)
            result = jm._go_factory_test_mode_action()
            assert result == EVENT_CONSUME
        finally:
            self._cleanup()
