"""Cross-adapter equivalence: one normalized dataset, every adapter, same answers.

The fixture adapter is the oracle. The same synthetic ``build_dataset(cloud)`` is loaded into a
``StubSqlEndpoint`` behind each vendor adapter (Fabric, Synapse serverless, Synapse dedicated,
Databricks), each built through its real config model and the capability-gated registry, and
every request must satisfy ``compare_results(fixture, adapter) == []``.

Tolerance: counts, sums, min and max compare exactly (Decimal cost included); approximate
quantiles compare within ``QUANTILE_REL_TOL`` relative / ``QUANTILE_ABS_TOL`` absolute, the
constants imported from ``compare`` (see ``tolerance_text``), never copied numbers.

Synapse serves quantiles through the exact windowed ``PERCENTILE_CONT`` (issue #59),
compared with the same documented tolerance.

Scope: pure in-process. No emulator, no network, no cloud call, so this runs in the default
``uv run pytest -q`` (deliberately NOT marked ``integration``/``live``). It proves contract
conformance of the adapter layer over a SQLite stub with declared rewrite shims, and says
nothing about vendor behaviour; the shims it records are the G12 parity gap.
"""

from __future__ import annotations

from typing import get_args

import pytest
from neurosphere_core.analytics.base import (
    QUANTILE_ABS_TOL,
    QUANTILE_REL_TOL,
    AggregateRequest,
    Aggregation,
    Cloud,
    Dimension,
    FilterClause,
    FilterOp,
    Metric,
    compare_results,
)
from neurosphere_core.analytics.fixture import domain_id, equivalence_cases

from .support import ADAPTERS, build_adapter, fixture_adapter, make_request, make_scope

CLOUDS: tuple[str, ...] = get_args(Cloud)
USD = FilterClause(field=Dimension.CURRENCY, op=FilterOp.EQ, values=("USD",))


EXPECTED_SHIMS: dict[str, list[str]] = {
    "fabric": [
        "fabric-tsql-rewrite",
        "decimal-cost",
        "quantile-ns_fabric_percentile",
        "scan-counter",
    ],
    "synapse-serverless": ["tsql-query-rewrites", "decimal-cost", "scan-counter"],
    "synapse-dedicated": ["tsql-query-rewrites", "decimal-cost", "scan-counter"],
    "databricks": [
        "databricks-dialect",
        "decimal-cost",
        "quantile-percentile_approx",
        "scan-counter",
    ],
}


def tolerance_text() -> str:
    return f"quantile rel<={QUANTILE_REL_TOL} abs<={QUANTILE_ABS_TOL}; all else exact"


MATRIX = [
    pytest.param(kind, cloud, name, request_, id=f"{kind}-{cloud}-{name}")
    for cloud in CLOUDS
    for kind in ADAPTERS
    for name, request_ in equivalence_cases(cloud)
]


@pytest.mark.parametrize(("kind", "cloud", "name", "request_"), MATRIX)
async def test_adapter_equals_fixture(
    kind: str, cloud: Cloud, name: str, request_: AggregateRequest
) -> None:
    built = build_adapter(kind, cloud)
    scope = make_scope(cloud)
    expected = await fixture_adapter(cloud).aggregate(request_, scope=scope)
    actual = await built.adapter.aggregate(request_, scope=scope)
    assert compare_results(expected, actual) == [], tolerance_text()
    assert expected.rows  # the case exercised data
    assert actual.cloud == cloud


@pytest.mark.parametrize("kind", [k for k in ADAPTERS if k.startswith("synapse-")])
async def test_synapse_quantile_runs_windowed_and_matches_the_fixture(kind: str) -> None:
    """Issue #59: the refusal became a pass; the statement is the windowed PERCENTILE_CONT."""
    built = build_adapter(kind, "commercial")
    request_ = make_request(
        Metric.DURATION_MS,
        Aggregation.APPROX_QUANTILE,
        quantile=0.95,
        group_by=(Dimension.MODEL,),
    )
    scope = make_scope()
    actual = await built.adapter.aggregate(request_, scope=scope)
    expected = await fixture_adapter("commercial").aggregate(request_, scope=scope)
    assert expected.rows
    assert compare_results(expected, actual) == [], tolerance_text()
    assert "tsql-query-rewrites" in [name for name, _ in built.endpoint.applied_shims]
    assert built.endpoint.last_sql is not None
    assert "OVER" in built.endpoint.last_sql  # the window form reached the engine text


@pytest.mark.parametrize("cloud", CLOUDS)
@pytest.mark.parametrize("kind", ["fixture", *ADAPTERS])
async def test_null_bearing_groups_are_unknown_never_zero(kind: str, cloud: Cloud) -> None:
    adapter = fixture_adapter(cloud) if kind == "fixture" else build_adapter(kind, cloud).adapter
    for metric in (Metric.OUTPUT_TOKENS, Metric.INPUT_TOKENS, Metric.DURATION_MS):
        for aggregation in (Aggregation.MAX, Aggregation.MIN, Aggregation.SUM):
            result = await adapter.aggregate(
                make_request(metric, aggregation, group_by=(Dimension.MODEL,)),
                scope=make_scope(cloud),
            )
            legacy = next(r for r in result.rows if r.keys == ("embed-legacy",))
            assert legacy.value is None, (kind, metric, aggregation)
            assert legacy.unknown_count == legacy.row_count > 0


@pytest.mark.parametrize("cloud", CLOUDS)
@pytest.mark.parametrize("kind", ["fixture", *ADAPTERS])
async def test_out_of_scope_never_appears(kind: str, cloud: Cloud) -> None:
    adapter = fixture_adapter(cloud) if kind == "fixture" else build_adapter(kind, cloud).adapter
    scope = make_scope(cloud, "contoso", ("retail",))
    result = await adapter.aggregate(make_request(group_by=(Dimension.DOMAIN_ID,)), scope=scope)
    allowed = domain_id(cloud, "contoso", "retail")
    keys = {r.keys[0] for r in result.rows}
    assert allowed in keys
    for key in keys - {None}:
        assert key == allowed, f"{kind} leaked {key}"  # no other domain, no other customer
    # an explicit filter for another customer's domain widens nothing
    other = FilterClause(
        field=Dimension.DOMAIN_ID, op=FilterOp.EQ, values=(domain_id(cloud, "fabrikam", "retail"),)
    )
    narrowed = await adapter.aggregate(make_request(filters=(other,)), scope=scope)
    assert all(r.row_count == 0 and r.value in (None, 0) for r in narrowed.rows)
    assert sum(r.row_count for r in narrowed.rows) == 0


@pytest.mark.parametrize("cloud", CLOUDS)
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_stub_shims_are_recorded_and_nonempty(kind: str, cloud: Cloud) -> None:
    """The G12 gap is real: the stub only runs the vendor SQL through declared rewrites."""
    built = build_adapter(kind, cloud)
    await built.adapter.aggregate(
        make_request(Metric.COST_AMOUNT, Aggregation.SUM, filters=(USD,)),
        scope=make_scope(cloud),
    )
    applied = built.endpoint.applied_shims
    assert applied, f"{kind} ran with no declared shim: the parity gap would be hidden"
    assert all(name and rule for name, rule in applied)
    assert [name for name, _ in applied] == EXPECTED_SHIMS[kind]
