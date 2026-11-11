"""Production ``EvidenceReader`` for the copilot's ``get_evidence`` tool (PRP-19 round 2, item 9).

Resolves evidence ids over the EXISTING scope-filtered stores with point reads only (no scans):

=====================  ========================================================================
kind                   store / read
=====================  ========================================================================
``recommendation``     ``RecommendationStore.get(scope, domain, id)``; ``observed_at`` = created_at
``evaluation_result``  ``EvaluationStore.get_result(scope, domain, id)`` when the store exposes it
                       (the shipped ``EvaluationStore`` protocol has no by-id read, so the kind is
                       omitted until it does; no scan fallback); ``observed_at`` = completed_at
``catalog_entity``     ``CatalogRepository.get_entity(scope, id)`` (domain checked against
                       ``domain_ids``); ``observed_at`` = updated_at
=====================  ========================================================================

Kinds with no store (``policy``, ``document``, ``telemetry_query``, ``cost_record``) are omitted.

Deterministic id dispatch (ids carry their kind in the id grammar, so exactly one store is read):

1. ``eval:`` prefix -> ``evaluation_result``;
2. ``<cloud>:<customer>:<source>:recommendation:<name>`` (five segments, fourth is
   ``recommendation``) -> ``recommendation``;
3. anything else -> ``catalog_entity``.

Rules: lookups are confined to the server-derived ``domain_ids``; an unknown, unreadable or
out-of-domain id (or a store error) is omitted, never raised and never explained; ``ref`` is a
pointer (``<kind>:<id>``), never a body; at most ``MAX_EVIDENCE_IDS`` ids are read per call
(extras are dropped). A store that is not wired omits its kind.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Final

from neurosphere_core.copilot.tools import EvidenceRecord
from neurosphere_core.scope import IdentityScope

__all__ = ["MAX_EVIDENCE_IDS", "StoreEvidenceReader"]

MAX_EVIDENCE_IDS: Final = 50  # the get_evidence tool's own evidence_ids max_length
_EVAL_PREFIX: Final = "eval:"


def _text(value: Any) -> str | None:
    if value is None:
        return None
    root = getattr(value, "root", value)
    return root if isinstance(root, str) else str(root)


def _is_recommendation(evidence_id: str) -> bool:
    parts = evidence_id.split(":")
    return len(parts) == 5 and parts[3] == "recommendation"


def _entity_domain(entity: Any) -> str | None:
    domain = getattr(entity, "domain_id", None)
    if domain is not None:
        return _text(domain)
    if getattr(entity, "entity_type", None) == "domain":
        return _text(getattr(entity, "id", None))
    return None


class StoreEvidenceReader:
    def __init__(
        self,
        *,
        recommendations: Any | None = None,
        evaluations: Any | None = None,
        catalog: Any | None = None,
    ) -> None:
        self._recommendations = recommendations
        self._evaluations = evaluations
        self._catalog = catalog

    async def get_many(
        self, scope: IdentityScope, domain_ids: Sequence[str], evidence_ids: Sequence[str]
    ) -> Sequence[EvidenceRecord]:
        domains = [d for d in dict.fromkeys(domain_ids) if d in scope.allowed_domains]
        out: list[EvidenceRecord] = []
        for evidence_id in list(dict.fromkeys(evidence_ids))[:MAX_EVIDENCE_IDS]:
            try:
                record = await self._resolve(scope, domains, evidence_id)
            except Exception:  # unreadable evidence is omitted, never explained
                record = None
            if record is not None:
                out.append(record)
        return tuple(out)

    async def _resolve(
        self, scope: IdentityScope, domains: Sequence[str], evidence_id: str
    ) -> EvidenceRecord | None:
        if evidence_id.startswith(_EVAL_PREFIX):
            return await self._evaluation(scope, domains, evidence_id)
        if _is_recommendation(evidence_id):
            return await self._recommendation(scope, domains, evidence_id)
        return await self._entity(scope, domains, evidence_id)

    async def _recommendation(
        self, scope: IdentityScope, domains: Sequence[str], evidence_id: str
    ) -> EvidenceRecord | None:
        if self._recommendations is None:
            return None
        for domain in domains:
            rec = await self._recommendations.get(scope, domain, evidence_id)
            if rec is not None:
                return EvidenceRecord(
                    evidence_id=evidence_id,
                    kind="recommendation",
                    ref=f"recommendation:{evidence_id}",
                    domain_id=domain,
                    observed_at=_text(getattr(rec, "created_at", None)),
                )
        return None

    async def _evaluation(
        self, scope: IdentityScope, domains: Sequence[str], evidence_id: str
    ) -> EvidenceRecord | None:
        getter = getattr(self._evaluations, "get_result", None)
        if getter is None:
            return None
        for domain in domains:
            result = await getter(scope, domain, evidence_id)
            if result is not None:
                return EvidenceRecord(
                    evidence_id=evidence_id,
                    kind="evaluation_result",
                    ref=f"evaluation_result:{evidence_id}",
                    domain_id=domain,
                    observed_at=_text(getattr(result, "completed_at", None)),
                )
        return None

    async def _entity(
        self, scope: IdentityScope, domains: Sequence[str], evidence_id: str
    ) -> EvidenceRecord | None:
        if self._catalog is None:
            return None
        entity = await self._catalog.get_entity(scope, evidence_id)
        if entity is None:
            return None
        domain = _entity_domain(entity)
        if domain is None or domain not in domains:
            return None
        return EvidenceRecord(
            evidence_id=evidence_id,
            kind="catalog_entity",
            ref=f"catalog_entity:{evidence_id}",
            domain_id=domain,
            observed_at=_text(getattr(entity, "updated_at", None)),
        )
