"""Executor-side composition of the APIM gateway write connector (PRP-34 items 2 and 3).

The worker is the only place that applies and rolls back (PRP-17 D5), so this is where the APIM
connector is assembled with everything that makes it safe:

* the durable, append-only apply-record store (``CosmosGatewayRecordStore`` over the connector's
  ``ApplyRecord``, same container and partition as the gateway registration); the same store is
  the mode switch's ``ActivityProbe``, so a running apply OR rollback blocks a mode change;
* the ``GatewayModeHandler`` (permissions preflight, audited observe/manage flip) which the
  connector REQUIRES: every resource plan asks it first and an observe-mode gateway is refused
  with ``gateway_observe_mode`` before any ARM call;
* the advisory connector instead of the write connector where manage is disabled (Government),
  which the ``WriteTargetRegistry`` refuses to register, so such intents fail closed.

Wire the registration's store as the executor's ``gateways`` lookup too: the executor checks that
the connector's gateway is registered in the intent's domain before any connector call. The
connector is bound to ONE gateway (as on the API side); the canary probe for the same gateway is
:class:`~neurosphere_workers.actions.apim_canary.ApimBackendCanaryProbe`.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

from azure.cosmos.aio import CosmosClient
from neurosphere_connector_apim_gateway import (
    ApimArm,
    ApimGatewayAdvisoryConnector,
    ApimGatewayConnector,
    ApimPermissionsReader,
    ApplyRecord,
    ApplyRecordStore,
    GatewayModeHandler,
    GatewayRef,
    IntentTranslator,
    create_apim_connector,
)
from neurosphere_core.cloud.profile import CloudName
from neurosphere_core.gateway import CosmosGatewayRecordStore, GatewayRegistration, GatewayStore
from neurosphere_core.gateway.mode import ActivityProbe, GatewayModeSwitch

__all__ = [
    "ApplyRecords",
    "GatewayArm",
    "apim_gateway_ref",
    "apim_record_store",
    "build_apim_gateway_connector",
]


@runtime_checkable
class GatewayArm(ApimArm, ApimPermissionsReader, Protocol):
    """ARM access to one APIM service: resource tree plus the permissions read (preflight)."""


@runtime_checkable
class ApplyRecords(ApplyRecordStore, ActivityProbe, Protocol):
    """The connector's record store that also answers ``running`` for the mode switch."""


def _utc_now() -> datetime:
    return datetime.now(UTC)


def apim_gateway_ref(registration: GatewayRegistration) -> GatewayRef:
    return GatewayRef(
        gateway_id=registration.id,
        cloud=CloudName(registration.cloud),
        arm_resource_id=registration.arm_resource_id,
    )


def apim_record_store(
    client: CosmosClient, *, database: str, registration: GatewayRegistration
) -> CosmosGatewayRecordStore[ApplyRecord]:
    """Durable apply records in the registration's own ``gateways`` partition."""
    return CosmosGatewayRecordStore.from_client(
        client,
        database=database,
        customer_id=registration.customer_id,
        domain_id=registration.domain_id,
        model=ApplyRecord,
    )


def build_apim_gateway_connector(
    registration: GatewayRegistration,
    arm: GatewayArm,
    *,
    store: GatewayStore,
    records: ApplyRecords,
    translators: Sequence[IntentTranslator] = (),
    clock: Callable[[], datetime] | None = None,
) -> ApimGatewayConnector | ApimGatewayAdvisoryConnector:
    """The write connector for ``registration`` with the mode guard and durable records wired.

    ``translators`` adds target kinds (``apim_backend`` swaps, ``grant`` caps, ...). Register
    the result in the executor's ``WriteTargetRegistry``; an advisory result is refused there.
    """
    gateway = apim_gateway_ref(registration)
    switch = GatewayModeSwitch(
        store,
        customer_id=registration.customer_id,
        domain_id=registration.domain_id,
        gateway_id=registration.id,
        activity=records,
        clock=clock or _utc_now,
    )
    return create_apim_connector(
        gateway,
        arm,
        records=records,
        mode=GatewayModeHandler(gateway, arm, switch),
        translators=translators,
    )
