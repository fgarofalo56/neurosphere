"""PRP-16 item 8: the calibration label loop through the HITL review queue.

Human labels for judge calibration come from reviewers, not from a labeling tool:

* :func:`open_calibration_sample` picks a seeded, stratified random sample of STORED judged
  results and opens one ``evaluation_dispute`` review item per sampled result.
* :class:`HitlLabelSource` (a ``LabelSource``) turns the decided items into ``HumanLabelRecord``s.

Semantics of an ``evaluation_dispute`` item: "the judge's verdict on this result is wrong".
Reviewers can only approve or reject, so REJECTED = the judge is correct (label = judge value) and
APPROVED = the judge is wrong (label = the inverted value, ``1 - judge``). Pending, assigned,
escalated and expired items yield nothing.

Rules:

- Only BINARY verdicts are sampled: a score on a 0..1 scale whose value is exactly 0 or 1 from a
  judge with a model config (``judge_config_key``). Abstentions (``value is None``), aggregates
  such as 0.82 and other scales are never sampled, because the inverse of such a value is not a
  label anyone could give.
- Strata are (judge config id, version, dimension) -- the item 4 calibration key. Each stratum is
  shuffled with ``random.Random(f"{seed}|{stratum}")`` and the strata are drawn round-robin, so a
  low per-call cap still covers every stratum and the same seed picks the same sample.
- The sample is drawn from the FULL eligible population and already-opened results are skipped
  afterwards, so re-running with the same seed over the same results opens nothing new.
- Everything runs inside a caller-supplied server-derived ``IdentityScope``; results outside it
  are never read. Items are opened in the result's own domain.
- ``HumanLabelRecord.item_id`` is the evaluation id and the dimension is the sampled one. The
  review item's ``subject_ref`` is a deterministic canonical id derived from (evaluation id,
  dimension): evaluation ids may contain ``:`` which the canonical-id grammar forbids in the last
  segment, so the ref carries a digest and the label source resolves it through the result store.

``HitlLabelSource.labels()`` is synchronous (the ``LabelSource`` protocol), the HITL and evaluation
stores are async, so call ``await source.load()`` first; ``labels()`` serves that snapshot.
"""

from __future__ import annotations

import hashlib
import random
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

from neurosphere_contracts.evaluation.v1.evaluation_result import EvaluationResult
from neurosphere_core.errors import InvalidSchemaError
from neurosphere_core.evaluation.calibration import HumanLabelRecord
from neurosphere_core.evaluation.store import EvaluationStore, judge_config_key
from neurosphere_core.hitl import HitlService, ReviewItem
from neurosphere_core.paging.models import MAX_PAGE_SIZE
from neurosphere_core.scope import IdentityScope

__all__ = [
    "DISPUTE_KIND",
    "DisputeCandidate",
    "HitlLabelSource",
    "SampleConfig",
    "SampleReport",
    "dispute_subject_ref",
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
    result: EvaluationResult
    dimension: str
    judge_value: float
    stratum: _Stratum

    @property
    def subject_ref(self) -> str:
        return dispute_subject_ref(self.result, self.dimension)


@dataclass(frozen=True, slots=True)
class SampleReport:
    eligible: int
    """Binary judged results in scope."""
    selected: int
    """Sample size drawn (before skipping those already opened)."""
    opened: tuple[str, ...]
    """Review item ids opened by this call."""
    already_open: int


def dispute_subject_ref(result: EvaluationResult, dimension: str) -> str:
    """Deterministic canonical id of the (result, dimension) a dispute item is about."""
    digest = hashlib.sha256(f"{result.evaluation_id.root}|{dimension}".encode()).hexdigest()
    return f"{result.cloud}:{result.customer_id}:evaluation:dispute:{digest[:40]}"


def _binary_candidates(result: EvaluationResult) -> list[DisputeCandidate]:
    key = judge_config_key(result.judge)
    if key is None:
        return []
    found: list[DisputeCandidate] = []
    for score in result.scores:
        if score.value is None or score.scale.min != 0.0 or score.scale.max != 1.0:
            continue
        if score.value not in (0.0, 1.0):
            continue
        found.append(
            DisputeCandidate(result, score.dimension, score.value, (*key, score.dimension))
        )
    return found


def select_sample(
    results: list[EvaluationResult], config: SampleConfig
) -> tuple[tuple[DisputeCandidate, ...], int]:
    """Pure draw: ``(sample, eligible count)``. Round-robin over strata, seeded per stratum."""
    strata: dict[_Stratum, list[DisputeCandidate]] = {}
    for result in sorted(results, key=lambda r: r.evaluation_id.root):
        for cand in _binary_candidates(result):
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


async def _scoped_results(scope: IdentityScope, store: EvaluationStore) -> list[EvaluationResult]:
    found: list[EvaluationResult] = []
    for domain in sorted(set(scope.allowed_domains)):
        for result in await store.results(scope, domain):
            # The store already filters; re-check so a faulty store cannot widen the scope.
            if result.cloud == scope.cloud and result.customer_id == scope.customer_id:
                found.append(result)
    return found


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
    store: EvaluationStore,
    hitl: HitlService,
    clock: Callable[[], datetime],
    config: SampleConfig,
    correlation_id: str = "evaluation-calibration-sample",
) -> SampleReport:
    """Draw the sample and open one ``evaluation_dispute`` item per not-yet-opened result."""
    results = await _scoped_results(scope, store)
    sample, eligible = select_sample(results, config)
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
            customer_id=cand.result.customer_id,
            domain_id=cand.result.domain_id.root,
            subject_ref=cand.subject_ref,
            now=now,
            correlation_id=correlation_id,
            scope_hash=scope.scope_hash,
        )
        existing.add(item.subject_ref)
        opened.append(item.item_id)
    return SampleReport(
        eligible=eligible, selected=len(sample), opened=tuple(opened), already_open=already
    )


class HitlLabelSource:
    """``LabelSource`` over decided ``evaluation_dispute`` items. Call :meth:`load` first."""

    def __init__(self, *, scope: IdentityScope, store: EvaluationStore, hitl: HitlService) -> None:
        self._scope = scope
        self._store = store
        self._hitl = hitl
        self._records: tuple[HumanLabelRecord, ...] = ()

    @property
    def label_set_version(self) -> str | None:
        return self._records[0].label_set_version if self._records else None

    async def load(self) -> HitlLabelSource:
        index: dict[str, tuple[EvaluationResult, str, float]] = {}
        for result in await _scoped_results(self._scope, self._store):
            for cand in _binary_candidates(result):
                index[cand.subject_ref] = (result, cand.dimension, cand.judge_value)
        decided: list[tuple[ReviewItem, str, float, str, datetime]] = []
        for item in await _dispute_items(self._scope, self._hitl):
            if item.state_name not in ("approved", "rejected") or item.decision_id is None:
                continue
            hit = index.get(item.subject_ref)
            decision = next(
                (
                    d
                    for d in await self._hitl.decisions(item.item_id)
                    if d.decision_id.root == item.decision_id
                ),
                None,
            )
            if hit is None or decision is None or decision.decision not in ("approved", "rejected"):
                continue
            result, dimension, judge_value = hit
            value = judge_value if decision.decision == "rejected" else 1.0 - judge_value
            decided.append(
                (item, dimension, value, decision.reviewer.principal_pseudonym, _decided_at(item))
            )
        version = _label_set_version([item.item_id for item, *_ in decided])
        self._records = tuple(
            HumanLabelRecord(
                item_id=index[item.subject_ref][0].evaluation_id.root,
                dimension=dimension,  # type: ignore[arg-type]
                label_set_version=version,
                value=value,
                labeler=labeler,
                labelled_at=at,
            )
            for item, dimension, value, labeler, at in sorted(decided, key=lambda d: d[0].item_id)
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
