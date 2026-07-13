from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import yaml


class ConfigError(ValueError):
    """Raised when the monitor configuration is invalid."""


@dataclass(frozen=True)
class ProviderConfig:
    api_base_url: str = "https://public-api.eventim.com/seatmap/api/public"
    connector_type: str = "inhouserest"
    connector_id: str = "1780"
    client_id: str = "001"
    cashier: str = "web"
    venue_id: int = 1
    servlet_url: str = "https://ticket.staatstheater-stuttgart.de/eventim.webshop/"
    origin: str = "webshop"
    api_version: str = "6.18.2"


@dataclass(frozen=True)
class EventConfig:
    key: str
    url: str
    label: str
    event_id: int


@dataclass(frozen=True)
class RuleConfig:
    key: str
    events: tuple[str, ...]
    minimum_adjacent: int = 2
    include_price_groups: tuple[int, ...] = ()
    exclude_price_groups: tuple[int, ...] = ()
    include_blocks: tuple[str, ...] = ()
    exclude_blocks: tuple[str, ...] = ()
    include_rows: tuple[str, ...] = ()
    exclude_rows: tuple[str, ...] = ()


@dataclass(frozen=True)
class AppConfig:
    poll_interval_seconds: int
    failure_alert_after: int
    state_path: Path
    request_timeout_seconds: float
    provider: ProviderConfig
    events: tuple[EventConfig, ...]
    rules: tuple[RuleConfig, ...]


_ROOT_KEYS = {
    "poll_interval_seconds",
    "failure_alert_after",
    "state_path",
    "request_timeout_seconds",
    "provider",
    "events",
    "rules",
}
_PROVIDER_KEYS = set(ProviderConfig.__dataclass_fields__)
_EVENT_KEYS = {"key", "url", "label"}
_RULE_KEYS = {
    "key",
    "events",
    "minimum_adjacent",
    "include_price_groups",
    "exclude_price_groups",
    "include_blocks",
    "exclude_blocks",
    "include_rows",
    "exclude_rows",
}


def _mapping(value: Any, location: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigError(f"{location} must be a mapping")
    return value


def _reject_unknown(data: dict[str, Any], allowed: set[str], location: str) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ConfigError(f"Unknown {location} key(s): {', '.join(unknown)}")


def _nonempty_string(value: Any, location: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{location} must be a non-empty string")
    return value.strip()


def _string_tuple(value: Any, location: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(item, (str, int)) for item in value):
        raise ConfigError(f"{location} must be a list of strings")
    return tuple(str(item) for item in value)


def _int_tuple(value: Any, location: str) -> tuple[int, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(item, int) and not isinstance(item, bool) for item in value):
        raise ConfigError(f"{location} must be a list of integers")
    return tuple(value)


def parse_event_id(url: str) -> int:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ConfigError(f"Invalid event URL: {url}")
    values = parse_qs(parsed.query).get("eventId", [])
    if len(values) != 1:
        raise ConfigError(f"Event URL must contain exactly one eventId: {url}")
    try:
        event_id = int(values[0])
    except ValueError as exc:
        raise ConfigError(f"eventId must be an integer: {url}") from exc
    if event_id <= 0:
        raise ConfigError(f"eventId must be positive: {url}")
    return event_id


def load_config(path: str | Path) -> AppConfig:
    config_path = Path(path)
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"Configuration file not found: {config_path}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in {config_path}: {exc}") from exc

    data = _mapping(raw, "configuration")
    _reject_unknown(data, _ROOT_KEYS, "configuration")

    poll_interval = data.get("poll_interval_seconds", 60)
    if not isinstance(poll_interval, int) or isinstance(poll_interval, bool) or poll_interval < 30:
        raise ConfigError("poll_interval_seconds must be an integer of at least 30")

    failure_after = data.get("failure_alert_after", 3)
    if not isinstance(failure_after, int) or isinstance(failure_after, bool) or failure_after < 1:
        raise ConfigError("failure_alert_after must be a positive integer")

    timeout = data.get("request_timeout_seconds", 20.0)
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not 1 <= timeout <= 120:
        raise ConfigError("request_timeout_seconds must be between 1 and 120")

    state_path_raw = data.get("state_path", "./data/oper-monitor.sqlite3")
    state_path = Path(_nonempty_string(state_path_raw, "state_path")).expanduser()

    provider_data = _mapping(data.get("provider", {}), "provider")
    _reject_unknown(provider_data, _PROVIDER_KEYS, "provider")
    try:
        provider = ProviderConfig(**provider_data)
    except TypeError as exc:
        raise ConfigError(f"Invalid provider configuration: {exc}") from exc
    if not provider.api_base_url.startswith("https://"):
        raise ConfigError("provider.api_base_url must use HTTPS")
    if not provider.servlet_url.startswith("https://"):
        raise ConfigError("provider.servlet_url must use HTTPS")
    if provider.venue_id <= 0:
        raise ConfigError("provider.venue_id must be positive")

    event_items = data.get("events")
    if not isinstance(event_items, list) or not event_items:
        raise ConfigError("events must be a non-empty list")
    events: list[EventConfig] = []
    event_keys: set[str] = set()
    for index, item in enumerate(event_items):
        event_data = _mapping(item, f"events[{index}]")
        _reject_unknown(event_data, _EVENT_KEYS, f"events[{index}]")
        key = _nonempty_string(event_data.get("key"), f"events[{index}].key")
        url = _nonempty_string(event_data.get("url"), f"events[{index}].url")
        label = _nonempty_string(event_data.get("label", key), f"events[{index}].label")
        if key in event_keys:
            raise ConfigError(f"Duplicate event key: {key}")
        event_keys.add(key)
        events.append(EventConfig(key=key, url=url, label=label, event_id=parse_event_id(url)))

    rule_items = data.get("rules")
    if not isinstance(rule_items, list) or not rule_items:
        raise ConfigError("rules must be a non-empty list")
    rules: list[RuleConfig] = []
    rule_keys: set[str] = set()
    for index, item in enumerate(rule_items):
        rule_data = _mapping(item, f"rules[{index}]")
        _reject_unknown(rule_data, _RULE_KEYS, f"rules[{index}]")
        key = _nonempty_string(rule_data.get("key"), f"rules[{index}].key")
        if key in rule_keys:
            raise ConfigError(f"Duplicate rule key: {key}")
        rule_keys.add(key)
        selected_events = _string_tuple(rule_data.get("events", list(event_keys)), f"rules[{index}].events")
        if not selected_events:
            raise ConfigError(f"rules[{index}].events cannot be empty")
        unknown_events = sorted(set(selected_events) - event_keys)
        if unknown_events:
            raise ConfigError(f"Rule {key} references unknown event(s): {', '.join(unknown_events)}")
        minimum_adjacent = rule_data.get("minimum_adjacent", 2)
        if not isinstance(minimum_adjacent, int) or isinstance(minimum_adjacent, bool) or minimum_adjacent < 1:
            raise ConfigError(f"rules[{index}].minimum_adjacent must be a positive integer")
        include_price_groups = _int_tuple(rule_data.get("include_price_groups"), f"rules[{index}].include_price_groups")
        exclude_price_groups = _int_tuple(rule_data.get("exclude_price_groups"), f"rules[{index}].exclude_price_groups")
        overlap = set(include_price_groups) & set(exclude_price_groups)
        if overlap:
            raise ConfigError(f"Rule {key} includes and excludes price group(s): {sorted(overlap)}")
        rules.append(
            RuleConfig(
                key=key,
                events=selected_events,
                minimum_adjacent=minimum_adjacent,
                include_price_groups=include_price_groups,
                exclude_price_groups=exclude_price_groups,
                include_blocks=_string_tuple(rule_data.get("include_blocks"), f"rules[{index}].include_blocks"),
                exclude_blocks=_string_tuple(rule_data.get("exclude_blocks"), f"rules[{index}].exclude_blocks"),
                include_rows=_string_tuple(rule_data.get("include_rows"), f"rules[{index}].include_rows"),
                exclude_rows=_string_tuple(rule_data.get("exclude_rows"), f"rules[{index}].exclude_rows"),
            )
        )

    return AppConfig(
        poll_interval_seconds=poll_interval,
        failure_alert_after=failure_after,
        state_path=state_path,
        request_timeout_seconds=float(timeout),
        provider=provider,
        events=tuple(events),
        rules=tuple(rules),
    )
