"""RSS/Atom feed connector.

Feeds are the most lawful way to consume third-party listing sites: they
are published for syndication, and OpenPath always stores and shows the
original item link. Each configured feed is one `Source` row, so adding a
feed needs no code change.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar
from urllib.parse import urlparse

import feedparser

from app.connectors.base import (
    FetchedRecord,
    FetchContext,
    NormalizedOpportunity,
    ParsedItem,
    SourceConnector,
)
from app.core.html import html_to_text
from app.core.http import FetchError, get_http_client
from app.enums import DegreeLevel, FundingType, OpportunityType
from app.logging_config import get_logger
from app.normalize.fields import (
    extract_skills,
    infer_opportunity_type,
    normalize_degree_level,
    normalize_funding,
)

log = get_logger("openpath.connectors.rss")

# Country hints used when a feed has no structured country field.
_COUNTRY_HINTS: tuple[tuple[str, str], ...] = (
    ("germany", "Germany"),
    ("netherlands", "Netherlands"),
    ("switzerland", "Switzerland"),
    ("sweden", "Sweden"),
    ("norway", "Norway"),
    ("denmark", "Denmark"),
    ("finland", "Finland"),
    ("belgium", "Belgium"),
    ("austria", "Austria"),
    ("ireland", "Ireland"),
    ("france", "France"),
    ("italy", "Italy"),
    ("spain", "Spain"),
    ("poland", "Poland"),
    ("canada", "Canada"),
    ("australia", "Australia"),
    ("new zealand", "New Zealand"),
    ("singapore", "Singapore"),
    ("japan", "Japan"),
    ("south korea", "South Korea"),
    ("china", "China"),
    ("india", "India"),
    ("united kingdom", "United Kingdom"),
    ("usa", "United States"),
    ("u.s.", "United States"),
    ("united states", "United States"),
    ("europe", "Europe"),
    ("worldwide", "Worldwide"),
    ("international", "Worldwide"),
    ("global", "Worldwide"),
)


class RssFeedConnector(SourceConnector):
    """Parse an RSS/Atom feed into opportunities.

    `options` (from the Source row / seed config) may contain:
      - `organization`: override when the feed has no per-item org
      - `default_type`: opportunity type when classification is ambiguous
      - `skills`: vocabulary used for skill extraction
      - `keyword_include` / `keyword_exclude`: cheap relevance filters
    """

    connector_type: ClassVar[str] = "rss"

    async def fetch(self, ctx: FetchContext) -> list[FetchedRecord]:
        url = ctx.endpoint_url or self.endpoint_url
        if not url:
            raise FetchError("rss connector requires an endpoint_url")
        client = get_http_client()
        result = await client.get(url, rate_limit_seconds=ctx.rate_limit_seconds)
        return [
            FetchedRecord(
                url=result.url, content=result.content, content_type=result.content_type
            )
        ]

    def parse(self, record: FetchedRecord) -> list[ParsedItem]:
        parsed = feedparser.parse(record.content)
        if parsed.bozo and not parsed.entries:
            log.warning(
                "rss_parse_failed",
                extra={"url": record.url, "error": str(parsed.bozo_exception)},
            )
            return []
        items: list[ParsedItem] = []
        for entry in parsed.entries:
            title = (entry.get("title") or "").strip()
            link = (entry.get("link") or "").strip()
            if not title or not link:
                continue
            summary_raw = entry.get("summary") or entry.get("description")
            content_list = entry.get("content") or []
            if not summary_raw and content_list:
                summary_raw = content_list[0].get("value")
            items.append(
                ParsedItem(
                    external_id=entry.get("id") or entry.get("guid"),
                    title=title,
                    link=link,
                    summary=html_to_text(summary_raw),
                    published_at=self._entry_date(entry),
                    extra={
                        "tags": [
                            t.get("term") for t in (entry.get("tags") or []) if t.get("term")
                        ],
                        "author": entry.get("author"),
                        "source_feed": record.url,
                    },
                )
            )
        return items

    @staticmethod
    def _entry_date(entry: Any) -> str | None:
        for key in ("published_parsed", "updated_parsed", "created_parsed"):
            value = entry.get(key)
            if value:
                try:
                    return datetime(*value[:6]).isoformat()  # noqa: DTZ007 - feed local time
                except (TypeError, ValueError):
                    continue
        return entry.get("published") or entry.get("updated")

    # -- normalization --------------------------------------------------
    def _keyword_allowed(self, text: str) -> bool:
        lowered = text.lower()
        exclude = [k.lower() for k in self.options.get("keyword_exclude") or []]
        if any(k in lowered for k in exclude):
            return False
        include = [k.lower() for k in self.options.get("keyword_include") or []]
        if include and not any(k in lowered for k in include):
            return False
        return True

    def normalize(self, item: ParsedItem) -> NormalizedOpportunity:
        text = f"{item.title}. {item.summary or ''}"
        default_type = OpportunityType(self.options.get("default_type", "other"))
        opportunity_type = infer_opportunity_type(text, default=default_type)
        degree_level = normalize_degree_level(text)
        return NormalizedOpportunity(
            title=item.title,
            official_url=item.link,
            opportunity_type=opportunity_type,
            organization=self.options.get("organization")
            or self._organization_from_link(item.link),
            country=self._country_hint(text),
            field=self.options.get("field"),
            degree_level=degree_level.value if degree_level is not DegreeLevel.UNKNOWN else None,
            degree_level_raw=degree_level.value if degree_level is not DegreeLevel.UNKNOWN else None,
            funding_type=normalize_funding(text),
            funding_type_raw=None,
            skills=extract_skills(text, self.options.get("skills") or []),
            tags=[t for t in (item.extra.get("tags") or []) if t],
            description=item.summary,
            source_key="",
            source_name="",
            external_id=item.external_id,
            raw_payload={
                "title": item.title,
                "url": item.link,
                "published_at": item.published_at,
                "author": item.extra.get("author"),
                "feed": item.extra.get("source_feed"),
            },
        )

    @staticmethod
    def _organization_from_link(link: str) -> str | None:
        host = urlparse(link).netloc.lower()
        if not host:
            return None
        host = host[4:] if host.startswith("www.") else host
        label = host.split(".")[0].replace("-", " ").strip()
        return label.title() or None

    @staticmethod
    def _country_hint(text: str) -> str | None:
        lowered = f" {text.lower()} "
        for marker, country in _COUNTRY_HINTS:
            if marker in lowered:
                return country
        return None


__all__ = ["RssFeedConnector"]

