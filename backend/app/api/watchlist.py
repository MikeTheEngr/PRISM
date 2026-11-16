"""
PRISM Backend — Watchlist API

CRUD for a user's tracked assets. Now properly protected with JWT auth —
user_id is extracted from the verified token, not trusted from the request.

Free tier: max 3 watchlist slots (enforced server-side)
Pro tier: unlimited
"""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from app.core.database import get_supabase
from app.services.auth_service import verify_token
from app.models.auth import UserProfile

router = APIRouter(prefix="/watchlist", tags=["watchlist"])

FREE_TIER_LIMIT = 3


class WatchlistAddRequest(BaseModel):
    asset_symbol: str


@router.get("")
def get_watchlist(user: UserProfile = Depends(verify_token)):
    supabase = get_supabase()

    watchlist = (
        supabase.table("watchlist")
        .select("id, created_at, assets(symbol, name, asset_class)")
        .eq("user_id", user.id)
        .execute()
    )

    return {
        "items": watchlist.data,
        "count": len(watchlist.data),
        "tier": user.tier,
        "limit": user.watchlist_limit,
        "slots_remaining": (
            max(0, user.watchlist_limit - len(watchlist.data))
            if user.watchlist_limit is not None
            else None
        )
    }


@router.post("")
def add_to_watchlist(
    payload: WatchlistAddRequest,
    user: UserProfile = Depends(verify_token)
):
    supabase = get_supabase()

    if user.tier == "free":
        current_count = (
            supabase.table("watchlist")
            .select("id", count="exact")
            .eq("user_id", user.id)
            .execute()
        )
        if (current_count.count or 0) >= FREE_TIER_LIMIT:
            raise HTTPException(
                status_code=403,
                detail=f"Free tier is limited to {FREE_TIER_LIMIT} watchlist slots. Upgrade to Pro for unlimited tracking.",
            )

    asset = (
        supabase.table("assets")
        .select("id")
        .eq("symbol", payload.asset_symbol.upper())
        .execute()
    )
    if not asset.data:
        raise HTTPException(status_code=404, detail=f"Asset '{payload.asset_symbol}' not found.")

    asset_id = asset.data[0]["id"]

    existing = (
        supabase.table("watchlist")
        .select("id")
        .eq("user_id", user.id)
        .eq("asset_id", asset_id)
        .execute()
    )
    if existing.data:
        raise HTTPException(status_code=409, detail=f"{payload.asset_symbol.upper()} is already in your watchlist.")

    supabase.table("watchlist").insert({"user_id": user.id, "asset_id": asset_id}).execute()

    return {"success": True, "message": f"{payload.asset_symbol.upper()} added to watchlist."}


@router.delete("/{asset_symbol}")
def remove_from_watchlist(
    asset_symbol: str,
    user: UserProfile = Depends(verify_token)
):
    supabase = get_supabase()

    asset = (
        supabase.table("assets")
        .select("id")
        .eq("symbol", asset_symbol.upper())
        .execute()
    )
    if not asset.data:
        raise HTTPException(status_code=404, detail=f"Asset '{asset_symbol}' not found.")

    asset_id = asset.data[0]["id"]

    supabase.table("watchlist").delete().eq("user_id", user.id).eq("asset_id", asset_id).execute()

    return {"success": True, "message": f"{asset_symbol.upper()} removed from watchlist."}