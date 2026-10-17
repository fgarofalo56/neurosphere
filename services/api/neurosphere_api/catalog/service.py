"""Catalog domain service (PRP-10 item 5): entity writes, import, export, recertification and
stale-agent reconciliation over a ``CatalogRepository`` (protocol only).

Rules enforced here:

* Server-owned fields are never taken from the caller. On create the cloud and customer come from
  the derived scope and version, etag, timestamps are assigned; on update the id, entity type,
  cloud, customer, domain, creation time, lifecycle status and (for owners) the recertification
  fields are copied from the STORED entity. Lifecycle moves only through ``deprecate``;
  recertification only through ``recertify``.
* The write target domain is authorized against ``catalog.curate`` here for create and import (the
  document is the only place a new entity names its domain) and by the route's resource resolver,
  on the stored entity, for everything else. The repository re-checks the scope on every write.
* ``expected_etag`` is required for every change; the repository raises ``stale_version`` on a
  mismatch, so two edits with the same ETag cannot both succeed.
* Every mutation writes before/after audit records on the chain ``<customer>.<domain>`` and is
  read back to verify; a failed audit write aborts the action (fail closed). A refused request is
  recorded as denied when its target domain is one the caller can already see.
* Stale-agent reconciliation is two steps and stateless: ``stale_plan`` (a dry run that changes
  nothing) returns the candidate set and a digest; ``stale_confirm`` re-derives the set from the
  plan's own ``as_of`` and refuses (``stale_version``) any difference, then applies exactly that
  set, each agent under its own ETag. It marks (``attributes.stale_since``); it never deletes.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any, Final, Literal

from neurosphere_contracts.catalog.v1.agent import Agent
from neurosphere_core.audit import (
    AuditContext,
    AuditDraft,
    AuditRepository,
    build_after,
    build_before,
    build_denied,
    make_subject,
    run_audited_mutation,
)
from neurosphere_core.auth.scope import Permission, domains_with_permission
from neurosphere_core.catalog import (
    CatalogEntity,
    CatalogRepository,
    EdgeFilter,
    EntityFilter,
    format_timestamp,
    parse_timestamp,
)
from neurosphere_core.catalog.repo.documents import dump, entity_domain, parse_entity
from neurosphere_core.errors import (
    ForbiddenError,
    InvalidSchemaError,
    NeuroSphereError,
    StaleVersionError,
)
from neurosphere_core.paging import Page, PageRequest
from neurosphere_core.paging.models import MAX_PAGE_SIZE
from neurosphere_core.scope import IdentityScope

from neurosphere_api.catalog.curation.service import Clock
from neurosphere_api.catalog.models import (
    ExportPage,
    ImportItemResult,
    ImportRequest,
    ImportResult,
    PlanRef,
    RecertificationItem,
    RecertificationPage,
    StaleAgentConfirm,
    StaleAgentOutcome,
    StaleAgentPlan,
    StaleCandidate,
    StaleItemResult,
)

__all__ = [
    "MAX_SCAN_PAGES",
    "PLAN_TTL",
    "CatalogService",
    "audit_chain_for",
    "plan_digest",
]

Channel = Literal["button", "chat", "rest", "mcp", "websocket", "worker"]
Doc = dict[str, Any]

MAX_SCAN_PAGES: Final = 10
"""Bounded scan for recertification listing and stale detection (pages of 500)."""
PLAN_TTL: Final = timedelta(hours=1)
"""A dry-run plan can be confirmed for this long; after that it must be re-planned."""
_STALE_ATTRIBUTE: Final = "stale_since"
_IMMUTABLE: Final = ("id", "entity_type", "cloud", "customer_id", "domain_id", "created_at")
_OWNER_RECERT: Final = ("recertified_at", "recertify_by")


def audit_chain_for(customer_id: str, domain_id: str) -> str:
    """Audit chain of a domain: ``<customer>.<domain name>`` (audit_mount convention)."""
    return f"{customer_id}.{domain_id.rsplit(':', 1)[-1]}"


def _refusal(exc: BaseException) -> str:
    """Short machine code for an audit record or a report: the error's reason, else its code."""
    if isinstance(exc, NeuroSphereError):
        reason = getattr(exc, "reason", None)
        return reason if isinstance(reason, str) and reason else exc.code
    return "error"


def plan_digest(scope_hash: str, as_of: str, window_days: int, refs: list[tuple[str, str]]) -> str:
    """Digest binding a stale-agent plan to the caller scope, time, window and exact set."""
    payload = json.dumps(
        [scope_hash, as_of, window_days, sorted(refs)], separators=(",", ":"), sort_keys=True
    )
    return "plan-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:48]


class CatalogService:
    """Entity writes and governance workflows. Reads go straight to the repository / graph."""

    def __init__(self, repository: CatalogRepository, audit: AuditRepository, clock: Clock) -> None:
        self._repo = repository
        self._audit = audit
        self._clock = clock

    # -- authorization helpers -------------------------------------------------------------

    def _curate_domains(self, scope: IdentityScope) -> frozenset[str]:
        held = domains_with_permission(scope, Permission.CATALOG_CURATE, now=self._clock())
        return held & frozenset(scope.allowed_domains)

    def export_domains(self, scope: IdentityScope) -> frozenset[str]:
        """Domains the caller may export: ``data.export`` held AND readable in the scope."""
        held = domains_with_permission(scope, Permission.DATA_EXPORT, now=self._clock())
        return held & frozenset(scope.allowed_domains)

    # -- audited mutation ------------------------------------------------------------------

    async def _mutate(
        self,
        scope: IdentityScope,
        *,
        operation: str,
        correlation_id: str,
        channel: Channel,
        entity_id: str,
        entity_type: str,
        domain_id: str,
        customer_id: str,
        before: CatalogEntity | None,
        action: Callable[[], Awaitable[CatalogEntity]],
    ) -> CatalogEntity:
        ctx = AuditContext.from_scope(
            scope, correlation_id=correlation_id, operation=operation, channel=channel
        )
        chain = audit_chain_for(customer_id, domain_id)
        subject = make_subject(
            entity_id,
            entity_type,
            target_version=str(before.version.root) if before is not None else None,
            state=dump(before) if before is not None else None,
        )

        async def mutate() -> CatalogEntity:
            stored = await action()
            fresh = await self._repo.get_entity(scope, stored.id)
            if fresh is None or fresh.etag.root != stored.etag.root:
                raise InvalidSchemaError(
                    "stored entity could not be read back", reason="unverified"
                )
            return stored

        def succeeded(result: CatalogEntity) -> AuditDraft:
            return build_after(
                ctx,
                make_subject(
                    result.id,
                    entity_type,
                    target_version=str(result.version.root),
                    state=dump(result),
                ),
                result="succeeded",
                verified=True,
                detail=operation.rsplit(".", 1)[-1],
            )

        def failed(exc: BaseException) -> AuditDraft:
            return build_after(ctx, subject, result="failed", verified=False, detail=_refusal(exc))

        return await run_audited_mutation(
            self._audit,
            chain,
            before=build_before(ctx, subject),
            mutate=mutate,
            after=succeeded,
            on_error=failed,
        )

    async def _deny(
        self,
        scope: IdentityScope,
        stored: CatalogEntity,
        exc: NeuroSphereError,
        *,
        operation: str,
        correlation_id: str,
    ) -> None:
        """Record a refused request on the chain of an entity the caller can already see."""
        ctx = AuditContext.from_scope(
            scope, correlation_id=correlation_id, operation=operation, channel="rest"
        )
        subject = make_subject(
            stored.id,
            stored.entity_type,
            target_version=str(stored.version.root),
            state=dump(stored),
        )
        domain = entity_domain(dump(stored)) or ""
        await self._audit.append(
            audit_chain_for(stored.customer_id.root, domain),
            build_denied(ctx, code=exc.code, reason=_refusal(exc), subject=subject),
        )

    # -- create ----------------------------------------------------------------------------

    def _prepare_new(self, scope: IdentityScope, doc: Doc) -> CatalogEntity:
        """Contract-validate a new entity document with server-owned fields applied.

        Raises ``InvalidSchemaError`` for a contract violation and ``ForbiddenError`` when the
        document's domain is not one the caller may curate. Caller-supplied cloud, customer,
        version, etag and timestamps are overwritten, never trusted.
        """
        now = format_timestamp(self._clock())
        payload: Doc = dict(doc)
        payload.update(
            cloud=scope.cloud,
            customer_id=scope.customer_id,
            version=1,
            etag="pending",
            created_at=now,
            updated_at=now,
        )
        payload.setdefault("schema_version", "1.0.0")
        payload.setdefault("lifecycle_status", "draft")
        if payload["lifecycle_status"] not in ("draft", "active"):
            raise InvalidSchemaError(
                "a new entity starts as draft or active", reason="lifecycle_not_allowed"
            )
        entity = parse_entity(payload)
        domain = entity_domain(dump(entity))
        if domain is None or domain not in self._curate_domains(scope):
            raise ForbiddenError("the target domain is outside the caller's scope")
        return entity

    async def create(
        self,
        scope: IdentityScope,
        doc: Doc,
        *,
        correlation_id: str,
        channel: Channel = "rest",
    ) -> CatalogEntity:
        entity = self._prepare_new(scope, doc)
        return await self._create_prepared(
            scope, entity, correlation_id=correlation_id, channel=channel
        )

    async def _create_prepared(
        self, scope: IdentityScope, entity: CatalogEntity, *, correlation_id: str, channel: Channel
    ) -> CatalogEntity:
        domain = entity_domain(dump(entity)) or ""
        return await self._mutate(
            scope,
            operation="catalog.entity_create",
            correlation_id=correlation_id,
            channel=channel,
            entity_id=entity.id,
            entity_type=entity.entity_type,
            domain_id=domain,
            customer_id=entity.customer_id.root,
            before=None,
            action=lambda: self._repo.create_entity(scope, entity),
        )

    # -- update / deprecate / recertify ----------------------------------------------------

    async def update(
        self,
        scope: IdentityScope,
        stored: CatalogEntity,
        doc: Doc,
        expected_etag: str,
        *,
        correlation_id: str,
        channel: Channel = "rest",
    ) -> CatalogEntity:
        """Replace ``stored`` with ``doc`` (server-owned fields kept from the stored entity)."""
        current = dump(stored)
        payload: Doc = dict(doc)
        for key in _IMMUTABLE:
            if key in current:
                payload[key] = current[key]
        payload.update(
            lifecycle_status=current["lifecycle_status"],
            version=current["version"],
            etag=current["etag"],
            updated_at=format_timestamp(self._clock()),
        )
        payload.setdefault("schema_version", current["schema_version"])
        if stored.entity_type == "owner":
            for key in _OWNER_RECERT:
                payload[key] = current.get(key)
        entity = parse_entity(payload)
        return await self._guarded(
            scope,
            stored,
            "catalog.entity_update",
            correlation_id,
            channel,
            lambda: self._repo.update_entity(scope, entity, expected_etag),
        )

    async def deprecate(
        self,
        scope: IdentityScope,
        stored: CatalogEntity,
        expected_etag: str,
        *,
        correlation_id: str,
        channel: Channel = "rest",
    ) -> CatalogEntity:
        """Lifecycle deprecation: a state, not a deletion (edges and history remain)."""
        operation = "catalog.entity_deprecate"
        if stored.lifecycle_status.root in ("deprecated", "retired"):
            exc = InvalidSchemaError(
                "the entity is already deprecated or retired", reason="already_deprecated"
            )
            await self._deny(scope, stored, exc, operation=operation, correlation_id=correlation_id)
            raise exc
        return await self._guarded(
            scope,
            stored,
            operation,
            correlation_id,
            channel,
            lambda: self._repo.deprecate_entity(scope, stored.id, expected_etag),
        )

    async def recertify(
        self,
        scope: IdentityScope,
        stored: CatalogEntity,
        valid_for_days: int,
        expected_etag: str,
        *,
        correlation_id: str,
        channel: Channel = "rest",
    ) -> CatalogEntity:
        """Record an ownership recertification now, valid for ``valid_for_days``."""
        operation = "catalog.owner_recertify"
        if stored.entity_type != "owner" or stored.lifecycle_status.root != "active":
            exc = InvalidSchemaError(
                "only an active owner can be recertified", reason="not_an_active_owner"
            )
            await self._deny(scope, stored, exc, operation=operation, correlation_id=correlation_id)
            raise exc
        now = self._clock()
        payload = dump(stored)
        payload.update(
            recertified_at=format_timestamp(now),
            recertify_by=format_timestamp(now + timedelta(days=valid_for_days)),
            updated_at=format_timestamp(now),
        )
        entity = parse_entity(payload)
        return await self._guarded(
            scope,
            stored,
            operation,
            correlation_id,
            channel,
            lambda: self._repo.update_entity(scope, entity, expected_etag),
        )

    async def _guarded(
        self,
        scope: IdentityScope,
        stored: CatalogEntity,
        operation: str,
        correlation_id: str,
        channel: Channel,
        action: Callable[[], Awaitable[CatalogEntity]],
    ) -> CatalogEntity:
        domain = entity_domain(dump(stored)) or ""
        return await self._mutate(
            scope,
            operation=operation,
            correlation_id=correlation_id,
            channel=channel,
            entity_id=stored.id,
            entity_type=stored.entity_type,
            domain_id=domain,
            customer_id=stored.customer_id.root,
            before=stored,
            action=action,
        )

    # -- import ----------------------------------------------------------------------------

    async def import_entities(
        self,
        scope: IdentityScope,
        request: ImportRequest,
        *,
        correlation_id: str,
        channel: Channel = "rest",
    ) -> ImportResult:
        """Validate every item first; write only if all are valid (all-or-report)."""
        prepared: list[CatalogEntity | None] = []
        results: list[ImportItemResult] = []
        seen: set[str] = set()
        for index, doc in enumerate(request.items):
            ident = doc.get("id") if isinstance(doc.get("id"), str) else None
            try:
                entity = self._prepare_new(scope, doc)
                if entity.id in seen or await self._repo.get_entity(scope, entity.id) is not None:
                    raise InvalidSchemaError(
                        "an entity with this ID already exists", reason="exists"
                    )
                seen.add(entity.id)
            except NeuroSphereError as exc:
                prepared.append(None)
                results.append(
                    ImportItemResult(index=index, id=ident, status="rejected", code=_refusal(exc))
                )
                continue
            prepared.append(entity)
            results.append(ImportItemResult(index=index, id=entity.id, status="valid"))
        if request.dry_run or any(r.status == "rejected" for r in results):
            return ImportResult(committed=False, dry_run=request.dry_run, items=results)

        failed = False
        for index, entity in enumerate(prepared):
            if entity is None:  # pragma: no cover - no item is rejected on this path
                continue
            if failed:
                results[index] = results[index].model_copy(update={"status": "skipped"})
                continue
            try:
                await self._create_prepared(
                    scope, entity, correlation_id=correlation_id, channel=channel
                )
            except NeuroSphereError as exc:
                failed = True
                results[index] = results[index].model_copy(
                    update={"status": "failed", "code": _refusal(exc)}
                )
            else:
                results[index] = results[index].model_copy(update={"status": "created"})
        return ImportResult(committed=not failed, dry_run=False, items=results)

    # -- export ----------------------------------------------------------------------------

    async def export_page(
        self,
        scope: IdentityScope,
        flt: EntityFilter,
        page: PageRequest,
    ) -> ExportPage:
        """One page of entities limited to the caller's ``data.export`` domains.

        A requested domain outside that set is dropped, never honored; if nothing remains the
        page is empty (the same answer as for a domain that does not exist).
        """
        allowed = self.export_domains(scope)
        wanted = [d for d in (flt.domain_ids or sorted(allowed)) if d in allowed]
        stamp = format_timestamp(self._clock())
        if not wanted:
            return ExportPage(exported_at=stamp, domains=[], items=[])
        narrowed = flt.model_copy(update={"domain_ids": sorted(set(wanted))})
        found = await self._repo.list_entities(scope, narrowed, page)
        return ExportPage(
            exported_at=stamp,
            domains=sorted(set(wanted)),
            items=list(found.items),
            next_cursor=found.next_cursor,
        )

    # -- recertification listing -----------------------------------------------------------

    async def due_recertifications(
        self,
        scope: IdentityScope,
        *,
        within_days: int,
        include: Literal["due", "overdue", "both"],
        page: PageRequest,
    ) -> RecertificationPage:
        """Active owners whose ``recertify_by`` is overdue or falls within ``within_days``.

        One bounded repository page is scanned per call; page with ``next_cursor``. Owners with
        no ``recertify_by`` are not scheduled and not listed.
        """
        now = self._clock()
        horizon = now + timedelta(days=within_days)
        found = await self._repo.list_entities(
            scope, EntityFilter(entity_types=["owner"], lifecycle_statuses=["active"]), page
        )
        items: list[RecertificationItem] = []
        for entity in found.items:
            body = dump(entity)
            by = body.get("recertify_by")
            if not isinstance(by, str):
                continue
            deadline = parse_timestamp(by)
            overdue = deadline < now
            if overdue and include == "due":
                continue
            if not overdue and (include == "overdue" or deadline > horizon):
                continue
            items.append(
                RecertificationItem(
                    owner_id=entity.id,
                    domain_id=str(body["domain_id"]),
                    owner_kind=str(body["owner_kind"]),
                    recertified_at=body.get("recertified_at"),
                    recertify_by=by,
                    state="overdue" if overdue else "due",
                    days_until_due=(deadline - now).days,
                )
            )
        items.sort(key=lambda i: (i.recertify_by, i.owner_id))
        return RecertificationPage(
            items=items, scanned=len(found.items), next_cursor=found.next_cursor
        )

    # -- stale agents ----------------------------------------------------------------------

    async def _stale_candidates(
        self, scope: IdentityScope, as_of: datetime, window_days: int
    ) -> tuple[list[StaleCandidate], bool]:
        """Active agents in the caller's curate domains with no observation inside the window.

        An agent's last observation is the newest ``last_observed`` of the edges touching it
        (first edge page, scope-filtered); with no edges it is the agent's creation time. Agents
        already marked stale are skipped. Returns ``(candidates, truncated)``.
        """
        domains = sorted(self._curate_domains(scope))
        if not domains:
            return [], False
        cutoff = as_of - timedelta(days=window_days)
        flt = EntityFilter(
            entity_types=["agent"], domain_ids=domains, lifecycle_statuses=["active"]
        )
        candidates: list[StaleCandidate] = []
        cursor: str | None = None
        for _ in range(MAX_SCAN_PAGES):
            page: Page[CatalogEntity] = await self._repo.list_entities(
                scope, flt, PageRequest(page_size=MAX_PAGE_SIZE, cursor=cursor)
            )
            for entity in page.items:
                body = dump(entity)
                if (body.get("attributes") or {}).get(_STALE_ATTRIBUTE) is not None:
                    continue
                seen = await self._last_observed(scope, entity)
                if seen < cutoff:
                    candidates.append(
                        StaleCandidate(
                            agent_id=entity.id,
                            etag=entity.etag.root,
                            domain_id=str(body["domain_id"]),
                            last_observed=format_timestamp(seen),
                        )
                    )
            cursor = page.next_cursor
            if cursor is None:
                return candidates, False
        return candidates, True

    async def _last_observed(self, scope: IdentityScope, agent: CatalogEntity) -> datetime:
        edges = await self._repo.list_edges_by_node(
            scope, agent.id, "both", EdgeFilter(), PageRequest(page_size=MAX_PAGE_SIZE)
        )
        stamps = [parse_timestamp(e.last_observed.root) for e in edges.items]
        return max(stamps) if stamps else parse_timestamp(agent.created_at.root)

    async def stale_plan(self, scope: IdentityScope, window_days: int) -> StaleAgentPlan:
        """Dry run: the agents that would be marked stale now. Changes nothing."""
        as_of = self._clock()
        candidates, truncated = await self._stale_candidates(scope, as_of, window_days)
        stamp = format_timestamp(as_of)
        refs = [(c.agent_id, c.etag) for c in candidates]
        return StaleAgentPlan(
            plan_id=plan_digest(scope.scope_hash, stamp, window_days, refs),
            as_of=stamp,
            window_days=window_days,
            candidates=candidates,
            truncated=truncated,
        )

    async def stale_confirm(
        self,
        scope: IdentityScope,
        confirm: StaleAgentConfirm,
        *,
        correlation_id: str,
        channel: Channel = "rest",
    ) -> StaleAgentOutcome:
        """Apply exactly the dry-run set, or refuse.

        Refused with ``invalid_schema`` when the plan digest does not match its contents or the
        plan is unusable, and with ``stale_version`` when the plan expired or the live set (or any
        agent ETag) differs from the plan. A truncated scan can never be confirmed because it
        cannot be proven complete.
        """
        try:
            as_of = parse_timestamp(confirm.as_of)
        except ValueError:
            raise InvalidSchemaError("as_of is not a timestamp", reason="bad_plan") from None
        refs = [(r.agent_id, r.etag) for r in confirm.candidates]
        expected = plan_digest(scope.scope_hash, confirm.as_of, confirm.window_days, refs)
        if confirm.plan_id != expected:
            raise InvalidSchemaError("the plan does not match its contents", reason="bad_plan")
        now = self._clock()
        if as_of > now or now - as_of > PLAN_TTL:
            raise StaleVersionError(
                "the plan expired; run the dry run again", reason="plan_expired"
            )
        live, truncated = await self._stale_candidates(scope, as_of, confirm.window_days)
        if truncated or sorted((c.agent_id, c.etag) for c in live) != sorted(refs):
            raise StaleVersionError("the stale set changed since the dry run", reason="stale_plan")

        results: list[StaleItemResult] = []
        for ref in confirm.candidates:
            results.append(
                await self._mark_stale(
                    scope, ref, now, confirm.window_days, correlation_id, channel
                )
            )
        return StaleAgentOutcome(plan_id=confirm.plan_id, items=results)

    async def _mark_stale(
        self,
        scope: IdentityScope,
        ref: PlanRef,
        now: datetime,
        window_days: int,
        correlation_id: str,
        channel: Channel,
    ) -> StaleItemResult:
        stored = await self._repo.get_entity(scope, ref.agent_id)
        if stored is None or not isinstance(stored, Agent):
            return StaleItemResult(agent_id=ref.agent_id, status="failed", code="not_found")
        payload = dump(stored)
        attributes = dict(payload.get("attributes") or {})
        attributes[_STALE_ATTRIBUTE] = format_timestamp(now)
        attributes["stale_window_days"] = float(window_days)
        payload.update(attributes=attributes, updated_at=format_timestamp(now))
        try:
            updated = await self._guarded(
                scope,
                stored,
                "catalog.agent_mark_stale",
                correlation_id,
                channel,
                lambda: self._repo.update_entity(scope, parse_entity(payload), ref.etag),
            )
        except NeuroSphereError as exc:
            return StaleItemResult(agent_id=ref.agent_id, status="failed", code=_refusal(exc))
        return StaleItemResult(agent_id=ref.agent_id, status="marked", etag=updated.etag.root)
