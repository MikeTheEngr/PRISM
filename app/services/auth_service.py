"""
PRISM Backend — Auth Service

Handles user signup, login, and JWT verification using Supabase Auth.
All protected endpoints go through verify_token() to extract the user
and their tier before processing the request.

Design decisions:
- Supabase Auth handles the heavy lifting (token issuance, refresh, expiry)
- We maintain our own profiles table (linked to auth.users) for app-level
  data like tier, preferences, etc. that Supabase Auth doesn't store
- Tokens are verified server-side on every protected request — no client
  trust, no "just check the frontend" shortcuts
"""

from fastapi import HTTPException, Header
from supabase import AuthApiError

from app.core.database import get_supabase
from app.models.auth import UserProfile


async def signup(email: str, password: str) -> dict:
    """
    Create a new user account. Returns session tokens on success.
    Profile row is created automatically via Supabase trigger or
    explicitly here as a fallback.
    """
    supabase = get_supabase()

    try:
        response = supabase.auth.sign_up({
            "email": email,
            "password": password,
        })
    except AuthApiError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not response.user:
        raise HTTPException(status_code=400, detail="Signup failed — no user returned.")

    # Explicitly create the profile row
    try:
        supabase.table("profiles").upsert({
            "id": response.user.id,
            "email": email,
            "tier": "free",
        }).execute()
    except Exception as e:
        # Log but don't fail signup — profile can be recreated on next login
        print(f"Warning: Profile creation failed for {email}: {e}")

    return {
        "user_id": response.user.id,
        "email": response.user.email,
        "tier": "free",
        "access_token": response.session.access_token if response.session else None,
        "refresh_token": response.session.refresh_token if response.session else None,
        "message": "Account created successfully. Check your email to confirm."
    }


async def login(email: str, password: str) -> dict:
    """
    Authenticate an existing user. Returns session tokens on success.
    """
    supabase = get_supabase()

    try:
        response = supabase.auth.sign_in_with_password({
            "email": email,
            "password": password,
        })
    except AuthApiError as e:
        # Don't leak whether email exists — use generic message
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    if not response.user or not response.session:
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    # Fetch tier from profiles table, auto-create if missing
    profile = supabase.table("profiles").select("tier").eq("id", response.user.id).execute()
    if not profile.data:
        # Profile missing — create it now (handles edge cases from signup)
        supabase.table("profiles").upsert({
            "id": response.user.id,
            "email": email,
            "tier": "free",
        }).execute()
        tier = "free"
    else:
        tier = profile.data[0]["tier"]

    return {
        "user_id": response.user.id,
        "email": response.user.email,
        "tier": tier,
        "access_token": response.session.access_token,
        "refresh_token": response.session.refresh_token,
    }


async def verify_token(authorization: str = Header(...)) -> UserProfile:
    """
    FastAPI dependency — extracts and verifies the JWT from Authorization header.
    Usage: add `user: UserProfile = Depends(verify_token)` to any protected endpoint.

    Returns a UserProfile with id, email, and tier so endpoints can
    make tier-based decisions without an extra DB call.
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header format.")

    token = authorization.replace("Bearer ", "").strip()
    supabase = get_supabase()

    try:
        user_response = supabase.auth.get_user(token)
    except AuthApiError:
        raise HTTPException(status_code=401, detail="Invalid or expired token.")

    if not user_response or not user_response.user:
        raise HTTPException(status_code=401, detail="Invalid or expired token.")

    user = user_response.user

    # Fetch tier from profiles
    profile = supabase.table("profiles").select("tier").eq("id", user.id).execute()
    tier = profile.data[0]["tier"] if profile.data else "free"

    return UserProfile(
        id=user.id,
        email=user.email,
        tier=tier,
    )


async def get_optional_user(authorization: str = Header(default=None)) -> UserProfile | None:
    """
    Optional auth dependency — returns a UserProfile if a valid token is present,
    or None if no token provided. Used for endpoints that serve both
    authenticated and anonymous users differently (e.g. signal feed with
    limited results for anonymous, full feed for Pro users).
    """
    if not authorization:
        return None
    try:
        return await verify_token(authorization)
    except HTTPException:
        return None