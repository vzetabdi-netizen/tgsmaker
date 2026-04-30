# SVG / PNG to TGS — Telegram Bot

A production-ready Telegram bot that converts **SVG** and **PNG** files to **TGS** (Telegram animated sticker) format, with a full **Free / Pro** subscription system powered by **Telegram Stars**.

---

## Features

| Feature | Free | Pro |
|---|---|---|
| SVG → TGS (512×512 px) | ✅ | ✅ |
| PNG → TGS (≥100×100 px) | ✅ | ✅ |
| Daily conversions | 5 | Unlimited |
| Batch size | 5 files | 15 files |
| ZIP archive upload | ✅ | ✅ |
| Price | Free | 150 ⭐ Stars / month |

### Admin features
- `/broadcast` — text, photo, video, or document to all users
- `/ban` / `/unban` — user management
- `/giveplan` / `/removeplan` — manually grant or revoke plans
- `/makeadmin` / `/removeadmin` — owner-only privilege management
- `/stats` — live bot statistics (users, conversions, Stars earned)

### User commands
| Command | Description |
|---|---|
| `/start` | Welcome screen with current quota |
| `/myplan` | Active plan, daily limit & remaining |
| `/mystats` | Personal conversion statistics |
| `/myhistory` | Last 10 conversions |
| `/upgrade` | Pay via Telegram Stars and activate Pro |
| `/help` | Full help message |

---

## Architecture

```
enhanced_bot.py   — Main bot (polling, command router, premium logic)
converter.py      — SVG & PNG → TGS conversion engine
batch_converter.py— Concurrent batch conversion + ZIP extraction
svg_validator.py  — SVGValidator (512×512) + PNGValidator (≥100×100)
database.py       — PostgreSQL: users, subscriptions, payments, usage, history
plans.py          — Plan definitions, pricing, helper formatters
config.py         — Environment variable loader
```

---

## Quick Start

### Prerequisites
- Python 3.11+
- PostgreSQL database
- Telegram Bot Token from [@BotFather](https://t.me/BotFather)
- (For Stars payments) Enable payments in BotFather → Payments → Telegram Stars

### Environment Variables

| Variable | Required | Description |
|---|---|---|
| `BOT_TOKEN` | ✅ | Telegram bot token |
| `DATABASE_URL` | ✅ | PostgreSQL connection string |
| `OWNER_ID` | ✅ | Your Telegram user ID (gets auto-Pro + owner admin) |

### Installation

```bash
git clone <your-repo-url>
cd svg-to-tgs-bot
pip install -r deploy-requirements.txt
```

Set your environment variables, then:

```bash
python enhanced_bot.py
```

---

## Deployment

### Render (recommended)

1. Create a new **Web Service** on [Render](https://render.com)
2. Connect your GitHub repository
3. Settings:
   - **Build**: `pip install -r deploy-requirements.txt`
   - **Start**: `python enhanced_bot.py`
4. Add environment variables in the Render dashboard
5. Add a **PostgreSQL** database and link `DATABASE_URL`

A `render.yaml` is included for one-click deploy.

### Heroku

```bash
heroku create
heroku addons:create heroku-postgresql:mini
heroku config:set BOT_TOKEN=... OWNER_ID=...
git push heroku main
```

---

## Payment Flow (Telegram Stars)

1. User runs `/upgrade`
2. Bot sends a Telegram Stars invoice (150 ⭐)
3. User pays inside Telegram — no external redirect
4. Telegram sends `successful_payment` to the bot
5. Bot activates Pro plan for 30 days in the database
6. Plan auto-expires and user returns to Free after 30 days

To test payments use `@BotFather → Payments → Test Mode`.

---

## Admin Command Reference

```
/stats                          — Bot statistics
/broadcast Hello everyone!      — Text broadcast
/ban 123456789                  — Ban a user
/unban 123456789                — Unban a user
/giveplan 123456789 pro 30      — Give Pro for 30 days
/giveplan 123456789 pro         — Give Pro permanently
/removeplan 123456789           — Downgrade to Free
/makeadmin 123456789            — Grant admin (owner only)
/removeadmin 123456789          — Revoke admin (owner only)
/adminhelp                      — Admin command list
```

---

## File Requirements

| Type | Requirement |
|---|---|
| SVG | Exactly 512×512 pixels, valid XML, ≤1 MB, ≤1000 elements |
| PNG | At least 100×100 pixels, valid PNG signature |
| Both | Maximum 10 MB file size |

---

## License

MIT License
