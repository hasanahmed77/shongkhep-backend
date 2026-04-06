from uuid import UUID

from pydantic import BaseModel, ConfigDict


class UserPreferencesResponse(BaseModel):
    user_id: UUID
    preferred_language: str
    favorite_categories: list[str]
    blocked_sources: list[str]
    personalization_enabled: bool

    model_config = ConfigDict(from_attributes=True)
