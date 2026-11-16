"""PRP-54 item 1: keyed resolution; the unkeyed call shape is unchanged."""

from __future__ import annotations

from neurosphere_core.actions.targets import resolve_write_target, resolve_write_targets


class KeyedRegistry:
    def __init__(self, held: dict[tuple[str, str | None], str]) -> None:
        self._held = held
        self.calls: list[tuple[str, str | None]] = []

    def supports(self, name: str, action: str, *, target_key: str | None = None) -> bool:
        return (name, target_key) in self._held and (
            name != "apim-gateway" or action != "model_deployment_swap"
        )

    def get(self, name: str, *, target_key: str | None = None) -> str:
        self.calls.append((name, target_key))
        return self._held[(name, target_key)]


class LegacyRegistry:
    """A source that predates the key: its methods take no ``target_key``."""

    def supports(self, name: str, action: str) -> bool:
        return name == "apim-gateway"

    def get(self, name: str) -> str:
        return f"legacy:{name}"


def test_key_selects_the_domain_target() -> None:
    reg = KeyedRegistry({("apim-gateway", "dom-a"): "gw-a", ("apim-gateway", "dom-b"): "gw-b"})
    assert resolve_write_target(reg, "gateway_mode_change", target_key="dom-b") == "gw-b"
    assert resolve_write_target(reg, "gateway_mode_change", target_key="dom-a") == "gw-a"


def test_domain_without_target_is_advisory() -> None:
    reg = KeyedRegistry({("apim-gateway", "dom-a"): "gw-a"})
    assert resolve_write_target(reg, "gateway_mode_change", target_key="dom-c") is None
    assert reg.calls == []


def test_unkeyed_call_shape_is_unchanged() -> None:
    assert resolve_write_target(LegacyRegistry(), "gateway_mode_change") == "legacy:apim-gateway"
    assert resolve_write_targets(LegacyRegistry(), "gateway_mode_change") == {
        "apim-gateway": "legacy:apim-gateway"
    }


def test_resolve_targets_keyed() -> None:
    reg = KeyedRegistry({("apim-gateway", "dom-a"): "gw-a", ("foundry-model-swap", "dom-a"): "f"})
    assert resolve_write_targets(reg, "model_deployment_swap", target_key="dom-a") == {
        "foundry-model-swap": "f"
    }
