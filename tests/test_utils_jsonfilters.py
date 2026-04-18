"""Tests for jive.utils.jsonfilters — JSON encode/decode LTN12-style filters."""

from __future__ import annotations

import json

import pytest

from jive.utils.jsonfilters import decode, encode


class TestDecode:
    """Tests for the decode() filter function."""

    def test_none_returns_none(self) -> None:
        assert decode(None) is None

    def test_empty_string_returns_empty_string(self) -> None:
        result = decode("")
        assert result == ""
        assert isinstance(result, str)

    def test_empty_bytes_returns_empty_string(self) -> None:
        result = decode(b"")
        assert result == ""

    def test_dict(self) -> None:
        assert decode('{"a": 1}') == {"a": 1}

    def test_list(self) -> None:
        assert decode("[1,2,3]") == [1, 2, 3]

    def test_string(self) -> None:
        assert decode('"hello"') == "hello"

    def test_integer(self) -> None:
        assert decode("42") == 42

    def test_float(self) -> None:
        assert decode("3.14") == pytest.approx(3.14)

    def test_boolean_true(self) -> None:
        assert decode("true") is True

    def test_boolean_false(self) -> None:
        assert decode("false") is False

    def test_json_null(self) -> None:
        # JSON "null" decodes to Python None — distinct from passing None as chunk
        assert decode("null") is None

    def test_nested_dict(self) -> None:
        assert decode('{"a":{"b":2}}') == {"a": {"b": 2}}

    def test_bytes_input(self) -> None:
        assert decode(b'{"a":1}') == {"a": 1}

    def test_bytes_list(self) -> None:
        assert decode(b"[1,2,3]") == [1, 2, 3]

    def test_unicode_string(self) -> None:
        assert decode('"caf\\u00e9"') == "café"

    def test_invalid_json_raises(self) -> None:
        with pytest.raises(json.JSONDecodeError):
            decode("invalid")

    def test_invalid_json_partial_raises(self) -> None:
        with pytest.raises(json.JSONDecodeError):
            decode("{bad")

    def test_whitespace_around_json(self) -> None:
        assert decode("  42  ") == 42

    def test_empty_dict(self) -> None:
        assert decode("{}") == {}

    def test_empty_list(self) -> None:
        assert decode("[]") == []


class TestEncode:
    """Tests for the encode() filter function."""

    def test_none_returns_none(self) -> None:
        assert encode(None) is None

    def test_empty_string_returns_empty_string(self) -> None:
        result = encode("")
        assert result == ""
        assert isinstance(result, str)

    def test_dict_compact(self) -> None:
        result = encode({"a": 1})
        assert result == '{"a":1}'

    def test_list_compact(self) -> None:
        assert encode([1, 2, 3]) == "[1,2,3]"

    def test_string(self) -> None:
        assert encode("hello") == '"hello"'

    def test_integer(self) -> None:
        assert encode(42) == "42"

    def test_float(self) -> None:
        assert encode(3.14) == "3.14"

    def test_boolean_true(self) -> None:
        assert encode(True) == "true"

    def test_boolean_false(self) -> None:
        assert encode(False) == "false"

    def test_nested_dict_compact(self) -> None:
        result = encode({"a": {"b": 2}})
        parsed = json.loads(result)
        assert parsed == {"a": {"b": 2}}
        # Verify compact — no spaces after separators
        assert ": " not in result
        assert ", " not in result

    def test_empty_dict(self) -> None:
        assert encode({}) == "{}"

    def test_empty_list(self) -> None:
        assert encode([]) == "[]"

    def test_unicode_preserved(self) -> None:
        # ensure_ascii=False means unicode chars are kept as-is
        result = encode("café")
        assert "café" in result

    def test_not_json_serializable_raises(self) -> None:
        with pytest.raises(TypeError):
            encode(object())


class TestRoundTrip:
    """Verify decode(encode(obj)) == obj for various types."""

    @pytest.mark.parametrize(
        "obj",
        [
            {"a": 1, "b": [2, 3]},
            [1, "two", 3.0, True, False, None],
            "hello",
            42,
            3.14,
            True,
            False,
            [],
            {},
            {"nested": {"deep": {"value": 99}}},
        ],
        ids=[
            "dict_with_list",
            "mixed_list",
            "string",
            "int",
            "float",
            "true",
            "false",
            "empty_list",
            "empty_dict",
            "deeply_nested",
        ],
    )
    def test_round_trip(self, obj: object) -> None:
        assert decode(encode(obj)) == obj

    def test_round_trip_none_passthrough(self) -> None:
        # None round-trips as None (LTN12 end-of-stream)
        assert encode(None) is None
        assert decode(None) is None

    def test_round_trip_empty_string_passthrough(self) -> None:
        assert decode(encode("")) == ""
