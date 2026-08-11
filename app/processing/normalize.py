"""Event text normalization utilities (Sprint 4).

Used by `app.processing.deduplicate` to compare titles across sources
without being thrown off by punctuation/casing/stopword differences --
e.g. "Apple Beats Q3 Earnings" vs. "apple beats q3 earnings, shares rise".
"""
from __future__ import annotations

import re

_PUNCTUATION_RE = re.compile(r"[^\w\s]")
_WHITESPACE_RE = re.compile(r"\s+")

# Small stopword list -- enough to stop common connector words from
# dominating the token-overlap comparison; not meant to be linguistically
# exhaustive.
_STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "of", "in", "on", "at", "to",
    "for", "with", "by", "is", "are", "was", "were", "be", "as", "it",
    "its", "this", "that", "from", "into", "after", "before", "over",
    "than", "amid", "says", "said", "new", "will",
}


def normalize_title(title: str) -> str:
    """Lowercase, strip punctuation, and collapse whitespace."""
    lowered = title.lower()
    no_punct = _PUNCTUATION_RE.sub(" ", lowered)
    return _WHITESPACE_RE.sub(" ", no_punct).strip()


def title_tokens(title: str) -> set[str]:
    """Normalized, stopword-filtered token set for a title -- the input to
    the Jaccard similarity comparison in `app.processing.deduplicate`."""
    normalized = normalize_title(title)
    return {tok for tok in normalized.split() if tok not in _STOPWORDS and len(tok) > 1}
