"""
Configuration Module
Handles bot configuration including environment variables
"""

import os
import logging

logger = logging.getLogger(__name__)

class Config:
    def __init__(self):
        self.bot_token = self._get_bot_token()
        self.owner_id = self._get_owner_id()
        self.max_file_size = 10 * 1024 * 1024  # 10MB limit
        self.temp_dir = os.environ.get('TEMP_DIR', '/tmp')

        logger.info("Bot configuration loaded successfully")
        logger.info(f"Max file size: {self.max_file_size} bytes")
        logger.info(f"Temp directory: {self.temp_dir}")
        if self.owner_id:
            logger.info(f"Bot owner ID configured: {self.owner_id}")
        else:
            logger.warning("No owner ID configured. Admin features may not work properly.")

    def _get_bot_token(self) -> str:
        """
        Get Telegram bot token from environment variables

        Returns:
            str: Bot token

        Raises:
            ValueError: If bot token is not found
        """
        token_vars = ['BOT_TOKEN', 'TELEGRAM_BOT_TOKEN', 'TELEGRAM_TOKEN']

        for var_name in token_vars:
            token = os.environ.get(var_name)
            if token:
                logger.info(f"Bot token found in environment variable: {var_name}")
                return token

        raise ValueError(
            "Bot token not found! Please set BOT_TOKEN, TELEGRAM_BOT_TOKEN, or TELEGRAM_TOKEN environment variable."
        )

    def _get_owner_id(self) -> int | None:
        """
        Get bot owner Telegram user ID from environment variables

        Returns:
            int | None: Owner user ID or None if not configured
        """
        owner_vars = ['OWNER_ID', 'BOT_OWNER_ID', 'ADMIN_ID']

        for var_name in owner_vars:
            owner_id_str = os.environ.get(var_name)
            if owner_id_str:
                try:
                    owner_id = int(owner_id_str)
                    logger.info(f"Owner ID found in environment variable: {var_name}")
                    return owner_id
                except ValueError:
                    logger.warning(f"Invalid owner ID format in {var_name}: {owner_id_str}")
                    continue

        logger.warning("No owner ID configured. Set OWNER_ID environment variable.")
        return None

    def validate(self) -> tuple[bool, str]:
        """
        Validate configuration settings

        Returns:
            tuple[bool, str]: (is_valid, error_message)
        """
        try:
            if not self.bot_token or len(self.bot_token.split(':')) != 2:
                return False, "Invalid bot token format. Expected format: 'bot_id:bot_secret'"

            if not os.path.exists(self.temp_dir):
                try:
                    os.makedirs(self.temp_dir, exist_ok=True)
                except Exception as e:
                    return False, f"Cannot create temp directory {self.temp_dir}: {str(e)}"

            if not os.access(self.temp_dir, os.W_OK):
                return False, f"Temp directory {self.temp_dir} is not writable"

            if self.owner_id is None:
                logger.warning("Owner ID not configured. Some admin features may not work properly.")

            return True, "Configuration is valid"

        except Exception as e:
            return False, f"Configuration validation error: {str(e)}"
