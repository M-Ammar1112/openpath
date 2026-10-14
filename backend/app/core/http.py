"""Central HTTP client for data acquisition.

Every connector must go through this client so lawful collection is the
default: honest User-Agent, per-host rate limiting, timeouts, payload size
caps, robots.txt gating, and a small on-disk response cache.

The cache lives under `data/cache/` as JSON files keyed by URL hash.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from urllib import robotparser
from urllib.parse import urlsplit

import httpx

from app.config import settings
from app.logging_config import get_logger

log = get_logger("openpath.http")

MAX_RESPONSE_BYTES = 5 * 1024 * 1024  # 5 MiB safety cap


class FetchBlockedError(RuntimeError):
    """Raised when robots.txt disallows the requested path."""


class FetchError(RuntimeError):
    """Raised for network/HTTP failures after retries."""


@dataclass(slots=True)
class FetchResult:
    url: str
    status_code: int
    content: bytes
    content_type: str
    from_cache: bool = False

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")


class _RateLimiter:
    """Minimum delay between requests to the same host."""

    def __init__(self, default_delay: float) -> None:
        self.default_delay = default_delay
        self._last: dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def wait(self, host: str, delay: float | None = None) -> None:
        async with self._lock:
            now = time.monotonic()
            min_delay = self.default_delay if delay is None else delay
            last = self._last.get(host, 0.0)
            sleep_for = last + min_delay - now
            if sleep_for > 0:
                await asyncio.sleep(sleep_for)
            self._last[host] = time.monotonic()


class _RobotsCache:
    def __init__(self) -> None:
        self._parsers: dict[str, robotparser.RobotFileParser | None] = {}

    async def allowed(self, client: httpx.AsyncClient, url: str, ua: str) -> bool:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._parsers:
            parser: robotparser.RobotFileParser | None = robotparser.RobotFileParser()
            robots_url = f"{origin}/robots.txt"
            try:
                resp = await client.get(robots_url, timeout=10.0)
                if resp.status_code >= 400:
                    parser = None  # no robots.txt → nothing disallowed
                else:
                    parser.parse(resp.text.splitlines())
            except (httpx.HTTPError, OSError):
                parser = None
            self._parsers[origin] = parser
        parser = self._parsers[origin]
        if parser is None:
            return True
        return parser.can_fetch(ua, url)


class HttpClient:
    """Shared fetcher. One instance per process is enough."""

    def __init__(
        self,
        *,
        user_agent: str | None = None,
        timeout: float | None = None,
        rate_limit_seconds: float | None = None,
        respect_robots: bool | None = None,
        cache_ttl_hours: float | None = None,
        cache_dir: Path | None = None,
        use_cache: bool = True,
    ) -> None:
        self.user_agent = user_agent or settings.crawler_user_agent
        self.timeout = timeout if timeout is not None else settings.crawler_timeout_seconds
        self.respect_robots = (
            respect_robots if respect_robots is not None else settings.crawler_respect_robots
        )
        self.cache_ttl = (
            cache_ttl_hours if cache_ttl_hours is not None else settings.crawler_cache_ttl_hours
        )
        self.cache_dir = cache_dir or (settings.data_dir / "cache")
        self.use_cache = use_cache
        self.rate_limiter = _RateLimiter(
            rate_limit_seconds
            if rate_limit_seconds is not None
            else settings.crawler_rate_limit_seconds
        )
        self._robots = _RobotsCache()
        self._client = httpx.AsyncClient(
            headers={"User-Agent": self.user_agent, "Accept": "*/*"},
            timeout=self.timeout,
            follow_redirects=True,
        )

    # -- cache ---------------------------------------------------------
    def _cache_path(self, url: str) -> Path:
        digest = hashlib.sha256(url.encode()).hexdigest()
        return self.cache_dir / f"{digest}.json"

    def _read_cache(self, url: str) -> FetchResult | None:
        if not self.use_cache or self.cache_ttl <= 0:
            return None
        path = self._cache_path(url)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if time.time() - payload.get("stored_at", 0) > self.cache_ttl * 3600:
            return None
        return FetchResult(
            url=url,
            status_code=payload["status_code"],
            content=payload["content"].encode("utf-8"),
            content_type=payload.get("content_type", ""),
            from_cache=True,
        )

    def _write_cache(self, result: FetchResult) -> None:
        if not self.use_cache or result.status_code != 200:
            return
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            payload = {
                "stored_at": time.time(),
                "status_code": result.status_code,
                "content_type": result.content_type,
                "content": result.content.decode("utf-8", errors="replace"),
            }
            self._cache_path(result.url).write_text(
                json.dumps(payload), encoding="utf-8"
            )
        except OSError as exc:  # cache problems must never break ingestion
            log.warning("cache_write_failed", extra={"url": result.url, "error": str(exc)})

    # -- fetching ------------------------------------------------------
    async def get(
        self,
        url: str,
        *,
        params: dict[str, str] | None = None,
        rate_limit_seconds: float | None = None,
        use_cache: bool = True,
    ) -> FetchResult:
        cache_key = url + (
            ("?" + "&".join(f"{k}={v}" for k, v in sorted(params.items()))) if params else ""
        )
        if use_cache:
            cached = self._read_cache(cache_key)
            if cached is not None:
                return cached

        host = urlsplit(url).netloc
        if self.respect_robots:
            allowed = await self._robots.allowed(self._client, url, self.user_agent)
            if not allowed:
                raise FetchBlockedError(f"robots.txt disallows fetching {url}")
        await self.rate_limiter.wait(host, rate_limit_seconds)

        try:
            response = await self._client.get(url, params=params)
        except httpx.HTTPError as exc:
            raise FetchError(f"request failed for {url}: {exc}") from exc

        if len(response.content) > MAX_RESPONSE_BYTES:
            raise FetchError(f"response exceeds {MAX_RESPONSE_BYTES} bytes for {url}")
        if response.status_code >= 400:
            raise FetchError(f"HTTP {response.status_code} for {url}")

        result = FetchResult(
            url=cache_key,
            status_code=response.status_code,
            content=response.content,
            content_type=response.headers.get("content-type", ""),
        )
        if use_cache:
            self._write_cache(result)
        return result

    async def aclose(self) -> None:
        await self._client.aclose()


_default_client: HttpClient | None = None


def get_http_client() -> HttpClient:
    global _default_client
    if _default_client is None:
        _default_client = HttpClient()
    return _default_client


def reset_http_client() -> None:
    global _default_client
    _default_client = None