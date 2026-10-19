"""Snapshot harness: synthetic fixture documents and a canonical, system-field-free hash.

Synthetic data only. Never load production data here (CLAUDE.md hard constraint).
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable

__all__ = ["SYSTEM_FIELDS", "canonical_json", "snapshot_hash", "synthetic_snapshot"]

SYSTEM_FIELDS = frozenset({"_rid", "_etag", "_ts", "_self", "_attachments"})


def canonical_json(documents: Iterable[dict[str, Any]]) -> str:
    """Documents ordered by id, system fields dropped, keys sorted, no whitespace."""
    cleaned = [{k: v for k, v in d.items() if k not in SYSTEM_FIELDS} for d in documents]
    cleaned.sort(key=lambda d: str(d.get("id", "")))
    return json.dumps(cleaned, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def snapshot_hash(documents: Iterable[dict[str, Any]]) -> str:
    """SHA-256 over ``canonical_json``."""
    return hashlib.sha256(canonical_json(documents).encode("utf-8")).hexdigest()


def synthetic_snapshot(count: int = 12) -> list[dict[str, Any]]:
    """Deterministic synthetic documents at ``schema_version`` 0 (sandbox-style, no real data)."""
    return [
        {
            "id": f"doc-{i:04d}",
            "name": f"synthetic-model-{i}",
            "legacy_label": f"label-{i % 3}",
            "tags": [f"t{i % 2}"],
            "schema_version": 0,
        }
        for i in range(count)
    ]
