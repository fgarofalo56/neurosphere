"""PRP-16 item 8: calibration sample -> HITL evaluation_dispute items -> HumanLabelRecords.

Real in-memory HITL service/store, the real calibration and the real ``run_pipeline``; the items
are the per-item ``ItemOutcome``s of an offline run. No mocks of HITL or calibration.
"""

from __future__ import annotations

import itertools
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from neurosphere_contracts.actions.v1.actor import Actor
from neurosphere_contracts.scope.v1.identity_scope import IdentityScope as ContractScope
from neurosphere_core.audit import AuditRepository, InMemoryAuditStore
from neurosphere_core.auth.scope.permissions import Permission
from neurosphere_core.capabilities import load_matrix
from neurosphere_core.evaluation.calibration import LabelSource, ingest_labels
from neurosphere_core.evaluation.registry import (
    Criterion,
    DatasetItem,
    DatasetVersion,
    RubricVersion,
)
from neurosphere_core.evaluation.samples import CalibrationSample
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

# ``sandbox`` lives at the repo root; make this module importable when run on its own.
_REPO_ROOT = str(Path(__file__).resolve().parents[4])
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from neurosphere_workers.evaluation.labels import (  # noqa: E402
    DISPUTE_KIND,
    HitlLabelSource,
    SampleConfig,
    dispute_subject_ref,
    open_calibration_sample,
    select_sample,
)
from neurosphere_workers.evaluation.models import ItemOutcome  # noqa: E402
from neurosphere_workers.evaluation.pipeline import (  # noqa: E402
    CalibrationSettings,
    OfflineStage,
    run_pipeline,
)
from neurosphere_workers.evaluation.service import OfflineRunConfig  # noqa: E402

from sandbox.evaluation.loader import (  # noqa: E402
    PILOT_DATASET_ID,
    PILOT_VERSION,
    load_fixture_judge,
    load_registry,
)

from .support import ledger  # noqa: E402

CONTRACTS = Path(__file__).resolve().parents[4] / "packages/contracts/schemas"
FINANCE = "commercial:contoso:catalog:domain:finance"
OPERATIONS = "commercial:contoso:catalog:domain:operations"
T0 = datetime(2026, 10, 20, 9, 0, 0, tzinfo=UTC)
REVIEWER_ID = "commercial:contoso:entra:person:psn_reviewer0000001"
REVIEWER = Actor.model_validate(
    {"principal_pseudonym": "p-reviewer", "principal_kind": "user", "on_behalf_of": None}
)
SCOPE_HASH = "sha256:" + "0" * 64
RUBRIC = RubricVersion(
    rubric_id="rubric-t",
    version="1",
    dimensions=("groundedness", "safety"),
    criteria=(Criterion(criterion_id="c1", dimension="groundedness", description="grounded"),),
    scale_min=0.0,
    scale_max=1.0,
)
FIVE_POINT = RubricVersion(
    rubric_id="rubric-5",
    version="1",
    dimensions=("groundedness",),
    criteria=(Criterion(criterion_id="c1", dimension="groundedness", description="grounded"),),
    scale_min=1.0,
    scale_max=5.0,
)


def make_scope(
    *domains: str, cloud: str = "commercial", customer: str = "contoso"
) -> IdentityScope:
    doc = json.loads(
        (CONTRACTS / "scope/v1/examples/valid/identity-scope.viewer.json").read_text("utf-8")
    )
    chosen = list(domains or (FINANCE,))
    doc["allowed_domains"] = chosen
    doc["roles"] = [{"role": "viewer", "domain_ids": chosen}]
    doc["customer_id"] = customer
    doc["cloud"] = cloud
    return IdentityScope._from_verified_contract(ContractScope.model_validate(doc))  # pyright: ignore[reportPrivateUsage]


def make_outcome(
    n: int,
    value: float | None = 1.0,
    *,
    dimension: str = "groundedness",
    judge_version: str = "7",
    domain: str | None = FINANCE,
    customer: str | None = "contoso",
    **overrides: Any,
) -> ItemOutcome:
    doc: dict[str, Any] = {
        "item_id": f"item-{n:04d}",
        "stratum": "s/a/public",
        "domain": "finance",
        "customer_id": customer,
        "domain_id": domain,
        "subject_id": None,
        "dimension": dimension,
        "status": "scored" if value is not None else "abstained",
        "judge_config_id": "judge-a",
        "judge_config_version": judge_version,
        "value": value,
    }
    doc.update(overrides)
    return ItemOutcome.model_validate(doc)


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


def sample_ids(outcomes: list[ItemOutcome], seed: int, cap: int = 100, per: int = 3) -> list[str]:
    sample, _ = select_sample(
        outcomes, RUBRIC, make_scope(), SampleConfig(seed=seed, max_per_call=cap, per_stratum=per)
    )
    return [c.outcome.item_id for c in sample]


def population() -> list[ItemOutcome]:
    out: list[ItemOutcome] = []
    for n in range(1, 21):
        out.append(make_outcome(n, float(n % 2), judge_version="7"))
    for n in range(21, 41):
        out.append(make_outcome(n, float(n % 2), judge_version="8"))
    for n in range(41, 61):
        out.append(make_outcome(n, float(n % 2), dimension="safety", judge_version="7"))
    return out


def test_sample_is_reproducible_for_a_seed_and_differs_across_seeds() -> None:
    pop = population()
    assert sample_ids(pop, seed=1) == sample_ids(pop, seed=1)
    assert sample_ids(pop, seed=1) == sample_ids(list(reversed(pop)), seed=1)
    assert sample_ids(pop, seed=1) != sample_ids(pop, seed=2)


def test_sample_is_stratified_per_judge_config_and_dimension() -> None:
    pop = population()
    scope = make_scope()
    sample, eligible = select_sample(
        pop, RUBRIC, scope, SampleConfig(seed=3, max_per_call=100, per_stratum=3)
    )
    assert eligible == 60
    counts: dict[tuple[str, str, str], int] = {}
    for cand in sample:
        counts[cand.stratum] = counts.get(cand.stratum, 0) + 1
    assert len(counts) == 3
    assert set(counts.values()) == {3}
    # A cap below strata x per_stratum still touches every stratum first.
    capped, _ = select_sample(
        pop, RUBRIC, scope, SampleConfig(seed=3, max_per_call=3, per_stratum=3)
    )
    assert len({c.stratum for c in capped}) == 3
    four, _ = select_sample(pop, RUBRIC, scope, SampleConfig(seed=3, max_per_call=4, per_stratum=3))
    assert len(four) == 4


def test_non_binary_unscored_and_unattributed_outcomes_are_never_sampled() -> None:
    outcomes = [
        make_outcome(1, 0.82),
        make_outcome(2, None),
        make_outcome(3, 1.0, status="skipped"),
        make_outcome(4, 1.0, judge_config_id=None),
        make_outcome(5, 1.0, judge_config_version=None),
        make_outcome(6, 1.0, customer=None),
        make_outcome(7, 1.0, domain=None),
        make_outcome(8, 1.0, dimension="tool_correctness"),  # not a rubric dimension
        make_outcome(9, 1.0),
    ]
    assert sample_ids(outcomes, seed=0) == ["item-0009"]
    # A non-binary rubric scale makes every verdict ineligible.
    sample, eligible = select_sample(
        [make_outcome(1, 1.0)], FIVE_POINT, make_scope(), SampleConfig()
    )
    assert sample == () and eligible == 0


def test_subject_ref_binds_the_exact_verdict_shown() -> None:
    base = make_outcome(1, 1.0)
    ref = dispute_subject_ref("commercial", "contoso", base)
    assert ref == dispute_subject_ref("commercial", "contoso", make_outcome(1, 1.0))
    for other in (
        make_outcome(1, 0.0),
        make_outcome(2, 1.0),
        make_outcome(1, 1.0, judge_version="8"),
        make_outcome(1, 1.0, dimension="safety"),
        make_outcome(1, 1.0, judge_config_id="judge-b"),
    ):
        assert dispute_subject_ref("commercial", "contoso", other) != ref


async def test_opening_is_idempotent_and_uses_deterministic_subjects() -> None:
    hitl = build_hitl()
    scope = make_scope()
    cfg = SampleConfig(seed=5, max_per_call=6, per_stratum=2)
    first = await open_calibration_sample(
        scope=scope, outcomes=population(), rubric=RUBRIC, hitl=hitl, clock=Clock(), config=cfg
    )
    assert len(first.opened) == 6
    assert first.already_open == 0
    second = await open_calibration_sample(
        scope=scope, outcomes=population(), rubric=RUBRIC, hitl=hitl, clock=Clock(), config=cfg
    )
    assert second.opened == ()
    assert second.already_open == 6
    page = await hitl.store.list(scope, FINANCE, kind=DISPUTE_KIND)
    assert len(page.items) == 6
    assert all(i.state_name == "pending" and i.domain_id == FINANCE for i in page.items)
    assert len({i.subject_ref for i in page.items}) == 6


async def test_outcomes_outside_the_scope_are_never_sampled() -> None:
    hitl = build_hitl()
    outcomes = [
        make_outcome(1, 1.0, domain=OPERATIONS),
        make_outcome(
            2, 1.0, customer="fabrikam", domain="commercial:fabrikam:catalog:domain:finance"
        ),
        make_outcome(3, 0.0),
    ]
    report = await open_calibration_sample(
        scope=make_scope(),
        outcomes=outcomes,
        rubric=RUBRIC,
        hitl=hitl,
        clock=Clock(),
        config=SampleConfig(seed=0),
    )
    assert report.eligible == 1
    assert len(report.opened) == 1
    wide = await hitl.store.list(make_scope(FINANCE, OPERATIONS), OPERATIONS, kind=DISPUTE_KIND)
    assert wide.items == ()


async def _setup(values: list[float]) -> tuple[HitlService, HitlLabelSource, list[ItemOutcome]]:
    hitl = build_hitl()
    outcomes = [make_outcome(n, v) for n, v in enumerate(values, start=1)]
    scope = make_scope()
    await open_calibration_sample(
        scope=scope,
        outcomes=outcomes,
        rubric=RUBRIC,
        hitl=hitl,
        clock=Clock(),
        config=SampleConfig(seed=0, max_per_call=50, per_stratum=50),
    )
    source = HitlLabelSource(scope=scope, outcomes=outcomes, rubric=RUBRIC, hitl=hitl)
    return hitl, source, outcomes


async def _items_by_n(hitl: HitlService, outcomes: list[ItemOutcome]) -> dict[int, ReviewItem]:
    items = (await hitl.store.list(make_scope(), FINANCE, kind=DISPUTE_KIND)).items
    by_ref = {i.subject_ref: i for i in items}
    return {
        n: by_ref[dispute_subject_ref("commercial", "contoso", o)]
        for n, o in enumerate(outcomes, start=1)
    }


async def test_label_mapping_rejected_approved_expired_and_pending() -> None:
    hitl, source, outcomes = await _setup([1.0, 1.0, 0.0, 0.0, 1.0, 0.0])
    item_of = await _items_by_n(hitl, outcomes)
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
        "item-0001": 1.0,
        "item-0002": 0.0,
        "item-0003": 0.0,
        "item-0004": 1.0,
    }
    assert source.unmatched == 0
    assert {r.labeler for r in records.values()} == {"p-reviewer"}
    assert {r.dimension for r in records.values()} == {"groundedness"}
    assert len({r.label_set_version for r in records.values()}) == 1
    assert isinstance(source, LabelSource)
    label_set = ingest_labels(source)
    assert label_set.consensus("item-0002", "groundedness") == 0.0
    assert label_set.consensus("item-0004", "groundedness") == 1.0
    assert label_set.consensus("item-0005", "groundedness") is None
    assert label_set.consensus("item-0006", "groundedness") is None


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
    outcomes = [make_outcome(1, 1.0, domain=OPERATIONS)]
    await open_calibration_sample(
        scope=make_scope(FINANCE, OPERATIONS),
        outcomes=outcomes,
        rubric=RUBRIC,
        hitl=hitl,
        clock=Clock(),
        config=SampleConfig(),
    )
    narrow = await HitlLabelSource(
        scope=make_scope(), outcomes=outcomes, rubric=RUBRIC, hitl=hitl
    ).load()
    assert narrow.labels() == ()


async def test_a_changed_verdict_never_inherits_the_old_decision() -> None:
    hitl, _, outcomes = await _setup([1.0, 0.0])
    item_of = await _items_by_n(hitl, outcomes)
    await decide(hitl, item_of[1].item_id, "approved", at=T0 + timedelta(hours=1))
    await decide(hitl, item_of[2].item_id, "rejected", at=T0 + timedelta(hours=1))
    # A later run flips the verdict of item 1; item 2 is unchanged.
    rerun = [make_outcome(1, 0.0), make_outcome(2, 0.0)]
    source = await HitlLabelSource(
        scope=make_scope(), outcomes=rerun, rubric=RUBRIC, hitl=hitl
    ).load()
    assert [(r.item_id, r.value) for r in source.labels()] == [("item-0002", 0.0)]
    assert source.unmatched == 1


async def test_zero_cap_opens_nothing() -> None:
    report = await open_calibration_sample(
        scope=make_scope(),
        outcomes=[make_outcome(1, 1.0)],
        rubric=RUBRIC,
        hitl=build_hitl(),
        clock=Clock(),
        config=SampleConfig(max_per_call=0),
    )
    assert report.opened == ()


async def test_hitl_labels_join_real_calibration_in_the_pipeline() -> None:
    """Labels from decided dispute items reach ``calibrate`` through the real ``run_pipeline``."""
    registry = load_registry()
    pilot = registry.datasets.get(PILOT_DATASET_ID, PILOT_VERSION)
    judge_cfg = registry.judge_configs.latest("sbx-judge-government")
    rubric = registry.rubrics.latest("sbx-rubric")
    assert pilot is not None and judge_cfg is not None and rubric is not None
    domain = "government:sandbox:neurosphere:domain:sbx-dom"
    config = OfflineRunConfig(
        run_id="off-join",
        cloud="government",
        rubric=rubric,
        judges={"groundedness": judge_cfg},
        customer_id="sandbox",
        domain_id=domain,
        subject_id="government:sandbox:foundry:agent:sbx-agent",
    )

    async def run(labels: LabelSource | None) -> Any:
        return await run_pipeline(
            registry=registry,
            judge=load_fixture_judge(),
            matrix=load_matrix(),
            store=InMemoryEvaluationStore(),
            ledger=ledger(),
            clock=lambda: T0,
            offline=OfflineStage(pilot, config),
            labels=None if labels is None else ingest_labels(labels),
            calibration=CalibrationSettings(metric="accuracy", min_labels=1),
        )

    first = await run(None)
    outcomes = first.offline.outcomes
    scope = make_scope(domain, cloud="government", customer="sandbox")
    hitl = build_hitl()
    opened = await open_calibration_sample(
        scope=scope,
        outcomes=outcomes,
        rubric=rubric,
        hitl=hitl,
        clock=Clock(),
        config=SampleConfig(seed=11, max_per_call=12, per_stratum=12),
    )
    assert len(opened.opened) == 12
    items = (await hitl.store.list(scope, domain, kind=DISPUTE_KIND)).items
    for n, item in enumerate(sorted(items, key=lambda i: i.item_id)[:9]):
        await decide(
            hitl, item.item_id, "approved" if n % 3 == 0 else "rejected", at=T0 + timedelta(hours=1)
        )

    source = await HitlLabelSource(scope=scope, outcomes=outcomes, rubric=rubric, hitl=hitl).load()
    assert len(source.labels()) == 9
    assert source.unmatched == 0

    second = await run(source)
    (report,) = second.calibrations
    assert report.dimension == "groundedness"
    assert report.overall_coverage.labelled == 9
    assert report.agreement_sample_size == 9
    assert second.offline.judged_items == first.offline.judged_items


# -- PRP-16 round 2 item 14: calibration review context -------------------------------------------


def _dataset(classifications: dict[int, str]) -> DatasetVersion:
    items = tuple(
        DatasetItem(
            item_id=f"item-{n:04d}",
            dimension="groundedness",
            classification=cls,  # type: ignore[arg-type]
            payload={"question": f"q{n}"},
        )
        for n, cls in classifications.items()
    )
    return DatasetVersion.build(
        dataset_id="ds-1",
        version="3",
        kind="offline_benchmark",
        dimensions=("groundedness",),
        items=items,
        data_state="synthetic",
        created_at="2026-10-01T00:00:00Z",
    )


class _CountingSink:
    def __init__(self, inner: InMemoryEvaluationStore) -> None:
        self._inner = inner
        self.puts = 0

    async def put_calibration_sample(self, sample: CalibrationSample) -> None:
        self.puts += 1
        await self._inner.put_calibration_sample(sample)


async def test_sink_records_one_sample_per_newly_opened_item_and_none_on_rerun() -> None:
    hitl = build_hitl()
    store = InMemoryEvaluationStore()
    sink = _CountingSink(store)
    scope = make_scope()
    outcomes = [make_outcome(n, float(n % 2)) for n in (1, 2, 3)]
    dataset = _dataset({1: "internal", 2: "restricted", 3: "public"})
    cfg = SampleConfig(seed=0, max_per_call=50, per_stratum=50)
    first = await open_calibration_sample(
        scope=scope,
        outcomes=outcomes,
        rubric=RUBRIC,
        hitl=hitl,
        clock=Clock(),
        config=cfg,
        samples=sink,
        dataset=dataset,
    )
    assert len(first.opened) == 3
    assert sink.puts == 3
    got = {
        o.item_id: await store.get_calibration_sample(
            scope, FINANCE, dispute_subject_ref("commercial", "contoso", o)
        )
        for o in outcomes
    }
    one = got["item-0001"]
    assert one is not None
    assert (one.dataset_id, one.dataset_version) == ("ds-1", "3")
    assert (one.judge_config_id, one.judge_config_version, one.value) == ("judge-a", "7", 1.0)
    assert (one.rubric_id, one.rubric_version, one.dimension) == ("rubric-t", "1", "groundedness")
    assert one.payload == {"question": "q1"}
    assert one.payload_withheld is False
    two = got["item-0002"]
    assert two is not None
    assert two.payload is None
    assert two.withheld_reason == "restricted"

    second = await open_calibration_sample(
        scope=scope,
        outcomes=outcomes,
        rubric=RUBRIC,
        hitl=hitl,
        clock=Clock(),
        config=cfg,
        samples=sink,
        dataset=dataset,
    )
    assert second.opened == ()
    assert second.already_open == 3
    assert sink.puts == 3


async def test_without_a_dataset_the_sample_has_no_payload() -> None:
    store = InMemoryEvaluationStore()
    scope = make_scope()
    outcome = make_outcome(1, 0.0)
    await open_calibration_sample(
        scope=scope,
        outcomes=[outcome],
        rubric=RUBRIC,
        hitl=build_hitl(),
        clock=Clock(),
        config=SampleConfig(),
        samples=store,
    )
    got = await store.get_calibration_sample(
        scope, FINANCE, dispute_subject_ref("commercial", "contoso", outcome)
    )
    assert got is not None
    assert got.payload is None
    assert got.payload_withheld is True
    assert got.dataset_id is None
    assert got.classification is None
