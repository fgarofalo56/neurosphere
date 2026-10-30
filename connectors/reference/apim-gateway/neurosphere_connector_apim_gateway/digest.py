"""Deterministic digests for payloads and plans (canonical JSON, SHA-256)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from typing import Any

from neurosphere_connector_apim_gateway.models import PlanStep

__all__ = ["canonical_json", "payload_digest", "plan_digest"]


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def payload_digest(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def plan_digest(
    *, gateway_id: str, target: str, target_version: str, steps: Iterable[PlanStep]
) -> str:
    """SHA-256 over the intent facets; step order is part of the digest."""
    facets = {
        "gateway_id": gateway_id,
        "target": target,
        "target_version": target_version,
        "steps": [
            [
                s.index,
                s.resource_type.value,
                s.name,
                s.operation,
                s.expected,
                s.changes,
                s.payload_digest,
            ]
            for s in steps
        ],
    }
    return hashlib.sha256(canonical_json(facets).encode("utf-8")).hexdigest()
