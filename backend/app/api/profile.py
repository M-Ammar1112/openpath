"""Profile endpoints (read/update) and re-scoring trigger."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import DbSession
from app.schemas.profile import ProfileRead, ProfileUpdate
from app.services.scoring import get_profile, rescore_after_profile_change, touch_updated_at

router = APIRouter(prefix="/profile", tags=["profile"])


@router.get("", response_model=ProfileRead, summary="Read the user profile")
def read_profile(session: DbSession) -> ProfileRead:
    return ProfileRead.model_validate(get_profile(session))


@router.patch("", response_model=ProfileRead, summary="Update the user profile")
def update_profile(payload: ProfileUpdate, session: DbSession) -> ProfileRead:
    """Apply a partial update, then re-score so the dashboard stays accurate."""
    profile = get_profile(session)
    data = payload.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(profile, key, value)
    touch_updated_at(profile)
    session.flush()
    rescore_after_profile_change(session)
    session.commit()
    session.refresh(profile)
    return ProfileRead.model_validate(profile)


@router.post("/rescore", summary="Re-score all opportunities with the current profile")
def rescore(session: DbSession) -> dict[str, int]:
    scored = rescore_after_profile_change(session)
    session.commit()
    return {"scored": scored}


__all__ = ["router"]
