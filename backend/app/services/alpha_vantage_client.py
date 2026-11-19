"""
PRISM Backend — Alpha Vantage Client (Stock Market Data)

Alpha Vantage's free tier allows roughly 25 requests/day, so:
  - prices are cached for CACHE_TTL_STOCK_PRICE seconds
  - the last good price is kept for 24h and served as "delayed" when the quota
    runs out, so stocks don't vanish
  - only one live call runs at a time
Failures are logged (type and status only; the URL contains the API key and
must never be logged).
"""

import asyncio
import json
import logging
import httpx
from datetime import datetime, timezone
from typing import Optional

from app.core.cache import get_cache
from app.core.config import get_settings
from app.models.market import AssetPrice
from app.utils.errors import describe_error

logger = logging.getLogger("prism.alphavantage")
ALPHA_VANTAGE_BASE = "https://www.alphavantage.co/query"
_http_gate = asyncio.Semaphore(1)  # one live Alpha Vantage call at a time


async def fetch_stock_price(symbol: str, name: str) -> Optional[AssetPrice]:
    """Fetch current price data for a single stock (GLOBAL_QUOTE endpoint)."""
    cache = get_cache()
    settings = get_settings()
    cache_key = f"price:stock:{symbol}"

    cached = await cache.get(cache_key)
    if cached:
        if isinstance(cached, str):
            cached = json.loads(cached)
        cached["is_stale"] = False
        return AssetPrice(**cached)

    stale_key = f"{cache_key}:last_good"

    async def _stale() -> Optional[AssetPrice]:
        """Last known price, flagged stale: quota trouble shows older data
        instead of making the stock disappear."""
        last = await cache.get(stale_key)
        if last:
            last["is_stale"] = True
            return AssetPrice(**last)
        return None

    if not settings.ALPHA_VANTAGE_API_KEY:
        logger.warning("ALPHA_VANTAGE_API_KEY is not set: stock prices are unavailable")
        return await _stale()

    if await cache.get("av:limited"):
        # Alpha Vantage said "quota used up" recently: don't keep asking.
        logger.warning("alpha vantage paused (limit flag set); serving last known price for %s", symbol)
        return await _stale()

    try:
        async with _http_gate, httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(
                ALPHA_VANTAGE_BASE,
                params={
                    "function": "GLOBAL_QUOTE",
                    "symbol": symbol,
                    "apikey": settings.ALPHA_VANTAGE_API_KEY,
                },
            )
            resp.raise_for_status()
            body = resp.json()
            raw = body.get("Global Quote", {})
            limited = "Information" in body or "Note" in body

            if not raw or "05. price" not in raw:
                # Alpha Vantage returns an empty object or a rate-limit message
                # (not an HTTP error) when the quota is exhausted.
                logger.warning("alpha vantage returned no quote for %s (quota exhausted?)", symbol)
                if limited:
                    await cache.set("av:limited", True, 3600)  # stop asking for 1 hour
                return await _stale()

            price = float(raw.get("05. price", 0))
            change_pct_str = raw.get("10. change percent", "0%").replace("%", "")

            result = AssetPrice(
                symbol=symbol,
                name=name,
                asset_class="stock",
                price=price,
                change_24h_pct=float(change_pct_str) if change_pct_str else None,
                volume_24h=float(raw.get("06. volume", 0)) if raw.get("06. volume") else None,
                market_cap=None,  # not provided by GLOBAL_QUOTE
                last_updated=datetime.now(timezone.utc).isoformat(),
                source="alpha_vantage",
                is_stale=False,
            )

            await cache.set(cache_key, result.model_dump(), settings.CACHE_TTL_STOCK_PRICE)
            await cache.set(stale_key, result.model_dump(), settings.CACHE_TTL_STALE_FALLBACK)
            return result

    except Exception as exc:
        logger.warning("alpha vantage fetch failed for %s: %s", symbol, describe_error(exc))
        return await _stale()