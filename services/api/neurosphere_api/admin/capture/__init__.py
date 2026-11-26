"""Read-only interaction capture admin API (PRP-103 item 5), at ``/api/v1/admin/interactions``.

Capture policies and capture status: metadata and counters only, never content. There is no
write route; changes are ``capture_policy_change`` actions (PRP-108). See ``router`` for the
route table and ``service`` for the authorization rules.
"""

from __future__ import annotations

from neurosphere_api.admin.capture.router import PREFIX, build_router, register

__all__ = ["PREFIX", "build_router", "register"]
