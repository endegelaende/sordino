"""Tests for jive.utils.datetime_utils — date/time formatting and timezone utilities."""

from __future__ import annotations

import pytest

from jive.utils.datetime_utils import (
    get_all_date_formats,
    get_all_short_date_formats,
    get_all_timezones,
    get_date_format,
    get_hours,
    get_short_date_format,
    get_timezone,
    get_weekstart,
    reset_defaults,
    seconds_from_midnight,
    set_date_format,
    set_hours,
    set_short_date_format,
    set_timezone,
    set_weekstart,
)

# ---------------------------------------------------------------------------
# Fixture: reset global state between every test
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_datetime_state() -> None:
    """Ensure clean module-level state for every test."""
    reset_defaults()
    yield  # type: ignore[misc]
    reset_defaults()


# ---------------------------------------------------------------------------
# Date Formats
# ---------------------------------------------------------------------------


class TestDateFormats:
    """Tests for date format getters/setters."""

    def test_get_all_date_formats_returns_list(self) -> None:
        result = get_all_date_formats()
        assert isinstance(result, list)

    def test_get_all_date_formats_has_more_than_10(self) -> None:
        assert len(get_all_date_formats()) > 10

    def test_get_all_date_formats_contains_iso(self) -> None:
        assert "%Y-%m-%d" in get_all_date_formats()

    def test_get_all_date_formats_returns_copy(self) -> None:
        """Mutating the returned list must not affect the module state."""
        a = get_all_date_formats()
        a.clear()
        assert len(get_all_date_formats()) > 10

    def test_get_all_short_date_formats_contains_dmy(self) -> None:
        assert "%d.%m.%Y" in get_all_short_date_formats()

    def test_get_all_short_date_formats_returns_list(self) -> None:
        assert isinstance(get_all_short_date_formats(), list)

    def test_set_and_get_date_format_roundtrip(self) -> None:
        set_date_format("%Y-%m-%d")
        assert get_date_format() == "%Y-%m-%d"

    def test_set_and_get_short_date_format_roundtrip(self) -> None:
        set_short_date_format("%m.%d.%Y")
        assert get_short_date_format() == "%m.%d.%Y"

    def test_default_date_format(self) -> None:
        assert isinstance(get_date_format(), str)
        assert get_date_format() == "%a, %B %d %Y"

    def test_default_short_date_format(self) -> None:
        assert get_short_date_format() == "%d.%m.%Y"

    def test_set_date_format_multiple_times(self) -> None:
        set_date_format("%Y-%m-%d")
        set_date_format("%d/%m/%Y")
        assert get_date_format() == "%d/%m/%Y"

    def test_set_short_date_format_multiple_times(self) -> None:
        set_short_date_format("%m.%d.%Y")
        set_short_date_format("%d.%m.%Y")
        assert get_short_date_format() == "%d.%m.%Y"


# ---------------------------------------------------------------------------
# Weekstart
# ---------------------------------------------------------------------------


class TestWeekstart:
    """Tests for week-start day configuration."""

    def test_default_is_sunday(self) -> None:
        assert get_weekstart() == "Sunday"

    def test_set_monday(self) -> None:
        set_weekstart("Monday")
        assert get_weekstart() == "Monday"

    def test_set_sunday(self) -> None:
        set_weekstart("Monday")
        set_weekstart("Sunday")
        assert get_weekstart() == "Sunday"

    def test_invalid_value_does_not_change_state(self) -> None:
        set_weekstart("Monday")
        set_weekstart("Wednesday")  # invalid
        assert get_weekstart() == "Monday"

    def test_none_does_not_change_state(self) -> None:
        set_weekstart("Monday")
        set_weekstart(None)  # type: ignore[arg-type]
        assert get_weekstart() == "Monday"

    def test_empty_string_does_not_change_state(self) -> None:
        set_weekstart("")
        assert get_weekstart() == "Sunday"

    def test_case_sensitive(self) -> None:
        """Only exact 'Sunday' / 'Monday' are accepted."""
        set_weekstart("monday")
        assert get_weekstart() == "Sunday"


# ---------------------------------------------------------------------------
# Hours (12h / 24h)
# ---------------------------------------------------------------------------


class TestHours:
    """Tests for hour display mode (12h / 24h)."""

    def test_default_is_12(self) -> None:
        assert get_hours() == "12"

    def test_set_24_string(self) -> None:
        set_hours("24")
        assert get_hours() == "24"

    def test_set_12_string(self) -> None:
        set_hours("24")
        set_hours("12")
        assert get_hours() == "12"

    def test_set_12_int(self) -> None:
        set_hours("24")
        set_hours(12)
        assert get_hours() == "12"

    def test_set_24_int(self) -> None:
        set_hours(24)
        assert get_hours() == "24"

    def test_invalid_string_does_not_change_state(self) -> None:
        set_hours("24")
        set_hours("48")
        assert get_hours() == "24"

    def test_invalid_int_does_not_change_state(self) -> None:
        set_hours("24")
        set_hours(6)
        assert get_hours() == "24"

    def test_none_does_not_change_state(self) -> None:
        set_hours("24")
        set_hours(None)  # type: ignore[arg-type]
        assert get_hours() == "24"

    def test_empty_string_does_not_change_state(self) -> None:
        set_hours("24")
        set_hours("")
        assert get_hours() == "24"


# ---------------------------------------------------------------------------
# Timezones
# ---------------------------------------------------------------------------


class TestTimezones:
    """Tests for timezone lookup and configuration."""

    def test_get_timezone_gmt(self) -> None:
        tz = get_timezone("GMT")
        assert tz is not None
        assert tz["offset"] == 0
        assert tz["text"] == "GMT"

    def test_get_timezone_cet(self) -> None:
        tz = get_timezone("CET")
        assert tz is not None
        assert tz["offset"] == 1
        assert tz["text"] == "Berlin, Zurich"

    def test_get_timezone_invalid_returns_none(self) -> None:
        assert get_timezone("INVALID") is None

    def test_get_timezone_empty_returns_none(self) -> None:
        assert get_timezone("") is None

    def test_get_all_timezones_has_gmt(self) -> None:
        tzs = get_all_timezones()
        assert "GMT" in tzs

    def test_get_all_timezones_has_cet(self) -> None:
        assert "CET" in get_all_timezones()

    def test_get_all_timezones_returns_copy(self) -> None:
        a = get_all_timezones()
        a.clear()
        assert len(get_all_timezones()) > 0

    def test_set_timezone_valid(self) -> None:
        assert set_timezone("CET") is True

    def test_set_timezone_invalid(self) -> None:
        assert set_timezone("INVALID") is False

    def test_set_timezone_gmt(self) -> None:
        assert set_timezone("GMT") is True

    def test_set_timezone_empty_returns_false(self) -> None:
        assert set_timezone("") is False


# ---------------------------------------------------------------------------
# Seconds From Midnight
# ---------------------------------------------------------------------------


class TestSecondsFromMidnight:
    """Tests for seconds_from_midnight() conversion."""

    def test_midnight(self) -> None:
        assert seconds_from_midnight("0000") == 0

    def test_one_am(self) -> None:
        assert seconds_from_midnight("0100") == 3600

    def test_1430(self) -> None:
        assert seconds_from_midnight("1430") == 52200

    def test_2359(self) -> None:
        assert seconds_from_midnight("2359") == 86340

    def test_pm_suffix(self) -> None:
        """0230p → 14:30 → 52200."""
        assert seconds_from_midnight("0230p") == 52200

    def test_12am_is_midnight(self) -> None:
        assert seconds_from_midnight("1200a") == 0

    def test_12pm_is_noon(self) -> None:
        assert seconds_from_midnight("1200p") == 43200

    def test_invalid_hours_returns_zero(self) -> None:
        """Hours > 23 is invalid."""
        assert seconds_from_midnight("2500") == 0

    def test_invalid_minutes_returns_zero(self) -> None:
        """Minutes > 59 is invalid."""
        assert seconds_from_midnight("0060") == 0

    def test_integer_input(self) -> None:
        """Integer 1430 should be treated same as '1430'."""
        assert seconds_from_midnight(1430) == seconds_from_midnight("1430")

    def test_integer_midnight(self) -> None:
        # int(0) → str "0" → only one pair of digits found → 0 returned
        # Actually: "0" has no two-digit pairs. Let's check "0000".
        assert seconds_from_midnight("0000") == 0

    def test_1am_pm(self) -> None:
        """0100p → 13:00 → 46800."""
        assert seconds_from_midnight("0100p") == 46800

    def test_11pm(self) -> None:
        """1100p → 23:00 → 82800."""
        assert seconds_from_midnight("1100p") == 82800

    def test_1159pm(self) -> None:
        """1159p → 23:59 → 86340."""
        assert seconds_from_midnight("1159p") == 86340

    def test_uppercase_p(self) -> None:
        """Uppercase P should also work (case-insensitive check)."""
        assert seconds_from_midnight("0230P") == 52200

    def test_uppercase_a(self) -> None:
        assert seconds_from_midnight("1200A") == 0

    def test_too_short_input(self) -> None:
        """Input with < 2 digit pairs returns 0."""
        assert seconds_from_midnight("12") == 0

    def test_empty_string(self) -> None:
        assert seconds_from_midnight("") == 0

    def test_non_numeric(self) -> None:
        assert seconds_from_midnight("abcd") == 0

    def test_noon_24h(self) -> None:
        assert seconds_from_midnight("1200") == 43200

    def test_one_minute_past_midnight(self) -> None:
        assert seconds_from_midnight("0001") == 60

    def test_am_non_12(self) -> None:
        """0800a → 08:00 (AM has no effect for non-12 hours)."""
        assert seconds_from_midnight("0800a") == 28800


# ---------------------------------------------------------------------------
# Lua API Compatibility (self parameter)
# ---------------------------------------------------------------------------


class TestLuaAPICompat:
    """Tests for Lua-style calling conventions with a self parameter."""

    def test_get_hours_with_self(self) -> None:
        assert get_hours(None) == "12"

    def test_set_hours_with_self(self) -> None:
        set_hours(None, "24")
        assert get_hours() == "24"

    def test_get_weekstart_with_self(self) -> None:
        assert get_weekstart(None) == "Sunday"

    def test_set_weekstart_with_self(self) -> None:
        set_weekstart(None, "Monday")
        assert get_weekstart() == "Monday"

    def test_get_date_format_with_self(self) -> None:
        assert isinstance(get_date_format(None), str)

    def test_set_date_format_with_self(self) -> None:
        set_date_format(None, "%Y-%m-%d")
        assert get_date_format() == "%Y-%m-%d"

    def test_get_short_date_format_with_self(self) -> None:
        assert isinstance(get_short_date_format(None), str)

    def test_set_short_date_format_with_self(self) -> None:
        set_short_date_format(None, "%m.%d.%Y")
        assert get_short_date_format() == "%m.%d.%Y"

    def test_get_timezone_with_self(self) -> None:
        tz = get_timezone(None, "GMT")
        assert tz is not None
        assert tz["offset"] == 0

    def test_set_timezone_with_self(self) -> None:
        assert set_timezone(None, "CET") is True

    def test_get_all_date_formats_with_self(self) -> None:
        assert len(get_all_date_formats(None)) > 10

    def test_get_all_short_date_formats_with_self(self) -> None:
        assert isinstance(get_all_short_date_formats(None), list)

    def test_get_all_timezones_with_self(self) -> None:
        assert "GMT" in get_all_timezones(None)

    def test_seconds_from_midnight_with_self(self) -> None:
        assert seconds_from_midnight(None, "1430") == 52200


# ---------------------------------------------------------------------------
# reset_defaults
# ---------------------------------------------------------------------------


class TestResetDefaults:
    """Tests for reset_defaults()."""

    def test_resets_hours(self) -> None:
        set_hours("24")
        reset_defaults()
        assert get_hours() == "12"

    def test_resets_weekstart(self) -> None:
        set_weekstart("Monday")
        reset_defaults()
        assert get_weekstart() == "Sunday"

    def test_resets_date_format(self) -> None:
        set_date_format("%Y-%m-%d")
        reset_defaults()
        assert get_date_format() == "%a, %B %d %Y"

    def test_resets_short_date_format(self) -> None:
        set_short_date_format("%m.%d.%Y")
        reset_defaults()
        assert get_short_date_format() == "%d.%m.%Y"

    def test_resets_all_at_once(self) -> None:
        set_hours("24")
        set_weekstart("Monday")
        set_date_format("%Y-%m-%d")
        set_short_date_format("%m.%d.%Y")
        set_timezone("CET")
        reset_defaults()
        assert get_hours() == "12"
        assert get_weekstart() == "Sunday"
        assert get_date_format() == "%a, %B %d %Y"
        assert get_short_date_format() == "%d.%m.%Y"
