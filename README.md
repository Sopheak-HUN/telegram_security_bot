# Telegram Link-Guard Bot (Python)

A Telegram group bot built with [python-telegram-bot](https://python-telegram-bot.org/) that automatically deletes any message containing a link whose domain is **not** on an approved whitelist. Keeps groups free of unsolicited links, ads, and online-game promos.

Two deployment modes share the same bot logic:

- **Vercel** — deployed as Python serverless functions at `/api/telegram` (webhook) and `/api/setup` (one-shot configuration). Whitelist lives in **Upstash Redis**.
- **Local / VPS / Pi** — `python index.py` runs the bot in long-polling mode using the same `lib/bot.py`.

## Features

- Detects URLs in messages, captions, edits, mentions (`@username`), and text-link buttons.
- Deletes **any** unapproved link, including from admins (admin bypass has been removed — see [Admin behaviour](#admin-behaviour)).
- Deletes executable and script file attachments (`.exe`, `.msi`, `.bat`, `.sh`, `.scr`, `.com`, `.vbs`, and more — see [Blocked file types](#blocked-file-types)), including from admins.
- Posts a short warning reply identifying the offending domains.
- Logs every removal with user ID, chat ID, and offending host(s) to Vercel function logs.
- Admins manage the whitelist in-chat with `/addlink`, `/removelink`, `/listlinks`.
- Group dashboard at `/api/groups` — see every group the bot is in, its admin status, and last activity (HTML UI + JSON API — see [Where is the bot?](#where-is-the-bot-group-dashboard)).
- Subdomains are treated as distinct entries (e.g. `youtube.com` ≠ `m.youtube.com`).
- Strict hostname validation — junk input to `/addlink foo bar` is rejected.

## Requirements

- Python **3.11+** locally (Vercel runs Python 3.12).
- A Telegram bot token from [@BotFather](https://t.me/BotFather).
- An Upstash Redis database (free tier is enough). Either provision from the [Vercel Marketplace](https://vercel.com/marketplace) or directly at [console.upstash.com](https://console.upstash.com).

## File layout

```
.
├── api/
│   ├── telegram.py    # POST webhook receiver
│   ├── setup.py       # GET one-shot: registers webhook + seeds Redis
│   └── groups.py      # GET dashboard: which groups is the bot in? (HTML + JSON)
├── lib/
│   ├── __init__.py
│   ├── bot.py         # dispatcher + handlers (shared)
│   ├── chats.py       # group membership registry (Redis)
│   └── whitelist.py   # Upstash Redis helpers
├── tools/
│   └── cleanup_history.py  # one-shot sweep of OLD blocked files (Telethon, run locally)
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

### 3. Connect Upstash Redis

In the Vercel dashboard → your project → **Storage** → **Connect Database** → **Upstash → Redis** → create. Vercel auto-injects `UPSTASH_REDIS_REST_URL` and `UPSTASH_REDIS_REST_TOKEN` (and `KV_*` aliases) into all environments.

Or, if you already have an Upstash database:

```powershell
npx vercel env add UPSTASH_REDIS_REST_URL production
npx vercel env add UPSTASH_REDIS_REST_TOKEN production
```

### 4. Set the remaining environment variables

In **Project → Settings → Environment Variables**, add for all environments:

| Name | Value |
|---|---|
| `BOT_TOKEN` | Your token from @BotFather |
| `WEBHOOK_SECRET` | A long random string (A-Z, a-z, 0-9, `_`, `-`) |
| `SETUP_SECRET` | A different long random string |

Then redeploy so the new env vars are picked up:

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

If you ever need to wipe pending updates, append `&reset=1` to the URL.

### 6. Add the bot to your group

1. Add the bot to your Telegram group.
2. Promote to **Administrator**.
3. Grant the **Delete Messages** permission.

Test: send `youtube.com` in the group — message should disappear within ~1 second with a warning reply.

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

## Where is the bot? (group dashboard)

Telegram gives bots **no API to list their own chats**, so the bot keeps its own registry in Redis (`chats:known`): it records a group whenever it is **added/removed/promoted** (`my_chat_member` events) and on **every group message** (this backfills groups it joined before the feature existed, and keeps titles fresh).

Open the dashboard in a browser (uses the same secret as `/api/setup`):

```
https://<your-app>.vercel.app/api/groups?secret=<SETUP_SECRET>
```

Shows each group's title, chat id, the bot's status (**admin** ✅ / **member** ⚠️ — a warning, because without admin + delete permission the guard can't delete anything), and last activity.

For scripts or monitoring, append `&format=json`:

```json
{ "ok": true, "count": 2, "groups": [
  { "id": -1001234, "type": "supergroup", "title": "My Group",
    "username": null, "status": "administrator",
    "first_seen": 1754800000, "last_seen": 1754810000 } ] }
```

Notes:

- **After deploying this feature, re-run `/api/setup` once.** It re-registers the webhook with `my_chat_member` in `allowed_updates` — without that, Telegram never delivers add/remove events.
- Groups the bot was already in appear after the **first message** someone sends there (status shows "unknown" until a `my_chat_member` event fires — remove & re-add the bot, or promote/demote it, to populate the status immediately).
- If the bot is kicked from a group, it disappears from the list automatically.

## Blocked file types

Any **document** attachment whose file name ends in an executable or script extension is deleted immediately, with a warning reply — same policy as the link guard, admins included. Photos, videos, voice notes, and stickers are unaffected (Telegram re-encodes those; they can't carry executables).

Blocked extensions (defined in `BLOCKED_EXTENSIONS` in `lib/bot.py`):

| Category | Extensions |
|---|---|
| Windows executables / installers | `exe` `msi` `msp` `com` `scr` `pif` `cpl` `dll` `msc` |
| Windows scripts & shortcuts | `bat` `cmd` `vbs` `vbe` `js` `jse` `wsf` `wsh` `hta` `ps1` `psm1` `psd1` `reg` `lnk` |
| Unix / macOS | `sh` `bash` `zsh` `csh` `run` `bin` `command` `app` `dmg` `deb` `rpm` `appimage` |
| Interpreted languages & bytecode | `py` `pyw` `pyc` `pl` `rb` `php` `jar` |
| Mobile packages | `apk` `xapk` `ipa` |

Notes:

- Matching is case-insensitive and uses the **final** extension, so `invoice.pdf.exe` and `SETUP.EXE.` are caught.
- Archives (`zip`, `rar`, `7z`) are **not** blocked — an executable hidden inside one can't run until extracted. Add them to `BLOCKED_EXTENSIONS` if your group doesn't need file sharing.
- Source-code extensions (`py`, `js`, `sh`, …) are blocked because script hosts execute them on double-click. If your group shares code, remove them from the set or share via a paste service instead.

### Cleaning up OLD files (history sweep)

The live bot deletes blocked files **as they arrive**. It cannot retroactively delete files sent before it was active — the Telegram **Bot API has no access to message history**. (Short downtime is fine: Telegram queues undelivered updates for up to 24 h and the bot cleans them on recovery.)

To sweep files that are already in the group, run the one-shot script `tools/cleanup_history.py`. It logs in as **your own Telegram account** (which *can* read history) via [Telethon](https://docs.telethon.dev/), scans the full history, and deletes every document matching `BLOCKED_EXTENSIONS`. You must be an admin with delete permission in the group.

```powershell
pip install telethon
# create api_id / api_hash at https://my.telegram.org/apps then:
$env:TG_API_ID = "1234567"
$env:TG_API_HASH = "0123456789abcdef0123456789abcdef"

python tools/cleanup_history.py --chat @yourgroup --dry-run   # preview matches
python tools/cleanup_history.py --chat @yourgroup             # delete for everyone
```

The first run asks for your phone number and a login code, then saves `tools/cleanup-session.session`. That file grants full access to your account — it is git-ignored; never share or commit it. Telethon is **not** in `requirements.txt` on purpose: it's only needed locally for this script, never on Vercel.

## Commands

All commands must be sent inside a group. Only group admins receive a response.

| Command | Action |
|---|---|
| `/addlink <domain>` | Add a domain. Example: `/addlink youtube.com` |
| `/removelink <domain>` | Remove a domain. |
| `/listlinks` | Show every approved domain. |

The bot accepts `youtube.com`, `https://youtube.com`, or `https://youtube.com/watch?v=x` — it extracts the hostname.

## AI spam classifier (optional)

For messages **without a URL**, the bot can call Google Gemini 2.0 Flash to decide whether the text is spam (crypto/casino/MLM/etc). The free tier covers most groups.

### Enable

1. Get a free API key at [aistudio.google.com/apikey](https://aistudio.google.com/apikey) — no credit card.
2. Add it to Vercel:
   ```powershell
   npx vercel env add GEMINI_API_KEY production
   npx vercel --prod
   ```
3. That's it. No code change needed — the classifier auto-activates when the key is present.

### How it behaves

- Runs **only** when a message has no URL (URLs go through the whitelist as before).
- Skips messages shorter than 10 chars or longer than 600 chars.
- Free tier: **1500 requests/day** on Gemini 2.0 Flash, 15 req/minute. Plenty for most groups.
- Verdicts are cached in Redis for an hour (SHA-1 of the message), so copy-paste spam floods only cost the first request.
- On any AI failure (network, quota exhausted, missing key), the bot **fails open** — the message is not deleted.

To disable, remove `GEMINI_API_KEY` from Vercel and redeploy. The URL whitelist keeps working unchanged.

Privacy: when enabled, plain-text messages without URLs are sent to Google. See [SECURITY.md](./SECURITY.md#ai-classifier-privacy-optional-feature) for the full implications.

## Admin behaviour

There are **two separate** admin checks in the code:

1. **Commands** (`/addlink`, `/removelink`, `/listlinks`) — only admins receive a reply. Non-admins are silently ignored. This is enforced in `_handle_command`.
2. **Link filtering** (the auto-delete behaviour) — **admin bypass has been removed**. Any user, including the group owner, will have their unapproved-link messages deleted.

If you want admin messages to bypass the link filter again, edit `lib/bot.py` → `_handle_message` and re-add:

```python
if await is_admin(bot, msg.chat.id, msg.from_user.id):
    return
```

right after the `if not msg.from_user: return` line.

## How detection works

For every message in a group (admin or not):

0. If the message carries a document with a blocked executable/script extension, it is deleted immediately — before command routing, so an `.exe` with a `/command` caption can't slip past.
1. Reads Telegram's message `entities` to find URLs, text-links, and `@mentions`.
2. Runs a fallback regex over the text/caption to catch bare links Telegram didn't tag.
3. Normalizes each URL to a lowercase hostname via `urllib.parse`, then validates against a strict domain regex (rejects junk like `not a url`).
4. Issues a single `SMISMEMBER` against Redis to check all hosts at once.
5. If **any** hostname is not in the whitelist → deletes the message, posts a warning, logs the event.

Failures (missing permission, message too old, etc.) are logged but never throw — the function always returns `200 OK` so Telegram doesn't retry.

## Troubleshooting

- **`/api/setup` returns 401 unauthorized.** The `?secret=` value doesn't match `SETUP_SECRET`. Check the env var in Vercel and redeploy.
- **`/api/setup` returns 500 with an Upstash error.** Upstash isn't connected, or you redeployed before adding it. Connect it under Storage and redeploy.
- **Bot ignores normal messages with links in a group.** Group Privacy is still enabled in @BotFather. Disable it, then **remove and re-add the bot** to the group.
- **Function logs show webhook 401s.** `WEBHOOK_SECRET` doesn't match what was registered. Re-run `/api/setup` to register the current secret.
- **`/listlinks` doesn't reply, even though I'm an admin.** Try `/listlinks@<botname>` — the explicit form bypasses Group Privacy.
- **`ModuleNotFoundError: No module named 'lib'` on Vercel.** Each handler adds the project root to `sys.path` at the top of the file to import `lib/*`. Make sure those lines aren't deleted.
- **Local `python index.py` works, Vercel doesn't.** Likely missing env vars in production. Confirm `BOT_TOKEN`, `WEBHOOK_SECRET`, `SETUP_SECRET`, and the Upstash variables are all set in **Production** scope.

## Security

Found a security issue? **Do not open a public issue.** Email **sopheakhun.dev@gmail.com** with the subject `[SECURITY] telegram-link-guard-bot — <short description>`.

Full policy, threat model, and operational hardening guidance are in [SECURITY.md](./SECURITY.md). Highlights:

- Keep `BOT_TOKEN`, `WEBHOOK_SECRET`, and `SETUP_SECRET` in Vercel env vars only — never commit them.
- Use long random strings for `WEBHOOK_SECRET` and `SETUP_SECRET`. Rotate if exposed.
- Revoke the bot token via `/revoke` in @BotFather if it leaks.
- Grant the bot only the *Delete Messages* admin permission.
- Don't whitelist URL shorteners (`bit.ly`, `t.co`, …) — they bypass the filter.
- Only promote trusted users to admin — they can still modify the whitelist via `/addlink`.

## License

[MIT](./LICENSE) © 2026 Sopheak HUN
