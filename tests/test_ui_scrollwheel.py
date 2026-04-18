"""Tests for jive.ui.scrollwheel.ScrollWheel and jive.ui.scrollaccel.ScrollAccel."""

from __future__ import annotations

from typing import Callable, Optional

import pytest

from jive.ui.scrollaccel import ScrollAccel
from jive.ui.scrollwheel import ScrollWheel

# ---------------------------------------------------------------------------
# Mock scroll event — avoids importing the real Event (which touches pygame)
# ---------------------------------------------------------------------------


class MockScrollEvent:
    """Minimal stand-in for ``jive.ui.event.Event`` with scroll data."""

    def __init__(self, scroll: int, ticks: int = 0) -> None:
        self._scroll = scroll
        self._ticks = ticks

    def get_scroll(self) -> int:
        return self._scroll

    def get_ticks(self) -> int:
        return self._ticks


# ---------------------------------------------------------------------------
# ScrollWheel tests
# ---------------------------------------------------------------------------


class TestScrollWheelConstruction:
    """Constructor validation."""

    def test_default_construction(self) -> None:
        wheel = ScrollWheel()
        assert wheel is not None

    def test_custom_item_available(self) -> None:
        wheel = ScrollWheel(item_available=lambda t, v: True)
        assert wheel.item_available is not None

    def test_rejects_non_callable(self) -> None:
        with pytest.raises(TypeError, match="callable"):
            ScrollWheel(item_available=42)  # type: ignore[arg-type]

    def test_rejects_string(self) -> None:
        with pytest.raises(TypeError, match="callable"):
            ScrollWheel(item_available="nope")  # type: ignore[arg-type]

    def test_none_item_available_uses_default(self) -> None:
        wheel = ScrollWheel(item_available=None)
        # Default always returns True — verify via _check_item_available
        assert wheel._check_item_available(1, 5, 10) is True


class TestScrollWheelBasicScroll:
    """Basic scroll direction normalisation."""

    def test_positive_scroll_returns_plus_one(self) -> None:
        wheel = ScrollWheel()
        ev = MockScrollEvent(scroll=5)
        result = wheel.event(ev, list_top=1, list_index=3, list_visible=5, list_size=20)
        assert result == 1

    def test_negative_scroll_returns_minus_one(self) -> None:
        wheel = ScrollWheel()
        ev = MockScrollEvent(scroll=-3)
        result = wheel.event(ev, list_top=1, list_index=3, list_visible=5, list_size=20)
        assert result == -1

    def test_scroll_plus_one(self) -> None:
        wheel = ScrollWheel()
        ev = MockScrollEvent(scroll=1)
        result = wheel.event(ev, list_top=1, list_index=1, list_visible=5, list_size=20)
        assert result == 1

    def test_scroll_minus_one(self) -> None:
        wheel = ScrollWheel()
        ev = MockScrollEvent(scroll=-1)
        result = wheel.event(ev, list_top=1, list_index=5, list_visible=5, list_size=20)
        assert result == -1

    def test_large_positive_scroll_still_plus_one(self) -> None:
        wheel = ScrollWheel()
        ev = MockScrollEvent(scroll=100)
        result = wheel.event(ev, list_top=1, list_index=3, list_visible=5, list_size=100)
        assert result == 1

    def test_large_negative_scroll_still_minus_one(self) -> None:
        wheel = ScrollWheel()
        ev = MockScrollEvent(scroll=-100)
        result = wheel.event(ev, list_top=1, list_index=3, list_visible=5, list_size=100)
        assert result == -1


class TestScrollWheelItemAvailable:
    """Custom item_available callback can block scrolling."""

    def test_item_available_blocks_scroll(self) -> None:
        wheel = ScrollWheel(item_available=lambda t, v: False)
        ev = MockScrollEvent(scroll=1)
        result = wheel.event(ev, list_top=1, list_index=3, list_visible=5, list_size=20)
        assert result == 0

    def test_item_available_allows_scroll(self) -> None:
        wheel = ScrollWheel(item_available=lambda t, v: True)
        ev = MockScrollEvent(scroll=1)
        result = wheel.event(ev, list_top=1, list_index=3, list_visible=5, list_size=20)
        assert result == 1

    def test_item_available_called_with_correct_args(self) -> None:
        calls: list[tuple[int, int]] = []

        def tracker(top: int, vis: int) -> bool:
            calls.append((top, vis))
            return True

        wheel = ScrollWheel(item_available=tracker)
        ev = MockScrollEvent(scroll=1)
        wheel.event(ev, list_top=1, list_index=3, list_visible=5, list_size=20)
        assert len(calls) == 1
        # Args are the clamped target_top and list_visible
        top_called, vis_called = calls[0]
        assert isinstance(top_called, int)
        assert isinstance(vis_called, int)

    def test_item_available_property_setter(self) -> None:
        wheel = ScrollWheel()
        new_func: Callable[[int, int], bool] = lambda t, v: False
        wheel.item_available = new_func
        assert wheel.item_available is new_func

    def test_item_available_property_setter_rejects_non_callable(self) -> None:
        wheel = ScrollWheel()
        with pytest.raises(TypeError, match="callable"):
            wheel.item_available = 99  # type: ignore[assignment]


class TestScrollWheelCheckItemAvailable:
    """Edge cases for _check_item_available clamping."""

    def test_clamps_visible_to_list_size(self) -> None:
        calls: list[tuple[int, int]] = []

        def tracker(top: int, vis: int) -> bool:
            calls.append((top, vis))
            return True

        wheel = ScrollWheel(item_available=tracker)
        # list_visible (10) > list_size (5) → clamped to 5
        wheel._check_item_available(list_top=1, list_visible=10, list_size=5)
        assert calls[0][1] == 5

    def test_clamps_top_when_exceeds_size(self) -> None:
        calls: list[tuple[int, int]] = []

        def tracker(top: int, vis: int) -> bool:
            calls.append((top, vis))
            return True

        wheel = ScrollWheel(item_available=tracker)
        # top(8) + visible(5) = 13 > size(10) → top = 10-5 = 5
        wheel._check_item_available(list_top=8, list_visible=5, list_size=10)
        assert calls[0][0] == 5

    def test_clamps_top_minimum_to_one(self) -> None:
        calls: list[tuple[int, int]] = []

        def tracker(top: int, vis: int) -> bool:
            calls.append((top, vis))
            return True

        wheel = ScrollWheel(item_available=tracker)
        # Negative top gets clamped to 1
        wheel._check_item_available(list_top=-5, list_visible=5, list_size=10)
        assert calls[0][0] == 1

    def test_zero_top_clamped_to_one(self) -> None:
        calls: list[tuple[int, int]] = []

        def tracker(top: int, vis: int) -> bool:
            calls.append((top, vis))
            return True

        wheel = ScrollWheel(item_available=tracker)
        wheel._check_item_available(list_top=0, list_visible=3, list_size=10)
        assert calls[0][0] == 1

    def test_exact_fit_no_clamping(self) -> None:
        calls: list[tuple[int, int]] = []

        def tracker(top: int, vis: int) -> bool:
            calls.append((top, vis))
            return True

        wheel = ScrollWheel(item_available=tracker)
        # top(6) + visible(5) = 11 > size(10) → clamped to 5
        wheel._check_item_available(list_top=6, list_visible=5, list_size=10)
        assert calls[0][0] == 5
        assert calls[0][1] == 5


class TestScrollWheelRepr:
    """String representation."""

    def test_repr(self) -> None:
        wheel = ScrollWheel()
        assert "ScrollWheel" in repr(wheel)

    def test_str_matches_repr(self) -> None:
        wheel = ScrollWheel()
        assert str(wheel) == repr(wheel)


# ---------------------------------------------------------------------------
# ScrollAccel tests
# ---------------------------------------------------------------------------


class TestScrollAccelConstruction:
    """Constructor and initial state."""

    def test_default_construction(self) -> None:
        accel = ScrollAccel()
        assert accel is not None

    def test_inherits_from_scrollwheel(self) -> None:
        accel = ScrollAccel()
        assert isinstance(accel, ScrollWheel)

    def test_initial_state(self) -> None:
        accel = ScrollAccel()
        assert accel.scroll_accel is None
        assert accel.scroll_dir == 0

    def test_custom_item_available(self) -> None:
        accel = ScrollAccel(item_available=lambda t, v: True)
        assert accel.item_available is not None


class TestScrollAccelNoAcceleration:
    """Without acceleration (direction change or long pause): returns ±1."""

    def test_first_scroll_no_acceleration(self) -> None:
        accel = ScrollAccel()
        ev = MockScrollEvent(scroll=1, ticks=0)
        result = accel.event(ev, list_top=1, list_index=3, list_visible=5, list_size=100)
        assert result == 1

    def test_first_negative_scroll_no_acceleration(self) -> None:
        accel = ScrollAccel()
        ev = MockScrollEvent(scroll=-1, ticks=0)
        result = accel.event(ev, list_top=1, list_index=3, list_visible=5, list_size=100)
        assert result == -1

    def test_direction_change_resets(self) -> None:
        accel = ScrollAccel()
        # Scroll down several times to build acceleration
        for i in range(15):
            ev = MockScrollEvent(scroll=1, ticks=i * 10)
            accel.event(ev, list_top=1, list_index=3, list_visible=5, list_size=100)

        # Now change direction — should reset to ±1
        ev = MockScrollEvent(scroll=-1, ticks=200)
        result = accel.event(ev, list_top=1, list_index=3, list_visible=5, list_size=100)
        assert result == -1

    def test_pause_resets_acceleration(self) -> None:
        accel = ScrollAccel()
        # Build up some acceleration
        for i in range(15):
            ev = MockScrollEvent(scroll=1, ticks=i * 10)
            accel.event(ev, list_top=1, list_index=3, list_visible=5, list_size=100)

        assert accel.scroll_accel is not None

        # Pause longer than 250ms per unit of scroll
        ev = MockScrollEvent(scroll=1, ticks=15 * 10 + 500)
        result = accel.event(ev, list_top=1, list_index=3, list_visible=5, list_size=100)
        # After pause, acceleration resets — delegates to base class → ±1
        assert result == 1
        assert accel.scroll_accel is None


class TestScrollAccelAccelerationTiers:
    """Acceleration increases with consecutive same-direction scrolls."""

    def _build_accel(
        self,
        count: int,
        scroll: int = 1,
        *,
        list_size: int = 10000,
    ) -> tuple[ScrollAccel, int]:
        """Scroll *count* times and return (accel_obj, last_result)."""
        accel = ScrollAccel()
        result = 0
        for i in range(count):
            ev = MockScrollEvent(scroll=scroll, ticks=i * 10)
            result = accel.event(
                ev,
                list_top=1,
                list_index=3,
                list_visible=5,
                list_size=list_size,
            )
        return accel, result

    def test_tier_1_to_10_no_multiplier(self) -> None:
        """Scrolls 1-10: accel counter ≤10 → scroll value is raw (1×)."""
        # First scroll has no acceleration (direction init), so accel starts at 2nd
        accel = ScrollAccel()
        results = []
        for i in range(11):
            ev = MockScrollEvent(scroll=1, ticks=i * 10)
            r = accel.event(ev, list_top=1, list_index=3, list_visible=5, list_size=10000)
            results.append(r)
        # First event: no previous dir → delegates to base class → 1
        assert results[0] == 1
        # Events 2-11 should have accel 1..10 → 1× multiplier → scroll=1
        for r in results[1:11]:
            assert r == 1

    def test_tier_11_to_20_double(self) -> None:
        """Scrolls 11-20: accel 11-20 → 2× multiplier."""
        # We need 12 scrolls (1st sets dir, 2nd-11th = accel 1-10, 12th = accel 11)
        accel, result = self._build_accel(12)
        assert accel.scroll_accel == 11
        assert result == 2  # scroll(1) * 2

    def test_tier_21_to_30_quad(self) -> None:
        """Scrolls 21-30: accel 21-30 → 4× multiplier."""
        accel, result = self._build_accel(22)
        assert accel.scroll_accel == 21
        assert result == 4  # scroll(1) * 4

    def test_tier_31_to_40_octa(self) -> None:
        """Scrolls 31-40: accel 31-40 → 8× multiplier."""
        accel, result = self._build_accel(32)
        assert accel.scroll_accel == 31
        assert result == 8  # scroll(1) * 8

    def test_tier_41_to_50_sixteen(self) -> None:
        """Scrolls 41-50: accel 41-50 → 16× multiplier."""
        accel, result = self._build_accel(42)
        assert accel.scroll_accel == 41
        assert result == 16  # scroll(1) * 16

    def test_tier_above_50_max(self) -> None:
        """Scrolls >50: max(list_size/50, |scroll|*16)."""
        import math

        list_size = 10000
        accel, result = self._build_accel(52, list_size=list_size)
        assert accel.scroll_accel is not None
        assert accel.scroll_accel == 51
        expected = max(math.ceil(list_size / 50), abs(1) * 16)
        assert result == expected  # 200

    def test_tier_above_50_small_list(self) -> None:
        """When list_size/50 < |scroll|*16, the scroll*16 wins."""
        import math

        list_size = 100
        accel, result = self._build_accel(52, scroll=2, list_size=list_size)
        assert accel.scroll_accel == 51
        expected = max(math.ceil(list_size / 50), abs(2) * 16)
        assert result == expected

    def test_negative_scroll_acceleration(self) -> None:
        """Acceleration works in the negative direction too."""
        accel, result = self._build_accel(12, scroll=-1)
        assert accel.scroll_accel == 11
        assert result == -2  # scroll(-1) * 2

    def test_accel_counter_increments(self) -> None:
        """The accel counter increments with each same-direction scroll."""
        accel = ScrollAccel()
        for i in range(5):
            ev = MockScrollEvent(scroll=1, ticks=i * 10)
            accel.event(ev, list_top=1, list_index=3, list_visible=5, list_size=100)

        # First event sets direction (no accel), next 4 increment 1..4
        assert accel.scroll_accel == 4


class TestScrollAccelReset:
    """reset() clears acceleration state."""

    def test_reset_clears_accel(self) -> None:
        accel = ScrollAccel()
        # Build some acceleration
        for i in range(5):
            ev = MockScrollEvent(scroll=1, ticks=i * 10)
            accel.event(ev, list_top=1, list_index=3, list_visible=5, list_size=100)

        assert accel.scroll_accel is not None
        assert accel.scroll_dir != 0

        accel.reset()
        assert accel.scroll_accel is None
        assert accel.scroll_dir == 0

    def test_reset_allows_fresh_start(self) -> None:
        accel = ScrollAccel()
        for i in range(15):
            ev = MockScrollEvent(scroll=1, ticks=i * 10)
            accel.event(ev, list_top=1, list_index=3, list_visible=5, list_size=100)

        accel.reset()

        # First scroll after reset should behave like the first-ever scroll
        ev = MockScrollEvent(scroll=1, ticks=200)
        result = accel.event(ev, list_top=1, list_index=3, list_visible=5, list_size=100)
        assert result == 1
        assert accel.scroll_accel is None  # still None after direction-init


class TestScrollAccelProperties:
    """State inspection properties."""

    def test_scroll_accel_none_initially(self) -> None:
        accel = ScrollAccel()
        assert accel.scroll_accel is None

    def test_scroll_dir_zero_initially(self) -> None:
        accel = ScrollAccel()
        assert accel.scroll_dir == 0

    def test_scroll_dir_positive_after_down(self) -> None:
        accel = ScrollAccel()
        ev = MockScrollEvent(scroll=1, ticks=0)
        accel.event(ev, list_top=1, list_index=3, list_visible=5, list_size=100)
        assert accel.scroll_dir == 1

    def test_scroll_dir_negative_after_up(self) -> None:
        accel = ScrollAccel()
        ev = MockScrollEvent(scroll=-1, ticks=0)
        accel.event(ev, list_top=1, list_index=3, list_visible=5, list_size=100)
        assert accel.scroll_dir == -1


class TestScrollAccelItemAvailable:
    """Item availability blocks accelerated scrolling too."""

    def test_blocked_returns_zero(self) -> None:
        accel = ScrollAccel(item_available=lambda t, v: False)
        # Build acceleration first with available items... actually the callback
        # is always called, so if it always returns False, all scrolls return 0
        ev = MockScrollEvent(scroll=1, ticks=0)
        result = accel.event(ev, list_top=1, list_index=3, list_visible=5, list_size=100)
        assert result == 0


class TestScrollAccelRepr:
    """String representation."""

    def test_repr_initial(self) -> None:
        accel = ScrollAccel()
        r = repr(accel)
        assert "ScrollAccel" in r
        assert "off" in r  # accel is None → "off"

    def test_repr_after_scrolling(self) -> None:
        accel = ScrollAccel()
        for i in range(3):
            ev = MockScrollEvent(scroll=1, ticks=i * 10)
            accel.event(ev, list_top=1, list_index=3, list_visible=5, list_size=100)

        r = repr(accel)
        assert "ScrollAccel" in r
        assert "dir=1" in r

    def test_str_matches_repr(self) -> None:
        accel = ScrollAccel()
        assert str(accel) == repr(accel)
