"""Tests for jive.ui.timer — interval-based callback timer."""

from __future__ import annotations

from typing import List
from unittest.mock import MagicMock

import pytest

from jive.ui.timer import Timer


@pytest.fixture(autouse=True)
def clean_timer_queue():
    """Isolate every test from class-level timer state."""
    Timer.clear_all()
    yield
    Timer.clear_all()


# =========================================================================
# Construction
# =========================================================================


class TestTimerConstruction:
    """Timer.__init__ validation."""

    def test_basic_construction(self) -> None:
        t = Timer(1000, lambda: None)
        assert t.interval == 1000
        assert t.once is False
        assert t.is_running() is False

    def test_once_flag(self) -> None:
        t = Timer(500, lambda: None, once=True)
        assert t.once is True

    def test_float_interval_is_truncated(self) -> None:
        t = Timer(1500.9, lambda: None)  # type: ignore[arg-type]
        assert t.interval == 1500

    def test_rejects_non_numeric_interval(self) -> None:
        with pytest.raises(TypeError, match="interval must be a number"):
            Timer("fast", lambda: None)  # type: ignore[arg-type]

    def test_rejects_non_callable_callback(self) -> None:
        with pytest.raises(TypeError, match="callback must be callable"):
            Timer(100, 42)  # type: ignore[arg-type]

    def test_zero_interval_is_valid(self) -> None:
        t = Timer(0, lambda: None)
        assert t.interval == 0

    def test_negative_interval_is_accepted(self) -> None:
        # No validation in constructor — fires immediately
        t = Timer(-10, lambda: None)
        assert t.interval == -10


# =========================================================================
# Start / Stop / is_running
# =========================================================================


class TestStartStop:
    """Timer.start, .stop, .is_running lifecycle."""

    def test_start_makes_running(self) -> None:
        t = Timer(1000, lambda: None)
        t.start()
        assert t.is_running() is True
        assert t.expires is not None

    def test_stop_makes_not_running(self) -> None:
        t = Timer(1000, lambda: None)
        t.start()
        t.stop()
        assert t.is_running() is False
        assert t.expires is None

    def test_stop_when_not_running_is_safe(self) -> None:
        t = Timer(1000, lambda: None)
        t.stop()  # should not raise
        assert t.is_running() is False

    def test_double_start_does_not_duplicate(self) -> None:
        t = Timer(1000, lambda: None)
        t.start()
        t.start()
        assert Timer.pending_count() == 1

    def test_start_adds_to_queue(self) -> None:
        assert Timer.pending_count() == 0
        t = Timer(100, lambda: None)
        t.start()
        assert Timer.pending_count() == 1

    def test_stop_removes_from_queue(self) -> None:
        t = Timer(100, lambda: None)
        t.start()
        t.stop()
        assert Timer.pending_count() == 0


# =========================================================================
# run_timers — one-shot
# =========================================================================


class TestOneShotTimer:
    """One-shot timers fire once then stop."""

    def test_fires_once(self) -> None:
        cb = MagicMock()
        t = Timer(100, cb, once=True)
        t.start()

        # Advance past expiry
        expires = t.expires
        assert expires is not None
        Timer.run_timers(expires + 1)

        cb.assert_called_once()
        assert t.is_running() is False

    def test_does_not_fire_before_expiry(self) -> None:
        cb = MagicMock()
        t = Timer(100, cb, once=True)
        t.start()

        expires = t.expires
        assert expires is not None
        Timer.run_timers(expires - 1)

        cb.assert_not_called()
        assert t.is_running() is True

    def test_fires_exactly_at_expiry(self) -> None:
        cb = MagicMock()
        t = Timer(100, cb, once=True)
        t.start()

        expires = t.expires
        assert expires is not None
        Timer.run_timers(expires)

        cb.assert_called_once()

    def test_removed_from_queue_after_fire(self) -> None:
        t = Timer(100, lambda: None, once=True)
        t.start()
        assert Timer.pending_count() == 1

        Timer.run_timers(t.expires)  # type: ignore[arg-type]
        assert Timer.pending_count() == 0


# =========================================================================
# run_timers — repeating
# =========================================================================


class TestRepeatingTimer:
    """Repeating timers re-insert themselves after firing."""

    def test_fires_multiple_times(self) -> None:
        cb = MagicMock()
        t = Timer(100, cb)
        t.start()

        first_expiry = t.expires
        assert first_expiry is not None

        Timer.run_timers(first_expiry)
        assert cb.call_count == 1
        assert t.is_running() is True

        # Should be rescheduled for first_expiry + 100
        Timer.run_timers(first_expiry + 100)
        assert cb.call_count == 2
        assert t.is_running() is True

    def test_stays_in_queue_after_fire(self) -> None:
        t = Timer(100, lambda: None)
        t.start()
        Timer.run_timers(t.expires)  # type: ignore[arg-type]
        assert Timer.pending_count() == 1
        assert t.is_running() is True

    def test_catch_up_when_behind(self) -> None:
        """If a repeating timer falls behind, it jumps ahead instead of burst-firing."""
        call_count = 0

        def inc() -> None:
            nonlocal call_count
            call_count += 1

        t = Timer(100, inc)
        t.start()

        first_expiry = t.expires
        assert first_expiry is not None

        # Advance far past several intervals — should fire once, not burst
        Timer.run_timers(first_expiry + 5000)
        assert call_count == 1

        # Next expiry should be way in the future (now + interval), not stacked
        assert t.expires is not None
        assert t.expires > first_expiry + 5000


# =========================================================================
# restart / set_interval
# =========================================================================


class TestRestartAndSetInterval:
    """Timer.restart and Timer.set_interval."""

    def test_restart_resets_expiry(self) -> None:
        t = Timer(100, lambda: None)
        t.start()
        first_expiry = t.expires

        t.restart()
        assert t.is_running() is True
        assert t.expires is not None
        assert t.expires >= first_expiry  # type: ignore[operator]

    def test_restart_with_new_interval(self) -> None:
        t = Timer(100, lambda: None)
        t.start()
        t.restart(interval=500)
        assert t.interval == 500
        assert t.is_running() is True

    def test_restart_not_running_starts_it(self) -> None:
        t = Timer(100, lambda: None)
        t.restart()
        assert t.is_running() is True

    def test_set_interval_when_stopped(self) -> None:
        t = Timer(100, lambda: None)
        t.set_interval(500)
        assert t.interval == 500
        assert t.is_running() is False

    def test_set_interval_when_running_restarts(self) -> None:
        t = Timer(100, lambda: None)
        t.start()
        old_expiry = t.expires
        t.set_interval(500)
        assert t.interval == 500
        assert t.is_running() is True
        # New expiry should be further out
        assert t.expires is not None
        assert t.expires >= old_expiry  # type: ignore[operator]

    def test_restart_does_not_duplicate_in_queue(self) -> None:
        t = Timer(100, lambda: None)
        t.start()
        t.restart()
        t.restart()
        assert Timer.pending_count() == 1


# =========================================================================
# clear_all / pending_count
# =========================================================================


class TestClearAllAndPendingCount:
    """Timer.clear_all and Timer.pending_count class methods."""

    def test_clear_all_empties_queue(self) -> None:
        Timer(100, lambda: None).start()
        Timer(200, lambda: None).start()
        Timer(300, lambda: None).start()
        assert Timer.pending_count() == 3
        Timer.clear_all()
        assert Timer.pending_count() == 0

    def test_clear_all_marks_timers_stopped(self) -> None:
        t1 = Timer(100, lambda: None)
        t2 = Timer(200, lambda: None)
        t1.start()
        t2.start()
        Timer.clear_all()
        assert t1.is_running() is False
        assert t2.is_running() is False

    def test_pending_count_empty(self) -> None:
        assert Timer.pending_count() == 0

    def test_clear_all_on_empty_is_safe(self) -> None:
        Timer.clear_all()  # should not raise


# =========================================================================
# Ordering — multiple timers fire in expiry order
# =========================================================================


class TestTimerOrdering:
    """Multiple timers should fire in order of expiry."""

    def test_fifo_order(self) -> None:
        order: List[str] = []

        t1 = Timer(100, lambda: order.append("A"), once=True)
        t2 = Timer(200, lambda: order.append("B"), once=True)
        t3 = Timer(300, lambda: order.append("C"), once=True)

        t1.start()
        t2.start()
        t3.start()

        # Grab all expiries so we can run past all of them
        max_expiry = max(t.expires for t in [t1, t2, t3] if t.expires is not None)
        Timer.run_timers(max_expiry + 1)

        assert order == ["A", "B", "C"]

    def test_reverse_insertion_still_fires_in_order(self) -> None:
        order: List[str] = []

        t1 = Timer(300, lambda: order.append("A"), once=True)
        t2 = Timer(200, lambda: order.append("B"), once=True)
        t3 = Timer(100, lambda: order.append("C"), once=True)

        t1.start()
        t2.start()
        t3.start()

        max_expiry = max(t.expires for t in [t1, t2, t3] if t.expires is not None)
        Timer.run_timers(max_expiry + 1)

        assert order == ["C", "B", "A"]

    def test_equal_interval_fires_in_insertion_order(self) -> None:
        order: List[str] = []

        t1 = Timer(100, lambda: order.append("first"), once=True)
        t2 = Timer(100, lambda: order.append("second"), once=True)
        t3 = Timer(100, lambda: order.append("third"), once=True)

        t1.start()
        t2.start()
        t3.start()

        max_expiry = max(t.expires for t in [t1, t2, t3] if t.expires is not None)
        Timer.run_timers(max_expiry + 1)

        assert order == ["first", "second", "third"]


# =========================================================================
# Callback error handling
# =========================================================================


class TestCallbackErrors:
    """Errors in callbacks must not kill the timer queue."""

    def test_error_in_callback_does_not_stop_other_timers(self) -> None:
        order: List[str] = []

        def bad() -> None:
            raise RuntimeError("boom")

        t1 = Timer(100, bad, once=True)
        t2 = Timer(200, lambda: order.append("ok"), once=True)

        t1.start()
        t2.start()

        max_expiry = max(t.expires for t in [t1, t2] if t.expires is not None)
        Timer.run_timers(max_expiry + 1)

        assert order == ["ok"]

    def test_error_in_repeating_callback_keeps_timer_alive(self) -> None:
        call_count = 0

        def flaky() -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ValueError("first call fails")

        t = Timer(100, flaky)
        t.start()

        first_expiry = t.expires
        assert first_expiry is not None

        Timer.run_timers(first_expiry)
        assert call_count == 1
        assert t.is_running() is True

        # Second fire should work
        Timer.run_timers(first_expiry + 100)
        assert call_count == 2


# =========================================================================
# Callback modifies timer
# =========================================================================


class TestCallbackModifiesTimer:
    """Callbacks that stop or restart the timer they belong to."""

    def test_callback_stops_own_repeating_timer(self) -> None:
        call_count = 0
        t: Timer

        def stop_self() -> None:
            nonlocal call_count
            call_count += 1
            t.stop()

        t = Timer(100, stop_self)
        t.start()

        Timer.run_timers(t.expires)  # type: ignore[arg-type]
        assert call_count == 1
        assert t.is_running() is False
        assert Timer.pending_count() == 0

    def test_callback_restarts_with_different_interval(self) -> None:
        t: Timer

        def change_interval() -> None:
            t.restart(interval=999)

        t = Timer(100, change_interval, once=True)
        t.start()

        Timer.run_timers(t.expires)  # type: ignore[arg-type]
        assert t.interval == 999
        assert t.is_running() is True


# =========================================================================
# Repr
# =========================================================================


class TestTimerRepr:
    """Timer.__repr__ output."""

    def test_stopped_repr(self) -> None:
        t = Timer(1000, lambda: None, once=True)
        r = repr(t)
        assert "interval=1000" in r
        assert "once=True" in r
        assert "stopped" in r

    def test_running_repr(self) -> None:
        t = Timer(500, lambda: None)
        t.start()
        r = repr(t)
        assert "interval=500" in r
        assert "running" in r
        assert "expires=" in r


# =========================================================================
# Edge cases
# =========================================================================


class TestEdgeCases:
    """Miscellaneous edge cases."""

    def test_run_timers_with_empty_queue(self) -> None:
        Timer.run_timers(999999)  # should not raise

    def test_run_timers_none_uses_current_ticks(self) -> None:
        # Just verifying it doesn't crash
        Timer.run_timers(None)

    def test_start_stop_start(self) -> None:
        cb = MagicMock()
        t = Timer(100, cb, once=True)
        t.start()
        t.stop()
        t.start()

        assert Timer.pending_count() == 1
        Timer.run_timers(t.expires)  # type: ignore[arg-type]
        cb.assert_called_once()

    def test_many_timers(self) -> None:
        """Stress test with many timers."""
        count = 0

        def inc() -> None:
            nonlocal count
            count += 1

        timers = [Timer(i * 10, inc, once=True) for i in range(1, 51)]
        for t in timers:
            t.start()

        assert Timer.pending_count() == 50

        max_expiry = max(t.expires for t in timers if t.expires is not None)
        Timer.run_timers(max_expiry + 1)

        assert count == 50
        assert Timer.pending_count() == 0

    def test_zero_interval_repeating_stops_from_callback(self) -> None:
        """A zero-interval repeating timer will re-fire on the same tick.
        Verify it can be stopped from its own callback without hanging."""
        call_count = 0
        t: Timer

        def stop_after_3() -> None:
            nonlocal call_count
            call_count += 1
            if call_count >= 3:
                t.stop()

        t = Timer(0, stop_after_3)
        t.start()

        Timer.run_timers(t.expires)  # type: ignore[arg-type]
        assert call_count == 3
        assert t.is_running() is False
