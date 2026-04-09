from datetime import UTC, datetime
import re
from urllib.parse import urlparse

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain.models.article import Article, ArticleTranslation, FeedState, RawFeedEntry, StoryCluster


class ArticleRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_feed(
        self,
        *,
        language: str,
        vertical: str,
        category: str | None,
        limit: int,
        before: tuple[int, datetime, str] | None = None,
        after: tuple[int, datetime, str] | None = None,
    ) -> list[tuple[StoryCluster, Article, ArticleTranslation]]:
        stmt: Select[tuple[StoryCluster, Article, ArticleTranslation]] = (
            select(StoryCluster, Article, ArticleTranslation)
            .join(Article, Article.id == StoryCluster.representative_article_id)
            .join(ArticleTranslation, ArticleTranslation.article_id == Article.id)
            .where(StoryCluster.language == language)
            .where(StoryCluster.vertical == vertical)
            .where(ArticleTranslation.language == language)
            .order_by(
                Article.source_priority.desc(),
                Article.published_at.desc().nullslast(),
                StoryCluster.id.desc(),
            )
            .limit(limit)
        )
        if category:
            stmt = stmt.where(StoryCluster.category == category)
        if before:
            before_priority, before_published_at, before_cluster_id = before
            stmt = stmt.where(
                or_(
                    Article.source_priority < before_priority,
                    and_(
                        Article.source_priority == before_priority,
                        or_(
                            Article.published_at < before_published_at,
                            and_(
                                Article.published_at == before_published_at,
                                StoryCluster.id < before_cluster_id,
                            ),
                        ),
                    ),
                )
            )
        if after:
            after_priority, after_published_at, after_cluster_id = after
            stmt = stmt.where(
                or_(
                    Article.source_priority > after_priority,
                    and_(
                        Article.source_priority == after_priority,
                        or_(
                            Article.published_at > after_published_at,
                            and_(
                                Article.published_at == after_published_at,
                                StoryCluster.id > after_cluster_id,
                            ),
                        ),
                    ),
                )
            )
        result = await self.session.execute(stmt)
        return list(result.all())

    async def get_feed_updates(
        self,
        *,
        language: str,
        vertical: str,
        category: str | None,
        after: tuple[int, datetime, str] | None,
        limit: int = 20,
    ) -> tuple[int, str | None]:
        if after is None:
            return 0, None

        state = await self.get_feed_state(language=language, vertical=vertical, category=category or "All")
        if state is None or state.latest_cursor is None or state.latest_cursor == _encode_cursor_parts(*after):
            return 0, state.latest_cursor if state else None

        count_stmt = (
            select(func.count())
            .select_from(StoryCluster)
            .join(Article, Article.id == StoryCluster.representative_article_id)
            .where(StoryCluster.language == language)
            .where(StoryCluster.vertical == vertical)
            .where(_newer_than_cursor(after))
        )
        if category:
            count_stmt = count_stmt.where(StoryCluster.category == category)
        count_result = await self.session.execute(count_stmt)
        total_new = count_result.scalar_one()
        return min(total_new, limit), state.latest_cursor

    async def get_by_canonical_url(self, canonical_url: str) -> Article | None:
        stmt = (
            select(Article)
            .options(selectinload(Article.translations), selectinload(Article.story_cluster))
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

    async def find_duplicate_candidate(
        self,
        *,
        language: str,
        vertical: str,
        title: str,
        category: str,
        article_body: str,
        published_at: datetime | None,
    ) -> Article | None:
        stmt = (
            select(Article, ArticleTranslation)
            .join(ArticleTranslation, ArticleTranslation.article_id == Article.id)
            .where(ArticleTranslation.language == language)
            .where(Article.vertical == vertical)
            .where(Article.category == category)
            .order_by(Article.published_at.desc().nullslast(), Article.created_at.desc())
            .limit(40)
        )
        result = await self.session.execute(stmt)
        title_tokens = _title_tokens(title)
        body_tokens = _body_tokens(article_body)

        best_article: Article | None = None
        best_score = 0.0
        for article, translation in result.all():
            title_score = _title_similarity(title_tokens, _title_tokens(translation.title))
            body_score = _body_similarity(body_tokens, _body_tokens(translation.article_body))
            if published_at and article.published_at:
                if abs((article.published_at - published_at).total_seconds()) > 60 * 60 * 18:
                    continue
            if title_score < 0.45 and body_score < 0.82:
                continue
            score = max(title_score, body_score)
            if score > best_score:
                best_article = article
                best_score = score

        if best_score >= 0.72:
            return best_article
        return None

    async def create_story_cluster(
        self, *, language: str, vertical: str, category: str, representative_article: Article | None = None
    ) -> StoryCluster:
        cluster = StoryCluster(
            language=language,
            vertical=vertical,
            category=category,
            representative_article_id=representative_article.id if representative_article else None,
        )
        self.session.add(cluster)
        await self.session.flush()
        if representative_article is not None:
            representative_article.story_cluster_id = cluster.id
        return cluster

    async def ensure_story_cluster(
        self, *, article: Article, language: str, vertical: str, category: str
    ) -> StoryCluster:
        if article.story_cluster is not None:
            return article.story_cluster

        cluster = await self.create_story_cluster(language=language, vertical=vertical, category=category)
        article.story_cluster_id = cluster.id
        cluster.representative_article_id = article.id
        return cluster

    async def maybe_promote_representative(
        self, *, cluster: StoryCluster, article: Article
    ) -> None:
        current = cluster.representative_article
        if current is None:
            cluster.representative_article_id = article.id
            return

        current_published = current.published_at or datetime.min.replace(tzinfo=UTC)
        candidate_published = article.published_at or datetime.min.replace(tzinfo=UTC)
        candidate_wins = (
            article.source_priority > current.source_priority
            or (
                article.source_priority == current.source_priority
                and candidate_published > current_published
            )
        )
        if candidate_wins:
            cluster.representative_article_id = article.id

    async def upsert_article(
        self,
        *,
        canonical_url: str,
        source_name: str,
        vertical: str,
        category: str,
        image_url: str | None,
        published_at: datetime | None,
        language: str,
        title: str,
        summary: str,
        article_body: str,
        source_priority: int,
        metadata_json: dict | None = None,
        raw_entry: dict | None = None,
    ) -> Article:
        article = await self.get_by_canonical_url(canonical_url)
        cluster: StoryCluster | None = None
        if article is not None:
            cluster = await self.ensure_story_cluster(
                article=article, language=language, vertical=vertical, category=category
            )
        else:
            duplicate_candidate = await self.find_duplicate_candidate(
                language=language,
                vertical=vertical,
                title=title,
                category=category,
                article_body=article_body,
                published_at=published_at,
            )
            if duplicate_candidate is not None:
                cluster = await self.ensure_story_cluster(
                    article=duplicate_candidate,
                    language=language,
                    vertical=vertical,
                    category=category,
                )

        if article is None:
            article = Article(
                canonical_url=canonical_url,
                source_name=source_name,
                source_domain=urlparse(canonical_url).netloc,
                vertical=vertical,
                category=category,
                story_cluster_id=cluster.id if cluster else None,
                image_url=image_url,
                published_at=published_at or datetime.now(UTC),
                original_language=language,
                source_priority=source_priority,
                metadata_json=metadata_json or {},
            )
            self.session.add(article)
            await self.session.flush()
            if cluster is None:
                cluster = await self.create_story_cluster(
                    language=language,
                    vertical=vertical,
                    category=category,
                    representative_article=article,
                )
        else:
            article.source_name = source_name
            article.source_domain = urlparse(canonical_url).netloc
            article.vertical = vertical
            article.category = category
            article.image_url = image_url
            article.published_at = published_at or article.published_at
            article.source_priority = source_priority
            article.metadata_json = metadata_json or article.metadata_json

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

        if raw_entry is not None:
            await self.upsert_raw_entry(article_id=article.id, **raw_entry)

        if cluster is not None:
            cluster.vertical = vertical
            cluster.category = category
            await self.maybe_promote_representative(cluster=cluster, article=article)
            await self.touch_feed_state(language=language, vertical=vertical, category=category, cluster=cluster)
            await self.touch_feed_state(language=language, vertical=vertical, category="All", cluster=cluster)

        return article

    async def upsert_raw_entry(
        self,
        *,
        article_id,
        source_name: str,
        source_url: str,
        language: str,
        vertical: str,
        entry_guid: str,
        content_hash: str,
        category_hint: str | None,
        raw_payload: dict,
    ) -> RawFeedEntry:
        stmt = select(RawFeedEntry).where(
            RawFeedEntry.source_name == source_name,
            RawFeedEntry.entry_guid == entry_guid,
        )
        result = await self.session.execute(stmt)
        raw_entry = result.scalar_one_or_none()

        if raw_entry is None:
            raw_entry = RawFeedEntry(
                article_id=article_id,
                source_name=source_name,
                source_url=source_url,
                language=language,
                vertical=vertical,
                entry_guid=entry_guid,
                content_hash=content_hash,
                category_hint=category_hint,
                raw_payload=raw_payload,
            )
            self.session.add(raw_entry)
            return raw_entry

        raw_entry.article_id = article_id
        raw_entry.source_url = source_url
        raw_entry.language = language
        raw_entry.vertical = vertical
        raw_entry.content_hash = content_hash
        raw_entry.category_hint = category_hint
        raw_entry.raw_payload = raw_payload
        return raw_entry

    async def get_feed_state(self, *, language: str, vertical: str, category: str) -> FeedState | None:
        stmt = select(FeedState).where(
            FeedState.language == language,
            FeedState.vertical == vertical,
            FeedState.category == category,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def touch_feed_state(self, *, language: str, vertical: str, category: str, cluster: StoryCluster) -> FeedState:
        state = await self.get_feed_state(language=language, vertical=vertical, category=category)
        latest_cursor = await self.get_latest_cursor(language=language, vertical=vertical, category=category)
        if state is None:
            state = FeedState(language=language, vertical=vertical, category=category, version=1, latest_cursor=latest_cursor)
            self.session.add(state)
            return state

        state.version += 1
        state.latest_cursor = latest_cursor
        return state

    async def get_latest_cursor(self, *, language: str, vertical: str, category: str) -> str | None:
        stmt = (
            select(StoryCluster, Article)
            .join(Article, Article.id == StoryCluster.representative_article_id)
            .where(StoryCluster.language == language)
            .where(StoryCluster.vertical == vertical)
            .order_by(
                Article.source_priority.desc(),
                Article.published_at.desc().nullslast(),
                StoryCluster.id.desc(),
            )
            .limit(1)
        )
        if category != "All":
            stmt = stmt.where(StoryCluster.category == category)
        result = await self.session.execute(stmt)
        row = result.first()
        if row is None:
            return None
        cluster, article = row
        return _encode_cursor(cluster, article)


def _title_tokens(title: str) -> set[str]:
    normalized = re.sub(r"[^a-z0-9\s]", " ", title.casefold())
    tokens = [token for token in normalized.split() if len(token) > 2 and token not in _STOP_WORDS]
    return set(tokens)


def _title_similarity(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    intersection = len(left & right)
    union = len(left | right)
    return intersection / union if union else 0.0


def _body_tokens(body: str) -> set[str]:
    normalized = re.sub(r"[^a-z0-9\s]", " ", body.casefold())
    tokens = [
        token for token in normalized.split() if len(token) > 3 and token not in _STOP_WORDS
    ]
    return set(tokens[:180])


def _body_similarity(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    intersection = len(left & right)
    base = min(len(left), len(right))
    return intersection / base if base else 0.0


_STOP_WORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "that",
    "this",
    "after",
    "into",
    "over",
    "amid",
    "news",
    "said",
    "says",
    "will",
    "have",
    "been",
    "were",
}


def _newer_than_cursor(after: tuple[int, datetime, str]):
    after_priority, after_published_at, after_cluster_id = after
    return or_(
        Article.source_priority > after_priority,
        and_(
            Article.source_priority == after_priority,
            or_(
                Article.published_at > after_published_at,
                and_(
                    Article.published_at == after_published_at,
                    StoryCluster.id > after_cluster_id,
                ),
            ),
        ),
    )


def _encode_cursor(cluster: StoryCluster, article: Article) -> str:
    published_at = (article.published_at or datetime.now(UTC)).isoformat()
    return f"{article.source_priority}|{published_at}|{cluster.id}"


def _encode_cursor_parts(source_priority: int, published_at: datetime, cluster_id) -> str:
    return f"{source_priority}|{published_at.isoformat()}|{cluster_id}"
