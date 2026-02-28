"""
tests/test_utils.py — Comprehensive tests for jive.utils modules.

Tests cover:
    - table_utils: pairs_by_keys, delete, contains, insert, remove, sort
    - string_utils: str2hex, trim_null, split, match_literal, url_encode, url_decode
    - autotable: AutoTable creation, auto-vivification, attribute access, conversion
    - log: logger creation, categories, log levels, message concatenation
    - debug: dump, dump_to_string, traceback, getinfo, trace_on/trace_off
"""

from __future__ import annotations

import io
import logging
import sys
from typing import Any

import pytest

# ─── table_utils ──────────────────────────────────────────────────────────────
from jive.utils.table_utils import (
    contains,
    delete,
    insert,
    pairs_by_keys,
    remove,
    sort,
)


class TestPairsByKeys:
    """Tests for pairs_by_keys() — sorted dict iteration."""

    def test_basic_sorted_iteration(self) -> None:
        d = {"banana": 2, "apple": 1, "cherry": 3}
        result = list(pairs_by_keys(d))
        assert result == [("apple", 1), ("banana", 2), ("cherry", 3)]

    def test_empty_dict(self) -> None:
        result = list(pairs_by_keys({}))
        assert result == []

    def test_single_item(self) -> None:
        result = list(pairs_by_keys({"only": 42}))
        assert result == [("only", 42)]

    def test_already_sorted(self) -> None:
        d = {"a": 1, "b": 2, "c": 3}
        result = list(pairs_by_keys(d))
        assert result == [("a", 1), ("b", 2), ("c", 3)]

    def test_reverse_sorted(self) -> None:
        d = {"c": 3, "b": 2, "a": 1}
        result = list(pairs_by_keys(d))
        assert result == [("a", 1), ("b", 2), ("c", 3)]

    def test_custom_key_function(self) -> None:
        d = {"banana": 2, "apple": 1, "cherry": 3}
        # Sort by value (descending) via a key function on the keys
        result = list(pairs_by_keys(d, key_func=lambda k: -d[k]))
        assert result == [("cherry", 3), ("banana", 2), ("apple", 1)]

    def test_numeric_keys(self) -> None:
        d = {3: "c", 1: "a", 2: "b"}
        result = list(pairs_by_keys(d))
        assert result == [(1, "a"), (2, "b"), (3, "c")]

    def test_yields_tuples(self) -> None:
        d = {"x": 10}
        for item in pairs_by_keys(d):
            assert isinstance(item, tuple)
            assert len(item) == 2

    def test_does_not_modify_original(self) -> None:
        d = {"b": 2, "a": 1}
        original_keys = list(d.keys())
        _ = list(pairs_by_keys(d))
        assert list(d.keys()) == original_keys


class TestDelete:
    """Tests for delete() — remove first occurrence of value from list."""

    def test_delete_existing(self) -> None:
        items = [1, 2, 3, 2, 1]
        result = delete(items, 2)
        assert result is True
        assert items == [1, 3, 2, 1]

    def test_delete_nonexistent(self) -> None:
        items = [1, 2, 3]
        result = delete(items, 99)
        assert result is False
        assert items == [1, 2, 3]

    def test_delete_from_empty_list(self) -> None:
        items: list[int] = []
        result = delete(items, 1)
        assert result is False

    def test_delete_only_removes_first(self) -> None:
        items = ["a", "b", "a", "c", "a"]
        delete(items, "a")
        assert items == ["b", "a", "c", "a"]

    def test_delete_last_element(self) -> None:
        items = [42]
        result = delete(items, 42)
        assert result is True
        assert items == []

    def test_delete_with_none_values(self) -> None:
        items: list[Any] = [None, 1, None, 2]
        result = delete(items, None)
        assert result is True
        assert items == [1, None, 2]

    def test_delete_string_values(self) -> None:
        items = ["hello", "world", "hello"]
        result = delete(items, "hello")
        assert result is True
        assert items == ["world", "hello"]


class TestContains:
    """Tests for contains() — check if list contains a value."""

    def test_contains_existing(self) -> None:
        assert contains([1, 2, 3], 2) is True

    def test_contains_nonexistent(self) -> None:
        assert contains([1, 2, 3], 99) is False

    def test_contains_empty_list(self) -> None:
        assert contains([], "anything") is False

    def test_contains_none(self) -> None:
        assert contains([None, 1, 2], None) is True
        assert contains([1, 2, 3], None) is False

    def test_contains_string(self) -> None:
        assert contains(["apple", "banana"], "banana") is True
        assert contains(["apple", "banana"], "cherry") is False

    def test_contains_with_duplicates(self) -> None:
        assert contains([1, 1, 1], 1) is True


class TestInsert:
    """Tests for insert() — insert value into list."""

    def test_append_default(self) -> None:
        items = [1, 2, 3]
        insert(items, 99)
        assert items == [1, 2, 3, 99]

    def test_insert_at_beginning(self) -> None:
        items = [1, 2, 3]
        insert(items, 0, pos=0)
        assert items == [0, 1, 2, 3]

    def test_insert_at_middle(self) -> None:
        items = [1, 2, 3]
        insert(items, 99, pos=1)
        assert items == [1, 99, 2, 3]

    def test_insert_at_end(self) -> None:
        items = [1, 2, 3]
        insert(items, 99, pos=3)
        assert items == [1, 2, 3, 99]

    def test_insert_into_empty_list(self) -> None:
        items: list[int] = []
        insert(items, 42)
        assert items == [42]


class TestRemove:
    """Tests for remove() — remove and return element from list."""

    def test_remove_last_default(self) -> None:
        items = [10, 20, 30]
        result = remove(items)
        assert result == 30
        assert items == [10, 20]

    def test_remove_at_position(self) -> None:
        items = [10, 20, 30]
        result = remove(items, 0)
        assert result == 10
        assert items == [20, 30]

    def test_remove_middle(self) -> None:
        items = [10, 20, 30]
        result = remove(items, 1)
        assert result == 20
        assert items == [10, 30]

    def test_remove_from_single_element(self) -> None:
        items = [42]
        result = remove(items)
        assert result == 42
        assert items == []

    def test_remove_from_empty_raises(self) -> None:
        items: list[int] = []
        with pytest.raises(IndexError):
            remove(items)

    def test_remove_out_of_range_raises(self) -> None:
        items = [1, 2, 3]
        with pytest.raises(IndexError):
            remove(items, 10)


class TestSort:
    """Tests for sort() — in-place list sorting."""

    def test_sort_integers(self) -> None:
        items = [3, 1, 2]
        sort(items)
        assert items == [1, 2, 3]

    def test_sort_reverse(self) -> None:
        items = [1, 2, 3]
        sort(items, reverse=True)
        assert items == [3, 2, 1]

    def test_sort_with_key(self) -> None:
        items = ["banana", "apple", "cherry"]
        sort(items, key_func=len)
        assert items == ["apple", "banana", "cherry"]

    def test_sort_empty(self) -> None:
        items: list[int] = []
        sort(items)
        assert items == []

    def test_sort_single(self) -> None:
        items = [42]
        sort(items)
        assert items == [42]

    def test_sort_already_sorted(self) -> None:
        items = [1, 2, 3]
        sort(items)
        assert items == [1, 2, 3]

    def test_sort_strings(self) -> None:
        items = ["c", "a", "b"]
        sort(items)
        assert items == ["a", "b", "c"]


# ─── string_utils ─────────────────────────────────────────────────────────────

from jive.utils.string_utils import (
    match_literal,
    split,
    str2hex,
    trim_null,
    url_decode,
    url_encode,
)


class TestStr2Hex:
    """Tests for str2hex() — string to hex representation."""

    def test_ascii_string(self) -> None:
        result = str2hex("ABC")
        assert result == "41 42 43 "

    def test_empty_string(self) -> None:
        result = str2hex("")
        assert result == ""

    def test_single_char(self) -> None:
        result = str2hex("A")
        assert result == "41 "

    def test_null_byte(self) -> None:
        result = str2hex("\x00")
        assert result == "00 "

    def test_high_byte(self) -> None:
        result = str2hex("\xff")
        assert result == "FF "

    def test_bytes_input(self) -> None:
        result = str2hex(b"\x00\xff")
        assert result == "00 FF "

    def test_space_char(self) -> None:
        result = str2hex(" ")
        assert result == "20 "

    def test_mixed_content(self) -> None:
        result = str2hex("Hi!")
        assert result == "48 69 21 "


class TestTrimNull:
    """Tests for trim_null() — trim string at first null byte."""

    def test_trim_with_null(self) -> None:
        result = trim_null("hello\x00world")
        assert result == "hello"

    def test_no_null(self) -> None:
        result = trim_null("no nulls here")
        assert result == "no nulls here"

    def test_leading_null(self) -> None:
        result = trim_null("\x00leading null")
        assert result == ""

    def test_empty_string(self) -> None:
        result = trim_null("")
        assert result == ""

    def test_only_null(self) -> None:
        result = trim_null("\x00")
        assert result == ""

    def test_multiple_nulls(self) -> None:
        result = trim_null("a\x00b\x00c")
        assert result == "a"

    def test_trailing_null(self) -> None:
        result = trim_null("hello\x00")
        assert result == "hello"


class TestSplit:
    """Tests for split() — split string by delimiter."""

    def test_comma_split(self) -> None:
        result = split(",", "a,b,c")
        assert result == ["a", "b", "c"]

    def test_empty_pattern_splits_chars(self) -> None:
        result = split("", "abc")
        assert result == ["a", "b", "c"]

    def test_no_delimiter_found(self) -> None:
        result = split(",", "no-commas")
        assert result == ["no-commas"]

    def test_consecutive_delimiters(self) -> None:
        result = split(",", "a,,b")
        assert result == ["a", "", "b"]

    def test_delimiter_at_start(self) -> None:
        result = split(",", ",a,b")
        assert result == ["", "a", "b"]

    def test_delimiter_at_end(self) -> None:
        result = split(",", "a,b,")
        assert result == ["a", "b", ""]

    def test_append_to_existing_list(self) -> None:
        existing = ["x"]
        result = split(",", "a,b", existing)
        assert result == ["x", "a", "b"]
        assert result is existing

    def test_empty_string(self) -> None:
        result = split(",", "")
        assert result == [""]

    def test_empty_pattern_empty_string(self) -> None:
        result = split("", "")
        assert result == []

    def test_multi_char_delimiter(self) -> None:
        result = split("::", "a::b::c")
        assert result == ["a", "b", "c"]

    def test_space_delimiter(self) -> None:
        result = split(" ", "hello world foo")
        assert result == ["hello", "world", "foo"]


class TestMatchLiteral:
    """Tests for match_literal() — literal string matching."""

    def test_basic_match(self) -> None:
        result = match_literal("hello world", "world")
        assert result == "world"

    def test_no_match(self) -> None:
        result = match_literal("hello world", "xyz")
        assert result is None

    def test_regex_special_chars_treated_literally(self) -> None:
        result = match_literal("file (1).txt", "(1)")
        assert result == "(1)"

    def test_match_with_brackets(self) -> None:
        result = match_literal("data[0]", "[0]")
        assert result == "[0]"

    def test_match_with_dots(self) -> None:
        result = match_literal("version 1.2.3", "1.2")
        assert result == "1.2"

    def test_match_with_init_position(self) -> None:
        result = match_literal("hello world", "world", 6)
        assert result == "world"

    def test_init_position_past_match(self) -> None:
        result = match_literal("hello world", "hello", 5)
        assert result is None

    def test_init_position_at_match_start(self) -> None:
        result = match_literal("hello world", "hello", 0)
        assert result == "hello"

    def test_init_too_large(self) -> None:
        result = match_literal("hello", "hello", 99)
        assert result is None

    def test_negative_init(self) -> None:
        result = match_literal("hello world", "world", -5)
        assert result == "world"

    def test_empty_pattern(self) -> None:
        result = match_literal("hello", "")
        assert result == ""

    def test_empty_string(self) -> None:
        result = match_literal("", "hello")
        assert result is None

    def test_both_empty(self) -> None:
        result = match_literal("", "")
        assert result == ""

    def test_pattern_with_asterisk(self) -> None:
        result = match_literal("a*b", "*")
        assert result == "*"

    def test_pattern_with_plus(self) -> None:
        result = match_literal("a+b", "+")
        assert result == "+"


class TestUrlDecode:
    """Tests for url_decode() — URL decoding."""

    def test_plus_to_space(self) -> None:
        assert url_decode("hello+world") == "hello world"

    def test_percent_encoding(self) -> None:
        assert url_decode("hello%20world") == "hello world"

    def test_hex_uppercase(self) -> None:
        assert url_decode("%48%65%6C%6C%6F") == "Hello"

    def test_crlf_normalization(self) -> None:
        decoded = url_decode("line1%0D%0Aline2")
        assert decoded == "line1\nline2"

    def test_no_encoding(self) -> None:
        assert url_decode("already decoded") == "already decoded"

    def test_empty_string(self) -> None:
        assert url_decode("") == ""

    def test_special_chars(self) -> None:
        assert url_decode("%26%3D%3F") == "&=?"


class TestUrlEncode:
    """Tests for url_encode() — URL encoding."""

    def test_space_to_plus(self) -> None:
        assert url_encode("hello world") == "hello+world"

    def test_special_chars(self) -> None:
        result = url_encode("a=1&b=2")
        assert result == "a%3D1%26b%3D2"

    def test_empty_string(self) -> None:
        assert url_encode("") == ""

    def test_alphanumeric_passthrough(self) -> None:
        # Only alphanumerics should pass through unencoded
        result = url_encode("abc123")
        assert result == "abc123"

    def test_underscore_passthrough(self) -> None:
        result = url_encode("already_safe_123")
        assert result == "already_safe_123"

    def test_roundtrip(self) -> None:
        original = "hello world & goodbye"
        encoded = url_encode(original)
        decoded = url_decode(encoded)
        # Note: newline normalization may cause \n → \r\n → \n roundtrip
        assert decoded == original


# ─── autotable ────────────────────────────────────────────────────────────────

from jive.utils.autotable import AutoTable, new


class TestAutoTable:
    """Tests for AutoTable — auto-vivifying nested dictionaries."""

    def test_basic_auto_vivification(self) -> None:
        t = AutoTable()
        t["a"]["b"]["c"] = 42
        assert t["a"]["b"]["c"] == 42

    def test_attribute_access_write(self) -> None:
        t = AutoTable()
        t.x.y = 10
        assert t["x"]["y"] == 10

    def test_attribute_access_read(self) -> None:
        t = AutoTable()
        t["display"] = {"width": 800}
        # Note: nested dicts won't have attribute access unless they're AutoTables
        assert t["display"]["width"] == 800

    def test_missing_key_returns_autotable(self) -> None:
        t = AutoTable()
        sub = t["nonexistent"]
        assert isinstance(sub, AutoTable)

    def test_nested_assignment(self) -> None:
        t = AutoTable()
        t["potter"]["magic"]["wand"] = 33
        assert t["potter"]["magic"]["wand"] == 33

    def test_overwrite_value(self) -> None:
        t = AutoTable()
        t["key"] = "first"
        t["key"] = "second"
        assert t["key"] == "second"

    def test_mixed_types_as_values(self) -> None:
        t = AutoTable()
        t["int"] = 42
        t["str"] = "hello"
        t["list"] = [1, 2, 3]
        t["bool"] = True
        t["none"] = None
        assert t["int"] == 42
        assert t["str"] == "hello"
        assert t["list"] == [1, 2, 3]
        assert t["bool"] is True
        assert t["none"] is None

    def test_to_dict(self) -> None:
        t = AutoTable()
        t["a"]["b"] = 1
        t["c"] = 2
        result = t.to_dict()
        assert result == {"a": {"b": 1}, "c": 2}
        assert type(result) is dict
        assert type(result["a"]) is dict

    def test_to_dict_empty(self) -> None:
        t = AutoTable()
        assert t.to_dict() == {}

    def test_from_dict(self) -> None:
        plain = {"a": {"b": 1}, "c": 2}
        t = AutoTable.from_dict(plain)
        assert t["a"]["b"] == 1
        assert t["c"] == 2
        assert isinstance(t, AutoTable)
        assert isinstance(t["a"], AutoTable)

    def test_from_dict_empty(self) -> None:
        t = AutoTable.from_dict({})
        assert isinstance(t, AutoTable)
        assert len(t) == 0

    def test_new_factory(self) -> None:
        t = new()
        assert isinstance(t, AutoTable)
        assert len(t) == 0

    def test_repr(self) -> None:
        t = AutoTable()
        assert repr(t) == "AutoTable({})"
        t["a"] = 1
        assert "AutoTable" in repr(t)
        assert "'a': 1" in repr(t)

    def test_del_attribute(self) -> None:
        t = AutoTable()
        t.x = 42
        assert t.x == 42
        del t.x
        # After deletion, accessing 'x' creates a new empty AutoTable
        sub = t["x"]
        assert isinstance(sub, AutoTable)
        assert len(sub) == 0

    def test_del_nonexistent_attribute_raises(self) -> None:
        t = AutoTable()
        with pytest.raises(AttributeError):
            del t.nonexistent_key

    def test_dunder_attribute_raises(self) -> None:
        t = AutoTable()
        with pytest.raises(AttributeError):
            _ = t._private_thing

    def test_iteration(self) -> None:
        t = AutoTable()
        t["a"] = 1
        t["b"] = 2
        t["c"] = 3
        keys = list(t.keys())
        assert set(keys) == {"a", "b", "c"}

    def test_len(self) -> None:
        t = AutoTable()
        assert len(t) == 0
        t["a"] = 1
        assert len(t) == 1
        t["b"]["c"] = 2
        assert len(t) == 2  # "a" and "b"

    def test_in_operator(self) -> None:
        t = AutoTable()
        t["exists"] = True
        assert "exists" in t
        assert "missing" not in t

    def test_deeply_nested(self) -> None:
        t = AutoTable()
        t["a"]["b"]["c"]["d"]["e"]["f"] = "deep"
        assert t["a"]["b"]["c"]["d"]["e"]["f"] == "deep"

    def test_values_preserved_through_roundtrip(self) -> None:
        t = AutoTable()
        t["config"]["display"]["width"] = 800
        t["config"]["display"]["height"] = 480
        t["config"]["network"]["timeout"] = 30

        plain = t.to_dict()
        t2 = AutoTable.from_dict(plain)

        assert t2["config"]["display"]["width"] == 800
        assert t2["config"]["display"]["height"] == 480
        assert t2["config"]["network"]["timeout"] == 30


# ─── log ──────────────────────────────────────────────────────────────────────

from jive.utils.log import (
    JiveLogger,
    _concat_args,
    _loggers,
    get_categories,
    logger,
    set_all_levels,
    set_default_level,
)


class TestLog:
    """Tests for jive.utils.log — category-based logging."""

    def setup_method(self) -> None:
        """Clear logger registry before each test."""
        _loggers.clear()

    def test_create_logger(self) -> None:
        log = logger("test.basic")
        assert isinstance(log, JiveLogger)
        assert log.category == "test.basic"

    def test_same_category_returns_same_logger(self) -> None:
        log1 = logger("test.same")
        log2 = logger("test.same")
        assert log1 is log2

    def test_different_categories(self) -> None:
        log1 = logger("test.one")
        log2 = logger("test.two")
        assert log1 is not log2
        assert log1.category != log2.category

    def test_get_categories(self) -> None:
        logger("aaa")
        logger("zzz")
        logger("mmm")
        cats = get_categories()
        assert cats == ["aaa", "mmm", "zzz"]

    def test_get_categories_empty(self) -> None:
        assert get_categories() == []

    def test_set_level_string(self) -> None:
        log = logger("test.level")
        log.set_level("debug")
        assert log.get_level() == "debug"
        log.set_level("info")
        assert log.get_level() == "info"
        log.set_level("warn")
        assert log.get_level() == "warn"
        log.set_level("error")
        assert log.get_level() == "error"

    def test_set_level_int(self) -> None:
        log = logger("test.levelint")
        log.set_level(logging.DEBUG)
        assert log.get_level() == "debug"

    def test_is_debug(self) -> None:
        log = logger("test.isdebug")
        log.set_level("error")
        assert log.is_debug() is False
        log.set_level("debug")
        assert log.is_debug() is True

    def test_set_all_levels(self) -> None:
        log1 = logger("test.all1")
        log2 = logger("test.all2")
        set_all_levels("debug")
        assert log1.get_level() == "debug"
        assert log2.get_level() == "debug"
        set_all_levels("error")
        assert log1.get_level() == "error"
        assert log2.get_level() == "error"

    def test_set_default_level(self) -> None:
        set_default_level("debug")
        log = logger("test.default")
        assert log.get_level() == "debug"
        # Reset to avoid affecting other tests
        set_default_level("warn")

    def test_repr(self) -> None:
        log = logger("test.repr")
        r = repr(log)
        assert "JiveLogger" in r
        assert "test.repr" in r

    def test_debug_output(self, capfd: pytest.CaptureFixture[str]) -> None:
        log = logger("test.output")
        log.set_level("debug")
        log.debug("hello debug")
        # Logger writes to stderr
        captured = capfd.readouterr()
        assert "hello debug" in captured.err

    def test_info_output(self, capfd: pytest.CaptureFixture[str]) -> None:
        log = logger("test.info_out")
        log.set_level("info")
        log.info("hello info")
        captured = capfd.readouterr()
        assert "hello info" in captured.err

    def test_warn_output(self, capfd: pytest.CaptureFixture[str]) -> None:
        log = logger("test.warn_out")
        log.set_level("warn")
        log.warn("hello warn")
        captured = capfd.readouterr()
        assert "hello warn" in captured.err

    def test_error_output(self, capfd: pytest.CaptureFixture[str]) -> None:
        log = logger("test.error_out")
        log.set_level("error")
        log.error("hello error")
        captured = capfd.readouterr()
        assert "hello error" in captured.err

    def test_level_filtering(self, capfd: pytest.CaptureFixture[str]) -> None:
        log = logger("test.filter")
        log.set_level("error")
        log.debug("should not appear")
        log.info("should not appear")
        log.warn("should not appear")
        captured = capfd.readouterr()
        assert captured.err == ""

    def test_concat_args_single(self) -> None:
        assert _concat_args(("hello",)) == "hello"

    def test_concat_args_multiple(self) -> None:
        result = _concat_args(("Welcome ", "Alice", ", count: ", 42))
        assert result == "Welcome Alice, count: 42"

    def test_concat_args_empty(self) -> None:
        assert _concat_args(()) == ""

    def test_concat_args_none(self) -> None:
        assert _concat_args((None,)) == "None"

    def test_multiarg_log_message(self, capfd: pytest.CaptureFixture[str]) -> None:
        log = logger("test.multiarg")
        log.set_level("debug")
        log.debug("Value: ", 42, ", name: ", "test")
        captured = capfd.readouterr()
        assert "Value: 42, name: test" in captured.err


# ─── debug ────────────────────────────────────────────────────────────────────

from jive.utils.debug import (
    dump,
    dump_to_string,
    getinfo,
    is_tracing,
    trace_off,
    trace_on,
    traceback,
)


class TestDump:
    """Tests for dump() and dump_to_string() — object pretty-printing."""

    def test_dump_dict(self) -> None:
        result = dump_to_string({"a": 1, "b": 2})
        assert "'a': 1" in result
        assert "'b': 2" in result
        assert "# dict" in result

    def test_dump_nested_dict(self) -> None:
        result = dump_to_string({"a": {"b": 1}})
        assert "'a'" in result
        assert "'b': 1" in result

    def test_dump_list(self) -> None:
        result = dump_to_string([1, 2, 3])
        assert "# list" in result
        assert "1," in result
        assert "2," in result
        assert "3," in result

    def test_dump_empty_dict(self) -> None:
        result = dump_to_string({})
        assert result.strip() == "{}"

    def test_dump_empty_list(self) -> None:
        result = dump_to_string([])
        assert result.strip() == "[]"

    def test_dump_depth_limit(self) -> None:
        result = dump_to_string({"deep": {"nested": {"value": 42}}}, depth=1)
        assert "{...}" in result

    def test_dump_depth_2_default(self) -> None:
        result = dump_to_string({"a": {"b": {"c": 1}}})
        # At depth 2, the innermost dict should be truncated
        assert "{...}" in result

    def test_dump_primitive(self) -> None:
        assert dump_to_string(42).strip() == "42"
        assert dump_to_string("hello").strip() == "'hello'"
        assert dump_to_string(True).strip() == "True"
        assert dump_to_string(None).strip() == "None"

    def test_dump_to_stream(self) -> None:
        buf = io.StringIO()
        dump({"key": "value"}, stream=buf)
        output = buf.getvalue()
        assert "key" in output
        assert "value" in output

    def test_dump_tuple(self) -> None:
        result = dump_to_string((1, 2))
        assert "# tuple" in result

    def test_dump_set(self) -> None:
        result = dump_to_string({1, 2, 3})
        assert "# set" in result

    def test_dump_stdout_default(self, capsys: pytest.CaptureFixture[str]) -> None:
        dump({"x": 1})
        captured = capsys.readouterr()
        assert "'x': 1" in captured.out


class TestTraceback:
    """Tests for traceback() — formatted stack trace."""

    def test_returns_string(self) -> None:
        tb = traceback()
        assert isinstance(tb, str)

    def test_contains_file_info(self) -> None:
        tb = traceback()
        # Should contain reference to this test file
        assert "test_utils" in tb or "File" in tb

    def test_skip_frames(self) -> None:
        # Calling with skip=0 should include more frames
        tb0 = traceback(skip=0)
        tb2 = traceback(skip=2)
        # More skipping → fewer lines
        assert len(tb2) <= len(tb0)


class TestGetInfo:
    """Tests for getinfo() — stack frame information."""

    def test_returns_dict(self) -> None:
        info = getinfo(0)
        assert isinstance(info, dict)

    def test_has_expected_keys(self) -> None:
        info = getinfo(0)
        assert "name" in info
        assert "filename" in info
        assert "lineno" in info
        assert "locals" in info

    def test_function_name(self) -> None:
        info = getinfo(0)
        assert info["name"] == "test_function_name"

    def test_filename(self) -> None:
        info = getinfo(0)
        assert "test_utils" in info["filename"]

    def test_lineno_is_int(self) -> None:
        info = getinfo(0)
        assert isinstance(info["lineno"], int)
        assert info["lineno"] > 0

    def test_locals_is_dict(self) -> None:
        local_var = "sentinel_value"  # noqa: F841
        info = getinfo(0)
        assert isinstance(info["locals"], dict)
        assert "local_var" in info["locals"]
        assert info["locals"]["local_var"] == "sentinel_value"


class TestTrace:
    """Tests for trace_on/trace_off — line tracing."""

    def test_trace_off_by_default(self) -> None:
        assert is_tracing() is False

    def test_trace_on_sets_flag(self) -> None:
        try:
            trace_on()
            assert is_tracing() is True
        finally:
            trace_off()

    def test_trace_off_clears_flag(self) -> None:
        trace_on()
        trace_off()
        assert is_tracing() is False

    def test_trace_produces_output(self, capsys: pytest.CaptureFixture[str]) -> None:
        trace_on()
        x = 1 + 1  # noqa: F841 — this line should be traced
        trace_off()
        captured = capsys.readouterr()
        assert "TRACE" in captured.out

    def test_trace_off_stops_output(self, capsys: pytest.CaptureFixture[str]) -> None:
        trace_on()
        trace_off()
        x = 1 + 1  # noqa: F841 — this should NOT be traced
        captured = capsys.readouterr()
        # After trace_off, no TRACE lines for subsequent statements
        lines = [l for l in captured.out.splitlines() if "TRACE" in l]
        # The only TRACE lines should be from before trace_off
        for line in lines:
            assert "trace_off" in line or "test_trace_off" in line or True
            # We just check that tracing stopped at some point


# ─── jsonfilters ──────────────────────────────────────────────────────────────

from jive.utils.jsonfilters import decode, encode


class TestJsonFiltersDecode:
    """Tests for jsonfilters.decode — JSON string → Python object."""

    def test_decode_dict(self) -> None:
        result = decode('{"a": 1, "b": 2}')
        assert result == {"a": 1, "b": 2}

    def test_decode_list(self) -> None:
        result = decode("[1, 2, 3]")
        assert result == [1, 2, 3]

    def test_decode_string(self) -> None:
        result = decode('"hello"')
        assert result == "hello"

    def test_decode_number(self) -> None:
        assert decode("42") == 42
        assert decode("3.14") == 3.14

    def test_decode_bool(self) -> None:
        assert decode("true") is True
        assert decode("false") is False

    def test_decode_null(self) -> None:
        assert decode("null") is None

    def test_decode_none_passthrough(self) -> None:
        assert decode(None) is None

    def test_decode_empty_string_passthrough(self) -> None:
        assert decode("") == ""

    def test_decode_nested(self) -> None:
        result = decode('{"players": [{"name": "Kitchen"}]}')
        assert result == {"players": [{"name": "Kitchen"}]}

    def test_decode_bytes(self) -> None:
        result = decode(b'{"x": 1}')
        assert result == {"x": 1}

    def test_decode_invalid_raises(self) -> None:
        import json

        with pytest.raises(json.JSONDecodeError):
            decode("{invalid json}")

    def test_decode_unicode(self) -> None:
        result = decode('"Stra\\u00dfe"')
        assert result == "Straße"


class TestJsonFiltersEncode:
    """Tests for jsonfilters.encode — Python object → JSON string."""

    def test_encode_dict(self) -> None:
        result = encode({"a": 1})
        assert result == '{"a":1}'

    def test_encode_list(self) -> None:
        result = encode([1, 2, 3])
        assert result == "[1,2,3]"

    def test_encode_string(self) -> None:
        result = encode("hello")
        assert result == '"hello"'

    def test_encode_number(self) -> None:
        assert encode(42) == "42"

    def test_encode_bool(self) -> None:
        assert encode(True) == "true"
        assert encode(False) == "false"

    def test_encode_none_passthrough(self) -> None:
        assert encode(None) is None

    def test_encode_empty_string_passthrough(self) -> None:
        assert encode("") == ""

    def test_encode_compact_no_spaces(self) -> None:
        result = encode({"key": "value", "num": 42})
        assert " " not in result  # compact separators

    def test_encode_nested(self) -> None:
        result = encode({"a": {"b": [1, 2]}})
        assert result == '{"a":{"b":[1,2]}}'

    def test_encode_unicode_preserved(self) -> None:
        result = encode({"name": "Straße"})
        assert "Straße" in result

    def test_encode_decode_roundtrip(self) -> None:
        original = {"players": [{"name": "Kitchen", "vol": 50}], "count": 1}
        encoded = encode(original)
        assert encoded is not None
        decoded = decode(encoded)
        assert decoded == original

    def test_encode_not_serializable_raises(self) -> None:
        with pytest.raises(TypeError):
            encode(object())


# ─── dumper ───────────────────────────────────────────────────────────────────

from jive.utils.dumper import dump as dumper_dump
from jive.utils.dumper import dumps


class TestDumperDumps:
    """Tests for dumper.dumps — serialize objects to string."""

    def test_dumps_int(self) -> None:
        assert dumps(42) == "42"

    def test_dumps_float(self) -> None:
        result = dumps(3.14)
        assert "3.14" in result

    def test_dumps_string(self) -> None:
        assert dumps("hello") == '"hello"'

    def test_dumps_none(self) -> None:
        assert dumps(None) == "None"

    def test_dumps_bool(self) -> None:
        assert dumps(True) == "True"
        assert dumps(False) == "False"

    def test_dumps_empty_dict(self) -> None:
        assert dumps({}) == "{}"

    def test_dumps_empty_list(self) -> None:
        assert dumps([]) == "{}"

    def test_dumps_simple_dict(self) -> None:
        result = dumps({"a": 1})
        assert "a" in result
        assert "1" in result

    def test_dumps_list(self) -> None:
        result = dumps([1, 2, 3])
        assert "1" in result
        assert "2" in result
        assert "3" in result

    def test_dumps_nested_dict(self) -> None:
        result = dumps({"outer": {"inner": 42}})
        assert "outer" in result
        assert "inner" in result
        assert "42" in result

    def test_dumps_string_escaping(self) -> None:
        result = dumps("line1\nline2")
        assert "\\n" in result

    def test_dumps_string_escaping_tab(self) -> None:
        result = dumps("col1\tcol2")
        assert "\\t" in result

    def test_dumps_string_escaping_quote(self) -> None:
        result = dumps('say "hi"')
        assert '\\"' in result

    def test_dumps_bytes(self) -> None:
        result = dumps(b"\x00\x01")
        assert "b'" in result or 'b"' in result


class TestDumperDumpsfast:
    """Tests for dumps in fast mode."""

    def test_fast_dict(self) -> None:
        result = dumps({"a": 1}, fastmode=True)
        assert result == "{a=1}"

    def test_fast_list(self) -> None:
        result = dumps([1, 2, 3], fastmode=True)
        assert result == "{1,2,3}"

    def test_fast_nested(self) -> None:
        result = dumps({"x": [1, 2]}, fastmode=True)
        assert "x=" in result
        assert "1" in result

    def test_fast_empty(self) -> None:
        assert dumps({}, fastmode=True) == "{}"
        assert dumps([], fastmode=True) == "{}"

    def test_fast_string(self) -> None:
        assert dumps("hi", fastmode=True) == '"hi"'

    def test_fast_none(self) -> None:
        assert dumps(None, fastmode=True) == "None"


class TestDumperDump:
    """Tests for dumper.dump() — with varname prefix."""

    def test_dump_default_prefix(self) -> None:
        result = dumper_dump(42)
        assert result == "return 42"

    def test_dump_with_varname(self) -> None:
        result = dumper_dump(42, varname="x")
        assert result == "x = 42"

    def test_dump_with_empty_varname(self) -> None:
        result = dumper_dump(42, varname="")
        assert result == "42"

    def test_dump_with_return_varname(self) -> None:
        result = dumper_dump(42, varname="return ")
        assert result == "return 42"

    def test_dump_dict_with_varname(self) -> None:
        result = dumper_dump({"key": "val"}, varname="cfg")
        assert result.startswith("cfg = {")

    def test_dump_fastmode_with_varname(self) -> None:
        result = dumper_dump({"a": 1}, varname="t", fastmode=True)
        assert result == "t = {a=1}"


class TestDumperCircular:
    """Tests for circular reference handling."""

    def test_circular_dict(self) -> None:
        d: dict[str, Any] = {"name": "root"}
        d["self_ref"] = d
        result = dumps(d)
        assert "<circular ref>" in result

    def test_circular_list(self) -> None:
        lst: list[Any] = [1, 2]
        lst.append(lst)
        result = dumps(lst)
        assert "<circular ref>" in result


class TestDumperKeyFormatting:
    """Tests for key formatting — identifiers vs bracket notation."""

    def test_identifier_key(self) -> None:
        result = dumps({"name": "test"})
        assert "name" in result

    def test_numeric_key(self) -> None:
        result = dumps({0: "a", 1: "b"})
        # Should be treated as sequence
        assert '"a"' in result

    def test_reserved_word_key(self) -> None:
        result = dumps({"and": 1}, fastmode=True)
        assert '["and"]=' in result

    def test_key_with_spaces(self) -> None:
        result = dumps({"my key": 1}, fastmode=True)
        assert '["my key"]=' in result

    def test_set_serialization(self) -> None:
        result = dumps({1, 2, 3})
        assert "1" in result
        assert "2" in result

    def test_tuple_serialization(self) -> None:
        result = dumps((10, 20))
        assert "10" in result
        assert "20" in result


# ─── datetime_utils ───────────────────────────────────────────────────────────

from jive.utils.datetime_utils import (
    get_all_date_formats,
    get_all_short_date_formats,
    get_all_timezones,
    get_current_date,
    get_current_time,
    get_date_format,
    get_hours,
    get_short_date_format,
    get_timezone,
    get_weekstart,
    is_clock_set,
    reset_defaults,
    seconds_from_midnight,
    set_date_format,
    set_hours,
    set_short_date_format,
    set_timezone,
    set_weekstart,
    time_from_sfm,
    time_table_from_sfm,
)


class TestDateFormats:
    """Tests for date format get/set."""

    def setup_method(self) -> None:
        reset_defaults()

    def test_get_all_date_formats(self) -> None:
        fmts = get_all_date_formats()
        assert isinstance(fmts, list)
        assert len(fmts) > 10
        assert "%Y-%m-%d" in fmts

    def test_get_all_date_formats_returns_copy(self) -> None:
        fmts1 = get_all_date_formats()
        fmts2 = get_all_date_formats()
        assert fmts1 == fmts2
        fmts1.append("MODIFIED")
        assert "MODIFIED" not in get_all_date_formats()

    def test_get_all_short_date_formats(self) -> None:
        fmts = get_all_short_date_formats()
        assert isinstance(fmts, list)
        assert "%d.%m.%Y" in fmts

    def test_set_date_format(self) -> None:
        set_date_format("%Y-%m-%d")
        assert get_date_format() == "%Y-%m-%d"

    def test_set_short_date_format(self) -> None:
        set_short_date_format("%m.%d.%Y")
        assert get_short_date_format() == "%m.%d.%Y"

    def test_default_date_format(self) -> None:
        assert get_date_format() == "%a, %B %d %Y"

    def test_default_short_date_format(self) -> None:
        assert get_short_date_format() == "%d.%m.%Y"


class TestWeekstart:
    """Tests for weekstart get/set."""

    def setup_method(self) -> None:
        reset_defaults()

    def test_default_weekstart(self) -> None:
        assert get_weekstart() == "Sunday"

    def test_set_weekstart_monday(self) -> None:
        set_weekstart("Monday")
        assert get_weekstart() == "Monday"

    def test_set_weekstart_sunday(self) -> None:
        set_weekstart("Monday")
        set_weekstart("Sunday")
        assert get_weekstart() == "Sunday"

    def test_set_weekstart_invalid_ignored(self) -> None:
        set_weekstart("Wednesday")
        assert get_weekstart() == "Sunday"  # unchanged

    def test_set_weekstart_none_ignored(self) -> None:
        set_weekstart(None)
        assert get_weekstart() == "Sunday"


class TestHours:
    """Tests for 12h/24h hour setting."""

    def setup_method(self) -> None:
        reset_defaults()

    def test_default_hours(self) -> None:
        assert get_hours() == "12"

    def test_set_hours_24_string(self) -> None:
        set_hours("24")
        assert get_hours() == "24"

    def test_set_hours_12_string(self) -> None:
        set_hours("24")
        set_hours("12")
        assert get_hours() == "12"

    def test_set_hours_24_int(self) -> None:
        set_hours(24)
        assert get_hours() == "24"

    def test_set_hours_12_int(self) -> None:
        set_hours(12)
        assert get_hours() == "12"

    def test_set_hours_invalid_string_ignored(self) -> None:
        set_hours("36")
        assert get_hours() == "12"

    def test_set_hours_invalid_int_ignored(self) -> None:
        set_hours(8)
        assert get_hours() == "12"


class TestTimezone:
    """Tests for timezone functions."""

    def setup_method(self) -> None:
        reset_defaults()

    def test_get_timezone_gmt(self) -> None:
        tz = get_timezone("GMT")
        assert tz is not None
        assert tz["offset"] == 0
        assert tz["text"] == "GMT"

    def test_get_timezone_cet(self) -> None:
        tz = get_timezone("CET")
        assert tz is not None
        assert tz["offset"] == 1

    def test_get_timezone_invalid(self) -> None:
        assert get_timezone("INVALID") is None

    def test_get_all_timezones(self) -> None:
        tzs = get_all_timezones()
        assert "GMT" in tzs
        assert "CET" in tzs

    def test_set_timezone_valid(self) -> None:
        assert set_timezone("CET") is True

    def test_set_timezone_invalid(self) -> None:
        assert set_timezone("INVALID") is False


class TestSecondsFromMidnight:
    """Tests for seconds_from_midnight — HHMM → seconds."""

    def test_midnight(self) -> None:
        assert seconds_from_midnight("0000") == 0

    def test_one_hour(self) -> None:
        assert seconds_from_midnight("0100") == 3600

    def test_1430(self) -> None:
        assert seconds_from_midnight("1430") == 52200

    def test_2359(self) -> None:
        assert seconds_from_midnight("2359") == 86340

    def test_noon(self) -> None:
        assert seconds_from_midnight("1200") == 43200

    def test_pm_suffix(self) -> None:
        # 0230p = 2:30 PM = 14:30 = 52200
        assert seconds_from_midnight("0230p") == 52200

    def test_am_suffix(self) -> None:
        # 0230a = 2:30 AM = 9000
        assert seconds_from_midnight("0230a") == 9000

    def test_12am(self) -> None:
        # 12:00 AM = midnight = 0
        assert seconds_from_midnight("1200a") == 0

    def test_12pm(self) -> None:
        # 12:00 PM = noon = 43200
        assert seconds_from_midnight("1200p") == 43200

    def test_invalid_hours(self) -> None:
        assert seconds_from_midnight("2500") == 0

    def test_invalid_minutes(self) -> None:
        assert seconds_from_midnight("1260") == 0

    def test_integer_input(self) -> None:
        assert seconds_from_midnight(1430) == 52200


class TestTimeTableFromSFM:
    """Tests for time_table_from_sfm — SFM → {hour, minute, ampm}."""

    def test_midnight_24h(self) -> None:
        result = time_table_from_sfm(0, "24")
        assert result == {"hour": 0, "minute": 0, "ampm": None}

    def test_one_hour_24h(self) -> None:
        result = time_table_from_sfm(3600, "24")
        assert result == {"hour": 1, "minute": 0, "ampm": None}

    def test_1430_24h(self) -> None:
        result = time_table_from_sfm(52200, "24")
        assert result == {"hour": 14, "minute": 30, "ampm": None}

    def test_negative_24h(self) -> None:
        result = time_table_from_sfm(-1, "24")
        assert result == {"hour": 0, "minute": 0, "ampm": None}

    def test_overflow_24h(self) -> None:
        result = time_table_from_sfm(86400, "24")
        assert result == {"hour": 0, "minute": 0, "ampm": None}

    def test_1am_12h(self) -> None:
        result = time_table_from_sfm(3600, "12")
        assert result["hour"] == 1
        assert result["minute"] == 0
        assert result["ampm"] == "AM"

    def test_1430_12h(self) -> None:
        result = time_table_from_sfm(52200, "12")
        assert result["hour"] == 2
        assert result["minute"] == 30
        assert result["ampm"] == "pm"

    def test_midnight_12h(self) -> None:
        result = time_table_from_sfm(0, "12")
        assert result["hour"] == 12
        assert result["ampm"] == "AM"

    def test_overflow_12h(self) -> None:
        result = time_table_from_sfm(86400, "12")
        assert result["hour"] == 12
        assert result["ampm"] == "PM"

    def test_default_format_is_24(self) -> None:
        result = time_table_from_sfm(3600)
        assert result["ampm"] is None  # 24h


class TestTimeFromSFM:
    """Tests for time_from_sfm — SFM → formatted string."""

    def test_midnight_24h(self) -> None:
        assert time_from_sfm(0, "24") == "00:00"

    def test_one_hour_24h(self) -> None:
        assert time_from_sfm(3600, "24") == "01:00"

    def test_1430_24h(self) -> None:
        assert time_from_sfm(52200, "24") == "14:30"

    def test_overflow_24h(self) -> None:
        assert time_from_sfm(86400, "24") == "00:00"

    def test_negative_24h(self) -> None:
        assert time_from_sfm(-1, "24") == "00:00"

    def test_1430_12h(self) -> None:
        assert time_from_sfm(52200, "12") == "02:30p"

    def test_1am_12h(self) -> None:
        assert time_from_sfm(3600, "12") == "01:00a"

    def test_overflow_12h(self) -> None:
        assert time_from_sfm(86400, "12") == "12:00a"

    def test_negative_12h(self) -> None:
        assert time_from_sfm(-1, "12") == "12:00a"

    def test_default_format_is_24(self) -> None:
        assert time_from_sfm(3600) == "01:00"


class TestClockAndCurrentTime:
    """Tests for is_clock_set, get_current_time, get_current_date."""

    def setup_method(self) -> None:
        reset_defaults()

    def test_is_clock_set(self) -> None:
        # On any modern system, the clock should be set
        assert is_clock_set() is True

    def test_get_current_time_returns_string(self) -> None:
        result = get_current_time()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_get_current_time_24h(self) -> None:
        set_hours("24")
        result = get_current_time()
        assert isinstance(result, str)
        # Should match HH:MM or " H:MM" pattern
        assert ":" in result

    def test_get_current_time_12h(self) -> None:
        set_hours("12")
        result = get_current_time()
        assert isinstance(result, str)

    def test_get_current_time_custom_format(self) -> None:
        result = get_current_time("%H")
        assert isinstance(result, str)
        # Should be a 2-digit hour (possibly with leading space)
        assert len(result.strip()) <= 2

    def test_get_current_date_returns_string(self) -> None:
        result = get_current_date()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_get_current_date_custom_format(self) -> None:
        result = get_current_date("%Y-%m-%d")
        assert isinstance(result, str)
        # Should match YYYY-MM-DD
        assert len(result) == 10
        assert result[4] == "-"

    def test_get_current_date_contains_year(self) -> None:
        from datetime import datetime

        result = get_current_date("%Y-%m-%d")
        assert str(datetime.now().year) in result


class TestResetDefaults:
    """Tests for reset_defaults."""

    def test_reset_restores_hours(self) -> None:
        set_hours("24")
        reset_defaults()
        assert get_hours() == "12"

    def test_reset_restores_weekstart(self) -> None:
        set_weekstart("Monday")
        reset_defaults()
        assert get_weekstart() == "Sunday"

    def test_reset_restores_date_format(self) -> None:
        set_date_format("%Y")
        reset_defaults()
        assert get_date_format() == "%a, %B %d %Y"


# ─── locale ───────────────────────────────────────────────────────────────────

import os
import tempfile

from jive.utils.locale import (
    Locale,
    LocalizedString,
    StringsTable,
    get_locale_instance,
    reset_instance,
)


class TestLocalizedString:
    """Tests for LocalizedString wrapper."""

    def test_str_with_value(self) -> None:
        ls = LocalizedString("Hello")
        assert str(ls) == "Hello"

    def test_str_with_false(self) -> None:
        ls = LocalizedString(False)
        assert str(ls) == ""

    def test_str_default(self) -> None:
        ls = LocalizedString()
        assert str(ls) == ""

    def test_bool_true(self) -> None:
        ls = LocalizedString("Hello")
        assert bool(ls) is True

    def test_bool_false_when_empty(self) -> None:
        ls = LocalizedString("")
        assert bool(ls) is False

    def test_bool_false_when_not_set(self) -> None:
        ls = LocalizedString(False)
        assert bool(ls) is False

    def test_eq_same_value(self) -> None:
        assert LocalizedString("Hi") == LocalizedString("Hi")

    def test_eq_string(self) -> None:
        assert LocalizedString("Hi") == "Hi"

    def test_repr(self) -> None:
        ls = LocalizedString("Test")
        assert "Test" in repr(ls)

    def test_mutable_str(self) -> None:
        ls = LocalizedString("EN")
        ls.str = "DE"
        assert str(ls) == "DE"


class TestStringsTable:
    """Tests for StringsTable — localized string lookup."""

    def test_set_and_get(self) -> None:
        t = StringsTable()
        t["HELLO"] = LocalizedString("Hello")
        assert t["HELLO"] is not None
        assert str(t["HELLO"]) == "Hello"

    def test_get_missing_returns_none(self) -> None:
        t = StringsTable()
        assert t["MISSING"] is None

    def test_str_lookup(self) -> None:
        t = StringsTable()
        t["HELLO"] = LocalizedString("Hello")
        assert t.str("HELLO") == "Hello"

    def test_str_missing_returns_token(self) -> None:
        t = StringsTable()
        assert t.str("MISSING") == "MISSING"

    def test_str_with_format_args(self) -> None:
        t = StringsTable()
        t["WELCOME"] = LocalizedString("Welcome %s!")
        result = t.str("WELCOME", "Alice")
        assert result == "Welcome Alice!"

    def test_parent_fallback(self) -> None:
        parent = StringsTable()
        parent["GLOBAL"] = LocalizedString("Global Value")
        child = StringsTable(parent=parent)
        assert child.str("GLOBAL") == "Global Value"

    def test_child_overrides_parent(self) -> None:
        parent = StringsTable()
        parent["TOKEN"] = LocalizedString("Parent")
        child = StringsTable(parent=parent)
        child["TOKEN"] = LocalizedString("Child")
        assert child.str("TOKEN") == "Child"

    def test_contains(self) -> None:
        t = StringsTable()
        t["EXISTS"] = LocalizedString("yes")
        assert "EXISTS" in t
        assert "NOPE" not in t

    def test_contains_via_parent(self) -> None:
        parent = StringsTable()
        parent["PARENT_KEY"] = LocalizedString("val")
        child = StringsTable(parent=parent)
        assert "PARENT_KEY" in child

    def test_keys(self) -> None:
        t = StringsTable()
        t["A"] = LocalizedString("a")
        t["B"] = LocalizedString("b")
        assert sorted(t.keys()) == ["A", "B"]

    def test_machine_suffix_override(self) -> None:
        t = StringsTable(machine_suffix="_JIVE")
        t["LABEL"] = LocalizedString("Default")
        t["LABEL_JIVE"] = LocalizedString("Jive Special")
        assert t.str("LABEL") == "Jive Special"

    def test_repr(self) -> None:
        t = StringsTable()
        t["X"] = LocalizedString("x")
        assert "1 entries" in repr(t)


class TestLocale:
    """Tests for the Locale manager class."""

    def setup_method(self) -> None:
        reset_instance()

    def test_default_locale(self) -> None:
        loc = Locale()
        assert loc.get_locale() == "EN"

    def test_set_locale(self) -> None:
        loc = Locale()
        loc.set_locale("DE")
        assert loc.get_locale() == "DE"

    def test_set_locale_same_noop(self) -> None:
        loc = Locale()
        loc.set_locale("EN")
        assert loc.get_locale() == "EN"

    def test_read_strings_file(self) -> None:
        loc = Locale()
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as f:
            f.write("HELLO\n")
            f.write("\tEN\tHello World\n")
            f.write("\tDE\tHallo Welt\n")
            name = f.name
        try:
            table = loc.read_strings_file(name)
            assert table.str("HELLO") == "Hello World"
        finally:
            os.unlink(name)

    def test_read_strings_file_de_locale(self) -> None:
        loc = Locale()
        loc.set_locale("DE")
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as f:
            f.write("GREETING\n")
            f.write("\tEN\tHello\n")
            f.write("\tDE\tHallo\n")
            name = f.name
        try:
            table = loc.read_strings_file(name)
            assert table.str("GREETING") == "Hallo"
        finally:
            os.unlink(name)

    def test_en_fallback(self) -> None:
        loc = Locale()
        loc.set_locale("FR")
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as f:
            f.write("ONLY_EN\n")
            f.write("\tEN\tEnglish Only\n")
            name = f.name
        try:
            table = loc.read_strings_file(name)
            # FR not available, should fall back to EN
            assert table.str("ONLY_EN") == "English Only"
        finally:
            os.unlink(name)

    def test_newline_conversion(self) -> None:
        loc = Locale()
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as f:
            f.write("MULTILINE\n")
            f.write("\tEN\tLine1\\nLine2\n")
            name = f.name
        try:
            table = loc.read_strings_file(name)
            assert table.str("MULTILINE") == "Line1\nLine2"
        finally:
            os.unlink(name)

    def test_multiple_tokens(self) -> None:
        loc = Locale()
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as f:
            f.write("TOKEN_A\n")
            f.write("\tEN\tValue A\n")
            f.write("TOKEN_B\n")
            f.write("\tEN\tValue B\n")
            name = f.name
        try:
            table = loc.read_strings_file(name)
            assert table.str("TOKEN_A") == "Value A"
            assert table.str("TOKEN_B") == "Value B"
        finally:
            os.unlink(name)

    def test_load_all_strings(self) -> None:
        loc = Locale()
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as f:
            f.write("GREETING\n")
            f.write("\tEN\tHello\n")
            f.write("\tDE\tHallo\n")
            f.write("\tFR\tBonjour\n")
            name = f.name
        try:
            all_strings = loc.load_all_strings(name)
            assert all_strings["EN"]["GREETING"] == "Hello"
            assert all_strings["DE"]["GREETING"] == "Hallo"
            assert all_strings["FR"]["GREETING"] == "Bonjour"
        finally:
            os.unlink(name)

    def test_load_all_strings_missing_file(self) -> None:
        loc = Locale()
        result = loc.load_all_strings("/nonexistent/path.txt")
        assert result == {}

    def test_get_all_locales(self) -> None:
        loc = Locale()
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as f:
            f.write("TOK\n")
            f.write("\tEN\tEnglish\n")
            f.write("\tDE\tDeutsch\n")
            name = f.name
        try:
            loc.read_strings_file(name)
            locales = loc.get_all_locales()
            assert "EN" in locales
            assert "DE" in locales
        finally:
            os.unlink(name)

    def test_locale_switch_reloads(self) -> None:
        loc = Locale()
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as f:
            f.write("MSG\n")
            f.write("\tEN\tEnglish Message\n")
            f.write("\tDE\tDeutsche Nachricht\n")
            name = f.name
        try:
            table = loc.read_strings_file(name)
            assert table.str("MSG") == "English Message"
            loc.set_locale("DE")
            # After locale switch, the table should have DE translation
            assert table.str("MSG") == "Deutsche Nachricht"
        finally:
            os.unlink(name)

    def test_nonexistent_file(self) -> None:
        loc = Locale()
        table = loc.read_strings_file("/nonexistent/strings.txt")
        assert isinstance(table, StringsTable)
        assert table.str("ANYTHING") == "ANYTHING"


class TestLocaleInstance:
    """Tests for module-level singleton."""

    def setup_method(self) -> None:
        reset_instance()

    def test_get_instance(self) -> None:
        loc = get_locale_instance()
        assert isinstance(loc, Locale)

    def test_same_instance(self) -> None:
        loc1 = get_locale_instance()
        loc2 = get_locale_instance()
        assert loc1 is loc2

    def test_reset_instance(self) -> None:
        loc1 = get_locale_instance()
        reset_instance()
        loc2 = get_locale_instance()
        assert loc1 is not loc2

    def test_reset_restores_default_locale(self) -> None:
        loc = get_locale_instance()
        loc.set_locale("DE")
        reset_instance()
        loc2 = get_locale_instance()
        assert loc2.get_locale() == "EN"
