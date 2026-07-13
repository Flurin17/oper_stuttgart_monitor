from oper_monitor.config import RuleConfig
from oper_monitor.models import AvailabilitySnapshot, EventContext, PriceCategory, SeatMapping, SeatMetadata
from oper_monitor.rules import evaluate_rule


def context() -> EventContext:
    seats = (
        SeatMetadata(1, 10, "Parkett links", "1", "29"),
        SeatMetadata(2, 10, "Parkett links", "1", "27"),
        SeatMetadata(3, 10, "Parkett links", "1", "25"),
        SeatMetadata(4, 10, "Parkett links", "2", "30"),
        SeatMetadata(5, 11, "Parkett rechts", "2", "2"),
        SeatMetadata(6, 11, "Parkett rechts", "2", "4"),
        SeatMetadata(7, 11, "Parkett rechts", "2", "6"),
    )
    mappings = {
        1: SeatMapping(1, 0, 1),
        2: SeatMapping(2, 0, 1),
        3: SeatMapping(3, 0, 2),
        4: SeatMapping(4, 0, 1),
        5: SeatMapping(5, 0, 18),
        6: SeatMapping(6, 0, 1),
        7: SeatMapping(7, 1, 1),
    }
    categories = {
        1: PriceCategory(1, "Preisgruppe 1"),
        2: PriceCategory(2, "Preisgruppe 2"),
        18: PriceCategory(18, "Rolli"),
    }
    return EventContext("hall", 1, mappings, categories, seats)


def availability(*seat_ids: int) -> AvailabilitySnapshot:
    return AvailabilitySnapshot("hall", 1, 1, frozenset(seat_ids))


def rule(**kwargs) -> RuleConfig:
    defaults = {"key": "pair", "events": ("event",), "minimum_adjacent": 2}
    defaults.update(kwargs)
    return RuleConfig(**defaults)


def test_adjacent_uses_eventim_order_not_numeric_difference() -> None:
    result = evaluate_rule(rule(), context(), availability(1, 2))
    assert result.matched
    assert [seat.seat_number for seat in result.runs[0].seats] == ["29", "27"]


def test_unavailable_seat_breaks_run() -> None:
    result = evaluate_rule(rule(minimum_adjacent=2), context(), availability(1, 3))
    assert not result.matched


def test_row_and_block_boundaries_break_runs() -> None:
    assert not evaluate_rule(rule(), context(), availability(3, 4)).matched
    assert not evaluate_rule(rule(), context(), availability(4, 5)).matched


def test_blocked_seat_breaks_run() -> None:
    assert not evaluate_rule(rule(), context(), availability(6, 7)).matched


def test_mixed_price_groups_can_form_a_run() -> None:
    result = evaluate_rule(rule(include_price_groups=(1, 2)), context(), availability(2, 3))
    assert result.matched
    assert {category.id for category in result.runs[0].price_categories} == {1, 2}


def test_price_block_and_row_filters() -> None:
    filtered = rule(include_price_groups=(1,), include_blocks=("Parkett l*",), include_rows=("1",))
    result = evaluate_rule(filtered, context(), availability(1, 2, 3, 4, 6))
    assert result.matched
    assert result.matching_seat_count == 2


def test_excluded_rolli_cannot_complete_pair() -> None:
    filtered = rule(exclude_price_groups=(18,))
    assert not evaluate_rule(filtered, context(), availability(5, 6)).matched


def test_exclude_filters_break_runs() -> None:
    excluded_block = rule(exclude_blocks=("*links",))
    assert not evaluate_rule(excluded_block, context(), availability(1, 2)).matched
    excluded_row = rule(exclude_rows=("1",))
    assert not evaluate_rule(excluded_row, context(), availability(1, 2)).matched
