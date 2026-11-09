"""PRP-16 item 8: calibration sample -> HITL evaluation_dispute items -> HumanLabelRecords.

Real in-memory HITL service/store and evaluation store; no mocks of HITL.
"""

from __future__ import annotations

import itertools
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from neurosphere_contracts.actions.v1.actor import Actor
from neurosphere_contracts.evaluation.v1.evaluation_result import EvaluationResult
from neurosphere_contracts.scope.v1.identity_scope import IdentityScope as ContractScope
from neurosphere_core.audit import AuditRepository, InMemoryAuditStore
from neurosphere_core.auth.scope.permissions import Permission
from neurosphere_core.evaluation.calibration import LabelSource, ingest_labels
from neurosphere_core.evaluation.store import InMemoryEvaluationStore
from neurosphere_core.hitl import (
    DecisionLog,
    HitlService,
    InMemoryDecisionStore,
    InMemoryHitlStore,
    ReviewItem,
    ReviewPolicyRegistry,
)
from neurosphere_core.scope import IdentityScope
from neurosphere_workers.evaluation.labels import (
    DISPUTE_KIND,
    HitlLabelSource,
    SampleConfig,
    dispute_subject_ref,
    open_calibration_sample,
    select_sample,
)

CONTRACTS = Path(__file__).resolve().parents[4] / "packages/contracts/schemas"
FINANCE = "commercial:contoso:catalog:domain:finance"
OPERATIONS = "commercial:contoso:catalog:domain:operations"
T0 = datetime(2026, 10, 20, 9, 0, 0, tzinfo=UTC)
REVIEWER_ID = "commercial:contoso:entra:person:psn_reviewer0000001"
REVIEWER = Actor.model_validate(
    {"principal_pseudonym": "p-reviewer", "principal_kind": "user", "on_behalf_of": None}
)
SCOPE_HASH = "sha256:" + "0" * 64


def make_scope(*domains: str) -> IdentityScope:
    doc = json.loads(
        (CONTRACTS / "scope/v1/examples/valid/identity-scope.viewer.json").read_text("utf-8")
    )
    chosen = list(domains or (FINANCE,))
    doc["allowed_domains"] = chosen
    doc["roles"] = [{"role": "viewer", "domain_ids": chosen}]
    doc["customer_id"] = "contoso"
    doc["cloud"] = "commercial"
    return IdentityScope._from_verified_contract(ContractScope.model_validate(doc))  # pyright: ignore[reportPrivateUsage]


def make_result(
    n: int,
    value: float | None = 1.0,
    *,
    dimension: str = "groundedness",
    judge_version: str = "7",
    scale_max: float = 1,
    domain: str = FINANCE,
    **overrides: Any,
) -> EvaluationResult:
    doc = json.loads(
        (
            CONTRACTS / "evaluation/v1/examples/valid/evaluation-result.offline-llm-judge.json"
        ).read_text("utf-8")
    )
    doc["evaluation_id"] = f"eval:r-{n:04d}"
    doc["domain_id"] = domain
    doc["judge"]["judge_prompt_version"] = judge_version
    doc["scores"] = [
        {
            "dimension": dimension,
            "value": value,
            "scale": {"min": 0, "max": scale_max},
            "uncertainty": {"method": "not_estimable"},
            "sample_size": 0 if value is None else 1,
            "abstained_count": None,
        }
    ]
    doc.update(overrides)
    return EvaluationResult.model_validate(doc)


class Authorizer:
    async def can_review(
        self, principal_id: str, customer_id: str, domain_id: str, permission: Permission
    ) -> bool:
        return principal_id == REVIEWER_ID and permission == Permission.CATALOG_CURATE


class Clock:
    def __init__(self) -> None:
        self._now = T0

    def __call__(self) -> datetime:
        self._now += timedelta(seconds=1)
        return self._now


def build_hitl() -> HitlService:
    ticks = itertools.count(1)
    audit = AuditRepository(
        InMemoryAuditStore(),
        clock=Clock(),
        id_factory=lambda: f"00000000-0000-4000-8000-{next(ticks):012d}",
    )
    return HitlService(
        InMemoryHitlStore(),
        DecisionLog(audit, InMemoryDecisionStore()),
        audit,
        ReviewPolicyRegistry(),
        Authorizer(),
        id_factory=lambda: f"22222222-2222-4222-8222-{next(ticks):012d}",
    )


async def decide(hitl: HitlService, item_id: str, decision: str, *, at: datetime) -> None:
    await hitl.decide(
        item_id,
        REVIEWER_ID,
        REVIEWER,
        decision,  # type: ignore[arg-type]
        "reviewed",
        None,
        at,
        "corr-decide",
        scope_hash=SCOPE_HASH,
    )


def sample_ids(
    results: list[EvaluationResult], seed: int, cap: int = 100, per: int = 3
) -> list[str]:
    sample, _ = select_sample(results, SampleConfig(seed=seed, max_per_call=cap, per_stratum=per))
    return [c.result.evaluation_id.root for c in sample]


def population() -> list[EvaluationResult]:
    out: list[EvaluationResult] = []
    for n in range(1, 21):
        out.append(make_result(n, float(n % 2), judge_version="7"))
    for n in range(21, 41):
        out.append(make_result(n, float(n % 2), judge_version="8"))
    for n in range(41, 61):
        out.append(make_result(n, float(n % 2), dimension="safety", judge_version="7"))
    return out


def test_sample_is_reproducible_for_a_seed_and_differs_across_seeds() -> None:
    pop = population()
    assert sample_ids(pop, seed=1) == sample_ids(pop, seed=1)
    assert sample_ids(pop, seed=1) == sample_ids(list(reversed(pop)), seed=1)
    assert sample_ids(pop, seed=1) != sample_ids(pop, seed=2)


def test_sample_is_stratified_per_judge_config_and_dimension() -> None:
    pop = population()
    sample, eligible = select_sample(pop, SampleConfig(seed=3, max_per_call=100, per_stratum=3))
    assert eligible == 60
    counts: dict[tuple[str, str, str], int] = {}
    for cand in sample:
        counts[cand.stratum] = counts.get(cand.stratum, 0) + 1
    assert len(counts) == 3
    assert set(counts.values()) == {3}
    # A cap below strata x per_stratum still touches every stratum first.
    capped, _ = select_sample(pop, SampleConfig(seed=3, max_per_call=3, per_stratum=3))
    assert len({c.stratum for c in capped}) == 3
    assert len(select_sample(pop, SampleConfig(seed=3, max_per_call=4, per_stratum=3))[0]) == 4


def test_non_binary_abstained_and_judgeless_results_are_never_sampled() -> None:
    results = [
        make_result(1, 0.82),
        make_result(2, None),
        make_result(3, 1.0, scale_max=5),
        make_result(4, 1.0, judge={"judge_kind": "human"}, calibration=None),
        make_result(5, 1.0),
    ]
    assert sample_ids(results, seed=0) == ["eval:r-0005"]


async def test_opening_is_idempotent_and_uses_deterministic_subjects() -> None:
    hitl = build_hitl()
    store = InMemoryEvaluationStore(population())
    scope = make_scope()
    cfg = SampleConfig(seed=5, max_per_call=6, per_stratum=2)
    first = await open_calibration_sample(
        scope=scope, store=store, hitl=hitl, clock=Clock(), config=cfg
    )
    assert len(first.opened) == 6
    assert first.already_open == 0
    second = await open_calibration_sample(
        scope=scope, store=store, hitl=hitl, clock=Clock(), config=cfg
    )
    assert second.opened == ()
    assert second.already_open == 6
    page = await hitl.store.list(scope, FINANCE, kind=DISPUTE_KIND)
    assert len(page.items) == 6
    assert all(i.state_name == "pending" and i.domain_id == FINANCE for i in page.items)
    assert len({i.subject_ref for i in page.items}) == 6


async def test_results_outside_the_scope_are_never_sampled() -> None:
    hitl = build_hitl()
    outside = make_result(1, 1.0, domain=OPERATIONS)
    other_customer = make_result(
        2,
        1.0,
        customer_id="fabrikam",
        domain_id="commercial:fabrikam:catalog:domain:finance",
        subject_id="commercial:fabrikam:foundry:agent_version:a/v=1",
    )
    inside = make_result(3, 0.0)
    store = InMemoryEvaluationStore([outside, other_customer, inside])
    report = await open_calibration_sample(
        scope=make_scope(), store=store, hitl=hitl, clock=Clock(), config=SampleConfig(seed=0)
    )
    assert report.eligible == 1
    assert len(report.opened) == 1
    wide = await hitl.store.list(make_scope(FINANCE, OPERATIONS), OPERATIONS, kind=DISPUTE_KIND)
    assert wide.items == ()


async def _setup(values: list[float]) -> tuple[HitlService, HitlLabelSource, list[str]]:
    hitl = build_hitl()
    store = InMemoryEvaluationStore([make_result(n, v) for n, v in enumerate(values, start=1)])
    scope = make_scope()
    report = await open_calibration_sample(
        scope=scope,
        store=store,
        hitl=hitl,
        clock=Clock(),
        config=SampleConfig(seed=0, max_per_call=50, per_stratum=50),
    )
    return hitl, HitlLabelSource(scope=scope, store=store, hitl=hitl), list(report.opened)


async def _items_by_eval(hitl: HitlService, values: dict[int, float]) -> dict[int, ReviewItem]:
    items = (await hitl.store.list(make_scope(), FINANCE, kind=DISPUTE_KIND)).items
    by_ref = {i.subject_ref: i for i in items}
    return {
        n: by_ref[dispute_subject_ref(make_result(n, v), "groundedness")] for n, v in values.items()
    }


async def test_label_mapping_rejected_approved_expired_and_pending() -> None:
    values = {1: 1.0, 2: 1.0, 3: 0.0, 4: 0.0, 5: 1.0, 6: 0.0}
    hitl, source, opened = await _setup(list(values.values()))
    assert len(opened) == 6
    item_of = await _items_by_eval(hitl, values)
    later = T0 + timedelta(hours=1)

    await decide(hitl, item_of[1].item_id, "rejected", at=later)  # judge 1 correct -> 1
    await decide(hitl, item_of[2].item_id, "approved", at=later)  # judge 1 wrong -> 0
    await decide(hitl, item_of[3].item_id, "rejected", at=later)  # judge 0 correct -> 0
    await decide(hitl, item_of[4].item_id, "approved", at=later)  # judge 0 wrong -> 1
    # item 5 expires without a decision, item 6 stays pending
    expired = await hitl.apply_timers(
        item_of[5], item_of[5].expires_at + timedelta(seconds=1), correlation_id="c-timer"
    )
    assert expired.item.state_name == "expired"
    assert item_of[6].state_name == "pending"

    await source.load()
    records = {r.item_id: r for r in source.labels()}
    assert {k: v.value for k, v in records.items()} == {
        "eval:r-0001": 1.0,
        "eval:r-0002": 0.0,
        "eval:r-0003": 0.0,
        "eval:r-0004": 1.0,
    }
    assert {r.labeler for r in records.values()} == {"p-reviewer"}
    assert {r.dimension for r in records.values()} == {"groundedness"}
    assert len({r.label_set_version for r in records.values()}) == 1
    assert isinstance(source, LabelSource)
    label_set = ingest_labels(source)
    assert label_set.consensus("eval:r-0002", "groundedness") == 0.0
    assert label_set.consensus("eval:r-0004", "groundedness") == 1.0
    assert label_set.consensus("eval:r-0005", "groundedness") is None
    assert label_set.consensus("eval:r-0006", "groundedness") is None


async def test_assigned_and_expired_items_yield_no_label() -> None:
    hitl, source, _ = await _setup([1.0, 0.0])
    first, second = (await hitl.store.list(make_scope(), FINANCE, kind=DISPUTE_KIND)).items
    await hitl.assign(
        first.item_id,
        None,
        REVIEWER_ID,
        T0 + timedelta(hours=1),
        by=REVIEWER,
        scope_hash=SCOPE_HASH,
        correlation_id="c-assign",
    )
    await hitl.apply_timers(second, second.expires_at + timedelta(seconds=1), correlation_id="c-t")
    await source.load()
    assert source.labels() == ()
    assert source.label_set_version is None


async def test_label_set_version_is_deterministic_and_changes_with_decisions() -> None:
    hitl, source, _ = await _setup([1.0, 0.0])
    items = (await hitl.store.list(make_scope(), FINANCE, kind=DISPUTE_KIND)).items
    await decide(hitl, items[0].item_id, "rejected", at=T0 + timedelta(hours=1))
    await source.load()
    first = source.label_set_version
    assert first is not None
    await source.load()
    assert source.label_set_version == first
    await decide(hitl, items[1].item_id, "approved", at=T0 + timedelta(hours=2))
    await source.load()
    assert source.label_set_version != first
    assert len(source.labels()) == 2


async def test_label_source_ignores_items_outside_the_scope() -> None:
    hitl = build_hitl()
    store = InMemoryEvaluationStore([make_result(1, 1.0, domain=OPERATIONS)])
    await open_calibration_sample(
        scope=make_scope(FINANCE, OPERATIONS),
        store=store,
        hitl=hitl,
        clock=Clock(),
        config=SampleConfig(),
    )
    narrow = await HitlLabelSource(scope=make_scope(), store=store, hitl=hitl).load()
    assert narrow.labels() == ()


async def test_zero_cap_opens_nothing() -> None:
    report = await open_calibration_sample(
        scope=make_scope(),
        store=InMemoryEvaluationStore([make_result(1, 1.0)]),
        hitl=build_hitl(),
        clock=Clock(),
        config=SampleConfig(max_per_call=0),
    )
    assert report.opened == ()
