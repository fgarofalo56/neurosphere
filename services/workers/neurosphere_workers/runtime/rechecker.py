"""The worker-side permission recheck, built once the same way for every role that needs it.

``actions`` (the intent executor), ``notifications`` (the delivery-time scope recheck) and the HITL
notification bridge all ask the same question of the same stores: does this principal currently
hold this permission in this domain. One construction keeps them on one policy read path and one
revocation check, instead of three copies that could drift.
"""

from __future__ import annotations

from neurosphere_core.actions.recheck import PolicyPermissionRechecker
from neurosphere_core.cloud import Settings

from neurosphere_workers.runtime.identity import PolicyStack

__all__ = ["build_permission_rechecker"]


def build_permission_rechecker(settings: Settings, stack: PolicyStack) -> PolicyPermissionRechecker:
    return PolicyPermissionRechecker(
        cloud=settings.cloud_profile.cloud,
        policy_repository=stack.policy,
        revocation_checker=stack.revocation,
    )
