"""Catalog side of the post-success publication hand-off (PRP-34 item 10).

When the executor worker finishes a Grant or McpServer publication intent ``succeeded`` and
verified, :class:`CatalogPublicationRecorder` records that REAL gateway change on the catalog
entity with exactly the rules of the catalog API routes (``grant`` / ``mcp`` modules here). It is
the catalog writer, not the action plane: the executor composition
(``neurosphere_workers.actions.apim.PublicationRecordingExecutor``) only calls :meth:`record`
after the executor has returned, outside every executor phase.

* Authorization: the worker's own derived scope (``ScopeProvider``, a workload identity) must
  hold ``catalog.curate`` in the entity's domain, and the entity must be in the intent's domain.
  The repository re-checks the scope on the read and the write. No bypass.
* Idempotent: an intent already recorded on the entity is a no-op (returns the entity).
* Audited and ETag-guarded like ``CatalogService.update``: a ``before`` record, the conditional
  write, read-back, then an ``after`` record (``failed`` with a reason code when the write fails),
  on the domain's audit chain, channel ``worker``. A failed audit write aborts (fail closed).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Final, Protocol, runtime_checkable

from neurosphere_core.actions import StoredIntent
from neurosphere_core.audit import (
    AuditContext,
    AuditDraft,
    AuditRepository,
    build_after,
    build_before,
    make_subject,
    run_audited_mutation,
)
from neurosphere_core.auth.scope import Permission, domains_with_permission
from neurosphere_core.catalog import CatalogEntity, CatalogRepository
from neurosphere_core.catalog.repo.documents import dump, entity_domain, parse_entity
from neurosphere_core.catalog.rules import format_timestamp
from neurosphere_core.errors import ForbiddenError, InvalidSchemaError, NeuroSphereError
from neurosphere_core.scope import IdentityScope

from neurosphere_workers.publication.grant import (
    GRANT_ENTITY_TYPE,
    GRANT_KINDS,
    check_grant_intent,
    grant_publication_update,
    grant_recorded,
)
from neurosphere_workers.publication.mcp import (
    MCP_ENTITY_TYPE,
    MCP_KINDS,
    check_mcp_intent,
    mcp_publication_document,
    mcp_recorded,
)
from neurosphere_workers.publication.records import ApplyRecordLookup, reader_for

__all__ = ["OPERATION", "CatalogPublicationRecorder", "ScopeProvider"]

#: Audit operation of the catalog write (same as a catalog entity update through the API).
OPERATION: Final = "catalog.entity_update"
_IMMUTABLE: Final = ("id", "entity_type", "cloud", "customer_id", "domain_id", "created_at")
_ENTITY_TYPES: Final = {GRANT_ENTITY_TYPE: GRANT_KINDS, MCP_ENTITY_TYPE: MCP_KINDS}

Clock = Callable[[], datetime]


@runtime_checkable
class ScopeProvider(Protocol):
    async def get(self) -> IdentityScope:
        """The worker's currently valid derived scope; raises when none can be derived."""
        ...


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _chain(customer_id: str, domain_id: str) -> str:
    return f"{customer_id}.{domain_id.rsplit(':', 1)[-1]}"


def _refusal(exc: BaseException) -> str:
    if isinstance(exc, NeuroSphereError):
        reason = getattr(exc, "reason", None)
        return reason if isinstance(reason, str) and reason else exc.code
    return "error"


class CatalogPublicationRecorder:
    """Records a verified gateway publication on its catalog Grant or McpServer."""

    def __init__(
        self,
        repository: CatalogRepository,
        audit: AuditRepository,
        scope: ScopeProvider,
        *,
        records: ApplyRecordLookup | None = None,
        clock: Clock = _utc_now,
    ) -> None:
        self._repo = repository
        self._audit = audit
        self._scope = scope
        self._records = records
        self._clock = clock

    async def record(self, stored: StoredIntent) -> CatalogEntity:
        """Record ``stored`` (a succeeded, verified publication intent) on its entity."""
        intent = stored.intent
        kinds = _ENTITY_TYPES.get(intent.target.entity_type)
        if kinds is None or intent.action_kind not in kinds:
            raise InvalidSchemaError(
                "not a catalog publication intent", reason="not_a_publication_intent"
            )
        scope = await self._scope.get()
        entity = await self._repo.get_entity(scope, intent.target.canonical_id)
        if entity is None or entity.entity_type != intent.target.entity_type:
            raise InvalidSchemaError(
                "the published entity is not in the catalog", reason="publication_entity_missing"
            )
        doc = dump(entity)
        domain = entity_domain(doc)
        if domain is None or domain != stored.domain_id:
            raise ForbiddenError("the entity is not in the intent's domain")
        if domain not in domains_with_permission(
            scope, Permission.CATALOG_CURATE, now=self._clock()
        ):
            raise ForbiddenError("the worker identity may not curate this domain")
        intent_id = str(intent.intent_id.root)
        now = self._clock()
        if intent.target.entity_type == GRANT_ENTITY_TYPE:
            check_grant_intent(stored, entity.id)
            if grant_recorded(doc, intent_id):
                return entity
            reader = reader_for(self._records, stored.customer_id, stored.domain_id)
            updated = await grant_publication_update(doc, stored, reader, format_timestamp(now))
        else:
            if mcp_recorded(doc, intent_id):
                return entity
            stage, publication = check_mcp_intent(doc, entity.id, stored)
            updated = mcp_publication_document(doc, entity.id, stage, publication, intent_id, now)
        return await self._update(scope, entity, updated, stored, domain)

    async def _update(
        self,
        scope: IdentityScope,
        stored: CatalogEntity,
        doc: dict[str, Any],
        intent: StoredIntent,
        domain: str,
    ) -> CatalogEntity:
        """``CatalogService.update`` semantics: server-owned fields from the stored entity."""
        current = dump(stored)
        payload: dict[str, Any] = dict(doc)
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
        entity = parse_entity(payload)
        expected = stored.etag.root
        ctx = AuditContext.from_scope(
            scope,
            correlation_id=f"publication-{intent.intent_id[:8]}",
            operation=OPERATION,
            channel="worker",
        )
        subject = make_subject(
            stored.id,
            stored.entity_type,
            target_version=str(stored.version.root),
            state=current,
        )

        async def mutate() -> CatalogEntity:
            written = await self._repo.update_entity(scope, entity, expected)
            fresh = await self._repo.get_entity(scope, written.id)
            if fresh is None or fresh.etag.root != written.etag.root:
                raise InvalidSchemaError(
                    "stored entity could not be read back", reason="unverified"
                )
            return written

        def succeeded(result: CatalogEntity) -> AuditDraft:
            return build_after(
                ctx,
                make_subject(
                    result.id,
                    result.entity_type,
                    target_version=str(result.version.root),
                    state=dump(result),
                ),
                result="succeeded",
                verified=True,
                detail="publication_recorded",
            )

        def failed(exc: BaseException) -> AuditDraft:
            return build_after(ctx, subject, result="failed", verified=False, detail=_refusal(exc))

        return await run_audited_mutation(
            self._audit,
            _chain(stored.customer_id.root, domain),
            before=build_before(ctx, subject),
            mutate=mutate,
            after=succeeded,
            on_error=failed,
        )
