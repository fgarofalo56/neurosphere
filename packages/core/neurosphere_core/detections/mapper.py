"""Finding to ``Recommendation`` mapper and the capability gate (PRP-61 item 2)."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any

from neurosphere_contracts.recommendations.v1.recommendation import Recommendation

from neurosphere_core.capabilities.loader import CapabilityMatrix
from neurosphere_core.detections.models import Finding

__all__ = ["finding_recommendation_id", "finding_to_recommendation", "read_unavailable"]

EXPIRY_INTERVALS = 2


def _utc(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def finding_recommendation_id(cloud: str, customer_id: str, finding: Finding) -> str:
    """Stable id: a hash of rule id, subject and observed value (idempotent upsert key)."""
    raw = "\x1f".join((finding.rule_id, finding.subject_id, finding.observed))
    token = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
    return f"{cloud}:{customer_id}:neurosphere:recommendation:det-{token}"


def finding_to_recommendation(
    finding: Finding,
    *,
    cloud: str,
    customer_id: str,
    domain_id: str,
    now: datetime,
    interval_seconds: float,
) -> Recommendation:
    """Map a finding to a stored recommendation.

    ``expires_at`` is two intervals after ``now``: while the finding keeps applying each run
    re-puts the same id with a fresh expiry; once it stops applying nothing extends it and the
    store's expiry filter retires it (no delete).
    """
    interval = timedelta(seconds=interval_seconds)
    coverage: dict[str, Any] = (
        {"method": "full", "observed_fraction": 1}
        if finding.coverage == "full"
        else {"method": "partial", "observed_fraction": None}
    )
    document: dict[str, Any] = {
        "schema_version": "1.0.0",
        "recommendation_id": finding_recommendation_id(cloud, customer_id, finding),
        "cloud": cloud,
        "customer_id": customer_id,
        "domain_id": finding.domain_id or domain_id,
        "kind": finding.kind,
        "subject_ids": [finding.subject_id],
        "method": "rule",
        "generator": {
            "generator_id": finding.rule_id,
            "generator_version": finding.rule_version,
        },
        "evidence_status": "sufficient",
        "evidence_window": {"start": _utc(now - interval), "end": _utc(now)},
        "evidence_ids": list(dict.fromkeys(finding.evidence))[:200],
        "coverage": coverage,
        "uncertainty": {"method": "not_estimable"},
        "prerequisites": [],
        "owner": {"resolution": "unresolved", "owner_id": None},
        "advisory": True,
        "created_at": _utc(now),
        "expires_at": _utc(now + EXPIRY_INTERVALS * interval),
    }
    return Recommendation.model_validate(document)


def read_unavailable(matrix: CapabilityMatrix, service: str, feature: str, cloud: str) -> bool:
    """True when every matrix row for the service feature in this cloud says ``unavailable``.

    No row at all is not "unavailable": the matrix only blocks what it explicitly disables.
    """
    rows = [
        r for r in matrix.rows if r.service == service and r.feature == feature and r.cloud == cloud
    ]
    return bool(rows) and all(r.availability == "unavailable" for r in rows)
