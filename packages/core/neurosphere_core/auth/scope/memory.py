"""In-memory ``PolicyRepository`` for tests and the local sandbox. Never a production store.

Mirrors the Cosmos repository contract: missing documents return ``None``; ``fail_with`` makes
every read raise (store outage simulation). Reads are counted so cache behavior is measurable.
"""

from __future__ import annotations

from neurosphere_core.auth.scope.policy import PolicyHead, PrincipalPolicy

__all__ = ["InMemoryPolicyRepository"]


class InMemoryPolicyRepository:
    def __init__(self) -> None:
        self._heads: dict[str, PolicyHead] = {}
        self._principals: dict[tuple[str, str], PrincipalPolicy] = {}
        self.error: BaseException | None = None
        self.head_reads = 0
        self.principal_reads = 0

    def put_head(self, head: PolicyHead) -> None:
        self._heads[head.customer_id] = head

    def put_principal(self, policy: PrincipalPolicy) -> None:
        self._principals[(policy.customer_id, policy.principal_id)] = policy

    def remove_principal(self, customer_id: str, principal_id: str) -> None:
        self._principals.pop((customer_id, principal_id), None)

    def fail_with(self, error: BaseException | None) -> None:
        self.error = error

    async def get_policy_head(self, customer_id: str) -> PolicyHead | None:
        self.head_reads += 1
        if self.error is not None:
            raise self.error
        return self._heads.get(customer_id)

    async def get_principal_policy(
        self, customer_id: str, principal_id: str
    ) -> PrincipalPolicy | None:
        self.principal_reads += 1
        if self.error is not None:
            raise self.error
        return self._principals.get((customer_id, principal_id))
