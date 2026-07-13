# Stuttgart Ticket Monitor

[![CI](https://github.com/Flurin17/oper_stuttgart_monitor/actions/workflows/ci.yml/badge.svg)](https://github.com/Flurin17/oper_stuttgart_monitor/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

A requests-only Python monitor for the Staatstheater Stuttgart Eventim seat maps. It calls Eventim's JSON seat-map API directly, evaluates configurable adjacent-seat rules, and sends state-change alerts to Discord.

It does **not** run Chromium, Playwright, Selenium, or scrape the Queue-it-protected webshop HTML during normal monitoring.

## Local setup

```bash
cp config.example.yaml config.yaml
uv sync --frozen
uv run oper-monitor --config config.yaml --check-config
uv run oper-monitor --config config.yaml --once --dry-run
```

The dry run performs live Eventim requests and prints any notification payloads without using Discord or writing persistent state.

To send a webhook test:

```bash
export DISCORD_WEBHOOK_URL='https://discord.com/api/webhooks/...'
uv run oper-monitor --config config.yaml --test-discord
```

Run continuously with:

```bash
export DISCORD_WEBHOOK_URL='https://discord.com/api/webhooks/...'
uv run oper-monitor --config config.yaml
```

## Configuration

`config.example.yaml` contains event `17304` and the initial rule: at least two adjacent seats in standard price groups 1–9. Wheelchair-only group 18 (`Rolli`) is excluded.

Each rule supports:

- `events`: event keys to which the rule applies.
- `minimum_adjacent`: required run length; `1` also supports single-seat alerts.
- `include_price_groups` and `exclude_price_groups`: Eventim numeric price-group IDs.
- `include_blocks` and `exclude_blocks`: case-insensitive shell-style globs, such as `Parkett*`.
- `include_rows` and `exclude_rows`: exact row labels represented as strings.

All configured filters must match each seat in a qualifying run. An unavailable, blocked, or filtered seat breaks adjacency. Empty filter lists mean unrestricted.

The provider section exposes the Stuttgart connector details and Eventim API version for recovery if the shop changes them. The API is used by Eventim's own frontend but is not a documented public contract; unexpected response schemas fail safely and trigger the configured operational alert.

## Alert behavior

- The first matching poll sends one availability alert.
- Unchanged matching state does not repeat, including after a restart.
- A matched-to-unmatched transition sends a cleared alert; a later match alerts again.
- Three consecutive failed cycles send one failure alert by default; the first fully successful cycle sends one recovery alert.
- Discord alerts include the event link, matching-seat total, and up to ten best adjacent runs with block, row, seat numbers, and price groups.

State and cached block metadata are stored in SQLite at `state_path`.

## Debian/Ubuntu VPS with systemd

Install `uv`, then deploy the repository and service account:

```bash
sudo useradd --system --home /opt/oper-monitor --shell /usr/sbin/nologin oper-monitor
sudo mkdir -p /opt/oper-monitor /etc/oper-monitor
sudo chown -R oper-monitor:oper-monitor /opt/oper-monitor
sudo -u oper-monitor git clone https://github.com/Flurin17/oper_stuttgart_monitor.git /opt/oper-monitor
cd /opt/oper-monitor
sudo -u oper-monitor uv sync --frozen --no-dev
sudo cp config.example.yaml /etc/oper-monitor/config.yaml
sudo cp oper-monitor.env.example /etc/oper-monitor/oper-monitor.env
sudo chmod 600 /etc/oper-monitor/oper-monitor.env
sudo cp deploy/oper-monitor.service /etc/systemd/system/oper-monitor.service
```

Edit `/etc/oper-monitor/config.yaml` so `state_path` is `/var/lib/oper-monitor/state.sqlite3`, and place the real webhook in `/etc/oper-monitor/oper-monitor.env`. Then enable the service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now oper-monitor
sudo journalctl -u oper-monitor -f
```

The systemd unit creates `/var/lib/oper-monitor`, runs as an unprivileged user, restarts on failures, and applies filesystem/kernel hardening.

## CLI

```text
oper-monitor --config CONFIG [--once] [--dry-run]
oper-monitor --config CONFIG --check-config
oper-monitor --config CONFIG --test-discord
```

`--dry-run` is intentionally limited to `--once` so a forgotten diagnostic process cannot poll indefinitely.

## Tests

```bash
uv run pytest
```

The GitHub Actions workflow runs the same suite on every push and pull request.

## Security and responsible use

Never commit a Discord webhook: provide it only through `DISCORD_WEBHOOK_URL`. Local configuration, environment files, SQLite state, and virtual environments are ignored by Git. See [SECURITY.md](SECURITY.md) for private vulnerability reporting guidance.

This project is an unofficial monitor and is not affiliated with Staatstheater Stuttgart or Eventim. Poll responsibly and comply with the site's terms and applicable law. The default 60-second interval is intentionally conservative.

## License

Released under the [MIT License](LICENSE).
