"""
PRISM Backend — CoinGecko Client (Crypto Market Data)

Cached aggressively, since concurrent users would otherwise multiply the
request count fast. Failures are logged (type and status only) instead of
being swallowed silently.
"""

import json
import logging
import httpx
from datetime import datetime, timezone
from typing import Optional

from app.core.cache import get_cache
from app.core.config import get_settings
from app.models.market import AssetPrice
from app.utils.errors import describe_error

logger = logging.getLogger("prism.coingecko")
COINGECKO_BASE = "https://api.coingecko.com/api/v3"


def _headers() -> dict:
    """Sends a CoinGecko Demo key if COINGECKO_API_KEY is set (steadier limits)."""
    key = get_settings().COINGECKO_API_KEY
    return {"x-cg-demo-api-key": key} if key else {}


async def fetch_crypto_price(symbol: str, provider_id: str, name: str) -> Optional[AssetPrice]:
    """
    Fetch current price data for a single crypto asset.
    provider_id is CoinGecko's internal id (e.g. 'bitcoin', not 'BTC').
    """
    cache = get_cache()
    settings = get_settings()
    cache_key = f"price:crypto:{provider_id}"

    cached = await cache.get(cache_key)
    if cached:
        if isinstance(cached, str):
            cached = json.loads(cached)
        cached["is_stale"] = False
        return AssetPrice(**cached)

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(
                f"{COINGECKO_BASE}/simple/price",
                headers=_headers(),
                params={
                    "ids": provider_id,
                    "vs_currencies": "usd",
                    "include_24hr_change": "true",
                    "include_24hr_vol": "true",
                    "include_market_cap": "true",
                },
            )
            resp.raise_for_status()
            data = resp.json().get(provider_id)

            if not data:
                return None

            result = AssetPrice(
                symbol=symbol,
                name=name,
                asset_class="crypto",
                price=data.get("usd", 0),
                change_24h_pct=data.get("usd_24h_change"),
                volume_24h=data.get("usd_24h_vol"),
                market_cap=data.get("usd_market_cap"),
                last_updated=datetime.now(timezone.utc).isoformat(),
                source="coingecko",
                is_stale=False,
            )

            await cache.set(cache_key, result.model_dump(), settings.CACHE_TTL_CRYPTO_PRICE)
            return result

    except Exception as exc:
        # Don't raise: degrade gracefully, but leave a trace.
        logger.warning("coingecko single fetch failed for %s: %s", provider_id, describe_error(exc))
        return None

async def fetch_crypto_prices_batch(assets: list[dict]) -> list[AssetPrice]:
    """
    assets: list of {symbol, provider_id, name} dicts.
    Fetches all in a single CoinGecko call to conserve the rate limit.

    If CoinGecko fails or rate-limits us, the last good prices (kept for 24h)
    are returned marked is_stale=True, so the site shows "delayed" prices
    instead of going empty.
    """
    cache = get_cache()
    settings = get_settings()

    provider_ids = [a["provider_id"] for a in assets]
    cache_key = f"price:crypto:batch:{','.join(sorted(provider_ids))}"
    stale_key = f"{cache_key}:last_good"

    cached = await cache.get(cache_key)
    if cached:
        if isinstance(cached, str):
            cached = json.loads(cached)
        return [AssetPrice(**item) for item in cached]

    async def _stale() -> list[AssetPrice]:
        last = await cache.get(stale_key)
        if not last:
            return []
        if isinstance(last, str):
            last = json.loads(last)
        out = []
        for item in last:
            item["is_stale"] = True
            out.append(AssetPrice(**item))
        logger.warning("serving %d delayed crypto prices from the last-good copy", len(out))
        return out

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{COINGECKO_BASE}/simple/price",
                headers=_headers(),
                params={
                    "ids": ",".join(provider_ids),
                    "vs_currencies": "usd",
                    "include_24hr_change": "true",
                    "include_24hr_vol": "true",
                    "include_market_cap": "true",
                },
            )
            resp.raise_for_status()
            raw = resp.json()

            results = []
            for asset in assets:
                pid = asset["provider_id"]
                data = raw.get(pid)
                if not data:
                    continue
                results.append(
                    AssetPrice(
                        symbol=asset["symbol"],
                        name=asset["name"],
                        asset_class="crypto",
                        price=data.get("usd", 0),
                        change_24h_pct=data.get("usd_24h_change"),
                        volume_24h=data.get("usd_24h_vol"),
                        market_cap=data.get("usd_market_cap"),
                        last_updated=datetime.now(timezone.utc).isoformat(),
                        source="coingecko",
                        is_stale=False,
                    )
                )

            if not results:
                logger.warning("coingecko returned no usable prices (ids may be wrong)")
                return await _stale()

            dumped = [r.model_dump() for r in results]
            await cache.set(cache_key, dumped, settings.CACHE_TTL_CRYPTO_PRICE)
            await cache.set(stale_key, dumped, settings.CACHE_TTL_STALE_FALLBACK)
            return results

    except Exception as exc:
        logger.warning("coingecko batch fetch failed: %s", describe_error(exc))
        return await _stale()


