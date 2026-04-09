from datetime import UTC, datetime
import uuid

from app.domain.schemas.news import FeedResponse, FeedUpdatesResponse, NewsItemResponse
from app.repositories.article import ArticleRepository


class NewsFeedService:
    def __init__(self, article_repository: ArticleRepository):
        self.article_repository = article_repository

    async def get_feed(
        self,
        *,
        language: str,
        category: str | None,
        limit: int,
        before: str | None,
        after: str | None,
    ) -> FeedResponse:
        normalized_language = "bn" if language == "bn" else "en"
        before_cursor = _decode_cursor(before)
        after_cursor = _decode_cursor(after)
        rows = await self.article_repository.list_feed(
            language=normalized_language,
            category=category,
            limit=limit + 1,
            before=before_cursor,
            after=after_cursor,
        )
        has_more = len(rows) > limit
        visible_rows = rows[:limit]
        articles = [
            NewsItemResponse(
                id=cluster.id,
                cursor=_encode_cursor(cluster, article),
                category=cluster.category,
                image_url=article.image_url,
                source_name=article.source_name,
                source_url=article.canonical_url,
                title=translation.title,
                summary=translation.summary,
                article_body=translation.article_body,
                published_at=article.published_at,
            )
            for cluster, article, translation in visible_rows
        ]
        return FeedResponse(
            language=normalized_language,
            updated_at=datetime.now(UTC),
            has_more=has_more,
            next_cursor=_encode_cursor(visible_rows[-1][0], visible_rows[-1][1]) if has_more and visible_rows else None,
            articles=articles,
        )

    async def get_feed_updates(
        self, *, language: str, category: str | None, after: str | None
    ) -> FeedUpdatesResponse:
        normalized_language = "bn" if language == "bn" else "en"
        after_cursor = _decode_cursor(after)
        new_count, latest_cursor = await self.article_repository.get_feed_updates(
            language=normalized_language,
            category=category,
            after=after_cursor,
        )
        return FeedUpdatesResponse(
            language=normalized_language,
            has_new=new_count > 0,
            new_count=new_count,
            latest_cursor=latest_cursor,
        )


def _encode_cursor(cluster, article) -> str:
    published_at = (article.published_at or datetime.now(UTC)).isoformat()
    return f"{article.source_priority}|{published_at}|{cluster.id}"


def _decode_cursor(cursor: str | None) -> tuple[int, datetime, uuid.UUID] | None:
    if not cursor:
        return None
    try:
        source_priority, published_at, cluster_id = cursor.split("|", 2)
        return int(source_priority), datetime.fromisoformat(published_at), uuid.UUID(cluster_id)
    except ValueError:
        return None
