"""PRP-139 item 1: the hosted deploy script's data-mode and customer-id flags.

Everything here runs offline: arguments are parsed and refused (or accepted) by the script's own
static validation, which runs before any ``az`` call. Registration writing is exercised on a
throwaway directory.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

GATES = Path(__file__).resolve().parents[3] / "scripts" / "gates"
SUB = "11111111-2222-3333-4444-555555555555"
TENANT = "cccccccc-0000-0000-0000-000000000001"
APP_ID = "bbbbbbbb-0000-0000-0000-000000000001"
WORKSPACE = (
    f"/subscriptions/{SUB}/resourceGroups/rg-obs/providers"
    "/Microsoft.OperationalInsights/workspaces/law-gw"
)
APIM = (
    f"/subscriptions/{SUB}/resourceGroups/rg-gw/providers/Microsoft.ApiManagement/service/apim-gw"
)


def _load() -> ModuleType:
    if str(GATES) not in sys.path:
        sys.path.insert(0, str(GATES))
    spec = importlib.util.spec_from_file_location(
        "hosted_demo_flags_under_test", GATES / "hosted_demo.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["hosted_demo_flags_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


mod = _load()


def _args(command: str, *extra: str) -> Any:
    argv = [
        command,
        "--subscription",
        SUB,
        "--operator",
        "tester",
        "--entra-tenant-id",
        TENANT,
        "--entra-client-id",
        APP_ID,
        *extra,
    ]
    return mod.build_parser().parse_args(argv)


@pytest.mark.parametrize("command", ["plan", "deploy"])
def test_data_mode_is_required_for_plan_and_deploy(command: str) -> None:
    with pytest.raises(mod.RefusedError, match="--data-mode"):
        mod.validate_static(_args(command))


def test_data_mode_is_optional_for_preflight() -> None:
    mod.validate_static(_args("preflight"))


def test_demo_mode_accepts_the_default_customer() -> None:
    mod.validate_static(_args("plan", "--data-mode", "demo"))


def test_real_tenant_with_a_real_customer_is_accepted() -> None:
    mod.validate_static(_args("plan", "--data-mode", "real-tenant", "--customer-id", "contoso"))


def test_real_tenant_refuses_the_synthetic_customer_by_name() -> None:
    with pytest.raises(mod.RefusedError, match="--customer-id"):
        mod.validate_static(_args("plan", "--data-mode", "real-tenant"))
    with pytest.raises(mod.RefusedError, match="--customer-id"):
        mod.validate_static(
            _args("deploy", "--data-mode", "real-tenant", "--customer-id", "synthco")
        )


@pytest.mark.parametrize("bad", ["Contoso", "con toso", "a:b", "x/y", "", "a" * 129])
def test_real_tenant_refuses_a_non_segment_customer(bad: str) -> None:
    with pytest.raises(mod.RefusedError, match="--customer-id"):
        mod.validate_static(_args("plan", "--data-mode", "real-tenant", "--customer-id", bad))


def test_real_tenant_refuses_government_regions() -> None:
    with pytest.raises(mod.RefusedError):
        mod.validate_static(
            _args(
                "plan",
                "--data-mode",
                "real-tenant",
                "--customer-id",
                "contoso",
                "--location",
                "usgovvirginia",
            )
        )


def test_resource_id_lists_must_be_arm_ids() -> None:
    with pytest.raises(mod.RefusedError, match="--log-analytics-workspace-ids"):
        mod.validate_static(
            _args("plan", "--data-mode", "demo", "--log-analytics-workspace-ids", "law-gw")
        )
    with pytest.raises(mod.RefusedError, match="--apim-service-ids"):
        mod.validate_static(_args("plan", "--data-mode", "demo", "--apim-service-ids", "apim"))


def test_customer_id_reaches_the_generated_parameters_and_the_registration(tmp_path: Path) -> None:
    args = _args(
        "plan",
        "--data-mode",
        "real-tenant",
        "--customer-id",
        "contoso",
        "--log-analytics-workspace-ids",
        WORKSPACE,
        "--apim-service-ids",
        APIM,
        "--image-tag",
        "0.1.0-rc.5",
        "--integration-subnet-id",
        f"/subscriptions/{SUB}/resourceGroups/h/providers/Microsoft.Network/virtualNetworks/v/subnets/s",
        "--private-endpoint-subnet-id",
        f"/subscriptions/{SUB}/resourceGroups/h/providers/Microsoft.Network/virtualNetworks/v/subnets/p",
        "--cosmos-zone-id",
        f"/subscriptions/{SUB}/resourceGroups/h/providers/Microsoft.Network/privateDnsZones/z1",
        "--eventhubs-zone-id",
        f"/subscriptions/{SUB}/resourceGroups/h/providers/Microsoft.Network/privateDnsZones/z2",
        "--blob-zone-id",
        f"/subscriptions/{SUB}/resourceGroups/h/providers/Microsoft.Network/privateDnsZones/z3",
        "--webapps-zone-id",
        f"/subscriptions/{SUB}/resourceGroups/h/providers/Microsoft.Network/privateDnsZones/z4",
        "--copilot-endpoint",
        "https://example.invalid",
        "--budget-contact-emails",
        "ops@example.invalid",
        "--tag-owner",
        "tester",
        "--state-dir",
        str(tmp_path),
    )
    ctx = mod.Ctx(
        run_az=lambda _a: None,  # pyright: ignore[reportArgumentType]
        args=args,
        work_dir=tmp_path,
        backend_factory=lambda *_a, **_k: None,  # pyright: ignore[reportArgumentType]
    )
    values = mod.infra_values(ctx)
    assert set(values) == set(mod.cm.GENERATED_PARAMS)
    assert values["dataMode"] == "real-tenant"
    assert values["customerId"] == "contoso"
    assert values["logAnalyticsWorkspaceIds"] == [WORKSPACE]
    assert values["apimServiceIds"] == [APIM]

    out = {"apiPrincipalId": "aaaaaaaa-0000-0000-0000-000000000001", "workersPrincipalId": "w"}
    # A prior registration under the synthetic customer: the replaced id is kept.
    (tmp_path / "registration.json").write_text(
        json.dumps({"customer_id": "synthco"}), encoding="utf-8"
    )
    reg = json.loads(mod.write_registration(ctx, out).read_text(encoding="utf-8"))
    assert reg["schema"] == 1
    assert reg["customer_id"] == "contoso"
    assert reg["data_mode"] == "real-tenant"
    assert reg["previous_customer_id"] == "synthco"
    assert reg["api_principal_id"] == out["apiPrincipalId"]

    # A second write with the same id keeps the recorded previous id.
    reg = json.loads(mod.write_registration(ctx, out).read_text(encoding="utf-8"))
    assert reg["previous_customer_id"] == "synthco"


def test_registration_without_a_prior_file_has_no_previous_customer(tmp_path: Path) -> None:
    args = SimpleNamespace(customer_id="synthco", data_mode="")
    ctx = SimpleNamespace(args=args, state_dir=tmp_path, deployment_id="hosted-x")
    reg = json.loads(mod.write_registration(ctx, {}).read_text(encoding="utf-8"))  # type: ignore[arg-type]
    assert reg["data_mode"] == "demo"
    assert "previous_customer_id" not in reg
    assert reg["customer_id"] == "synthco"
