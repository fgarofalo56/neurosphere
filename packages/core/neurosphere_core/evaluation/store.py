"""Evaluation store protocol and the in-memory implementation (PRP-16 item 4).

Holds four kinds of records, all addressed by cloud, customer and domain:

* ``EvaluationResult`` -- immutable. Putting the same document again is a no-op; putting a
  different document under an existing ``evaluation_id`` raises ``EvaluationConflictError``.
  Results are never mutated, so old results stay queryable.
* ``CalibrationReport`` (item 3) per judge config id + version + dimension.
* ``DriftAlert`` (item 3).
* ``SamplingCoverage`` per run and stratum, written by the worker pipeline (item 6).

Every read takes the server-derived ``IdentityScope`` plus the addressed domain. Customer, cloud and
the domain (which must be in the scope's allowed domains) are mandatory predicates: other scopes'
data is simply absent. A Cosmos implementation is OPEN (not built here).
"""

from __future__ import annotations

import base64
import binascii
from collections.abc import Iterable
from datetime import datetime
from typing import Final, Literal, Protocol, runtime_checkable

from neurosphere_contracts.evaluation.v1.evaluation_result import EvaluationResult, Judge
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from neurosphere_core.errors import InvalidSchemaError, StaleVersionError
from neurosphere_core.evaluation.calibration import CalibrationReport, DriftAlert
from neurosphere_core.paging import Page
from neurosphere_core.paging.models import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from neurosphere_core.scope import IdentityScope

__all__ = [
    "EvaluationConflictError",
    "EvaluationStore",
    "InMemoryEvaluationStore",
    "SamplingCoverage",
    "judge_config_key",
]

Cloud = Literal["commercial", "government"]
_ID: Final = r"^[A-Za-z0-9][A-Za-z0-9._:/=-]{0,255}$"


class EvaluationConflictError(StaleVersionError):
    """A different result already exists under this ``evaluation_id`` (results are immutable)."""


class SamplingCoverage(BaseModel):
    """Sampling coverage of one stratum in one run. ``None`` means unknown, never 0."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    cloud: Cloud
    customer_id: str = Field(pattern=r"^[a-z0-9._-]{1,128}$")
    domain_id: str = Field(min_length=1, max_length=512)
    run_id: str = Field(pattern=_ID)
    stratum: str = Field(min_length=1, max_length=128)
    sampled: int = Field(ge=0)
    population: int | None = Field(default=None, ge=0)
    coverage_fraction: float | None = Field(default=None, ge=0.0, le=1.0)
    recorded_at: AwareDatetime


def judge_config_key(judge: Judge) -> tuple[str, str] | None:
    """The (judge config id, version) a stored ``CalibrationReport`` is keyed by.

    id = ``judge_model_id``; version = ``<judge_model_version>+<judge_prompt_version>``. ``None``
    for judges without a model (human, programmatic): there is nothing to calibrate.
    """
    if (
        judge.judge_model_id is None
        or judge.judge_model_version is None
        or judge.judge_prompt_version is None
    ):
        return None
    return (
        judge.judge_model_id.root,
        f"{judge.judge_model_version.root}+{judge.judge_prompt_version.root}",
    )


@runtime_checkable
class EvaluationStore(Protocol):
    async def put_result(self, result: EvaluationResult) -> None:
        """Idempotent insert keyed by ``evaluation_id``; a differing re-put is a conflict."""
        ...

    async def put_calibration(
        self, cloud: Cloud, customer_id: str, domain_id: str, report: CalibrationReport
    ) -> None:
        """Upsert keyed by judge config id + version + dimension (the newest report wins)."""
        ...

    async def put_drift_alert(
        self, cloud: Cloud, customer_id: str, domain_id: str, alert: DriftAlert
    ) -> None: ...

    async def put_coverage(self, coverage: SamplingCoverage) -> None:
        """Upsert keyed by run id + stratum."""
        ...

    async def list_results(
        self,
        scope: IdentityScope,
        domain: str,
        subject_id: str | None = None,
        dimension: str | None = None,
        cursor: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> Page[EvaluationResult]:
        """One page of the scope's results in ``domain``, ordered by id."""
        ...

    async def results(
        self, scope: IdentityScope, domain: str, subject_id: str | None = None
    ) -> tuple[EvaluationResult, ...]:
        """All of the scope's results in ``domain`` (ordered by id) for aggregation."""
        ...

    async def calibrations(
        self, scope: IdentityScope, domain: str
    ) -> tuple[CalibrationReport, ...]: ...

    async def drift_alerts(
        self, scope: IdentityScope, domain: str, subject_id: str | None = None
    ) -> tuple[DriftAlert, ...]: ...

    async def coverage(self, scope: IdentityScope, domain: str) -> tuple[SamplingCoverage, ...]:
        """The latest record per stratum (by ``recorded_at``), ordered by stratum."""
        ...


def _in_scope(scope: IdentityScope, domain: str, cloud: str, customer: str, dom: str) -> bool:
    return (
        customer == scope.customer_id
        and cloud == scope.cloud
        and domain in scope.allowed_domains
        and dom == domain
    )


def _visible(scope: IdentityScope, domain: str, result: EvaluationResult) -> bool:
    return _in_scope(scope, domain, result.cloud, result.customer_id, result.domain_id.root)


def _encode_cursor(last_id: str) -> str:
    return base64.urlsafe_b64encode(last_id.encode("utf-8")).decode("ascii")


def _decode_cursor(cursor: str) -> str:
    try:
        return base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
    except (binascii.Error, UnicodeError, ValueError):
        raise InvalidSchemaError("invalid cursor", reason="invalid_cursor") from None


type _Key = tuple[str, str, str]


class InMemoryEvaluationStore:
    def __init__(self, results: Iterable[EvaluationResult] = ()) -> None:
        self._results: dict[str, EvaluationResult] = {}
        self._calibrations: dict[tuple[_Key, str | None, str | None, str], CalibrationReport] = {}
        self._alerts: dict[tuple[_Key, str, str, str], DriftAlert] = {}
        self._coverage: dict[tuple[_Key, str, str], SamplingCoverage] = {}
        for result in results:
            self._put_result(result)

    def _put_result(self, result: EvaluationResult) -> None:
        key = result.evaluation_id.root
        existing = self._results.get(key)
        if existing is None:
            self._results[key] = result.model_copy(deep=True)
        elif existing != result:
            raise EvaluationConflictError(
                "a different evaluation result already exists under this id",
                reason="evaluation_conflict",
            )

    async def put_result(self, result: EvaluationResult) -> None:
        self._put_result(result)

    async def put_calibration(
        self, cloud: Cloud, customer_id: str, domain_id: str, report: CalibrationReport
    ) -> None:
        key = (
            (cloud, customer_id, domain_id),
            report.judge_config_id,
            report.judge_config_version,
            report.dimension,
        )
        current = self._calibrations.get(key)
        if current is None or report.calibrated_at >= current.calibrated_at:
            self._calibrations[key] = report.model_copy(deep=True)

    async def put_drift_alert(
        self, cloud: Cloud, customer_id: str, domain_id: str, alert: DriftAlert
    ) -> None:
        key = (
            (cloud, customer_id, domain_id),
            alert.dimension,
            alert.subject_id,
            alert.detected_at,
        )
        self._alerts[key] = alert.model_copy(deep=True)

    async def put_coverage(self, coverage: SamplingCoverage) -> None:
        key = (
            (coverage.cloud, coverage.customer_id, coverage.domain_id),
            coverage.run_id,
            coverage.stratum,
        )
        self._coverage[key] = coverage.model_copy(deep=True)

    async def list_results(
        self,
        scope: IdentityScope,
        domain: str,
        subject_id: str | None = None,
        dimension: str | None = None,
        cursor: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> Page[EvaluationResult]:
        if not 1 <= limit <= MAX_PAGE_SIZE:
            raise InvalidSchemaError(f"limit must be 1..{MAX_PAGE_SIZE}", reason="invalid_limit")
        after = _decode_cursor(cursor) if cursor else None
        rows = [
            r
            for rid, r in sorted(self._results.items())
            if (after is None or rid > after)
            and _visible(scope, domain, r)
            and (subject_id is None or r.subject_id.root == subject_id)
            and (dimension is None or any(s.dimension == dimension for s in r.scores))
        ]
        page = rows[:limit]
        next_cursor = _encode_cursor(page[-1].evaluation_id.root) if len(rows) > limit else None
        return Page[EvaluationResult](
            items=tuple(r.model_copy(deep=True) for r in page), next_cursor=next_cursor
        )

    async def results(
        self, scope: IdentityScope, domain: str, subject_id: str | None = None
    ) -> tuple[EvaluationResult, ...]:
        return tuple(
            r.model_copy(deep=True)
            for _, r in sorted(self._results.items())
            if _visible(scope, domain, r)
            and (subject_id is None or r.subject_id.root == subject_id)
        )

    async def calibrations(
        self, scope: IdentityScope, domain: str
    ) -> tuple[CalibrationReport, ...]:
        return tuple(
            rep.model_copy(deep=True)
            for ((cloud, customer, dom), _id, _ver, _dim), rep in sorted(
                self._calibrations.items(),
                key=lambda kv: (kv[0][1] or "", kv[0][2] or "", kv[0][3]),
            )
            if _in_scope(scope, domain, cloud, customer, dom)
        )

    async def drift_alerts(
        self, scope: IdentityScope, domain: str, subject_id: str | None = None
    ) -> tuple[DriftAlert, ...]:
        return tuple(
            alert.model_copy(deep=True)
            for ((cloud, customer, dom), _dim, _sub, _at), alert in sorted(
                self._alerts.items(), key=lambda kv: (kv[1].detected_at, kv[1].dimension)
            )
            if _in_scope(scope, domain, cloud, customer, dom)
            and (subject_id is None or alert.subject_id == subject_id)
        )

    async def coverage(self, scope: IdentityScope, domain: str) -> tuple[SamplingCoverage, ...]:
        latest: dict[str, SamplingCoverage] = {}
        for cov in self._coverage.values():
            if not _in_scope(scope, domain, cov.cloud, cov.customer_id, cov.domain_id):
                continue
            current = latest.get(cov.stratum)
            if current is None or _later(cov.recorded_at, current.recorded_at):
                latest[cov.stratum] = cov
        return tuple(latest[s].model_copy(deep=True) for s in sorted(latest))


def _later(a: datetime, b: datetime) -> bool:
    return a >= b
