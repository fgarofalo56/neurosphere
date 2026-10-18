"""Deployment-profile gating of the analytics adapters against the capability matrix.

Pure in-process (matrix YAML + registry only): no emulator, no network, no cloud call, so it
runs in the default ``uv run pytest -q`` (deliberately NOT marked ``integration``/``live``).
It proves that availability gating and the cloud boundary are enforced; it is not evidence
that any vendor service exists or works in any region. Expectations are derived from the loaded
matrix, with a few documented facts pinned explicitly.
"""

from __future__ import annotations

from typing import Any

import pytest
from neurosphere_core.analytics.base import BackendStatus, list_backends
from neurosphere_core.analytics.base import create_adapter as registry_create
from neurosphere_core.analytics.base import registry as registry_module
from neurosphere_core.analytics.fabric import resolve_feature_flags
from neurosphere_core.capabilities.validate import (
    CapabilityResult,
    DeploymentProfile,
    validate_profile,
)
from neurosphere_core.errors import CapabilityUnavailableError, InvalidSchemaError

from .support import DBX_HOST, FABRIC_HOST

BACKENDS = ("fabric", "synapse", "databricks")
PROFILES: list[tuple[str, str]] = [
    ("government", "usgovvirginia"),
    ("government", "usgovtexas"),
    ("government", "usgovarizona"),
    ("government", "usdodeast"),
    ("commercial", "eastus2"),
    ("commercial", "swedensouth"),  # no per-region row: falls back to the unverified global row
]
IDS = [f"{c}-{r}" for c, r in PROFILES]


def matrix_result(name: str, cloud: str, region: str) -> CapabilityResult:
    profile = DeploymentProfile.model_validate(
        {"cloud": cloud, "regions": (region,), "hosting": "aks", "analytics": name}
    )
    return next(r for r in validate_profile(profile).results if r.kind == "analytics")


def by_name(cloud: str, region: str) -> dict[str, BackendStatus]:
    return {b.name: b for b in list_backends(cloud=cloud, region=region)}


class ExplodingExecutor:
    """Any use of it means a disabled backend reached the vendor layer."""

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"executor touched ({name}) for a disabled backend")


@pytest.mark.parametrize(("cloud", "region"), PROFILES, ids=IDS)
def test_every_backend_listed_with_matrix_status_and_reason(cloud: str, region: str) -> None:
    listed = by_name(cloud, region)
    assert tuple(listed) == BACKENDS  # disabled items are visible, never hidden
    for name in BACKENDS:
        result = matrix_result(name, cloud, region)
        item = listed[name]
        assert item.status == result.status
        assert item.row_id == result.row_id
        assert item.reason == result.reason
        assert item.reason_code == result.reason_code
        assert item.warnings == result.warnings
        if item.status == "disabled":
            assert item.reason, f"{name} disabled in {cloud} {region} without a reason"
            if item.row_id:
                assert item.row_id in item.reason
            else:  # no row at all: the reason must still name the capability and region
                assert f"{name}.base" in item.reason and region in item.reason
        else:
            assert item.reason is None


def test_documented_matrix_facts_are_pinned() -> None:
    gov = by_name("government", "usgovvirginia")
    assert {n: b.status for n, b in gov.items()} == {
        "fabric": "supported",
        "synapse": "supported",
        "databricks": "supported",
    }
    assert by_name("government", "usgovtexas")["fabric"].status == "supported"
    assert by_name("government", "usgovtexas")["databricks"].status == "disabled"
    assert by_name("government", "usgovarizona")["databricks"].status == "supported"
    assert by_name("government", "usgovarizona")["fabric"].status == "disabled"
    # DoD: Fabric and Databricks have no verified row and stay disabled.
    dod = by_name("government", "usdodeast")
    assert dod["fabric"].status == "disabled" and dod["databricks"].status == "disabled"
    # Commercial: per-region rows exist for eastus2; an unlisted region falls back to unverified.
    assert {b.status for b in by_name("commercial", "eastus2").values()} == {"supported"}
    unlisted = by_name("commercial", "swedensouth")
    assert {b.status for b in unlisted.values()} == {"disabled"}
    assert all(b.row_id and b.row_id.endswith(".commercial.global.any") for b in unlisted.values())


DISABLED = [
    pytest.param(name, cloud, region, id=f"{name}-{cloud}-{region}")
    for cloud, region in PROFILES
    for name, item in by_name(cloud, region).items()
    if item.status == "disabled"
]


@pytest.mark.parametrize(("name", "cloud", "region"), DISABLED)
def test_selecting_a_disabled_backend_is_refused_before_any_vendor_work(
    name: str, cloud: str, region: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    item = by_name(cloud, region)[name]
    assert item.status == "disabled"

    def no_import(path: str) -> Any:
        raise AssertionError(f"vendor module loaded for a disabled backend: {path}")

    monkeypatch.setattr(registry_module, "_load", no_import)
    with pytest.raises(CapabilityUnavailableError) as refusal:
        registry_create(name, cloud=cloud, region=region, config={}, executor=ExplodingExecutor())
    assert refusal.value.code == "capability_unavailable"
    assert str(refusal.value) == item.reason


def test_disabled_cases_exist_in_this_matrix() -> None:
    """Guard against the refusal test above running over an empty parameter set."""
    assert len(DISABLED) >= 6


@pytest.mark.parametrize(("cloud", "region"), PROFILES, ids=IDS)
def test_only_matrix_approved_adapters_are_constructible(cloud: str, region: str) -> None:
    from .support import build_adapter

    for name, item in by_name(cloud, region).items():
        if item.status == "supported":
            kind = {"synapse": "synapse-serverless"}.get(name, name)
            assert cloud in ("commercial", "government")
            built = build_adapter(kind, cloud, region)  # type: ignore[arg-type]
            assert built.adapter.cloud == cloud
        else:
            with pytest.raises(CapabilityUnavailableError):
                registry_create(name, cloud=cloud, region=region, config={}, executor=object())


def test_government_config_with_commercial_host_fails_at_construction() -> None:
    from neurosphere_core.analytics.base import StubSqlEndpoint

    endpoint = StubSqlEndpoint(())
    cases: list[tuple[str, dict[str, Any]]] = [
        ("fabric", {"sql_endpoint_host": FABRIC_HOST["commercial"], "database": "ns"}),
        (
            "synapse",
            {
                "mode": "dedicated",
                "workspace": "nsdemo",
                "database": "nsanalytics",
                "host": "nsdemo.sql.azuresynapse.net",
            },
        ),
        (
            "databricks",
            {
                "region": "usgovvirginia",
                "workspace_host": DBX_HOST["commercial"],
                "warehouse_id": "0123456789abcdef",
                "catalog": "neurosphere",
                "schema_name": "analytics",
            },
        ),
    ]
    for name, config in cases:
        assert by_name("government", "usgovvirginia")[name].status == "supported"
        with pytest.raises(InvalidSchemaError):
            registry_create(
                name, cloud="government", region="usgovvirginia", config=config, executor=endpoint
            )


def test_government_registry_never_yields_a_commercial_adapter() -> None:
    from neurosphere_core.analytics.base import StubSqlEndpoint

    from .support import build_adapter

    for region in ("usgovvirginia", "usgovtexas", "usgovarizona", "usdodeast", "eastus2"):
        for name in BACKENDS:
            try:
                adapter = registry_create(
                    name,
                    cloud="government",
                    region=region,
                    config={},
                    executor=StubSqlEndpoint(()),
                )
            except (CapabilityUnavailableError, InvalidSchemaError):
                continue  # refused: no fallback to another cloud
            assert adapter.cloud == "government"  # pragma: no cover
    for kind in ("fabric", "synapse-serverless", "synapse-dedicated", "databricks"):
        assert build_adapter(kind, "government").adapter.cloud == "government"


def test_fabric_gcc_high_feature_flags_resolve_disabled_with_matrix_reason() -> None:
    for region in ("usgovvirginia", "usgovtexas"):
        flags = resolve_feature_flags(cloud="government", region=region)
        for flag in (flags.customer_managed_keys, flags.workspace_identity, flags.fabric_iq_items):
            assert flag.enabled is False
            assert flag.row_id and flag.row_id in (flag.reason or "")
            assert flag.reason_code


@pytest.mark.parametrize(("cloud", "region"), PROFILES, ids=IDS)
def test_ga_unverified_warning_surfaces_where_the_row_says_so(cloud: str, region: str) -> None:
    for name, item in by_name(cloud, region).items():
        result = matrix_result(name, cloud, region)
        flagged = any(w.startswith("ga_unverified") for w in result.warnings)
        assert any(w.startswith("ga_unverified") for w in item.warnings) == flagged
        if item.status == "disabled":
            assert not flagged  # nothing to caveat on a backend that is not offered
    # pinned: Fabric GCC High is GA-verified, Synapse and Databricks government are not
    gov = by_name("government", "usgovvirginia")
    assert not gov["fabric"].warnings
    assert any(w.startswith("ga_unverified") for w in gov["synapse"].warnings)
    assert any(w.startswith("ga_unverified") for w in gov["databricks"].warnings)
