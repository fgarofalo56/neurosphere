"""Audited content read (PRP-104 item 3): the ONE code path that decrypts content for a person.

:class:`InteractionContentReader` wraps the installed :class:`InteractionExplorer` and answers
:meth:`~InteractionContentReader.read` (one interaction, the content-reads route) and
:meth:`~InteractionContentReader.read_many` (several interactions of one domain under ONE audit
record; the replay payload branch calls it once per trace read). Both run the same steps, in this
order, and nothing is decrypted unless every earlier step passed:

1. Purpose: the PRP-99 ``InteractionAccessPurpose`` is re-validated (a known ``purpose_code``; a
   ``case_ref`` that is a record id and passes the audit content guard, so no prose, e-mail-shaped
   or GUID-shaped value). Anything else is 422 ``interaction_purpose_invalid`` with no read, no
   audit append and no denial record.
2. Authorization: the caller's cloud and customer must equal the deployment's, and the path domain
   must be one where an UNEXPIRED role assignment confers ``interaction.read``
   (``domains_with_permission`` at the request clock) AND one of the scope's ``allowed_domains``
   (that function intersects with ``allowed_domains`` only for ``data.read``, so it is done here).
   Every refusal is 403 with a denied-attempt record through the authz denial recorder (for a
   non-GET request a failed denial write is 503 ``audit_write_failed``, as in ``require``).
3. Metadata: ``get_metadata`` per id; an absent record, or one of another cloud, customer or
   domain, is 404 ``interaction_not_found`` (a read) or skipped (a batch). A record whose content
   is already purged (``content_ref`` null) is 404 ``interaction_content_purged`` / skipped.
4. Audit, fail closed: ONE ``interaction.read`` allowed record is appended to the domain's chain
   (``domain_audit_chain_id``) with the caller as actor, the interaction (or, for several, the
   domain) as subject and ``{"domain_id", "interaction_ids", "purpose_code", "case_ref"}`` bound
   into ``subject.state_digest`` (the audit contract has no purpose field). If the append raises,
   the answer is 503 ``audit_write_failed`` and ``read_content`` is never called.
5. Only then ``InteractionStore.read_content``; the stored ``RedactedContent`` is returned
   unchanged (only redacted content is ever stored).

The audit record and the logs carry ids, codes and digests only: never content, never the case
reference in clear (it is inside the digest), never a filter value.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

from neurosphere_contracts.interactions.v1.interaction_access_purpose import (
    InteractionAccessPurpose,
)
from neurosphere_contracts.interactions.v1.interaction_record import InteractionRecord
from neurosphere_contracts.interactions.v1.redacted_content import RedactedContent
from neurosphere_core.audit import (
    AuditContext,
    build_allowed,
    domain_audit_chain_id,
    make_subject,
)
from neurosphere_core.audit.content_guard import assert_metadata_only
from neurosphere_core.auth.scope import Permission, domains_with_permission
from neurosphere_core.errors import (
    DependencyTransientError,
    ForbiddenError,
    InvalidSchemaError,
    NeuroSphereError,
    NotFoundError,
)
from neurosphere_core.interactions import (
    CONTENT_PURGED,
    INTERACTION_NOT_FOUND,
    InteractionStoreError,
    interaction_pointer,
)
from neurosphere_core.observability import get_logger
from neurosphere_core.scope import IdentityScope
from pydantic import ValidationError

from neurosphere_api.authz.recorder import SAFE_METHODS, DenialRecorder, DeniedAttempt
from neurosphere_api.interactions.service import STATE_ATTRIBUTE, InteractionExplorer

__all__ = [
    "AUDIT_OP_READ",
    "AUDIT_WRITE_FAILED",
    "CONTENT_PURGED_REASON",
    "DOMAIN_NOT_READABLE",
    "MAX_READ_BATCH",
    "PURPOSE_INVALID",
    "TENANCY_MISMATCH",
    "ContentAccess",
    "InteractionContentReader",
    "validate_purpose",
]

#: Audit operation of every content read (PRP-99 operation name).
AUDIT_OP_READ: Final = "interaction.read"
#: 503 reason when the fail-closed ``interaction.read`` record could not be appended.
AUDIT_WRITE_FAILED: Final = "audit_write_failed"
#: 422 reason of a missing, unknown or unsafe purpose.
PURPOSE_INVALID: Final = "interaction_purpose_invalid"
#: 403 reason when the caller's cloud or customer is not the deployment's.
TENANCY_MISMATCH: Final = "tenancy_mismatch"
#: 403 reason when the caller holds ``interaction.read`` in the domain but it is not one of the
#: scope's ``allowed_domains`` (no ``data.read`` there).
DOMAIN_NOT_READABLE: Final = "domain_not_readable"
#: 404 reason of an interaction whose content is already purged.
CONTENT_PURGED_REASON: Final = "interaction_content_purged"
#: Most interactions one :meth:`InteractionContentReader.read_many` call may decrypt.
MAX_READ_BATCH: Final = 100

_ENTITY_TYPE: Final = "interaction"
_DOMAIN_ENTITY_TYPE: Final = "domain"
_UUID: Final = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_CORRELATION: Final = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_LOG = get_logger("neurosphere_api.interactions.content")


@dataclass(frozen=True, slots=True)
class ContentAccess:
    """Who asks, when, and where denials go: built by the route from the request.

    ``scope`` is the server-derived scope; ``now`` the authz clock's time (assignment expiry is
    judged against it); ``request_id`` the request's correlation id (``correlation_id_of``);
    ``method``/``path`` describe the request for a denial record; ``denials`` is the authz denial
    recorder (``None`` when none is installed).
    """

    scope: IdentityScope
    now: datetime
    request_id: str | None
    method: str
    path: str
    denials: DenialRecorder | None


def validate_purpose(
    purpose: InteractionAccessPurpose | Mapping[str, Any],
) -> InteractionAccessPurpose:
    """A re-validated purpose, else 422 ``interaction_purpose_invalid`` (values never echoed).

    Re-validation also covers an instance built with ``model_construct``. The case reference must
    pass the audit content guard (no e-mail-, JWT- or GUID-shaped value: a directory object id is
    GUID-shaped).
    """
    raw: object = (
        purpose.model_dump(mode="json")
        if isinstance(purpose, InteractionAccessPurpose)
        else dict(purpose)
    )
    try:
        validated = InteractionAccessPurpose.model_validate(raw)
        assert_metadata_only(validated.model_dump(mode="json"))
    except (ValidationError, InvalidSchemaError, TypeError, ValueError):
        raise InvalidSchemaError(
            "a known purpose code and an optional case record id are required",
            reason=PURPOSE_INVALID,
        ) from None
    return validated


def _audit_correlation_id(request_id: str | None) -> str:
    """Audit-safe correlation id (``corr-`` + the request id without dashes), else generated."""
    if request_id:
        candidate = "corr-" + request_id.replace("-", "")
        if candidate != "corr-" and _CORRELATION.fullmatch(candidate):
            return candidate
    return f"corr-{uuid.uuid4().hex}"


def _unique_ids(interaction_ids: Sequence[str]) -> list[str]:
    if isinstance(interaction_ids, str):
        raise InvalidSchemaError("interaction ids must be a list", reason="interaction_id_invalid")
    ids = list(dict.fromkeys(interaction_ids))
    if len(ids) > MAX_READ_BATCH:
        raise InvalidSchemaError(
            "too many interactions in one content read", reason="interaction_batch_too_large"
        )
    if not all(isinstance(i, str) and _UUID.fullmatch(i) for i in ids):
        raise InvalidSchemaError(
            "interaction ids must be lowercase UUIDs", reason="interaction_id_invalid"
        )
    return ids


def _store_unavailable() -> DependencyTransientError:
    return DependencyTransientError(
        "the interaction store is unavailable", reason="interaction_store_unavailable"
    )


class InteractionContentReader:
    """Purpose, authorization, metadata, fail-closed audit, then decrypt. See the module doc."""

    def __init__(self, explorer: InteractionExplorer) -> None:
        self._explorer = explorer

    @classmethod
    def from_app_state(cls, app_state: object) -> InteractionContentReader | None:
        """The reader over ``app.state.interaction_explorer``; ``None`` while it is off."""
        explorer = getattr(app_state, STATE_ATTRIBUTE, None)
        return cls(explorer) if isinstance(explorer, InteractionExplorer) else None

    # --- public API ------------------------------------------------------------------------------

    async def read(
        self,
        access: ContentAccess,
        domain_id: str,
        interaction_id: str,
        purpose: InteractionAccessPurpose | Mapping[str, Any],
    ) -> RedactedContent:
        """The stored redacted content of one interaction (404 when absent or purged)."""
        validated = validate_purpose(purpose)
        ids = _unique_ids([interaction_id])
        await self._authorize(access, domain_id)
        readable, purged = await self._readable(access.scope, domain_id, ids)
        if not readable:
            reason = CONTENT_PURGED_REASON if purged else "interaction_not_found"
            raise NotFoundError("no such interaction content", reason=reason)
        contents = await self._audited_decrypt(access, domain_id, readable, validated)
        content = contents.get(interaction_id)
        if content is None:
            raise NotFoundError("no such interaction content", reason=CONTENT_PURGED_REASON)
        return content

    async def read_many(
        self,
        access: ContentAccess,
        domain_id: str,
        interaction_ids: Sequence[str],
        purpose: InteractionAccessPurpose | Mapping[str, Any],
    ) -> dict[str, RedactedContent]:
        """Stored redacted content of several interactions of ``domain_id`` under ONE record.

        Ids that are absent, foreign or purged are skipped (not listed in the record, not
        decrypted); the result maps each readable id to its content, in request order. At most
        :data:`MAX_READ_BATCH` distinct ids; none readable -> ``{}`` with no audit record.
        """
        validated = validate_purpose(purpose)
        ids = _unique_ids(interaction_ids)
        await self._authorize(access, domain_id)
        readable, _ = await self._readable(access.scope, domain_id, ids)
        if not readable:
            return {}
        return await self._audited_decrypt(access, domain_id, readable, validated)

    # --- steps -----------------------------------------------------------------------------------

    def _refusal(self, access: ContentAccess, domain_id: str) -> str | None:
        scope = access.scope
        if str(scope.cloud) != self._explorer.cloud or (
            scope.customer_id != self._explorer.customer_id
        ):
            return TENANCY_MISMATCH
        held = domains_with_permission(scope, Permission.INTERACTION_READ, now=access.now)
        if not held:
            return "permission_missing"
        if domain_id not in held:
            return "target_out_of_scope"
        # ``allowed_domains`` are the scope's data.read domains: content is read only where the
        # caller may also list the interaction (PRP-104 gotcha; clarification 6).
        if domain_id not in frozenset(scope.allowed_domains):
            return DOMAIN_NOT_READABLE
        return None

    async def _authorize(self, access: ContentAccess, domain_id: str) -> None:
        reason = self._refusal(access, domain_id)
        if reason is None:
            return
        _LOG.info("content read refused", extra={"deny_reason": reason})
        if access.denials is not None:
            attempt = DeniedAttempt(
                scope=access.scope,
                permission=Permission.INTERACTION_READ.value,
                reason=reason,
                method=access.method,
                path=access.path,
                domain_id=domain_id,
                resource_id=None,
                correlation_id=access.request_id,
            )
            try:
                await access.denials.record_denial(attempt)
            except Exception as exc:
                if access.method.upper() not in SAFE_METHODS:
                    raise DependencyTransientError(
                        "audit write failed", reason=AUDIT_WRITE_FAILED
                    ) from exc
                _LOG.warning("content read denial record failed", extra={"deny_reason": reason})
        raise ForbiddenError(
            f"this operation needs `{Permission.INTERACTION_READ.value}`", reason=reason
        )

    def _visible(
        self, record: InteractionRecord, scope: IdentityScope, domain_id: str, iid: str
    ) -> bool:
        return (
            record.cloud.root == self._explorer.cloud
            and record.customer_id.root == scope.customer_id
            and record.domain_id.root == domain_id
            and record.interaction_id.root == iid
        )

    async def _readable(
        self, scope: IdentityScope, domain_id: str, ids: list[str]
    ) -> tuple[list[str], bool]:
        """Ids with visible metadata and stored content, and whether any visible one was purged."""
        readable: list[str] = []
        purged = False
        for iid in ids:
            try:
                record = await self._explorer.store.get_metadata(scope.customer_id, domain_id, iid)
            except NeuroSphereError:
                raise
            except Exception as exc:
                raise _store_unavailable() from exc
            if record is None or not self._visible(record, scope, domain_id, iid):
                continue
            if record.content_ref is None:
                purged = True
                continue
            readable.append(iid)
        return readable, purged

    async def _audited_decrypt(
        self,
        access: ContentAccess,
        domain_id: str,
        ids: list[str],
        purpose: InteractionAccessPurpose,
    ) -> dict[str, RedactedContent]:
        scope = access.scope
        state = {
            "domain_id": domain_id,
            "interaction_ids": list(ids),
            "purpose_code": purpose.purpose_code,
            "case_ref": None if purpose.case_ref is None else purpose.case_ref.root,
        }
        # Step 4: the record first. Any failure here (chain id, content guard, store) is 503 and
        # nothing below runs.
        try:
            if len(ids) == 1:
                subject = make_subject(
                    f"{self._explorer.cloud}:{scope.customer_id}:neurosphere:{_ENTITY_TYPE}:{ids[0]}",
                    _ENTITY_TYPE,
                    state=state,
                    snapshot_ref=interaction_pointer(ids[0]),
                )
            else:
                subject = make_subject(domain_id, _DOMAIN_ENTITY_TYPE, state=state)
            ctx = AuditContext.from_scope(
                scope,
                correlation_id=_audit_correlation_id(access.request_id),
                operation=AUDIT_OP_READ,
                channel="rest",
            )
            await self._explorer.audit.append(
                domain_audit_chain_id(scope.customer_id, domain_id), build_allowed(ctx, subject)
            )
        except Exception as exc:
            _LOG.warning(
                "content read refused: audit write failed",
                extra={"read_audit_reason": AUDIT_WRITE_FAILED, "error_type": type(exc).__name__},
            )
            raise DependencyTransientError(
                "the content read could not be audited", reason=AUDIT_WRITE_FAILED
            ) from exc

        # Step 5: decrypt, only after the record is durable.
        contents: dict[str, RedactedContent] = {}
        for iid in ids:
            try:
                content = await self._explorer.store.read_content(scope.customer_id, domain_id, iid)
            except InteractionStoreError as exc:
                if exc.reason in (CONTENT_PURGED, INTERACTION_NOT_FOUND):
                    continue  # purged or removed between lookup and read
                raise _store_unavailable() from exc
            except NeuroSphereError:
                raise
            except Exception as exc:
                raise _store_unavailable() from exc
            if content.interaction_id.root != iid:
                raise _store_unavailable()
            contents[iid] = content
        return contents
