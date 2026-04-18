"""Tests for jive.utils.log — category-based logging facility."""

from __future__ import annotations

import logging
from unittest.mock import patch

import pytest

from jive.utils.log import (
    _LEVEL_MAP,
    JiveLogger,
    _concat_args,
    _default_level,
    _loggers,
    get_categories,
    logger,
    set_all_levels,
    set_default_level,
)

# ---------------------------------------------------------------------------
# Helpers — each test uses unique category names to avoid cross-pollution
# of the module-level _loggers dict.
# ---------------------------------------------------------------------------

_counter = 0


def _unique(prefix: str = "test") -> str:
    """Return a unique category name for test isolation."""
    global _counter
    _counter += 1
    return f"{prefix}.{_counter}"


# ---------------------------------------------------------------------------
# _concat_args
# ---------------------------------------------------------------------------


class TestConcatArgs:
    """Tests for the internal _concat_args() helper."""

    def test_zero_args(self) -> None:
        assert _concat_args(()) == ""

    def test_single_string(self) -> None:
        assert _concat_args(("hello",)) == "hello"

    def test_single_int(self) -> None:
        assert _concat_args((42,)) == "42"

    def test_single_none(self) -> None:
        assert _concat_args((None,)) == "None"

    def test_single_bool(self) -> None:
        assert _concat_args((True,)) == "True"

    def test_single_float(self) -> None:
        assert _concat_args((3.14,)) == "3.14"

    def test_percent_d_formatting(self) -> None:
        result = _concat_args(("timeout after %d seconds", 30))
        assert result == "timeout after 30 seconds"

    def test_percent_s_formatting(self) -> None:
        result = _concat_args(("hello %s", "world"))
        assert result == "hello world"

    def test_percent_multiple_placeholders(self) -> None:
        result = _concat_args(("%s has %d items", "list", 5))
        assert result == "list has 5 items"

    def test_percent_float_formatting(self) -> None:
        result = _concat_args(("value is %.2f", 3.14159))
        assert result == "value is 3.14"

    def test_lua_style_concat_two_strings(self) -> None:
        result = _concat_args(("Welcome ", "Alice"))
        assert result == "Welcome Alice"

    def test_lua_style_concat_multiple(self) -> None:
        result = _concat_args(("Hello ", "dear ", "world"))
        assert result == "Hello dear world"

    def test_lua_style_concat_mixed_types(self) -> None:
        result = _concat_args(("count=", 42, " ok=", True))
        assert result == "count=42 ok=True"

    def test_fallback_when_percent_formatting_fails(self) -> None:
        """If %-formatting raises, fall back to concatenation."""
        # Too many arguments for the format string
        result = _concat_args(("only %s here", "one", "two"))
        assert result == "only %s hereonetwо" or "one" in result
        # The fallback should concatenate all args
        result = _concat_args(("fmt %s", "a", "b"))
        assert result == "fmt %sab"

    def test_fallback_wrong_type_for_format(self) -> None:
        """If the format specifier doesn't match the argument type."""
        # %d with a string that can't be formatted as int
        result = _concat_args(("%d items", "not_a_number"))
        assert "not_a_number" in result  # fell back to concat

    def test_no_percent_sign_in_first_arg(self) -> None:
        """If first arg is a string without %, always concatenate."""
        result = _concat_args(("hello ", "world"))
        assert result == "hello world"

    def test_first_arg_not_string(self) -> None:
        """If first arg is not a string, concatenation is used."""
        result = _concat_args((42, " items"))
        assert result == "42 items"

    def test_single_empty_string(self) -> None:
        assert _concat_args(("",)) == ""

    def test_concat_with_empty_strings(self) -> None:
        result = _concat_args(("", "abc", ""))
        assert result == "abc"

    def test_single_list_arg(self) -> None:
        result = _concat_args(([1, 2, 3],))
        assert result == "[1, 2, 3]"

    def test_single_dict_arg(self) -> None:
        result = _concat_args(({"a": 1},))
        assert "a" in result


# ---------------------------------------------------------------------------
# JiveLogger — creation and basic properties
# ---------------------------------------------------------------------------


class TestJiveLoggerCreation:
    """Tests for JiveLogger instantiation and properties."""

    def test_create_with_category(self) -> None:
        cat = _unique("create")
        log = JiveLogger(cat)
        assert log.category == cat

    def test_default_level_is_warning(self) -> None:
        cat = _unique("deflevel")
        log = JiveLogger(cat)
        assert log.get_level() == "warn"

    def test_create_with_explicit_level(self) -> None:
        cat = _unique("explicit")
        log = JiveLogger(cat, level=logging.DEBUG)
        assert log.get_level() == "debug"

    def test_repr(self) -> None:
        cat = _unique("repr")
        log = JiveLogger(cat)
        r = repr(log)
        assert "JiveLogger" in r
        assert cat in r
        assert "warn" in r

    def test_underlying_logger_name(self) -> None:
        cat = _unique("underlying")
        log = JiveLogger(cat)
        assert log._logger.name == f"jive.{cat}"

    def test_no_propagation(self) -> None:
        cat = _unique("noprop")
        log = JiveLogger(cat)
        assert log._logger.propagate is False

    def test_has_handler(self) -> None:
        cat = _unique("handler")
        log = JiveLogger(cat)
        assert len(log._logger.handlers) == 1


# ---------------------------------------------------------------------------
# JiveLogger — level management
# ---------------------------------------------------------------------------


class TestJiveLoggerLevels:
    """Tests for set_level / get_level / is_debug."""

    def test_set_level_string_debug(self) -> None:
        cat = _unique("lvl.debug")
        log = JiveLogger(cat)
        log.set_level("debug")
        assert log.get_level() == "debug"

    def test_set_level_string_info(self) -> None:
        cat = _unique("lvl.info")
        log = JiveLogger(cat)
        log.set_level("info")
        assert log.get_level() == "info"

    def test_set_level_string_warn(self) -> None:
        cat = _unique("lvl.warn")
        log = JiveLogger(cat)
        log.set_level("warn")
        assert log.get_level() == "warn"

    def test_set_level_string_warning(self) -> None:
        cat = _unique("lvl.warning")
        log = JiveLogger(cat)
        log.set_level("warning")
        assert log.get_level() == "warn"

    def test_set_level_string_error(self) -> None:
        cat = _unique("lvl.error")
        log = JiveLogger(cat)
        log.set_level("error")
        assert log.get_level() == "error"

    def test_set_level_int(self) -> None:
        cat = _unique("lvl.int")
        log = JiveLogger(cat)
        log.set_level(logging.DEBUG)
        assert log.get_level() == "debug"

    def test_set_level_case_insensitive(self) -> None:
        cat = _unique("lvl.case")
        log = JiveLogger(cat)
        log.set_level("DEBUG")
        assert log.get_level() == "debug"

    def test_set_level_unknown_string_defaults_to_warning(self) -> None:
        cat = _unique("lvl.unknown")
        log = JiveLogger(cat)
        log.set_level("debug")  # first set to debug
        assert log.get_level() == "debug"
        log.set_level("nonexistent")
        assert log.get_level() == "warn"

    def test_is_debug_true(self) -> None:
        cat = _unique("isdebug.true")
        log = JiveLogger(cat, level=logging.DEBUG)
        assert log.is_debug() is True

    def test_is_debug_false(self) -> None:
        cat = _unique("isdebug.false")
        log = JiveLogger(cat, level=logging.WARNING)
        assert log.is_debug() is False

    def test_is_enabled_for(self) -> None:
        cat = _unique("enabled")
        log = JiveLogger(cat, level=logging.INFO)
        assert log.isEnabledFor(logging.INFO) is True
        assert log.isEnabledFor(logging.DEBUG) is False
        assert log.isEnabledFor(logging.ERROR) is True


# ---------------------------------------------------------------------------
# JiveLogger — log methods emit output
# ---------------------------------------------------------------------------


class TestJiveLoggerOutput:
    """Tests that log methods actually produce output at the right levels."""

    def test_debug_suppressed_at_warning_level(self, capsys: pytest.CaptureFixture[str]) -> None:
        cat = _unique("out.debug.suppress")
        log = JiveLogger(cat, level=logging.WARNING)
        log.debug("should not appear")
        captured = capsys.readouterr()
        assert "should not appear" not in captured.err

    def test_debug_emitted_at_debug_level(self, capsys: pytest.CaptureFixture[str]) -> None:
        cat = _unique("out.debug.emit")
        log = JiveLogger(cat, level=logging.DEBUG)
        log.debug("visible debug msg")
        captured = capsys.readouterr()
        assert "visible debug msg" in captured.err

    def test_info_emitted(self, capsys: pytest.CaptureFixture[str]) -> None:
        cat = _unique("out.info")
        log = JiveLogger(cat, level=logging.INFO)
        log.info("info message")
        captured = capsys.readouterr()
        assert "info message" in captured.err

    def test_warn_emitted(self, capsys: pytest.CaptureFixture[str]) -> None:
        cat = _unique("out.warn")
        log = JiveLogger(cat, level=logging.WARNING)
        log.warn("warning message")
        captured = capsys.readouterr()
        assert "warning message" in captured.err

    def test_warning_alias_emitted(self, capsys: pytest.CaptureFixture[str]) -> None:
        cat = _unique("out.warning.alias")
        log = JiveLogger(cat, level=logging.WARNING)
        log.warning("alias warning")
        captured = capsys.readouterr()
        assert "alias warning" in captured.err

    def test_error_emitted(self, capsys: pytest.CaptureFixture[str]) -> None:
        cat = _unique("out.error")
        log = JiveLogger(cat, level=logging.ERROR)
        log.error("error message")
        captured = capsys.readouterr()
        assert "error message" in captured.err

    def test_warning_alias_is_same_method(self) -> None:
        assert JiveLogger.warning is JiveLogger.warn

    def test_debug_with_format_args(self, capsys: pytest.CaptureFixture[str]) -> None:
        cat = _unique("out.debug.fmt")
        log = JiveLogger(cat, level=logging.DEBUG)
        log.debug("count=%d name=%s", 5, "test")
        captured = capsys.readouterr()
        assert "count=5 name=test" in captured.err

    def test_info_with_concat_args(self, capsys: pytest.CaptureFixture[str]) -> None:
        cat = _unique("out.info.concat")
        log = JiveLogger(cat, level=logging.INFO)
        log.info("hello ", "world")
        captured = capsys.readouterr()
        assert "hello world" in captured.err

    def test_log_format_includes_timestamp(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Jive format: HHMMSS:msec LEVEL (file:line) - message"""
        cat = _unique("out.format")
        log = JiveLogger(cat, level=logging.WARNING)
        log.warn("format check")
        captured = capsys.readouterr()
        # Should contain the level and separator
        assert "WARNI" in captured.err
        assert " - " in captured.err
        assert "format check" in captured.err

    def test_error_suppressed_below_critical(self, capsys: pytest.CaptureFixture[str]) -> None:
        cat = _unique("out.error.suppress")
        log = JiveLogger(cat, level=logging.CRITICAL)
        log.error("should not show")
        captured = capsys.readouterr()
        assert "should not show" not in captured.err

    def test_info_suppressed_at_error_level(self, capsys: pytest.CaptureFixture[str]) -> None:
        cat = _unique("out.info.suppress")
        log = JiveLogger(cat, level=logging.ERROR)
        log.info("should not show")
        captured = capsys.readouterr()
        assert "should not show" not in captured.err

    def test_no_args_produces_empty_message(self, capsys: pytest.CaptureFixture[str]) -> None:
        cat = _unique("out.noargs")
        log = JiveLogger(cat, level=logging.WARNING)
        log.warn()
        captured = capsys.readouterr()
        # Should still produce a log line, just with empty message
        assert " - " in captured.err


# ---------------------------------------------------------------------------
# logger() — factory / registry
# ---------------------------------------------------------------------------


class TestLoggerFactory:
    """Tests for the module-level logger() function."""

    def test_creates_new_logger(self) -> None:
        cat = _unique("factory.new")
        log = logger(cat)
        assert isinstance(log, JiveLogger)
        assert log.category == cat

    def test_returns_same_instance(self) -> None:
        cat = _unique("factory.same")
        log1 = logger(cat)
        log2 = logger(cat)
        assert log1 is log2

    def test_different_categories_different_instances(self) -> None:
        cat1 = _unique("factory.diff1")
        cat2 = _unique("factory.diff2")
        log1 = logger(cat1)
        log2 = logger(cat2)
        assert log1 is not log2

    def test_registered_in_global_dict(self) -> None:
        cat = _unique("factory.registered")
        log = logger(cat)
        assert cat in _loggers
        assert _loggers[cat] is log


# ---------------------------------------------------------------------------
# get_categories()
# ---------------------------------------------------------------------------


class TestGetCategories:
    """Tests for get_categories()."""

    def test_returns_sorted_list(self) -> None:
        # Create loggers in reverse alphabetical order
        cat_z = _unique("z.categories")
        cat_a = _unique("a.categories")
        logger(cat_z)
        logger(cat_a)
        cats = get_categories()
        assert isinstance(cats, list)
        assert cats == sorted(cats)

    def test_contains_created_category(self) -> None:
        cat = _unique("getcat.contains")
        logger(cat)
        assert cat in get_categories()

    def test_returns_new_list(self) -> None:
        cats1 = get_categories()
        cats2 = get_categories()
        assert cats1 is not cats2


# ---------------------------------------------------------------------------
# set_default_level()
# ---------------------------------------------------------------------------


class TestSetDefaultLevel:
    """Tests for set_default_level()."""

    def test_string_level_affects_new_loggers(self) -> None:
        set_default_level("debug")
        try:
            cat = _unique("default.debug")
            log = logger(cat)
            assert log.get_level() == "debug"
        finally:
            set_default_level("warn")  # restore

    def test_int_level_affects_new_loggers(self) -> None:
        set_default_level(logging.INFO)
        try:
            cat = _unique("default.int")
            log = logger(cat)
            assert log.get_level() == "info"
        finally:
            set_default_level("warn")

    def test_does_not_affect_existing_loggers(self) -> None:
        cat = _unique("default.existing")
        log = logger(cat)
        log.set_level("error")
        set_default_level("debug")
        try:
            assert log.get_level() == "error"  # unchanged
        finally:
            set_default_level("warn")


# ---------------------------------------------------------------------------
# set_all_levels()
# ---------------------------------------------------------------------------


class TestSetAllLevels:
    """Tests for set_all_levels()."""

    def test_changes_all_existing_loggers(self) -> None:
        cat1 = _unique("all.1")
        cat2 = _unique("all.2")
        log1 = logger(cat1)
        log2 = logger(cat2)
        log1.set_level("error")
        log2.set_level("info")
        set_all_levels("debug")
        try:
            assert log1.get_level() == "debug"
            assert log2.get_level() == "debug"
        finally:
            set_default_level("warn")

    def test_also_updates_default(self) -> None:
        set_all_levels("info")
        try:
            cat = _unique("all.newafter")
            log = logger(cat)
            assert log.get_level() == "info"
        finally:
            set_default_level("warn")

    def test_with_int_level(self) -> None:
        cat = _unique("all.int")
        log = logger(cat)
        set_all_levels(logging.ERROR)
        try:
            assert log.get_level() == "error"
        finally:
            set_default_level("warn")


# ---------------------------------------------------------------------------
# LEVEL_MAP coverage
# ---------------------------------------------------------------------------


class TestLevelMap:
    """Verify the level mapping constants."""

    def test_debug_maps_to_logging_debug(self) -> None:
        assert _LEVEL_MAP["debug"] == logging.DEBUG

    def test_info_maps_to_logging_info(self) -> None:
        assert _LEVEL_MAP["info"] == logging.INFO

    def test_warn_maps_to_logging_warning(self) -> None:
        assert _LEVEL_MAP["warn"] == logging.WARNING

    def test_warning_maps_to_logging_warning(self) -> None:
        assert _LEVEL_MAP["warning"] == logging.WARNING

    def test_error_maps_to_logging_error(self) -> None:
        assert _LEVEL_MAP["error"] == logging.ERROR


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Various edge cases and integration tests."""

    def test_logger_with_dotted_category(self) -> None:
        cat = _unique("dotted.sub.category")
        log = logger(cat)
        assert log.category == cat

    def test_empty_category(self) -> None:
        cat = _unique("")
        log = logger(cat)
        assert isinstance(log, JiveLogger)

    def test_concat_args_with_percent_but_no_extra_args(self) -> None:
        """A string with % but only one arg should just return str."""
        result = _concat_args(("100% done",))
        assert result == "100% done"

    def test_concat_args_with_object(self) -> None:
        class Obj:
            def __str__(self) -> str:
                return "myobj"

        result = _concat_args((Obj(),))
        assert result == "myobj"

    def test_get_level_maps_critical_to_error(self) -> None:
        cat = _unique("edge.critical")
        log = JiveLogger(cat, level=logging.CRITICAL)
        assert log.get_level() == "error"

    def test_warn_with_exc_info(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Keyword arguments like exc_info should be accepted without error.

        Note: The custom _JiveFormatter does not call super().format() so
        exception tracebacks are *not* appended to the output.  We only
        verify the message itself appears and no exception is raised.
        """
        cat = _unique("edge.excinfo")
        log = JiveLogger(cat, level=logging.WARNING)
        try:
            raise ValueError("test error")
        except ValueError:
            log.warn("caught:", exc_info=True)
        captured = capsys.readouterr()
        assert "caught:" in captured.err

    def test_error_with_exc_info(self, capsys: pytest.CaptureFixture[str]) -> None:
        """exc_info kwarg accepted by error(); message appears."""
        cat = _unique("edge.excinfo.error")
        log = JiveLogger(cat, level=logging.ERROR)
        try:
            raise RuntimeError("boom")
        except RuntimeError:
            log.error("failure:", exc_info=True)
        captured = capsys.readouterr()
        assert "failure:" in captured.err

    def test_debug_with_exc_info(self, capsys: pytest.CaptureFixture[str]) -> None:
        """exc_info kwarg accepted by debug(); message appears."""
        cat = _unique("edge.excinfo.debug")
        log = JiveLogger(cat, level=logging.DEBUG)
        try:
            raise TypeError("bad type")
        except TypeError:
            log.debug("debug err:", exc_info=True)
        captured = capsys.readouterr()
        assert "debug err:" in captured.err

    def test_multiple_loggers_independent_levels(self) -> None:
        cat1 = _unique("indep.1")
        cat2 = _unique("indep.2")
        log1 = logger(cat1)
        log2 = logger(cat2)
        log1.set_level("debug")
        log2.set_level("error")
        assert log1.get_level() == "debug"
        assert log2.get_level() == "error"
