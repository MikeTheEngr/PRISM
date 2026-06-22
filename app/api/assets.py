"""
PRISM Backend — Assets API

Serves unified price data across crypto and stocks. Pulls the asset
registry from Supabase, then fetches live prices from the appropriate
provider per asset class.
"""

import asyncio
from fastapi import APIRouter, HTTPException

from app.core.database import get_supabase
from app.services.coingecko_client import fetch_crypto_prices_batch
from app.services.alpha_vantage_client import fetch_stock_price
from app.models.market import AssetPrice

router = APIRouter(prefix="/assets", tags=["assets"])


@router.get("", response_model=list[AssetPrice])
async def list_assets():
    """
    Returns live price data for all active assets (crypto + stocks combined).
    This powers the Unified Dashboard's main asset list.
    """
    supabase = get_supabase()
    result = supabase.table("assets").select("*").eq("is_active", True).execute()
    assets = result.data

    if not assets:
        return []

    crypto_assets = [a for a in assets if a["asset_class"] == "crypto"]
    stock_assets = [a for a in assets if a["asset_class"] == "stock"]

    prices: list[AssetPrice] = []

    # Crypto — single batched call to conserve rate limit
    if crypto_assets:
        crypto_prices = await fetch_crypto_prices_batch(
            [{"symbol": a["symbol"], "provider_id": a["provider_id"], "name": a["name"]} for a in crypto_assets]
        )
        prices.extend(crypto_prices)

    # Stocks — sequential, since Alpha Vantage free tier is heavily rate-limited.
    # Failures for individual stocks are skipped, not fatal to the whole response.
    for asset in stock_assets:
        stock_price = await fetch_stock_price(asset["symbol"], asset["name"])
        if stock_price:
            prices.append(stock_price)

    return prices


@router.get("/{symbol}", response_model=AssetPrice)
async def get_asset(symbol: str):
    """
    Returns live price data for a single asset. Powers the Asset Detail View.
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
            detail=f"Price data temporarily unavailable for '{symbol}'. Please try again shortly.",
        )

    return price
