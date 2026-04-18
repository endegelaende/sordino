"""Tests for jive.utils.table_utils — table/list/dict utility functions.

Covers:
- pairs_by_keys: sorted dict iteration with optional key function
- delete: remove first occurrence of value from list
- contains: membership test
- insert: append or positional insert
- remove: pop last or positional remove
- sort: in-place sort with key/reverse
"""

from __future__ import annotations

import pytest

from jive.utils.table_utils import contains, delete, insert, pairs_by_keys, remove, sort

# ---------------------------------------------------------------------------
# pairs_by_keys
# ---------------------------------------------------------------------------


class TestPairsByKeys:
    """Tests for pairs_by_keys(d, key_func)."""

    def test_sorted_order(self) -> None:
        d = {"banana": 2, "apple": 1, "cherry": 3}
        result = list(pairs_by_keys(d))
        assert result == [("apple", 1), ("banana", 2), ("cherry", 3)]

    def test_empty_dict(self) -> None:
        assert list(pairs_by_keys({})) == []

    def test_single_entry(self) -> None:
        assert list(pairs_by_keys({"only": 1})) == [("only", 1)]

    def test_already_sorted(self) -> None:
        d = {"a": 1, "b": 2, "c": 3}
        assert list(pairs_by_keys(d)) == [("a", 1), ("b", 2), ("c", 3)]

    def test_reverse_sorted_input(self) -> None:
        d = {"c": 3, "b": 2, "a": 1}
        assert list(pairs_by_keys(d)) == [("a", 1), ("b", 2), ("c", 3)]

    def test_custom_key_func(self) -> None:
        d = {"banana": 2, "apple": 1, "cherry": 3}
        # Sort by value descending via key_func on keys
        result = list(pairs_by_keys(d, key_func=lambda k: -d[k]))
        assert result == [("cherry", 3), ("banana", 2), ("apple", 1)]

    def test_custom_key_func_case_insensitive(self) -> None:
        d = {"Banana": 2, "apple": 1, "Cherry": 3}
        result = list(pairs_by_keys(d, key_func=lambda k: k.lower()))
        assert result == [("apple", 1), ("Banana", 2), ("Cherry", 3)]

    def test_integer_keys(self) -> None:
        d = {3: "c", 1: "a", 2: "b"}
        assert list(pairs_by_keys(d)) == [(1, "a"), (2, "b"), (3, "c")]

    def test_yields_tuples(self) -> None:
        d = {"x": 10}
        for item in pairs_by_keys(d):
            assert isinstance(item, tuple)
            assert len(item) == 2

    def test_is_iterator(self) -> None:
        d = {"a": 1, "b": 2}
        it = pairs_by_keys(d)
        assert next(it) == ("a", 1)
        assert next(it) == ("b", 2)
        with pytest.raises(StopIteration):
            next(it)

    def test_duplicate_values(self) -> None:
        d = {"b": 1, "a": 1, "c": 1}
        result = list(pairs_by_keys(d))
        assert result == [("a", 1), ("b", 1), ("c", 1)]


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------


class TestDelete:
    """Tests for delete(lst, value)."""

    def test_removes_first_occurrence(self) -> None:
        lst = [1, 2, 3, 2, 1]
        assert delete(lst, 2) is True
        assert lst == [1, 3, 2, 1]

    def test_returns_false_if_not_found(self) -> None:
        lst = [1, 2, 3]
        assert delete(lst, 99) is False
        assert lst == [1, 2, 3]

    def test_empty_list(self) -> None:
        lst: list[int] = []
        assert delete(lst, 1) is False
        assert lst == []

    def test_removes_only_first(self) -> None:
        lst = [5, 5, 5]
        delete(lst, 5)
        assert lst == [5, 5]

    def test_single_element_found(self) -> None:
        lst = [42]
        assert delete(lst, 42) is True
        assert lst == []

    def test_single_element_not_found(self) -> None:
        lst = [42]
        assert delete(lst, 7) is False
        assert lst == [42]

    def test_string_values(self) -> None:
        lst = ["a", "b", "c"]
        assert delete(lst, "b") is True
        assert lst == ["a", "c"]

    def test_none_value(self) -> None:
        lst = [None, 1, None]
        assert delete(lst, None) is True
        assert lst == [1, None]

    def test_preserves_order(self) -> None:
        lst = [10, 20, 30, 40, 50]
        delete(lst, 30)
        assert lst == [10, 20, 40, 50]


# ---------------------------------------------------------------------------
# contains
# ---------------------------------------------------------------------------


class TestContains:
    """Tests for contains(lst, value)."""

    def test_found(self) -> None:
        assert contains([1, 2, 3], 2) is True

    def test_not_found(self) -> None:
        assert contains([1, 2, 3], 99) is False

    def test_empty_list(self) -> None:
        assert contains([], "anything") is False

    def test_none_value(self) -> None:
        assert contains([None, 1, 2], None) is True

    def test_none_not_in_list(self) -> None:
        assert contains([1, 2, 3], None) is False

    def test_string_values(self) -> None:
        assert contains(["hello", "world"], "world") is True
        assert contains(["hello", "world"], "nope") is False

    def test_first_element(self) -> None:
        assert contains([42, 1, 2], 42) is True

    def test_last_element(self) -> None:
        assert contains([1, 2, 42], 42) is True

    def test_type_mismatch(self) -> None:
        # 1 == True in Python, so this is True
        assert contains([1, 2, 3], True) is True
        # But "1" != 1
        assert contains([1, 2, 3], "1") is False


# ---------------------------------------------------------------------------
# insert
# ---------------------------------------------------------------------------


class TestInsert:
    """Tests for insert(lst, value, pos)."""

    def test_append_no_pos(self) -> None:
        lst = [1, 2, 3]
        insert(lst, 99)
        assert lst == [1, 2, 3, 99]

    def test_insert_at_beginning(self) -> None:
        lst = [1, 2, 3]
        insert(lst, 0, pos=0)
        assert lst == [0, 1, 2, 3]

    def test_insert_at_middle(self) -> None:
        lst = [1, 2, 3]
        insert(lst, 99, pos=1)
        assert lst == [1, 99, 2, 3]

    def test_insert_at_end(self) -> None:
        lst = [1, 2, 3]
        insert(lst, 99, pos=3)
        assert lst == [1, 2, 3, 99]

    def test_insert_into_empty_list(self) -> None:
        lst: list[int] = []
        insert(lst, 42)
        assert lst == [42]

    def test_insert_into_empty_list_at_pos_0(self) -> None:
        lst: list[int] = []
        insert(lst, 42, pos=0)
        assert lst == [42]

    def test_returns_none(self) -> None:
        lst = [1]
        result = insert(lst, 2)
        assert result is None

    def test_multiple_appends(self) -> None:
        lst: list[int] = []
        for i in range(5):
            insert(lst, i)
        assert lst == [0, 1, 2, 3, 4]

    def test_insert_preserves_existing_elements(self) -> None:
        lst = ["a", "b", "c"]
        insert(lst, "X", pos=1)
        assert lst == ["a", "X", "b", "c"]


# ---------------------------------------------------------------------------
# remove
# ---------------------------------------------------------------------------


class TestRemove:
    """Tests for remove(lst, pos)."""

    def test_remove_last_no_pos(self) -> None:
        lst = [10, 20, 30]
        result = remove(lst)
        assert result == 30
        assert lst == [10, 20]

    def test_remove_at_index(self) -> None:
        lst = [10, 20, 30]
        result = remove(lst, 0)
        assert result == 10
        assert lst == [20, 30]

    def test_remove_middle(self) -> None:
        lst = [10, 20, 30]
        result = remove(lst, 1)
        assert result == 20
        assert lst == [10, 30]

    def test_remove_last_by_index(self) -> None:
        lst = [10, 20, 30]
        result = remove(lst, 2)
        assert result == 30
        assert lst == [10, 20]

    def test_raises_on_empty_list(self) -> None:
        with pytest.raises(IndexError):
            remove([])

    def test_raises_on_empty_list_with_pos(self) -> None:
        with pytest.raises(IndexError):
            remove([], 0)

    def test_raises_on_out_of_range(self) -> None:
        with pytest.raises(IndexError):
            remove([1, 2, 3], 10)

    def test_single_element(self) -> None:
        lst = [42]
        result = remove(lst)
        assert result == 42
        assert lst == []

    def test_negative_index(self) -> None:
        lst = [10, 20, 30]
        result = remove(lst, -1)
        assert result == 30
        assert lst == [10, 20]

    def test_returns_correct_type(self) -> None:
        lst = ["a", "b", "c"]
        result = remove(lst, 0)
        assert result == "a"
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# sort
# ---------------------------------------------------------------------------


class TestSort:
    """Tests for sort(lst, key_func, reverse)."""

    def test_basic_sort(self) -> None:
        lst = [3, 1, 2]
        sort(lst)
        assert lst == [1, 2, 3]

    def test_reverse_sort(self) -> None:
        lst = [3, 1, 2]
        sort(lst, reverse=True)
        assert lst == [3, 2, 1]

    def test_with_key_func(self) -> None:
        lst = ["banana", "apple", "cherry"]
        sort(lst, key_func=len)
        assert lst == ["apple", "banana", "cherry"]

    def test_with_key_func_and_reverse(self) -> None:
        lst = ["hi", "hello", "hey"]
        sort(lst, key_func=len, reverse=True)
        assert lst == ["hello", "hey", "hi"]

    def test_already_sorted(self) -> None:
        lst = [1, 2, 3]
        sort(lst)
        assert lst == [1, 2, 3]

    def test_empty_list(self) -> None:
        lst: list[int] = []
        sort(lst)
        assert lst == []

    def test_single_element(self) -> None:
        lst = [42]
        sort(lst)
        assert lst == [42]

    def test_duplicates(self) -> None:
        lst = [3, 1, 2, 1, 3]
        sort(lst)
        assert lst == [1, 1, 2, 3, 3]

    def test_returns_none(self) -> None:
        lst = [3, 1, 2]
        result = sort(lst)
        assert result is None

    def test_strings_natural_order(self) -> None:
        lst = ["cherry", "apple", "banana"]
        sort(lst)
        assert lst == ["apple", "banana", "cherry"]

    def test_case_sensitive_key(self) -> None:
        lst = ["Banana", "apple", "Cherry"]
        sort(lst, key_func=str.lower)
        assert lst == ["apple", "Banana", "Cherry"]
