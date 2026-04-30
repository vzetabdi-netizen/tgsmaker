#!/usr/bin/env python3
"""
Enhanced Telegram Bot — SVG to TGS Conversion
Features:
  - SVG (512×512) → TGS conversion
  - Batch processing up to 15 files
  - Free plan  : 5 conversions/day
  - Pro plan   : unlimited, paid via Telegram Stars
  - /upgrade, /myplan, /myhistory, /mystats  (user commands)
  - /giveplan, /removeplan, /ban, /unban, /broadcast, /stats  (admin)
  - /makeadmin, /removeadmin  (owner only)
"""

import os
import logging
import requests
import tempfile
import asyncio
from pathlib import Path
from datetime import datetime, timezone, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading

from database import Database
from batch_converter import BatchConverter
from svg_validator import SVGValidator
from converter import SVGToTGSConverter
from config import Config
from plans import FREE_PLAN, PRO_PLAN, get_plan, format_plan_card, format_upgrade_message

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Instant processing — effectively no delay
BATCH_DELAY = 0.01

class EnhancedSVGToTGSBot:
    def __init__(self):
        self.config = Config()
        self.db = Database()
        self.svg_validator = SVGValidator()
        self.converter = SVGToTGSConverter()
        self.batch_converter = BatchConverter()
        self.base_url = f"https://api.telegram.org/bot{self.config.bot_token}"
        self.offset = 0

        self._init_owner_admin()

    def _init_owner_admin(self):
        oid = self.config.owner_id
        if oid:
            self.db.add_user(oid, "Bot Owner", "Bot", "Owner")
            self.db.set_admin(oid, True)
            self.db.set_user_plan(oid, 'pro', expires_at=None, granted_by=oid)
            logger.info(f"Owner {oid} initialised as admin with Pro plan")

    async def _handle_giveplanall(self, chat_id: int, admin_id: int, parts: list):
        """
        /giveplanall [plan_id] [days]
        Example: /giveplanall pro 7
        Skips users who have already paid via Telegram Stars.
        """
        if len(parts) < 3:
            await self.send_message(
                chat_id,
                "❌ Usage: /giveplanall [plan_id] [days]\n"
                "Example: /giveplanall pro 7\n"
                "Days range: 1–365\n\n"
                "⚠️ Users who paid via Stars are NOT affected."
            )
            return
        try:
            plan_id = parts[1].lower()
            if plan_id not in ('free', 'pro'):
                await self.send_message(chat_id, "❌ plan_id must be 'free' or 'pro'.")
                return

            days = int(parts[2])
            if not (1 <= days <= 365):
                await self.send_message(chat_id, "❌ Days must be between 1 and 365.")
                return

            expires_at = datetime.now(timezone.utc) + timedelta(days=days)
            pm = await self.send_message(chat_id, "⏳ Applying plan to users…")

            updated, skipped = self.db.set_plan_all_users(
                plan_id, expires_at, granted_by=admin_id, protect=['paid', 'manual']
            )
            plan    = get_plan(plan_id)
            exp_str = expires_at.strftime('%Y-%m-%d')

            if plan_id == 'pro':
                user_msg = (
                    f"🎉 <b>Plan Update!</b>\n\n"
                    f"⭐ An admin has activated the <b>Pro</b> plan for you!\n"
                    f"📅 Expires: <b>{exp_str}</b>\n\n"
                    f"✅ Unlimited conversions\n"
                    f"📦 Batch up to {plan.batch_limit} files\n\n"
                    f"Use /myplan to see your quota. Enjoy! 🚀"
                )
            else:
                user_msg = (
                    f"ℹ️ <b>Plan Update!</b>\n\n"
                    f"🆓 Your plan has been set to <b>Free</b> by an admin.\n"
                    f"📅 Valid until: <b>{exp_str}</b>\n\n"
                    f"📊 Daily limit: {plan.daily_limit} conversions\n"
                    f"📦 Batch size: up to {plan.batch_limit} files\n\n"
                    f"Use /upgrade to get Pro."
                )

            updated_uids = self.db.get_users_without_plan('manual')
            notified = 0
            for uid in updated_uids:
                if uid == admin_id:
                    continue
                try:
                    await self.send_message(uid, user_msg)
                    notified += 1
                    await asyncio.sleep(0.05)
                except Exception:
                    pass

            summary = (
                f"✅ {plan.emoji} <b>{plan.name}</b> plan applied!\n\n"
                f"👥 Updated  : <b>{updated}</b> users\n"
                f"💳 Skipped  : <b>{skipped}</b> (manual and paid plans protected)\n"
                f"📨 Notified : <b>{notified}</b> users\n"
                f"📅 Expires  : <b>{exp_str}</b>"
            )
            if pm:
                await self.edit_message(chat_id, pm['message_id'], summary)
            else:
                await self.send_message(chat_id, summary)

            logger.info(
                f"Admin {admin_id} gave {plan_id}/{days}d to {updated} users "
                f"(skipped {skipped} protected), notified {notified}"
            )
        except ValueError:
            await self.send_message(chat_id, "❌ Invalid days value. Use a number (1–365).")
        except Exception as e:
            logger.error(f"giveplanall error: {e}")
            await self.send_message(chat_id, f"❌ Error: {e}")

    async def _handle_removeplanall(self, chat_id: int, admin_id: int, parts: list):
        """
        /removeplanall
        Command to downgrade users with manually assigned plans (not purchased).
        Usage: /removeplanall        — with confirmation prompt
               /removeplanall confirm — executes immediately
        """
        confirmed = len(parts) > 1 and parts[1].lower() == 'confirm'
        if not confirmed:
            total = self.db.get_manual_plan_user_count()
            await self.send_message(
                chat_id,
                f"⚠️ <b>Remove manual plans?</b>\n\n"
                f"👥 Total manually assigned users : <b>{total}</b>\n"
                f"To confirm, send:\n<code>/removeplanall confirm</code>"
            )
            return

        pm = await self.send_message(chat_id, "⏳ Removing manual plans…")
        try:
            updated = self.db.remove_manual_plans(granted_by=admin_id)

            user_msg = (
                "ℹ️ <b>Plan Update!</b>\n\n"
                "🆓 Your plan has been changed to <b>Free</b> by an admin.\n\n"
                "📊 Daily limit: 5 conversions\n"
                "📦 Batch up to 5 files\n\n"
                "Use /upgrade to get Pro again."
            )

            notified = 0
            for uid in self.db.get_users_with_plan_change():
                if uid == admin_id:
                    continue
                try:
                    await self.send_message(uid, user_msg)
                    notified += 1
                    await asyncio.sleep(0.05)
                except Exception:
                    pass

            summary = (
                f"✅ <b>Remove Manual Plans — Done!</b>\n\n"
                f"🆓 Downgraded : <b>{updated}</b> users to Free\n"
                f"📨 Notified   : <b>{notified}</b> users"
            )
            if pm:
                await self.edit_message(chat_id, pm['message_id'], summary)
            else:
                await self.send_message(chat_id, summary)

            logger.info(
                f"Admin {admin_id} removed manual plans from {updated} users, notified {notified}"
            )
        except Exception as e:
            logger.error(f"removeplanall error: {e}")
            await self.send_message(chat_id, f"❌ Error: {e}")

# Remaining existing code continues...
