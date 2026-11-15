"""
PRISM Backend — Auth API

Signup, login, token refresh, and profile endpoints.
"""

from fastapi import APIRouter, Depends
from app.models.auth import SignupRequest, LoginRequest, RefreshRequest, AuthResponse, UserProfile
from app.services.auth_service import signup, login, refresh, verify_token

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup", response_model=AuthResponse)
async def register(payload: SignupRequest):
    """
    Create a new PRISM account. All new users start on the Free tier.
    Supabase may send a confirmation email depending on project settings.
    """
    return await signup(payload.email, payload.password)


@router.post("/login", response_model=AuthResponse)
async def sign_in(payload: LoginRequest):
    """
    Authenticate and receive access + refresh tokens.
    Send the access_token as: Authorization: Bearer <access_token>
    """
    return await login(payload.email, payload.password)


@router.post("/refresh", response_model=AuthResponse)
async def refresh_session(payload: RefreshRequest):
    """
    Swap a refresh token for a fresh access token (and a NEW refresh token).
    Refresh tokens are single-use: always store the new one that comes back.
    """
    return await refresh(payload.refresh_token)


@router.get("/me")
async def get_profile(user: UserProfile = Depends(verify_token)):
    """
    Returns the current authenticated user's profile and tier.
    Protected: requires a valid Bearer token.
    """
    return {
        "user_id": user.id,
        "email": user.email,
        "tier": user.tier,
        "is_pro": user.is_pro,
        "early_access": user.early_access,
        "limits": {
            "signals_per_session": user.signal_limit,
            "watchlist_slots": user.watchlist_limit,
        },
    }