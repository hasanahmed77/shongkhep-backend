from fastapi import APIRouter, Depends, Query, status

from app.api.deps import get_news_feed_service
from app.domain.schemas.news import FeedResponse, QueueSyncResponse
from app.services.news_feed import NewsFeedService
from app.workers.tasks import enqueue_ingestion_sync

router = APIRouter()


@router.get("/{language}", response_model=FeedResponse)
async def get_news_feed(
    language: str,
    category: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    service: NewsFeedService = Depends(get_news_feed_service),
) -> FeedResponse:
    return await service.get_feed(language=language, category=category, limit=limit)


@router.post("/sync", response_model=QueueSyncResponse, status_code=status.HTTP_202_ACCEPTED)
async def trigger_news_sync() -> QueueSyncResponse:
    task_id = enqueue_ingestion_sync()
    return QueueSyncResponse(task_id=task_id, status="queued")
