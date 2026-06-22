"""
PRISM Backend — AI Signal Engine

Generates predictive signals for an asset using Groq (primary) with
automatic fallback to Gemini if Groq fails or is rate-limited.

DESIGN PRINCIPLES (non-negotiable for a fintech product):
1. Every signal is probabilistic, never a bare directive. The model is
   instructed to output a confidence score and reasoning, never "buy" or "sell"
   commands.
2. Signals are generated from real price/volume/change data, not vibes —
   the prompt is grounded in actual numbers fetched moments before.
3. Output is strictly validated (Pydantic) before ever reaching a user.
   A malformed or out-of-range AI response is discarded, not shown.
4. Every signal carries a disclaimer at the data model level (see
   models/market.py), not just as a UI afterthought — so it's impossible
   to serve a signal without one.
5. Signals are cached/expired on a schedule, never regenerated on every
   page view — protects both API cost and consistency (a user refreshing
   the page shouldn't see the direction flip-flop from prompt randomness).
"""

import json
import re
from datetime import datetime, timezone, timedelta
from typing import Optional

import httpx
from pydantic import BaseModel, ValidationError, field_validator

from app.core.config import get_settings
from app.core.cache import get_cache
from app.models.market import AssetPrice, SignalOut

settings = get_settings()

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"

GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"


class _RawSignal(BaseModel):
    """Strict schema the AI's JSON output must conform to before we trust it."""
    direction: str
    confidence: float
    reasoning: str

    @field_validator("direction")
    @classmethod
    def validate_direction(cls, v: str) -> str:
        v = v.lower().strip()
        if v not in ("bullish", "bearish", "neutral"):
            raise ValueError(f"Invalid direction: {v}")
        return v

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, v: float) -> float:
        if not (0 <= v <= 100):
            raise ValueError(f"Confidence out of range: {v}")
        return round(v, 1)

    @field_validator("reasoning")
    @classmethod
    def validate_reasoning(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 10:
            raise ValueError("Reasoning too short to be meaningful")
        if len(v) > 500:
            v = v[:497] + "..."
        return v


def _build_prompt(asset: AssetPrice) -> str:
    change_str = f"{asset.change_24h_pct:+.2f}%" if asset.change_24h_pct is not None else "unknown"
    volume_str = f"${asset.volume_24h:,.0f}" if asset.volume_24h else "unknown"

    return f"""You are a financial pattern analysis engine. Analyze this asset's current data and output a signal.

Asset: {asset.name} ({asset.symbol})
Asset class: {asset.asset_class}
Current price: ${asset.price:,.2f}
24h change: {change_str}
24h volume: {volume_str}

Based on this data, provide a pattern-based signal. Be conservative — only express
high confidence (above 75) when the data shows a genuinely strong, clear pattern.
Most situations warrant moderate confidence (40-65) or neutral direction, since
short-term price/volume data alone rarely justifies high-confidence directional calls.

Respond with ONLY valid JSON, no markdown formatting, no other text:
{{
  "direction": "bullish" | "bearish" | "neutral",
  "confidence": <number 0-100>,
  "reasoning": "<1-2 sentences, plain language, grounded in the specific numbers above>"
}}"""


def _extract_json(text: str) -> Optional[dict]:
    """AI models sometimes wrap JSON in markdown fences despite instructions. Strip defensively."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Last resort: try to find the first {...} block
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                return None
        return None


async def _call_groq(prompt: str) -> Optional[dict]:
    if not settings.GROQ_API_KEY:
        return None
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                GROQ_API_URL,
                headers={"Authorization": f"Bearer {settings.GROQ_API_KEY}"},
                json={
                    "model": GROQ_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.3,  # low temperature — we want consistent, grounded output
                    "max_tokens": 300,
                },
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            return _extract_json(content)
    except Exception:
        return None


async def _call_gemini(prompt: str) -> Optional[dict]:
    if not settings.GEMINI_API_KEY:
        return None
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{GEMINI_API_URL}?key={settings.GEMINI_API_KEY}",
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"temperature": 0.3, "maxOutputTokens": 300},
                },
            )
            resp.raise_for_status()
            content = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
            return _extract_json(content)
    except Exception:
        return None


async def generate_signal(asset: AssetPrice) -> Optional[SignalOut]:
    """
    Generate a signal for one asset. Tries Groq first, falls back to Gemini.
    Returns None if both fail or output fails validation — callers must
    handle the absence of a signal gracefully (never fabricate one).
    """
    cache = get_cache()
    cache_key = f"signal:{asset.asset_class}:{asset.symbol}"

    cached = await cache.get(cache_key)
    if cached:
        if isinstance(cached, str):
            cached = json.loads(cached)
        return SignalOut(**cached)

    prompt = _build_prompt(asset)

    raw = await _call_groq(prompt)
    model_used = "groq"

    if raw is None:
        raw = await _call_gemini(prompt)
        model_used = "gemini"

    if raw is None:
        return None

    try:
        validated = _RawSignal(**raw)
    except ValidationError:
        # AI returned something that doesn't meet our schema/safety bar.
        # We do NOT show a degraded/guessed signal — absence is safer than
        # a malformed or out-of-spec one in a financial context.
        return None

    signal = SignalOut(
        symbol=asset.symbol,
        direction=validated.direction,
        confidence=validated.confidence,
        reasoning=validated.reasoning,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )

    await cache.set(cache_key, signal.model_dump(), settings.CACHE_TTL_SIGNAL)
    return signal
