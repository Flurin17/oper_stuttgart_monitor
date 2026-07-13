from __future__ import annotations

import json
from typing import Any, Protocol

import requests

from .config import EventConfig, RuleConfig
from .models import CandidateRun, RuleResult


class NotificationError(RuntimeError):
    """Raised when a Discord notification cannot be delivered."""


class Notifier(Protocol):
    def send(self, payload: dict[str, Any]) -> None: ...


class DiscordNotifier:
    def __init__(self, webhook_url: str, timeout: float = 15.0, session: requests.Session | None = None):
        if not webhook_url.startswith("https://"):
            raise NotificationError("DISCORD_WEBHOOK_URL must be an HTTPS URL")
        self.webhook_url = webhook_url
        self.timeout = timeout
        self.session = session or requests.Session()

    def send(self, payload: dict[str, Any]) -> None:
        try:
            response = self.session.post(self.webhook_url, json=payload, timeout=(5, self.timeout))
            response.raise_for_status()
        except requests.RequestException as exc:
            raise NotificationError(f"Discord webhook failed: {exc}") from exc


class DryRunNotifier:
    def send(self, payload: dict[str, Any]) -> None:
        print(json.dumps(payload, ensure_ascii=False, indent=2))


def _format_run(run: CandidateRun) -> str:
    category_names = list(dict.fromkeys(category.name for category in run.price_categories))
    seats = ", ".join(seat.seat_number for seat in run.seats)
    return f"**{run.block_name}**, row {run.row}, seats {seats} — {', '.join(category_names)}"


def build_match_payload(event: EventConfig, rule: RuleConfig, result: RuleResult) -> dict[str, Any]:
    lines = [_format_run(run) for run in result.runs[:10]]
    if len(result.runs) > 10:
        lines.append(f"…and {len(result.runs) - 10} more matching runs")
    description = "\n".join(lines)
    if len(description) > 3900:
        description = description[:3897] + "…"
    return {
        "content": f"🎟️ Adjacent tickets available for {event.label}",
        "embeds": [
            {
                "title": event.label,
                "url": event.url,
                "description": description or "A matching seat run is available.",
                "color": 0x2BA23B,
                "fields": [
                    {"name": "Rule", "value": rule.key, "inline": True},
                    {"name": "Matching seats", "value": str(result.matching_seat_count), "inline": True},
                    {"name": "Adjacent runs", "value": str(len(result.runs)), "inline": True},
                ],
            }
        ],
    }


def build_cleared_payload(event: EventConfig, rule: RuleConfig) -> dict[str, Any]:
    return {
        "content": f"Ticket match cleared for {event.label}",
        "embeds": [
            {
                "title": event.label,
                "url": event.url,
                "description": f"Rule `{rule.key}` no longer has a qualifying adjacent-seat run.",
                "color": 0x777777,
            }
        ],
    }


def build_failure_payload(errors: list[str], count: int) -> dict[str, Any]:
    details = "\n".join(f"• {error}" for error in errors)
    return {
        "content": "⚠️ Stuttgart ticket monitor is failing",
        "embeds": [
            {
                "title": "Eventim monitoring failure",
                "description": details[:3900],
                "color": 0xD83B3B,
                "fields": [{"name": "Consecutive failed cycles", "value": str(count), "inline": True}],
            }
        ],
    }


def build_recovery_payload() -> dict[str, Any]:
    return {
        "content": "✅ Stuttgart ticket monitor recovered",
        "embeds": [
            {
                "title": "Eventim monitoring restored",
                "description": "All configured events were checked successfully again.",
                "color": 0x2BA23B,
            }
        ],
    }


def build_test_payload() -> dict[str, Any]:
    return {
        "content": "✅ Stuttgart ticket monitor Discord test",
        "embeds": [{"title": "Webhook configured", "description": "Test notification delivered.", "color": 0x2BA23B}],
    }
