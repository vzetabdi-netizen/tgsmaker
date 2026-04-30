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

    async def _handle_giveplan(self, chat_id: int, admin_id: int, parts: list):
        """
        /giveplan [user_id] [plan_id] [days]
        Assigns a plan to a specific user.
        """
        if len(parts) < 3:
            await self.send_message(
                chat_id,
                "❌ Usage: /giveplan [user_id] [plan_id] [days]\n"
                "Example: /giveplan 123456789 pro 30\n"
            )
            return
        try:
            user_id = int(parts[1])
            plan_id = parts[2].lower()
            if plan_id not in ('free', 'pro'):
                await self.send_message(chat_id, "❌ Invalid plan_id. Use 'free' or 'pro'.")
                return

            days = int(parts[3]) if len(parts) > 3 else None
            expires_at = (
                datetime.now(timezone.utc) + timedelta(days=days)
                if days else None
            )

            self.db.set_user_plan(user_id, plan_id, expires_at=expires_at, granted_by=admin_id)

            await self.send_message(
                chat_id,
                f"✅ Plan {plan_id.upper()} has been assigned to user {user_id}.\n"
                f"Expires: {expires_at.strftime('%Y-%m-%d') if expires_at else 'Never'}"
            )
        except ValueError:
            await self.send_message(chat_id, "❌ Invalid user ID or days.")

    async def _handle_giveplanall(self, chat_id: int, admin_id: int, parts: list):
        """
        /giveplanall [plan_id] [days]
        Assigns a plan to multiple users who are eligible.
        """
        if len(parts) < 3:
            await self.send_message(
                chat_id,
                "❌ Usage: /giveplanall [plan_id] [days]\n"
                "Example: /giveplanall pro 7\n"
            )
            return
        try:
            plan_id = parts[1].lower()
            days = int(parts[2])
            if plan_id not in ('free', 'pro') or not (1 <= days <= 365):
                await self.send_message(chat_id, "❌ Invalid plan_id or days.")
                return

            expires_at = datetime.now(timezone.utc) + timedelta(days=days)
            eligible_users = self.db.get_eligible_users()

            for user in eligible_users:
                self.db.set_user_plan(
                    user['id'], plan_id, expires_at=expires_at, granted_by=admin_id
                )

            await self.send_message(
                chat_id,
                f"✅ Plan {plan_id.upper()} assigned to all eligible users.\n"
                f"Expires: {expires_at.strftime('%Y-%m-%d')}"
            )
        except ValueError:
            await self.send_message(chat_id, "❌ Invalid input.")

    async def _handle_removeplanall(self, chat_id: int, admin_id: int, parts: list):
        """
        /removeplanall
        Removes a plan from all manually-assigned users.
        """
        if len(parts) > 1 and parts[1].lower() == 'confirm':
            self.db.remove_manual_plans(granted_by=admin_id)
            await self.send_message(chat_id, "✅ All manually-assigned plans have been removed.")
        else:
            await self.send_message(
                chat_id,
                "⚠️ Are you sure you want to remove all manually-assigned plans?\n"
                "Send: /removeplanall confirm"
            )

# Remaining code unchanged...