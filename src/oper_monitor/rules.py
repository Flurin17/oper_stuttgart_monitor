from __future__ import annotations

from fnmatch import fnmatchcase

from .config import RuleConfig
from .models import AvailabilitySnapshot, CandidateRun, EventContext, RuleResult, SeatMetadata


def _matches_globs(value: str, patterns: tuple[str, ...]) -> bool:
    folded = value.casefold()
    return any(fnmatchcase(folded, pattern.casefold()) for pattern in patterns)


def _seat_matches(
    seat: SeatMetadata,
    rule: RuleConfig,
    context: EventContext,
    availability: AvailabilitySnapshot,
) -> bool:
    if seat.id not in availability.available_seat_ids:
        return False
    mapping = context.mappings.get(seat.id)
    if mapping is None or mapping.status != 0 or mapping.price_category_id <= 0:
        return False
    if mapping.price_category_id not in context.price_categories:
        return False
    if rule.include_price_groups and mapping.price_category_id not in rule.include_price_groups:
        return False
    if mapping.price_category_id in rule.exclude_price_groups:
        return False
    if rule.include_blocks and not _matches_globs(seat.block_name, rule.include_blocks):
        return False
    if rule.exclude_blocks and _matches_globs(seat.block_name, rule.exclude_blocks):
        return False
    if rule.include_rows and seat.row not in rule.include_rows:
        return False
    if seat.row in rule.exclude_rows:
        return False
    return True


def evaluate_rule(rule: RuleConfig, context: EventContext, availability: AvailabilitySnapshot) -> RuleResult:
    runs: list[CandidateRun] = []
    current: list[SeatMetadata] = []
    current_group: tuple[int, str] | None = None
    matching_count = 0

    def finish_run() -> None:
        nonlocal current
        if len(current) >= rule.minimum_adjacent:
            categories = tuple(
                context.price_categories[context.mappings[seat.id].price_category_id] for seat in current
            )
            runs.append(
                CandidateRun(
                    block_name=current[0].block_name,
                    row=current[0].row,
                    seats=tuple(current),
                    price_categories=categories,
                )
            )
        current = []

    for seat in context.ordered_seats:
        group = (seat.block_id, seat.row)
        if current_group is not None and group != current_group:
            finish_run()
        current_group = group
        if _seat_matches(seat, rule, context, availability):
            current.append(seat)
            matching_count += 1
        else:
            finish_run()
    finish_run()

    ordered_runs = tuple(
        sorted(runs, key=lambda item: (-item.length, item.block_name.casefold(), item.row, item.seats[0].seat_number))
    )
    return RuleResult(matched=bool(ordered_runs), matching_seat_count=matching_count, runs=ordered_runs)
