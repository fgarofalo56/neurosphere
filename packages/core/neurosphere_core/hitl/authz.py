"""Reviewer authorization port.

The HITL service never trusts a role claim or a hidden UI control: before every assignment and
decision it asks a :class:`ReviewerAuthorizer` whether the REAL principal holds the policy's
permission on the item's customer and domain. Item 4 implements it over the PRP-06 policy store;
a policy store outage must raise ``dependency_transient`` (the caller fails closed with 503),
never return ``True``.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from neurosphere_core.auth.scope.permissions import Permission

__all__ = ["ReviewerAuthorizer"]


@runtime_checkable
class ReviewerAuthorizer(Protocol):
    async def can_review(
        self, principal_id: str, customer_id: str, domain_id: str, permission: Permission
    ) -> bool:
        """True only when ``principal_id`` holds ``permission`` on ``domain_id`` now."""
        ...
