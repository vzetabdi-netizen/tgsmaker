# SVG to TGS — Telegram Bot

A production-ready Telegram bot that converts **SVG** files to **TGS** (Telegram animated sticker) format, with a full **Free / Pro** subscription system powered by **Telegram Stars**.

---

## Plans & Limits

| Feature | Free 🆓 | Pro ⭐ |
|---|---|---|
| SVG → TGS (512×512 px) | ✅ | ✅ |
| Daily conversions | 5 | Unlimited |
| Batch size (files at once) | 5 files | 50 files |
| ZIP archive upload | ✅ | ✅ |
| Conversion history | ✅ | ✅ |
| Price | Free | 150 ⭐ Stars/month (adjustable) |

> **Note:** PNG conversion is **not supported**. Only SVG files (exactly 512×512 px) are accepted.

---

## User Commands

| Command | Description |
|---|---|
| `/start` | Welcome screen — shows your plan and remaining quota |
| `/myplan` | Active plan, daily limit, remaining conversions, expiry date |
| `/mystats` | Personal stats: total, successful, failed conversions |
| `/myhistory` | Last 10 conversions with file name, size, and date |
| `/upgrade` | Pay via Telegram Stars and activate Pro instantly |
| `/help` | Full help message with file requirements and plan info |

---

## Admin Commands

| Command | Description |
|---|---|
| `/stats` | Live bot stats — users, conversions, Stars earned, current Pro price |
| `/broadcast [msg]` | Send text, photo, video, or document to all users |
| `/ban [user_id]` | Ban a user |
| `/unban [user_id]` | Unban a user |
| `/premium [id] [plan] [days]` | Grant a plan to a specific user (days optional = permanent) |
| `/rpremium [user_id]` | Downgrade a specific user to Free |
| `/premiumall [plan] [days]` | Grant a plan to all Free users (paid and `/premium` users are protected) |
| `/rpremiumall` | Revert only the plans granted via `/premiumall` (requires `/rpremiumall confirm`) |
| `/topusers` | Top 10 users by total successful conversions |
| `/setprice [stars]` | Change the Pro plan price (e.g. `/setprice 100`) |
| `/adminhelp` | Admin command reference |

### Owner-only Commands

| Command | Description |
|---|---|
| `/makeadmin [user_id]` | Grant admin privileges |
| `/removeadmin [user_id]` | Revoke admin privileges |

> **Paid user protection:** `/premiumall` and `/rpremiumall` never touch users who have paid via Telegram Stars or who were given Pro individually via `/premium`. Their plans are always preserved.

---

## Admin Command Examples

```
/stats
/broadcast Hello everyone! New feature released.
/ban 123456789
/unban 123456789
/premium 123456789 pro 30         — Pro for 30 days
/premium 123456789 pro            — Pro permanently
/rpremium 123456789
/premiumall pro 7                 — Pro for 7 days to all Free users
/rpremiumall                      — Shows confirmation prompt
/rpremiumall confirm              — Reverts only /premiumall grants
/setprice 100                     — Set Pro to 100 Stars/month
/makeadmin 123456789              — Owner only
/removeadmin 123456789            — Owner only
```

---

## Payment Flow (Telegram Stars)

1. User runs `/upgrade`
2. Bot sends a Telegram Stars invoice
3. User pays inside Telegram — no external redirect needed
4. Telegram sends `successful_payment` to the bot
5. Bot activates Pro plan for 30 days and notifies the user
6. Plan auto-expires; user returns to Free automatically

Paid users are **permanently protected** — `/premiumall` and `/rpremiumall` will never override their subscription.

To test payments: `@BotFather → Payments → Test Mode`

---

## File Requirements

| Type | Requirement |
|---|---|
| SVG | Exactly **512×512** pixels, valid XML, ≤ 1 MB, ≤ 1000 elements |
| ZIP | Must contain `.svg` files inside; non-SVG files are ignored |
| Both | Maximum **10 MB** per upload |

---

## Architecture

```
enhanced_bot.py    — Main bot: polling loop, command router, plan logic, payments
converter.py       — SVG → TGS conversion engine (in-process lottie, subprocess fallback)
batch_converter.py — Concurrent batch conversion + ZIP extraction
svg_validator.py   — SVG validation (512×512, ≤1MB, ≤1000 elements)
database.py        — MongoDB: users, subscriptions, payments, usage, history, pricing
plans.py           — Plan definitions (Free/Pro), pricing helpers
config.py          — Environment variable loader (BOT_TOKEN, DATABASE_URL, OWNER_ID)
```

**Database:** MongoDB (via `pymongo`) — hosted on MongoDB Atlas or any MongoDB provider.

---

## Quick Start

### Prerequisites

- Python 3.11+
- MongoDB database (MongoDB Atlas free tier works)
- Telegram Bot Token from [@BotFather](https://t.me/BotFather)
- Telegram Stars payments enabled in BotFather

### Environment Variables

| Variable | Required | Description |
|---|---|---|
| `BOT_TOKEN` | ✅ | Telegram bot token from @BotFather |
| `DATABASE_URL` | ✅ | MongoDB connection string (e.g. `mongodb+srv://...`) |
| `OWNER_ID` | ✅ | Your Telegram user ID — gets auto Pro + owner admin rights |
| `MONGO_DB_NAME` | ❌ | MongoDB database name (default: `svg_tgs_bot`) |

### Installation

```bash
git clone <your-repo-url>
cd svg-to-tgs-bot
pip install -r requirements.txt
```

Set your environment variables, then:

```bash
python enhanced_bot.py
```

---

## Deployment on Render

A `render.yaml` is included for one-click deploy.

1. Go to [render.com](https://render.com) → **New → Blueprint**
2. Connect your GitHub repository
3. Render detects `render.yaml` and creates the Web Service
4. Add your secret environment variables in the Render dashboard:

| Key | Value |
|---|---|
| `BOT_TOKEN` | Your bot token |
| `DATABASE_URL` | Your MongoDB Atlas connection string |
| `OWNER_ID` | Your Telegram user ID |

5. Click **Save Changes** — Render redeploys automatically

**Build command:** `pip install --upgrade pip && pip install -r requirements.txt`  
**Start command:** `python enhanced_bot.py`

> The bot runs as a **Web Service** on Render (includes a built-in `/health` endpoint to keep it alive). The Starter plan ($7/mo) is required — the free tier does not support always-on services.

---

## Updating the Bot

Every `git push` triggers an automatic redeploy on Render:

```bash
git add .
git commit -m "your change"
git push
```

---

## Troubleshooting

**Bot not responding**
- Check Render Logs for errors
- Confirm `BOT_TOKEN` is correct in Environment settings

**Database connection errors**
- Confirm `DATABASE_URL` is a valid MongoDB URI
- Make sure your MongoDB Atlas cluster allows connections from Render (set IP to `0.0.0.0/0` in Atlas Network Access)

**lottie / conversion errors**
- `lottie[all]` in `requirements.txt` installs both the Python library and `lottie_convert.py`
- The bot tries in-process conversion first (fast), then falls back to subprocess automatically

**Payment invoice not sending**
- Confirm Telegram Stars is enabled in BotFather → Payments
- Check Render Logs for `sendInvoice failed`

---

## License

MIT License
