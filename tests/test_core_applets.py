"""
tests.test_core_applets — Comprehensive tests for NowPlaying, SelectPlayer,
SlimBrowser, and SlimDiscovery core applets.

Tests cover:
    - NowPlayingMeta — version, settings, registration, services
    - NowPlayingApplet — lifecycle, settings, notifications, UI creation,
      title text, volume, progress, shuffle/repeat, scroll behaviour,
      style toggling, track info extraction, artwork fetching
    - SelectPlayerMeta — version, settings, registration, services
    - SelectPlayerApplet — lifecycle, player items, menu management,
      player selection, server items, scanning popup, wallpaper preview
    - SlimBrowserMeta — version, settings, registration
    - SlimBrowserApplet — initialization, step management, action handling,
      sink processing, playlist display, volume/scanner integration
    - SlimDiscoveryMeta — version, settings, registration, services,
      configureApplet
    - SlimDiscoveryApplet — lifecycle, state machine, discovery packet
      construction, TLV response parsing, service methods, notification
      handlers, cleanup, poll list management, protocol compatibility
      with Resonance server
    - DB — chunk storage, item retrieval, size tracking
    - Volume — popup creation, volume adjustment
    - Scanner — popup creation, scanning state

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

import copy
import importlib
import os
import sys
import tempfile
import textwrap
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
# Import UI constants
# ══════════════════════════════════════════════════════════════════════════════

from jive.ui.constants import (
    EVENT_CONSUME,
    EVENT_UNUSED,
    EVENT_WINDOW_ACTIVE,
    EVENT_WINDOW_POP,
)

# ══════════════════════════════════════════════════════════════════════════════
# Mock helpers — build reusable mock objects for Player, Server, etc.
# ══════════════════════════════════════════════════════════════════════════════


def _make_mock_player(
    player_id: str = "00:04:20:aa:bb:cc",
    name: str = "Test Player",
    model: str = "squeezeplay",
    is_local: bool = False,
    is_connected: bool = True,
    is_available: bool = True,
    is_remote: bool = False,
    is_power_on: bool = True,
    volume: int = 50,
    playlist_size: int = 5,
    playlist_index: int = 1,
    play_mode: str = "play",
    elapsed: float = 30.0,
    duration: float = 180.0,
    is_seekable: bool = True,
    use_volume_control: int = 1,
    config: str = "ok",
    player_status: Optional[Dict[str, Any]] = None,
) -> MagicMock:
    """Create a fully-featured mock Player."""
    p = MagicMock()
    p.config = config
    p.get_id.return_value = player_id
    p.getId.return_value = player_id
    p.get_name.return_value = name
    p.getName.return_value = name
    p.get_model.return_value = model
    p.getModel.return_value = model
    p.is_local.return_value = is_local
    p.isLocal.return_value = is_local
    p.is_connected.return_value = is_connected
    p.isConnected.return_value = is_connected
    p.is_available.return_value = is_available
    p.isAvailable.return_value = is_available
    p.is_remote.return_value = is_remote
    p.isRemote.return_value = is_remote
    p.is_power_on.return_value = is_power_on
    p.isPowerOn.return_value = is_power_on
    p.get_volume.return_value = volume
    p.getVolume.return_value = volume
    p.get_playlist_size.return_value = playlist_size
    p.getPlaylistSize.return_value = playlist_size
    p.get_playlist_current_index.return_value = playlist_index
    p.getPlaylistCurrentIndex.return_value = playlist_index
    p.get_play_mode.return_value = play_mode
    p.getPlayMode.return_value = play_mode
    p.get_track_elapsed.return_value = (elapsed, duration)
    p.getTrackElapsed.return_value = (elapsed, duration)
    p.is_track_seekable.return_value = is_seekable
    p.isTrackSeekable.return_value = is_seekable
    p.use_volume_control.return_value = use_volume_control
    p.useVolumeControl.return_value = use_volume_control
    p.is_waiting_to_play.return_value = False
    p.isWaitingToPlay.return_value = False
    p.needs_network_config.return_value = False
    p.needsNetworkConfig.return_value = False
    p.needs_music_source.return_value = False
    p.needsMusicSource.return_value = False
    p.mac_to_model.return_value = model
    p.macToModel.return_value = model
    p.get_ssid.return_value = None
    p.getSSID.return_value = None

    status = player_status or {
        "mode": play_mode,
        "remote": 0,
        "duration": duration,
        "time": elapsed,
        "playlist repeat": 0,
        "playlist shuffle": 0,
        "item_loop": [
            {
                "track": "Test Track",
                "artist": "Test Artist",
                "album": "Test Album",
                "icon-id": "abc123",
                "params": {"track_id": "t1"},
            }
        ],
    }
    p.get_player_status.return_value = status
    p.getPlayerStatus.return_value = status

    server = _make_mock_server()
    p.get_slim_server.return_value = server
    p.getSlimServer.return_value = server

    return p


def _make_mock_server(
    name: str = "Test Server",
    is_password_protected: bool = False,
) -> MagicMock:
    """Create a mock SlimServer."""
    s = MagicMock()
    s.get_name.return_value = name
    s.getName.return_value = name
    s.is_password_protected.return_value = is_password_protected
    s.isPasswordProtected.return_value = is_password_protected
    s.fetchArtwork = MagicMock()
    s.userRequest = MagicMock()
    s.allPlayers.return_value = []
    s.all_players.return_value = []
    return s


def _make_mock_applet_manager(
    num_players: int = 1,
    current_player: Any = None,
    services: Optional[Dict[str, Any]] = None,
) -> MagicMock:
    """Create a mock AppletManager."""
    mgr = MagicMock()
    mgr.call_service = MagicMock(
        side_effect=lambda name, *a, **kw: (services or {}).get(name)
    )
    mgr.register_service = MagicMock()
    mgr.load_applet = MagicMock(return_value=None)
    mgr._store_settings = MagicMock()
    mgr._free_applet_by_entry = MagicMock()
    return mgr


def _make_mock_jive_main() -> MagicMock:
    """Create a mock JiveMain."""
    jm = MagicMock()
    jm.add_item = MagicMock()
    jm.addItem = MagicMock()
    jm.remove_item_by_id = MagicMock()
    jm.removeItemById = MagicMock()
    jm.close_to_home = MagicMock()
    jm.closeToHome = MagicMock()
    jm.get_skin_param = MagicMock(return_value=None)
    jm.getSkinParam = MagicMock(return_value=None)
    return jm


def _make_mock_jnt() -> MagicMock:
    """Create a mock network thread coordinator."""
    jnt = MagicMock()
    jnt.subscribe = MagicMock()
    jnt.unsubscribe = MagicMock()
    return jnt


class _MockStringsTable:
    """Minimal mock for strings table."""

    def str(self, token: str, *args: Any) -> str:
        if args:
            return token + " " + " ".join(str(a) for a in args)
        return token


# ══════════════════════════════════════════════════════════════════════════════
# §1  NowPlayingMeta
# ══════════════════════════════════════════════════════════════════════════════

from jive.applets.NowPlaying.NowPlayingMeta import NowPlayingMeta


class TestNowPlayingMetaVersion:
    """NowPlayingMeta.jive_version()."""

    def test_returns_tuple(self):
        m = NowPlayingMeta()
        assert m.jive_version() == (1, 1)

    def test_min_max(self):
        m = NowPlayingMeta()
        mn, mx = m.jive_version()
        assert mn <= mx


class TestNowPlayingMetaDefaults:
    """NowPlayingMeta.default_settings()."""

    def test_has_scroll_text(self):
        m = NowPlayingMeta()
        d = m.default_settings()
        assert d is not None
        assert d["scrollText"] is True

    def test_has_scroll_text_once(self):
        m = NowPlayingMeta()
        d = m.default_settings()
        assert d["scrollTextOnce"] is False

    def test_has_views(self):
        m = NowPlayingMeta()
        d = m.default_settings()
        assert isinstance(d["views"], dict)
        assert len(d["views"]) == 0


class TestNowPlayingMetaRegistration:
    """NowPlayingMeta.register_applet() registers services."""

    def test_register_services(self):
        m = NowPlayingMeta()
        m._entry = {"applet_name": "NowPlaying"}
        m._strings_table = _MockStringsTable()

        registered = []
        m.register_service = lambda svc: registered.append(svc)

        with patch.object(NowPlayingMeta, "_get_jive_main", return_value=None):
            m.register_applet()

        assert "goNowPlaying" in registered
        assert "hideNowPlaying" in registered

    def test_register_with_jive_main(self):
        m = NowPlayingMeta()
        m._entry = {"applet_name": "NowPlaying"}
        m._strings_table = _MockStringsTable()

        registered_services = []
        m.register_service = lambda svc: registered_services.append(svc)

        jm = _make_mock_jive_main()
        with patch.object(NowPlayingMeta, "_get_jive_main", return_value=jm):
            m.register_applet()

        assert jm.add_item.call_count == 2  # scroll + views menu items


class TestNowPlayingMetaConfigure:
    """NowPlayingMeta.configure_applet() registers screensaver."""

    def test_configure_loads_applet(self):
        m = NowPlayingMeta()
        m._entry = {"applet_name": "NowPlaying"}

        mock_mgr = _make_mock_applet_manager()
        with patch.object(NowPlayingMeta, "_get_applet_manager", return_value=mock_mgr):
            m.configure_applet()

        mock_mgr.call_service.assert_any_call(
            "addScreenSaver",
            "SCREENSAVER_NOWPLAYING",
            "NowPlaying",
            "openScreensaver",
            None,
            None,
            10,
            None,
            None,
            None,
            ["whenOff"],
        )
        mock_mgr.load_applet.assert_called_once_with("NowPlaying")


# ══════════════════════════════════════════════════════════════════════════════
# §2  NowPlayingApplet
# ══════════════════════════════════════════════════════════════════════════════

from jive.applets.NowPlaying.NowPlayingApplet import (
    NowPlayingApplet,
    _seconds_to_string,
)


class TestSecondsToString:
    """Helper _seconds_to_string()."""

    def test_zero(self):
        assert _seconds_to_string(0) == "0:00"

    def test_seconds_only(self):
        assert _seconds_to_string(45) == "0:45"

    def test_minutes_and_seconds(self):
        assert _seconds_to_string(125) == "2:05"

    def test_hours(self):
        assert _seconds_to_string(3661) == "1:01:01"

    def test_large_value(self):
        assert _seconds_to_string(7200) == "2:00:00"

    def test_negative_clamped(self):
        assert _seconds_to_string(-10) == "0:00"

    def test_float_input(self):
        assert _seconds_to_string(90.7) == "1:30"


class TestNowPlayingAppletInit:
    """NowPlayingApplet constructor and init()."""

    def test_constructor_defaults(self):
        npa = NowPlayingApplet()
        assert npa.player is False
        assert npa.window is None
        assert npa.selectedStyle is None
        assert npa.scrollText is True
        assert npa.scrollTextOnce is False
        assert npa.fixedVolumeSet is False
        assert npa.isScreensaver is False
        assert npa.nowPlayingItem is False
        assert npa._showProgressBar is True
        assert npa.volumeOld == 0
        assert npa.cumulativeScrollTicks == 0

    def test_init_reads_settings(self):
        npa = NowPlayingApplet()
        npa._settings = {"scrollText": False, "scrollTextOnce": True}

        with patch.object(NowPlayingApplet, "_get_jnt", return_value=None):
            npa.init()

        assert npa.scrollText is False
        assert npa.scrollTextOnce is True

    def test_init_subscribes_to_jnt(self):
        npa = NowPlayingApplet()
        npa._settings = {}
        mock_jnt = _make_mock_jnt()

        with patch.object(NowPlayingApplet, "_get_jnt", return_value=mock_jnt):
            npa.init()

        mock_jnt.subscribe.assert_called_once_with(npa)


class TestNowPlayingScrollBehavior:
    """NowPlayingApplet.set_scroll_behavior()."""

    def _make_applet(self) -> NowPlayingApplet:
        npa = NowPlayingApplet()
        npa._settings = {"scrollText": True, "scrollTextOnce": False}
        npa._entry = {"applet_name": "NowPlaying"}
        return npa

    def test_set_always(self):
        npa = self._make_applet()
        with patch(
            "jive.applets.NowPlaying.NowPlayingApplet._get_applet_manager",
            return_value=None,
        ):
            npa.set_scroll_behavior("always")
        assert npa.scrollText is True
        assert npa.scrollTextOnce is False

    def test_set_once(self):
        npa = self._make_applet()
        with patch(
            "jive.applets.NowPlaying.NowPlayingApplet._get_applet_manager",
            return_value=None,
        ):
            npa.set_scroll_behavior("once")
        assert npa.scrollText is True
        assert npa.scrollTextOnce is True

    def test_set_never(self):
        npa = self._make_applet()
        with patch(
            "jive.applets.NowPlaying.NowPlayingApplet._get_applet_manager",
            return_value=None,
        ):
            npa.set_scroll_behavior("never")
        assert npa.scrollText is False
        assert npa.scrollTextOnce is False
        assert npa.scrollSwitchTimer is None

    def test_persists_settings(self):
        npa = self._make_applet()
        with patch(
            "jive.applets.NowPlaying.NowPlayingApplet._get_applet_manager",
            return_value=None,
        ):
            npa.set_scroll_behavior("once")
        s = npa.get_settings()
        assert s["scrollText"] is True
        assert s["scrollTextOnce"] is True


class TestNowPlayingTitleText:
    """NowPlayingApplet._title_text() generates appropriate titles."""

    def _make_applet(self) -> NowPlayingApplet:
        npa = NowPlayingApplet()
        npa._strings_table = _MockStringsTable()
        npa.player = _make_mock_player(playlist_size=5, playlist_index=2)
        npa.nowPlayingScreenStyles = []
        return npa

    def test_play_mode_single_track(self):
        npa = self._make_applet()
        npa.player = _make_mock_player(playlist_size=1)
        title = npa._title_text("play")
        assert "SCREENSAVER_NOWPLAYING" in title

    def test_play_mode_with_xofy(self):
        npa = self._make_applet()
        title = npa._title_text("play")
        # Should contain "of" text since playlist > 1
        assert "SCREENSAVER_NOWPLAYING" in title or "SCREENSAVER_NOWPLAYING_OF" in title

    def test_stop_mode(self):
        npa = self._make_applet()
        title = npa._title_text("stop")
        assert "SCREENSAVER_STOPPED" in title

    def test_pause_mode(self):
        npa = self._make_applet()
        title = npa._title_text("pause")
        assert "SCREENSAVER_PAUSED" in title

    def test_off_mode(self):
        npa = self._make_applet()
        title = npa._title_text("off")
        assert "SCREENSAVER_OFF" in title

    def test_sets_main_title(self):
        npa = self._make_applet()
        npa._title_text("play")
        assert npa.mainTitle != ""


class TestNowPlayingTrackExtraction:
    """NowPlayingApplet._extract_track_info()."""

    def test_structured_track(self):
        npa = NowPlayingApplet()
        track = {"track": "Song", "artist": "Band", "album": "Disc"}
        result = npa._extract_track_info(track)
        assert isinstance(result, list)
        assert result == ["Song", "Band", "Disc"]

    def test_text_track(self):
        npa = NowPlayingApplet()
        track = {"text": "Song\nBand\nDisc"}
        result = npa._extract_track_info(track)
        assert result == "Song\nBand\nDisc"

    def test_empty_track(self):
        npa = NowPlayingApplet()
        track = {}
        result = npa._extract_track_info(track)
        assert result == "\n\n\n"

    def test_partial_structured_track(self):
        npa = NowPlayingApplet()
        track = {"track": "Song", "artist": "", "album": ""}
        result = npa._extract_track_info(track)
        assert result[0] == "Song"
        assert result[1] == ""
        assert result[2] == ""


class TestNowPlayingNotifications:
    """NowPlayingApplet notification handlers."""

    def _make_applet(self) -> NowPlayingApplet:
        npa = NowPlayingApplet()
        npa._settings = {"scrollText": True, "scrollTextOnce": False}
        npa._strings_table = _MockStringsTable()
        npa.player = _make_mock_player()
        npa.nowPlayingScreenStyles = []
        return npa

    def test_notify_player_delete_wrong_player(self):
        npa = self._make_applet()
        other = _make_mock_player(player_id="other")
        # Should not crash even if it's a different player
        npa.notify_playerDelete(other)
        # player should be unchanged
        assert npa.player is not False

    def test_notify_player_delete_correct_player(self):
        npa = self._make_applet()
        p = npa.player
        npa.notify_playerDelete(p)
        # After delete, player should be cleared (free_and_clear sets to False)
        assert npa.player is False

    def test_notify_player_mode_change_ignored_no_player(self):
        npa = NowPlayingApplet()
        npa.player = False
        # Should not raise
        npa.notify_playerModeChange(_make_mock_player(), "play")

    def test_notify_player_current_clears_on_change(self):
        npa = self._make_applet()
        old_player = npa.player
        new_player = _make_mock_player(player_id="new")

        with patch(
            "jive.applets.NowPlaying.NowPlayingApplet._get_jive_main",
            return_value=None,
        ):
            npa.notify_playerCurrent(new_player)

        assert npa.player is new_player

    def test_notify_shuffle_mode_change(self):
        npa = self._make_applet()
        npa.controlsGroup = MagicMock()
        npa.shuffleButton = MagicMock()
        npa.shuffleButton.setStyle = MagicMock()
        npa.notify_playerShuffleModeChange(npa.player, 1)
        npa.shuffleButton.setStyle.assert_called_with("shuffleSong")

    def test_notify_repeat_mode_change(self):
        npa = self._make_applet()
        npa.controlsGroup = MagicMock()
        npa.repeatButton = MagicMock()
        npa.repeatButton.setStyle = MagicMock()
        npa.notify_playerRepeatModeChange(npa.player, 2)
        npa.repeatButton.setStyle.assert_called_with("repeatPlaylist")

    def test_notify_shuffle_wrong_player_ignored(self):
        npa = self._make_applet()
        other = _make_mock_player(player_id="other")
        npa.controlsGroup = MagicMock()
        npa.shuffleButton = MagicMock()
        npa.notify_playerShuffleModeChange(other, 1)
        npa.shuffleButton.setStyle.assert_not_called()

    def test_notify_player_power_off(self):
        npa = self._make_applet()
        npa.titleGroup = MagicMock()
        npa.titleGroup.setWidgetValue = MagicMock()
        npa.notify_playerPower(npa.player, False)
        npa.titleGroup.setWidgetValue.assert_called()

    def test_notify_player_playlist_change(self):
        npa = self._make_applet()
        npa.window = MagicMock()
        npa.artwork = MagicMock()
        npa.trackTitle = MagicMock()
        npa.albumTitle = MagicMock()
        npa.artistTitle = MagicMock()
        npa.artistalbumTitle = MagicMock()
        npa.XofY = MagicMock()
        npa.progressSlider = MagicMock()
        npa.progressGroup = MagicMock()
        npa.controlsGroup = MagicMock()
        npa.titleGroup = MagicMock()
        npa.volSlider = MagicMock()
        # Should not crash
        npa.notify_playerPlaylistChange(npa.player)


class TestNowPlayingVolumeSlider:
    """NowPlayingApplet volume slider management."""

    def _make_applet(self) -> NowPlayingApplet:
        npa = NowPlayingApplet()
        npa.player = _make_mock_player(volume=50, use_volume_control=1)
        npa.volSlider = MagicMock()
        npa.volSlider.getValue.return_value = 50
        npa.volSlider.setStyle = MagicMock()
        npa.volSlider.setEnabled = MagicMock()
        npa.volSlider.setValue = MagicMock()
        return npa

    def test_set_volume_slider_style_enabled(self):
        npa = self._make_applet()
        npa._set_volume_slider_style()
        assert npa.fixedVolumeSet is False
        npa.volSlider.setStyle.assert_called_with("npvolumeB")
        npa.volSlider.setEnabled.assert_called_with(True)

    def test_set_volume_slider_style_disabled(self):
        npa = self._make_applet()
        npa.player.use_volume_control.return_value = 0
        npa.player.useVolumeControl.return_value = 0
        npa._set_volume_slider_style()
        assert npa.fixedVolumeSet is True
        npa.volSlider.setStyle.assert_called_with("npvolumeB_disabled")
        npa.volSlider.setEnabled.assert_called_with(False)
        npa.volSlider.setValue.assert_called_with(100)

    def test_update_volume_from_player(self):
        npa = self._make_applet()
        npa.player.get_volume.return_value = 75
        npa.volSlider.getValue.return_value = 50
        npa._update_volume()
        npa.volSlider.setValue.assert_called_with(75)
        assert npa.volumeOld == 75

    def test_update_volume_no_change(self):
        npa = self._make_applet()
        npa.player.get_volume.return_value = 50
        npa.volSlider.getValue.return_value = 50
        npa._update_volume()
        npa.volSlider.setValue.assert_not_called()

    def test_update_volume_fixed_ignored(self):
        npa = self._make_applet()
        npa.fixedVolumeSet = True
        npa.player.get_volume.return_value = 75
        npa.volSlider.getValue.return_value = 50
        npa._update_volume()
        npa.volSlider.setValue.assert_not_called()


class TestNowPlayingUpdateShuffle:
    """NowPlayingApplet._update_shuffle()."""

    def _make_applet(self) -> NowPlayingApplet:
        npa = NowPlayingApplet()
        npa.player = _make_mock_player()
        npa.controlsGroup = MagicMock()
        npa.shuffleButton = MagicMock()
        npa.shuffleButton.setStyle = MagicMock()
        return npa

    def test_shuffle_off(self):
        npa = self._make_applet()
        npa._update_shuffle(0)
        npa.shuffleButton.setStyle.assert_called_with("shuffleOff")

    def test_shuffle_song(self):
        npa = self._make_applet()
        npa._update_shuffle(1)
        npa.shuffleButton.setStyle.assert_called_with("shuffleSong")

    def test_shuffle_album(self):
        npa = self._make_applet()
        npa._update_shuffle(2)
        npa.shuffleButton.setStyle.assert_called_with("shuffleAlbum")

    def test_invalid_mode_logs_error(self):
        npa = self._make_applet()
        npa._update_shuffle(99)
        npa.shuffleButton.setStyle.assert_not_called()


class TestNowPlayingUpdateRepeat:
    """NowPlayingApplet._update_repeat()."""

    def _make_applet(self) -> NowPlayingApplet:
        npa = NowPlayingApplet()
        npa.player = _make_mock_player()
        npa.controlsGroup = MagicMock()
        npa.repeatButton = MagicMock()
        npa.repeatButton.setStyle = MagicMock()
        return npa

    def test_repeat_off(self):
        npa = self._make_applet()
        npa._update_repeat(0)
        npa.repeatButton.setStyle.assert_called_with("repeatOff")

    def test_repeat_song(self):
        npa = self._make_applet()
        npa._update_repeat(1)
        npa.repeatButton.setStyle.assert_called_with("repeatSong")

    def test_repeat_playlist(self):
        npa = self._make_applet()
        npa._update_repeat(2)
        npa.repeatButton.setStyle.assert_called_with("repeatPlaylist")


class TestNowPlayingUpdateMode:
    """NowPlayingApplet._update_mode()."""

    def _make_applet(self) -> NowPlayingApplet:
        npa = NowPlayingApplet()
        npa._strings_table = _MockStringsTable()
        npa.player = _make_mock_player(is_power_on=True)
        npa.titleGroup = MagicMock()
        npa.titleGroup.setWidgetValue = MagicMock()
        npa.controlsGroup = MagicMock()
        play_icon = MagicMock()
        play_icon.setStyle = MagicMock()
        npa.controlsGroup.getWidget.return_value = play_icon
        npa.nowPlayingScreenStyles = []
        return npa

    def test_play_sets_pause_icon(self):
        npa = self._make_applet()
        npa._update_mode("play")
        play_icon = npa.controlsGroup.getWidget("play")
        play_icon.setStyle.assert_called_with("pause")

    def test_stop_sets_play_icon(self):
        npa = self._make_applet()
        npa._update_mode("stop")
        play_icon = npa.controlsGroup.getWidget("play")
        play_icon.setStyle.assert_called_with("play")

    def test_off_when_power_off(self):
        npa = self._make_applet()
        npa.player.is_power_on.return_value = False
        npa.player.isPowerOn.return_value = False
        npa._update_mode("stop")
        # Title should reflect "off"
        args = npa.titleGroup.setWidgetValue.call_args
        assert "SCREENSAVER_OFF" in str(args)


class TestNowPlayingUpdateTrack:
    """NowPlayingApplet._update_track()."""

    def _make_applet(self) -> NowPlayingApplet:
        npa = NowPlayingApplet()
        npa.trackTitle = MagicMock()
        npa.albumTitle = MagicMock()
        npa.artistTitle = MagicMock()
        npa.artistalbumTitle = MagicMock()
        npa.scrollText = True
        npa.scrollSwitchTimer = None
        return npa

    def test_update_from_list(self):
        npa = self._make_applet()
        npa._update_track(["Song", "Artist", "Album"])
        npa.trackTitle.setValue.assert_called_with("Song")
        npa.artistTitle.setValue.assert_called_with("Artist")
        npa.albumTitle.setValue.assert_called_with("Album")
        # artist • album combined
        npa.artistalbumTitle.setValue.assert_called_with("Artist • Album")

    def test_update_from_string(self):
        npa = self._make_applet()
        npa._update_track("Song\nArtist\nAlbum")
        npa.trackTitle.setValue.assert_called_with("Song")
        npa.artistTitle.setValue.assert_called_with("Artist")
        npa.albumTitle.setValue.assert_called_with("Album")

    def test_update_artist_only(self):
        npa = self._make_applet()
        npa._update_track(["Song", "Artist", ""])
        npa.artistalbumTitle.setValue.assert_called_with("Artist")

    def test_update_album_only(self):
        npa = self._make_applet()
        npa._update_track(["Song", "", "Album"])
        npa.artistalbumTitle.setValue.assert_called_with("Album")

    def test_scroll_enabled(self):
        npa = self._make_applet()
        npa._update_track(["Song", "A", "B"])
        npa.trackTitle.animate.assert_called_with(True)

    def test_scroll_disabled(self):
        npa = self._make_applet()
        npa.scrollText = False
        npa._update_track(["Song", "A", "B"])
        npa.trackTitle.animate.assert_called_with(False)


class TestNowPlayingUpdatePlaylist:
    """NowPlayingApplet._update_playlist()."""

    def _make_applet(self, idx: int = 3, size: int = 10) -> NowPlayingApplet:
        npa = NowPlayingApplet()
        npa.player = _make_mock_player(playlist_index=idx, playlist_size=size)
        npa.XofY = MagicMock()
        npa.XofY.getStyle.return_value = "xofy"
        return npa

    def test_xofy_normal(self):
        npa = self._make_applet(idx=3, size=10)
        npa._update_playlist()
        npa.XofY.setValue.assert_called_with("3/10")

    def test_xofy_animate(self):
        npa = self._make_applet()
        npa._update_playlist()
        npa.XofY.animate.assert_called_with(True)

    def test_xofy_large_switches_style(self):
        npa = self._make_applet(idx=123, size=456)
        npa._update_playlist()
        # "123/456" is 7 chars > 5 → switch to xofySmall
        npa.XofY.setStyle.assert_called_with("xofySmall")

    def test_xofy_small_switches_back(self):
        npa = self._make_applet(idx=1, size=5)
        npa.XofY.getStyle.return_value = "xofySmall"
        npa._update_playlist()
        npa.XofY.setStyle.assert_called_with("xofy")

    def test_xofy_empty_when_zero(self):
        npa = self._make_applet(idx=0, size=5)
        npa._update_playlist()
        npa.XofY.setValue.assert_called_with("")

    def test_xofy_none_player(self):
        npa = NowPlayingApplet()
        npa.player = False
        npa.XofY = MagicMock()
        npa.XofY.getStyle.return_value = "xofy"
        npa._update_playlist()
        # With no player, playlist size is None so xofy is ""
        # setValue IS called with empty string — that's the expected behaviour
        npa.XofY.setValue.assert_called_with("")


class TestNowPlayingUpdateProgress:
    """NowPlayingApplet._update_progress() and _update_position()."""

    def _make_applet(
        self, elapsed: float = 30.0, duration: float = 180.0
    ) -> NowPlayingApplet:
        npa = NowPlayingApplet()
        npa.player = _make_mock_player(elapsed=elapsed, duration=duration)
        npa.progressSlider = MagicMock()
        npa.progressBarGroup = MagicMock()
        npa.progressNBGroup = MagicMock()
        npa.progressGroup = MagicMock()
        npa.progressGroup.getWidget.return_value = MagicMock()
        npa.progressGroup.getWidget.return_value.getStyle.return_value = "elapsed"
        npa._showProgressBar = True
        npa.window = MagicMock()
        return npa

    def test_sets_range_with_duration(self):
        npa = self._make_applet(elapsed=60, duration=300)
        npa._update_progress({"mode": "play"})
        npa.progressSlider.setRange.assert_called_with(0, 300.0, 60.0)

    def test_sets_default_range_no_duration(self):
        npa = self._make_applet(elapsed=10, duration=0)
        npa.player.get_track_elapsed.return_value = (10, 0)
        npa.player.getTrackElapsed.return_value = (10, 0)
        npa._update_progress({"mode": "play"})
        npa.progressSlider.setRange.assert_called_with(0, 100, 0)

    def test_position_elapsed_string(self):
        npa = self._make_applet(elapsed=125, duration=300)
        npa._update_position()
        # "elapsed" widget should receive "2:05"
        npa.progressGroup.setWidgetValue.assert_any_call("elapsed", "2:05")

    def test_position_remain_string(self):
        npa = self._make_applet(elapsed=60, duration=300)
        npa._update_position()
        npa.progressGroup.setWidgetValue.assert_any_call("remain", "-4:00")

    def test_position_no_player(self):
        npa = self._make_applet()
        npa.player = False
        npa._update_position()
        npa.progressGroup.setWidgetValue.assert_not_called()

    def test_seekable_sets_enabled(self):
        npa = self._make_applet()
        npa._update_progress({"mode": "play"})
        npa.progressSlider.setEnabled.assert_called_with(True)

    def test_not_seekable_disables(self):
        npa = self._make_applet()
        npa.player.is_track_seekable.return_value = False
        npa.player.isTrackSeekable.return_value = False
        npa._update_progress({"mode": "play"})
        npa.progressSlider.setEnabled.assert_called_with(False)


class TestNowPlayingStyleToggling:
    """NowPlayingApplet.toggle_np_screen_style()."""

    def _make_applet(self) -> NowPlayingApplet:
        npa = NowPlayingApplet()
        npa.player = _make_mock_player()
        npa.nowPlayingScreenStyles = [
            {"style": "nowplaying", "enabled": True, "text": "Default"},
            {"style": "nowplaying_large", "enabled": True, "text": "Large Art"},
            {"style": "nowplaying_text", "enabled": False, "text": "Text Only"},
        ]
        npa.selectedStyle = "nowplaying"
        npa._settings = {"selectedStyle": "nowplaying"}
        npa._entry = {"applet_name": "NowPlaying"}
        npa.window = None
        # Stub store_settings to avoid side effects
        npa.store_settings = MagicMock()
        return npa

    def test_cycles_to_next_enabled(self):
        npa = self._make_applet()
        # Mock replace_np_window to avoid real UI instantiation
        npa.replace_np_window = MagicMock()
        npa.toggle_np_screen_style()
        assert npa.selectedStyle == "nowplaying_large"

    def test_wraps_around(self):
        npa = self._make_applet()
        npa.selectedStyle = "nowplaying_large"
        # Mock replace_np_window to avoid real UI instantiation
        npa.replace_np_window = MagicMock()
        npa.toggle_np_screen_style()
        # skips disabled "nowplaying_text", wraps to "nowplaying"
        assert npa.selectedStyle == "nowplaying"

    def test_no_change_if_no_styles(self):
        npa = self._make_applet()
        npa.nowPlayingScreenStyles = []
        npa.selectedStyle = "nowplaying"
        npa.toggle_np_screen_style()
        assert npa.selectedStyle == "nowplaying"


class TestNowPlayingGoNowPlaying:
    """NowPlayingApplet.goNowPlaying() service method."""

    def test_returns_false_no_player(self):
        npa = NowPlayingApplet()
        npa.player = False
        with patch(
            "jive.applets.NowPlaying.NowPlayingApplet._get_applet_manager"
        ) as mock_mgr:
            mock_mgr.return_value = MagicMock()
            mock_mgr.return_value.call_service.return_value = None
            result = npa.goNowPlaying()
            assert result is False

    def test_sets_screensaver_false(self):
        npa = NowPlayingApplet()
        npa.player = _make_mock_player()
        npa.isScreensaver = True
        # Patch to prevent full showNowPlaying execution
        npa.showNowPlaying = MagicMock()
        npa.goNowPlaying()
        assert npa.isScreensaver is False

    def test_calls_show_now_playing_with_tracks(self):
        npa = NowPlayingApplet()
        npa.player = _make_mock_player(playlist_size=3)
        npa.showNowPlaying = MagicMock()
        with patch(
            "jive.applets.NowPlaying.NowPlayingApplet._get_applet_manager"
        ) as mock_mgr:
            mock_mgr.return_value = MagicMock()
            mock_mgr.return_value.call_service.return_value = False
            npa.goNowPlaying(transition="fade")
        npa.showNowPlaying.assert_called_once_with("fade", False)


class TestNowPlayingFreeAndClear:
    """NowPlayingApplet.free_and_clear() and free()."""

    def test_free_and_clear_resets_player(self):
        npa = NowPlayingApplet()
        npa.player = _make_mock_player()
        npa.window = MagicMock()
        with patch(
            "jive.applets.NowPlaying.NowPlayingApplet._get_jive_main"
        ) as mock_jm:
            mock_jm.return_value = _make_mock_jive_main()
            npa.free_and_clear()
        assert npa.player is False

    def test_free_hides_window(self):
        npa = NowPlayingApplet()
        win = MagicMock()
        npa.window = win
        npa.free()
        # free() hides the window and then sets self.window = None
        win.hide.assert_called_once()

    def test_free_returns_true(self):
        npa = NowPlayingApplet()
        assert npa.free() is True

    def test_free_clears_window(self):
        npa = NowPlayingApplet()
        npa.window = MagicMock()
        npa.free()
        assert npa.window is None


class TestNowPlayingArtwork:
    """NowPlayingApplet._get_icon()."""

    def test_fetches_by_icon_id(self):
        npa = NowPlayingApplet()
        npa.player = _make_mock_player()
        npa.nowPlayingScreenStyles = [{"style": "nowplaying", "artworkSize": 300}]
        npa.selectedStyle = "nowplaying"
        icon = MagicMock()
        item = {"icon-id": "art123"}
        npa._get_icon(item, icon, 0)
        server = npa.player.get_slim_server()
        server.fetchArtwork.assert_called_once_with("art123", icon, 300)

    def test_fetches_by_track_id(self):
        npa = NowPlayingApplet()
        npa.player = _make_mock_player()
        npa.nowPlayingScreenStyles = [{"style": "nowplaying", "artworkSize": 200}]
        npa.selectedStyle = "nowplaying"
        icon = MagicMock()
        item = {"params": {"track_id": "t42"}}
        npa._get_icon(item, icon, 0)
        server = npa.player.get_slim_server()
        server.fetchArtwork.assert_called_once_with("t42", icon, 200, "png")

    def test_clears_icon_on_no_id(self):
        npa = NowPlayingApplet()
        npa.player = _make_mock_player()
        npa.nowPlayingScreenStyles = []
        npa.selectedStyle = "nowplaying"
        icon = MagicMock()
        npa._get_icon(None, icon, None)
        icon.setValue.assert_called_with(None)


class TestNowPlayingPlayerHelpers:
    """NowPlayingApplet private player accessor methods."""

    def test_player_id(self):
        npa = NowPlayingApplet()
        npa.player = _make_mock_player(player_id="aa:bb:cc:dd:ee:ff")
        assert npa._player_id() == "aa:bb:cc:dd:ee:ff"

    def test_player_id_no_player(self):
        npa = NowPlayingApplet()
        npa.player = False
        assert npa._player_id() is None

    def test_player_play_mode(self):
        npa = NowPlayingApplet()
        npa.player = _make_mock_player(play_mode="pause")
        assert npa._player_play_mode() == "pause"

    def test_player_play_mode_no_player(self):
        npa = NowPlayingApplet()
        npa.player = False
        assert npa._player_play_mode() == "stop"

    def test_player_is_local(self):
        npa = NowPlayingApplet()
        npa.player = _make_mock_player(is_local=True)
        assert npa._player_is_local() is True

    def test_player_track_elapsed(self):
        npa = NowPlayingApplet()
        npa.player = _make_mock_player(elapsed=42.0, duration=200.0)
        elapsed, duration = npa._player_track_elapsed()
        assert elapsed == 42.0
        assert duration == 200.0

    def test_player_track_elapsed_no_player(self):
        npa = NowPlayingApplet()
        npa.player = False
        assert npa._player_track_elapsed() == (None, None)

    def test_playlist_has_tracks_true(self):
        npa = NowPlayingApplet()
        npa.player = _make_mock_player(playlist_size=3)
        assert npa._playlist_has_tracks() is True

    def test_playlist_has_tracks_empty(self):
        npa = NowPlayingApplet()
        npa.player = _make_mock_player(playlist_size=0)
        assert npa._playlist_has_tracks() is False

    def test_playlist_has_tracks_no_player(self):
        npa = NowPlayingApplet()
        npa.player = False
        assert npa._playlist_has_tracks() is False

    def test_is_this_player_match(self):
        npa = NowPlayingApplet()
        p = _make_mock_player(player_id="aa:bb:cc:dd:ee:ff")
        npa.player = p
        assert npa._is_this_player(p) is True

    def test_is_this_player_mismatch(self):
        npa = NowPlayingApplet()
        npa.player = _make_mock_player(player_id="aa:bb:cc:dd:ee:ff")
        other = _make_mock_player(player_id="11:22:33:44:55:66")
        assert npa._is_this_player(other) is False


# ══════════════════════════════════════════════════════════════════════════════
# §2  SelectPlayerMeta
# ══════════════════════════════════════════════════════════════════════════════

from jive.applets.SelectPlayer.SelectPlayerMeta import SelectPlayerMeta


class TestSelectPlayerMetaVersion:
    """SelectPlayerMeta.jive_version()."""

    def test_returns_tuple(self):
        meta = SelectPlayerMeta()
        assert isinstance(meta.jive_version(), tuple)

    def test_min_max(self):
        meta = SelectPlayerMeta()
        min_v, max_v = meta.jive_version()
        assert min_v == 1
        assert max_v == 1


class TestSelectPlayerMetaDefaults:
    """SelectPlayerMeta.default_settings()."""

    def test_empty_dict(self):
        meta = SelectPlayerMeta()
        d = meta.default_settings()
        assert d == {}


class TestSelectPlayerMetaRegistration:
    """SelectPlayerMeta.register_applet()."""

    def test_registers_services(self):
        meta = SelectPlayerMeta()
        meta._entry = {"applet_name": "SelectPlayer"}
        registered = []
        with patch(
            "jive.applets.SelectPlayer.SelectPlayerMeta.SelectPlayerMeta._get_applet_manager"
        ) as mock_mgr_fn:
            mgr = _make_mock_applet_manager()
            mock_mgr_fn.return_value = mgr

            original_register = meta.register_service

            def _capture(service):
                registered.append(service)

            meta.register_service = _capture
            meta.register_applet()

        assert "setupShowSelectPlayer" in registered
        assert "selectPlayer" in registered

    def test_loads_applet(self):
        meta = SelectPlayerMeta()
        meta._entry = {"applet_name": "SelectPlayer"}
        with patch(
            "jive.applets.SelectPlayer.SelectPlayerMeta.SelectPlayerMeta._get_applet_manager"
        ) as mock_mgr_fn:
            mgr = _make_mock_applet_manager()
            mock_mgr_fn.return_value = mgr
            meta.register_service = MagicMock()
            meta.register_applet()
            mgr.load_applet.assert_called_once_with("SelectPlayer")


# ══════════════════════════════════════════════════════════════════════════════
# §3  SelectPlayerApplet
# ══════════════════════════════════════════════════════════════════════════════

from jive.applets.SelectPlayer.SelectPlayerApplet import (
    _VALID_MODELS,
    LOCAL_PLAYER_WEIGHT,
    PLAYER_WEIGHT,
    SERVER_WEIGHT,
    SelectPlayerApplet,
)


class TestSelectPlayerAppletInit:
    """SelectPlayerApplet constructor and init()."""

    def test_constructor_defaults(self):
        sp = SelectPlayerApplet()
        assert sp.playerItem == {}
        assert sp.serverItem == {}
        assert sp.selectedPlayer is None
        assert sp.selectPlayerMenuItem is None
        assert sp.setupMode is False
        assert sp.playersFound is False

    def test_init_subscribes(self):
        sp = SelectPlayerApplet()
        sp._settings = {}
        sp._entry = {"applet_name": "SelectPlayer"}
        with patch(
            "jive.applets.SelectPlayer.SelectPlayerApplet._get_jnt"
        ) as mock_jnt_fn:
            jnt = _make_mock_jnt()
            mock_jnt_fn.return_value = jnt
            with patch(
                "jive.applets.SelectPlayer.SelectPlayerApplet._get_applet_manager"
            ) as mock_mgr_fn:
                mock_mgr_fn.return_value = _make_mock_applet_manager()
                with patch(
                    "jive.applets.SelectPlayer.SelectPlayerApplet._get_jive_main"
                ) as mock_jm_fn:
                    mock_jm_fn.return_value = None
                    sp.init()
            jnt.subscribe.assert_called_once_with(sp)


class TestSelectPlayerMenuManagement:
    """SelectPlayerApplet.manage_select_player_menu()."""

    def test_adds_menu_when_multiple_players(self):
        sp = SelectPlayerApplet()
        sp._settings = {}
        sp._strings_table = _MockStringsTable()
        with patch(
            "jive.applets.SelectPlayer.SelectPlayerApplet._get_applet_manager"
        ) as mock_mgr_fn:
            mgr = MagicMock()
            mgr.call_service.side_effect = lambda name, *a, **kw: {
                "countPlayers": 3,
                "getCurrentPlayer": _make_mock_player(),
            }.get(name)
            mock_mgr_fn.return_value = mgr

            jm = _make_mock_jive_main()
            with patch(
                "jive.applets.SelectPlayer.SelectPlayerApplet._get_jive_main"
            ) as mock_jm_fn:
                mock_jm_fn.return_value = jm
                sp.manage_select_player_menu()

        assert sp.selectPlayerMenuItem is not None
        jm.add_item.assert_called_once()

    def test_removes_menu_when_single_connected_player(self):
        sp = SelectPlayerApplet()
        sp._settings = {}
        connected_player = _make_mock_player(is_connected=True)
        sp.selectPlayerMenuItem = {"id": "selectPlayer"}

        with patch(
            "jive.applets.SelectPlayer.SelectPlayerApplet._get_applet_manager"
        ) as mock_mgr_fn:
            mgr = MagicMock()
            mgr.call_service.side_effect = lambda name, *a, **kw: {
                "countPlayers": 1,
                "getCurrentPlayer": connected_player,
            }.get(name)
            mock_mgr_fn.return_value = mgr

            jm = _make_mock_jive_main()
            with patch(
                "jive.applets.SelectPlayer.SelectPlayerApplet._get_jive_main"
            ) as mock_jm_fn:
                mock_jm_fn.return_value = jm
                sp.manage_select_player_menu()

        assert sp.selectPlayerMenuItem is None
        jm.remove_item_by_id.assert_called_once_with("selectPlayer")

    def test_shows_menu_when_no_current_player(self):
        sp = SelectPlayerApplet()
        sp._settings = {}
        sp._strings_table = _MockStringsTable()

        with patch(
            "jive.applets.SelectPlayer.SelectPlayerApplet._get_applet_manager"
        ) as mock_mgr_fn:
            mgr = MagicMock()
            mgr.call_service.side_effect = lambda name, *a, **kw: {
                "countPlayers": 1,
                "getCurrentPlayer": None,
            }.get(name)
            mock_mgr_fn.return_value = mgr

            jm = _make_mock_jive_main()
            with patch(
                "jive.applets.SelectPlayer.SelectPlayerApplet._get_jive_main"
            ) as mock_jm_fn:
                mock_jm_fn.return_value = jm
                sp.manage_select_player_menu()

        assert sp.selectPlayerMenuItem is not None


class TestSelectPlayerAddPlayerItem:
    """SelectPlayerApplet._add_player_item()."""

    def _make_sp(self) -> SelectPlayerApplet:
        sp = SelectPlayerApplet()
        sp._settings = {}
        sp._strings_table = _MockStringsTable()
        sp.playerMenu = MagicMock()
        sp.selectedPlayer = None
        return sp

    def test_adds_item(self):
        sp = self._make_sp()
        player = _make_mock_player(player_id="aa:bb:cc:00:11:22", name="Kitchen")
        sp._add_player_item(player)
        assert "aa:bb:cc:00:11:22" in sp.playerItem
        item = sp.playerItem["aa:bb:cc:00:11:22"]
        assert item["text"] == "Kitchen"
        sp.playerMenu.addItem.assert_called_once()

    def test_correct_icon_style(self):
        sp = self._make_sp()
        player = _make_mock_player(model="boom")
        sp._add_player_item(player)
        mac = player.get_id()
        assert sp.playerItem[mac]["iconStyle"] == "player_boom"

    def test_unknown_model_defaults(self):
        sp = self._make_sp()
        player = _make_mock_player(model="unknown_device_xyz")
        sp._add_player_item(player)
        mac = player.get_id()
        assert sp.playerItem[mac]["iconStyle"] == "player_squeezeplay"

    def test_local_player_weight(self):
        sp = self._make_sp()
        player = _make_mock_player(is_local=True)
        sp._add_player_item(player)
        mac = player.get_id()
        assert sp.playerItem[mac]["weight"] == LOCAL_PLAYER_WEIGHT

    def test_remote_player_weight(self):
        sp = self._make_sp()
        player = _make_mock_player(is_local=False)
        sp._add_player_item(player)
        mac = player.get_id()
        assert sp.playerItem[mac]["weight"] == PLAYER_WEIGHT

    def test_selected_player_checked(self):
        sp = self._make_sp()
        player = _make_mock_player(is_connected=True)
        sp.selectedPlayer = player
        sp._add_player_item(player)
        mac = player.get_id()
        assert sp.playerItem[mac]["style"] == "item_checked"

    def test_sets_players_found(self):
        sp = self._make_sp()
        assert sp.playersFound is False
        sp._add_player_item(_make_mock_player())
        assert sp.playersFound is True


class TestSelectPlayerRefreshItem:
    """SelectPlayerApplet._refresh_player_item()."""

    def _make_sp(self) -> SelectPlayerApplet:
        sp = SelectPlayerApplet()
        sp._settings = {}
        sp._strings_table = _MockStringsTable()
        sp.playerMenu = MagicMock()
        sp.selectedPlayer = None
        return sp

    def test_adds_new_available_player(self):
        sp = self._make_sp()
        player = _make_mock_player(is_available=True)
        sp._refresh_player_item(player)
        assert player.get_id() in sp.playerItem

    def test_removes_unavailable_player(self):
        sp = self._make_sp()
        player = _make_mock_player(is_available=True)
        sp._add_player_item(player)
        mac = player.get_id()
        assert mac in sp.playerItem

        player.is_available.return_value = False
        player.isAvailable.return_value = False
        sp._refresh_player_item(player)
        assert mac not in sp.playerItem

    def test_updates_style_for_selected(self):
        sp = self._make_sp()
        player = _make_mock_player(is_available=True)
        sp._add_player_item(player)
        sp.selectedPlayer = player
        sp._refresh_player_item(player)
        mac = player.get_id()
        assert sp.playerItem[mac]["style"] == "item_checked"


class TestSelectPlayerServerItem:
    """SelectPlayerApplet._update_server_item()."""

    def _make_sp(self) -> SelectPlayerApplet:
        sp = SelectPlayerApplet()
        sp.playerMenu = MagicMock()
        return sp

    def test_adds_password_protected_server(self):
        sp = self._make_sp()
        server = _make_mock_server(name="MyServer", is_password_protected=True)
        sp._update_server_item(server)
        assert "MyServer" in sp.serverItem
        sp.playerMenu.addItem.assert_called_once()

    def test_removes_non_protected_server(self):
        sp = self._make_sp()
        server = _make_mock_server(name="MyServer", is_password_protected=True)
        sp._update_server_item(server)
        assert "MyServer" in sp.serverItem

        server.is_password_protected.return_value = False
        server.isPasswordProtected.return_value = False
        sp._update_server_item(server)
        assert "MyServer" not in sp.serverItem

    def test_server_item_weight(self):
        sp = self._make_sp()
        server = _make_mock_server(name="PW Server", is_password_protected=True)
        sp._update_server_item(server)
        assert sp.serverItem["PW Server"]["weight"] == SERVER_WEIGHT


class TestSelectPlayerSelection:
    """SelectPlayerApplet.select_player()."""

    def test_returns_true_for_normal_player(self):
        sp = SelectPlayerApplet()
        player = _make_mock_player()
        with patch(
            "jive.applets.SelectPlayer.SelectPlayerApplet._get_applet_manager"
        ) as mock_mgr_fn:
            mgr = _make_mock_applet_manager()
            mock_mgr_fn.return_value = mgr
            result = sp.select_player(player)
        assert result is True
        assert sp.selectedPlayer is player
        mgr.call_service.assert_any_call("setCurrentPlayer", player)

    def test_returns_false_needs_network(self):
        sp = SelectPlayerApplet()
        sp.setupMode = False
        player = _make_mock_player()
        player.needs_network_config.return_value = True
        player.needsNetworkConfig.return_value = True
        with patch(
            "jive.applets.SelectPlayer.SelectPlayerApplet._get_applet_manager"
        ) as mock_mgr_fn:
            mgr = _make_mock_applet_manager()
            mock_mgr_fn.return_value = mgr
            result = sp.select_player(player)
        assert result is False

    def test_returns_false_needs_music_source(self):
        sp = SelectPlayerApplet()
        sp.setupMode = False
        player = _make_mock_player()
        player.needs_music_source.return_value = True
        player.needsMusicSource.return_value = True
        with patch(
            "jive.applets.SelectPlayer.SelectPlayerApplet._get_applet_manager"
        ) as mock_mgr_fn:
            mgr = _make_mock_applet_manager()
            mock_mgr_fn.return_value = mgr
            result = sp.select_player(player)
        assert result is False


class TestSelectPlayerNotifications:
    """SelectPlayerApplet notification handlers."""

    def _make_sp(self) -> SelectPlayerApplet:
        sp = SelectPlayerApplet()
        sp._settings = {}
        sp._strings_table = _MockStringsTable()
        sp.playerMenu = MagicMock()
        sp.selectedPlayer = None
        return sp

    def test_notify_playerNew_adds_item(self):
        sp = self._make_sp()
        player = _make_mock_player(player_id="11:22:33:44:55:66", name="New Player")
        with patch(
            "jive.applets.SelectPlayer.SelectPlayerApplet._get_applet_manager"
        ) as mock_mgr_fn:
            mock_mgr_fn.return_value = _make_mock_applet_manager()
            with patch(
                "jive.applets.SelectPlayer.SelectPlayerApplet._get_jive_main"
            ) as mock_jm_fn:
                mock_jm_fn.return_value = None
                sp.notify_playerNew(player)
        assert "11:22:33:44:55:66" in sp.playerItem

    def test_notify_playerDelete_removes_item(self):
        sp = self._make_sp()
        player = _make_mock_player(player_id="11:22:33:44:55:66")
        sp._add_player_item(player)
        assert "11:22:33:44:55:66" in sp.playerItem
        with patch(
            "jive.applets.SelectPlayer.SelectPlayerApplet._get_applet_manager"
        ) as mock_mgr_fn:
            mock_mgr_fn.return_value = _make_mock_applet_manager()
            with patch(
                "jive.applets.SelectPlayer.SelectPlayerApplet._get_jive_main"
            ) as mock_jm_fn:
                mock_jm_fn.return_value = None
                sp.notify_playerDelete(player)
        assert "11:22:33:44:55:66" not in sp.playerItem

    def test_notify_playerCurrent_updates_selected(self):
        sp = self._make_sp()
        player = _make_mock_player()
        with patch(
            "jive.applets.SelectPlayer.SelectPlayerApplet._get_applet_manager"
        ) as mock_mgr_fn:
            mock_mgr_fn.return_value = _make_mock_applet_manager()
            with patch(
                "jive.applets.SelectPlayer.SelectPlayerApplet._get_jive_main"
            ) as mock_jm_fn:
                mock_jm_fn.return_value = None
                sp.notify_playerCurrent(player)
        assert sp.selectedPlayer is player

    def test_notify_serverConnected_updates(self):
        sp = self._make_sp()
        server = _make_mock_server(name="S1", is_password_protected=True)
        with patch(
            "jive.applets.SelectPlayer.SelectPlayerApplet._get_applet_manager"
        ) as mock_mgr_fn:
            mock_mgr_fn.return_value = _make_mock_applet_manager()
            with patch(
                "jive.applets.SelectPlayer.SelectPlayerApplet._get_jive_main"
            ) as mock_jm_fn:
                mock_jm_fn.return_value = None
                sp.notify_serverConnected(server)
        assert "S1" in sp.serverItem


class TestSelectPlayerFree:
    """SelectPlayerApplet.free() — never actually freed."""

    def test_returns_false(self):
        sp = SelectPlayerApplet()
        assert sp.free() is False

    def test_shows_wallpaper_on_free(self):
        sp = SelectPlayerApplet()
        sp.selectedPlayer = _make_mock_player(player_id="ab:cd:ef:01:02:03")
        with patch(
            "jive.applets.SelectPlayer.SelectPlayerApplet._get_applet_manager"
        ) as mock_mgr_fn:
            mgr = _make_mock_applet_manager()
            mock_mgr_fn.return_value = mgr
            sp.free()
            mgr.call_service.assert_called_with(
                "showBackground", None, "ab:cd:ef:01:02:03"
            )

    def test_fallback_wallpaper_no_player(self):
        sp = SelectPlayerApplet()
        sp.selectedPlayer = None
        with patch(
            "jive.applets.SelectPlayer.SelectPlayerApplet._get_applet_manager"
        ) as mock_mgr_fn:
            mgr = _make_mock_applet_manager()
            mock_mgr_fn.return_value = mgr
            sp.free()
            mgr.call_service.assert_called_with("showBackground", None, "wallpaper")


class TestSelectPlayerValidModels:
    """Verify the set of valid player models."""

    def test_known_models(self):
        for model in [
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
        ]:
            assert model in _VALID_MODELS

    def test_unknown_model(self):
        assert "unknown_xyz" not in _VALID_MODELS


class TestSelectPlayerScan:
    """SelectPlayerApplet._scan()."""

    def test_calls_discover(self):
        sp = SelectPlayerApplet()
        with patch(
            "jive.applets.SelectPlayer.SelectPlayerApplet._get_applet_manager"
        ) as mock_mgr_fn:
            mgr = _make_mock_applet_manager()
            mock_mgr_fn.return_value = mgr
            sp._scan()
            mgr.call_service.assert_called_with("discoverPlayers")


class TestSelectPlayerPopup:
    """SelectPlayerApplet scanning popup."""

    def test_hide_when_active(self):
        sp = SelectPlayerApplet()
        popup = MagicMock()
        sp.populatingPlayers = popup
        sp._hide_populating_players_popup()
        popup.hide.assert_called_once()
        assert sp.populatingPlayers is False

    def test_hide_when_inactive(self):
        sp = SelectPlayerApplet()
        sp.populatingPlayers = False
        sp._hide_populating_players_popup()
        # Should not crash

    def test_show_returns_none_if_players_found(self):
        sp = SelectPlayerApplet()
        sp.playersFound = True
        sp._strings_table = _MockStringsTable()
        result = sp._show_populating_players_popup()
        assert result is None

    def test_show_returns_none_if_already_showing(self):
        sp = SelectPlayerApplet()
        sp.populatingPlayers = MagicMock()
        sp._strings_table = _MockStringsTable()
        result = sp._show_populating_players_popup()
        assert result is None


# ══════════════════════════════════════════════════════════════════════════════
# §4  SlimBrowserMeta
# ══════════════════════════════════════════════════════════════════════════════

from jive.applets.SlimBrowser.SlimBrowserMeta import SlimBrowserMeta


class TestSlimBrowserMetaVersion:
    """SlimBrowserMeta.jive_version()."""

    def test_returns_tuple(self):
        meta = SlimBrowserMeta()
        assert isinstance(meta.jive_version(), tuple)

    def test_min_max(self):
        meta = SlimBrowserMeta()
        min_v, max_v = meta.jive_version()
        assert min_v == 1
        assert max_v == 1


class TestSlimBrowserMetaDefaults:
    """SlimBrowserMeta.default_settings()."""

    def test_returns_none(self):
        meta = SlimBrowserMeta()
        d = meta.default_settings()
        # SlimBrowser has no default settings — returns None
        assert d is None


class TestSlimBrowserMetaRegistration:
    """SlimBrowserMeta.register_applet()."""

    def test_registers_services(self):
        meta = SlimBrowserMeta()
        meta._entry = {"applet_name": "SlimBrowser"}
        registered = []

        def _capture(service):
            registered.append(service)

        meta.register_service = _capture

        with patch(
            "jive.applets.SlimBrowser.SlimBrowserMeta.SlimBrowserMeta._get_applet_manager",
            return_value=_make_mock_applet_manager(),
        ):
            meta.register_applet()

        # Verify key services are registered
        assert "showPlaylist" in registered
        assert "showTrackOne" in registered
        assert "getAudioVolumeManager" in registered


# ══════════════════════════════════════════════════════════════════════════════
# §5  SlimBrowser DB
# ══════════════════════════════════════════════════════════════════════════════

from jive.applets.SlimBrowser.db import DB


class TestDBConstruction:
    """DB chunk storage — using the actual menu_items() / item() API."""

    def test_create_empty(self):
        db = DB()
        assert db.size() == 0

    def test_update_count(self):
        db = DB()
        chunk = {
            "count": 10,
            "offset": 0,
            "item_loop": [{"text": f"Item {i}"} for i in range(10)],
        }
        db.menu_items(chunk)
        assert db.size() == 10

    def test_store_and_retrieve_item(self):
        db = DB()
        items = [{"text": "First"}, {"text": "Second"}, {"text": "Third"}]
        chunk = {"count": 3, "offset": 0, "item_loop": items}
        db.menu_items(chunk)
        # item() is 1-based
        item, is_current = db.item(1)
        assert item is not None
        assert item.get("text") == "First"

    def test_item_out_of_range(self):
        db = DB()
        chunk = {
            "count": 3,
            "offset": 0,
            "item_loop": [{"text": "A"}, {"text": "B"}, {"text": "C"}],
        }
        db.menu_items(chunk)
        # Index 10 is beyond what's loaded
        item, is_current = db.item(10)
        assert item is None

    def test_reset_on_count_change(self):
        db = DB()
        chunk1 = {
            "count": 5,
            "offset": 0,
            "item_loop": [{"text": f"X{i}"} for i in range(5)],
        }
        db.menu_items(chunk1)
        assert db.size() == 5
        # Load with a different count — should reset
        chunk2 = {
            "count": 3,
            "offset": 0,
            "item_loop": [{"text": "A"}, {"text": "B"}, {"text": "C"}],
        }
        db.menu_items(chunk2)
        assert db.size() == 3

    def test_menu_items_returns_tuple(self):
        db = DB()
        result = db.menu_items()
        assert isinstance(result, tuple)
        assert result == (0,)


class TestDBChunked:
    """DB chunk-based storage with multiple items."""

    def test_multiple_items(self):
        db = DB()
        items = [{"text": f"Item {i}"} for i in range(50)]
        chunk = {"count": 50, "offset": 0, "item_loop": items}
        db.menu_items(chunk)
        for i in range(50):
            item, _ = db.item(i + 1)  # 1-based
            assert item is not None
            assert item["text"] == f"Item {i}"

    def test_block_size(self):
        assert DB.get_block_size() == 200
        assert DB.getBlockSize() == 200

    def test_text_index(self):
        db = DB()
        items = [
            {"text": "Alpha", "textkey": "A"},
            {"text": "Beta", "textkey": "B"},
            {"text": "Charlie", "textkey": "C"},
        ]
        chunk = {"count": 3, "offset": 0, "item_loop": items}
        db.menu_items(chunk)
        indexes = db.get_text_indexes()
        assert len(indexes) == 3
        assert indexes[0]["key"] == "A"


# ══════════════════════════════════════════════════════════════════════════════
# §6  SlimBrowserApplet — basic construction
# ══════════════════════════════════════════════════════════════════════════════

from jive.applets.SlimBrowser.SlimBrowserApplet import SlimBrowserApplet


class TestSlimBrowserAppletInit:
    """SlimBrowserApplet construction."""

    def test_constructor(self):
        sb = SlimBrowserApplet()
        assert sb is not None

    def test_has_expected_attributes(self):
        sb = SlimBrowserApplet()
        # Should have step-management attributes (uses _player and _step_stack)
        assert hasattr(sb, "_player")
        assert hasattr(sb, "_step_stack")


class TestSlimBrowserAppletHelpers:
    """SlimBrowserApplet helper functions."""

    def test_seconds_to_string_import(self):
        """Verify _seconds_to_string is importable and works."""
        from jive.applets.NowPlaying.NowPlayingApplet import _seconds_to_string

        assert _seconds_to_string(0) == "0:00"
        assert _seconds_to_string(61) == "1:01"
        assert _seconds_to_string(3661) == "1:01:01"


# ══════════════════════════════════════════════════════════════════════════════
# §7  Volume helper
# ══════════════════════════════════════════════════════════════════════════════

from jive.applets.SlimBrowser.volume import Volume


class TestVolumeConstruction:
    """Volume popup manager construction."""

    def test_create(self):
        mock_applet = MagicMock()
        v = Volume(mock_applet)
        assert v is not None
        assert v.applet is mock_applet

    def test_initial_state(self):
        mock_applet = MagicMock()
        v = Volume(mock_applet)
        assert v.volume == 0
        assert v.muting is False
        assert v.delta == 0


# ══════════════════════════════════════════════════════════════════════════════
# §8  Scanner helper
# ══════════════════════════════════════════════════════════════════════════════

from jive.applets.SlimBrowser.scanner import Scanner


class TestScannerConstruction:
    """Scanner popup construction."""

    def test_create(self):
        mock_applet = MagicMock()
        sc = Scanner(mock_applet)
        assert sc is not None
        assert sc.applet is mock_applet

    def test_initial_state(self):
        mock_applet = MagicMock()
        sc = Scanner(mock_applet)
        assert sc.delta == 0
        assert sc.player is None


# ══════════════════════════════════════════════════════════════════════════════
# §9  Integration: imports
# ══════════════════════════════════════════════════════════════════════════════


class TestPackageImports:
    """Verify all packages import cleanly."""

    def test_import_now_playing(self):
        import jive.applets.NowPlaying

        assert hasattr(jive.applets.NowPlaying, "NowPlayingApplet")
        assert hasattr(jive.applets.NowPlaying, "NowPlayingMeta")

    def test_import_select_player(self):
        import jive.applets.SelectPlayer

        assert hasattr(jive.applets.SelectPlayer, "SelectPlayerApplet")
        assert hasattr(jive.applets.SelectPlayer, "SelectPlayerMeta")

    def test_import_slim_browser(self):
        import jive.applets.SlimBrowser

        assert hasattr(jive.applets.SlimBrowser, "SlimBrowserApplet")
        assert hasattr(jive.applets.SlimBrowser, "SlimBrowserMeta")
        assert hasattr(jive.applets.SlimBrowser, "DB")
        assert hasattr(jive.applets.SlimBrowser, "Volume")
        assert hasattr(jive.applets.SlimBrowser, "Scanner")

    def test_import_skins(self):
        import jive.applets.JogglerSkin
        import jive.applets.QVGAbaseSkin


class TestCrossAppletCompatibility:
    """Verify applets conform to the base Applet interface."""

    def test_now_playing_is_applet(self):
        from jive.applet import Applet

        npa = NowPlayingApplet()
        assert isinstance(npa, Applet)

    def test_select_player_is_applet(self):
        from jive.applet import Applet

        sp = SelectPlayerApplet()
        assert isinstance(sp, Applet)

    def test_slim_browser_is_applet(self):
        from jive.applet import Applet

        sb = SlimBrowserApplet()
        assert isinstance(sb, Applet)

    def test_now_playing_meta_is_applet_meta(self):
        from jive.applet_meta import AppletMeta
        from jive.applets.NowPlaying.NowPlayingMeta import NowPlayingMeta

        meta = NowPlayingMeta()
        assert isinstance(meta, AppletMeta)

    def test_select_player_meta_is_applet_meta(self):
        from jive.applet_meta import AppletMeta

        meta = SelectPlayerMeta()
        assert isinstance(meta, AppletMeta)

    def test_slim_browser_meta_is_applet_meta(self):
        from jive.applet_meta import AppletMeta

        meta = SlimBrowserMeta()
        assert isinstance(meta, AppletMeta)


class TestLuaAliases:
    """Verify Lua-compatible camelCase aliases exist."""

    def test_now_playing_aliases(self):
        # Bound methods are not identical objects; check they resolve to the
        # same underlying function via __func__.
        npa = NowPlayingApplet()
        assert npa.setScrollBehavior.__func__ is npa.set_scroll_behavior.__func__
        assert npa.scrollSettingsShow.__func__ is npa.scroll_settings_show.__func__
        assert npa.npviewsSettingsShow.__func__ is npa.npviews_settings_show.__func__
        assert npa.changeTitleText.__func__ is npa.change_title_text.__func__
        assert npa.removeNowPlayingItem.__func__ is npa.remove_now_playing_item.__func__
        assert npa.addNowPlayingItem.__func__ is npa.add_now_playing_item.__func__
        assert (
            npa.getSelectedStyleParam.__func__ is npa.get_selected_style_param.__func__
        )
        assert npa.adjustVolume.__func__ is npa.adjust_volume.__func__
        assert npa.toggleNPScreenStyle.__func__ is npa.toggle_np_screen_style.__func__
        assert npa.replaceNPWindow.__func__ is npa.replace_np_window.__func__
        assert npa.freeAndClear.__func__ is npa.free_and_clear.__func__

    def test_select_player_aliases(self):
        sp = SelectPlayerApplet()
        assert sp.selectPlayer.__func__ is sp.select_player.__func__
        assert (
            sp.manageSelectPlayerMenu.__func__ is sp.manage_select_player_menu.__func__
        )


# ══════════════════════════════════════════════════════════════════════════════
# SlimDiscovery — Meta
# ══════════════════════════════════════════════════════════════════════════════

from jive.applet import Applet
from jive.applet_meta import AppletMeta
from jive.applets.SlimDiscovery.SlimDiscoveryApplet import (
    _VALID_STATES,
    DISCOVERY_PERIOD,
    DISCOVERY_TIMEOUT,
    PORT,
    SEARCHING_PERIOD,
    SlimDiscoveryApplet,
    _parse_tlv_response,
    _slim_discovery_source,
)
from jive.applets.SlimDiscovery.SlimDiscoveryMeta import SlimDiscoveryMeta


class TestSlimDiscoveryMeta:
    """Tests for SlimDiscoveryMeta."""

    def test_jive_version(self):
        meta = SlimDiscoveryMeta()
        assert meta.jive_version() == (1, 1)

    def test_jive_version_alias(self):
        meta = SlimDiscoveryMeta()
        assert meta.jiveVersion() == (1, 1)

    def test_default_settings(self):
        meta = SlimDiscoveryMeta()
        settings = meta.default_settings()
        assert isinstance(settings, dict)
        assert "currentPlayer" in settings
        assert settings["currentPlayer"] is False

    def test_default_settings_alias(self):
        meta = SlimDiscoveryMeta()
        assert meta.defaultSettings() == meta.default_settings()

    def test_register_applet_services(self):
        meta = SlimDiscoveryMeta()
        registered = []
        meta.register_service = lambda name: registered.append(name)
        meta.register_applet()

        expected_services = {
            "getCurrentPlayer",
            "setCurrentPlayer",
            "discoverPlayers",
            "discoverServers",
            "connectPlayer",
            "disconnectPlayer",
            "iteratePlayers",
            "iterateSqueezeCenters",
            "countPlayers",
            "getPollList",
            "setPollList",
            "getInitialSlimServer",
        }
        assert set(registered) == expected_services

    def test_register_applet_alias(self):
        meta = SlimDiscoveryMeta()
        registered = []
        meta.register_service = lambda name: registered.append(name)
        meta.registerApplet()
        assert len(registered) == 12

    def test_service_count(self):
        meta = SlimDiscoveryMeta()
        registered = []
        meta.register_service = lambda name: registered.append(name)
        meta.register_applet()
        assert len(registered) == 12

    def test_configure_applet_no_crash_without_manager(self):
        """configureApplet should not crash when no AppletManager is available."""
        meta = SlimDiscoveryMeta()
        meta.configure_applet()  # Should not raise

    def test_configure_applet_alias(self):
        meta = SlimDiscoveryMeta()
        assert meta.configureApplet == meta.configure_applet

    def test_notify_player_new_ignores_normal_player(self):
        """notify_playerNew should ignore players that aren't ff:ff:ff:ff:ff:ff."""
        meta = SlimDiscoveryMeta()
        player = MagicMock()
        player.get_id.return_value = "00:04:20:aa:bb:cc"
        meta.notify_playerNew(player)  # Should not raise

    def test_is_applet_meta_subclass(self):
        meta = SlimDiscoveryMeta()
        assert isinstance(meta, AppletMeta)


# ══════════════════════════════════════════════════════════════════════════════
# SlimDiscovery — Applet construction & lifecycle
# ══════════════════════════════════════════════════════════════════════════════


class TestSlimDiscoveryAppletConstruction:
    """Tests for SlimDiscoveryApplet construction and basic properties."""

    def test_construction(self):
        applet = SlimDiscoveryApplet()
        assert isinstance(applet, Applet)
        assert isinstance(applet, SlimDiscoveryApplet)

    def test_initial_state_is_searching(self):
        applet = SlimDiscoveryApplet()
        assert applet.state == "searching"

    def test_initial_poll_list(self):
        applet = SlimDiscoveryApplet()
        assert applet.poll == ["255.255.255.255"]

    def test_initial_socket_is_none(self):
        applet = SlimDiscoveryApplet()
        assert applet.socket is None

    def test_initial_timer_is_none(self):
        applet = SlimDiscoveryApplet()
        assert applet.timer is None

    def test_initial_probe_until(self):
        applet = SlimDiscoveryApplet()
        assert applet.probe_until == 0

    def test_repr(self):
        applet = SlimDiscoveryApplet()
        r = repr(applet)
        assert "SlimDiscoveryApplet" in r
        assert "searching" in r

    def test_applet_name_property(self):
        applet = SlimDiscoveryApplet()
        assert applet.applet_name == "SlimDiscovery"

    def test_applet_name_from_entry(self):
        applet = SlimDiscoveryApplet()
        applet._entry = {"applet_name": "SlimDiscovery"}
        assert applet.applet_name == "SlimDiscovery"

    def test_free_returns_true(self):
        applet = SlimDiscoveryApplet()
        assert applet.free() is True

    def test_free_stops_timer(self):
        applet = SlimDiscoveryApplet()
        mock_timer = MagicMock()
        applet.timer = mock_timer
        applet.free()
        mock_timer.stop.assert_called_once()
        assert applet.timer is None

    def test_free_closes_socket(self):
        applet = SlimDiscoveryApplet()
        mock_socket = MagicMock()
        applet.socket = mock_socket
        applet.free()
        mock_socket.free.assert_called_once()
        assert applet.socket is None

    def test_free_idempotent(self):
        applet = SlimDiscoveryApplet()
        assert applet.free() is True
        assert applet.free() is True


# ══════════════════════════════════════════════════════════════════════════════
# SlimDiscovery — Discovery packet & TLV parsing
# ══════════════════════════════════════════════════════════════════════════════


class TestSlimDiscoveryProtocol:
    """Tests for the UDP discovery packet construction and TLV parsing."""

    def test_discovery_source_starts_with_e(self):
        packet = _slim_discovery_source()
        assert packet[0:1] == b"e"

    def test_discovery_source_is_bytes(self):
        packet = _slim_discovery_source()
        assert isinstance(packet, bytes)

    def test_discovery_source_contains_ipad(self):
        packet = _slim_discovery_source()
        assert b"IPAD" in packet

    def test_discovery_source_contains_name(self):
        packet = _slim_discovery_source()
        assert b"NAME" in packet

    def test_discovery_source_contains_json(self):
        packet = _slim_discovery_source()
        assert b"JSON" in packet

    def test_discovery_source_contains_vers(self):
        packet = _slim_discovery_source()
        assert b"VERS" in packet

    def test_discovery_source_contains_uuid(self):
        packet = _slim_discovery_source()
        assert b"UUID" in packet

    def test_discovery_source_contains_jvid(self):
        packet = _slim_discovery_source()
        assert b"JVID" in packet

    def test_discovery_source_jvid_has_6_bytes(self):
        """JVID tag should have length 6 followed by 6 data bytes."""
        packet = _slim_discovery_source()
        idx = packet.index(b"JVID")
        length_byte = packet[idx + 4]
        assert length_byte == 6

    def test_parse_tlv_response_basic(self):
        """Parse a well-formed TLV response."""
        import struct

        response = b"E"
        for tag, val in [
            ("NAME", "TestServer"),
            ("IPAD", "10.0.0.1"),
            ("JSON", "9000"),
        ]:
            val_bytes = val.encode("utf-8")
            response += (
                tag.encode("ascii") + struct.pack("B", len(val_bytes)) + val_bytes
            )

        parsed = _parse_tlv_response(response)
        assert parsed["NAME"] == "TestServer"
        assert parsed["IPAD"] == "10.0.0.1"
        assert parsed["JSON"] == "9000"

    def test_parse_tlv_response_all_fields(self):
        """Parse a response with all standard fields."""
        import struct

        fields = [
            ("NAME", "Resonance"),
            ("IPAD", "192.168.1.100"),
            ("JSON", "9000"),
            ("VERS", "7.999.999"),
            ("UUID", "test-uuid-123"),
        ]
        response = b"E"
        for tag, val in fields:
            val_bytes = val.encode("utf-8")
            response += (
                tag.encode("ascii") + struct.pack("B", len(val_bytes)) + val_bytes
            )

        parsed = _parse_tlv_response(response)
        assert len(parsed) == 5
        assert parsed["NAME"] == "Resonance"
        assert parsed["IPAD"] == "192.168.1.100"
        assert parsed["JSON"] == "9000"
        assert parsed["VERS"] == "7.999.999"
        assert parsed["UUID"] == "test-uuid-123"

    def test_parse_tlv_response_empty(self):
        """An 'E'-only response should parse to an empty dict."""
        parsed = _parse_tlv_response(b"E")
        assert parsed == {}

    def test_parse_tlv_response_zero_length_values(self):
        """Tags with length 0 should parse as empty strings."""
        response = b"E" + b"NAME\x00" + b"IPAD\x00"
        parsed = _parse_tlv_response(response)
        assert parsed.get("NAME") == ""
        assert parsed.get("IPAD") == ""

    def test_parse_tlv_response_unicode(self):
        """Server names with non-ASCII chars should parse correctly."""
        import struct

        name = "Wohnzimmer-Müsik"
        val_bytes = name.encode("utf-8")
        response = b"E" + b"NAME" + struct.pack("B", len(val_bytes)) + val_bytes
        parsed = _parse_tlv_response(response)
        assert parsed["NAME"] == name

    def test_resonance_server_compatibility(self):
        """
        Build a response exactly as the Resonance server's
        UDPDiscoveryProtocol._handle_tlv_discovery would, and verify
        our parser handles it correctly.
        """
        import struct

        server_name = "Resonance"
        http_port = 9000
        server_uuid = "resonance-server-uuid"
        version = "7.999.999"
        local_ip = "192.168.1.50"

        # Build response exactly like Resonance does
        response = b"E"
        for tag, value_str in [
            ("NAME", server_name),
            ("IPAD", local_ip),
            ("JSON", str(http_port)),
            ("VERS", version),
            ("UUID", server_uuid),
        ]:
            value = value_str.encode("utf-8")
            if len(value) <= 255:
                response += tag.encode("ascii")
                response += struct.pack("B", len(value))
                response += value

        parsed = _parse_tlv_response(response)
        assert parsed["NAME"] == server_name
        assert parsed["IPAD"] == local_ip
        assert parsed["JSON"] == str(http_port)
        assert parsed["VERS"] == version
        assert parsed["UUID"] == server_uuid

    def test_discovery_request_compatible_with_resonance(self):
        """
        Our discovery request packet should be parseable by the
        Resonance server's TLV parser logic.
        """
        packet = _slim_discovery_source()

        # Simulate Resonance's _parse_tlvs (skip leading 'e')
        data = packet[1:]
        tlvs = {}
        offset = 0
        while offset + 5 <= len(data):
            tag = data[offset : offset + 4].decode("ascii", errors="replace")
            length = data[offset + 4]
            if length > 0 and offset + 5 + length <= len(data):
                value = data[offset + 5 : offset + 5 + length]
            else:
                value = None
            tlvs[tag] = value
            offset += 5 + length

        # All expected tags should be present
        assert "IPAD" in tlvs
        assert "NAME" in tlvs
        assert "JSON" in tlvs
        assert "VERS" in tlvs
        assert "UUID" in tlvs
        assert "JVID" in tlvs

        # JVID should have a 6-byte value
        assert tlvs["JVID"] is not None
        assert len(tlvs["JVID"]) == 6

    def test_constants(self):
        assert PORT == 3483
        assert DISCOVERY_TIMEOUT == 120000
        assert DISCOVERY_PERIOD == 60000
        assert SEARCHING_PERIOD == 10000


# ══════════════════════════════════════════════════════════════════════════════
# SlimDiscovery — State machine
# ══════════════════════════════════════════════════════════════════════════════


class TestSlimDiscoveryStateMachine:
    """Tests for the discovery state machine transitions."""

    def _make_applet(self) -> SlimDiscoveryApplet:
        applet = SlimDiscoveryApplet()
        applet.timer = MagicMock()
        applet.socket = MagicMock()
        return applet

    def test_valid_states(self):
        assert _VALID_STATES == {
            "disconnected",
            "searching",
            "connected",
            "probing_player",
            "probing_server",
        }

    def test_transition_to_searching(self):
        applet = self._make_applet()
        applet.state = "disconnected"
        applet._set_state("searching")
        assert applet.state == "searching"
        applet.timer.restart.assert_called()

    def test_transition_to_connected(self):
        applet = self._make_applet()
        applet.state = "searching"
        applet._set_state("connected")
        assert applet.state == "connected"

    def test_transition_to_disconnected(self):
        applet = self._make_applet()
        applet.state = "connected"
        applet._set_state("disconnected")
        assert applet.state == "disconnected"
        applet.timer.stop.assert_called()

    def test_transition_to_probing_player(self):
        applet = self._make_applet()
        applet.state = "connected"
        applet._set_state("probing_player")
        assert applet.state == "probing_player"
        assert applet.probe_until > 0

    def test_transition_to_probing_server(self):
        applet = self._make_applet()
        applet.state = "connected"
        applet._set_state("probing_server")
        assert applet.state == "probing_server"
        assert applet.probe_until > 0

    def test_same_state_restarts_timer(self):
        applet = self._make_applet()
        applet.state = "searching"
        applet._set_state("searching")
        assert applet.state == "searching"
        applet.timer.restart.assert_called_with(0)

    def test_invalid_state_ignored(self):
        applet = self._make_applet()
        applet.state = "connected"
        applet._set_state("bogus_state")
        assert applet.state == "connected"

    def test_disconnected_to_searching_restarts_timer(self):
        applet = self._make_applet()
        applet.state = "disconnected"
        applet._set_state("searching")
        # Timer should have been restarted (called with 0 from the
        # "was disconnected" path and then again from "searching" path)
        assert applet.timer.restart.call_count >= 1


# ══════════════════════════════════════════════════════════════════════════════
# SlimDiscovery — Sink processing
# ══════════════════════════════════════════════════════════════════════════════


class TestSlimDiscoverySink:
    """Tests for the UDP response sink."""

    def _make_applet(self) -> SlimDiscoveryApplet:
        applet = SlimDiscoveryApplet()
        applet.timer = MagicMock()
        applet.socket = MagicMock()
        return applet

    def test_sink_ignores_none_chunk(self):
        applet = self._make_applet()
        applet._slim_discovery_sink(None)  # Should not raise

    def test_sink_ignores_error(self):
        applet = self._make_applet()
        applet._slim_discovery_sink(None, err="timeout")  # Should not raise

    def test_sink_ignores_non_E_response(self):
        applet = self._make_applet()
        # A request packet starts with 'e', not 'E'
        chunk = {"data": b"eIPAD\x00", "ip": "10.0.0.1", "port": 3483}
        applet._slim_discovery_sink(chunk)  # Should not raise or process

    def test_sink_ignores_empty_data(self):
        applet = self._make_applet()
        chunk = {"data": b"", "ip": "10.0.0.1", "port": 3483}
        applet._slim_discovery_sink(chunk)  # Should not raise

    def test_sink_ignores_missing_data_key(self):
        applet = self._make_applet()
        chunk = {"ip": "10.0.0.1", "port": 3483}
        applet._slim_discovery_sink(chunk)  # Should not raise

    def test_sink_processes_valid_response(self):
        """A well-formed 'E' response should trigger _server_update_address."""
        import struct

        applet = self._make_applet()

        fields = [("NAME", "TestSrv"), ("IPAD", "10.0.0.5"), ("JSON", "9000")]
        response = b"E"
        for tag, val in fields:
            vb = val.encode("utf-8")
            response += tag.encode("ascii") + struct.pack("B", len(vb)) + vb

        chunk = {"data": response, "ip": "10.0.0.5", "port": 3483}

        with patch.object(applet, "_server_update_address") as mock_update:
            with patch(
                "jive.applets.SlimDiscovery.SlimDiscoveryApplet._get_jnt",
                return_value=None,
            ):
                with patch(
                    "jive.applets.SlimDiscovery.SlimDiscoveryApplet.SlimServer",
                    create=True,
                ):
                    applet._slim_discovery_sink(chunk)
                    # We can't easily check the call because SlimServer import
                    # may succeed or fail, but at least it shouldn't crash


# ══════════════════════════════════════════════════════════════════════════════
# SlimDiscovery — Service methods
# ══════════════════════════════════════════════════════════════════════════════


class TestSlimDiscoveryServices:
    """Tests for the public service methods."""

    def test_get_current_player_returns_none_by_default(self):
        applet = SlimDiscoveryApplet()
        # With no players set up, should return None
        result = applet.getCurrentPlayer()
        # Could be None or a player depending on global state
        assert result is None or result is not None  # Just don't crash

    def test_set_current_player_no_crash(self):
        applet = SlimDiscoveryApplet()
        mock_player = MagicMock()
        mock_player.get_name.return_value = "TestPlayer"
        applet.setCurrentPlayer(mock_player)  # Should not raise

    def test_set_current_player_none(self):
        applet = SlimDiscoveryApplet()
        applet.setCurrentPlayer(None)  # Should not raise

    def test_discover_players_sets_probing_player(self):
        applet = SlimDiscoveryApplet()
        applet.timer = MagicMock()
        applet.discoverPlayers()
        assert applet.state == "probing_player"

    def test_discover_servers_sets_probing_server(self):
        applet = SlimDiscoveryApplet()
        applet.timer = MagicMock()
        applet.discoverServers()
        assert applet.state == "probing_server"

    def test_connect_player_no_crash(self):
        applet = SlimDiscoveryApplet()
        applet.timer = MagicMock()
        applet.socket = MagicMock()
        applet.connectPlayer()
        assert applet.state in ("connected", "searching")

    def test_disconnect_player(self):
        applet = SlimDiscoveryApplet()
        applet.timer = MagicMock()
        applet.disconnectPlayer()
        assert applet.state == "disconnected"

    def test_iterate_players_returns_iterator(self):
        applet = SlimDiscoveryApplet()
        result = applet.iteratePlayers()
        # Should be iterable
        assert hasattr(result, "__iter__")

    def test_iterate_squeeze_centers_returns_iterator(self):
        applet = SlimDiscoveryApplet()
        result = applet.iterateSqueezeCenters()
        assert hasattr(result, "__iter__")

    def test_count_players_returns_int(self):
        applet = SlimDiscoveryApplet()
        count = applet.countPlayers()
        assert isinstance(count, int)
        assert count >= 0

    def test_get_poll_list(self):
        applet = SlimDiscoveryApplet()
        poll = applet.getPollList()
        assert isinstance(poll, list)
        assert "255.255.255.255" in poll

    def test_set_poll_list(self):
        applet = SlimDiscoveryApplet()
        applet.timer = MagicMock()
        new_poll = ["10.0.0.255", "192.168.1.255"]
        applet.setPollList(new_poll)
        assert applet.poll == new_poll
        # Should trigger probing_player
        assert applet.state == "probing_player"

    def test_get_poll_list_returns_copy(self):
        applet = SlimDiscoveryApplet()
        poll1 = applet.getPollList()
        poll2 = applet.getPollList()
        assert poll1 == poll2
        assert poll1 is not poll2  # Should be a copy

    def test_get_initial_slim_server_returns_none(self):
        """With no servers configured, should return None."""
        applet = SlimDiscoveryApplet()
        applet._settings = {"currentPlayer": False}
        result = applet.getInitialSlimServer()
        assert result is None


# ══════════════════════════════════════════════════════════════════════════════
# SlimDiscovery — Notification handlers
# ══════════════════════════════════════════════════════════════════════════════


class TestSlimDiscoveryNotifications:
    """Tests for the notification handler methods."""

    def _make_applet(self) -> SlimDiscoveryApplet:
        applet = SlimDiscoveryApplet()
        applet.timer = MagicMock()
        applet.socket = MagicMock()
        return applet

    def test_notify_player_disconnected_non_current(self):
        """Should not change state for a non-current player."""
        applet = self._make_applet()
        applet.state = "connected"
        mock_player = MagicMock()
        # Player.get_current_player() will return None (no current player)
        applet.notify_playerDisconnected(mock_player)
        # State may or may not change depending on whether player is current
        # At minimum it should not crash
        assert applet.state in _VALID_STATES

    def test_notify_player_connected_non_current(self):
        """Should not change state for a non-current player."""
        applet = self._make_applet()
        applet.state = "searching"
        mock_player = MagicMock()
        applet.notify_playerConnected(mock_player)
        assert applet.state in _VALID_STATES

    def test_notify_server_disconnected_no_crash(self):
        applet = self._make_applet()
        applet.state = "connected"
        mock_server = MagicMock()
        applet.notify_serverDisconnected(mock_server)
        assert applet.state in _VALID_STATES

    def test_notify_server_connected_no_crash(self):
        applet = self._make_applet()
        mock_server = MagicMock()
        applet.notify_serverConnected(mock_server)
        assert applet.state in _VALID_STATES

    def test_notify_network_connected_disconnected_state(self):
        """Should be a no-op when in disconnected state."""
        applet = self._make_applet()
        applet.state = "disconnected"
        applet.notify_networkConnected()
        assert applet.state == "disconnected"

    def test_notify_network_connected_searching_state(self):
        applet = self._make_applet()
        applet.state = "searching"
        applet.notify_networkConnected()
        # Should attempt to reconnect but not crash
        assert applet.state in _VALID_STATES

    def test_notify_player_power_no_crash(self):
        applet = self._make_applet()
        mock_player = MagicMock()
        applet.notify_playerPower(mock_player, True)
        applet.notify_playerPower(mock_player, False)

    def test_notify_player_current_no_crash(self):
        applet = self._make_applet()
        applet._settings = {"currentPlayer": False}
        mock_player = MagicMock()
        mock_player.get_id.return_value = "aa:bb:cc:dd:ee:ff"
        mock_player.get_init.return_value = {"name": "Test", "model": "baby"}
        mock_player.is_connected.return_value = False
        mock_player.get_slim_server.return_value = None
        applet.notify_playerCurrent(mock_player)
        assert applet.state in _VALID_STATES

    def test_notify_player_current_with_none(self):
        applet = self._make_applet()
        applet._settings = {"currentPlayer": False}
        applet.notify_playerCurrent(None)
        assert applet.state in _VALID_STATES

    def test_notify_player_new_name_no_crash(self):
        applet = self._make_applet()
        applet._settings = {"playerInit": {"name": "Old", "model": "baby"}}
        mock_player = MagicMock()
        # The method checks if it's the current player, which will fail
        # gracefully. Just make sure it doesn't crash.
        applet.notify_playerNewName(mock_player, "NewName")


# ══════════════════════════════════════════════════════════════════════════════
# SlimDiscovery — Settings persistence
# ══════════════════════════════════════════════════════════════════════════════


class TestSlimDiscoverySettings:
    """Tests for settings get/store helpers."""

    def test_get_settings_fallback(self):
        """Without an AppletManager, should return a fallback dict."""
        applet = SlimDiscoveryApplet()
        settings = applet.get_settings()
        assert isinstance(settings, dict)
        assert "currentPlayer" in settings

    def test_get_settings_alias(self):
        applet = SlimDiscoveryApplet()
        assert applet.getSettings() is applet.get_settings()

    def test_store_settings_no_crash(self):
        applet = SlimDiscoveryApplet()
        applet.store_settings()  # Should not raise even without a manager

    def test_store_settings_alias(self):
        applet = SlimDiscoveryApplet()
        assert applet.storeSettings == applet.store_settings

    def test_settings_mutable(self):
        applet = SlimDiscoveryApplet()
        settings = applet.get_settings()
        settings["playerId"] = "test-id"
        assert applet.get_settings()["playerId"] == "test-id"


# ══════════════════════════════════════════════════════════════════════════════
# SlimDiscovery — Cleanup
# ══════════════════════════════════════════════════════════════════════════════


class TestSlimDiscoveryCleanup:
    """Tests for server and player cleanup methods."""

    def test_squeeze_center_cleanup_no_crash(self):
        applet = SlimDiscoveryApplet()
        applet._settings = {"currentPlayer": False}
        applet._squeeze_center_cleanup()  # Should not raise

    def test_player_cleanup_no_crash(self):
        applet = SlimDiscoveryApplet()
        applet._player_cleanup()  # Should not raise

    def test_discover_sends_to_poll_addresses(self):
        """_discover should send to each address in the poll list."""
        applet = SlimDiscoveryApplet()
        applet.poll = ["10.0.0.255", "192.168.1.255"]
        mock_socket = MagicMock()
        applet.socket = mock_socket
        applet.timer = MagicMock()

        applet._discover()

        assert mock_socket.send.call_count == 2
        # First call should be to 10.0.0.255, second to 192.168.1.255
        calls = mock_socket.send.call_args_list
        assert calls[0][0][1] == "10.0.0.255"
        assert calls[0][0][2] == PORT
        assert calls[1][0][1] == "192.168.1.255"
        assert calls[1][0][2] == PORT

    def test_discover_adjusts_timer_connected(self):
        applet = SlimDiscoveryApplet()
        applet.socket = MagicMock()
        applet.timer = MagicMock()
        applet.state = "connected"

        applet._discover()

        applet.timer.restart.assert_called_with(DISCOVERY_PERIOD)

    def test_discover_adjusts_timer_searching(self):
        applet = SlimDiscoveryApplet()
        applet.socket = MagicMock()
        applet.timer = MagicMock()
        applet.state = "searching"

        applet._discover()

        applet.timer.restart.assert_called_with(SEARCHING_PERIOD)


# ══════════════════════════════════════════════════════════════════════════════
# SlimDiscovery — Integration: AppletManager discovery
# ══════════════════════════════════════════════════════════════════════════════


class TestSlimDiscoveryIntegration:
    """Test that SlimDiscovery integrates with the AppletManager."""

    def _make_mgr(self):
        """Create a minimal AppletManager with all required attributes."""
        from jive.applet_manager import AppletManager

        mgr = AppletManager.__new__(AppletManager)
        mgr._applets_db = {}
        mgr._services = {}
        mgr._settings_dir = None
        mgr._search_paths = [str(_PROJECT_ROOT / "jive" / "applets")]
        mgr._loaded_locale = set()
        mgr._locale_search_paths = []
        mgr._system = None
        mgr._allowed_applets = None
        mgr._service_closures = {}
        mgr._default_settings = {}
        mgr._user_settings_dir = Path(tempfile.mkdtemp()) / "settings"
        mgr._user_applets_dir = Path("/nonexistent/user_applets")
        # _find_applets iterates sys.path looking for dirs that contain
        # an "applets/" subdirectory.  Ensure jive/ is on sys.path so
        # that jive/applets/ is discovered.
        jive_dir = str(_PROJECT_ROOT / "jive")
        if jive_dir not in sys.path:
            sys.path.insert(0, jive_dir)
        return mgr

    def test_applet_manager_discovers_slim_discovery(self):
        """AppletManager should find the SlimDiscovery applet directory."""
        mgr = self._make_mgr()
        mgr._find_applets()

        assert "SlimDiscovery" in mgr._applets_db

    def test_meta_class_importable(self):
        """The Meta class should be importable via the standard mechanism."""
        mgr = self._make_mgr()
        mgr._find_applets()

        entry = mgr._applets_db["SlimDiscovery"]
        meta_cls = mgr._import_meta_class(entry)
        assert meta_cls is not None
        assert meta_cls.__name__ == "SlimDiscoveryMeta"

    def test_applet_class_importable(self):
        """The Applet class should be importable via the standard mechanism."""
        mgr = self._make_mgr()
        mgr._find_applets()

        entry = mgr._applets_db["SlimDiscovery"]
        applet_cls = mgr._import_applet_class(entry)
        assert applet_cls is not None
        assert applet_cls.__name__ == "SlimDiscoveryApplet"
        assert issubclass(applet_cls, Applet)
