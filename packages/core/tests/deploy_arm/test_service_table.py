"""The ARM allowlist (PRP-55 item 3, decision 2): exactly three services, uninstall-pinned
api-versions, valid deterministic names, the created-by tag and no secret in a create body."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
from neurosphere_core.deploy.arm import (
    ARM_SERVICES,
    CREATED_BY_TAG,
    arm_resource_name,
    arm_service,
    creation_tags,
    resource_group_id,
)
from neurosphere_core.errors import InvalidSchemaError

SUB = "aaaaaaaa-0000-4000-8000-000000000001"
ROOT = Path(__file__).resolve().parents[4]


def _uninstall_api_versions() -> dict[str, str]:
    path = ROOT / "infra" / "scripts" / "uninstall.py"
    spec = importlib.util.spec_from_file_location("ns_uninstall_for_tests", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("ns_uninstall_for_tests", module)
    spec.loader.exec_module(module)
    return dict(module._API_VERSIONS)  # pyright: ignore[reportPrivateUsage]


def test_the_allowlist_is_exactly_decision_2() -> None:
    assert set(ARM_SERVICES) == {"storage", "event_hubs", "monitoring"}
    for other in (
        "key_vault",
        "cosmos_db",
        "ai_search",
        "container_registry",
        "api_management",
        "model_endpoint",
        "hosting",
    ):
        assert arm_service(other) is None


def test_api_versions_match_the_uninstall_pins() -> None:
    pinned = _uninstall_api_versions()
    for entry in ARM_SERVICES.values():
        assert pinned[entry.provider_type.lower()] == entry.api_version


@pytest.mark.parametrize(
    "deployment_id",
    ["abc", "demo-eastus2", "a" * 63, "x-" * 31 + "y", "0-start-with-digit"],
)
def test_derived_names_satisfy_each_name_rule(deployment_id: str) -> None:
    for service, entry in ARM_SERVICES.items():
        name = arm_resource_name(service, deployment_id)
        entry.check_name(name)
        assert name == arm_resource_name(service, deployment_id)  # deterministic


def test_other_services_keep_the_generic_name() -> None:
    assert arm_resource_name("key_vault", "demo-eastus2") == "key_vault-demo-eastus2"


def test_create_body_carries_location_and_tags_and_no_secret() -> None:
    tags = creation_tags("demo-eastus2", "plan-1")
    assert tags[CREATED_BY_TAG] == "neurosphere"
    for entry in ARM_SERVICES.values():
        body = entry.create_body("eastus2", tags)
        assert body["location"] == "eastus2" and body["tags"] == tags
        text = json.dumps(body).lower()
        assert "key" not in text.replace("keyvault", "") and "password" not in text
        body["tags"]["x"] = "y"  # the table is never mutated through a body
        assert "x" not in entry.create_body("eastus2", tags)["tags"]


def test_storage_body_is_hardened() -> None:
    props = ARM_SERVICES["storage"].create_body("eastus2", {})["properties"]
    assert props == {
        "minimumTlsVersion": "TLS1_2",
        "allowBlobPublicAccess": False,
        "supportsHttpsTrafficOnly": True,
    }


def test_resource_ids_are_validated() -> None:
    entry = ARM_SERVICES["storage"]
    rid = entry.resource_id(SUB, "rg-ns", "nsstdemo")
    assert rid == (
        f"/subscriptions/{SUB}/resourceGroups/rg-ns/providers/Microsoft.Storage/storageAccounts/nsstdemo"
    )
    with pytest.raises(InvalidSchemaError):
        entry.resource_id(SUB, "rg-ns", "Not_Valid")
    with pytest.raises(InvalidSchemaError):
        resource_group_id("not-a-guid", "rg-ns")
    with pytest.raises(InvalidSchemaError):
        resource_group_id(SUB, "rg/../x")
