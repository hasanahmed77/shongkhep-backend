from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.repositories.article import ArticleRepository
from app.repositories.user import UserPreferenceRepository
from app.services.ingestion import IngestionService
from app.services.news_feed import NewsFeedService


async def get_session(session: AsyncSession = Depends(get_db_session)) -> AsyncSession:
    return session


def get_article_repository(session: AsyncSession = Depends(get_session)) -> ArticleRepository:
    return ArticleRepository(session)


def get_user_preference_repository(
    session: AsyncSession = Depends(get_session),
) -> UserPreferenceRepository:
    return UserPreferenceRepository(session)


def get_news_feed_service(
    article_repository: ArticleRepository = Depends(get_article_repository),
) -> NewsFeedService:
    return NewsFeedService(article_repository)


def get_ingestion_service(
    article_repository: ArticleRepository = Depends(get_article_repository),
) -> IngestionService:
    return IngestionService(article_repository)
