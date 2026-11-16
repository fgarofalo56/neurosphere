"""Read and replace the stored review policy (PRP-44 item 1).

One ``admin_config`` document, kind ``review_policy``, id ``review-policy``. ``If-Match`` is
always required: while nothing is stored the ETag is :data:`DEFAULTS_ETAG`, so the first write
says "I am replacing the built-in defaults". The server assigns ``policy_version`` as
``admin-v<document version>`` (a client value is replaced), so the version bumps on every write.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from neurosphere_contracts.admin.v1.admin_config_document import AdminConfigDocument
from neurosphere_contracts.admin.v1.review_policy_document import ReviewPolicyDocument

from neurosphere_core.admin.platform.review_policy import (
    REVIEW_POLICY_ID,
    REVIEW_POLICY_KIND,
    PolicyChange,
    defaults_document,
    diff_documents,
    validate_review_policy,
)
from neurosphere_core.admin.store import AdminConfigRepository
from neurosphere_core.errors import StaleVersionError

__all__ = ["DEFAULTS_ETAG", "ReviewPolicyAdmin", "ReviewPolicyRead", "ReviewPolicyWrite"]

DEFAULTS_ETAG: Final = '"defaults"'


@dataclass(frozen=True, slots=True)
class ReviewPolicyRead:
    document: ReviewPolicyDocument
    etag: str
    version: int
    #: ``"stored"`` or ``"defaults"``.
    source: str


@dataclass(frozen=True, slots=True)
class ReviewPolicyWrite:
    stored: AdminConfigDocument
    before: ReviewPolicyDocument
    after: ReviewPolicyDocument
    changes: tuple[PolicyChange, ...]


def _body(document: AdminConfigDocument) -> ReviewPolicyDocument:
    body = document.body
    assert isinstance(body, ReviewPolicyDocument)
    return body


class ReviewPolicyAdmin:
    def __init__(self, repository: AdminConfigRepository) -> None:
        self._repository = repository

    async def get(self, customer_id: str) -> ReviewPolicyRead:
        stored = await self._repository.get(customer_id, REVIEW_POLICY_KIND, REVIEW_POLICY_ID)
        if stored is None:
            return ReviewPolicyRead(defaults_document(), DEFAULTS_ETAG, 0, "defaults")
        return ReviewPolicyRead(_body(stored), stored.etag.root, stored.version.root, "stored")

    async def replace(
        self,
        customer_id: str,
        document: ReviewPolicyDocument,
        *,
        if_match: str,
        updated_by: str,
    ) -> ReviewPolicyWrite:
        validate_review_policy(document)
        current = await self.get(customer_id)
        if current.etag.strip('"') != if_match.strip('"'):
            raise StaleVersionError(
                "review policy changed since it was read", reason="admin_config_modified"
            )
        next_version = current.version + 1
        after = document.model_copy(update={"policy_version": f"admin-v{next_version}"})
        if current.source == "defaults":
            stored = await self._repository.create(
                customer_id, REVIEW_POLICY_KIND, REVIEW_POLICY_ID, after, updated_by=updated_by
            )
        else:
            stored = await self._repository.replace(
                customer_id,
                REVIEW_POLICY_KIND,
                REVIEW_POLICY_ID,
                after,
                if_match=current.etag,
                updated_by=updated_by,
            )
        return ReviewPolicyWrite(
            stored, current.document, after, tuple(diff_documents(current.document, after))
        )
