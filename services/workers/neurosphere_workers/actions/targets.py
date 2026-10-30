"""``action_kind`` (and target kind) -> write connector resolution for the executor.

An intent names an ``action_kind``; the executor maps it to a connector manifest name with a
small table, refined by the target's ``entity_type`` through core's ``TARGET_KIND_CONNECTORS``
(PRP-34: a ``model_deployment_swap`` on an ``apim_backend`` and a ``budget_cap_change`` on a
``grant`` reach the APIM gateway connector; the same swap on a Foundry ``model_deployment`` keeps
its Foundry mapping), and looks the connector up in the injected PRP-09
:class:`WriteTargetRegistry` (which already refuses advisory and write-less connectors at
registration). Resolution additionally requires the connector's manifest to list the
``action_kind`` in ``write_support.actions`` and the connector to report ``advisory=False`` at
run time. Anything else is ``capability_unavailable`` and the executor fails the intent WITHOUT a
connector call (the API should never let such an intent reach ``executing``; this is defence in
depth).

:func:`check_gateway_binding` is the extra check for the APIM gateway connector (PRP-34 item 2
review): the connector is bound to ONE registered gateway, but a ``WriteRequest`` carries no
domain, so the executor asserts the gateway is registered in the intent's own domain before any
connector call (``gateway_domain_mismatch``; an unknown gateway is ``gateway_not_registered``).
With the intent at hand it also ties the diff grammar to the action kind through the connector's
``check_action`` (PRP-34 item 10: ``WriteRequest`` carries no kind, so e.g. a ``remove`` stage
under ``mcp_server_publish`` or an unpublish diff under ``grant_publish`` is refused here,
``action_kind_mismatch``, before any connector call).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Final

from neurosphere_connector.write import WriteConnector, WriteRequest, WriteTargetRegistry
from neurosphere_contracts.actions.v1.action_intent import ActionIntent
from neurosphere_core.actions.targets import (
    ACTION_CONNECTORS,
    APIM_GATEWAY_CONNECTOR,
    TARGET_KIND_CONNECTORS,
)
from neurosphere_core.errors import CapabilityUnavailableError, InvalidSchemaError
from neurosphere_core.gateway.mode import GATEWAY_NOT_REGISTERED
from neurosphere_core.gateway.models import GATEWAY_ID_PATTERN
from neurosphere_core.gateway.store import GatewayModeLookup

__all__ = [
    "ACTION_KIND_MISMATCH",
    "DEFAULT_ACTION_CONNECTORS",
    "GATEWAY_DOMAIN_MISMATCH",
    "GATEWAY_LOOKUP_UNCONFIGURED",
    "check_gateway_binding",
    "connector_name",
    "resolve_connector",
]

#: The ONE action-kind table lives in core (item 4); this is an alias of that same object.
#: Extend by passing a mapping to the executor.
DEFAULT_ACTION_CONNECTORS: Final[Mapping[str, str]] = ACTION_CONNECTORS
GATEWAY_DOMAIN_MISMATCH: Final = "gateway_domain_mismatch"
GATEWAY_LOOKUP_UNCONFIGURED: Final = "gateway_lookup_unconfigured"
ACTION_KIND_MISMATCH: Final = "action_kind_mismatch"
_GATEWAY_ID: Final = re.compile(GATEWAY_ID_PATTERN)


def _unavailable(detail: str, reason: str = "capability_unavailable") -> CapabilityUnavailableError:
    return CapabilityUnavailableError(reason, detail)


def connector_name(
    table: Mapping[str, str], action_kind: str, target_kind: str | None = None
) -> str | None:
    """Manifest name for ``action_kind`` on ``target_kind``; only kinds in ``table`` resolve."""
    name = table.get(action_kind)
    if name is None or target_kind is None:
        return name
    return TARGET_KIND_CONNECTORS.get(target_kind, name)


def resolve_connector(
    registry: WriteTargetRegistry,
    table: Mapping[str, str],
    action_kind: str,
    target_kind: str | None = None,
) -> WriteConnector:
    """The connector that executes ``action_kind`` on ``target_kind``, or unavailable."""
    name = connector_name(table, action_kind, target_kind)
    if name is None:
        raise _unavailable("no write connector is mapped to this action kind")
    if not registry.supports(name, action_kind):
        raise _unavailable("the mapped connector is not a write target for this action")
    connector = registry.get(name)
    if connector.advisory or connector.manifest.advisory:
        raise _unavailable("the mapped connector is advisory")
    return connector


def _bound_gateway_id(connector: WriteConnector) -> str:
    gateway_id = getattr(getattr(connector, "gateway", None), "gateway_id", None)
    if not isinstance(gateway_id, str) or not _GATEWAY_ID.fullmatch(gateway_id):
        raise _unavailable("the APIM connector is not bound to a gateway", "gateway_unresolved")
    return gateway_id


async def check_gateway_binding(
    connector: WriteConnector,
    lookup: GatewayModeLookup | None,
    *,
    customer_id: str,
    domain_id: str,
    intent: ActionIntent | None = None,
) -> None:
    """Refuse an APIM connector whose gateway is not registered in the intent's domain, or
    (given ``intent``) whose diff grammar does not belong to the intent's action kind.

    No-op for every other connector. Fails closed: without a gateway lookup an APIM intent never
    runs (``gateway_lookup_unconfigured``). A store outage propagates (the pass is deferred). A
    grammar refusal is final (``action_kind_mismatch``), never retried.
    """
    if connector.manifest.name != APIM_GATEWAY_CONNECTOR:
        return
    if lookup is None:
        raise _unavailable("the gateway registry is not wired", GATEWAY_LOOKUP_UNCONFIGURED)
    registration = await lookup.find(customer_id, _bound_gateway_id(connector))
    if registration is None:
        raise _unavailable(
            "the gateway is not registered for this customer", GATEWAY_NOT_REGISTERED
        )
    if registration.domain_id != domain_id:
        raise _unavailable(
            "the gateway is registered in another domain than the intent", GATEWAY_DOMAIN_MISMATCH
        )
    check = getattr(connector, "check_action", None)
    if intent is None or not callable(check):
        return
    request = WriteRequest(
        target=intent.target,
        target_version=intent.target_version,
        proposed_diff=intent.proposed_diff,
    )
    try:
        check(intent.action_kind, request)
    except InvalidSchemaError:
        raise _unavailable(
            "the diff does not belong to the intent's action kind", ACTION_KIND_MISMATCH
        ) from None
