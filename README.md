# BargainBites

**BargainBites** is a self-hosted Telegram bot that watches your [Too Good To Go](https://www.toogoodtogo.com/) favourites and pings you the moment a surprise bag comes back in stock — so you never miss a deal and help fight food waste. 🍽️

It supports multiple users, private and group chats, per-user notification preferences, and a store blacklist, all backed by a local SQLite database.

> **Current version:** 2.0.0 — built for `tgtg` 0.19.0 with the email **PIN** login flow.

---

## Features

- **PIN-based login** — log in with just your TGTG email; you confirm with a short PIN sent to your inbox. No password ever stored.
- **Smart notifications** — get alerted on `new stock`, `sold out`, `stock increased`, and `stock reduced`, toggled individually per chat.
- **Background polling** — checks your favourites continuously with randomised timing and a quieter "night mode" to stay under TGTG's bot-detection radar.
- **Multi-user & group chats** — many people can use the same bot at once, in private DMs or shared groups.
- **Private access tokens** — admins can hand out one-time invite tokens to authorise specific users.
- **Interactive store blacklist** — mute stores you don't care about, straight from the notification message or via `/blacklist`.
- **Secure, local storage** — credentials and preferences live in a local SQLite database; nothing leaves your server.
- **Hardened container** — ships as a rootless, distroless Docker image.

---

## Quick Start (Docker Compose — recommended)

### 1. Prerequisites

- [Docker](https://docs.docker.com/get-docker/) with Compose v2
- A **Telegram bot token** — create one by messaging [@BotFather](https://t.me/BotFather) and copying the token it gives you
- Your **Telegram numeric user ID** — get it from [@userinfobot](https://t.me/userinfobot) (needed for admin features)
- A **Too Good To Go account** (the regular consumer app account)

### 2. Get the code

```bash
git clone https://github.com/BattermanZ/BargainBites.git
cd BargainBites
```

### 3. Configure

```bash
cp .env.example .env
```

Edit `.env`:

```ini
# Telegram Bot Configuration
TELEGRAM_BOT_TOKEN=123456:ABC-your-token-from-botfather
TELEGRAM_ADMIN_IDS=123456789            # comma-separated, e.g. 123456789,987654321

# Logging (optional, defaults to INFO)
LOG_LEVEL=INFO                          # DEBUG | INFO | WARNING | ERROR
```

The compose file mounts two host folders for persistent state and sets the
timezone (used to show pickup times in your local time and to drive night mode):

```yaml
# docker-compose.yml (excerpt)
environment:
  - TZ=Europe/Amsterdam                 # change to your timezone
volumes:
  - ./db:/app/database                  # SQLite database
  - ./logs:/app/logs                    # rotating log files
```

> **Note:** the published image in `docker-compose.yml` points at a private
> registry (`registry.batterlan.cc`). To run your own build, either replace the
> `image:` line with `build: .`, or build and tag the image yourself (see
> [Building the image](#building-the-image)).

### 4. Run

```bash
docker compose up -d
docker compose logs -f          # watch it start; Ctrl+C to stop watching
```

### 5. Log in from Telegram

Open a chat with your bot and:

```
/login your-email@example.com
```

You'll receive a **PIN code by email** from Too Good To Go. Send it back to the bot:

```
/pin 12345
```

That's it — you're logged in and will start receiving alerts. 🎉

---

## Running without Docker

Requires **Python 3.12+**.

```bash
git clone https://github.com/BattermanZ/BargainBites.git
cd BargainBites

python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env              # then edit it (see Configure, above)

# Export the variables and run (the app reads them from the environment):
set -a; source .env; set +a
python3 app/main.py
```

The app creates `database/` and `logs/` folders in the project root on first run.

---

## Using the Bot

### Logging in

| Step | Command | What happens |
|------|---------|--------------|
| 1 | `/login email@example.com` | Requests a login; TGTG emails you a PIN |
| 2 | `/pin 12345` | Confirms the PIN and finishes login |
| — | `/relogin email@example.com` | Force a fresh login (e.g. after credentials expire) |

No password is needed or stored — login works entirely through the emailed PIN.

### Everyday commands

| Command | Description |
|---------|-------------|
| `/start` | Start the bot (or redeem an invite token: `/start <token>`) |
| `/help` | Show usage instructions |
| `/login <email>` | Log in to Too Good To Go |
| `/pin <code>` | Complete login with the emailed PIN |
| `/relogin <email>` | Re-authenticate from scratch |
| `/info` | Show favourites that currently have bags available |
| `/settings` | Toggle which events notify you (inline buttons) |
| `/blacklist` | View and manage muted stores |
| `/remove_blacklist <store_id>` | Unmute a store by ID |

### Admin commands

Available only to user IDs listed in `TELEGRAM_ADMIN_IDS`:

| Command | Description |
|---------|-------------|
| `/generate_token` | Create a one-time invite token for a new private user |
| `/list_tokens` | List all tokens and whether they've been used |

---

## How it Works

### Notification settings

`/settings` opens an inline keyboard where you toggle each alert type
independently: **sold out**, **new stock**, **stock reduced**, **stock
increased**, plus shortcuts to enable or disable everything at once.
🟢 = enabled, 🔴 = disabled.

### Private access tokens

By default only admins (and chats that have logged in) can use the bot. To grant
a specific person access in a private chat:

1. An admin runs `/generate_token`.
2. The admin shares the token with the new user.
3. The user sends `/start <token>` to the bot to unlock access.

### Background polling & anti-detection

To avoid tripping Too Good To Go's bot detection, polling is deliberately
irregular:

- **Day mode** (07:00–00:59 local): a fresh bag check every ~5–8 minutes.
- **Night mode** (01:00–06:59 local): checks slow to every ~45–90 minutes.
- **Per-user spacing**: a random 20–40 s delay between users each cycle.
- **Jitter & shuffling**: small random noise on every interval and a shuffled
  user order each pass.
- **CAPTCHA handling**: if a user hits a CAPTCHA/Datadome block, that user is put
  on a 30–60 minute cooldown instead of stalling everyone.
- **Idle skipping**: users with no active notification settings, or with no
  favourites, are probed less often.

Local time (and therefore night-mode hours and displayed pickup times) is driven
by the `TZ` environment variable.

---

## Configuration Reference

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `TELEGRAM_BOT_TOKEN` | ✅ | — | Bot token from @BotFather |
| `TELEGRAM_ADMIN_IDS` | — | _(none)_ | Comma-separated numeric Telegram user IDs with admin rights |
| `LOG_LEVEL` | — | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `TZ` | — | container default | Timezone for pickup times and night mode (e.g. `Europe/Amsterdam`) |

---

## Building the Image

To build and run your own image instead of the prebuilt one:

```bash
docker build -t bargainbites:local .
```

Then point `docker-compose.yml` at it:

```yaml
services:
  bargainbites:
    image: bargainbites:local
    # ...rest unchanged
```

The image is a two-stage build: dependencies are compiled on Debian 13 (trixie)
and copied into a rootless [distroless](https://github.com/GoogleContainerTools/distroless)
runtime that runs as UID `65532`.

---

## Development

Install dev dependencies and run the test suite:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements-dev.txt
PYTHONPATH=app python -m pytest
```

Tests live in `tests/` and cover the message formatting, login/PIN flow,
polling-cadence logic, cookie persistence, and database helpers.

---

## Project Layout

```
.
├── app/
│   ├── main.py            # Entry point: logging, signals, event loop
│   ├── Telegram.py        # Telegram bot handlers and inline keyboards
│   ├── TooGoodToGo.py     # TGTG API integration, polling loop, formatting
│   └── database.py        # SQLite persistence
├── tests/                 # pytest suite
├── docs/                  # design/implementation notes
├── Dockerfile             # Distroless, rootless multi-stage build
├── docker-compose.yml     # Recommended deployment
├── requirements.txt       # Runtime dependencies
├── requirements-dev.txt   # + test tooling
├── .env.example           # Configuration template
├── database/              # SQLite data (created at runtime; gitignored)
└── logs/                  # Rotating log files (created at runtime; gitignored)
```

---

## Troubleshooting

- **No alerts arriving** — make sure you completed both `/login` *and* `/pin`,
  and that you've enabled at least one event in `/settings`.
- **Prices showing correctly?** — fixed in 2.0.0; bag prices are read from the
  TGTG `item_price` field.
- **Login keeps failing** — try `/relogin <email>`; TGTG sessions expire and the
  PIN is single-use and short-lived.
- **CAPTCHA / rate limits** — the bot self-throttles; give an affected account
  30–60 minutes to clear its cooldown.
- **Check the logs** — `docker compose logs -f`, or set `LOG_LEVEL=DEBUG` for
  more detail.

---

## A Note on AI Assistance

Parts of this project were built and refactored with AI tools. The code is
covered by an automated test suite, but please review it and test in a safe
environment before relying on it in production. Your security and privacy matter
— proceed thoughtfully. 🛡️

---

## Acknowledgements

- **[tgtg-python](https://github.com/ahivert/tgtg-python)** — the Too Good To Go API client.
- **[TooGoodToGo-TelegramBot](https://github.com/TorbenStriegel/TooGoodToGo-TelegramBot)** — the original project this was forked from and adapted.
- **[Too Good To Go](https://www.toogoodtogo.com/)** — for helping us all waste less food. 🌍

---

## License

Licensed under the **GNU GPL v3**. See [`LICENSE`](LICENSE) for details.
