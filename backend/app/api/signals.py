"""
PRISM Backend — Signals API

A signal is only returned if generation succeeded and passed validation (see
services/signal_engine.py). We never invent a signal to fill a gap.

Tier gating:
- Anonymous: top 3 signals (a teaser), and NO per-symbol access.
- Free: top 5.   Pro: everything.
The per-symbol endpoint used to have no login check, which let anyone read
every signal one symbol at a time and skip the teaser limit.
"""

import asyncio
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from app.models.auth import UserProfile
from app.models.market import SignalOut
from app.services.auth_service import get_optional_user, verify_token
from app.services.market_service import fetch_price, fetch_prices, load_active_assets, load_asset
from app.services.signal_engine import generate_signal

router = APIRouter(prefix="/signals", tags=["signals"])

# At most this many AI calls at once, so a cold cache doesn't hit provider rate limits.
_LLM_CONCURRENCY = 2


@router.get("", response_model=list[SignalOut])
async def list_signals(user: Optional[UserProfile] = Depends(get_optional_user)):
    assets = await load_active_assets()
    if not assets:
        return []

    prices = await fetch_prices(assets)
    sem = asyncio.Semaphore(_LLM_CONCURRENCY)

    async def _one(price):
        async with sem:
            return await generate_signal(price)

    results = await asyncio.gather(*[_one(p) for p in prices])
    signals = sorted((s for s in results if s), key=lambda s: s.confidence, reverse=True)

    if user is None:
        return signals[:3]
    if user.tier == "free":
        return signals[:5]
    return signals


@router.get("/{symbol}", response_model=SignalOut)
async def get_signal(symbol: str, user: UserProfile = Depends(verify_token)):
    """Single-asset signal. Requires login."""
    asset = await load_asset(symbol)
    if not asset:
        raise HTTPException(status_code=404, detail=f"Asset '{symbol}' not found")

    price = await fetch_price(asset)
    if not price:
        raise HTTPException(
            status_code=503,
            detail=f"Price data unavailable for '{symbol}', cannot generate signal.",
        )

    signal = await generate_signal(price)
    if not signal:
        raise HTTPException(
            status_code=503,
            detail=f"Signal generation temporarily unavailable for '{symbol}'. Please try again shortly.",
        )
    return signal