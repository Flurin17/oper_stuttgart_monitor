from pathlib import Path

from oper_monitor.state import StateStore


def test_rule_state_persists_across_reopen(tmp_path: Path) -> None:
    path = tmp_path / "state.sqlite3"
    first = StateStore(path)
    assert first.get_rule_active("event", "rule") is None
    first.set_rule_active("event", "rule", True)
    first.close()

    second = StateStore(path)
    assert second.get_rule_active("event", "rule") is True
    second.close()


def test_failure_episode_and_recovery() -> None:
    state = StateStore(":memory:")
    assert state.increment_failure("one") == (1, False)
    assert state.increment_failure("two") == (2, False)
    state.mark_failure_alerted()
    assert state.increment_failure("three") == (3, True)
    assert state.failure_was_alerted() is True
    state.reset_failures()
    assert state.failure_was_alerted() is False
    state.close()


def test_metadata_cache_round_trip() -> None:
    state = StateStore(":memory:")
    assert state.get_cached_json("missing") is None
    state.set_cached_json("key", [{"id": 1, "name": "Block"}])
    assert state.get_cached_json("key") == [{"id": 1, "name": "Block"}]
    state.close()
