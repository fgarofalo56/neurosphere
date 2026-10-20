"""The sampling worker service (PRP-16 item 2): online archive sampling and offline benchmarks.

``EvaluationService`` is a plain async API; hosting it in the PRP-05 worker runtime is OPEN. Both
modes share one evaluation loop: every selected item passes the pre-call guard (``guard``) and a
worst-case budget reservation (``budget``) BEFORE the judge is called. A denied reservation stops
the run with status ``budget_exhausted`` and the coverage achieved; remaining selected items are
reported as ``unevaluated``, never dropped. Nothing here makes a network call: the ``Judge`` is
injected (recorded fixtures in CI).
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Final

from neurosphere_core.capabilities import CapabilityMatrix
from neurosphere_core.errors import InvalidSchemaError
from neurosphere_core.evaluation.calibration import CalibrationReport, JudgedItem
from neurosphere_core.evaluation.judge import (
    Judge,
    JudgeRequest,
    JudgeResponse,
    MissingFixtureError,
)
from neurosphere_core.evaluation.registry import (
    Cloud,
    DatasetVersion,
    Dimension,
    EvaluationRegistryProtocol,
    JudgeConfig,
    RubricVersion,
)
from pydantic import ValidationError

from neurosphere_workers.evaluation.budget import (
    DEFAULT_PROMPT_OVERHEAD_TOKENS,
    BudgetDenial,
    BudgetLedger,
    Reservation,
    estimate_input_tokens,
    price_call,
)
from neurosphere_workers.evaluation.guard import check_candidate
from neurosphere_workers.evaluation.models import (
    REASON_FIXTURE_MISSING,
    REASON_INVALID_VALUE,
    REASON_JUDGE_ERROR,
    Candidate,
    GroupPopulation,
    ItemOutcome,
    JudgeUsage,
    Mode,
    RunReport,
    RunStatus,
    SamplingCoverage,
)
from neurosphere_workers.evaluation.online import ONLINE_LIMITED_DIMENSIONS, candidate_from_record
from neurosphere_workers.evaluation.results import build_results
from neurosphere_workers.evaluation.sampling import SampleResult, stratified_sample
from neurosphere_workers.evaluation.source import RecordSource

__all__ = [
    "REASON_BUDGET_EXHAUSTED",
    "REASON_INVALID_REQUEST",
    "EvaluationService",
    "OfflineRunConfig",
    "OnlineRunConfig",
]

REASON_BUDGET_EXHAUSTED: Final = "budget_exhausted"
REASON_INVALID_REQUEST: Final = "invalid_request"
_RUN_ID: Final = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


@dataclass(frozen=True, kw_only=True)
class _RunBase:
    run_id: str
    cloud: Cloud
    rubric: RubricVersion
    judges: Mapping[Dimension, JudgeConfig]


@dataclass(frozen=True, kw_only=True)
class OnlineRunConfig(_RunBase):
    """Sampling-frame dataset (versioned), stratified rate and seed."""

    frame_dataset_id: str
    frame_dataset_version: str
    rate: float
    seed: int


@dataclass(frozen=True, kw_only=True)
class OfflineRunConfig(_RunBase):
    """Subject under test; ``domain_id`` and ``subject_id`` are canonical ids."""

    customer_id: str
    domain_id: str
    subject_id: str


def _default_clock() -> datetime:
    return datetime.now(UTC)


class EvaluationService:
    def __init__(
        self,
        *,
        judge: Judge,
        matrix: CapabilityMatrix,
        registry: EvaluationRegistryProtocol,
        ledger: BudgetLedger,
        clock: Callable[[], datetime] = _default_clock,
        prompt_overhead_tokens: int = DEFAULT_PROMPT_OVERHEAD_TOKENS,
    ) -> None:
        self._judge = judge
        self._matrix = matrix
        self._registry = registry
        self._ledger = ledger
        self._clock = clock
        self._overhead = prompt_overhead_tokens

    # --- entry points -------------------------------------------------------------------------

    async def run_online(
        self,
        source: RecordSource,
        config: OnlineRunConfig,
        *,
        calibrations: Iterable[CalibrationReport] = (),
    ) -> RunReport:
        """Stratified sample of redacted archive records; metadata-derivable dimensions only."""
        self._validate(config, config.frame_dataset_id, config.frame_dataset_version)
        started = self._clock()
        candidates: list[Candidate] = []
        excluded: Counter[str] = Counter()
        async for record in source.records():
            candidate, reason = candidate_from_record(record, config.cloud)
            if candidate is None:
                excluded[reason or "excluded"] += 1
            else:
                candidates.append(candidate)
        sample = stratified_sample(candidates, rate=config.rate, seed=config.seed)
        unique: dict[str, Candidate] = {}
        for cand in sorted(candidates, key=lambda c: c.item_id):
            unique.setdefault(cand.item_id, cand)  # de-duplicated exactly like the sampler
        populations = self._populations(unique.values())
        return await self._run(
            mode="online_sampled",
            config=config,
            dataset_id=config.frame_dataset_id,
            dataset_version=config.frame_dataset_version,
            data_state="redacted",
            started=started,
            sample=sample,
            population_total=sum(s.population for s in sample.strata),
            populations=populations,
            seed=config.seed,
            rate=config.rate,
            check_bodies=True,
            excluded=dict(excluded),
            limited=dict(ONLINE_LIMITED_DIMENSIONS),
            calibrations=calibrations,
        )

    async def run_offline(
        self,
        dataset: DatasetVersion,
        config: OfflineRunConfig,
        *,
        calibrations: Iterable[CalibrationReport] = (),
    ) -> RunReport:
        """Run every item of a registered dataset version through the same guards and budgets."""
        self._validate(config, dataset.dataset_id, dataset.version)
        stored = self._registry.datasets.get(dataset.dataset_id, dataset.version)
        if stored is None or stored.content_hash != dataset.content_hash:
            raise InvalidSchemaError(
                "dataset is not the registered version", reason="dataset_version_unregistered"
            )
        started = self._clock()
        domain = config.domain_id.rsplit(":", 1)[-1]
        candidates = [
            Candidate(
                item_id=item.item_id,
                domain=domain,
                agent=item.dimension,
                classification=item.classification,
                dimension=item.dimension,
                payload=dict(item.payload),
                customer_id=config.customer_id,
                domain_id=config.domain_id,
                subject_id=config.subject_id,
            )
            for item in dataset.items
        ]
        sample = stratified_sample(candidates, rate=1.0, seed=0)
        return await self._run(
            mode="offline_benchmark",
            config=config,
            dataset_id=dataset.dataset_id,
            dataset_version=dataset.version,
            data_state=dataset.data_state,
            started=started,
            sample=sample,
            population_total=len(candidates),
            populations=self._populations(candidates),
            seed=None,
            rate=None,
            # Synthetic benchmark payloads may legitimately contain a ``response`` field (safety
            # items); archive-derived data is always body-checked.
            check_bodies=dataset.data_state != "synthetic",
            excluded={},
            limited={},
            calibrations=calibrations,
        )

    def attach_calibrations(
        self, report: RunReport, calibrations: Iterable[CalibrationReport]
    ) -> RunReport:
        """Re-emit contract results once calibration reports exist for the run's judged items."""
        results, uncalibrated, unemitted = build_results(
            report, calibrations=calibrations, registry=self._registry
        )
        return report.model_copy(
            update={"results": results, "uncalibrated_judges": uncalibrated, "unemitted": unemitted}
        )

    # --- internals ----------------------------------------------------------------------------

    def _validate(self, config: _RunBase, dataset_id: str, dataset_version: str) -> None:
        if not _RUN_ID.match(config.run_id):
            raise InvalidSchemaError("run_id is not a valid id", reason="invalid_run_id")
        if self._registry.datasets.get(dataset_id, dataset_version) is None:
            raise InvalidSchemaError(
                "dataset version is not registered", reason="dataset_version_unregistered"
            )
        if self._registry.rubrics.get(config.rubric.rubric_id, config.rubric.version) is None:
            raise InvalidSchemaError(
                "rubric version is not registered", reason="rubric_version_unregistered"
            )
        for judge in config.judges.values():
            if self._registry.judge_configs.get(judge.judge_config_id, judge.version) is None:
                raise InvalidSchemaError(
                    "judge config version is not registered", reason="judge_config_unregistered"
                )

    @staticmethod
    def _populations(candidates: Iterable[Candidate]) -> tuple[GroupPopulation, ...]:
        counts: Counter[tuple[str | None, str | None, str | None, Dimension]] = Counter()
        for c in candidates:
            counts[(c.customer_id, c.domain_id, c.subject_id, c.dimension)] += 1
        return tuple(
            GroupPopulation(
                customer_id=k[0], domain_id=k[1], subject_id=k[2], dimension=k[3], population=n
            )
            for k, n in sorted(counts.items(), key=lambda kv: tuple(str(p) for p in kv[0]))
        )

    async def _run(
        self,
        *,
        mode: Mode,
        config: _RunBase,
        dataset_id: str,
        dataset_version: str,
        data_state: str,
        started: datetime,
        sample: SampleResult,
        population_total: int,
        populations: tuple[GroupPopulation, ...],
        seed: int | None,
        rate: float | None,
        check_bodies: bool,
        excluded: dict[str, int],
        limited: dict[str, str],
        calibrations: Iterable[CalibrationReport],
    ) -> RunReport:
        self._ledger.begin_run()
        outcomes: list[ItemOutcome] = []
        stop: str | None = None
        for cand in sample.selected:
            if stop is not None:
                outcomes.append(self._outcome(cand, "unevaluated", REASON_BUDGET_EXHAUSTED, stop))
                continue
            outcome, stop = await self._evaluate_one(cand, config, check_bodies)
            outcomes.append(outcome)

        skip_counts: Counter[str] = Counter(
            o.reason or "unknown" for o in outcomes if o.status in ("skipped", "unevaluated")
        )
        evaluated = sum(1 for o in outcomes if o.status in ("scored", "abstained"))
        unevaluated = sum(1 for o in outcomes if o.status == "unevaluated")
        status: RunStatus = "completed"
        if stop is not None:
            status = "budget_exhausted"
        elif any(o.status in ("skipped", "abstained") for o in outcomes):
            status = "partial"
        completed = self._clock()
        configs = tuple(
            sorted(config.judges.values(), key=lambda c: (c.judge_config_id, c.version))
        )
        report = RunReport(
            run_id=config.run_id,
            mode=mode,
            cloud=config.cloud,
            status=status,
            started_at=started,
            completed_at=max(completed, started),
            seed=seed,
            rate=rate,
            dataset_id=dataset_id,
            dataset_version=dataset_version,
            data_state=data_state,  # type: ignore[arg-type]  # validated by the callers above
            rubric=config.rubric,
            judge_configs=configs,
            population_total=population_total,
            sampled_total=len(sample.selected),
            evaluated_total=evaluated,
            unevaluated_total=unevaluated,
            budget_exhausted_reason=stop,
            skip_counts=dict(skip_counts),
            excluded_counts=excluded,
            coverage=self._coverage(sample, outcomes),
            group_populations=populations,
            outcomes=tuple(outcomes),
            judged_items=self._judged(outcomes),
            usage=self._usage(outcomes, configs),
            limited_dimensions=limited,
        )
        return self.attach_calibrations(report, calibrations)

    async def _evaluate_one(
        self, cand: Candidate, config: _RunBase, check_bodies: bool
    ) -> tuple[ItemOutcome, str | None]:
        """``(outcome, stop reason)``; a stop reason ends the run."""
        decision = check_candidate(
            cand,
            judges=config.judges,
            matrix=self._matrix,
            cloud=config.cloud,
            check_bodies=check_bodies,
        )
        judge_config = decision.config
        if judge_config is None:
            return self._outcome(cand, "skipped", decision.reason, decision.detail), None

        try:
            request = JudgeRequest(
                judge_config_id=judge_config.judge_config_id,
                judge_config_version=judge_config.version,
                rubric_id=config.rubric.rubric_id,
                rubric_version=config.rubric.version,
                dimension=cand.dimension,
                item_id=cand.item_id,
                classification=cand.classification,
                payload=cand.payload,
            )
        except ValidationError:
            return self._outcome(
                cand, "skipped", REASON_INVALID_REQUEST, "judge request failed validation"
            ), None

        if judge_config.judge_kind == "programmatic":
            tokens_in, tokens_out = 0, 0
        else:
            tokens_in = estimate_input_tokens(request, self._overhead)
            tokens_out = judge_config.max_output_tokens
        worst_cost = price_call(judge_config, tokens_in, tokens_out)
        reservation = self._ledger.reserve(cand.domain, tokens_in + tokens_out, worst_cost)
        if isinstance(reservation, BudgetDenial):
            code = f"{reservation.code}:{reservation.domain}"
            return self._outcome(cand, "unevaluated", REASON_BUDGET_EXHAUSTED, code), code

        return await self._call(cand, judge_config, request, reservation, config.rubric), None

    async def _call(
        self,
        cand: Candidate,
        judge_config: JudgeConfig,
        request: JudgeRequest,
        reservation: Reservation,
        rubric: RubricVersion,
    ) -> ItemOutcome:
        try:
            response: JudgeResponse = await self._judge.score(request)
        except MissingFixtureError:
            self._ledger.release(reservation)  # nothing was sent anywhere
            return self._outcome(
                cand, "skipped", REASON_FIXTURE_MISSING, "no recorded fixture", judge_config
            )
        except Exception:
            # The spend is unknown, so charge the worst case rather than under-count.
            self._ledger.settle(reservation, reservation.tokens, reservation.cost)
            return self._outcome(
                cand, "skipped", REASON_JUDGE_ERROR, "judge call failed", judge_config
            )

        actual_in, actual_out = response.input_tokens, response.output_tokens
        cost = price_call(judge_config, actual_in, actual_out)
        self._ledger.settle(reservation, actual_in + actual_out, cost)
        usage = {"input_tokens": actual_in, "output_tokens": actual_out, "cost": cost}
        length = len(json.dumps(cand.payload, sort_keys=True))
        if response.abstained or response.value is None:
            return self._outcome(
                cand, "abstained", None, "judge abstained", judge_config, length=length, **usage
            )
        if not rubric.scale_min <= response.value <= rubric.scale_max:
            return self._outcome(
                cand,
                "skipped",
                REASON_INVALID_VALUE,
                "judge value outside the rubric scale",
                judge_config,
                length=length,
                **usage,
            )
        return self._outcome(
            cand,
            "scored",
            None,
            None,
            judge_config,
            value=float(response.value),
            length=length,
            **usage,
        )

    @staticmethod
    def _outcome(
        cand: Candidate,
        status: str,
        reason: str | None,
        detail: str | None,
        judge_config: JudgeConfig | None = None,
        *,
        value: float | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        cost: Decimal | None = None,
        length: int | None = None,
    ) -> ItemOutcome:
        return ItemOutcome(
            item_id=cand.item_id,
            stratum=cand.stratum,
            domain=cand.domain,
            customer_id=cand.customer_id,
            domain_id=cand.domain_id,
            subject_id=cand.subject_id,
            dimension=cand.dimension,
            status=status,  # type: ignore[arg-type]
            reason=reason,
            detail=detail,
            judge_config_id=None if judge_config is None else judge_config.judge_config_id,
            judge_config_version=None if judge_config is None else judge_config.version,
            value=value,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost=cost,
            response_length=length,
            event_time=cand.event_time,
        )

    @staticmethod
    def _coverage(
        sample: SampleResult, outcomes: Sequence[ItemOutcome]
    ) -> tuple[SamplingCoverage, ...]:
        evaluated: Counter[str] = Counter()
        skipped: Counter[str] = Counter()
        for o in outcomes:
            if o.status in ("scored", "abstained"):
                evaluated[o.stratum] += 1
            elif o.status == "skipped":
                skipped[o.stratum] += 1
        return tuple(
            SamplingCoverage(
                stratum=s.stratum,
                population=s.population,
                sampled=s.sampled,
                evaluated=evaluated[s.stratum],
                skipped=skipped[s.stratum],
                sampled_fraction=s.fraction,
                evaluated_fraction=(evaluated[s.stratum] / s.population) if s.population else None,
            )
            for s in sample.strata
        )

    @staticmethod
    def _judged(outcomes: Sequence[ItemOutcome]) -> tuple[JudgedItem, ...]:
        return tuple(
            JudgedItem(
                item_id=o.item_id,
                stratum=o.stratum,
                dimension=o.dimension,
                judge_config_id=o.judge_config_id,
                judge_config_version=o.judge_config_version,
                score=o.value,
                response_length=o.response_length,
            )
            for o in outcomes
            if o.status in ("scored", "abstained")
            and o.judge_config_id is not None
            and o.judge_config_version is not None
        )

    @staticmethod
    def _usage(
        outcomes: Sequence[ItemOutcome], configs: Sequence[JudgeConfig]
    ) -> tuple[JudgeUsage, ...]:
        totals: dict[tuple[str, str], list[int | Decimal]] = defaultdict(
            lambda: [0, 0, 0, Decimal(0)]
        )
        for o in outcomes:
            if o.judge_config_id is None or o.input_tokens is None:
                continue
            row = totals[(o.judge_config_id, o.judge_config_version or "")]
            row[0] = int(row[0]) + 1
            row[1] = int(row[1]) + o.input_tokens
            row[2] = int(row[2]) + (o.output_tokens or 0)
            row[3] = Decimal(row[3]) + (o.cost or Decimal(0))
        prices = {(c.judge_config_id, c.version): c.price_version for c in configs}
        return tuple(
            JudgeUsage(
                judge_config_id=key[0],
                judge_config_version=key[1],
                calls=int(row[0]),
                input_tokens=int(row[1]),
                output_tokens=int(row[2]),
                estimated_cost=Decimal(row[3]),
                price_version=prices.get(key),
            )
            for key, row in sorted(totals.items())
        )
