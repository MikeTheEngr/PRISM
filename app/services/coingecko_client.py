"""
PRISM Backend — CoinGecko Client (Crypto Market Data)

CoinGecko's free tier has no API key requirement for basic endpoints and
generous rate limits (~10-30 calls/min), making it the right default for
crypto data in Phase 1. Cached aggressively regardless, since concurrent
users would otherwise multiply the request count fast.
"""

import json
import httpx
from datetime import datetime, timezone
from typing import Optional

from app.core.cache import get_cache
from app.core.config import get_settings
from app.models.market import AssetPrice

COINGECKO_BASE = "https://api.coingecko.com/api/v3"


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

    except Exception:
        # On failure, do NOT raise — a fintech dashboard should degrade
        # gracefully (show stale/cached/missing data) rather than crash
        # the whole response for one failed asset.
        return None


async def fetch_crypto_prices_batch(assets: list[dict]) -> list[AssetPrice]:
    """
    assets: list of {symbol, provider_id, name} dicts.
    Fetches all in a single CoinGecko call where possible to conserve rate limit.
    """
    cache = get_cache()
    settings = get_settings()

    provider_ids = [a["provider_id"] for a in assets]
    cache_key = f"price:crypto:batch:{','.join(sorted(provider_ids))}"

    cached = await cache.get(cache_key)
    if cached:
        if isinstance(cached, str):
            cached = json.loads(cached)
        return [AssetPrice(**item) for item in cached]

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{COINGECKO_BASE}/simple/price",
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

            await cache.set(
                cache_key,
                [r.model_dump() for r in results],
                settings.CACHE_TTL_CRYPTO_PRICE,
            )
            return results

    except Exception:
        return []
