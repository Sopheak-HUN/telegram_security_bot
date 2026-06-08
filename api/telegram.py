import asyncio
import json
import os
import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.bot import dispatch_update  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        expected = os.environ.get("WEBHOOK_SECRET")
        if expected:
            got = self.headers.get("X-Telegram-Bot-Api-Secret-Token")
            if got != expected:
                self.send_response(401)
                self.end_headers()
                self.wfile.write(b'{"error":"bad secret token"}')
                return

        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""

        try:
            update = json.loads(raw) if raw else {}
            asyncio.run(dispatch_update(update))
        except Exception as err:
            print(f"[webhook] handler error: {err}")

        # Always 200 — anything else makes Telegram retry the same update.
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def do_GET(self) -> None:
        self.send_response(405)
        self.end_headers()
        self.wfile.write(b'{"error":"method not allowed"}')

    def log_message(self, format, *args) -> None:
        # Quiet the default access-log noise; rely on print() instead.
        pass
