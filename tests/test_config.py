from pathlib import Path

import pytest

from oper_monitor.config import ConfigError, load_config, parse_event_id


VALID = """
events:
  - key: first
    url: https://example.test/seatmap?eventId=17308
rules:
  - key: pair
    events: [first]
    minimum_adjacent: 2
    include_price_groups: [1, 2]
"""


def write(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(content, encoding="utf-8")
    return path


def test_loads_valid_config(tmp_path: Path) -> None:
    config = load_config(write(tmp_path, VALID))
    assert config.poll_interval_seconds == 60
    assert config.events[0].event_id == 17308
    assert config.rules[0].include_price_groups == (1, 2)


@pytest.mark.parametrize(
    "url",
    [
        "not-a-url",
        "https://example.test/seatmap",
        "https://example.test/seatmap?eventId=nope",
        "https://example.test/seatmap?eventId=1&eventId=2",
    ],
)
def test_rejects_invalid_event_urls(url: str) -> None:
    with pytest.raises(ConfigError):
        parse_event_id(url)


def test_rejects_unknown_keys(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="Unknown configuration"):
        load_config(write(tmp_path, VALID + "mystery: true\n"))


def test_rejects_unknown_rule_event(tmp_path: Path) -> None:
    content = VALID.replace("events: [first]", "events: [missing]")
    with pytest.raises(ConfigError, match="unknown event"):
        load_config(write(tmp_path, content))


def test_rejects_overlapping_price_groups(tmp_path: Path) -> None:
    content = VALID.replace("include_price_groups: [1, 2]", "include_price_groups: [1, 2]\n    exclude_price_groups: [2]")
    with pytest.raises(ConfigError, match="includes and excludes"):
        load_config(write(tmp_path, content))


def test_rejects_too_fast_polling(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="at least 30"):
        load_config(write(tmp_path, "poll_interval_seconds: 10\n" + VALID))
