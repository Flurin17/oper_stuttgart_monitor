from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PriceCategory:
    id: int
    name: str
    color: str = ""


@dataclass(frozen=True)
class SeatMapping:
    id: int
    status: int
    price_category_id: int


@dataclass(frozen=True)
class SeatMetadata:
    id: int
    block_id: int
    block_name: str
    row: str
    seat_number: str
    handicap: int = 0


@dataclass(frozen=True)
class EventContext:
    seatmap_id: str
    seatmap_version: int
    mappings: dict[int, SeatMapping]
    price_categories: dict[int, PriceCategory]
    ordered_seats: tuple[SeatMetadata, ...]


@dataclass(frozen=True)
class AvailabilitySnapshot:
    seatmap_id: str
    seatmap_version: int
    timestamp: int
    available_seat_ids: frozenset[int]


@dataclass(frozen=True)
class CandidateRun:
    block_name: str
    row: str
    seats: tuple[SeatMetadata, ...]
    price_categories: tuple[PriceCategory, ...]

    @property
    def length(self) -> int:
        return len(self.seats)


@dataclass(frozen=True)
class RuleResult:
    matched: bool
    matching_seat_count: int
    runs: tuple[CandidateRun, ...] = field(default_factory=tuple)
