from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.integrations.news_providers import ProviderArticle, get_news_provider_client
from app.repositories.article import ArticleRepository


@dataclass
class InboundArticle:
    canonical_url: str
    source_name: str
    category: str
    image_url: str | None
    title: str
    description: str
    body: str
    published_at: datetime


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
                    category=inbound.category,
                    image_url=inbound.image_url,
                    published_at=inbound.published_at,
                    language="en",
                    title=inbound.title,
                    summary=summary,
                    article_body=inbound.body,
                    metadata_json={"pipeline": "rss"},
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

    @staticmethod
    def build_demo_payload() -> list[InboundArticle]:
        timestamp = datetime.now(UTC)
        return [
            InboundArticle(
                canonical_url="https://example.com/world-energy-transition",
                source_name="Global Dispatch",
                category="World",
                image_url=(
                    "https://images.unsplash.com/photo-1541872705-1f73c6400ec9"
                    "?auto=format&fit=crop&w=1200&q=80"
                ),
                title="Nations accelerate clean energy deals before winter demand rises",
                description=(
                    "Governments are racing to secure power supply agreements ahead of winter."
                ),
                body=(
                    "Energy ministers entered a new round of talks this week to secure supply "
                    "stability before peak winter demand. The agreements combine immediate "
                    "resilience measures with long-term grid and renewables investment."
                ),
                published_at=timestamp,
            ),
            InboundArticle(
                canonical_url="https://example.com/ai-phone-rollout",
                source_name="Circuit Weekly",
                category="Technology",
                image_url=(
                    "https://images.unsplash.com/photo-1516321318423-f06f85e504b3"
                    "?auto=format&fit=crop&w=1200&q=80"
                ),
                title="AI-first phones push offline translation and summarization to the edge",
                description=(
                    "Manufacturers are moving premium AI features from the cloud onto devices."
                ),
                body=(
                    "Manufacturers are shifting premium mobile features from cloud-only workflows "
                    "to on-device models, reducing latency and improving privacy for users."
                ),
                published_at=timestamp,
            ),
        ]

    @staticmethod
    async def fetch_provider_payload() -> list[InboundArticle]:
        provider = get_news_provider_client()
        articles = await provider.fetch_feed()
        return [IngestionService._from_provider_article(article) for article in articles if article.body]

    @staticmethod
    def _from_provider_article(article: ProviderArticle) -> InboundArticle:
        return InboundArticle(
            canonical_url=article.canonical_url,
            source_name=article.source_name,
            category=article.category,
            image_url=article.image_url,
            title=article.title,
            description=article.description,
            body=article.body,
            published_at=article.published_at,
        )

    @staticmethod
    def _excerpt(text: str, word_limit: int = 50) -> str:
        words = text.split()
        if len(words) <= word_limit:
            return " ".join(words)
        return f"{' '.join(words[:word_limit]).rstrip()}..."
