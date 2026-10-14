"""Connector registry: connector_type -> SourceConnector implementation.

Adding a new source integration means adding a class to `_REGISTRY` and a
`Source` row (or seed entry). No central code changes are required for
additional feeds, job boards, or manual imports.
"""

from __future__ import annotations

from typing import Any

from app.connectors.base import SourceConnector
from app.connectors.job_boards import ArbeitnowConnector, AshbyConnector, RemotiveConnector
from app.connectors.manual import ManualImportConnector
from app.connectors.rss import RssFeedConnector

_REGISTRY: dict[str, type[SourceConnector]] = {
    ArbeitnowConnector.connector_type: ArbeitnowConnector,
    AshbyConnector.connector_type: AshbyConnector,
    RemotiveConnector.connector_type: RemotiveConnector,
    ManualImportConnector.connector_type: ManualImportConnector,
    RssFeedConnector.connector_type: RssFeedConnector,
}


class UnknownConnectorTypeError(KeyError):
    """Raised when a source references a connector type we do not implement."""


def register_connector(cls: type[SourceConnector]) -> type[SourceConnector]:
    """Register (or replace) a connector implementation by its type key."""
    if not cls.connector_type or cls.connector_type == "abstract":
        raise ValueError("connector_type must be set on the connector class")
    _REGISTRY[cls.connector_type] = cls
    return cls


def available_connector_types() -> list[str]:
    return sorted(_REGISTRY)


def build_connector(
    connector_type: str,
    *,
    endpoint_url: str | None = None,
    options: dict[str, Any] | None = None,
) -> SourceConnector:
    """Instantiate the connector implementation for a configured source."""
    try:
        cls = _REGISTRY[connector_type]
    except KeyError as exc:  # pragma: no cover - guarded by source seeding
        raise UnknownConnectorTypeError(
            f"unknown connector type {connector_type!r}; known: {', '.join(available_connector_types())}"
        ) from exc
    return cls(endpoint_url=endpoint_url, options=options or {})


__all__ = [
    "UnknownConnectorTypeError",
    "available_connector_types",
    "build_connector",
    "register_connector",
]
