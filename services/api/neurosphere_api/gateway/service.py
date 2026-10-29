"""Gateway registry flows: register (read-only preflight), list/detail, inventory, sync.

Permission and domain scope are enforced by the router before any method here runs. The only
writes are to NeuroSphere's own store; the customer's gateway is only ever read (GET) through the
cloud-pinned ARM client. Register and sync are audited on the ``<customer>.gateway`` chain
(before record, change, after record; a failed audit write aborts). Audit records carry the
actor pseudonym, the gateway id and short codes; the ARM id is only hashed into the state digest.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final

from fastapi import HTTPException
from neurosphere_core.audit import (
    AuditContext,
    AuditDraft,
    build_after,
    build_before,
    make_subject,
    run_audited_mutation,
)
from neurosphere_core.cloud import CloudName, CloudProfile, profile_for
from neurosphere_core.errors import NeuroSphereError
from neurosphere_core.gateway import (
    GatewayInventory,
    GatewayRegistration,
    gateway_id_for,
    preflight,
    read_inventory,
)
from neurosphere_core.gateway.capability import capabilities_for, coverage_for
from neurosphere_core.scope import IdentityScope

from neurosphere_api.gateway.dependencies import GatewayPlane
from neurosphere_api.gateway.models import GatewayDetail, GatewayList, RegisterGatewayBody

__all__ = ["CHAIN_SUFFIX", "ENTITY_TYPE", "GatewayApi", "audit_chain_id"]

CHAIN_SUFFIX: Final = "gateway"
ENTITY_TYPE: Final = "apim_gateway"


def audit_chain_id(customer_id: str) -> str:
    return f"{customer_id}.{CHAIN_SUFFIX}"


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="not found")


def _code(exc: BaseException) -> str:
    reason = getattr(exc, "reason", None)
    return reason if isinstance(reason, str) and reason else "error"


def _profile(scope: IdentityScope) -> CloudProfile:
    return profile_for(CloudName(scope.cloud))


class GatewayApi:
    def __init__(self, plane: GatewayPlane) -> None:
        self._plane = plane

    # -- views -----------------------------------------------------------------------------

    def _fresh(self, registration: GatewayRegistration) -> GatewayRegistration:
        if registration.last_sync_at is None:
            return registration
        age = max(0, int((self._plane.now() - registration.last_sync_at).total_seconds()))
        return registration.model_copy(update={"freshness_seconds": age})

    async def _load(
        self, scope: IdentityScope, domain: str, gateway_id: str
    ) -> GatewayRegistration:
        found = await self._plane.store.get(scope.customer_id, domain, gateway_id)
        if found is None:
            raise _not_found()
        return found

    # -- reads -----------------------------------------------------------------------------

    async def list(
        self, scope: IdentityScope, domain: str, *, cursor: str | None, limit: int
    ) -> GatewayList:
        page = await self._plane.store.list(scope.customer_id, domain, cursor=cursor, limit=limit)
        return GatewayList(items=[self._fresh(r) for r in page.items], next_cursor=page.next_cursor)

    async def detail(self, scope: IdentityScope, domain: str, gateway_id: str) -> GatewayDetail:
        registration = self._fresh(await self._load(scope, domain, gateway_id))
        inventory = await self._plane.store.get_inventory(scope.customer_id, domain, gateway_id)
        return GatewayDetail(
            **registration.model_dump(),
            inventory_counts=None if inventory is None else inventory.counts(),
            inventory_taken_at=None if inventory is None else inventory.taken_at.isoformat(),
        )

    async def inventory(
        self, scope: IdentityScope, domain: str, gateway_id: str
    ) -> GatewayInventory:
        await self._load(scope, domain, gateway_id)
        found = await self._plane.store.get_inventory(scope.customer_id, domain, gateway_id)
        if found is None:
            raise _not_found()
        return found

    # -- audit -----------------------------------------------------------------------------

    @staticmethod
    def _audited_parts(
        scope: IdentityScope, correlation_id: str, operation: str, gateway_id: str
    ) -> tuple[AuditContext, str]:
        ctx = AuditContext.from_scope(
            scope, correlation_id=correlation_id, operation=operation, channel="rest"
        )
        subject_id = f"{scope.cloud}:{scope.customer_id}:neurosphere:{ENTITY_TYPE}:{gateway_id}"
        return ctx, subject_id

    # -- register --------------------------------------------------------------------------

    async def register(
        self, scope: IdentityScope, domain: str, body: RegisterGatewayBody, correlation_id: str
    ) -> GatewayRegistration:
        plane = self._plane
        profile = _profile(scope)
        gateway_id = gateway_id_for(scope.customer_id, domain, body.arm_resource_id)
        ctx, subject_id = self._audited_parts(scope, correlation_id, "gateway.register", gateway_id)
        async with plane.arm_factory(profile) as client:
            pre = await preflight(
                client,
                body.arm_resource_id,
                api_version=plane.settings.arm_api_version,
                profile=profile,
            )
        capabilities = capabilities_for(pre.tier, scope.cloud)
        now = plane.now()
        registration = GatewayRegistration(
            id=gateway_id,
            customer_id=scope.customer_id,
            domain_id=domain,
            cloud=CloudName(scope.cloud).value,  # type: ignore[arg-type]
            arm_resource_id=body.arm_resource_id,
            name=pre.name,
            tier=pre.tier,
            sku_name_raw=pre.sku_name_raw,
            workspace_id=body.workspace_id,
            diagnostics=pre.diagnostics,
            capabilities=capabilities,
            coverage=coverage_for(capabilities, pre.diagnostics),
            created_at=now,
            updated_at=now,
            registered_by=ctx.actor.principal_pseudonym,
        )
        state = {"tier": pre.tier, "mode": "observe", "arm_resource_id": body.arm_resource_id}

        def after(saved: GatewayRegistration) -> AuditDraft:
            subject = make_subject(subject_id, ENTITY_TYPE, state=state)
            return build_after(
                ctx,
                subject,
                result="succeeded",
                verified=True,
                detail=f"registered:tier={saved.tier}",
            )

        def failed(exc: BaseException) -> AuditDraft:
            subject = make_subject(subject_id, ENTITY_TYPE, state=state)
            return build_after(ctx, subject, result="failed", verified=False, detail=_code(exc))

        return await run_audited_mutation(
            plane.audit,
            _chain(scope),
            before=build_before(ctx, make_subject(subject_id, ENTITY_TYPE, state=state)),
            mutate=lambda: plane.store.create(registration),
            after=after,
            on_error=failed,
        )

    # -- sync ------------------------------------------------------------------------------

    async def sync(
        self, scope: IdentityScope, domain: str, gateway_id: str, correlation_id: str
    ) -> GatewayDetail:
        plane = self._plane
        current = await self._load(scope, domain, gateway_id)
        profile = _profile(scope)
        ctx, subject_id = self._audited_parts(scope, correlation_id, "gateway.sync", gateway_id)
        state = {"operation": "sync", "mode": "observe"}
        counts: dict[str, int] = {}

        async def mutate() -> GatewayRegistration:
            try:
                async with plane.arm_factory(profile) as client:
                    pre = await preflight(
                        client,
                        current.arm_resource_id,
                        api_version=plane.settings.arm_api_version,
                        profile=profile,
                    )
                    taken = plane.now()
                    inventory = await read_inventory(
                        client,
                        current.arm_resource_id,
                        api_version=plane.settings.arm_api_version,
                        profile=profile,
                        gateway_id=gateway_id,
                        now=taken,
                    )
            except NeuroSphereError:
                await self._record_failure(current)
                raise
            capabilities = capabilities_for(pre.tier, scope.cloud)
            # Replace, never merge: the snapshot is stored whole, then the registration moves.
            await plane.store.put_inventory(scope.customer_id, domain, inventory)
            counts.update(inventory.counts())
            return await plane.store.replace(
                current.model_copy(
                    update={
                        "tier": pre.tier,
                        "sku_name_raw": pre.sku_name_raw,
                        "diagnostics": pre.diagnostics,
                        "capabilities": capabilities,
                        "coverage": coverage_for(capabilities, pre.diagnostics),
                        "last_sync_at": taken,
                        "last_sync_status": "ok",
                        "freshness_seconds": 0,
                        "updated_at": taken,
                    }
                ),
                if_match=_etag(current),
            )

        def after(saved: GatewayRegistration) -> AuditDraft:
            subject = make_subject(subject_id, ENTITY_TYPE, state={**state, "counts": counts})
            return build_after(
                ctx, subject, result="succeeded", verified=True, detail=f"synced:tier={saved.tier}"
            )

        def failed(exc: BaseException) -> AuditDraft:
            subject = make_subject(subject_id, ENTITY_TYPE, state=state)
            return build_after(ctx, subject, result="failed", verified=False, detail=_code(exc))

        await run_audited_mutation(
            plane.audit,
            _chain(scope),
            before=build_before(ctx, make_subject(subject_id, ENTITY_TYPE, state=state)),
            mutate=mutate,
            after=after,
            on_error=failed,
        )
        return await self.detail(scope, domain, gateway_id)

    async def _record_failure(self, current: GatewayRegistration) -> None:
        """Best effort: mark the registration ``failed`` without hiding the original error."""
        at: datetime = self._plane.now()
        try:
            await self._plane.store.replace(
                current.model_copy(update={"last_sync_status": "failed", "updated_at": at}),
                if_match=_etag(current),
            )
        except Exception:
            return


def _chain(scope: IdentityScope) -> str:
    return audit_chain_id(scope.customer_id)


def _etag(registration: GatewayRegistration) -> str:
    # A stored registration always carries its etag; an empty one can never match.
    return registration.etag or ""
