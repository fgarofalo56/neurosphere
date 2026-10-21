"""Execution-time permission recheck port (implemented by the API and worker wiring).

``ActionService.confirm`` and ``apply_approval`` (and the executor before apply) call
:meth:`PermissionRechecker.check` against the CURRENT policy store, because approval is not a
standing grant: a revocation between confirmation, approval and execution must block.

Contract: ``check`` returns ``True`` (granted) or ``False`` (denied, including a revoked
principal). It must raise ``dependency_transient`` when the policy store or revocation store
cannot be read; it must never answer ``True`` from a stale cache after an outage (fail closed).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

__all__ = ["GrantTablePermissionRechecker", "PermissionRechecker"]


@runtime_checkable
class PermissionRechecker(Protocol):
    async def check(
        self, principal_id: str, customer_id: str, domain_id: str, permission: str
    ) -> bool:
        """Current decision for ``principal_id`` holding ``permission`` on the domain."""
        ...


class GrantTablePermissionRechecker:
    """Deny-by-default grant table. Test double and sandbox wiring, never production policy.

    ``fail_with`` makes every check raise (policy store outage simulation).
    """

    def __init__(self) -> None:
        self._grants: set[tuple[str, str, str, str]] = set()
        self.error: Exception | None = None
        self.calls: list[tuple[str, str, str, str]] = []

    def grant(self, principal_id: str, customer_id: str, domain_id: str, permission: str) -> None:
        self._grants.add((principal_id, customer_id, domain_id, permission))

    def revoke(self, principal_id: str, customer_id: str, domain_id: str, permission: str) -> None:
        self._grants.discard((principal_id, customer_id, domain_id, permission))

    def fail_with(self, error: Exception | None) -> None:
        self.error = error

    async def check(
        self, principal_id: str, customer_id: str, domain_id: str, permission: str
    ) -> bool:
        entry = (principal_id, customer_id, domain_id, permission)
        self.calls.append(entry)
        if self.error is not None:
            raise self.error
        return entry in self._grants
