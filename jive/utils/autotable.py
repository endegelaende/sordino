"""
jive.utils.autotable — Auto-vivifying nested dictionaries.

Ported from share/jive/jive/utils/autotable.lua

Creates dictionaries that automatically create missing sub-dictionaries
on access, eliminating the need to manually initialise intermediate
levels of a nested structure.

In Lua, an "autotable" is a table with a metatable that intercepts
__index (read of missing key) and __newindex (write of missing key)
to automatically create sub-tables.  In Python we achieve the same
effect by subclassing :class:`dict` and overriding ``__missing__``.

Usage::

    from jive.utils.autotable import AutoTable

    # Create an auto-vivifying dict
    harry = AutoTable()

    # Intermediate dicts are created automatically
    harry["potter"]["magic"]["wand"] = 33

    # Equivalent — attribute-style access also works
    config = AutoTable()
    config.display.width = 800
    config.display.height = 480
    config.network.timeout = 30

    print(config["display"]["width"])  # 800

    # Convert to a plain dict (recursively) for serialisation
    plain = config.to_dict()

Copyright 2010 Logitech. All Rights Reserved.
This file is licensed under BSD. Please see the LICENSE file for details.
"""

from __future__ import annotations

from typing import Any, Iterator


class AutoTable(dict):  # type: ignore[type-arg]
    """
    A dictionary that automatically creates nested sub-dictionaries
    when a missing key is accessed.

    This replicates the Lua ``autotable`` pattern where writing to
    ``t.a.b.c = value`` automatically creates tables ``a`` and ``b``
    as intermediaries.

    Both item access (``d["key"]``) and attribute access (``d.key``)
    are supported for convenience.  Attribute access is syntactic sugar
    that delegates to ``__getitem__`` / ``__setitem__``.

    Examples:
        >>> t = AutoTable()
        >>> t["a"]["b"]["c"] = 42
        >>> t["a"]["b"]["c"]
        42

        >>> t2 = AutoTable()
        >>> t2.x.y = 10
        >>> t2["x"]["y"]
        10

        >>> # Accessing a missing key returns a new empty AutoTable
        >>> sub = t["nonexistent"]
        >>> isinstance(sub, AutoTable)
        True
    """

    # ── Core auto-vivification ────────────────────────────────────────────

    def __missing__(self, key: Any) -> "AutoTable":
        """
        Called by ``__getitem__`` when *key* is not found.

        Creates a new :class:`AutoTable` for the missing key, stores it,
        and returns it.  This is the mechanism that enables chained
        assignment like ``t["a"]["b"]["c"] = value`` without manual
        initialisation of intermediate dictionaries.
        """
        value: AutoTable = AutoTable()
        self[key] = value
        return value

    # ── Attribute-style access ────────────────────────────────────────────

    def __getattr__(self, name: str) -> Any:
        """
        Enable ``t.key`` as shorthand for ``t["key"]``.

        Raises :exc:`KeyError` (via ``__missing__``, which creates a new
        sub-table) only for genuine attribute-style access — never for
        Python internals or dunder methods.
        """
        # Avoid infinite recursion for dunder/private attributes that
        # Python's object machinery looks up internally.
        if name.startswith("_"):
            raise AttributeError(
                f"'{type(self).__name__}' object has no attribute {name!r}"
            )
        try:
            return self[name]
        except KeyError:
            # __missing__ should make this unreachable, but guard anyway
            raise AttributeError(
                f"'{type(self).__name__}' object has no attribute {name!r}"
            ) from None

    def __setattr__(self, name: str, value: Any) -> None:
        """
        Enable ``t.key = value`` as shorthand for ``t["key"] = value``.
        """
        if name.startswith("_"):
            # Let Python handle true private/dunder attributes normally
            super().__setattr__(name, value)
        else:
            self[name] = value

    def __delattr__(self, name: str) -> None:
        """
        Enable ``del t.key`` as shorthand for ``del t["key"]``.
        """
        if name.startswith("_"):
            super().__delattr__(name)
        else:
            try:
                del self[name]
            except KeyError:
                raise AttributeError(
                    f"'{type(self).__name__}' object has no attribute {name!r}"
                ) from None

    # ── Conversion ────────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        """
        Recursively convert this :class:`AutoTable` (and all nested
        ``AutoTable`` instances) to plain :class:`dict` objects.

        Empty auto-vivified sub-tables (created by read access but
        never assigned to) are pruned — they become empty ``{}``
        in the output, matching the expectation that accessing a
        missing key should not permanently pollute the structure
        when you later serialise it.

        Returns:
            A plain ``dict`` tree with no ``AutoTable`` instances.

        Examples:
            >>> t = AutoTable()
            >>> t["a"]["b"] = 1
            >>> t.to_dict()
            {'a': {'b': 1}}
        """
        result: dict[str, Any] = {}
        for key, value in self.items():
            if isinstance(value, AutoTable):
                result[key] = value.to_dict()
            else:
                result[key] = value
        return result

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "AutoTable":
        """
        Recursively convert a plain :class:`dict` to an :class:`AutoTable`.

        Nested dictionaries are also converted, so the result is fully
        auto-vivifying at every level.

        Args:
            d: A plain dictionary, potentially with nested dicts.

        Returns:
            An ``AutoTable`` mirroring the structure of *d*.

        Examples:
            >>> plain = {"a": {"b": 1}, "c": 2}
            >>> t = AutoTable.from_dict(plain)
            >>> t["a"]["b"]
            1
            >>> t.c
            2
        """
        at = cls()
        for key, value in d.items():
            if isinstance(value, dict):
                at[key] = cls.from_dict(value)
            else:
                at[key] = value
        return at

    # ── Representation ────────────────────────────────────────────────────

    def __repr__(self) -> str:
        """
        Return a string representation that makes the auto-vivifying
        nature clear.

        Examples:
            >>> AutoTable()
            AutoTable({})
            >>> t = AutoTable(); t["a"] = 1
            AutoTable({'a': 1})
        """
        return f"AutoTable({dict.__repr__(self)})"


# ── Module-level factory (matching Lua API) ───────────────────────────────


def new() -> AutoTable:
    """
    Create and return a new auto-vivifying table.

    This is the module-level factory matching the Lua API::

        local autotable = require("jive.utils.autotable")
        local t = autotable.new()

    In Python, you can also just call ``AutoTable()`` directly.

    Returns:
        A new empty :class:`AutoTable`.
    """
    return AutoTable()
