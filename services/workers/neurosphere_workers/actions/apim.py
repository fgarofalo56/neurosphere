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

Default translators (PRP-34 item 10): every composed connector registers the connector's
``default_translators``: backend swaps (``apim_backend``), the ``grant`` dispatcher (budget cap
vs publication by diff grammar; the cap edits the publication's own fragment; an unpublish is
checked against this very apply-record store) and MCP publication (``mcp_server``) with the
gateway's API path index (``HttpApiPathIndex`` over the same ARM client, see
:func:`build_http_apim_gateway_connector`; without one an MCP publish is refused, never guessed).

Post-success publication recording (PRP-34 item 10): :class:`PublicationRecordingExecutor` is the
executor with one step AROUND it, never inside it. After ``ActionExecutor.execute`` has returned
(every phase, audit record and state transition done) and the intent is a ``succeeded``,
verified, non-dry-run Grant or McpServer publication executed by this connector, it hands the
stored intent to an injected recorder (the catalog side,
``neurosphere_workers.publication.CatalogPublicationRecorder``). The recorder is idempotent; its
failure never changes the intent, the gateway or the outcome: it is audited
(``catalog.publication_record`` ``failed``), logged, and surfaced on the report as reason
``publication_record_failed``, and the catalog routes stay the manual retry path.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, Final, Protocol, runtime_checkable

import httpx
from azure.cosmos.aio import CosmosClient
from neurosphere_connector.write import WriteTargetRegistry
from neurosphere_connector_apim_gateway import (
    ApimArm,
    ApimGatewayAdvisoryConnector,
    ApimGatewayConnector,
    ApimPermissionsReader,
    ApplyRecord,
    ApplyRecordStore,
    GatewayModeHandler,
    GatewayRef,
    HttpApimArm,
    IntentTranslator,
    create_apim_connector,
    default_translators,
)
from neurosphere_connector_apim_gateway.mcp import ApiPathIndex, HttpApiPathIndex
from neurosphere_contracts.actions.v1.actor import Actor
from neurosphere_core.actions import (
    ActionAuditEvent,
    ActionAuditor,
    ActionService,
    IntentKey,
    StoredIntent,
)
from neurosphere_core.actions.targets import APIM_GATEWAY_CONNECTOR
from neurosphere_core.audit.canonical import sha256_digest
from neurosphere_core.cloud.profile import CloudName, CloudProfile
from neurosphere_core.errors import NeuroSphereError
from neurosphere_core.gateway import (
    DEFAULT_GATEWAY_CONTAINER,
    CosmosGatewayRecordStore,
    GatewayRegistration,
    GatewayStore,
)
from neurosphere_core.gateway.mode import ActivityProbe, GatewayModeSwitch

from neurosphere_workers.actions.executor import ActionExecutor, ExecutionReport, logger
from neurosphere_workers.actions.targets import DEFAULT_ACTION_CONNECTORS, connector_name

__all__ = [
    "PUBLICATION_KINDS",
    "PUBLICATION_RECORD_FAILED",
    "PUBLICATION_RECORD_OPERATION",
    "ApplyRecords",
    "GatewayArm",
    "PublicationRecorder",
    "PublicationRecordingExecutor",
    "apim_gateway_ref",
    "apim_record_store",
    "build_apim_gateway_connector",
    "build_http_apim_gateway_connector",
    "recordable_publication",
]

#: Action kind -> the catalog target kind whose entity records the publication.
PUBLICATION_KINDS: Final = {
    "grant_publish": "grant",
    "grant_unpublish": "grant",
    "mcp_server_publish": "mcp_server",
    "mcp_server_unpublish": "mcp_server",
}
PUBLICATION_RECORD_FAILED: Final = "publication_record_failed"
PUBLICATION_RECORD_OPERATION: Final = "catalog.publication_record"
_SYSTEM_ACTOR: Final = Actor(
    principal_pseudonym="svc.neurosphere-actions",
    principal_kind="service_principal",
    on_behalf_of=None,
)
_SYSTEM_SCOPE_HASH: Final = sha256_digest({"system_scope": "neurosphere.actions.publication"})


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
    client: CosmosClient,
    *,
    database: str,
    registration: GatewayRegistration,
    container: str = DEFAULT_GATEWAY_CONTAINER,
) -> CosmosGatewayRecordStore[ApplyRecord]:
    """Durable apply records in the registration's own ``gateways`` partition (the API reads
    the same partition through ``neurosphere_workers.publication.CosmosApplyRecordLookup``)."""
    return CosmosGatewayRecordStore.from_client(
        client,
        database=database,
        customer_id=registration.customer_id,
        domain_id=registration.domain_id,
        model=ApplyRecord,
        container=container,
    )


def build_apim_gateway_connector(
    registration: GatewayRegistration,
    arm: GatewayArm,
    *,
    store: GatewayStore,
    records: ApplyRecords,
    translators: Sequence[IntentTranslator] = (),
    api_paths: ApiPathIndex | None = None,
    clock: Callable[[], datetime] | None = None,
) -> ApimGatewayConnector | ApimGatewayAdvisoryConnector:
    """The write connector for ``registration`` with the mode guard, durable records and the
    default translators wired (``default_translators(records=records, paths=api_paths)``).

    ``translators`` are registered after the defaults and replace them per target kind (tests,
    a canary percentage). Register the result in the executor's ``WriteTargetRegistry``; an
    advisory result is refused there.
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
        translators=[*default_translators(records=records, paths=api_paths), *translators],
    )


def build_http_apim_gateway_connector(
    registration: GatewayRegistration,
    client: httpx.AsyncClient,
    *,
    profile: CloudProfile,
    store: GatewayStore,
    records: ApplyRecords,
    clock: Callable[[], datetime] | None = None,
) -> ApimGatewayConnector | ApimGatewayAdvisoryConnector:
    """Production composition over ARM REST: one bearer-authenticated ARM client (bound to the
    deployment cloud) for the resource tree, the permissions preflight AND the MCP API path
    index (``HttpApiPathIndex(client, registration.arm_resource_id)``)."""
    arm = HttpApimArm(client, registration.arm_resource_id, profile=profile)
    return build_apim_gateway_connector(
        registration,
        arm,
        store=store,
        records=records,
        api_paths=HttpApiPathIndex(client, registration.arm_resource_id),
        clock=clock,
    )


# -- post-success publication recording (outside the executor phases) -------------------------


@runtime_checkable
class PublicationRecorder(Protocol):
    async def record(self, stored: StoredIntent) -> object:
        """Record a succeeded, verified publication on its catalog entity; idempotent."""
        ...


def recordable_publication(stored: StoredIntent, table: Mapping[str, str] | None = None) -> bool:
    """True only for a succeeded, verified, non-dry-run, non-advisory Grant or McpServer
    publication intent that the APIM gateway connector executed."""
    intent = stored.intent
    execution = stored.execution
    entity_type = PUBLICATION_KINDS.get(intent.action_kind)
    return (
        entity_type is not None
        and intent.target.entity_type == entity_type
        and connector_name(
            DEFAULT_ACTION_CONNECTORS if table is None else table,
            intent.action_kind,
            intent.target.entity_type,
        )
        == APIM_GATEWAY_CONNECTOR
        and stored.state == "succeeded"
        and not intent.dry_run
        and not stored.advisory
        and execution is not None
        and execution.verify_matched is True
        and execution.apply_result is not None
    )


def _reason(exc: BaseException) -> str:
    if isinstance(exc, NeuroSphereError):
        reason = exc.reason if isinstance(exc.reason, str) and exc.reason else exc.code
        return str(reason)[:64]
    return "recorder_error"


class PublicationRecordingExecutor(ActionExecutor):
    """``ActionExecutor`` plus the post-success catalog hand-off (see the module docstring).

    Runs the executor unchanged, then, for a recordable publication, calls ``recorder``. Never
    raises for a recording failure and never changes the intent, the target or the outcome.
    """

    def __init__(
        self,
        service: ActionService,
        registry: WriteTargetRegistry,
        *,
        recorder: PublicationRecorder,
        auditor: ActionAuditor,
        **options: Any,
    ) -> None:
        super().__init__(service, registry, **options)
        if not isinstance(recorder, PublicationRecorder):
            raise TypeError("recorder must implement record(stored)")
        if not isinstance(auditor, ActionAuditor):
            raise TypeError("an auditor is required: a recording failure is always audited")
        self._intents = service
        self._recorder = recorder
        self._publication_auditor = auditor
        table = options.get("action_connectors")
        self._publication_table = dict(table) if table is not None else None

    async def execute(self, key: IntentKey) -> ExecutionReport:
        report = await super().execute(key)
        if report.state != "succeeded":
            return report
        try:
            stored = await self._intents.get(key)
        except Exception as exc:
            return await self._failed(key, None, report, exc)
        if not recordable_publication(stored, self._publication_table):
            return report
        try:
            await self._recorder.record(stored)
        except Exception as exc:
            return await self._failed(key, stored, report, exc)
        return report

    async def _failed(
        self,
        key: IntentKey,
        stored: StoredIntent | None,
        report: ExecutionReport,
        exc: BaseException,
    ) -> ExecutionReport:
        reason = _reason(exc)
        logger.warning(
            "publication record failed; the applied change stands",
            extra={
                "event": "action.publication_record_failed",
                "intent_id": key.intent_id,
                "reason": reason,
            },
        )
        if stored is not None:
            try:
                await self._publication_auditor.record(
                    ActionAuditEvent(
                        kind="after",
                        operation=PUBLICATION_RECORD_OPERATION,
                        actor=_SYSTEM_ACTOR,
                        scope_hash=_SYSTEM_SCOPE_HASH,
                        correlation_id=f"publication-{stored.intent_id[:8]}",
                        channel=None,
                        customer_id=stored.customer_id,
                        domain_id=stored.domain_id,
                        intent_id=stored.intent_id,
                        target=stored.intent.target,
                        target_version=stored.intent.target_version,
                        result="failed",
                        reason=reason,
                    )
                )
            except Exception:
                logger.warning(
                    "publication record audit failed",
                    extra={
                        "event": "action.publication_record_audit_failed",
                        "intent_id": key.intent_id,
                    },
                )
        return dataclasses.replace(report, reason=PUBLICATION_RECORD_FAILED)
