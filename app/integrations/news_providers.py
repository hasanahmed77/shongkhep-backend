from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from html import unescape
import hashlib
from re import sub
from urllib.parse import urlparse

import feedparser
import httpx

from app.core.config import settings


@dataclass
class ProviderArticle:
    canonical_url: str
    language: str
    source_name: str
    source_url: str
    category: str
    image_url: str | None
    title: str
    description: str
    body: str
    published_at: datetime
    entry_guid: str
    raw_payload: dict


class BaseNewsProviderClient:
    async def fetch_feed(
        self, language: str | None = None, category: str | None = None
    ) -> list[ProviderArticle]:
        raise NotImplementedError


class RssFeedClient(BaseNewsProviderClient):
    async def fetch_feed(
        self, language: str | None = None, category: str | None = None
    ) -> list[ProviderArticle]:
        results: list[ProviderArticle] = []
        feed_groups = _select_feed_groups(language=language, category=category)

        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            for feed_language, feed_entries in feed_groups.items():
                for feed_url, forced_category in feed_entries:
                    response = await client.get(feed_url)
                    response.raise_for_status()
                    parsed = feedparser.parse(response.text)
                    source_name = _rss_source_name(parsed.feed, feed_url)
                    results.extend(
                        _map_rss_payload(
                            parsed.entries,
                            source_name,
                            feed_language,
                            forced_category=forced_category,
                        )
                    )
        return _dedupe_articles(results)


def get_news_provider_client() -> BaseNewsProviderClient:
    return RssFeedClient()


def _dedupe_articles(articles: list[ProviderArticle]) -> list[ProviderArticle]:
    deduped: dict[str, ProviderArticle] = {}
    for article in articles:
        deduped[article.canonical_url] = article
    return list(deduped.values())


def _select_feed_groups(
    *, language: str | None, category: str | None
) -> dict[str, list[tuple[str, str | None]]]:
    normalized_language = "bn" if language == "bn" else "en"

    if normalized_language == "en":
        return {"en": [(feed_url, None) for feed_url in settings.rss_feed_urls_en]}

    return {"bn": [(feed_url, None) for feed_url in settings.rss_feed_urls_bn]}


def _map_rss_payload(
    entries: list,
    source_name: str,
    language: str,
    *,
    forced_category: str | None = None,
) -> list[ProviderArticle]:
    articles: list[ProviderArticle] = []
    for entry in entries:
        link = entry.get("link")
        title = _clean_text(entry.get("title", ""))
        if not link or not title:
            continue

        description = _extract_rss_text(entry, prefer_full_text=False)
        body = _extract_rss_text(entry, prefer_full_text=True) or description or title
        image_url = _extract_rss_image(entry)
        published_at = _parse_rss_datetime(
            entry.get("published") or entry.get("updated") or entry.get("pubDate")
        )
        category = forced_category or _infer_rss_category(entry)

        articles.append(
            ProviderArticle(
                canonical_url=link,
                language=language,
                source_name=source_name,
                source_url=link,
                category=category,
                image_url=image_url,
                title=title,
                description=description,
                body=body,
                published_at=published_at,
                entry_guid=_entry_guid(entry, link),
                raw_payload=_entry_payload(entry),
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
    return sub(r"\s+", " ", unescape(sub(r"<[^>]+>", " ", value))).strip()


def _extract_rss_text(entry: dict, *, prefer_full_text: bool) -> str:
    candidates: list[str] = []

    if prefer_full_text:
        content = entry.get("content", [])
        if content:
            candidates.extend(item.get("value", "") for item in content)
        candidates.append(entry.get("summary_detail", {}).get("value", ""))

    candidates.extend(
        [
            entry.get("summary", ""),
            entry.get("description", ""),
            entry.get("content:encoded", ""),
        ]
    )

    if not prefer_full_text:
        candidates.append(entry.get("summary_detail", {}).get("value", ""))

    for candidate in candidates:
        cleaned = _clean_text(candidate)
        if cleaned:
            return cleaned

    return ""


def _entry_guid(entry: dict, fallback_link: str) -> str:
    guid = entry.get("id") or entry.get("guid") or entry.get("link") or fallback_link
    return _clean_text(str(guid))


def _entry_payload(entry: dict) -> dict:
    payload: dict[str, str | int | float | bool | None] = {}
    for key, value in entry.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            payload[key] = value
        else:
            payload[key] = str(value)
    payload["_payload_hash"] = hashlib.sha256(str(sorted(payload.items())).encode("utf-8")).hexdigest()
    return payload
