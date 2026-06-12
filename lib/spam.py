import os

from .whitelist import _get_redis

SPAM_LIMIT = int(os.environ.get("SPAM_LIMIT", "5"))
SPAM_WINDOW_SECONDS = int(os.environ.get("SPAM_WINDOW_SECONDS", "10"))


async def register_message(chat_id: int, user_id: int) -> bool:
    """Count one message; return True when the user just hit the spam limit.

    Returns True only on the message that reaches SPAM_LIMIT, so the
    warning fires once per window instead of on every message after it.
    """
    redis = _get_redis()
    key = f"spam:{chat_id}:{user_id}"
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, SPAM_WINDOW_SECONDS)
    return count == SPAM_LIMIT
