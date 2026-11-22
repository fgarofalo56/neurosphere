"""get_timeline (PRP-78 item 2): scoped, bounded, partial-not-denied, no actors or bodies."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from neurosphere_contracts.recommendations.v1.recommendation import Recommendation
from neurosphere_contracts.scope.v1.identity_scope import IdentityScope as ContractScope
from neurosphere_core.aggregates import (
    AggregateSeries,
    AggregateWindow,
    ErrorPoint,
    Grain,
    LatencyPoint,
    Metric,
    QueryResult,
)
from neurosphere_core.copilot.tools import ToolRegistry, ToolResult, unknown_citations
from neurosphere_core.copilot.tools.errors import (
    ScopeArgumentRefusedError,
    ToolPermissionError,
)
from neurosphere_core.copilot.tools.ports import ChangeRecord
from neurosphere_core.copilot.tools.timeline import (
    MAX_TIMELINE_ENTRIES,
    MAX_TIMELINE_WINDOW,
    get_timeline_spec,
)
from neurosphere_core.errors import InvalidSchemaError
from neurosphere_core.paging import Page
from neurosphere_core.scope import IdentityScope

SCHEMAS = Path(__file__).resolve().parents[4] / "packages" / "contracts" / "schemas"
CUSTOMER = "contoso"
FINANCE = "commercial:contoso:catalog:domain:finance"
OPERATIONS = "commercial:contoso:catalog:domain:operations"
NOW = datetime(2026, 10, 21, 12, 0, 0, tzinfo=UTC)
WINDOW = 60


def _z(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def make_scope(roles: list[tuple[str, list[str]]], allowed: list[str]) -> IdentityScope:
    contract = ContractScope.model_validate(
        {
            "schema_version": "1.0.0",
            "cloud": "commercial",
            "customer_id": CUSTOMER,
            "principal": {
                "principal_id": f"commercial:{CUSTOMER}:entra:person:psn_0123456789abcdef",
                "principal_pseudonym": "p-7f3a9c21",
                "principal_kind": "user",
            },
            "roles": [
                {
                    "role": role,
                    "domain_ids": domains,
                    **(
                        {"expires_at": "2099-01-01T00:00:00Z"}
                        if role in ("admin", "security_auditor")
                        else {}
                    ),
                }
                for role, domains in roles
            ],
            "allowed_domains": allowed,
            "allowed_resources": [],
            "policy_version": "v1",
            "derived_at": "2026-10-20T00:00:00Z",
            "scope_hash": "sha256:" + hashlib.sha256(b"timeline-scope").hexdigest(),
        }
    )
    return IdentityScope._from_verified_contract(contract)  # pyright: ignore[reportPrivateUsage]


def viewer_with_audit() -> IdentityScope:
    """data.read on finance and operations; audit.read on finance only."""
    return make_scope(
        [("viewer", [FINANCE, OPERATIONS]), ("security_auditor", [FINANCE])],
        [FINANCE, OPERATIONS],
    )


def viewer_only() -> IdentityScope:
    return make_scope([("viewer", [FINANCE, OPERATIONS])], [FINANCE, OPERATIONS])


def change(n: int, domain: str, minutes_ago: int) -> ChangeRecord:
    return ChangeRecord(
        record_id=f"audit-{n:04d}",
        operation="catalog.update",
        subject_id=f"commercial:{CUSTOMER}:foundry:agent:a{n}",
        outcome="success",
        occurred_at=NOW - timedelta(minutes=minutes_ago),
        domain_id=domain,
    )


def recommendation(n: int, domain: str, created: datetime) -> Recommendation:
    raw: dict[str, Any] = json.loads(
        (
            SCHEMAS / "recommendations/v1/examples/valid/recommendation.cost-spike-scored.json"
        ).read_text(encoding="utf-8")
    )
    raw["recommendation_id"] = f"commercial:{CUSTOMER}:neurosphere:recommendation:rec-{n:04d}"
    raw["domain_id"] = domain
    raw["created_at"] = _z(created)
    return Recommendation.model_validate(raw)


@dataclass
class FakeChanges:
    records: list[ChangeRecord]
    domains_seen: list[tuple[str, ...]] = field(default_factory=list[tuple[str, ...]])

    async def changes(
        self,
        scope: IdentityScope,
        domain_ids: Any,
        since: datetime,
        until: datetime,
        *,
        limit: int,
    ) -> list[ChangeRecord]:
        self.domains_seen.append(tuple(domain_ids))
        return list(self.records)  # deliberately ignores domain_ids: the tool must re-filter


@dataclass
class FakeMetrics:
    """``values[(domain, metric, is_current)]`` is one hourly value; absent means no points."""

    values: dict[tuple[str, str, bool], int] = field(
        default_factory=dict[tuple[str, str, bool], int]
    )
    windows: list[AggregateWindow] = field(default_factory=list[AggregateWindow])

    async def query(
        self,
        customer_id: str,
        domain_id: str,
        metric: Metric,
        grain: Grain,
        window: AggregateWindow,
        *,
        max_series: int,
        max_points: int,
    ) -> QueryResult:
        self.windows.append(window)
        assert grain == "hour"
        current = window.end == NOW
        value = self.values.get((domain_id, metric, current))
        if value is None:
            return QueryResult(series=(), truncated=False)
        bucket = _z(window.start)
        common: dict[str, Any] = {
            "id": f"agg-{domain_id[-7:]}-{metric}-{'cur' if current else 'prev'}",
            "customer_id": customer_id,
            "domain_id": domain_id,
            "grain": "hour",
            "bucket_start": bucket,
            "series_key": "total",
            "watermark": _z(NOW),
            "complete": True,
        }
        point: ErrorPoint | LatencyPoint
        if metric == "errors":
            point = ErrorPoint(request_count=100, unknown_count=0, error_count=value, **common)
        else:
            point = LatencyPoint(sample_count=100, missing_count=0, p95_ms=value, **common)
        return QueryResult(series=(AggregateSeries(key="total", points=(point,)),), truncated=False)


@dataclass
class FakeRecs:
    items: list[Recommendation]

    async def list(
        self,
        scope: IdentityScope,
        domain: str,
        kind: str | None = None,
        q: str | None = None,
        cursor: str | None = None,
        limit: int = 50,
    ) -> Page[Recommendation]:
        return Page[Recommendation](
            items=tuple(r for r in self.items if r.domain_id.root == domain)
        )


def registry(
    *,
    changes: FakeChanges | None,
    metrics: FakeMetrics | None = None,
    recs: FakeRecs | None = None,
) -> ToolRegistry:
    spec = get_timeline_spec(
        changes=changes,
        metrics=metrics or FakeMetrics(),
        recommendations=recs or FakeRecs([]),
        clock=lambda: NOW,
    )
    return ToolRegistry([spec])


def entries(result: ToolResult) -> list[dict[str, Any]]:
    return [dict(r.data) for r in result.records if r.kind != "timeline_meta"]


def meta(result: ToolResult) -> dict[str, Any]:
    (record,) = [r for r in result.records if r.kind == "timeline_meta"]
    return dict(record.data)


async def test_merged_newest_first_across_sections() -> None:
    metrics = FakeMetrics({(FINANCE, "errors", True): 9, (FINANCE, "errors", False): 3})
    recs = FakeRecs([recommendation(1, FINANCE, NOW - timedelta(minutes=10))])
    changes = FakeChanges([change(1, FINANCE, 30), change(2, FINANCE, 5)])
    result = await registry(changes=changes, metrics=metrics, recs=recs).invoke(
        "get_timeline", {"window_minutes": WINDOW}, viewer_with_audit()
    )
    rows = entries(result)
    stamps = [r["occurred_at"] for r in rows]
    assert stamps == sorted(stamps, reverse=True)
    assert {r["kind"] for r in rows} == {"change", "metric_shift", "recommendation"}
    assert len(result.citations) == len(rows)
    assert {c.source for c in result.citations} == {"audit", "aggregates", "recommendations"}
    assert unknown_citations([c.record_id for c in result.citations], [result]) == ()


async def test_cap_at_100_and_truncated() -> None:
    records = [change(n, FINANCE, 1 + n % 50) for n in range(150)]
    result = await registry(changes=FakeChanges(records)).invoke(
        "get_timeline", {"window_minutes": WINDOW}, viewer_with_audit()
    )
    assert len(entries(result)) == MAX_TIMELINE_ENTRIES == 100
    assert result.truncated is True


async def test_changes_only_for_audit_read_domains_and_refiltered() -> None:
    changes = FakeChanges([change(1, FINANCE, 5), change(2, OPERATIONS, 6)])
    result = await registry(changes=changes).invoke(
        "get_timeline", {"window_minutes": WINDOW}, viewer_with_audit()
    )
    assert changes.domains_seen == [(FINANCE,)]
    assert [r["domain_id"] for r in entries(result)] == [FINANCE]


async def test_no_audit_read_is_partial_not_denied() -> None:
    changes = FakeChanges([change(1, FINANCE, 5)])
    recs = FakeRecs([recommendation(1, FINANCE, NOW - timedelta(minutes=3))])
    result = await registry(changes=changes, recs=recs).invoke(
        "get_timeline", {"window_minutes": WINDOW}, viewer_only()
    )
    assert changes.domains_seen == []
    assert [r["kind"] for r in entries(result)] == ["recommendation"]
    info = meta(result)
    assert info["sections_omitted"] == [{"section": "changes", "reason": "audit_read_not_held"}]
    assert "changes" not in info["sections_included"]
    assert all(c.record_id != "timeline_meta" for c in result.citations)


async def test_change_log_unavailable_is_reported() -> None:
    result = await registry(changes=None).invoke(
        "get_timeline", {"window_minutes": WINDOW, "sections": ["changes"]}, viewer_with_audit()
    )
    assert entries(result) == []
    assert meta(result)["sections_omitted"] == [
        {"section": "changes", "reason": "change_log_unavailable"}
    ]


async def test_metric_shift_compares_window_with_previous_window() -> None:
    metrics = FakeMetrics(
        {
            (FINANCE, "errors", True): 9,
            (FINANCE, "errors", False): 3,
            (FINANCE, "latency", True): 400,
            (FINANCE, "latency", False): 400,  # unchanged: no entry
            (OPERATIONS, "errors", True): 5,  # no previous value: unknown, no entry
        }
    )
    result = await registry(changes=None, metrics=metrics).invoke(
        "get_timeline", {"window_minutes": WINDOW, "sections": ["metric_shifts"]}, viewer_only()
    )
    (shift,) = entries(result)
    assert shift["metric"] == "errors"
    assert (shift["previous"], shift["current"], shift["delta"]) == (3.0, 9.0, 6.0)
    assert shift["domain_id"] == FINANCE
    start = NOW - timedelta(minutes=WINDOW)
    assert AggregateWindow(start=start, end=NOW) in metrics.windows
    assert AggregateWindow(start=start - timedelta(minutes=WINDOW), end=start) in metrics.windows


async def test_only_recommendations_created_in_window() -> None:
    recs = FakeRecs(
        [
            recommendation(1, FINANCE, NOW - timedelta(minutes=10)),
            recommendation(2, FINANCE, NOW - timedelta(minutes=WINDOW + 1)),
            recommendation(3, OPERATIONS, NOW - timedelta(minutes=1)),
        ]
    )
    result = await registry(changes=None, recs=recs).invoke(
        "get_timeline", {"window_minutes": WINDOW, "sections": ["recommendations"]}, viewer_only()
    )
    assert [r["recommendation_id"].rsplit(":", 1)[-1] for r in entries(result)] == [
        "rec-0003",
        "rec-0001",
    ]


@pytest.mark.parametrize("minutes", [0, 4, 1441, -5, 60.5, "60", True])
async def test_window_bounds_refused(minutes: object) -> None:
    with pytest.raises(InvalidSchemaError):
        await registry(changes=None).invoke(
            "get_timeline", {"window_minutes": minutes}, viewer_only()
        )


@pytest.mark.parametrize("minutes", [5, 1440])
async def test_window_bounds_accepted(minutes: int) -> None:
    assert MAX_TIMELINE_WINDOW == timedelta(minutes=1440)
    await registry(changes=None).invoke("get_timeline", {"window_minutes": minutes}, viewer_only())


@pytest.mark.parametrize("sections", [["changes", "changes"], [], ["audit"]])
async def test_bad_sections_refused(sections: list[str]) -> None:
    with pytest.raises(InvalidSchemaError):
        await registry(changes=None).invoke(
            "get_timeline", {"window_minutes": WINDOW, "sections": sections}, viewer_only()
        )


async def test_no_actor_or_body_fields_in_serialized_output() -> None:
    metrics = FakeMetrics({(FINANCE, "latency", True): 500, (FINANCE, "latency", False): 100})
    recs = FakeRecs([recommendation(1, FINANCE, NOW - timedelta(minutes=2))])
    result = await registry(
        changes=FakeChanges([change(1, FINANCE, 4)]), metrics=metrics, recs=recs
    ).invoke("get_timeline", {"window_minutes": WINDOW}, viewer_with_audit())
    text = result.model_dump_json().lower()
    for banned in ("actor", "principal", "pseudonym", "before", "after", "body", "p-7f3a9c21"):
        assert banned not in text
    assert {r["kind"] for r in entries(result)} == {"change", "metric_shift", "recommendation"}


async def test_scope_shaped_key_refused_via_registry() -> None:
    with pytest.raises(ScopeArgumentRefusedError):
        await registry(changes=None).invoke(
            "get_timeline", {"window_minutes": WINDOW, "domain_ids": [OPERATIONS]}, viewer_only()
        )


async def test_no_data_read_is_denied() -> None:
    auditor = make_scope([("security_auditor", [FINANCE])], [FINANCE])
    with pytest.raises(ToolPermissionError):
        await registry(changes=FakeChanges([])).invoke(
            "get_timeline", {"window_minutes": WINDOW}, auditor
        )
