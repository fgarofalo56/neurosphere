"""action_kind -> write connector table and its resolver (PRP-17 item 4)."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from neurosphere_core.actions.targets import (
    ACTION_CONNECTORS,
    APIM_GATEWAY_CONNECTOR,
    TARGET_KIND_CONNECTORS,
    WriteTargetSource,
    connector_name_for,
    connector_names_for,
    resolve_write_target,
    resolve_write_targets,
)

_TARGETS = Path(__file__).resolve().parents[2] / "neurosphere_core" / "actions" / "targets.py"


class FakeRegistry:
    """Same shape as ``WriteTargetRegistry``: only writable connectors are ever registered."""

    def __init__(self, actions: dict[str, tuple[str, ...]]) -> None:
        self._actions = actions
        self.gets: list[str] = []

    def supports(self, name: str, action: str) -> bool:
        return action in self._actions.get(name, ())

    def get(self, name: str) -> str:
        self.gets.append(name)
        if name not in self._actions:
            raise LookupError(name)
        return f"connector:{name}"


def test_model_swap_maps_to_the_foundry_swap_connector() -> None:
    assert ACTION_CONNECTORS["model_deployment_swap"] == "foundry-model-swap"
    assert connector_name_for("model_deployment_swap") == "foundry-model-swap"


def test_table_is_read_only() -> None:
    with pytest.raises(TypeError):
        ACTION_CONNECTORS["budget_cap_change"] = "x"  # type: ignore[index]


def test_registered_connector_resolves() -> None:
    registry = FakeRegistry({"foundry-model-swap": ("model_deployment_swap",)})
    assert isinstance(registry, WriteTargetSource)
    assert resolve_write_target(registry, "model_deployment_swap") == "connector:foundry-model-swap"


@pytest.mark.parametrize(
    "registered",
    [
        {},  # read-only/unsupported: the advisory connector is never registered
        {"foundry-model-swap": ()},  # registered but does not declare the action
        {"foundry-model-swap-advisory": ("model_deployment_swap",)},  # some other name
    ],
)
def test_unresolvable_target_is_advisory(registered: dict[str, tuple[str, ...]]) -> None:
    registry = FakeRegistry(registered)
    assert resolve_write_target(registry, "model_deployment_swap") is None
    assert registry.gets == []  # never asks for a connector it was not told exists


def test_unknown_kind_is_advisory() -> None:
    registry = FakeRegistry({"foundry-model-swap": ("model_deployment_swap",)})
    assert connector_name_for("model_deployment_scale") is None
    assert connector_name_for("model_deployment_scale", "apim_backend") is None
    assert connector_names_for("model_deployment_scale") == ()
    assert resolve_write_target(registry, "model_deployment_scale") is None
    # A known APIM kind with no APIM connector registered is advisory too.
    assert resolve_write_target(registry, "budget_cap_change") is None


PRP34_KINDS = (
    "budget_cap_change",
    "grant_publish",
    "grant_unpublish",
    "mcp_server_publish",
    "mcp_server_unpublish",
    "gateway_mode_change",
)


@pytest.mark.parametrize("kind", PRP34_KINDS)
def test_prp34_kinds_map_to_the_apim_gateway_connector(kind: str) -> None:
    assert ACTION_CONNECTORS[kind] == APIM_GATEWAY_CONNECTOR == "apim-gateway"
    assert connector_names_for(kind) == ("apim-gateway",)


def test_target_kind_routes_model_swap_between_foundry_and_apim() -> None:
    assert TARGET_KIND_CONNECTORS["apim_backend"] == "apim-gateway"
    assert TARGET_KIND_CONNECTORS["grant"] == "apim-gateway"
    assert connector_name_for("model_deployment_swap", "model_deployment") == "foundry-model-swap"
    assert connector_name_for("model_deployment_swap", "apim_backend") == "apim-gateway"
    assert connector_name_for("budget_cap_change", "grant") == "apim-gateway"
    assert connector_names_for("model_deployment_swap") == ("foundry-model-swap", "apim-gateway")
    with pytest.raises(TypeError):
        TARGET_KIND_CONNECTORS["agent"] = "x"  # type: ignore[index]


def test_target_kind_resolution_uses_the_registry() -> None:
    registry = FakeRegistry(
        {
            "foundry-model-swap": ("model_deployment_swap",),
            "apim-gateway": ("model_deployment_swap", "budget_cap_change"),
        }
    )
    assert (
        resolve_write_target(registry, "model_deployment_swap", "apim_backend")
        == "connector:apim-gateway"
    )
    assert (
        resolve_write_target(registry, "model_deployment_swap", "model_deployment")
        == "connector:foundry-model-swap"
    )
    assert resolve_write_targets(registry, "model_deployment_swap") == {
        "foundry-model-swap": "connector:foundry-model-swap",
        "apim-gateway": "connector:apim-gateway",
    }
    only_foundry = FakeRegistry({"foundry-model-swap": ("model_deployment_swap",)})
    assert resolve_write_target(only_foundry, "model_deployment_swap", "apim_backend") is None
    assert resolve_write_targets(only_foundry, "budget_cap_change") == {}


def test_core_table_does_not_import_the_connector_sdk() -> None:
    tree = ast.parse(_TARGETS.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    assert not roots & {"neurosphere_connector", "neurosphere_api", "neurosphere_workers"}
