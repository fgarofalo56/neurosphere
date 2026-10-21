"""Harness for replay tests: PRP-06 authz harness + real router + in-memory trace reader."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import authz.authz_helpers as helpers  # pyright: ignore[reportMissingImports]
from neurosphere_api.replay import (
    PREFIX,
    InMemoryTraceReader,
    PayloadPolicy,
    SpanRecord,
    build_router,
    get_payload_policy,
    get_trace_reader,
)
from neurosphere_core.auth.scope import Role

ALICE: str = helpers.ALICE
BOB: str = helpers.BOB
CUSTOMER: str = helpers.CUSTOMER
FINANCE: str = helpers.FINANCE
OPERATIONS: str = helpers.OPERATIONS
T0 = datetime(2027, 1, 15, 8, 0, 0, tzinfo=UTC)
TRACE = "a" * 32
OTHER_TRACE = "b" * 32


def sid(n: int) -> str:
    return f"{n:016x}"


def span(
    n: int,
    parent: int | None,
    *,
    offset_ms: int = 0,
    duration_ms: int | None = 100,
    domain: str | None = FINANCE,
    customer: str = CUSTOMER,
    trace: str = TRACE,
    kind: str = "agent_run",
    outcome: str = "success",
    rate: float | None = None,
    method: str | None = None,
    reason: str | None = None,
    late: bool = False,
    ingested_after_s: int = 1,
    pointer: str | None = None,
    redaction: str | None = None,
) -> SpanRecord:
    start = T0 + timedelta(milliseconds=offset_ms)
    return SpanRecord(
        customer_id=customer,
        domain_id=domain,
        trace_id=trace,
        span_id=sid(n),
        parent_span_id=None if parent is None else sid(parent),
        span_kind=kind,
        outcome=outcome,
        event_time=start,
        duration_ms=duration_ms,
        ingestion_time=start + timedelta(seconds=ingested_after_s),
        late_flag=late,
        agent="support-bot" if n == 1 else None,
        sampling_rate=rate,
        sampling_method=method,
        sampling_reason=reason,
        payload_pointer=pointer,
        payload_redaction_state=redaction,
    )


@dataclass
class Api:
    h: Any
    reader: InMemoryTraceReader

    def get(self, who: str | None, path: str, **params: Any) -> Any:
        headers = self.h.auth(who) if who else {}
        return self.h.client.get(f"{PREFIX}{path}", params=params or None, headers=headers)

    def trace(self, who: str | None, domain: str, trace_id: str = TRACE, **params: Any) -> Any:
        return self.get(who, f"/domains/{domain}/traces/{trace_id}", **params)


def make_api(*records: SpanRecord, policy: PayloadPolicy | None = None) -> Api:
    h = helpers.harness(
        helpers.policy(ALICE, helpers.role(Role.VIEWER, FINANCE)),
        helpers.policy(BOB, helpers.role(Role.VIEWER, OPERATIONS)),
        routers={PREFIX: build_router()},
    )
    reader = InMemoryTraceReader()
    reader.add(*records)
    h.app.dependency_overrides[get_trace_reader] = lambda: reader
    if policy is not None:
        h.app.dependency_overrides[get_payload_policy] = lambda: policy
    return Api(h=h, reader=reader)
