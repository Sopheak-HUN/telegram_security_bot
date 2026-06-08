# Security Policy

## Supported Versions

This project currently supports security updates on the latest commit of the `main` branch only. Older releases or forks are not maintained.

| Version | Supported |
| ------- | --------- |
| `main`  | ✅        |
| Other   | ❌        |

## Reporting a Vulnerability

**Please do not open a public GitHub issue for security problems.**

If you believe you have found a vulnerability — for example, a way to bypass the link filter, leak the bot token, or escalate privileges through a bot command — report it privately to:

- **Email:** turbotech.kh@gmail.com
- **Subject line:** `[SECURITY] telegram-link-guard-bot — <short description>`

Please include:

1. A clear description of the issue and its impact.
2. Step-by-step reproduction (a minimal proof of concept is ideal).
3. The version / commit SHA you tested against.
4. Any suggested fix or mitigation, if you have one.

### What to expect

| Step | Target time |
| --- | --- |
| Acknowledgement of your report | within **72 hours** |
| Initial assessment & severity rating | within **7 days** |
| Fix or mitigation released | within **30 days** for high/critical |
| Public disclosure (coordinated with you) | after a fix ships, or **90 days**, whichever comes first |

Researchers who report in good faith will be credited in the release notes unless they request anonymity.

## Scope

### In scope

- The bot source code in this repository (`index.js`, configuration files).
- Default operational guidance documented in `README.md`.
- Dependency vulnerabilities affecting `telegraf` or `dotenv` as used here.

### Out of scope

- Vulnerabilities in the Telegram Bot API itself (report to Telegram).
- Vulnerabilities in Node.js, npm, or transitive dependencies — report to the upstream project. We'll bump versions once they ship a fix.
- Social-engineering of group admins (e.g. tricking an admin into running `/addlink evil.com`). That is by design — admins are trusted.
- Issues that only reproduce with `NODE_TLS_REJECT_UNAUTHORIZED=0` set, or other security flags the user has deliberately disabled.
- Denial-of-service via Telegram's normal rate limits.

## Threat Model

This bot is intended to run as a long-lived process on a server or workstation. The main assets it protects are:

1. **The bot token** — anyone who has it can impersonate the bot. Stored in `.env`, which is git-ignored.
2. **The whitelist** (`whitelist.json`) — controls what links pass through the filter.
3. **The group(s)** the bot moderates — the bot has admin + delete-messages permission.

### Trust boundaries

| Actor | Trust level |
| --- | --- |
| Telegram Bot API | Trusted transport |
| Group admins | Trusted — they can modify the whitelist |
| Group members | **Untrusted** — all input is treated as hostile |
| The host filesystem | Trusted (anyone with shell access to it owns the bot) |

## Operational Security Guidance

If you are deploying this bot, follow these practices:

### Token handling

- Never commit `.env` or paste your token in chat, issues, or PRs.
- If you suspect the token leaked, revoke it immediately via `/revoke` in [@BotFather](https://t.me/BotFather) and replace the value in `.env`.
- Restrict file permissions on `.env` to the bot's user account only.

### Bot privileges

- Grant the bot **only** the *Delete Messages* permission. It does not need *Ban Users*, *Pin Messages*, *Add Admins*, or *Anonymous*.
- Do not promote the bot to "Anonymous" admin — it can no longer be diagnosed if it misbehaves.

### Whitelist hygiene

- Avoid whitelisting URL shorteners (`bit.ly`, `t.co`, `tinyurl.com`, etc.). They defeat the filter by hiding the real destination.
- Avoid whitelisting hosting/file-share roots where any user can upload content (`drive.google.com` for public links, `mediafire.com`, `mega.nz`, etc.) unless that is intentional.
- Review `/listlinks` periodically. Remove entries you no longer recognise.

### Network & TLS

- The bot uses HTTPS to talk to `api.telegram.org`. **Do not** set `NODE_TLS_REJECT_UNAUTHORIZED=0` in production — it disables certificate verification entirely. The README mentions it only as a one-shot debug step.
- If you are behind a TLS-inspecting proxy or antivirus, install that root CA into Windows' trust store and run with `--use-system-ca` (already configured in `package.json`), or point `NODE_EXTRA_CA_CERTS` at a `.pem` file. Do not work around TLS errors by disabling verification.

### Process & host

- Run the bot under a dedicated, unprivileged OS user.
- Keep Node.js patched. This project targets Node `>= 18`.
- Run `npm audit` periodically; address `high` / `critical` advisories promptly.
- Treat console logs as sensitive — they contain user IDs and chat IDs.

## Known Limitations

These are documented behaviours, not vulnerabilities:

- **Group admins bypass the filter.** Anyone you promote to admin can post any link. This is by design.
- **The bot only sees messages if Group Privacy is disabled in @BotFather.** Until that is done, the filter silently does nothing.
- **Subdomain matching is exact.** `youtube.com` does not cover `m.youtube.com`. This is by design to prevent over-broad rules.
- **The bot does not resolve shortened URLs.** A shortener that is not whitelisted is blocked. A shortener that is whitelisted will pass through regardless of where it ultimately redirects.
- **`whitelist.json` is hot-reloaded from disk.** Anyone with write access to that file can modify the policy without restarting the bot.

## Credits

Thanks to everyone who responsibly discloses issues to keep this project safe.
