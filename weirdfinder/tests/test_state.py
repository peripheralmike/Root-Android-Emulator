import time

from conftest import *  # noqa: F401,F403 - puts src on sys.path

from weirdfinder.state import State


def test_first_seen_is_stable_across_runs(tmp_path):
    state = State(tmp_path / "s.db")
    assert state.is_new("steam:1")
    first = state.record("steam:1", "A Game", 80.0)

    time.sleep(0.01)
    assert not state.is_new("steam:1")
    again = state.record("steam:1", "A Game (renamed)", 91.0)
    assert again == first  # first_seen never moves


def test_state_file_and_parent_directory_are_created(tmp_path):
    path = tmp_path / "nested" / "deeper" / "state.db"
    State(path)
    assert path.exists()


def test_cache_round_trips_structured_values(tmp_path):
    state = State(tmp_path / "s.db")
    state.put("k", {"tags": ["Horror"], "n": 3})
    assert state.get("k") == {"tags": ["Horror"], "n": 3}


def test_cache_miss_returns_none(tmp_path):
    assert State(tmp_path / "s.db").get("nope") is None


def test_cache_entries_expire(tmp_path):
    state = State(tmp_path / "s.db", cache_ttl_hours=0)
    state.put("k", "value")
    assert state.get("k") is None


def test_expired_entries_are_purged(tmp_path):
    state = State(tmp_path / "s.db", cache_ttl_hours=0)
    state.put("a", 1)
    state.put("b", 2)
    assert state.purge_expired() == 2
    assert state.purge_expired() == 0


def test_unserialisable_values_are_skipped_not_fatal(tmp_path):
    state = State(tmp_path / "s.db")
    state.put("k", object())  # must not raise
    assert state.get("k") is None


def test_reopening_the_database_keeps_history(tmp_path):
    path = tmp_path / "s.db"
    first = State(path).record("itch:9", "TAPE NINE", 84.0)
    assert State(path).first_seen("itch:9") == first
