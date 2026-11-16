"""Audit-chain integrity evidence (PRP-56 item 3).

Verifies the domain's hash chain with ``AuditRepository.verify`` (bounded by the cap) and reports
the record count, whether the chain verified, and the newest record time. The chain is read, never
written; no record body, actor or subject leaves this module.
"""

from __future__ import annotations

from datetime import datetime

from neurosphere_contracts.compliance.v1.evidence_observation import EvidenceObservation

from neurosphere_core.audit import AuditRepository, domain_audit_chain_id
from neurosphere_core.compliance.sources.base import (
    SourceRequest,
    make_observation,
    parse_utc,
    unavailable,
)
from neurosphere_core.errors import InvalidSchemaError

__all__ = ["AuditChainSource"]

_MEASURES = ("records", "chain_intact")


class AuditChainSource:
    source_id = "audit_chain"

    def __init__(self, repository: AuditRepository | None) -> None:
        self._repository = repository

    async def observe(self, request: SourceRequest) -> EvidenceObservation:
        if self._repository is None:
            return unavailable(self.source_id, request, "store_unconfigured", _MEASURES)
        try:
            chain_id = domain_audit_chain_id(request.scope.customer_id, request.domain_id)
        except InvalidSchemaError:
            return unavailable(self.source_id, request, "chain_unencodable", _MEASURES)
        try:
            tail = await self._repository.tail(chain_id)
            if tail is None:
                return make_observation(
                    self.source_id,
                    request,
                    status="observed",
                    measures={"records": 0, "chain_intact": None},
                )
            result = await self._repository.verify(chain_id, max_records=request.cap)
            latest: datetime | None = None
            newest = await self._repository.read_range(chain_id, start=tail.sequence, limit=1)
            if newest:
                latest = parse_utc(newest[0].recorded_at.root)
        except Exception:
            return unavailable(self.source_id, request, "store_error", _MEASURES)
        if result.reason == "verify_limit_exceeded":
            return make_observation(
                self.source_id,
                request,
                status="partial",
                reason_code="capped",
                latest_at=latest,
                truncated=True,
                measures={"records": tail.sequence + 1, "chain_intact": None},
            )
        return make_observation(
            self.source_id,
            request,
            status="observed",
            reason_code=None if result.ok else result.reason,
            latest_at=latest,
            measures={"records": tail.sequence + 1, "chain_intact": 1 if result.ok else 0},
        )
