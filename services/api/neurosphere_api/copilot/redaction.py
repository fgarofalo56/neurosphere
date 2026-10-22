"""Redaction and pseudonymization applied before anything is stored (PRP-19 item 2).

Order matters: people first (email addresses and canonical person ids become stable pseudonyms
when a vault key is configured, else a fixed marker), then the shared outbound redaction rules
from the model adapters (secrets, tokens, GUIDs, card and SSN shapes). The result is what a
stored turn holds; the unredacted text is never persisted.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from collections.abc import Mapping
from typing import Any, Final

from neurosphere_core.copilot.models import redact_text

__all__ = ["redact_for_storage", "redact_mapping_for_storage"]

_EMAIL: Final = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PERSON_ID: Final = re.compile(
    r"\b(?:commercial|government):[a-z0-9._-]+:[a-z0-9._-]+:person:[a-z0-9._/=-]+", re.IGNORECASE
)


def _pseudonym(value: str, key: bytes | None) -> str:
    if key is None:
        return "[person]"
    digest = hmac.new(key, value.lower().encode(), hashlib.sha256).hexdigest()
    return f"person-{digest[:10]}"


def redact_for_storage(text: str, *, key: bytes | None, max_chars: int) -> str:
    """Pseudonymize people, redact secret- and PII-shaped substrings, bound the length."""
    text = _EMAIL.sub(lambda m: _pseudonym(m.group(0), key), text)
    text = _PERSON_ID.sub(lambda m: _pseudonym(m.group(0), key), text)
    return redact_text(text)[:max_chars]


def redact_mapping_for_storage(
    value: Mapping[str, Any], *, key: bytes | None, max_chars: int
) -> dict[str, Any]:
    """Every string leaf of a JSON-like mapping goes through :func:`redact_for_storage`."""

    def walk(node: Any) -> Any:
        if isinstance(node, str):
            return redact_for_storage(node, key=key, max_chars=max_chars)
        if isinstance(node, Mapping):
            return {k: walk(v) for k, v in node.items()}  # pyright: ignore[reportUnknownVariableType]
        if isinstance(node, list | tuple):
            return [walk(v) for v in node]  # pyright: ignore[reportUnknownVariableType]
        return node

    return {k: walk(v) for k, v in value.items()}
