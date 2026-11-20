"""The one tokenizer for the agent/tool matcher (task text, tags and capabilities)."""

from __future__ import annotations

import re

__all__ = ["STOP_WORDS", "TOKEN_LIMIT", "normalize_tokens"]

TOKEN_LIMIT = 32

_SPLIT = re.compile(r"[^a-z0-9]+")

STOP_WORDS: frozenset[str] = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "in",
        "into",
        "is",
        "it",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "with",
    }
)


def normalize_tokens(text: str, limit: int = TOKEN_LIMIT) -> tuple[str, ...]:
    """Lowercase, split on non-alphanumerics, drop stop words, de-duplicate (order kept), cap.

    The text is only ever split into tokens; it is never parsed or evaluated.
    """
    seen: dict[str, None] = {}
    for tok in _SPLIT.split(text.lower()):
        if tok and tok not in STOP_WORDS and tok not in seen:
            seen[tok] = None
            if len(seen) >= limit:
                break
    return tuple(seen)
