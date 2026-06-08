require('dotenv').config();
const fs = require('fs');
const path = require('path');
const { Telegraf } = require('telegraf');

const BOT_TOKEN = process.env.BOT_TOKEN;
if (!BOT_TOKEN) {
  console.error('Missing BOT_TOKEN. Copy .env.example to .env and paste your token from @BotFather.');
  process.exit(1);
}

const WHITELIST_PATH = path.join(__dirname, 'whitelist.json');

function loadWhitelist() {
  try {
    const raw = fs.readFileSync(WHITELIST_PATH, 'utf8');
    const data = JSON.parse(raw);
    const list = Array.isArray(data.domains) ? data.domains : [];
    return new Set(list.map((d) => d.toLowerCase().trim()).filter(Boolean));
  } catch (err) {
    console.warn('Could not read whitelist.json, starting with empty list:', err.message);
    return new Set();
  }
}

function saveWhitelist(set) {
  const data = { domains: [...set].sort() };
  fs.writeFileSync(WHITELIST_PATH, JSON.stringify(data, null, 2) + '\n');
}

let whitelist = loadWhitelist();

// Reload if the file changes on disk (manual edits).
fs.watch(WHITELIST_PATH, { persistent: false }, () => {
  setTimeout(() => {
    whitelist = loadWhitelist();
    console.log(`[whitelist] reloaded, ${whitelist.size} domain(s)`);
  }, 100);
});

// --- URL extraction -------------------------------------------------------

// Plain-text URL regex (covers http(s), and bare domains like "youtube.com/...").
const URL_REGEX = /\b((?:https?:\/\/)?(?:[a-z0-9-]+\.)+[a-z]{2,}(?:[/?#][^\s]*)?)/gi;

function extractHostnames(message) {
  const hostnames = new Set();
  const text = message.text || message.caption || '';
  const entities = message.entities || message.caption_entities || [];

  // Pull explicit Telegram-flagged URLs first (most reliable).
  for (const ent of entities) {
    if (ent.type === 'url') {
      const slice = text.slice(ent.offset, ent.offset + ent.length);
      const host = toHostname(slice);
      if (host) hostnames.add(host);
    } else if (ent.type === 'text_link' && ent.url) {
      const host = toHostname(ent.url);
      if (host) hostnames.add(host);
    } else if (ent.type === 'mention') {
      // @username — treat as a t.me link.
      hostnames.add('t.me');
    }
  }

  // Fallback regex sweep for anything Telegram didn't tag (rare, but defensive).
  if (text) {
    const matches = text.match(URL_REGEX) || [];
    for (const m of matches) {
      const host = toHostname(m);
      if (host) hostnames.add(host);
    }
  }

  return hostnames;
}

function toHostname(raw) {
  if (!raw) return null;
  let s = raw.trim();
  if (!/^https?:\/\//i.test(s)) s = 'http://' + s;
  try {
    const u = new URL(s);
    return u.hostname.toLowerCase();
  } catch {
    return null;
  }
}

// --- Admin check ----------------------------------------------------------

const adminCache = new Map(); // chatId -> { ids: Set<number>, expires: number }

async function isAdmin(ctx) {
  if (!ctx.from || !ctx.chat) return false;
  const chatId = ctx.chat.id;
  const now = Date.now();
  let entry = adminCache.get(chatId);
  if (!entry || entry.expires < now) {
    try {
      const admins = await ctx.telegram.getChatAdministrators(chatId);
      entry = {
        ids: new Set(admins.map((a) => a.user.id)),
        expires: now + 60_000, // cache for 60s
      };
      adminCache.set(chatId, entry);
    } catch (err) {
      console.warn('getChatAdministrators failed:', err.message);
      return false;
    }
  }
  return entry.ids.has(ctx.from.id);
}

// --- Bot ------------------------------------------------------------------

const bot = new Telegraf(BOT_TOKEN);

bot.start((ctx) => ctx.reply('Link-guard bot is active. Add me as admin with delete-messages permission.'));

bot.command('listlinks', async (ctx) => {
  if (ctx.chat.type === 'private') return ctx.reply('Run this inside a group.');
  if (!(await isAdmin(ctx))) return; // silent for non-admins
  if (whitelist.size === 0) return ctx.reply('Whitelist is empty. All links will be removed.');
  const list = [...whitelist].sort().map((d) => `• ${d}`).join('\n');
  return ctx.reply(`Approved domains (${whitelist.size}):\n${list}`);
});

bot.command('addlink', async (ctx) => {
  if (ctx.chat.type === 'private') return ctx.reply('Run this inside a group.');
  if (!(await isAdmin(ctx))) return;
  const arg = ctx.message.text.split(/\s+/).slice(1).join(' ').trim();
  if (!arg) return ctx.reply('Usage: /addlink <domain>  (e.g. /addlink youtube.com)');
  const host = toHostname(arg);
  if (!host) return ctx.reply(`Could not parse "${arg}" as a domain.`);
  if (whitelist.has(host)) return ctx.reply(`Already approved: ${host}`);
  whitelist.add(host);
  saveWhitelist(whitelist);
  return ctx.reply(`Added to whitelist: ${host}`);
});

bot.command('removelink', async (ctx) => {
  if (ctx.chat.type === 'private') return ctx.reply('Run this inside a group.');
  if (!(await isAdmin(ctx))) return;
  const arg = ctx.message.text.split(/\s+/).slice(1).join(' ').trim();
  if (!arg) return ctx.reply('Usage: /removelink <domain>');
  const host = toHostname(arg);
  if (!host || !whitelist.has(host)) return ctx.reply(`Not in whitelist: ${arg}`);
  whitelist.delete(host);
  saveWhitelist(whitelist);
  return ctx.reply(`Removed from whitelist: ${host}`);
});

// Guard handler — runs on every message in a group.
bot.on(['message', 'edited_message'], async (ctx, next) => {
  const msg = ctx.message || ctx.editedMessage;
  if (!msg || !ctx.chat) return next?.();
  if (ctx.chat.type !== 'group' && ctx.chat.type !== 'supergroup') return next?.();

  // Skip commands handled above.
  const text = msg.text || msg.caption || '';
  if (text.startsWith('/')) return next?.();

  // Admins bypass.
  if (await isAdmin(ctx)) return next?.();

  const hosts = extractHostnames(msg);
  if (hosts.size === 0) return next?.();

  const offending = [...hosts].filter((h) => !whitelist.has(h));
  if (offending.length === 0) return next?.();

  const user = msg.from;
  const name = user.username ? `@${user.username}` : (user.first_name || 'user');

  try {
    await ctx.telegram.deleteMessage(ctx.chat.id, msg.message_id);
  } catch (err) {
    console.warn(`[guard] could not delete msg ${msg.message_id}:`, err.message);
  }

  try {
    const warn = await ctx.telegram.sendMessage(
      ctx.chat.id,
      `${name}, your message was removed — link(s) not approved: ${offending.join(', ')}`
    );
    // Auto-delete the warning after 10s to keep the chat clean.
    setTimeout(() => {
      ctx.telegram.deleteMessage(ctx.chat.id, warn.message_id).catch(() => {});
    }, 10_000);
  } catch (err) {
    console.warn('[guard] could not send warning:', err.message);
  }

  console.log(
    `[guard] deleted msg from ${name} (id=${user.id}) in chat ${ctx.chat.id} — bad hosts: ${offending.join(', ')}`
  );
});

bot.catch((err, ctx) => {
  console.error(`[telegraf] error for ${ctx.updateType}:`, err);
});

bot.launch().then(() => console.log('Link-guard bot running.'));

process.once('SIGINT', () => bot.stop('SIGINT'));
process.once('SIGTERM', () => bot.stop('SIGTERM'));
