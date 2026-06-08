# Security Policy

## Supported Versions

This project currently supports security updates on the latest commit of the `main` branch only. Older releases or forks are not maintained.

| Version  | Supported |
| -------- | --------- |
| `main`   | ✅        |
| Other    | ❌        |

## Reporting a Vulnerability

**Please do not open a public GitHub issue for security problems.**

If you believe you have found a vulnerability — for example, a way to bypass the link filter, leak the bot token or webhook secret, or escalate privileges through a bot command — report it privately to:

- **Email:** sopheakhun.dev@gmail.com
- **Subject line:** `[SECURITY] telegram-link-guard-bot — <short description>`

Please include:

1. A clear description of the issue and its impact.
2. Step-by-step reproduction (a minimal proof of concept is ideal).
3. The version / commit SHA you tested against.
4. Any suggested fix or mitigation, if you have one.

### What to expect

| Step                                     | Target time                                                   |
| ---------------------------------------- | ------------------------------------------------------------- |
| Acknowledgement of your report           | within **72 hours**                                           |
| Initial assessment & severity rating     | within **7 days**                                             |
| Fix or mitigation released               | within **30 days** for high/critical                          |
| Public disclosure (coordinated with you) | after a fix ships, or **90 days**, whichever comes first      |

Researchers who report in good faith will be credited in the release notes unless they request anonymity.

## Scope

### In scope

- The bot source code in this repository (`api/`, `lib/`, `index.py`, configuration files).
- The Vercel deployment topology described in `README.md` (webhook endpoint, setup endpoint, env vars).
- Dependency vulnerabilities affecting `python-telegram-bot`, `upstash-redis`, or `python-dotenv` as used here.

### Out of scope

- Vulnerabilities in the Telegram Bot API itself (report to Telegram).
- Vulnerabilities in Python, pip, the Vercel platform, or Upstash — report to the upstream project / vendor. We'll bump versions once they ship a fix.
- Social-engineering of group admins (e.g. tricking an admin into running `/addlink evil.com`). That is by design — admins are trusted with whitelist management.
- Denial-of-service via Telegram's normal rate limits or Vercel's function concurrency limits.
- Issues that only reproduce when the user has deliberately disabled security controls (e.g. removed the `WEBHOOK_SECRET` check from `api/telegram.py`).

## Threat Model

This bot runs as Python serverless functions on Vercel (production) or as a long-polling process locally. It also reaches out to a managed Upstash Redis instance over HTTPS. The main assets it protects are:

1. **The bot token** (`BOT_TOKEN`) — anyone who has it can impersonate the bot. Stored only in Vercel env vars and (for local dev) a git-ignored `.env`.
2. **The webhook secret** (`WEBHOOK_SECRET`) — anyone with it can forge fake Telegram updates that the bot will process as real. Stored only in Vercel env vars.
3. **The setup secret** (`SETUP_SECRET`) — gates `/api/setup`, which can re-register the webhook and seed Redis. Should be different from `WEBHOOK_SECRET`.
4. **The whitelist** in Redis — controls what links pass through the filter.
5. **The group(s)** the bot moderates — the bot has *Delete Messages* admin permission.

### Trust boundaries

| Actor               | Trust level                                                              |
| ------------------- | ------------------------------------------------------------------------ |
| Telegram Bot API    | Trusted transport, identified by the `X-Telegram-Bot-Api-Secret-Token` header |
| Vercel platform     | Trusted runtime + secrets store                                          |
| Upstash Redis       | Trusted state store, reached over HTTPS with a bearer token              |
| Group admins        | Trusted — they can modify the whitelist                                  |
| Group members       | **Untrusted** — all message text/captions/entities are treated as hostile input |
| Public internet     | Untrusted — `/api/telegram` rejects anything missing the secret header   |

### Webhook authentication

`api/telegram.py` rejects any POST whose `X-Telegram-Bot-Api-Secret-Token` header doesn't match `WEBHOOK_SECRET`, returning 401. Telegram sends this header on every legitimate webhook call after `setWebhook` is run with a `secret_token` argument (which `/api/setup` does for you). This prevents anyone who knows the public webhook URL from spoofing fake updates.

## Operational Security Guidance

If you are deploying this bot, follow these practices.

### Secret handling

- Never commit `.env`, never paste `BOT_TOKEN` / `WEBHOOK_SECRET` / `SETUP_SECRET` into chat, issues, or PRs.
- If `BOT_TOKEN` leaks, revoke it via `/revoke` in [@BotFather](https://t.me/BotFather) and replace the value in Vercel env vars + your local `.env`.
- If `WEBHOOK_SECRET` or `SETUP_SECRET` leaks, generate a new one (`python -c "import secrets; print(secrets.token_urlsafe(48))"`), update Vercel env vars, redeploy, and re-run `/api/setup`.
- Use **long, random** values for both secrets — at least 32 URL-safe characters. The provided `.env.example` is a template; do not deploy with the placeholder values.
- Treat the `?secret=` query parameter on `/api/setup` as sensitive — it may end up in Vercel access logs and your browser history. Rotate `SETUP_SECRET` if you suspect exposure.

### Bot privileges

- Grant the bot **only** the *Delete Messages* permission in the group. It does not need *Ban Users*, *Pin Messages*, *Add Admins*, *Restrict Members*, or *Anonymous*.
- Do not promote the bot to "Anonymous" admin — debugging permission issues becomes much harder.

### Whitelist hygiene

- Avoid whitelisting URL shorteners (`bit.ly`, `t.co`, `tinyurl.com`, etc.). They bypass the domain filter by hiding the real destination.
- Avoid whitelisting hosting / file-share roots where any user can upload public content (`drive.google.com`, `mediafire.com`, `mega.nz`) unless that is intentional.
- Review the output of `/listlinks` periodically — admins can quietly add entries with `/addlink`, and a compromised admin account is the most likely real-world attack on this bot.
- Subdomains are intentionally distinct from their apex (`youtube.com` ≠ `m.youtube.com`). Add each variant you want.

### Vercel hardening

- Restrict Vercel project access to people who need it; the deployment can read all env vars.
- Set **Production** scope on every secret — don't accidentally only set it on Preview.
- Keep an eye on Vercel function logs for `[webhook]`, `[guard]`, and `[setup]` lines — sudden spikes are an early sign something is off.

### Upstash hardening

- Use a dedicated database for this bot — don't reuse credentials with other services.
- The bot only needs read/write access to the single key `whitelist:domains`. If you rotate the token, update both Vercel and (for local dev) your `.env`.
- Treat the Upstash REST token as equivalent to direct database access.

### Process & host (local mode)

- Keep Python patched. This project targets Python `>= 3.11` locally and Python 3.12 on Vercel.
- Run `pip list --outdated` or `pip-audit` periodically and address advisories for `python-telegram-bot`, `upstash-redis`, `python-dotenv`.
- Treat console logs as sensitive — they contain user IDs, chat IDs, and the hostnames the bot saw.
- Run the bot under a dedicated, unprivileged OS user; do not run as Administrator.

## Known Limitations

These are documented behaviours, not vulnerabilities:

- **All users are filtered by default in this build.** The admin bypass on the link guard has been removed — admins (including the group owner) will have their unapproved-link messages deleted. To restore the bypass, see the *Admin behaviour* section in `README.md`.
- **The bot only sees messages if Group Privacy is disabled in @BotFather.** Until that is done, the filter silently does nothing on plain-text messages.
- **Subdomain matching is exact.** `youtube.com` does not cover `m.youtube.com`. This is by design to prevent over-broad rules.
- **The bot does not resolve shortened URLs.** A shortener that is not whitelisted is blocked. A shortener that is whitelisted will pass regardless of where it ultimately redirects — so don't whitelist them.
- **The whitelist is hot-readable from Redis.** Anyone with the Upstash REST token can edit the whitelist out-of-band without the bot logging anything.
- **`/api/telegram` always returns `200 OK`.** Even when internal processing throws, the function swallows the error and returns 200 so Telegram doesn't retry. Errors are logged but not surfaced to the caller. This is required by the Telegram Bot API contract.

## Credits

Thanks to everyone who responsibly discloses issues to keep this project safe.
