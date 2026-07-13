# Security Policy

## Reporting a vulnerability

Please do not open a public issue for a suspected vulnerability or an exposed secret. Use GitHub's private vulnerability reporting feature on the repository's **Security** tab instead.

Include the affected version or commit, reproduction steps, impact, and any suggested mitigation. You should receive an acknowledgement within seven days.

## Secrets

Discord webhooks must be supplied through the `DISCORD_WEBHOOK_URL` environment variable. If a webhook is ever exposed, rotate it immediately in Discord; removing it from a later Git commit does not invalidate the leaked credential.
