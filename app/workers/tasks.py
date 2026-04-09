import asyncio

from app.core.database import create_db_and_tables
from app.core.logging import configure_logging
from app.services.ingestion import IngestionService
from app.workers.celery_app import celery_app


@celery_app.task(name="app.workers.tasks.ingest_news_sources")
def ingest_news_sources() -> dict[str, int]:
    configure_logging()
    return asyncio.run(_run_ingestion())


def enqueue_ingestion_sync() -> str:
    result = ingest_news_sources.delay()
    return result.id


async def _run_ingestion() -> dict[str, int]:
    await create_db_and_tables()
    service = await IngestionService.create_for_worker()
    articles = await service.fetch_provider_payload()
    inserted = await service.ingest_articles(articles)
    await service.article_repository.session.close()
    return {"inserted": inserted}
