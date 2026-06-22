"""
PRISM Backend — Signals API

Serves AI-generated signals for assets. A signal is only returned if
generation succeeded and passed validation — see services/signal_engine.py
for why we never fabricate or degrade a signal to "fill in" a gap.
"""

from fastapi import APIRouter, HTTPException

from app.core.database import get_supabase
from app.services.coingecko_client import fetch_crypto_prices_batch
from app.services.alpha_vantage_client import fetch_stock_price
from app.services.signal_engine import generate_signal
from app.models.market import SignalOut

router = APIRouter(prefix="/signals", tags=["signals"])


@router.get("", response_model=list[SignalOut])
async def list_signals():
    """
    Returns signals for all active assets that currently have valid price data.
    Powers the AI Signal Feed screen. Assets without a generatable signal
    are simply omitted from the list, never shown with placeholder data.
    """
    supabase = get_supabase()
    result = supabase.table("assets").select("*").eq("is_active", True).execute()
    assets = result.data

    if not assets:
        return []

    signals: list[SignalOut] = []

    crypto_assets = [a for a in assets if a["asset_class"] == "crypto"]
    stock_assets = [a for a in assets if a["asset_class"] == "stock"]

    if crypto_assets:
        crypto_prices = await fetch_crypto_prices_batch(
            [{"symbol": a["symbol"], "provider_id": a["provider_id"], "name": a["name"]} for a in crypto_assets]
        )
        for price in crypto_prices:
            signal = await generate_signal(price)
            if signal:
                signals.append(signal)

    for asset in stock_assets:
        price = await fetch_stock_price(asset["symbol"], asset["name"])
        if price:
            signal = await generate_signal(price)
            if signal:
                signals.append(signal)

    # Highest confidence first — most actionable signals surface to the top
    signals.sort(key=lambda s: s.confidence, reverse=True)
    return signals


@router.get("/{symbol}", response_model=SignalOut)
async def get_signal(symbol: str):
    """
    Returns the signal for a single asset. Powers the Asset Detail View's
    signal breakdown panel.
    """
    supabase = get_supabase()
    result = supabase.table("assets").select("*").eq("symbol", symbol.upper()).eq("is_active", True).execute()

    if not result.data:
        raise HTTPException(status_code=404, detail=f"Asset '{symbol}' not found")

    asset = result.data[0]

    if asset["asset_class"] == "crypto":
        prices = await fetch_crypto_prices_batch(
            [{"symbol": asset["symbol"], "provider_id": asset["provider_id"], "name": asset["name"]}]
        )
        price = prices[0] if prices else None
    else:
        price = await fetch_stock_price(asset["symbol"], asset["name"])

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
