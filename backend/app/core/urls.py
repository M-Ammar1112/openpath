"""URL safety and canonicalization helpers."""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Query params that never change page identity.
_STRIP_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
}


class InvalidURLError(ValueError):
    """Raised when a URL is missing, malformed, or not http(s)."""


def validate_http_url(url: str | None, *, field: str = "url") -> str:
    """Require an absolute http(s) URL. Returns the URL unchanged."""
    if not url or not url.strip():
        raise InvalidURLError(f"{field}: URL is required")
    parts = urlsplit(url.strip())
    if parts.scheme not in {"http", "https"}:
        raise InvalidURLError(f"{field}: only http/https URLs are allowed: {url!r}")
    if not parts.netloc:
        raise InvalidURLError(f"{field}: missing host: {url!r}")
    if any(ch.isspace() for ch in url):
        raise InvalidURLError(f"{field}: URL contains whitespace: {url!r}")
    return url.strip()


def is_safe_http_url(url: str | None) -> bool:
    try:
        validate_http_url(url)
    except InvalidURLError:
        return False
    return True


def canonicalize_url(url: str) -> str:
    """Normalize a URL for duplicate detection.

    Lowercases scheme/host, strips fragments, tracking params, default
    ports, and a trailing slash on the path.
    """
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    host = parts.netloc.lower()
    for default in (":80", ":443"):
        if host.endswith(default) and (
            (default == ":80" and scheme == "http") or (default == ":443" and scheme == "https")
        ):
            host = host[: -len(default)]
    path = parts.path or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    query_pairs = [(k, v) for k, v in parse_qsl(parts.query) if k not in _STRIP_PARAMS]
    query = urlencode(query_pairs, doseq=True)
    return urlunsplit((scheme, host, path, query, ""))


def url_domain(url: str) -> str:
    """Host of a URL without the www prefix (for display labels)."""
    host = urlsplit(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host