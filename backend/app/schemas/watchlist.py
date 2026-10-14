"""Watchlist and notification schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class WatchlistCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    query: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True

    @field_validator("query")
    @classmethod
    def _limit_query_size(cls, value: dict[str, Any]) -> dict[str, Any]:
        if len(value) > 25:
            raise ValueError("watchlist query has too many keys")
        return value


class WatchlistUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    query: dict[str, Any] | None = None
    enabled: bool | None = None


class WatchlistRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None = None
    query: dict[str, Any] = Field(default_factory=dict)
    enabled: bool
    created_at: datetime
    last_checked_at: datetime | None = None


class NotificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    watchlist_id: int
    opportunity_id: int
    message: str
    is_read: bool
    created_at: datetime


__all__ = [
    "NotificationRead",
    "WatchlistCreate",
    "WatchlistRead",
    "WatchlistUpdate",
]
