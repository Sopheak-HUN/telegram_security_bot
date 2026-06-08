const { Telegraf } = require('telegraf');
const {
  checkHosts,
  addDomain,
  removeDomain,
  listDomains,
} = require('./whitelist');

const URL_REGEX = /\b((?:https?:\/\/)?(?:[a-z0-9-]+\.)+[a-z]{2,}(?:[/?#][^\s]*)?)/gi;

const HOSTNAME_RE = /^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$/;

function toHostname(raw) {
  if (!raw) return null;
  let s = String(raw).trim();
  if (!/^https?:\/\//i.test(s)) s = 'http://' + s;
  let host;
  try {
    host = new URL(s).hostname.toLowerCase();
  } catch {
    return null;
  }
  if (!host || !HOSTNAME_RE.test(host)) return null;
  return host;
}

function extractHostnames(message) {
  const hostnames = new Set();
  const text = message.text || message.caption || '';
  const entities = message.entities || message.caption_entities || [];

  for (const ent of entities) {
    if (ent.type === 'url') {
      const host = toHostname(text.slice(ent.offset, ent.offset + ent.length));
      if (host) hostnames.add(host);
    } else if (ent.type === 'text_link' && ent.url) {
      const host = toHostname(ent.url);
      if (host) hostnames.add(host);
    } else if (ent.type === 'mention') {
      hostnames.add('t.me');
    }
  }

  if (text) {
    const matches = text.match(URL_REGEX) || [];
    for (const m of matches) {
      const host = toHostname(m);
      if (host) hostnames.add(host);
    }
  }

  return [...hostnames];
}

const adminCache = new Map();

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
        expires: now + 60_000,
      };
      adminCache.set(chatId, entry);
    } catch (err) {
      console.warn('getChatAdministrators failed:', err.message);
      return false;
    }
  }
  return entry.ids.has(ctx.from.id);
}

function createBot() {
  const token = process.env.BOT_TOKEN;
  if (!token) throw new Error('BOT_TOKEN is not set.');
  const bot = new Telegraf(token);

  bot.start((ctx) =>
    ctx.reply('Link-guard bot is active. Add me as admin with delete-messages permission.')
  );

  bot.command('listlinks', async (ctx) => {
    if (ctx.chat.type === 'private') return ctx.reply('Run this inside a group.');
    if (!(await isAdmin(ctx))) return;
    const domains = await listDomains();
    if (!domains.length) return ctx.reply('Whitelist is empty. All links will be removed.');
    return ctx.reply(
      `Approved domains (${domains.length}):\n` + domains.map((d) => `• ${d}`).join('\n')
    );
  });

  bot.command('addlink', async (ctx) => {
    if (ctx.chat.type === 'private') return ctx.reply('Run this inside a group.');
    if (!(await isAdmin(ctx))) return;
    const arg = ctx.message.text.split(/\s+/).slice(1).join(' ').trim();
    if (!arg) return ctx.reply('Usage: /addlink <domain>  (e.g. /addlink youtube.com)');
    const host = toHostname(arg);
    if (!host) return ctx.reply(`Could not parse "${arg}" as a domain.`);
    const added = await addDomain(host);
    return ctx.reply(added ? `Added to whitelist: ${host}` : `Already approved: ${host}`);
  });

  bot.command('removelink', async (ctx) => {
    if (ctx.chat.type === 'private') return ctx.reply('Run this inside a group.');
    if (!(await isAdmin(ctx))) return;
    const arg = ctx.message.text.split(/\s+/).slice(1).join(' ').trim();
    if (!arg) return ctx.reply('Usage: /removelink <domain>');
    const host = toHostname(arg);
    if (!host) return ctx.reply(`Could not parse "${arg}" as a domain.`);
    const removed = await removeDomain(host);
    return ctx.reply(removed ? `Removed from whitelist: ${host}` : `Not in whitelist: ${host}`);
  });

  bot.on(['message', 'edited_message'], async (ctx, next) => {
    const msg = ctx.message || ctx.editedMessage;
    if (!msg || !ctx.chat) return next?.();
    if (ctx.chat.type !== 'group' && ctx.chat.type !== 'supergroup') return next?.();
    const text = msg.text || msg.caption || '';
    if (text.startsWith('/')) return next?.();
    if (await isAdmin(ctx)) return next?.();

    const hosts = extractHostnames(msg);
    if (!hosts.length) return next?.();

    const approved = await checkHosts(hosts);
    const offending = hosts.filter((_, i) => !approved[i]);
    if (!offending.length) return next?.();

    const user = msg.from;
    const name = user.username ? `@${user.username}` : user.first_name || 'user';

    try {
      await ctx.telegram.deleteMessage(ctx.chat.id, msg.message_id);
    } catch (err) {
      console.warn(`[guard] could not delete msg ${msg.message_id}:`, err.message);
    }

    try {
      await ctx.telegram.sendMessage(
        ctx.chat.id,
        `${name}, your message was removed — link(s) not approved: ${offending.join(', ')}`
      );
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

  return bot;
}

module.exports = { createBot, toHostname, extractHostnames };
