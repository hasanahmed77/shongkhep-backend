from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status

from app.api.deps import get_user_preference_repository
from app.domain.schemas.user import UserPreferencesResponse
from app.repositories.user import UserPreferenceRepository

router = APIRouter()


@router.get("/me/preferences", response_model=UserPreferencesResponse)
async def get_my_preferences(
    x_user_id: str | None = Header(default=None),
    repository: UserPreferenceRepository = Depends(get_user_preference_repository),
) -> UserPreferencesResponse:
    if not x_user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication layer not connected yet. Expected X-User-Id header.",
        )

    try:
        user_id = UUID(x_user_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid X-User-Id header."
        ) from exc

    preferences = await repository.get_or_create_preferences(user_id=user_id)
    return UserPreferencesResponse.model_validate(preferences)
