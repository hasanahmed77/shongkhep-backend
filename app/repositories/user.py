from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.user import User, UserPreference


class UserPreferenceRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_or_create_preferences(self, *, user_id: UUID) -> UserPreference:
        preference = await self.session.get(UserPreference, user_id)
        if preference is not None:
            return preference

        user = await self.session.get(User, user_id)
        if user is None:
            user = User(id=user_id)
            self.session.add(user)
            await self.session.flush()

        preference = UserPreference(user_id=user_id)
        self.session.add(preference)
        await self.session.commit()
        await self.session.refresh(preference)
        return preference

    async def get_user(self, *, user_id: UUID) -> User | None:
        result = await self.session.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()
