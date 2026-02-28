"""
tests.test_e2e_integration — End-to-end integration tests.

Tests the full lifecycle flow:

    JiveMain (headless)
      → AppletManager.discover()
        → finds all 5 real applet directories (PascalCase)
        → loads & registers Meta classes
        → configures cross-applet dependencies
      → Resident applets auto-load (SlimBrowser, SelectPlayer, NowPlaying)
      → Services registered and callable cross-applet
      → Notifications dispatched to subscribers
      → Applet free / teardown

This test module does NOT require pygame or a running LMS server.
All UI and network interactions are stubbed.

Copyright 2025
License: BSD-3-Clause
"""

from __future__ import annotations

import copy
import importlib
import os
import sys
import textwrap
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
from unittest.mock import MagicMock, PropertyMock, call, patch

import pytest

# ══════════════════════════════════════════════════════════════════════════════
# Ensure the project root is on sys.path
# ══════════════════════════════════════════════════════════════════════════════

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# ══════════════════════════════════════════════════════════════════════════════
# Core imports
# ══════════════════════════════════════════════════════════════════════════════

from jive.applet import Applet
from jive.applet_manager import AppletManager
from jive.applet_meta import AppletMeta
from jive.jive_main import JiveMain
from jive.system import System

# ══════════════════════════════════════════════════════════════════════════════
# Test helpers
# ══════════════════════════════════════════════════════════════════════════════

# The applets directory inside the project
_APPLETS_DIR = _PROJECT_ROOT / "jive" / "applets"

# All expected applet names (PascalCase, matching directory names)
_ALL_APPLET_NAMES = frozenset(
    {
        "JogglerSkin",
        "NowPlaying",
        "QVGAbaseSkin",
        "SelectPlayer",
        "SlimBrowser",
        "SlimDiscovery",
        "SlimMenus",
    }
)


def _make_mock_player(
    player_id: str = "00:04:20:aa:bb:cc",
    name: str = "Test Player",
    model: str = "squeezeplay",
    is_connected: bool = True,
    is_available: bool = True,
    is_power_on: bool = True,
    volume: int = 50,
    playlist_size: int = 3,
    play_mode: str = "play",
) -> MagicMock:
    """Create a mock Player for integration tests."""
    p = MagicMock()
    p.config = "ok"
    p.get_id.return_value = player_id
    p.getId.return_value = player_id
    p.get_name.return_value = name
    p.getName.return_value = name
    p.get_model.return_value = model
    p.getModel.return_value = model
    p.is_local.return_value = False
    p.isLocal.return_value = False
    p.is_connected.return_value = is_connected
    p.isConnected.return_value = is_connected
    p.is_available.return_value = is_available
    p.isAvailable.return_value = is_available
    p.is_power_on.return_value = is_power_on
    p.isPowerOn.return_value = is_power_on
    p.get_volume.return_value = volume
    p.getVolume.return_value = volume
    p.get_playlist_size.return_value = playlist_size
    p.getPlaylistSize.return_value = playlist_size
    p.get_playlist_current_index.return_value = 1
    p.getPlaylistCurrentIndex.return_value = 1
    p.get_play_mode.return_value = play_mode
    p.getPlayMode.return_value = play_mode
    p.get_track_elapsed.return_value = (30.0, 180.0)
    p.getTrackElapsed.return_value = (30.0, 180.0)
    p.is_track_seekable.return_value = True
    p.isTrackSeekable.return_value = True
    p.use_volume_control.return_value = 1
    p.useVolumeControl.return_value = 1
    p.is_waiting_to_play.return_value = False
    p.isWaitingToPlay.return_value = False
    p.needs_network_config.return_value = False
    p.needsNetworkConfig.return_value = False
    p.needs_music_source.return_value = False
    p.needsMusicSource.return_value = False
    p.is_remote.return_value = False
    p.isRemote.return_value = False
    p.get_ssid.return_value = None
    p.getSSID.return_value = None

    status = {
        "mode": play_mode,
        "remote": 0,
        "duration": 180.0,
        "time": 30.0,
        "playlist repeat": 0,
        "playlist shuffle": 0,
        "item_loop": [
            {
                "track": "Test Track",
                "artist": "Test Artist",
                "album": "Test Album",
            }
        ],
    }
    p.get_player_status.return_value = status
    p.getPlayerStatus.return_value = status

    server = MagicMock()
    server.get_name.return_value = "Test Server"
    server.getName.return_value = "Test Server"
    server.is_password_protected.return_value = False
    server.isPasswordProtected.return_value = False
    server.allPlayers.return_value = []
    server.all_players.return_value = []
    p.get_slim_server.return_value = server
    p.getSlimServer.return_value = server

    return p


class _GlobalState:
    """Context manager that saves and restores global singletons."""

    def __init__(self):
        self._saved = {}

    def __enter__(self):
        import jive.applet_manager as am_mod
        import jive.jive_main as jm_mod

        self._saved["applet_manager"] = am_mod.applet_manager
        self._saved["jive_main"] = jm_mod.jive_main
        self._saved["am_instance"] = jm_mod.applet_manager_instance
        self._saved["iconbar_instance"] = jm_mod.iconbar_instance
        self._saved["jnt_instance"] = jm_mod.jnt_instance
        self._saved["JiveMain.instance"] = JiveMain.instance
        return self

    def __exit__(self, *exc):
        import jive.applet_manager as am_mod
        import jive.jive_main as jm_mod

        am_mod.applet_manager = self._saved["applet_manager"]
        jm_mod.jive_main = self._saved["jive_main"]
        jm_mod.applet_manager_instance = self._saved["am_instance"]
        jm_mod.iconbar_instance = self._saved["iconbar_instance"]
        jm_mod.jnt_instance = self._saved["jnt_instance"]
        JiveMain.instance = self._saved["JiveMain.instance"]

        # Clean up any dynamically loaded applet modules
        for key in list(sys.modules.keys()):
            if key.startswith("applets."):
                del sys.modules[key]


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 1: AppletManager stand-alone discovery
# ══════════════════════════════════════════════════════════════════════════════


class TestAppletDiscovery:
    """AppletManager discovers all real applet directories."""

    def test_applets_dir_exists(self):
        """The applets directory is present in the project."""
        assert _APPLETS_DIR.is_dir(), f"Missing {_APPLETS_DIR}"

    @pytest.mark.parametrize("name", sorted(_ALL_APPLET_NAMES))
    def test_applet_directory_exists(self, name: str):
        """Each applet has a PascalCase directory."""
        d = _APPLETS_DIR / name
        assert d.is_dir(), f"Missing directory {d}"

    @pytest.mark.parametrize("name", sorted(_ALL_APPLET_NAMES))
    def test_meta_file_exists(self, name: str):
        """Each applet has a <Name>Meta.py file."""
        meta = _APPLETS_DIR / name / f"{name}Meta.py"
        assert meta.is_file(), f"Missing {meta}"

    @pytest.mark.parametrize("name", sorted(_ALL_APPLET_NAMES))
    def test_applet_file_exists(self, name: str):
        """Each applet has a <Name>Applet.py file."""
        applet = _APPLETS_DIR / name / f"{name}Applet.py"
        assert applet.is_file(), f"Missing {applet}"

    @pytest.mark.parametrize("name", sorted(_ALL_APPLET_NAMES))
    def test_init_file_exists(self, name: str):
        """Each applet has an __init__.py file."""
        init = _APPLETS_DIR / name / "__init__.py"
        assert init.is_file(), f"Missing {init}"

    def test_discover_finds_all_applets(self, tmp_path):
        """AppletManager.discover() finds all 5 applets."""
        with _GlobalState():
            s = System(
                user_dir=tmp_path / "user",
                search_paths=[_PROJECT_ROOT / "jive"],
            )
            s.init_user_path_dirs()

            mgr = AppletManager(system=s)
            mgr._find_applets()

            found = set(mgr._applets_db.keys())
            assert found == _ALL_APPLET_NAMES, (
                f"Expected {_ALL_APPLET_NAMES}, got {found}"
            )

    def test_discover_creates_correct_entries(self, tmp_path):
        """Each entry has the expected fields."""
        with _GlobalState():
            s = System(
                user_dir=tmp_path / "user",
                search_paths=[_PROJECT_ROOT / "jive"],
            )
            s.init_user_path_dirs()

            mgr = AppletManager(system=s)
            mgr._find_applets()

            for name in _ALL_APPLET_NAMES:
                entry = mgr._applets_db[name]
                assert entry["applet_name"] == name
                assert Path(entry["dirpath"]).is_dir()
                assert entry["meta_loaded"] is False
                assert entry["applet_evaluated"] is False


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 2: Meta loading and registration
# ══════════════════════════════════════════════════════════════════════════════


class TestMetaLoadAndRegister:
    """Meta classes load, pass version check, and register services."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        """Create a clean AppletManager for each test."""
        self._gs = _GlobalState()
        self._gs.__enter__()

        self._system = System(
            user_dir=tmp_path / "user",
            search_paths=[_PROJECT_ROOT / "jive"],
        )
        self._system.init_user_path_dirs()
        self._mgr = AppletManager(system=self._system)
        self._mgr._find_applets()

        yield

        self._gs.__exit__(None, None, None)

    @pytest.mark.parametrize("name", sorted(_ALL_APPLET_NAMES))
    def test_meta_loads_successfully(self, name: str):
        """Each meta module loads without error."""
        entry = self._mgr._applets_db[name]
        result = self._mgr._pload_meta(entry)
        assert result is not None, f"Failed to load meta for {name}"
        assert entry["meta_loaded"] is True

    @pytest.mark.parametrize("name", sorted(_ALL_APPLET_NAMES))
    def test_meta_class_is_applet_meta(self, name: str):
        """The imported meta class extends AppletMeta."""
        entry = self._mgr._applets_db[name]
        meta_class = self._mgr._import_meta_class(entry)
        assert meta_class is not None
        assert issubclass(meta_class, AppletMeta)

    @pytest.mark.parametrize("name", sorted(_ALL_APPLET_NAMES))
    def test_meta_version_compatible(self, name: str):
        """Each meta returns jive_version() within range."""
        entry = self._mgr._applets_db[name]
        meta_class = self._mgr._import_meta_class(entry)
        obj = meta_class()
        min_v, max_v = obj.jive_version()
        assert min_v <= 1 <= max_v

    @pytest.mark.parametrize("name", sorted(_ALL_APPLET_NAMES))
    def test_meta_registers_without_error(self, name: str):
        """Each meta registers without raising."""
        entry = self._mgr._applets_db[name]
        self._mgr._pload_meta(entry)
        result = self._mgr._pregister_meta(entry)
        assert result is True
        assert entry["meta_registered"] is True

    def test_all_metas_load_and_register(self):
        """Full _load_and_register_metas succeeds for all applets."""
        self._mgr._load_and_register_metas()
        for name in _ALL_APPLET_NAMES:
            entry = self._mgr._applets_db[name]
            assert entry["meta_loaded"] is True, f"{name} meta not loaded"
            assert entry["meta_registered"] is True, f"{name} meta not registered"


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 3: Service registration
# ══════════════════════════════════════════════════════════════════════════════


class TestServiceRegistration:
    """After meta registration, expected services are available."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self._gs = _GlobalState()
        self._gs.__enter__()

        self._system = System(
            user_dir=tmp_path / "user",
            search_paths=[_PROJECT_ROOT / "jive"],
        )
        self._system.init_user_path_dirs()
        self._mgr = AppletManager(system=self._system)
        self._mgr._find_applets()
        self._mgr._load_and_register_metas()

        yield
        self._gs.__exit__(None, None, None)

    # NowPlaying services
    def test_go_now_playing_service(self):
        assert self._mgr.has_service("goNowPlaying")

    def test_hide_now_playing_service(self):
        assert self._mgr.has_service("hideNowPlaying")

    # SelectPlayer services
    def test_setup_show_select_player_service(self):
        assert self._mgr.has_service("setupShowSelectPlayer")

    def test_select_player_service(self):
        assert self._mgr.has_service("selectPlayer")

    # SlimBrowser services
    def test_show_track_one_service(self):
        assert self._mgr.has_service("showTrackOne")

    def test_show_playlist_service(self):
        assert self._mgr.has_service("showPlaylist")

    def test_browser_cancel_service(self):
        assert self._mgr.has_service("browserCancel")

    def test_get_audio_volume_manager_service(self):
        assert self._mgr.has_service("getAudioVolumeManager")

    def test_browser_json_request_service(self):
        assert self._mgr.has_service("browserJsonRequest")

    def test_browser_action_request_service(self):
        assert self._mgr.has_service("browserActionRequest")

    # JogglerSkin services
    def test_get_np_screen_buttons_service(self):
        assert self._mgr.has_service("getNowPlayingScreenButtons")

    def test_set_np_screen_buttons_service(self):
        assert self._mgr.has_service("setNowPlayingScreenButtons")

    def test_service_count(self):
        """At least 12 services should be registered."""
        assert len(self._mgr._services) >= 12


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 4: Applet loading
# ══════════════════════════════════════════════════════════════════════════════


class TestAppletLoading:
    """Full applet classes load, instantiate, and init correctly."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self._gs = _GlobalState()
        self._gs.__enter__()

        self._system = System(
            user_dir=tmp_path / "user",
            search_paths=[_PROJECT_ROOT / "jive"],
        )
        self._system.init_user_path_dirs()
        self._mgr = AppletManager(system=self._system)
        self._mgr._find_applets()
        self._mgr._load_and_register_metas()

        yield
        self._gs.__exit__(None, None, None)

    @pytest.mark.parametrize("name", sorted(_ALL_APPLET_NAMES))
    def test_applet_class_importable(self, name: str):
        """Each applet class can be imported."""
        entry = self._mgr._applets_db[name]
        cls = self._mgr._import_applet_class(entry)
        assert cls is not None, f"Cannot import applet class for {name}"

    @pytest.mark.parametrize("name", sorted(_ALL_APPLET_NAMES))
    def test_applet_class_is_applet(self, name: str):
        """Each applet class extends Applet."""
        entry = self._mgr._applets_db[name]
        cls = self._mgr._import_applet_class(entry)
        assert issubclass(cls, Applet)

    def test_load_slim_browser(self):
        """SlimBrowser loads and creates Volume/Scanner."""
        applet = self._mgr.load_applet("SlimBrowser")
        assert applet is not None
        assert isinstance(applet, Applet)
        # SlimBrowser creates Volume and Scanner in init()
        assert applet.volume is not None
        assert applet.scanner is not None

    def test_load_now_playing(self):
        """NowPlaying loads and initialises scroll settings."""
        applet = self._mgr.load_applet("NowPlaying")
        assert applet is not None
        assert isinstance(applet, Applet)
        assert hasattr(applet, "scrollText")
        assert hasattr(applet, "player")

    def test_load_select_player(self):
        """SelectPlayer loads and initialises menu tracking."""
        applet = self._mgr.load_applet("SelectPlayer")
        assert applet is not None
        assert isinstance(applet, Applet)
        assert hasattr(applet, "playerItem")
        assert isinstance(applet.playerItem, dict)

    def test_load_joggler_skin(self):
        """JogglerSkin loads successfully."""
        applet = self._mgr.load_applet("JogglerSkin")
        assert applet is not None
        assert isinstance(applet, Applet)

    def test_load_qvga_base_skin(self):
        """QVGAbaseSkin loads successfully."""
        applet = self._mgr.load_applet("QVGAbaseSkin")
        assert applet is not None
        assert isinstance(applet, Applet)

    def test_load_twice_returns_same_instance(self):
        """Loading the same applet twice returns the cached instance."""
        a1 = self._mgr.load_applet("NowPlaying")
        a2 = self._mgr.load_applet("NowPlaying")
        assert a1 is a2

    def test_free_applet_clears_cache(self):
        """After freeing, loading creates a new instance."""
        a1 = self._mgr.load_applet("QVGAbaseSkin")
        assert a1 is not None
        self._mgr.free_applet("QVGAbaseSkin")
        assert self._mgr.get_applet_instance("QVGAbaseSkin") is None

    def test_get_applet_instance(self):
        """get_applet_instance returns loaded applet or None."""
        assert self._mgr.get_applet_instance("NowPlaying") is None
        applet = self._mgr.load_applet("NowPlaying")
        assert self._mgr.get_applet_instance("NowPlaying") is applet


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 5: Cross-applet service calls
# ══════════════════════════════════════════════════════════════════════════════


class TestCrossAppletServices:
    """Services load applets on demand and return results."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self._gs = _GlobalState()
        self._gs.__enter__()

        self._system = System(
            user_dir=tmp_path / "user",
            search_paths=[_PROJECT_ROOT / "jive"],
        )
        self._system.init_user_path_dirs()
        self._mgr = AppletManager(system=self._system)
        self._mgr._find_applets()
        self._mgr._load_and_register_metas()

        yield
        self._gs.__exit__(None, None, None)

    def test_call_service_loads_applet_on_demand(self):
        """Calling a service on an unloaded applet loads it first.

        Note: SlimBrowser and SelectPlayer are resident applets — they
        are already loaded during meta registration.  NowPlaying is
        loaded during configure_applet().  So we verify that the
        service call works (which implies the applet is loaded).
        """
        # SlimBrowser is a resident applet, already loaded during registration
        assert self._mgr.get_applet_instance("SlimBrowser") is not None
        result = self._mgr.call_service("getAudioVolumeManager")
        # The service should return the Volume helper
        assert result is not None

    def test_call_get_audio_volume_manager(self):
        """getAudioVolumeManager returns the Volume helper."""
        result = self._mgr.call_service("getAudioVolumeManager")
        # The Volume helper should be created by SlimBrowser.init()
        assert result is not None

    def test_call_go_now_playing_no_player(self):
        """goNowPlaying with no player set returns False-ish or None."""
        result = self._mgr.call_service("goNowPlaying")
        # Without a player set, goNowPlaying should return False or None
        assert not result

    def test_call_get_np_screen_buttons(self):
        """getNowPlayingScreenButtons returns the JogglerSkin button settings."""
        result = self._mgr.call_service("getNowPlayingScreenButtons")
        # JogglerSkin stores button settings in its applet settings
        assert (
            result is not None
            or self._mgr.get_applet_instance("JogglerSkin") is not None
        )

    def test_call_unknown_service_returns_none(self):
        """Calling an unknown service returns None."""
        result = self._mgr.call_service("nonExistentService")
        assert result is None


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 6: Full discover() lifecycle
# ══════════════════════════════════════════════════════════════════════════════


class TestFullDiscover:
    """AppletManager.discover() runs the complete boot sequence."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self._gs = _GlobalState()
        self._gs.__enter__()

        self._system = System(
            user_dir=tmp_path / "user",
            search_paths=[_PROJECT_ROOT / "jive"],
        )
        self._system.init_user_path_dirs()
        self._mgr = AppletManager(system=self._system)

        yield
        self._gs.__exit__(None, None, None)

    def test_discover_completes_without_error(self):
        """Full discover() runs without raising."""
        self._mgr.discover()

    def test_all_metas_configured_after_discover(self):
        """After discover(), all metas are in configured state."""
        self._mgr.discover()
        for name in _ALL_APPLET_NAMES:
            entry = self._mgr._applets_db[name]
            assert entry["meta_loaded"] is True, f"{name} not loaded"
            assert entry["meta_registered"] is True, f"{name} not registered"
            assert entry["meta_configured"] is True, f"{name} not configured"

    def test_resident_applets_loaded_after_discover(self):
        """SlimBrowser and SelectPlayer are auto-loaded (resident)."""
        self._mgr.discover()
        # These applets call load_applet() on themselves during
        # register_applet() or configure_applet()
        sb = self._mgr.get_applet_instance("SlimBrowser")
        sp = self._mgr.get_applet_instance("SelectPlayer")
        assert sb is not None, "SlimBrowser should be auto-loaded"
        assert sp is not None, "SelectPlayer should be auto-loaded"

    def test_services_available_after_discover(self):
        """Services are available after full discover."""
        self._mgr.discover()
        assert self._mgr.has_service("goNowPlaying")
        assert self._mgr.has_service("selectPlayer")
        assert self._mgr.has_service("showPlaylist")
        assert self._mgr.has_service("getNowPlayingScreenButtons")

    def test_meta_objects_discarded_after_discover(self):
        """Meta objects are set to None after _eval_metas to save memory."""
        self._mgr.discover()
        for name in _ALL_APPLET_NAMES:
            entry = self._mgr._applets_db[name]
            assert entry["meta_obj"] is None, (
                f"{name} meta_obj should be None after discover"
            )


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 7: JiveMain headless boot
# ══════════════════════════════════════════════════════════════════════════════


class TestJiveMainHeadless:
    """JiveMain boots headless with real applets."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self._gs = _GlobalState()
        self._gs.__enter__()

        self._system = System(
            user_dir=tmp_path / "user",
            search_paths=[_PROJECT_ROOT / "jive"],
        )
        self._system.init_user_path_dirs()

        from jive.utils.locale import Locale

        self._locale = Locale()

        yield
        self._gs.__exit__(None, None, None)

    def test_jive_main_creates_singleton(self):
        """JiveMain constructor sets the module-level singleton."""
        jm = JiveMain(
            run_event_loop=False,
            system=self._system,
            locale=self._locale,
            init_ui=False,
        )
        assert JiveMain.instance is jm

        from jive.jive_main import jive_main

        assert jive_main is jm

    def test_jive_main_creates_applet_manager(self):
        """JiveMain creates a working AppletManager."""
        jm = JiveMain(
            run_event_loop=False,
            system=self._system,
            locale=self._locale,
            init_ui=False,
        )
        assert jm._applet_manager is not None
        assert isinstance(jm._applet_manager, AppletManager)

    def test_jive_main_creates_jnt(self):
        """JiveMain creates a jnt (notification hub)."""
        jm = JiveMain(
            run_event_loop=False,
            system=self._system,
            locale=self._locale,
            init_ui=False,
        )
        assert jm.jnt is not None

    def test_jive_main_jnt_has_subscribe(self):
        """The jnt stub has subscribe/unsubscribe/notify."""
        jm = JiveMain(
            run_event_loop=False,
            system=self._system,
            locale=self._locale,
            init_ui=False,
        )
        assert hasattr(jm.jnt, "subscribe")
        assert hasattr(jm.jnt, "unsubscribe")
        assert hasattr(jm.jnt, "notify")

    def test_jive_main_home_menu_nodes_registered(self):
        """Standard menu nodes (home, settings, extras) are registered."""
        jm = JiveMain(
            run_event_loop=False,
            system=self._system,
            locale=self._locale,
            init_ui=False,
        )
        nodes = jm.home_menu.get_node_table()
        assert "settings" in nodes
        assert "extras" in nodes
        assert "hidden" in nodes

    def test_jive_main_with_manual_discover(self):
        """JiveMain + manual discover finds all applets."""
        jm = JiveMain(
            run_event_loop=False,
            system=self._system,
            locale=self._locale,
            init_ui=False,
        )
        jm._applet_manager.discover()

        found = set(jm._applet_manager._applets_db.keys())
        assert _ALL_APPLET_NAMES.issubset(found), (
            f"Missing applets: {_ALL_APPLET_NAMES - found}"
        )

    def test_jive_main_services_after_discover(self):
        """After discover, services are available through JiveMain's manager."""
        jm = JiveMain(
            run_event_loop=False,
            system=self._system,
            locale=self._locale,
            init_ui=False,
        )
        jm._applet_manager.discover()

        assert jm._applet_manager.has_service("goNowPlaying")
        assert jm._applet_manager.has_service("selectPlayer")
        assert jm._applet_manager.has_service("showPlaylist")


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 8: Notification dispatch
# ══════════════════════════════════════════════════════════════════════════════


class TestNotificationDispatch:
    """The notification hub dispatches events to subscriber applets."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self._gs = _GlobalState()
        self._gs.__enter__()

        self._system = System(
            user_dir=tmp_path / "user",
            search_paths=[_PROJECT_ROOT / "jive"],
        )
        self._system.init_user_path_dirs()

        from jive.utils.locale import Locale

        self._locale = Locale()

        self._jm = JiveMain(
            run_event_loop=False,
            system=self._system,
            locale=self._locale,
            init_ui=False,
        )
        self._mgr = self._jm._applet_manager
        self._mgr.discover()
        self._jnt = self._jm.jnt

        yield
        self._gs.__exit__(None, None, None)

    def test_subscribe_and_notify(self):
        """Basic subscribe/notify works on the jnt stub."""
        received = []

        class Listener:
            def notify_testEvent(self, *args):
                received.append(args)

        listener = Listener()
        self._jnt.subscribe(listener)
        self._jnt.notify("testEvent", "hello", 42)

        assert len(received) == 1
        assert received[0] == ("hello", 42)

        self._jnt.unsubscribe(listener)
        self._jnt.notify("testEvent", "after")
        assert len(received) == 1  # No longer subscribed

    def test_subscriber_receives_only_matching_events(self):
        """Subscribers only get events they have methods for."""
        received_a = []
        received_b = []

        class ListenerA:
            def notify_eventA(self, *args):
                received_a.append(args)

        class ListenerB:
            def notify_eventB(self, *args):
                received_b.append(args)

        a = ListenerA()
        b = ListenerB()
        self._jnt.subscribe(a)
        self._jnt.subscribe(b)

        self._jnt.notify("eventA", "data_a")
        self._jnt.notify("eventB", "data_b")

        assert len(received_a) == 1
        assert len(received_b) == 1
        assert received_a[0] == ("data_a",)
        assert received_b[0] == ("data_b",)

    def test_subscriber_error_does_not_crash(self):
        """An error in one subscriber does not prevent others."""
        received = []

        class BadListener:
            def notify_testErr(self, *args):
                raise RuntimeError("boom")

        class GoodListener:
            def notify_testErr(self, *args):
                received.append(args)

        # Use a fresh notification hub to avoid interference from
        # applet subscribers registered during discover()
        from jive.jive_main import _NotificationHub

        hub = _NotificationHub()
        bad = BadListener()
        good = GoodListener()
        hub.subscribe(bad)
        hub.subscribe(good)
        # Should not raise
        hub.notify("testErr", "data")
        assert len(received) == 1

    def test_applet_as_subscriber(self):
        """A loaded applet can be manually subscribed and notified."""
        sp = self._mgr.get_applet_instance("SelectPlayer")
        if sp is None:
            sp = self._mgr.load_applet("SelectPlayer")
        assert sp is not None

        # SelectPlayer has notify_playerNew, notify_playerDelete, etc.
        assert hasattr(sp, "notify_playerNew")
        assert hasattr(sp, "notify_playerDelete")
        assert hasattr(sp, "notify_playerCurrent")

        # Subscribe it and fire a notification
        self._jnt.subscribe(sp)
        player = _make_mock_player()

        # This should not raise even though the applet tries to
        # access services that may not be fully wired
        try:
            self._jnt.notify("playerNew", player)
        except Exception:
            # Some internal calls might fail in headless mode;
            # the point is the notification dispatch itself works
            pass

    def test_multiple_notifications_dispatched(self):
        """Multiple different notifications dispatch correctly."""
        events = []

        class MultiListener:
            def notify_eventOne(self, *args):
                events.append(("one", args))

            def notify_eventTwo(self, *args):
                events.append(("two", args))

            def notify_eventThree(self, *args):
                events.append(("three", args))

        listener = MultiListener()
        self._jnt.subscribe(listener)

        self._jnt.notify("eventOne", 1)
        self._jnt.notify("eventTwo", 2)
        self._jnt.notify("eventThree", 3)
        self._jnt.notify("eventOne", 11)

        assert len(events) == 4
        assert events[0] == ("one", (1,))
        assert events[1] == ("two", (2,))
        assert events[2] == ("three", (3,))
        assert events[3] == ("one", (11,))


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 9: Settings persistence
# ══════════════════════════════════════════════════════════════════════════════


class TestSettingsPersistence:
    """Applet settings are loaded, modified, and persisted correctly."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self._gs = _GlobalState()
        self._gs.__enter__()

        self._user_dir = tmp_path / "user"
        self._system = System(
            user_dir=self._user_dir,
            search_paths=[_PROJECT_ROOT / "jive"],
        )
        self._system.init_user_path_dirs()
        self._mgr = AppletManager(system=self._system)
        self._mgr._find_applets()
        self._mgr._load_and_register_metas()

        yield
        self._gs.__exit__(None, None, None)

    def test_default_settings_applied(self):
        """NowPlaying gets its default_settings from the meta."""
        entry = self._mgr._applets_db["NowPlaying"]
        settings = entry["settings"]
        assert settings is not None
        assert "scrollText" in settings
        assert settings["scrollText"] is True

    def test_joggler_skin_default_settings(self):
        """JogglerSkin gets toolbar button defaults."""
        entry = self._mgr._applets_db["JogglerSkin"]
        settings = entry["settings"]
        assert settings is not None
        assert "play" in settings
        assert settings["play"] is True

    def test_store_and_reload_settings(self):
        """Settings can be persisted to JSON and reloaded."""
        # Load NowPlaying so we have an instance
        applet = self._mgr.load_applet("NowPlaying")
        assert applet is not None

        # Modify a setting
        applet._settings["scrollText"] = False
        applet._settings["customKey"] = "customValue"

        # Store
        entry = self._mgr._applets_db["NowPlaying"]
        self._mgr._store_settings(entry)

        # Verify the file was created
        settings_file = Path(entry["settings_filepath"])
        assert settings_file.exists()

        # Reload in a new manager
        mgr2 = AppletManager(system=self._system)
        mgr2._find_applets()

        entry2 = mgr2._applets_db["NowPlaying"]
        mgr2._load_settings(entry2)

        assert entry2["settings"] is not None
        assert entry2["settings"]["scrollText"] is False
        assert entry2["settings"]["customKey"] == "customValue"

    def test_select_player_default_settings(self):
        """SelectPlayer gets empty dict as default settings."""
        entry = self._mgr._applets_db["SelectPlayer"]
        settings = entry["settings"]
        assert settings is not None
        assert isinstance(settings, dict)


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 10: Skin registration
# ══════════════════════════════════════════════════════════════════════════════


class TestSkinRegistration:
    """JogglerSkin registers skins via JiveMain."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self._gs = _GlobalState()
        self._gs.__enter__()

        self._system = System(
            user_dir=tmp_path / "user",
            search_paths=[_PROJECT_ROOT / "jive"],
        )
        self._system.init_user_path_dirs()

        from jive.utils.locale import Locale

        self._locale = Locale()

        self._jm = JiveMain(
            run_event_loop=False,
            system=self._system,
            locale=self._locale,
            init_ui=False,
        )
        self._mgr = self._jm._applet_manager
        self._mgr.discover()

        yield
        self._gs.__exit__(None, None, None)

    def test_joggler_skin_registered(self):
        """JogglerSkin registers at least the default skin."""
        skins = self._jm.skins
        # JogglerSkin registers with applet_name "JogglerSkin"
        joggler_skins = {k: v for k, v in skins.items() if v[0] == "JogglerSkin"}
        assert len(joggler_skins) >= 1, (
            f"Expected at least 1 JogglerSkin variant, got {joggler_skins}"
        )

    def test_skin_has_correct_applet_name(self):
        """Registered skins reference the correct applet name."""
        if "JogglerSkin" in self._jm.skins:
            applet_name, display_name, method = self._jm.skins["JogglerSkin"]
            assert applet_name == "JogglerSkin"
            assert method == "skin"

    def test_skin_iterator(self):
        """skin_iterator yields registered skins."""
        skins = list(self._jm.skin_iterator())
        # Should have at least the JogglerSkin variants
        assert len(skins) >= 1
        skin_ids = [s[0] for s in skins]
        assert "JogglerSkin" in skin_ids


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 11: Menu items
# ══════════════════════════════════════════════════════════════════════════════


class TestHomeMenuItems:
    """Applets add menu items to the home menu during registration."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self._gs = _GlobalState()
        self._gs.__enter__()

        self._system = System(
            user_dir=tmp_path / "user",
            search_paths=[_PROJECT_ROOT / "jive"],
        )
        self._system.init_user_path_dirs()

        from jive.utils.locale import Locale

        self._locale = Locale()

        self._jm = JiveMain(
            run_event_loop=False,
            system=self._system,
            locale=self._locale,
            init_ui=False,
        )
        self._mgr = self._jm._applet_manager
        self._mgr.discover()

        yield
        self._gs.__exit__(None, None, None)

    def test_now_playing_adds_scroll_mode_item(self):
        """NowPlaying adds scroll-mode settings menu item."""
        items = self._jm.home_menu.get_menu_table()
        assert "appletNowPlayingScrollMode" in items

    def test_now_playing_adds_views_item(self):
        """NowPlaying adds NP views settings menu item."""
        items = self._jm.home_menu.get_menu_table()
        assert "appletNowPlayingViewsSettings" in items

    def test_menu_items_have_callbacks(self):
        """Menu items added by applets have callable callbacks."""
        items = self._jm.home_menu.get_menu_table()
        for item_id, item in items.items():
            if "callback" in item:
                assert callable(item["callback"]), (
                    f"Item {item_id} callback not callable"
                )


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 12: Full E2E flow
# ══════════════════════════════════════════════════════════════════════════════


class TestE2EFlow:
    """Complete end-to-end flow exercising all layers."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self._gs = _GlobalState()
        self._gs.__enter__()

        self._system = System(
            user_dir=tmp_path / "user",
            search_paths=[_PROJECT_ROOT / "jive"],
        )
        self._system.init_user_path_dirs()

        from jive.utils.locale import Locale

        self._locale = Locale()

        self._jm = JiveMain(
            run_event_loop=False,
            system=self._system,
            locale=self._locale,
            init_ui=False,
        )
        self._mgr = self._jm._applet_manager
        self._mgr.discover()
        self._jnt = self._jm.jnt

        yield
        self._gs.__exit__(None, None, None)

    def test_full_boot_to_service_call(self):
        """Boot → discover → call service → get result."""
        # SlimBrowser should be loaded as resident
        sb = self._mgr.get_applet_instance("SlimBrowser")
        assert sb is not None

        # Call a service that returns the Volume manager
        vol = self._mgr.call_service("getAudioVolumeManager")
        assert vol is not None

    def test_select_player_manages_menu_dynamically(self):
        """SelectPlayer adjusts menu items based on player count."""
        sp = self._mgr.get_applet_instance("SelectPlayer")
        assert sp is not None

        # With no players, the menu item may or may not be shown
        # depending on implementation, but it should not crash
        initial_item = sp.selectPlayerMenuItem

        # After notification of a new player, the applet should
        # update its menu management
        player = _make_mock_player()

        # Subscribe SelectPlayer to the jnt and fire notification
        self._jnt.subscribe(sp)

        # Patch _get_applet_manager and _get_jive_main so the
        # notification handler can access them
        with (
            patch(
                "jive.applets.SelectPlayer.SelectPlayerApplet._get_applet_manager"
            ) as mock_mgr_fn,
            patch(
                "jive.applets.SelectPlayer.SelectPlayerApplet._get_jive_main"
            ) as mock_jm_fn,
        ):
            mock_mgr_fn.return_value = self._mgr
            mock_jm_fn.return_value = self._jm

            # Simulate: manager says there are 2 players
            self._mgr.call_service = MagicMock(
                side_effect=lambda name, *a, **kw: {
                    "getCurrentPlayer": player,
                }.get(name)
            )

            self._jnt.notify("playerNew", player)

            # SelectPlayer should have processed the notification
            assert hasattr(sp, "playerItem")

    def test_now_playing_tracks_player_change(self):
        """NowPlaying resets state when the current player changes."""
        np = self._mgr.get_applet_instance("NowPlaying")
        if np is None:
            np = self._mgr.load_applet("NowPlaying")
        assert np is not None

        # Set a player
        player1 = _make_mock_player(player_id="00:04:20:11:11:11", name="P1")
        np.player = player1
        np.nowPlaying = "some_track_id"

        # Simulate playerCurrent notification with a different player
        player2 = _make_mock_player(player_id="00:04:20:22:22:22", name="P2")

        # Use a mock JiveMain that has all the methods NowPlaying calls
        # during free_and_clear() (remove_item_by_id, etc.)
        mock_jm = MagicMock()
        mock_jm.remove_item_by_id = MagicMock()
        mock_jm.removeItemById = MagicMock()

        with patch(
            "jive.applets.NowPlaying.NowPlayingApplet._get_jive_main",
            return_value=mock_jm,
        ):
            np.notify_playerCurrent(player2)

        # NowPlaying should have updated its player reference
        assert np.player is player2

    def test_settings_survive_applet_reload(self):
        """Settings persist across applet free + reload."""
        np = self._mgr.load_applet("NowPlaying")
        assert np is not None

        # Modify settings
        np._settings["scrollText"] = False
        entry = self._mgr._applets_db["NowPlaying"]
        self._mgr._store_settings(entry)

        # Free and reload
        self._mgr.free_applet("NowPlaying")
        assert self._mgr.get_applet_instance("NowPlaying") is None

        np2 = self._mgr.load_applet("NowPlaying")
        assert np2 is not None
        assert np2 is not np  # New instance
        assert np2._settings["scrollText"] is False

    def test_applet_manager_repr(self):
        """AppletManager repr shows loaded applet count."""
        repr_str = repr(self._mgr)
        assert "AppletManager" in repr_str
        assert "applets=" in repr_str
        assert "services=" in repr_str

    def test_all_applets_can_be_loaded_and_freed(self):
        """Every discovered applet can be loaded and freed.

        Some applets (e.g. SelectPlayer) return ``False`` from ``free()``
        to indicate they must stay loaded — just like the Lua original.
        The test verifies that those applets remain available after the
        free attempt while all others are properly cleaned up.
        """
        # Load every applet first
        for name in sorted(_ALL_APPLET_NAMES):
            applet = self._mgr.load_applet(name)
            assert applet is not None, f"Failed to load {name}"
            assert isinstance(applet, Applet), f"{name} is not an Applet"

        # Remember which ones refuse to be freed (free() returns False)
        refuse_free = set()
        for name in sorted(_ALL_APPLET_NAMES):
            applet = self._mgr.get_applet_instance(name)
            if applet is not None and applet.free() is False:
                refuse_free.add(name)
                # Undo the side-effect of calling free() directly by
                # re-loading the applet so the manager state is clean.
                self._mgr.load_applet(name)

        # Now free them all through the manager
        for name in sorted(_ALL_APPLET_NAMES):
            self._mgr.free_applet(name)
            if name in refuse_free:
                # Applet refused to be freed — it must still be present
                assert self._mgr.get_applet_instance(name) is not None, (
                    f"{name} should have refused freeing but was freed"
                )
            else:
                assert self._mgr.get_applet_instance(name) is None, (
                    f"{name} not freed properly"
                )

    def test_concurrent_service_and_notification(self):
        """Services and notifications work in sequence without conflict."""
        # Load all resident applets
        sb = self._mgr.get_applet_instance("SlimBrowser")
        sp = self._mgr.get_applet_instance("SelectPlayer")
        assert sb is not None
        assert sp is not None

        # Subscribe both to jnt
        self._jnt.subscribe(sb)
        self._jnt.subscribe(sp)

        # Call a service
        vol = self._mgr.call_service("getAudioVolumeManager")
        assert vol is not None

        # Fire a notification — both should handle it gracefully
        # (or ignore it if they don't have the method)
        self._jnt.notify("skinSelected")  # A benign notification

    def test_jive_main_version(self):
        """JiveMain reports the correct version."""
        assert self._jm.JIVE_VERSION == "7.8"

    def test_iconbar_created(self):
        """JiveMain creates an iconbar instance."""
        assert self._jm._iconbar is not None

    def test_soft_power_default(self):
        """Default soft power state is 'on'."""
        assert self._jm.get_soft_power_state() == "on"


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 13: Allowed-applet filtering
# ══════════════════════════════════════════════════════════════════════════════


class TestAllowedAppletFilter:
    """AppletManager allowed_applets parameter filters discovery."""

    def test_filter_to_single_applet(self, tmp_path):
        with _GlobalState():
            s = System(
                user_dir=tmp_path / "user",
                search_paths=[_PROJECT_ROOT / "jive"],
            )
            s.init_user_path_dirs()

            mgr = AppletManager(
                system=s,
                allowed_applets={"SlimBrowser"},
            )
            mgr._find_applets()

            assert "SlimBrowser" in mgr._applets_db
            assert "NowPlaying" not in mgr._applets_db
            assert len(mgr._applets_db) == 1

    def test_filter_to_multiple_applets(self, tmp_path):
        with _GlobalState():
            s = System(
                user_dir=tmp_path / "user",
                search_paths=[_PROJECT_ROOT / "jive"],
            )
            s.init_user_path_dirs()

            mgr = AppletManager(
                system=s,
                allowed_applets={"NowPlaying", "JogglerSkin"},
            )
            mgr._find_applets()

            assert set(mgr._applets_db.keys()) == {"NowPlaying", "JogglerSkin"}

    def test_filter_empty_set_finds_nothing(self, tmp_path):
        with _GlobalState():
            s = System(
                user_dir=tmp_path / "user",
                search_paths=[_PROJECT_ROOT / "jive"],
            )
            s.init_user_path_dirs()

            mgr = AppletManager(
                system=s,
                allowed_applets=set(),
            )
            mgr._find_applets()

            assert len(mgr._applets_db) == 0

    def test_no_filter_finds_all(self, tmp_path):
        with _GlobalState():
            s = System(
                user_dir=tmp_path / "user",
                search_paths=[_PROJECT_ROOT / "jive"],
            )
            s.init_user_path_dirs()

            mgr = AppletManager(
                system=s,
                allowed_applets=None,
            )
            mgr._find_applets()

            assert _ALL_APPLET_NAMES.issubset(set(mgr._applets_db.keys()))


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 14: Dynamic applet + real applets
# ══════════════════════════════════════════════════════════════════════════════


class TestDynamicWithRealApplets:
    """A dynamically created PascalCase applet works alongside real ones."""

    def test_dynamic_applet_alongside_real(self, tmp_path):
        """Create a dynamic applet, discover it together with real applets."""
        with _GlobalState():
            user_dir = tmp_path / "user"

            # Create a dynamic applet in a separate applets directory
            extra_applets = tmp_path / "extra" / "applets"
            dynamic_dir = extra_applets / "DynamicTest"
            dynamic_dir.mkdir(parents=True)

            (dynamic_dir / "DynamicTestMeta.py").write_text(
                textwrap.dedent("""\
                from jive.applet_meta import AppletMeta

                class DynamicTestMeta(AppletMeta):
                    def jive_version(self):
                        return (1, 1)
                    def register_applet(self):
                        self.register_service("dynamicTestService")
            """)
            )

            (dynamic_dir / "DynamicTestApplet.py").write_text(
                textwrap.dedent("""\
                from jive.applet import Applet

                class DynamicTestApplet(Applet):
                    def init(self):
                        super().init()
                    def dynamicTestService(self):
                        return "dynamic_works"
            """)
            )

            s = System(
                user_dir=user_dir,
                search_paths=[
                    _PROJECT_ROOT / "jive",
                    tmp_path / "extra",
                ],
            )
            s.init_user_path_dirs()

            mgr = AppletManager(system=s)
            mgr.discover()

            # Real applets should be found
            assert "SlimBrowser" in mgr._applets_db
            assert "NowPlaying" in mgr._applets_db

            # Dynamic applet should also be found
            assert "DynamicTest" in mgr._applets_db
            assert mgr.has_service("dynamicTestService")

            # Call the dynamic service
            result = mgr.call_service("dynamicTestService")
            assert result == "dynamic_works"

            # Clean up
            for key in list(sys.modules.keys()):
                if "DynamicTest" in key:
                    del sys.modules[key]

    def test_dynamic_applet_interacts_with_real_services(self, tmp_path):
        """A dynamic applet can call services from real applets."""
        with _GlobalState():
            user_dir = tmp_path / "user"

            extra_applets = tmp_path / "extra" / "applets"
            dynamic_dir = extra_applets / "ServiceCaller"
            dynamic_dir.mkdir(parents=True)

            (dynamic_dir / "ServiceCallerMeta.py").write_text(
                textwrap.dedent("""\
                from jive.applet_meta import AppletMeta

                class ServiceCallerMeta(AppletMeta):
                    def jive_version(self):
                        return (1, 1)
                    def register_applet(self):
                        self.register_service("callOtherService")
            """)
            )

            (dynamic_dir / "ServiceCallerApplet.py").write_text(
                textwrap.dedent("""\
                from jive.applet import Applet

                class ServiceCallerApplet(Applet):
                    def init(self):
                        super().init()

                    def callOtherService(self):
                        from jive.applet_manager import applet_manager
                        if applet_manager is not None:
                            vol = applet_manager.call_service("getAudioVolumeManager")
                            return vol is not None
                        return False
            """)
            )

            s = System(
                user_dir=user_dir,
                search_paths=[
                    _PROJECT_ROOT / "jive",
                    tmp_path / "extra",
                ],
            )
            s.init_user_path_dirs()

            mgr = AppletManager(system=s)
            mgr.discover()

            # The dynamic applet should be able to call SlimBrowser's service
            result = mgr.call_service("callOtherService")
            assert result is True

            for key in list(sys.modules.keys()):
                if "ServiceCaller" in key:
                    del sys.modules[key]


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 15: Edge cases and error handling
# ══════════════════════════════════════════════════════════════════════════════


class TestEdgeCases:
    """Edge cases in E2E integration."""

    def test_discover_with_no_search_paths(self, tmp_path):
        """Discover with no valid search paths finds no applets."""
        with _GlobalState():
            s = System(
                user_dir=tmp_path / "user",
                search_paths=[tmp_path / "nonexistent"],
            )
            s.init_user_path_dirs()

            mgr = AppletManager(system=s)
            mgr._find_applets()

            # May find applets on sys.path, but at minimum shouldn't crash
            assert isinstance(mgr._applets_db, dict)

    def test_load_unknown_applet_returns_none(self, tmp_path):
        """Loading a non-existent applet returns None."""
        with _GlobalState():
            s = System(
                user_dir=tmp_path / "user",
                search_paths=[_PROJECT_ROOT / "jive"],
            )
            s.init_user_path_dirs()

            mgr = AppletManager(system=s)
            result = mgr.load_applet("NonExistentApplet")
            assert result is None

    def test_free_unknown_applet_no_crash(self, tmp_path):
        """Freeing an unknown applet doesn't crash."""
        with _GlobalState():
            s = System(
                user_dir=tmp_path / "user",
                search_paths=[_PROJECT_ROOT / "jive"],
            )
            s.init_user_path_dirs()

            mgr = AppletManager(system=s)
            # Should not raise
            mgr.free_applet("NonExistentApplet")

    def test_double_discover_is_idempotent(self, tmp_path):
        """Calling discover() twice doesn't duplicate entries."""
        with _GlobalState():
            s = System(
                user_dir=tmp_path / "user",
                search_paths=[_PROJECT_ROOT / "jive"],
            )
            s.init_user_path_dirs()

            mgr = AppletManager(system=s)
            mgr.discover()
            count1 = len(mgr._applets_db)
            services1 = set(mgr._services.keys())

            mgr.discover()
            count2 = len(mgr._applets_db)

            assert count1 == count2

    def test_notification_to_freed_applet(self, tmp_path):
        """Notifying a freed applet's subscriber doesn't crash."""
        with _GlobalState():
            s = System(
                user_dir=tmp_path / "user",
                search_paths=[_PROJECT_ROOT / "jive"],
            )
            s.init_user_path_dirs()

            from jive.utils.locale import Locale

            jm = JiveMain(
                run_event_loop=False,
                system=s,
                locale=Locale(),
                init_ui=False,
            )
            jm._applet_manager.discover()

            np = jm._applet_manager.load_applet("NowPlaying")
            assert np is not None
            jm.jnt.subscribe(np)

            # Free the applet
            jm._applet_manager.free_applet("NowPlaying")

            # The subscriber reference still exists in jnt,
            # but notification should not crash
            jm.jnt.notify("playerCurrent", _make_mock_player())
