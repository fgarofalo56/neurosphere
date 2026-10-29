"""Which write connector backs an ``action_kind`` (PRP-17 item 4, delta D5; PRP-34 item 2).

:data:`ACTION_CONNECTORS` is the ONE table from action kind to connector manifest name. A kind
that is not in the table, or whose connector is not registered as a write target, or whose
registered connector does not declare the action, resolves to ``None``: the intent is advisory.
It may be drafted, validated and reviewed, but it never executes and nothing is changed anywhere
to stand in for the change (no catalog metadata edit).

:data:`TARGET_KIND_CONNECTORS` refines that table by the target's ``entity_type`` for target
kinds that only one connector can change: a ``model_deployment_swap`` against an ``apim_backend``
is executed by the APIM gateway connector, while the same kind against a Foundry
``model_deployment`` keeps its Foundry mapping. An override applies only to kinds that are in
:data:`ACTION_CONNECTORS` (an unknown kind stays advisory whatever its target).

Connector-agnostic: core never imports ``neurosphere_connector``. :class:`WriteTargetSource` is
the structural shape of ``neurosphere_connector.write.WriteTargetRegistry`` (``supports`` plus
``get``), which only ever holds connectors with real write support (it rejects advisory ones at
registration), so "not registered" is exactly "read-only or unsupported".
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final, Protocol, runtime_checkable

__all__ = [
    "ACTION_CONNECTORS",
    "APIM_GATEWAY_CONNECTOR",
    "FOUNDRY_SWAP_CONNECTOR",
    "TARGET_KIND_CONNECTORS",
    "WriteTargetSource",
    "connector_name_for",
    "connector_names_for",
    "resolve_write_target",
    "resolve_write_targets",
]

FOUNDRY_SWAP_CONNECTOR: Final = "foundry-model-swap"
APIM_GATEWAY_CONNECTOR: Final = "apim-gateway"

#: action_kind -> write connector manifest name. Add a row only for a shipped write connector.
ACTION_CONNECTORS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "model_deployment_swap": FOUNDRY_SWAP_CONNECTOR,
        # PRP-34: the APIM AI gateway write connector (Clarification 10) and the audited
        # observe -> manage switch (item 2).
        "budget_cap_change": APIM_GATEWAY_CONNECTOR,
        "grant_publish": APIM_GATEWAY_CONNECTOR,
        "grant_unpublish": APIM_GATEWAY_CONNECTOR,
        "mcp_server_publish": APIM_GATEWAY_CONNECTOR,
        "mcp_server_unpublish": APIM_GATEWAY_CONNECTOR,
        "gateway_mode_change": APIM_GATEWAY_CONNECTOR,
    }
)

#: target entity_type -> connector manifest name, overriding ACTION_CONNECTORS for that target.
TARGET_KIND_CONNECTORS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "apim_backend": APIM_GATEWAY_CONNECTOR,
        "grant": APIM_GATEWAY_CONNECTOR,
    }
)


@runtime_checkable
class WriteTargetSource[T](Protocol):
    """Registry of connectors accepted as action targets, keyed by manifest name."""

    def supports(self, name: str, action: str) -> bool:
        """True when ``name`` is registered and its manifest declares ``action``."""
        ...

    def get(self, name: str) -> T:
        """The registered connector; raises when ``name`` is not registered."""
        ...


def connector_name_for(action_kind: str, target_kind: str | None = None) -> str | None:
    """Manifest name of the connector for ``action_kind`` on ``target_kind``, or ``None``.

    Without ``target_kind`` this is the kind's default connector.
    """
    default = ACTION_CONNECTORS.get(action_kind)
    if default is None:
        return None
    if target_kind is not None:
        return TARGET_KIND_CONNECTORS.get(target_kind, default)
    return default


def connector_names_for(action_kind: str) -> tuple[str, ...]:
    """Every connector that may execute ``action_kind`` (default first, then overrides)."""
    default = ACTION_CONNECTORS.get(action_kind)
    if default is None:
        return ()
    extra = sorted(set(TARGET_KIND_CONNECTORS.values()) - {default})
    return (default, *extra)


def resolve_write_target[T](
    source: WriteTargetSource[T], action_kind: str, target_kind: str | None = None
) -> T | None:
    """The write connector for ``action_kind`` (on ``target_kind``), or ``None`` (advisory).

    ``supports`` is asked first, so ``get`` is only called for a registered connector that
    declares the action; an unexpected ``get`` failure propagates (it is not "advisory").
    """
    name = connector_name_for(action_kind, target_kind)
    if name is None or not source.supports(name, action_kind):
        return None
    return source.get(name)


def resolve_write_targets[T](source: WriteTargetSource[T], action_kind: str) -> dict[str, T]:
    """Every registered connector that declares ``action_kind``, by manifest name."""
    return {
        name: source.get(name)
        for name in connector_names_for(action_kind)
        if source.supports(name, action_kind)
    }
