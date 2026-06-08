"""Local long-polling entrypoint.

For Vercel deployment, the webhook handler in api/telegram.py is used instead.
This file is only for local development on your own machine.

Run with:  python index.py
"""

import asyncio
import os

from dotenv import load_dotenv

from lib.bot import dispatch_update, get_bot

load_dotenv()


async def main() -> None:
    bot = get_bot()
    print("Link-guard bot running (long-polling). Ctrl+C to stop.")
    async with bot:
        offset: int | None = None
        while True:
            try:
                updates = await bot.get_updates(
                    offset=offset,
                    timeout=30,
                    allowed_updates=["message", "edited_message"],
                )
            except Exception as err:
                print(f"[poll] error: {err}")
                await asyncio.sleep(2)
                continue

            for update in updates:
                try:
                    await dispatch_update(update.to_dict())
                except Exception as err:
                    print(f"[dispatch] error: {err}")
                offset = update.update_id + 1


if __name__ == "__main__":
    if not os.environ.get("BOT_TOKEN"):
        raise SystemExit("Missing BOT_TOKEN. Copy .env.example to .env and paste your token.")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Stopped.")
