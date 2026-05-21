# Cryptorg Telegram Bot

Telegram control bot for Cryptorg trading bots.

The bot provides a compact Telegram interface for starting bots from templates, checking active bots, viewing status and PnL, stopping bots, closing positions, and cancelling deals.

## Features

- Telegram command menu.
- Cryptorg website authentication via environment variables.
- Bybit client integration for market/account data.
- SQLite persistence.
- Optional polling for deal/status notifications.
- Railway deployment configuration.

## Commands

- `/new SYMBOL` — start a bot, for example `/new DOGEUSDT`.
- `/active` — list active bots.
- `/status SYMBOL` — show status and PnL.
- `/stop SYMBOL` — stop a bot.
- `/close SYMBOL` — close a position at market.
- `/cancel SYMBOL` — cancel a deal.
- `/templates` — list available templates.

## Environment

Copy the example file and fill real values locally or in Railway variables:

```bash
cp .env.example .env
```

Required variables:

- `TELEGRAM_TOKEN` — Telegram bot token from BotFather.
- `ALLOWED_USER_ID` — Telegram user ID allowed to use the bot.
- `CRYPTORG_EMAIL` — cryptorg.net login email.
- `CRYPTORG_PASSWORD` — cryptorg.net password.
- `DATABASE_URL` — SQLite URL, default `sqlite:///cryptorg_bot.db`.
- `POLL_INTERVAL` — notification polling interval in seconds.

## Local Run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
nano .env
python main.py
```

## Deployment

The repository includes `railway.toml` for Railway deployment.

Before deploy, set all required environment variables in Railway project settings. Do not commit `.env`.

## Security

- Do not commit real Cryptorg credentials.
- Restrict usage with `ALLOWED_USER_ID`.
- Rotate credentials if they were ever exposed.
