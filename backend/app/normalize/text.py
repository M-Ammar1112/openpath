"""Text normalization helpers shared by dedup and ranking."""

from __future__ import annotations

import re
import unicodedata

_WS_RE = re.compile(r"\s+")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9+#]+")

STOPWORDS = frozenset(
    """
    a an and are as at be by for from has have in is it of on or that the this to was were will
    with you your we our us their they their his her he she i not but if then than so such
    do does did can could should would may might must about into over under after before
    during within without via per each other more most some any all one two three
    """.split()
)


def clean_text(value: str | None) -> str | None:
    """Collapse whitespace and normalize unicode. Returns None for empties."""
    if value is None:
        return None
    text = unicodedata.normalize("NFKC", str(value))
    text = _WS_RE.sub(" ", text).strip()
    return text or None


def normalize_key(value: str | None) -> str:
    """Aggressive normalization for identity/dedup keys (lowercase, alnum)."""
    text = clean_text(value) or ""
    text = text.lower()
    text = _NON_ALNUM_RE.sub(" ", text)
    return _WS_RE.sub(" ", text).strip()


def tokenize(text: str | None, *, drop_stopwords: bool = True) -> set[str]:
    """Lowercase word tokens; keeps tokens with digits/+# (e.g. c++, 5g, vlsi)."""
    if not text:
        return set()
    lowered = unicodedata.normalize("NFKC", text).lower()
    pieces = re.split(r"[^a-z0-9+#]+", lowered)
    tokens = {p for p in pieces if p and len(p) > 1}
    if not drop_stopwords:
        return tokens
    return {t for t in tokens if t not in STOPWORDS}


# Alias kept for readability at call sites that care about c++/c# tokens.
tokenize_with_symbols = tokenize


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def containment(a: set[str], b: set[str]) -> float:
    """|a ∩ b| / min(|a|, |b|) — good for short title vs long description."""
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def contains_term(haystack: str | None, term: str) -> bool:
    """True when every token of `term` appears in `haystack`.

    Token-based so symbols survive: searching "c++" only matches a c++ token,
    never every word starting with "c".
    """
    if not haystack or not term:
        return False
    needle = tokenize(term, drop_stopwords=False)
    if not needle:
        return False
    return needle <= tokenize(haystack, drop_stopwords=False)
