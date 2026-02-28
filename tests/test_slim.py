"""
Comprehensive tests for jive.slim — Slim protocol layer.

Tests cover:
    - ArtworkCache: LRU eviction, set/get/free, loading sentinels, limit changes
    - Player: construction, singleton, identity, state, commands, notifications,
              status processing, MAC-to-model, browse history, playback controls
    - SlimServer: construction, singleton, address updates, serverstatus processing,
                  player management, artwork URL building, version comparison,
                  connect/disconnect lifecycle, credentials, app parameters
    - LocalPlayer: construction, device type, sequence numbers, local identity,
                   disconnect-and-preserve, refresh parameters

Copyright 2025 — BSD-3-Clause
"""

from __future__ import annotations

import gc
import time
import weakref
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Mock jnt (NetworkThread) for testing
# ---------------------------------------------------------------------------


class MockJnt:
    """Minimal mock of NetworkThread for testing notifications."""

    def __init__(self) -> None:
        self.notifications: List[Tuple[str, Tuple[Any, ...]]] = []
        self._subscribers: Dict[int, Any] = {}

    def notify(self, event: str, *args: Any) -> None:
        self.notifications.append((event, args))

    def subscribe(self, obj: Any) -> None:
        self._subscribers[id(obj)] = obj

    def unsubscribe(self, obj: Any) -> None:
        self._subscribers.pop(id(obj), None)

    def clear(self) -> None:
        self.notifications.clear()

    def get_events(self, event_name: str) -> List[Tuple[str, Tuple[Any, ...]]]:
        return [n for n in self.notifications if n[0] == event_name]


# ---------------------------------------------------------------------------
# Mock Comet for testing server/player interactions
# ---------------------------------------------------------------------------


class MockComet:
    """Minimal mock of Comet for testing SlimServer."""

    def __init__(self) -> None:
        self.connected: bool = False
        self.endpoint: Optional[Tuple[str, int, str]] = None
        self.subscriptions: Dict[str, Any] = {}
        self.requests: List[Any] = []
        self.batching: bool = False
        self.client_id: Optional[str] = None
        self._idle_timeout: Optional[int] = None
        self._aggressive: bool = False

    def connect(self) -> None:
        self.connected = True

    def disconnect(self) -> None:
        self.connected = False

    def set_endpoint(self, ip: str, port: int, path: str) -> None:
        self.endpoint = (ip, port, path)

    def subscribe(
        self,
        subscription: str,
        func: Any,
        player_id: Any = None,
        request: Any = None,
        **kwargs: Any,
    ) -> int:
        self.subscriptions[subscription] = {
            "func": func,
            "player_id": player_id,
            "request": request,
        }
        return len(self.subscriptions)

    def unsubscribe(self, subscription: str) -> None:
        self.subscriptions.pop(subscription, None)

    def request(self, func: Any, *args: Any) -> int:
        self.requests.append({"func": func, "args": args})
        return len(self.requests)

    def remove_request(self, req_id: int) -> bool:
        return True

    def start_batch(self) -> None:
        self.batching = True

    def end_batch(self) -> None:
        self.batching = False

    def aggressive_reconnect(self, value: bool) -> None:
        self._aggressive = value

    def set_idle_timeout(self, timeout: int) -> None:
        self._idle_timeout = timeout


# ===================================================================
# Fixtures
# ===================================================================


@pytest.fixture(autouse=True)
def _reset_globals():
    """Reset module-level state before each test."""
    from jive.slim.player import reset_player_globals
    from jive.slim.slim_server import reset_server_globals

    reset_player_globals()
    reset_server_globals()
    yield
    reset_player_globals()
    reset_server_globals()


@pytest.fixture
def jnt() -> MockJnt:
    return MockJnt()


@pytest.fixture
def comet() -> MockComet:
    return MockComet()


# ===================================================================
# ArtworkCache tests
# ===================================================================


class TestArtworkCache:
    """Tests for jive.slim.artwork_cache.ArtworkCache."""

    def _make_cache(self, limit: int = 1024) -> Any:
        from jive.slim.artwork_cache import ArtworkCache

        return ArtworkCache(limit=limit)

    # ----- Basic set / get -----

    def test_set_and_get_bytes(self):
        cache = self._make_cache()
        cache.set("key1", b"hello")
        assert cache.get("key1") == b"hello"

    def test_get_missing_key_returns_none(self):
        cache = self._make_cache()
        assert cache.get("nonexistent") is None

    def test_set_none_removes_entry(self):
        cache = self._make_cache()
        cache.set("key1", b"data")
        assert cache.get("key1") == b"data"
        cache.set("key1", None)
        assert cache.get("key1") is None

    def test_set_true_marks_as_loading(self):
        cache = self._make_cache()
        cache.set("key1", True)
        assert cache.get("key1") is True
        assert cache.total == 0  # Loading sentinel has no byte cost

    def test_overwrite_existing_key(self):
        cache = self._make_cache()
        cache.set("key1", b"old")
        cache.set("key1", b"new_value")
        assert cache.get("key1") == b"new_value"

    def test_overwrite_loading_with_bytes(self):
        cache = self._make_cache()
        cache.set("key1", True)
        assert cache.get("key1") is True
        cache.set("key1", b"real_data")
        assert cache.get("key1") == b"real_data"

    def test_set_invalid_type_raises(self):
        cache = self._make_cache()
        with pytest.raises(TypeError):
            cache.set("key1", 42)  # type: ignore[arg-type]

    # ----- Byte total tracking -----

    def test_total_tracks_bytes(self):
        cache = self._make_cache()
        cache.set("a", b"12345")
        assert cache.total == 5
        cache.set("b", b"abc")
        assert cache.total == 8
        cache.set("a", None)
        assert cache.total == 3

    def test_total_after_overwrite(self):
        cache = self._make_cache()
        cache.set("key", b"short")
        assert cache.total == 5
        cache.set("key", b"much_longer_value")
        assert cache.total == 17

    # ----- LRU eviction -----

    def test_eviction_when_over_limit(self):
        cache = self._make_cache(limit=10)
        cache.set("a", b"12345")  # 5 bytes
        cache.set("b", b"67890")  # 5 bytes → total 10
        assert cache.total == 10
        cache.set("c", b"x")  # 1 byte → total 11 → evict LRU (a)
        assert cache.get("a") is None
        assert cache.get("b") == b"67890"
        assert cache.get("c") == b"x"

    def test_eviction_order_is_lru(self):
        cache = self._make_cache(limit=15)
        cache.set("a", b"11111")  # 5
        cache.set("b", b"22222")  # 5 → total 10
        cache.set("c", b"33333")  # 5 → total 15

        # Access 'a' to make it MRU
        cache.get("a")

        # Now add new entry to trigger eviction
        cache.set("d", b"44444")  # 5 → total 20 → evict LRU = 'b'
        assert cache.get("b") is None  # evicted
        assert cache.get("a") == b"11111"  # still alive (was MRU)
        assert cache.get("c") == b"33333"  # might be evicted next
        assert cache.get("d") == b"44444"

    def test_multiple_evictions(self):
        cache = self._make_cache(limit=10)
        cache.set("a", b"12345")
        cache.set("b", b"67890")
        # Adding a big entry evicts both
        cache.set("c", b"ABCDEFGHIJ")  # 10 bytes
        assert cache.get("a") is None
        assert cache.get("b") is None
        assert cache.get("c") == b"ABCDEFGHIJ"
        assert cache.total == 10

    # ----- Loading sentinels not evicted -----

    def test_loading_sentinel_not_evicted(self):
        cache = self._make_cache(limit=5)
        cache.set("loading", True)
        cache.set("data", b"12345")
        assert cache.total == 5
        assert cache.get("loading") is True  # still there

    # ----- free() -----

    def test_free_clears_everything(self):
        cache = self._make_cache()
        cache.set("a", b"data")
        cache.set("b", True)
        cache.free()
        assert cache.get("a") is None
        assert cache.get("b") is None
        assert cache.total == 0
        assert len(cache) == 0

    # ----- __len__, __contains__, __repr__ -----

    def test_len(self):
        cache = self._make_cache()
        assert len(cache) == 0
        cache.set("a", b"x")
        cache.set("b", True)
        assert len(cache) == 2

    def test_contains(self):
        cache = self._make_cache()
        cache.set("a", b"x")
        assert "a" in cache
        assert "z" not in cache

    def test_repr(self):
        cache = self._make_cache(limit=1024)
        cache.set("a", b"hello")
        r = repr(cache)
        assert "ArtworkCache" in r
        assert "1024" in r

    # ----- limit property -----

    def test_limit_getter(self):
        cache = self._make_cache(limit=500)
        assert cache.limit == 500

    def test_limit_setter_triggers_eviction(self):
        cache = self._make_cache(limit=100)
        cache.set("a", b"x" * 50)
        cache.set("b", b"y" * 50)
        assert cache.total == 100
        cache.limit = 60  # shrink — should evict LRU (a)
        assert cache.total <= 60
        assert cache.get("a") is None
        assert cache.get("b") == b"y" * 50

    # ----- dump() doesn't crash -----

    def test_dump_does_not_crash(self):
        cache = self._make_cache()
        cache.set("a", b"data")
        cache.set("b", True)
        cache.dump()  # should not raise

    # ----- Edge cases -----

    def test_set_empty_bytes(self):
        cache = self._make_cache()
        cache.set("empty", b"")
        assert cache.get("empty") == b""
        assert cache.total == 0

    def test_set_bytearray(self):
        cache = self._make_cache()
        cache.set("ba", bytearray(b"hello"))
        assert cache.get("ba") == bytearray(b"hello")
        assert cache.total == 5

    def test_get_promotes_to_mru(self):
        cache = self._make_cache(limit=10)
        cache.set("old", b"aaa")  # 3 bytes
        cache.set("mid", b"bbb")  # 3 bytes
        cache.set("new", b"ccc")  # 3 bytes → total 9

        # Access "old" to make it MRU
        cache.get("old")

        # Add another → must evict LRU which is now "mid"
        cache.set("extra", b"dd")  # 2 bytes → total 11 → evict "mid"
        assert cache.get("mid") is None
        assert cache.get("old") == b"aaa"

    def test_single_entry_eviction(self):
        cache = self._make_cache(limit=3)
        cache.set("a", b"123")  # exactly at limit
        assert cache.total == 3
        cache.set("b", b"x")  # 1 byte → total 4 → evict a
        assert cache.get("a") is None
        assert cache.get("b") == b"x"
        assert cache.total == 1


# ===================================================================
# Player tests
# ===================================================================


class TestPlayer:
    """Tests for jive.slim.player.Player."""

    def _make_player(self, jnt: MockJnt, player_id: str = "00:04:20:aa:bb:cc") -> Any:
        from jive.slim.player import Player

        return Player(jnt, player_id)

    # ----- Construction -----

    def test_construction(self, jnt: MockJnt):
        player = self._make_player(jnt)
        assert player.id == "00:04:20:aa:bb:cc"
        assert player.jnt is jnt
        assert player.mode == "off"
        assert player.slim_server is False

    def test_id_lowercased(self, jnt: MockJnt):
        from jive.slim.player import Player

        p = Player(jnt, "AA:BB:CC:DD:EE:FF")
        assert p.id == "aa:bb:cc:dd:ee:ff"

    def test_singleton_per_id(self, jnt: MockJnt):
        from jive.slim.player import Player

        p1 = Player(jnt, "11:22:33:44:55:66")
        p2 = Player(jnt, "11:22:33:44:55:66")
        assert p1 is p2

    def test_different_ids_different_instances(self, jnt: MockJnt):
        from jive.slim.player import Player

        p1 = Player(jnt, "11:22:33:44:55:01")
        p2 = Player(jnt, "11:22:33:44:55:02")
        assert p1 is not p2

    # ----- Class-level operations -----

    def test_iterate_empty(self):
        from jive.slim.player import Player

        assert list(Player.iterate()) == []

    def test_get_current_player_initially_none(self):
        from jive.slim.player import Player

        assert Player.get_current_player() is None

    def test_set_current_player(self, jnt: MockJnt):
        from jive.slim.player import Player

        p = self._make_player(jnt)
        # Need a mock server for set_current_player
        mock_server = MagicMock()
        p.slim_server = mock_server
        Player.set_current_player(p)
        assert Player.get_current_player() is p

    def test_is_local_class_method(self):
        from jive.slim.player import Player

        assert Player.is_local() is False

    def test_get_rate_limit_time(self):
        from jive.slim.player import Player

        assert Player.get_rate_limit_time() == 150

    def test_get_local_player_none(self):
        from jive.slim.player import Player

        assert Player.get_local_player() is None

    # ----- Instance identity -----

    def test_is_local_player(self, jnt: MockJnt):
        p = self._make_player(jnt)
        assert p.is_local_player() is False

    def test_get_last_squeeze_center(self, jnt: MockJnt):
        p = self._make_player(jnt)
        assert p.get_last_squeeze_center() is None

    # ----- update_init -----

    def test_update_init(self, jnt: MockJnt):
        from jive.slim.player import Player

        p = self._make_player(jnt)
        p.update_init(None, {"name": "Living Room", "model": "squeezeplay"})
        assert p.info["name"] == "Living Room"
        assert p.info["model"] == "squeezeplay"
        assert p.info["connected"] is False
        # Should be in the player list now
        assert list(Player.iterate())

    def test_update_init_with_server(self, jnt: MockJnt):
        p = self._make_player(jnt)
        mock_server = MagicMock()
        p.update_init(mock_server, {"name": "Test", "model": "boom"})
        assert p.slim_server is mock_server
        mock_server._add_player.assert_called_once_with(p)

    def test_get_init(self, jnt: MockJnt):
        p = self._make_player(jnt)
        p.update_init(None, {"name": "Test", "model": "boom"})
        init = p.get_init()
        assert init["name"] == "Test"
        assert init["model"] == "boom"

    # ----- Property accessors -----

    def test_get_name_with_name(self, jnt: MockJnt):
        p = self._make_player(jnt)
        p.info["name"] = "Kitchen"
        assert p.get_name() == "Kitchen"

    def test_get_name_fallback(self, jnt: MockJnt):
        p = self._make_player(jnt)
        name = p.get_name()
        assert "Squeezebox" in name

    def test_get_id(self, jnt: MockJnt):
        p = self._make_player(jnt)
        assert p.get_id() == "00:04:20:aa:bb:cc"

    def test_is_power_on(self, jnt: MockJnt):
        p = self._make_player(jnt)
        assert p.is_power_on() is None
        p.info["power"] = True
        assert p.is_power_on() is True

    def test_get_model(self, jnt: MockJnt):
        p = self._make_player(jnt)
        p.info["model"] = "transporter"
        assert p.get_model() == "transporter"

    def test_get_uuid(self, jnt: MockJnt):
        p = self._make_player(jnt)
        assert p.get_uuid() is None
        p.info["uuid"] = "abc-123"
        assert p.get_uuid() == "abc-123"

    def test_get_pin(self, jnt: MockJnt):
        p = self._make_player(jnt)
        assert p.get_pin() is None
        p.info["pin"] = "1234"
        assert p.get_pin() == "1234"

    def test_clear_pin(self, jnt: MockJnt):
        p = self._make_player(jnt)
        p.info["pin"] = "1234"
        p.clear_pin()
        assert p.get_pin() is None

    def test_get_slim_server(self, jnt: MockJnt):
        p = self._make_player(jnt)
        assert p.get_slim_server() is False

    def test_get_mac_address_squeezeplay(self, jnt: MockJnt):
        p = self._make_player(jnt, "00:04:20:aa:bb:cc")
        p.info["model"] = "squeezeplay"
        mac = p.get_mac_address()
        assert mac == "000420aabbcc"

    def test_get_mac_address_unknown_model(self, jnt: MockJnt):
        p = self._make_player(jnt, "00:04:20:aa:bb:cc")
        p.info["model"] = "unknown_model"
        assert p.get_mac_address() is None

    # ----- Browse history -----

    def test_browse_history(self, jnt: MockJnt):
        p = self._make_player(jnt)
        assert p.get_last_browse("key1") is None
        assert p.get_last_browse_index("key1") is None

        p.set_last_browse_index("key1", 42)
        assert p.get_last_browse_index("key1") == 42

        p.set_last_browse("key2", {"index": 10, "data": "test"})
        assert p.get_last_browse("key2")["index"] == 10

        p.set_last_browse("key2", None)
        assert p.get_last_browse("key2") is None

    # ----- Track elapsed -----

    def test_get_track_elapsed_none(self, jnt: MockJnt):
        p = self._make_player(jnt)
        elapsed, duration = p.get_track_elapsed()
        assert elapsed is None
        assert duration is None

    def test_get_track_elapsed_stopped(self, jnt: MockJnt):
        p = self._make_player(jnt)
        p.track_time = 30.0
        p.track_duration = 180.0
        p.mode = "stop"
        p.track_correction = 0.0

        elapsed, duration = p.get_track_elapsed()
        assert elapsed == 30.0
        assert duration == 180.0

    def test_get_track_elapsed_playing(self, jnt: MockJnt):
        p = self._make_player(jnt)
        p.track_time = 10.0
        p.track_duration = 200.0
        p.mode = "play"
        p.rate = 1.0
        p.track_seen = time.monotonic()  # now
        p.track_correction = 0.0

        time.sleep(0.01)
        elapsed, duration = p.get_track_elapsed()
        # Elapsed should be slightly more than 10.0
        assert elapsed is not None
        assert elapsed >= 10.0
        assert duration == 200.0

    # ----- Playlist accessors -----

    def test_playlist_accessors(self, jnt: MockJnt):
        p = self._make_player(jnt)
        assert p.get_playlist_timestamp() is None
        assert p.get_playlist_size() is None
        assert p.get_playlist_current_index() is None

        p.playlist_timestamp = "123456"
        p.playlist_size = 10
        p.playlist_current_index = 3
        assert p.get_playlist_timestamp() == "123456"
        assert p.get_playlist_size() == 10
        assert p.get_playlist_current_index() == 3

    def test_get_player_mode(self, jnt: MockJnt):
        p = self._make_player(jnt)
        # state is empty dict {} which is falsy, but get_play_mode checks
        # `if self.state` — empty dict is falsy so returns None.
        # However, get_player_mode returns self.mode which is "off" initially.
        # The Lua original returns nil when state is empty, but our state
        # starts as {} which is truthy in the `if self.state` check...
        # Actually {} is falsy in Python? No, {} is truthy in Python!
        # So get_play_mode returns self.mode = "off"
        assert p.get_player_mode() == "off"

    def test_get_player_mode_with_state(self, jnt: MockJnt):
        p = self._make_player(jnt)
        p.state = {"mode": "play"}
        p.mode = "play"
        assert p.get_player_mode() == "play"

    # ----- Playback commands (mock server) -----

    def test_toggle_pause_from_stop(self, jnt: MockJnt, comet: MockComet):
        p = self._make_player(jnt)
        p.state = {"mode": "stop"}
        p.mode = "stop"
        mock_server = MagicMock()
        mock_server.comet = comet
        p.slim_server = mock_server
        p.toggle_pause()
        assert p.mode == "play"

    def test_toggle_pause_from_play(self, jnt: MockJnt, comet: MockComet):
        p = self._make_player(jnt)
        p.state = {"mode": "play"}
        p.mode = "play"
        mock_server = MagicMock()
        mock_server.comet = comet
        p.slim_server = mock_server
        p.toggle_pause()
        assert p.mode == "pause"

    def test_pause(self, jnt: MockJnt):
        p = self._make_player(jnt)
        p.state = {"mode": "play"}
        mock_server = MagicMock()
        p.slim_server = mock_server
        p.pause()
        assert p.mode == "pause"
        mock_server.user_request.assert_called()

    def test_unpause(self, jnt: MockJnt):
        p = self._make_player(jnt)
        p.state = {"mode": "pause"}
        p.mode = "pause"
        mock_server = MagicMock()
        p.slim_server = mock_server
        p.unpause()
        assert p.mode == "play"

    def test_play(self, jnt: MockJnt):
        p = self._make_player(jnt)
        p.state = {"mode": "stop"}
        p.mode = "stop"
        mock_server = MagicMock()
        p.slim_server = mock_server
        p.play()
        assert p.mode == "play"

    def test_stop(self, jnt: MockJnt):
        p = self._make_player(jnt)
        p.state = {"mode": "play"}
        mock_server = MagicMock()
        p.slim_server = mock_server
        p.stop()
        assert p.mode == "stop"

    def test_pause_without_state_does_nothing(self, jnt: MockJnt):
        p = self._make_player(jnt)
        p.state = {}  # empty
        p.pause()
        # Should not crash, mode unchanged

    def test_stop_preview(self, jnt: MockJnt):
        p = self._make_player(jnt)
        p.state = {"mode": "play"}
        mock_server = MagicMock()
        p.slim_server = mock_server
        p.stop_preview()
        mock_server.user_request.assert_called()

    # ----- is_paused / is_preset_defined -----

    def test_is_paused(self, jnt: MockJnt):
        p = self._make_player(jnt)
        assert p.is_paused() is False
        p.state = {"mode": "pause"}
        p.mode = "pause"
        assert p.is_paused() is True

    def test_is_preset_defined(self, jnt: MockJnt):
        p = self._make_player(jnt)
        # No presets → default True
        assert p.is_preset_defined(0) is True
        p.defined_presets = {0: 0, 1: 1, 2: 0}
        assert p.is_preset_defined(0) is False
        assert p.is_preset_defined(1) is True
        assert p.is_preset_defined(2) is False

    # ----- Alarm state -----

    def test_alarm_state(self, jnt: MockJnt):
        p = self._make_player(jnt)
        assert p.get_alarm_state() is None
        p.set_alarm_state("active")
        assert p.get_alarm_state() == "active"

    def test_waiting_to_play(self, jnt: MockJnt):
        p = self._make_player(jnt)
        assert p.is_waiting_to_play() is False
        p.set_waiting_to_play(True)
        assert p.is_waiting_to_play() is True

    # ----- Snooze / stop alarm -----

    def test_snooze(self, jnt: MockJnt):
        p = self._make_player(jnt)
        p.state = {"mode": "play"}
        p.alarm_state = "active"
        mock_server = MagicMock()
        p.slim_server = mock_server
        p.snooze()
        assert p.alarm_state == "snooze"

    def test_stop_alarm(self, jnt: MockJnt):
        p = self._make_player(jnt)
        p.state = {"mode": "play"}
        p.alarm_state = "active"
        mock_server = MagicMock()
        p.slim_server = mock_server
        p.stop_alarm()
        assert p.alarm_state == "none"

    # ----- Playlist operations -----

    def test_playlist_jump_index(self, jnt: MockJnt):
        p = self._make_player(jnt)
        mock_server = MagicMock()
        p.slim_server = mock_server
        p.playlist_jump_index(3)
        call_args = mock_server.user_request.call_args
        cmd = call_args[0][1]  # second arg to user_request is player_id
        # The sink is first, player_id second, cmd third
        # Actually call() builds the command internally via _get_sink
        mock_server.user_request.assert_called()

    def test_playlist_jump_index_zero(self, jnt: MockJnt):
        p = self._make_player(jnt)
        mock_server = MagicMock()
        p.slim_server = mock_server
        p.playlist_jump_index(0)  # Should be rejected
        mock_server.user_request.assert_not_called()

    def test_playlist_delete_index(self, jnt: MockJnt):
        p = self._make_player(jnt)
        mock_server = MagicMock()
        p.slim_server = mock_server
        p.playlist_delete_index(5)
        mock_server.user_request.assert_called()

    # ----- Button commands -----

    def test_button(self, jnt: MockJnt):
        p = self._make_player(jnt)
        mock_server = MagicMock()
        p.slim_server = mock_server
        p.button("play")
        mock_server.user_request.assert_called()
        # Second call within rate limit should be suppressed
        mock_server.reset_mock()
        p.button("play")
        mock_server.user_request.assert_not_called()

    def test_repeat_toggle(self, jnt: MockJnt):
        p = self._make_player(jnt)
        mock_server = MagicMock()
        p.slim_server = mock_server
        p.repeat_toggle()
        mock_server.user_request.assert_called()

    def test_shuffle_toggle(self, jnt: MockJnt):
        p = self._make_player(jnt)
        mock_server = MagicMock()
        p.slim_server = mock_server
        p.shuffle_toggle()
        mock_server.user_request.assert_called()

    def test_power_toggle(self, jnt: MockJnt):
        p = self._make_player(jnt)
        mock_server = MagicMock()
        p.slim_server = mock_server
        p.power_toggle()
        mock_server.user_request.assert_called()

    def test_rew_fwd(self, jnt: MockJnt):
        p = self._make_player(jnt)
        mock_server = MagicMock()
        p.slim_server = mock_server
        p.rew()
        mock_server.user_request.assert_called()
        mock_server.reset_mock()
        # reset button_to so fwd goes through
        p.button_to = None
        p.fwd()
        mock_server.user_request.assert_called()

    # ----- Power -----

    def test_set_power(self, jnt: MockJnt):
        p = self._make_player(jnt)
        p.state = {"power": 0}
        mock_server = MagicMock()
        p.slim_server = mock_server
        p.set_power(True)
        mock_server.request.assert_called()

    def test_set_power_server_request_ignored(self, jnt: MockJnt):
        p = self._make_player(jnt)
        p.state = {"power": 0}
        mock_server = MagicMock()
        p.slim_server = mock_server
        p.set_power(True, is_server_request=True)
        mock_server.request.assert_not_called()

    # ----- Volume -----

    def test_volume(self, jnt: MockJnt):
        p = self._make_player(jnt)
        p.state = {"mixer volume": 50}
        mock_server = MagicMock()
        p.slim_server = mock_server
        result = p.volume(75)
        assert result == 75
        assert p.state["mixer volume"] == 75

    def test_volume_rate_limited(self, jnt: MockJnt):
        p = self._make_player(jnt)
        p.state = {"mixer volume": 50}
        mock_server = MagicMock()
        p.slim_server = mock_server
        p.volume(60)
        result = p.volume(70)  # rate-limited
        assert result is None

    def test_get_volume(self, jnt: MockJnt):
        p = self._make_player(jnt)
        assert p.get_volume() is None
        p.state = {"mixer volume": 42}
        assert p.get_volume() == 42

    def test_mute_unmute(self, jnt: MockJnt):
        p = self._make_player(jnt)
        p.state = {"mixer volume": 50}
        mock_server = MagicMock()
        p.slim_server = mock_server
        vol = p.mute(True)
        assert vol == -50
        vol = p.mute(False)
        assert vol == 50

    # ----- goto_time -----

    def test_goto_time(self, jnt: MockJnt):
        p = self._make_player(jnt)
        mock_server = MagicMock()
        p.slim_server = mock_server
        p.goto_time(30.5)
        assert p.track_time == 30.5
        assert p.is_waiting_to_play() is True

    # ----- is_track_seekable / is_remote -----

    def test_is_track_seekable(self, jnt: MockJnt):
        p = self._make_player(jnt)
        assert p.is_track_seekable() is False
        p.track_duration = 180.0
        p.state = {"can_seek": 1}
        assert p.is_track_seekable() is True

    def test_is_remote(self, jnt: MockJnt):
        p = self._make_player(jnt)
        assert p.is_remote() is False
        p.state = {"remote": 1}
        assert p.is_remote() is True

    # ----- is_current -----

    def test_is_current(self, jnt: MockJnt):
        p = self._make_player(jnt)
        assert p.is_current(1) is False
        p.state = {"playlist_cur_index": 0}
        assert p.is_current(1) is True
        assert p.is_current(2) is False

    # ----- is_connected -----

    def test_is_connected(self, jnt: MockJnt):
        p = self._make_player(jnt)
        assert p.is_connected() is False

        mock_server = MagicMock()
        mock_server.is_connected.return_value = True
        p.slim_server = mock_server
        p.info["connected"] = True
        assert p.is_connected() is True

    # ----- is_available / needs_* -----

    def test_is_available(self, jnt: MockJnt):
        p = self._make_player(jnt)
        assert p.is_available() is False  # config is False
        p.config = True
        assert p.is_available() is True

    def test_needs_network_config(self, jnt: MockJnt):
        p = self._make_player(jnt)
        assert p.needs_network_config() is False
        p.config = "needsNetwork"
        assert p.needs_network_config() is True

    def test_needs_music_source(self, jnt: MockJnt):
        p = self._make_player(jnt)
        assert p.needs_music_source() is False
        p.config = "needsServer"
        assert p.needs_music_source() is True

    # ----- can_connect_to_server -----

    def test_can_connect_to_server(self, jnt: MockJnt):
        p = self._make_player(jnt)
        p.info["model"] = "squeezeplay"
        assert p.can_connect_to_server() is True
        p.info["model"] = "squeezebox3"
        assert p.can_connect_to_server() is True
        p.info["model"] = "softsqueeze"
        assert p.can_connect_to_server() is False

    # ----- sequence number stubs -----

    def test_sequence_number_in_sync(self, jnt: MockJnt):
        p = self._make_player(jnt)
        assert p.is_sequence_number_in_sync(99) is True

    # ----- capture play mode -----

    def test_capture_play_mode(self, jnt: MockJnt):
        p = self._make_player(jnt)
        assert p.get_capture_play_mode() is False
        p.set_capture_play_mode(True)
        # Base Player ignores it
        assert p.get_capture_play_mode() is False

    # ----- __repr__ / __str__ -----

    def test_repr(self, jnt: MockJnt):
        p = self._make_player(jnt)
        assert "00:04:20:aa:bb:cc" in repr(p)

    def test_str(self, jnt: MockJnt):
        p = self._make_player(jnt)
        p.info["name"] = "Bedroom"
        assert "Bedroom" in str(p)

    # ----- MAC-to-model -----

    def test_mac_to_model_slim_prefix(self, jnt: MockJnt):
        from jive.slim.player import Player

        # 'a' in "aa" is alpha → squeezebox2; digit-only b → squeezebox
        assert Player.mac_to_model("00:04:20:05:11:bb") == "squeezebox"
        assert Player.mac_to_model("00:04:20:05:aa:bb") == "squeezebox2"
        assert Player.mac_to_model("00:04:20:06:aa:bb") == "squeezebox3"
        assert Player.mac_to_model("00:04:20:10:aa:bb") == "transporter"
        assert Player.mac_to_model("00:04:20:16:aa:bb") == "receiver"
        assert Player.mac_to_model("00:04:20:1a:aa:bb") == "controller"
        assert Player.mac_to_model("00:04:20:1e:aa:bb") == "boom"
        assert Player.mac_to_model("00:04:20:04:aa:bb") == "slimp3"

    def test_mac_to_model_non_slim(self, jnt: MockJnt):
        from jive.slim.player import Player

        assert Player.mac_to_model("aa:bb:cc:dd:ee:ff") == "squeezeplay"

    def test_mac_to_model_none(self, jnt: MockJnt):
        from jive.slim.player import Player

        assert Player.mac_to_model(None) is None

    def test_mac_to_model_invalid(self, jnt: MockJnt):
        from jive.slim.player import Player

        assert Player.mac_to_model("not-a-mac") == "squeezeplay"

    # ----- ssid_is_squeezebox -----

    def test_ssid_is_squeezebox(self):
        from jive.slim.player import Player

        mac, eth = Player.ssid_is_squeezebox("logitech+squeezebox+aabbccddeeff")
        assert mac == "aa:bb:cc:dd:ee:ff"

    def test_ssid_is_squeezebox_not_matching(self):
        from jive.slim.player import Player

        mac, eth = Player.ssid_is_squeezebox("MyWiFiNetwork")
        assert mac is None

    # ----- free -----

    def test_free_removes_from_player_list(self, jnt: MockJnt):
        from jive.slim.player import Player

        p = self._make_player(jnt)
        p.update_init(None, {"name": "Test", "model": "squeezeplay"})
        assert p.id in dict(Player.iterate())
        p.free()
        assert p.id not in dict(Player.iterate())

    def test_free_with_wrong_server(self, jnt: MockJnt):
        p = self._make_player(jnt)
        server1 = MagicMock()
        server2 = MagicMock()
        p.slim_server = server1
        p.free(server2)  # Should be ignored
        assert p.slim_server is server1

    # ----- on_stage / off_stage -----

    def test_on_stage_off_stage(self, jnt: MockJnt, comet: MockComet):
        p = self._make_player(jnt)
        mock_server = MagicMock()
        mock_server.comet = comet
        p.slim_server = mock_server
        p.on_stage()
        assert p.is_on_stage is True
        assert f"/slim/playerstatus/{p.id}" in comet.subscriptions

        p.off_stage()
        assert p.is_on_stage is False

    # ----- _process_status -----

    def test_process_status(self, jnt: MockJnt):
        p = self._make_player(jnt)
        p.state = {}
        mock_server = MagicMock()
        mock_server.is_connected.return_value = True
        p.slim_server = mock_server
        p.update_init(mock_server, {"name": "Test", "model": "squeezeplay"})

        status_data = {
            "data": {
                "mode": "play",
                "rate": 1.0,
                "time": 42.5,
                "duration": 200.0,
                "playlist_tracks": 10,
                "playlist_cur_index": 2,
                "playlist_timestamp": "ts123",
                "player_name": "Test",
                "player_connected": 1,
                "power": 1,
                "mixer volume": 75,
                "playlist shuffle": 0,
                "playlist repeat": 0,
                "item_loop": [{"text": "Song Title", "params": {"track_id": "123"}}],
            }
        }

        jnt.clear()
        p._process_status(status_data)

        assert p.mode == "play"
        assert p.track_time == 42.5
        assert p.track_duration == 200.0
        assert p.playlist_size == 10
        assert p.playlist_current_index == 3  # 0-based + 1
        assert p.now_playing == "123"

    def test_process_status_error_ignored(self, jnt: MockJnt):
        p = self._make_player(jnt)
        p.state = {}
        mock_server = MagicMock()
        mock_server.is_connected.return_value = True
        p.slim_server = mock_server
        p.update_init(mock_server, {"name": "Test", "model": "squeezeplay"})

        status_data = {"data": {"error": "some error"}}
        p._process_status(status_data)
        # Should not update state
        assert p.mode != "play"

    # ----- _process_displaystatus (smoke test) -----

    def test_process_displaystatus_smoke(self, jnt: MockJnt):
        p = self._make_player(jnt)
        # Should not crash
        p._process_displaystatus(
            {
                "data": {
                    "display": {
                        "type": "text",
                        "text": ["Hello", "World"],
                        "duration": 3000,
                    }
                }
            }
        )

    # ----- _process_button -----

    def test_process_button_clears_timeout(self, jnt: MockJnt):
        p = self._make_player(jnt)
        p.button_to = 999999
        p._process_button({})
        assert p.button_to is None

    # ----- update_player_info with notifications -----

    def test_update_player_info_notifications(self, jnt: MockJnt):
        p = self._make_player(jnt)
        mock_server = MagicMock()
        mock_server.is_connected.return_value = True
        p.slim_server = mock_server
        p.update_init(mock_server, {"name": "OldName", "model": "squeezeplay"})

        jnt.clear()

        p.update_player_info(
            mock_server,
            {
                "name": "NewName",
                "model": "squeezeplay",
                "connected": 1,
                "power": 1,
            },
        )

        events = [n[0] for n in jnt.notifications]
        assert "playerNewName" in events
        assert "playerConnected" in events

    def test_update_player_info_server_change(self, jnt: MockJnt):
        from jive.slim.player import Player

        p = self._make_player(jnt)
        server1 = MagicMock()
        server1.is_connected.return_value = True
        server2 = MagicMock()
        server2.is_connected.return_value = True

        p.update_init(server1, {"name": "Test", "model": "squeezeplay"})
        p.slim_server = server1
        p.info["connected"] = True

        jnt.clear()
        p.update_player_info(
            server2,
            {
                "name": "Test",
                "model": "squeezeplay",
                "connected": 1,
                "power": 1,
            },
        )

        events = [n[0] for n in jnt.notifications]
        assert "playerNew" in events
        assert p.slim_server is server2

    # ----- volume_local -----

    def test_volume_local(self, jnt: MockJnt):
        p = self._make_player(jnt)
        p.state = {"mixer volume": 50}
        p.volume_local(80)
        assert p.state["mixer volume"] == 80

    # ----- get_alarm_snooze_seconds / get_alarm_timeout_seconds -----

    def test_alarm_seconds_defaults(self, jnt: MockJnt):
        p = self._make_player(jnt)
        assert p.get_alarm_snooze_seconds() == 540
        assert p.get_alarm_timeout_seconds() == 3600

    def test_alarm_seconds_custom(self, jnt: MockJnt):
        p = self._make_player(jnt)
        p.alarm_snooze_seconds = 300
        p.alarm_timeout_seconds = 1800
        assert p.get_alarm_snooze_seconds() == 300
        assert p.get_alarm_timeout_seconds() == 1800

    # ----- digital volume control -----

    def test_digital_volume_control(self, jnt: MockJnt):
        p = self._make_player(jnt)
        assert p.get_digital_volume_control() == 1  # default when None
        # 0 is falsy, so `or 1` returns 1 — matching Lua `or 1` semantics
        p.info["digital_volume_control"] = 0
        assert p.get_digital_volume_control() == 1  # 0 or 1 == 1
        p.info["digital_volume_control"] = 2
        assert p.get_digital_volume_control() == 2

    def test_use_volume_control(self, jnt: MockJnt):
        p = self._make_player(jnt)
        assert p.use_volume_control() == 1

    # ----- get_effective_play_mode -----

    def test_get_effective_play_mode(self, jnt: MockJnt):
        p = self._make_player(jnt)
        p.state = {"mode": "play"}
        p.mode = "play"
        assert p.get_effective_play_mode() == "play"

    # ----- has_connection_failed -----

    def test_has_connection_failed(self, jnt: MockJnt):
        p = self._make_player(jnt)
        assert p.has_connection_failed() is False

    # ----- is_needs_upgrade / is_upgrading -----

    def test_is_needs_upgrade(self, jnt: MockJnt):
        p = self._make_player(jnt)
        assert p.is_needs_upgrade() is False
        p.info["needs_upgrade"] = True
        assert p.is_needs_upgrade() is True

    def test_is_upgrading(self, jnt: MockJnt):
        p = self._make_player(jnt)
        assert p.is_upgrading() is False
        p.info["is_upgrading"] = True
        assert p.is_upgrading() is True

    # ----- get_ssid -----

    def test_get_ssid(self, jnt: MockJnt):
        p = self._make_player(jnt)
        assert p.get_ssid() is None
        p.config = "needsNetwork"
        p.config_ssid = "logitech+squeezebox+aabbccddeeff"
        assert p.get_ssid() == "logitech+squeezebox+aabbccddeeff"


# ===================================================================
# Player helper tests
# ===================================================================


class TestPlayerHelpers:
    """Tests for module-level helper functions in player.py."""

    def test_to_bool(self):
        from jive.slim.player import _to_bool

        assert _to_bool(None) is False
        assert _to_bool(True) is True
        assert _to_bool(False) is False
        assert _to_bool(1) is True
        assert _to_bool(0) is False
        assert _to_bool("1") is True
        assert _to_bool("0") is False

    def test_to_int_or_none(self):
        from jive.slim.player import _to_int_or_none

        assert _to_int_or_none(None) is None
        assert _to_int_or_none(42) == 42
        assert _to_int_or_none("7") == 7
        assert _to_int_or_none("abc") is None

    def test_to_float(self):
        from jive.slim.player import _to_float

        assert _to_float(None) is None
        assert _to_float(3.14) == 3.14
        assert _to_float("2.5") == 2.5
        assert _to_float("abc") is None

    def test_format_show_briefly_text_string(self):
        from jive.slim.player import _format_show_briefly_text

        assert _format_show_briefly_text("hello") == "hello"
        assert _format_show_briefly_text("a\\nb") == "a\nb"

    def test_format_show_briefly_text_list(self):
        from jive.slim.player import _format_show_briefly_text

        assert _format_show_briefly_text(["hello", "world"]) == "hello\nworld"

    def test_format_show_briefly_text_mixed(self):
        from jive.slim.player import _format_show_briefly_text

        result = _format_show_briefly_text(["line1", 42, "line3"])
        assert "line1" in result
        assert "42" in result

    def test_format_show_briefly_text_none(self):
        from jive.slim.player import _format_show_briefly_text

        assert _format_show_briefly_text(None) == ""

    def test_whats_playing_with_track_id(self):
        from jive.slim.player import _whats_playing

        data = {"item_loop": [{"params": {"track_id": "123"}, "text": "Song"}]}
        wp, art = _whats_playing(data)
        assert wp == "123"

    def test_whats_playing_remote(self):
        from jive.slim.player import _whats_playing

        data = {
            "remote": True,
            "current_title": "Radio Station",
            "item_loop": [{"params": {"track_id": "x"}, "text": "Stream Name"}],
        }
        wp, art = _whats_playing(data)
        assert "Stream Name" in wp
        assert "Radio Station" in wp

    def test_whats_playing_empty(self):
        from jive.slim.player import _whats_playing

        wp, art = _whats_playing({})
        assert wp is None
        assert art is None

    def test_whats_playing_artwork(self):
        from jive.slim.player import _whats_playing

        data = {"item_loop": [{"params": {"track_id": "1"}, "icon-id": "abc123"}]}
        wp, art = _whats_playing(data)
        assert art == "abc123"


# ===================================================================
# SlimServer tests
# ===================================================================


class TestSlimServer:
    """Tests for jive.slim.slim_server.SlimServer."""

    def _make_server(
        self,
        jnt: MockJnt,
        server_id: str = "test-server-1",
        name: str = "Test LMS",
        version: str = "8.5.0",
        comet: Optional[MockComet] = None,
    ) -> Any:
        from jive.slim.slim_server import SlimServer

        server = SlimServer(jnt, server_id, name, version)
        if comet is not None:
            server.comet = comet
        return server

    # ----- Construction -----

    def test_construction(self, jnt: MockJnt, comet: MockComet):
        server = self._make_server(jnt, comet=comet)
        assert server.id == "test-server-1"
        assert server.name == "Test LMS"
        assert server.get_version() == "8.5.0"
        assert server.netstate == "disconnected"

    def test_singleton_per_id(self, jnt: MockJnt, comet: MockComet):
        from jive.slim.slim_server import SlimServer

        s1 = SlimServer(jnt, "same-id", "Server1")
        s1.comet = comet
        s2 = SlimServer(jnt, "same-id", "Server2")
        assert s1 is s2

    def test_different_ids_different_instances(self, jnt: MockJnt, comet: MockComet):
        s1 = self._make_server(jnt, "id-1", comet=comet)
        s2 = self._make_server(jnt, "id-2", comet=comet)
        assert s1 is not s2

    # ----- Class-level operations -----

    def test_iterate_empty(self):
        from jive.slim.slim_server import SlimServer

        assert list(SlimServer.iterate()) == []

    def test_get_current_server_initially_none(self):
        from jive.slim.slim_server import SlimServer

        assert SlimServer.get_current_server() is None

    def test_set_current_server(self, jnt: MockJnt, comet: MockComet):
        from jive.slim.slim_server import SlimServer

        s = self._make_server(jnt, comet=comet)
        SlimServer.set_current_server(s)
        assert SlimServer.get_current_server() is s

    def test_set_current_server_none(self, jnt: MockJnt, comet: MockComet):
        from jive.slim.slim_server import SlimServer

        s = self._make_server(jnt, comet=comet)
        SlimServer.set_current_server(s)
        SlimServer.set_current_server(None)
        assert SlimServer.get_current_server() is None

    def test_get_server_by_address(self, jnt: MockJnt, comet: MockComet):
        from jive.slim.slim_server import SlimServer

        s = self._make_server(jnt, comet=comet)
        s.ip = "192.168.1.100"
        s.last_seen = 1
        from jive.slim.slim_server import _server_list

        _server_list[s.id] = s
        result = SlimServer.get_server_by_address("192.168.1.100")
        assert result is s
        assert SlimServer.get_server_by_address("10.0.0.1") is None

    # ----- Accessors -----

    def test_get_name(self, jnt: MockJnt, comet: MockComet):
        s = self._make_server(jnt, name="My Server", comet=comet)
        assert s.get_name() == "My Server"

    def test_get_id(self, jnt: MockJnt, comet: MockComet):
        s = self._make_server(jnt, server_id="srv-42", comet=comet)
        assert s.get_id() == "srv-42"

    def test_get_ip_port(self, jnt: MockJnt, comet: MockComet):
        s = self._make_server(jnt, comet=comet)
        assert s.get_ip_port() == (False, False)
        s.ip = "10.0.0.1"
        s.port = 9000
        assert s.get_ip_port() == ("10.0.0.1", 9000)

    def test_get_last_seen(self, jnt: MockJnt, comet: MockComet):
        s = self._make_server(jnt, comet=comet)
        assert s.get_last_seen() == 0

    def test_is_connected(self, jnt: MockJnt, comet: MockComet):
        s = self._make_server(jnt, comet=comet)
        assert s.is_connected() is False
        s.netstate = "connected"
        assert s.is_connected() is True

    def test_is_squeeze_network(self, jnt: MockJnt, comet: MockComet):
        s = self._make_server(jnt, comet=comet)
        assert s.is_squeeze_network() is False

    # ----- Version comparison -----

    def test_is_more_recent(self):
        from jive.slim.slim_server import SlimServer

        assert SlimServer.is_more_recent("8.0.0", "7.4.0") is True
        assert SlimServer.is_more_recent("7.4.0", "8.0.0") is False
        assert SlimServer.is_more_recent("7.4.0", "7.4.0") is False
        assert SlimServer.is_more_recent("7.5.0", "7.4.9") is True
        assert SlimServer.is_more_recent("7.4.1", "7.4.0") is True

    def test_is_compatible(self, jnt: MockJnt, comet: MockComet):
        s = self._make_server(jnt, version="8.5.0", comet=comet)
        assert s.is_compatible() is True

        s2 = self._make_server(jnt, server_id="old", version="7.0.0", comet=comet)
        assert s2.is_compatible() is False

    def test_is_compatible_unknown_version(self, jnt: MockJnt, comet: MockComet):
        s = self._make_server(jnt, server_id="unknown", version=None, comet=comet)
        assert s.is_compatible() is None

    def test_set_minimum_version(self, jnt: MockJnt, comet: MockComet):
        from jive.slim.slim_server import SlimServer

        SlimServer.set_minimum_version("8.0.0")
        s = self._make_server(jnt, server_id="v75", version="7.5.0", comet=comet)
        assert s.is_compatible() is False
        SlimServer.set_minimum_version("7.4")  # reset

    # ----- update_init / get_init -----

    def test_update_init(self, jnt: MockJnt, comet: MockComet):
        from jive.slim.slim_server import SlimServer

        s = self._make_server(jnt, comet=comet)
        s.update_init({"ip": "10.0.0.1", "mac": "aa:bb:cc:dd:ee:ff"})
        assert s.ip == "10.0.0.1"
        assert s.mac == "aa:bb:cc:dd:ee:ff"
        assert s.id in dict(SlimServer.iterate())

    def test_update_init_already_initialised(self, jnt: MockJnt, comet: MockComet):
        from jive.slim.slim_server import SlimServer

        s = self._make_server(jnt, comet=comet)
        s.update_init({"ip": "10.0.0.1"})
        s.update_init({"ip": "10.0.0.2"})  # Should be ignored
        assert s.ip == "10.0.0.1"

    def test_get_init(self, jnt: MockJnt, comet: MockComet):
        s = self._make_server(jnt, comet=comet)
        s.ip = "192.168.1.1"
        s.mac = "ab:cd:ef:01:02:03"
        init = s.get_init()
        assert init["ip"] == "192.168.1.1"
        assert init["mac"] == "ab:cd:ef:01:02:03"

    # ----- update_address -----

    def test_update_address(self, jnt: MockJnt, comet: MockComet):
        s = self._make_server(jnt, comet=comet)
        jnt.clear()
        s.update_address("192.168.1.50", 9000, "NewName")
        assert s.ip == "192.168.1.50"
        assert s.port == 9000
        assert s.name == "NewName"
        assert comet.endpoint == ("192.168.1.50", 9000, "/cometd")
        events = [n[0] for n in jnt.notifications]
        assert "serverNew" in events

    def test_update_address_no_change(self, jnt: MockJnt, comet: MockComet):
        s = self._make_server(jnt, comet=comet)
        s.ip = "10.0.0.1"
        s.port = 9000
        s.name = "Same"
        s.last_seen = 1
        jnt.clear()
        # Same address should still update last_seen
        s.update_address("10.0.0.1", 9000, "Same")
        assert s.last_seen > 0

    # ----- connect / disconnect / reconnect -----

    def test_connect(self, jnt: MockJnt, comet: MockComet):
        s = self._make_server(jnt, comet=comet)
        s.ip = "10.0.0.1"
        s.last_seen = 1
        s.connect()
        assert s.netstate == "connecting"
        assert comet.connected is True

    def test_connect_already_connected(self, jnt: MockJnt, comet: MockComet):
        s = self._make_server(jnt, comet=comet)
        s.netstate = "connected"
        s.connect()
        assert s.netstate == "connected"

    def test_connect_without_ip(self, jnt: MockJnt, comet: MockComet):
        s = self._make_server(jnt, comet=comet)
        s.last_seen = 0
        s.connect()
        assert s.netstate == "disconnected"

    def test_disconnect(self, jnt: MockJnt, comet: MockComet):
        s = self._make_server(jnt, comet=comet)
        s.netstate = "connected"
        s.disconnect()
        assert s.netstate == "disconnected"
        assert comet.connected is False

    def test_disconnect_already_disconnected(self, jnt: MockJnt, comet: MockComet):
        s = self._make_server(jnt, comet=comet)
        s.disconnect()  # Should not crash

    def test_reconnect(self, jnt: MockJnt, comet: MockComet):
        s = self._make_server(jnt, comet=comet)
        s.ip = "10.0.0.1"
        s.last_seen = 1
        s.netstate = "connected"
        s.reconnect()
        assert comet.connected is True

    # ----- free -----

    def test_free(self, jnt: MockJnt, comet: MockComet):
        from jive.slim.slim_server import SlimServer

        s = self._make_server(jnt, comet=comet)
        s.update_init({"ip": "10.0.0.1"})
        assert s.id in dict(SlimServer.iterate())
        jnt.clear()
        s.free()
        events = [n[0] for n in jnt.notifications]
        assert "serverDelete" in events
        assert s.id not in dict(SlimServer.iterate())

    # ----- Comet notification handlers -----

    def test_notify_comet_connected(self, jnt: MockJnt, comet: MockComet):
        s = self._make_server(jnt, comet=comet)
        s.netstate = "connecting"
        jnt.clear()
        s.notify_cometConnected(comet)
        assert s.netstate == "connected"
        events = [n[0] for n in jnt.notifications]
        assert "serverConnected" in events

    def test_notify_comet_connected_wrong_comet(self, jnt: MockJnt, comet: MockComet):
        s = self._make_server(jnt, comet=comet)
        other_comet = MockComet()
        s.notify_cometConnected(other_comet)
        assert s.netstate == "disconnected"  # unchanged

    def test_notify_comet_disconnected(self, jnt: MockJnt, comet: MockComet):
        s = self._make_server(jnt, comet=comet)
        s.netstate = "connected"
        jnt.clear()
        s.notify_cometDisconnected(comet)
        assert s.netstate == "connecting"
        events = [n[0] for n in jnt.notifications]
        assert "serverDisconnected" in events

    def test_notify_comet_disconnected_idle(self, jnt: MockJnt, comet: MockComet):
        s = self._make_server(jnt, comet=comet)
        s.netstate = "connected"
        s.notify_cometDisconnected(comet, idle_timeout_triggered=True)
        assert s.netstate == "disconnected"

    # ----- is_password_protected -----

    def test_is_password_protected(self, jnt: MockJnt, comet: MockComet):
        s = self._make_server(jnt, comet=comet)
        protected, realm = s.is_password_protected()
        assert protected is False
        assert realm is None

        s.realm = "LMS"
        s.netstate = "connecting"
        protected, realm = s.is_password_protected()
        assert protected is True
        assert realm == "LMS"

    # ----- get_upgrade_url -----

    def test_get_upgrade_url(self, jnt: MockJnt, comet: MockComet):
        s = self._make_server(jnt, comet=comet)
        url, force = s.get_upgrade_url()
        assert url is False
        assert force is False

    # ----- all_players -----

    def test_all_players(self, jnt: MockJnt, comet: MockComet):
        s = self._make_server(jnt, comet=comet)
        assert list(s.all_players()) == []

        mock_player = MagicMock()
        mock_player.get_id.return_value = "p1"
        s._add_player(mock_player)
        players = list(s.all_players())
        assert len(players) == 1
        assert players[0][0] == "p1"

    def test_add_delete_player(self, jnt: MockJnt, comet: MockComet):
        s = self._make_server(jnt, comet=comet)
        mock_player = MagicMock()
        mock_player.get_id.return_value = "p1"
        s._add_player(mock_player)
        assert "p1" in s.players
        s._delete_player(mock_player)
        assert "p1" not in s.players

    # ----- set_idle_timeout -----

    def test_set_idle_timeout(self, jnt: MockJnt, comet: MockComet):
        s = self._make_server(jnt, comet=comet)
        s.set_idle_timeout(300)
        assert comet._idle_timeout == 300

    # ----- App parameters -----

    def test_app_parameters(self, jnt: MockJnt, comet: MockComet):
        s = self._make_server(jnt, comet=comet)
        assert s.get_app_parameters("facebook") is None
        s.set_app_parameter("facebook", "icon_id", "fb-icon-123")
        params = s.get_app_parameters("facebook")
        assert params is not None
        assert params["icon_id"] == "fb-icon-123"

    # ----- PIN / linking -----

    def test_get_pin(self, jnt: MockJnt, comet: MockComet):
        s = self._make_server(jnt, comet=comet)
        assert s.get_pin() is False

    def test_linked(self, jnt: MockJnt, comet: MockComet):
        s = self._make_server(jnt, comet=comet)
        s.pin = "1234"
        s.linked("1234")
        assert s.pin is False

    # ----- artwork_thumb_cached -----

    def test_artwork_thumb_cached(self, jnt: MockJnt, comet: MockComet):
        s = self._make_server(jnt, comet=comet)
        assert s.artwork_thumb_cached("abc", "200") is False
        s.artwork_cache.set("abc@200/", b"image_data")
        assert s.artwork_thumb_cached("abc", "200") is True

    # ----- cancel_artwork -----

    def test_cancel_artwork(self, jnt: MockJnt, comet: MockComet):
        s = self._make_server(jnt, comet=comet)
        mock_icon = MagicMock()
        mock_icon.get_image.return_value = MagicMock()
        s.artwork_thumb_icons[mock_icon] = "key1"
        s.cancel_artwork(mock_icon)
        assert mock_icon not in s.artwork_thumb_icons

    def test_cancel_all_artwork(self, jnt: MockJnt, comet: MockComet):
        s = self._make_server(jnt, comet=comet)
        s.artwork_cache.set("k1", True)
        s.artwork_fetch_queue.append({"key": "k1"})
        mock_icon = MagicMock()
        s.artwork_thumb_icons[mock_icon] = "k1"
        s.cancel_all_artwork()
        assert len(s.artwork_fetch_queue) == 0
        assert mock_icon not in s.artwork_thumb_icons

    # ----- _build_artwork_url -----

    def test_build_artwork_url_coverid(self, jnt: MockJnt, comet: MockComet):
        s = self._make_server(jnt, comet=comet)
        url = s._build_artwork_url("abc123def", "200")
        assert "/music/abc123def/cover_200x200_m" in url

    def test_build_artwork_url_coverid_with_format(
        self, jnt: MockJnt, comet: MockComet
    ):
        s = self._make_server(jnt, comet=comet)
        url = s._build_artwork_url("abc123", "200", "png")
        assert url.endswith(".png")

    def test_build_artwork_url_private_ip(self, jnt: MockJnt, comet: MockComet):
        s = self._make_server(jnt, comet=comet)
        url = s._build_artwork_url("http://192.168.1.1/art.jpg", "200")
        assert url == "http://192.168.1.1/art.jpg"

    def test_build_artwork_url_remote_new_lms(self, jnt: MockJnt, comet: MockComet):
        s = self._make_server(jnt, version="8.0.0", comet=comet)
        url = s._build_artwork_url("http://example.com/art.jpg", "200")
        assert "/imageproxy/" in url

    def test_build_artwork_url_contributor(self, jnt: MockJnt, comet: MockComet):
        s = self._make_server(jnt, comet=comet)
        url = s._build_artwork_url("contributor/123/image", "100x80")
        assert "_100x80_m" in url

    def test_build_artwork_url_static_path(self, jnt: MockJnt, comet: MockComet):
        s = self._make_server(jnt, comet=comet)
        url = s._build_artwork_url("html/images/icon.png", "50")
        assert "_50x50_m" in url

    # ----- _serverstatus_sink -----

    def test_serverstatus_sink_creates_players(self, jnt: MockJnt, comet: MockComet):
        s = self._make_server(jnt, comet=comet)
        s.last_seen = 1

        data = {
            "data": {
                "player count": 1,
                "players_loop": [
                    {
                        "playerid": "aa:bb:cc:dd:ee:ff",
                        "name": "Test Player",
                        "model": "squeezeplay",
                        "connected": 1,
                        "power": 1,
                    }
                ],
            }
        }

        jnt.clear()
        s._serverstatus_sink(data)

        assert "aa:bb:cc:dd:ee:ff" in s.players
        player = s.players["aa:bb:cc:dd:ee:ff"]
        assert player.get_name() == "Test Player"

    def test_serverstatus_sink_removes_gone_players(
        self, jnt: MockJnt, comet: MockComet
    ):
        s = self._make_server(jnt, comet=comet)
        s.last_seen = 1

        # First, add a player via serverstatus
        mock_player = MagicMock()
        mock_player.get_id.return_value = "old-player"
        mock_player.is_local_player.return_value = False
        mock_player.is_on_stage = False
        mock_player.slim_server = s
        mock_player.get_slim_server.return_value = s
        mock_player.is_connected.return_value = True
        s.players["old-player"] = mock_player

        # Serverstatus with no players
        data = {
            "data": {
                "player count": 0,
                "players_loop": [],
            }
        }

        s._serverstatus_sink(data)
        # Old player should have been freed
        mock_player.free.assert_called_with(s)

    def test_serverstatus_sink_no_data(self, jnt: MockJnt, comet: MockComet):
        s = self._make_server(jnt, comet=comet)
        # Should not crash
        s._serverstatus_sink("not a dict")
        s._serverstatus_sink({})

    def test_serverstatus_sink_rescan(self, jnt: MockJnt, comet: MockComet):
        s = self._make_server(jnt, comet=comet)
        s.state = {"rescan": "1"}
        s.last_seen = 1

        jnt.clear()
        s._serverstatus_sink({"data": {"rescan": None, "player count": 0}})
        events = [n[0] for n in jnt.notifications]
        assert "serverRescanning" in events

    # ----- _upgrade_sink -----

    def test_upgrade_sink(self, jnt: MockJnt, comet: MockComet):
        s = self._make_server(jnt, comet=comet)
        s.ip = "10.0.0.1"
        s.port = 9000
        jnt.clear()

        s._upgrade_sink({"data": {"relativeFirmwareUrl": "/firmware/update.bin"}})
        assert s.upgrade_url == "http://10.0.0.1:9000/firmware/update.bin"
        events = [n[0] for n in jnt.notifications]
        assert "firmwareAvailable" in events

    def test_upgrade_sink_error(self, jnt: MockJnt, comet: MockComet):
        s = self._make_server(jnt, comet=comet)
        s._upgrade_sink(None, err="Network error")
        # Should not crash

    # ----- wake_on_lan -----

    def test_wake_on_lan_no_mac(self, jnt: MockJnt, comet: MockComet):
        s = self._make_server(jnt, comet=comet)
        s.mac = None
        # Should log warning but not crash
        s.wake_on_lan()

    # ----- user_request / request -----

    def test_user_request(self, jnt: MockJnt, comet: MockComet):
        s = self._make_server(jnt, comet=comet)
        s.ip = "10.0.0.1"
        s.last_seen = 1
        s.netstate = "connected"

        callback = MagicMock()
        req_id = s.user_request(callback, "player_id", ["status"])
        assert req_id is not None
        assert len(s.user_requests) == 1

    def test_request(self, jnt: MockJnt, comet: MockComet):
        s = self._make_server(jnt, comet=comet)
        s.request(lambda: None, "player_id", ["status"])
        assert len(comet.requests) == 1

    def test_remove_all_user_requests(self, jnt: MockJnt, comet: MockComet):
        s = self._make_server(jnt, comet=comet)
        s.user_requests = [
            {"func": None, "args": (), "comet_request_id": 1},
            {"func": None, "args": (), "comet_request_id": 2},
        ]
        s.remove_all_user_requests()
        assert len(s.user_requests) == 0

    # ----- credentials -----

    def test_set_credentials(self, jnt: MockJnt, comet: MockComet):
        s = self._make_server(jnt, comet=comet)
        s.ip = "10.0.0.1"
        s.port = 9000
        s.last_seen = 1
        s.netstate = "connected"

        from jive.slim.slim_server import _credentials

        s.set_credentials({"realm": "LMS", "username": "admin", "password": "pass"})
        assert s.id in _credentials

    def test_set_credentials_global(self, jnt: MockJnt, comet: MockComet):
        s = self._make_server(jnt, comet=comet)
        from jive.slim.slim_server import _credentials

        s.set_credentials(
            {"realm": "R", "username": "u", "password": "p"}, cred_id="global-1"
        )
        assert "global-1" in _credentials

    # ----- __repr__ / __str__ -----

    def test_repr(self, jnt: MockJnt, comet: MockComet):
        s = self._make_server(jnt, comet=comet)
        assert "test-server-1" in repr(s)

    def test_str(self, jnt: MockJnt, comet: MockComet):
        s = self._make_server(jnt, comet=comet)
        assert "Test LMS" in str(s)


# ===================================================================
# SlimServer helper tests
# ===================================================================


class TestSlimServerHelpers:
    """Tests for module-level helpers in slim_server.py."""

    def test_to_bool(self):
        from jive.slim.slim_server import _to_bool

        assert _to_bool(None) is False
        assert _to_bool(1) is True
        assert _to_bool(0) is False
        assert _to_bool("1") is True

    def test_to_int(self):
        from jive.slim.slim_server import _to_int

        assert _to_int(None) == 0
        assert _to_int(42) == 42
        assert _to_int("abc", 99) == 99


# ===================================================================
# LocalPlayer tests
# ===================================================================


class TestLocalPlayer:
    """Tests for jive.slim.local_player.LocalPlayer."""

    def _make_local_player(
        self, jnt: MockJnt, player_id: str = "00:04:20:dd:ee:ff"
    ) -> Any:
        from jive.slim.local_player import LocalPlayer

        return LocalPlayer(jnt, player_id)

    # ----- Construction -----

    def test_construction(self, jnt: MockJnt):
        lp = self._make_local_player(jnt)
        assert lp.id == "00:04:20:dd:ee:ff"
        assert lp.is_local_player() is True
        assert lp.info["name"] == "SqueezePlay"
        assert lp.info["model"] == "squeezeplay"

    def test_is_local_class_method(self):
        from jive.slim.local_player import LocalPlayer

        assert LocalPlayer.is_local() is True

    def test_inherits_from_player(self, jnt: MockJnt):
        from jive.slim.player import Player

        lp = self._make_local_player(jnt)
        assert isinstance(lp, Player)

    # ----- Device type -----

    def test_get_device_type(self):
        from jive.slim.local_player import LocalPlayer

        dev_id, model, name = LocalPlayer.get_device_type()
        assert dev_id == 12
        assert model == "squeezeplay"
        assert name == "SqueezePlay"

    def test_set_device_type(self):
        from jive.slim.local_player import _DEVICE_ID, LocalPlayer

        old = LocalPlayer.get_device_type()
        try:
            LocalPlayer.set_device_type("controller", "Squeezebox Controller")
            dev_id, model, name = LocalPlayer.get_device_type()
            assert dev_id == 9
            assert model == "controller"
            assert name == "Squeezebox Controller"
        finally:
            # Restore
            import jive.slim.local_player as lp_mod

            lp_mod._DEVICE_ID = old[0]
            lp_mod._DEVICE_MODEL = old[1]
            lp_mod._DEVICE_NAME = old[2]

    def test_set_device_type_name_defaults_to_model(self):
        from jive.slim.local_player import LocalPlayer

        old = LocalPlayer.get_device_type()
        try:
            LocalPlayer.set_device_type("boom")
            _, model, name = LocalPlayer.get_device_type()
            assert model == "boom"
            assert name == "boom"
        finally:
            import jive.slim.local_player as lp_mod

            lp_mod._DEVICE_ID = old[0]
            lp_mod._DEVICE_MODEL = old[1]
            lp_mod._DEVICE_NAME = old[2]

    # ----- Sequence numbers -----

    def test_initial_sequence_number(self, jnt: MockJnt):
        lp = self._make_local_player(jnt)
        assert lp.get_current_sequence_number() == 1

    def test_increment_sequence_number(self, jnt: MockJnt):
        lp = self._make_local_player(jnt)
        result = lp.increment_sequence_number()
        assert result == 2
        assert lp.get_current_sequence_number() == 2

    def test_increment_multiple(self, jnt: MockJnt):
        lp = self._make_local_player(jnt)
        lp.increment_sequence_number()
        lp.increment_sequence_number()
        lp.increment_sequence_number()
        assert lp.get_current_sequence_number() == 4

    def test_is_sequence_number_in_sync(self, jnt: MockJnt):
        lp = self._make_local_player(jnt)
        # Simplified version always returns True
        assert lp.is_sequence_number_in_sync(1) is True
        assert lp.is_sequence_number_in_sync(999) is True

    # ----- Last SqueezeCenter -----

    def test_last_squeeze_center(self, jnt: MockJnt):
        lp = self._make_local_player(jnt)
        assert lp.get_last_squeeze_center() is None

        mock_server = MagicMock()
        lp.set_last_squeeze_center(mock_server)
        assert lp.get_last_squeeze_center() is mock_server

    # ----- Capture play mode -----

    def test_capture_play_mode(self, jnt: MockJnt):
        lp = self._make_local_player(jnt)
        assert lp.get_capture_play_mode() is False
        lp.set_capture_play_mode(True)
        assert lp.get_capture_play_mode() is True

    # ----- _volume_no_increment -----

    def test_volume_no_increment(self, jnt: MockJnt):
        lp = self._make_local_player(jnt)
        lp.state = {"mixer volume": 50}
        mock_server = MagicMock()
        lp.slim_server = mock_server
        result = lp._volume_no_increment(75, send=True)
        assert result == 75

    # ----- refresh_locally_maintained_parameters -----

    def test_refresh_locally_maintained_parameters(self, jnt: MockJnt):
        lp = self._make_local_player(jnt)
        lp.state = {"mixer volume": 60, "power": 1}
        lp.info["power"] = True
        mock_server = MagicMock()
        lp.slim_server = mock_server
        # Should not crash
        lp.refresh_locally_maintained_parameters()

    # ----- disconnect_server_and_preserve_local_player -----

    def test_disconnect_server_and_preserve(self, jnt: MockJnt):
        from jive.slim.local_player import LocalPlayer
        from jive.slim.player import Player

        lp = self._make_local_player(jnt)
        lp.update_init(None, {"name": "Local", "model": "squeezeplay"})

        # Make lp the current player
        mock_server = MagicMock()
        lp.slim_server = mock_server
        Player.set_current_player(lp)
        assert Player.get_current_player() is lp

        jnt.clear()

        # Create another player and set it as current
        from jive.slim.player import reset_player_globals

        # Don't reset, just set a different current
        other = Player(jnt, "11:22:33:44:55:66")
        other.slim_server = mock_server
        Player.set_current_player(other)

        # Now disconnect and preserve
        LocalPlayer.disconnect_server_and_preserve_local_player(other)

        # Local player should be current again
        current = Player.get_current_player()
        assert current is lp

    # ----- __repr__ / __str__ -----

    def test_repr(self, jnt: MockJnt):
        lp = self._make_local_player(jnt)
        r = repr(lp)
        assert "LocalPlayer" in r
        assert "00:04:20:dd:ee:ff" in r

    def test_str(self, jnt: MockJnt):
        lp = self._make_local_player(jnt)
        s = str(lp)
        assert "LocalPlayer" in s


# ===================================================================
# __init__.py lazy imports test
# ===================================================================


class TestSlimPackageInit:
    """Tests for jive.slim.__init__ lazy imports."""

    def test_import_artwork_cache(self):
        from jive.slim import ArtworkCache

        assert ArtworkCache is not None

    def test_import_player(self):
        from jive.slim import Player

        assert Player is not None

    def test_import_slim_server(self):
        from jive.slim import SlimServer

        assert SlimServer is not None

    def test_import_local_player(self):
        from jive.slim import LocalPlayer

        assert LocalPlayer is not None

    def test_import_nonexistent_raises(self):
        import jive.slim

        with pytest.raises(AttributeError):
            _ = jive.slim.NonExistentThing  # type: ignore[attr-defined]


# ===================================================================
# Integration tests — Player ↔ SlimServer
# ===================================================================


class TestPlayerServerIntegration:
    """Integration tests verifying Player and SlimServer work together."""

    def test_serverstatus_creates_and_updates_player(self, jnt: MockJnt):
        from jive.slim.player import Player
        from jive.slim.slim_server import SlimServer

        comet = MockComet()
        server = SlimServer(jnt, "srv-int-1", "IntServer", "8.5.0")
        server.comet = comet
        server.last_seen = 1

        # Simulate serverstatus with one player
        data = {
            "data": {
                "player count": 1,
                "players_loop": [
                    {
                        "playerid": "aa:bb:cc:11:22:33",
                        "name": "Integration Player",
                        "model": "squeezeplay",
                        "connected": 1,
                        "power": 1,
                    }
                ],
            }
        }

        server._serverstatus_sink(data)

        # Player should exist
        assert "aa:bb:cc:11:22:33" in server.players
        player = server.players["aa:bb:cc:11:22:33"]
        assert player.get_name() == "Integration Player"
        assert player.get_slim_server() is server

    def test_player_call_routes_to_server(self, jnt: MockJnt):
        from jive.slim.slim_server import SlimServer

        comet = MockComet()
        server = SlimServer(jnt, "srv-call-1", "CallServer", "8.5.0")
        server.comet = comet
        server.ip = "10.0.0.1"
        server.last_seen = 1
        server.netstate = "connected"

        from jive.slim.player import Player

        player = Player(jnt, "cc:dd:ee:ff:00:11")
        player.slim_server = server
        player.state = {"mode": "play"}

        # Call should route through server.user_request
        player.pause()
        assert player.mode == "pause"
        # user_request should have created a Comet request
        assert len(comet.requests) > 0

    def test_set_current_player_updates_server(self, jnt: MockJnt):
        from jive.slim.player import Player
        from jive.slim.slim_server import SlimServer

        comet = MockComet()
        server = SlimServer(jnt, "srv-cur-1", "CurServer", "8.5.0")
        server.comet = comet

        player = Player(jnt, "ff:ee:dd:cc:bb:aa")
        player.slim_server = server

        Player.set_current_player(player)
        assert SlimServer.get_current_server() is server

    def test_player_free_removes_from_server(self, jnt: MockJnt):
        from jive.slim.player import Player
        from jive.slim.slim_server import SlimServer

        comet = MockComet()
        server = SlimServer(jnt, "srv-free-1", "FreeServer", "8.5.0")
        server.comet = comet

        player = Player(jnt, "11:11:11:11:11:11")
        player.slim_server = server
        server._add_player(player)
        player.update_init(None, {"name": "FreeMe", "model": "squeezeplay"})

        assert player.get_id() in server.players
        player.free(server)
        assert player.get_id() not in server.players


# ===================================================================
# Edge case and stress tests
# ===================================================================


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_artwork_cache_large_eviction(self):
        """Stress test: many items, verify cache stays within limit."""
        from jive.slim.artwork_cache import ArtworkCache

        cache = ArtworkCache(limit=1000)
        for i in range(200):
            cache.set(f"key_{i}", bytes(range(256))[:50])  # 50 bytes each
        assert cache.total <= 1000

    def test_player_no_jnt(self):
        """Player with None jnt should not crash."""
        from jive.slim.player import Player

        p = Player(None, "no:jn:t0:00:00:01")
        p.state = {"mode": "play"}
        p.mode = "play"
        # Operations that notify should not crash
        p.update_iconbar()
        p._process_status({"data": {"mode": "stop", "time": 0}})

    def test_server_no_jnt(self):
        """SlimServer with None jnt should not crash."""
        from jive.slim.slim_server import SlimServer

        comet = MockComet()
        s = SlimServer(None, "no-jnt-server", "NoJNT")
        s.comet = comet
        s.free()  # Should not crash

    def test_player_volume_edge_values(self, jnt: MockJnt):
        """Volume at boundaries."""
        from jive.slim.player import Player

        p = Player(jnt, "vol:ed:ge:00:00:01")
        p.state = {"mixer volume": 0}
        mock_server = MagicMock()
        p.slim_server = mock_server

        result = p.volume(0)
        assert result == 0

        p.mixer_to = None  # reset rate limit
        result = p.volume(100)
        assert result == 100

    def test_player_get_name_short_id(self, jnt: MockJnt):
        """Player with very short ID."""
        from jive.slim.player import Player

        p = Player(jnt, "ab")
        name = p.get_name()
        assert "Squeezebox" in name

    def test_multiple_server_status_updates(self, jnt: MockJnt):
        """Multiple serverstatus updates should be handled correctly."""
        from jive.slim.slim_server import SlimServer

        comet = MockComet()
        server = SlimServer(jnt, "multi-status", "MultiStatus", "8.0.0")
        server.comet = comet
        server.last_seen = 1

        for i in range(5):
            data = {
                "data": {
                    "player count": 1,
                    "players_loop": [
                        {
                            "playerid": "aa:bb:cc:dd:ee:01",
                            "name": f"Player Update {i}",
                            "model": "squeezeplay",
                            "connected": 1,
                            "power": 1,
                        }
                    ],
                }
            }
            server._serverstatus_sink(data)

        assert "aa:bb:cc:dd:ee:01" in server.players
        player = server.players["aa:bb:cc:dd:ee:01"]
        assert player.get_name() == "Player Update 4"

    def test_server_version_comparison_edge_cases(self):
        from jive.slim.slim_server import SlimServer

        # Same version
        assert SlimServer.is_more_recent("7.4.0", "7.4.0") is False
        # Different lengths
        assert SlimServer.is_more_recent("7.4", "7.3.9") is True
        assert SlimServer.is_more_recent("7.4", "7.5") is False
        # Single component
        assert SlimServer.is_more_recent("8", "7") is True

    def test_artwork_cache_rapid_set_get(self):
        """Rapid set/get cycles should not corrupt the cache."""
        from jive.slim.artwork_cache import ArtworkCache

        cache = ArtworkCache(limit=100)
        for i in range(50):
            key = f"k{i}"
            cache.set(key, b"x" * 5)
            val = cache.get(key)
            assert val == b"x" * 5 or val is None  # might have been evicted

    def test_player_status_mode_change_notification(self, jnt: MockJnt):
        """Verify playerModeChange is fired when mode changes."""
        from jive.slim.player import Player

        p = Player(jnt, "mode:ch:an:ge:00:01")
        mock_server = MagicMock()
        mock_server.is_connected.return_value = True
        p.slim_server = mock_server
        p.update_init(mock_server, {"name": "ModeTest", "model": "squeezeplay"})
        p.state = {"mode": "stop"}
        p.mode = "stop"

        jnt.clear()
        p._process_status(
            {
                "data": {
                    "mode": "play",
                    "time": 0,
                    "player_name": "ModeTest",
                    "player_connected": 1,
                    "power": 1,
                }
            }
        )

        events = [n[0] for n in jnt.notifications]
        assert "playerModeChange" in events

    def test_player_shuffle_repeat_notifications(self, jnt: MockJnt):
        """Verify shuffle and repeat mode change notifications."""
        from jive.slim.player import Player

        p = Player(jnt, "sh:uf:fl:e0:00:01")
        mock_server = MagicMock()
        mock_server.is_connected.return_value = True
        p.slim_server = mock_server
        p.update_init(mock_server, {"name": "ShuffleTest", "model": "squeezeplay"})
        p.state = {"playlist shuffle": 0, "playlist repeat": 0}

        jnt.clear()
        p._process_status(
            {
                "data": {
                    "mode": "play",
                    "playlist shuffle": 1,
                    "playlist repeat": 2,
                    "player_name": "ShuffleTest",
                    "player_connected": 1,
                    "power": 1,
                }
            }
        )

        events = [n[0] for n in jnt.notifications]
        assert "playerShuffleModeChange" in events
        assert "playerRepeatModeChange" in events

    def test_player_sleep_notification(self, jnt: MockJnt):
        """Verify sleep change notification."""
        from jive.slim.player import Player

        p = Player(jnt, "sl:ee:p0:00:00:01")
        mock_server = MagicMock()
        mock_server.is_connected.return_value = True
        p.slim_server = mock_server
        p.update_init(mock_server, {"name": "SleepTest", "model": "squeezeplay"})
        p.state = {}

        jnt.clear()
        p._process_status(
            {
                "data": {
                    "mode": "play",
                    "sleep": 300,
                    "player_name": "SleepTest",
                    "player_connected": 1,
                    "power": 1,
                }
            }
        )

        events = [n[0] for n in jnt.notifications]
        assert "playerSleepChange" in events
