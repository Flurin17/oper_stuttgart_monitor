from oper_monitor.config import EventConfig, RuleConfig
from oper_monitor.discord import build_cleared_payload, build_match_payload
from oper_monitor.models import CandidateRun, PriceCategory, RuleResult, SeatMetadata


def make_run(index: int, long_name: bool = False) -> CandidateRun:
    name = ("Very long block name " * 30) if long_name else f"Block {index}"
    seats = (
        SeatMetadata(index * 2 + 1, index, name, str(index), "1"),
        SeatMetadata(index * 2 + 2, index, name, str(index), "2"),
    )
    category = PriceCategory(1, "Preisgruppe 1")
    return CandidateRun(name, str(index), seats, (category, category))


def test_match_payload_contains_link_and_seats() -> None:
    event = EventConfig("event", "https://example.test/?eventId=1", "Opening night", 1)
    rule = RuleConfig("pair", ("event",), minimum_adjacent=2)
    payload = build_match_payload(event, rule, RuleResult(True, 2, (make_run(1),)))
    assert payload["embeds"][0]["url"] == event.url
    assert "seats 1, 2" in payload["embeds"][0]["description"]


def test_payload_truncates_many_runs_and_long_text() -> None:
    event = EventConfig("event", "https://example.test/?eventId=1", "Opening night", 1)
    rule = RuleConfig("pair", ("event",), minimum_adjacent=2)
    runs = tuple(make_run(index, long_name=True) for index in range(20))
    payload = build_match_payload(event, rule, RuleResult(True, 40, runs))
    description = payload["embeds"][0]["description"]
    assert len(description) <= 3900


def test_cleared_payload_names_rule() -> None:
    event = EventConfig("event", "https://example.test/?eventId=1", "Opening night", 1)
    rule = RuleConfig("pair", ("event",), minimum_adjacent=2)
    assert "pair" in build_cleared_payload(event, rule)["embeds"][0]["description"]
