"""Policy engine stores: ONE contract run against the in-memory stores and the Cosmos stores over
an in-process fake container (PRP-105 item 1).

Covers ETag create and replace, ``stale_version`` on a stale If-Match, published-version
immutability (``policy_published``), violation dedup/bump/resolve, exception transitions and
``active_for``, run-status documents, enforcement bindings over both ``admin_config``
repositories, outages, and the Cosmos one-ORDER-BY-term rule.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import pytest
from neurosphere_core.admin import CosmosAdminConfigRepository, InMemoryAdminConfigRepository
from neurosphere_core.errors import (
    DependencyTransientError,
    InvalidSchemaError,
    NotFoundError,
    RateLimitedError,
    StaleVersionError,
)
from neurosphere_core.governance.policy import (
    BindingStore,
    CosmosEvaluationStatusStore,
    CosmosExceptionStore,
    CosmosPolicyDefinitionStore,
    CosmosViolationStore,
    EvaluationStatus,
    EvaluationStatusStore,
    ExceptionFilters,
    ExceptionStore,
    GovernancePolicyNotFoundError,
    GovernancePolicyStaleError,
    InMemoryDocumentBackend,
    InMemoryEvaluationStatusStore,
    InMemoryExceptionStore,
    InMemoryPolicyDefinitionStore,
    InMemoryViolationStore,
    PolicyDefinitionStore,
    PolicyPublishedError,
    PolicyValidationError,
    RuleRunStatus,
    ViolationFilters,
    ViolationStore,
    dedup_key,
    validate_draft,
)
from neurosphere_core.governance.policy.cosmos_store import build_query
from neurosphere_core.governance.policy.models import PolicyViolation
from neurosphere_core.governance.policy.store import (
    PARTITION_KEY_PATHS,
    DocumentQuery,
)
from neurosphere_core.paging import PageRequest

from .builders import (
    ASSET,
    AUTHOR,
    CUSTOMER,
    DOMAIN,
    OTHER_DOMAIN,
    OTHER_SUBJECT,
    REVIEWER,
    SUBJECT,
    T0,
    draft,
    exception,
    new_uuid,
    observation,
    target,
)
from .fake_container import FakeContainer, throttled

INTENT = "00000001-0000-4000-8000-000000000001"
AUDIT = "00000002-0000-4000-8000-000000000002"


@dataclass
class Rig:
    kind: str
    policies: PolicyDefinitionStore
    statuses: EvaluationStatusStore
    violations: ViolationStore
    exceptions: ExceptionStore
    raw: dict[str, Any]  # container name -> FakeContainer or InMemoryDocumentBackend

    def docs(self, container: str) -> list[dict[str, Any]]:
        store = self.raw[container]
        return list(store.docs.values() if self.kind == "cosmos-fake" else store._docs.values())

    def fail(self, container: str, error: Exception) -> None:
        store = self.raw[container]
        if self.kind == "cosmos-fake":
            store.fail = error
        else:
            store.fail_with(error)


@pytest.fixture(params=["memory", "cosmos-fake"])
def rig(request: pytest.FixtureRequest) -> Rig:
    if request.param == "memory":
        definitions = InMemoryDocumentBackend()
        violations = InMemoryDocumentBackend()
        exceptions = InMemoryDocumentBackend()
        return Rig(
            kind="memory",
            policies=InMemoryPolicyDefinitionStore(definitions),
            statuses=InMemoryEvaluationStatusStore(definitions),
            violations=InMemoryViolationStore(violations),
            exceptions=InMemoryExceptionStore(exceptions),
            raw={"definitions": definitions, "violations": violations, "exceptions": exceptions},
        )
    definitions_c = FakeContainer(PARTITION_KEY_PATHS)
    violations_c = FakeContainer(PARTITION_KEY_PATHS)
    exceptions_c = FakeContainer(PARTITION_KEY_PATHS)
    return Rig(
        kind="cosmos-fake",
        policies=CosmosPolicyDefinitionStore(definitions_c),  # type: ignore[arg-type]
        statuses=CosmosEvaluationStatusStore(definitions_c),  # type: ignore[arg-type]
        violations=CosmosViolationStore(violations_c),  # type: ignore[arg-type]
        exceptions=CosmosExceptionStore(exceptions_c),  # type: ignore[arg-type]
        raw={"definitions": definitions_c, "violations": violations_c, "exceptions": exceptions_c},
    )


@pytest.fixture(params=["memory", "cosmos-fake"])
def bindings(request: pytest.FixtureRequest) -> BindingStore:
    if request.param == "memory":
        return BindingStore(InMemoryAdminConfigRepository(cloud="commercial"))
    container = FakeContainer(("/customer_id",))
    return BindingStore(CosmosAdminConfigRepository(container, cloud="commercial"))  # type: ignore[arg-type]


async def _published(rig: Rig, policy_id: str = "support-governance", **kw: Any) -> Any:
    created = await rig.policies.create_draft(draft(policy_id, **kw))
    return await rig.policies.mark_published(
        CUSTOMER,
        policy_id,
        created.policy.policy_version,
        if_match=created.etag,
        published_at=T0,
        intent_id=INTENT,
        audit_id=AUDIT,
    )


# --- policy definitions -------------------------------------------------------------------------


async def test_create_draft_stores_version_one_with_an_etag(rig: Rig) -> None:
    stored = await rig.policies.create_draft(draft())
    assert stored.etag
    assert stored.policy.policy_version == 1
    assert stored.policy.status == "draft"
    fetched = await rig.policies.get(CUSTOMER, "support-governance")
    assert fetched is not None
    assert fetched.policy == stored.policy
    assert fetched.etag == stored.etag
    by_version = await rig.policies.get(CUSTOMER, "support-governance", version=1)
    assert by_version is not None
    assert by_version.etag == stored.etag


async def test_an_invalid_draft_stores_nothing(rig: Rig) -> None:
    document = draft()
    document["rules"][0]["kind"] = "free_text"
    with pytest.raises(PolicyValidationError) as info:
        await rig.policies.create_draft(document)
    assert info.value.code == "invalid_schema"
    missing = await rig.policies.get(CUSTOMER, "support-governance")
    assert missing is None
    assert rig.docs("definitions") == []


async def test_versions_start_at_one_and_follow_the_latest(rig: Rig) -> None:
    with pytest.raises(GovernancePolicyStaleError) as info:
        await rig.policies.create_draft(draft(version=2, previous=1))
    assert info.value.reason == "policy_modified"
    await rig.policies.create_draft(draft())
    with pytest.raises(GovernancePolicyStaleError) as info:
        await rig.policies.create_draft(draft(version=2, previous=1))
    assert info.value.reason == "policy_draft_exists"


async def test_replace_draft_needs_the_current_etag(rig: Rig) -> None:
    stored = await rig.policies.create_draft(draft())
    changed = draft()
    changed["display_name"] = "Support governance v1b"
    replaced = await rig.policies.replace_draft(changed, if_match=stored.etag)
    assert replaced.etag != stored.etag
    assert replaced.policy.display_name.root == "Support governance v1b"
    with pytest.raises(StaleVersionError) as info:
        await rig.policies.replace_draft(changed, if_match=stored.etag)
    assert info.value.code == "stale_version"
    assert info.value.reason == "policy_modified"


async def test_replace_draft_of_a_missing_version_is_not_found(rig: Rig) -> None:
    with pytest.raises(NotFoundError) as info:
        await rig.policies.replace_draft(draft(), if_match='"1"')
    assert isinstance(info.value, GovernancePolicyNotFoundError)
    assert info.value.reason == "policy_not_found"


async def test_a_published_version_is_immutable(rig: Rig) -> None:
    published = await _published(rig)
    assert published.policy.status == "published"
    assert published.policy.published_intent_id is not None
    assert published.policy.published_intent_id.root == INTENT
    with pytest.raises(PolicyPublishedError) as info:
        await rig.policies.replace_draft(draft(), if_match=published.etag)
    assert info.value.code == "stale_version"
    assert info.value.reason == "policy_published"
    with pytest.raises(PolicyPublishedError):
        await rig.policies.mark_published(
            CUSTOMER,
            "support-governance",
            1,
            if_match=published.etag,
            published_at=T0,
            intent_id=INTENT,
            audit_id=AUDIT,
        )


async def test_publish_with_a_stale_etag_is_refused(rig: Rig) -> None:
    created = await rig.policies.create_draft(draft())
    await rig.policies.replace_draft(draft(), if_match=created.etag)
    with pytest.raises(GovernancePolicyStaleError) as info:
        await rig.policies.mark_published(
            CUSTOMER,
            "support-governance",
            1,
            if_match=created.etag,
            published_at=T0,
            intent_id=INTENT,
            audit_id=AUDIT,
        )
    assert info.value.reason == "policy_modified"


async def test_a_new_version_supersedes_in_list_but_not_in_published(rig: Rig) -> None:
    await _published(rig)
    v2 = await rig.policies.create_draft(draft(version=2, previous=1))
    assert v2.policy.policy_version == 2
    page = await rig.policies.list(CUSTOMER, [DOMAIN], PageRequest())
    assert [(s.policy.policy_id.root, s.policy.policy_version) for s in page.items] == [
        ("support-governance", 2)
    ]
    published = await rig.policies.list_published(CUSTOMER, [DOMAIN])
    assert [(s.policy.policy_version, s.policy.status) for s in published] == [(1, "published")]
    versions = await rig.policies.versions(CUSTOMER, "support-governance")
    assert [s.policy.policy_version for s in versions] == [1, 2]
    latest = await rig.policies.get(CUSTOMER, "support-governance")
    assert latest is not None
    assert latest.policy.policy_version == 2


async def test_retire_only_a_published_version(rig: Rig) -> None:
    created = await rig.policies.create_draft(draft())
    with pytest.raises(GovernancePolicyStaleError) as info:
        await rig.policies.mark_retired(CUSTOMER, "support-governance", 1, if_match=created.etag)
    assert info.value.reason == "policy_not_published"
    published = await rig.policies.mark_published(
        CUSTOMER,
        "support-governance",
        1,
        if_match=created.etag,
        published_at=T0,
        intent_id=INTENT,
        audit_id=AUDIT,
    )
    retired = await rig.policies.mark_retired(
        CUSTOMER, "support-governance", 1, if_match=published.etag
    )
    assert retired.policy.status == "retired"
    with pytest.raises(PolicyPublishedError):
        await rig.policies.replace_draft(draft(), if_match=retired.etag)
    with pytest.raises(GovernancePolicyStaleError) as info:
        await rig.policies.mark_retired(CUSTOMER, "support-governance", 1, if_match=retired.etag)
    assert info.value.reason == "policy_retired"
    published_now = await rig.policies.list_published(CUSTOMER)
    assert published_now == []


async def test_a_policy_id_is_unique_per_customer(rig: Rig) -> None:
    await _published(rig)
    with pytest.raises(GovernancePolicyStaleError) as info:
        await rig.policies.create_draft(draft(version=2, previous=1, domain=OTHER_DOMAIN))
    assert info.value.reason == "policy_exists"


async def test_list_filters_by_domain_and_pages(rig: Rig) -> None:
    for name in ("alpha", "bravo", "charlie"):
        await rig.policies.create_draft(draft(name))
    await rig.policies.create_draft(draft("delta", domain=OTHER_DOMAIN))
    first = await rig.policies.list(CUSTOMER, [DOMAIN], PageRequest(page_size=2))
    assert [s.policy.policy_id.root for s in first.items] == ["alpha", "bravo"]
    assert first.next_cursor is not None
    second = await rig.policies.list(
        CUSTOMER, [DOMAIN], PageRequest(page_size=2, cursor=first.next_cursor)
    )
    assert [s.policy.policy_id.root for s in second.items] == ["charlie"]
    assert second.next_cursor is None
    both = await rig.policies.list(CUSTOMER, [DOMAIN, OTHER_DOMAIN], PageRequest())
    assert len(both.items) == 4
    nothing = await rig.policies.list(CUSTOMER, [], PageRequest())
    assert nothing.items == ()
    other_customer = await rig.policies.list("globex", [DOMAIN], PageRequest())
    assert other_customer.items == ()
    foreign = await rig.policies.get("globex", "alpha")
    assert foreign is None


async def test_a_stale_unsuperseded_version_does_not_end_the_listing_early(rig: Rig) -> None:
    # Review A (PRP-105 item 3): the supersede replace after a new version can lose a race and
    # leave the older version ``superseded=False``. The page cursor comes from the raw rows, so
    # the de-dup dropping that stale row cannot make the listing stop before "bravo".
    await _published(rig, "alpha")
    await rig.policies.create_draft(draft("alpha", version=2, previous=1))
    await rig.policies.create_draft(draft("bravo"))
    for doc in rig.docs("definitions"):
        if doc.get("policy_id") == "alpha" and doc.get("policy_version") == 1:
            doc["superseded"] = False  # simulate the lost supersede write
    seen: list[tuple[str, int]] = []
    cursor: str | None = None
    for _ in range(10):
        page = await rig.policies.list(CUSTOMER, [DOMAIN], PageRequest(page_size=1, cursor=cursor))
        seen.extend((s.policy.policy_id.root, s.policy.policy_version) for s in page.items)
        cursor = page.next_cursor
        if cursor is None:
            break
    assert seen == [("alpha", 2), ("bravo", 1)]


async def test_a_bad_cursor_is_invalid_schema(rig: Rig) -> None:
    with pytest.raises(InvalidSchemaError) as info:
        await rig.policies.list(CUSTOMER, [DOMAIN], PageRequest(cursor="bm90LWEta2V5"))
    assert info.value.reason == "invalid_cursor"


async def test_a_tampered_policy_record_is_upstream_invalid(rig: Rig) -> None:
    await rig.policies.create_draft(draft())
    for doc in rig.docs("definitions"):
        doc["rules"][0]["params"]["allowed_models"][0]["model_name"] = "tampered"
    with pytest.raises(DependencyTransientError) as info:
        await rig.policies.get(CUSTOMER, "support-governance")
    assert info.value.status == 502


# --- evaluation status --------------------------------------------------------------------------


def _status(run_id: str, started: str, state: str = "completed") -> EvaluationStatus:
    return EvaluationStatus.model_validate(
        {
            "run_id": run_id,
            "cloud": "commercial",
            "customer_id": CUSTOMER,
            "domain_id": DOMAIN,
            "trigger": "interval",
            "state": state,
            "started_at": started,
            "correlation_id": "corr-run",
            "rules": [
                RuleRunStatus(
                    policy_id="support-governance",
                    policy_version=1,
                    rule_id="pii-access",
                    rule_kind="data_sensitivity_access",
                    outcome="truncated" if state == "truncated" else "complete",
                    reason_code="subject_budget" if state == "truncated" else None,
                    subjects_evaluated=10,
                ).model_dump()
            ],
        }
    )


async def test_run_status_documents_live_beside_policies(rig: Rig) -> None:
    first, second = new_uuid(), new_uuid()
    await rig.statuses.record(_status(first, "2026-11-20T09:00:00Z"))
    await rig.statuses.record(_status(second, "2026-11-20T09:05:00Z", "truncated"))
    latest = await rig.statuses.latest(CUSTOMER, DOMAIN)
    assert latest is not None
    assert latest.status.run_id == second
    assert latest.status.state == "truncated"
    recent = await rig.statuses.recent(CUSTOMER, DOMAIN)
    assert [s.status.run_id for s in recent] == [second, first]
    again = await rig.statuses.record(
        _status(first, "2026-11-20T09:00:00Z").model_copy(update={"state": "failed"})
    )
    fetched = await rig.statuses.get(CUSTOMER, DOMAIN, first)
    assert fetched is not None
    assert fetched.status.state == "failed"
    assert fetched.etag == again.etag
    # run status never shows up as a policy
    as_policies = await rig.policies.list(CUSTOMER, [DOMAIN], PageRequest())
    assert as_policies.items == ()


# --- violations ---------------------------------------------------------------------------------


def _key(subject: str = SUBJECT, rule: str = "pii-access") -> str:
    return dedup_key("support-governance", rule, subject, "reads_sensitive")


async def test_a_repeat_observation_bumps_the_one_violation(rig: Rig) -> None:
    run1, run2 = new_uuid(), new_uuid()
    first = await rig.violations.upsert_observed(_key(), observation(run_id=run1), now=T0)
    assert first.created
    v = first.stored.violation
    assert v.status == "open"
    assert v.occurrence_count == 1
    assert v.first_seen_at == v.last_seen_at
    assert {e.ref for e in v.evidence} == {SUBJECT + "/reads", ASSET}
    later = T0 + timedelta(minutes=5)
    second = await rig.violations.upsert_observed(_key(), observation(run_id=run2), now=later)
    assert not second.created
    assert second.stored.violation.violation_id == v.violation_id
    assert second.stored.violation.occurrence_count == 2
    assert second.stored.violation.last_seen_at.root == "2026-11-20T09:05:00Z"
    assert second.stored.violation.first_seen_at == v.first_seen_at
    assert second.stored.last_run_id == run2
    page = await rig.violations.list(
        CUSTOMER, ViolationFilters(domain_ids=(DOMAIN,)), PageRequest()
    )
    assert len(page.items) == 1


async def test_the_dedup_key_must_match_the_observation(rig: Rig) -> None:
    with pytest.raises(InvalidSchemaError) as info:
        await rig.violations.upsert_observed(
            _key(OTHER_SUBJECT), observation(run_id=new_uuid()), now=T0
        )
    assert info.value.reason == "dedup_key_mismatch"
    assert rig.docs("violations") == []


async def test_resolve_missing_resolves_only_what_the_run_did_not_see(rig: Rig) -> None:
    run1, run2, run3 = new_uuid(), new_uuid(), new_uuid()
    a = await rig.violations.upsert_observed(_key(), observation(run_id=run1), now=T0)
    b = await rig.violations.upsert_observed(
        _key(OTHER_SUBJECT), observation(run_id=run1, subject=OTHER_SUBJECT), now=T0
    )
    later = T0 + timedelta(minutes=5)
    await rig.violations.upsert_observed(_key(), observation(run_id=run2), now=later)
    resolved = await rig.violations.resolve_missing(
        CUSTOMER,
        [DOMAIN],
        run_id=run2,
        policy_id="support-governance",
        rule_id="pii-access",
        now=later,
    )
    assert [r.violation.violation_id for r in resolved] == [b.stored.violation.violation_id]
    gone = resolved[0].violation
    assert gone.status == "resolved"
    assert gone.resolution is not None
    assert gone.resolution.reason_code.root == "condition_cleared"
    assert gone.resolution.resolved_at.root == "2026-11-20T09:05:00Z"
    still = await rig.violations.get(CUSTOMER, DOMAIN, a.stored.violation.violation_id.root)
    assert still is not None
    assert still.violation.status == "open"
    # the condition recurs: a NEW violation (generation 2), the resolved one stays resolved
    back = await rig.violations.upsert_observed(
        _key(OTHER_SUBJECT), observation(run_id=run3, subject=OTHER_SUBJECT), now=later
    )
    assert back.created
    assert back.stored.violation.violation_id != b.stored.violation.violation_id
    everything = await rig.violations.list(
        CUSTOMER, ViolationFilters(domain_ids=(DOMAIN,)), PageRequest()
    )
    assert len(everything.items) == 3


async def test_resolve_missing_stays_inside_the_given_domains_and_rule(rig: Rig) -> None:
    run1, run2 = new_uuid(), new_uuid()
    other = await rig.violations.upsert_observed(
        _key(), observation(run_id=run1, domain=OTHER_DOMAIN), now=T0
    )
    owner = await rig.violations.upsert_observed(
        dedup_key("support-governance", "owner-needed", SUBJECT, "reads_sensitive"),
        observation(run_id=run1, rule_id="owner-needed"),
        now=T0,
    )
    resolved = await rig.violations.resolve_missing(
        CUSTOMER,
        [DOMAIN],
        run_id=run2,
        policy_id="support-governance",
        rule_id="pii-access",
        now=T0,
    )
    assert resolved == []
    for stored, domain in ((other, OTHER_DOMAIN), (owner, DOMAIN)):
        fetched = await rig.violations.get(
            CUSTOMER, domain, stored.stored.violation.violation_id.root
        )
        assert fetched is not None
        assert fetched.violation.status == "open"
    no_domains = await rig.violations.resolve_missing(
        CUSTOMER, [], run_id=run2, policy_id="support-governance", rule_id="pii-access", now=T0
    )
    assert no_domains == []


def _small_batch_violations(kind: str, *, batch: int, max_batches: int) -> ViolationStore:
    if kind == "memory":
        return InMemoryViolationStore(resolve_batch=batch, resolve_max_batches=max_batches)
    return CosmosViolationStore(
        FakeContainer(PARTITION_KEY_PATHS),  # type: ignore[arg-type]
        resolve_batch=batch,
        resolve_max_batches=max_batches,
    )


async def _observe(store: ViolationStore, run_id: str, subjects: list[str]) -> None:
    for subject in subjects:
        await store.upsert_observed(
            _key(subject), observation(run_id=run_id, subject=subject), now=T0
        )


_SUBJECTS = [f"commercial:acme:neurosphere:agent:bot-{i}" for i in range(5)]


@pytest.mark.parametrize("kind", ["memory", "cosmos-fake"])
async def test_rows_seen_this_run_do_not_use_up_the_resolve_batch(kind: str) -> None:
    # Review A (PRP-105 item 3): the old pass read TOP n rows and skipped the ones this run had
    # seen, so n seen rows hid every stale one behind them. Seen rows are now excluded by the
    # query (``c.last_run_id != @run_id``) and the pass pages until the stale rows are read.
    store = _small_batch_violations(kind, batch=2, max_batches=10)
    run1, run2 = new_uuid(), new_uuid()
    await _observe(store, run1, _SUBJECTS)
    await _observe(store, run2, _SUBJECTS[:3])  # bot-0..2 seen again; bot-3, bot-4 are stale
    report = await store.resolve_missing_report(
        CUSTOMER,
        [DOMAIN],
        run_id=run2,
        policy_id="support-governance",
        rule_id="pii-access",
        now=T0,
    )
    assert not report.truncated
    assert sorted(r.violation.subject.canonical_id for r in report.resolved) == _SUBJECTS[3:]


@pytest.mark.parametrize("kind", ["memory", "cosmos-fake"])
async def test_a_resolve_pass_past_its_batch_cap_reports_truncated(kind: str) -> None:
    store = _small_batch_violations(kind, batch=2, max_batches=2)
    run1, run2 = new_uuid(), new_uuid()
    await _observe(store, run1, _SUBJECTS)
    report = await store.resolve_missing_report(
        CUSTOMER,
        [DOMAIN],
        run_id=run2,
        policy_id="support-governance",
        rule_id="pii-access",
        now=T0,
    )
    assert report.truncated
    assert len(report.resolved) == 4  # two full batches; the fifth stays open for next run
    again = await store.resolve_missing_report(
        CUSTOMER,
        [DOMAIN],
        run_id=run2,
        policy_id="support-governance",
        rule_id="pii-access",
        now=T0,
    )
    assert not again.truncated
    assert len(again.resolved) == 1


async def test_set_exception_marks_excepted_and_back(rig: Rig) -> None:
    made = await rig.violations.upsert_observed(_key(), observation(run_id=new_uuid()), now=T0)
    vid = made.stored.violation.violation_id.root
    exception_id = new_uuid()
    excepted = await rig.violations.set_exception(
        CUSTOMER, DOMAIN, vid, exception_id, if_match=made.stored.etag
    )
    assert excepted.violation.status == "excepted"
    assert excepted.violation.exception_id is not None
    assert excepted.violation.exception_id.root == exception_id
    with pytest.raises(GovernancePolicyStaleError) as info:
        await rig.violations.set_exception(CUSTOMER, DOMAIN, vid, None, if_match=made.stored.etag)
    assert info.value.reason == "violation_modified"
    reopened = await rig.violations.set_exception(
        CUSTOMER, DOMAIN, vid, None, if_match=excepted.etag
    )
    assert reopened.violation.status == "open"
    with pytest.raises(GovernancePolicyNotFoundError):
        await rig.violations.set_exception(CUSTOMER, DOMAIN, new_uuid(), None, if_match="x")


async def test_a_resolved_violation_cannot_be_excepted(rig: Rig) -> None:
    run1 = new_uuid()
    made = await rig.violations.upsert_observed(_key(), observation(run_id=run1), now=T0)
    (resolved,) = await rig.violations.resolve_missing(
        CUSTOMER,
        [DOMAIN],
        run_id=new_uuid(),
        policy_id="support-governance",
        rule_id="pii-access",
        now=T0,
    )
    with pytest.raises(GovernancePolicyStaleError) as info:
        await rig.violations.set_exception(
            CUSTOMER,
            DOMAIN,
            made.stored.violation.violation_id.root,
            new_uuid(),
            if_match=resolved.etag,
        )
    assert info.value.reason == "violation_resolved"


async def test_violation_list_filters_and_pages_newest_first(rig: Rig) -> None:
    subjects = [f"commercial:acme:neurosphere:agent:bot-{i}" for i in range(3)]
    for i, subject in enumerate(subjects):
        await rig.violations.upsert_observed(
            _key(subject),
            observation(run_id=new_uuid(), subject=subject),
            now=T0 + timedelta(minutes=i),
        )
    first = await rig.violations.list(
        CUSTOMER, ViolationFilters(domain_ids=(DOMAIN,)), PageRequest(page_size=2)
    )
    assert [s.violation.subject.canonical_id for s in first.items] == [subjects[2], subjects[1]]
    assert first.next_cursor is not None
    second = await rig.violations.list(
        CUSTOMER,
        ViolationFilters(domain_ids=(DOMAIN,)),
        PageRequest(page_size=2, cursor=first.next_cursor),
    )
    assert [s.violation.subject.canonical_id for s in second.items] == [subjects[0]]
    only = await rig.violations.list(
        CUSTOMER,
        ViolationFilters(domain_ids=(DOMAIN,), subject_id=subjects[1], status="open"),
        PageRequest(),
    )
    assert [s.violation.subject.canonical_id for s in only.items] == [subjects[1]]
    none = await rig.violations.list(
        CUSTOMER, ViolationFilters(domain_ids=(OTHER_DOMAIN,)), PageRequest()
    )
    assert none.items == ()


async def test_a_violation_document_carries_ids_and_counts_only(rig: Rig) -> None:
    await rig.violations.upsert_observed(_key(), observation(run_id=new_uuid()), now=T0)
    (doc,) = rig.docs("violations")
    allowed = set(PolicyViolation.model_fields) | {
        "id",
        "doc_kind",
        "sort_key",
        "subject_id",
        "last_run_id",
        "_etag",
        "_ts",
    }
    assert set(doc) <= allowed
    for evidence in doc["evidence"]:
        assert set(evidence) == {"evidence_kind", "ref", "observed_at"}


# --- exceptions ---------------------------------------------------------------------------------


async def test_exception_request_is_create_only(rig: Rig) -> None:
    requested = exception()
    stored = await rig.exceptions.request(requested)
    assert stored.exception.status == "requested"
    with pytest.raises(GovernancePolicyStaleError) as info:
        await rig.exceptions.request(requested)
    assert info.value.reason == "exception_exists"
    approved = requested.model_copy(update={"status": "approved"})
    with pytest.raises(InvalidSchemaError):
        await rig.exceptions.request(approved)


async def test_an_approved_exception_is_active_until_it_expires(rig: Rig) -> None:
    stored = await rig.exceptions.request(exception())
    eid = stored.exception.exception_id.root
    now = T0 + timedelta(days=1)
    pending = await rig.exceptions.active_for(
        CUSTOMER,
        DOMAIN,
        subject_id=SUBJECT,
        policy_id="support-governance",
        rule_id="pii-access",
        now=now,
    )
    assert pending is None
    approved = await rig.exceptions.set_state(
        CUSTOMER,
        DOMAIN,
        eid,
        "approved",
        if_match=stored.etag,
        decided_by=REVIEWER,
        decided_at=now,
        audit_id=AUDIT,
    )
    assert approved.exception.status == "approved"
    assert approved.exception.decided_by is not None
    assert approved.exception.decided_by.root == REVIEWER
    active = await rig.exceptions.active_for(
        CUSTOMER,
        DOMAIN,
        subject_id=SUBJECT,
        policy_id="support-governance",
        rule_id="pii-access",
        now=now,
    )
    assert active is not None
    assert active.exception.exception_id.root == eid
    expired = await rig.exceptions.active_for(
        CUSTOMER,
        DOMAIN,
        subject_id=SUBJECT,
        policy_id="support-governance",
        rule_id="pii-access",
        now=T0 + timedelta(days=60),
    )
    assert expired is None
    other_rule = await rig.exceptions.active_for(
        CUSTOMER,
        DOMAIN,
        subject_id=SUBJECT,
        policy_id="support-governance",
        rule_id="owner-needed",
        now=now,
    )
    assert other_rule is None


async def test_exception_transitions_are_closed(rig: Rig) -> None:
    stored = await rig.exceptions.request(exception())
    eid = stored.exception.exception_id.root
    with pytest.raises(InvalidSchemaError):
        await rig.exceptions.set_state(CUSTOMER, DOMAIN, eid, "approved", if_match=stored.etag)
    rejected = await rig.exceptions.set_state(
        CUSTOMER, DOMAIN, eid, "rejected", if_match=stored.etag, decided_by=REVIEWER, decided_at=T0
    )
    with pytest.raises(GovernancePolicyStaleError) as info:
        await rig.exceptions.set_state(
            CUSTOMER,
            DOMAIN,
            eid,
            "approved",
            if_match=rejected.etag,
            decided_by=REVIEWER,
            decided_at=T0,
        )
    assert info.value.reason == "invalid_exception_transition"
    second = await rig.exceptions.request(exception())
    with pytest.raises(GovernancePolicyStaleError) as info:
        await rig.exceptions.set_state(
            CUSTOMER, DOMAIN, second.exception.exception_id.root, "revoked", if_match='"stale"'
        )
    assert info.value.reason == "exception_modified"
    with pytest.raises(GovernancePolicyNotFoundError):
        await rig.exceptions.set_state(CUSTOMER, DOMAIN, new_uuid(), "revoked", if_match="x")


async def test_exception_list_filters(rig: Rig) -> None:
    await rig.exceptions.request(exception(requested_at="2026-11-20T09:00:00Z"))
    await rig.exceptions.request(
        exception(subject=OTHER_SUBJECT, requested_at="2026-11-20T10:00:00Z")
    )
    page = await rig.exceptions.list(
        CUSTOMER, ExceptionFilters(domain_ids=(DOMAIN,)), PageRequest()
    )
    assert [s.exception.subject.canonical_id for s in page.items] == [OTHER_SUBJECT, SUBJECT]
    one = await rig.exceptions.list(
        CUSTOMER, ExceptionFilters(domain_ids=(DOMAIN,), subject_id=SUBJECT), PageRequest()
    )
    assert len(one.items) == 1
    wrong_domain = await rig.exceptions.get(
        CUSTOMER, OTHER_DOMAIN, one.items[0].exception.exception_id.root
    )
    assert wrong_domain is None


# --- outages ------------------------------------------------------------------------------------


async def test_an_outage_is_dependency_transient(rig: Rig) -> None:
    error: Exception = (
        RuntimeError("socket closed")
        if rig.kind == "cosmos-fake"
        else DependencyTransientError("down", reason="govpolicy_store_unavailable")
    )
    rig.fail("definitions", error)
    with pytest.raises(DependencyTransientError) as info:
        await rig.policies.get(CUSTOMER, "support-governance")
    assert info.value.reason == "govpolicy_store_unavailable"
    assert "socket" not in str(info.value)


async def test_cosmos_throttling_is_rate_limited() -> None:
    container = FakeContainer(PARTITION_KEY_PATHS)
    store = CosmosViolationStore(container)  # type: ignore[arg-type]
    container.fail = throttled()
    with pytest.raises(RateLimitedError):
        await store.get(CUSTOMER, DOMAIN, new_uuid())


# --- Cosmos query shape -------------------------------------------------------------------------


async def test_every_cosmos_query_orders_by_one_property_with_parameters() -> None:
    containers = {name: FakeContainer(PARTITION_KEY_PATHS) for name in ("d", "v", "e")}
    policies = CosmosPolicyDefinitionStore(containers["d"])  # type: ignore[arg-type]
    violations = CosmosViolationStore(containers["v"])  # type: ignore[arg-type]
    exceptions = CosmosExceptionStore(containers["e"])  # type: ignore[arg-type]
    created = await policies.create_draft(draft())
    await policies.list(CUSTOMER, [DOMAIN], PageRequest())
    await policies.list_published(CUSTOMER)
    await policies.versions(CUSTOMER, "support-governance")
    await policies.mark_published(
        CUSTOMER,
        "support-governance",
        1,
        if_match=created.etag,
        published_at=T0,
        intent_id=INTENT,
        audit_id=AUDIT,
    )
    await violations.upsert_observed(_key(), observation(run_id=new_uuid()), now=T0)
    await violations.resolve_missing(
        CUSTOMER,
        [DOMAIN],
        run_id=new_uuid(),
        policy_id="support-governance",
        rule_id="pii-access",
        now=T0,
    )
    await violations.list(CUSTOMER, ViolationFilters(domain_ids=(DOMAIN,)), PageRequest())
    await exceptions.list(CUSTOMER, ExceptionFilters(domain_ids=(DOMAIN,)), PageRequest())
    await exceptions.active_for(
        CUSTOMER,
        DOMAIN,
        subject_id=SUBJECT,
        policy_id="support-governance",
        rule_id="pii-access",
        now=T0,
    )
    queries = [q for c in containers.values() for q in c.queries]
    assert queries
    for sql, params, _ in queries:
        order = sql.split("ORDER BY", 1)[1]
        assert "," not in order, sql
        assert "c.sort_key" in order
        assert "@customer_id" in sql
        assert params["@customer_id"] == CUSTOMER
        for value in params.values():
            if isinstance(value, str):
                assert value not in sql  # values are parameters, never text


async def test_the_fake_refuses_a_multi_property_order_by_like_cosmos() -> None:
    from azure.cosmos.exceptions import CosmosHttpResponseError

    container = FakeContainer(PARTITION_KEY_PATHS)
    with pytest.raises(CosmosHttpResponseError) as info:
        container.query_items(
            "SELECT * FROM c ORDER BY c.policy_id ASC, c.policy_version DESC", parameters=[]
        )
    assert info.value.status_code == 400


def test_document_query_accepts_only_the_closed_field_list() -> None:
    with pytest.raises(ValueError, match="not queryable"):
        DocumentQuery(customer_id=CUSTOMER, limit=1, equals=(("content", "x"),))
    with pytest.raises(ValueError, match="not queryable"):
        DocumentQuery(customer_id=CUSTOMER, limit=1, any_of=(("rule_id", ("a",)),))
    sql, params = build_query(
        DocumentQuery(customer_id=CUSTOMER, limit=5, equals=(("policy_id", "p'; DROP"),))
    )
    assert "DROP" not in sql
    assert {"name": "@policy_id", "value": "p'; DROP"} in params


# --- enforcement bindings -----------------------------------------------------------------------


def _policy(mode: str = "audit", kinds: tuple[str, ...] | None = None) -> Any:
    document = draft(kinds=kinds)
    document["mode"] = mode
    return validate_draft(document)


async def test_bindings_start_in_audit_and_are_idempotent(bindings: BindingStore) -> None:
    policy = _policy()
    made = await bindings.ensure_bindings(policy, ["gateway", "sdk"], "audit", updated_by=AUTHOR)
    assert [b.binding.point.root for b in made] == ["gateway", "sdk"]
    for stored in made:
        assert stored.binding.mode is not None
        assert stored.binding.mode.root == "audit"
        assert stored.binding.state == "pending"
        assert stored.binding.target is None
        assert stored.binding.domain_id.root == DOMAIN
    again = await bindings.ensure_bindings(policy, ["gateway", "sdk"], "audit", updated_by=AUTHOR)
    assert [b.etag for b in again] == [b.etag for b in made]


async def test_off_mode_policy_gets_off_bindings(bindings: BindingStore) -> None:
    made = await bindings.ensure_bindings(
        _policy("off"), ["registration"], "off", updated_by=AUTHOR
    )
    assert made[0].binding.mode is not None
    assert made[0].binding.mode.root == "off"


async def test_enforce_is_never_set_at_creation(bindings: BindingStore) -> None:
    with pytest.raises(InvalidSchemaError) as info:
        await bindings.ensure_bindings(_policy(), ["gateway"], "enforce", updated_by=AUTHOR)
    assert info.value.reason == "enforce_requires_mode_change"
    none_made = await bindings.list(CUSTOMER)
    assert none_made == []


async def test_a_point_no_rule_binds_to_is_refused(bindings: BindingStore) -> None:
    policy = _policy(kinds=("model_allow_list",))
    with pytest.raises(InvalidSchemaError) as info:
        await bindings.ensure_bindings(policy, ["budget"], "audit", updated_by=AUTHOR)
    assert info.value.reason == "point_not_applicable"
    with pytest.raises(InvalidSchemaError) as info:
        await bindings.ensure_bindings(policy, ["firewall"], "audit", updated_by=AUTHOR)
    assert info.value.reason == "unknown_enforcement_point"


async def test_set_mode_is_the_etag_guarded_path_to_enforce(bindings: BindingStore) -> None:
    policy = _policy()
    (made,) = await bindings.ensure_bindings(policy, ["gateway"], "audit", updated_by=AUTHOR)
    bid = made.binding.binding_id.root
    enforced = await bindings.set_mode(
        CUSTOMER, bid, "enforce", if_match=made.etag, updated_by=REVIEWER, intent_id=INTENT
    )
    assert enforced.binding.mode is not None
    assert enforced.binding.mode.root == "enforce"
    assert enforced.binding.state == "pending"
    assert enforced.binding.last_intent_id is not None
    assert enforced.binding.last_intent_id.root == INTENT
    assert enforced.version == made.version + 1
    with pytest.raises(StaleVersionError) as info:
        await bindings.set_mode(CUSTOMER, bid, "audit", if_match=made.etag, updated_by=REVIEWER)
    assert info.value.reason == "binding_modified"
    # a later publish never resets an approved mode
    (kept,) = await bindings.ensure_bindings(policy, ["gateway"], "audit", updated_by=AUTHOR)
    assert kept.binding.mode is not None
    assert kept.binding.mode.root == "enforce"
    applied = await bindings.set_state(
        CUSTOMER,
        bid,
        "applied",
        intent_id=INTENT,
        audit_id=AUDIT,
        if_match=enforced.etag,
        updated_by=REVIEWER,
        verified_at=T0,
    )
    assert applied.binding.state == "applied"
    assert applied.binding.last_verified_at is not None
    assert applied.binding.last_verified_at.root == "2026-11-20T09:00:00Z"
    with pytest.raises(NotFoundError):
        await bindings.set_mode(CUSTOMER, "b-missing", "off", if_match="x", updated_by=REVIEWER)
    missing = await bindings.get(CUSTOMER, "b-missing")
    assert missing is None


async def test_binding_list_filters(bindings: BindingStore) -> None:
    policy = _policy()
    await bindings.ensure_bindings(policy, ["gateway", "tool_call"], "audit", updated_by=AUTHOR)
    tool = target("commercial:acme:neurosphere:tool:crm-lookup", "tool")
    await bindings.ensure_bindings(policy, ["tool_call"], "audit", updated_by=AUTHOR, target=tool)
    assert len(await bindings.list(CUSTOMER)) == 3
    assert len(await bindings.list(CUSTOMER, point="tool_call")) == 2
    assert len(await bindings.list(CUSTOMER, policy_id="other")) == 0
    covering = await bindings.list(CUSTOMER, point="tool_call", target=tool.canonical_id)
    assert len(covering) == 2
    exact = await bindings.list(
        CUSTOMER, point="tool_call", target=tool.canonical_id, include_all_targets=False
    )
    assert [b.binding.target.canonical_id for b in exact if b.binding.target] == [tool.canonical_id]
    elsewhere = await bindings.list(CUSTOMER, domain_ids=[OTHER_DOMAIN])
    assert elsewhere == []
