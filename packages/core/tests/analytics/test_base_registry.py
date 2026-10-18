from __future__ import annotations

import sys
import types
from collections.abc import Mapping
from typing import Any

import pytest
from neurosphere_core.analytics.base import (
    AnsiDialect,
    SqlAnalytics,
    StubSqlEndpoint,
    create_adapter,
    list_backends,
    standard_shims,
)
from neurosphere_core.analytics.base.registry import VENDOR_FACTORIES
from neurosphere_core.analytics.fixture import build_dataset
from neurosphere_core.errors import CapabilityUnavailableError, ForbiddenError, InvalidSchemaError

from .analytics_helpers import make_request, make_scope


def test_list_backends_shows_all_three_with_reasons() -> None:
    commercial = {b.name: b for b in list_backends(cloud="commercial", region="eastus2")}
    assert set(commercial) == {"fabric", "synapse", "databricks"}
    assert {b.status for b in commercial.values()} == {"supported"}
    # A region with no verified row falls back to the unverified global row: visible, disabled,
    # with the matrix reason.
    for backend in list_backends(cloud="commercial", region="zzzregion"):
        assert backend.status == "disabled"
        assert backend.reason and backend.reason_code
        assert backend.row_id and backend.row_id.endswith(".commercial.global.any")
    gov = {b.name: b for b in list_backends(cloud="government", region="usgovvirginia")}
    assert gov["fabric"].status == "supported"
    assert gov["fabric"].row_id == "fabric.base.government.usgovvirginia.any"
    assert gov["databricks"].status == "supported"
    assert any("ga_unverified" in w for w in gov["databricks"].warnings)
    unlisted = {b.name: b for b in list_backends(cloud="government", region="usgovtexas")}
    assert unlisted["databricks"].status == "disabled"  # Arizona and Virginia only


def test_disabled_backend_raises_capability_unavailable_with_matrix_reason() -> None:
    with pytest.raises(CapabilityUnavailableError) as err:
        create_adapter("fabric", cloud="commercial", region="zzzregion")
    assert err.value.code == "capability_unavailable"
    assert "fabric.base.commercial.global.any" in (err.value.detail or "")


def test_invalid_names_and_regions() -> None:
    with pytest.raises(InvalidSchemaError):
        create_adapter("clickhouse", cloud="commercial", region="eastus2")
    with pytest.raises(InvalidSchemaError):
        create_adapter("fabric", cloud="commercial", region="usgovvirginia")


def test_supported_backend_without_installed_package_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "neurosphere_core.analytics.fabric", None)  # import fails
    with pytest.raises(CapabilityUnavailableError) as err:
        create_adapter("fabric", cloud="government", region="usgovvirginia")
    assert err.value.reason == "adapter_not_installed"


def test_supported_backend_resolves_the_lazy_vendor_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, Any] = {}

    def factory(
        *, cloud: str, region: str, config: Mapping[str, Any], executor: object | None
    ) -> SqlAnalytics:
        calls.update(cloud=cloud, region=region, config=dict(config), executor=executor)
        endpoint = StubSqlEndpoint(build_dataset("government", 20), shims=standard_shims())
        return SqlAnalytics(
            backend="fabric", cloud="government", dialect=AnsiDialect(), executor=endpoint
        )

    module = types.ModuleType("neurosphere_core.analytics.fabric")
    module.create_adapter = factory  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "neurosphere_core.analytics.fabric", module)
    assert VENDOR_FACTORIES["fabric"] == "neurosphere_core.analytics.fabric:create_adapter"
    adapter = create_adapter(
        "fabric", cloud="government", region="usgovvirginia", config={"workspace": "w"}
    )
    assert adapter.cloud == "government"
    assert calls["config"] == {"workspace": "w"} and calls["region"] == "usgovvirginia"


def test_cloud_mismatch_from_a_vendor_factory_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    def factory(**_: Any) -> SqlAnalytics:
        endpoint = StubSqlEndpoint(build_dataset("commercial", 5), shims=standard_shims())
        return SqlAnalytics(
            backend="fabric", cloud="commercial", dialect=AnsiDialect(), executor=endpoint
        )

    module = types.ModuleType("neurosphere_core.analytics.fabric")
    module.create_adapter = factory  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "neurosphere_core.analytics.fabric", module)
    with pytest.raises(CapabilityUnavailableError) as err:
        create_adapter("fabric", cloud="government", region="usgovvirginia")
    assert err.value.reason == "cloud_mismatch"


async def test_fixture_through_the_registry_is_sandbox_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = create_adapter("fixture", cloud="commercial", region="eastus2", config={"size": 40})
    assert (await adapter.aggregate(make_request(), scope=make_scope())).rows
    monkeypatch.setenv("NS_ENV", "staging")
    monkeypatch.setenv("NS_CLOUD", "commercial")
    with pytest.raises(ForbiddenError):
        create_adapter("fixture", cloud="commercial", region="eastus2")
    create_adapter("fixture", cloud="commercial", region="eastus2", sandbox=True)
