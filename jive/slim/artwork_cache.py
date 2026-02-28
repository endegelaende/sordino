"""
jive.slim.artwork_cache — Size-bounded LRU cache for artwork.

Ported from ``jive/slim/ArtworkCache.lua`` in the original jivelite project.

ArtworkCache implements a Least-Recently-Used (LRU) cache for compressed
artwork data (bytes).  The cache enforces a maximum total size in bytes
and evicts the least-recently-used entries when the limit is exceeded.

The cache stores raw artwork bytes (e.g., JPEG/PNG data).  The separate
``imageCache`` on SlimServer stores decoded Surface objects and uses
Python's weak-reference semantics for automatic eviction.

Internally the LRU ordering is maintained via a doubly-linked list.
Each cache entry contains:

* ``key``   — the cache key (typically ``"<iconId>@<size>/<format>"``)
* ``value`` — the raw bytes, or ``True`` as a "loading" sentinel
* ``bytes`` — the byte count of *value* (0 when *value* is ``True``)
* ``prev``  — link toward the MRU end
* ``next``  — link toward the LRU end

``self._mru`` points to the most-recently-used entry (head).
``self._lru`` points to the least-recently-used entry (tail).

When ``get()`` is called, the accessed entry is promoted to MRU.
When ``set()`` is called with a new value, the entry is inserted at MRU
and old entries are evicted from the LRU end until the total size is
within the configured limit.

Special sentinel value ``True`` marks an entry as "currently loading"
without contributing to the byte total.  This prevents duplicate fetch
requests for the same artwork.

Usage::

    from jive.slim.artwork_cache import ArtworkCache

    cache = ArtworkCache()
    cache.set("abc@200/png", b"\\x89PNG...")
    data = cache.get("abc@200/png")  # returns bytes or None

    cache.set("xyz@100/", True)  # mark as loading
    cache.free()                 # clear all entries

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Copyright 2013-2014 Adrian Smith (jivelite amendments)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Union

__all__ = ["ArtworkCache"]

log = logging.getLogger("squeezebox.server.cache")

# Default artwork cache limit: 24 MiB (matches the Lua original)
_DEFAULT_ARTWORK_LIMIT: int = 24 * 1024 * 1024


class _CacheEntry:
    """
    Internal doubly-linked-list node for the LRU cache.

    Attributes
    ----------
    key : str
        The cache key.
    value : Union[bytes, bool]
        Raw artwork bytes, or ``True`` as a loading sentinel.
    entry_bytes : int
        Byte count of *value* (0 when *value* is ``True``).
    prev : _CacheEntry or None
        Previous entry (toward MRU end).  ``None`` if this is the MRU.
    next : _CacheEntry or None
        Next entry (toward LRU end).  ``None`` if this is the LRU.
    """

    __slots__ = ("key", "value", "entry_bytes", "prev", "next")

    def __init__(
        self,
        key: str,
        value: Union[bytes, bool],
        entry_bytes: int = 0,
    ) -> None:
        self.key: str = key
        self.value: Union[bytes, bool] = value
        self.entry_bytes: int = entry_bytes
        self.prev: Optional[_CacheEntry] = None
        self.next: Optional[_CacheEntry] = None

    def __repr__(self) -> str:  # pragma: no cover — debug aid
        val_repr = (
            f"<{self.entry_bytes} bytes>"
            if isinstance(self.value, (bytes, bytearray))
            else repr(self.value)
        )
        return f"_CacheEntry(key={self.key!r}, value={val_repr})"


class ArtworkCache:
    """
    Size-bounded LRU cache for raw artwork data.

    Parameters
    ----------
    limit : int, optional
        Maximum total bytes of artwork data to keep in the cache.
        Defaults to 24 MiB (``_DEFAULT_ARTWORK_LIMIT``).
    """

    # ------------------------------------------------------------------
    # Construction / teardown
    # ------------------------------------------------------------------

    def __init__(self, limit: int = _DEFAULT_ARTWORK_LIMIT) -> None:
        self._limit: int = limit
        # Backing store: key → _CacheEntry
        self._cache: Dict[str, _CacheEntry] = {}
        # Doubly-linked list endpoints
        self._mru: Optional[_CacheEntry] = None
        self._lru: Optional[_CacheEntry] = None
        # Running total of stored bytes (excludes "loading" sentinels)
        self._total: int = 0

    def free(self) -> None:
        """
        Clear the entire cache, releasing all entries and resetting
        the byte total.
        """
        self._cache.clear()
        self._mru = None
        self._lru = None
        self._total = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set(self, key: str, value: Optional[Union[bytes, bool]]) -> None:
        """
        Store or remove a cache entry.

        Parameters
        ----------
        key : str
            Cache key (e.g., ``"<iconId>@<size>/<format>"``).
        value : bytes, True, or None
            * ``None``  — remove the entry for *key*.
            * ``True``  — mark *key* as "loading" (no byte cost).
            * ``bytes`` — store the raw artwork data and enforce the
              size limit, evicting LRU entries as needed.
        """
        # --- Remove existing entry first (if any) ---
        old_entry = self._cache.get(key)
        if old_entry is not None:
            self._unlink(old_entry)
            self._total -= old_entry.entry_bytes
            del self._cache[key]

        # --- Clear entry ---
        if value is None:
            return

        # --- Mark as loading ---
        if value is True:
            entry = _CacheEntry(key=key, value=True, entry_bytes=0)
            self._cache[key] = entry
            # Loading sentinels are NOT linked into the LRU list —
            # they have no byte cost and should never be evicted.
            return

        # --- Store artwork bytes ---
        if not isinstance(value, (bytes, bytearray)):
            raise TypeError(
                f"ArtworkCache.set() expects bytes, True, or None — "
                f"got {type(value).__name__}"
            )

        nbytes = len(value)
        entry = _CacheEntry(key=key, value=value, entry_bytes=nbytes)
        self._cache[key] = entry
        self._total += nbytes

        # Link at MRU end
        self._link_mru(entry)

        # Evict from LRU end while over the limit
        while self._total > self._limit and self._lru is not None:
            victim = self._lru
            log.debug(
                "Free artwork entry=%s total=%d",
                victim.key,
                self._total,
            )

            # Remove from backing store
            self._cache.pop(victim.key, None)

            # Unlink from list
            self._unlink(victim)
            self._total -= victim.entry_bytes

        if log.isEnabledFor(logging.DEBUG):
            self.dump()

    def get(self, key: str) -> Optional[Union[bytes, bool]]:
        """
        Retrieve a cache entry, promoting it to most-recently-used.

        Parameters
        ----------
        key : str
            The cache key.

        Returns
        -------
        bytes
            The stored artwork data.
        True
            The entry is marked as "loading".
        None
            The key is not in the cache.
        """
        entry = self._cache.get(key)
        if entry is None:
            return None

        # Loading sentinel — return immediately, no LRU promotion
        if entry.value is True:
            return True

        # Already the MRU entry — nothing to do
        if self._mru is entry:
            return entry.value

        # Promote to MRU
        self._unlink(entry)
        self._link_mru(entry)

        if log.isEnabledFor(logging.DEBUG):
            self.dump()

        return entry.value

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def dump(self) -> None:
        """
        Log cache statistics at DEBUG level.
        """
        # Count entries via the backing dict
        cached_items = len(self._cache)

        # Count linked-list items (those with byte cost)
        linked_items = 0
        node = self._mru
        while node is not None:
            linked_items += 1
            node = node.next

        fullness = (self._total / self._limit * 100) if self._limit else 0.0

        log.debug(
            "artworkThumbCache items=%d linked=%d bytes=%d fullness=%.1f%%",
            cached_items,
            linked_items,
            self._total,
            fullness,
        )

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def total(self) -> int:
        """Return the current total byte usage."""
        return self._total

    @property
    def limit(self) -> int:
        """Return the configured byte limit."""
        return self._limit

    @limit.setter
    def limit(self, value: int) -> None:
        """
        Set a new byte limit.  If the current total exceeds the new
        limit, LRU entries are evicted immediately.
        """
        self._limit = value
        while self._total > self._limit and self._lru is not None:
            victim = self._lru
            self._cache.pop(victim.key, None)
            self._unlink(victim)
            self._total -= victim.entry_bytes

    def __len__(self) -> int:
        """Return the number of entries (including loading sentinels)."""
        return len(self._cache)

    def __contains__(self, key: str) -> bool:
        """Check whether *key* is in the cache."""
        return key in self._cache

    def __repr__(self) -> str:
        return (
            f"ArtworkCache(limit={self._limit}, "
            f"items={len(self._cache)}, "
            f"bytes={self._total})"
        )

    # ------------------------------------------------------------------
    # Internal linked-list operations
    # ------------------------------------------------------------------

    def _unlink(self, entry: _CacheEntry) -> None:
        """Remove *entry* from the doubly-linked list."""
        if entry.prev is not None:
            entry.prev.next = entry.next
        else:
            # entry was the MRU head
            self._mru = entry.next

        if entry.next is not None:
            entry.next.prev = entry.prev
        else:
            # entry was the LRU tail
            self._lru = entry.prev

        entry.prev = None
        entry.next = None

    def _link_mru(self, entry: _CacheEntry) -> None:
        """Insert *entry* at the MRU (head) end of the list."""
        entry.prev = None
        entry.next = self._mru

        if self._mru is not None:
            self._mru.prev = entry

        self._mru = entry

        if self._lru is None:
            self._lru = entry
