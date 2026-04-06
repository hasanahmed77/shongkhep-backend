import asyncio

from app.core.database import create_db_and_tables
from app.services.ingestion import IngestionService


async def main() -> None:
    await create_db_and_tables()
    service = await IngestionService.create_for_worker()
    articles = await IngestionService.fetch_provider_payload()
    if not articles:
        articles = IngestionService.build_demo_payload()
    await service.ingest_articles(articles)
    await service.article_repository.session.close()


if __name__ == "__main__":
    asyncio.run(main())
