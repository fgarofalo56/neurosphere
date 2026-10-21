"""Which write connector backs an ``action_kind`` (PRP-17 item 4, delta D5).

:data:`ACTION_CONNECTORS` is the ONE table from action kind to connector manifest name. A kind
that is not in the table, or whose connector is not registered as a write target, or whose
registered connector does not declare the action, resolves to ``None``: the intent is advisory.
It may be drafted, validated and reviewed, but it never executes and nothing is changed anywhere
to stand in for the change (no catalog metadata edit).

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
    "WriteTargetSource",
    "connector_name_for",
    "resolve_write_target",
]

#: action_kind -> write connector manifest name. Add a row only for a shipped write connector.
ACTION_CONNECTORS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "model_deployment_swap": "foundry-model-swap",
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


def connector_name_for(action_kind: str) -> str | None:
    """Manifest name of the connector for ``action_kind``, or ``None`` (advisory)."""
    return ACTION_CONNECTORS.get(action_kind)


def resolve_write_target[T](source: WriteTargetSource[T], action_kind: str) -> T | None:
    """The write connector for ``action_kind``, or ``None`` when the intent is advisory.

    ``supports`` is asked first, so ``get`` is only called for a registered connector that
    declares the action; an unexpected ``get`` failure propagates (it is not "advisory").
    """
    name = connector_name_for(action_kind)
    if name is None or not source.supports(name, action_kind):
        return None
    return source.get(name)
