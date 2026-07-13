from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from .config import ConfigError, load_config
from .discord import DiscordNotifier, DryRunNotifier, NotificationError, build_test_payload
from .eventim import EventimClient
from .monitor import TicketMonitor
from .state import StateStore


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Monitor Stuttgart Eventim seat availability")
    parser.add_argument("--config", "-c", default="config.yaml", help="Path to YAML configuration")
    parser.add_argument("--once", action="store_true", help="Run one polling cycle and exit")
    parser.add_argument("--dry-run", action="store_true", help="Print notifications instead of sending them")
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--check-config", action="store_true", help="Validate configuration and exit")
    actions.add_argument("--test-discord", action="store_true", help="Send a Discord test notification and exit")
    return parser


def _configure_logging() -> None:
    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    _configure_logging()
    try:
        config = load_config(Path(args.config))
        if args.check_config:
            print(f"Configuration valid: {len(config.events)} event(s), {len(config.rules)} rule(s)")
            return 0

        webhook = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
        if args.test_discord:
            if not webhook:
                raise ConfigError("DISCORD_WEBHOOK_URL is required for --test-discord")
            DiscordNotifier(webhook, timeout=config.request_timeout_seconds).send(build_test_payload())
            print("Discord test notification sent")
            return 0

        if args.dry_run and not args.once:
            raise ConfigError("--dry-run must be used with --once")
        if not args.dry_run and not webhook:
            raise ConfigError("DISCORD_WEBHOOK_URL is required unless --dry-run is used")

        notifier = DryRunNotifier() if args.dry_run else DiscordNotifier(webhook, timeout=config.request_timeout_seconds)
        state = StateStore(":memory:" if args.dry_run else config.state_path)
        client = EventimClient(config.provider, timeout=config.request_timeout_seconds)
        monitor = TicketMonitor(config, client, state, notifier)
        try:
            if args.once:
                summary = monitor.run_once()
                return 0 if summary.successful else 2
            monitor.run_forever()
            return 0
        finally:
            state.close()
    except (ConfigError, NotificationError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
