"""action_kind -> write connector table and its resolver (PRP-17 item 4)."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from neurosphere_core.actions.targets import (
    ACTION_CONNECTORS,
    WriteTargetSource,
    connector_name_for,
    resolve_write_target,
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
    assert connector_name_for("budget_cap_change") is None
    assert resolve_write_target(registry, "budget_cap_change") is None


def test_core_table_does_not_import_the_connector_sdk() -> None:
    tree = ast.parse(_TARGETS.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    assert not roots & {"neurosphere_connector", "neurosphere_api", "neurosphere_workers"}
