"""The ``AuthorizedSearch`` protocol (PRP-03 clarification 10).

Search is authorized by construction: the caller passes the server-derived
``IdentityScope`` plus a structured request (a term string and allowlisted filters) and a
``Budget``. Raw query text produced by a model never reaches an implementation; the term is
only ever tokenized, never parsed or evaluated. Implementations must apply the scope before
ranking so out-of-scope documents cannot influence results or scores.

PRP-03 provides the in-process fixture implementation; PRP-10 provides the Azure AI Search one.
"""

from __future__ import annotations

from typing import Annotated, Literal, Protocol, runtime_checkable

from neurosphere_contracts.query.v1.budget import Budget
from neurosphere_contracts.scope.v1.identity_scope import IdentityScope
from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, StrictStr

CANONICAL_ID_PATTERN = (
    r"^(commercial|government):[a-z0-9._-]+:[a-z0-9._-]+:[a-z0-9._-]+:[a-z0-9._/=-]+$"
)

CanonicalIdStr = Annotated[StrictStr, Field(max_length=512, pattern=CANONICAL_ID_PATTERN)]

SearchEntity = Literal[
    "person",
    "agent",
    "agent_version",
    "model_deployment",
    "grounding_source",
    "tool",
    "service",
    "domain",
    "owner",
    "policy",
    "recommendation",
    "run_reference",
]


class SearchFilters(BaseModel):
    """Allowlisted filters, combined with AND. They can only narrow the scope, never widen it."""

    model_config = ConfigDict(extra="forbid")

    entities: Annotated[list[SearchEntity] | None, Field(max_length=12)] = None
    domain_ids: Annotated[list[CanonicalIdStr] | None, Field(max_length=100)] = None


class SearchRequest(BaseModel):
    """A term string plus structured filters plus a mandatory budget."""

    model_config = ConfigDict(extra="forbid")

    term: Annotated[StrictStr, Field(max_length=256)]
    filters: SearchFilters = Field(default_factory=SearchFilters)
    budget: Budget


class SearchHit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: CanonicalIdStr
    score: StrictFloat


class SearchResult(BaseModel):
    """Ranked hits (best first) with an explicit partial-result flag."""

    model_config = ConfigDict(extra="forbid")

    hits: list[SearchHit]
    matched: Annotated[StrictInt, Field(ge=0)]
    """Candidates that matched before the result limit applied (scored ones on timeout)."""
    partial: bool
    """True when a budget stopped the result early; the caller must label it as partial."""
    partial_reason: Literal["limit", "timeout_ms"] | None = None


@runtime_checkable
class AuthorizedSearch(Protocol):
    """Scope-first search over catalog entity documents."""

    async def search(self, scope: IdentityScope, request: SearchRequest) -> SearchResult: ...
