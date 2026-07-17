"""One-shot sweep: delete OLD documents in a group whose file name has a
blocked executable/script extension (same BLOCKED_EXTENSIONS as the live bot).

Why this exists: the Telegram *Bot* API cannot read message history — the bot
only sees messages sent while it is registered. To clean up files sent before
the bot was active, this script logs in as YOUR OWN Telegram account (MTProto
via Telethon). You must be an admin with the delete-messages permission in the
target group.

Setup (one time):
    pip install telethon
    Get api_id + api_hash at https://my.telegram.org/apps
    Set them as env vars:  TG_API_ID  and  TG_API_HASH

Usage:
    python tools/cleanup_history.py --chat @mygroup --dry-run   # preview only
    python tools/cleanup_history.py --chat @mygroup             # really delete
    python tools/cleanup_history.py --chat -1001234567890       # by chat id

First run asks for your phone number + login code, then stores a local
session file (cleanup-session.session — DO NOT commit it; it grants access
to your account).
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# lib.bot needs BOT_TOKEN only when the bot object is built — stub it so the
# import succeeds (same trick as tests/smoke.py).
os.environ.setdefault("BOT_TOKEN", "unused-for-cleanup")

from lib.bot import BLOCKED_EXTENSIONS, blocked_extension_for_name  # noqa: E402

try:
    from telethon import TelegramClient
except ImportError:
    sys.exit("Telethon is not installed. Run:  pip install telethon")

DELETE_BATCH = 100  # Telegram's max message ids per delete call


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument(
        "--chat",
        required=True,
        help="Target group: @username, invite title, or numeric chat id (e.g. -100123...).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Only list matching files; delete nothing.",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Scan at most this many recent messages (default: entire history).",
    )
    return p.parse_args()


async def run(args: argparse.Namespace) -> None:
    api_id = os.environ.get("TG_API_ID")
    api_hash = os.environ.get("TG_API_HASH")
    if not api_id or not api_hash:
        sys.exit(
            "Set TG_API_ID and TG_API_HASH first (create them at "
            "https://my.telegram.org/apps)."
        )

    chat: int | str = args.chat
    if isinstance(chat, str) and chat.lstrip("-").isdigit():
        chat = int(chat)

    # flood_sleep_threshold: auto-sleep on rate limits instead of crashing
    client = TelegramClient(
        str(Path(__file__).parent / "cleanup-session"),
        int(api_id),
        api_hash,
        flood_sleep_threshold=120,
    )

    async with client:
        entity = await client.get_entity(chat)
        title = getattr(entity, "title", None) or str(chat)
        mode = "DRY RUN — nothing will be deleted" if args.dry_run else "deleting"
        print(f"Scanning history of {title!r} ({mode}) ...")
        print(f"Blocked extensions: {', '.join(sorted(BLOCKED_EXTENSIONS))}\n")

        scanned = 0
        matched = 0
        deleted = 0
        pending: list[int] = []

        async def flush() -> None:
            nonlocal deleted, pending
            if not pending:
                return
            # revoke=True -> delete for everyone, not just this account
            await client.delete_messages(entity, pending, revoke=True)
            deleted += len(pending)
            print(f"  ... deleted batch of {len(pending)} (total {deleted})")
            pending = []

        async for message in client.iter_messages(entity, limit=args.limit):
            scanned += 1
            if scanned % 1000 == 0:
                print(f"  ... scanned {scanned} messages")

            if message.document is None:
                continue
            name = message.file.name if message.file else None
            ext = blocked_extension_for_name(name)
            if ext is None:
                continue

            matched += 1
            sender = message.sender_id if message.sender_id else "?"
            when = message.date.strftime("%Y-%m-%d %H:%M") if message.date else "?"
            print(f"[match] msg {message.id} | {when} | sender {sender} | {name} (.{ext})")

            if not args.dry_run:
                pending.append(message.id)
                if len(pending) >= DELETE_BATCH:
                    await flush()

        await flush()

        print(f"\nDone. Scanned {scanned} messages, matched {matched}, deleted {deleted}.")
        if args.dry_run and matched:
            print("Re-run without --dry-run to delete them.")


if __name__ == "__main__":
    asyncio.run(run(parse_args()))
