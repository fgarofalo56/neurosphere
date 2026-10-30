"""Request and response bodies of the UI-facing adapters (PRP-31 item 2).

Every request body is ``extra="forbid"``: a browser that smuggles a scope key (``domain_id``,
``customer_id``, ``cloud``), an identity (``actor``), a server timestamp (``decided_at``) or a
target (``edge_id``, ``relation_type``) gets 422 instead of having it silently honored or dropped.
Those values come from the path, the authenticated scope, the server clock or the stored edge.

The field types are plain constrained primitives rather than the generated contract root models,
so the OpenAPI document gains new components instead of renaming existing ones; the contract
models still validate the assembled ``EdgeOverride`` before the curation service sees it.
"""

from __future__ import annotations

from typing import Annotated, Literal

from neurosphere_contracts.deployment.v1.capability_matrix_entry import CapabilityMatrixEntry
from neurosphere_contracts.query.v1.budget import Budget
from neurosphere_core.catalog.protocol import EntityTypeName
from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, StrictStr

__all__ = [
    "AuditDomainList",
    "AuditDomainView",
    "CapabilityMatrixView",
    "CatalogDomainSearchRequest",
    "CurationDecisionRequest",
    "DecisionValidity",
]

#: RFC 3339 UTC timestamp with ``Z`` (the contract ``Timestamp`` pattern).
_TIMESTAMP = r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,9})?Z$"

TimestampStr = Annotated[StrictStr, Field(pattern=_TIMESTAMP)]


class CatalogDomainSearchRequest(BaseModel):
    """``POST /api/v1/catalog/domains/{domain}/search``: the server sets the domain filter."""

    model_config = ConfigDict(extra="forbid")

    term: Annotated[StrictStr, Field(max_length=256)]
    entity_types: Annotated[list[EntityTypeName] | None, Field(max_length=14)] = None
    budget: Budget


class DecisionValidity(BaseModel):
    """Pinned validity interval for ``lock``/``override`` (``valid_to`` null = open-ended)."""

    model_config = ConfigDict(extra="forbid")

    valid_from: TimestampStr
    valid_to: TimestampStr | None = None


class CurationDecisionRequest(BaseModel):
    """A steward decision as the browser may send it: the decision and its preconditions only.

    ``lock_expiry`` applies to ``lock`` and ``override`` (the lock reason is ``reason`` and the lock
    actor is the caller); ``set_confidence``/``set_validity`` apply to those two decisions only,
    which the curation service enforces.
    """

    model_config = ConfigDict(extra="forbid")

    decision: Literal["accept", "reject", "override", "lock", "unlock"]
    reason: Annotated[StrictStr, Field(min_length=1, max_length=2000)]
    expected_edge_version: Annotated[StrictInt, Field(ge=1)]
    expected_edge_etag: Annotated[StrictStr, Field(min_length=1, max_length=256)]
    lock_expiry: TimestampStr | None = None
    set_confidence: Annotated[StrictFloat, Field(ge=0.0, le=1.0)] | None = None
    set_validity: DecisionValidity | None = None


class AuditDomainView(BaseModel):
    """One domain the caller may read the audit log of."""

    model_config = ConfigDict(extra="forbid")

    domain_id: str
    display_name: str
    display_name_source: Literal["catalog", "derived"]


class AuditDomainList(BaseModel):
    """``GET /api/v1/audit/domains``: sorted by display name, then id."""

    model_config = ConfigDict(extra="forbid")

    items: list[AuditDomainView]


class CapabilityMatrixView(BaseModel):
    """``GET /api/v1/capabilities``: shipped matrix rows, unchanged (unverified stays unverified).

    ``matrix_version`` is a content digest of the whole shipped matrix (it changes whenever any
    row changes); ``observed_at`` is the latest ``observed_on`` date among all rows.
    """

    model_config = ConfigDict(extra="forbid")

    matrix_version: str
    observed_at: str
    items: list[CapabilityMatrixEntry]
