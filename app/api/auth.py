"""
PRISM Backend — Auth API

Signup, login, and profile endpoints.
"""

from fastapi import APIRouter, Depends
from app.models.auth import SignupRequest, LoginRequest, AuthResponse, UserProfile
from app.services.auth_service import signup, login, verify_token

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
    Store the access_token on the client and include it as:
    Authorization: Bearer <access_token>
    on all protected requests.
    """
    return await login(payload.email, payload.password)


@router.get("/me")
async def get_profile(user: UserProfile = Depends(verify_token)):
    """
    Returns the current authenticated user's profile and tier.
    Protected — requires valid Bearer token.
    """
    return {
        "user_id": user.id,
        "email": user.email,
        "tier": user.tier,
        "is_pro": user.is_pro,
        "limits": {
            "signals_per_session": user.signal_limit,
            "watchlist_slots": user.watchlist_limit,
        }
    }
