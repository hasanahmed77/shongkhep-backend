from datetime import UTC, datetime

from app.domain.schemas.news import FeedResponse, NewsItemResponse
from app.repositories.article import ArticleRepository


class NewsFeedService:
    def __init__(self, article_repository: ArticleRepository):
        self.article_repository = article_repository

    async def get_feed(self, *, language: str, category: str | None, limit: int) -> FeedResponse:
        normalized_language = "bn" if language == "bn" else "en"
        rows = await self.article_repository.list_feed(
            language=normalized_language, category=category, limit=limit
        )
        articles = [
            NewsItemResponse(
                id=article.id,
                category=article.category,
                image_url=article.image_url,
                source_name=article.source_name,
                source_url=article.canonical_url,
                title=translation.title,
                summary=translation.summary,
                article_body=translation.article_body,
                published_at=article.published_at,
            )
            for article, translation in rows
        ]
        return FeedResponse(
            language=normalized_language,
            updated_at=datetime.now(UTC),
            articles=articles,
        )
