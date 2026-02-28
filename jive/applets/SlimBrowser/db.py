"""
jive.applets.slim_browser.db — Item database for browsing data.

Ported from ``share/jive/applets/SlimBrowser/DB.lua`` (~386 LOC) in the
original jivelite project.

This class stores and manages the browsing data that Jive receives from
the server. Conceptually, the data is a long list of items which is
received in chunks. Each chunk is a dict with properties including:

- ``count``: total number of items in the long list
- ``offset``: index of the first item in ``item_loop``
- ``item_loop``: list of consecutive items
- ``playlist_timestamp``: optional timestamp for change detection

If count is 0, the other fields are optional.

Fresh data always replaces old data, except when it would be cost-
prohibitive to do so. There should be one DB per long list "type". If
the count or timestamp changes, existing data is discarded.

Copyright 2010 Logitech. All Rights Reserved. (original Lua code)
Python port: 2025
License: BSD-3-Clause
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

from jive.utils.log import logger

__all__ = ["DB"]

log = logger("applet.SlimBrowser.data")

# Block size for chunked loading
BLOCK_SIZE = 200


class DB:
    """Sparse database of menu items received from the server.

    Items are stored in blocks of ``BLOCK_SIZE`` and can be accessed
    individually by 1-based index. The database tracks the total item
    count, a playlist timestamp (for change detection), and the
    current playlist index.
    """

    def __init__(self, window_spec: Optional[Dict[str, Any]] = None) -> None:
        if window_spec is None:
            window_spec = {}

        # Data storage — keyed by block number
        self.store: Dict[int, List[Dict[str, Any]]] = {}

        # Text index for accelerated alphabetical scrolling
        self.text_index: Dict[str, int] = {}

        # Last chunk received (for accessing non-DB fields)
        self.last_chunk: Optional[Dict[str, Any]] = None

        # Major items extracted from data
        self.count: int = 0
        self.ts: Any = False  # playlist_timestamp (False = not set)
        self.current_index: int = 0  # 1-based current song index

        # Cache flags
        self.last_indexed_chunk: Any = False
        self.complete: bool = False
        self.up_completed: bool = False
        self.down_completed: bool = False

        # Search direction state
        self.search_direction: Optional[str] = None

        # Window spec (for creating labels in renderer)
        self.window_spec: Dict[str, Any] = dict(window_spec)

        # Radio group (lazy-created)
        self._radio_group: Any = None

    # ------------------------------------------------------------------
    # Window spec accessors
    # ------------------------------------------------------------------

    def menu_style(self) -> str:
        """Return the menu style string."""
        return self.window_spec.get("menuStyle", "menu")

    # Alias for Lua compatibility
    def menuStyle(self) -> str:
        return self.menu_style()

    def window_style(self) -> str:
        """Return the window style string."""
        return self.window_spec.get("windowStyle", "text_list")

    # Alias
    def windowStyle(self) -> str:
        return self.window_style()

    def label_item_style(self) -> str:
        """Return the label item style string."""
        return self.window_spec.get("labelItemStyle", "item")

    # Alias
    def labelItemStyle(self) -> str:
        return self.label_item_style()

    @staticmethod
    def get_block_size() -> int:
        """Return the block size used for chunked loading."""
        return BLOCK_SIZE

    # Alias
    @staticmethod
    def getBlockSize() -> int:
        return BLOCK_SIZE

    # ------------------------------------------------------------------
    # Radio group
    # ------------------------------------------------------------------

    def get_radio_group(self) -> Any:
        """Return (or create) the RadioGroup for this DB."""
        if self._radio_group is None:
            try:
                from jive.ui.radio import RadioGroup

                self._radio_group = RadioGroup()
            except ImportError:
                # Headless / test mode — use a stub
                self._radio_group = _RadioGroupStub()
        return self._radio_group

    # Alias
    def getRadioGroup(self) -> Any:
        return self.get_radio_group()

    # ------------------------------------------------------------------
    # Status update
    # ------------------------------------------------------------------

    def update_status(self, chunk: Dict[str, Any]) -> bool:
        """Update the DB status from a received chunk.

        Returns ``True`` if the stored data was invalidated (i.e. a
        reset occurred because count or timestamp changed).
        """
        assert "count" in chunk, "chunk must have 'count' field"

        # Keep the chunk as header
        self.last_chunk = chunk

        # Update currentIndex if present
        current_index = chunk.get("playlist_cur_index")
        if current_index is not None:
            self.current_index = int(current_index) + 1  # 0-based → 1-based

        # Detect changes that invalidate data
        ts = chunk.get("playlist_timestamp", False)
        c_count = int(chunk["count"])

        reset = False
        if c_count != self.count:
            log.debug("..store invalid, different count")
            reset = True
        elif ts and self.ts != ts:
            log.debug("..store invalid, different timestamp")
            reset = True

        if reset:
            self.store = {}
            self.complete = False
            self.up_completed = False
            self.down_completed = False
            self.text_index = {}

        # Update window properties from chunk
        window = chunk.get("window")
        if window is None and isinstance(chunk.get("data"), dict):
            window = chunk["data"].get("window")
        if window:
            if "menuStyle" in window:
                self.window_spec["menuStyle"] = window["menuStyle"] + "menu"
                self.window_spec["labelItemStyle"] = window["menuStyle"] + "item"
            if "windowStyle" in window:
                self.window_spec["windowStyle"] = window["windowStyle"]

        self.ts = ts
        self.count = c_count

        return reset

    # Alias
    def updateStatus(self, chunk: Dict[str, Any]) -> bool:
        return self.update_status(chunk)

    # ------------------------------------------------------------------
    # Menu items
    # ------------------------------------------------------------------

    def menu_items(self, chunk: Optional[Dict[str, Any]] = None) -> Tuple[int, ...]:
        """Store the chunk and return data suitable for ``menu.set_items()``.

        Returns
        -------
        tuple
            ``(count,)`` if no chunk is provided, or
            ``(count, c_from, c_to)`` after storing the chunk.
        """
        log.debug("DB.menu_items()")

        if chunk is None:
            return (self.count,)

        # Update status
        self.update_status(chunk)

        # Fix offset — CLI is 0-based, we are 1-based
        c_from = 0
        c_to = 0
        if self.count > 0:
            item_loop = chunk.get("item_loop")
            assert item_loop is not None, "chunk must have item_loop if count > 0"
            assert "offset" in chunk, "chunk must have offset field if count > 0"

            c_from = int(chunk["offset"]) + 1
            c_to = c_from + len(item_loop) - 1

        # Store chunk by block key
        key = c_from // BLOCK_SIZE

        log.debug("loading key number %d", key)
        log.debug("c_from: %d", c_from)
        log.debug("c_to: %d", c_to)

        item_loop = chunk.get("item_loop", [])
        self.store[key] = item_loop

        # Build text index
        offset_val = int(chunk.get("offset", 0))
        for i, item_data in enumerate(item_loop):
            index = i + offset_val
            text_key = item_data.get("textkey")
            if text_key is None:
                params = item_data.get("params")
                if isinstance(params, dict):
                    text_key = params.get("textkey")
            if text_key is not None:
                existing = self.text_index.get(text_key)
                if existing is None or existing > index:
                    self.text_index[text_key] = index

        return (self.count, c_from, c_to)

    # Alias
    def menuItems(self, chunk: Optional[Dict[str, Any]] = None) -> Tuple[int, ...]:
        return self.menu_items(chunk)

    # ------------------------------------------------------------------
    # Text index
    # ------------------------------------------------------------------

    def get_text_indexes(self) -> List[Dict[str, Any]]:
        """Return text indexes sorted by index value.

        Returns a list of ``{"key": str, "index": int}`` dicts.
        """
        tmp = [{"key": k, "index": v} for k, v in self.text_index.items()]
        tmp.sort(key=lambda x: x["index"])
        return tmp

    # Alias
    def getTextIndexes(self) -> List[Dict[str, Any]]:
        return self.get_text_indexes()

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    def chunk(self) -> Optional[Dict[str, Any]]:
        """Return the last received chunk."""
        return self.last_chunk

    def playlist_index(self) -> Optional[int]:
        """Return the 1-based current playlist index, or ``None``."""
        if self.ts:
            return self.current_index
        return None

    # Alias
    def playlistIndex(self) -> Optional[int]:
        return self.playlist_index()

    def item(self, index: int) -> Tuple[Optional[Dict[str, Any]], bool]:
        """Return ``(item_dict, is_current)`` for the given 1-based index.

        Returns ``(None, False)`` if the item has not been loaded yet.
        """
        current = index == self.current_index

        # Convert to 0-based
        idx0 = index - 1

        key = idx0 // BLOCK_SIZE
        offset = idx0 % BLOCK_SIZE

        block = self.store.get(key)
        if block is None:
            return None, False

        if offset >= len(block):
            return None, False

        return block[offset], current

    def size(self) -> int:
        """Return the total number of items."""
        return self.count

    # ------------------------------------------------------------------
    # Missing chunks
    # ------------------------------------------------------------------

    def missing(self, index: Optional[int] = None) -> Optional[Tuple[int, int]]:
        """Identify the next chunk to load.

        Parameters
        ----------
        index : int or None
            If provided, load the chunk containing this 1-based index
            first, then expand outward. If ``None``, load first chunk,
            last chunk, then middle chunks top-down.

        Returns
        -------
        tuple or None
            ``(from_offset, block_size)`` for the next chunk to load,
            or ``None`` if all chunks are loaded.
        """
        # Use cached result
        if self.complete:
            log.debug("%s complete (cached)", self)
            return None

        if self.last_chunk is None or "count" not in self.last_chunk:
            return (0, BLOCK_SIZE)

        count = int(self.last_chunk["count"])
        if count == 0:
            self.complete = True
            return None

        # Determine the key for the last chunk
        last_key = 0
        if count > BLOCK_SIZE:
            last_key = count // BLOCK_SIZE
            if last_key * BLOCK_SIZE == count:
                last_key -= 1

        first_chunk_from = 0
        first_chunk_key = 0

        if index is None:
            # Load first chunk
            if 0 not in self.store:
                return (0, BLOCK_SIZE)
            # Load last chunk
            if last_key not in self.store:
                return (last_key * BLOCK_SIZE, BLOCK_SIZE)
            # Up is done, search downward
            self.search_direction = "down"
            self.up_completed = True
        else:
            # Calculate the block for this index
            first_chunk_from = index - (index % BLOCK_SIZE)
            first_chunk_key = first_chunk_from // BLOCK_SIZE

        # Don't search down if the first chunk is also the last
        if first_chunk_from + BLOCK_SIZE >= count:
            self.down_completed = True
            self.search_direction = "up"

        # Both done?
        if self.down_completed and self.up_completed:
            log.debug("%s scan complete (calculated)", self)
            self.complete = True
            return None

        # Search up and down around first_chunk_key
        if self.search_direction is None:
            self.search_direction = "up"

        if self.search_direction == "up" and not self.up_completed:
            # Search upward from first_chunk_key - 1 down to 0
            if not self.down_completed:
                self.search_direction = "down"

            for key in range(first_chunk_key - 1, -1, -1):
                if key not in self.store:
                    this_from = key * BLOCK_SIZE
                    if key == 0:
                        self.up_completed = True
                    return (this_from, BLOCK_SIZE)
            self.up_completed = True

        if self.search_direction == "down" and not self.down_completed:
            if not self.up_completed:
                self.search_direction = "up"

            for key in range(first_chunk_key + 1, last_key + 1):
                if key not in self.store:
                    this_from = key * BLOCK_SIZE
                    if key == last_key:
                        self.down_completed = True
                    return (this_from, BLOCK_SIZE)
            self.down_completed = True

        # If we reach here and both are done, mark complete
        if self.down_completed and self.up_completed:
            self.complete = True

        return None

    # ------------------------------------------------------------------
    # Dunder methods
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        text = self.window_spec.get("text", "")
        return f"DB {{{text}}}"

    def __str__(self) -> str:
        return self.__repr__()


# ======================================================================
# Stub for headless / test mode
# ======================================================================


class _RadioGroupStub:
    """Minimal stub for RadioGroup when UI is not available."""

    def __init__(self) -> None:
        self._selected: Any = None
        self._buttons: List[Any] = []

    def add_button(self, button: Any) -> None:
        self._buttons.append(button)

    def get_selected(self) -> Any:
        return self._selected

    def set_selected(self, button: Any) -> None:
        self._selected = button
