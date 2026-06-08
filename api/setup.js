const { createBot } = require('../lib/bot');
const { seedIfEmpty, listDomains } = require('../lib/whitelist');

module.exports = async function handler(req, res) {
  const setupSecret = process.env.SETUP_SECRET;
  if (!setupSecret) {
    res.status(500).json({ error: 'SETUP_SECRET is not configured on the server.' });
    return;
  }
  if (req.query.secret !== setupSecret) {
    res.status(401).json({ error: 'unauthorized' });
    return;
  }

  const host = req.headers['x-forwarded-host'] || req.headers.host;
  if (!host) {
    res.status(500).json({ error: 'could not determine deployment host' });
    return;
  }
  const url = `https://${host}/api/telegram`;

  try {
    const bot = createBot();
    await bot.telegram.setWebhook(url, {
      secret_token: process.env.WEBHOOK_SECRET || undefined,
      allowed_updates: ['message', 'edited_message'],
      drop_pending_updates: req.query.reset === '1',
    });
    const info = await bot.telegram.getWebhookInfo();
    const seeded = await seedIfEmpty();
    const domains = await listDomains();
    res.status(200).json({ ok: true, webhook_url: url, info, seeded, domains });
  } catch (err) {
    console.error('[setup] error:', err);
    res.status(500).json({ ok: false, error: err.message });
  }
};
