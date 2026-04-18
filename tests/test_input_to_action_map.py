"""Tests for jive.input_to_action_map — input-to-action mapping tables."""

from __future__ import annotations

import pytest

from jive.input_to_action_map import (
    action_action_mappings,
    char_action_mappings,
    gesture_action_mappings,
    ir_action_mappings,
    key_action_mappings,
    unassigned_action_mappings,
)
from jive.ui.constants import (
    GESTURE_L_R,
    GESTURE_R_L,
    KEY_ADD,
    KEY_ALARM,
    KEY_BACK,
    KEY_DOWN,
    KEY_FWD,
    KEY_FWD_SCAN,
    KEY_GO,
    KEY_HOME,
    KEY_LEFT,
    KEY_MUTE,
    KEY_PAGE_DOWN,
    KEY_PAGE_UP,
    KEY_PAUSE,
    KEY_PLAY,
    KEY_POWER,
    KEY_PRESET_0,
    KEY_PRESET_1,
    KEY_PRESET_2,
    KEY_PRESET_3,
    KEY_PRESET_4,
    KEY_PRESET_5,
    KEY_PRESET_6,
    KEY_PRESET_7,
    KEY_PRESET_8,
    KEY_PRESET_9,
    KEY_PRINT,
    KEY_REW,
    KEY_REW_SCAN,
    KEY_RIGHT,
    KEY_STOP,
    KEY_UP,
    KEY_VOLUME_DOWN,
    KEY_VOLUME_UP,
)

# ---------------------------------------------------------------------------
# char_action_mappings
# ---------------------------------------------------------------------------


class TestCharActionMappings:
    """Tests for keyboard character → action mappings."""

    def test_has_press_key(self) -> None:
        assert "press" in char_action_mappings

    def test_press_is_dict(self) -> None:
        assert isinstance(char_action_mappings["press"], dict)

    @pytest.mark.parametrize(
        ("char", "expected_action"),
        [
            (" ", "pause"),
            ("x", "play"),
            ("p", "play"),
            ("P", "create_mix"),
            ("c", "pause"),
            ("C", "stop"),
            ("+", "volume_up"),
            ("=", "volume_up"),
            ("-", "volume_down"),
            ("h", "go_home"),
            ("J", "go_home_or_now_playing"),
            ("n", "go_home_or_now_playing"),
            ("\x1b", "back"),  # ESC
            ("\b", "back"),  # BACKSPACE
            ("j", "back"),
            ("l", "go"),
            ("/", "go_search"),
            ("a", "add"),
            ("A", "add_end"),
            ("z", "jump_rew"),
            ("<", "jump_rew"),
            ("b", "jump_fwd"),
            (">", "jump_fwd"),
            ("S", "take_screenshot"),
            ("D", "soft_reset"),
            ("q", "power"),
            ("Q", "power"),
            ("s", "sleep"),
            ("|", "sleep"),
            ("f", "go_favorites"),
            (",", "shuffle_toggle"),
            (".", "repeat_toggle"),
            ("u", "mute"),
            ("M", "mute"),
            ("m", "create_mix"),
            ("g", "stop"),
            ("d", "add_end"),
            ("y", "play_next"),
            ("e", "scanner_rew"),
            ("r", "scanner_fwd"),
            ("Z", "scanner_rew"),
            ("B", "scanner_fwd"),
            ("o", "quit"),
            ("t", "go_current_track_info"),
            ("{", "go_current_track_info"),
            ("`", "go_playlists"),
            (";", "go_music_library"),
            ("'", "go_brightness"),
            ("[", "go_now_playing"),
            ("]", "go_playlist"),
            ("k", "power_on"),
            ("i", "power_off"),
            ("?", "help"),
            ("R", "reload_skin"),
            ("}", "debug_skin"),
            ("~", "debug_touch"),
        ],
    )
    def test_char_press_mapping(self, char: str, expected_action: str) -> None:
        assert char_action_mappings["press"][char] == expected_action

    @pytest.mark.parametrize("digit", list("0123456789"))
    def test_digit_presets(self, digit: str) -> None:
        action = char_action_mappings["press"][digit]
        assert action == f"play_preset_{digit}"

    @pytest.mark.parametrize(
        ("char", "digit"),
        [
            (")", "0"),
            ("!", "1"),
            ("@", "2"),
            ("#", "3"),
            ("$", "4"),
            ("%", "5"),
            ("^", "6"),
            ("&", "7"),
            ("*", "8"),
            ("(", "9"),
        ],
    )
    def test_shift_digit_set_presets(self, char: str, digit: str) -> None:
        assert char_action_mappings["press"][char] == f"set_preset_{digit}"

    def test_all_press_values_are_strings(self) -> None:
        for char, action in char_action_mappings["press"].items():
            assert isinstance(char, str), f"Key {char!r} is not a string"
            assert isinstance(action, str), f"Value for {char!r} is not a string"

    def test_no_none_values(self) -> None:
        for char, action in char_action_mappings["press"].items():
            assert action is not None, f"Action for {char!r} is None"


# ---------------------------------------------------------------------------
# key_action_mappings
# ---------------------------------------------------------------------------


class TestKeyActionMappings:
    """Tests for hardware key → action mappings."""

    def test_has_press_and_hold(self) -> None:
        assert "press" in key_action_mappings
        assert "hold" in key_action_mappings

    def test_press_and_hold_are_dicts(self) -> None:
        assert isinstance(key_action_mappings["press"], dict)
        assert isinstance(key_action_mappings["hold"], dict)

    @pytest.mark.parametrize(
        ("key", "expected"),
        [
            (KEY_PLAY, "play"),
            (KEY_BACK, "back"),
            (KEY_GO, "go"),
            (KEY_HOME, "go_home_or_now_playing"),
            (KEY_VOLUME_UP, "volume_up"),
            (KEY_VOLUME_DOWN, "volume_down"),
            (KEY_PAUSE, "pause"),
            (KEY_STOP, "stop"),
            (KEY_ADD, "add"),
            (KEY_MUTE, "mute"),
            (KEY_PAGE_UP, "page_up"),
            (KEY_PAGE_DOWN, "page_down"),
            (KEY_FWD, "jump_fwd"),
            (KEY_REW, "jump_rew"),
            (KEY_FWD_SCAN, "scanner_fwd"),
            (KEY_REW_SCAN, "scanner_rew"),
            (KEY_PRINT, "take_screenshot"),
            (KEY_POWER, "power"),
            (KEY_ALARM, "go_alarms"),
        ],
    )
    def test_key_press_mapping(self, key: int, expected: str) -> None:
        assert key_action_mappings["press"][key] == expected

    @pytest.mark.parametrize(
        ("key", "expected"),
        [
            (KEY_PLAY, "create_mix"),
            (KEY_HOME, "go_home"),
            (KEY_PAUSE, "stop"),
            (KEY_BACK, "go_home"),
            (KEY_LEFT, "go_home"),
            (KEY_ADD, "add_end"),
            (KEY_GO, "add"),
            (KEY_RIGHT, "add"),
            (KEY_FWD, "scanner_fwd"),
            (KEY_REW, "scanner_rew"),
            (KEY_VOLUME_UP, "volume_up"),
            (KEY_VOLUME_DOWN, "volume_down"),
            (KEY_POWER, "shutdown"),
            (KEY_ALARM, "go_alarms"),
        ],
    )
    def test_key_hold_mapping(self, key: int, expected: str) -> None:
        assert key_action_mappings["hold"][key] == expected

    @pytest.mark.parametrize("i", range(10))
    def test_preset_key_press(self, i: int) -> None:
        key = getattr(__import__("jive.ui.constants", fromlist=["*"]), f"KEY_PRESET_{i}")
        assert key_action_mappings["press"][key] == f"play_preset_{i}"

    @pytest.mark.parametrize("i", range(10))
    def test_preset_key_hold(self, i: int) -> None:
        key = getattr(__import__("jive.ui.constants", fromlist=["*"]), f"KEY_PRESET_{i}")
        assert key_action_mappings["hold"][key] == f"set_preset_{i}"

    def test_all_press_values_are_strings(self) -> None:
        for key, action in key_action_mappings["press"].items():
            assert isinstance(action, str), f"Action for key {key} is not a string"

    def test_all_hold_values_are_strings(self) -> None:
        for key, action in key_action_mappings["hold"].items():
            assert isinstance(action, str), f"Action for key {key} is not a string"

    def test_no_none_values_press(self) -> None:
        for key, action in key_action_mappings["press"].items():
            assert action is not None, f"Action for key {key} is None"

    def test_no_none_values_hold(self) -> None:
        for key, action in key_action_mappings["hold"].items():
            assert action is not None, f"Action for key {key} is None"

    def test_all_keys_are_ints(self) -> None:
        for key in key_action_mappings["press"]:
            assert isinstance(key, int), f"Key {key!r} is not int"
        for key in key_action_mappings["hold"]:
            assert isinstance(key, int), f"Key {key!r} is not int"


# ---------------------------------------------------------------------------
# gesture_action_mappings
# ---------------------------------------------------------------------------


class TestGestureActionMappings:
    """Tests for gesture code → action mappings."""

    def test_is_dict(self) -> None:
        assert isinstance(gesture_action_mappings, dict)

    def test_l_r_gesture(self) -> None:
        assert gesture_action_mappings[GESTURE_L_R] == "go_home"

    def test_r_l_gesture(self) -> None:
        assert gesture_action_mappings[GESTURE_R_L] == "go_now_playing_or_playlist"

    def test_has_exactly_two_entries(self) -> None:
        assert len(gesture_action_mappings) == 2

    def test_all_values_are_strings(self) -> None:
        for code, action in gesture_action_mappings.items():
            assert isinstance(action, str), f"Action for gesture {code} is not a string"

    def test_no_none_values(self) -> None:
        for code, action in gesture_action_mappings.items():
            assert action is not None


# ---------------------------------------------------------------------------
# ir_action_mappings
# ---------------------------------------------------------------------------


class TestIrActionMappings:
    """Tests for IR remote button name → action mappings."""

    def test_has_press_and_hold(self) -> None:
        assert "press" in ir_action_mappings
        assert "hold" in ir_action_mappings

    @pytest.mark.parametrize(
        ("button", "expected"),
        [
            ("play", "play"),
            ("pause", "pause"),
            ("home", "go_home_or_now_playing"),
            ("power", "power"),
            ("sleep", "sleep"),
            ("search", "go_search"),
            ("now_playing", "go_now_playing"),
            ("size", "go_playlist"),
            ("browse", "go_music_library"),
            ("favorites", "go_favorites"),
            ("brightness", "go_brightness"),
            ("shuffle", "shuffle_toggle"),
            ("repeat", "repeat_toggle"),
            ("arrow_up", "up"),
            ("arrow_down", "down"),
            ("arrow_left", "back"),
            ("arrow_right", "go"),
            ("add", "add"),
            ("fwd", "jump_fwd"),
            ("rew", "jump_rew"),
            ("volup", "volume_up"),
            ("voldown", "volume_down"),
            ("mute", "mute"),
            ("power_off", "power_off"),
            ("power_on", "power_on"),
            ("factory_test_mode", "go_factory_test_mode"),
            ("test_audio_routing", "go_test_audio_routing"),
        ],
    )
    def test_ir_press_mapping(self, button: str, expected: str) -> None:
        assert ir_action_mappings["press"][button] == expected

    @pytest.mark.parametrize("digit", list("0123456789"))
    def test_ir_digit_press(self, digit: str) -> None:
        assert ir_action_mappings["press"][digit] == f"play_preset_{digit}"

    @pytest.mark.parametrize("digit", list("0123456789"))
    def test_ir_digit_hold_is_disabled(self, digit: str) -> None:
        assert ir_action_mappings["hold"][digit] == "disabled"

    @pytest.mark.parametrize(
        ("button", "expected"),
        [
            ("home", "go_home"),
            ("play", "create_mix"),
            ("pause", "stop"),
            ("add", "add_end"),
            ("arrow_left", "go_home"),
            ("arrow_right", "add"),
            ("fwd", "scanner_fwd"),
            ("rew", "scanner_rew"),
            ("volup", "volume_up"),
            ("voldown", "volume_down"),
            ("sleep", "sleep"),
            ("power", "power"),
        ],
    )
    def test_ir_hold_mapping(self, button: str, expected: str) -> None:
        assert ir_action_mappings["hold"][button] == expected

    @pytest.mark.parametrize("i", range(1, 7))
    def test_harmony_preset_aliases(self, i: int) -> None:
        assert ir_action_mappings["press"][f"preset_{i}"] == f"play_preset_{i}"

    def test_all_press_values_are_strings(self) -> None:
        for button, action in ir_action_mappings["press"].items():
            assert isinstance(button, str)
            assert isinstance(action, str)

    def test_all_hold_values_are_strings(self) -> None:
        for button, action in ir_action_mappings["hold"].items():
            assert isinstance(button, str)
            assert isinstance(action, str)

    def test_no_none_values(self) -> None:
        for section in ("press", "hold"):
            for button, action in ir_action_mappings[section].items():
                assert action is not None, f"IR {section} {button!r} is None"


# ---------------------------------------------------------------------------
# action_action_mappings
# ---------------------------------------------------------------------------


class TestActionActionMappings:
    """Tests for action → action chaining mappings."""

    def test_is_dict(self) -> None:
        assert isinstance(action_action_mappings, dict)

    @pytest.mark.parametrize(
        ("source", "target"),
        [
            ("title_left_press", "back"),
            ("title_left_hold", "go_home"),
            ("title_right_press", "go_now_playing"),
            ("title_right_hold", "go_playlist"),
            ("home_title_left_press", "power"),
            ("home_title_left_hold", "power"),
        ],
    )
    def test_action_chaining(self, source: str, target: str) -> None:
        assert action_action_mappings[source] == target

    def test_has_six_entries(self) -> None:
        assert len(action_action_mappings) == 6

    def test_all_values_are_strings(self) -> None:
        for source, target in action_action_mappings.items():
            assert isinstance(source, str)
            assert isinstance(target, str)

    def test_no_none_values(self) -> None:
        for source, target in action_action_mappings.items():
            assert target is not None, f"Action chain target for {source!r} is None"


# ---------------------------------------------------------------------------
# unassigned_action_mappings
# ---------------------------------------------------------------------------


class TestUnassignedActionMappings:
    """Tests for the unassigned (programmatic) action list."""

    def test_is_list(self) -> None:
        assert isinstance(unassigned_action_mappings, list)

    def test_not_empty(self) -> None:
        assert len(unassigned_action_mappings) > 0

    @pytest.mark.parametrize(
        "action",
        [
            "mute",
            "play_next",
            "disabled",
            "nothing",
            "ignore",
            "cancel",
            "power_off",
            "power_on",
            "text_mode",
            "finish_operation",
            "more_help",
            "cursor_left",
            "cursor_right",
            "clear",
            "go_settings",
            "go_rhapsody",
            "start_demo",
        ],
    )
    def test_contains_expected_action(self, action: str) -> None:
        assert action in unassigned_action_mappings

    def test_all_entries_are_strings(self) -> None:
        for action in unassigned_action_mappings:
            assert isinstance(action, str), f"Entry {action!r} is not a string"

    def test_no_none_entries(self) -> None:
        for action in unassigned_action_mappings:
            assert action is not None

    def test_no_empty_strings(self) -> None:
        for action in unassigned_action_mappings:
            assert action != "", "Empty string in unassigned_action_mappings"


# ---------------------------------------------------------------------------
# Cross-cutting integrity checks
# ---------------------------------------------------------------------------


class TestMappingIntegrity:
    """Cross-cutting checks across all mapping tables."""

    def test_char_mappings_only_has_press(self) -> None:
        """char_action_mappings should only have a 'press' sub-dict."""
        assert set(char_action_mappings.keys()) == {"press"}

    def test_key_mappings_only_has_press_and_hold(self) -> None:
        assert set(key_action_mappings.keys()) == {"press", "hold"}

    def test_ir_mappings_only_has_press_and_hold(self) -> None:
        assert set(ir_action_mappings.keys()) == {"press", "hold"}

    def test_no_overlap_between_press_and_hold_actions_for_same_key(self) -> None:
        """Press and hold for the same key should map to different actions."""
        common_keys = set(key_action_mappings["press"]) & set(key_action_mappings["hold"])
        for key in common_keys:
            press_action = key_action_mappings["press"][key]
            hold_action = key_action_mappings["hold"][key]
            # volume_up/volume_down are the same on press and hold — that's intentional
            if press_action == hold_action:
                assert press_action in ("volume_up", "volume_down", "go_alarms"), (
                    f"Key {key}: press and hold both map to {press_action!r} unexpectedly"
                )

    def test_gesture_keys_are_ints(self) -> None:
        for code in gesture_action_mappings:
            assert isinstance(code, int), f"Gesture code {code!r} is not int"

    def test_action_action_keys_and_values_differ(self) -> None:
        """No action should chain to itself."""
        for source, target in action_action_mappings.items():
            assert source != target, f"Action {source!r} chains to itself"
