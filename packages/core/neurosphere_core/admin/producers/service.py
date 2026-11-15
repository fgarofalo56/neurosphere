"""Producer administration over the ``admin_config`` store (PRP-41 item 1).

``ProducerAdmin`` creates, rotates, enables/disables, reads and lists ``ProducerRecord``
documents (kind ``producer``, document id = ``producer_id``). Rules:

* the secret is generated here, returned once in :class:`ProducerResult.issued` and only its
  SHA-256 digest is stored; nothing in this module logs;
* a requested customer other than the caller's is ``forbidden`` (``cross_customer``) and a cloud
  other than the deployment's is ``invalid_schema`` (``cross_cloud``), both BEFORE any write;
* every update goes through the repository's ``If-Match`` precondition (``stale_version``);
* a duplicate id is ``stale_version`` (``admin_config_exists``), ids are never reused.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final, Literal

from neurosphere_contracts.admin.v1.admin_config_document import AdminConfigDocument
from neurosphere_contracts.admin.v1.producer_record import ProducerRecord

from neurosphere_core.admin.models import ADMIN_CONFIG_SCHEMA_VERSION, CloudName
from neurosphere_core.admin.producers.secret import IssuedSecret, issue_secret
from neurosphere_core.admin.store import DEFAULT_LIST_LIMIT, AdminConfigRepository
from neurosphere_core.errors import (
    ForbiddenError,
    InvalidSchemaError,
    NotFoundError,
    ValidationIssue,
)

__all__ = [
    "PRODUCER_KIND",
    "ProducerAdmin",
    "ProducerResult",
    "registration_from_record",
]

PRODUCER_KIND: Final = "producer"
ObservationKind = Literal["gateway", "application", "billing"]
ProducerStatus = Literal["active", "disabled"]
Clock = Callable[[], datetime]


@dataclass(frozen=True, slots=True)
class ProducerResult:
    """The stored document, plus the show-once secret on create and rotate only."""

    document: AdminConfigDocument
    issued: IssuedSecret | None = None
    issued_at: str | None = None


def _stamp(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _refuse(pointer: str, detail: str, reason: str) -> InvalidSchemaError:
    return InvalidSchemaError(
        "producer request is invalid", errors=[ValidationIssue(pointer, detail)], reason=reason
    )


def _record(document: AdminConfigDocument) -> ProducerRecord:
    body = document.body
    if not isinstance(body, ProducerRecord):  # pragma: no cover - kind pins the model
        raise NotFoundError("no such producer", reason="producer_not_found")
    return body


def registration_from_record(record: ProducerRecord) -> dict[str, Any]:
    """Ingest-edge registration (``ProducerRegistration`` JSON shape) for a stored record."""
    return {
        "producer_id": record.producer_id,
        "secret_sha256": record.secret_sha256,
        "customer_id": record.customer_id.root,
        "cloud": record.cloud.root,
        "sources": {s.source_id: s.observation_kind for s in record.sources},
    }


class ProducerAdmin:
    def __init__(
        self,
        repository: AdminConfigRepository,
        *,
        cloud: CloudName,
        clock: Clock | None = None,
        token_factory: Callable[[int], str] | None = None,
    ) -> None:
        self._repo = repository
        self._cloud: CloudName = cloud
        self._clock: Clock = clock or (lambda: datetime.now(UTC))
        self._token_factory = token_factory

    def _issue(self) -> IssuedSecret:
        if self._token_factory is None:
            return issue_secret()
        return issue_secret(self._token_factory)

    def _body(
        self,
        customer_id: str,
        producer_id: str,
        cloud: str,
        sources: Mapping[str, str],
        *,
        digest: str,
        status: ProducerStatus,
        rotated_at: str,
    ) -> ProducerRecord:
        return ProducerRecord.model_validate(
            {
                "schema_version": ADMIN_CONFIG_SCHEMA_VERSION,
                "producer_id": producer_id,
                "customer_id": customer_id,
                "cloud": cloud,
                "sources": [
                    {"source_id": sid, "observation_kind": kind}
                    for sid, kind in sorted(sources.items())
                ],
                "secret_sha256": digest,
                "status": status,
                "rotated_at": rotated_at,
            }
        )

    async def create(
        self,
        customer_id: str,
        producer_id: str,
        *,
        cloud: str,
        sources: Mapping[str, ObservationKind],
        updated_by: str,
        requested_customer_id: str | None = None,
    ) -> ProducerResult:
        if requested_customer_id is not None and requested_customer_id != customer_id:
            raise ForbiddenError("producer belongs to another customer", reason="cross_customer")
        if cloud != self._cloud:
            raise _refuse("/cloud", "another cloud", "cross_cloud")
        if not sources:
            raise _refuse("/sources", "at least one source", "sources_required")
        issued = self._issue()
        issued_at = _stamp(self._clock())
        body = self._body(
            customer_id,
            producer_id,
            cloud,
            sources,
            digest=issued.sha256,
            status="active",
            rotated_at=issued_at,
        )
        document = await self._repo.create(
            customer_id, PRODUCER_KIND, producer_id, body, updated_by=updated_by
        )
        return ProducerResult(document, issued, issued_at)

    async def get(self, customer_id: str, producer_id: str) -> AdminConfigDocument:
        document = await self._repo.get(customer_id, PRODUCER_KIND, producer_id)
        if document is None:
            raise NotFoundError("no such producer", reason="producer_not_found")
        return document

    async def list(
        self, customer_id: str, *, limit: int = DEFAULT_LIST_LIMIT
    ) -> list[AdminConfigDocument]:
        return await self._repo.list_by_kind(customer_id, PRODUCER_KIND, limit=limit)

    async def rotate(
        self, customer_id: str, producer_id: str, *, if_match: str, updated_by: str
    ) -> ProducerResult:
        current = _record(await self.get(customer_id, producer_id))
        issued = self._issue()
        issued_at = _stamp(self._clock())
        body = self._body(
            customer_id,
            producer_id,
            current.cloud.root,
            {s.source_id: s.observation_kind for s in current.sources},
            digest=issued.sha256,
            status=current.status,
            rotated_at=issued_at,
        )
        document = await self._repo.replace(
            customer_id, PRODUCER_KIND, producer_id, body, if_match=if_match, updated_by=updated_by
        )
        return ProducerResult(document, issued, issued_at)

    async def set_status(
        self,
        customer_id: str,
        producer_id: str,
        status: ProducerStatus,
        *,
        if_match: str,
        updated_by: str,
    ) -> ProducerResult:
        current = _record(await self.get(customer_id, producer_id))
        body = current.model_copy(update={"status": status})
        document = await self._repo.replace(
            customer_id, PRODUCER_KIND, producer_id, body, if_match=if_match, updated_by=updated_by
        )
        return ProducerResult(document)
