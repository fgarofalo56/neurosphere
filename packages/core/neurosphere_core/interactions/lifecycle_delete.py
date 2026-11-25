"""Lifecycle target over captured interaction content: index plus encrypted blob (PRP-102 item 5).

A new module beside the interaction store: the store itself is not edited. One lifecycle record
is one interaction, i.e. its ``interaction_index`` document AND its content blob, so the data
class ``interaction_content`` is purged as a unit. The backend is bound to one customer; every
read, listing and mutation addresses that customer's partition only.

Record id: ``{interaction_id}/{domain_id}``. The interaction id (a lowercase UUID, fixed width)
comes first so record-id order equals the index's ``id`` order and an ``after`` cursor maps to
it exactly; the domain completes the index partition key (a domain id may itself contain ``/``,
so the id is split at the fixed 36th character, never at a slash).

How a record maps onto :class:`~neurosphere_core.lifecycle.models.TargetRecord`:

- ``data_class`` is always ``interaction_content`` (``DATA_CLASS_INTERACTION``), so a legal hold
  selecting that class covers every captured interaction;
- ``created_at`` is the record's ``captured_at``, which the engine's min/max retention rule runs
  from, and ``expires_at`` is the record's own expiry (the earlier of the capture policy's
  retention and the rule); the engine expires at the earlier of the two and never before
  minimum retention (item 8);
- ``subject_id`` is the record's ``principal_id`` (the PRP-99 principal pseudonym), the only
  person identifier an index record carries;
- ``pseudonymized`` is true once the record carries neither a principal nor a content reference.

Purge order is blob first, then the index document, and both steps are idempotent: a purge
interrupted between them is completed by the next run, and a read in between answers
``content_purged`` (the store sees an index document whose blob is gone). Only the blob name the
store would derive for the record is ever deleted; a pointer in the document is never trusted as
a delete target.

``pseudonymize`` (PRP-102 clarification 6, an ASSUMPTION until PRP-83 confirms the DSR
semantics) deletes the content blob, because encrypted content cannot be pseudonymized in place,
and rewrites the index record with ``principal_id`` and ``content_ref`` cleared. ``export``
returns index metadata only: never content, never the content reference, and it never touches a
key wrapper (this module has none).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Final

from neurosphere_contracts.interactions.v1.interaction_record import InteractionRecord

from neurosphere_core.errors import CapabilityUnavailableError
from neurosphere_core.interactions.blob_content import ContentBackend, content_blob_name
from neurosphere_core.interactions.cosmos_index import IndexBackend
from neurosphere_core.interactions.models import (
    CONTENT_RECORD_MISMATCH,
    DATA_CLASS_INTERACTION,
    MAX_QUERY_PAGE_SIZE,
    InteractionStoreError,
    parse_timestamp,
)
from neurosphere_core.lifecycle.adapters import BackendTarget
from neurosphere_core.lifecycle.rules import is_audit_container

__all__ = [
    "DATA_CLASS_INTERACTION",
    "KIND_INTERACTION",
    "InteractionLifecycleBackend",
    "InteractionTarget",
    "interaction_record_id",
    "interaction_target",
    "parse_interaction_record_id",
]

_LOG = logging.getLogger(__name__)

KIND_INTERACTION: Final = "interaction"
_DOC_TYPE: Final = "interaction"
_UUID: Final = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_UUID_LEN: Final = 36
#: ``TargetRecord.record_id`` and ``LegalHold.record_id`` allow at most this many characters.
_MAX_RECORD_ID: Final = 512


def interaction_record_id(interaction_id: str, domain_id: str) -> str:
    """The lifecycle record id of one interaction (``{interaction_id}/{domain_id}``)."""
    if not _UUID.fullmatch(interaction_id) or not domain_id:
        raise ValueError("not an interaction record id")
    return f"{interaction_id}/{domain_id}"


def parse_interaction_record_id(record_id: object) -> tuple[str, str] | None:
    """``(interaction_id, domain_id)`` of a record id, or ``None`` for anything else."""
    if not isinstance(record_id, str) or len(record_id) <= _UUID_LEN + 1:
        return None
    interaction_id, sep, domain_id = (
        record_id[:_UUID_LEN],
        record_id[_UUID_LEN],
        record_id[_UUID_LEN + 1 :],
    )
    if sep != "/" or not _UUID.fullmatch(interaction_id) or not domain_id:
        return None
    return interaction_id, domain_id


def _cursor(after: str | None) -> str | None:
    """Index ``id`` cursor for a record-id cursor (record-id order equals interaction-id order)."""
    if after is None:
        return None
    parsed = parse_interaction_record_id(after)
    return parsed[0] if parsed is not None else after[:_UUID_LEN]


class InteractionLifecycleBackend:
    """:class:`~neurosphere_core.lifecycle.adapters.DocumentBackend` for one customer's content.

    ``index`` and ``content`` are item 4's backends (Cosmos or in-memory index; blob or
    in-memory content). No key wrapper is taken: nothing here decrypts.
    """

    def __init__(self, index: IndexBackend, content: ContentBackend, *, customer_id: str) -> None:
        if not customer_id or "/" in customer_id or "\\" in customer_id:
            raise ValueError("customer_id is not usable as an interaction partition")
        self._index = index
        self._content = content
        self._customer = customer_id

    # -- mapping ------------------------------------------------------------------------------

    @staticmethod
    def _created_at(record: InteractionRecord) -> datetime:
        try:
            return parse_timestamp(record.captured_at.root)
        except ValueError:
            return datetime.now(UTC)  # unparsable: never looks older than it is

    def _mapping(self, record: InteractionRecord) -> dict[str, Any] | None:
        domain_id = record.domain_id.root
        record_id = interaction_record_id(record.interaction_id.root, domain_id)
        if len(record_id) > _MAX_RECORD_ID:
            # Not addressable through the lifecycle API; visible as a reason code, never data.
            _LOG.warning(
                "interaction record not addressable by lifecycle",
                extra={"reason": "interaction_record_id_too_long"},
            )
            return None
        principal = record.principal_id.root if record.principal_id is not None else None
        return {
            "id": record_id,
            "data_class": DATA_CLASS_INTERACTION,
            "created_at": self._created_at(record),
            "subject_id": principal,
            "doc_type": _DOC_TYPE,
            "customer_id": record.customer_id.root,
            "domain_id": domain_id,
            "pseudonymized": principal is None and record.content_ref is None,
            # The capture policy's expiry; the engine expires at the earlier of this and the rule.
            "expires_at": self._expires_at(record),
        }

    @staticmethod
    def _expires_at(record: InteractionRecord) -> datetime | None:
        try:
            return parse_timestamp(record.expires_at.root)
        except ValueError:
            return None  # unparsable: fall back to the class rule, never expire early

    async def _record(self, record_id: str) -> InteractionRecord | None:
        parsed = parse_interaction_record_id(record_id)
        if parsed is None:
            return None
        interaction_id, domain_id = parsed
        return await self._index.get(self._customer, domain_id, interaction_id)

    @staticmethod
    def _blob_name(record: InteractionRecord) -> str | None:
        """The one blob name the store writes for ``record``; ``None`` when none can exist."""
        try:
            return content_blob_name(
                record.customer_id.root,
                record.domain_id.root,
                parse_timestamp(record.captured_at.root),
                record.interaction_id.root,
            )
        except ValueError:
            if record.content_ref is not None:
                # A record pointing at content under a name the store never writes.
                raise InteractionStoreError(CONTENT_RECORD_MISMATCH) from None
            return None

    async def _delete_blob(self, record: InteractionRecord) -> None:
        name = self._blob_name(record)
        if name is not None:
            await self._content.delete(name)  # idempotent: absent is fine

    async def _pages(
        self, limit: int, after: str | None, principal_id: str | None
    ) -> list[Mapping[str, Any]]:
        """Up to ``limit`` mapped records, paging the index in bounded steps."""
        want = max(1, limit)
        cursor = _cursor(after)
        out: list[Mapping[str, Any]] = []
        while len(out) < want:
            step = min(MAX_QUERY_PAGE_SIZE, want - len(out))
            rows = await self._index.list_records(
                limit=step, after=cursor, customer_id=self._customer, principal_id=principal_id
            )
            for row in rows:
                mapped = self._mapping(row)
                if mapped is not None:
                    out.append(mapped)
                elif principal_id is not None:
                    # A subject request must not silently miss one of the subject's records:
                    # fail closed rather than report the erase or export as complete.
                    raise CapabilityUnavailableError("interaction_record_id_too_long")
            if len(rows) < step:
                break
            cursor = rows[-1].interaction_id.root
        return out

    # -- DocumentBackend -----------------------------------------------------------------------

    async def read(self, record_id: str) -> Mapping[str, Any] | None:
        record = await self._record(record_id)
        return None if record is None else self._mapping(record)

    async def remove(self, record_id: str) -> None:
        """Blob first, then the index document. A rerun completes an interrupted purge."""
        parsed = parse_interaction_record_id(record_id)
        if parsed is None:
            return  # not an interaction record id: never delete anything
        record = await self._record(record_id)
        if record is None:
            return
        await self._delete_blob(record)
        await self._index.delete(self._customer, parsed[1], parsed[0])

    async def page(self, data_class: str, limit: int, after: str | None) -> list[Mapping[str, Any]]:
        if data_class != DATA_CLASS_INTERACTION:
            return []
        return await self._pages(limit, after, None)

    async def page_by_subject(
        self, subject_id: str, limit: int, after: str | None
    ) -> list[Mapping[str, Any]]:
        return await self._pages(limit, after, subject_id)

    async def redact_subject(self, record_id: str) -> None:
        """Delete the content blob, then clear the principal and the content reference."""
        record = await self._record(record_id)
        if record is None:
            return
        await self._delete_blob(record)
        if record.principal_id is None and record.content_ref is None:
            return
        body = record.model_dump(mode="json")
        body["principal_id"] = None
        body["content_ref"] = None
        await self._index.replace(InteractionRecord.model_validate(body))

    async def project(self, record_id: str) -> Mapping[str, Any]:
        """Index metadata only: no content, no content reference, no decryption."""
        record = await self._record(record_id)
        if record is None:
            return {}
        body = record.model_dump(mode="json")
        body.pop("content_ref", None)
        body["content_stored"] = record.content_ref is not None
        return body


class InteractionTarget(BackendTarget):
    """The ``interaction`` lifecycle target (data class ``interaction_content``)."""

    def __init__(self, container: str, backend: InteractionLifecycleBackend) -> None:
        super().__init__(KIND_INTERACTION, container, backend)


def interaction_target(
    container_name: str, backend: InteractionLifecycleBackend
) -> InteractionTarget:
    """The registry-ready target. Refuses the audit container by name."""
    if is_audit_container(container_name):
        raise ValueError("the audit container cannot be a lifecycle target")
    return InteractionTarget(container_name, backend)
