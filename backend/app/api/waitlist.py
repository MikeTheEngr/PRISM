"""
PRISM Backend — Waitlist API

Migrated from the standalone prism-waitlist service into this unified
backend as part of consolidating into one growing API.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr

from app.core.database import get_supabase

router = APIRouter(prefix="/waitlist", tags=["waitlist"])


class WaitlistRequest(BaseModel):
    email: EmailStr
    source: str = "landing_page"


class WaitlistResponse(BaseModel):
    success: bool
    message: str


@router.post("", response_model=WaitlistResponse)
def join_waitlist(payload: WaitlistRequest):
    supabase = get_supabase()
    email = payload.email.lower().strip()

    existing = supabase.table("waitlist").select("id").eq("email", email).execute()

    if existing.data and len(existing.data) > 0:
        return WaitlistResponse(success=True, message="You're already on the waitlist!")

    try:
        supabase.table("waitlist").insert({"email": email, "source": payload.source}).execute()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to join waitlist: {str(e)}")

    return WaitlistResponse(success=True, message="You're on the list. We'll be in touch soon.")


@router.get("/count")
def waitlist_count():
    supabase = get_supabase()
    result = supabase.table("waitlist").select("id", count="exact").execute()
    return {"count": result.count if result.count is not None else 0}
