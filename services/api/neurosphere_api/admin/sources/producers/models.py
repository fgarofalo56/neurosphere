"""Request and response models of the producer admin routes (PRP-41 item 3).

``ProducerView`` deliberately has no digest member: a read never carries the secret or its
SHA-256. The show-once response is the contract model ``ProducerSecretIssued``.
"""

from __future__ import annotations

from typing import Final, Literal

from neurosphere_contracts.admin.v1.admin_config_document import AdminConfigDocument
from neurosphere_contracts.admin.v1.producer_record import ProducerRecord
from neurosphere_contracts.admin.v1.producer_secret_issued import ProducerSecretIssued
from neurosphere_core.admin.producers import ProducerResult
from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "DEFAULT_PAGE_LIMIT",
    "MAX_PAGE_LIMIT",
    "ProducerCreateRequest",
    "ProducerPage",
    "ProducerView",
    "issued_response",
    "producer_view",
]

DEFAULT_PAGE_LIMIT: Final = 100
MAX_PAGE_LIMIT: Final = 200


class ProducerCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    producer_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,128}$")
    cloud: Literal["commercial", "government"]
    #: source_id -> how that source's data is observed.
    sources: dict[
        str,
        Literal["gateway", "application", "billing"],
    ] = Field(min_length=1, max_length=64)
    #: Optional echo of the caller's customer; any other value is refused (403).
    customer_id: str | None = Field(default=None, max_length=128)


class ProducerSourceView(BaseModel):
    source_id: str
    observation_kind: Literal["gateway", "application", "billing"]


class ProducerView(BaseModel):
    producer_id: str
    customer_id: str
    cloud: Literal["commercial", "government"]
    sources: list[ProducerSourceView]
    status: Literal["active", "disabled"]
    rotated_at: str | None
    version: int
    updated_at: str


class ProducerPage(BaseModel):
    items: list[ProducerView]
    truncated: bool


def producer_view(document: AdminConfigDocument) -> ProducerView:
    body = document.body
    assert isinstance(body, ProducerRecord)  # kind pins the model
    return ProducerView(
        producer_id=body.producer_id,
        customer_id=body.customer_id.root,
        cloud=body.cloud.root,
        sources=[ProducerSourceView(**s.model_dump()) for s in body.sources],
        status=body.status,
        rotated_at=body.rotated_at.root if body.rotated_at is not None else None,
        version=document.version.root,
        updated_at=document.updated_at.root,
    )


def issued_response(result: ProducerResult) -> ProducerSecretIssued:
    issued = result.issued
    assert issued is not None and result.issued_at is not None
    return ProducerSecretIssued.model_validate(
        {
            "schema_version": "1.0.0",
            "producer_id": result.document.id.root,
            "secret": issued.secret,
            "secret_sha256": issued.sha256,
            "issued_at": result.issued_at,
            "shown_once": True,
        }
    )
