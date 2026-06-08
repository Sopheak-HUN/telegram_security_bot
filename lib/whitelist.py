import json
import os
from pathlib import Path

from upstash_redis.asyncio import Redis

KEY = "whitelist:domains"

_redis: Redis | None = None


def _get_redis() -> Redis:
    global _redis
    if _redis is None:
        url = os.environ.get("UPSTASH_REDIS_REST_URL") or os.environ.get("KV_REST_API_URL")
        token = os.environ.get("UPSTASH_REDIS_REST_TOKEN") or os.environ.get("KV_REST_API_TOKEN")
        if not url or not token:
            raise RuntimeError(
                "Upstash Redis env vars not set. Need UPSTASH_REDIS_REST_URL / "
                "UPSTASH_REDIS_REST_TOKEN (or KV_REST_API_URL / KV_REST_API_TOKEN)."
            )
        _redis = Redis(url=url, token=token)
    return _redis


async def check_hosts(hosts: list[str]) -> list[bool]:
    if not hosts:
        return []
    result = await _get_redis().smismember(KEY, *hosts)
    return [bool(x) for x in result]


async def add_domain(host: str) -> bool:
    return (await _get_redis().sadd(KEY, host)) == 1


async def remove_domain(host: str) -> bool:
    return (await _get_redis().srem(KEY, host)) == 1


async def list_domains() -> list[str]:
    members = await _get_redis().smembers(KEY)
    return sorted(members)


async def seed_if_empty() -> dict:
    current = await list_domains()
    if current:
        return {"added": 0, "already": len(current)}
    seed = Path(__file__).resolve().parent.parent / "whitelist.json"
    if not seed.exists():
        return {"added": 0, "already": 0}
    try:
        data = json.loads(seed.read_text(encoding="utf-8"))
        domains = data.get("domains") or []
        if not domains:
            return {"added": 0, "already": 0}
        await _get_redis().sadd(KEY, *domains)
        return {"added": len(domains), "already": 0}
    except Exception as err:
        return {"added": 0, "already": 0, "error": str(err)}
