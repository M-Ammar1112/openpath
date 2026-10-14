"""Manual-import connector for curated entries.

Some valuable sources (scholarship databases, university funding pages)
do not permit automated collection. For those, OpenPath supports a manual
import: a human curates a JSON file, and this connector loads it with full
fidelity — funding, deadlines, tuition, eligibility, and the official URL.

The importer never invents data: every field comes from the curated file.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, ClassVar

from app.connectors.base import (
    FetchedRecord,
    FetchContext,
    NormalizedOpportunity,
    ParsedItem,
    SourceConnector,
)
from app.core.html import html_to_text
from app.core.http import FetchError
from app.enums import DegreeLevel, FundingType, OpportunityType
from app.logging_config import get_logger
from app.normalize.fields import extract_skills, normalize_degree_level, parse_date

log = get_logger("openpath.connectors.manual")


class ManualImportConnector(SourceConnector):
    """Load curated opportunities from a local JSON file.

    Options:
      - `file`: path (absolute or repo-relative) to the JSON file
      - `skills`: vocabulary used for skill extraction
    See `docs/SOURCES.md` for the schema and `config/manual_import.sample.json`
    for a working example.
    """

    connector_type: ClassVar[str] = "manual"

    def _resolve_path(self, ctx: FetchContext) -> Path:
        raw = self.options.get("file") or ctx.endpoint_url or self.endpoint_url
        if not raw:
            raise FetchError("manual connector requires options['file']")
        path = Path(str(raw)).expanduser()
        if not path.is_absolute():
            from app.config import REPO_ROOT

            path = REPO_ROOT / path
        if not path.exists():
            raise FetchError(f"manual import file not found: {path}")
        return path

    async def fetch(self, ctx: FetchContext) -> list[FetchedRecord]:
        path = self._resolve_path(ctx)
        try:
            content = path.read_bytes()
        except OSError as exc:
            raise FetchError(f"cannot read manual import file {path}: {exc}") from exc
        return [
            FetchedRecord(url=path.as_uri(), content=content, content_type="application/json")
        ]

    def parse(self, record: FetchedRecord) -> list[ParsedItem]:
        try:
            payload = json.loads(record.content.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            log.warning("manual_import_parse_failed", extra={"url": record.url, "error": str(exc)})
            return []
        rows = payload.get("opportunities") if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            log.warning("manual_import_unexpected_shape", extra={"url": record.url})
            return []
        items: list[ParsedItem] = []
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            title = str(row.get("title") or "").strip()
            url = str(row.get("official_url") or row.get("url") or "").strip()
            if not title or not url:
                log.warning(
                    "manual_import_row_skipped",
                    extra={"index": index, "reason": "missing title/url"},
                )
                continue
            items.append(
                ParsedItem(
                    external_id=str(row.get("external_id") or f"manual-{index}"),
                    title=title,
                    link=url,
                    summary=html_to_text(row.get("description")),
                    published_at=row.get("discovered_at"),
                    extra={k: v for k, v in row.items() if k not in {"title", "description"}},
                )
            )
        return items

    # -- normalization --------------------------------------------------
    def normalize(self, item: ParsedItem) -> NormalizedOpportunity:
        extra = item.extra
        raw_type = extra.get("opportunity_type") or extra.get("type")
        opportunity_type = OpportunityType.OTHER
        if raw_type:
            try:
                opportunity_type = OpportunityType(str(raw_type))
            except ValueError:
                opportunity_type = OpportunityType.OTHER
        funding_raw = extra.get("funding_type_raw") or extra.get("funding")
        degree_raw = extra.get("degree_level")
        text = f"{item.title}. {item.summary or ''}"
        degree = (
            normalize_degree_level(str(degree_raw)) if degree_raw else normalize_degree_level(text)
        )
        return NormalizedOpportunity(
            title=item.title,
            official_url=item.link,
            opportunity_type=opportunity_type,
            organization=extra.get("organization") or extra.get("university"),
            country=extra.get("country"),
            city=extra.get("city"),
            field=extra.get("field"),
            degree_level=degree.value if degree is not DegreeLevel.UNKNOWN else None,
            degree_level_raw=str(degree_raw) if degree_raw else None,
            funding_type=self._funding(extra.get("funding_type")),
            funding_type_raw=str(funding_raw) if funding_raw else None,
            tuition=_float_or_none(extra.get("tuition")),
            tuition_currency=extra.get("tuition_currency"),
            stipend=_float_or_none(extra.get("stipend")),
            salary=_float_or_none(extra.get("salary")),
            salary_currency=extra.get("salary_currency"),
            deadline=parse_date(extra.get("deadline")),
            opens_at=parse_date(extra.get("opens_at")),
            eligibility=extra.get("eligibility"),
            required_degree=extra.get("required_degree"),
            gpa_requirement=extra.get("gpa_requirement"),
            english_requirement=extra.get("english_requirement"),
            ielts_requirement=extra.get("ielts_requirement"),
            toefl_requirement=extra.get("toefl_requirement"),
            gre_requirement=extra.get("gre_requirement"),
            experience_requirement=extra.get("experience_requirement"),
            citizenship_restrictions=extra.get("citizenship_restrictions"),
            age_restrictions=extra.get("age_restrictions"),
            research_area=extra.get("research_area"),
            skills=list(extra.get("skills") or [])
            or extract_skills(text, self.options.get("skills") or []),
            tags=list(extra.get("tags") or []),
            description=item.summary,
            remote_status=extra.get("remote_status"),
            source_key="",
            source_name="",
            external_id=item.external_id,
            raw_payload=dict(extra),
        )

    @staticmethod
    def _funding(explicit: Any) -> FundingType:
        """Curated funding must be explicit; never inferred at import time."""
        if not explicit:
            return FundingType.UNKNOWN
        try:
            return FundingType(str(explicit))
        except ValueError:
            return FundingType.UNKNOWN


def _float_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


__all__ = ["ManualImportConnector"]

