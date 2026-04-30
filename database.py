"""
Database module — user management, statistics, and subscription/plan system.
"""

import os
import logging
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime

logger = logging.getLogger(__name__)


class Database:
    def __init__(self):
        self.connection_string = os.environ.get('DATABASE_URL')
        if not self.connection_string:
            raise ValueError("DATABASE_URL environment variable not found")
        self.init_tables()

    def get_connection(self):
        return psycopg2.connect(self.connection_string)

    # ------------------------------------------------------------------ #
    # Schema
    # ------------------------------------------------------------------ #

    def init_tables(self):
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:

                    # ── users ──────────────────────────────────────────
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS users (
                            user_id     BIGINT PRIMARY KEY,
                            username    VARCHAR(255),
                            first_name  VARCHAR(255),
                            last_name   VARCHAR(255),
                            is_banned   BOOLEAN   DEFAULT FALSE,
                            is_admin    BOOLEAN   DEFAULT FALSE,
                            join_date   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    """)

                    # ── subscriptions ──────────────────────────────────
                    # plan_id : 'free' | 'pro'
                    # expires_at NULL  → plan never expires (admin grant or free)
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS subscriptions (
                            user_id    BIGINT PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
                            plan_id    VARCHAR(50)  NOT NULL DEFAULT 'free',
                            started_at TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
                            expires_at TIMESTAMP    DEFAULT NULL,
                            granted_by BIGINT       DEFAULT NULL
                        )
                    """)

                    # ── payments (Telegram Stars) ──────────────────────
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS payments (
                            id                 SERIAL PRIMARY KEY,
                            user_id            BIGINT REFERENCES users(user_id),
                            telegram_charge_id VARCHAR(255) UNIQUE,
                            stars_amount       INTEGER,
                            plan_id            VARCHAR(50),
                            status             VARCHAR(50) DEFAULT 'pending',
                            created_at         TIMESTAMP   DEFAULT CURRENT_TIMESTAMP
                        )
                    """)

                    # ── daily usage ───────────────────────────────────
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS daily_usage (
                            user_id    BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
                            usage_date DATE    NOT NULL DEFAULT CURRENT_DATE,
                            count      INTEGER NOT NULL DEFAULT 0,
                            PRIMARY KEY (user_id, usage_date)
                        )
                    """)

                    # ── conversions ───────────────────────────────────
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS conversions (
                            id              SERIAL PRIMARY KEY,
                            user_id         BIGINT REFERENCES users(user_id),
                            file_name       VARCHAR(255),
                            file_size       INTEGER,
                            file_type       VARCHAR(10) DEFAULT 'svg',
                            conversion_date TIMESTAMP   DEFAULT CURRENT_TIMESTAMP,
                            success         BOOLEAN     DEFAULT TRUE
                        )
                    """)

                    # ── broadcasts ────────────────────────────────────
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS broadcasts (
                            id            SERIAL PRIMARY KEY,
                            admin_id      BIGINT,
                            message_text  TEXT,
                            media_type    VARCHAR(50),
                            media_file_id VARCHAR(255),
                            sent_count    INTEGER   DEFAULT 0,
                            created_date  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    """)

                conn.commit()
            logger.info("Database tables initialised successfully")
        except Exception as e:
            logger.error(f"Error initialising database: {e}")
            raise

    # ------------------------------------------------------------------ #
    # User management
    # ------------------------------------------------------------------ #

    def add_user(self, user_id, username=None, first_name=None, last_name=None):
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO users (user_id, username, first_name, last_name, last_active)
                        VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
                        ON CONFLICT (user_id) DO UPDATE SET
                            username    = EXCLUDED.username,
                            first_name  = EXCLUDED.first_name,
                            last_name   = EXCLUDED.last_name,
                            last_active = CURRENT_TIMESTAMP
                    """, (user_id, username, first_name, last_name))

                    # Ensure a subscription row exists (default free)
                    cur.execute("""
                        INSERT INTO subscriptions (user_id, plan_id)
                        VALUES (%s, 'free')
                        ON CONFLICT (user_id) DO NOTHING
                    """, (user_id,))

                conn.commit()
        except Exception as e:
            logger.error(f"Error adding user {user_id}: {e}")

    def ban_user(self, user_id: int) -> bool:
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("UPDATE users SET is_banned = TRUE WHERE user_id = %s", (user_id,))
                    affected = cur.rowcount
                conn.commit()
            return affected > 0
        except Exception as e:
            logger.error(f"Error banning user {user_id}: {e}")
            return False

    def unban_user(self, user_id: int) -> bool:
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("UPDATE users SET is_banned = FALSE WHERE user_id = %s", (user_id,))
                    affected = cur.rowcount
                conn.commit()
            return affected > 0
        except Exception as e:
            logger.error(f"Error unbanning user {user_id}: {e}")
            return False

    def is_user_banned(self, user_id: int) -> bool:
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT is_banned FROM users WHERE user_id = %s", (user_id,))
                    row = cur.fetchone()
                    return bool(row[0]) if row else False
        except Exception as e:
            logger.error(f"Error checking ban for {user_id}: {e}")
            return False

    def is_admin(self, user_id: int) -> bool:
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT is_admin FROM users WHERE user_id = %s", (user_id,))
                    row = cur.fetchone()
                    return bool(row[0]) if row else False
        except Exception as e:
            logger.error(f"Error checking admin for {user_id}: {e}")
            return False

    def set_admin(self, user_id: int, is_admin: bool = True) -> bool:
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("UPDATE users SET is_admin = %s WHERE user_id = %s", (is_admin, user_id))
                    affected = cur.rowcount
                conn.commit()
            return affected > 0
        except Exception as e:
            logger.error(f"Error setting admin for {user_id}: {e}")
            return False

    # ------------------------------------------------------------------ #
    # Subscription / Plan system
    # ------------------------------------------------------------------ #

    def get_user_plan(self, user_id: int) -> str:
        """
        Return the user's active plan_id ('free' or 'pro').
        Auto-downgrades expired Pro subscriptions to 'free'.
        """
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT plan_id, expires_at FROM subscriptions WHERE user_id = %s",
                        (user_id,)
                    )
                    row = cur.fetchone()
                    if not row:
                        return 'free'

                    plan_id, expires_at = row

                    if plan_id != 'free' and expires_at is not None:
                        if datetime.utcnow() > expires_at:
                            cur.execute("""
                                UPDATE subscriptions
                                SET plan_id = 'free', expires_at = NULL
                                WHERE user_id = %s
                            """, (user_id,))
                            conn.commit()
                            logger.info(f"User {user_id} Pro expired → downgraded to Free")
                            return 'free'

                    return plan_id or 'free'
        except Exception as e:
            logger.error(f"Error getting plan for {user_id}: {e}")
            return 'free'

    def get_subscription_info(self, user_id: int) -> dict:
        """Full subscription row as a dict."""
        try:
            with self.get_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute("""
                        SELECT plan_id, started_at, expires_at, granted_by
                        FROM subscriptions WHERE user_id = %s
                    """, (user_id,))
                    row = cur.fetchone()
                    return dict(row) if row else {
                        'plan_id': 'free', 'started_at': None,
                        'expires_at': None, 'granted_by': None
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
        """
        Activate a plan for a user.
        expires_at=None → never expires (admin grant).
        """
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO subscriptions (user_id, plan_id, started_at, expires_at, granted_by)
                        VALUES (%s, %s, CURRENT_TIMESTAMP, %s, %s)
                        ON CONFLICT (user_id) DO UPDATE SET
                            plan_id    = EXCLUDED.plan_id,
                            started_at = CURRENT_TIMESTAMP,
                            expires_at = EXCLUDED.expires_at,
                            granted_by = EXCLUDED.granted_by
                    """, (user_id, plan_id, expires_at, granted_by))
                conn.commit()
            logger.info(f"Plan '{plan_id}' set for user {user_id} (expires: {expires_at})")
            return True
        except Exception as e:
            logger.error(f"Error setting plan for {user_id}: {e}")
            return False

    # ------------------------------------------------------------------ #
    # Daily usage / rate-limiting
    # ------------------------------------------------------------------ #

    def get_today_usage(self, user_id: int) -> int:
        """Successful conversions today."""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT count FROM daily_usage
                        WHERE user_id = %s AND usage_date = CURRENT_DATE
                    """, (user_id,))
                    row = cur.fetchone()
                    return row[0] if row else 0
        except Exception as e:
            logger.error(f"Error getting usage for {user_id}: {e}")
            return 0

    def increment_today_usage(self, user_id: int, amount: int = 1):
        """Upsert the daily usage counter."""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO daily_usage (user_id, usage_date, count)
                        VALUES (%s, CURRENT_DATE, %s)
                        ON CONFLICT (user_id, usage_date) DO UPDATE
                        SET count = daily_usage.count + EXCLUDED.count
                    """, (user_id, amount))
                conn.commit()
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
        used = self.get_today_usage(user_id)
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
    ) -> int | None:
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO payments
                            (user_id, telegram_charge_id, stars_amount, plan_id, status)
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (telegram_charge_id) DO NOTHING
                        RETURNING id
                    """, (user_id, telegram_charge_id, stars_amount, plan_id, status))
                    row = cur.fetchone()
                conn.commit()
            return row[0] if row else None
        except Exception as e:
            logger.error(f"Error logging payment for {user_id}: {e}")
            return None

    def get_payment_history(self, user_id: int, limit: int = 10) -> list[dict]:
        try:
            with self.get_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute("""
                        SELECT telegram_charge_id, stars_amount, plan_id, status, created_at
                        FROM payments WHERE user_id = %s
                        ORDER BY created_at DESC LIMIT %s
                    """, (user_id, limit))
                    return [dict(r) for r in cur.fetchall()]
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
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO conversions (user_id, file_name, file_size, success, file_type)
                        VALUES (%s, %s, %s, %s, %s)
                    """, (user_id, file_name, file_size, success, file_type))
                conn.commit()
        except Exception as e:
            logger.error(f"Error logging conversion for {user_id}: {e}")

    def get_user_conversion_history(self, user_id: int, limit: int = 10) -> list[dict]:
        try:
            with self.get_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute("""
                        SELECT file_name, file_size, file_type, success, conversion_date
                        FROM conversions WHERE user_id = %s
                        ORDER BY conversion_date DESC LIMIT %s
                    """, (user_id, limit))
                    return [dict(r) for r in cur.fetchall()]
        except Exception as e:
            logger.error(f"Error getting history for {user_id}: {e}")
            return []

    # ------------------------------------------------------------------ #
    # Statistics
    # ------------------------------------------------------------------ #

    def get_stats(self) -> dict:
        try:
            with self.get_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute("SELECT COUNT(*) AS v FROM users")
                    total_users = cur.fetchone()['v']

                    cur.execute("""
                        SELECT COUNT(*) AS v FROM users
                        WHERE last_active >= CURRENT_TIMESTAMP - INTERVAL '7 days'
                    """)
                    active_users = cur.fetchone()['v']

                    cur.execute("SELECT COUNT(*) AS v FROM conversions")
                    total_conversions = cur.fetchone()['v']

                    cur.execute("SELECT COUNT(*) AS v FROM conversions WHERE success = TRUE")
                    success_conversions = cur.fetchone()['v']

                    cur.execute("SELECT COUNT(*) AS v FROM users WHERE is_banned = TRUE")
                    banned_users = cur.fetchone()['v']

                    cur.execute("SELECT COUNT(*) AS v FROM subscriptions WHERE plan_id = 'pro'")
                    pro_users = cur.fetchone()['v']

                    cur.execute("""
                        SELECT COALESCE(SUM(stars_amount), 0) AS v
                        FROM payments WHERE status = 'completed'
                    """)
                    total_stars = cur.fetchone()['v']

            return {
                'total_users':         total_users,
                'active_users':        active_users,
                'total_conversions':   total_conversions,
                'success_conversions': success_conversions,
                'banned_users':        banned_users,
                'pro_users':           pro_users,
                'total_stars_earned':  total_stars,
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
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT user_id FROM users WHERE is_banned = FALSE")
                    return [row[0] for row in cur.fetchall()]
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
    ) -> int | None:
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO broadcasts (admin_id, message_text, media_type, media_file_id)
                        VALUES (%s, %s, %s, %s) RETURNING id
                    """, (admin_id, message_text, media_type, media_file_id))
                    row = cur.fetchone()
                conn.commit()
            return row[0] if row else None
        except Exception as e:
            logger.error(f"Error logging broadcast: {e}")
            return None

    def update_broadcast_count(self, broadcast_id: int, sent_count: int):
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE broadcasts SET sent_count = %s WHERE id = %s",
                        (sent_count, broadcast_id)
                    )
                conn.commit()
        except Exception as e:
            logger.error(f"Error updating broadcast count: {e}")
