from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any, Iterable

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import EventConfig, ProviderConfig
from .models import (
    AvailabilitySnapshot,
    EventContext,
    PriceCategory,
    SeatMapping,
    SeatMetadata,
)


class EventimError(RuntimeError):
    """Raised when Eventim returns an error or an unexpected schema."""


def _integer(value: Any, location: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise EventimError(f"Expected integer at {location}")
    return value


def _string(value: Any, location: str) -> str:
    if not isinstance(value, str):
        raise EventimError(f"Expected string at {location}")
    return value


def _list(value: Any, location: str) -> list[Any]:
    if not isinstance(value, list):
        raise EventimError(f"Expected list at {location}")
    return value


def decode_mapping(payload: dict[str, Any]) -> tuple[dict[int, SeatMapping], dict[int, PriceCategory]]:
    try:
        raw_categories = _list(payload["priceCategories"], "mapping.priceCategories")
        raw_seats = _list(payload["seats"], "mapping.seats")
    except KeyError as exc:
        raise EventimError(f"Missing mapping field: {exc.args[0]}") from exc

    categories: dict[int, PriceCategory] = {}
    for index, item in enumerate(raw_categories):
        if not isinstance(item, dict):
            raise EventimError(f"Expected object at mapping.priceCategories[{index}]")
        category_id = _integer(item.get("id"), f"mapping.priceCategories[{index}].id")
        categories[category_id] = PriceCategory(
            id=category_id,
            name=_string(item.get("name"), f"mapping.priceCategories[{index}].name"),
            color=str(item.get("color", "")),
        )

    seat_id = 0
    category_id = 0
    mappings: dict[int, SeatMapping] = {}
    for index, item in enumerate(raw_seats):
        if not isinstance(item, list) or len(item) < 3:
            raise EventimError(f"Expected at least three values at mapping.seats[{index}]")
        seat_id += _integer(item[0], f"mapping.seats[{index}][0]")
        status = _integer(item[1], f"mapping.seats[{index}][1]")
        category_id += _integer(item[2], f"mapping.seats[{index}][2]")
        if seat_id <= 0 or seat_id in mappings:
            raise EventimError(f"Invalid cumulative seat id at mapping.seats[{index}]")
        mappings[seat_id] = SeatMapping(id=seat_id, status=status, price_category_id=category_id)
    return mappings, categories


def decode_availability(payload: dict[str, Any]) -> AvailabilitySnapshot:
    try:
        raw_seats = _list(payload["seats"], "availability.seats")
        seatmap_id = _string(payload["seatmapId"], "availability.seatmapId")
        version = _integer(payload["seatmapVersion"], "availability.seatmapVersion")
        timestamp = _integer(payload["timestamp"], "availability.timestamp")
    except KeyError as exc:
        raise EventimError(f"Missing availability field: {exc.args[0]}") from exc

    seat_id = 0
    available: set[int] = set()
    for index, item in enumerate(raw_seats):
        if not isinstance(item, list) or len(item) < 2:
            raise EventimError(f"Expected two values at availability.seats[{index}]")
        seat_id += _integer(item[0], f"availability.seats[{index}][0]")
        status = _integer(item[1], f"availability.seats[{index}][1]")
        if seat_id <= 0:
            raise EventimError(f"Invalid cumulative seat id at availability.seats[{index}]")
        if status == 1:
            available.add(seat_id)
    return AvailabilitySnapshot(
        seatmap_id=seatmap_id,
        seatmap_version=version,
        timestamp=timestamp,
        available_seat_ids=frozenset(available),
    )


@dataclass(frozen=True)
class SeatmapDefinition:
    seatmap_id: str
    seatmap_version: int
    block_ids: tuple[int, ...]


def decode_seatmap(payload: dict[str, Any]) -> SeatmapDefinition:
    try:
        seatmap_id = _string(payload["seatmapId"], "seatmap.seatmapId")
        version = _integer(payload["seatmapVersion"], "seatmap.seatmapVersion")
        areas = _list(payload["areas"], "seatmap.areas")
    except KeyError as exc:
        raise EventimError(f"Missing seatmap field: {exc.args[0]}") from exc
    block_ids: list[int] = []
    seen: set[int] = set()
    for area_index, area in enumerate(areas):
        if not isinstance(area, dict):
            raise EventimError(f"Expected object at seatmap.areas[{area_index}]")
        for block_index, block in enumerate(_list(area.get("blocks"), f"seatmap.areas[{area_index}].blocks")):
            if not isinstance(block, dict):
                raise EventimError(f"Expected object at seatmap block {block_index}")
            block_id = _integer(block.get("id"), f"seatmap block {block_index}.id")
            if block_id not in seen:
                seen.add(block_id)
                block_ids.append(block_id)
    return SeatmapDefinition(seatmap_id=seatmap_id, seatmap_version=version, block_ids=tuple(block_ids))


def decode_block_infos(payloads: Iterable[dict[str, Any]]) -> tuple[SeatMetadata, ...]:
    seats: list[SeatMetadata] = []
    seen: set[int] = set()
    for payload_index, payload in enumerate(payloads):
        block_id = _integer(payload.get("id"), f"block[{payload_index}].id")
        block_name = _string(payload.get("name"), f"block[{payload_index}].name")
        for seat_index, item in enumerate(_list(payload.get("seatInfos"), f"block[{payload_index}].seatInfos")):
            if not isinstance(item, dict):
                raise EventimError(f"Expected object at block[{payload_index}].seatInfos[{seat_index}]")
            if bool(item.get("GA", False)):
                continue
            seat_id = _integer(item.get("id"), f"block[{payload_index}].seatInfos[{seat_index}].id")
            if seat_id in seen:
                raise EventimError(f"Duplicate seat id in block metadata: {seat_id}")
            seen.add(seat_id)
            row = item.get("row", "")
            seat_number = item.get("seatNumber", "")
            seats.append(
                SeatMetadata(
                    id=seat_id,
                    block_id=block_id,
                    block_name=block_name,
                    row=str(row),
                    seat_number=str(seat_number),
                    handicap=int(item.get("handicap", 0) or 0),
                )
            )
    return tuple(seats)


class EventimClient:
    def __init__(self, provider: ProviderConfig, timeout: float, session: requests.Session | None = None):
        self.provider = provider
        self.timeout = timeout
        self.session = session or requests.Session()
        retry = Retry(
            total=4,
            connect=4,
            read=4,
            status=4,
            allowed_methods=frozenset({"GET"}),
            status_forcelist=(429, 500, 502, 503, 504),
            backoff_factor=0.5,
            backoff_jitter=0.5,
            respect_retry_after_header=True,
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=8, pool_maxsize=8)
        self.session.mount("https://", adapter)
        self.session.headers.update(
            {
                "Accept": "application/json",
                "X-Version": provider.api_version,
                "User-Agent": "oper-stuttgart-monitor/0.1 (+requests-only availability monitor)",
            }
        )

    def _identifier(self, event_id: int) -> str:
        return f"{self.provider.connector_type}-{self.provider.connector_id}-{event_id}"

    def _params(self) -> dict[str, str | int]:
        return {
            "a_kassierer": self.provider.cashier,
            "a_servleturl": self.provider.servlet_url,
            "a_venue": self.provider.venue_id,
            "a_origin": self.provider.origin,
            "a_username": self.provider.cashier,
            "a_client": self.provider.client_id,
        }

    def _get_json(self, path: str, extra_params: dict[str, str] | None = None) -> dict[str, Any]:
        params = self._params()
        if extra_params:
            params.update(extra_params)
        url = f"{self.provider.api_base_url.rstrip('/')}/{path.lstrip('/')}"
        try:
            response = self.session.get(url, params=params, timeout=(5, self.timeout))
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, json.JSONDecodeError) as exc:
            raise EventimError(f"Eventim request failed for {path}: {exc}") from exc
        if not isinstance(payload, dict):
            raise EventimError(f"Eventim returned a non-object payload for {path}")
        return payload

    def seatmap(self, event_id: int) -> dict[str, Any]:
        return self._get_json(f"seatmap/{self._identifier(event_id)}", {"generateTiles": "false"})

    def mapping(self, event_id: int) -> dict[str, Any]:
        return self._get_json(f"mapping/{self._identifier(event_id)}")

    def availability(self, event_id: int) -> AvailabilitySnapshot:
        return decode_availability(self._get_json(f"availability/{self._identifier(event_id)}"))

    def block_info(self, event_id: int, block_id: int) -> dict[str, Any]:
        return self._get_json(f"seatmap/{self._identifier(event_id)}/block/{block_id}")

    def load_block_infos(self, event_id: int, block_ids: tuple[int, ...], workers: int = 4) -> list[dict[str, Any]]:
        results: dict[int, dict[str, Any]] = {}
        with ThreadPoolExecutor(max_workers=min(workers, max(1, len(block_ids)))) as executor:
            futures = {executor.submit(self.block_info, event_id, block_id): block_id for block_id in block_ids}
            for future in as_completed(futures):
                block_id = futures[future]
                try:
                    results[block_id] = future.result()
                except Exception as exc:
                    raise EventimError(f"Failed to load block metadata for block {block_id}: {exc}") from exc
        return [results[block_id] for block_id in block_ids]

    def build_context(self, event: EventConfig, block_infos: Iterable[dict[str, Any]] | None = None) -> tuple[EventContext, SeatmapDefinition, list[dict[str, Any]]]:
        definition = decode_seatmap(self.seatmap(event.event_id))
        mappings, categories = decode_mapping(self.mapping(event.event_id))
        loaded_blocks = list(block_infos) if block_infos is not None else self.load_block_infos(event.event_id, definition.block_ids)
        context = EventContext(
            seatmap_id=definition.seatmap_id,
            seatmap_version=definition.seatmap_version,
            mappings=mappings,
            price_categories=categories,
            ordered_seats=decode_block_infos(loaded_blocks),
        )
        return context, definition, loaded_blocks
