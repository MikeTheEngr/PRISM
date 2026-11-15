"""
PRISM Backend — Auth Service

Supabase Auth issues/checks tokens; our `profiles` table stores the tier and
the early_access (founding member) flag.

The Supabase client is synchronous, so blocking calls run in a threadpool
(run_in_threadpool) to avoid freezing the whole server on every request.
"""

import logging

from fastapi import Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from supabase import AuthApiError

from app.core.database import get_auth_client, get_supabase, get_token_verifier
from app.models.auth import UserProfile

logger = logging.getLogger("prism.auth")
bearer_scheme = HTTPBearer(auto_error=False)


def _grant_early_access_if_waitlisted(user_id: str, email: str, confirmed: bool) -> bool:
    """
    Marks the profile as a founding member if this email is on the waitlist.
    Only for CONFIRMED emails, so nobody can claim it with someone else's address.
    Never raises: a failure here must not break login.
    """
    if not confirmed:
        return False
    try:
        db = get_supabase()
        hit = (
            db.table("waitlist").select("id")
            .eq("email", email.lower().strip()).limit(1).execute()
        )
        if not hit.data:
            return False
        db.table("profiles").update({"early_access": True}).eq("id", user_id).execute()
        return True
    except Exception:
        logger.exception("early access check failed for user %s", user_id)
        return False


def _signup_sync(email: str, password: str) -> dict:
    auth = get_auth_client()
    try:
        response = auth.auth.sign_up({"email": email, "password": password})
    except AuthApiError as exc:
        # Log the real reason, but don't show it to the user: it can reveal
        # whether an email is already registered.
        logger.info("signup rejected: %s", getattr(exc, "message", "AuthApiError"))
        raise HTTPException(
            status_code=400,
            detail="Could not create the account. Check your details and try again.",
        )

    if not response.user:
        raise HTTPException(status_code=400, detail="Could not create the account.")

    try:
        get_supabase().table("profiles").upsert(
            {"id": response.user.id, "email": email, "tier": "free"}
        ).execute()
    except Exception:
        # Profile is re-created on next login, so don't fail the signup.
        logger.exception("profile creation failed for new user %s", response.user.id)

    return {
        "user_id": response.user.id,
        "email": response.user.email,
        "tier": "free",
        "access_token": response.session.access_token if response.session else None,
        "refresh_token": response.session.refresh_token if response.session else None,
        "message": "Account created successfully. Check your email to confirm.",
    }


def _login_sync(email: str, password: str) -> dict:
    auth = get_auth_client()
    try:
        response = auth.auth.sign_in_with_password({"email": email, "password": password})
    except AuthApiError:
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    if not response.user or not response.session:
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    db = get_supabase()
    profile = db.table("profiles").select("tier, early_access").eq("id", response.user.id).execute()
    if not profile.data:
        db.table("profiles").upsert(
            {"id": response.user.id, "email": email, "tier": "free"}
        ).execute()
        tier, early = "free", False
    else:
        tier = profile.data[0]["tier"]
        early = bool(profile.data[0].get("early_access"))

    if not early:
        confirmed = bool(getattr(response.user, "email_confirmed_at", None))
        _grant_early_access_if_waitlisted(response.user.id, email, confirmed)

    return {
        "user_id": response.user.id,
        "email": response.user.email,
        "tier": tier,
        "access_token": response.session.access_token,
        "refresh_token": response.session.refresh_token,
    }


def _refresh_sync(refresh_token: str) -> dict:
    try:
        response = get_auth_client().auth.refresh_session(refresh_token)
    except AuthApiError:
        raise HTTPException(status_code=401, detail="Session expired. Please log in again.")

    if not response.user or not response.session:
        raise HTTPException(status_code=401, detail="Session expired. Please log in again.")

    profile = get_supabase().table("profiles").select("tier").eq("id", response.user.id).execute()
    tier = profile.data[0]["tier"] if profile.data else "free"

    return {
        "user_id": response.user.id,
        "email": response.user.email,
        "tier": tier,
        "access_token": response.session.access_token,
        "refresh_token": response.session.refresh_token,
    }


def _verify_sync(token: str) -> UserProfile:
    try:
        user_response = get_token_verifier().auth.get_user(token)
    except AuthApiError:
        raise HTTPException(status_code=401, detail="Invalid or expired token.")

    if not user_response or not user_response.user:
        raise HTTPException(status_code=401, detail="Invalid or expired token.")

    user = user_response.user
    profile = (
        get_supabase().table("profiles").select("tier, early_access").eq("id", user.id).execute()
    )
    tier = profile.data[0]["tier"] if profile.data else "free"
    early = bool(profile.data[0].get("early_access")) if profile.data else False
    return UserProfile(id=user.id, email=user.email, tier=tier, early_access=early)


async def signup(email: str, password: str) -> dict:
    return await run_in_threadpool(_signup_sync, email, password)


async def login(email: str, password: str) -> dict:
    return await run_in_threadpool(_login_sync, email, password)


async def refresh(refresh_token: str) -> dict:
    return await run_in_threadpool(_refresh_sync, refresh_token)


async def verify_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> UserProfile:
    """Use on protected routes: `user: UserProfile = Depends(verify_token)`."""
    if (
        credentials is None
        or credentials.scheme.lower() != "bearer"
        or not credentials.credentials.strip()
    ):
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid authorization header.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return await run_in_threadpool(_verify_sync, credentials.credentials.strip())


async def get_optional_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> UserProfile | None:
    """Returns the user if a valid token is sent, otherwise None (anonymous)."""
    if credentials is None:
        return None
    try:
        return await verify_token(credentials)
    except HTTPException:
        return None