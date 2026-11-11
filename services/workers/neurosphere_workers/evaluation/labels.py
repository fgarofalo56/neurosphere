"""PRP-16 item 8: the calibration label loop through the HITL review queue.

Human labels for judge calibration come from reviewers, not from a labeling tool:

* :func:`open_calibration_sample` picks a seeded, stratified random sample of the PER-ITEM verdicts
  (``ItemOutcome``) of an offline run and opens one ``evaluation_dispute`` review item per sample.
* :class:`HitlLabelSource` (a ``LabelSource``) turns the decided items into ``HumanLabelRecord``s.

The items are the offline run's own, because calibration joins labels to the run's ``JudgedItem``s
by the DATASET item id (and dimension); stored ``EvaluationResult``s are per-group aggregates and
cannot be labelled item by item.

Semantics of an ``evaluation_dispute`` item: "the judge's verdict on this item is wrong".
Reviewers can only approve or reject, so REJECTED = the judge is correct (label = judge value) and
APPROVED = the judge is wrong (label = the inverted value, ``1 - judge``). Pending, assigned,
escalated, expired and unmatched items yield nothing.

Rules:

- Only BINARY verdicts are sampled: status ``scored``, value exactly 0.0 or 1.0, on a dimension of
  a rubric scaled 0..1, from a judge config (id and version), with a customer and domain.
  Abstentions, skips and other scales are never sampled: the inverse of such a value is not a
  label anyone could give.
- Strata are (judge config id, version, dimension) -- the item 4 calibration key. Each stratum is
  shuffled with ``random.Random(f"{seed}|{stratum}")`` and the strata are drawn round-robin, so a
  low per-call cap still covers every stratum and the same seed picks the same sample.
- The sample is drawn from the FULL eligible population and already-opened subjects are skipped
  afterwards, so re-running with the same seed over the same outcomes opens nothing new.
- Everything runs inside a caller-supplied server-derived ``IdentityScope``: an outcome whose
  customer or domain is outside it is never sampled or labelled. Items are opened in the
  outcome's own domain. Ids on an outcome are never authority.
- The review item's ``subject_ref`` binds the exact verdict shown: a digest over
  ``item_id|dimension|judge_config_id|judge_config_version|value``. A later run whose verdict
  differs gets a different subject, so a decision never inverts a verdict the reviewer did not see.
- ``HumanLabelRecord.item_id`` is the dataset item id, so labels join in ``calibrate``.

``HitlLabelSource.labels()`` is synchronous (the ``LabelSource`` protocol) while the HITL store is
async, so call ``await source.load()`` first; ``labels()`` serves that snapshot.
"""

from __future__ import annotations

import hashlib
import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, Protocol

from neurosphere_core.errors import InvalidSchemaError
from neurosphere_core.evaluation.calibration import HumanLabelRecord
from neurosphere_core.evaluation.registry import DatasetVersion, RubricVersion
from neurosphere_core.evaluation.samples import CalibrationSample, build_calibration_sample
from neurosphere_core.hitl import HitlService, ReviewItem
from neurosphere_core.paging.models import MAX_PAGE_SIZE
from neurosphere_core.scope import IdentityScope

from neurosphere_workers.evaluation.models import ItemOutcome

__all__ = [
    "DISPUTE_KIND",
    "CalibrationSampleSink",
    "DisputeCandidate",
    "HitlLabelSource",
    "SampleConfig",
    "SampleReport",
    "dispute_subject_ref",
    "eligible_candidates",
    "open_calibration_sample",
    "select_sample",
]

DISPUTE_KIND: Final = "evaluation_dispute"
_DEFAULT_MAX_PER_CALL: Final = 20
_DEFAULT_PER_STRATUM: Final = 10

type _Stratum = tuple[str, str, str]


@dataclass(frozen=True, slots=True)
class SampleConfig:
    """``seed`` makes the draw reproducible; ``max_per_call`` caps items opened in one call."""

    seed: int = 0
    max_per_call: int = _DEFAULT_MAX_PER_CALL
    per_stratum: int = _DEFAULT_PER_STRATUM

    def __post_init__(self) -> None:
        if self.max_per_call < 0 or self.per_stratum < 0:
            raise ValueError("sample caps must be non-negative")


@dataclass(frozen=True, slots=True)
class DisputeCandidate:
    outcome: ItemOutcome
    cloud: str
    customer_id: str
    domain_id: str
    judge_config_id: str
    judge_config_version: str
    judge_value: float

    @property
    def dimension(self) -> str:
        return self.outcome.dimension

    @property
    def stratum(self) -> _Stratum:
        return (self.judge_config_id, self.judge_config_version, self.dimension)

    @property
    def subject_ref(self) -> str:
        return dispute_subject_ref(self.cloud, self.customer_id, self.outcome)


@dataclass(frozen=True, slots=True)
class SampleReport:
    eligible: int
    """Binary judged outcomes in scope."""
    selected: int
    """Sample size drawn (before skipping those already opened)."""
    opened: tuple[str, ...]
    """Review item ids opened by this call."""
    already_open: int


def dispute_subject_ref(cloud: str, customer_id: str, outcome: ItemOutcome) -> str:
    """Deterministic canonical id of the exact verdict a dispute item is about.

    The digest covers the item, dimension, judge config id and version and the judged value, so
    a different verdict in a later run is a different subject.
    """
    basis = "|".join(
        (
            outcome.item_id,
            outcome.dimension,
            outcome.judge_config_id or "",
            outcome.judge_config_version or "",
            repr(outcome.value),
        )
    )
    digest = hashlib.sha256(basis.encode()).hexdigest()
    return f"{cloud}:{customer_id}:evaluation:dispute:{digest[:40]}"


def eligible_candidates(
    outcomes: Sequence[ItemOutcome], rubric: RubricVersion, scope: IdentityScope
) -> list[DisputeCandidate]:
    """Binary, scored, judge-attributed outcomes inside ``scope``, de-duplicated and ordered."""
    if rubric.scale_min != 0.0 or rubric.scale_max != 1.0:
        return []
    allowed = set(scope.allowed_domains)
    found: dict[str, DisputeCandidate] = {}
    for outcome in outcomes:
        if (
            outcome.status != "scored"
            or outcome.value not in (0.0, 1.0)
            or outcome.value is None
            or outcome.dimension not in rubric.dimensions
            or not outcome.judge_config_id
            or not outcome.judge_config_version
            or not outcome.customer_id
            or not outcome.domain_id
        ):
            continue
        if outcome.customer_id != scope.customer_id or outcome.domain_id not in allowed:
            continue
        cand = DisputeCandidate(
            outcome,
            scope.cloud,
            outcome.customer_id,
            outcome.domain_id,
            outcome.judge_config_id,
            outcome.judge_config_version,
            outcome.value,
        )
        found.setdefault(cand.subject_ref, cand)
    return [found[ref] for ref in sorted(found)]


def select_sample(
    outcomes: Sequence[ItemOutcome],
    rubric: RubricVersion,
    scope: IdentityScope,
    config: SampleConfig,
) -> tuple[tuple[DisputeCandidate, ...], int]:
    """Pure draw: ``(sample, eligible count)``. Round-robin over strata, seeded per stratum."""
    strata: dict[_Stratum, list[DisputeCandidate]] = {}
    for cand in eligible_candidates(outcomes, rubric, scope):
        strata.setdefault(cand.stratum, []).append(cand)
    eligible = sum(len(v) for v in strata.values())
    drawn: dict[_Stratum, list[DisputeCandidate]] = {}
    for stratum in sorted(strata):
        pool = list(strata[stratum])
        rng = random.Random(f"{config.seed}|{'|'.join(stratum)}")  # noqa: S311 - not security
        rng.shuffle(pool)
        drawn[stratum] = pool[: config.per_stratum]
    sample: list[DisputeCandidate] = []
    depth = 0
    while len(sample) < config.max_per_call and any(len(v) > depth for v in drawn.values()):
        for stratum in sorted(drawn):
            if len(sample) >= config.max_per_call:
                break
            if len(drawn[stratum]) > depth:
                sample.append(drawn[stratum][depth])
        depth += 1
    return tuple(sample), eligible


async def _dispute_items(scope: IdentityScope, hitl: HitlService) -> list[ReviewItem]:
    items: list[ReviewItem] = []
    for domain in sorted(set(scope.allowed_domains)):
        cursor: str | None = None
        while True:
            page = await hitl.store.list(
                scope, domain, kind=DISPUTE_KIND, cursor=cursor, limit=MAX_PAGE_SIZE
            )
            items.extend(page.items)
            cursor = page.next_cursor
            if cursor is None:
                break
    return items


async def open_calibration_sample(
    *,
    scope: IdentityScope,
    outcomes: Sequence[ItemOutcome],
    rubric: RubricVersion,
    hitl: HitlService,
    clock: Callable[[], datetime],
    config: SampleConfig,
    correlation_id: str = "evaluation-calibration-sample",
    samples: CalibrationSampleSink | None = None,
    dataset: DatasetVersion | None = None,
) -> SampleReport:
    """Draw the sample and open one ``evaluation_dispute`` item per not-yet-opened verdict.

    ``samples`` (optional) records one :class:`CalibrationSample` per NEWLY opened item, so a
    reviewer sees the item and verdict, not a hash. ``dataset`` supplies the dataset id/version, the
    item classification and the redacted payload; without it the sample has no dataset ids, a null
    classification and therefore NO payload (fail closed).
    """
    sample, eligible = select_sample(outcomes, rubric, scope, config)
    dataset_items = (
        {(i.item_id, i.dimension): i for i in dataset.items} if dataset is not None else {}
    )
    existing = {item.subject_ref for item in await _dispute_items(scope, hitl)}
    now = clock()
    opened: list[str] = []
    already = 0
    for cand in sample:
        if cand.subject_ref in existing:
            already += 1
            continue
        item = await hitl.open_item(
            kind=DISPUTE_KIND,
            customer_id=cand.customer_id,
            domain_id=cand.domain_id,
            subject_ref=cand.subject_ref,
            now=now,
            correlation_id=correlation_id,
            scope_hash=scope.scope_hash,
        )
        existing.add(item.subject_ref)
        opened.append(item.item_id)
        if samples is not None:
            source = dataset_items.get((cand.outcome.item_id, cand.dimension))
            await samples.put_calibration_sample(
                build_calibration_sample(
                    subject_ref=cand.subject_ref,
                    cloud=cand.cloud,  # type: ignore[arg-type]
                    customer_id=cand.customer_id,
                    domain_id=cand.domain_id,
                    dataset_id=dataset.dataset_id if dataset is not None else None,
                    dataset_version=dataset.version if dataset is not None else None,
                    item_id=cand.outcome.item_id,
                    dimension=cand.dimension,
                    classification=source.classification if source is not None else None,
                    judge_config_id=cand.judge_config_id,
                    judge_config_version=cand.judge_config_version,
                    value=cand.judge_value,
                    rubric_id=rubric.rubric_id,
                    rubric_version=rubric.version,
                    opened_at=now,
                    payload=source.payload if source is not None else None,
                )
            )
    return SampleReport(
        eligible=eligible, selected=len(sample), opened=tuple(opened), already_open=already
    )


class CalibrationSampleSink(Protocol):
    """Where :func:`open_calibration_sample` records review context (an ``EvaluationStore``)."""

    async def put_calibration_sample(self, sample: CalibrationSample) -> None: ...


class HitlLabelSource:
    """``LabelSource`` over decided ``evaluation_dispute`` items. Call :meth:`load` first.

    ``outcomes`` are the per-item outcomes of the CURRENT offline run: a decided item whose
    verdict is not (any longer) among them is counted in :attr:`unmatched` and yields no label.
    """

    def __init__(
        self,
        *,
        scope: IdentityScope,
        outcomes: Sequence[ItemOutcome],
        rubric: RubricVersion,
        hitl: HitlService,
    ) -> None:
        self._scope = scope
        self._outcomes = tuple(outcomes)
        self._rubric = rubric
        self._hitl = hitl
        self._records: tuple[HumanLabelRecord, ...] = ()
        self._unmatched = 0

    @property
    def label_set_version(self) -> str | None:
        return self._records[0].label_set_version if self._records else None

    @property
    def unmatched(self) -> int:
        """Decided items (approved/rejected) that map to no verdict of the current run."""
        return self._unmatched

    async def load(self) -> HitlLabelSource:
        index = {
            cand.subject_ref: cand
            for cand in eligible_candidates(self._outcomes, self._rubric, self._scope)
        }
        decided: list[tuple[ReviewItem, DisputeCandidate, float, str, datetime]] = []
        unmatched = 0
        for item in await _dispute_items(self._scope, self._hitl):
            if item.state_name not in ("approved", "rejected") or item.decision_id is None:
                continue
            decision = next(
                (
                    d
                    for d in await self._hitl.decisions(item.item_id)
                    if d.decision_id.root == item.decision_id
                ),
                None,
            )
            if decision is None or decision.decision not in ("approved", "rejected"):
                continue
            cand = index.get(item.subject_ref)
            if cand is None:
                unmatched += 1
                continue
            value = cand.judge_value if decision.decision == "rejected" else 1.0 - cand.judge_value
            decided.append(
                (item, cand, value, decision.reviewer.principal_pseudonym, _decided_at(item))
            )
        self._unmatched = unmatched
        version = _label_set_version([item.item_id for item, *_ in decided])
        self._records = tuple(
            HumanLabelRecord(
                item_id=cand.outcome.item_id,
                dimension=cand.dimension,  # type: ignore[arg-type]
                label_set_version=version,
                value=value,
                labeler=labeler,
                labelled_at=at,
            )
            for item, cand, value, labeler, at in sorted(decided, key=lambda d: d[0].item_id)
        )
        return self

    def labels(self) -> tuple[HumanLabelRecord, ...]:
        return self._records


def _decided_at(item: ReviewItem) -> datetime:
    if item.decided_at is None:
        raise InvalidSchemaError(
            "decided review item has no decided_at", reason="invalid_review_item"
        )
    return item.decided_at.astimezone(UTC)


def _label_set_version(item_ids: list[str]) -> str:
    digest = hashlib.sha256("\n".join(sorted(item_ids)).encode()).hexdigest()
    return f"hitl-{digest[:16]}"
