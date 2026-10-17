"""Trace spans -> inferred catalog edge candidates (PRP-10 item 3). Pure: no I/O, no clock.

Rules (all produce ``status = inferred``, provenance method ``trace_observation``):

* ``model_call`` span of an agent -> USES_MODEL agent -> model deployment
* ``tool_call`` span of an agent -> INVOKES agent -> tool (the span's canonical tool ref)
* ``delegation`` span + the child ``agent_run`` span (its parent_span_id is the delegation
  span_id) -> INVOKES delegating agent -> child agent

Confidence is a RULE output, not a measurement: corroborated delegation 0.9, a successful span
0.85, a failed or cancelled span 0.6. It is never presented without provenance and evidence IDs.

Evidence IDs are pointers only (``event:<doc_id>``, ``trace:<trace_id>``). No span attribute,
payload reference or body is copied onto an edge: raw telemetry stays outside the graph.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Final, Literal

from neurosphere_contracts.catalog.v1.invokes import InvokesRelation
from neurosphere_contracts.catalog.v1.uses_model import UsesModelRelation
from neurosphere_contracts.telemetry.v1.telemetry_event import TelemetryEvent
from neurosphere_core.catalog.protocol import CatalogEdge
from neurosphere_core.catalog.rules import format_timestamp

from neurosphere_workers.ingestion.models import parse_timestamp
from neurosphere_workers.projections.catalog.source import LoadedEvent

EDGE_ID_SOURCE: Final = "neurosphere"
INFERENCE_VERSION: Final = "trace-rules-1.0"
CONFIDENCE_DELEGATION: Final = 0.9
CONFIDENCE_OK: Final = 0.85
CONFIDENCE_FAILED: Final = 0.6

_CANONICAL: Final = re.compile(
    r"(commercial|government):[a-z0-9._-]+:[a-z0-9._-]+:[a-z0-9._-]+:[a-z0-9._/=-]+"
)
_TOKEN: Final = re.compile(r"[a-z0-9][a-z0-9._-]*")
_UNSAFE: Final = re.compile(r"[^a-z0-9._-]+")

RelationType = Literal["invokes", "uses_model"]


@dataclass(frozen=True, slots=True)
class EdgeCandidate:
    """One inferred edge observation, before it is merged into the stored edge."""

    relation_type: RelationType
    source_id: str
    target_id: str
    cloud: str
    customer_id: str
    domain_id: str
    provenance_source: str
    evidence_ids: tuple[str, ...]
    confidence: float
    first_observed: str
    last_observed: str
    rule: str

    @property
    def edge_id(self) -> str:
        return edge_id(
            self.cloud, self.customer_id, self.relation_type, self.source_id, self.target_id
        )


def edge_id(cloud: str, customer_id: str, relation: str, source_id: str, target_id: str) -> str:
    """Deterministic canonical edge ID: the same endpoints always map to the same edge."""
    digest = hashlib.sha256(f"{relation}|{source_id}|{target_id}".encode()).hexdigest()[:40]
    return f"{cloud}:{customer_id}:{EDGE_ID_SOURCE}:{relation}:{digest}"


def slug(value: str, fallback: str) -> str:
    """Lowercase ``[a-z0-9._-]`` form of ``value``; ``fallback`` when nothing usable remains."""
    cleaned = _UNSAFE.sub("-", value.lower()).strip("-._")
    return cleaned[:128] if _TOKEN.fullmatch(cleaned[:128]) else fallback


def deterministic_model_id(event: TelemetryEvent) -> str | None:
    """Fallback model-deployment ID ``cloud:customer:source:model_deployment:model-version``.

    It only matches a curated deployment when the catalog used the same naming; an alias
    (``AliasModelResolver``) is the way to point provider/model/version at a curated ID.
    """
    if event.model is None:
        return None
    parts = [event.model.root]
    if event.model_version is not None:
        parts.append(event.model_version.root)
    source = slug(event.source_id.root, "trace")
    tail = slug("-".join(parts), "")
    if not tail:
        return None
    return f"{event.cloud}:{event.customer_id.root}:{source}:model_deployment:{tail}"


def model_alias_value(event: TelemetryEvent) -> str | None:
    """``provider/model/version`` with absent parts omitted; the alias lookup value."""
    if event.model is None:
        return None
    parts = [p.root for p in (event.provider, event.model, event.model_version) if p is not None]
    return "/".join(parts)


def _owned(value: str, event: TelemetryEvent, type_: str) -> bool:
    if len(value) > 512 or not _CANONICAL.fullmatch(value):
        return False
    cloud, customer, _source, kind, _ident = value.split(":", 4)
    return cloud == event.cloud and customer == event.customer_id.root and kind == type_


def _domain(event: TelemetryEvent) -> str | None:
    domain = event.domain_id.root if event.domain_id is not None else None
    return domain if domain is not None and _owned(domain, event, "domain") else None


def _agent(event: TelemetryEvent) -> str | None:
    agent = event.canonical_agent_id.root if event.canonical_agent_id is not None else None
    return agent if agent is not None and _owned(agent, event, "agent") else None


def _evidence(*loaded: LoadedEvent) -> tuple[str, ...]:
    ids: dict[str, None] = {}
    for item in loaded:
        ids.setdefault(f"event:{item.doc_id}")
        if item.event.trace_id is not None:
            ids.setdefault(f"trace:{item.event.trace_id.root}")
    return tuple(ids)


def _window(*loaded: LoadedEvent) -> tuple[str, str]:
    times = sorted(parse_timestamp(item.event.event_time.root) for item in loaded)
    return format_timestamp(times[0]), format_timestamp(times[-1])


def _confidence(event: TelemetryEvent) -> float:
    return CONFIDENCE_OK if event.outcome == "success" else CONFIDENCE_FAILED


def _candidate(
    relation: RelationType,
    source_id: str,
    target_id: str,
    domain_id: str,
    confidence: float,
    rule: str,
    *loaded: LoadedEvent,
) -> EdgeCandidate:
    event = loaded[0].event
    first, last = _window(*loaded)
    return EdgeCandidate(
        relation_type=relation,
        source_id=source_id,
        target_id=target_id,
        cloud=event.cloud,
        customer_id=event.customer_id.root,
        domain_id=domain_id,
        provenance_source=slug(event.source_id.root, "trace"),
        evidence_ids=_evidence(*loaded),
        confidence=confidence,
        first_observed=first,
        last_observed=last,
        rule=rule,
    )


def model_call_candidate(loaded: LoadedEvent, model_id: str | None) -> EdgeCandidate | None:
    """USES_MODEL from a ``model_call`` span; ``model_id`` is the resolved deployment ID."""
    event = loaded.event
    if (
        event.span_kind != "model_call"
        or model_id is None
        or not _owned(model_id, event, "model_deployment")
    ):
        return None
    agent, domain = _agent(event), _domain(event)
    if agent is None or domain is None:
        return None
    return _candidate(
        "uses_model", agent, model_id, domain, _confidence(event), "model_call", loaded
    )


def tool_call_candidates(loaded: LoadedEvent) -> list[EdgeCandidate]:
    """INVOKES agent -> tool for each canonical tool reference of a ``tool_call`` span."""
    event = loaded.event
    if event.span_kind != "tool_call" or not event.data_source_refs:
        return []
    agent, domain = _agent(event), _domain(event)
    if agent is None or domain is None:
        return []
    tools = dict.fromkeys(r.ref for r in event.data_source_refs if _owned(r.ref, event, "tool"))
    return [
        _candidate("invokes", agent, tool, domain, _confidence(event), "tool_call", loaded)
        for tool in tools
    ]


def delegation_candidate(delegation: LoadedEvent, child_run: LoadedEvent) -> EdgeCandidate | None:
    """INVOKES delegating agent -> child agent from a delegation span and its child run.

    The pair must belong to the same trace, ``child_run`` must be an ``agent_run`` whose parent is
    the delegation span, and the two agents must differ.
    """
    parent, child = delegation.event, child_run.event
    if (
        parent.span_kind != "delegation"
        or child.span_kind != "agent_run"
        or parent.span_id is None
        or child.parent_span_id is None
        or child.parent_span_id.root != parent.span_id.root
        or parent.trace_id is None
        or child.trace_id is None
        or parent.trace_id.root != child.trace_id.root
    ):
        return None
    source, target, domain = _agent(parent), _agent(child), _domain(parent)
    if source is None or target is None or domain is None or source == target:
        return None
    return _candidate(
        "invokes",
        source,
        target,
        domain,
        CONFIDENCE_DELEGATION,
        "delegation",
        delegation,
        child_run,
    )


def build_edge(candidate: EdgeCandidate, now_text: str) -> CatalogEdge:
    """The new-observation edge document handed to ``rules.merge_observation``.

    ``version`` and ``etag`` are placeholders: the repository assigns the real ones on write.
    """
    doc: dict[str, Any] = {
        "schema_version": "1.0.0",
        "id": candidate.edge_id,
        "relation_type": candidate.relation_type,
        "version": 1,
        "etag": "pending",
        "source_id": candidate.source_id,
        "target_id": candidate.target_id,
        "cloud": candidate.cloud,
        "customer_id": candidate.customer_id,
        "domain_id": candidate.domain_id,
        "provenance": {
            "method": "trace_observation",
            "source_id": candidate.provenance_source,
            "inference_version": INFERENCE_VERSION,
            "recorded_at": candidate.last_observed,
        },
        "evidence_ids": list(candidate.evidence_ids),
        "security_evidence_ids": [],
        "confidence": candidate.confidence,
        "first_observed": candidate.first_observed,
        "last_observed": candidate.last_observed,
        "validity": {"valid_from": candidate.first_observed, "valid_to": None},
        "status": "inferred",
        "lock": {"locked": False},
        "created_at": now_text,
        "updated_at": now_text,
    }
    if candidate.relation_type == "invokes":
        return InvokesRelation.model_validate(doc)
    return UsesModelRelation.model_validate(doc)
