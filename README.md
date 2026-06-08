# Telegram Link-Guard Bot

A Telegram group bot built with [Telegraf](https://telegraf.js.org/) that automatically deletes any message containing a link whose domain is **not** on an approved whitelist. Keeps groups free of unsolicited links, ads, and online-game promos.

Two deployment modes share the same bot logic:

- **Vercel** — deployed as a serverless function at `/api/telegram`, receiving Telegram updates via webhook. Whitelist lives in **Upstash Redis**.
- **Local / VPS / Pi** — `npm start` runs `index.js` in long-polling mode. Same `lib/bot.js`, same Upstash Redis whitelist.

## Features

- Detects URLs in messages, captions, edits, mentions (`@username`), and text-link buttons.
- Deletes any message with a domain **not** on the whitelist; replies with a short warning.
- Logs every removal to the function/console logs with user ID, chat ID, and offending host(s).
- Admins manage the whitelist in-chat with `/addlink`, `/removelink`, `/listlinks`.
- Group admins always bypass the filter.
- Subdomains are treated as distinct entries (e.g. `youtube.com` ≠ `m.youtube.com`).

## Requirements

- Node.js **22.x** (matches Vercel runtime). Node 18+ works locally.
- A Telegram bot token from [@BotFather](https://t.me/BotFather).
- An Upstash Redis database (free tier is enough). Either provision from the [Vercel Marketplace](https://vercel.com/marketplace) or directly at [console.upstash.com](https://console.upstash.com).

## File layout

```
.
├── api/
│   ├── telegram.js     # POST webhook receiver
│   └── setup.js        # GET one-shot: registers webhook + seeds Redis
├── lib/
│   ├── bot.js          # Telegraf instance + handlers (shared)
│   └── whitelist.js    # Upstash Redis helpers
├── index.js            # local long-polling entrypoint
├── whitelist.json      # seed list — copied into Redis on first /api/setup
├── vercel.json
├── package.json
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
npm install
npx vercel link
npx vercel --prod
```

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

Test from a non-admin account: send `youtube.com` → the message should disappear and a warning should appear.

---

## Run locally (long-polling)

For development on your own machine — no public URL needed.

```powershell
npm install
Copy-Item .env.example .env
notepad .env
```

Fill in `BOT_TOKEN`. For Upstash credentials, after linking with Vercel:

```powershell
npx vercel env pull .env
```

Or paste the Upstash REST URL and token manually into `.env`. Then:

```powershell
npm start          # node --use-system-ca index.js
npm run dev        # with auto-restart
```

The local script and the Vercel function share `lib/bot.js`, so behaviour is identical.

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
3. Normalizes each URL to a lowercase hostname (strict validation — only real-looking domains are accepted).
4. Issues a single `SMISMEMBER` against Redis to check all hosts at once.
5. If **any** hostname is not in the whitelist → deletes the message, posts a warning, logs the event.

Failures (missing permission, message too old, etc.) are logged but never throw — the function always returns `200 OK` so Telegram doesn't retry.

## Troubleshooting

- **`/api/setup` returns 401 unauthorized.** The `?secret=` value doesn't match `SETUP_SECRET`. Check the env var in Vercel and redeploy.
- **`/api/setup` returns 500 with an Upstash error.** Upstash isn't connected, or you redeployed before adding it. Connect it under Storage and redeploy.
- **Bot ignores normal messages with links in a group.** Group Privacy is still enabled in @BotFather. Disable it, then **remove and re-add the bot** to the group.
- **Function logs show webhook 401s.** `WEBHOOK_SECRET` doesn't match what was registered. Re-run `/api/setup` to register the current secret.
- **`/listlinks` doesn't reply, even though I'm an admin.** Try `/listlinks@<botname>` — the explicit form bypasses Group Privacy.
- **Messages I send aren't being deleted.** You are a group admin. The bot bypasses admins by design — test from a non-admin account, or remove the `if (await isAdmin(ctx)) return next?.();` line in [lib/bot.js](./lib/bot.js#L120) if you want admins filtered too.
- **Local `npm start` works, Vercel doesn't.** Likely missing env vars in production. Confirm all 5 are set in Production scope.

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
