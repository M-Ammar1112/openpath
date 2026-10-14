"""Safe HTML handling: convert to plain text, never execute or render raw.

Collected descriptions are stored as text and rendered as React text nodes,
so script/`on*` attributes cannot reach a browser. These helpers exist so
connectors can also *analyze* descriptions (skill extraction) without
carrying markup noise.
"""

from __future__ import annotations

import html as html_module
import re

from bs4 import BeautifulSoup

_WS_RE = re.compile(r"[ \t\r\f\v]+")
_MANY_NEWLINES_RE = re.compile(r"\n{3,}")
_BLOCK_TAGS = ("p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section")

MAX_TEXT_CHARS = 8000


def html_to_text(value: str | None, *, max_chars: int = MAX_TEXT_CHARS) -> str | None:
    """Convert an HTML fragment to cleaned plain text.

    - unescapes double-escaped markup (common in JSON feeds)
    - drops script/style/noscript content entirely
    - inserts newlines at block boundaries
    - truncates very long descriptions
    """
    if not value:
        return None
    text = str(value)
    # Feeds frequently double-escape ("&lt;p&gt;"); unescape once and re-check.
    if "&lt;" in text and "<" not in text:
        text = html_module.unescape(text)
    if "<" in text:
        soup = BeautifulSoup(text, "lxml")
        for tag in soup(["script", "style", "noscript", "iframe", "object", "embed"]):
            tag.decompose()
        for tag in soup.find_all(_BLOCK_TAGS):
            tag.insert_after("\n")
        text = soup.get_text(separator="")
    text = html_module.unescape(text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _WS_RE.sub(" ", text)
    lines = [line.strip() for line in text.split("\n")]
    text = "\n".join(line for line in lines if line)
    text = _MANY_NEWLINES_RE.sub("\n\n", text).strip()
    if not text:
        return None
    return text[:max_chars]


def looks_like_html(value: str | None) -> bool:
    if not value:
        return False
    return bool(re.search(r"<\s*(p|div|br|ul|li|strong|em|a)\b", value, re.IGNORECASE))


__all__ = ["MAX_TEXT_CHARS", "html_to_text", "looks_like_html"]
