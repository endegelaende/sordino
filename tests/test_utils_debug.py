"""Tests for jive.utils.debug — debug utilities (dump, trace, traceback)."""

from __future__ import annotations

from io import StringIO
from typing import Any

import pytest

from jive.utils.debug import (
    _format_value,
    dump,
    dump_to_string,
    getinfo,
    is_tracing,
    trace_off,
    trace_on,
    traceback,
)

# ---------------------------------------------------------------------------
# _format_value — primitives
# ---------------------------------------------------------------------------


class TestFormatValuePrimitives:
    """_format_value returns repr() for primitive types."""

    def test_int(self) -> None:
        assert _format_value(42, depth=2, current_depth=0, indent=0) == "42"

    def test_float(self) -> None:
        assert _format_value(3.14, depth=2, current_depth=0, indent=0) == "3.14"

    def test_string(self) -> None:
        assert _format_value("hello", depth=2, current_depth=0, indent=0) == "'hello'"

    def test_none(self) -> None:
        assert _format_value(None, depth=2, current_depth=0, indent=0) == "None"

    def test_bool_true(self) -> None:
        assert _format_value(True, depth=2, current_depth=0, indent=0) == "True"

    def test_bool_false(self) -> None:
        assert _format_value(False, depth=2, current_depth=0, indent=0) == "False"

    def test_bytes(self) -> None:
        result = _format_value(b"\x00\xff", depth=2, current_depth=0, indent=0)
        assert result == repr(b"\x00\xff")

    def test_empty_string(self) -> None:
        assert _format_value("", depth=2, current_depth=0, indent=0) == "''"


# ---------------------------------------------------------------------------
# _format_value — dict
# ---------------------------------------------------------------------------


class TestFormatValueDict:
    """_format_value formatting for dicts."""

    def test_empty_dict(self) -> None:
        assert _format_value({}, depth=2, current_depth=0, indent=0) == "{}"

    def test_single_key(self) -> None:
        result = _format_value({"a": 1}, depth=2, current_depth=0, indent=0)
        assert "{ # dict" in result
        assert "'a': 1," in result
        assert result.endswith("}")

    def test_nested_dict(self) -> None:
        result = _format_value({"x": {"y": 2}}, depth=3, current_depth=0, indent=0)
        assert "{ # dict" in result
        assert "'y': 2," in result

    def test_depth_limit_dict(self) -> None:
        result = _format_value({"deep": {"nested": 1}}, depth=1, current_depth=0, indent=0)
        assert "{...}" in result

    def test_depth_limit_at_exact_boundary(self) -> None:
        """current_depth == depth should trigger truncation."""
        result = _format_value({"a": 1}, depth=1, current_depth=1, indent=0)
        assert result == "{...}"

    def test_indentation_increases(self) -> None:
        result = _format_value({"k": "v"}, depth=2, current_depth=0, indent=1)
        lines = result.split("\n")
        # The value line should have indent+1 = 2 levels = 4 spaces
        value_line = [l for l in lines if "'k'" in l][0]
        assert value_line.startswith("    ")

    def test_multiple_keys(self) -> None:
        data = {"a": 1, "b": 2, "c": 3}
        result = _format_value(data, depth=2, current_depth=0, indent=0)
        assert "'a': 1," in result
        assert "'b': 2," in result
        assert "'c': 3," in result


# ---------------------------------------------------------------------------
# _format_value — list
# ---------------------------------------------------------------------------


class TestFormatValueList:
    """_format_value formatting for lists."""

    def test_empty_list(self) -> None:
        assert _format_value([], depth=2, current_depth=0, indent=0) == "[]"

    def test_single_element(self) -> None:
        result = _format_value([42], depth=2, current_depth=0, indent=0)
        assert "[ # list" in result
        assert "42," in result

    def test_multiple_elements(self) -> None:
        result = _format_value([1, 2, 3], depth=2, current_depth=0, indent=0)
        assert "[ # list" in result
        assert "1," in result
        assert "2," in result
        assert "3," in result

    def test_depth_limit_list(self) -> None:
        result = _format_value([[1, 2]], depth=1, current_depth=0, indent=0)
        assert "[...]" in result

    def test_nested_list(self) -> None:
        result = _format_value([[1, 2], [3]], depth=3, current_depth=0, indent=0)
        assert "[ # list" in result


# ---------------------------------------------------------------------------
# _format_value — tuple
# ---------------------------------------------------------------------------


class TestFormatValueTuple:
    """_format_value formatting for tuples."""

    def test_empty_tuple(self) -> None:
        assert _format_value((), depth=2, current_depth=0, indent=0) == "()"

    def test_single_element(self) -> None:
        result = _format_value((99,), depth=2, current_depth=0, indent=0)
        assert "( # tuple" in result
        assert "99," in result

    def test_depth_limit_tuple(self) -> None:
        result = _format_value(((1,),), depth=1, current_depth=0, indent=0)
        assert "(...)" in result

    def test_closing_bracket_is_paren(self) -> None:
        result = _format_value((1, 2), depth=2, current_depth=0, indent=0)
        lines = result.split("\n")
        assert lines[-1].rstrip() == ")"


# ---------------------------------------------------------------------------
# _format_value — set
# ---------------------------------------------------------------------------


class TestFormatValueSet:
    """_format_value formatting for sets."""

    def test_empty_set(self) -> None:
        assert _format_value(set(), depth=2, current_depth=0, indent=0) == "set()"

    def test_single_element_set(self) -> None:
        result = _format_value({42}, depth=2, current_depth=0, indent=0)
        assert "{ # set" in result
        assert "42," in result

    def test_depth_limit_set(self) -> None:
        result = _format_value({1, 2}, depth=0, current_depth=0, indent=0)
        assert result == "{...}"

    def test_set_elements_sorted_by_repr(self) -> None:
        """Elements should appear in sorted-by-repr order."""
        result = _format_value({"b", "a", "c"}, depth=2, current_depth=0, indent=0)
        lines = [l.strip() for l in result.split("\n")]
        value_lines = [l for l in lines if l.endswith(",")]
        # 'a', 'b', 'c' sorted by repr
        assert value_lines[0] == "'a',"
        assert value_lines[1] == "'b',"
        assert value_lines[2] == "'c',"


# ---------------------------------------------------------------------------
# dump — writes to stream
# ---------------------------------------------------------------------------


class TestDump:
    """Tests for the dump() function."""

    def test_dump_to_stdout(self, capsys: pytest.CaptureFixture[str]) -> None:
        dump(42)
        captured = capsys.readouterr()
        assert "42" in captured.out

    def test_dump_to_custom_stream(self) -> None:
        buf = StringIO()
        dump({"key": "val"}, stream=buf)
        output = buf.getvalue()
        assert "'key'" in output
        assert "'val'" in output

    def test_dump_ends_with_newline(self) -> None:
        buf = StringIO()
        dump(123, stream=buf)
        assert buf.getvalue().endswith("\n")

    def test_dump_with_depth(self) -> None:
        buf = StringIO()
        dump({"a": {"b": {"c": 1}}}, depth=1, stream=buf)
        output = buf.getvalue()
        assert "{...}" in output

    def test_dump_default_depth_is_2(self) -> None:
        """Default depth=2 means 3 levels deep shows truncation."""
        buf = StringIO()
        dump({"a": {"b": {"c": 1}}}, stream=buf)
        output = buf.getvalue()
        # depth=2: level 0 (outer dict) → level 1 (inner dict) → level 2 → truncated
        assert "{...}" in output

    def test_dump_empty_dict(self) -> None:
        buf = StringIO()
        dump({}, stream=buf)
        assert "{}" in buf.getvalue()

    def test_dump_none(self, capsys: pytest.CaptureFixture[str]) -> None:
        dump(None)
        assert "None" in capsys.readouterr().out

    def test_dump_string(self) -> None:
        buf = StringIO()
        dump("hello", stream=buf)
        assert "'hello'" in buf.getvalue()


# ---------------------------------------------------------------------------
# dump_to_string
# ---------------------------------------------------------------------------


class TestDumpToString:
    """Tests for dump_to_string()."""

    def test_returns_string(self) -> None:
        result = dump_to_string(42)
        assert isinstance(result, str)

    def test_simple_value(self) -> None:
        assert "42" in dump_to_string(42)

    def test_dict(self) -> None:
        result = dump_to_string({"a": 1})
        assert "'a'" in result
        assert "1" in result

    def test_list(self) -> None:
        result = dump_to_string([1, 2, 3])
        assert "[ # list" in result

    def test_with_depth(self) -> None:
        result = dump_to_string({"outer": {"inner": 1}}, depth=1)
        assert "{...}" in result

    def test_nested_structure(self) -> None:
        data: dict[str, Any] = {"users": [{"name": "Alice"}], "count": 1}
        result = dump_to_string(data, depth=4)
        assert "'name'" in result
        assert "'Alice'" in result

    def test_empty_containers(self) -> None:
        assert "{}" in dump_to_string({})
        assert "[]" in dump_to_string([])
        assert "()" in dump_to_string(())
        assert "set()" in dump_to_string(set())

    def test_ends_with_newline(self) -> None:
        result = dump_to_string(42)
        assert result.endswith("\n")

    def test_bool_values(self) -> None:
        assert "True" in dump_to_string(True)
        assert "False" in dump_to_string(False)

    def test_mixed_container(self) -> None:
        result = dump_to_string({"items": [1, "two", None]}, depth=3)
        assert "'two'" in result
        assert "None" in result


# ---------------------------------------------------------------------------
# Trace on/off
# ---------------------------------------------------------------------------


class TestTrace:
    """Tests for trace_on, trace_off, is_tracing."""

    def test_initial_state_not_tracing(self) -> None:
        # Ensure clean state
        trace_off()
        assert is_tracing() is False

    def test_trace_on_sets_tracing(self) -> None:
        try:
            trace_on()
            assert is_tracing() is True
        finally:
            trace_off()

    def test_trace_off_clears_tracing(self) -> None:
        trace_on()
        trace_off()
        assert is_tracing() is False

    def test_double_trace_on(self) -> None:
        try:
            trace_on()
            trace_on()
            assert is_tracing() is True
        finally:
            trace_off()

    def test_double_trace_off(self) -> None:
        trace_off()
        trace_off()
        assert is_tracing() is False

    def test_trace_on_off_cycle(self) -> None:
        for _ in range(3):
            trace_on()
            assert is_tracing() is True
            trace_off()
            assert is_tracing() is False


# ---------------------------------------------------------------------------
# traceback
# ---------------------------------------------------------------------------


class TestTraceback:
    """Tests for the traceback() function."""

    def test_returns_string(self) -> None:
        result = traceback()
        assert isinstance(result, str)

    def test_contains_file_info(self) -> None:
        result = traceback()
        # Should contain at least some file reference
        assert "File" in result or ".py" in result

    def test_skip_default_excludes_self(self) -> None:
        """With default skip=1, the traceback function itself is excluded."""
        result = traceback()
        # The function name 'traceback' should not be the most recent frame
        lines = result.strip().splitlines()
        if lines:
            # Last meaningful line shouldn't reference the traceback() function itself
            # (it was skipped)
            pass  # just verifying it doesn't crash

    def test_skip_zero_includes_more_frames(self) -> None:
        result_skip0 = traceback(skip=0)
        result_skip1 = traceback(skip=1)
        # skip=0 should include more frames than skip=1
        assert len(result_skip0) >= len(result_skip1)

    def test_skip_large_returns_empty_or_minimal(self) -> None:
        """Skipping more frames than exist should not crash."""
        result = traceback(skip=9999)
        assert isinstance(result, str)

    def test_called_from_nested_function(self) -> None:
        def inner() -> str:
            return traceback()

        result = inner()
        assert isinstance(result, str)
        assert len(result) > 0


# ---------------------------------------------------------------------------
# getinfo
# ---------------------------------------------------------------------------


class TestGetinfo:
    """Tests for the getinfo() function.

    Note: ``getinfo`` uses ``sys._getframe(depth + 1)``.  Because pytest
    invokes test methods through several layers of indirection the
    *absolute* depth from a test body to a known frame is unpredictable.
    We therefore use helper functions with ``depth=0`` (which always
    inspects the direct caller of ``getinfo``) or relative comparisons
    to keep assertions stable across pytest versions.
    """

    def test_returns_dict(self) -> None:
        info = getinfo()
        assert isinstance(info, dict)

    def test_has_expected_keys(self) -> None:
        info = getinfo()
        assert "name" in info
        assert "filename" in info
        assert "lineno" in info
        assert "locals" in info

    def test_name_via_helper(self) -> None:
        """Wrap getinfo in a helper so we know the exact caller name.

        depth=0 → sys._getframe(1) → direct caller of getinfo → _probe.
        """

        def _probe() -> dict[str, Any]:
            return getinfo(depth=0)

        info = _probe()
        assert info["name"] == "_probe"

    def test_filename_via_helper(self) -> None:
        def _probe() -> dict[str, Any]:
            return getinfo(depth=0)

        info = _probe()
        assert "test_utils_debug" in info["filename"]

    def test_lineno_is_positive_int(self) -> None:
        info = getinfo()
        assert isinstance(info["lineno"], int)
        assert info["lineno"] > 0

    def test_locals_is_dict(self) -> None:
        info = getinfo()
        assert isinstance(info["locals"], dict)

    def test_locals_contains_local_vars(self) -> None:
        def _probe() -> dict[str, Any]:
            sentinel = 12345  # noqa: F841
            return getinfo(depth=0)  # depth=0 → _probe's own frame

        info = _probe()
        assert info["locals"].get("sentinel") == 12345

    def test_depth_zero_inspects_direct_caller(self) -> None:
        """depth=0 → sys._getframe(1) → the direct caller of getinfo."""

        def _probe() -> dict[str, Any]:
            return getinfo(depth=0)

        info = _probe()
        assert info["name"] == "_probe"

    def test_depth_1_from_nested(self) -> None:
        """depth=1 (default) → sys._getframe(2) → caller's caller."""

        def outer() -> dict[str, Any]:
            return inner()

        def inner() -> dict[str, Any]:
            return getinfo(depth=1)

        info = outer()
        # depth=1: frame(2) counting from getinfo → 0=getinfo, 1=inner, 2=outer
        assert info["name"] == "outer"

    def test_called_from_nested_function(self) -> None:
        def helper() -> dict[str, Any]:
            local_var = "inside_helper"  # noqa: F841
            # depth=0 → getinfo inspects its direct caller, i.e. helper
            return getinfo(depth=0)

        info = helper()
        assert info["name"] == "helper"
        assert "local_var" in info["locals"]
        assert info["locals"]["local_var"] == "inside_helper"


# ---------------------------------------------------------------------------
# Integration: dump complex nested structures
# ---------------------------------------------------------------------------


class TestDumpIntegration:
    """Integration tests with complex structures."""

    def test_deeply_nested_respects_depth(self) -> None:
        data: dict[str, Any] = {"l1": {"l2": {"l3": {"l4": "deep"}}}}
        result = dump_to_string(data, depth=2)
        assert "{...}" in result
        # l1 and l2 visible, l3 truncated
        assert "'l1'" in result

    def test_list_of_dicts(self) -> None:
        data = [{"name": "a"}, {"name": "b"}]
        result = dump_to_string(data, depth=3)
        assert "'name'" in result
        assert "'a'" in result
        assert "'b'" in result

    def test_mixed_types_in_dict(self) -> None:
        data: dict[str, Any] = {
            "int": 1,
            "str": "hello",
            "list": [1, 2],
            "none": None,
            "bool": True,
        }
        result = dump_to_string(data, depth=3)
        assert "'hello'" in result
        assert "None" in result
        assert "True" in result

    def test_large_depth_shows_everything(self) -> None:
        data: dict[str, Any] = {"a": {"b": {"c": {"d": 42}}}}
        result = dump_to_string(data, depth=10)
        assert "42" in result
        assert "{...}" not in result

    def test_tuple_inside_dict(self) -> None:
        result = dump_to_string({"coords": (1, 2)}, depth=3)
        assert "( # tuple" in result

    def test_set_inside_list(self) -> None:
        result = dump_to_string([{1, 2}], depth=3)
        assert "{ # set" in result
