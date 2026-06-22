"""
PRISM Backend — Alpha Vantage Client (Stock Market Data)

IMPORTANT CONSTRAINT: Alpha Vantage's free tier allows roughly 25 requests/day
total. This is the single biggest constraint on Phase 1's stock coverage and
must be respected aggressively:
  - Long cache TTL (5 min minimum, longer outside market hours)
  - Batch/sequential fetching only at controlled intervals, never per-user-request
  - A background refresh job (not built here yet) should populate cache on a
    schedule rather than relying on user traffic to trigger fetches

If this becomes a bottleneck, Polygon.io is the documented upgrade path
(see Phase 1 roadmap) — this client is written so swapping providers later
only requires changes inside this file, not callers.
"""

import json
import httpx
from datetime import datetime, timezone
from typing import Optional

from app.core.cache import get_cache
from app.core.config import get_settings
from app.models.market import AssetPrice

ALPHA_VANTAGE_BASE = "https://www.alphavantage.co/query"


async def fetch_stock_price(symbol: str, name: str) -> Optional[AssetPrice]:
    """
    Fetch current price data for a single stock.
    Uses GLOBAL_QUOTE endpoint — lightest-weight Alpha Vantage call available.
    """
    cache = get_cache()
    settings = get_settings()
    cache_key = f"price:stock:{symbol}"

    cached = await cache.get(cache_key)
    if cached:
        if isinstance(cached, str):
            cached = json.loads(cached)
        cached["is_stale"] = False
        return AssetPrice(**cached)

    if not settings.ALPHA_VANTAGE_API_KEY:
        # No key configured — fail gracefully rather than throwing,
        # consistent with how the crypto client degrades.
        return None

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
            raw = resp.json().get("Global Quote", {})

            if not raw or "05. price" not in raw:
                # Alpha Vantage returns an empty object or a rate-limit
                # message (not an HTTP error) when the quota is exhausted.
                return None

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
            return result

    except Exception:
        return None
