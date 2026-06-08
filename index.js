// Local long-polling entrypoint. For Vercel deployment, the webhook handler
// in api/telegram.js is used instead. This file is only for local development.

require('dotenv').config();
const { createBot } = require('./lib/bot');

const bot = createBot();
bot.launch().then(() => console.log('Link-guard bot running (long-polling).'));

process.once('SIGINT', () => bot.stop('SIGINT'));
process.once('SIGTERM', () => bot.stop('SIGTERM'));
