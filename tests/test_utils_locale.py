"""Tests for jive.utils.locale — localisation module with strings.txt parser."""

from __future__ import annotations

import pytest

from jive.utils.locale import (
    Locale,
    LocalizedString,
    StringsTable,
    _parse_strings_file,
    get_locale_instance,
    reset_instance,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_locale_singleton() -> None:
    """Ensure a fresh singleton for every test."""
    reset_instance()
    yield  # type: ignore[misc]
    reset_instance()


# ---------------------------------------------------------------------------
# LocalizedString
# ---------------------------------------------------------------------------


class TestLocalizedString:
    """Tests for the LocalizedString wrapper."""

    def test_str_returns_value(self) -> None:
        ls = LocalizedString("Hello")
        assert str(ls) == "Hello"

    def test_str_false_returns_empty(self) -> None:
        ls = LocalizedString(False)
        assert str(ls) == ""

    def test_str_default_is_false(self) -> None:
        ls = LocalizedString()
        assert str(ls) == ""

    def test_bool_true_for_nonempty(self) -> None:
        assert bool(LocalizedString("Hello")) is True

    def test_bool_false_for_false(self) -> None:
        assert bool(LocalizedString(False)) is False

    def test_bool_false_for_empty_string(self) -> None:
        assert bool(LocalizedString("")) is False

    def test_eq_with_str(self) -> None:
        ls = LocalizedString("Hello")
        assert ls == "Hello"
        assert ls != "Goodbye"

    def test_eq_with_localized_string(self) -> None:
        a = LocalizedString("Hello")
        b = LocalizedString("Hello")
        assert a == b

    def test_eq_different_values(self) -> None:
        a = LocalizedString("Hello")
        b = LocalizedString("World")
        assert a != b

    def test_eq_with_false(self) -> None:
        a = LocalizedString(False)
        b = LocalizedString(False)
        assert a == b

    def test_eq_not_implemented_for_other_types(self) -> None:
        ls = LocalizedString("Hello")
        assert ls != 42

    def test_hash(self) -> None:
        ls = LocalizedString("Hello")
        assert hash(ls) == hash("Hello")

    def test_hash_false(self) -> None:
        ls = LocalizedString(False)
        assert hash(ls) == hash(False)

    def test_hashable_in_set(self) -> None:
        a = LocalizedString("Hello")
        b = LocalizedString("Hello")
        s = {a, b}
        assert len(s) == 1

    def test_repr(self) -> None:
        ls = LocalizedString("Hello")
        assert repr(ls) == "LocalizedString('Hello')"

    def test_repr_false(self) -> None:
        ls = LocalizedString(False)
        assert repr(ls) == "LocalizedString(False)"

    def test_mutation(self) -> None:
        """LocalizedString.str can be changed after creation."""
        ls = LocalizedString("Hello")
        assert str(ls) == "Hello"
        ls.str = "Hallo"
        assert str(ls) == "Hallo"

    def test_mutation_to_false(self) -> None:
        ls = LocalizedString("Hello")
        ls.str = False
        assert str(ls) == ""
        assert bool(ls) is False


# ---------------------------------------------------------------------------
# StringsTable
# ---------------------------------------------------------------------------


class TestStringsTable:
    """Tests for the StringsTable dict-like string lookup."""

    def test_setitem_getitem(self) -> None:
        t = StringsTable()
        t["HELLO"] = LocalizedString("Hello")
        result = t["HELLO"]
        assert result is not None
        assert str(result) == "Hello"

    def test_getitem_missing_returns_none(self) -> None:
        t = StringsTable()
        assert t["MISSING"] is None

    def test_contains(self) -> None:
        t = StringsTable()
        t["HELLO"] = LocalizedString("Hello")
        assert "HELLO" in t
        assert "MISSING" not in t

    def test_len_empty(self) -> None:
        t = StringsTable()
        assert len(t) == 0

    def test_len(self) -> None:
        t = StringsTable()
        t["A"] = LocalizedString("a")
        t["B"] = LocalizedString("b")
        assert len(t) == 2

    def test_iter(self) -> None:
        t = StringsTable()
        t["A"] = LocalizedString("a")
        t["B"] = LocalizedString("b")
        keys = list(t)
        assert sorted(keys) == ["A", "B"]

    def test_get_with_default(self) -> None:
        t = StringsTable()
        assert t.get("MISSING", "fallback") == "fallback"

    def test_get_existing(self) -> None:
        t = StringsTable()
        t["HELLO"] = LocalizedString("Hello")
        result = t.get("HELLO", "fallback")
        assert result is not None
        assert str(result) == "Hello"

    def test_keys(self) -> None:
        t = StringsTable()
        t["A"] = LocalizedString("a")
        t["B"] = LocalizedString("b")
        assert sorted(t.keys()) == ["A", "B"]

    def test_str_lookup(self) -> None:
        t = StringsTable()
        t["HELLO"] = LocalizedString("Hello")
        result = t.str("HELLO")
        assert isinstance(result, LocalizedString)
        assert str(result) == "Hello"

    def test_str_missing_returns_token_name(self) -> None:
        t = StringsTable()
        result = t.str("MISSING")
        assert result == "MISSING"
        assert isinstance(result, str)

    def test_str_with_format_args_percent(self) -> None:
        t = StringsTable()
        t["WELCOME"] = LocalizedString("Welcome %s")
        result = t.str("WELCOME", "Alice")
        assert result == "Welcome Alice"
        assert isinstance(result, str)

    def test_str_with_format_args_multiple(self) -> None:
        t = StringsTable()
        t["MSG"] = LocalizedString("%s has %d items")
        result = t.str("MSG", "Alice", 5)
        assert result == "Alice has 5 items"

    def test_str_missing_with_args(self) -> None:
        """Formatting with missing token uses the token name as template."""
        t = StringsTable()
        result = t.str("MISSING %s", "Alice")
        assert "Alice" in str(result)

    def test_repr(self) -> None:
        t = StringsTable()
        t["A"] = LocalizedString("a")
        r = repr(t)
        assert "1 entries" in r
        assert "StringsTable" in r

    # --- Parent (fallback) chain ---

    def test_parent_fallback(self) -> None:
        parent = StringsTable()
        parent["GLOBAL"] = LocalizedString("Global Value")
        child = StringsTable(parent=parent)
        result = child["GLOBAL"]
        assert result is not None
        assert str(result) == "Global Value"

    def test_child_overrides_parent(self) -> None:
        parent = StringsTable()
        parent["KEY"] = LocalizedString("parent")
        child = StringsTable(parent=parent)
        child["KEY"] = LocalizedString("child")
        result = child["KEY"]
        assert result is not None
        assert str(result) == "child"

    def test_contains_parent(self) -> None:
        parent = StringsTable()
        parent["GLOBAL"] = LocalizedString("g")
        child = StringsTable(parent=parent)
        assert "GLOBAL" in child

    def test_len_with_parent(self) -> None:
        parent = StringsTable()
        parent["A"] = LocalizedString("a")
        parent["B"] = LocalizedString("b")
        child = StringsTable(parent=parent)
        child["C"] = LocalizedString("c")
        assert len(child) == 3

    def test_len_with_parent_overlap(self) -> None:
        """Overlapping keys are deduplicated."""
        parent = StringsTable()
        parent["A"] = LocalizedString("a")
        child = StringsTable(parent=parent)
        child["A"] = LocalizedString("override")
        assert len(child) == 1

    def test_iter_with_parent_deduplicates(self) -> None:
        parent = StringsTable()
        parent["A"] = LocalizedString("a")
        parent["B"] = LocalizedString("b")
        child = StringsTable(parent=parent)
        child["B"] = LocalizedString("override")
        child["C"] = LocalizedString("c")
        keys = sorted(child)
        assert keys == ["A", "B", "C"]

    def test_str_lookup_parent(self) -> None:
        parent = StringsTable()
        parent["GLOBAL"] = LocalizedString("Global")
        child = StringsTable(parent=parent)
        result = child.str("GLOBAL")
        assert isinstance(result, LocalizedString)
        assert str(result) == "Global"

    # --- Machine suffix ---

    def test_machine_suffix_override(self) -> None:
        t = StringsTable(machine_suffix="_JIVE")
        t["HELLO_JIVE"] = LocalizedString("Jive Hello")
        t["HELLO"] = LocalizedString("Normal Hello")
        result = t.str("HELLO")
        assert isinstance(result, LocalizedString)
        assert str(result) == "Jive Hello"

    def test_machine_suffix_fallback_to_regular(self) -> None:
        t = StringsTable(machine_suffix="_JIVE")
        t["HELLO"] = LocalizedString("Normal Hello")
        result = t.str("HELLO")
        assert isinstance(result, LocalizedString)
        assert str(result) == "Normal Hello"

    def test_str_with_localized_string_as_token(self) -> None:
        t = StringsTable()
        t["HELLO"] = LocalizedString("Hello")
        token = LocalizedString("HELLO")
        result = t.str(token)
        assert str(result) == "Hello"

    def test_str_false_entry_falls_through(self) -> None:
        """An entry with str=False (untranslated) is falsy → treated as missing."""
        t = StringsTable()
        t["EMPTY"] = LocalizedString(False)
        result = t.str("EMPTY")
        # Since the entry is falsy, it should fall through to returning the token name
        assert result == "EMPTY"


# ---------------------------------------------------------------------------
# _parse_strings_file
# ---------------------------------------------------------------------------


class TestParseStringsFile:
    """Tests for the internal _parse_strings_file function."""

    def test_basic_parsing(self, tmp_path: object) -> None:
        from pathlib import Path

        p = Path(str(tmp_path)) / "strings.txt"
        p.write_text(
            "GREETING\n\tEN\tHello\n\tDE\tHallo\n\n"
            "FAREWELL\n\tEN\tGoodbye\n\tDE\tAuf Wiedersehen\n",
            encoding="utf-8",
        )
        table = StringsTable()
        all_locales: dict[str, bool] = {}
        _parse_strings_file("EN", str(p), table, all_locales)

        assert "GREETING" in table
        assert str(table["GREETING"]) == "Hello"
        assert "FAREWELL" in table
        assert str(table["FAREWELL"]) == "Goodbye"

    def test_german_locale(self, tmp_path: object) -> None:
        from pathlib import Path

        p = Path(str(tmp_path)) / "strings.txt"
        p.write_text(
            "GREETING\n\tEN\tHello\n\tDE\tHallo\n",
            encoding="utf-8",
        )
        table = StringsTable()
        all_locales: dict[str, bool] = {}
        _parse_strings_file("DE", str(p), table, all_locales)

        assert str(table["GREETING"]) == "Hallo"

    def test_en_fallback(self, tmp_path: object) -> None:
        """If a token has no translation for the requested locale, EN is used."""
        from pathlib import Path

        p = Path(str(tmp_path)) / "strings.txt"
        p.write_text(
            "GREETING\n\tEN\tHello\n",
            encoding="utf-8",
        )
        table = StringsTable()
        all_locales: dict[str, bool] = {}
        _parse_strings_file("FR", str(p), table, all_locales)

        assert str(table["GREETING"]) == "Hello"

    def test_all_locales_tracking(self, tmp_path: object) -> None:
        from pathlib import Path

        p = Path(str(tmp_path)) / "strings.txt"
        p.write_text(
            "GREETING\n\tEN\tHello\n\tDE\tHallo\n\tFR\tBonjour\n",
            encoding="utf-8",
        )
        table = StringsTable()
        all_locales: dict[str, bool] = {}
        _parse_strings_file("EN", str(p), table, all_locales)

        assert "EN" in all_locales
        assert "DE" in all_locales
        assert "FR" in all_locales

    def test_backslash_n_becomes_newline(self, tmp_path: object) -> None:
        from pathlib import Path

        p = Path(str(tmp_path)) / "strings.txt"
        p.write_text(
            "MSG\n\tEN\tLine1\\nLine2\n",
            encoding="utf-8",
        )
        table = StringsTable()
        all_locales: dict[str, bool] = {}
        _parse_strings_file("EN", str(p), table, all_locales)

        assert str(table["MSG"]) == "Line1\nLine2"

    def test_nonexistent_file(self) -> None:
        """Parsing a nonexistent file returns the (empty) table without error."""
        table = StringsTable()
        all_locales: dict[str, bool] = {}
        result = _parse_strings_file("EN", "/no/such/file.txt", table, all_locales)
        assert result is table
        assert len(table) == 0

    def test_empty_file(self, tmp_path: object) -> None:
        from pathlib import Path

        p = Path(str(tmp_path)) / "empty.txt"
        p.write_text("", encoding="utf-8")
        table = StringsTable()
        all_locales: dict[str, bool] = {}
        _parse_strings_file("EN", str(p), table, all_locales)
        assert len(table) == 0

    def test_multiple_tokens(self, tmp_path: object) -> None:
        from pathlib import Path

        p = Path(str(tmp_path)) / "strings.txt"
        content = "TOKEN_A\n\tEN\tAlpha\n\nTOKEN_B\n\tEN\tBravo\n\nTOKEN_C\n\tEN\tCharlie\n"
        p.write_text(content, encoding="utf-8")
        table = StringsTable()
        all_locales: dict[str, bool] = {}
        _parse_strings_file("EN", str(p), table, all_locales)

        assert str(table["TOKEN_A"]) == "Alpha"
        assert str(table["TOKEN_B"]) == "Bravo"
        assert str(table["TOKEN_C"]) == "Charlie"

    def test_reparse_updates_in_place(self, tmp_path: object) -> None:
        """Re-parsing a file updates existing LocalizedString objects in place."""
        from pathlib import Path

        p = Path(str(tmp_path)) / "strings.txt"
        p.write_text("HELLO\n\tEN\tHello\n\tDE\tHallo\n", encoding="utf-8")

        table = StringsTable()
        all_locales: dict[str, bool] = {}

        # First parse with EN
        _parse_strings_file("EN", str(p), table, all_locales)
        entry = table["HELLO"]
        assert entry is not None
        assert str(entry) == "Hello"

        # Re-parse with DE — the same LocalizedString object should be updated
        _parse_strings_file("DE", str(p), table, all_locales)
        assert entry is table["HELLO"]  # same object
        assert str(entry) == "Hallo"

    def test_tab_separated_format(self, tmp_path: object) -> None:
        """Translation lines can use multiple tabs between locale and text."""
        from pathlib import Path

        p = Path(str(tmp_path)) / "strings.txt"
        p.write_text("HELLO\n\tEN\t\tHello World\n", encoding="utf-8")
        table = StringsTable()
        all_locales: dict[str, bool] = {}
        _parse_strings_file("EN", str(p), table, all_locales)

        # The regex captures everything after the second set of tabs
        result = str(table["HELLO"])
        assert "Hello" in result


# ---------------------------------------------------------------------------
# Locale
# ---------------------------------------------------------------------------


class TestLocale:
    """Tests for the Locale manager class."""

    def test_default_locale_is_en(self) -> None:
        loc = Locale()
        assert loc.get_locale() == "EN"

    def test_set_locale_round_trip(self) -> None:
        loc = Locale()
        loc.set_locale("DE")
        assert loc.get_locale() == "DE"

    def test_set_locale_same_is_noop(self) -> None:
        loc = Locale()
        loc.set_locale("EN")  # same as default — should not error
        assert loc.get_locale() == "EN"

    def test_get_all_locales_initially_empty(self) -> None:
        loc = Locale()
        result = loc.get_all_locales()
        assert isinstance(result, list)

    def test_get_all_locales_after_loading(self, tmp_path: object) -> None:
        from pathlib import Path

        p = Path(str(tmp_path)) / "strings.txt"
        p.write_text(
            "HELLO\n\tEN\tHello\n\tDE\tHallo\n\tFR\tBonjour\n",
            encoding="utf-8",
        )
        loc = Locale()
        loc.read_strings_file(str(p))
        locales = loc.get_all_locales()
        assert "EN" in locales
        assert "DE" in locales
        assert "FR" in locales

    def test_read_strings_file(self, tmp_path: object) -> None:
        from pathlib import Path

        p = Path(str(tmp_path)) / "strings.txt"
        p.write_text("HELLO\n\tEN\tHello World\n", encoding="utf-8")
        loc = Locale()
        table = loc.read_strings_file(str(p))
        assert isinstance(table, StringsTable)
        result = table.str("HELLO")
        assert str(result) == "Hello World"

    def test_read_strings_file_with_existing_table(self, tmp_path: object) -> None:
        from pathlib import Path

        p = Path(str(tmp_path)) / "strings.txt"
        p.write_text("HELLO\n\tEN\tHello\n", encoding="utf-8")
        loc = Locale()
        existing = StringsTable()
        table = loc.read_strings_file(str(p), strings_table=existing)
        assert table is existing
        assert str(table["HELLO"]) == "Hello"

    def test_read_strings_file_has_global_parent(self, tmp_path: object) -> None:
        """read_strings_file creates a table with the global strings as parent."""
        from pathlib import Path

        global_path = Path(str(tmp_path)) / "global.txt"
        global_path.write_text("GLOBAL_KEY\n\tEN\tGlobal Value\n", encoding="utf-8")

        local_path = Path(str(tmp_path)) / "local.txt"
        local_path.write_text("LOCAL_KEY\n\tEN\tLocal Value\n", encoding="utf-8")

        loc = Locale()
        loc.read_global_strings_file(str(global_path))
        table = loc.read_strings_file(str(local_path))

        # Local key present
        assert str(table.str("LOCAL_KEY")) == "Local Value"
        # Global key accessible via parent chain
        assert str(table.str("GLOBAL_KEY")) == "Global Value"

    def test_read_global_strings_file(self, tmp_path: object) -> None:
        from pathlib import Path

        p = Path(str(tmp_path)) / "global_strings.txt"
        p.write_text("APP_NAME\n\tEN\tSordino\n", encoding="utf-8")
        loc = Locale()
        gs = loc.read_global_strings_file(str(p))
        assert isinstance(gs, StringsTable)
        assert str(gs["APP_NAME"]) == "Sordino"

    def test_read_global_strings_file_no_path(self) -> None:
        """Without a path and no find_file callback, returns the empty global table."""
        loc = Locale()
        gs = loc.read_global_strings_file()
        assert isinstance(gs, StringsTable)

    def test_global_strings_property(self) -> None:
        loc = Locale()
        gs = loc.global_strings
        assert isinstance(gs, StringsTable)

    def test_load_all_strings(self, tmp_path: object) -> None:
        from pathlib import Path

        p = Path(str(tmp_path)) / "strings.txt"
        p.write_text(
            "HELLO\n\tEN\tHello\n\tDE\tHallo\nBYE\n\tEN\tGoodbye\n\tDE\tTschuess\n",
            encoding="utf-8",
        )
        loc = Locale()
        all_strings = loc.load_all_strings(str(p))
        assert all_strings["EN"]["HELLO"] == "Hello"
        assert all_strings["DE"]["HELLO"] == "Hallo"
        assert all_strings["EN"]["BYE"] == "Goodbye"
        assert all_strings["DE"]["BYE"] == "Tschuess"

    def test_load_all_strings_nonexistent(self) -> None:
        loc = Locale()
        result = loc.load_all_strings("/no/such/file.txt")
        assert result == {}

    def test_machine_suffix(self, tmp_path: object) -> None:
        from pathlib import Path

        p = Path(str(tmp_path)) / "strings.txt"
        p.write_text(
            "HELLO\n\tEN\tGeneric Hello\nHELLO_JIVE\n\tEN\tJive Hello\n",
            encoding="utf-8",
        )
        loc = Locale(machine="jive")
        table = loc.read_strings_file(str(p))
        result = table.str("HELLO")
        assert str(result) == "Jive Hello"

    def test_set_locale_reloads_files(self, tmp_path: object) -> None:
        """Changing locale re-parses previously loaded files."""
        from pathlib import Path

        p = Path(str(tmp_path)) / "strings.txt"
        p.write_text(
            "GREETING\n\tEN\tHello\n\tDE\tHallo\n",
            encoding="utf-8",
        )
        loc = Locale()
        table = loc.read_strings_file(str(p))
        assert str(table.str("GREETING")) == "Hello"

        loc.set_locale("DE")
        assert loc.get_locale() == "DE"
        # The entry should now be updated to German
        assert str(table.str("GREETING")) == "Hallo"

    def test_find_file_callback(self, tmp_path: object) -> None:
        from pathlib import Path

        p = Path(str(tmp_path)) / "global_strings.txt"
        p.write_text("FOUND\n\tEN\tFound it\n", encoding="utf-8")

        def finder(logical_path: str) -> str | None:
            if "global_strings" in logical_path:
                return str(p)
            return None

        loc = Locale(find_file=finder)
        gs = loc.read_global_strings_file()
        assert str(gs["FOUND"]) == "Found it"

    def test_str_with_format_via_locale(self, tmp_path: object) -> None:
        from pathlib import Path

        p = Path(str(tmp_path)) / "strings.txt"
        p.write_text("WELCOME\n\tEN\tWelcome %s!\n", encoding="utf-8")
        loc = Locale()
        table = loc.read_strings_file(str(p))
        result = table.str("WELCOME", "Alice")
        assert result == "Welcome Alice!"


# ---------------------------------------------------------------------------
# Module-level Singleton
# ---------------------------------------------------------------------------


class TestSingleton:
    """Tests for get_locale_instance / reset_instance."""

    def test_returns_locale_instance(self) -> None:
        loc = get_locale_instance()
        assert isinstance(loc, Locale)

    def test_same_instance(self) -> None:
        a = get_locale_instance()
        b = get_locale_instance()
        assert a is b

    def test_reset_creates_new_instance(self) -> None:
        a = get_locale_instance()
        reset_instance()
        b = get_locale_instance()
        assert a is not b

    def test_reset_gives_default_locale(self) -> None:
        loc = get_locale_instance()
        loc.set_locale("DE")
        reset_instance()
        loc2 = get_locale_instance()
        assert loc2.get_locale() == "EN"


# ---------------------------------------------------------------------------
# Edge Cases & Integration
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Miscellaneous edge-case tests."""

    def test_empty_translation(self, tmp_path: object) -> None:
        """A token with no translations gets EN fallback or stays False."""
        from pathlib import Path

        p = Path(str(tmp_path)) / "strings.txt"
        # Token with only a DE translation, requesting FR
        p.write_text("ONLY_DE\n\tDE\tNur Deutsch\n", encoding="utf-8")
        table = StringsTable()
        all_locales: dict[str, bool] = {}
        _parse_strings_file("FR", str(p), table, all_locales)

        entry = table["ONLY_DE"]
        assert entry is not None
        # No EN fallback either, so it should remain False → str == ""
        assert str(entry) == ""

    def test_strings_table_str_with_empty_entry(self) -> None:
        """str() on a token whose LocalizedString is False → returns token name."""
        t = StringsTable()
        t["UNTRANSLATED"] = LocalizedString(False)
        result = t.str("UNTRANSLATED")
        assert result == "UNTRANSLATED"

    def test_localized_string_in_dict(self) -> None:
        """LocalizedString is hashable and usable as a dict key."""
        d: dict[LocalizedString, int] = {}
        ls = LocalizedString("key")
        d[ls] = 42
        assert d[ls] == 42

    def test_parse_ignores_comment_like_lines(self, tmp_path: object) -> None:
        """Lines not starting with uppercase and not matching translation format are skipped."""
        from pathlib import Path

        p = Path(str(tmp_path)) / "strings.txt"
        content = "# This is a comment\n\nHELLO\n\tEN\tHello\n\nlowercase line\n"
        p.write_text(content, encoding="utf-8")
        table = StringsTable()
        all_locales: dict[str, bool] = {}
        _parse_strings_file("EN", str(p), table, all_locales)

        assert str(table["HELLO"]) == "Hello"
        # Comments and lowercase lines should not create entries
        assert "# This is a comment" not in table
        assert "lowercase line" not in table

    def test_backslash_n_in_all_strings(self, tmp_path: object) -> None:
        """load_all_strings also converts \\n to newlines."""
        from pathlib import Path

        p = Path(str(tmp_path)) / "strings.txt"
        p.write_text("MSG\n\tEN\tLine1\\nLine2\n", encoding="utf-8")
        loc = Locale()
        result = loc.load_all_strings(str(p))
        assert result["EN"]["MSG"] == "Line1\nLine2"

    def test_multiple_files_share_global_parent(self, tmp_path: object) -> None:
        from pathlib import Path

        g = Path(str(tmp_path)) / "global.txt"
        g.write_text("SHARED\n\tEN\tShared Value\n", encoding="utf-8")

        a = Path(str(tmp_path)) / "a.txt"
        a.write_text("KEY_A\n\tEN\tA Value\n", encoding="utf-8")

        b = Path(str(tmp_path)) / "b.txt"
        b.write_text("KEY_B\n\tEN\tB Value\n", encoding="utf-8")

        loc = Locale()
        loc.read_global_strings_file(str(g))
        table_a = loc.read_strings_file(str(a))
        table_b = loc.read_strings_file(str(b))

        # Both tables can access the global key
        assert str(table_a.str("SHARED")) == "Shared Value"
        assert str(table_b.str("SHARED")) == "Shared Value"
        # Each has its own keys
        assert str(table_a.str("KEY_A")) == "A Value"
        assert str(table_b.str("KEY_B")) == "B Value"
