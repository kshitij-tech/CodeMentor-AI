from datetime import datetime

from pydantic import BaseModel, ConfigDict


class UserCreate(BaseModel):
    email: str
    password: str


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: str


class LoginRequest(BaseModel):
    email: str
    password: str


class UserProfileUpsert(BaseModel):
    full_name: str
    bio: str | None = None
    leetcode_username: str | None = None
    preferred_language: str
    experience_level: str
    target_role: str
    target_companies: list[str] = []
    preparation_timeline: str | None = None


class UserProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    full_name: str | None
    leetcode_username: str | None
    preferred_language: str | None
    experience_level: str | None
    target_role: str | None
    bio: str | None
    target_companies: list[str] | None
    preparation_timeline: str | None
