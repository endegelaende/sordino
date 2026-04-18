"""Tests for jive.system.System — system properties and hardware capabilities."""

from __future__ import annotations

import platform
import re
from pathlib import Path

import pytest

from jive.system import System

# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------


class TestIdentity:
    """Machine, arch, UUID, MAC address."""

    def test_default_machine(self) -> None:
        s = System()
        assert s.get_machine() == "jivelite"

    def test_default_arch(self) -> None:
        s = System()
        expected = platform.machine() or "unknown"
        assert s.get_arch() == expected

    def test_custom_machine(self) -> None:
        s = System(machine="squeezeplay")
        assert s.get_machine() == "squeezeplay"

    def test_custom_arch(self) -> None:
        s = System(arch="armv7l")
        assert s.get_arch() == "armv7l"

    def test_set_machine(self) -> None:
        s = System()
        s.set_machine("jive")
        assert s.get_machine() == "jive"

    def test_is_hardware_false_for_jivelite(self) -> None:
        s = System()
        assert s.is_hardware() is False

    def test_is_hardware_true_for_other(self) -> None:
        s = System(machine="jive")
        assert s.is_hardware() is True

    def test_is_hardware_true_for_squeezeplay(self) -> None:
        s = System(machine="squeezeplay")
        assert s.is_hardware() is True

    def test_get_uuid_is_string(self) -> None:
        s = System()
        uid = s.get_uuid()
        assert isinstance(uid, str)
        # Should be a valid UUID4 format
        uuid_re = re.compile(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
            re.IGNORECASE,
        )
        assert uuid_re.match(uid), f"Not a valid UUID: {uid!r}"

    def test_custom_uuid(self) -> None:
        s = System(uuid_str="test-uuid-1234")
        assert s.get_uuid() == "test-uuid-1234"

    def test_get_mac_address_format(self) -> None:
        s = System()
        mac = s.get_mac_address()
        assert isinstance(mac, str)
        # Colon-separated, 6 octets
        parts = mac.split(":")
        assert len(parts) == 6
        for part in parts:
            assert len(part) == 2
            int(part, 16)  # must be valid hex

    def test_get_mac_address_logitech_oui(self) -> None:
        s = System()
        mac = s.get_mac_address()
        assert mac.startswith("00:04:20:")

    def test_custom_mac(self) -> None:
        s = System(mac_address="aa:bb:cc:dd:ee:ff")
        assert s.get_mac_address() == "aa:bb:cc:dd:ee:ff"

    def test_two_instances_same_mac(self) -> None:
        """Without custom MAC, the generated address is deterministic per host."""
        s1 = System()
        s2 = System()
        assert s1.get_mac_address() == s2.get_mac_address()

    def test_two_instances_different_uuid(self) -> None:
        """Each instance generates a fresh UUID by default."""
        s1 = System()
        s2 = System()
        assert s1.get_uuid() != s2.get_uuid()


# ---------------------------------------------------------------------------
# JIVE_VERSION
# ---------------------------------------------------------------------------


class TestJiveVersion:
    """JIVE_VERSION class attribute."""

    def test_jive_version(self) -> None:
        assert System.JIVE_VERSION == "7.8"

    def test_jive_version_on_instance(self) -> None:
        s = System()
        assert s.JIVE_VERSION == "7.8"


# ---------------------------------------------------------------------------
# Capabilities
# ---------------------------------------------------------------------------


class TestCapabilities:
    """Hardware capability management."""

    def test_set_capabilities(self) -> None:
        s = System()
        s.set_capabilities({"touch": 1, "ir": 1})
        assert s.has_touch() is True
        assert s.has_ir() is True

    def test_has_volume_knob_false_when_not_set(self) -> None:
        s = System()
        assert s.has_volume_knob() is False

    def test_has_volume_knob_true_when_set(self) -> None:
        s = System()
        s.set_capabilities({"volumeKnob": 1})
        assert s.has_volume_knob() is True

    def test_add_capability(self) -> None:
        s = System()
        assert s.has_touch() is False
        s.add_capability("touch")
        assert s.has_touch() is True

    def test_remove_capability(self) -> None:
        s = System()
        s.set_capabilities({"touch": 1})
        assert s.has_touch() is True
        s.remove_capability("touch")
        assert s.has_touch() is False

    def test_remove_nonexistent_capability(self) -> None:
        """Removing a capability that was never set should not raise."""
        s = System()
        s.remove_capability("touch")  # no-op
        assert s.has_touch() is False

    def test_has_capability_generic(self) -> None:
        s = System()
        s.add_capability("ir")
        assert s.has_capability("ir") is True
        assert s.has_capability("touch") is False

    def test_set_capabilities_replaces(self) -> None:
        """set_capabilities replaces previous capabilities entirely."""
        s = System()
        s.set_capabilities({"touch": 1})
        s.set_capabilities({"ir": 1})
        assert s.has_touch() is False
        assert s.has_ir() is True

    # --- Soft power ---

    def test_has_soft_power_via_touch(self) -> None:
        s = System()
        s.set_capabilities({"touch": 1})
        assert s.has_soft_power() is True

    def test_has_soft_power_via_power_key(self) -> None:
        s = System()
        s.set_capabilities({"powerKey": 1})
        assert s.has_soft_power() is True

    def test_has_soft_power_false_when_neither(self) -> None:
        s = System()
        assert s.has_soft_power() is False

    # --- Local storage ---

    def test_has_local_storage_via_usb(self) -> None:
        s = System()
        s.set_capabilities({"usb": 1})
        assert s.has_local_storage() is True

    def test_has_local_storage_via_sdcard(self) -> None:
        s = System()
        s.set_capabilities({"sdcard": 1})
        assert s.has_local_storage() is True

    def test_has_local_storage_not_hardware(self) -> None:
        """jivelite (not hardware) always has local storage."""
        s = System()
        assert s.is_hardware() is False
        assert s.has_local_storage() is True

    def test_has_local_storage_false_on_hardware_without_storage(self) -> None:
        s = System(machine="jive")
        assert s.is_hardware() is True
        assert s.has_local_storage() is False

    # --- All has_* convenience methods ---

    def test_has_tiny_sc(self) -> None:
        s = System()
        assert s.has_tiny_sc() is False
        s.add_capability("hasTinySC")
        assert s.has_tiny_sc() is True

    def test_has_digital_out(self) -> None:
        s = System()
        assert s.has_digital_out() is False
        s.add_capability("hasDigitalOut")
        assert s.has_digital_out() is True

    def test_has_home_as_power_key(self) -> None:
        s = System()
        assert s.has_home_as_power_key() is False
        s.add_capability("homeAsPowerKey")
        assert s.has_home_as_power_key() is True

    def test_has_power_key(self) -> None:
        s = System()
        assert s.has_power_key() is False
        s.add_capability("powerKey")
        assert s.has_power_key() is True

    def test_has_mute_key(self) -> None:
        s = System()
        assert s.has_mute_key() is False
        s.add_capability("muteKey")
        assert s.has_mute_key() is True

    def test_has_audio_by_default(self) -> None:
        s = System()
        assert s.has_audio_by_default() is False
        s.add_capability("audioByDefault")
        assert s.has_audio_by_default() is True

    def test_has_wired_networking(self) -> None:
        s = System()
        assert s.has_wired_networking() is False
        s.add_capability("wiredNetworking")
        assert s.has_wired_networking() is True

    def test_has_device_rotation(self) -> None:
        s = System()
        assert s.has_device_rotation() is False
        s.add_capability("deviceRotation")
        assert s.has_device_rotation() is True

    def test_has_core_keys(self) -> None:
        s = System()
        assert s.has_core_keys() is False
        s.add_capability("coreKeys")
        assert s.has_core_keys() is True

    def test_has_preset_keys(self) -> None:
        s = System()
        assert s.has_preset_keys() is False
        s.add_capability("presetKeys")
        assert s.has_preset_keys() is True

    def test_has_alarm_key(self) -> None:
        s = System()
        assert s.has_alarm_key() is False
        s.add_capability("alarmKey")
        assert s.has_alarm_key() is True

    def test_has_usb(self) -> None:
        s = System()
        assert s.has_usb() is False
        s.add_capability("usb")
        assert s.has_usb() is True

    def test_has_sd_card(self) -> None:
        s = System()
        assert s.has_sd_card() is False
        s.add_capability("sdcard")
        assert s.has_sd_card() is True

    def test_has_battery_capability(self) -> None:
        s = System()
        assert s.has_battery_capability() is False
        s.add_capability("batteryCapable")
        assert s.has_battery_capability() is True

    def test_has_ir_blaster_capability(self) -> None:
        s = System()
        assert s.has_ir_blaster_capability() is False
        s.add_capability("IRBlasterCapable")
        assert s.has_ir_blaster_capability() is True

    # --- Touchpad correction ---

    def test_touchpad_bottom_correction_default(self) -> None:
        s = System()
        assert s.get_touchpad_bottom_correction() == 0

    def test_set_touchpad_bottom_correction(self) -> None:
        s = System()
        s.set_touchpad_bottom_correction(42)
        assert s.get_touchpad_bottom_correction() == 42


# ---------------------------------------------------------------------------
# User paths
# ---------------------------------------------------------------------------


class TestPaths:
    """User directories, settings, applets."""

    def test_get_user_dir_returns_path(self) -> None:
        s = System()
        assert isinstance(s.get_user_dir(), Path)

    def test_get_settings_dir(self) -> None:
        s = System()
        assert s.get_settings_dir() == s.get_user_dir() / "settings"

    def test_get_user_applets_dir(self) -> None:
        s = System()
        assert s.get_user_applets_dir() == s.get_user_dir() / "applets"

    def test_custom_user_dir(self) -> None:
        s = System(user_dir="/custom/path")
        assert s.get_user_dir() == Path("/custom/path")
        assert s.get_settings_dir() == Path("/custom/path/settings")
        assert s.get_user_applets_dir() == Path("/custom/path/applets")

    def test_custom_user_dir_as_path(self) -> None:
        p = Path("/another/path")
        s = System(user_dir=p)
        assert s.get_user_dir() == p

    def test_init_user_path_dirs(self, tmp_path: Path) -> None:
        user_dir = tmp_path / "test_user"
        s = System(user_dir=user_dir)
        # Directories should not exist yet
        assert not user_dir.exists()
        s.init_user_path_dirs()
        assert user_dir.is_dir()
        assert (user_dir / "settings").is_dir()
        assert (user_dir / "applets").is_dir()

    def test_init_user_path_dirs_idempotent(self, tmp_path: Path) -> None:
        user_dir = tmp_path / "test_user"
        s = System(user_dir=user_dir)
        s.init_user_path_dirs()
        s.init_user_path_dirs()  # should not raise
        assert user_dir.is_dir()


# ---------------------------------------------------------------------------
# Search paths
# ---------------------------------------------------------------------------


class TestSearchPaths:
    """Search path management and file finding."""

    def test_search_paths_property(self) -> None:
        s = System(search_paths=["/a", "/b"])
        paths = s.search_paths
        assert paths == [Path("/a"), Path("/b")]

    def test_search_paths_returns_copy(self) -> None:
        s = System(search_paths=["/a"])
        paths = s.search_paths
        paths.append(Path("/b"))
        assert len(s.search_paths) == 1

    def test_search_paths_setter(self) -> None:
        s = System(search_paths=["/a"])
        s.search_paths = ["/x", "/y"]
        assert s.search_paths == [Path("/x"), Path("/y")]

    def test_add_search_path_append(self) -> None:
        s = System(search_paths=["/a"])
        s.add_search_path("/b")
        assert s.search_paths == [Path("/a"), Path("/b")]

    def test_add_search_path_prepend(self) -> None:
        s = System(search_paths=["/a"])
        s.add_search_path("/b", prepend=True)
        assert s.search_paths == [Path("/b"), Path("/a")]

    def test_add_search_path_no_duplicate(self) -> None:
        s = System(search_paths=["/a"])
        s.add_search_path("/a")
        assert len(s.search_paths) == 1

    def test_find_file_found(self, tmp_path: Path) -> None:
        d = tmp_path / "share"
        d.mkdir()
        (d / "test.txt").write_text("hello")
        s = System(search_paths=[str(d)])
        result = s.find_file("test.txt")
        assert result is not None
        assert result.exists()
        assert result == d / "test.txt"

    def test_find_file_not_found(self, tmp_path: Path) -> None:
        s = System(search_paths=[str(tmp_path)])
        result = s.find_file("nonexistent.txt")
        assert result is None

    def test_find_file_searches_in_order(self, tmp_path: Path) -> None:
        d1 = tmp_path / "first"
        d2 = tmp_path / "second"
        d1.mkdir()
        d2.mkdir()
        (d1 / "file.txt").write_text("first")
        (d2 / "file.txt").write_text("second")
        s = System(search_paths=[str(d1), str(d2)])
        result = s.find_file("file.txt")
        assert result == d1 / "file.txt"

    def test_find_file_subdirectory(self, tmp_path: Path) -> None:
        d = tmp_path / "base"
        sub = d / "sub"
        sub.mkdir(parents=True)
        (sub / "deep.txt").write_text("deep")
        s = System(search_paths=[str(d)])
        result = s.find_file("sub/deep.txt")
        assert result is not None
        assert result.exists()

    def test_find_all_files(self, tmp_path: Path) -> None:
        d1 = tmp_path / "first"
        d2 = tmp_path / "second"
        d1.mkdir()
        d2.mkdir()
        (d1 / "file.txt").write_text("first")
        (d2 / "file.txt").write_text("second")
        s = System(search_paths=[str(d1), str(d2)])
        results = s.find_all_files("file.txt")
        assert len(results) == 2
        assert d1 / "file.txt" in results
        assert d2 / "file.txt" in results

    def test_find_all_files_empty(self, tmp_path: Path) -> None:
        s = System(search_paths=[str(tmp_path)])
        results = s.find_all_files("nope.txt")
        assert results == []

    def test_find_all_files_partial(self, tmp_path: Path) -> None:
        d1 = tmp_path / "first"
        d2 = tmp_path / "second"
        d1.mkdir()
        d2.mkdir()
        (d1 / "file.txt").write_text("only here")
        s = System(search_paths=[str(d1), str(d2)])
        results = s.find_all_files("file.txt")
        assert len(results) == 1


# ---------------------------------------------------------------------------
# Atomic write
# ---------------------------------------------------------------------------


class TestAtomicWrite:
    """Atomic file writing."""

    def test_atomic_write_creates_file(self, tmp_path: Path) -> None:
        target = tmp_path / "out.txt"
        System.atomic_write(target, "hello world")
        assert target.read_text(encoding="utf-8") == "hello world"

    def test_atomic_write_creates_parent_dirs(self, tmp_path: Path) -> None:
        target = tmp_path / "deep" / "nested" / "out.txt"
        System.atomic_write(target, "nested content")
        assert target.exists()
        assert target.read_text(encoding="utf-8") == "nested content"

    def test_atomic_write_overwrites_existing(self, tmp_path: Path) -> None:
        target = tmp_path / "out.txt"
        target.write_text("old content", encoding="utf-8")
        System.atomic_write(target, "new content")
        assert target.read_text(encoding="utf-8") == "new content"

    def test_atomic_write_string_path(self, tmp_path: Path) -> None:
        target = str(tmp_path / "str_path.txt")
        System.atomic_write(target, "via string")
        assert Path(target).read_text(encoding="utf-8") == "via string"

    def test_atomic_write_empty_content(self, tmp_path: Path) -> None:
        target = tmp_path / "empty.txt"
        System.atomic_write(target, "")
        assert target.read_text(encoding="utf-8") == ""

    def test_atomic_write_unicode(self, tmp_path: Path) -> None:
        target = tmp_path / "unicode.txt"
        System.atomic_write(target, "café ☕ 日本語")
        assert target.read_text(encoding="utf-8") == "café ☕ 日本語"

    def test_atomic_write_no_temp_file_left(self, tmp_path: Path) -> None:
        target = tmp_path / "clean.txt"
        System.atomic_write(target, "content")
        # Only the target file should exist
        files = list(tmp_path.iterdir())
        assert len(files) == 1
        assert files[0].name == "clean.txt"


# ---------------------------------------------------------------------------
# Repr
# ---------------------------------------------------------------------------


class TestRepr:
    """__repr__ output."""

    def test_repr_contains_machine(self) -> None:
        s = System(machine="testmachine")
        r = repr(s)
        assert "testmachine" in r

    def test_repr_contains_capabilities(self) -> None:
        s = System()
        s.set_capabilities({"touch": 1, "ir": 1})
        r = repr(s)
        assert "touch" in r
        assert "ir" in r

    def test_repr_no_capabilities(self) -> None:
        s = System()
        r = repr(s)
        assert "none" in r
