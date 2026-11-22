"""The ``recommend_agent`` copilot tool (PRP-78 item 3): task-to-agent matching.

The model supplies only a contract ``AgentMatchRequest`` (``extra="forbid"``, no scope field: a
``domain_id`` or ``customer_id`` inside ``request`` is an unknown key and is refused by the
contract). Domains are server-derived from the scope (``data.read``, the same permission the API
match route requires), optionally narrowed by ``preferred_domains`` (the dock's domain context),
capped at ``MAX_MATCH_DOMAINS`` and matched one at a time through the ``AgentMatchReader`` port.

Errors per domain: ``ForbiddenError`` and ``NotFoundError`` from the matcher skip that domain (a
domain the scope cannot match in is indistinguishable from an empty one, and one bad domain must
not fail the call). Every other error (validation, transient dependency, timeout, programming
errors) propagates. No readable domain at all raises ``ToolPermissionError``.

Factory use (item 4)::

    recommend_agent_spec(matcher=matcher, clock=clock, freshness=freshness,
                         preferred_domains=lambda scope: ("commercial:c:catalog:domain:ops",))
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Any, Final

from neurosphere_contracts.recommendations.v1.agent_match_request import AgentMatchRequest
from neurosphere_contracts.recommendations.v1.agent_match_response import AgentMatchCandidate

from neurosphere_core.auth.scope import Permission, domains_with_permission
from neurosphere_core.copilot.tools.args import ToolArgs
from neurosphere_core.copilot.tools.errors import ToolPermissionError
from neurosphere_core.copilot.tools.models import (
    Citation,
    FreshnessPolicy,
    ToolRecord,
    ToolResult,
)
from neurosphere_core.copilot.tools.registry import ToolHandler, ToolSpec
from neurosphere_core.errors import ForbiddenError, NotFoundError
from neurosphere_core.recommendations.matching.service import AgentMatchReader
from neurosphere_core.scope import IdentityScope

__all__ = [
    "MAX_MATCH_DOMAINS",
    "TOOL_NAME",
    "RecommendAgentArgs",
    "recommend_agent_spec",
]

TOOL_NAME: Final = "recommend_agent"
MAX_MATCH_DOMAINS: Final = 5
_DEFAULT_LIMIT: Final = 10
_PERMISSION: Final = Permission.DATA_READ


class RecommendAgentArgs(ToolArgs):
    """The model supplies the match request only; scope never comes from arguments."""

    request: AgentMatchRequest


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _plain(value: Any) -> str:
    while hasattr(value, "root"):
        value = value.root
    return str(value)


def _domains(
    scope: IdentityScope,
    now: datetime,
    preferred: Callable[[IdentityScope], Sequence[str]] | None,
) -> tuple[tuple[str, ...], bool]:
    """Readable domains (narrowed, never widened, by ``preferred``) capped; and whether cut."""
    readable = tuple(sorted(domains_with_permission(scope, _PERMISSION, now=now)))
    if not readable:
        raise ToolPermissionError(_PERMISSION.value)
    if preferred is not None:
        wanted = set(preferred(scope))
        if wanted:
            readable = tuple(d for d in readable if d in wanted)
    return readable[:MAX_MATCH_DOMAINS], len(readable) > MAX_MATCH_DOMAINS


def _handler(
    matcher: AgentMatchReader,
    clock: Callable[[], datetime],
    freshness: FreshnessPolicy,
    preferred: Callable[[IdentityScope], Sequence[str]] | None,
) -> ToolHandler:
    async def run(scope: IdentityScope, args: RecommendAgentArgs) -> ToolResult:
        now = clock()
        request = args.request
        domains, truncated = _domains(scope, now, preferred)
        readable = frozenset(domains_with_permission(scope, _PERMISSION, now=now))
        limit = request.limit or _DEFAULT_LIMIT
        found: list[tuple[AgentMatchCandidate, str, str]] = []
        for domain in domains:
            try:
                response = await matcher.match(scope, domain, request)
            except (ForbiddenError, NotFoundError):
                continue
            response_domain = _plain(response.domain_id)
            # A misbehaving port must not leak another domain: re-filter on the readable set.
            if response_domain != domain or response_domain not in readable:
                continue
            truncated = truncated or response.truncated
            generated = _plain(response.generated_at)
            found.extend((cand, response_domain, generated) for cand in response.candidates)
        found.sort(key=lambda item: (-item[0].score, _plain(item[0].entity_id)))
        if len(found) > limit:
            found, truncated = found[:limit], True
        records: list[ToolRecord] = []
        citations: list[Citation] = []
        for cand, domain, generated in found:
            entity_id = _plain(cand.entity_id)
            data: dict[str, Any] = cand.model_dump(mode="json")
            data["domain_id"] = domain
            records.append(ToolRecord(record_id=entity_id, kind=cand.entity_type, data=data))
            citations.append(
                Citation(
                    record_id=entity_id,
                    kind=cand.entity_type,
                    source="agent_match",
                    as_of=generated,
                    freshness=freshness.state(generated, now),
                )
            )
        return ToolResult(
            tool=TOOL_NAME,
            records=tuple(records),
            citations=tuple(citations),
            truncated=truncated,
            domain_ids=tuple(sorted(domains)),
        )

    return run


def recommend_agent_spec(
    *,
    matcher: AgentMatchReader,
    clock: Callable[[], datetime] = _utc_now,
    freshness: FreshnessPolicy = FreshnessPolicy(),  # noqa: B008 - frozen dataclass default
    preferred_domains: Callable[[IdentityScope], Sequence[str]] | None = None,
) -> ToolSpec:
    """Build the ``recommend_agent`` spec (permission ``data.read``, read-only).

    ``preferred_domains`` returns the dock's context domains; a non-empty result narrows the
    readable set to the intersection (it can never add a domain the scope cannot read).
    """
    return ToolSpec(
        TOOL_NAME,
        "Rank agents or tools for a task in the caller's readable domains.",
        RecommendAgentArgs,
        _PERMISSION,
        _handler(matcher, clock, freshness, preferred_domains),
    )
