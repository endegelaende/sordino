"""
jive.input_to_action_map — Input-to-action mapping tables.

Ported from ``jive/InputToActionMap.lua`` in the original jivelite project.

This module defines the mapping tables that translate raw input events
(keyboard characters, hardware keys, IR remote buttons, gestures) into
named semantic actions (e.g. ``"play"``, ``"pause"``, ``"go_home"``).

The Framework uses these mappings to convert low-level input events
into high-level ``ACTION`` events that widgets and applets can listen
for without caring about the specific input device.

Mapping tables
~~~~~~~~~~~~~~

* ``char_action_mappings`` — Keyboard character → action name.
  Sub-dicts for ``"press"`` events.
* ``key_action_mappings`` — Hardware key code → action name.
  Sub-dicts for ``"press"`` and ``"hold"`` events.
* ``ir_action_mappings`` — IR remote button name → action name.
  Sub-dicts for ``"press"`` and ``"hold"`` events.
* ``gesture_action_mappings`` — Gesture code → action name.
* ``action_action_mappings`` — Action name → action name (chaining).
* ``unassigned_action_mappings`` — List of action names that are
  triggered programmatically but not by any hardware input.

Usage::

    from jive.input_to_action_map import (
        char_action_mappings,
        key_action_mappings,
        ir_action_mappings,
        gesture_action_mappings,
        action_action_mappings,
        unassigned_action_mappings,
    )

    # Look up the action for a key press
    action = key_action_mappings["press"].get(KEY_PLAY)  # -> "play"

    # Look up the action for a key hold
    action = key_action_mappings["hold"].get(KEY_PLAY)   # -> "create_mix"

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Copyright 2013-2014 Adrian Smith (jivelite amendments)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

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

__all__ = [
    "char_action_mappings",
    "key_action_mappings",
    "ir_action_mappings",
    "gesture_action_mappings",
    "action_action_mappings",
    "unassigned_action_mappings",
]

# ---------------------------------------------------------------------------
# Character (keyboard) → action mappings
# ---------------------------------------------------------------------------

char_action_mappings: dict[str, dict[str, str]] = {
    "press": {
        # --- Temp shortcuts to test action framework ---
        "[": "go_now_playing",
        "]": "go_playlist",
        "{": "go_current_track_info",
        "`": "go_playlists",
        ";": "go_music_library",
        ":": "go_favorites",
        "'": "go_brightness",
        ",": "shuffle_toggle",
        ".": "repeat_toggle",
        "|": "sleep",
        "Q": "power",
        # --- Alternatives avoiding keyboard modifiers ---
        "f": "go_favorites",
        "s": "sleep",
        "q": "power",
        "k": "power_on",
        "i": "power_off",
        "t": "go_current_track_info",
        "n": "go_home_or_now_playing",
        "m": "create_mix",
        "g": "stop",
        "d": "add_end",
        "y": "play_next",
        "e": "scanner_rew",
        "r": "scanner_fwd",
        "u": "mute",
        "o": "quit",
        # --- Original mappings ---
        "/": "go_search",
        "h": "go_home",
        "J": "go_home_or_now_playing",
        "D": "soft_reset",
        "x": "play",
        "p": "play",
        "P": "create_mix",
        " ": "pause",
        "c": "pause",
        "C": "stop",
        "a": "add",
        "A": "add_end",
        "W": "play_next",
        "M": "mute",
        "\b": "back",  # BACKSPACE
        "\x1b": "back",  # ESC
        "j": "back",
        "l": "go",
        "S": "take_screenshot",
        "z": "jump_rew",
        "<": "jump_rew",
        "Z": "scanner_rew",
        "b": "jump_fwd",
        ">": "jump_fwd",
        "B": "scanner_fwd",
        "+": "volume_up",
        "=": "volume_up",
        "-": "volume_down",
        "0": "play_preset_0",
        "1": "play_preset_1",
        "2": "play_preset_2",
        "3": "play_preset_3",
        "4": "play_preset_4",
        "5": "play_preset_5",
        "6": "play_preset_6",
        "7": "play_preset_7",
        "8": "play_preset_8",
        "9": "play_preset_9",
        ")": "set_preset_0",
        "!": "set_preset_1",
        "@": "set_preset_2",
        "#": "set_preset_3",
        "$": "set_preset_4",
        "%": "set_preset_5",
        "^": "set_preset_6",
        "&": "set_preset_7",
        "*": "set_preset_8",
        "(": "set_preset_9",
        "?": "help",
        # --- Development tools ---
        "R": "reload_skin",
        "}": "debug_skin",
        "~": "debug_touch",
    },
}

# ---------------------------------------------------------------------------
# Hardware key → action mappings
# ---------------------------------------------------------------------------

key_action_mappings: dict[str, dict[int, str]] = {
    "press": {
        KEY_HOME: "go_home_or_now_playing",
        KEY_PLAY: "play",
        KEY_ADD: "add",
        KEY_BACK: "back",
        # KEY_LEFT: "back",
        KEY_GO: "go",
        # KEY_RIGHT: "go",
        KEY_PAUSE: "pause",
        KEY_STOP: "stop",
        KEY_PRESET_0: "play_preset_0",
        KEY_PRESET_1: "play_preset_1",
        KEY_PRESET_2: "play_preset_2",
        KEY_PRESET_3: "play_preset_3",
        KEY_PRESET_4: "play_preset_4",
        KEY_PRESET_5: "play_preset_5",
        KEY_PRESET_6: "play_preset_6",
        KEY_PRESET_7: "play_preset_7",
        KEY_PRESET_8: "play_preset_8",
        KEY_PRESET_9: "play_preset_9",
        KEY_MUTE: "mute",
        KEY_PAGE_UP: "page_up",
        KEY_PAGE_DOWN: "page_down",
        KEY_FWD: "jump_fwd",
        KEY_REW: "jump_rew",
        KEY_FWD_SCAN: "scanner_fwd",
        KEY_REW_SCAN: "scanner_rew",
        KEY_VOLUME_UP: "volume_up",
        KEY_VOLUME_DOWN: "volume_down",
        KEY_PRINT: "take_screenshot",
        KEY_POWER: "power",
        KEY_ALARM: "go_alarms",
    },
    "hold": {
        KEY_HOME: "go_home",
        KEY_PLAY: "create_mix",
        KEY_ADD: "add_end",
        KEY_BACK: "go_home",
        KEY_LEFT: "go_home",
        KEY_GO: "add",  # no default assignment yet
        KEY_RIGHT: "add",
        KEY_PAUSE: "stop",
        KEY_PRESET_0: "set_preset_0",
        KEY_PRESET_1: "set_preset_1",
        KEY_PRESET_2: "set_preset_2",
        KEY_PRESET_3: "set_preset_3",
        KEY_PRESET_4: "set_preset_4",
        KEY_PRESET_5: "set_preset_5",
        KEY_PRESET_6: "set_preset_6",
        KEY_PRESET_7: "set_preset_7",
        KEY_PRESET_8: "set_preset_8",
        KEY_PRESET_9: "set_preset_9",
        KEY_FWD: "scanner_fwd",
        KEY_REW: "scanner_rew",
        KEY_VOLUME_UP: "volume_up",
        KEY_VOLUME_DOWN: "volume_down",
        KEY_POWER: "shutdown",
        KEY_ALARM: "go_alarms",
    },
}

# ---------------------------------------------------------------------------
# Gesture → action mappings
# ---------------------------------------------------------------------------

gesture_action_mappings: dict[int, str] = {
    GESTURE_L_R: "go_home",  # will be reset by ShortcutsMeta defaults
    GESTURE_R_L: "go_now_playing_or_playlist",  # will be reset by ShortcutsMeta defaults
}

# ---------------------------------------------------------------------------
# IR remote button name → action mappings
# ---------------------------------------------------------------------------

ir_action_mappings: dict[str, dict[str, str]] = {
    "press": {
        "sleep": "sleep",
        "power": "power",
        "power_off": "power_off",
        "power_on": "power_on",
        "home": "go_home_or_now_playing",
        "search": "go_search",
        "now_playing": "go_now_playing",
        "size": "go_playlist",
        "browse": "go_music_library",
        "favorites": "go_favorites",
        "brightness": "go_brightness",
        "shuffle": "shuffle_toggle",
        "repeat": "repeat_toggle",
        "arrow_up": "up",
        "arrow_down": "down",
        "arrow_left": "back",
        "arrow_right": "go",
        "play": "play",
        "pause": "pause",
        "add": "add",
        "fwd": "jump_fwd",
        "rew": "jump_rew",
        "volup": "volume_up",
        "voldown": "volume_down",
        "mute": "mute",
        "0": "play_preset_0",
        "1": "play_preset_1",
        "2": "play_preset_2",
        "3": "play_preset_3",
        "4": "play_preset_4",
        "5": "play_preset_5",
        "6": "play_preset_6",
        "7": "play_preset_7",
        "8": "play_preset_8",
        "9": "play_preset_9",
        "factory_test_mode": "go_factory_test_mode",
        "test_audio_routing": "go_test_audio_routing",
        # Harmony remote integration: discrete IR codes for presets 1-6
        "preset_1": "play_preset_1",
        "preset_2": "play_preset_2",
        "preset_3": "play_preset_3",
        "preset_4": "play_preset_4",
        "preset_5": "play_preset_5",
        "preset_6": "play_preset_6",
    },
    "hold": {
        "sleep": "sleep",
        "power": "power",
        "power_off": "power_off",
        "power_on": "power_on",
        "home": "go_home",
        "search": "go_search",
        "now_playing": "go_now_playing",
        "size": "go_playlist",
        "browse": "go_music_library",
        "favorites": "go_favorites",
        "brightness": "go_brightness",
        "shuffle": "shuffle_toggle",
        "repeat": "repeat_toggle",
        "arrow_left": "go_home",
        "arrow_right": "add",
        "play": "create_mix",
        "pause": "stop",
        "add": "add_end",
        "fwd": "scanner_fwd",
        "rew": "scanner_rew",
        "volup": "volume_up",
        "voldown": "volume_down",
        "0": "disabled",
        "1": "disabled",
        "2": "disabled",
        "3": "disabled",
        "4": "disabled",
        "5": "disabled",
        "6": "disabled",
        "7": "disabled",
        "8": "disabled",
        "9": "disabled",
    },
}

# ---------------------------------------------------------------------------
# Action → action mappings (action chaining / title-bar buttons)
# ---------------------------------------------------------------------------

action_action_mappings: dict[str, str] = {
    "title_left_press": "back",  # will be reset by ShortcutsMeta defaults
    "title_left_hold": "go_home",  # will be reset by ShortcutsMeta defaults
    "title_right_press": "go_now_playing",  # will be reset by ShortcutsMeta defaults
    "title_right_hold": "go_playlist",  # will be reset by ShortcutsMeta defaults
    "home_title_left_press": "power",  # will be reset by ShortcutsMeta defaults
    "home_title_left_hold": "power",  # will be reset by ShortcutsMeta defaults
}

# ---------------------------------------------------------------------------
# Unassigned actions — triggered programmatically, not by hardware input.
# Listing them here ensures they are registered with the Framework so
# they can be used by applets via add_action_listener().
# ---------------------------------------------------------------------------

unassigned_action_mappings: list[str] = [
    "text_mode",
    "play_next",
    "finish_operation",
    "more_help",
    "cursor_left",
    "cursor_right",
    "clear",
    "go_settings",
    "go_rhapsody",
    "nothing",
    "disabled",
    "ignore",
    "power_off",
    "power_on",
    "cancel",
    "mute",
    "start_demo",
]
