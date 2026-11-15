"""
PRISM Backend — Auth Models
"""

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class SignupRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {"email": "user@example.com", "password": "securepassword123"}
        }
    )

    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class UserProfile(BaseModel):
    id: str
    email: str
    tier: str  # 'free' | 'pro'

    @property
    def is_pro(self) -> bool:
        return self.tier == "pro"

    @property
    def signal_limit(self) -> int | None:
        """None means unlimited (Pro). Free users get 5 signals."""
        return None if self.is_pro else 5

    @property
    def watchlist_limit(self) -> int | None:
        """None means unlimited (Pro). Free users get 3 watchlist slots."""
        return None if self.is_pro else 3


class AuthResponse(BaseModel):
    user_id: str
    email: str
    tier: str
    access_token: str | None
    refresh_token: str | None
    message: str | None = None



class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=10, max_length=2048)