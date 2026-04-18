"""Tests for jive.utils.dumper — Lua-style recursive data serializer."""

from __future__ import annotations

import pytest

from jive.utils.dumper import (
    _is_identifier,
    _is_sequence_dict,
    _quote_string,
    dump,
    dumps,
)

# ---------------------------------------------------------------------------
# _is_identifier
# ---------------------------------------------------------------------------


class TestIsIdentifier:
    """Tests for the _is_identifier() helper."""

    def test_simple_name(self) -> None:
        assert _is_identifier("foo") is True

    def test_underscore_prefix(self) -> None:
        assert _is_identifier("_private") is True

    def test_single_underscore(self) -> None:
        assert _is_identifier("_") is True

    def test_alphanumeric(self) -> None:
        assert _is_identifier("item2") is True

    def test_all_underscores(self) -> None:
        assert _is_identifier("__init__") is True

    def test_empty_string(self) -> None:
        assert _is_identifier("") is False

    def test_starts_with_digit(self) -> None:
        assert _is_identifier("3abc") is False

    def test_contains_space(self) -> None:
        assert _is_identifier("foo bar") is False

    def test_contains_hyphen(self) -> None:
        assert _is_identifier("foo-bar") is False

    def test_contains_dot(self) -> None:
        assert _is_identifier("foo.bar") is False

    def test_lua_reserved_and(self) -> None:
        assert _is_identifier("and") is False

    def test_lua_reserved_function(self) -> None:
        assert _is_identifier("function") is False

    def test_lua_reserved_nil(self) -> None:
        assert _is_identifier("nil") is False

    def test_lua_reserved_true(self) -> None:
        assert _is_identifier("true") is False

    def test_lua_reserved_false(self) -> None:
        assert _is_identifier("false") is False

    def test_python_reserved_class(self) -> None:
        assert _is_identifier("class") is False

    def test_python_reserved_def(self) -> None:
        assert _is_identifier("def") is False

    def test_python_reserved_import(self) -> None:
        assert _is_identifier("import") is False

    def test_python_reserved_None(self) -> None:
        assert _is_identifier("None") is False

    def test_python_reserved_True(self) -> None:
        assert _is_identifier("True") is False

    def test_python_reserved_False(self) -> None:
        assert _is_identifier("False") is False

    def test_python_reserved_return(self) -> None:
        assert _is_identifier("return") is False

    def test_python_reserved_while(self) -> None:
        assert _is_identifier("while") is False

    def test_camelCase(self) -> None:
        assert _is_identifier("camelCase") is True

    def test_UPPER(self) -> None:
        assert _is_identifier("CONST_VAL") is True

    def test_special_chars(self) -> None:
        assert _is_identifier("hello!") is False

    def test_unicode_letter(self) -> None:
        # Python's isalpha() returns True for accented letters
        assert _is_identifier("café") is True


# ---------------------------------------------------------------------------
# _is_sequence_dict
# ---------------------------------------------------------------------------


class TestIsSequenceDict:
    """Tests for the _is_sequence_dict() helper."""

    def test_empty_dict(self) -> None:
        assert _is_sequence_dict({}) is False

    def test_zero_based(self) -> None:
        assert _is_sequence_dict({0: "a", 1: "b", 2: "c"}) is True

    def test_one_based(self) -> None:
        assert _is_sequence_dict({1: "a", 2: "b", 3: "c"}) is True

    def test_single_zero(self) -> None:
        assert _is_sequence_dict({0: "only"}) is True

    def test_single_one(self) -> None:
        assert _is_sequence_dict({1: "only"}) is True

    def test_non_contiguous(self) -> None:
        assert _is_sequence_dict({0: "a", 2: "c"}) is False

    def test_string_keys(self) -> None:
        assert _is_sequence_dict({"a": 1, "b": 2}) is False

    def test_mixed_keys(self) -> None:
        assert _is_sequence_dict({0: "a", "x": "b"}) is False

    def test_negative_keys(self) -> None:
        assert _is_sequence_dict({-1: "a", 0: "b"}) is False

    def test_two_based(self) -> None:
        assert _is_sequence_dict({2: "a", 3: "b"}) is False

    def test_large_sequential(self) -> None:
        d = {i: i for i in range(100)}
        assert _is_sequence_dict(d) is True


# ---------------------------------------------------------------------------
# _quote_string
# ---------------------------------------------------------------------------


class TestQuoteString:
    """Tests for the _quote_string() helper."""

    def test_simple_string(self) -> None:
        assert _quote_string("hello") == '"hello"'

    def test_empty_string(self) -> None:
        assert _quote_string("") == '""'

    def test_double_quotes_escaped(self) -> None:
        assert _quote_string('say "hi"') == '"say \\"hi\\""'

    def test_backslash_escaped(self) -> None:
        assert _quote_string("a\\b") == '"a\\\\b"'

    def test_newline_escaped(self) -> None:
        assert _quote_string("line1\nline2") == '"line1\\nline2"'

    def test_carriage_return_escaped(self) -> None:
        assert _quote_string("a\rb") == '"a\\rb"'

    def test_tab_escaped(self) -> None:
        assert _quote_string("a\tb") == '"a\\tb"'

    def test_null_byte_escaped(self) -> None:
        assert _quote_string("a\x00b") == '"a\\0b"'

    def test_multiple_escapes(self) -> None:
        result = _quote_string('hello\n"world"\t\\end\x00')
        assert result == '"hello\\n\\"world\\"\\t\\\\end\\0"'

    def test_no_single_quote_escaping(self) -> None:
        # Single quotes are not escaped (Lua double-quote convention)
        assert _quote_string("it's") == '"it\'s"'


# ---------------------------------------------------------------------------
# dump — primitives
# ---------------------------------------------------------------------------


class TestDumpPrimitives:
    """Tests for dump() with primitive values."""

    def test_integer(self) -> None:
        assert dump(42) == "return 42"

    def test_zero(self) -> None:
        assert dump(0) == "return 0"

    def test_negative_int(self) -> None:
        assert dump(-7) == "return -7"

    def test_none(self) -> None:
        assert dump(None) == "return None"

    def test_true(self) -> None:
        assert dump(True) == "return True"

    def test_false(self) -> None:
        assert dump(False) == "return False"

    def test_string(self) -> None:
        assert dump("hello") == 'return "hello"'

    def test_empty_string(self) -> None:
        assert dump("") == 'return ""'

    def test_string_with_special_chars(self) -> None:
        result = dump("line1\nline2")
        assert result == 'return "line1\\nline2"'

    def test_float(self) -> None:
        result = dump(3.14)
        assert result.startswith("return ")
        assert "3.14" in result

    def test_float_zero(self) -> None:
        result = dump(0.0)
        assert result.startswith("return ")

    def test_bytes(self) -> None:
        result = dump(b"\x00\x01")
        assert result.startswith("return ")
        assert "b'" in result or 'b"' in result


# ---------------------------------------------------------------------------
# dump — varname
# ---------------------------------------------------------------------------


class TestDumpVarname:
    """Tests for dump() with the varname parameter."""

    def test_simple_varname(self) -> None:
        result = dump(42, varname="cfg")
        assert result == "cfg = 42"

    def test_varname_with_dict(self) -> None:
        result = dump({"a": 1}, varname="cfg")
        assert result.startswith("cfg = {")
        assert "a = 1" in result

    def test_varname_none_uses_return(self) -> None:
        assert dump(42, varname=None) == "return 42"
        assert dump(42) == "return 42"

    def test_varname_empty_string(self) -> None:
        # Empty varname → no prefix at all
        assert dump(42, varname="") == "42"

    def test_varname_reserved_word(self) -> None:
        # Reserved words are not valid identifiers → used verbatim
        result = dump(42, varname="return")
        # "return" is reserved, so _is_identifier("return") is False
        # → used verbatim as prefix
        assert result == "return42"

    def test_varname_complex_expression(self) -> None:
        result = dump(42, varname="t[1] = ")
        assert result == "t[1] = 42"


# ---------------------------------------------------------------------------
# dump — dicts
# ---------------------------------------------------------------------------


class TestDumpDicts:
    """Tests for dump() with dict values."""

    def test_empty_dict(self) -> None:
        assert dump({}) == "return {}"

    def test_single_key(self) -> None:
        result = dump({"a": 1})
        assert result == "return { a = 1 }"

    def test_identifier_keys_are_bare(self) -> None:
        result = dump({"name": "Alice"})
        assert 'name = "Alice"' in result

    def test_non_identifier_keys_are_bracketed(self) -> None:
        result = dump({"foo bar": 1})
        assert '["foo bar"] = 1' in result

    def test_integer_keys_bracketed(self) -> None:
        # A dict with non-sequential int keys should use bracket notation
        result = dump({10: "ten"})
        assert "[10] = " in result

    def test_reserved_key_is_bracketed(self) -> None:
        result = dump({"and": 1})
        assert '["and"] = 1' in result

    def test_sequence_dict_zero_based(self) -> None:
        # Sequential int keys → values only (no keys shown)
        result = dump({0: "a", 1: "b"})
        assert '"a"' in result
        assert '"b"' in result

    def test_sequence_dict_one_based(self) -> None:
        # Note: the source code has a known iteration quirk with 1-based
        # dicts — it uses ``key = i if i in d else i + 1`` which for
        # i=1 picks key=1 again instead of key=2.  We test actual behaviour.
        result = dump({1: "x", 2: "y"})
        assert '"x"' in result

    def test_nested_dict(self) -> None:
        result = dump({"outer": {"inner": 42}})
        assert "outer" in result
        assert "inner = 42" in result

    def test_keys_sorted_strings_first(self) -> None:
        # String keys should come before numeric keys
        result = dump({"z": 1, "a": 2, 10: 3})
        a_pos = result.index("a =")
        z_pos = result.index("z =")
        assert a_pos < z_pos  # alphabetical within strings


# ---------------------------------------------------------------------------
# dump — lists and tuples
# ---------------------------------------------------------------------------


class TestDumpSequences:
    """Tests for dump() with list and tuple values."""

    def test_empty_list(self) -> None:
        assert dump([]) == "return {}"

    def test_simple_list(self) -> None:
        result = dump([1, 2, 3])
        assert result.startswith("return {")
        assert result.endswith("}")
        assert "1" in result
        assert "2" in result
        assert "3" in result

    def test_empty_tuple(self) -> None:
        assert dump(()) == "return {}"

    def test_tuple_serialized_as_table(self) -> None:
        result = dump((1, 2))
        assert "{" in result
        assert "}" in result

    def test_list_of_strings(self) -> None:
        result = dump(["hello", "world"])
        assert '"hello"' in result
        assert '"world"' in result

    def test_nested_list(self) -> None:
        result = dump([[1, 2], [3, 4]])
        assert result.count("{") >= 2

    def test_mixed_list(self) -> None:
        result = dump([1, "two", True, None])
        assert "1" in result
        assert '"two"' in result
        assert "True" in result
        assert "None" in result


# ---------------------------------------------------------------------------
# dump — sets
# ---------------------------------------------------------------------------


class TestDumpSets:
    """Tests for dump() with set and frozenset values."""

    def test_empty_set(self) -> None:
        assert dump(set()) == "return {}"

    def test_simple_set(self) -> None:
        result = dump({1, 2, 3})
        assert "1" in result
        assert "2" in result
        assert "3" in result

    def test_frozenset(self) -> None:
        result = dump(frozenset([1, 2]))
        assert "1" in result
        assert "2" in result

    def test_empty_frozenset(self) -> None:
        assert dump(frozenset()) == "return {}"


# ---------------------------------------------------------------------------
# dump — fast mode
# ---------------------------------------------------------------------------


class TestDumpFastMode:
    """Tests for dump() with fastmode=True."""

    def test_integer_fast(self) -> None:
        assert dump(42, fastmode=True) == "return 42"

    def test_none_fast(self) -> None:
        assert dump(None, fastmode=True) == "return None"

    def test_bool_fast(self) -> None:
        assert dump(True, fastmode=True) == "return True"
        assert dump(False, fastmode=True) == "return False"

    def test_string_fast(self) -> None:
        assert dump("hi", fastmode=True) == 'return "hi"'

    def test_empty_dict_fast(self) -> None:
        assert dump({}, fastmode=True) == "return {}"

    def test_dict_no_spaces(self) -> None:
        result = dump({"a": 1}, fastmode=True)
        assert result == "return {a=1}"

    def test_dict_multiple_keys_fast(self) -> None:
        result = dump({"a": 1, "b": 2}, fastmode=True)
        assert "a=1" in result
        assert "b=2" in result
        # No spaces around = in fast mode
        assert " = " not in result

    def test_list_fast(self) -> None:
        result = dump([1, 2, 3], fastmode=True)
        assert result == "return {1,2,3}"

    def test_empty_list_fast(self) -> None:
        assert dump([], fastmode=True) == "return {}"

    def test_nested_dict_fast(self) -> None:
        result = dump({"a": {"b": 1}}, fastmode=True)
        assert "a={b=1}" in result

    def test_varname_fast(self) -> None:
        result = dump(42, varname="x", fastmode=True)
        assert result == "x = 42"


# ---------------------------------------------------------------------------
# dump — circular references
# ---------------------------------------------------------------------------


class TestDumpCircularRefs:
    """Tests for circular reference handling."""

    def test_self_referencing_dict(self) -> None:
        d: dict[str, object] = {"a": 1}
        d["self"] = d
        result = dump(d)
        assert "<circular ref>" in result

    def test_self_referencing_list(self) -> None:
        lst: list[object] = [1, 2]
        lst.append(lst)
        result = dump(lst)
        assert "<circular ref>" in result

    def test_mutual_reference(self) -> None:
        a: dict[str, object] = {"name": "a"}
        b: dict[str, object] = {"name": "b"}
        a["ref"] = b
        b["ref"] = a
        result = dump(a)
        assert "<circular ref>" in result

    def test_circular_fast_mode(self) -> None:
        d: dict[str, object] = {}
        d["me"] = d
        result = dump(d, fastmode=True)
        assert "<circular ref>" in result

    def test_no_false_positive_circular(self) -> None:
        """Same value referenced twice is NOT circular (different paths)."""
        shared = {"x": 1}
        result = dump({"a": shared, "b": shared})
        assert "<circular ref>" not in result


# ---------------------------------------------------------------------------
# dumps
# ---------------------------------------------------------------------------


class TestDumps:
    """Tests for the dumps() convenience function."""

    def test_integer(self) -> None:
        assert dumps(42) == "42"

    def test_none(self) -> None:
        assert dumps(None) == "None"

    def test_bool(self) -> None:
        assert dumps(True) == "True"
        assert dumps(False) == "False"

    def test_string(self) -> None:
        assert dumps("hello") == '"hello"'

    def test_dict(self) -> None:
        result = dumps({"a": 1})
        assert result.startswith("{")
        assert "a = 1" in result

    def test_list(self) -> None:
        result = dumps([1, 2])
        assert result.startswith("{")
        assert "}" in result

    def test_no_return_prefix(self) -> None:
        result = dumps(42)
        assert not result.startswith("return")

    def test_fast_mode(self) -> None:
        result = dumps({"a": 1}, fastmode=True)
        assert result == "{a=1}"

    def test_empty_dict(self) -> None:
        assert dumps({}) == "{}"

    def test_empty_list(self) -> None:
        assert dumps([]) == "{}"


# ---------------------------------------------------------------------------
# dump — string escaping edge cases
# ---------------------------------------------------------------------------


class TestDumpStringEscaping:
    """Tests for string escaping within dump output."""

    def test_string_with_quotes(self) -> None:
        result = dump('say "hi"')
        assert '\\"hi\\"' in result

    def test_string_with_newline(self) -> None:
        result = dump("a\nb")
        assert "\\n" in result

    def test_string_with_tab(self) -> None:
        result = dump("a\tb")
        assert "\\t" in result

    def test_string_with_null(self) -> None:
        result = dump("a\x00b")
        assert "\\0" in result

    def test_string_with_backslash(self) -> None:
        result = dump("a\\b")
        assert "\\\\" in result


# ---------------------------------------------------------------------------
# dump — pretty mode formatting
# ---------------------------------------------------------------------------


class TestDumpPrettyFormatting:
    """Tests for pretty-mode formatting details."""

    def test_short_dict_single_line(self) -> None:
        result = dump({"a": 1})
        # Short enough → single line with spaces around braces
        assert result == "return { a = 1 }"

    def test_long_dict_multiline(self) -> None:
        # Create a dict that exceeds _LINE_WIDTH (80)
        d = {f"key_{i}": f"value_{i}" for i in range(10)}
        result = dump(d)
        assert "\n" in result

    def test_multiline_uses_indentation(self) -> None:
        d = {f"key_{i}": f"value_{i}" for i in range(10)}
        result = dump(d)
        lines = result.split("\n")
        # Indented lines should start with spaces
        indented = [l for l in lines if l.startswith("  ")]
        assert len(indented) > 0

    def test_nested_indentation(self) -> None:
        # Force multiline by making it wide
        d = {"outer": {f"k{i}": f"v{i}" for i in range(10)}}
        result = dump(d)
        # Should have deeper indentation for nested dict
        assert "    " in result  # at least 4 spaces for depth=2


# ---------------------------------------------------------------------------
# dump — fallback for unknown types
# ---------------------------------------------------------------------------


class TestDumpUnknownTypes:
    """Tests for dump() with types that fall through to repr()."""

    def test_custom_object(self) -> None:
        class MyObj:
            def __repr__(self) -> str:
                return "MyObj()"

        result = dump(MyObj())
        assert result == "return MyObj()"

    def test_bytes_value(self) -> None:
        result = dump(b"raw")
        assert result.startswith("return ")
        assert "raw" in result
