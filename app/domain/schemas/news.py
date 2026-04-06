from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class NewsItemResponse(BaseModel):
    id: UUID
    category: str
    image_url: str | None
    source_name: str
    source_url: str
    title: str
    summary: str
    article_body: str
    published_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class FeedResponse(BaseModel):
    language: str
    updated_at: datetime
    articles: list[NewsItemResponse]


class QueueSyncResponse(BaseModel):
    task_id: str
    status: str
