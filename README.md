# Telegram Link-Guard Bot

A Telegram group bot built with [Telegraf](https://telegraf.js.org/) that automatically deletes any message containing a link whose domain is **not** on an approved whitelist. Useful for keeping groups free of unsolicited links, ads, and online-game promos.

## Features

- Detects URLs in normal messages, captions, edits, mentions (`@username`), and text-link buttons.
- Deletes any message containing a domain that is **not** in `whitelist.json`.
- Posts a short warning reply that auto-deletes after 10 seconds.
- Logs every removal to the console with user ID, chat ID, and the offending host(s).
- Admins can manage the whitelist in-chat with `/addlink`, `/removelink`, `/listlinks`.
- Whitelist is stored in `whitelist.json` — you can edit it directly; the bot hot-reloads it.
- Group admins always bypass the filter.
- Subdomains are treated as distinct entries (e.g. `youtube.com` ≠ `m.youtube.com`).

## Requirements

- Node.js **18+**
- A Telegram bot token from [@BotFather](https://t.me/BotFather)

## Setup

Run these from the project folder in PowerShell:

```powershell
npm install
Copy-Item .env.example .env
notepad .env   # paste your bot token from @BotFather
```

### Configure the bot in @BotFather

1. `/newbot` — create the bot and copy the token into `.env`.
2. `/setprivacy` → choose your bot → **Disable**.
   > Without this step, your bot will only see commands (`/...`) and explicit mentions, so it cannot scan ordinary messages for links.
3. *(optional)* `/setcommands` → paste:
   ```
   addlink - Approve a domain (admins only)
   removelink - Remove a domain from the whitelist (admins only)
   listlinks - Show approved domains (admins only)
   ```

### Add the bot to your group

1. Add the bot to your group.
2. Promote it to **Administrator**.
3. Grant the **Delete Messages** permission (the others can stay off).

### Run

```powershell
npm start          # production
npm run dev        # auto-restart on code changes
```

## Whitelist

`whitelist.json` is the single source of truth:

```json
{
  "domains": [
    "t.me",
    "telegram.org",
    "youtube.com"
  ]
}
```

- Domains are matched **exactly** (case-insensitive). `youtube.com` does **not** automatically cover `www.youtube.com` or `m.youtube.com` — add each variant you want to allow.
- You can edit the file by hand; the bot reloads it within a second.
- You can also manage it from inside the group with commands (below).

## Commands

All commands must be sent inside a group, and only group admins get a response.

| Command | What it does |
|---|---|
| `/addlink <domain>` | Adds a domain to the whitelist. Example: `/addlink youtube.com` |
| `/removelink <domain>` | Removes a domain. Example: `/removelink youtube.com` |
| `/listlinks` | Lists every approved domain. |

The bot accepts `youtube.com`, `https://youtube.com`, or `https://youtube.com/watch?v=x` — it extracts the hostname.

## How detection works

For every non-admin message in a group, the bot:

1. Reads Telegram's message `entities` to find URLs, text-links, and `@mentions`.
2. Runs a fallback regex over the text/caption to catch bare links Telegram didn't tag.
3. Normalizes each URL to a lowercase hostname.
4. If **any** hostname is not in the whitelist → deletes the message, replies with a short warning, logs the event.

If the bot fails to delete (missing permission, message too old, etc.), the failure is logged but does not crash the bot.

## File layout

```
.
├── index.js          # bot logic
├── package.json
├── whitelist.json    # approved domains
├── .env.example      # template for BOT_TOKEN
├── .env              # your real token (gitignored)
└── .gitignore
```

## Troubleshooting

- **Bot ignores normal messages with links.** Group Privacy is still enabled in @BotFather. Disable it, then **remove and re-add the bot** to the group.
- **Messages stay in the chat after warning.** The bot isn't a group admin, or the *Delete Messages* permission is off.
- **Admins want their own messages filtered too.** Remove the `if (await isAdmin(ctx)) return next?.();` line in the guard handler in `index.js`.
- **Need a per-link allowlist instead of per-domain.** Replace the `whitelist.has(host)` check in `index.js` with a full-URL comparison.

## Security

Found a security issue? **Do not open a public issue.** Email **turbotech.kh@gmail.com** with the subject `[SECURITY] telegram-link-guard-bot — <short description>`.

Full policy, threat model, and operational hardening guidance are in [SECURITY.md](./SECURITY.md). Highlights:

- Keep your bot token in `.env` only — never commit it. Revoke via `/revoke` in @BotFather if it leaks.
- Grant the bot only the *Delete Messages* admin permission.
- Don't whitelist URL shorteners (`bit.ly`, `t.co`, …) — they bypass the filter.
- Never run with `NODE_TLS_REJECT_UNAUTHORIZED=0` in production.
- Group admins bypass the filter by design — only promote people you trust.

## License

MIT
