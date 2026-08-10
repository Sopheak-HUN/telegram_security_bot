"""Track which groups the bot is in.

The Telegram Bot API has no "list my chats" method, so membership is recorded
from the updates the bot receives:

- ``my_chat_member`` events — fired when the bot is added, removed, promoted,
  or demoted in a chat (needs "my_chat_member" in allowed_updates).
- Every group message — backfills groups the bot joined before this tracking
  existed, and keeps titles fresh after renames.

Stored as a Redis hash under ``chats:known``: field = chat id, value = JSON
record {id, type, title, username, status, first_seen, last_seen}.
"""

import json
import time

from .whitelist import _get_redis

KEY = "chats:known"


def chat_record(chat, status: str | None = None, prev: dict | None = None) -> dict:
    """Build the JSON record for a chat, merging fields from a previous one."""
    prev = prev or {}
    now = int(time.time())
    return {
        "id": chat.id,
        "type": chat.type,
        "title": chat.title or chat.username or str(chat.id),
        "username": chat.username,
        # bot's own membership status — only my_chat_member events know it,
        # so keep the last known value when updating from a plain message
        "status": status or prev.get("status"),
        "first_seen": prev.get("first_seen") or now,
        "last_seen": now,
    }


async def upsert_chat(chat, status: str | None = None) -> None:
    redis = _get_redis()
    prev_raw = await redis.hget(KEY, str(chat.id))
    try:
        prev = json.loads(prev_raw) if prev_raw else None
    except (TypeError, ValueError):
        prev = None
    await redis.hset(KEY, str(chat.id), json.dumps(chat_record(chat, status, prev)))


async def remove_chat(chat_id: int) -> None:
    redis = _get_redis()
    await redis.hdel(KEY, str(chat_id))


async def list_chats() -> list[dict]:
    redis = _get_redis()
    raw = await redis.hgetall(KEY)
    chats: list[dict] = []
    for value in (raw or {}).values():
        try:
            chats.append(json.loads(value))
        except (TypeError, ValueError):
            continue
    chats.sort(key=lambda c: (c.get("title") or "").lower())
    return chats
