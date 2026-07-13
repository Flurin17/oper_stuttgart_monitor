from __future__ import annotations

import hashlib
import json
import logging
import random
import signal
import threading
from dataclasses import dataclass
from typing import Any

from .config import AppConfig, EventConfig
from .discord import (
    Notifier,
    build_cleared_payload,
    build_failure_payload,
    build_match_payload,
    build_recovery_payload,
)
from .eventim import EventimClient, EventimError, decode_block_infos, decode_mapping, decode_seatmap
from .models import EventContext
from .rules import evaluate_rule
from .state import StateStore


LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class CycleSummary:
    checked_events: int
    errors: tuple[str, ...]

    @property
    def successful(self) -> bool:
        return not self.errors


class TicketMonitor:
    def __init__(self, config: AppConfig, client: EventimClient, state: StateStore, notifier: Notifier):
        self.config = config
        self.client = client
        self.state = state
        self.notifier = notifier
        self.contexts: dict[str, EventContext] = {}
        self._stop = threading.Event()

    def install_signal_handlers(self) -> None:
        def stop(signum: int, _frame: Any) -> None:
            LOG.info("Received signal %s; stopping after the current request", signum)
            self._stop.set()

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)

    def _cache_key(self, seatmap_id: str, seatmap_version: int) -> str:
        identity = "|".join(
            [
                self.config.provider.api_base_url,
                self.config.provider.connector_type,
                self.config.provider.connector_id,
                self.config.provider.client_id,
                str(self.config.provider.venue_id),
                seatmap_id,
                str(seatmap_version),
            ]
        )
        return "block-metadata:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()

    @staticmethod
    def _cached_blocks_valid(payload: Any, block_ids: tuple[int, ...]) -> bool:
        if not isinstance(payload, list) or len(payload) != len(block_ids):
            return False
        try:
            return tuple(int(item["id"]) for item in payload) == block_ids
        except (KeyError, TypeError, ValueError):
            return False

    def _load_context(self, event: EventConfig) -> EventContext:
        definition = decode_seatmap(self.client.seatmap(event.event_id))
        mappings, categories = decode_mapping(self.client.mapping(event.event_id))
        cache_key = self._cache_key(definition.seatmap_id, definition.seatmap_version)
        block_infos = self.state.get_cached_json(cache_key)
        if not self._cached_blocks_valid(block_infos, definition.block_ids):
            LOG.info("Loading block metadata for seat map %s", definition.seatmap_id)
            block_infos = self.client.load_block_infos(event.event_id, definition.block_ids)
            self.state.set_cached_json(cache_key, block_infos)
        context = EventContext(
            seatmap_id=definition.seatmap_id,
            seatmap_version=definition.seatmap_version,
            mappings=mappings,
            price_categories=categories,
            ordered_seats=decode_block_infos(block_infos),
        )
        self.contexts[event.key] = context
        return context

    def _process_event(self, event: EventConfig) -> None:
        context = self.contexts.get(event.key) or self._load_context(event)
        availability = self.client.availability(event.event_id)
        if (
            availability.seatmap_id != context.seatmap_id
            or availability.seatmap_version != context.seatmap_version
        ):
            LOG.info("Seat map changed for %s; refreshing metadata", event.key)
            context = self._load_context(event)
            availability = self.client.availability(event.event_id)
            if (
                availability.seatmap_id != context.seatmap_id
                or availability.seatmap_version != context.seatmap_version
            ):
                raise EventimError(f"Seat-map version remained inconsistent for {event.key}")

        LOG.info(
            "%s: %d currently available seats",
            event.key,
            len(availability.available_seat_ids),
        )
        for rule in self.config.rules:
            if event.key not in rule.events:
                continue
            result = evaluate_rule(rule, context, availability)
            LOG.info(
                "%s/%s: matched=%s matching_seats=%d adjacent_runs=%d",
                event.key,
                rule.key,
                result.matched,
                result.matching_seat_count,
                len(result.runs),
            )
            previous = self.state.get_rule_active(event.key, rule.key)
            if previous is None:
                if result.matched:
                    self.notifier.send(build_match_payload(event, rule, result))
                self.state.set_rule_active(event.key, rule.key, result.matched)
            elif previous != result.matched:
                payload = build_match_payload(event, rule, result) if result.matched else build_cleared_payload(event, rule)
                self.notifier.send(payload)
                self.state.set_rule_active(event.key, rule.key, result.matched)

    def run_once(self) -> CycleSummary:
        errors: list[str] = []
        checked = 0
        for event in self.config.events:
            try:
                self._process_event(event)
                checked += 1
            except Exception as exc:
                message = f"{event.key}: {exc}"
                LOG.exception("Failed to check %s", event.key)
                errors.append(message)

        if errors:
            count, alerted = self.state.increment_failure("\n".join(errors))
            if count >= self.config.failure_alert_after and not alerted:
                self.notifier.send(build_failure_payload(errors, count))
                self.state.mark_failure_alerted()
        else:
            if self.state.failure_was_alerted():
                self.notifier.send(build_recovery_payload())
            self.state.reset_failures()
        return CycleSummary(checked_events=checked, errors=tuple(errors))

    def run_forever(self) -> None:
        self.install_signal_handlers()
        LOG.info("Starting monitor with a %d-second interval", self.config.poll_interval_seconds)
        while not self._stop.is_set():
            self.run_once()
            jitter = random.uniform(0, min(5.0, self.config.poll_interval_seconds * 0.1))
            self._stop.wait(self.config.poll_interval_seconds + jitter)
