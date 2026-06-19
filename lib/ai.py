"""AI-powered spam classifier for messages that contain no URLs.

Uses Google Gemini 2.0 Flash via the `google-genai` SDK. Free tier on
aistudio.google.com is plenty for most groups (1500 req/day).

URLs are still handled by the whitelist (cheap + deterministic). The classifier
only runs for plain-text messages where the whitelist can't help — e.g. crypto
scams, gambling promos, drug sales without an explicit link.

Verdicts are cached in Redis for an hour so duplicate spam messages (the
copy-paste flood pattern) only cost one API call.
"""

import hashlib
import os

from .whitelist import _get_redis

CACHE_TTL_SECONDS = 3600
MIN_LENGTH = 10        # below this, treat as too short to classify
MAX_LENGTH = 600       # above this, skip — likely legit long-form text

MODEL = "gemini-2.0-flash"

SYSTEM_PROMPT = """You are a content moderator for a Telegram group chat where members speak Khmer and English.

Decide whether the user's message is SPAM or OK.

SPAM includes (any one is enough):
- Crypto / investment / forex / trading scams
- Online casino, betting, lottery, slots promos
- Drug, weapon, or other illegal-goods sales
- Pyramid / MLM recruitment ("earn $X/day from home")
- Phishing or fake job offers
- Sexual solicitation, adult-content baiting
- Generic "DM me", "click my profile", "private message me for details" baits
- Promo for unlicensed financial services

OK includes:
- Normal conversation, questions, jokes, casual chat
- News, sports, work, school discussion
- Polite requests, thanks, greetings
- Technical / educational content

Reply with exactly one word: SPAM or OK. No punctuation, no explanation."""

_client = None


def _get_client():
    """Lazy-init the Gemini client. Returns None if not configured."""
    global _client
    if _client is not None:
        return _client
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None
    try:
        from google import genai
    except ImportError:
        print("[ai] google-genai SDK not installed — skipping spam classification.")
        return None
    _client = genai.Client(api_key=api_key)
    return _client


def _cache_key(text: str) -> str:
    normalized = text.strip().lower()
    digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()
    return f"spam:{digest}"


async def is_spam(text: str) -> bool:
    """Return True if `text` is classified as spam by the AI moderator.

    Returns False (fail-open) for: empty / too-short / too-long text, missing
    GEMINI_API_KEY, Gemini API errors, or any other failure. We never delete a
    message based on a failed AI call.
    """
    if not text:
        return False
    stripped = text.strip()
    if len(stripped) < MIN_LENGTH or len(stripped) > MAX_LENGTH:
        return False

    client = _get_client()
    if client is None:
        return False

    key = _cache_key(stripped)

    try:
        cached = await _get_redis().get(key)
        if cached is not None:
            return cached == "1"
    except Exception as err:
        print(f"[ai] cache read failed (continuing): {err}")

    try:
        response = await client.aio.models.generate_content(
            model=MODEL,
            contents=stripped,
            config={
                "system_instruction": SYSTEM_PROMPT,
                "max_output_tokens": 4,
                "temperature": 0,
            },
        )
        verdict_text = (response.text or "").strip().upper()
        is_spam_result = verdict_text.startswith("SPAM")
    except Exception as err:
        print(f"[ai] classification failed: {err}")
        return False

    try:
        await _get_redis().set(key, "1" if is_spam_result else "0", ex=CACHE_TTL_SECONDS)
    except Exception as err:
        print(f"[ai] cache write failed (continuing): {err}")

    if is_spam_result:
        print(f"[ai] SPAM verdict for: {stripped[:80]!r}")
    return is_spam_result
