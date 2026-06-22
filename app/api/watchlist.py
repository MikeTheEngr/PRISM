"""
PRISM Backend — Watchlist API

CRUD for a user's tracked assets. Free tier is capped at 3 slots — enforced
here server-side, not just in the UI, since client-side limits are trivially
bypassed and this is exactly the kind of business rule that must live on
the server in a real product.

NOTE: Auth middleware (Step 4) is not yet wired in — these endpoints take
user_id as a parameter for now and will be updated to pull it from a verified
session/JWT once auth is built. Flagged clearly so this isn't mistaken for
the final design.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.database import get_supabase

router = APIRouter(prefix="/watchlist", tags=["watchlist"])

FREE_TIER_LIMIT = 3


class WatchlistAddRequest(BaseModel):
    user_id: str  # TODO: replace with auth-derived user once Step 4 (auth) is built
    asset_symbol: str


@router.get("/{user_id}")
def get_watchlist(user_id: str):
    supabase = get_supabase()

    profile = supabase.table("profiles").select("tier").eq("id", user_id).execute()
    if not profile.data:
        raise HTTPException(status_code=404, detail="User not found")

    watchlist = (
        supabase.table("watchlist")
        .select("id, assets(symbol, name, asset_class)")
        .eq("user_id", user_id)
        .execute()
    )
    return {"items": watchlist.data, "tier": profile.data[0]["tier"]}


@router.post("")
def add_to_watchlist(payload: WatchlistAddRequest):
    supabase = get_supabase()

    profile = supabase.table("profiles").select("tier").eq("id", payload.user_id).execute()
    if not profile.data:
        raise HTTPException(status_code=404, detail="User not found")

    tier = profile.data[0]["tier"]

    if tier == "free":
        current_count = (
            supabase.table("watchlist")
            .select("id", count="exact")
            .eq("user_id", payload.user_id)
            .execute()
        )
        if (current_count.count or 0) >= FREE_TIER_LIMIT:
            raise HTTPException(
                status_code=403,
                detail=f"Free tier is limited to {FREE_TIER_LIMIT} watchlist items. Upgrade to Pro for unlimited tracking.",
            )

    asset = supabase.table("assets").select("id").eq("symbol", payload.asset_symbol.upper()).execute()
    if not asset.data:
        raise HTTPException(status_code=404, detail=f"Asset '{payload.asset_symbol}' not found")

    asset_id = asset.data[0]["id"]

    try:
        supabase.table("watchlist").insert({"user_id": payload.user_id, "asset_id": asset_id}).execute()
    except Exception:
        raise HTTPException(status_code=409, detail="Asset already in watchlist")

    return {"success": True}


@router.delete("/{user_id}/{asset_symbol}")
def remove_from_watchlist(user_id: str, asset_symbol: str):
    supabase = get_supabase()

    asset = supabase.table("assets").select("id").eq("symbol", asset_symbol.upper()).execute()
    if not asset.data:
        raise HTTPException(status_code=404, detail=f"Asset '{asset_symbol}' not found")

    asset_id = asset.data[0]["id"]

    supabase.table("watchlist").delete().eq("user_id", user_id).eq("asset_id", asset_id).execute()
    return {"success": True}
