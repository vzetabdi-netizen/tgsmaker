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

---

## User Commands

| Command | Description |
|---|---|
| `/start` | Welcome screen with current quota |
| `/myplan` | Active plan, daily limit & remaining |
| `/mystats` | Personal conversion statistics |
| `/myhistory` | Last 10 conversions |
| `/upgrade` | Pay via Telegram Stars → activate Pro |
| `/help` | Full help message |

---

## Admin Commands

| Command | Description |
|---|---|
| `/giveplan [id] [plan] [days]` | Grant plan to a specific user |
| `/giveplanall [plan] [days]` | Grant plan to ALL users at once |
| `/removeplan [id]` | Downgrade user to Free immediately |
| `/ban [id]` | Ban a user |
| `/unban [id]` | Unban a user |
| `/stats` | Live bot statistics |
| `/broadcast [msg]` | Broadcast message to all users |
| `/adminhelp` | Admin command reference |

### Owner-Only Commands

| Command | Description |
|---|---|
| `/makeadmin [id]` | Grant admin privileges |
| `/removeadmin [id]` | Revoke admin privileges |

### Admin Examples

```
/giveplan 123456789 pro 30      → Pro for 30 days
/giveplan 123456789 pro         → Pro permanently
/giveplanall pro 7              → Pro for 7 days to ALL users
/removeplan 123456789           → Downgrade to Free
/ban 123456789
/broadcast Hello everyone!
```

---

## Architecture

```
enhanced_bot.py    — Main bot (polling, commands, premium logic)
converter.py       — SVG & PNG → TGS conversion engine
batch_converter.py — Concurrent batch + ZIP extraction
svg_validator.py   — SVGValidator (512×512) + PNGValidator (≥100×100)
database.py        — MongoDB: users, subscriptions, payments, usage
plans.py           — Plan definitions, pricing, formatters
config.py          — Environment variable loader
```

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `BOT_TOKEN` | ✅ | Telegram bot token from @BotFather |
| `DATABASE_URL` | ✅ | MongoDB Atlas connection string |
| `OWNER_ID` | ✅ | Your Telegram user ID (gets auto-Pro + admin) |
| `MONGO_DB_NAME` | ➖ | MongoDB database name (default: `svg_tgs_bot`) |

---

## Deployment (Render)

1. Push code to a private GitHub repo
2. Render → **New → Blueprint** → select repo
3. `render.yaml` is detected automatically — click **Apply**
4. Set `BOT_TOKEN`, `DATABASE_URL`, `OWNER_ID` in Render **Environment**
5. Enable **Telegram Stars** in @BotFather → Payments

See **DEPLOY.md** for full step-by-step instructions.

---

## Payment Flow (Telegram Stars)

1. User runs `/upgrade`
2. Bot sends a Stars invoice (150 ⭐)
3. User pays inside Telegram — no external redirect needed
4. Bot activates Pro for 30 days
5. Plan auto-expires → user returns to Free

---

## File Requirements

| Type | Requirement |
|---|---|
| SVG | Exactly 512×512 px, valid XML, ≤1 MB, ≤1000 elements |
| PNG | At least 100×100 px, valid PNG header |
| Both | Max 10 MB file size |

---

## License

MIT License
