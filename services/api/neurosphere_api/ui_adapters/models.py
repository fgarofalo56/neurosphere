"""Request and response bodies of the UI-facing adapters (PRP-31 item 2).

Every request body is ``extra="forbid"``: a browser that smuggles a scope key (``domain_id``,
``customer_id``, ``cloud``), an identity (``actor``), a server timestamp (``decided_at``) or a
target (``edge_id``, ``relation_type``) gets 422 instead of having it silently honored or dropped.
Those values come from the path, the authenticated scope, the server clock or the stored edge.

The entity write bodies (item 13) are the exception: an entity document has type-specific fields,
so they allow extra keys but refuse every server-owned key by name (422) and are bounded in size;
the entity's own contract validates the stamped document before anything is stored.

The field types are plain constrained primitives rather than the generated contract root models,
so the OpenAPI document gains new components instead of renaming existing ones; the contract
models still validate the assembled ``EdgeOverride`` before the curation service sees it.
"""

from __future__ import annotations

import json
from typing import Annotated, Any, Literal

from neurosphere_contracts.deployment.v1.capability_matrix_entry import CapabilityMatrixEntry
from neurosphere_contracts.query.v1.budget import Budget
from neurosphere_core.catalog import PresentedEdge
from neurosphere_core.catalog.protocol import EntityTypeName
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictFloat,
    StrictInt,
    StrictStr,
    model_validator,
)

__all__ = [
    "MAX_ENTITY_BYTES",
    "MAX_ENTITY_KEYS",
    "SERVER_OWNED_ENTITY_KEYS",
    "UPDATE_SERVER_OWNED_ENTITY_KEYS",
    "AuditDomainList",
    "AuditDomainView",
    "CapabilityMatrixView",
    "CatalogDomainSearchRequest",
    "CatalogEntityCreateRequest",
    "CatalogEntityUpdateRequest",
    "CreatableEntityType",
    "CurationDecisionRequest",
    "CurationEdgeView",
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


class CurationEdgeView(BaseModel):
    """``GET /api/v1/catalog/domains/{domain}/curation/edges/{edge_id}``: the presented edge plus
    the stored version and etag a decision must echo as its preconditions."""

    model_config = ConfigDict(extra="forbid")

    edge: PresentedEdge
    edge_version: Annotated[StrictInt, Field(ge=1)]
    edge_etag: Annotated[StrictStr, Field(min_length=1, max_length=256)]


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


# ------------------------------------------------------------------------ entity writes (item 13)

#: Keys of an entity document the server owns on BOTH create and update. ``id`` is minted,
#: ``cloud``/``customer_id`` come from the caller's scope, ``domain_id`` from the path, version,
#: etag, timestamps and schema version from ``CatalogService``; an owner's recertification fields
#: move only through the recertify route. A body naming any of them is 422, never overwritten.
SERVER_OWNED_ENTITY_KEYS: frozenset[str] = frozenset(
    {
        "id",
        "cloud",
        "customer_id",
        "domain_id",
        "version",
        "etag",
        "created_at",
        "updated_at",
        "schema_version",
        "recertified_at",
        "recertify_by",
    }
)
#: Additionally server-owned on update: ``CatalogService.update`` keeps the stored lifecycle
#: status (lifecycle moves only through deprecate), so a body naming it would be silently ignored.
UPDATE_SERVER_OWNED_ENTITY_KEYS: frozenset[str] = SERVER_OWNED_ENTITY_KEYS | {"lifecycle_status"}
#: Bounds on a browser entity body (top-level keys, compact JSON bytes).
MAX_ENTITY_KEYS = 64
MAX_ENTITY_BYTES = 65_536

#: Entity types the domain-path create accepts: every type ``CatalogService.create`` accepts
#: except ``domain``, whose id IS its scope anchor (a new domain cannot be created inside one).
CreatableEntityType = Literal[
    "person",
    "agent",
    "agent_version",
    "model_deployment",
    "grounding_source",
    "tool",
    "service",
    "owner",
    "policy",
    "recommendation",
    "run_reference",
    "grant",
    "mcp_server",
]


def _check_entity_body(data: Any, forbidden: frozenset[str]) -> Any:
    """Refuse server-owned keys and oversized bodies (key names only in the message)."""
    if not isinstance(data, dict):
        return data  # pydantic reports the wrong type
    offending = sorted(k for k in data if k in forbidden)
    if offending:
        raise ValueError("server-owned field(s) are not accepted: " + ", ".join(offending))
    if len(data) > MAX_ENTITY_KEYS:
        raise ValueError(f"an entity body has at most {MAX_ENTITY_KEYS} fields")
    try:
        size = len(json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    except (TypeError, ValueError):
        raise ValueError("the entity body is not JSON") from None
    if size > MAX_ENTITY_BYTES:
        raise ValueError(f"an entity body is at most {MAX_ENTITY_BYTES} bytes")
    return data


class CatalogEntityCreateRequest(BaseModel):
    """``POST /api/v1/catalog/domains/{domain}/entities``: an entity document without any
    server-owned key (see ``SERVER_OWNED_ENTITY_KEYS``). The remaining fields are validated by
    the entity's contract after the server stamps its own."""

    model_config = ConfigDict(extra="allow")

    entity_type: CreatableEntityType

    @model_validator(mode="before")
    @classmethod
    def _no_server_owned_keys(cls, data: Any) -> Any:
        return _check_entity_body(data, SERVER_OWNED_ENTITY_KEYS)

    def document(self) -> dict[str, Any]:
        """The caller's fields as a plain document (server-owned keys are added by the route)."""
        return {**(self.model_extra or {}), "entity_type": self.entity_type}


class CatalogEntityUpdateRequest(BaseModel):
    """``PUT /api/v1/catalog/domains/{domain}/entities/{entity_id}``: the replacement document
    without any server-owned key (see ``UPDATE_SERVER_OWNED_ENTITY_KEYS``). ``entity_type`` must
    equal the stored entity's type."""

    model_config = ConfigDict(extra="allow")

    entity_type: EntityTypeName

    @model_validator(mode="before")
    @classmethod
    def _no_server_owned_keys(cls, data: Any) -> Any:
        return _check_entity_body(data, UPDATE_SERVER_OWNED_ENTITY_KEYS)

    def document(self) -> dict[str, Any]:
        """The caller's fields as a plain document (server-owned keys are added by the service)."""
        return {**(self.model_extra or {}), "entity_type": self.entity_type}
