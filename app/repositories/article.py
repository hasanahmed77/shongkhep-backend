from datetime import UTC, datetime
from urllib.parse import urlparse

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain.models.article import Article, ArticleTranslation


class ArticleRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_feed(
        self, *, language: str, category: str | None, limit: int
    ) -> list[tuple[Article, ArticleTranslation]]:
        stmt: Select[tuple[Article, ArticleTranslation]] = (
            select(Article, ArticleTranslation)
            .join(ArticleTranslation, ArticleTranslation.article_id == Article.id)
            .where(ArticleTranslation.language == language)
            .order_by(Article.published_at.desc().nullslast(), Article.created_at.desc())
            .limit(limit)
        )
        if category:
            stmt = stmt.where(Article.category == category)
        result = await self.session.execute(stmt)
        return list(result.all())

    async def get_by_canonical_url(self, canonical_url: str) -> Article | None:
        stmt = (
            select(Article)
            .options(selectinload(Article.translations))
            .where(Article.canonical_url == canonical_url)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_translation(
        self, *, article_id, language: str
    ) -> ArticleTranslation | None:
        stmt = select(ArticleTranslation).where(
            ArticleTranslation.article_id == article_id,
            ArticleTranslation.language == language,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def upsert_article(
        self,
        *,
        canonical_url: str,
        source_name: str,
        category: str,
        image_url: str | None,
        published_at: datetime | None,
        language: str,
        title: str,
        summary: str,
        article_body: str,
        metadata_json: dict | None = None,
    ) -> Article:
        article = await self.get_by_canonical_url(canonical_url)
        if article is None:
            article = Article(
                canonical_url=canonical_url,
                source_name=source_name,
                source_domain=urlparse(canonical_url).netloc,
                category=category,
                image_url=image_url,
                published_at=published_at or datetime.now(UTC),
                original_language=language,
                metadata_json=metadata_json or {},
            )
            self.session.add(article)
            await self.session.flush()

        translation = await self.get_translation(article_id=article.id, language=language)
        if translation is None:
            translation = ArticleTranslation(
                article_id=article.id,
                language=language,
                title=title,
                summary=summary,
                article_body=article_body,
            )
            self.session.add(translation)
        else:
            translation.title = title
            translation.summary = summary
            translation.article_body = article_body

        return article
