"""Smoke test for pure helpers in lib.bot and gating logic in lib.ai.

Doesn't touch Telegram, Redis, or Gemini — just verifies hostname extraction
and that the AI classifier fails open in all configured-off / out-of-range
cases. Real Gemini calls would need GEMINI_API_KEY + a live Upstash.

Run with:  .venv/Scripts/python tests/smoke.py
"""

import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Stub env vars so importing the modules doesn't blow up at module load.
os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.pop("GEMINI_API_KEY", None)  # explicitly disable AI for these tests

from lib.ai import _cache_key, is_spam  # noqa: E402
from lib.bot import URL_REGEX, extract_hostnames, to_hostname  # noqa: E402


def fake_msg(text=None, caption=None, entities=None, caption_entities=None):
    return SimpleNamespace(
        text=text,
        caption=caption,
        entities=entities or [],
        caption_entities=caption_entities or [],
    )


def fake_entity(type_, offset, length, url=None):
    return SimpleNamespace(type=type_, offset=offset, length=length, url=url)


passed = 0
failed = 0


def check(label, got, expected):
    global passed, failed
    ok = got == expected
    mark = "OK " if ok else "FAIL"
    print(f"  [{mark}] {label}")
    if not ok:
        print(f"        got:      {got}")
        print(f"        expected: {expected}")
        failed += 1
    else:
        passed += 1


print("--- to_hostname ---")
check("bare domain", to_hostname("youtube.com"), "youtube.com")
check("http url", to_hostname("http://youtube.com/x"), "youtube.com")
check("https url + path", to_hostname("https://m.youtube.com/watch?v=abc"), "m.youtube.com")
check("uppercase", to_hostname("Https://YouTube.COM"), "youtube.com")
check("empty", to_hostname(""), None)
check("None", to_hostname(None), None)
check("nonsense rejected", to_hostname("not a url"), None)

print("--- URL_REGEX ---")
sample = "hey check youtube.com and https://x.com/foo, also a@b.com (email)"
matches = URL_REGEX.findall(sample)
check("regex finds youtube.com", "youtube.com" in matches, True)
check("regex finds x.com path", any("x.com" in m for m in matches), True)

print("--- extract_hostnames: plain text ---")
m = fake_msg(text="check this youtube.com and https://github.com/foo")
hosts = sorted(extract_hostnames(m))
check("plain text URLs", hosts, ["github.com", "youtube.com"])

print("--- extract_hostnames: text_link entity ---")
text = "click here"
m = fake_msg(
    text=text,
    entities=[fake_entity("text_link", 0, len(text), url="https://evil.example/")],
)
hosts = sorted(extract_hostnames(m))
check("text_link entity hostname", hosts, ["evil.example"])

print("--- extract_hostnames: caption fallback ---")
m = fake_msg(text=None, caption="watch on twitch.tv now")
hosts = sorted(extract_hostnames(m))
check("caption is scanned", hosts, ["twitch.tv"])

print("--- extract_hostnames: subdomain distinct from apex ---")
m = fake_msg(text="m.youtube.com vs youtube.com")
hosts = sorted(extract_hostnames(m))
check("subdomain + apex both present", hosts, ["m.youtube.com", "youtube.com"])

print("--- extract_hostnames: no URL ---")
m = fake_msg(text="hello world, nothing here")
hosts = extract_hostnames(m)
check("no URL -> empty", hosts, [])

print("--- extract_hostnames: URL entity (Telegram-tagged) ---")
text = "see https://docs.python.org/3/ for details"
url = "https://docs.python.org/3/"
m = fake_msg(text=text, entities=[fake_entity("url", text.index(url), len(url))])
hosts = sorted(extract_hostnames(m))
check("url entity hostname", hosts, ["docs.python.org"])

print("--- ai.is_spam: gating (no GEMINI_API_KEY) ---")
loop = asyncio.new_event_loop()
try:
    check("empty -> False", loop.run_until_complete(is_spam("")), False)
    check("None -> False", loop.run_until_complete(is_spam(None)), False)  # type: ignore
    check("too short -> False", loop.run_until_complete(is_spam("hi")), False)
    check("too long -> False", loop.run_until_complete(is_spam("x" * 700)), False)
    # When key is missing, every call short-circuits to False before any
    # network or Redis call.
    check(
        "normal text -> False (no key)",
        loop.run_until_complete(is_spam("this is a normal-length message that would otherwise be classified")),
        False,
    )
finally:
    loop.close()

print("--- ai._cache_key: determinism ---")
k1 = _cache_key("Hello World")
k2 = _cache_key("  hello world  ")  # whitespace + case normalized
check("normalization", k1, k2)
check("key has prefix", k1.startswith("spam:"), True)
check("key has sha1 length", len(k1), len("spam:") + 40)

print()
print(f"RESULTS: {passed} passed, {failed} failed")
sys.exit(0 if failed == 0 else 1)
