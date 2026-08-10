import asyncio
import json
import os
import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.bot import get_bot  # noqa: E402
from lib.whitelist import list_domains, seed_if_empty  # noqa: E402


async def _do_setup(host: str, drop_pending: bool) -> dict:
    url = f"https://{host}/api/telegram"
    bot = get_bot()
    async with bot:
        await bot.set_webhook(
            url=url,
            secret_token=os.environ.get("WEBHOOK_SECRET") or None,
            allowed_updates=["message", "edited_message", "my_chat_member"],
            drop_pending_updates=drop_pending,
        )
        info = await bot.get_webhook_info()
        seeded = await seed_if_empty()
        domains = await list_domains()
        return {
            "ok": True,
            "webhook_url": url,
            "info": info.to_dict(),
            "seeded": seeded,
            "domains": domains,
        }


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        setup_secret = os.environ.get("SETUP_SECRET")
        if not setup_secret:
            self._reply(500, {"error": "SETUP_SECRET is not configured on the server."})
            return

        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        provided = (params.get("secret") or [""])[0]
        if provided != setup_secret:
            self._reply(401, {"error": "unauthorized"})
            return

        host = (
            self.headers.get("X-Forwarded-Host")
            or self.headers.get("Host")
            or os.environ.get("VERCEL_URL")
        )
        if not host:
            self._reply(500, {"error": "could not determine deployment host"})
            return

        drop_pending = (params.get("reset") or [""])[0] == "1"

        try:
            result = asyncio.run(_do_setup(host, drop_pending))
            self._reply(200, result)
        except Exception as err:
            print(f"[setup] error: {err}")
            self._reply(500, {"ok": False, "error": str(err)})

    def _reply(self, status: int, body: dict) -> None:
        payload = json.dumps(body, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format, *args) -> None:
        pass
