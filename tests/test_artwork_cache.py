"""Tests for jive.slim.artwork_cache — LRU artwork cache."""

from __future__ import annotations

import pytest

from jive.slim.artwork_cache import ArtworkCache

# ---------------------------------------------------------------------------
# Construction / basics
# ---------------------------------------------------------------------------


class TestBasicOperations:
    """Basic get / set / contains / len / free."""

    def test_get_missing_key_returns_none(self) -> None:
        cache = ArtworkCache()
        assert cache.get("nonexistent") is None

    def test_set_and_get_bytes(self) -> None:
        cache = ArtworkCache()
        data = b"\x89PNG fake image data"
        cache.set("img@200/png", data)
        assert cache.get("img@200/png") == data

    def test_set_none_removes_entry(self) -> None:
        cache = ArtworkCache()
        cache.set("k", b"hello")
        assert "k" in cache
        cache.set("k", None)
        assert "k" not in cache
        assert cache.get("k") is None

    def test_set_none_on_missing_key_is_noop(self) -> None:
        cache = ArtworkCache()
        cache.set("nonexistent", None)  # should not raise
        assert len(cache) == 0

    def test_len_reflects_entry_count(self) -> None:
        cache = ArtworkCache()
        assert len(cache) == 0
        cache.set("a", b"aaa")
        assert len(cache) == 1
        cache.set("b", b"bbb")
        assert len(cache) == 2
        cache.set("a", None)
        assert len(cache) == 1

    def test_contains(self) -> None:
        cache = ArtworkCache()
        cache.set("present", b"data")
        assert "present" in cache
        assert "absent" not in cache

    def test_free_clears_everything(self) -> None:
        cache = ArtworkCache()
        cache.set("a", b"aaaa")
        cache.set("b", b"bbbb")
        cache.set("c", True)
        cache.free()
        assert len(cache) == 0
        assert cache.total == 0
        assert cache.get("a") is None
        assert cache.get("b") is None
        assert cache.get("c") is None

    def test_repr_includes_stats(self) -> None:
        cache = ArtworkCache(limit=1000)
        cache.set("x", b"12345")
        r = repr(cache)
        assert "1000" in r
        assert "items=1" in r
        assert "bytes=5" in r

    def test_empty_bytes_value(self) -> None:
        cache = ArtworkCache()
        cache.set("empty", b"")
        assert cache.get("empty") == b""
        assert cache.total == 0


# ---------------------------------------------------------------------------
# Loading sentinel
# ---------------------------------------------------------------------------


class TestLoadingSentinel:
    """The special ``True`` value marks a key as 'loading'."""

    def test_set_true_marks_loading(self) -> None:
        cache = ArtworkCache()
        cache.set("loading_key", True)
        assert cache.get("loading_key") is True

    def test_loading_sentinel_in_cache(self) -> None:
        cache = ArtworkCache()
        cache.set("k", True)
        assert "k" in cache

    def test_loading_sentinel_counts_in_len(self) -> None:
        cache = ArtworkCache()
        cache.set("a", b"data")
        cache.set("b", True)
        assert len(cache) == 2

    def test_loading_sentinel_zero_byte_cost(self) -> None:
        cache = ArtworkCache()
        cache.set("a", True)
        assert cache.total == 0

    def test_loading_sentinel_not_evictable(self) -> None:
        """Loading sentinels are not in the LRU list and cannot be evicted."""
        cache = ArtworkCache(limit=10)
        cache.set("sentinel", True)
        # Fill cache past limit — sentinel must survive
        cache.set("big", b"x" * 20)
        # big itself exceeds the limit so it stays as the only linked entry
        # but the sentinel should still be present
        assert "sentinel" in cache
        assert cache.get("sentinel") is True

    def test_replace_loading_with_bytes(self) -> None:
        cache = ArtworkCache()
        cache.set("k", True)
        assert cache.get("k") is True
        cache.set("k", b"actual data")
        assert cache.get("k") == b"actual data"
        assert cache.total == len(b"actual data")

    def test_replace_bytes_with_loading(self) -> None:
        cache = ArtworkCache()
        cache.set("k", b"12345")
        assert cache.total == 5
        cache.set("k", True)
        assert cache.get("k") is True
        assert cache.total == 0

    def test_remove_loading_sentinel(self) -> None:
        cache = ArtworkCache()
        cache.set("k", True)
        cache.set("k", None)
        assert "k" not in cache
        assert len(cache) == 0


# ---------------------------------------------------------------------------
# LRU eviction
# ---------------------------------------------------------------------------


class TestLRUEviction:
    """LRU eviction behaviour when the byte limit is exceeded."""

    def test_evicts_lru_when_over_limit(self) -> None:
        cache = ArtworkCache(limit=100)
        cache.set("a", b"x" * 50)
        cache.set("b", b"x" * 50)
        # Cache is at exactly 100 — no eviction yet
        assert "a" in cache
        assert "b" in cache
        # Adding a third pushes over the limit; "a" is LRU
        cache.set("c", b"x" * 50)
        assert "a" not in cache
        assert "b" in cache
        assert "c" in cache

    def test_get_promotes_to_mru(self) -> None:
        """Accessing an entry via get() makes it most-recently-used."""
        cache = ArtworkCache(limit=100)
        cache.set("a", b"x" * 50)
        cache.set("b", b"x" * 50)
        # "a" is LRU, "b" is MRU. Promote "a":
        cache.get("a")
        # Now "b" is LRU. Adding "c" should evict "b", not "a".
        cache.set("c", b"x" * 50)
        assert "a" in cache
        assert "b" not in cache
        assert "c" in cache

    def test_evicts_multiple_entries_if_needed(self) -> None:
        cache = ArtworkCache(limit=100)
        cache.set("a", b"x" * 30)
        cache.set("b", b"x" * 30)
        cache.set("c", b"x" * 30)
        # total = 90, under limit
        assert len(cache) == 3
        # Insert a large entry that requires evicting both a and b
        cache.set("big", b"x" * 80)
        assert "a" not in cache
        assert "b" not in cache
        assert "c" not in cache
        assert "big" in cache

    def test_eviction_order_is_lru(self) -> None:
        """Entries are evicted oldest-first."""
        cache = ArtworkCache(limit=150)
        cache.set("first", b"x" * 50)
        cache.set("second", b"x" * 50)
        cache.set("third", b"x" * 50)
        # total = 150, at limit
        # Insert one more — "first" (LRU) should be evicted
        cache.set("fourth", b"x" * 50)
        assert "first" not in cache
        assert "second" in cache
        assert "third" in cache
        assert "fourth" in cache

    def test_total_tracks_bytes_after_eviction(self) -> None:
        cache = ArtworkCache(limit=100)
        cache.set("a", b"x" * 60)
        cache.set("b", b"x" * 60)
        # "a" should be evicted, total = 60
        assert cache.total == 60

    def test_single_entry_exceeding_limit(self) -> None:
        """A single entry larger than the limit is inserted then
        immediately evicted (it becomes both MRU and LRU)."""
        cache = ArtworkCache(limit=10)
        cache.set("huge", b"x" * 100)
        # The entry evicts itself because it exceeds the limit
        assert "huge" not in cache
        assert cache.total == 0
        assert len(cache) == 0

    def test_loading_sentinels_survive_eviction(self) -> None:
        """Loading sentinels are never in the LRU list, so eviction skips them."""
        cache = ArtworkCache(limit=50)
        cache.set("sentinel1", True)
        cache.set("sentinel2", True)
        cache.set("data_a", b"x" * 30)
        cache.set("data_b", b"x" * 30)
        # Over limit → data_a evicted
        assert "sentinel1" in cache
        assert "sentinel2" in cache
        assert "data_a" not in cache
        assert "data_b" in cache


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------


class TestProperties:
    """Test total, limit, and limit-setter."""

    def test_total_starts_at_zero(self) -> None:
        assert ArtworkCache().total == 0

    def test_total_accumulates(self) -> None:
        cache = ArtworkCache()
        cache.set("a", b"123")
        cache.set("b", b"45678")
        assert cache.total == 8

    def test_total_decreases_on_remove(self) -> None:
        cache = ArtworkCache()
        cache.set("a", b"12345")
        cache.set("a", None)
        assert cache.total == 0

    def test_limit_property(self) -> None:
        cache = ArtworkCache(limit=5000)
        assert cache.limit == 5000

    def test_default_limit_is_24mib(self) -> None:
        cache = ArtworkCache()
        assert cache.limit == 24 * 1024 * 1024

    def test_set_lower_limit_triggers_eviction(self) -> None:
        cache = ArtworkCache(limit=1000)
        cache.set("a", b"x" * 400)
        cache.set("b", b"x" * 400)
        cache.set("c", b"x" * 200)
        assert cache.total == 1000
        # Lower the limit — should evict LRU entries
        cache.limit = 500
        assert cache.total <= 500
        # "a" was LRU, should be gone first
        assert "a" not in cache

    def test_set_higher_limit_no_eviction(self) -> None:
        cache = ArtworkCache(limit=100)
        cache.set("a", b"x" * 50)
        cache.set("b", b"x" * 50)
        cache.limit = 200
        assert "a" in cache
        assert "b" in cache
        assert cache.total == 100

    def test_dump_does_not_raise(self) -> None:
        """dump() logs at DEBUG level and must not raise."""
        cache = ArtworkCache(limit=100)
        cache.set("a", b"data")
        cache.set("b", True)
        cache.dump()  # should not raise

    def test_dump_on_empty_cache(self) -> None:
        ArtworkCache().dump()  # should not raise


# ---------------------------------------------------------------------------
# Replacement / update
# ---------------------------------------------------------------------------


class TestReplacement:
    """Replacing an existing key with a new value."""

    def test_replace_updates_value(self) -> None:
        cache = ArtworkCache()
        cache.set("k", b"old")
        cache.set("k", b"new_value")
        assert cache.get("k") == b"new_value"

    def test_replace_updates_byte_total(self) -> None:
        cache = ArtworkCache()
        cache.set("k", b"12345")  # 5 bytes
        assert cache.total == 5
        cache.set("k", b"ab")  # 2 bytes
        assert cache.total == 2

    def test_replace_does_not_double_count(self) -> None:
        cache = ArtworkCache()
        cache.set("k", b"xxxxx")
        cache.set("k", b"yyy")
        assert cache.total == 3  # not 8

    def test_replace_with_larger_value(self) -> None:
        cache = ArtworkCache()
        cache.set("k", b"ab")
        cache.set("k", b"abcdef")
        assert cache.total == 6

    def test_replace_promotes_to_mru(self) -> None:
        """Replacing a key should put it at the MRU end."""
        cache = ArtworkCache(limit=100)
        cache.set("a", b"x" * 40)
        cache.set("b", b"x" * 40)
        # "a" is LRU. Replace "a" with new data:
        cache.set("a", b"y" * 40)
        # Now "b" is LRU. Adding "c" should evict "b":
        cache.set("c", b"z" * 40)
        assert "a" in cache
        assert "b" not in cache
        assert "c" in cache


# ---------------------------------------------------------------------------
# Type safety
# ---------------------------------------------------------------------------


class TestTypeSafety:
    """Invalid value types raise TypeError."""

    def test_set_string_raises(self) -> None:
        cache = ArtworkCache()
        with pytest.raises(TypeError, match="str"):
            cache.set("k", "not bytes")  # type: ignore[arg-type]

    def test_set_int_raises(self) -> None:
        cache = ArtworkCache()
        with pytest.raises(TypeError, match="int"):
            cache.set("k", 42)  # type: ignore[arg-type]

    def test_set_list_raises(self) -> None:
        cache = ArtworkCache()
        with pytest.raises(TypeError, match="list"):
            cache.set("k", [1, 2, 3])  # type: ignore[arg-type]

    def test_set_false_raises(self) -> None:
        """Only ``True`` is the loading sentinel; ``False`` is invalid."""
        cache = ArtworkCache()
        with pytest.raises(TypeError):
            cache.set("k", False)  # type: ignore[arg-type]

    def test_set_bytearray_accepted(self) -> None:
        cache = ArtworkCache()
        cache.set("k", bytearray(b"hello"))
        assert cache.get("k") == bytearray(b"hello")
        assert cache.total == 5


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_single_entry_cache(self) -> None:
        cache = ArtworkCache(limit=10)
        cache.set("only", b"x" * 10)
        assert cache.get("only") == b"x" * 10
        assert cache.total == 10

    def test_zero_limit_evicts_immediately(self) -> None:
        cache = ArtworkCache(limit=0)
        cache.set("k", b"data")
        # Entry added then immediately evicted (it's the only LRU entry)
        assert "k" not in cache
        assert cache.total == 0

    def test_get_on_empty_cache(self) -> None:
        assert ArtworkCache().get("anything") is None

    def test_free_on_empty_cache(self) -> None:
        cache = ArtworkCache()
        cache.free()  # should not raise
        assert len(cache) == 0

    def test_many_entries(self) -> None:
        cache = ArtworkCache(limit=10_000)
        for i in range(200):
            cache.set(f"key_{i}", b"x" * 10)
        # 200 * 10 = 2000 bytes, under limit
        assert len(cache) == 200
        assert cache.total == 2000

    def test_get_does_not_promote_missing(self) -> None:
        """get() on a missing key returns None and doesn't modify cache."""
        cache = ArtworkCache()
        cache.set("a", b"aaa")
        result = cache.get("missing")
        assert result is None
        assert len(cache) == 1

    def test_get_mru_entry_no_change(self) -> None:
        """Getting the already-MRU entry is a no-op (no crash)."""
        cache = ArtworkCache()
        cache.set("a", b"data")
        # "a" is already MRU; get should still return data
        assert cache.get("a") == b"data"
        assert cache.get("a") == b"data"

    def test_exact_limit_no_eviction(self) -> None:
        cache = ArtworkCache(limit=100)
        cache.set("a", b"x" * 50)
        cache.set("b", b"x" * 50)
        # Exactly at limit — no eviction
        assert "a" in cache
        assert "b" in cache
        assert cache.total == 100

    def test_interleaved_loading_and_data(self) -> None:
        """Mix loading sentinels and real data in various orders."""
        cache = ArtworkCache(limit=100)
        cache.set("a", True)
        cache.set("b", b"x" * 50)
        cache.set("c", True)
        cache.set("d", b"x" * 50)
        assert len(cache) == 4
        assert cache.total == 100
        # Now push over limit
        cache.set("e", b"x" * 50)
        # "b" is LRU data entry, should be evicted
        assert "a" in cache  # sentinel survives
        assert "b" not in cache
        assert "c" in cache  # sentinel survives
        assert "d" in cache
        assert "e" in cache
