import os
import re
import time
from urllib.parse import urlparse

from telegram import Bot, Update
from telegram.error import TelegramError

from .whitelist import add_domain, check_hosts, list_domains, remove_domain

URL_REGEX = re.compile(
    r"\b((?:https?://)?(?:[a-z0-9-]+\.)+[a-z]{2,}(?:[/?#][^\s]*)?)",
    re.IGNORECASE,
)


def get_bot() -> Bot:
    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN is not set.")
    return Bot(token=token)


_HOSTNAME_RE = re.compile(
    r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$"
)


def to_hostname(raw: str | None) -> str | None:
    if not raw:
        return None
    s = str(raw).strip()
    if not re.match(r"^https?://", s, re.IGNORECASE):
        s = "http://" + s
    try:
        host = urlparse(s).hostname
    except Exception:
        return None
    if not host:
        return None
    host = host.lower()
    if not _HOSTNAME_RE.match(host):
        return None
    return host


def extract_hostnames(msg) -> list[str]:
    hosts: set[str] = set()
    text = msg.text or msg.caption or ""
    entities = msg.entities or msg.caption_entities or []

    for ent in entities:
        if ent.type == "url":
            slice_ = text[ent.offset : ent.offset + ent.length]
            host = to_hostname(slice_)
            if host:
                hosts.add(host)
        elif ent.type == "text_link" and ent.url:
            host = to_hostname(ent.url)
            if host:
                hosts.add(host)
        elif ent.type == "mention":
            hosts.add("t.me")

    if text:
        for m in URL_REGEX.findall(text):
            host = to_hostname(m)
            if host:
                hosts.add(host)

    return list(hosts)


_admin_cache: dict[int, tuple[set[int], float]] = {}


async def is_admin(bot: Bot, chat_id: int, user_id: int) -> bool:
    now = time.time()
    entry = _admin_cache.get(chat_id)
    if entry is None or entry[1] < now:
        try:
            admins = await bot.get_chat_administrators(chat_id)
            ids = {a.user.id for a in admins}
            _admin_cache[chat_id] = (ids, now + 60.0)
            entry = _admin_cache[chat_id]
        except TelegramError as err:
            print(f"get_chat_administrators failed: {err}")
            return False
    return user_id in entry[0]


def _cmd_arg(text: str) -> str:
    parts = text.split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ""


async def _handle_command(bot: Bot, msg, text: str) -> None:
    cmd = text.split()[0].lstrip("/").split("@", 1)[0].lower()

    if cmd == "start":
        await bot.send_message(
            chat_id=msg.chat.id,
            text="Link-guard bot is active. Add me as admin with delete-messages permission.",
        )
        return

    if msg.chat.type == "private":
        await bot.send_message(chat_id=msg.chat.id, text="Run this inside a group.")
        return

    if not msg.from_user:
        return
    if not await is_admin(bot, msg.chat.id, msg.from_user.id):
        return  # silently ignore non-admins

    arg = _cmd_arg(text)

    if cmd == "listlinks":
        domains = await list_domains()
        if not domains:
            await bot.send_message(
                chat_id=msg.chat.id,
                text="Whitelist is empty. All links will be removed.",
            )
            return
        body = "\n".join(f"• {d}" for d in domains)
        await bot.send_message(
            chat_id=msg.chat.id, text=f"Approved domains ({len(domains)}):\n{body}"
        )

    elif cmd == "addlink":
        if not arg:
            await bot.send_message(
                chat_id=msg.chat.id,
                text="Usage: /addlink <domain>  (e.g. /addlink youtube.com)",
            )
            return
        host = to_hostname(arg)
        if not host:
            await bot.send_message(
                chat_id=msg.chat.id, text=f'Could not parse "{arg}" as a domain.'
            )
            return
        added = await add_domain(host)
        await bot.send_message(
            chat_id=msg.chat.id,
            text=f"Added to whitelist: {host}" if added else f"Already approved: {host}",
        )

    elif cmd == "removelink":
        if not arg:
            await bot.send_message(chat_id=msg.chat.id, text="Usage: /removelink <domain>")
            return
        host = to_hostname(arg)
        if not host:
            await bot.send_message(
                chat_id=msg.chat.id, text=f'Could not parse "{arg}" as a domain.'
            )
            return
        removed = await remove_domain(host)
        await bot.send_message(
            chat_id=msg.chat.id,
            text=f"Removed from whitelist: {host}" if removed else f"Not in whitelist: {host}",
        )


async def _handle_message(bot: Bot, msg) -> None:
    if msg.chat.type not in ("group", "supergroup"):
        return
    if not msg.from_user:
        return
    if await is_admin(bot, msg.chat.id, msg.from_user.id):
        return

    hosts = extract_hostnames(msg)
    if not hosts:
        return

    approved = await check_hosts(hosts)
    offending = [h for h, ok in zip(hosts, approved) if not ok]
    if not offending:
        return

    user = msg.from_user
    name = f"@{user.username}" if user.username else (user.first_name or "user")

    try:
        await bot.delete_message(chat_id=msg.chat.id, message_id=msg.message_id)
    except TelegramError as err:
        print(f"[guard] could not delete msg {msg.message_id}: {err}")

    try:
        await bot.send_message(
            chat_id=msg.chat.id,
            text=f"{name}, your message was removed — link(s) not approved: {', '.join(offending)}",
        )
    except TelegramError as err:
        print(f"[guard] could not send warning: {err}")

    print(
        f"[guard] deleted msg from {name} (id={user.id}) in chat {msg.chat.id} — "
        f"bad hosts: {', '.join(offending)}"
    )


async def dispatch_update(update_dict: dict) -> None:
    bot = get_bot()
    async with bot:
        update = Update.de_json(update_dict, bot)
        if update is None:
            return
        msg = update.message or update.edited_message
        if msg is None:
            return

        text = msg.text or msg.caption or ""
        if text.startswith("/"):
            await _handle_command(bot, msg, text)
        else:
            await _handle_message(bot, msg)
