"""FastAPI providers for the agent match routes (PRP-72 item 4).

* :func:`get_agent_matcher` -- ``app.state.agent_matcher`` (an ``AgentMatcher``). When the data
  builder could not compose it because search or the catalog is unavailable it records the reason
  code in ``app.state.agent_matcher_unavailable`` and this provider answers 409
  ``capability_unavailable`` with that reason. With neither set (nothing composed it) it fails
  closed with 503 ``recommendations_unconfigured``.
* :func:`get_match_audit` -- ``app.state.audit_repository``; 503 ``audit_unconfigured`` when unset
  (a feedback write is never accepted without its audit records).

Tests use ``app.dependency_overrides``. No ``from __future__ import annotations``: FastAPI
inspects these signatures.
"""

from typing import Final

from fastapi import Request
from neurosphere_core.audit import AuditRepository
from neurosphere_core.errors import CapabilityUnavailableError, DependencyTransientError
from neurosphere_core.recommendations.matching import AgentMatcher

__all__ = [
    "MATCHER_ATTRIBUTE",
    "UNAVAILABLE_ATTRIBUTE",
    "get_agent_matcher",
    "get_match_audit",
]

MATCHER_ATTRIBUTE: Final = "agent_matcher"
UNAVAILABLE_ATTRIBUTE: Final = "agent_matcher_unavailable"


def get_agent_matcher(request: Request) -> AgentMatcher:
    state = request.app.state
    matcher = getattr(state, MATCHER_ATTRIBUTE, None)
    if isinstance(matcher, AgentMatcher):
        return matcher
    reason = getattr(state, UNAVAILABLE_ATTRIBUTE, None)
    if isinstance(reason, str) and reason:
        raise CapabilityUnavailableError(reason, detail="agent matching is not available")
    raise DependencyTransientError(
        "the agent matcher is not configured", reason="recommendations_unconfigured"
    )


def get_match_audit(request: Request) -> AuditRepository:
    audit = getattr(request.app.state, "audit_repository", None)
    if not isinstance(audit, AuditRepository):
        raise DependencyTransientError("audit is not configured", reason="audit_unconfigured")
    return audit
