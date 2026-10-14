"""Generic JSON API connector base.

Subclasses supply the endpoint, the JSON path to the job list, and a
field mapping. Network access always goes through app.core.http.
"""

from __future__ import annotations

import json
from typing import Any, ClassVar

from app.connectors.base import FetchedRecord, FetchContext, ParsedItem, SourceConnector
from app.core.http import FetchError, get_http_client
from app.logging_config import get_logger

log = get_logger("openpath.connectors.json")


class JsonApiConnector(SourceConnector):
    """Fetch JSON, then let subclasses map records to ParsedItem."""

    connector_type: ClassVar[str] = "json_api"
    items_key: ClassVar[str | None] = None  # None => payload is already a list

    async def fetch(self, ctx: FetchContext) -> list[FetchedRecord]:
        url = ctx.endpoint_url or self.endpoint_url
        if not url:
            raise FetchError(f"{type(self).__name__} requires an endpoint_url")
        client = get_http_client()
        result = await client.get(
            url,
            params=self.options.get("params") or None,
            rate_limit_seconds=ctx.rate_limit_seconds,
        )
        return [
            FetchedRecord(
                url=result.url,
                content=result.content,
                content_type=result.content_type,
            )
        ]

    # -- helpers ------------------------------------------------------
    def extract_items(self, payload: Any) -> list[dict[str, Any]]:
        if self.items_key is None:
            return payload if isinstance(payload, list) else []
        node: Any = payload
        for part in self.items_key.split("."):
            if isinstance(node, dict):
                node = node.get(part)
            else:
                return []
        return node if isinstance(node, list) else []

    # -- to implement in subclasses ------------------------------------
    def parse(self, record: FetchedRecord) -> list[ParsedItem]:
        try:
            payload = json.loads(record.content.decode("utf-8", errors="replace"))
        except json.JSONDecodeError as exc:
            log.warning("json_parse_failed", extra={"url": record.url, "error": str(exc)})
            return []
        items: list[ParsedItem] = []
        for raw in self.extract_items(payload):
            if not isinstance(raw, dict):
                continue
            item = self.to_parsed_item(raw)
            if item is not None:
                items.append(item)
        return items

    def to_parsed_item(self, raw: dict[str, Any]) -> ParsedItem | None:  # pragma: no cover
        raise NotImplementedError
