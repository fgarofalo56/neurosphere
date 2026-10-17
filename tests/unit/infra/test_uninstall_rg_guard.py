"""ARM-backed live inventory for the uninstall script (PRP-08 review): no network."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest
from neurosphere_core.errors import NeuroSphereError

SCRIPT = Path(__file__).resolve().parents[3] / "infra" / "scripts" / "uninstall.py"
SUB = "/subscriptions/00000000-0000-0000-0000-000000000000"
RG = f"{SUB}/resourceGroups/rg-ns"


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("ns_uninstall_under_test", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


uninstall = _load()


class Resp:
    def __init__(self, status: int, body: dict[str, Any]) -> None:
        self.status_code = status
        self._body = body

    def json(self) -> dict[str, Any]:
        return self._body


class FakeHttp:
    def __init__(self, responses: list[Resp]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, dict[str, str] | None]] = []
        self.deletes: list[str] = []

    async def get(self, url: str, params: dict[str, str] | None = None, **_: Any) -> Resp:
        self.calls.append((url, params))
        return self.responses.pop(0)

    async def delete(self, url: str, **_: Any) -> Resp:
        self.deletes.append(url)
        return Resp(202, {})


async def _token() -> str:
    return "t"


async def test_inventory_follows_next_link_and_pins_api_version() -> None:
    http = FakeHttp(
        [
            Resp(200, {"value": [{"id": "/a"}], "nextLink": "https://m/next?skip=1"}),
            Resp(200, {"value": [{"id": "/b"}]}),
        ]
    )
    inventory = uninstall.ArmInventory("https://management.azure.com/", _token, http)
    assert await inventory.list_resource_group(RG) == ["/a", "/b"]
    assert http.calls[0] == (
        f"https://management.azure.com{RG}/resources",
        {"api-version": "2021-04-01"},
    )
    assert http.calls[1] == ("https://m/next?skip=1", None)


async def test_inventory_non_200_raises_so_caller_fails_closed() -> None:
    inventory = uninstall.ArmInventory("https://m", _token, FakeHttp([Resp(403, {})]))
    with pytest.raises(NeuroSphereError):
        await inventory.list_resource_group(RG)


async def test_remove_through_arm_issues_no_delete_when_foreign_resource_present() -> None:
    from datetime import UTC, datetime

    from neurosphere_core.deploy.register import Ownership, ResourceRow, remove
    from neurosphere_core.errors import ForbiddenError

    def mk(rid: str, svc: str) -> ResourceRow:
        return ResourceRow(
            deployment_id="d",
            resource_id=rid,
            service=svc,
            ownership=Ownership.CREATED,
            created_by="neurosphere",
            owner="principal:abc123",
            creating_plan_id="p",
            recorded_at=datetime(2026, 10, 16, tzinfo=UTC),
        )

    kv = f"{RG}/providers/Microsoft.KeyVault/vaults/kv1"
    rows = [mk(RG, "resource-group"), mk(kv, "keyvault")]
    foreign = f"{RG}/providers/Microsoft.Storage/storageAccounts/theirs"
    http = FakeHttp([Resp(200, {"value": [{"id": kv}, {"id": foreign}]})])
    deleter = uninstall.ArmDeleter("https://m", _token, http)
    inventory = uninstall.ArmInventory("https://m", _token, http)
    with pytest.raises(ForbiddenError):
        await remove("d", rows, deleter, inventory)
    assert http.deletes == []
