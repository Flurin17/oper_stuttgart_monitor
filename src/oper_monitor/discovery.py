"""Discover ticketed performances across the public Staatsoper season calendar."""
from __future__ import annotations

from datetime import datetime
from html.parser import HTMLParser
import re
from urllib.parse import parse_qs, urljoin, urlparse
from zoneinfo import ZoneInfo

import requests

from .config import EventConfig

PROGRAMME_URL = "https://www.staatsoper-stuttgart.de/spielplan/"


class DiscoveryError(RuntimeError):
    pass


class ProgrammeParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.months: set[str] = set()
        self.events: dict[int, EventConfig] = {}
        self.performance_count = 0
        self.start = ""
        self.title: list[str] = []
        self.in_headline = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = attrs.get("class", "").split()
        if "performance" in classes:
            self.performance_count += 1
            self.start = ""
            self.title = []
        if tag == "h2":
            self.in_headline = True
        if attrs.get("itemprop") == "startDate":
            self.start = attrs.get("content", "")
        href = attrs.get("href", "")
        if re.fullmatch(r"/spielplan/kalender/\d{4}-\d{2}/", href):
            self.months.add(urljoin(PROGRAMME_URL, href))
        parsed = urlparse(href)
        if parsed.hostname != "ticket.staatstheater-stuttgart.de":
            return
        query = parse_qs(parsed.query)
        ids = query.get("event", query.get("eventId", []))
        if len(ids) != 1 or not ids[0].isdigit() or int(ids[0]) <= 0:
            return
        if not self.start:
            raise DiscoveryError("Ticket link has no performance date")
        try:
            start = datetime.fromisoformat(self.start)
        except ValueError as exc:
            raise DiscoveryError("Invalid performance date") from exc
        if start.tzinfo is None:
            start = start.replace(tzinfo=ZoneInfo("Europe/Berlin"))
        if start <= datetime.now(ZoneInfo("Europe/Berlin")):
            return
        event_id = int(ids[0])
        label = " ".join("".join(self.title).split()) or f"Performance {event_id}"
        self.events[event_id] = EventConfig(
            key=f"event-{event_id}",
            url=f"https://ticket.staatstheater-stuttgart.de/eventim.webshop/webticket/seatmap?eventId={event_id}",
            label=f"{label} — {self.start}",
            event_id=event_id,
        )

    def handle_endtag(self, tag):
        if tag == "h2":
            self.in_headline = False

    def handle_data(self, data):
        if self.in_headline:
            self.title.append(data)


def discover_events(timeout: float = 20, title: str | None = None) -> tuple[EventConfig, ...]:
    def read(url):
        response = session.get(url, timeout=(5, timeout))
        response.raise_for_status()
        parser = ProgrammeParser()
        parser.feed(response.text)
        if not parser.performance_count:
            raise DiscoveryError(f"No programme entries found at {url}")
        return parser

    try:
        with requests.Session() as session:
            session.headers["User-Agent"] = "oper-stuttgart-monitor/0.1 (programme discovery)"
            root = read(PROGRAMME_URL)
            if not root.months:
                raise DiscoveryError("Programme month navigation is missing")
            events = dict(root.events)
            for url in sorted(root.months):
                events.update(read(url).events)
    except requests.RequestException as exc:
        raise DiscoveryError(f"Programme discovery failed: {exc}") from exc
    if not events:
        raise DiscoveryError("No future ticketed performances found; retaining previous events")
    selected = tuple(events[key] for key in sorted(events) if title is None or
                     events[key].label.rsplit(" — ", 1)[0].casefold() == title.casefold())
    if not selected:
        raise DiscoveryError(f"No future ticketed performances found for {title!r}")
    return selected
