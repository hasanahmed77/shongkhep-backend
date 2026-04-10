from dataclasses import dataclass
from datetime import datetime
import hashlib

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.integrations.news_providers import ProviderArticle, get_news_provider_client
from app.repositories.article import ArticleRepository


@dataclass
class InboundArticle:
    canonical_url: str
    language: str
    vertical: str
    source_name: str
    source_url: str
    category: str
    image_url: str | None
    title: str
    description: str
    body: str
    published_at: datetime
    entry_guid: str
    raw_payload: dict


class IngestionService:
    def __init__(self, article_repository: ArticleRepository):
        self.article_repository = article_repository

    async def ingest_articles(self, articles: list[InboundArticle]) -> int:
        count = 0
        try:
            for inbound in articles:
                summary = self._excerpt(inbound.description or inbound.body)
                await self.article_repository.upsert_article(
                    canonical_url=inbound.canonical_url,
                    source_name=inbound.source_name,
                    vertical=inbound.vertical,
                    category=inbound.category,
                    image_url=inbound.image_url,
                    published_at=inbound.published_at,
                    language=inbound.language,
                    title=inbound.title,
                    summary=summary,
                    article_body=inbound.body,
                    source_priority=self._source_priority(inbound.source_name),
                    metadata_json={"pipeline": "rss", "entry_guid": inbound.entry_guid},
                    raw_entry={
                        "source_name": inbound.source_name,
                        "source_url": inbound.source_url,
                        "language": inbound.language,
                        "vertical": inbound.vertical,
                        "entry_guid": inbound.entry_guid,
                        "content_hash": self._content_hash(inbound),
                        "category_hint": inbound.category,
                        "raw_payload": inbound.raw_payload,
                    },
                )
                count += 1

            await self.article_repository.session.commit()
            return count
        except Exception:
            await self.article_repository.session.rollback()
            raise

    @staticmethod
    async def create_for_worker() -> "IngestionService":
        session: AsyncSession = AsyncSessionLocal()
        repository = ArticleRepository(session)
        return IngestionService(repository)

    async def fetch_provider_payload(
        language: str | None = None, vertical: str | None = None, category: str | None = None
    ) -> list[InboundArticle]:
        provider = get_news_provider_client()
        articles = await provider.fetch_feed(language=language, vertical=vertical, category=category)
        return [IngestionService._from_provider_article(article) for article in articles if article.body]

    @staticmethod
    def _from_provider_article(article: ProviderArticle) -> InboundArticle:
        return InboundArticle(
            canonical_url=article.canonical_url,
            language=article.language,
            vertical=article.vertical,
            source_name=article.source_name,
            source_url=article.source_url,
            category=article.category,
            image_url=article.image_url,
            title=article.title,
            description=article.description,
            body=article.body,
            published_at=article.published_at,
            entry_guid=article.entry_guid,
            raw_payload=article.raw_payload,
        )

    @staticmethod
    def _excerpt(text: str, word_limit: int = 50) -> str:
        words = text.split()
        if len(words) <= word_limit:
            return " ".join(words)
        return f"{' '.join(words[:word_limit]).rstrip()}..."

    @staticmethod
    def _content_hash(article: InboundArticle) -> str:
        payload = "|".join(
            [
                article.canonical_url,
                article.title,
                article.description,
                article.body,
            ]
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _source_priority(source_name: str) -> int:
        normalized = source_name.casefold()
        priorities = {
            "prothom alo": 100,
            "the daily star": 95,
            "bdnews24.com": 92,
            "jagonews24.com": 85,
            "bd24live.com": 75,
        }
        for name, priority in priorities.items():
            if name in normalized:
                return priority
        return 50
