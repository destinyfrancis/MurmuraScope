"""Tests for RoundCache in-memory cache."""

from backend.app.services.round_cache import RoundCache


def test_round_cache_get_set():
    cache = RoundCache()
    cache.set_agent("a1", {"id": "a1", "name": "Alice"})
    assert cache.get_agent("a1")["name"] == "Alice"


def test_round_cache_get_missing():
    cache = RoundCache()
    assert cache.get_agent("nonexistent") is None


def test_round_cache_get_trust():
    cache = RoundCache()
    cache.set_trust(("a1", "a2"), 0.7)
    assert cache.get_trust(("a1", "a2")) == 0.7
    assert cache.get_trust(("a1", "a3")) == 0.0  # default


def test_round_cache_collect_writes():
    cache = RoundCache()
    cache.queue_write("INSERT INTO t VALUES (?)", ("v1",))
    cache.queue_write("INSERT INTO t VALUES (?)", ("v2",))
    writes = cache.flush_writes()
    assert len(writes) == 2
    assert cache.flush_writes() == []  # cleared after flush


def test_round_cache_bulk_load_agents():
    cache = RoundCache()
    cache.bulk_load_agents({"a1": {"name": "A"}, "a2": {"name": "B"}})
    assert cache.get_agent("a1")["name"] == "A"
    assert cache.get_agent("a2")["name"] == "B"


def test_round_cache_bulk_load_trusts():
    cache = RoundCache()
    cache.bulk_load_trusts({("a1", "a2"): 0.5, ("a2", "a3"): 0.9})
    assert cache.get_trust(("a1", "a2")) == 0.5
    assert cache.get_trust(("a2", "a3")) == 0.9


def test_round_cache_clear():
    cache = RoundCache()
    cache.set_agent("a1", {"name": "A"})
    cache.set_trust(("a1", "a2"), 0.5)
    cache.queue_write("INSERT INTO t VALUES (?)", ("v1",))
    cache.clear()
    assert cache.get_agent("a1") is None
    assert cache.get_trust(("a1", "a2")) == 0.0
    assert cache.flush_writes() == []
