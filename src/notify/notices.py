"""One plain Telegram notice (risk-envelope plan, Task 1).

Used for a data-gated switch change and, later, the envelope's own alerts. Never raises: a
notice is information, not a dependency.
"""

from __future__ import annotations

import logging

from src.common.config import get_config
from src.notify.robust_bot import RobustBot as Bot
from src.notify.sender import thread_id

log = logging.getLogger(__name__)


async def send_notice(text: str, *, thread: str = "account") -> bool:
    """Post *text* as plain text to ``TELEGRAM_THREAD_<THREAD>``; False (logged) on any error."""
    try:
        secrets = get_config().secrets
        token = secrets.telegram_bot_token
        chat_id = secrets.telegram_chat_id
        if not token or not chat_id:
            log.warning("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set, notice not sent")
            return False
        thread_val = thread_id(getattr(secrets, f"telegram_thread_{thread}", ""))
        async with Bot(token=token) as bot:
            await bot.send_message(chat_id=chat_id, message_thread_id=thread_val, text=text)
        return True
    except Exception:
        log.warning("notice not sent", exc_info=True)
        return False
