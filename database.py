"""
Database module — MongoDB (pymongo) with certifi SSL fix.
Compatible with Python 3.11+ and MongoDB Atlas on Render.
"""

import os
import logging
import certifi
from datetime import datetime, timezone, timedelta

from pymongo import MongoClient, DESCENDING
from pymongo.errors import DuplicateKeyError
from bson import ObjectId

logger = logging.getLogger(__name__)


class Database:
    def __init__(self):
        uri = os.environ.get('DATABASE_URL')
        if not uri:
            raise ValueError("DATABASE_URL environment variable not found")

        # tlsCAFile=certifi.where() fixes SSL handshake errors on Render / Python 3.11+
        # tz_aware=True makes MongoDB return timezone-aware datetimes (UTC) so that
        # comparisons against datetime.now(timezone.utc) don't raise TypeError.
        self.client = MongoClient(
            uri,
            tlsCAFile=certifi.where(),
            tz_aware=True,
            serverSelectionTimeoutMS=30000,
            connectTimeoutMS=20000,
            socketTimeoutMS=20000,
        )

        db_name  = os.environ.get('MONGO_DB_NAME', 'svg_tgs_bot')
        self.db  = self.client[db_name]

        self.users            = self.db['users']
        self.subscriptions    = self.db['subscriptions']
        self.payments         = self.db['payments']
        self.daily_usage      = self.db['daily_usage']
        self.conversions      = self.db['conversions']
        self.broadcasts       = self.db['broadcasts']
        self.activation_keys  = self.db['activation_keys']
        self.plan_prices      = self.db['plan_prices']

        self._ensure_indexes()
        logger.info(f"MongoDB connected — db: {db_name}")

    def _ensure_indexes(self):
        try:
            self.users.create_index('user_id', unique=True)
            self.subscriptions.create_index('user_id', unique=True)
            self.payments.create_index('telegram_charge_id', unique=True, sparse=True)
            self.daily_usage.create_index(
                [('user_id', 1), ('usage_date', 1)], unique=True
            )
            self.conversions.create_index('user_id')
            self.conversions.create_index('conversion_date')
            self.activation_keys.create_index('key', unique=True)
            self.plan_prices.create_index('plan_id', unique=True)
        except Exception as e:
            logger.error(f"Index error: {e}")

    # ------------------------------------------------------------------ #
    # User management
    # ------------------------------------------------------------------ #

    def add_user(self, user_id, username=None, first_name=None, last_name=None):
        try:
            now = datetime.now(timezone.utc)
            self.users.update_one(
                {'user_id': user_id},
                {
                    '$set': {
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
                    }
                },
                upsert=True
            )
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
            res = self.users.update_one({'user_id': user_id}, {'$set': {'is_banned': True}})
            return res.matched_count > 0
        except Exception as e:
            logger.error(f"Error banning {user_id}: {e}")
            return False

    def unban_user(self, user_id: int) -> bool:
        try:
            res = self.users.update_one({'user_id': user_id}, {'$set': {'is_banned': False}})
            return res.matched_count > 0
        except Exception as e:
            logger.error(f"Error unbanning {user_id}: {e}")
            return False

    def is_user_banned(self, user_id: int) -> bool:
        try:
            doc = self.users.find_one({'user_id': user_id}, {'is_banned': 1})
            return bool(doc.get('is_banned', False)) if doc else False
        except Exception as e:
            logger.error(f"Error checking ban {user_id}: {e}")
            return False

    def is_admin(self, user_id: int) -> bool:
        try:
            doc = self.users.find_one({'user_id': user_id}, {'is_admin': 1})
            return bool(doc.get('is_admin', False)) if doc else False
        except Exception as e:
            logger.error(f"Error checking admin {user_id}: {e}")
            return False

    def set_admin(self, user_id: int, is_admin: bool = True) -> bool:
        try:
            res = self.users.update_one({'user_id': user_id}, {'$set': {'is_admin': is_admin}})
            return res.matched_count > 0
        except Exception as e:
            logger.error(f"Error setting admin {user_id}: {e}")
            return False

    # ------------------------------------------------------------------ #
    # Subscription / Plan
    # ------------------------------------------------------------------ #

    def get_user_plan(self, user_id: int) -> str:
        try:
            doc = self.subscriptions.find_one({'user_id': user_id})
            if not doc:
                return 'free'
            plan_id    = doc.get('plan_id', 'free')
            expires_at = doc.get('expires_at')

            # Defensive: ensure expires_at is timezone-aware before comparing.
            # Older docs written before tz_aware=True may have naive UTC datetimes.
            if expires_at is not None and expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)

            if plan_id != 'free' and expires_at and datetime.now(timezone.utc) > expires_at:
                self.subscriptions.update_one(
                    {'user_id': user_id},
                    {'$set': {'plan_id': 'free', 'expires_at': None}}
                )
                logger.info(f"User {user_id} Pro expired → Free")
                return 'free'
            return plan_id
        except Exception as e:
            logger.error(f"Error getting plan {user_id}: {e}")
            return 'free'

    def get_subscription_info(self, user_id: int) -> dict:
        try:
            doc = self.subscriptions.find_one({'user_id': user_id})
            if not doc:
                return {
                    'plan_id': 'free', 'started_at': None, 'expires_at': None,
                    'granted_by': None, 'grant_source': None,
                }
            return {
                'plan_id':      doc.get('plan_id', 'free'),
                'started_at':   doc.get('started_at'),
                'expires_at':   doc.get('expires_at'),
                'granted_by':   doc.get('granted_by'),
                'grant_source': doc.get('grant_source'),
            }
        except Exception as e:
            logger.error(f"Error getting subscription {user_id}: {e}")
            return {'plan_id': 'free'}

    def set_user_plan(self, user_id: int, plan_id: str,
                      expires_at: datetime | None = None,
                      granted_by: int | None = None,
                      grant_source: str | None = None) -> bool:
        """
        Set a user's plan.

        grant_source is a marker indicating HOW the plan was granted, used by the
        bulk admin commands (/giveplanall, /removeplanall) to avoid clobbering
        plans that came from other sources. Known values:
            'payment'      — purchased via Telegram Stars
            'giveplan'     — granted individually by an admin
            'giveplanall'  — granted via the bulk admin command
            'key'          — redeemed an activation key
            'admin_remove' — explicitly downgraded by an admin
            None           — unspecified / legacy
        """
        try:
            self.subscriptions.update_one(
                {'user_id': user_id},
                {'$set': {
                    'plan_id':      plan_id,
                    'started_at':   datetime.now(timezone.utc),
                    'expires_at':   expires_at,
                    'granted_by':   granted_by,
                    'grant_source': grant_source,
                }},
                upsert=True
            )
            return True
        except Exception as e:
            logger.error(f"Error setting plan {user_id}: {e}")
            return False

    # ------------------------------------------------------------------ #
    # Daily usage
    # ------------------------------------------------------------------ #

    def get_today_usage(self, user_id: int) -> int:
        try:
            today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
            doc   = self.daily_usage.find_one({'user_id': user_id, 'usage_date': today})
            return doc.get('count', 0) if doc else 0
        except Exception as e:
            logger.error(f"Error getting usage {user_id}: {e}")
            return 0

    def increment_today_usage(self, user_id: int, amount: int = 1):
        try:
            today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
            self.daily_usage.update_one(
                {'user_id': user_id, 'usage_date': today},
                {'$inc': {'count': amount}},
                upsert=True
            )
        except Exception as e:
            logger.error(f"Error incrementing usage {user_id}: {e}")

    def check_daily_limit(self, user_id: int, daily_limit: int) -> tuple[bool, int, int]:
        if daily_limit == -1:
            return True, self.get_today_usage(user_id), -1
        used      = self.get_today_usage(user_id)
        remaining = max(0, daily_limit - used)
        return remaining > 0, used, remaining

    # ------------------------------------------------------------------ #
    # Payments
    # ------------------------------------------------------------------ #

    def log_payment(self, user_id: int, telegram_charge_id: str,
                    stars_amount: int, plan_id: str,
                    status: str = 'completed') -> str | None:
        try:
            result = self.payments.insert_one({
                'user_id':            user_id,
                'telegram_charge_id': telegram_charge_id,
                'stars_amount':       stars_amount,
                'plan_id':            plan_id,
                'status':             status,
                'created_at':         datetime.now(timezone.utc),
            })
            return str(result.inserted_id)
        except DuplicateKeyError:
            return None
        except Exception as e:
            logger.error(f"Error logging payment {user_id}: {e}")
            return None

    def get_payment_history(self, user_id: int, limit: int = 10) -> list[dict]:
        try:
            return list(self.payments.find(
                {'user_id': user_id}, {'_id': 0}
            ).sort('created_at', DESCENDING).limit(limit))
        except Exception as e:
            logger.error(f"Error payment history {user_id}: {e}")
            return []

    # ------------------------------------------------------------------ #
    # Conversions
    # ------------------------------------------------------------------ #

    def add_conversion(self, user_id, file_name, file_size,
                       success=True, file_type: str = 'svg'):
        try:
            self.conversions.insert_one({
                'user_id':         user_id,
                'file_name':       file_name,
                'file_size':       file_size,
                'file_type':       file_type,
                'success':         success,
                'conversion_date': datetime.now(timezone.utc),
            })
        except Exception as e:
            logger.error(f"Error logging conversion {user_id}: {e}")

    def get_user_conversion_history(self, user_id: int, limit: int = 10) -> list[dict]:
        try:
            return list(self.conversions.find(
                {'user_id': user_id}, {'_id': 0}
            ).sort('conversion_date', DESCENDING).limit(limit))
        except Exception as e:
            logger.error(f"Error getting history {user_id}: {e}")
            return []

    # ------------------------------------------------------------------ #
    # Statistics
    # ------------------------------------------------------------------ #

    def get_stats(self) -> dict:
        try:
            active_cutoff      = datetime.now(timezone.utc) - timedelta(days=7)
            total_users        = self.users.count_documents({})
            active_users       = self.users.count_documents({'last_active': {'$gte': active_cutoff}})
            banned_users       = self.users.count_documents({'is_banned': True})
            admin_users        = self.users.count_documents({'is_admin': True})
            pro_users          = self.subscriptions.count_documents({'plan_id': 'pro'})
            total_conversions  = self.conversions.count_documents({})
            success_conversions = self.conversions.count_documents({'success': True})

            stars_agg   = list(self.payments.aggregate([
                {'$match': {'status': 'completed'}},
                {'$group': {'_id': None, 'total': {'$sum': '$stars_amount'}}}
            ]))
            total_stars = stars_agg[0]['total'] if stars_agg else 0

            pro_price = self.get_effective_price('pro', 150)

            return {
                'total_users':          total_users,
                'active_users':         active_users,
                'banned_users':         banned_users,
                'admin_users':          admin_users,
                'pro_users':            pro_users,
                'total_conversions':    total_conversions,
                'success_conversions':  success_conversions,
                'total_stars_earned':   total_stars,
                'pro_price':            pro_price,
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
            return [d['user_id'] for d in
                    self.users.find({'is_banned': False}, {'user_id': 1, '_id': 0})]
        except Exception as e:
            logger.error(f"Error getting all users: {e}")
            return []

    # ------------------------------------------------------------------ #
    # Broadcasts
    # ------------------------------------------------------------------ #

    def log_broadcast(self, admin_id: int, message_text: str,
                      media_file_id: str | None = None,
                      media_type: str | None = None) -> str | None:
        try:
            result = self.broadcasts.insert_one({
                'admin_id':      admin_id,
                'message_text':  message_text,
                'media_type':    media_type,
                'media_file_id': media_file_id,
                'sent_count':    0,
                'created_date':  datetime.now(timezone.utc),
            })
            return str(result.inserted_id)
        except Exception as e:
            logger.error(f"Error logging broadcast: {e}")
            return None

    def update_broadcast_count(self, broadcast_id: str, sent_count: int):
        try:
            self.broadcasts.update_one(
                {'_id': ObjectId(broadcast_id)},
                {'$set': {'sent_count': sent_count}}
            )
        except Exception as e:
            logger.error(f"Error updating broadcast count: {e}")

    # ------------------------------------------------------------------ #
    # Top Users
    # ------------------------------------------------------------------ #

    def get_top_users(self, limit: int = 10) -> list[dict]:
        """Return top users ranked by total successful conversions."""
        try:
            pipeline = [
                {'$match': {'success': True}},
                {'$group': {'_id': '$user_id', 'total': {'$sum': 1}}},
                {'$sort': {'total': -1}},
                {'$limit': limit},
            ]
            rows = list(self.conversions.aggregate(pipeline))
            result = []
            for row in rows:
                uid  = row['_id']
                user = self.users.find_one({'user_id': uid},
                                           {'username': 1, 'first_name': 1, '_id': 0})
                sub  = self.subscriptions.find_one({'user_id': uid}, {'plan_id': 1, '_id': 0})
                result.append({
                    'user_id':    uid,
                    'username':   (user or {}).get('username'),
                    'first_name': (user or {}).get('first_name', 'User'),
                    'plan_id':    (sub or {}).get('plan_id', 'free'),
                    'total':      row['total'],
                })
            return result
        except Exception as e:
            logger.error(f"Error getting top users: {e}")
            return []

    # ------------------------------------------------------------------ #
    # Give plan to ALL users
    # ------------------------------------------------------------------ #

    def get_paid_user_ids(self) -> set:
        """Return set of user_ids who have at least one completed Stars payment."""
        try:
            docs = self.payments.find({'status': 'completed'}, {'user_id': 1, '_id': 0})
            return {d['user_id'] for d in docs}
        except Exception as e:
            logger.error(f"Error getting paid user ids: {e}")
            return set()

    def get_users_without_paid_plan(self) -> list[int]:
        """Return non-banned user IDs who have never paid via Stars."""
        try:
            all_ids  = {d['user_id'] for d in
                        self.users.find({'is_banned': False}, {'user_id': 1, '_id': 0})}
            paid_ids = self.get_paid_user_ids()
            return list(all_ids - paid_ids)
        except Exception as e:
            logger.error(f"Error getting non-paid users: {e}")
            return []

    def _user_has_active_pro(self, uid: int, paid_ids: set) -> bool:
        """
        True if the user currently has an active Pro plan from ANY source —
        a Stars payment, an individual /giveplan grant, an activation key,
        or a previous /giveplanall that hasn't expired yet.
        """
        if uid in paid_ids:
            return True
        sub = self.subscriptions.find_one(
            {'user_id': uid},
            {'plan_id': 1, 'expires_at': 1, '_id': 0}
        )
        if not sub:
            return False
        if sub.get('plan_id') != 'pro':
            return False
        exp = sub.get('expires_at')
        if exp is None:
            return True  # permanent Pro
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) < exp

    def set_plan_all_users(self, plan_id: str,
                           expires_at, granted_by: int) -> tuple[int, int, list[int]]:
        """
        Bulk-grant a plan to every non-banned user who is currently on Free.

        Users are SKIPPED (left untouched) if they already have an active Pro
        plan from ANY source — Stars payments, /giveplan grants, redeemed keys,
        or previous /giveplanall grants that haven't expired. This ensures the
        bulk command never downgrades or reschedules an existing Pro plan.

        The new plan is tagged with grant_source='giveplanall' so that
        /removeplanall can later remove ONLY plans granted this way.

        Returns (count_updated, count_skipped, updated_user_ids).
        """
        try:
            user_ids = [d['user_id'] for d in
                        self.users.find({'is_banned': False}, {'user_id': 1, '_id': 0})]
            paid_ids = self.get_paid_user_ids()
            now = datetime.now(timezone.utc)
            updated_ids: list[int] = []
            skipped = 0
            for uid in user_ids:
                if self._user_has_active_pro(uid, paid_ids):
                    skipped += 1
                    continue
                self.subscriptions.update_one(
                    {'user_id': uid},
                    {'$set': {
                        'plan_id':      plan_id,
                        'started_at':   now,
                        'expires_at':   expires_at,
                        'granted_by':   granted_by,
                        'grant_source': 'giveplanall',
                    }},
                    upsert=True
                )
                updated_ids.append(uid)
            return len(updated_ids), skipped, updated_ids
        except Exception as e:
            logger.error(f"Error in set_plan_all_users: {e}")
            return 0, 0, []

    def remove_plan_all_users(self, granted_by: int) -> tuple[int, int, list[int]]:
        """
        Bulk-revert ONLY the plans that were granted via /giveplanall.

        Plans coming from any other source are left untouched:
          - Stars payments
          - Individual /giveplan grants
          - Redeemed activation keys
          - Anything with grant_source != 'giveplanall'

        Returns (count_updated, count_skipped, updated_user_ids).
        skipped = total non-banned users that were NOT downgraded.
        """
        try:
            total_users = self.users.count_documents({'is_banned': False})

            # Only target subscriptions explicitly tagged as bulk grants from
            # /giveplanall. As an extra safety net, also confirm the user is
            # not in the paid-users set before downgrading.
            paid_ids = self.get_paid_user_ids()
            target_docs = list(self.subscriptions.find(
                {'grant_source': 'giveplanall'},
                {'user_id': 1, '_id': 0}
            ))

            now = datetime.now(timezone.utc)
            updated_ids: list[int] = []
            for doc in target_docs:
                uid = doc['user_id']
                if uid in paid_ids:
                    # Defense in depth: never downgrade a paying customer,
                    # even if their record was somehow tagged as 'giveplanall'.
                    continue
                # Make sure this user still exists and is not banned.
                u = self.users.find_one(
                    {'user_id': uid, 'is_banned': False},
                    {'_id': 1}
                )
                if not u:
                    continue
                self.subscriptions.update_one(
                    {'user_id': uid},
                    {'$set': {
                        'plan_id':      'free',
                        'started_at':   now,
                        'expires_at':   None,
                        'granted_by':   granted_by,
                        'grant_source': 'admin_remove',
                    }}
                )
                updated_ids.append(uid)

            skipped = total_users - len(updated_ids)
            return len(updated_ids), skipped, updated_ids
        except Exception as e:
            logger.error(f"Error in remove_plan_all_users: {e}")
            return 0, 0, []

    # ------------------------------------------------------------------ #
    # Activation Keys
    # ------------------------------------------------------------------ #

    def create_activation_keys(self, keys: list, plan_id: str,
                               days: int, created_by: int,
                               max_uses: int = 1) -> int:
        """Bulk-insert activation keys. Returns count inserted."""
        from pymongo.errors import BulkWriteError
        now  = datetime.now(timezone.utc)
        docs = []
        for k in keys:
            docs.append({
                'key':        k,
                'plan_id':    plan_id,
                'days':       days,
                'max_uses':   max_uses,
                'uses':       0,
                'used_by':    [],
                'created_by': created_by,
                'created_at': now,
                'active':     True,
            })
        if not docs:
            return 0
        try:
            result = self.activation_keys.insert_many(docs, ordered=False)
            return len(result.inserted_ids)
        except BulkWriteError as bwe:
            # ordered=False: partial inserts succeed; count what actually went in
            inserted = bwe.details.get('nInserted', 0)
            logger.warning(f"Partial key insert: {inserted}/{len(docs)} inserted (duplicates skipped)")
            return inserted
        except Exception as e:
            logger.error(f"Error creating keys: {e}")
            return 0

    def redeem_key(self, key: str, user_id: int):
        """
        Redeem an activation key for a user.
        Returns (success, message, key_doc).
        """
        try:
            doc = self.activation_keys.find_one({'key': key})
            if not doc:
                return False, "❌ Key not found.", None
            if not doc.get('active', True):
                return False, "❌ This key has been deactivated.", None
            if user_id in (doc.get('used_by') or []):
                return False, "❌ You have already used this key.", None
            if doc['uses'] >= doc['max_uses']:
                return False, "❌ This key has already been fully used.", None

            expires_at = datetime.now(timezone.utc) + timedelta(days=doc['days'])
            self.set_user_plan(user_id, doc['plan_id'],
                               expires_at=expires_at, granted_by=None,
                               grant_source='key')

            self.activation_keys.update_one(
                {'key': key},
                {
                    '$inc': {'uses': 1},
                    '$push': {'used_by': user_id},
                    '$set': {'active': doc['uses'] + 1 < doc['max_uses']},
                }
            )
            return True, "✅ Key redeemed!", doc

        except Exception as e:
            logger.error(f"Error redeeming key {key}: {e}")
            return False, f"❌ Error: {e}", None

    def get_key_info(self, key: str):
        try:
            return self.activation_keys.find_one({'key': key}, {'_id': 0})
        except Exception as e:
            logger.error(f"Error getting key info: {e}")
            return None

    # ------------------------------------------------------------------ #
    # Dynamic Plan Pricing
    # ------------------------------------------------------------------ #

    def get_plan_price(self, plan_id: str):
        """Return override price in Stars, or None if no override set."""
        try:
            doc = self.plan_prices.find_one({'plan_id': plan_id})
            return doc['price_stars'] if doc else None
        except Exception as e:
            logger.error(f"Error getting plan price: {e}")
            return None

    def set_plan_price(self, plan_id: str, price_stars: int, set_by: int) -> bool:
        try:
            self.plan_prices.update_one(
                {'plan_id': plan_id},
                {'$set': {
                    'price_stars': price_stars,
                    'set_by':      set_by,
                    'updated_at':  datetime.now(timezone.utc),
                }},
                upsert=True
            )
            return True
        except Exception as e:
            logger.error(f"Error setting plan price: {e}")
            return False

    def get_effective_price(self, plan_id: str, default_price: int) -> int:
        """Return DB override price if set, else the default."""
        override = self.get_plan_price(plan_id)
        return override if override is not None else default_price
