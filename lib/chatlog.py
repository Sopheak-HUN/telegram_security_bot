"""Mirror group messages into Redis for the admin UI chat view.

The Bot API cannot read group history, so the bot records a compact copy of
every group message it receives into a capped Redis list per chat:

    ui:chat:log:{chat_id}  (newest first, trimmed to MAX_ENTRIES)

The admin UI writes its own broadcasts into the same list with dir="out",
so the panel's chat pane can interleave both directions.

Media messages carry the Telegram file_id in "media" plus a "kind", and the
admin UI fetches the bytes on demand through its own getFile proxy:

    kind: photo | sticker | sticker_video | gif | video | voice | audio | file
"""

import json
import time

from .whitelist import _get_redis

KEY_PREFIX = "ui:chat:log:"
MAX_ENTRIES = 200
MAX_TEXT = 1000


def _media_info(msg) -> tuple[str | None, str | None, str]:
    """(kind, file_id, fallback_text) for the message's media, if any."""
    sticker = getattr(msg, "sticker", None)
    if sticker is not None:
        fallback = f"[sticker] {sticker.emoji or ''}".strip()
        if sticker.is_video:
            return "sticker_video", sticker.file_id, fallback
        if sticker.is_animated:
            # .tgs is Lottie JSON — browsers can't show it; use the thumbnail
            thumb = getattr(sticker, "thumbnail", None) or getattr(sticker, "thumb", None)
            return ("sticker", thumb.file_id, fallback) if thumb else (None, None, fallback)
        return "sticker", sticker.file_id, fallback
    if getattr(msg, "animation", None) is not None:  # before document: gifs set both
        return "gif", msg.animation.file_id, "[gif]"
    if getattr(msg, "photo", None):
        return "photo", msg.photo[-1].file_id, "[photo]"
    if getattr(msg, "video", None) is not None:
        return "video", msg.video.file_id, "[video]"
    if getattr(msg, "video_note", None) is not None:
        return "video", msg.video_note.file_id, "[video note]"
    if getattr(msg, "voice", None) is not None:
        return "voice", msg.voice.file_id, "[voice message]"
    if getattr(msg, "audio", None) is not None:
        return "audio", msg.audio.file_id, "[audio]"
    doc = getattr(msg, "document", None)
    if doc is not None:
        return "file", doc.file_id, f"[file] {doc.file_name or ''}".strip()
    return None, None, ""


def _sender_name(user) -> str:
    if user and user.username:
        return f"@{user.username}"
    if user and user.first_name:
        return user.first_name
    return "user"


def _reply_info(msg) -> dict | None:
    """Compact context of the message this one replies to, if any."""
    r = getattr(msg, "reply_to_message", None)
    # in forum topics every message "replies" to the topic service message
    if r is None or getattr(r, "forum_topic_created", None) is not None:
        return None
    preview = r.text or r.caption or _media_info(r)[2] or ""
    return {
        "id": r.message_id,
        "from": _sender_name(r.from_user),
        "text": preview[:80],
    }


async def log_message(msg, direction: str = "in") -> None:
    kind, file_id, fallback = _media_info(msg)
    text = (msg.text or msg.caption or "")[:MAX_TEXT]
    if not text and kind is None:
        if not fallback:
            return  # nothing we can show (service message etc.)
        text = fallback

    user = msg.from_user
    record = {
        "id": msg.message_id,
        "dir": direction,
        "from": _sender_name(user),
        "uid": user.id if user else None,
        "text": text,
        "at": int(msg.date.timestamp()) if msg.date else int(time.time()),
    }
    reply = _reply_info(msg)
    if reply:
        record["reply"] = reply
    if kind and file_id:
        record["kind"] = kind
        record["media"] = file_id
        if kind == "file":
            record["name"] = (msg.document.file_name or "file")[:120]

    redis = _get_redis()
    key = f"{KEY_PREFIX}{msg.chat.id}"
    await redis.lpush(key, json.dumps(record))
    await redis.ltrim(key, 0, MAX_ENTRIES - 1)
