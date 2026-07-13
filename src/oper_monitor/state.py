from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class StateStore:
    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=NORMAL")
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS rule_state (
                event_key TEXT NOT NULL,
                rule_key TEXT NOT NULL,
                active INTEGER NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (event_key, rule_key)
            );
            CREATE TABLE IF NOT EXISTS service_state (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                consecutive_failures INTEGER NOT NULL,
                failure_alerted INTEGER NOT NULL,
                last_error TEXT
            );
            CREATE TABLE IF NOT EXISTS metadata_cache (
                cache_key TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            INSERT OR IGNORE INTO service_state(singleton, consecutive_failures, failure_alerted, last_error)
            VALUES (1, 0, 0, NULL);
            """
        )
        self.connection.commit()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def close(self) -> None:
        self.connection.close()

    def get_rule_active(self, event_key: str, rule_key: str) -> bool | None:
        row = self.connection.execute(
            "SELECT active FROM rule_state WHERE event_key = ? AND rule_key = ?",
            (event_key, rule_key),
        ).fetchone()
        return None if row is None else bool(row[0])

    def set_rule_active(self, event_key: str, rule_key: str, active: bool) -> None:
        self.connection.execute(
            """
            INSERT INTO rule_state(event_key, rule_key, active, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(event_key, rule_key) DO UPDATE SET
                active = excluded.active,
                updated_at = excluded.updated_at
            """,
            (event_key, rule_key, int(active), self._now()),
        )
        self.connection.commit()

    def increment_failure(self, error: str) -> tuple[int, bool]:
        self.connection.execute(
            """
            UPDATE service_state
            SET consecutive_failures = consecutive_failures + 1, last_error = ?
            WHERE singleton = 1
            """,
            (error[:4000],),
        )
        self.connection.commit()
        row = self.connection.execute(
            "SELECT consecutive_failures, failure_alerted FROM service_state WHERE singleton = 1"
        ).fetchone()
        assert row is not None
        return int(row[0]), bool(row[1])

    def mark_failure_alerted(self) -> None:
        self.connection.execute("UPDATE service_state SET failure_alerted = 1 WHERE singleton = 1")
        self.connection.commit()

    def failure_was_alerted(self) -> bool:
        row = self.connection.execute(
            "SELECT failure_alerted FROM service_state WHERE singleton = 1"
        ).fetchone()
        return bool(row and row[0])

    def reset_failures(self) -> None:
        self.connection.execute(
            """
            UPDATE service_state
            SET consecutive_failures = 0, failure_alerted = 0, last_error = NULL
            WHERE singleton = 1
            """
        )
        self.connection.commit()

    def get_cached_json(self, cache_key: str) -> Any | None:
        row = self.connection.execute(
            "SELECT payload FROM metadata_cache WHERE cache_key = ?", (cache_key,)
        ).fetchone()
        if row is None:
            return None
        try:
            return json.loads(row[0])
        except json.JSONDecodeError:
            self.connection.execute("DELETE FROM metadata_cache WHERE cache_key = ?", (cache_key,))
            self.connection.commit()
            return None

    def set_cached_json(self, cache_key: str, payload: Any) -> None:
        serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        self.connection.execute(
            """
            INSERT INTO metadata_cache(cache_key, payload, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(cache_key) DO UPDATE SET
                payload = excluded.payload,
                updated_at = excluded.updated_at
            """,
            (cache_key, serialized, self._now()),
        )
        self.connection.commit()
