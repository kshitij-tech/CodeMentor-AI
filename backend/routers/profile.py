from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import User, UserProfile
from backend.routers.auth import get_current_user
from backend.schemas import UserProfileResponse, UserProfileUpsert


router = APIRouter(prefix="/profile", tags=["Profile"])


@router.get("", response_model=UserProfileResponse)
def get_profile(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    profile = db.query(UserProfile).filter(
        UserProfile.user_id == current_user.id
    ).first()

    if profile is None:
        profile = UserProfile(user_id=current_user.id)
        db.add(profile)
        db.commit()
        db.refresh(profile)

    return profile


@router.put("", response_model=UserProfileResponse)
def update_profile(
    profile_data: UserProfileUpsert,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    profile = db.query(UserProfile).filter(
        UserProfile.user_id == current_user.id
    ).first()

    if profile is None:
        profile = UserProfile(user_id=current_user.id)
        db.add(profile)

    profile.full_name = profile_data.full_name.strip()
    if len(profile_data.bio or "") > 180:
        profile_data.bio = profile_data.bio[:180]

    profile.leetcode_username = (
        profile_data.leetcode_username.strip()
        if profile_data.leetcode_username
        else None
    )
    profile.bio = profile_data.bio.strip() if profile_data.bio else None
    profile.preferred_language = profile_data.preferred_language.strip()
    profile.experience_level = profile_data.experience_level.strip()
    profile.target_role = profile_data.target_role.strip()
    profile.target_companies = profile_data.target_companies
    profile.preparation_timeline = profile_data.preparation_timeline
    profile.onboarding_completed = bool(
        profile.full_name
        and profile.preferred_language
        and profile.experience_level
        and profile.target_role
    )

    db.commit()
    db.refresh(profile)

    return profile
