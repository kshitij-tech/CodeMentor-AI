from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import User, UserProfile
from backend.routers.auth import get_current_user
from backend.schemas import (
    OnboardingStatusResponse,
    RecommendationProfileContext,
    UserProfileResponse,
    UserProfileUpsert,
)


router = APIRouter(prefix="/profile", tags=["Profile"])


def _get_or_create_profile(current_user: User, db: Session) -> UserProfile:
    profile = (
        db.query(UserProfile)
        .filter(UserProfile.user_id == current_user.id)
        .first()
    )
    if profile is None:
        profile = UserProfile(
            user_id=current_user.id,
            preferred_languages=[],
            dsa_familiarity=[],
            target_companies=[],
            target_categories=[],
            daily_practice_target=3,
            learning_preferences={
                "learning_style": "Mixed",
                "hint_preference": "Guided",
                "session_length": "30-60 min",
                "feedback_preference": "Balanced",
            },
            onboarding_completed=False,
        )
        db.add(profile)
        db.commit()
        db.refresh(profile)
    return profile


def _missing_onboarding_fields(profile_data: UserProfileUpsert) -> list[str]:
    missing: list[str] = []

    if not profile_data.full_name:
        missing.append("full_name")
    if not profile_data.experience_level:
        missing.append("experience_level")
    if not profile_data.dsa_familiarity:
        missing.append("dsa_familiarity")
    if not profile_data.preferred_languages:
        missing.append("preferred_languages")
    if not profile_data.target_role:
        missing.append("target_role")
    if not profile_data.target_companies and not profile_data.target_categories:
        missing.append("target")
    if not profile_data.daily_practice_target:
        missing.append("daily_practice_target")
    if profile_data.learning_preferences is None:
        missing.append("learning_preferences")

    return missing


def _apply_profile(profile: UserProfile, profile_data: UserProfileUpsert) -> None:
    profile.full_name = profile_data.full_name
    profile.bio = profile_data.bio or None
    profile.leetcode_username = profile_data.leetcode_username or None
    profile.preferred_languages = list(profile_data.preferred_languages)
    profile.preferred_language = (
        profile_data.preferred_languages[0]
        if profile_data.preferred_languages
        else profile_data.preferred_language
    )
    profile.experience_level = profile_data.experience_level
    profile.dsa_familiarity = list(profile_data.dsa_familiarity)
    profile.target_role = profile_data.target_role
    profile.target_companies = list(profile_data.target_companies)
    profile.target_categories = list(profile_data.target_categories)
    profile.daily_practice_target = profile_data.daily_practice_target
    profile.learning_preferences = profile_data.learning_preferences.model_dump()
    profile.preparation_timeline = profile_data.preparation_timeline or None


def _profile_context(profile: UserProfile) -> RecommendationProfileContext:
    preferences = profile.learning_preferences or {}
    return RecommendationProfileContext(
        experience_level=profile.experience_level,
        dsa_familiarity=list(profile.dsa_familiarity or []),
        preferred_languages=list(
            profile.preferred_languages
            or ([profile.preferred_language] if profile.preferred_language else [])
        ),
        target_role=profile.target_role,
        target_companies=list(profile.target_companies or []),
        target_categories=list(profile.target_categories or []),
        daily_practice_target=profile.daily_practice_target,
        learning_preferences=preferences,
    )


@router.get("", response_model=UserProfileResponse)
def get_profile(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _get_or_create_profile(current_user, db)


@router.get("/status", response_model=OnboardingStatusResponse)
def get_onboarding_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    profile = _get_or_create_profile(current_user, db)
    missing: list[str] = []

    if not profile.full_name:
        missing.append("full_name")
    if not profile.experience_level:
        missing.append("experience_level")
    if not profile.dsa_familiarity:
        missing.append("dsa_familiarity")
    if not (profile.preferred_languages or profile.preferred_language):
        missing.append("preferred_languages")
    if not profile.target_role:
        missing.append("target_role")
    if not profile.target_companies and not profile.target_categories:
        missing.append("target")
    if not profile.daily_practice_target:
        missing.append("daily_practice_target")
    if not profile.learning_preferences:
        missing.append("learning_preferences")

    return OnboardingStatusResponse(
        onboarding_completed=bool(profile.onboarding_completed and not missing),
        missing_fields=missing,
    )


@router.get("/recommendation-context", response_model=RecommendationProfileContext)
def get_recommendation_context(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    profile = _get_or_create_profile(current_user, db)
    return _profile_context(profile)


@router.put("", response_model=UserProfileResponse)
def update_profile(
    profile_data: UserProfileUpsert,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    profile = _get_or_create_profile(current_user, db)
    _apply_profile(profile, profile_data)

    missing = _missing_onboarding_fields(profile_data)
    profile.onboarding_completed = not missing

    db.commit()
    db.refresh(profile)

    return profile


@router.post(
    "/onboarding",
    response_model=UserProfileResponse,
    status_code=status.HTTP_200_OK,
)
def complete_onboarding(
    profile_data: UserProfileUpsert,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    profile = _get_or_create_profile(current_user, db)

    if profile.onboarding_completed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Onboarding has already been completed. Edit preferences from Settings.",
        )

    missing = _missing_onboarding_fields(profile_data)
    if missing:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "Complete every mandatory onboarding field before finishing.",
                "missing_fields": missing,
            },
        )

    _apply_profile(profile, profile_data)
    profile.onboarding_completed = True

    db.commit()
    db.refresh(profile)

    return profile
