"""Approval guard for the live catalog latency mode (PRP-10 item 13).

Pure and import-light so the refusal is unit-tested in CI without any Azure SDK call.
"""

from __future__ import annotations

from collections.abc import Mapping

ENV_APPROVED = "NS_LIVE_APPROVED"
ENV_ENDPOINT = "NS_CATALOG_LATENCY_LIVE_ENDPOINT"
ENV_DATABASE = "NS_CATALOG_LATENCY_LIVE_DATABASE"

NOT_APPROVED_REASON = "OPEN: live run not approved (set NS_LIVE_APPROVED=1 with operator approval)"


def live_refusal(env: Mapping[str, str]) -> str | None:
    """Return the reason the live run must not start, or ``None`` when it may proceed."""
    if env.get(ENV_APPROVED) != "1":
        return NOT_APPROVED_REASON
    if not env.get(ENV_ENDPOINT):
        return f"OPEN: live run needs {ENV_ENDPOINT} (Cosmos account endpoint, Entra auth only)"
    if not env.get(ENV_DATABASE):
        return (
            f"OPEN: live run needs {ENV_DATABASE} (an existing database; containers are throwaway)"
        )
    return None
