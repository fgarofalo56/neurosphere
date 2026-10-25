"""Cosmos NoSQL evaluation store (azure-cosmos aio), PRP-29 item 2.

Two containers, both with the hierarchical key ``/customer_id``, ``/domain_id`` (``MultiHash``):

* ``evaluation_results``: one document per ``EvaluationResult`` (the contract document plus
  ``id``, ``doc_type`` and ``sort_key`` = the raw ``evaluation_id``). Immutable: ``put_result``
  first looks the id up across partitions (the id is caller-supplied, so it can recur under
  another customer/domain; the in-memory store keys by id alone), then no-ops (equal) or raises
  ``EvaluationConflictError``; otherwise create-only, a racing 409 re-checks the same way.
* ``evaluation_runs``: the per-run records, discriminated by ``doc_type``: ``calibration``,
  ``drift_alert`` and ``coverage``. Each is ``{id, doc_type, cloud, customer_id, domain_id,
  body}`` where ``body`` is the model's JSON dump. Calibration is "newest wins", written with an
  ETag-conditional replace (create-only when absent) and a bounded retry.

Every query is single-partition AND repeats the customer, domain and cloud predicates. A domain
outside the scope's allowed domains never reaches Cosmos (empty result). Every list is bounded:
``list_results`` pages by ``sort_key``; ``results`` (aggregation) reads at most
``MAX_AGGREGATE_RESULTS`` and fails loudly past that rather than aggregating a truncated set;
``calibrations`` is bounded by ``MAX_RECORDS`` the same way; ``drift_alerts`` and ``coverage``
read the NEWEST ``MAX_RECORDS`` records (a documented, deliberate truncation of history).
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Final, NoReturn

from azure.core import MatchConditions
from azure.cosmos import PartitionKey
from azure.cosmos.aio import ContainerProxy, CosmosClient, DatabaseProxy
from azure.cosmos.exceptions import (
    CosmosAccessConditionFailedError,
    CosmosHttpResponseError,
    CosmosResourceExistsError,
    CosmosResourceNotFoundError,
)
from neurosphere_contracts.evaluation.v1.evaluation_result import EvaluationResult
from pydantic import ValidationError

from neurosphere_core.errors import (
    DependencyTransientError,
    InvalidSchemaError,
    NeuroSphereError,
    RateLimitedError,
)
from neurosphere_core.evaluation.calibration import CalibrationReport, DriftAlert
from neurosphere_core.evaluation.store import (
    Cloud,
    EvaluationConflictError,
    SamplingCoverage,
    _decode_cursor,  # pyright: ignore[reportPrivateUsage]
    _encode_cursor,  # pyright: ignore[reportPrivateUsage]
)
from neurosphere_core.paging import Page
from neurosphere_core.paging.models import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from neurosphere_core.scope import IdentityScope

__all__ = [
    "DEFAULT_RESULTS_CONTAINER",
    "DEFAULT_RUNS_CONTAINER",
    "EVALUATION_PARTITION_KEY_PATHS",
    "MAX_AGGREGATE_RESULTS",
    "MAX_RECORDS",
    "CosmosEvaluationStore",
    "create_evaluation_containers",
    "create_evaluation_results_container",
    "create_evaluation_runs_container",
]

DEFAULT_RESULTS_CONTAINER: Final = "evaluation_results"
DEFAULT_RUNS_CONTAINER: Final = "evaluation_runs"
EVALUATION_PARTITION_KEY_PATHS: Final = ("/customer_id", "/domain_id")
RESULT_DOC_TYPE: Final = "evaluation_result"
RESULT_BY_ID_QUERY: Final = "SELECT * FROM c WHERE c.id = @id"
CALIBRATION_DOC_TYPE: Final = "calibration"
DRIFT_DOC_TYPE: Final = "drift_alert"
COVERAGE_DOC_TYPE: Final = "coverage"
MAX_AGGREGATE_RESULTS: Final = 10_000
MAX_RECORDS: Final = 1_000
_CALIBRATION_ATTEMPTS: Final = 4
_SAFE_ID: Final = re.compile(r"^[A-Za-z0-9._:=-]{1,200}$")
_RESULT_SYSTEM_FIELDS: Final = frozenset({"id", "doc_type", "sort_key"})


async def create_evaluation_results_container(
    database: DatabaseProxy, container_id: str = DEFAULT_RESULTS_CONTAINER
) -> ContainerProxy:
    return await database.create_container_if_not_exists(
        id=container_id,
        partition_key=PartitionKey(path=list(EVALUATION_PARTITION_KEY_PATHS), kind="MultiHash"),
    )


async def create_evaluation_runs_container(
    database: DatabaseProxy, container_id: str = DEFAULT_RUNS_CONTAINER
) -> ContainerProxy:
    return await database.create_container_if_not_exists(
        id=container_id,
        partition_key=PartitionKey(path=list(EVALUATION_PARTITION_KEY_PATHS), kind="MultiHash"),
    )


async def create_evaluation_containers(
    database: DatabaseProxy,
    results_id: str = DEFAULT_RESULTS_CONTAINER,
    runs_id: str = DEFAULT_RUNS_CONTAINER,
) -> tuple[ContainerProxy, ContainerProxy]:
    return (
        await create_evaluation_results_container(database, results_id),
        await create_evaluation_runs_container(database, runs_id),
    )


def _doc_id(raw: str) -> str:
    """Cosmos forbids ``/ \\ ? #`` in ids; encode anything outside a conservative alphabet."""
    if _SAFE_ID.match(raw):
        return raw
    return "b64-" + base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")


def _hash_id(prefix: str, *parts: str | None) -> str:
    digest = hashlib.sha256(json.dumps(parts, separators=(",", ":")).encode("utf-8")).hexdigest()
    return f"{prefix}-{digest}"


def _utc_key(moment: datetime) -> str:
    """Fixed-width UTC timestamp so string order is time order."""
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _unavailable() -> DependencyTransientError:
    return DependencyTransientError(
        "evaluation store unavailable", reason="evaluation_store_unavailable"
    )


def _invalid() -> DependencyTransientError:
    return DependencyTransientError(
        "stored evaluation record failed validation",
        reason="evaluation_record_invalid",
        upstream_invalid=True,
    )


def _too_large() -> DependencyTransientError:
    return DependencyTransientError(
        "evaluation record set exceeds the supported bound", reason="evaluation_set_too_large"
    )


def _raise_mapped(exc: Exception) -> NoReturn:
    if isinstance(exc, NeuroSphereError):
        raise exc
    if isinstance(exc, CosmosHttpResponseError) and exc.status_code == 429:
        raise RateLimitedError(1, "evaluation store throttled the request") from exc
    raise _unavailable() from exc


def _result_from_row(row: Mapping[str, Any]) -> EvaluationResult:
    document = {
        k: v for k, v in row.items() if not k.startswith("_") and k not in _RESULT_SYSTEM_FIELDS
    }
    try:
        return EvaluationResult.model_validate(document)
    except ValidationError as exc:
        raise _invalid() from exc


def _body(row: Mapping[str, Any]) -> Mapping[str, Any]:
    body = row.get("body")
    if not isinstance(body, dict):
        raise _invalid()
    return body  # pyright: ignore[reportUnknownVariableType]


class CosmosEvaluationStore:
    """:class:`neurosphere_core.evaluation.store.EvaluationStore` on two Cosmos containers."""

    def __init__(self, results: ContainerProxy, runs: ContainerProxy) -> None:
        self._results = results
        self._runs = runs

    @classmethod
    def from_client(
        cls,
        client: CosmosClient,
        *,
        database: str,
        results_container: str = DEFAULT_RESULTS_CONTAINER,
        runs_container: str = DEFAULT_RUNS_CONTAINER,
    ) -> CosmosEvaluationStore:
        db = client.get_database_client(database)
        return cls(
            db.get_container_client(results_container), db.get_container_client(runs_container)
        )

    # -- helpers --------------------------------------------------------------------------------

    @staticmethod
    def _scope_clauses(
        scope: IdentityScope, domain: str, doc_type: str
    ) -> tuple[list[str], list[dict[str, Any]]]:
        clauses = [
            "c.doc_type = @doc_type",
            "c.customer_id = @customer",
            "c.domain_id = @domain",
            "c.cloud = @cloud",
        ]
        params: list[dict[str, Any]] = [
            {"name": "@doc_type", "value": doc_type},
            {"name": "@customer", "value": scope.customer_id},
            {"name": "@domain", "value": domain},
            {"name": "@cloud", "value": scope.cloud},
        ]
        return clauses, params

    @staticmethod
    async def _query(
        container: ContainerProxy, sql: str, params: list[dict[str, Any]], partition: list[str]
    ) -> list[dict[str, Any]]:
        try:
            return [
                dict(row)
                async for row in container.query_items(
                    sql, parameters=params, partition_key=partition
                )
            ]
        except Exception as exc:
            _raise_mapped(exc)

    @staticmethod
    def _run_doc(
        doc_type: str,
        doc_id: str,
        cloud: str,
        customer_id: str,
        domain_id: str,
        body: Mapping[str, Any],
        **extra: Any,
    ) -> dict[str, Any]:
        return {
            "id": doc_id,
            "doc_type": doc_type,
            "cloud": cloud,
            "customer_id": customer_id,
            "domain_id": domain_id,
            "body": dict(body),
            **extra,
        }

    async def _upsert_run(self, document: dict[str, Any]) -> None:
        try:
            await self._runs.upsert_item(body=document)
        except Exception as exc:
            _raise_mapped(exc)

    # -- writes ---------------------------------------------------------------------------------

    async def put_result(self, result: EvaluationResult) -> None:
        body = result.model_dump(mode="json")
        raw_id = result.evaluation_id.root
        body["id"] = _doc_id(raw_id)
        body["doc_type"] = RESULT_DOC_TYPE
        body["sort_key"] = raw_id
        # ``evaluation_id`` is caller-supplied and not derived from the domain, so the same id can
        # arrive under another customer/domain. The in-memory store keys results by id alone, so a
        # differing re-put anywhere is a conflict: look the id up across partitions first.
        try:
            stored = [
                row
                async for row in self._results.query_items(
                    RESULT_BY_ID_QUERY,
                    parameters=[{"name": "@id", "value": body["id"]}],
                )
            ]
        except Exception as exc:
            _raise_mapped(exc)
        if stored:
            if any(_result_from_row(row) != result for row in stored):
                raise EvaluationConflictError(
                    "a different evaluation result already exists under this id",
                    reason="evaluation_conflict",
                )
            return
        try:
            await self._results.create_item(body=body)
            return
        except CosmosResourceExistsError:
            pass
        except Exception as exc:
            _raise_mapped(exc)
        try:
            row = await self._results.read_item(
                item=body["id"], partition_key=[result.customer_id, result.domain_id.root]
            )
        except Exception as exc:
            _raise_mapped(exc)
        if _result_from_row(row) != result:
            raise EvaluationConflictError(
                "a different evaluation result already exists under this id",
                reason="evaluation_conflict",
            )

    async def put_calibration(
        self, cloud: Cloud, customer_id: str, domain_id: str, report: CalibrationReport
    ) -> None:
        doc_id = _hash_id(
            "cal", report.judge_config_id, report.judge_config_version, report.dimension
        )
        document = self._run_doc(
            CALIBRATION_DOC_TYPE,
            doc_id,
            cloud,
            customer_id,
            domain_id,
            report.model_dump(mode="json"),
            sort_key="|".join(
                (report.judge_config_id or "", report.judge_config_version or "", report.dimension)
            ),
        )
        for _ in range(_CALIBRATION_ATTEMPTS):
            try:
                current = await self._runs.read_item(
                    item=doc_id, partition_key=[customer_id, domain_id]
                )
            except CosmosResourceNotFoundError:
                try:
                    await self._runs.create_item(body=document)
                    return
                except CosmosResourceExistsError:
                    continue
                except Exception as exc:
                    _raise_mapped(exc)
            except Exception as exc:
                _raise_mapped(exc)
            try:
                existing = CalibrationReport.model_validate(_body(current))
            except ValidationError as exc:
                raise _invalid() from exc
            if report.calibrated_at < existing.calibrated_at:
                return
            try:
                await self._runs.replace_item(
                    item=doc_id,
                    body=document,
                    etag=current.get("_etag"),
                    match_condition=MatchConditions.IfNotModified,
                )
                return
            except (CosmosAccessConditionFailedError, CosmosResourceNotFoundError):
                continue
            except Exception as exc:
                _raise_mapped(exc)
        raise _unavailable()

    async def put_drift_alert(
        self, cloud: Cloud, customer_id: str, domain_id: str, alert: DriftAlert
    ) -> None:
        doc_id = _hash_id("drift", alert.dimension, alert.subject_id, alert.detected_at)
        await self._upsert_run(
            self._run_doc(
                DRIFT_DOC_TYPE,
                doc_id,
                cloud,
                customer_id,
                domain_id,
                alert.model_dump(mode="json"),
                detected_at=alert.detected_at,
                subject_id=alert.subject_id,
            )
        )

    async def put_coverage(self, coverage: SamplingCoverage) -> None:
        doc_id = _hash_id("cov", coverage.run_id, coverage.stratum)
        await self._upsert_run(
            self._run_doc(
                COVERAGE_DOC_TYPE,
                doc_id,
                coverage.cloud,
                coverage.customer_id,
                coverage.domain_id,
                coverage.model_dump(mode="json"),
                recorded_key=_utc_key(coverage.recorded_at),
            )
        )

    # -- reads ----------------------------------------------------------------------------------

    @staticmethod
    def _result_filters(
        subject_id: str | None, dimension: str | None
    ) -> tuple[list[str], list[dict[str, Any]]]:
        clauses: list[str] = []
        params: list[dict[str, Any]] = []
        if subject_id is not None:
            clauses.append("c.subject_id = @subject")
            params.append({"name": "@subject", "value": subject_id})
        if dimension is not None:
            clauses.append(
                "EXISTS(SELECT VALUE s FROM s IN c.scores WHERE s.dimension = @dimension)"
            )
            params.append({"name": "@dimension", "value": dimension})
        return clauses, params

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
        if domain not in scope.allowed_domains:
            return Page[EvaluationResult](items=(), next_cursor=None)
        clauses, params = self._scope_clauses(scope, domain, RESULT_DOC_TYPE)
        params.append({"name": "@limit", "value": limit + 1})
        if after is not None:
            clauses.append("c.sort_key > @after")
            params.append({"name": "@after", "value": after})
        extra_clauses, extra_params = self._result_filters(subject_id, dimension)
        clauses += extra_clauses
        params += extra_params
        sql = (
            "SELECT TOP @limit * FROM c WHERE "  # noqa: S608
            + " AND ".join(clauses)
            + " ORDER BY c.sort_key ASC"
        )
        rows = await self._query(self._results, sql, params, [scope.customer_id, domain])
        found = [_result_from_row(row) for row in rows]
        page = found[:limit]
        next_cursor = _encode_cursor(page[-1].evaluation_id.root) if len(found) > limit else None
        return Page[EvaluationResult](items=tuple(page), next_cursor=next_cursor)

    async def results(
        self, scope: IdentityScope, domain: str, subject_id: str | None = None
    ) -> tuple[EvaluationResult, ...]:
        if domain not in scope.allowed_domains:
            return ()
        clauses, params = self._scope_clauses(scope, domain, RESULT_DOC_TYPE)
        params.append({"name": "@limit", "value": MAX_AGGREGATE_RESULTS + 1})
        extra_clauses, extra_params = self._result_filters(subject_id, None)
        clauses += extra_clauses
        params += extra_params
        sql = (
            "SELECT TOP @limit * FROM c WHERE "  # noqa: S608
            + " AND ".join(clauses)
            + " ORDER BY c.sort_key ASC"
        )
        rows = await self._query(self._results, sql, params, [scope.customer_id, domain])
        if len(rows) > MAX_AGGREGATE_RESULTS:
            raise _too_large()
        return tuple(_result_from_row(row) for row in rows)

    async def _run_rows(
        self,
        scope: IdentityScope,
        domain: str,
        doc_type: str,
        order: str,
        *,
        limit: int,
        subject_id: str | None = None,
    ) -> list[dict[str, Any]]:
        if domain not in scope.allowed_domains:
            return []
        clauses, params = self._scope_clauses(scope, domain, doc_type)
        params.append({"name": "@limit", "value": limit})
        if subject_id is not None:
            clauses.append("c.subject_id = @subject")
            params.append({"name": "@subject", "value": subject_id})
        sql = (
            "SELECT TOP @limit * FROM c WHERE "  # noqa: S608
            + " AND ".join(clauses)
            + f" ORDER BY {order}"
        )
        return await self._query(self._runs, sql, params, [scope.customer_id, domain])

    async def calibrations(
        self, scope: IdentityScope, domain: str
    ) -> tuple[CalibrationReport, ...]:
        rows = await self._run_rows(
            scope, domain, CALIBRATION_DOC_TYPE, "c.sort_key ASC", limit=MAX_RECORDS + 1
        )
        if len(rows) > MAX_RECORDS:
            raise _too_large()
        try:
            reports = [CalibrationReport.model_validate(_body(row)) for row in rows]
        except ValidationError as exc:
            raise _invalid() from exc
        return tuple(
            sorted(
                reports,
                key=lambda r: (r.judge_config_id or "", r.judge_config_version or "", r.dimension),
            )
        )

    async def drift_alerts(
        self, scope: IdentityScope, domain: str, subject_id: str | None = None
    ) -> tuple[DriftAlert, ...]:
        rows = await self._run_rows(
            scope,
            domain,
            DRIFT_DOC_TYPE,
            "c.detected_at DESC",
            limit=MAX_RECORDS,
            subject_id=subject_id,
        )
        try:
            alerts = [DriftAlert.model_validate(_body(row)) for row in rows]
        except ValidationError as exc:
            raise _invalid() from exc
        return tuple(sorted(alerts, key=lambda a: (a.detected_at, a.dimension)))

    async def coverage(self, scope: IdentityScope, domain: str) -> tuple[SamplingCoverage, ...]:
        rows = await self._run_rows(
            scope, domain, COVERAGE_DOC_TYPE, "c.recorded_key DESC", limit=MAX_RECORDS
        )
        latest: dict[str, SamplingCoverage] = {}
        for row in rows:  # newest first: the first record seen per stratum is the latest
            try:
                cov = SamplingCoverage.model_validate(_body(row))
            except ValidationError as exc:
                raise _invalid() from exc
            latest.setdefault(cov.stratum, cov)
        return tuple(latest[s] for s in sorted(latest))
