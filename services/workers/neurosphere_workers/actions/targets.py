"""``action_kind`` -> write connector resolution for the executor.

An intent names an ``action_kind``; the executor maps it to a connector manifest name with a
small table and looks the connector up in the injected PRP-09 :class:`WriteTargetRegistry` (which
already refuses advisory and write-less connectors at registration). Resolution additionally
requires the connector's manifest to list the ``action_kind`` in ``write_support.actions`` and
the connector to report ``advisory=False`` at run time. Anything else is ``capability_unavailable``
and the executor fails the intent WITHOUT a connector call (the API should never let such an
intent reach ``executing``; this is defence in depth).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from neurosphere_connector.write import WriteConnector, WriteTargetRegistry
from neurosphere_core.actions.targets import ACTION_CONNECTORS
from neurosphere_core.errors import CapabilityUnavailableError

__all__ = ["DEFAULT_ACTION_CONNECTORS", "resolve_connector"]

#: The ONE action-kind table lives in core (item 4); this is an alias of that same object.
#: Extend by passing a mapping to the executor.
DEFAULT_ACTION_CONNECTORS: Final[Mapping[str, str]] = ACTION_CONNECTORS


def _unavailable(detail: str) -> CapabilityUnavailableError:
    return CapabilityUnavailableError("capability_unavailable", detail)


def resolve_connector(
    registry: WriteTargetRegistry, table: Mapping[str, str], action_kind: str
) -> WriteConnector:
    """The connector that executes ``action_kind``, or ``capability_unavailable``."""
    name = table.get(action_kind)
    if name is None:
        raise _unavailable("no write connector is mapped to this action kind")
    if not registry.supports(name, action_kind):
        raise _unavailable("the mapped connector is not a write target for this action")
    connector = registry.get(name)
    if connector.advisory or connector.manifest.advisory:
        raise _unavailable("the mapped connector is advisory")
    return connector
