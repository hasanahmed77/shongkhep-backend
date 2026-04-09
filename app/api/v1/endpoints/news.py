from fastapi import APIRouter, Depends, Query, status

from app.api.deps import get_news_feed_service
from app.domain.schemas.news import FeedResponse, FeedUpdatesResponse, QueueSyncResponse, SyncResponse
from app.services.ingestion import IngestionService
from app.services.news_feed import NewsFeedService
from app.workers.tasks import enqueue_ingestion_sync

router = APIRouter()


@router.get("/{language}", response_model=FeedResponse)
async def get_news_feed(
    language: str,
    category: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    before: str | None = Query(default=None),
    after: str | None = Query(default=None),
    service: NewsFeedService = Depends(get_news_feed_service),
    ) -> FeedResponse:
    return await service.get_feed(
        language=language,
        category=category,
        limit=limit,
        before=before,
        after=after,
    )


@router.get("/{language}/updates", response_model=FeedUpdatesResponse)
async def get_news_feed_updates(
    language: str,
    category: str | None = Query(default=None),
    after: str | None = Query(default=None),
    service: NewsFeedService = Depends(get_news_feed_service),
) -> FeedUpdatesResponse:
    return await service.get_feed_updates(language=language, category=category, after=after)


@router.post("/sync", response_model=QueueSyncResponse, status_code=status.HTTP_202_ACCEPTED)
async def trigger_news_sync() -> QueueSyncResponse:
    task_id = enqueue_ingestion_sync()
    return QueueSyncResponse(task_id=task_id, status="queued")


@router.post("/sync-now", response_model=SyncResponse)
async def sync_news_now(
    language: str | None = Query(default=None, pattern="^(en|bn)$"),
    category: str | None = Query(default=None),
) -> SyncResponse:
    service = await IngestionService.create_for_worker()
    try:
        articles = await IngestionService.fetch_provider_payload(
            language=language, category=category
        )
        inserted = await service.ingest_articles(articles)
        return SyncResponse(inserted=inserted, status="ok")
    finally:
        await service.article_repository.session.close()
