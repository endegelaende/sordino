"""Tests for jive.utils.string_utils — string utility functions."""

from __future__ import annotations

import pytest

from jive.utils.string_utils import (
    match_literal,
    split,
    str2hex,
    trim_null,
    url_decode,
    url_encode,
)

# ---------------------------------------------------------------------------
# str2hex
# ---------------------------------------------------------------------------


class TestStr2Hex:
    """Tests for str2hex()."""

    def test_ascii_letters(self) -> None:
        assert str2hex("ABC") == "41 42 43 "

    def test_empty_string(self) -> None:
        assert str2hex("") == ""

    def test_single_char(self) -> None:
        assert str2hex("A") == "41 "

    def test_bytes_input(self) -> None:
        assert str2hex(b"\x00\xff") == "00 FF "

    def test_null_byte_in_string(self) -> None:
        assert str2hex("\x00") == "00 "

    def test_space_character(self) -> None:
        assert str2hex(" ") == "20 "

    def test_digits(self) -> None:
        assert str2hex("09") == "30 39 "

    def test_mixed_bytes(self) -> None:
        assert str2hex(b"\x41\x00\x7f") == "41 00 7F "

    def test_trailing_space_present(self) -> None:
        """Every hex value is followed by a space, including the last one."""
        result = str2hex("A")
        assert result.endswith(" ")

    def test_bytes_empty(self) -> None:
        assert str2hex(b"") == ""

    def test_high_latin1_char(self) -> None:
        # é is 0xE9 in latin-1
        assert str2hex("é") == "E9 "


# ---------------------------------------------------------------------------
# trim_null
# ---------------------------------------------------------------------------


class TestTrimNull:
    """Tests for trim_null()."""

    def test_null_in_middle(self) -> None:
        assert trim_null("hello\x00world") == "hello"

    def test_no_null(self) -> None:
        assert trim_null("no nulls here") == "no nulls here"

    def test_leading_null(self) -> None:
        assert trim_null("\x00leading") == ""

    def test_empty_string(self) -> None:
        assert trim_null("") == ""

    def test_trailing_null(self) -> None:
        assert trim_null("trailing\x00") == "trailing"

    def test_multiple_nulls(self) -> None:
        """Should trim at the *first* null byte."""
        assert trim_null("a\x00b\x00c") == "a"

    def test_only_null(self) -> None:
        assert trim_null("\x00") == ""

    def test_two_consecutive_nulls(self) -> None:
        assert trim_null("ok\x00\x00") == "ok"


# ---------------------------------------------------------------------------
# split
# ---------------------------------------------------------------------------


class TestSplit:
    """Tests for split()."""

    def test_comma_split(self) -> None:
        assert split(",", "a,b,c") == ["a", "b", "c"]

    def test_empty_pattern_splits_chars(self) -> None:
        assert split("", "abc") == ["a", "b", "c"]

    def test_empty_string(self) -> None:
        assert split(",", "") == [""]

    def test_empty_pattern_empty_string(self) -> None:
        assert split("", "") == []

    def test_no_delimiter_found(self) -> None:
        assert split(",", "no-commas") == ["no-commas"]

    def test_append_to_existing_list(self) -> None:
        existing: list[str] = ["x"]
        result = split(",", "a,b", existing)
        assert result == ["x", "a", "b"]
        assert result is existing

    def test_consecutive_delimiters(self) -> None:
        assert split(",", "a,,b") == ["a", "", "b"]

    def test_delimiter_at_start(self) -> None:
        assert split(",", ",a,b") == ["", "a", "b"]

    def test_delimiter_at_end(self) -> None:
        assert split(",", "a,b,") == ["a", "b", ""]

    def test_multi_char_delimiter(self) -> None:
        assert split("::", "a::b::c") == ["a", "b", "c"]

    def test_single_element(self) -> None:
        assert split(",", "only") == ["only"]

    def test_returns_new_list_when_none(self) -> None:
        result = split(",", "a,b")
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# match_literal
# ---------------------------------------------------------------------------


class TestMatchLiteral:
    """Tests for match_literal()."""

    def test_basic_match(self) -> None:
        assert match_literal("hello world", "world") == "world"

    def test_no_match(self) -> None:
        assert match_literal("hello world", "xyz") is None

    def test_regex_special_chars_treated_as_literal(self) -> None:
        """Parentheses and other regex metacharacters must not be interpreted."""
        assert match_literal("file (1).txt", "(1)") == "(1)"

    def test_dot_is_literal(self) -> None:
        assert match_literal("file.txt", ".txt") == ".txt"
        # A regex dot would match any char; make sure "Xtxt" doesn't match ".txt"
        assert match_literal("Xtxt", ".txt") is None

    def test_with_init_offset(self) -> None:
        assert match_literal("hello world", "world", 6) == "world"

    def test_init_offset_skips_earlier_match(self) -> None:
        assert match_literal("abab", "ab", 1) == "ab"

    def test_init_past_end(self) -> None:
        assert match_literal("hello world", "world", 99) is None

    def test_negative_init(self) -> None:
        # -5 from end of "hello world" (len=11) → index 6
        assert match_literal("hello world", "world", -5) == "world"

    def test_negative_init_large(self) -> None:
        # Very negative init clamps to 0
        assert match_literal("hello", "hello", -100) == "hello"

    def test_empty_pattern(self) -> None:
        # Empty string is found at position 0
        assert match_literal("anything", "") == ""

    def test_empty_string_empty_pattern(self) -> None:
        assert match_literal("", "") == ""

    def test_empty_string_nonempty_pattern(self) -> None:
        assert match_literal("", "x") is None

    def test_match_at_start(self) -> None:
        assert match_literal("hello world", "hello") == "hello"

    def test_bracket_literal(self) -> None:
        assert match_literal("a[0]", "[0]") == "[0]"

    def test_backslash_literal(self) -> None:
        assert match_literal("path\\file", "\\") == "\\"

    def test_init_zero(self) -> None:
        assert match_literal("hello", "hello", 0) == "hello"


# ---------------------------------------------------------------------------
# url_encode
# ---------------------------------------------------------------------------


class TestUrlEncode:
    """Tests for url_encode()."""

    def test_space_becomes_plus(self) -> None:
        assert url_encode("hello world") == "hello+world"

    def test_special_chars(self) -> None:
        result = url_encode("a=1&b=2")
        assert result == "a%3D1%26b%3D2"

    def test_empty_string(self) -> None:
        assert url_encode("") == ""

    def test_safe_chars_unchanged(self) -> None:
        assert url_encode("already_safe_123") == "already_safe_123"

    def test_newline_converted(self) -> None:
        # \n → \r\n before encoding, then encoded as %0D%0A
        encoded = url_encode("a\nb")
        assert "%0D%0A" in encoded

    def test_slash_encoded(self) -> None:
        assert "%2F" in url_encode("/")

    def test_unicode_char(self) -> None:
        # Should not crash; should percent-encode
        result = url_encode("café")
        assert "caf" in result


# ---------------------------------------------------------------------------
# url_decode
# ---------------------------------------------------------------------------


class TestUrlDecode:
    """Tests for url_decode()."""

    def test_plus_becomes_space(self) -> None:
        assert url_decode("hello+world") == "hello world"

    def test_percent_encoding(self) -> None:
        assert url_decode("hello%20world") == "hello world"

    def test_hex_decoding(self) -> None:
        assert url_decode("%48%65%6C%6C%6F") == "Hello"

    def test_crlf_normalized(self) -> None:
        assert url_decode("line1%0D%0Aline2") == "line1\nline2"

    def test_already_decoded(self) -> None:
        assert url_decode("already decoded") == "already decoded"

    def test_empty_string(self) -> None:
        assert url_decode("") == ""

    def test_round_trip(self) -> None:
        original = "hello world & goodbye=true"
        assert url_decode(url_encode(original)) == original
