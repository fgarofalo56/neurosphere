"""Bounded, audited interaction export (PRP-104 item 4; criteria 5 and 6, clarification 7).

:class:`InteractionExporter` creates an export, returns its manifest and serves its bundle. The
owner decisions (GD-17): at most :data:`MAX_EXPORT` (500) interactions from ONE domain, the
bundle expires :data:`EXPORT_TTL` (24 hours) after creation, and an investigator has at most
:data:`MAX_OPEN_EXPORTS` (5) open (unexpired) exports.

Create, in this order (nothing is decrypted unless every earlier step passed):

1. Purpose: the PRP-99 ``InteractionAccessPurpose`` is re-validated exactly as for a content
   read (:func:`~neurosphere_api.interactions.content.validate_purpose`); the filters are the
   PRP-99 manifest ``Filters`` (``from`` inclusive, ``to`` exclusive on ``captured_at``,
   ``agent_ids``, ``detected_categories``; ``from`` before ``to``). Anything else is 422 with no
   read, no audit append and no denial record.
2. Exports configured, else 503 ``interaction_export_unconfigured``.
3. Authorization as for a content read but for ``interaction.export``: deployment cloud and
   customer, an UNEXPIRED assignment conferring ``interaction.export`` in the path domain at the
   request clock, and the domain in the scope's ``allowed_domains``. 403 with a denial record.
4. The open-export cap, judged from the manifests under ``exports/{customer}/`` (expired exports
   found on the way are deleted). A 6th open export is 429 ``interaction_export_limit_reached``
   with ``Retry-After`` = seconds until the caller's oldest open export expires: the limit lifts
   by itself with time, which is a quota/rate condition (429), not a conflict with the target
   resource's state (409 is ``stale_version``/``capability_unavailable`` in this taxonomy).
5. Selection over ``InteractionStore.query_index`` (metadata only): visible records of the
   domain, newest ``captured_at`` first; the first 500 with stored content are bundled, the rest
   (and records whose content is already purged) are counted in ``excluded_count``. Selections
   matching more than :data:`MAX_SELECTION_SCAN` are 422 ``interaction_export_selection_too_broad``
   (so ``excluded_count`` is always exact). Nothing selected is 404 ``interaction_export_empty``.
6. Audit, fail closed: ONE ``interaction.export`` allowed record on the domain's chain with the
   export id as subject and ids, counts and the purpose bound into ``subject.state_digest``. If the
   append raises: 503 ``audit_write_failed``, nothing decrypted, nothing written.
7. Only then ``read_content`` per id (the stored redacted content; nothing is re-derived), the
   bundle is sealed with PRP-102's envelope under the content key wrapper with
   :func:`bundle_aad` (customer, domain, export id, bundle format), and the bundle then the
   manifest are written under ``exports/{customer}/{domain}/{export_id}/``.

Held content IS exportable (``includes_held_content`` says so); nothing here deletes interaction
content. Only expired export blobs are deleted.

Manifest and bundle reads need ``interaction.export`` in the domain (same checks as create) AND
being the export's creator (``requested_by``): an export is bound to the purpose its creator
stated, so another investigator states their own purpose and creates their own audited export.
Another investigator gets 403 ``export_not_owned`` with a denial record. An expired export is 404
``interaction_export_expired`` and its blobs are deleted. The bundle download appends its own
fail-closed ``interaction.export_download`` record before the envelope is opened.

Bundle format (decrypted, UTF-8 JSON)::

    {"format": "ns-interaction-export-bundle-1", "export_id": ..., "customer_id": ...,
     "domain_id": ..., "interactions": {"<interaction id>": <RedactedContent>, ...}}

with ``interactions`` in manifest order. Logs carry reason codes only.
"""

from __future__ import annotations

import hashlib
import json
import math
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final

from neurosphere_contracts.interactions.v1.interaction_access_purpose import (
    InteractionAccessPurpose,
)
from neurosphere_contracts.interactions.v1.interaction_export_manifest import (
    Filters,
    InteractionExportManifest,
)
from neurosphere_contracts.interactions.v1.interaction_record import (
    EncryptedObjectRef,
    InteractionRecord,
)
from neurosphere_core.audit import AuditContext, build_allowed, domain_audit_chain_id, make_subject
from neurosphere_core.auth.scope import Permission
from neurosphere_core.crypto import Envelope, EnvelopeError, canonical_aad, open_envelope, seal
from neurosphere_core.errors import (
    DependencyTransientError,
    InvalidSchemaError,
    NeuroSphereError,
    NotFoundError,
    RateLimitedError,
)
from neurosphere_core.interactions import MAX_QUERY_PAGE_SIZE, InteractionQuery
from neurosphere_core.interactions.models import parse_timestamp
from neurosphere_core.observability import get_logger
from pydantic import ValidationError

from neurosphere_api.interactions.content import (
    AUDIT_WRITE_FAILED,
    ContentAccess,
    audit_correlation_id,
    authorize_content_access,
    decrypt_stored,
    deny,
    validate_purpose,
)
from neurosphere_api.interactions.export_storage import (
    BUNDLE_BLOB,
    MANIFEST_BLOB,
    InteractionExportStorage,
    export_customer_prefix,
    export_prefix,
)
from neurosphere_api.interactions.service import InteractionExplorer

__all__ = [
    "AUDIT_OP_DOWNLOAD",
    "AUDIT_OP_EXPORT",
    "BUNDLE_FORMAT",
    "EXPORT_TTL",
    "MANIFEST_SCHEMA_VERSION",
    "MAX_EXPORT",
    "MAX_OPEN_EXPORTS",
    "MAX_SELECTION_SCAN",
    "ExportBundle",
    "InteractionExporter",
    "bundle_aad",
]

#: Most interactions in one export (GD-17; the lifecycle ``MAX_EXPORT_RECORDS`` precedent).
MAX_EXPORT: Final = 500
#: Most open (unexpired) exports per investigator (GD-17).
MAX_OPEN_EXPORTS: Final = 5
#: Lifetime of an export bundle (GD-17).
EXPORT_TTL: Final = timedelta(hours=24)
#: Most matching records one selection may scan, so ``excluded_count`` stays exact.
MAX_SELECTION_SCAN: Final = 10_000
#: Most manifests the open-export scan reads before refusing (export state unavailable).
MAX_MANIFEST_SCAN: Final = 2_000

AUDIT_OP_EXPORT: Final = "interaction.export"
AUDIT_OP_DOWNLOAD: Final = "interaction.export_download"
BUNDLE_FORMAT: Final = "ns-interaction-export-bundle-1"
MANIFEST_SCHEMA_VERSION: Final = "1.2.0"

EXPORT_UNCONFIGURED: Final = "interaction_export_unconfigured"
EXPORT_LIMIT_REACHED: Final = "interaction_export_limit_reached"
EXPORT_NOT_FOUND: Final = "interaction_export_not_found"
EXPORT_EXPIRED: Final = "interaction_export_expired"
EXPORT_EMPTY: Final = "interaction_export_empty"
EXPORT_NOT_OWNED: Final = "export_not_owned"
EXPORT_FILTERS_INVALID: Final = "interaction_export_filters_invalid"
EXPORT_SELECTION_TOO_BROAD: Final = "interaction_export_selection_too_broad"
EXPORT_STATE_UNAVAILABLE: Final = "interaction_export_state_unavailable"
EXPORT_SEAL_FAILED: Final = "interaction_export_seal_failed"
EXPORT_INTEGRITY_FAILED: Final = "interaction_export_integrity_failed"

_ENTITY_TYPE: Final = "interaction_export"
_ALGORITHM: Final = "aes_256_gcm"
_LOG = get_logger("neurosphere_api.interactions.export")


def bundle_aad(customer_id: str, domain_id: str, export_id: str) -> bytes:
    """The associated data binding a bundle envelope to exactly one export."""
    return canonical_aad(
        {
            "customer_id": customer_id,
            "domain_id": domain_id,
            "export_id": export_id,
            "format": BUNDLE_FORMAT,
        }
    )


def _stamp(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _principal_id(access: ContentAccess) -> str:
    principal = access.scope.to_contract().principal.principal_id
    return str(getattr(principal, "root", principal))


def _validated_filters(filters: Filters | Mapping[str, Any]) -> tuple[Filters, datetime, datetime]:
    raw: object = (
        filters.model_dump(mode="json", by_alias=True)
        if isinstance(filters, Filters)
        else dict(filters)
    )
    try:
        validated = Filters.model_validate(raw)
        start = parse_timestamp(validated.from_.root)
        end = parse_timestamp(validated.to.root)
    except (ValidationError, TypeError, ValueError):
        raise InvalidSchemaError(
            "the export filters are invalid", reason=EXPORT_FILTERS_INVALID
        ) from None
    if start >= end:
        raise InvalidSchemaError("`from` must be before `to`", reason=EXPORT_FILTERS_INVALID)
    return validated, start, end


def _unconfigured() -> DependencyTransientError:
    return DependencyTransientError(
        "interaction exports are not configured in this deployment", reason=EXPORT_UNCONFIGURED
    )


def _store_unavailable() -> DependencyTransientError:
    return DependencyTransientError(
        "the interaction store is unavailable", reason="interaction_store_unavailable"
    )


@dataclass(frozen=True, slots=True)
class ExportBundle:
    """A decrypted bundle ready to stream (``content`` is the bundle JSON)."""

    export_id: str
    content: bytes


@dataclass(frozen=True, slots=True)
class _Selection:
    records: list[InteractionRecord]
    excluded_count: int


class InteractionExporter:
    """Create, describe and download exports. See the module doc for the order of steps."""

    def __init__(self, explorer: InteractionExplorer) -> None:
        self._explorer = explorer

    def _storage(self) -> InteractionExportStorage:
        storage = self._explorer.exports
        if storage is None:
            raise _unconfigured()
        return storage

    # --- create ----------------------------------------------------------------------------------

    async def create(
        self,
        access: ContentAccess,
        domain_id: str,
        purpose: InteractionAccessPurpose | Mapping[str, Any],
        filters: Filters | Mapping[str, Any],
    ) -> InteractionExportManifest:
        validated = validate_purpose(purpose)
        selection_filters, start, end = _validated_filters(filters)
        storage = self._storage()
        await authorize_content_access(
            self._explorer, access, domain_id, Permission.INTERACTION_EXPORT
        )
        requester = _principal_id(access)
        async with storage.lock:
            await self._check_open_cap(storage, access, requester)
            selection = await self._select(access, domain_id, selection_filters, start, end)
            if not selection.records:
                raise NotFoundError("no interactions match the export", reason=EXPORT_EMPTY)
            export_id = str(uuid.uuid4())
            ids = [r.interaction_id.root for r in selection.records]
            held = any(r.legal_hold_ids for r in selection.records)
            audit_id = await self._append(
                access,
                domain_id,
                export_id,
                AUDIT_OP_EXPORT,
                {
                    "export_id": export_id,
                    "domain_id": domain_id,
                    "interaction_ids": ids,
                    "interaction_count": len(ids),
                    "excluded_count": selection.excluded_count,
                    "includes_held_content": held,
                    "purpose_code": validated.purpose_code,
                    "case_ref": None if validated.case_ref is None else validated.case_ref.root,
                },
            )
            # Only after the record is durable: decrypt the stored redacted content.
            contents = await decrypt_stored(
                self._explorer, access.scope.customer_id, domain_id, ids
            )
            bundled = [r for r in selection.records if r.interaction_id.root in contents]
            excluded = selection.excluded_count + (len(ids) - len(bundled))
            bundled_ids = [r.interaction_id.root for r in bundled]
            document = {
                "format": BUNDLE_FORMAT,
                "export_id": export_id,
                "customer_id": access.scope.customer_id,
                "domain_id": domain_id,
                "interactions": {iid: contents[iid].model_dump(mode="json") for iid in bundled_ids},
            }
            plaintext = json.dumps(
                document, sort_keys=False, separators=(",", ":"), ensure_ascii=False
            ).encode("utf-8")
            del contents, document
            try:
                envelope = await seal(
                    plaintext,
                    bundle_aad(access.scope.customer_id, domain_id, export_id),
                    storage.wrapper,
                )
            except (EnvelopeError, ValueError) as exc:
                _LOG.warning("export seal failed", extra={"export_reason": EXPORT_SEAL_FAILED})
                raise DependencyTransientError(
                    "the export could not be sealed", reason=EXPORT_SEAL_FAILED
                ) from exc
            finally:
                del plaintext
            sealed = envelope.to_bytes()
            prefix = export_prefix(access.scope.customer_id, domain_id, export_id)
            created = access.now
            manifest = InteractionExportManifest.model_validate(
                {
                    "schema_version": MANIFEST_SCHEMA_VERSION,
                    "export_id": export_id,
                    "cloud": self._explorer.cloud,
                    "customer_id": access.scope.customer_id,
                    "domain_ids": [domain_id],
                    "requested_by": requester,
                    "requested_at": _stamp(created),
                    "purpose": validated.model_dump(mode="json"),
                    "filters": selection_filters.model_dump(mode="json", by_alias=True),
                    "interaction_count": len(bundled_ids),
                    "interaction_ids": bundled_ids,
                    "excluded_count": excluded,
                    "includes_held_content": any(r.legal_hold_ids for r in bundled),
                    "bundle": EncryptedObjectRef(
                        pointer=prefix + BUNDLE_BLOB,
                        kek_uri=storage.kek_uri,
                        algorithm=_ALGORITHM,
                        ciphertext_sha256=hashlib.sha256(sealed).hexdigest(),
                        byte_length=len(sealed),
                    ).model_dump(mode="json"),
                    "audit_id": audit_id,
                    "expires_at": _stamp(created + EXPORT_TTL),
                }
            )
            await storage.backend.put(prefix + BUNDLE_BLOB, sealed)
            try:
                await storage.backend.put(
                    prefix + MANIFEST_BLOB,
                    manifest.model_dump_json(by_alias=True).encode("utf-8"),
                )
            except Exception:
                await self._delete_quietly(storage, prefix)
                raise
        return manifest

    async def _check_open_cap(
        self, storage: InteractionExportStorage, access: ContentAccess, requester: str
    ) -> None:
        open_expiries: list[datetime] = []
        for manifest in await self._live_manifests(storage, access):
            if manifest.requested_by.root == requester:
                open_expiries.append(parse_timestamp(manifest.expires_at.root))
        if len(open_expiries) >= MAX_OPEN_EXPORTS:
            wait = (min(open_expiries) - access.now).total_seconds()
            _LOG.info("export refused", extra={"export_reason": EXPORT_LIMIT_REACHED})
            raise RateLimitedError(
                max(1, math.ceil(wait)),
                f"at most {MAX_OPEN_EXPORTS} open exports per investigator",
                reason=EXPORT_LIMIT_REACHED,
            )

    async def _live_manifests(
        self, storage: InteractionExportStorage, access: ContentAccess
    ) -> list[InteractionExportManifest]:
        """Unexpired manifests of the customer; expired exports met on the way are deleted."""
        live: list[InteractionExportManifest] = []
        seen = 0
        names = [
            name
            async for name in storage.backend.list_names(
                export_customer_prefix(access.scope.customer_id)
            )
            if name.endswith("/" + MANIFEST_BLOB)
        ]
        for name in names:
            seen += 1
            if seen > MAX_MANIFEST_SCAN:
                raise DependencyTransientError(
                    "export state is unavailable", reason=EXPORT_STATE_UNAVAILABLE
                )
            data = await storage.backend.get(name)
            if data is None:
                continue
            try:
                manifest = InteractionExportManifest.model_validate_json(data)
            except ValidationError:
                _LOG.warning("export manifest unreadable", extra={"export_reason": "invalid"})
                continue
            if parse_timestamp(manifest.expires_at.root) <= access.now:
                await self._delete_quietly(storage, name[: -len(MANIFEST_BLOB)])
                continue
            live.append(manifest)
        return live

    async def _select(
        self,
        access: ContentAccess,
        domain_id: str,
        filters: Filters,
        start: datetime,
        end: datetime,
    ) -> _Selection:
        body = filters.model_dump(mode="json", by_alias=True)
        agents: list[str | None] = list(body["agent_ids"]) or [None]
        categories = frozenset(body["detected_categories"])
        single = next(iter(categories)) if len(categories) == 1 else None
        matched: dict[str, InteractionRecord] = {}
        for agent in agents:
            continuation: str | None = None
            while True:
                query = InteractionQuery(
                    customer_id=access.scope.customer_id,
                    domain_id=domain_id,
                    agent_id=agent,
                    detected_category=single,
                    captured_from=start,
                    captured_before=end,
                    page_size=MAX_QUERY_PAGE_SIZE,
                    continuation=continuation,
                )
                try:
                    page = await self._explorer.store.query_index(query)
                except NeuroSphereError:
                    raise
                except Exception as exc:  # InteractionStoreError, an SDK error...
                    raise _store_unavailable() from exc
                for record in page.items:
                    if self._selected(record, access, domain_id, categories):
                        matched[record.interaction_id.root] = record
                if len(matched) > MAX_SELECTION_SCAN:
                    raise InvalidSchemaError(
                        f"the selection matches more than {MAX_SELECTION_SCAN} interactions",
                        reason=EXPORT_SELECTION_TOO_BROAD,
                    )
                continuation = page.continuation
                if continuation is None or not page.items:
                    break
        ordered = sorted(
            matched.values(),
            key=_newest_first,
            reverse=True,
        )
        readable = [r for r in ordered if r.content_ref is not None]
        purged = len(ordered) - len(readable)
        return _Selection(
            records=readable[:MAX_EXPORT],
            excluded_count=purged + max(0, len(readable) - MAX_EXPORT),
        )

    def _selected(
        self,
        record: InteractionRecord,
        access: ContentAccess,
        domain_id: str,
        categories: frozenset[str],
    ) -> bool:
        if (
            record.cloud.root != self._explorer.cloud
            or record.customer_id.root != access.scope.customer_id
            or record.domain_id.root != domain_id
        ):
            return False
        if categories:
            found = {item.category.root for item in record.findings_summary or []}
            if not found & categories:
                return False
        return True

    # --- manifest and bundle ---------------------------------------------------------------------

    async def manifest(
        self, access: ContentAccess, domain_id: str, export_id: str
    ) -> InteractionExportManifest:
        storage = self._storage()
        await authorize_content_access(
            self._explorer, access, domain_id, Permission.INTERACTION_EXPORT
        )
        return await self._owned_live(storage, access, domain_id, export_id)

    async def bundle(self, access: ContentAccess, domain_id: str, export_id: str) -> ExportBundle:
        storage = self._storage()
        await authorize_content_access(
            self._explorer, access, domain_id, Permission.INTERACTION_EXPORT
        )
        manifest = await self._owned_live(storage, access, domain_id, export_id)
        sealed = await storage.backend.get(manifest.bundle.pointer)
        if sealed is None:
            raise NotFoundError("no such export", reason=EXPORT_NOT_FOUND)
        if (
            len(sealed) != manifest.bundle.byte_length
            or hashlib.sha256(sealed).hexdigest() != manifest.bundle.ciphertext_sha256
        ):
            raise DependencyTransientError(
                "the export bundle failed its integrity check", reason=EXPORT_INTEGRITY_FAILED
            )
        await self._append(
            access,
            domain_id,
            export_id,
            AUDIT_OP_DOWNLOAD,
            {
                "export_id": export_id,
                "domain_id": domain_id,
                "export_audit_id": manifest.audit_id.root,
                "interaction_count": manifest.interaction_count,
                "bundle_sha256": manifest.bundle.ciphertext_sha256,
            },
        )
        # Only after the download record is durable: open the envelope.
        try:
            plaintext = await open_envelope(
                Envelope.from_bytes(sealed),
                bundle_aad(access.scope.customer_id, domain_id, export_id),
                storage.wrapper,
            )
        except EnvelopeError as exc:
            _LOG.warning("export open failed", extra={"export_reason": exc.reason})
            raise DependencyTransientError(
                "the export bundle could not be opened", reason=EXPORT_INTEGRITY_FAILED
            ) from exc
        return ExportBundle(export_id=export_id, content=plaintext)

    async def _owned_live(
        self,
        storage: InteractionExportStorage,
        access: ContentAccess,
        domain_id: str,
        export_id: str,
    ) -> InteractionExportManifest:
        customer = access.scope.customer_id
        try:
            prefix = export_prefix(customer, domain_id, export_id)
        except ValueError:
            raise NotFoundError("no such export", reason=EXPORT_NOT_FOUND) from None
        data = await storage.backend.get(prefix + MANIFEST_BLOB)
        if data is None:
            raise NotFoundError("no such export", reason=EXPORT_NOT_FOUND)
        try:
            manifest = InteractionExportManifest.model_validate_json(data)
        except ValidationError:
            raise NotFoundError("no such export", reason=EXPORT_NOT_FOUND) from None
        if (
            manifest.export_id.root != export_id
            or manifest.cloud.root != self._explorer.cloud
            or manifest.customer_id.root != customer
            or [d.root for d in manifest.domain_ids] != [domain_id]
            or manifest.bundle.pointer != prefix + BUNDLE_BLOB
        ):
            raise NotFoundError("no such export", reason=EXPORT_NOT_FOUND)
        if manifest.requested_by.root != _principal_id(access):
            raise await deny(
                access,
                domain_id,
                Permission.INTERACTION_EXPORT,
                EXPORT_NOT_OWNED,
                resource_id=export_id,
            )
        if parse_timestamp(manifest.expires_at.root) <= access.now:
            await self._delete_quietly(storage, prefix)
            raise NotFoundError("the export has expired", reason=EXPORT_EXPIRED)
        return manifest

    # --- shared steps ----------------------------------------------------------------------------

    async def _append(
        self,
        access: ContentAccess,
        domain_id: str,
        export_id: str,
        operation: str,
        state: Mapping[str, object],
    ) -> str:
        """Append one allowed record (fail closed: any failure is 503, the caller stops)."""
        scope = access.scope
        try:
            subject = make_subject(
                f"{self._explorer.cloud}:{scope.customer_id}:neurosphere:{_ENTITY_TYPE}:{export_id}",
                _ENTITY_TYPE,
                state=dict(state),
            )
            ctx = AuditContext.from_scope(
                scope,
                correlation_id=audit_correlation_id(access.request_id),
                operation=operation,
                channel="rest",
            )
            record = await self._explorer.audit.append(
                domain_audit_chain_id(scope.customer_id, domain_id), build_allowed(ctx, subject)
            )
        except Exception as exc:
            _LOG.warning(
                "export refused: audit write failed",
                extra={"export_reason": AUDIT_WRITE_FAILED, "error_type": type(exc).__name__},
            )
            raise DependencyTransientError(
                "the export could not be audited", reason=AUDIT_WRITE_FAILED
            ) from exc
        return record.audit_id.root

    @staticmethod
    async def _delete_quietly(storage: InteractionExportStorage, prefix: str) -> None:
        """Delete an export's blobs, bundle first; a failure is logged, left for a later sweep."""
        for leaf in (BUNDLE_BLOB, MANIFEST_BLOB):
            try:
                await storage.backend.delete(prefix + leaf)
            except Exception:
                _LOG.warning("export cleanup failed", extra={"export_reason": "delete_failed"})


def _newest_first(record: InteractionRecord) -> tuple[datetime, str]:
    return parse_timestamp(record.captured_at.root), record.interaction_id.root
