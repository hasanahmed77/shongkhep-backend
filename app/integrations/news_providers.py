from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from html import unescape
import hashlib
import logging
from re import search, sub
from urllib.parse import urlparse

import feedparser
import httpx

from app.core.config import settings


logger = logging.getLogger(__name__)


@dataclass
class ProviderArticle:
    canonical_url: str
    language: str
    vertical: str
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
        self, language: str | None = None, vertical: str | None = None, category: str | None = None
    ) -> list[ProviderArticle]:
        raise NotImplementedError


class RssFeedClient(BaseNewsProviderClient):
    async def fetch_feed(
        self, language: str | None = None, vertical: str | None = None, category: str | None = None
    ) -> list[ProviderArticle]:
        results: list[ProviderArticle] = []
        feed_groups = _select_feed_groups(language=language, vertical=vertical, category=category)

        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            for feed_language, feed_vertical, feed_entries in feed_groups:
                for feed_url, forced_category in feed_entries:
                    try:
                        response = await client.get(feed_url)
                        response.raise_for_status()
                        parsed = feedparser.parse(response.text)
                        source_name = _rss_source_name(parsed.feed, feed_url)
                        results.extend(
                            _map_rss_payload(
                                parsed.entries,
                                source_name,
                                feed_language,
                                feed_vertical,
                                forced_category=forced_category,
                            )
                        )
                    except Exception as exc:
                        logger.warning(
                            "Skipping feed after fetch/parse failure",
                            extra={
                                "feed_url": feed_url,
                                "language": feed_language,
                                "vertical": feed_vertical,
                                "error": str(exc),
                            },
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
    *, language: str | None, vertical: str | None, category: str | None
) -> list[tuple[str, str, list[tuple[str, str | None]]]]:
    normalized_vertical = (vertical or "").casefold()

    all_groups = {
        "en": {
            "news": [(feed_url, None) for feed_url in settings.rss_feed_urls_en],
            "tech": [(feed_url, None) for feed_url in settings.rss_feed_urls_en_tech],
            "science": [(feed_url, None) for feed_url in settings.rss_feed_urls_en_science],
            "gaming": [(feed_url, None) for feed_url in settings.rss_feed_urls_en_gaming],
        },
        "bn": {
            "news": [(feed_url, None) for feed_url in settings.rss_feed_urls_bn],
        },
    }

    selected_languages = [language] if language in all_groups else list(all_groups.keys())
    selected_verticals = (
        [normalized_vertical]
        if normalized_vertical
        else []
    )

    groups: list[tuple[str, str, list[tuple[str, str | None]]]] = []
    for selected_language in selected_languages:
        available_verticals = all_groups.get(selected_language, {})
        verticals_for_language = selected_verticals or list(available_verticals.keys())
        for selected in verticals_for_language:
            feeds = available_verticals.get(selected)
            if feeds:
                groups.append((selected_language, selected, feeds))
    return groups


def _map_rss_payload(
    entries: list,
    source_name: str,
    language: str,
    vertical: str,
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
        category = forced_category or _infer_rss_category(entry, vertical=vertical)

        articles.append(
            ProviderArticle(
                canonical_url=link,
                language=language,
                vertical=vertical,
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

    media_thumbnail = entry.get("media:thumbnail")
    if isinstance(media_thumbnail, dict):
        thumb_url = media_thumbnail.get("url")
        if thumb_url:
            return thumb_url

    media_content_alt = entry.get("media:content")
    if isinstance(media_content_alt, dict):
        media_url = media_content_alt.get("url")
        if media_url:
            return media_url

    html_candidates: list[str] = []
    content = entry.get("content", [])
    if content:
        html_candidates.extend(item.get("value", "") for item in content if item.get("value"))
    html_candidates.extend(
        [
            entry.get("summary", ""),
            entry.get("description", ""),
            entry.get("content:encoded", ""),
            entry.get("summary_detail", {}).get("value", ""),
        ]
    )

    for candidate in html_candidates:
        image_url = _extract_first_image_from_html(candidate)
        if image_url:
            return image_url

    return None


def _extract_first_image_from_html(value: str) -> str | None:
    if not value:
        return None
    match = search(r'<img[^>]+src=["\']([^"\']+)["\']', value, flags=0)
    if not match:
        return None
    return match.group(1).strip()


def _infer_rss_category(entry: dict, *, vertical: str) -> str:
    tags = entry.get("tags", [])
    category_haystack = _category_haystack(entry)
    if vertical == "tech":
        if _matches_any(category_haystack, "ai", "artificial intelligence"):
            return "AI"
        if _matches_any(category_haystack, "startup"):
            return "Startups"
        if _matches_any(category_haystack, "device", "hardware", "pixel"):
            return "Devices"
        if _matches_any(category_haystack, "android", "platform", "cloud"):
            return "Platforms"
        return "AI"
    if vertical == "science":
        if _matches_any(category_haystack, "space", "mars", "moon"):
            return "Space"
        if _matches_any(category_haystack, "research", "study"):
            return "Research"
        if _matches_any(category_haystack, "health", "medicine"):
            return "Health"
        if _matches_any(category_haystack, "climate", "earth", "environment"):
            return "Climate"
        return "Research"
    if vertical == "gaming":
        source_url = _clean_text(entry.get("link", "")).casefold()
        if "ps-store" in source_url or "store" in source_url or "sale" in source_url or "discount" in source_url:
            return "Sales"
        if _matches_any(category_haystack, "sale", "discount", "store"):
            return "Sales"
        if _matches_any(category_haystack, "release", "launch"):
            return "Releases"
        if _matches_any(category_haystack, "review"):
            return "Reviews"
        if _matches_any(category_haystack, "xbox", "playstation", "platform"):
            return "Platform News"
        return "Platform News"
    if _matches_any(
        category_haystack,
        "polit",
        "elect",
        "gov",
        "রাজনীতি",
        "নির্বাচন",
        "সরকার",
        "সংসদ",
        "মন্ত্রী",
        "আওয়ামী লীগ",
        "বিএনপি",
    ):
        return "Politics"
    if _matches_any(
        category_haystack,
        "business",
        "econom",
        "market",
        "trade",
        "stock",
        "ব্যবসা",
        "অর্থনীতি",
        "বাজার",
        "শেয়ার",
        "বাণিজ্য",
        "রপ্তানি",
        "আমদানি",
        "ব্যাংক",
    ):
        return "Business"
    if _matches_any(
        category_haystack,
        "tech",
        "technology",
        "science",
        "software",
        "internet",
        "startup",
        "প্রযুক্তি",
        "বিজ্ঞান",
        "সফটওয়্যার",
        "সফটওয়ার",
        "ইন্টারনেট",
        "মোবাইল",
        "ডিজিটাল",
    ):
        return "Technology"
    if _matches_any(
        category_haystack,
        "sport",
        "cricket",
        "football",
        "match",
        "tournament",
        "ক্রীড়া",
        "খেলা",
        "ক্রিকেট",
        "ফুটবল",
        "টুর্নামেন্ট",
    ):
        return "Sports"
    return "World"


def _category_haystack(entry: dict) -> str:
    tags = entry.get("tags", [])
    tag_terms = " ".join(_clean_text(tag.get("term", "")) for tag in tags)
    return " ".join(
        part
        for part in [
            tag_terms,
            _clean_text(entry.get("title", "")),
            _clean_text(entry.get("summary", "")),
            _clean_text(entry.get("description", "")),
            _clean_text(entry.get("link", "")),
        ]
        if part
    ).casefold()


def _matches_any(haystack: str, *needles: str) -> bool:
    return any(needle.casefold() in haystack for needle in needles)


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
