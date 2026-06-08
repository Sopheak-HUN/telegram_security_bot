"""Smoke test for the pure helpers in lib.bot.

Doesn't touch Telegram or Redis — just verifies hostname extraction.
Run with:  .venv/Scripts/python tests/smoke.py
"""

import os
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Stub env vars so importing lib.bot / lib.whitelist doesn't blow up.
os.environ.setdefault("BOT_TOKEN", "test-token")

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
check("nonsense", to_hostname("not a url"), None)

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

print("--- extract_hostnames: mention -> t.me ---")
text = "ping @somebody"
m = fake_msg(
    text=text,
    entities=[fake_entity("mention", 5, 9)],
)
hosts = sorted(extract_hostnames(m))
check("mention treated as t.me", hosts, ["t.me"])

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

print()
print(f"RESULTS: {passed} passed, {failed} failed")
sys.exit(0 if failed == 0 else 1)
