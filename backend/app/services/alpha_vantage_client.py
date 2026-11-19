"""
PRISM Backend — Alpha Vantage Client (Stock Market Data)

Alpha Vantage's free tier allows about 25 requests/day AND roughly 1 request per
second, so:
  - prices are cached for CACHE_TTL_STOCK_PRICE seconds
  - the last good price is kept for 24h and served as "delayed" when a call fails
  - only one live call runs at a time, with a gap between calls
  - after waiting for its turn, a call re-checks the cache (another request may
    have just fetched the same stock)
  - a "slow down" reply pauses calls for 20 seconds; a "daily limit" reply for 1 hour
Failures are logged without URLs (the URL contains the API key).
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
_http_gate = asyncio.Semaphore(1)   # one live Alpha Vantage call at a time
_MIN_GAP_SECONDS = 1.3              # free keys allow about 1 request per second


async def fetch_stock_price(symbol: str, name: str) -> Optional[AssetPrice]:
    """Fetch current price data for a single stock (GLOBAL_QUOTE endpoint)."""
    cache = get_cache()
    settings = get_settings()
    cache_key = f"price:stock:{symbol}"
    stale_key = f"{cache_key}:last_good"

    async def _cached(key: str, stale: bool) -> Optional[AssetPrice]:
        data = await cache.get(key)
        if not data:
            return None
        if isinstance(data, str):
            data = json.loads(data)
        data["is_stale"] = stale
        return AssetPrice(**data)

    hit = await _cached(cache_key, False)
    if hit:
        return hit

    if not settings.ALPHA_VANTAGE_API_KEY:
        logger.warning("ALPHA_VANTAGE_API_KEY is not set: stock prices are unavailable")
        return await _cached(stale_key, True)

    if await cache.get("av:limited"):
        logger.warning("alpha vantage paused (limit flag set); serving last known price for %s", symbol)
        return await _cached(stale_key, True)

    async with _http_gate:
        # Someone else may have fetched this stock while we waited our turn.
        hit = await _cached(cache_key, False)
        if hit:
            return hit

        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
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

            if not raw or "05. price" not in raw:
                msg = str(body.get("Information") or body.get("Note") or "")
                if msg:
                    daily = "per day" in msg.lower() or "daily" in msg.lower()
                    await cache.set("av:limited", True, 3600 if daily else 20)
                    logger.warning(
                        "alpha vantage %s limit reached (fetching %s)",
                        "daily" if daily else "rate", symbol,
                    )
                else:
                    logger.warning("alpha vantage returned no quote for %s", symbol)
                return await _cached(stale_key, True)

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
            return await _cached(stale_key, True)

        finally:
            await asyncio.sleep(_MIN_GAP_SECONDS)  # spacing between live calls