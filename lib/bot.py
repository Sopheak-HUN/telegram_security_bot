import os
import re
import time
from urllib.parse import urlparse

from telegram import Bot, ReplyParameters, Update
from telegram.error import TelegramError

from .spam import SPAM_LIMIT, SPAM_WINDOW_SECONDS, register_message
from .ai import is_spam
from .whitelist import add_domain, check_hosts, list_domains, remove_domain

URL_REGEX = re.compile(
    r"\b((?:https?://)?(?:[a-z0-9-]+\.)+[a-z]{2,}(?:[/?#][^\s]*)?)",
    re.IGNORECASE,
)

_HOSTNAME_RE = re.compile(
    r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$"
)

# File extensions that can execute code or scripts when opened — any document
# whose name ends in one of these is deleted on sight.
BLOCKED_EXTENSIONS = {
    # Windows executables / installers
    "exe", "msi", "msp", "com", "scr", "pif", "cpl", "dll", "msc", "rtf","z"
    # Windows scripts, script hosts & shortcuts
    "bat", "cmd", "vbs", "vbe", "js", "jse", "wsf", "wsh", "hta",
    "ps1", "psm1", "psd1", "reg", "lnk",
    # Unix / macOS executables & shell scripts
    "sh", "bash", "zsh", "csh", "run", "bin", "command", "app", "dmg",
    "deb", "rpm", "appimage",
    # Interpreted languages & bytecode
    "py", "pyw", "pyc", "pl", "rb", "php", "jar",
    # Mobile packages
    "apk", "xapk", "ipa",
}


def get_bot() -> Bot:
    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN is not set.")
    return Bot(token=token)


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

    if text:
        for m in URL_REGEX.findall(text):
            host = to_hostname(m)
            if host:
                hosts.add(host)

    return list(hosts)


def blocked_extension_for_name(file_name: str | None) -> str | None:
    """Return the blocked extension of a file name, or None."""
    if not file_name:
        return None
    # normalize: lowercase, drop trailing dots/spaces ("evil.EXE." -> "evil.exe")
    name = file_name.lower().strip().rstrip(". ")
    if "." not in name:
        return None
    ext = name.rsplit(".", 1)[1].strip()
    return ext if ext in BLOCKED_EXTENSIONS else None


def blocked_extension(msg) -> str | None:
    """Return the blocked extension of an attached document, or None."""
    doc = getattr(msg, "document", None)
    if doc is None:
        return None
    return blocked_extension_for_name(doc.file_name)


_bot_username: str | None = None


async def get_bot_username(bot: Bot) -> str | None:
    global _bot_username
    if _bot_username is None:
        try:
            me = await bot.get_me()
            _bot_username = (me.username or "").lower()
        except TelegramError as err:
            print(f"get_me failed: {err}")
            return None
    return _bot_username or None


async def _mentions_bot(bot: Bot, msg) -> bool:
    text = msg.text or msg.caption or ""
    entities = msg.entities or msg.caption_entities or []
    for ent in entities:
        if ent.type == "mention":
            handle = text[ent.offset + 1 : ent.offset + ent.length].lower()
            username = await get_bot_username(bot)
            if username and handle == username:
                return True
        elif ent.type == "text_mention" and ent.user and ent.user.id == bot.id:
            return True
    return False


def _display_name(user) -> str:
    if user and user.username:
        return f"@{user.username}"
    if user and user.first_name:
        return user.first_name
    return "user"


async def _handle_delete_request(bot: Bot, msg) -> None:
    if not await is_admin(bot, msg.chat.id, msg.from_user.id):
        return  # silently ignore non-admins

    target = msg.reply_to_message
    # In forum topics every message "replies" to the topic service message;
    # only act on a real reply to a user's message.
    if target is None or target.forum_topic_created is not None:
        await bot.send_message(
            chat_id=msg.chat.id,
            text="Reply to the message you want removed, mention me and include !delete.",
        )
        return

    name = _display_name(target.from_user)

    try:
        await bot.delete_message(chat_id=msg.chat.id, message_id=target.message_id)
    except TelegramError as err:
        print(f"[mod] could not delete msg {target.message_id}: {err}")
        return  # nothing was deleted — skip the warning

    # clean up the "!delete" trigger message as well
    try:
        await bot.delete_message(chat_id=msg.chat.id, message_id=msg.message_id)
    except TelegramError as err:
        print(f"[mod] could not delete trigger msg {msg.message_id}: {err}")

    try:
        await bot.send_message(
            chat_id=msg.chat.id,
            text=f"⚠️ {name}, your message was removed by an admin.",
        )
    except TelegramError as err:
        print(f"[mod] could not send warning: {err}")

    print(
        f"[mod] admin {msg.from_user.id} removed msg {target.message_id} "
        f"from {name} in chat {msg.chat.id}"
    )


async def _handle_mention(bot: Bot, msg) -> None:
    if not msg.from_user:
        return
    if not await _mentions_bot(bot, msg):
        return

    text = msg.text or msg.caption or ""
    if "!delete" in text.lower():
        await _handle_delete_request(bot, msg)
        return

    name = _display_name(msg.from_user)
    try:
        await bot.send_message(
            chat_id=msg.chat.id,
            text=f"Hello {name} 👋",
            reply_parameters=ReplyParameters(message_id=msg.message_id),
        )
    except TelegramError as err:
        print(f"[greet] could not send greeting: {err}")


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


async def _warn_if_spamming(bot: Bot, msg) -> None:
    if msg.from_user.is_bot:
        return
    try:
        hit_limit = await register_message(msg.chat.id, msg.from_user.id)
    except Exception as err:  # Redis trouble must not break the link guard
        print(f"[spam] tracking failed: {err}")
        return
    if not hit_limit:
        return

    name = _display_name(msg.from_user)
    try:
        await bot.send_message(
            chat_id=msg.chat.id,
            text=(
                f"⚠️ {name}, please slow down — "
                f"{SPAM_LIMIT} messages in {SPAM_WINDOW_SECONDS}s looks like spam."
            ),
        )
    except TelegramError as err:
        print(f"[spam] could not send warning: {err}")
    print(f"[spam] warned {name} (id={msg.from_user.id}) in chat {msg.chat.id}")


async def _delete_and_warn(bot: Bot, msg, reason: str, log_detail: str) -> None:
    user = msg.from_user
    name = _display_name(user)

    try:
        await bot.delete_message(chat_id=msg.chat.id, message_id=msg.message_id)
    except TelegramError as err:
        print(f"[guard] could not delete msg {msg.message_id}: {err}")

    try:
        await bot.send_message(
            chat_id=msg.chat.id,
            text=f"{name}, your message was removed — {reason}",
        )
    except TelegramError as err:
        print(f"[guard] could not send warning: {err}")

    print(
        f"[guard] deleted msg from {name} (id={user.id}) in chat {msg.chat.id} — "
        f"{log_detail}"
    )


async def _handle_message(bot: Bot, msg, is_edit: bool = False) -> None:
    if msg.chat.type not in ("group", "supergroup"):
        return
    if not msg.from_user:
        return

    if not is_edit:  # editing a message is not spamming
        await _warn_if_spamming(bot, msg)

    # NOTE: admin bypass removed — admins (including the group owner) are
    # filtered too. Re-add the lines below if you want admin messages to pass:
    #     if await is_admin(bot, msg.chat.id, msg.from_user.id):
    #         return

    hosts = extract_hostnames(msg)
    if not hosts:
        text = msg.text or msg.caption or ""
        if await is_spam(text):
            await _delete_and_warn(
                bot,
                msg,
                reason="message flagged as spam.",
                log_detail=f"AI spam verdict (preview: {text[:60]!r})",
            )
            return
        await _handle_mention(bot, msg)
        return

    approved = await check_hosts(hosts)
    offending = [h for h, ok in zip(hosts, approved) if not ok]
    if not offending:
        await _handle_mention(bot, msg)
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
            text=f"{name}, your message was removed — link not approved in this group.",
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

        # File guard runs first — before command routing — so an executable
        # with a "/command" caption can't slip past. Applies to everyone,
        # admins included (same policy as the link guard).
        if msg.chat.type in ("group", "supergroup") and msg.from_user:
            ext = blocked_extension(msg)
            if ext is not None:
                await _delete_and_warn(
                    bot,
                    msg,
                    reason=f".{ext} files are not allowed in this group.",
                    log_detail=f"blocked executable file {msg.document.file_name!r}",
                )
                return

        text = msg.text or msg.caption or ""
        if text.startswith("/"):
            await _handle_command(bot, msg, text)
        else:
            await _handle_message(bot, msg, is_edit=update.message is None)
