"""PRP-104 item 5: the replay payload branch obeys the content-read rule (criterion 7).

The real replay router runs over the PRP-06 authz harness with an in-memory trace reader whose
spans point at synthetic interactions (``interaction:<id>``, the PRP-103 pointer scheme) held in
the spying :class:`InMemoryInteractionStore` of ``test_content_read``. The shared ``events`` list
records the audit append and every decrypt, so the tests prove ONE ``interaction.read`` record per
trace read, listing the interaction ids, is durable BEFORE any content is decrypted. Synthetic data
only: every canary is generated at runtime.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import authz.authz_helpers as helpers  # pyright: ignore[reportMissingImports]
import pytest
from neurosphere_api.interactions import InteractionExplorer, configure_interaction_explorer
from neurosphere_api.replay import (
    PREFIX,
    InMemoryTraceReader,
    SpanRecord,
    build_router,
    get_payload_policy,
    get_trace_reader,
)
from neurosphere_api.replay.reader import ArchiveTraceReader, TraceRecords
from neurosphere_contracts.audit.v1.audit_record import AuditRecord
from neurosphere_contracts.interactions.v1.interaction_record import InteractionRecord
from neurosphere_core.audit import ALLOW_DETAIL, domain_audit_chain_id, sha256_digest
from neurosphere_core.auth.scope import Role
from neurosphere_core.interactions import interaction_pointer
from test_content_read import (  # pyright: ignore[reportMissingImports]
    ADMIN,
    CUSTOMER,
    EXPIRING,
    EXPIRY_SECONDS,
    FINANCE,
    INVESTIGATOR,
    OPERATIONS,
    PURPOSE,
    VIEWER,
    SpyAudit,
    SpyStore,
    canary,
    investigator_role,
    new_id,
    record_doc,
    redacted,
)

FIN_CHAIN = domain_audit_chain_id(CUSTOMER, FINANCE)
TRACE = "c" * 32
T0 = datetime(2026, 11, 20, 9, 0, tzinfo=UTC)
PURPOSE_PARAMS = {"purpose_code": PURPOSE["purpose_code"], "case_ref": PURPOSE["case_ref"]}


def sid(n: int) -> str:
    return f"{n:016x}"


def span(
    n: int,
    *,
    pointer: str | None,
    state: str | None = "redacted",
    domain: str | None = FINANCE,
) -> SpanRecord:
    start = T0 + timedelta(milliseconds=n)
    return SpanRecord(
        customer_id=CUSTOMER,
        domain_id=domain,
        trace_id=TRACE,
        span_id=sid(n),
        parent_span_id=None if n == 1 else sid(1),
        span_kind="agent_run",
        outcome="success",
        event_time=start,
        duration_ms=10,
        ingestion_time=start + timedelta(seconds=1),
        agent="support-bot" if n == 1 else None,
        payload_pointer=pointer,
        payload_redaction_state=state if pointer is not None else None,
    )


class CountingReader(InMemoryTraceReader):
    """The in-memory trace reader, counting trace reads and legacy payload reads."""

    def __init__(self) -> None:
        super().__init__()
        self.trace_reads = 0
        self.payload_reads = 0

    async def get_trace(self, customer_id: str, domain_id: str, trace_id: str) -> TraceRecords:
        self.trace_reads += 1
        return await super().get_trace(customer_id, domain_id, trace_id)

    async def read_payload(
        self, customer_id: str, domain_id: str, pointer: str
    ) -> dict[str, Any] | None:
        self.payload_reads += 1
        return await super().read_payload(customer_id, domain_id, pointer)


class ReplayApi:
    def __init__(self, tmp_path: Path, *, explorer: bool = True, audit_fails: bool = False) -> None:
        self.events: list[str] = []
        self.store = SpyStore(tmp_path, self.events)
        self.audit = SpyAudit(self.events, fail=audit_fails)
        self.denials = helpers.RecordingDenials()
        viewer_fin = helpers.role(Role.VIEWER, FINANCE)
        self.h = helpers.harness(
            helpers.policy(INVESTIGATOR, investigator_role(FINANCE), viewer_fin),
            helpers.policy(ADMIN, helpers.role(Role.ADMIN, FINANCE)),
            helpers.policy(VIEWER, viewer_fin),
            helpers.policy(
                EXPIRING, investigator_role(FINANCE, expires_in=EXPIRY_SECONDS), viewer_fin
            ),
            routers={PREFIX: build_router()},
            denials=self.denials,
        )
        self.h.app.state.audit_repository = self.audit
        self.reader = CountingReader()
        self.h.app.dependency_overrides[get_trace_reader] = lambda: self.reader
        if explorer:
            configure_interaction_explorer(
                self.h.app,
                InteractionExplorer(
                    store=self.store, audit=self.audit, cloud="commercial", customer_id=CUSTOMER
                ),
            )

    def seed(self, *interaction_ids: str, domain: str = FINANCE) -> list[str]:
        marks: list[str] = []

        async def put_all() -> None:
            for iid in interaction_ids:
                mark = canary()
                marks.append(mark)
                record = InteractionRecord.model_validate(record_doc(iid, domain_id=domain))
                await self.store.put(record, redacted(iid, mark), capture_retention_days=30)

        asyncio.run(put_all())
        return marks

    def trace(self, who: str, **params: Any) -> Any:
        return self.h.client.get(
            f"{PREFIX}/domains/{FINANCE}/traces/{TRACE}",
            params=params or None,
            headers=self.h.auth(who),
        )

    def records(self) -> list[AuditRecord]:
        return list(asyncio.run(self.audit.read_range(FIN_CHAIN, start=0, limit=100)))


def payloads(response: Any) -> dict[str, Any]:
    return {s["span_id"]: s["payload"] for s in response.json()["spans"]}


def batch_digest(ids: list[str]) -> str:
    return sha256_digest(
        {
            "domain_id": FINANCE,
            "interaction_ids": ids,
            "purpose_code": PURPOSE["purpose_code"],
            "case_ref": PURPOSE["case_ref"],
        }
    )


@pytest.fixture
def api(tmp_path: Path) -> ReplayApi:
    return ReplayApi(tmp_path)


def two_interaction_trace(api: ReplayApi) -> tuple[list[str], list[str]]:
    ids = [new_id(), new_id()]
    marks = api.seed(*ids)
    pending_id = new_id()
    api.seed(pending_id)
    other_domain_id = new_id()
    api.seed(other_domain_id, domain=OPERATIONS)
    api.reader.add(
        span(1, pointer=interaction_pointer(ids[0])),
        span(2, pointer=interaction_pointer(ids[1])),
        span(3, pointer=interaction_pointer(pending_id), state="pending"),
        span(4, pointer="p/legacy-blob"),
        span(5, pointer=None),
        span(6, pointer=interaction_pointer(other_domain_id), domain=OPERATIONS),
    )
    api.reader.payloads[(CUSTOMER, "p/legacy-blob")] = {"note": canary()}
    return ids, marks


# --- the policy switch (clarification 9) ----------------------------------------------------------


def test_policy_allows_bodies_only_while_the_explorer_is_installed(tmp_path: Path) -> None:
    on = ReplayApi(tmp_path / "on")
    off = ReplayApi(tmp_path / "off", explorer=False)
    assert get_payload_policy(SimpleNamespace(app=on.h.app)).allow_bodies is True  # type: ignore[arg-type]
    assert get_payload_policy(SimpleNamespace(app=off.h.app)).allow_bodies is False  # type: ignore[arg-type]


# --- payload-free paths: exactly as before --------------------------------------------------------


def test_explorer_off_is_payload_free_even_for_an_investigator(tmp_path: Path) -> None:
    api = ReplayApi(tmp_path, explorer=False)
    two_interaction_trace(api)
    response = api.trace(INVESTIGATOR, include_payload="true", **PURPOSE_PARAMS)
    assert response.status_code == 200, response.text
    assert all(p is None for p in payloads(response).values())
    assert api.events == []
    assert api.reader.payload_reads == 0


def test_without_include_payload_the_investigator_gets_no_body(api: ReplayApi) -> None:
    two_interaction_trace(api)
    response = api.trace(INVESTIGATOR, **PURPOSE_PARAMS)
    assert response.status_code == 200, response.text
    assert all(p is None for p in payloads(response).values())
    assert api.events == []
    assert api.records() == []


@pytest.mark.parametrize("who", [VIEWER, ADMIN])
def test_viewer_and_admin_get_payload_free_detail_without_error(api: ReplayApi, who: str) -> None:
    _, marks = two_interaction_trace(api)
    for params in ({}, PURPOSE_PARAMS, {"purpose_code": "curiosity"}):
        response = api.trace(who, include_payload="true", **params)
        assert response.status_code == 200, response.text
        body = payloads(response)
        assert all(p is None for p in body.values())
        assert response.json()["spans"][0]["payload_state"] == "redacted"
        assert not any(mark in response.text for mark in marks)
    assert api.store.content_reads == 0
    assert api.reader.payload_reads == 0
    assert api.events == []
    assert api.records() == []
    assert api.denials.attempts == []


def test_expired_investigator_gets_payload_free_detail(api: ReplayApi) -> None:
    two_interaction_trace(api)
    api.h.clock.advance(EXPIRY_SECONDS + 1)
    response = api.trace(EXPIRING, include_payload="true", **PURPOSE_PARAMS)
    assert response.status_code == 200, response.text
    assert all(p is None for p in payloads(response).values())
    assert api.store.content_reads == 0


# --- 422: purpose before any read -----------------------------------------------------------------


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"case_ref": "INC-1"},
        {"purpose_code": "curiosity"},
        {"purpose_code": PURPOSE["purpose_code"], "case_ref": "someone@example.com"},
    ],
)
def test_investigator_without_a_valid_purpose_is_422_before_any_read(
    api: ReplayApi, params: dict[str, str]
) -> None:
    two_interaction_trace(api)
    response = api.trace(INVESTIGATOR, include_payload="true", **params)
    assert response.status_code == 422, response.text
    assert response.json()["reason"] == "interaction_purpose_invalid"
    assert api.reader.trace_reads == 0
    assert api.store.content_reads == 0
    assert api.audit.attempts == 0


# --- the audited batch read -----------------------------------------------------------------------


def test_one_record_lists_the_ids_before_any_decrypt_and_bodies_attach(api: ReplayApi) -> None:
    ids, marks = two_interaction_trace(api)
    response = api.trace(INVESTIGATOR, include_payload="true", **PURPOSE_PARAMS)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"

    # One record for the trace read, appended before either decrypt.
    assert api.events == ["audit:interaction.read", f"decrypt:{ids[0]}", f"decrypt:{ids[1]}"]
    (record,) = api.records()
    assert record.operation == "interaction.read"
    assert record.outcome is not None and record.outcome.detail == ALLOW_DETAIL
    assert record.subject is not None and record.subject.state_digest is not None
    assert record.subject.state_digest.root == batch_digest(ids)
    dumped = record.model_dump_json()
    assert not any(mark in dumped for mark in marks)
    assert str(PURPOSE["case_ref"]) not in dumped

    body = payloads(response)
    for n, (iid, mark) in enumerate(zip(ids, marks, strict=True), start=1):
        stored = redacted(iid, mark).model_dump(mode="json")
        assert body[sid(n)] == stored
    assert body[sid(3)] is None  # pending: never read
    assert body[sid(4)] is None  # not an interaction pointer: no body, no legacy read
    assert body[sid(5)] is None
    assert sid(6) not in body  # another domain's span is withheld
    assert api.reader.payload_reads == 0
    assert api.store.content_reads == 2


def test_one_interaction_shared_by_spans_is_read_once(api: ReplayApi) -> None:
    iid = new_id()
    (mark,) = api.seed(iid)
    api.reader.add(
        span(1, pointer=interaction_pointer(iid)), span(2, pointer=interaction_pointer(iid))
    )
    response = api.trace(INVESTIGATOR, include_payload="true", **PURPOSE_PARAMS)
    assert response.status_code == 200, response.text
    assert api.events == ["audit:interaction.read", f"decrypt:{iid}"]
    body = payloads(response)
    assert body[sid(1)] == body[sid(2)] == redacted(iid, mark).model_dump(mode="json")


def test_absent_purged_and_malformed_pointers_get_no_body(api: ReplayApi) -> None:
    live, purged, absent = new_id(), new_id(), new_id()
    api.seed(live, purged)
    api.store.purged.add(purged)
    api.reader.add(
        span(1, pointer=interaction_pointer(live)),
        span(2, pointer=interaction_pointer(purged)),
        span(3, pointer=interaction_pointer(absent)),
        span(4, pointer="interaction:NOT-A-UUID"),
    )
    response = api.trace(INVESTIGATOR, include_payload="true", **PURPOSE_PARAMS)
    assert response.status_code == 200, response.text
    body = payloads(response)
    assert body[sid(1)] is not None
    assert body[sid(2)] is None and body[sid(3)] is None and body[sid(4)] is None
    assert api.events == ["audit:interaction.read", f"decrypt:{live}"]


def test_trace_without_interaction_pointers_writes_no_record(api: ReplayApi) -> None:
    api.reader.add(span(1, pointer="p/legacy-blob"), span(2, pointer=None))
    response = api.trace(INVESTIGATOR, include_payload="true", **PURPOSE_PARAMS)
    assert response.status_code == 200, response.text
    assert all(p is None for p in payloads(response).values())
    assert api.audit.attempts == 0
    assert api.reader.payload_reads == 0


def test_audit_failure_is_503_and_nothing_is_decrypted(tmp_path: Path) -> None:
    api = ReplayApi(tmp_path, audit_fails=True)
    _, marks = two_interaction_trace(api)
    response = api.trace(INVESTIGATOR, include_payload="true", **PURPOSE_PARAMS)
    assert response.status_code == 503, response.text
    assert response.json()["reason"] == "audit_write_failed"
    assert api.audit.attempts == 1
    assert api.store.content_reads == 0
    assert api.events == []
    assert not any(mark in response.text for mark in marks)


def test_more_than_100_interactions_in_one_trace_is_422_before_any_audit(api: ReplayApi) -> None:
    api.reader.add(*(span(n, pointer=interaction_pointer(new_id())) for n in range(1, 102)))
    response = api.trace(INVESTIGATOR, include_payload="true", **PURPOSE_PARAMS)
    assert response.status_code == 422, response.text
    assert response.json()["reason"] == "interaction_batch_too_large"
    assert api.audit.attempts == 0
    assert api.store.content_reads == 0


def test_exactly_100_interactions_is_one_read(api: ReplayApi) -> None:
    ids = [new_id() for _ in range(100)]
    api.seed(*ids)
    api.reader.add(*(span(n, pointer=interaction_pointer(i)) for n, i in enumerate(ids, start=1)))
    response = api.trace(INVESTIGATOR, include_payload="true", **PURPOSE_PARAMS)
    assert response.status_code == 200, response.text
    assert api.audit.attempts == 1
    assert api.store.content_reads == 100
    (record,) = api.records()
    assert record.subject is not None and record.subject.state_digest is not None
    assert record.subject.state_digest.root == batch_digest(ids)


# --- the archive reader never decrypts ------------------------------------------------------------


@pytest.mark.parametrize("pointer", [interaction_pointer(new_id()), "p/1", ""])
def test_archive_reader_read_payload_is_always_none(pointer: str) -> None:
    reader = ArchiveTraceReader(container=SimpleNamespace())  # type: ignore[arg-type]
    assert asyncio.run(reader.read_payload(CUSTOMER, FINANCE, pointer)) is None
