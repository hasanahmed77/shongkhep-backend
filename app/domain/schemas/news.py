from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class NewsItemResponse(BaseModel):
    id: UUID
    cursor: str
    vertical: str
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
    has_more: bool
    next_cursor: str | None
    articles: list[NewsItemResponse]


class QueueSyncResponse(BaseModel):
    task_id: str
    status: str


class SyncResponse(BaseModel):
    inserted: int
    status: str


class FeedUpdatesResponse(BaseModel):
    language: str
    has_new: bool
    new_count: int
    latest_cursor: str | None
