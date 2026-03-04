"""
jive.utils.table_utils — Table/list/dict utility functions.

Ported from share/jive/jive/utils/table.lua

The original Lua module extends Lua's built-in table module with
additional utility functions. In Python, we provide equivalent
functionality operating on lists (for ordered sequences) and dicts
(for key-value mappings).

Usage:
    from jive.utils.table_utils import pairs_by_keys, delete, contains

    # Iterate over a dict in sorted key order
    for key, value in pairs_by_keys(my_dict):
        print(key, value)

    # Remove first occurrence of a value from a list
    if delete(my_list, "unwanted"):
        print("removed")

    # Check if a list contains a value
    if contains(my_list, "target"):
        print("found")

Copyright 2010 Logitech. All Rights Reserved.
This file is licensed under BSD. Please see the LICENSE file for details.
"""

from __future__ import annotations

from typing import (
    Any,
    Callable,
    Iterator,
    Optional,
    TypeVar,
)

T = TypeVar("T")
K = TypeVar("K")
V = TypeVar("V")


def pairs_by_keys(
    t: dict[K, V],
    key_func: Optional[Callable[[K], Any]] = None,
) -> Iterator[tuple[K, V]]:
    """
    Iterate over a dictionary in sorted key order.

    Equivalent to Lua's ``table.pairsByKeys(t, f)``.

    In Lua, tables have no guaranteed iteration order, so pairsByKeys
    provides deterministic traversal by sorting the keys first. Python
    dicts maintain insertion order since 3.7, but sorted iteration is
    still useful when you want alphabetical or custom ordering.

    Args:
        t: The dictionary to iterate over.
        key_func: Optional sort key function applied to each dict key.
                  Works like the ``key`` argument to :func:`sorted`.
                  If ``None``, keys are sorted by their natural order.

    Yields:
        Tuples of ``(key, value)`` in sorted key order.

    Examples:
        >>> d = {"banana": 2, "apple": 1, "cherry": 3}
        >>> list(pairs_by_keys(d))
        [('apple', 1), ('banana', 2), ('cherry', 3)]

        >>> list(pairs_by_keys(d, key_func=lambda k: -d[k]))
        [('cherry', 3), ('banana', 2), ('apple', 1)]
    """
    sorted_keys = sorted(t.keys(), key=key_func)  # type: ignore[type-var, arg-type]
    for k in sorted_keys:
        yield k, t[k]


def delete(lst: list[T], value: T) -> bool:
    """
    Remove the first occurrence of *value* from a list.

    Equivalent to Lua's ``table.delete(table, value)``.

    Searches the list sequentially and removes the first element that
    equals *value*, shifting subsequent elements down (preserving order).

    Args:
        lst: The list to modify in place.
        value: The value to find and remove.

    Returns:
        ``True`` if an element was removed, ``False`` if *value* was
        not found in the list.

    Examples:
        >>> items = [1, 2, 3, 2, 1]
        >>> delete(items, 2)
        True
        >>> items
        [1, 3, 2, 1]

        >>> delete(items, 99)
        False
    """
    try:
        lst.remove(value)
        return True
    except ValueError:
        return False


def contains(lst: list[T], value: T) -> bool:
    """
    Check whether a list contains a given value.

    Equivalent to Lua's ``table.contains(table, value)``.

    This is a thin wrapper around Python's ``in`` operator, provided
    for API compatibility with the original Lua module.

    Args:
        lst: The list to search.
        value: The value to look for.

    Returns:
        ``True`` if *value* is found in *lst*, ``False`` otherwise.

    Examples:
        >>> contains([1, 2, 3], 2)
        True
        >>> contains([1, 2, 3], 99)
        False
        >>> contains([], "anything")
        False
    """
    return value in lst


def insert(lst: list[T], value: T, pos: Optional[int] = None) -> None:
    """
    Insert a value into a list, optionally at a specific position.

    Equivalent to Lua's ``table.insert(table, [pos,] value)``.

    If *pos* is not given, appends *value* to the end of the list.
    If *pos* is given, inserts *value* before the element currently at
    that position (0-based, matching Python conventions rather than
    Lua's 1-based indexing).

    Args:
        lst: The list to modify in place.
        value: The value to insert.
        pos: Optional 0-based index at which to insert. If ``None``,
             the value is appended.

    Examples:
        >>> items = [1, 2, 3]
        >>> insert(items, 99)
        >>> items
        [1, 2, 3, 99]

        >>> insert(items, 0, pos=0)
        >>> items
        [0, 1, 2, 3, 99]
    """
    if pos is None:
        lst.append(value)
    else:
        lst.insert(pos, value)


def remove(lst: list[T], pos: Optional[int] = None) -> T:
    """
    Remove and return an element from a list.

    Equivalent to Lua's ``table.remove(table, pos)``.

    If *pos* is not given, removes and returns the last element.
    If *pos* is given, removes and returns the element at that
    position (0-based), shifting subsequent elements down.

    Args:
        lst: The list to modify in place.
        pos: Optional 0-based index of the element to remove.
             If ``None``, the last element is removed.

    Returns:
        The removed element.

    Raises:
        IndexError: If the list is empty or *pos* is out of range.

    Examples:
        >>> items = [10, 20, 30]
        >>> remove(items)
        30
        >>> items
        [10, 20]

        >>> remove(items, 0)
        10
        >>> items
        [20]
    """
    if pos is None:
        return lst.pop()
    return lst.pop(pos)


def sort(
    lst: list[T],
    key_func: Optional[Callable[[T], Any]] = None,
    reverse: bool = False,
) -> None:
    """
    Sort a list in place.

    Equivalent to Lua's ``table.sort(table, comp)``.

    A thin wrapper around :meth:`list.sort` for API consistency with
    the original Lua table module.

    Args:
        lst: The list to sort in place.
        key_func: Optional key function for custom sort order.
        reverse: If ``True``, sort in descending order.

    Examples:
        >>> items = [3, 1, 2]
        >>> sort(items)
        >>> items
        [1, 2, 3]

        >>> sort(items, reverse=True)
        >>> items
        [3, 2, 1]
    """
    lst.sort(key=key_func, reverse=reverse)
