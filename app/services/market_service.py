"""
PRISM Backend — Market service

One place that turns active `assets` rows into prices, so /assets and /signals
don't each repeat the same crypto-batch + stocks logic. Prices are fetched in
parallel instead of one by one.
"""

import asyncio
import logging
from typing import Optional

from fastapi.concurrency import run_in_threadpool

from app.core.database import get_supabase
from app.models.market import AssetPrice
from app.services.alpha_vantage_client import fetch_stock_price
from app.services.coingecko_client import fetch_crypto_prices_batch

logger = logging.getLogger("prism.market")


async def load_active_assets() -> list[dict]:
    def _query():
        return get_supabase().table("assets").select("*").eq("is_active", True).execute().data

    rows = await run_in_threadpool(_query) or []
    if not rows:
        logger.warning("assets table returned 0 active rows (check SUPABASE_URL / SUPABASE_SERVICE_KEY)")
    return rows


async def load_asset(symbol: str) -> Optional[dict]:
    def _query():
        return (
            get_supabase().table("assets").select("*")
            .eq("symbol", symbol.upper()).eq("is_active", True).execute().data
        )

    rows = await run_in_threadpool(_query)
    return rows[0] if rows else None


async def fetch_prices(assets: list[dict]) -> list[AssetPrice]:
    crypto = [a for a in assets if a["asset_class"] == "crypto"]
    stocks = [a for a in assets if a["asset_class"] == "stock"]

    async def _crypto() -> list[AssetPrice]:
        if not crypto:
            return []
        return await fetch_crypto_prices_batch(
            [{"symbol": a["symbol"], "provider_id": a["provider_id"], "name": a["name"]} for a in crypto]
        )

    async def _stock(a: dict) -> Optional[AssetPrice]:
        return await fetch_stock_price(a["symbol"], a["name"])

    crypto_prices, *stock_prices = await asyncio.gather(_crypto(), *[_stock(a) for a in stocks])
    stock_ok = [p for p in stock_prices if p]

    # Only logs when something is missing, so normal requests stay quiet.
    if len(crypto_prices) < len(crypto) or len(stock_ok) < len(stocks):
        logger.warning(
            "prices missing: crypto %d/%d, stocks %d/%d",
            len(crypto_prices), len(crypto), len(stock_ok), len(stocks),
        )
    return [*crypto_prices, *stock_ok]


async def fetch_price(asset: dict) -> Optional[AssetPrice]:
    prices = await fetch_prices([asset])
    return prices[0] if prices else None