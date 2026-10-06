from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


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
    onboarding_completed: bool


class CareerTargetRoleRequest(BaseModel):
    role_key: str = Field(min_length=2, max_length=80)


class CareerSkillProgressUpsert(BaseModel):
    skill_type: str = Field(min_length=2, max_length=40)
    skill_key: str = Field(min_length=1, max_length=120)
    status: str = Field(default="in_progress", max_length=30)
    score: int = Field(default=0, ge=0, le=100)
    evidence_count: int = Field(default=1, ge=0, le=100000)
    notes: str | None = Field(default=None, max_length=2000)


class MockInterviewCreate(BaseModel):
    role_key: str | None = Field(default=None, max_length=80)
    mode: str = Field(default="mixed", max_length=30)
    question_count: int = Field(default=6, ge=3, le=12)


class MockInterviewResponseCreate(BaseModel):
    question_id: str = Field(min_length=1, max_length=100)
    answer: str = Field(min_length=1, max_length=12000)


class ResumeSkillAnalysisRequest(BaseModel):
    resume_text: str = Field(min_length=50, max_length=30000)
    role_key: str | None = Field(default=None, max_length=80)
