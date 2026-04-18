"""Tests for jive.utils.autotable — auto-vivifying nested dictionaries."""

from __future__ import annotations

import pytest

from jive.utils.autotable import AutoTable, new


class TestAutoVivification:
    """Auto-vivification: missing keys create nested AutoTables."""

    def test_single_level_assignment(self) -> None:
        t = AutoTable()
        t["a"] = 1
        assert t["a"] == 1

    def test_nested_chain_assignment(self) -> None:
        t = AutoTable()
        t["a"]["b"]["c"] = 42
        assert t["a"]["b"]["c"] == 42

    def test_intermediate_dicts_are_autotables(self) -> None:
        t = AutoTable()
        t["a"]["b"]["c"] = 42
        assert isinstance(t["a"], AutoTable)
        assert isinstance(t["a"]["b"], AutoTable)

    def test_missing_key_returns_autotable(self) -> None:
        t = AutoTable()
        sub = t["nonexistent"]
        assert isinstance(sub, AutoTable)
        assert len(sub) == 0

    def test_missing_key_is_stored(self) -> None:
        t = AutoTable()
        sub = t["x"]
        assert "x" in t
        assert t["x"] is sub

    def test_deeply_nested(self) -> None:
        t = AutoTable()
        t["a"]["b"]["c"]["d"]["e"] = "deep"
        assert t["a"]["b"]["c"]["d"]["e"] == "deep"

    def test_multiple_branches(self) -> None:
        t = AutoTable()
        t["a"]["x"] = 1
        t["a"]["y"] = 2
        t["b"]["z"] = 3
        assert t["a"]["x"] == 1
        assert t["a"]["y"] == 2
        assert t["b"]["z"] == 3

    def test_overwrite_value(self) -> None:
        t = AutoTable()
        t["a"]["b"] = 1
        t["a"]["b"] = 2
        assert t["a"]["b"] == 2

    def test_overwrite_subtable_with_value(self) -> None:
        t = AutoTable()
        _ = t["a"]["b"]  # creates intermediate
        t["a"] = 99
        assert t["a"] == 99

    def test_integer_keys(self) -> None:
        t = AutoTable()
        t[0][1][2] = "nums"
        assert t[0][1][2] == "nums"


class TestAttributeAccess:
    """Attribute-style access delegates to item access."""

    def test_setattr_getattr(self) -> None:
        t = AutoTable()
        t.x = 10
        assert t.x == 10
        assert t["x"] == 10

    def test_nested_attr(self) -> None:
        t = AutoTable()
        t.x.y = 10
        assert t["x"]["y"] == 10

    def test_attr_read_creates_subtable(self) -> None:
        t = AutoTable()
        sub = t.missing
        assert isinstance(sub, AutoTable)

    def test_attr_setitem_interop(self) -> None:
        t = AutoTable()
        t["key"] = 5
        assert t.key == 5

    def test_setattr_setitem_interop(self) -> None:
        t = AutoTable()
        t.key = 5
        assert t["key"] == 5


class TestPrivateAttributes:
    """Private/dunder attributes use normal object mechanism, not dict."""

    def test_private_attr_not_in_dict(self) -> None:
        t = AutoTable()
        t._secret = 42  # type: ignore[attr-defined]
        assert "_secret" not in t
        assert t._secret == 42  # type: ignore[attr-defined]

    def test_dunder_attr_raises(self) -> None:
        t = AutoTable()
        with pytest.raises(AttributeError):
            _ = t._nonexistent  # type: ignore[attr-defined]

    def test_private_setattr_getattr(self) -> None:
        t = AutoTable()
        t._foo = "bar"  # type: ignore[attr-defined]
        assert t._foo == "bar"  # type: ignore[attr-defined]
        assert "_foo" not in t  # not in dict keys


class TestDelattr:
    """Deletion via del t.key and del t['key']."""

    def test_delattr_existing(self) -> None:
        t = AutoTable()
        t.x = 1
        del t.x
        assert "x" not in t

    def test_delattr_missing_raises(self) -> None:
        t = AutoTable()
        with pytest.raises(AttributeError):
            del t.x

    def test_delitem(self) -> None:
        t = AutoTable()
        t["k"] = 1
        del t["k"]
        assert "k" not in t

    def test_delitem_missing_raises(self) -> None:
        t = AutoTable()
        with pytest.raises(KeyError):
            del t["k"]

    def test_delattr_private_uses_object(self) -> None:
        t = AutoTable()
        t._p = 1  # type: ignore[attr-defined]
        del t._p
        with pytest.raises(AttributeError):
            _ = t._p  # type: ignore[attr-defined]


class TestToDict:
    """Recursive conversion to plain dict."""

    def test_empty(self) -> None:
        t = AutoTable()
        assert t.to_dict() == {}

    def test_flat(self) -> None:
        t = AutoTable()
        t["a"] = 1
        t["b"] = 2
        assert t.to_dict() == {"a": 1, "b": 2}

    def test_nested(self) -> None:
        t = AutoTable()
        t["a"]["b"] = 1
        result = t.to_dict()
        assert result == {"a": {"b": 1}}
        assert type(result["a"]) is dict  # not AutoTable

    def test_deeply_nested_type(self) -> None:
        t = AutoTable()
        t["a"]["b"]["c"] = 1
        result = t.to_dict()
        assert type(result["a"]) is dict
        assert type(result["a"]["b"]) is dict

    def test_empty_autovivified_subtable(self) -> None:
        t = AutoTable()
        _ = t["a"]["b"]  # auto-vivify but never assign
        result = t.to_dict()
        assert result == {"a": {"b": {}}}

    def test_mixed_values(self) -> None:
        t = AutoTable()
        t["x"] = [1, 2, 3]
        t["y"]["z"] = "hello"
        result = t.to_dict()
        assert result == {"x": [1, 2, 3], "y": {"z": "hello"}}


class TestFromDict:
    """Recursive conversion from plain dict."""

    def test_empty(self) -> None:
        t = AutoTable.from_dict({})
        assert isinstance(t, AutoTable)
        assert len(t) == 0

    def test_flat(self) -> None:
        t = AutoTable.from_dict({"a": 1, "b": 2})
        assert t["a"] == 1
        assert t["b"] == 2

    def test_nested(self) -> None:
        t = AutoTable.from_dict({"a": {"b": 1}})
        assert isinstance(t["a"], AutoTable)
        assert t["a"]["b"] == 1

    def test_nested_autovivify_still_works(self) -> None:
        t = AutoTable.from_dict({"a": {"b": 1}})
        t["a"]["c"]["d"] = 99
        assert t["a"]["c"]["d"] == 99

    def test_roundtrip(self) -> None:
        original = {"a": {"b": 1}, "c": [1, 2], "d": "hello"}
        t = AutoTable.from_dict(original)
        assert t.to_dict() == original

    def test_non_dict_values_preserved(self) -> None:
        t = AutoTable.from_dict({"lst": [1, 2], "num": 42, "s": "hi"})
        assert t["lst"] == [1, 2]
        assert t["num"] == 42
        assert t["s"] == "hi"


class TestRepr:
    """String representation."""

    def test_empty(self) -> None:
        assert repr(AutoTable()) == "AutoTable({})"

    def test_with_data(self) -> None:
        t = AutoTable()
        t["a"] = 1
        assert repr(t) == "AutoTable({'a': 1})"

    def test_contains_autotable_prefix(self) -> None:
        t = AutoTable()
        assert repr(t).startswith("AutoTable(")


class TestNewFactory:
    """new() module-level factory."""

    def test_returns_autotable(self) -> None:
        t = new()
        assert isinstance(t, AutoTable)

    def test_is_empty(self) -> None:
        t = new()
        assert len(t) == 0

    def test_autovivification_works(self) -> None:
        t = new()
        t["a"]["b"] = 1
        assert t["a"]["b"] == 1


class TestDictBehavior:
    """AutoTable inherits dict behavior."""

    def test_len(self) -> None:
        t = AutoTable()
        t["a"] = 1
        t["b"] = 2
        assert len(t) == 2

    def test_iter(self) -> None:
        t = AutoTable()
        t["a"] = 1
        t["b"] = 2
        assert set(t) == {"a", "b"}

    def test_keys_values_items(self) -> None:
        t = AutoTable()
        t["x"] = 10
        assert list(t.keys()) == ["x"]
        assert list(t.values()) == [10]
        assert list(t.items()) == [("x", 10)]

    def test_update(self) -> None:
        t = AutoTable()
        t.update({"a": 1, "b": 2})
        assert t["a"] == 1
        assert t["b"] == 2

    def test_in_operator(self) -> None:
        t = AutoTable()
        t["a"] = 1
        assert "a" in t
        assert "b" not in t

    def test_equality_with_dict(self) -> None:
        t = AutoTable()
        t["a"] = 1
        assert t == {"a": 1}

    def test_bool_empty(self) -> None:
        # Empty dict is falsy in Python, but note: accessing a missing
        # key will create a subtable making it truthy
        t = AutoTable()
        assert not t  # empty

    def test_bool_nonempty(self) -> None:
        t = AutoTable()
        t["a"] = 1
        assert t
