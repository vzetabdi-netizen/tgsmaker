#!/usr/bin/env python3
"""
Enhanced Telegram Bot — SVG/PNG to TGS Conversion
Features:
  - SVG (512×512) and PNG (≥100×100) → TGS conversion
  - Batch processing up to 15 files
  - Free plan  : 5 conversions/day
  - Pro plan   : unlimited, paid via Telegram Stars
  - /upgrade, /myplan, /myhistory, /mystats      (user commands)
  - /giveplan, /giveplanall, /removeplan         (admin)
  - /ban, /unban, /broadcast, /stats, /adminhelp (admin)
  - /makeadmin, /removeadmin                     (owner only)
"""

import os
import logging
import requests
import tempfile
import asyncio
from pathlib import Path
from datetime import datetime, timezone, timedelta

from database import Database
from batch_converter import BatchConverter
from svg_validator import SVGValidator, PNGValidator
from converter import SVGToTGSConverter
from config import Config
from plans import FREE_PLAN, PRO_PLAN, get_plan, format_plan_card, format_upgrade_message

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BATCH_DELAY = 3.0   # seconds to wait after last file before processing


def _now() -> datetime:
    return datetime.now(timezone.utc)


class EnhancedSVGToTGSBot:
    def __init__(self):
        self.config = Config()
        self.db = Database()
        self.svg_validator = SVGValidator()
        self.png_validator = PNGValidator()
        self.converter = SVGToTGSConverter()
        self.batch_converter = BatchConverter()
        self.base_url = f"https://api.telegram.org/bot{self.config.bot_token}"
        self.offset = 0

        self.user_files: dict[int, list]            = {}
        self.user_timers: dict[int, asyncio.Task]   = {}
        self.user_waiting_message: dict[int, dict]  = {}

        self._init_owner_admin()

    def _init_owner_admin(self):
        oid = self.config.owner_id
        if oid:
            self.db.add_user(oid, "Bot Owner", "Bot", "Owner")
            self.db.set_admin(oid, True)
            self.db.set_user_plan(oid, 'pro', expires_at=None, granted_by=oid)
            logger.info(f"Owner {oid} initialised as admin with Pro plan")

    # ================================================================== #
    # Polling loop
    # ================================================================== #

    async def start(self):
        logger.info("Starting SVG/PNG → TGS bot…")
        try:
            me = await self._api_get("getMe")
            logger.info(f"Bot online: @{me.get('username', '?')}")
        except Exception as e:
            logger.error(f"Cannot contact Telegram API: {e}")
            return

        while True:
            try:
                updates = await self._get_updates()
                for upd in updates:
                    asyncio.create_task(self._handle_update(upd))
            except KeyboardInterrupt:
                logger.info("Bot stopped.")
                break
            except Exception as e:
                logger.error(f"Polling error: {e}")
                await asyncio.sleep(5)

    async def _get_updates(self) -> list:
        params = {'offset': self.offset, 'limit': 100, 'timeout': 10}
        resp = await asyncio.to_thread(
            requests.get, f"{self.base_url}/getUpdates",
            params=params, timeout=15
        )
        if resp.status_code != 200:
            return []
        updates = resp.json().get('result', [])
        if updates:
            self.offset = updates[-1]['update_id'] + 1
        return updates

    # ================================================================== #
    # Update router
    # ================================================================== #

    async def _handle_update(self, update: dict):
        try:
            if 'pre_checkout_query' in update:
                await self._answer_pre_checkout(update['pre_checkout_query'])
                return

            if 'message' not in update:
                return

            msg     = update['message']
            chat_id = msg['chat']['id']
            user_id = msg['from']['id']

            u = msg['from']
            self.db.add_user(user_id, u.get('username'), u.get('first_name'), u.get('last_name'))

            if 'successful_payment' in msg:
                await self._handle_successful_payment(msg)
                return

            if self.db.is_user_banned(user_id):
                await self.send_message(chat_id, "🚫 You are banned from using this bot.")
                return

            text = msg.get('text', '').strip()
            if text.startswith('/'):
                await self._handle_command(msg, text)
            elif 'document' in msg:
                await self._handle_document(msg)
            else:
                await self._send_help_message(chat_id)

        except Exception as e:
            logger.error(f"_handle_update error: {e}")

    # ================================================================== #
    # Command router
    # ================================================================== #

    async def _handle_command(self, msg: dict, text: str):
        chat_id = msg['chat']['id']
        user_id = msg['from']['id']
        parts   = text.split()
        cmd     = parts[0].lower().split('@')[0]

        # ── Public ─────────────────────────────────────────────────
        if cmd == '/start':
            await self._send_welcome_message(chat_id, user_id)
        elif cmd == '/help':
            await self._send_help_message(chat_id)
        elif cmd == '/upgrade':
            await self._handle_upgrade(chat_id, user_id)
        elif cmd == '/myplan':
            await self._handle_myplan(chat_id, user_id)
        elif cmd == '/myhistory':
            await self._handle_myhistory(chat_id, user_id)
        elif cmd == '/mystats':
            await self._handle_mystats(chat_id, user_id)

        # ── Owner only ──────────────────────────────────────────────
        elif cmd == '/makeadmin' and user_id == self.config.owner_id:
            await self._handle_makeadmin(chat_id, parts)
        elif cmd == '/removeadmin' and user_id == self.config.owner_id:
            await self._handle_removeadmin(chat_id, parts)

        # ── Admin ───────────────────────────────────────────────────
        elif self.db.is_admin(user_id):
            if cmd == '/stats':
                await self._send_admin_stats(chat_id)
            elif cmd == '/broadcast':
                await self._handle_broadcast_command(msg)
            elif cmd == '/ban' and len(parts) > 1:
                await self._handle_ban(chat_id, parts[1])
            elif cmd == '/unban' and len(parts) > 1:
                await self._handle_unban(chat_id, parts[1])
            elif cmd == '/giveplan':
                await self._handle_giveplan(chat_id, user_id, parts)
            elif cmd == '/giveplanall':
                await self._handle_giveplanall(chat_id, user_id, parts)
            elif cmd == '/removeplan' and len(parts) > 1:
                await self._handle_removeplan(chat_id, user_id, parts)
            elif cmd == '/adminhelp':
                await self._send_admin_help(chat_id)
            else:
                await self.send_message(chat_id, "❌ Unknown command. Use /adminhelp.")
        else:
            await self.send_message(chat_id, "❌ Unknown command. Use /help.")

    # ================================================================== #
    # User plan commands
    # ================================================================== #

    async def _handle_myplan(self, chat_id: int, user_id: int):
        plan_id = self.db.get_user_plan(user_id)
        plan    = get_plan(plan_id)
        info    = self.db.get_subscription_info(user_id)
        used, _, remaining = self._usage_status(user_id, plan)

        expires_at = info.get('expires_at')
        exp_str    = "Never" if expires_at is None else expires_at.strftime('%Y-%m-%d')

        limit_str     = "Unlimited" if plan.daily_limit == -1 else str(plan.daily_limit)
        remaining_str = "Unlimited" if remaining == -1 else str(remaining)

        text = (
            f"{plan.emoji} <b>Your Plan: {plan.name}</b>\n\n"
            f"Daily limit   : {limit_str} conversions\n"
            f"Used today    : {used}\n"
            f"Remaining     : {remaining_str}\n"
            f"Batch size    : up to {plan.batch_limit} files\n"
            f"Expires       : {exp_str}\n"
        )
        if plan_id == 'free':
            text += "\n💎 Upgrade to Pro for unlimited conversions!\nUse /upgrade"
        await self.send_message(chat_id, text)

    async def _handle_mystats(self, chat_id: int, user_id: int):
        history = self.db.get_user_conversion_history(user_id, limit=100)
        total   = len(history)
        success = sum(1 for h in history if h['success'])
        plan_id = self.db.get_user_plan(user_id)
        plan    = get_plan(plan_id)
        used, _, remaining = self._usage_status(user_id, plan)
        remaining_str = "Unlimited" if remaining == -1 else str(remaining)

        text = (
            f"📊 <b>Your Conversion Stats</b>\n\n"
            f"{plan.emoji} Plan          : {plan.name}\n"
            f"🔄 Total converted : {total}\n"
            f"✅ Successful      : {success}\n"
            f"❌ Failed          : {total - success}\n"
            f"📅 Used today      : {used}\n"
            f"⏳ Remaining today : {remaining_str}\n"
        )
        await self.send_message(chat_id, text)

    async def _handle_myhistory(self, chat_id: int, user_id: int):
        history = self.db.get_user_conversion_history(user_id, limit=10)
        if not history:
            await self.send_message(chat_id, "📭 You have no conversion history yet.")
            return

        lines = ["📋 <b>Your Last 10 Conversions</b>\n"]
        for i, h in enumerate(history, 1):
            status  = "✅" if h['success'] else "❌"
            name    = h.get('file_name') or 'unknown'
            ftype   = (h.get('file_type') or 'svg').upper()
            size_kb = round((h.get('file_size') or 0) / 1024, 1)
            dt      = h.get('conversion_date')
            date    = dt.strftime('%m-%d %H:%M') if dt else '?'
            lines.append(f"{i}. {status} <code>{name}</code> [{ftype}] {size_kb}KB — {date}")

        await self.send_message(chat_id, "\n".join(lines))

    # ================================================================== #
    # Upgrade / Telegram Stars payment
    # ================================================================== #

    async def _handle_upgrade(self, chat_id: int, user_id: int):
        plan_id = self.db.get_user_plan(user_id)
        if plan_id == 'pro':
            info    = self.db.get_subscription_info(user_id)
            expires = info.get('expires_at')
            exp_str = "Never" if expires is None else expires.strftime('%Y-%m-%d')
            await self.send_message(
                chat_id,
                f"⭐ You are already on the <b>Pro</b> plan!\nExpires: {exp_str}"
            )
            return
        await self._send_stars_invoice(chat_id, user_id)

    async def _send_stars_invoice(self, chat_id: int, user_id: int):
        url  = f"{self.base_url}/sendInvoice"
        data = {
            'chat_id':        chat_id,
            'title':          '⭐ Pro Plan — 1 Month',
            'description':    'Unlimited SVG & PNG → TGS conversions for 30 days. Batch up to 15 files.',
            'payload':        f'pro_1month_{user_id}',
            'currency':       'XTR',
            'prices':         f'[{{"label":"Pro Plan 1 Month","amount":{PRO_PLAN.price_stars}}}]',
            'provider_token': '',
        }
        resp = await asyncio.to_thread(requests.post, url, data=data)
        if resp.status_code != 200:
            logger.error(f"sendInvoice failed: {resp.text}")
            await self.send_message(chat_id, format_upgrade_message(FREE_PLAN))

    async def _answer_pre_checkout(self, pcq: dict):
        url  = f"{self.base_url}/answerPreCheckoutQuery"
        data = {'pre_checkout_query_id': pcq['id'], 'ok': True}
        await asyncio.to_thread(requests.post, url, data=data)

    async def _handle_successful_payment(self, msg: dict):
        user_id   = msg['from']['id']
        chat_id   = msg['chat']['id']
        payment   = msg['successful_payment']
        charge_id = payment['telegram_payment_charge_id']
        stars     = payment['total_amount']

        expires = _now() + timedelta(days=30)
        self.db.set_user_plan(user_id, 'pro', expires_at=expires)
        self.db.log_payment(user_id, charge_id, stars, 'pro', status='completed')

        await self.send_message(
            chat_id,
            f"🎉 <b>Pro Plan Activated!</b>\n\n"
            f"Thank you for <b>{stars} ⭐ Stars</b>.\n"
            f"Pro plan active until <b>{expires.strftime('%Y-%m-%d')}</b>.\n\n"
            f"Enjoy unlimited conversions! 🚀"
        )
        logger.info(f"User {user_id} upgraded to Pro (charge {charge_id}, {stars} Stars)")

    # ================================================================== #
    # Admin — plan management
    # ================================================================== #

    async def _handle_giveplan(self, chat_id: int, admin_id: int, parts: list):
        """
        /giveplan [user_id] [plan_id] [days]
        days is optional — omit for a permanent grant.
        Examples:
          /giveplan 123456789 pro 30
          /giveplan 123456789 pro
        """
        if len(parts) < 3:
            await self.send_message(
                chat_id,
                "❌ Usage: /giveplan [user_id] [plan] [days]\n"
                "Example: /giveplan 123456789 pro 30\n"
                "Omit [days] for a permanent grant."
            )
            return

        try:
            uid     = int(parts[1])
            plan_id = parts[2].lower()

            if plan_id not in ('free', 'pro'):
                await self.send_message(chat_id, "❌ Plan must be 'free' or 'pro'.")
                return

            expires_at = None
            days_given = None
            if len(parts) >= 4:
                # BUG FIX: strip any non-digit characters so "2day" or "30days" also works
                raw_days = ''.join(filter(str.isdigit, parts[3]))
                if not raw_days:
                    await self.send_message(chat_id, "❌ Invalid days value. Use a number e.g. 30")
                    return
                days_given = int(raw_days)
                if days_given < 1 or days_given > 3650:
                    await self.send_message(chat_id, "❌ Days must be between 1 and 3650.")
                    return
                expires_at = _now() + timedelta(days=days_given)

            # Ensure user row exists in DB before setting plan
            self.db.add_user(uid)
            ok = self.db.set_user_plan(uid, plan_id, expires_at=expires_at, granted_by=admin_id)

            if not ok:
                await self.send_message(chat_id, f"❌ Failed to set plan for user {uid}.")
                return

            plan    = get_plan(plan_id)
            exp_str = "Never (permanent)" if expires_at is None else expires_at.strftime('%Y-%m-%d')

            # Confirm to admin
            await self.send_message(
                chat_id,
                f"✅ {plan.emoji} <b>{plan.name}</b> plan granted to user <code>{uid}</code>\n"
                f"Expires: {exp_str}"
            )

            # Notify the user
            if days_given:
                user_msg = (
                    f"🎁 <b>Plan Updated!</b>\n\n"
                    f"An admin has given you the {plan.emoji} <b>{plan.name}</b> plan "
                    f"for <b>{days_given} days</b>.\n"
                    f"Expires: <b>{expires_at.strftime('%Y-%m-%d')}</b>\n\n"
                    f"Enjoy your conversions! 🚀"
                )
            else:
                user_msg = (
                    f"🎁 <b>Plan Updated!</b>\n\n"
                    f"An admin has given you the {plan.emoji} <b>{plan.name}</b> plan "
                    f"<b>permanently</b>.\n\n"
                    f"Enjoy unlimited conversions! 🚀"
                )
            try:
                await self.send_message(uid, user_msg)
            except Exception as e:
                logger.warning(f"Could not notify user {uid}: {e}")

            logger.info(f"Admin {admin_id} gave {plan_id} to user {uid} (expires {expires_at})")

        except ValueError:
            await self.send_message(chat_id, "❌ Invalid user_id. Must be a number.")

    async def _handle_giveplanall(self, chat_id: int, admin_id: int, parts: list):
        """
        /giveplanall [plan_id] [days]
        Give a plan to ALL non-banned users.
        Examples:
          /giveplanall pro 7
          /giveplanall free 30
        """
        if len(parts) < 3:
            await self.send_message(
                chat_id,
                "❌ Usage: /giveplanall [plan] [days]\n"
                "Example: /giveplanall pro 7\n"
                "Days range: 1–3650"
            )
            return

        try:
            plan_id = parts[1].lower()
            if plan_id not in ('free', 'pro'):
                await self.send_message(chat_id, "❌ Plan must be 'free' or 'pro'.")
                return

            raw_days = ''.join(filter(str.isdigit, parts[2]))
            if not raw_days:
                await self.send_message(chat_id, "❌ Invalid days value. Use a number e.g. 7")
                return
            days = int(raw_days)
            if days < 1 or days > 3650:
                await self.send_message(chat_id, "❌ Days must be between 1 and 3650.")
                return

            expires_at = _now() + timedelta(days=days)
            plan       = get_plan(plan_id)
            exp_str    = expires_at.strftime('%Y-%m-%d')

            pm    = await self.send_message(chat_id, "⏳ Applying plan to all users…")
            count = self.db.set_plan_all_users(plan_id, expires_at, granted_by=admin_id)

            # Notify all users
            all_uids = self.db.get_all_users()
            if plan_id == 'pro':
                user_msg = (
                    f"🎉 <b>Plan Updated!</b>\n\n"
                    f"⭐ An admin has activated the <b>Pro</b> plan for you!\n"
                    f"📅 Expires: <b>{exp_str}</b>\n\n"
                    f"✅ Unlimited conversions, batch up to {plan.batch_limit} files.\n"
                    f"Enjoy! 🚀"
                )
            else:
                user_msg = (
                    f"ℹ️ <b>Plan Updated!</b>\n\n"
                    f"🆓 Your plan has been set to <b>Free</b> by an admin.\n"
                    f"📅 Valid until: <b>{exp_str}</b>\n\n"
                    f"• Daily limit : 5 conversions\n"
                    f"• Batch size  : up to {plan.batch_limit} files\n"
                    f"Use /upgrade to get Pro."
                )

            notified = 0
            for uid in all_uids:
                if uid == admin_id:
                    continue
                try:
                    await self.send_message(uid, user_msg)
                    notified += 1
                    await asyncio.sleep(0.05)
                except Exception:
                    pass

            summary = (
                f"✅ {plan.emoji} <b>{plan.name}</b> plan applied to <b>{count}</b> users!\n"
                f"📅 Expires: <b>{exp_str}</b>\n"
                f"📨 Notified: <b>{notified}</b> users"
            )
            if pm:
                await self.edit_message(chat_id, pm['message_id'], summary)
            else:
                await self.send_message(chat_id, summary)

            logger.info(f"Admin {admin_id} ran giveplanall {plan_id}/{days}d → {count} users")

        except ValueError:
            await self.send_message(chat_id, "❌ Invalid value.")
        except Exception as e:
            logger.error(f"giveplanall error: {e}")
            await self.send_message(chat_id, f"❌ Error: {e}")

    async def _handle_removeplan(self, chat_id: int, admin_id: int, parts: list):
        """
        /removeplan [user_id]  — Downgrade user to Free immediately.
        """
        if len(parts) < 2:
            await self.send_message(chat_id, "❌ Usage: /removeplan [user_id]")
            return
        try:
            uid = int(parts[1])
            self.db.add_user(uid)
            self.db.set_user_plan(uid, 'free', expires_at=None, granted_by=admin_id)

            await self.send_message(
                chat_id,
                f"✅ User <code>{uid}</code> downgraded to the 🆓 Free plan."
            )
            try:
                await self.send_message(
                    uid,
                    "⚠️ <b>Plan Updated!</b>\n\n"
                    "Your plan has been changed to 🆓 <b>Free</b> by an admin.\n\n"
                    "Daily limit: 5 conversions/day.\n"
                    "Use /upgrade to get Pro again."
                )
            except Exception:
                pass

            logger.info(f"Admin {admin_id} removed plan from user {uid}")
        except ValueError:
            await self.send_message(chat_id, "❌ Invalid user ID.")

    # ================================================================== #
    # Admin — user commands
    # ================================================================== #

    async def _handle_makeadmin(self, chat_id: int, parts: list):
        if len(parts) < 2:
            await self.send_message(chat_id, "❌ Usage: /makeadmin [user_id]")
            return
        try:
            uid = int(parts[1])
            if self.db.set_admin(uid, True):
                await self.send_message(chat_id, f"✅ User <code>{uid}</code> is now an admin.")
            else:
                await self.send_message(chat_id, f"❌ User <code>{uid}</code> not found.")
        except ValueError:
            await self.send_message(chat_id, "❌ Invalid user ID.")

    async def _handle_removeadmin(self, chat_id: int, parts: list):
        if len(parts) < 2:
            await self.send_message(chat_id, "❌ Usage: /removeadmin [user_id]")
            return
        try:
            uid = int(parts[1])
            if uid == self.config.owner_id:
                await self.send_message(chat_id, "❌ Cannot remove owner admin privileges.")
                return
            if self.db.set_admin(uid, False):
                await self.send_message(chat_id, f"✅ User <code>{uid}</code> is no longer an admin.")
            else:
                await self.send_message(chat_id, f"❌ User <code>{uid}</code> not found.")
        except ValueError:
            await self.send_message(chat_id, "❌ Invalid user ID.")

    async def _handle_ban(self, chat_id: int, uid_str: str):
        try:
            uid = int(uid_str)
            if uid == self.config.owner_id:
                await self.send_message(chat_id, "❌ Cannot ban the bot owner.")
                return
            if self.db.ban_user(uid):
                await self.send_message(chat_id, f"✅ User <code>{uid}</code> has been banned.")
            else:
                await self.send_message(chat_id, f"❌ User <code>{uid}</code> not found.")
        except ValueError:
            await self.send_message(chat_id, "❌ Invalid user ID.")

    async def _handle_unban(self, chat_id: int, uid_str: str):
        try:
            uid = int(uid_str)
            if self.db.unban_user(uid):
                await self.send_message(chat_id, f"✅ User <code>{uid}</code> has been unbanned.")
            else:
                await self.send_message(chat_id, f"❌ User <code>{uid}</code> not found / not banned.")
        except ValueError:
            await self.send_message(chat_id, "❌ Invalid user ID.")

    async def _send_admin_stats(self, chat_id: int):
        try:
            s = self.db.get_stats()
            text = (
                "<b>📊 Bot Statistics</b>\n\n"
                f"👥 Total Users        : {s.get('total_users', 0)}\n"
                f"🟢 Active (7 days)    : {s.get('active_users', 0)}\n"
                f"🚫 Banned             : {s.get('banned_users', 0)}\n"
                f"⭐ Pro Users          : {s.get('pro_users', 0)}\n\n"
                f"🔄 Total Conversions  : {s.get('total_conversions', 0)}\n"
                f"✅ Successful         : {s.get('success_conversions', 0)}\n"
                f"📊 Success Rate       : {s.get('success_rate', 0)}%\n\n"
                f"💰 Stars Earned       : {s.get('total_stars_earned', 0)} ⭐\n\n"
                f"🕐 {_now().strftime('%Y-%m-%d %H:%M:%S')} UTC"
            )
            await self.send_message(chat_id, text)
        except Exception as e:
            logger.error(f"Error getting stats: {e}")
            await self.send_message(chat_id, "❌ Error retrieving statistics.")

    async def _handle_broadcast_command(self, msg: dict):
        chat_id  = msg['chat']['id']
        admin_id = msg['from']['id']
        if 'reply_to_message' in msg:
            await self._do_broadcast(chat_id, msg['reply_to_message'], admin_id)
        else:
            text  = msg.get('text', '')
            parts = text.split(' ', 1)
            if len(parts) < 2:
                await self.send_message(
                    chat_id,
                    "❌ Usage: /broadcast [message]  or reply to a message with /broadcast"
                )
                return
            await self._do_broadcast(chat_id, {'text': parts[1]}, admin_id)

    async def _do_broadcast(self, admin_chat_id: int, bcast_msg: dict, admin_id: int):
        users = self.db.get_all_users()
        if not users:
            await self.send_message(admin_chat_id, "❌ No users to broadcast to.")
            return

        media_file_id = None
        media_type    = 'text'
        if bcast_msg.get('photo'):
            media_file_id = bcast_msg['photo'][-1]['file_id'];  media_type = 'photo'
        elif bcast_msg.get('video'):
            media_file_id = bcast_msg['video']['file_id'];      media_type = 'video'
        elif bcast_msg.get('document'):
            media_file_id = bcast_msg['document']['file_id'];   media_type = 'document'

        bcast_id = self.db.log_broadcast(admin_id, bcast_msg.get('text', '[Media]'),
                                         media_file_id, media_type)
        progress = await self.send_message(admin_chat_id,
                                           f"📡 Broadcasting to {len(users)} users…")
        sent = failed = 0
        for i, uid in enumerate(users):
            if uid == admin_id:
                continue
            try:
                if 'text' in bcast_msg:
                    await self.send_message(uid, bcast_msg['text'])
                elif media_type == 'photo':
                    await self._send_photo(uid, media_file_id, bcast_msg.get('caption', ''))
                elif media_type == 'video':
                    await self._send_video(uid, media_file_id, bcast_msg.get('caption', ''))
                elif media_type == 'document':
                    await self._send_document_by_id(uid, media_file_id, bcast_msg.get('caption', ''))
                sent += 1
                if (i + 1) % 10 == 0 and progress:
                    await self.edit_message(admin_chat_id, progress['message_id'],
                                            f"📡 Broadcasting… {sent}/{len(users)}")
                await asyncio.sleep(0.05)
            except Exception as e:
                failed += 1
                logger.warning(f"Broadcast failed uid {uid}: {e}")

        if bcast_id:
            self.db.update_broadcast_count(bcast_id, sent)

        rate  = round(sent / len(users) * 100, 1) if users else 0
        final = (f"✅ <b>Broadcast done!</b>\n"
                 f"📤 Sent: {sent}  ❌ Failed: {failed}  📊 {rate}%")
        if progress:
            await self.edit_message(admin_chat_id, progress['message_id'], final)

    # ================================================================== #
    # Document handling
    # ================================================================== #

    async def _handle_document(self, msg: dict):
        chat_id = msg['chat']['id']
        doc     = msg['document']

        if doc['file_size'] > self.config.max_file_size:
            mb = self.config.max_file_size // (1024 * 1024)
            await self.send_message(chat_id, f"❌ File too large. Max: {mb} MB")
            return

        if self._is_svg_file(doc):
            await self._queue_file(msg, 'svg')
        elif self._is_png_file(doc):
            await self._queue_file(msg, 'png')
        elif (doc.get('mime_type') == 'application/zip' or
              doc.get('file_name', '').lower().endswith('.zip')):
            await self._handle_batch_zip(msg)
        else:
            await self.send_message(
                chat_id,
                "❌ Please send SVG or PNG files.\n"
                "SVG: must be 512×512 px\n"
                "PNG: must be at least 100×100 px"
            )

    @staticmethod
    def _is_svg_file(doc: dict) -> bool:
        return (doc.get('mime_type') == 'image/svg+xml' or
                doc.get('file_name', '').lower().endswith('.svg'))

    @staticmethod
    def _is_png_file(doc: dict) -> bool:
        return (doc.get('mime_type') == 'image/png' or
                doc.get('file_name', '').lower().endswith('.png'))

    # ================================================================== #
    # Batch queue
    # ================================================================== #

    def _usage_status(self, user_id: int, plan) -> tuple[int, int, int]:
        _, used, remaining = self.db.check_daily_limit(user_id, plan.daily_limit)
        return used, plan.daily_limit, remaining

    async def _queue_file(self, msg: dict, file_type: str):
        chat_id = msg['chat']['id']
        user_id = msg['from']['id']
        doc     = msg['document']

        plan_id = self.db.get_user_plan(user_id)
        plan    = get_plan(plan_id)

        allowed, used, remaining = self.db.check_daily_limit(user_id, plan.daily_limit)
        if not allowed:
            upgrade_hint = "\n\n💎 Upgrade to Pro for unlimited conversions — /upgrade" \
                           if plan_id == 'free' else ""
            await self.send_message(
                chat_id,
                f"⛔ You've reached your daily limit of <b>{plan.daily_limit}</b> conversions.\n"
                f"Used today: {used}{upgrade_hint}"
            )
            return

        if user_id not in self.user_files:
            self.user_files[user_id] = []

        pending = len(self.user_files[user_id])
        if pending >= plan.batch_limit:
            await self.send_message(
                chat_id,
                f"❌ Your plan allows max <b>{plan.batch_limit}</b> files per batch.\n"
                f"Please wait for the current batch to finish."
            )
            return

        slots_by_quota = (remaining if remaining != -1 else plan.batch_limit) - pending
        if slots_by_quota <= 0:
            await self.send_message(
                chat_id,
                f"⛔ Adding this file would exceed your daily limit of <b>{plan.daily_limit}</b>."
            )
            return

        self.user_files[user_id].append({'document': doc, 'file_type': file_type})

        if len(self.user_files[user_id]) == 1:
            self.user_waiting_message[user_id] = await self.send_message(
                chat_id, f"⏳ Please wait {int(BATCH_DELAY)} seconds…"
            )

        if user_id in self.user_timers:
            self.user_timers[user_id].cancel()

        self.user_timers[user_id] = asyncio.create_task(
            self._delayed_process(user_id, chat_id)
        )

    async def _delayed_process(self, user_id: int, chat_id: int):
        try:
            await asyncio.sleep(BATCH_DELAY)
            if self.user_files.get(user_id):
                await self._process_batch(user_id, chat_id)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"_delayed_process error: {e}")

    # ================================================================== #
    # Core batch processing
    # ================================================================== #

    async def _process_batch(self, user_id: int, chat_id: int):
        files       = self.user_files.pop(user_id, [])
        self.user_timers.pop(user_id, None)
        waiting_msg = self.user_waiting_message.pop(user_id, None)

        if not files:
            return

        plan_id = self.db.get_user_plan(user_id)
        plan    = get_plan(plan_id)

        successful: list[dict] = []
        failed_count = 0

        for i, fi in enumerate(files):
            doc   = fi['document']
            ftype = fi['file_type']
            fname = doc.get('file_name', f'file_{i+1}.{ftype}')

            try:
                fpath = await self._download_file(doc['file_id'], suffix=f'.{ftype}')
                try:
                    if ftype == 'svg':
                        ok, err = self.svg_validator.validate_svg_file(fpath)
                    else:
                        ok, err = self.png_validator.validate_png_file(fpath)

                    if not ok:
                        failed_count += 1
                        self.db.add_conversion(user_id, fname, doc['file_size'],
                                               success=False, file_type=ftype)
                        continue

                    tgs_path = await self.converter.convert(fpath)
                    tgs_name = Path(fname).stem + '.tgs'
                    successful.append({'tgs_path': tgs_path, 'filename': tgs_name})
                    self.db.add_conversion(user_id, fname, doc['file_size'],
                                           success=True, file_type=ftype)

                except Exception as e:
                    logger.error(f"Conversion error [{fname}]: {e}")
                    failed_count += 1
                    self.db.add_conversion(user_id, fname, doc['file_size'],
                                           success=False, file_type=ftype)
                finally:
                    if os.path.exists(fpath):
                        os.unlink(fpath)

            except Exception as e:
                logger.error(f"Download error [{fname}]: {e}")
                failed_count += 1

        if successful:
            self.db.increment_today_usage(user_id, len(successful))

        for conv in successful:
            try:
                await self._send_document(chat_id, conv['tgs_path'], conv['filename'])
            except Exception as e:
                logger.error(f"Send error [{conv['filename']}]: {e}")
            finally:
                if os.path.exists(conv['tgs_path']):
                    os.unlink(conv['tgs_path'])

        if waiting_msg:
            try:
                await self.edit_message(chat_id, waiting_msg['message_id'], "✅ Done — 100%")
            except Exception:
                pass

        if plan_id == 'free' and successful:
            used_now = self.db.get_today_usage(user_id)
            left     = max(0, plan.daily_limit - used_now)
            if left == 0:
                await self.send_message(
                    chat_id,
                    f"⚠️ You've used all {plan.daily_limit} free conversions for today.\n"
                    f"Upgrade to Pro — /upgrade"
                )
            else:
                await self.send_message(
                    chat_id,
                    f"💡 {left} free conversion{'s' if left != 1 else ''} remaining today. "
                    f"Use /upgrade for unlimited."
                )

    # ================================================================== #
    # ZIP batch
    # ================================================================== #

    async def _handle_batch_zip(self, msg: dict):
        chat_id = msg['chat']['id']
        user_id = msg['from']['id']
        doc     = msg['document']

        plan_id = self.db.get_user_plan(user_id)
        plan    = get_plan(plan_id)
        allowed, used, remaining = self.db.check_daily_limit(user_id, plan.daily_limit)
        if not allowed:
            upgrade = "\n\nUpgrade with /upgrade" if plan_id == 'free' else ""
            await self.send_message(
                chat_id,
                f"⛔ Daily limit reached ({plan.daily_limit} conversions).{upgrade}"
            )
            return

        try:
            pm    = await self.send_message(chat_id, "🔄 Processing ZIP archive…")
            zpath = await self._download_file(doc['file_id'], suffix='.zip')

            try:
                fpaths, names, errors = self.batch_converter.extract_files_from_zip(
                    zpath, max_files=plan.batch_limit
                )
                if errors:
                    await self.send_message(chat_id, f"❌ ZIP errors: {'; '.join(errors)}")
                    return
                if not fpaths:
                    await self.send_message(chat_id, "❌ No SVG files found in ZIP.")
                    return

                results = await self.batch_converter.convert_batch(fpaths, names)
                self.batch_converter.cleanup_temp_files(fpaths)

                if results['successful']:
                    for cr in results['successful']:
                        try:
                            await self._send_document(chat_id, cr['tgs_path'], cr['output_name'])
                        except Exception as e:
                            logger.error(f"ZIP send error: {e}")
                        finally:
                            if os.path.exists(cr['tgs_path']):
                                os.unlink(cr['tgs_path'])
                    self.db.increment_today_usage(user_id, results['success_count'])

                summary = (
                    f"🎯 <b>ZIP done!</b> "
                    f"✅ {results['success_count']}  ❌ {results['error_count']}  "
                    f"📁 {results['total_processed']}"
                )
                if pm:
                    await self.edit_message(chat_id, pm['message_id'], summary)
            finally:
                if os.path.exists(zpath):
                    os.unlink(zpath)

        except Exception as e:
            logger.error(f"ZIP error: {e}")
            await self.send_message(chat_id, f"❌ ZIP processing failed: {e}")

    # ================================================================== #
    # Telegram API helpers
    # ================================================================== #

    async def _api_get(self, method: str, params: dict | None = None) -> dict:
        resp = await asyncio.to_thread(
            requests.get, f"{self.base_url}/{method}", params=params or {}, timeout=15
        )
        resp.raise_for_status()
        data = resp.json()
        if not data.get('ok'):
            raise Exception(data.get('description', 'Unknown Telegram error'))
        return data['result']

    async def _download_file(self, file_id: str, suffix: str = '.tmp') -> str:
        info    = await self._api_get("getFile", {'file_id': file_id})
        dl_url  = f"https://api.telegram.org/file/bot{self.config.bot_token}/{info['file_path']}"
        dl_resp = await asyncio.to_thread(requests.get, dl_url, timeout=60)
        if dl_resp.status_code != 200:
            raise Exception(f"Download failed: {dl_resp.status_code}")
        fd, path = tempfile.mkstemp(suffix=suffix)
        with os.fdopen(fd, 'wb') as f:
            f.write(dl_resp.content)
        return path

    async def send_message(self, chat_id, text: str) -> dict | None:
        resp = await asyncio.to_thread(
            requests.post, f"{self.base_url}/sendMessage",
            data={'chat_id': chat_id, 'text': text, 'parse_mode': 'HTML'}
        )
        if resp.status_code == 200:
            return resp.json()['result']
        logger.error(f"sendMessage failed: {resp.text[:200]}")
        return None

    async def edit_message(self, chat_id, message_id, text: str) -> dict | None:
        resp = await asyncio.to_thread(
            requests.post, f"{self.base_url}/editMessageText",
            data={'chat_id': chat_id, 'message_id': message_id,
                  'text': text, 'parse_mode': 'HTML'}
        )
        if resp.status_code == 200:
            return resp.json()['result']
        return None

    async def _send_document(self, chat_id, fpath: str, fname: str, caption: str = '') -> dict | None:
        with open(fpath, 'rb') as f:
            resp = await asyncio.to_thread(
                requests.post, f"{self.base_url}/sendDocument",
                data={'chat_id': chat_id, 'caption': caption},
                files={'document': (fname, f)}
            )
        if resp.status_code == 200:
            return resp.json()['result']
        logger.error(f"sendDocument failed: {resp.text[:200]}")
        return None

    async def _send_document_by_id(self, chat_id, file_id: str, caption: str = '') -> dict | None:
        resp = await asyncio.to_thread(
            requests.post, f"{self.base_url}/sendDocument",
            data={'chat_id': chat_id, 'document': file_id, 'caption': caption}
        )
        if resp.status_code == 200:
            return resp.json()['result']
        return None

    async def _send_photo(self, chat_id, photo_id: str, caption: str = '') -> dict | None:
        resp = await asyncio.to_thread(
            requests.post, f"{self.base_url}/sendPhoto",
            data={'chat_id': chat_id, 'photo': photo_id, 'caption': caption}
        )
        if resp.status_code == 200:
            return resp.json()['result']
        return None

    async def _send_video(self, chat_id, video_id: str, caption: str = '') -> dict | None:
        resp = await asyncio.to_thread(
            requests.post, f"{self.base_url}/sendVideo",
            data={'chat_id': chat_id, 'video': video_id, 'caption': caption}
        )
        if resp.status_code == 200:
            return resp.json()['result']
        return None

    # ================================================================== #
    # Static messages
    # ================================================================== #

    async def _send_welcome_message(self, chat_id: int, user_id: int):
        plan_id = self.db.get_user_plan(user_id)
        plan    = get_plan(plan_id)
        used, _, remaining = self._usage_status(user_id, plan)
        rem_str = "Unlimited" if remaining == -1 else str(remaining)

        text = (
            "🎨 <b>SVG / PNG → TGS Converter</b>\n\n"
            f"Your plan: {plan.emoji} <b>{plan.name}</b>\n"
            f"Used today: {used}  |  Remaining: {rem_str}\n\n"
            "<b>Supported formats:</b>\n"
            "• SVG — must be exactly 512×512 px\n"
            "• PNG — minimum 100×100 px\n\n"
            "<b>How to use:</b>\n"
            f"1. Send up to {plan.batch_limit} files\n"
            f"2. Wait {int(BATCH_DELAY)}s after your last file\n"
            "3. Receive your TGS stickers!\n\n"
            "<b>Commands:</b>\n"
            "/myplan     — Your plan & quota\n"
            "/mystats    — Your conversion stats\n"
            "/myhistory  — Last 10 conversions\n"
            "/upgrade    — Go Pro (unlimited)\n"
            "/help       — Full help"
        )
        await self.send_message(chat_id, text)

    async def _send_help_message(self, chat_id: int):
        text = (
            "<b>🔧 Help</b>\n\n"
            "<b>File requirements:</b>\n"
            "• SVG: exactly 512×512 px\n"
            "• PNG: at least 100×100 px\n"
            "• Max 10 MB per file\n\n"
            "<b>Plans:</b>\n"
            f"🆓 Free — 5 conversions/day, batch up to {FREE_PLAN.batch_limit}\n"
            f"⭐ Pro  — Unlimited, batch up to {PRO_PLAN.batch_limit}, "
            f"{PRO_PLAN.price_stars} Stars/month\n\n"
            "<b>Commands:</b>\n"
            "/start      — Welcome screen\n"
            "/myplan     — View your plan & quota\n"
            "/mystats    — Your stats\n"
            "/myhistory  — Last 10 conversions\n"
            "/upgrade    — Upgrade to Pro\n"
            "/help       — This message"
        )
        await self.send_message(chat_id, text)

    async def _send_admin_help(self, chat_id: int):
        text = (
            "<b>🔑 Admin Commands</b>\n\n"
            "<b>Plan management:</b>\n"
            "/giveplan [id] [plan] [days]  — Grant plan to user\n"
            "/giveplanall [plan] [days]    — Grant plan to ALL users\n"
            "/removeplan [id]              — Downgrade user to Free\n\n"
            "<b>User management:</b>\n"
            "/ban [id]                     — Ban user\n"
            "/unban [id]                   — Unban user\n\n"
            "<b>Stats & broadcast:</b>\n"
            "/stats                        — Bot statistics\n"
            "/broadcast [msg]              — Broadcast to all users\n"
            "/adminhelp                    — This message\n\n"
            "<b>Owner only:</b>\n"
            "/makeadmin [id]               — Grant admin\n"
            "/removeadmin [id]             — Revoke admin\n\n"
            "<b>Examples:</b>\n"
            "<code>/giveplan 123456789 pro 30</code>\n"
            "<code>/giveplan 123456789 pro</code>  (permanent)\n"
            "<code>/giveplanall pro 7</code>\n"
            "<code>/removeplan 123456789</code>"
        )
        await self.send_message(chat_id, text)


# ======================================================================== #

async def main():
    bot = EnhancedSVGToTGSBot()
    await bot.start()


if __name__ == '__main__':
    asyncio.run(main())
