"""GET /api/groups — where is the bot?

Lists every group the bot has recorded itself in (Redis hash ``chats:known``,
maintained by lib/chats.py). Protected by the same secret as /api/setup.

  /api/groups?secret=<SETUP_SECRET>              -> HTML dashboard
  /api/groups?secret=<SETUP_SECRET>&format=json  -> JSON
"""

import asyncio
import html
import json
import os
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.chats import list_chats  # noqa: E402

STATUS_LABELS = {
    "administrator": ("admin", "ok"),
    "member": ("member — needs admin + delete permission!", "warn"),
    "restricted": ("restricted", "warn"),
    "creator": ("owner", "ok"),
}


def _fmt_time(ts) -> str:
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except (TypeError, ValueError, OSError):
        return "?"


def _render_html(chats: list[dict]) -> str:
    rows = []
    for c in chats:
        title = html.escape(str(c.get("title") or "?"))
        username = c.get("username")
        link = (
            f'<a href="https://t.me/{html.escape(username)}" target="_blank">@{html.escape(username)}</a>'
            if username
            else '<span class="muted">private group</span>'
        )
        label, badge = STATUS_LABELS.get(c.get("status") or "", ("unknown — re-add the bot or send a message", "muted"))
        rows.append(
            "<tr>"
            f"<td><strong>{title}</strong><br>{link}</td>"
            f'<td><code>{c.get("id")}</code><br><span class="muted">{html.escape(str(c.get("type") or ""))}</span></td>'
            f'<td><span class="badge {badge}">{html.escape(label)}</span></td>'
            f'<td>{_fmt_time(c.get("last_seen"))}</td>'
            "</tr>"
        )

    body = (
        "\n".join(rows)
        if rows
        else '<tr><td colspan="4" class="empty">No groups recorded yet.<br>'
        "Send any message in a group the bot is in, or remove &amp; re-add the bot — "
        "it records membership from incoming updates.</td></tr>"
    )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Link-Guard — Groups</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font-family: system-ui, sans-serif; margin: 0; padding: 2rem 1rem;
         background: #f6f7f9; color: #1a1d21; }}
  @media (prefers-color-scheme: dark) {{
    body {{ background: #14161a; color: #e6e8eb; }}
  }}
  .wrap {{ max-width: 760px; margin: 0 auto; }}
  h1 {{ font-size: 1.3rem; }} .muted {{ opacity: .6; font-size: .85em; }}
  table {{ width: 100%; border-collapse: collapse; background: #fff;
           border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,.1); }}
  @media (prefers-color-scheme: dark) {{ table {{ background: #1d2026; }} }}
  th, td {{ text-align: left; padding: .65rem .8rem; border-bottom: 1px solid rgba(128,128,128,.2);
            vertical-align: top; font-size: .92rem; }}
  th {{ font-size: .8rem; text-transform: uppercase; letter-spacing: .04em; opacity: .65; }}
  .badge {{ display: inline-block; padding: .15rem .5rem; border-radius: 99px; font-size: .78rem; }}
  .badge.ok {{ background: #d3f2dd; color: #14632e; }}
  .badge.warn {{ background: #fdeccc; color: #7a4b06; }}
  .badge.muted {{ background: rgba(128,128,128,.18); }}
  @media (prefers-color-scheme: dark) {{
    .badge.ok {{ background: #163f24; color: #7fd89a; }}
    .badge.warn {{ background: #46320d; color: #f0c069; }}
  }}
  .empty {{ text-align: center; padding: 2.5rem 1rem !important; opacity: .7; }}
  code {{ font-size: .85em; }}
  footer {{ margin-top: 1rem; font-size: .8rem; opacity: .55; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>🤖 Link-Guard bot — groups ({len(chats)})</h1>
  <table>
    <thead><tr><th>Group</th><th>Chat ID / type</th><th>Bot status</th><th>Last activity</th></tr></thead>
    <tbody>{body}</tbody>
  </table>
  <footer>Status comes from Telegram <code>my_chat_member</code> events; "last activity"
  is the latest message or membership change the bot saw. Reload the page to refresh.</footer>
</div>
</body>
</html>"""


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        secret = os.environ.get("SETUP_SECRET")
        if not secret:
            self._reply_json(500, {"error": "SETUP_SECRET is not configured on the server."})
            return

        params = parse_qs(urlparse(self.path).query)
        if (params.get("secret") or [""])[0] != secret:
            self._reply_json(401, {"error": "unauthorized"})
            return

        try:
            chats = asyncio.run(list_chats())
        except Exception as err:
            print(f"[groups] error: {err}")
            self._reply_json(500, {"ok": False, "error": str(err)})
            return

        if (params.get("format") or [""])[0] == "json":
            self._reply_json(200, {"ok": True, "count": len(chats), "groups": chats})
        else:
            payload = _render_html(chats).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    def _reply_json(self, status: int, body: dict) -> None:
        payload = json.dumps(body, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format, *args) -> None:
        pass
