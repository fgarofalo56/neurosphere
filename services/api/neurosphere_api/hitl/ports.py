"""Adapters and ports the review queue API needs (PRP-17 item 4).

* :class:`RecheckerReviewerAuthorizer` -- the HITL ``ReviewerAuthorizer`` over the action plane's
  ``PermissionRechecker`` (the CURRENT policy store), so reviewers and action approvals are
  checked by the same source. Outage -> ``dependency_transient`` (503), never ``True``.
* :class:`ReviewerDirectory` -- resolves the pseudonymous ``Actor`` of a principal one reviewer
  assigns an item to (``app.state.reviewer_directory``; optional: without it only claiming,
  ``assignee_principal_id: null``, is available).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from neurosphere_contracts.actions.v1.actor import Actor
from neurosphere_core.actions import PermissionRechecker
from neurosphere_core.actions.errors import POLICY_STORE_UNAVAILABLE
from neurosphere_core.auth.scope.permissions import Permission
from neurosphere_core.errors import DependencyTransientError, NeuroSphereError

__all__ = ["RecheckerReviewerAuthorizer", "ReviewerDirectory"]


class RecheckerReviewerAuthorizer:
    """``ReviewerAuthorizer`` backed by a ``PermissionRechecker`` (fail closed)."""

    def __init__(self, rechecker: PermissionRechecker) -> None:
        self._rechecker = rechecker

    async def can_review(
        self, principal_id: str, customer_id: str, domain_id: str, permission: Permission
    ) -> bool:
        try:
            granted = await self._rechecker.check(
                principal_id, customer_id, domain_id, permission.value
            )
        except NeuroSphereError:
            raise
        except Exception as exc:
            raise DependencyTransientError(
                "policy store unavailable", reason=POLICY_STORE_UNAVAILABLE
            ) from exc
        return granted is True


@runtime_checkable
class ReviewerDirectory(Protocol):
    async def actor_for(self, customer_id: str, principal_id: str) -> Actor | None:
        """Pseudonymous actor of ``principal_id`` in ``customer_id``; ``None`` when unknown."""
        ...
