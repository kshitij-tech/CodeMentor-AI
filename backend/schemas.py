from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


EXPERIENCE_LEVELS = ("Beginner", "Intermediate", "Advanced")
SUPPORTED_LANGUAGES = (
    "Python",
    "C++",
    "Java",
    "JavaScript",
    "TypeScript",
    "Go",
    "Rust",
)
TARGET_ROLES = (
    "Software Engineer",
    "Full Stack Engineer",
    "Backend Engineer",
    "Frontend Engineer",
    "Data Scientist",
    "Machine Learning Engineer",
    "DevOps Engineer",
    "Mobile App Developer",
)
TARGET_CATEGORIES = (
    "FAANG / Big Tech",
    "Startups",
    "Fintech",
    "SaaS",
    "AI / ML",
    "Product Companies",
    "Consulting",
    "Remote-first",
)


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


class LearningPreferences(BaseModel):
    learning_style: Literal["Hands-on", "Explanation-first", "Visual", "Mixed"] = "Mixed"
    hint_preference: Literal["Minimal", "Guided", "Detailed"] = "Guided"
    session_length: Literal["15-30 min", "30-60 min", "60-90 min", "90+ min"] = "30-60 min"
    feedback_preference: Literal["Concise", "Balanced", "Detailed"] = "Balanced"


class UserProfileUpsert(BaseModel):
    full_name: str = Field(min_length=1, max_length=120)
    bio: str | None = Field(default=None, max_length=180)
    leetcode_username: str | None = Field(default=None, max_length=100)
    preferred_language: str | None = Field(default=None, max_length=50)
    preferred_languages: list[str] = Field(default_factory=list, max_length=7)
    experience_level: str | None = Field(default=None, max_length=50)
    dsa_familiarity: list[str] = Field(default_factory=list, max_length=18)
    target_role: str | None = Field(default=None, max_length=100)
    target_companies: list[str] = Field(default_factory=list, max_length=10)
    target_categories: list[str] = Field(default_factory=list, max_length=8)
    daily_practice_target: int = Field(default=3, ge=1, le=20)
    learning_preferences: LearningPreferences = Field(
        default_factory=LearningPreferences
    )
    preparation_timeline: str | None = Field(default=None, max_length=100)

    @field_validator(
        "full_name",
        "bio",
        "leetcode_username",
        "preferred_language",
        "experience_level",
        "target_role",
        "preparation_timeline",
        mode="before",
    )
    @classmethod
    def strip_strings(cls, value):
        if value is None:
            return value
        return str(value).strip()

    @field_validator(
        "preferred_languages",
        "dsa_familiarity",
        "target_companies",
        "target_categories",
        mode="before",
    )
    @classmethod
    def clean_lists(cls, value):
        if value is None:
            return []
        cleaned = []
        for item in value:
            item = str(item).strip()
            if item and item not in cleaned:
                cleaned.append(item)
        return cleaned

    @field_validator("preferred_languages")
    @classmethod
    def validate_languages(cls, value):
        invalid = [item for item in value if item not in SUPPORTED_LANGUAGES]
        if invalid:
            raise ValueError(
                "Unsupported programming language(s): " + ", ".join(invalid)
            )
        return value

    @field_validator("preferred_language")
    @classmethod
    def validate_preferred_language(cls, value):
        if value is not None and value not in SUPPORTED_LANGUAGES:
            raise ValueError(
                "Unsupported programming language: " + value
            )
        return value

    @field_validator("experience_level")
    @classmethod
    def validate_experience(cls, value):
        if value is not None and value not in EXPERIENCE_LEVELS:
            raise ValueError(
                "Experience level must be Beginner, Intermediate, or Advanced."
            )
        return value

    @field_validator("target_role")
    @classmethod
    def validate_target_role(cls, value):
        if value is not None and value not in TARGET_ROLES:
            raise ValueError("Unsupported target interview role.")
        return value

    @field_validator("target_categories")
    @classmethod
    def validate_target_categories(cls, value):
        invalid = [item for item in value if item not in TARGET_CATEGORIES]
        if invalid:
            raise ValueError("Unsupported target category: " + ", ".join(invalid))
        return value

    @model_validator(mode="after")
    def normalize_preferred_languages(self):
        if not self.preferred_languages and self.preferred_language:
            self.preferred_languages = [self.preferred_language]
        elif self.preferred_languages and not self.preferred_language:
            self.preferred_language = self.preferred_languages[0]
        elif self.preferred_languages:
            self.preferred_language = self.preferred_languages[0]
        return self


class UserProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    full_name: str | None
    leetcode_username: str | None
    preferred_language: str | None
    preferred_languages: list[str] | None
    experience_level: str | None
    dsa_familiarity: list[str] | None
    target_role: str | None
    bio: str | None
    target_companies: list[str] | None
    target_categories: list[str] | None
    daily_practice_target: int | None
    learning_preferences: LearningPreferences | dict | None
    preparation_timeline: str | None
    onboarding_completed: bool


class OnboardingStatusResponse(BaseModel):
    onboarding_completed: bool
    missing_fields: list[str]


class RecommendationProfileContext(BaseModel):
    experience_level: str | None
    dsa_familiarity: list[str]
    preferred_languages: list[str]
    target_role: str | None
    target_companies: list[str]
    target_categories: list[str]
    daily_practice_target: int
    learning_preferences: LearningPreferences
