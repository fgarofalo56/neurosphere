"""apply_capture_policy_change / read_back_capture_policy: approval, diff, ETag, audit."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from typing import Any

import pytest
from azure.cosmos.exceptions import (
    CosmosAccessConditionFailedError,
    CosmosHttpResponseError,
    CosmosResourceExistsError,
    CosmosResourceNotFoundError,
)
from neurosphere_core.audit import AuditRepository, domain_audit_chain_id
from neurosphere_core.audit.content_guard import find_sensitive_content
from neurosphere_core.errors import (
    DependencyTransientError,
    ForbiddenError,
    InvalidSchemaError,
    NotFoundError,
    StaleVersionError,
)
from neurosphere_core.interactions.policy import (
    CaptureMatcher,
    CapturePolicy,
    parse_capture_policy,
)
from neurosphere_core.interactions.policy_store import (
    CapturePolicyChange,
    CapturePolicyStore,
    CosmosCapturePolicyStore,
    InMemoryCapturePolicyStore,
    StoredCapturePolicy,
    apply_capture_policy_change,
    read_back_capture_policy,
)

from .policy_helpers import (
    APPROVAL_AUDIT_ID,
    CUSTOMER,
    DOMAIN,
    INTENT_ID,
    NOW,
    POLICY_ID,
    SOURCE,
    audit_repo,
    make_ctx,
    policy_doc,
    retention,
)

CHAIN = domain_audit_chain_id(CUSTOMER, DOMAIN)
SECOND_AUDIT_ID = "5b2f0c1d-6a7e-4f80-9b3c-2d1e0f9a8b7c"


def _change(stage: str, *, base: int | None = None, **extra: Any) -> CapturePolicyChange:
    return CapturePolicyChange.model_validate(
        {
            "stage": stage,
            "capture_policy_id": POLICY_ID,
            "customer_id": CUSTOMER,
            "base_version": base,
            "approved_intent_id": INTENT_ID,
            **extra,
        }
    )


async def _apply(
    store: CapturePolicyStore,
    change: CapturePolicyChange,
    audit: AuditRepository,
    approved: str | None = APPROVAL_AUDIT_ID,
) -> CapturePolicy:
    return await apply_capture_policy_change(
        store, change, approved, audit=audit, ctx=make_ctx(), clock=lambda: NOW
    )


async def _records(audit: AuditRepository) -> list[Any]:
    return await audit.read_range(CHAIN, start=0, limit=100)


async def test_propose_then_activate_and_read_back() -> None:
    store = InMemoryCapturePolicyStore()
    audit = audit_repo()
    proposed = await _apply(store, _change("propose", policy=policy_doc()), audit)
    assert proposed.version == 1
    assert proposed.state == "proposed"
    assert proposed.approved_audit_id is None

    active = await _apply(store, _change("activate", base=1), audit)
    assert active.version == 2
    assert active.previous_version == 1
    assert active.state == "active"
    assert active.approved_audit_id is not None
    assert active.approved_audit_id.root == APPROVAL_AUDIT_ID
    assert active.approved_intent_id is not None
    assert active.approved_intent_id.root == INTENT_ID
    assert active.effective_from is not None
    assert active.effective_from.root == "2026-11-25T12:00:00Z"

    read = await read_back_capture_policy(store, POLICY_ID)
    assert read == active
    assert await read_back_capture_policy(store, POLICY_ID, customer_id=CUSTOMER) == active

    matcher = await CaptureMatcher.from_store(store, setting_enabled=True, retention=retention())
    assert matcher.match(SOURCE, DOMAIN, "e") is not None

    records = await _records(audit)
    assert [(r.kind, r.operation) for r in records] == [
        ("before", "capture_policy.apply"),
        ("after", "capture_policy.apply"),
        ("before", "capture_policy.apply"),
        ("after", "capture_policy.apply"),
    ]
    last = records[-1]
    assert last.outcome is not None
    assert last.outcome.result == "succeeded"
    assert last.outcome.verified is True
    assert last.outcome.detail == "activate"
    assert last.subject is not None
    assert last.subject.target.entity_type == "capture_policy"
    assert last.subject.target.canonical_id == (
        "commercial:contoso:neurosphere:capture_policy:support-capture"
    )
    assert last.subject.target_version == "2"
    assert last.intent_id is not None
    assert last.intent_id.root == INTENT_ID
    for record in records:
        assert find_sensitive_content(record.model_dump(mode="json")) == []


async def test_suspend_and_retire_keep_approval_trail() -> None:
    store = InMemoryCapturePolicyStore()
    audit = audit_repo()
    await _apply(store, _change("propose", policy=policy_doc()), audit)
    await _apply(store, _change("activate", base=1), audit)
    suspended = await _apply(store, _change("suspend", base=2), audit, SECOND_AUDIT_ID)
    assert suspended.state == "suspended"
    assert suspended.approved_audit_id is not None
    assert suspended.approved_audit_id.root == APPROVAL_AUDIT_ID
    retired = await _apply(store, _change("retire", base=3), audit)
    assert retired.state == "retired"
    with pytest.raises(InvalidSchemaError) as info:
        await _apply(store, _change("activate", base=4), audit)
    assert info.value.reason == "capture_policy_retired"


@pytest.mark.parametrize("approved", [None, "", "not-a-uuid"])
async def test_refused_without_approving_audit_id(approved: str | None) -> None:
    store = InMemoryCapturePolicyStore()
    audit = audit_repo()
    with pytest.raises(ForbiddenError) as info:
        await _apply(store, _change("propose", policy=policy_doc()), audit, approved)
    assert info.value.reason == "approval_required"
    assert await store.list() == []
    records = await _records(audit)
    assert [(r.kind, r.denial.reason if r.denial else None) for r in records] == [
        ("denied", "approval_required")
    ]


async def test_stale_base_version_refused() -> None:
    store = InMemoryCapturePolicyStore()
    audit = audit_repo()
    await _apply(store, _change("propose", policy=policy_doc()), audit)
    with pytest.raises(StaleVersionError):
        await _apply(store, _change("activate", base=7), audit)
    with pytest.raises(StaleVersionError):
        await _apply(store, _change("propose", policy=policy_doc()), audit)  # base None
    stored = await read_back_capture_policy(store, POLICY_ID)
    assert stored.version == 1


@pytest.mark.parametrize(
    "domain",
    [
        "commercial:fabrikam:neurosphere:domain:support",  # another customer's chain
        "government:contoso:neurosphere:domain:support",  # another cloud
        "not-a-domain",
    ],
)
@pytest.mark.parametrize("approved", [APPROVAL_AUDIT_ID, None])
async def test_new_policy_domain_checked_before_any_audit_write(
    domain: str, approved: str | None
) -> None:
    store = InMemoryCapturePolicyStore()
    audit = audit_repo()
    with pytest.raises(InvalidSchemaError) as info:
        await _apply(
            store, _change("propose", policy=policy_doc(domain_id=domain)), audit, approved
        )
    assert info.value.reason == "capture_policy_invalid"
    assert await audit.tail(CHAIN) is None
    foreign = domain_audit_chain_id("fabrikam", "commercial:fabrikam:neurosphere:domain:support")
    assert await audit.tail(foreign) is None  # no denied record on another customer's chain
    assert await store.list() == []


@pytest.mark.parametrize(
    ("stage", "base", "extra", "reason"),
    [
        ("suspend", 1, {}, "capture_policy_transition_refused"),
        ("activate", 1, {"policy": policy_doc()}, "capture_policy_body_not_allowed"),
        ("propose", 1, {}, "capture_policy_body_required"),
        (
            "propose",
            1,
            {"policy": policy_doc(domain_id="commercial:contoso:neurosphere:domain:sales")},
            "capture_policy_identity_changed",
        ),
        (
            "propose",
            1,
            {"policy": policy_doc(capture_policy_id="other")},
            "capture_policy_id_mismatch",
        ),
        ("propose", 1, {"policy": policy_doc()}, "capture_policy_no_change"),
        (
            "propose",
            1,
            {"policy": policy_doc(kept_categories=["private_key"])},
            "capture_policy_invalid",
        ),
    ],
)
async def test_invalid_diffs_refused(
    stage: str, base: int, extra: dict[str, Any], reason: str
) -> None:
    store = InMemoryCapturePolicyStore()
    audit = audit_repo()
    await _apply(store, _change("propose", policy=policy_doc()), audit)
    before = await _records(audit)
    with pytest.raises(InvalidSchemaError) as info:
        await _apply(store, _change(stage, base=base, **extra), audit)
    assert info.value.reason == reason
    assert (await read_back_capture_policy(store, POLICY_ID)).version == 1
    assert len(await _records(audit)) == len(before)  # refused before any audit write


async def test_reproposal_with_a_real_change_bumps_version() -> None:
    store = InMemoryCapturePolicyStore()
    audit = audit_repo()
    await _apply(store, _change("propose", policy=policy_doc()), audit)
    body = policy_doc(sampling={"rate": 0.5, "max_per_minute": 60}, version=99, state="active")
    updated = await _apply(store, _change("propose", base=1, policy=body), audit)
    assert updated.version == 2
    assert updated.state == "proposed"  # server-set fields in the body are ignored
    assert updated.sampling.rate == 0.5


async def test_non_propose_on_missing_policy_is_not_found() -> None:
    with pytest.raises(NotFoundError):
        await _apply(InMemoryCapturePolicyStore(), _change("activate", base=1), audit_repo())
    with pytest.raises(NotFoundError):
        await read_back_capture_policy(InMemoryCapturePolicyStore(), POLICY_ID)


class _RacingStore(InMemoryCapturePolicyStore):
    """Another writer changes the policy between the read and the write."""

    async def replace(self, policy: CapturePolicy, *, if_match: str) -> StoredCapturePolicy:
        current = await self.get(policy.policy_id, customer_id=policy.customer)
        assert current is not None
        await super().replace(current.policy, if_match=current.etag)
        return await super().replace(policy, if_match=if_match)


async def test_lost_etag_race_audits_failure() -> None:
    store = _RacingStore()
    audit = audit_repo()
    await _apply(store, _change("propose", policy=policy_doc()), audit)
    with pytest.raises(StaleVersionError) as info:
        await _apply(store, _change("activate", base=1), audit)
    assert info.value.reason == "capture_policy_modified"
    last = (await _records(audit))[-1]
    assert last.outcome is not None
    assert last.outcome.result == "failed"
    assert last.outcome.detail == "capture_policy_modified"
    assert (await read_back_capture_policy(store, POLICY_ID)).state == "proposed"


class _LyingStore(InMemoryCapturePolicyStore):
    async def get(
        self, policy_id: str, *, customer_id: str | None = None
    ) -> StoredCapturePolicy | None:
        stored = await super().get(policy_id, customer_id=customer_id)
        if stored is None or stored.policy.version == 1:
            return stored
        stale = parse_capture_policy(policy_doc())
        return StoredCapturePolicy(policy=stale, etag=stored.etag)


async def test_read_back_mismatch_fails_verify() -> None:
    store = _LyingStore()
    audit = audit_repo()
    await _apply(store, _change("propose", policy=policy_doc()), audit)
    with pytest.raises(DependencyTransientError) as info:
        await _apply(store, _change("activate", base=1), audit)
    assert info.value.reason == "capture_policy_read_back_mismatch"
    last = (await _records(audit))[-1]
    assert last.outcome is not None
    assert last.outcome.verified is False


# --- Cosmos store against a fake container (ETag mapping) ---------------------------------------


class _FakeContainer:
    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], dict[str, Any]] = {}
        self.queries: list[str] = []
        self._n = 0

    def _stamp(self, body: Mapping[str, Any]) -> dict[str, Any]:
        self._n += 1
        row = dict(body)
        row["_etag"] = f'"e{self._n}"'
        row["_ts"] = self._n
        self.rows[(row["customer_id"], row["id"])] = row
        return dict(row)

    async def read_item(self, *, item: str, partition_key: str) -> dict[str, Any]:
        row = self.rows.get((partition_key, item))
        if row is None:
            raise CosmosResourceNotFoundError(status_code=404, message="nf")
        return dict(row)

    async def create_item(self, *, body: Mapping[str, Any]) -> dict[str, Any]:
        if (body["customer_id"], body["id"]) in self.rows:
            raise CosmosResourceExistsError(status_code=409, message="exists")
        return self._stamp(body)

    async def replace_item(
        self, *, item: str, body: Mapping[str, Any], etag: str, match_condition: object
    ) -> dict[str, Any]:
        del match_condition
        row = self.rows.get((body["customer_id"], item))
        if row is None:
            raise CosmosResourceNotFoundError(status_code=404, message="nf")
        if row["_etag"] != etag:
            raise CosmosAccessConditionFailedError(status_code=412, message="pre")
        return self._stamp(body)

    def query_items(
        self, sql: str, *, parameters: list[dict[str, Any]]
    ) -> AsyncIterator[dict[str, Any]]:
        values = {p["name"]: p["value"] for p in parameters}
        self.queries.append(sql)
        if _order_by_terms(sql) > 1:
            # Real Cosmos answers 400 without a composite index; the container declares none.
            raise CosmosHttpResponseError(status_code=400, message="composite index required")

        async def rows() -> AsyncIterator[dict[str, Any]]:
            for key in sorted(self.rows):
                row = self.rows[key]
                if "@id" in values and row["id"] != values["@id"]:
                    continue
                if "@customer_id" in values and row["customer_id"] != values["@customer_id"]:
                    continue
                yield dict(row)

        return rows()


def _order_by_terms(sql: str) -> int:
    upper = sql.upper()
    if "ORDER BY" not in upper:
        return 0
    return len(upper.split("ORDER BY", 1)[1].split(","))


async def test_cosmos_queries_use_at_most_one_order_by_term() -> None:
    container = _FakeContainer()
    store = CosmosCapturePolicyStore(container)  # type: ignore[arg-type]
    await store.create(parse_capture_policy(policy_doc()))
    await store.create(
        parse_capture_policy(
            policy_doc(
                customer_id="acme",
                domain_id="commercial:acme:neurosphere:domain:support",
            )
        )
    )
    everyone = await store.list()
    assert [(s.policy.customer, s.policy.policy_id) for s in everyone] == [
        ("acme", POLICY_ID),
        (CUSTOMER, POLICY_ID),
    ]
    assert len(await store.list(customer_id=CUSTOMER)) == 1
    matcher = await CaptureMatcher.from_store(store, setting_enabled=True, retention=retention())
    assert matcher.status() == "not_approved"
    assert container.queries  # the list queries really went through the fake
    for sql in container.queries:
        assert _order_by_terms(sql) <= 1, sql


async def test_cosmos_store_apply_and_read_back() -> None:
    container = _FakeContainer()
    store = CosmosCapturePolicyStore(container)  # type: ignore[arg-type]
    audit = audit_repo()
    await _apply(store, _change("propose", policy=policy_doc()), audit)
    active = await _apply(store, _change("activate", base=1), audit)
    row = container.rows[(CUSTOMER, POLICY_ID)]
    assert row["doc_type"] == "capture_policy"
    assert row["version"] == 2
    assert await read_back_capture_policy(store, POLICY_ID) == active
    listed = await store.list(customer_id=CUSTOMER)
    assert [s.policy.policy_id for s in listed] == [POLICY_ID]
    stale = listed[0]
    await store.replace(stale.policy, if_match=stale.etag)
    with pytest.raises(StaleVersionError):
        await store.replace(stale.policy, if_match=stale.etag)
    with pytest.raises(StaleVersionError):
        await store.create(stale.policy)
    assert await store.get("missing", customer_id=CUSTOMER) is None


async def test_cosmos_invalid_row_is_upstream_invalid() -> None:
    container = _FakeContainer()
    container.rows[(CUSTOMER, POLICY_ID)] = {
        **policy_doc(state="active"),  # active without approval: invalid
        "id": POLICY_ID,
        "doc_type": "capture_policy",
        "_etag": '"x"',
    }
    store = CosmosCapturePolicyStore(container)  # type: ignore[arg-type]
    with pytest.raises(DependencyTransientError) as info:
        await store.get(POLICY_ID, customer_id=CUSTOMER)
    assert info.value.reason == "capture_policy_record_invalid"
