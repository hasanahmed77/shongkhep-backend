from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from html import unescape
from urllib.parse import urlparse

import feedparser
import httpx

from app.core.config import settings


@dataclass
class ProviderArticle:
    canonical_url: str
    source_name: str
    category: str
    image_url: str | None
    title: str
    description: str
    body: str
    published_at: datetime


class BaseNewsProviderClient:
    async def fetch_feed(self) -> list[ProviderArticle]:
        raise NotImplementedError


class RssFeedClient(BaseNewsProviderClient):
    async def fetch_feed(self) -> list[ProviderArticle]:
        results: list[ProviderArticle] = []
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            for feed_url in settings.rss_feed_urls:
                response = await client.get(feed_url)
                response.raise_for_status()
                parsed = feedparser.parse(response.text)
                source_name = _rss_source_name(parsed.feed, feed_url)
                results.extend(_map_rss_payload(parsed.entries, source_name))
        return _dedupe_articles(results)


def get_news_provider_client() -> BaseNewsProviderClient:
    return RssFeedClient()


def _dedupe_articles(articles: list[ProviderArticle]) -> list[ProviderArticle]:
    deduped: dict[str, ProviderArticle] = {}
    for article in articles:
        deduped[article.canonical_url] = article
    return list(deduped.values())


def _map_rss_payload(entries: list, source_name: str) -> list[ProviderArticle]:
    articles: list[ProviderArticle] = []
    for entry in entries:
        link = entry.get("link")
        title = _clean_text(entry.get("title", ""))
        if not link or not title:
            continue

        description = _clean_text(
            entry.get("summary", "") or entry.get("description", "") or ""
        )
        body = description
        image_url = _extract_rss_image(entry)
        published_at = _parse_rss_datetime(
            entry.get("published") or entry.get("updated") or entry.get("pubDate")
        )
        category = _infer_rss_category(entry)

        articles.append(
            ProviderArticle(
                canonical_url=link,
                source_name=source_name,
                category=category,
                image_url=image_url,
                title=title,
                description=description,
                body=body,
                published_at=published_at,
            )
        )
    return articles


def _rss_source_name(feed: dict, feed_url: str) -> str:
    title = feed.get("title")
    if title:
        return _clean_text(title)
    return urlparse(feed_url).netloc


def _extract_rss_image(entry: dict) -> str | None:
    media_content = entry.get("media_content", [])
    if media_content:
        media_url = media_content[0].get("url")
        if media_url:
            return media_url

    media_thumbnail = entry.get("media_thumbnail", [])
    if media_thumbnail:
        thumb_url = media_thumbnail[0].get("url")
        if thumb_url:
            return thumb_url

    enclosure = entry.get("enclosures", [])
    if enclosure:
        enclosure_url = enclosure[0].get("href")
        if enclosure_url:
            return enclosure_url

    return None


def _infer_rss_category(entry: dict) -> str:
    tags = entry.get("tags", [])
    for tag in tags:
        term = _clean_text(tag.get("term", ""))
        normalized = term.casefold()
        if "polit" in normalized or "elect" in normalized or "gov" in normalized:
            return "Politics"
        if "business" in normalized or "econom" in normalized or "market" in normalized:
            return "Business"
        if "tech" in normalized or "science" in normalized:
            return "Technology"
        if "sport" in normalized or "cricket" in normalized or "football" in normalized:
            return "Sports"
    return "World"


def _parse_rss_datetime(value: str | None) -> datetime:
    if not value:
        return datetime.now(UTC)
    try:
        parsed = parsedate_to_datetime(value)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except (TypeError, ValueError, IndexError):
        return datetime.now(UTC)


def _clean_text(value: str) -> str:
    return unescape(value).strip()
