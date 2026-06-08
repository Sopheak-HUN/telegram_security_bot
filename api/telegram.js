const { createBot } = require('../lib/bot');

let _bot;
function getBot() {
  if (!_bot) _bot = createBot();
  return _bot;
}

module.exports = async function handler(req, res) {
  if (req.method !== 'POST') {
    res.status(405).json({ error: 'method not allowed' });
    return;
  }

  const expected = process.env.WEBHOOK_SECRET;
  if (expected) {
    const got = req.headers['x-telegram-bot-api-secret-token'];
    if (got !== expected) {
      res.status(401).json({ error: 'bad secret token' });
      return;
    }
  }

  try {
    await getBot().handleUpdate(req.body);
  } catch (err) {
    console.error('[webhook] handler error:', err);
  }

  // Always 200 — anything else makes Telegram retry the same update.
  res.status(200).end();
};
