"""
Database module — MongoDB version (pymongo).
Drop-in replacement for the PostgreSQL version.
All public method signatures are identical so the rest of the codebase is unchanged.
"""

import os
import logging
from datetime import datetime, timedelta

from pymongo import MongoClient, DESCENDING
from pymongo.errors import DuplicateKeyError

logger = logging.getLogger(__name__)


class Database:
    def __init__(self):
        uri = os.environ.get('DATABASE_URL')
        if not uri:
            raise ValueError("DATABASE_URL environment variable not found")

        self.client = MongoClient(uri)
        # Use database name from env or default
        db_name = os.environ.get('MONGO_DB_NAME', 'svg_tgs_bot')
        self.db = self.client[db_name]

        # Collections
        self.users         = self.db['users']
        self.subscriptions = self.db['subscriptions']
        self.payments      = self.db['payments']
        self.daily_usage   = self.db['daily_usage']
        self.conversions   = self.db['conversions']
        self.broadcasts    = self.db['broadcasts']

        self._ensure_indexes()
        logger.info(f"MongoDB connected — database: {db_name}")

    def _ensure_indexes(self):
        """Create indexes for fast lookups."""
        try:
            self.users.create_index('user_id', unique=True)
            self.subscriptions.create_index('user_id', unique=True)
            self.payments.create_index('telegram_charge_id', unique=True, sparse=True)
            self.daily_usage.create_index(
                [('user_id', 1), ('usage_date', 1)], unique=True
            )
            self.conversions.create_index('user_id')
            self.conversions.create_index('conversion_date')
            logger.info("MongoDB indexes ensured")
        except Exception as e:
            logger.error(f"Index creation error: {e}")

    # ------------------------------------------------------------------ #
    # User management
    # ------------------------------------------------------------------ #

    def add_user(self, user_id, username=None, first_name=None, last_name=None):
        try:
            now = datetime.utcnow()
            self.users.update_one(
                {'user_id': user_id},
                {'$set': {
                    'username':    username,
                    'first_name':  first_name,
                    'last_name':   last_name,
                    'last_active': now,
                },
                 '$setOnInsert': {
                    'user_id':   user_id,
                    'is_banned': False,
                    'is_admin':  False,
                    'join_date': now,
                }},
                upsert=True
            )
            # Ensure subscription row exists
            self.subscriptions.update_one(
                {'user_id': user_id},
                {'$setOnInsert': {
                    'user_id':    user_id,
                    'plan_id':    'free',
                    'started_at': now,
                    'expires_at': None,
                    'granted_by': None,
                }},
                upsert=True
            )
        except Exception as e:
            logger.error(f"Error adding user {user_id}: {e}")

    def ban_user(self, user_id: int) -> bool:
        try:
            res = self.users.update_one(
                {'user_id': user_id}, {'$set': {'is_banned': True}}
            )
            return res.matched_count > 0
        except Exception as e:
            logger.error(f"Error banning user {user_id}: {e}")
            return False

    def unban_user(self, user_id: int) -> bool:
        try:
            res = self.users.update_one(
                {'user_id': user_id}, {'$set': {'is_banned': False}}
            )
            return res.matched_count > 0
        except Exception as e:
            logger.error(f"Error unbanning user {user_id}: {e}")
            return False

    def is_user_banned(self, user_id: int) -> bool:
        try:
            doc = self.users.find_one({'user_id': user_id}, {'is_banned': 1})
            return bool(doc.get('is_banned', False)) if doc else False
        except Exception as e:
            logger.error(f"Error checking ban for {user_id}: {e}")
            return False

    def is_admin(self, user_id: int) -> bool:
        try:
            doc = self.users.find_one({'user_id': user_id}, {'is_admin': 1})
            return bool(doc.get('is_admin', False)) if doc else False
        except Exception as e:
            logger.error(f"Error checking admin for {user_id}: {e}")
            return False

    def set_admin(self, user_id: int, is_admin: bool = True) -> bool:
        try:
            res = self.users.update_one(
                {'user_id': user_id}, {'$set': {'is_admin': is_admin}}
            )
            return res.matched_count > 0
        except Exception as e:
            logger.error(f"Error setting admin for {user_id}: {e}")
            return False

    # ------------------------------------------------------------------ #
    # Subscription / Plan system
    # ------------------------------------------------------------------ #

    def get_user_plan(self, user_id: int) -> str:
        """
        Return the user's active plan_id ('free' or 'pro').
        Auto-downgrades expired Pro subscriptions.
        """
        try:
            doc = self.subscriptions.find_one({'user_id': user_id})
            if not doc:
                return 'free'

            plan_id    = doc.get('plan_id', 'free')
            expires_at = doc.get('expires_at')

            if plan_id != 'free' and expires_at is not None:
                if datetime.utcnow() > expires_at:
                    self.subscriptions.update_one(
                        {'user_id': user_id},
                        {'$set': {'plan_id': 'free', 'expires_at': None}}
                    )
                    logger.info(f"User {user_id} Pro expired → Free")
                    return 'free'

            return plan_id
        except Exception as e:
            logger.error(f"Error getting plan for {user_id}: {e}")
            return 'free'

    def get_subscription_info(self, user_id: int) -> dict:
        try:
            doc = self.subscriptions.find_one({'user_id': user_id})
            if not doc:
                return {'plan_id': 'free', 'started_at': None,
                        'expires_at': None, 'granted_by': None}
            return {
                'plan_id':    doc.get('plan_id', 'free'),
                'started_at': doc.get('started_at'),
                'expires_at': doc.get('expires_at'),
                'granted_by': doc.get('granted_by'),
            }
        except Exception as e:
            logger.error(f"Error getting subscription info for {user_id}: {e}")
            return {'plan_id': 'free'}

    def set_user_plan(
        self,
        user_id: int,
        plan_id: str,
        expires_at: datetime | None = None,
        granted_by: int | None = None,
    ) -> bool:
        try:
            self.subscriptions.update_one(
                {'user_id': user_id},
                {'$set': {
                    'plan_id':    plan_id,
                    'started_at': datetime.utcnow(),
                    'expires_at': expires_at,
                    'granted_by': granted_by,
                }},
                upsert=True
            )
            logger.info(f"Plan '{plan_id}' set for user {user_id} (expires: {expires_at})")
            return True
        except Exception as e:
            logger.error(f"Error setting plan for {user_id}: {e}")
            return False

    # ------------------------------------------------------------------ #
    # Daily usage / rate-limiting
    # ------------------------------------------------------------------ #

    def get_today_usage(self, user_id: int) -> int:
        try:
            today = datetime.utcnow().strftime('%Y-%m-%d')
            doc   = self.daily_usage.find_one(
                {'user_id': user_id, 'usage_date': today}
            )
            return doc.get('count', 0) if doc else 0
        except Exception as e:
            logger.error(f"Error getting usage for {user_id}: {e}")
            return 0

    def increment_today_usage(self, user_id: int, amount: int = 1):
        try:
            today = datetime.utcnow().strftime('%Y-%m-%d')
            self.daily_usage.update_one(
                {'user_id': user_id, 'usage_date': today},
                {'$inc': {'count': amount}},
                upsert=True
            )
        except Exception as e:
            logger.error(f"Error incrementing usage for {user_id}: {e}")

    def check_daily_limit(self, user_id: int, daily_limit: int) -> tuple[bool, int, int]:
        """
        Returns (allowed, used_today, remaining).
        daily_limit = -1 means unlimited.
        """
        if daily_limit == -1:
            used = self.get_today_usage(user_id)
            return True, used, -1
        used      = self.get_today_usage(user_id)
        remaining = max(0, daily_limit - used)
        return remaining > 0, used, remaining

    # ------------------------------------------------------------------ #
    # Payments (Telegram Stars)
    # ------------------------------------------------------------------ #

    def log_payment(
        self,
        user_id: int,
        telegram_charge_id: str,
        stars_amount: int,
        plan_id: str,
        status: str = 'completed',
    ) -> str | None:
        try:
            doc = {
                'user_id':            user_id,
                'telegram_charge_id': telegram_charge_id,
                'stars_amount':       stars_amount,
                'plan_id':            plan_id,
                'status':             status,
                'created_at':         datetime.utcnow(),
            }
            result = self.payments.insert_one(doc)
            return str(result.inserted_id)
        except DuplicateKeyError:
            logger.warning(f"Duplicate payment charge_id: {telegram_charge_id}")
            return None
        except Exception as e:
            logger.error(f"Error logging payment for {user_id}: {e}")
            return None

    def get_payment_history(self, user_id: int, limit: int = 10) -> list[dict]:
        try:
            cursor = self.payments.find(
                {'user_id': user_id},
                {'_id': 0}
            ).sort('created_at', DESCENDING).limit(limit)
            return list(cursor)
        except Exception as e:
            logger.error(f"Error getting payment history for {user_id}: {e}")
            return []

    # ------------------------------------------------------------------ #
    # Conversions
    # ------------------------------------------------------------------ #

    def add_conversion(
        self,
        user_id,
        file_name,
        file_size,
        success=True,
        file_type: str = 'svg',
    ):
        try:
            self.conversions.insert_one({
                'user_id':         user_id,
                'file_name':       file_name,
                'file_size':       file_size,
                'file_type':       file_type,
                'success':         success,
                'conversion_date': datetime.utcnow(),
            })
        except Exception as e:
            logger.error(f"Error logging conversion for {user_id}: {e}")

    def get_user_conversion_history(self, user_id: int, limit: int = 10) -> list[dict]:
        try:
            cursor = self.conversions.find(
                {'user_id': user_id},
                {'_id': 0}
            ).sort('conversion_date', DESCENDING).limit(limit)
            return list(cursor)
        except Exception as e:
            logger.error(f"Error getting history for {user_id}: {e}")
            return []

    # ------------------------------------------------------------------ #
    # Statistics
    # ------------------------------------------------------------------ #

    def get_stats(self) -> dict:
        try:
            total_users   = self.users.count_documents({})
            active_cutoff = datetime.utcnow() - timedelta(days=7)
            active_users  = self.users.count_documents(
                {'last_active': {'$gte': active_cutoff}}
            )
            banned_users       = self.users.count_documents({'is_banned': True})
            pro_users          = self.subscriptions.count_documents({'plan_id': 'pro'})
            total_conversions  = self.conversions.count_documents({})
            success_conversions = self.conversions.count_documents({'success': True})

            stars_agg = list(self.payments.aggregate([
                {'$match': {'status': 'completed'}},
                {'$group': {'_id': None, 'total': {'$sum': '$stars_amount'}}}
            ]))
            total_stars = stars_agg[0]['total'] if stars_agg else 0

            return {
                'total_users':          total_users,
                'active_users':         active_users,
                'banned_users':         banned_users,
                'pro_users':            pro_users,
                'total_conversions':    total_conversions,
                'success_conversions':  success_conversions,
                'total_stars_earned':   total_stars,
                'success_rate': round(
                    (success_conversions / total_conversions * 100)
                    if total_conversions > 0 else 0, 2
                ),
            }
        except Exception as e:
            logger.error(f"Error getting stats: {e}")
            return {}

    def get_all_users(self) -> list[int]:
        try:
            cursor = self.users.find({'is_banned': False}, {'user_id': 1, '_id': 0})
            return [doc['user_id'] for doc in cursor]
        except Exception as e:
            logger.error(f"Error getting all users: {e}")
            return []

    # ------------------------------------------------------------------ #
    # Broadcasts
    # ------------------------------------------------------------------ #

    def log_broadcast(
        self,
        admin_id: int,
        message_text: str,
        media_file_id: str | None = None,
        media_type: str | None = None,
    ) -> str | None:
        try:
            result = self.broadcasts.insert_one({
                'admin_id':      admin_id,
                'message_text':  message_text,
                'media_type':    media_type,
                'media_file_id': media_file_id,
                'sent_count':    0,
                'created_date':  datetime.utcnow(),
            })
            return str(result.inserted_id)
        except Exception as e:
            logger.error(f"Error logging broadcast: {e}")
            return None

    def update_broadcast_count(self, broadcast_id: str, sent_count: int):
        try:
            from bson import ObjectId
            self.broadcasts.update_one(
                {'_id': ObjectId(broadcast_id)},
                {'$set': {'sent_count': sent_count}}
            )
        except Exception as e:
            logger.error(f"Error updating broadcast count: {e}")
