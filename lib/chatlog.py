"""Mirror group messages into Redis for the admin UI chat view.

The Bot API cannot read group history, so the bot records a compact copy of
every group message it receives into a capped Redis list per chat:

    ui:chat:log:{chat_id}  (newest first, trimmed to MAX_ENTRIES)

The admin UI writes its own broadcasts into the same list with dir="out",
so the panel's chat pane can interleave both directions.
"""

import json
import time

from .whitelist import _get_redis

KEY_PREFIX = "ui:chat:log:"
MAX_ENTRIES = 200
MAX_TEXT = 1000


def _preview(msg) -> str | None:
    """Text of the message, or a short placeholder for media."""
    text = msg.text or msg.caption
    if text:
        return text[:MAX_TEXT]
    if getattr(msg, "sticker", None) is not None:
        emoji = msg.sticker.emoji or ""
        return f"[sticker] {emoji}".strip()
    if getattr(msg, "animation", None) is not None:  # before document: gifs set both
        return "[gif]"
    if getattr(msg, "document", None) is not None:
        return f"[file] {msg.document.file_name or ''}".strip()
    if getattr(msg, "photo", None):
        return "[photo]"
    if getattr(msg, "video", None) is not None:
        return "[video]"
    if getattr(msg, "voice", None) is not None:
        return "[voice message]"
    if getattr(msg, "audio", None) is not None:
        return "[audio]"
    return None


def _sender_name(user) -> str:
    if user and user.username:
        return f"@{user.username}"
    if user and user.first_name:
        return user.first_name
    return "user"


async def log_message(msg) -> None:
    preview = _preview(msg)
    if preview is None:
        return
    user = msg.from_user
    record = {
        "id": msg.message_id,
        "dir": "in",
        "from": _sender_name(user),
        "uid": user.id if user else None,
        "text": preview,
        "at": int(msg.date.timestamp()) if msg.date else int(time.time()),
    }
    redis = _get_redis()
    key = f"{KEY_PREFIX}{msg.chat.id}"
    await redis.lpush(key, json.dumps(record))
    await redis.ltrim(key, 0, MAX_ENTRIES - 1)
