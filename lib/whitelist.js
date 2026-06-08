const fs = require('fs');
const path = require('path');
const { Redis } = require('@upstash/redis');

const KEY = 'whitelist:domains';

let _redis;
function redis() {
  if (_redis) return _redis;
  const url = process.env.UPSTASH_REDIS_REST_URL || process.env.KV_REST_API_URL;
  const token = process.env.UPSTASH_REDIS_REST_TOKEN || process.env.KV_REST_API_TOKEN;
  if (!url || !token) {
    throw new Error(
      'Upstash Redis env vars not set. Need UPSTASH_REDIS_REST_URL / ' +
        'UPSTASH_REDIS_REST_TOKEN (or KV_REST_API_URL / KV_REST_API_TOKEN).'
    );
  }
  _redis = new Redis({ url, token });
  return _redis;
}

async function checkHosts(hosts) {
  if (!hosts.length) return [];
  const r = await redis().smismember(KEY, hosts);
  return r.map((x) => x === 1);
}

async function addDomain(host) {
  return (await redis().sadd(KEY, host)) === 1;
}

async function removeDomain(host) {
  return (await redis().srem(KEY, host)) === 1;
}

async function listDomains() {
  const r = await redis().smembers(KEY);
  return [...r].sort();
}

async function seedIfEmpty() {
  const current = await listDomains();
  if (current.length > 0) return { added: 0, already: current.length };
  const file = path.join(process.cwd(), 'whitelist.json');
  if (!fs.existsSync(file)) return { added: 0, already: 0 };
  try {
    const data = JSON.parse(fs.readFileSync(file, 'utf8'));
    const domains = Array.isArray(data.domains) ? data.domains : [];
    if (!domains.length) return { added: 0, already: 0 };
    await redis().sadd(KEY, ...domains);
    return { added: domains.length, already: 0 };
  } catch (err) {
    return { added: 0, already: 0, error: err.message };
  }
}

module.exports = { checkHosts, addDomain, removeDomain, listDomains, seedIfEmpty };
