"""
PRISM Backend — Assets API

Unified price data across crypto and stocks. The asset list comes from
Supabase; prices come from the right provider per asset class
(see services/market_service.py).
"""

from fastapi import APIRouter, HTTPException

from app.models.market import AssetPrice
from app.services.market_service import fetch_price, fetch_prices, load_active_assets, load_asset

router = APIRouter(prefix="/assets", tags=["assets"])


@router.get("", response_model=list[AssetPrice])
async def list_assets():
    """Live prices for all active assets. Powers the dashboard."""
    assets = await load_active_assets()
    return await fetch_prices(assets) if assets else []


@router.get("/{symbol}", response_model=AssetPrice)
async def get_asset(symbol: str):
    """Live price for one asset. Powers the asset detail view."""
    asset = await load_asset(symbol)
    if not asset:
        raise HTTPException(status_code=404, detail=f"Asset '{symbol}' not found")

    price = await fetch_price(asset)
    if not price:
        raise HTTPException(
            status_code=503,
            detail=f"Price data temporarily unavailable for '{symbol}'. Please try again shortly.",
        )
    return price