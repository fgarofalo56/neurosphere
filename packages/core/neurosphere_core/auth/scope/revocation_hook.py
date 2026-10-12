"""Minimal revocation interface consumed by scope derivation (implementation: PRP-06 item 5).

Derivation calls ``is_revoked`` before reading the policy store. ``True`` denies with
``forbidden`` (reason ``principal_revoked``). A checker that raises ``dependency_transient``
propagates unchanged; any other failure is converted to ``dependency_transient``. No failure is
ever treated as "not revoked".
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

__all__ = ["RevocationChecker"]


@runtime_checkable
class RevocationChecker(Protocol):
    async def is_revoked(self, principal_id: str, issued_at: datetime) -> bool:
        """Whether tokens for canonical ``principal_id`` issued at ``issued_at`` are revoked."""
        ...
