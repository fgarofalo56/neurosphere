"""Governance policy API (PRP-105 item 6): routes under ``/api/v1/governance/policy``.

The plane (``app.state.governance_policy``) is installed by ``runtime/builders/governance.py``;
the routes are in :mod:`.router`, their logic in :mod:`.service`, bodies and views in
:mod:`.models`.
"""

from neurosphere_api.governance.policy.deps import (
    OFF_REASON_ATTRIBUTE,
    STATE_ATTRIBUTE,
    GovernancePolicyPlane,
    configure_governance_policy,
    get_plane,
)
from neurosphere_api.governance.policy.router import PREFIX, build_router, register

__all__ = [
    "OFF_REASON_ATTRIBUTE",
    "PREFIX",
    "STATE_ATTRIBUTE",
    "GovernancePolicyPlane",
    "build_router",
    "configure_governance_policy",
    "get_plane",
    "register",
]
