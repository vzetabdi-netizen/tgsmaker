# Deployment Guide — GitHub → Render

Follow these steps **in order** and your bot will be live.

---

## Step 1 — Prepare your files

Make sure your project folder contains these files:

```
enhanced_bot.py
converter.py
batch_converter.py
svg_validator.py
database.py
plans.py
config.py
requirements.txt
runtime.txt
render.yaml
.gitignore
README.md
```

> **Do NOT include** `.env`, `secrets.json`, or any file with your bot token.

---

## Step 2 — Create a GitHub repository

1. Go to [github.com](https://github.com) → **New repository**
2. Name it (e.g. `svg-tgs-bot`)
3. Set it to **Private** (your bot token will be in Render, not GitHub, but private is safer)
4. Do NOT initialize with README (you already have one)
5. Click **Create repository**

---

## Step 3 — Push your code to GitHub

Open a terminal in your project folder and run:

```bash
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/svg-tgs-bot.git
git push -u origin main
```

Replace `YOUR_USERNAME` with your GitHub username.

---

## Step 4 — Create a Render account

Go to [render.com](https://render.com) and sign up (free).  
Connect your GitHub account when prompted.

---

## Step 5 — Deploy using render.yaml (Blueprint)

1. In Render dashboard click **New → Blueprint**
2. Select your `svg-tgs-bot` GitHub repository
3. Render will detect `render.yaml` automatically
4. It will show you **two resources** to create:
   - `svg-tgs-bot` (Worker)
   - `svg-tgs-db` (PostgreSQL)
5. Click **Apply**

---

## Step 6 — Set your secret environment variables

After the Blueprint is created:

1. Go to your **svg-tgs-bot** Worker in the Render dashboard
2. Click **Environment** in the left sidebar
3. Add these two variables:

| Key | Value |
|---|---|
| `BOT_TOKEN` | Your bot token from @BotFather |
| `OWNER_ID` | Your Telegram user ID (get it from @userinfobot) |

> `DATABASE_URL` is set automatically by Render from the linked database.

4. Click **Save Changes** — Render will redeploy automatically.

---

## Step 7 — Verify the bot is running

1. Go to your Worker → **Logs** tab
2. You should see:

```
Bot online: @yourbotname
```

3. Open Telegram and send `/start` to your bot — it should reply.

---

## Step 8 — Enable Telegram Stars payments (for /upgrade)

1. Open [@BotFather](https://t.me/BotFather) in Telegram
2. Send `/mybots` → select your bot
3. Go to **Payments**
4. Select **Telegram Stars**
5. Done — no extra code needed, the bot handles it automatically.

---

## Updating the bot later

Every time you push to GitHub, Render redeploys automatically:

```bash
# make your changes, then:
git add .
git commit -m "describe your change"
git push
```

Render will build and restart the worker within ~2 minutes.

---

## Troubleshooting

**Bot not responding:**
- Check Render Logs for errors
- Confirm `BOT_TOKEN` is correct in Environment variables
- Make sure the Worker is not suspended (free Worker tier may need a paid plan)

**Database errors:**
- Confirm `DATABASE_URL` is linked (Render does this automatically via render.yaml)
- Check Render Logs for `psycopg2` errors

**lottie_convert.py not found:**
- This is installed by `lottie[all]` in requirements.txt
- Check build logs to confirm it installed successfully
- PNG conversion does NOT need lottie_convert.py and will always work

**Payment invoice not sending:**
- Confirm you enabled Telegram Stars in BotFather (Step 8)
- Check Render Logs for `sendInvoice failed`

---

## Free vs Paid Render tier

| | Free | Starter ($7/mo) |
|---|---|---|
| Worker | ❌ Not available | ✅ Always running |
| PostgreSQL | ✅ 90 days free | ✅ Paid |
| Auto-deploy | ✅ | ✅ |

> Telegram bots need a **Worker** (not Web Service), and Workers require the Starter plan on Render.  
> The PostgreSQL database has a free 90-day trial.
