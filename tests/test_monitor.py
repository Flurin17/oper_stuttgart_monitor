from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from oper_monitor.config import AppConfig, EventConfig, ProviderConfig, RuleConfig
from oper_monitor.models import AvailabilitySnapshot, EventContext, PriceCategory, SeatMapping, SeatMetadata
from oper_monitor.monitor import TicketMonitor
from oper_monitor.state import StateStore


class CollectNotifier:
    def __init__(self) -> None:
        self.payloads: list[dict[str, Any]] = []

    def send(self, payload: dict[str, Any]) -> None:
        self.payloads.append(payload)


class FakeClient:
    def __init__(self, snapshots: list[AvailabilitySnapshot | Exception]):
        self.snapshots = snapshots

    def availability(self, _event_id: int) -> AvailabilitySnapshot:
        item = self.snapshots.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def config(state_path: Path | str = ":memory:", failure_after: int = 3) -> AppConfig:
    return AppConfig(
        poll_interval_seconds=60,
        failure_alert_after=failure_after,
        state_path=Path(state_path),
        request_timeout_seconds=10,
        provider=ProviderConfig(),
        events=(EventConfig("event", "https://example.test/?eventId=1", "Event", 1),),
        rules=(RuleConfig("pair", ("event",), minimum_adjacent=2, include_price_groups=(1,)),),
    )


def context() -> EventContext:
    return EventContext(
        seatmap_id="hall",
        seatmap_version=1,
        mappings={1: SeatMapping(1, 0, 1), 2: SeatMapping(2, 0, 1)},
        price_categories={1: PriceCategory(1, "Preisgruppe 1")},
        ordered_seats=(
            SeatMetadata(1, 1, "Block", "1", "1"),
            SeatMetadata(2, 1, "Block", "1", "2"),
        ),
    )


def snapshot(*available: int) -> AvailabilitySnapshot:
    return AvailabilitySnapshot("hall", 1, 1, frozenset(available))


def make_monitor(snapshots, state=None, failure_after=3):
    notifier = CollectNotifier()
    store = state or StateStore(":memory:")
    monitor = TicketMonitor(config(failure_after=failure_after), FakeClient(list(snapshots)), store, notifier)
    monitor.contexts["event"] = context()
    return monitor, store, notifier


def test_alert_dedup_clear_and_reappear() -> None:
    monitor, state, notifier = make_monitor([snapshot(1, 2), snapshot(1, 2), snapshot(1), snapshot(1, 2)])
    for _ in range(4):
        assert monitor.run_once().successful
    assert [payload["content"] for payload in notifier.payloads] == [
        "🎟️ Adjacent tickets available for Event",
        "Ticket match cleared for Event",
        "🎟️ Adjacent tickets available for Event",
    ]
    state.close()


def test_active_state_survives_restart(tmp_path: Path) -> None:
    path = tmp_path / "state.sqlite3"
    first_state = StateStore(path)
    first, _, first_notifier = make_monitor([snapshot(1, 2)], first_state)
    first.run_once()
    assert len(first_notifier.payloads) == 1
    first_state.close()

    second_state = StateStore(path)
    second, _, second_notifier = make_monitor([snapshot(1, 2)], second_state)
    second.run_once()
    assert second_notifier.payloads == []
    second_state.close()


def test_failure_threshold_and_recovery() -> None:
    monitor, state, notifier = make_monitor(
        [RuntimeError("down"), RuntimeError("down"), RuntimeError("down"), snapshot()],
        failure_after=3,
    )
    assert not monitor.run_once().successful
    assert not monitor.run_once().successful
    assert not monitor.run_once().successful
    assert len(notifier.payloads) == 1
    assert "failing" in notifier.payloads[0]["content"]
    assert monitor.run_once().successful
    assert notifier.payloads[-1]["content"].endswith("recovered")
    state.close()
