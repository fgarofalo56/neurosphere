"""Response models of the read-only capture admin routes (PRP-103 item 5).

Metadata and counters only. A capture policy holds no content (ids, parts, modes, sampling,
retention, state and the approval audit id); the status view is an off reason and integer
counters keyed by reason codes. Nothing here carries captured text, key material, a key URI or a
connection string, and these are API-local models (not contract models used as
``response_model``), so the ``openapi.json`` components keep their own names.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Final, Literal

from neurosphere_core.interactions import CapturePolicy
from pydantic import BaseModel, ConfigDict

__all__ = [
    "DEFAULT_PAGE_LIMIT",
    "MAX_PAGE_LIMIT",
    "NOT_CONFIGURED",
    "CaptureCountersView",
    "CapturePolicyPage",
    "CapturePolicyView",
    "CaptureSamplingView",
    "CaptureStatusView",
    "PolicyStateCounts",
    "counters_view",
    "policy_view",
]

DEFAULT_PAGE_LIMIT: Final = 100
MAX_PAGE_LIMIT: Final = 500
#: Off reason when the ``interactions`` builder was not composed or built no policy store.
NOT_CONFIGURED: Final = "capture_not_configured"

#: Counter keys must look like reason codes; anything else is dropped, never echoed.
_REASON_CODE: Final = re.compile(r"^[a-z][a-z0-9_]{0,63}$")

PolicyState = Literal["proposed", "active", "suspended", "retired"]


class _View(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CaptureSamplingView(_View):
    rate: float
    max_per_minute: int


class CapturePolicyView(_View):
    """One capture policy, metadata only (no content exists on a policy)."""

    policy_id: str
    display_name: str
    version: int
    previous_version: int | None
    domain_id: str
    source_ids: list[str]
    parts: list[str]
    detector_set_version: str
    customer_dictionary_ids: list[str]
    redaction_mode: str
    kept_categories: list[str]
    sampling: CaptureSamplingView
    max_part_chars: int | None
    retention_class: str
    retention_days: int | None
    state: PolicyState
    approved_intent_id: str | None
    approved_audit_id: str | None
    effective_from: str | None


class CapturePolicyPage(_View):
    items: list[CapturePolicyView]
    truncated: bool
    #: ``False`` when no capture policy store is composed (``reason`` says why).
    configured: bool
    reason: str | None


class PolicyStateCounts(_View):
    total: int
    proposed: int
    active: int
    suspended: int
    retired: int


class CaptureCountersView(_View):
    """Deployment-wide capture counters (integers keyed by reason codes only)."""

    captured: int
    capture_skipped_no_policy: int
    capture_skipped_item_cap: int
    skipped_reasons: dict[str, int]
    capture_failed: dict[str, int]
    capture_failed_total: int
    capture_shed: int
    shed_reasons: dict[str, int]
    audit_write_failed: int
    failure_record_failed: int
    cleanup_failed: int
    in_flight: int


class CaptureStatusView(_View):
    """Whether capture is on and, when off, the reason code.

    ``counters`` are deployment-wide, so they are present only for a customer-wide caller and
    only once the capture edge has been built; a domain-scoped view gets ``null``.
    """

    state: Literal["active", "off"]
    off_reason: str | None
    configured: bool
    domain_id: str | None
    policies: PolicyStateCounts
    policies_truncated: bool
    counters: CaptureCountersView | None
    counters_scope: Literal["customer"]


def policy_view(policy: CapturePolicy) -> CapturePolicyView:
    return CapturePolicyView(
        policy_id=policy.policy_id,
        display_name=policy.display_name.root,
        version=policy.version,
        previous_version=policy.previous_version,
        domain_id=policy.domain,
        source_ids=[s.root for s in policy.source_ids],
        parts=[p.root for p in policy.parts],
        detector_set_version=policy.detector_set_version,
        customer_dictionary_ids=[d.root for d in policy.customer_dictionary_ids or []],
        redaction_mode=policy.redaction_mode or "redact_all_detections",
        kept_categories=[c.root for c in policy.kept_categories or []],
        sampling=CaptureSamplingView(
            rate=policy.sampling.rate, max_per_minute=policy.sampling.max_per_minute
        ),
        max_part_chars=policy.max_part_chars,
        retention_class=policy.retention_class,
        retention_days=policy.retention_days,
        state=policy.state,
        approved_intent_id=_root(policy.approved_intent_id),
        approved_audit_id=_root(policy.approved_audit_id),
        effective_from=_root(policy.effective_from),
    )


def _root(value: object) -> str | None:
    if value is None:
        return None
    root = getattr(value, "root", value)
    return str(root)


def _int(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _reasons(value: object) -> dict[str, int]:
    if not isinstance(value, Mapping):
        return {}
    return {
        str(k): _int(v)
        for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))  # pyright: ignore[reportUnknownArgumentType, reportUnknownLambdaType]
        if isinstance(k, str) and _REASON_CODE.fullmatch(k)
    }


def counters_view(snapshot: Mapping[str, object]) -> CaptureCountersView:
    """Integers and reason-code keyed integers from ``EdgeCaptureStats.snapshot()`` only."""
    return CaptureCountersView(
        captured=_int(snapshot.get("captured")),
        capture_skipped_no_policy=_int(snapshot.get("capture_skipped_no_policy")),
        capture_skipped_item_cap=_int(snapshot.get("capture_skipped_item_cap")),
        skipped_reasons=_reasons(snapshot.get("skipped_reasons")),
        capture_failed=_reasons(snapshot.get("capture_failed")),
        capture_failed_total=_int(snapshot.get("capture_failed_total")),
        capture_shed=_int(snapshot.get("capture_shed")),
        shed_reasons=_reasons(snapshot.get("shed_reasons")),
        audit_write_failed=_int(snapshot.get("audit_write_failed")),
        failure_record_failed=_int(snapshot.get("failure_record_failed")),
        cleanup_failed=_int(snapshot.get("cleanup_failed")),
        in_flight=_int(snapshot.get("in_flight")),
    )
