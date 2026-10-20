"""Archive record to sampling candidate (PRP-16 item 2, online mode, delta D2).

The archive keeps no prompt or response bodies, so online evaluation scores only what metadata can
support: ``task_success`` from a request or agent-run span outcome and ``tool_correctness`` from a
tool-call span outcome. The judge payload is a fixed whitelist of those metadata fields, never the
record itself. ``groundedness`` is not estimable online and is never fabricated.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Final

from neurosphere_core.evaluation.registry import Cloud, Dimension
from neurosphere_core.payload import find_body_fields

from neurosphere_workers.evaluation.models import (
    NO_AGENT,
    NO_DOMAIN,
    REASON_CLOUD_MISMATCH,
    REASON_NOT_SCORABLE,
    Candidate,
)

__all__ = ["ONLINE_LIMITED_DIMENSIONS", "candidate_from_record", "canonical_domain_id"]

ONLINE_LIMITED_DIMENSIONS: Final = {"groundedness": "bodies_not_archived"}
REASON_NO_ITEM_ID: Final = "no_item_id"

_DIMENSION_BY_SPAN: Final[dict[str, Dimension]] = {
    "request": "task_success",
    "agent_run": "task_success",
    "tool_call": "tool_correctness",
}
_PAYLOAD_FIELDS: Final = ("span_kind", "outcome", "duration_ms", "retry_attempt")
_BAD_ID_CHARS: Final = re.compile(r"[^a-z0-9._:/=-]")
_CANONICAL: Final = re.compile(
    r"^(commercial|government):[a-z0-9._-]+:[a-z0-9._-]+:[a-z0-9._-]+:[a-z0-9._/=-]+$"
)
_SEGMENT: Final = re.compile(r"^[a-z0-9._-]+$")


def canonical_domain_id(cloud: str, customer_id: str | None, domain: str | None) -> str | None:
    """``cloud:customer:neurosphere:domain:<domain>`` when every segment is representable."""
    if not customer_id or not domain:
        return None
    customer, dom = customer_id.lower(), domain.lower()
    if not _SEGMENT.match(customer) or not re.fullmatch(r"[a-z0-9._/=-]+", dom):
        return None
    candidate = f"{cloud}:{customer}:neurosphere:domain:{dom}"
    return candidate if _CANONICAL.fullmatch(candidate) else None


def _item_id(record: Mapping[str, Any], contract: Mapping[str, Any]) -> str | None:
    raw = record.get("doc_id") or contract.get("event_id")
    if not isinstance(raw, str):
        return None
    cleaned = _BAD_ID_CHARS.sub("-", raw.lower()).strip("-")
    return cleaned[:256] or None


def _event_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo else None


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def candidate_from_record(
    record: Mapping[str, Any], cloud: Cloud
) -> tuple[Candidate | None, str | None]:
    """``(candidate, None)`` or ``(None, exclusion reason)``. Never raises on odd records."""
    inner = record.get("contract")
    contract: Mapping[str, Any] = inner if isinstance(inner, Mapping) else record
    if contract.get("cloud") != cloud:
        return None, REASON_CLOUD_MISMATCH  # never bridge a record across clouds
    dimension = _DIMENSION_BY_SPAN.get(str(contract.get("span_kind")))
    if dimension is None:
        return None, REASON_NOT_SCORABLE
    item_id = _item_id(record, contract)
    if item_id is None:
        return None, REASON_NO_ITEM_ID
    customer = _text(contract.get("customer_id"))
    domain = _text(contract.get("domain_id"))
    subject = _text(contract.get("canonical_agent_id"))
    agent = subject or _text(contract.get("external_agent_id")) or NO_AGENT
    classification = contract.get("classification")
    return (
        Candidate(
            item_id=item_id,
            domain=domain or NO_DOMAIN,
            agent=agent,
            classification=classification if isinstance(classification, str) else None,
            dimension=dimension,
            payload={name: contract.get(name) for name in _PAYLOAD_FIELDS},
            customer_id=customer,
            domain_id=canonical_domain_id(cloud, customer, domain),
            subject_id=subject,
            raw_body_fields=len(find_body_fields(record)),
            event_time=_event_time(contract.get("event_time")),
        ),
        None,
    )
