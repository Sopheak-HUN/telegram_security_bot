# Telegram Link-Guard Bot (Python)

A Telegram group bot built with [python-telegram-bot](https://python-telegram-bot.org/) that automatically deletes any message containing a link whose domain is **not** on an approved whitelist. Keeps groups free of unsolicited links, ads, and online-game promos.

Two deployment modes share the same bot logic:

- **Vercel** — deployed as Python serverless functions at `/api/telegram` (webhook) and `/api/setup` (one-shot configuration). Whitelist lives in **Upstash Redis** (auto-provisioned via the Vercel Marketplace).
- **Local / VPS / Pi** — `python index.py` runs the bot in long-polling mode using the same `lib/bot.py` and the same Upstash Redis whitelist.

## Features

- Detects URLs in messages, captions, edits, mentions (`@username`), and text-link buttons.
- Deletes any message with a domain **not** on the whitelist; replies with a short warning.
- Logs every removal with user ID, chat ID, and offending host(s).
- Admins manage the whitelist in-chat with `/addlink`, `/removelink`, `/listlinks`.
- Group admins always bypass the filter.
- Subdomains are treated as distinct entries (e.g. `youtube.com` ≠ `m.youtube.com`).

## Requirements

- Python **3.11+** (Vercel runs Python 3.12).
- A Telegram bot token from [@BotFather](https://t.me/BotFather).
- An Upstash Redis database (one click from the Vercel Marketplace).

## File layout

```
.
├── api/
│   ├── telegram.py    # POST webhook receiver
│   └── setup.py       # GET one-shot: registers webhook + seeds Redis
├── lib/
│   ├── __init__.py
│   ├── bot.py         # dispatcher + handlers (shared)
│   └── whitelist.py   # Upstash Redis helpers
├── index.py           # local long-polling entrypoint
├── whitelist.json     # seed list — copied into Redis on first /api/setup
├── requirements.txt
├── vercel.json
├── .env.example
├── .gitignore
├── README.md
└── SECURITY.md
```

---

## Deploy to Vercel (production)

### 1. @BotFather setup

In a Telegram chat with [@BotFather](https://t.me/BotFather):

1. `/newbot` — create the bot and copy the token.
2. `/setprivacy` → choose your bot → **Disable**. Without this, the bot only sees commands and direct mentions and can't scan normal messages for links.
3. *(optional)* `/setcommands` → paste:
   ```
   addlink - Approve a domain (admins only)
   removelink - Remove a domain from the whitelist (admins only)
   listlinks - Show approved domains (admins only)
   ```

### 2. Push to Vercel

```powershell
npx vercel link
npx vercel --prod
```

Vercel auto-detects this as a Python project via `requirements.txt`.

### 3. Add Upstash Redis from the Marketplace

In the Vercel dashboard → your project → **Storage** → **Connect Database** → **Upstash → Redis** → create. Vercel auto-injects `UPSTASH_REDIS_REST_URL` / `UPSTASH_REDIS_REST_TOKEN` (and `KV_*` aliases) into all environments.

### 4. Set the remaining environment variables

In **Project → Settings → Environment Variables**, add for all environments:

| Name | Value |
|---|---|
| `BOT_TOKEN` | Your token from @BotFather |
| `WEBHOOK_SECRET` | A long random string (A-Z, a-z, 0-9, `_`, `-`) |
| `SETUP_SECRET` | A different long random string |

Then redeploy:

```powershell
npx vercel --prod
```

### 5. Register the webhook

Visit this URL once in your browser (replace placeholders):

```
https://<your-app>.vercel.app/api/setup?secret=<SETUP_SECRET>
```

Expected JSON response:

```json
{
  "ok": true,
  "webhook_url": "https://<your-app>.vercel.app/api/telegram",
  "info": { "url": "...", "pending_update_count": 0, ... },
  "seeded": { "added": 2, "already": 0 },
  "domains": ["t.me", "telegram.org"]
}
```

`seeded.added > 0` means the contents of `whitelist.json` were copied into Redis on first run.

If you ever need to wipe pending updates, append `&reset=1` to the URL.

### 6. Add the bot to your group

1. Add the bot to your Telegram group.
2. Promote to **Administrator**.
3. Grant the **Delete Messages** permission.

Test from a non-admin account: send `youtube.com` → the message should disappear and a warning should appear.

---

## Run locally (long-polling)

For development on your own machine — no public URL needed.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env
```

Fill in `BOT_TOKEN`. For Upstash credentials, after linking with Vercel:

```powershell
npx vercel env pull .env
```

Or paste the Upstash REST URL and token manually into `.env`. Then run:

```powershell
python index.py
```

The local script and the Vercel function share `lib/bot.py`, so behaviour is identical.

---

## Whitelist

Stored as a Redis set under the key `whitelist:domains`.

`whitelist.json` is **seed data only** — copied into Redis the first time you hit `/api/setup` (when the set is empty). After that, all reads/writes go through Redis. Editing `whitelist.json` after the seed has no effect.

- Domains are matched **exactly** (case-insensitive). `youtube.com` does **not** cover `www.youtube.com` or `m.youtube.com` — add each variant you want.
- Manage from inside the group with `/addlink`, `/removelink`, `/listlinks`.
- Or edit directly in the [Upstash console](https://console.upstash.com) → your DB → Data Browser.

## Commands

All commands must be sent inside a group. Only group admins get a response.

| Command | Action |
|---|---|
| `/addlink <domain>` | Add a domain. Example: `/addlink youtube.com` |
| `/removelink <domain>` | Remove a domain. |
| `/listlinks` | Show every approved domain. |

The bot accepts `youtube.com`, `https://youtube.com`, or `https://youtube.com/watch?v=x` — it extracts the hostname.

## How detection works

For every non-admin message in a group:

1. Reads Telegram's message `entities` to find URLs, text-links, and `@mentions`.
2. Runs a fallback regex over the text/caption to catch bare links Telegram didn't tag.
3. Normalizes each URL to a lowercase hostname via `urllib.parse`.
4. Issues a single `SMISMEMBER` against Redis to check all hosts at once.
5. If **any** hostname is not in the whitelist → deletes the message, posts a warning, logs the event.

Failures (missing permission, message too old, etc.) are logged but never throw — the function always returns `200 OK` so Telegram doesn't retry.

## Troubleshooting

- **`/api/setup` returns 401 unauthorized.** The `?secret=` value doesn't match `SETUP_SECRET`. Check the env var in Vercel and redeploy.
- **`/api/setup` returns 500 with an Upstash error.** The Marketplace database isn't connected, or you redeployed before adding it. Connect it under Storage and redeploy.
- **Bot ignores normal messages with links in a group.** Group Privacy is still enabled in @BotFather. Disable it, then **remove and re-add the bot** to the group.
- **Function logs show webhook 401s.** `WEBHOOK_SECRET` doesn't match what was registered. Re-run `/api/setup` to register the current secret.
- **`ModuleNotFoundError: No module named 'lib'` on Vercel.** Vercel builds each function in isolation; the handlers add the project root to `sys.path` at the top of each file to import `lib/*`. Make sure those lines aren't deleted.
- **Local `python index.py` works, Vercel doesn't.** Likely missing env vars in production. Confirm `BOT_TOKEN`, `WEBHOOK_SECRET`, `SETUP_SECRET`, and the Upstash variables are all set in **Production** scope.

## Security

Found a security issue? **Do not open a public issue.** Email **sopheakhun.dev@gmail.com** with the subject `[SECURITY] telegram-link-guard-bot — <short description>`.

Full policy, threat model, and operational hardening guidance are in [SECURITY.md](./SECURITY.md). Highlights:

- Keep `BOT_TOKEN`, `WEBHOOK_SECRET`, and `SETUP_SECRET` in Vercel env vars only — never commit them.
- Use long random strings for `WEBHOOK_SECRET` and `SETUP_SECRET`. Rotate if exposed.
- Revoke the bot token via `/revoke` in @BotFather if it leaks.
- Grant the bot only the *Delete Messages* admin permission.
- Don't whitelist URL shorteners (`bit.ly`, `t.co`, …) — they bypass the filter.
- Group admins bypass the filter by design — only promote people you trust.

## License

MIT
