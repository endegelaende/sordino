"""Tests for jive.ui.event — UI event creation and typed accessors."""

from __future__ import annotations

import pytest

from jive.ui.constants import (
    ACTION,
    EVENT_CHAR_PRESS,
    EVENT_FOCUS_GAINED,
    EVENT_FOCUS_LOST,
    EVENT_GESTURE,
    EVENT_HIDE,
    EVENT_IR_DOWN,
    EVENT_IR_HOLD,
    EVENT_IR_PRESS,
    EVENT_IR_REPEAT,
    EVENT_IR_UP,
    EVENT_KEY_DOWN,
    EVENT_KEY_HOLD,
    EVENT_KEY_PRESS,
    EVENT_KEY_UP,
    EVENT_MOTION,
    EVENT_MOUSE_DOWN,
    EVENT_MOUSE_DRAG,
    EVENT_MOUSE_HOLD,
    EVENT_MOUSE_MOVE,
    EVENT_MOUSE_PRESS,
    EVENT_MOUSE_UP,
    EVENT_NONE,
    EVENT_SCROLL,
    EVENT_SHOW,
    EVENT_SWITCH,
    EVENT_UPDATE,
    EVENT_WINDOW_ACTIVE,
    EVENT_WINDOW_INACTIVE,
    EVENT_WINDOW_POP,
    EVENT_WINDOW_PUSH,
    GESTURE_L_R,
    GESTURE_R_L,
    KEY_BACK,
    KEY_DOWN,
    KEY_FWD,
    KEY_GO,
    KEY_HOME,
    KEY_NONE,
    KEY_PLAY,
    KEY_REW,
    KEY_UP,
    KEY_VOLUME_DOWN,
    KEY_VOLUME_UP,
)
from jive.ui.event import (
    ActionData,
    CharData,
    Event,
    GestureData,
    IRData,
    KeyData,
    MotionData,
    MouseData,
    ScrollData,
    SwitchData,
)

# =========================================================================
# Scroll events
# =========================================================================


class TestScrollEvent:
    """Event(EVENT_SCROLL, rel=…) construction and accessor."""

    def test_positive_scroll(self) -> None:
        ev = Event(EVENT_SCROLL, rel=3)
        assert ev.get_scroll() == 3
        assert ev.get_type() == EVENT_SCROLL

    def test_negative_scroll(self) -> None:
        ev = Event(EVENT_SCROLL, rel=-5)
        assert ev.get_scroll() == -5

    def test_zero_scroll(self) -> None:
        ev = Event(EVENT_SCROLL, rel=0)
        assert ev.get_scroll() == 0

    def test_large_scroll(self) -> None:
        ev = Event(EVENT_SCROLL, rel=9999)
        assert ev.get_scroll() == 9999

    def test_data_is_scroll_data(self) -> None:
        ev = Event(EVENT_SCROLL, rel=1)
        assert isinstance(ev._data, ScrollData)


# =========================================================================
# Key events
# =========================================================================


class TestKeyEvent:
    """Event(EVENT_KEY_*, code=…) construction and accessor."""

    def test_key_press_go(self) -> None:
        ev = Event(EVENT_KEY_PRESS, code=KEY_GO)
        assert ev.get_keycode() == KEY_GO
        assert ev.get_type() == EVENT_KEY_PRESS

    def test_key_down(self) -> None:
        ev = Event(EVENT_KEY_DOWN, code=KEY_BACK)
        assert ev.get_keycode() == KEY_BACK
        assert ev.get_type() == EVENT_KEY_DOWN

    def test_key_up(self) -> None:
        ev = Event(EVENT_KEY_UP, code=KEY_UP)
        assert ev.get_keycode() == KEY_UP

    def test_key_hold(self) -> None:
        ev = Event(EVENT_KEY_HOLD, code=KEY_PLAY)
        assert ev.get_keycode() == KEY_PLAY

    def test_key_none(self) -> None:
        ev = Event(EVENT_KEY_PRESS, code=KEY_NONE)
        assert ev.get_keycode() == KEY_NONE

    def test_key_volume_up(self) -> None:
        ev = Event(EVENT_KEY_PRESS, code=KEY_VOLUME_UP)
        assert ev.get_keycode() == KEY_VOLUME_UP

    def test_key_volume_down(self) -> None:
        ev = Event(EVENT_KEY_PRESS, code=KEY_VOLUME_DOWN)
        assert ev.get_keycode() == KEY_VOLUME_DOWN

    def test_key_home(self) -> None:
        ev = Event(EVENT_KEY_PRESS, code=KEY_HOME)
        assert ev.get_keycode() == KEY_HOME

    def test_key_rew_fwd(self) -> None:
        ev_r = Event(EVENT_KEY_PRESS, code=KEY_REW)
        ev_f = Event(EVENT_KEY_PRESS, code=KEY_FWD)
        assert ev_r.get_keycode() == KEY_REW
        assert ev_f.get_keycode() == KEY_FWD

    def test_all_key_event_types_produce_key_data(self) -> None:
        for etype in (EVENT_KEY_DOWN, EVENT_KEY_UP, EVENT_KEY_PRESS, EVENT_KEY_HOLD):
            ev = Event(etype, code=KEY_GO)
            assert isinstance(ev._data, KeyData)

    def test_key_down_code_is_key_down_constant(self) -> None:
        """KEY_DOWN the key-code (4) vs EVENT_KEY_DOWN the event type — no confusion."""
        ev = Event(EVENT_KEY_PRESS, code=KEY_DOWN)
        assert ev.get_keycode() == KEY_DOWN
        assert ev.get_keycode() == 4


# =========================================================================
# Char events
# =========================================================================


class TestCharEvent:
    """Event(EVENT_CHAR_PRESS, unicode=…) construction and accessor."""

    def test_ascii_char(self) -> None:
        ev = Event(EVENT_CHAR_PRESS, unicode=65)
        assert ev.get_unicode() == 65

    def test_unicode_char(self) -> None:
        ev = Event(EVENT_CHAR_PRESS, unicode=0x1F600)
        assert ev.get_unicode() == 0x1F600

    def test_zero_unicode(self) -> None:
        ev = Event(EVENT_CHAR_PRESS, unicode=0)
        assert ev.get_unicode() == 0

    def test_data_is_char_data(self) -> None:
        ev = Event(EVENT_CHAR_PRESS, unicode=42)
        assert isinstance(ev._data, CharData)


# =========================================================================
# Mouse events
# =========================================================================


class TestMouseEvent:
    """Event(EVENT_MOUSE_*, x=…, y=…) construction and accessors."""

    def test_mouse_down_xy(self) -> None:
        ev = Event(EVENT_MOUSE_DOWN, x=100, y=200)
        assert ev.get_mouse_xy() == (100, 200)
        assert ev.get_type() == EVENT_MOUSE_DOWN

    def test_mouse_up(self) -> None:
        ev = Event(EVENT_MOUSE_UP, x=50, y=60)
        assert ev.get_mouse_xy() == (50, 60)

    def test_mouse_press(self) -> None:
        ev = Event(EVENT_MOUSE_PRESS, x=0, y=0)
        assert ev.get_mouse_xy() == (0, 0)

    def test_mouse_hold(self) -> None:
        ev = Event(EVENT_MOUSE_HOLD, x=300, y=400)
        assert ev.get_mouse_xy() == (300, 400)

    def test_mouse_move(self) -> None:
        ev = Event(EVENT_MOUSE_MOVE, x=10, y=20)
        assert ev.get_mouse_xy() == (10, 20)

    def test_mouse_drag(self) -> None:
        ev = Event(EVENT_MOUSE_DRAG, x=999, y=1)
        assert ev.get_mouse_xy() == (999, 1)

    def test_get_mouse_full_tuple_no_chiral(self) -> None:
        ev = Event(EVENT_MOUSE_DOWN, x=10, y=20)
        result = ev.get_mouse()
        assert result == (10, 20, 0, 0, 0, None)

    def test_get_mouse_with_finger_data(self) -> None:
        ev = Event(
            EVENT_MOUSE_DOWN,
            x=10,
            y=20,
            finger_count=2,
            finger_width=5,
            finger_pressure=100,
        )
        x, y, fc, fw, fp, ch = ev.get_mouse()
        assert x == 10
        assert y == 20
        assert fc == 2
        assert fw == 5
        assert fp == 100
        assert ch is None  # chiral_active defaults to False

    def test_get_mouse_with_chiral(self) -> None:
        ev = Event(
            EVENT_MOUSE_DOWN,
            x=10,
            y=20,
            chiral_value=42,
            chiral_active=True,
        )
        _, _, _, _, _, ch = ev.get_mouse()
        assert ch == 42

    def test_get_mouse_chiral_inactive(self) -> None:
        ev = Event(
            EVENT_MOUSE_DOWN,
            x=10,
            y=20,
            chiral_value=42,
            chiral_active=False,
        )
        _, _, _, _, _, ch = ev.get_mouse()
        assert ch is None

    def test_all_mouse_types_produce_mouse_data(self) -> None:
        for etype in (
            EVENT_MOUSE_DOWN,
            EVENT_MOUSE_UP,
            EVENT_MOUSE_PRESS,
            EVENT_MOUSE_HOLD,
            EVENT_MOUSE_MOVE,
            EVENT_MOUSE_DRAG,
        ):
            ev = Event(etype, x=1, y=2)
            assert isinstance(ev._data, MouseData)


# =========================================================================
# Action events
# =========================================================================


class TestActionEvent:
    """Event(ACTION, index=…) construction and accessor."""

    def test_action_index(self) -> None:
        ev = Event(ACTION, index=5)
        assert ev.get_action_internal() == 5
        assert ev.get_type() == ACTION

    def test_action_index_zero(self) -> None:
        ev = Event(ACTION, index=0)
        assert ev.get_action_internal() == 0

    def test_action_index_large(self) -> None:
        ev = Event(ACTION, index=9999)
        assert ev.get_action_internal() == 9999

    def test_data_is_action_data(self) -> None:
        ev = Event(ACTION, index=3)
        assert isinstance(ev._data, ActionData)


# =========================================================================
# Motion events
# =========================================================================


class TestMotionEvent:
    """Event(EVENT_MOTION, x=…, y=…, z=…) construction and accessor."""

    def test_motion_xyz(self) -> None:
        ev = Event(EVENT_MOTION, x=1, y=2, z=3)
        assert ev.get_motion() == (1, 2, 3)
        assert ev.get_type() == EVENT_MOTION

    def test_motion_zeros(self) -> None:
        ev = Event(EVENT_MOTION, x=0, y=0, z=0)
        assert ev.get_motion() == (0, 0, 0)

    def test_motion_negative(self) -> None:
        ev = Event(EVENT_MOTION, x=-10, y=-20, z=-30)
        assert ev.get_motion() == (-10, -20, -30)

    def test_data_is_motion_data(self) -> None:
        ev = Event(EVENT_MOTION, x=1, y=2, z=3)
        assert isinstance(ev._data, MotionData)


# =========================================================================
# Switch events
# =========================================================================


class TestSwitchEvent:
    """Event(EVENT_SWITCH, code=…, value=…) construction and accessor."""

    def test_switch_code_value(self) -> None:
        ev = Event(EVENT_SWITCH, code=1, value=2)
        assert ev.get_switch() == (1, 2)
        assert ev.get_type() == EVENT_SWITCH

    def test_switch_zeros(self) -> None:
        ev = Event(EVENT_SWITCH, code=0, value=0)
        assert ev.get_switch() == (0, 0)

    def test_data_is_switch_data(self) -> None:
        ev = Event(EVENT_SWITCH, code=1, value=2)
        assert isinstance(ev._data, SwitchData)


# =========================================================================
# IR events
# =========================================================================


class TestIREvent:
    """Event(EVENT_IR_*, code=…) construction and accessor."""

    def test_ir_press(self) -> None:
        ev = Event(EVENT_IR_PRESS, code=42)
        assert ev.get_ir_code() == 42
        assert ev.get_type() == EVENT_IR_PRESS

    def test_ir_hold(self) -> None:
        ev = Event(EVENT_IR_HOLD, code=99)
        assert ev.get_ir_code() == 99

    def test_ir_up(self) -> None:
        ev = Event(EVENT_IR_UP, code=7)
        assert ev.get_ir_code() == 7

    def test_ir_down(self) -> None:
        ev = Event(EVENT_IR_DOWN, code=0xFF)
        assert ev.get_ir_code() == 0xFF

    def test_ir_repeat(self) -> None:
        ev = Event(EVENT_IR_REPEAT, code=1234)
        assert ev.get_ir_code() == 1234

    def test_all_ir_types_produce_ir_data(self) -> None:
        for etype in (
            EVENT_IR_PRESS,
            EVENT_IR_HOLD,
            EVENT_IR_UP,
            EVENT_IR_DOWN,
            EVENT_IR_REPEAT,
        ):
            ev = Event(etype, code=10)
            assert isinstance(ev._data, IRData)


# =========================================================================
# Gesture events
# =========================================================================


class TestGestureEvent:
    """Event(EVENT_GESTURE, code=…) construction and accessor."""

    def test_gesture_left_to_right(self) -> None:
        ev = Event(EVENT_GESTURE, code=GESTURE_L_R)
        assert ev.get_gesture() == GESTURE_L_R
        assert ev.get_type() == EVENT_GESTURE

    def test_gesture_right_to_left(self) -> None:
        ev = Event(EVENT_GESTURE, code=GESTURE_R_L)
        assert ev.get_gesture() == GESTURE_R_L

    def test_data_is_gesture_data(self) -> None:
        ev = Event(EVENT_GESTURE, code=GESTURE_L_R)
        assert isinstance(ev._data, GestureData)


# =========================================================================
# Payload-less events (SHOW, HIDE, WINDOW_*, FOCUS_*)
# =========================================================================


class TestPayloadlessEvents:
    """Events that carry no typed payload have _data == None."""

    @pytest.mark.parametrize(
        "event_type",
        [
            EVENT_SHOW,
            EVENT_HIDE,
            EVENT_WINDOW_PUSH,
            EVENT_WINDOW_POP,
            EVENT_WINDOW_ACTIVE,
            EVENT_WINDOW_INACTIVE,
            EVENT_FOCUS_GAINED,
            EVENT_FOCUS_LOST,
        ],
    )
    def test_no_typed_data(self, event_type: int) -> None:
        ev = Event(event_type)
        assert ev._data is None
        assert ev.get_type() == event_type

    def test_show_event_type(self) -> None:
        ev = Event(EVENT_SHOW)
        assert ev.get_type() == EVENT_SHOW

    def test_hide_event_type(self) -> None:
        ev = Event(EVENT_HIDE)
        assert ev.get_type() == EVENT_HIDE


# =========================================================================
# Type errors — wrong accessor for the event type
# =========================================================================


class TestTypeErrors:
    """Calling the wrong typed accessor raises TypeError."""

    def test_scroll_on_key_event(self) -> None:
        ev = Event(EVENT_KEY_PRESS, code=KEY_GO)
        with pytest.raises(TypeError, match="Not a scroll event"):
            ev.get_scroll()

    def test_keycode_on_scroll_event(self) -> None:
        ev = Event(EVENT_SCROLL, rel=1)
        with pytest.raises(TypeError, match="Not a key event"):
            ev.get_keycode()

    def test_unicode_on_key_event(self) -> None:
        ev = Event(EVENT_KEY_PRESS, code=KEY_GO)
        with pytest.raises(TypeError, match="Not a char event"):
            ev.get_unicode()

    def test_mouse_on_scroll_event(self) -> None:
        ev = Event(EVENT_SCROLL, rel=1)
        with pytest.raises(TypeError, match="Not a mouse event"):
            ev.get_mouse()

    def test_mouse_xy_on_key_event(self) -> None:
        ev = Event(EVENT_KEY_PRESS, code=KEY_GO)
        with pytest.raises(TypeError, match="Not a mouse event"):
            ev.get_mouse_xy()

    def test_action_on_scroll_event(self) -> None:
        ev = Event(EVENT_SCROLL, rel=1)
        with pytest.raises(TypeError, match="Not an action event"):
            ev.get_action_internal()

    def test_motion_on_scroll_event(self) -> None:
        ev = Event(EVENT_SCROLL, rel=1)
        with pytest.raises(TypeError, match="Not a motion event"):
            ev.get_motion()

    def test_switch_on_scroll_event(self) -> None:
        ev = Event(EVENT_SCROLL, rel=1)
        with pytest.raises(TypeError, match="Not a switch event"):
            ev.get_switch()

    def test_ir_code_on_key_event(self) -> None:
        ev = Event(EVENT_KEY_PRESS, code=KEY_GO)
        with pytest.raises(TypeError, match="Not an IR event"):
            ev.get_ir_code()

    def test_gesture_on_scroll_event(self) -> None:
        ev = Event(EVENT_SCROLL, rel=1)
        with pytest.raises(TypeError, match="Not a gesture event"):
            ev.get_gesture()

    def test_scroll_on_show_event(self) -> None:
        ev = Event(EVENT_SHOW)
        with pytest.raises(TypeError, match="Not a scroll event"):
            ev.get_scroll()

    def test_keycode_on_mouse_event(self) -> None:
        ev = Event(EVENT_MOUSE_DOWN, x=0, y=0)
        with pytest.raises(TypeError, match="Not a key event"):
            ev.get_keycode()

    def test_action_on_gesture_event(self) -> None:
        ev = Event(EVENT_GESTURE, code=GESTURE_L_R)
        with pytest.raises(TypeError, match="Not an action event"):
            ev.get_action_internal()

    def test_get_action_on_non_action_event(self) -> None:
        ev = Event(EVENT_SCROLL, rel=1)
        with pytest.raises(TypeError, match="Not an action event"):
            ev.get_action()


# =========================================================================
# Ticks / timestamps
# =========================================================================


class TestTicks:
    """Event.get_ticks() returns auto-generated or custom timestamps."""

    def test_auto_ticks_non_negative(self) -> None:
        ev = Event(EVENT_SCROLL, rel=1)
        assert ev.get_ticks() >= 0
        assert isinstance(ev.get_ticks(), int)

    def test_custom_ticks(self) -> None:
        ev = Event(EVENT_SCROLL, rel=1, ticks=12345)
        assert ev.get_ticks() == 12345

    def test_custom_ticks_zero(self) -> None:
        ev = Event(EVENT_SCROLL, rel=1, ticks=0)
        assert ev.get_ticks() == 0

    def test_two_events_have_close_ticks(self) -> None:
        """Two events created in quick succession should have similar ticks."""
        ev1 = Event(EVENT_SCROLL, rel=1)
        ev2 = Event(EVENT_SCROLL, rel=2)
        # Both created in the same test — should be within 100ms of each other
        assert abs(ev1.get_ticks() - ev2.get_ticks()) < 100


# =========================================================================
# get_value (generic value accessor)
# =========================================================================


class TestGetValue:
    """Event.get_value() returns the generic value field."""

    def test_default_value_zero(self) -> None:
        ev = Event(EVENT_SCROLL, rel=1)
        assert ev.get_value() == 0

    def test_custom_value(self) -> None:
        ev = Event(EVENT_SWITCH, code=1, value=42)
        assert ev.get_value() == 42

    def test_value_on_payloadless_event(self) -> None:
        ev = Event(EVENT_SHOW, value=10)
        assert ev.get_value() == 10


# =========================================================================
# camelCase aliases
# =========================================================================


class TestCamelCaseAliases:
    """camelCase aliases match their snake_case counterparts."""

    def test_getType(self) -> None:
        ev = Event(EVENT_SCROLL, rel=1)
        assert ev.getType == ev.get_type
        assert ev.getType() == ev.get_type()

    def test_getTicks(self) -> None:
        ev = Event(EVENT_SCROLL, rel=1, ticks=100)
        assert ev.getTicks == ev.get_ticks
        assert ev.getTicks() == 100

    def test_getScroll(self) -> None:
        ev = Event(EVENT_SCROLL, rel=5)
        assert ev.getScroll == ev.get_scroll
        assert ev.getScroll() == 5

    def test_getKeycode(self) -> None:
        ev = Event(EVENT_KEY_PRESS, code=KEY_GO)
        assert ev.getKeycode == ev.get_keycode
        assert ev.getKeycode() == KEY_GO

    def test_getUnicode(self) -> None:
        ev = Event(EVENT_CHAR_PRESS, unicode=65)
        assert ev.getUnicode == ev.get_unicode
        assert ev.getUnicode() == 65

    def test_getMouse(self) -> None:
        ev = Event(EVENT_MOUSE_DOWN, x=10, y=20)
        assert ev.getMouse == ev.get_mouse
        assert ev.getMouse() == ev.get_mouse()

    def test_getMouseXY(self) -> None:
        ev = Event(EVENT_MOUSE_DOWN, x=10, y=20)
        assert ev.getMouseXY == ev.get_mouse_xy
        assert ev.getMouseXY() == (10, 20)

    def test_getActionInternal(self) -> None:
        ev = Event(ACTION, index=7)
        assert ev.getActionInternal == ev.get_action_internal
        assert ev.getActionInternal() == 7

    def test_getMotion(self) -> None:
        ev = Event(EVENT_MOTION, x=1, y=2, z=3)
        assert ev.getMotion == ev.get_motion
        assert ev.getMotion() == (1, 2, 3)

    def test_getSwitch(self) -> None:
        ev = Event(EVENT_SWITCH, code=1, value=2)
        assert ev.getSwitch == ev.get_switch
        assert ev.getSwitch() == (1, 2)

    def test_getIRCode(self) -> None:
        ev = Event(EVENT_IR_PRESS, code=42)
        assert ev.getIRCode == ev.get_ir_code
        assert ev.getIRCode() == 42

    def test_getGesture(self) -> None:
        ev = Event(EVENT_GESTURE, code=GESTURE_L_R)
        assert ev.getGesture == ev.get_gesture
        assert ev.getGesture() == GESTURE_L_R

    def test_getValue(self) -> None:
        ev = Event(EVENT_SWITCH, code=1, value=99)
        assert ev.getValue == ev.get_value
        assert ev.getValue() == 99

    def test_getAction_alias_exists(self) -> None:
        ev = Event(ACTION, index=1)
        assert ev.getAction == ev.get_action


# =========================================================================
# __repr__
# =========================================================================


class TestRepr:
    """__repr__ includes type name and relevant payload data."""

    def test_scroll_repr(self) -> None:
        ev = Event(EVENT_SCROLL, rel=3, ticks=100)
        r = repr(ev)
        assert "SCROLL" in r
        assert "rel=3" in r

    def test_key_repr(self) -> None:
        ev = Event(EVENT_KEY_PRESS, code=KEY_GO, ticks=100)
        r = repr(ev)
        assert "KEY_PRESS" in r
        assert "code=" in r

    def test_char_repr(self) -> None:
        ev = Event(EVENT_CHAR_PRESS, unicode=65, ticks=100)
        r = repr(ev)
        assert "CHAR_PRESS" in r
        assert "unicode=65" in r

    def test_mouse_repr_simple(self) -> None:
        ev = Event(EVENT_MOUSE_DOWN, x=10, y=20, ticks=100)
        r = repr(ev)
        assert "MOUSE_DOWN" in r
        assert "x=10" in r
        assert "y=20" in r

    def test_mouse_repr_with_finger(self) -> None:
        ev = Event(
            EVENT_MOUSE_DOWN,
            x=10,
            y=20,
            finger_count=2,
            finger_width=5,
            finger_pressure=100,
            ticks=100,
        )
        r = repr(ev)
        assert "n=2" in r
        assert "w=5" in r
        assert "p=100" in r

    def test_action_repr(self) -> None:
        ev = Event(ACTION, index=5, ticks=100)
        r = repr(ev)
        assert "ACTION" in r
        assert "actionIndex=5" in r

    def test_motion_repr(self) -> None:
        ev = Event(EVENT_MOTION, x=1, y=2, z=3, ticks=100)
        r = repr(ev)
        assert "MOTION" in r
        assert "x=1" in r
        assert "z=3" in r

    def test_switch_repr(self) -> None:
        ev = Event(EVENT_SWITCH, code=1, value=2, ticks=100)
        r = repr(ev)
        assert "SWITCH" in r
        assert "code=1" in r
        assert "value=2" in r

    def test_ir_repr(self) -> None:
        ev = Event(EVENT_IR_PRESS, code=0xFF, ticks=100)
        r = repr(ev)
        assert "IR_PRESS" in r
        assert "code=0x" in r

    def test_gesture_repr(self) -> None:
        ev = Event(EVENT_GESTURE, code=GESTURE_L_R, ticks=100)
        r = repr(ev)
        assert "GESTURE" in r
        assert "code=" in r

    def test_show_repr_no_payload(self) -> None:
        ev = Event(EVENT_SHOW, ticks=100)
        r = repr(ev)
        assert "SHOW" in r
        assert "Event(" in r
        assert r.endswith(")")

    def test_str_matches_repr(self) -> None:
        ev = Event(EVENT_SCROLL, rel=1, ticks=100)
        assert str(ev) == repr(ev)

    def test_repr_starts_with_event(self) -> None:
        ev = Event(EVENT_SCROLL, rel=1, ticks=100)
        assert repr(ev).startswith("Event(")

    def test_repr_contains_ticks(self) -> None:
        ev = Event(EVENT_SCROLL, rel=1, ticks=42)
        assert "ticks=42" in repr(ev)


# =========================================================================
# EVENT_NONE
# =========================================================================


class TestEventNone:
    """Event with type EVENT_NONE (0)."""

    def test_none_event_type(self) -> None:
        ev = Event(EVENT_NONE)
        assert ev.get_type() == 0
        assert ev._data is None


# =========================================================================
# Edge cases
# =========================================================================


class TestEdgeCases:
    """Miscellaneous edge cases."""

    def test_event_type_stored_as_int(self) -> None:
        ev = Event(EVENT_SCROLL, rel=1)
        assert isinstance(ev.get_type(), int)

    def test_event_preserves_raw_type_value(self) -> None:
        ev = Event(EVENT_KEY_PRESS, code=KEY_GO)
        assert ev.get_type() == 0x00000040

    def test_action_type_value(self) -> None:
        ev = Event(ACTION, index=1)
        assert ev.get_type() == 0x10000000

    def test_multiple_events_independent(self) -> None:
        ev1 = Event(EVENT_SCROLL, rel=1, ticks=100)
        ev2 = Event(EVENT_SCROLL, rel=99, ticks=200)
        assert ev1.get_scroll() == 1
        assert ev2.get_scroll() == 99
        assert ev1.get_ticks() == 100
        assert ev2.get_ticks() == 200

    def test_event_update_has_no_data(self) -> None:
        """EVENT_UPDATE is a virtual event with no typed payload."""
        ev = Event(EVENT_UPDATE, value=42)
        assert ev._data is None
        assert ev.get_value() == 42
