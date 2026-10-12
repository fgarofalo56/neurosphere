"""Server-derived authorization scope holder.

This is deliberately NOT a Pydantic model: a model would expose ``model_validate``,
``model_construct`` and dict coercion, i.e. a path from request input to a scope. The class
wraps the contract's output-only ``IdentityScope`` and can only be built through the private
``_from_verified_contract`` hook. PRP-06 adds ``from_verified_claims`` (token validation plus
policy-store derivation) on top of that hook; no derivation logic lives here.
"""

from __future__ import annotations

from typing import Any, NoReturn

from neurosphere_contracts.scope.v1.identity_scope import IdentityScope as ContractIdentityScope

_TOKEN = object()


class IdentityScope:
    """Immutable view over a verified contract scope. Public construction is refused."""

    __slots__ = ("_contract",)

    _contract: ContractIdentityScope

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        if len(args) != 2 or kwargs or args[0] is not _TOKEN:
            raise TypeError(
                "IdentityScope cannot be constructed directly; it is derived server-side "
                "from a verified token (PRP-06 from_verified_claims)"
            )
        object.__setattr__(self, "_contract", args[1].model_copy(deep=True))

    @classmethod
    def _from_verified_contract(cls, contract: ContractIdentityScope) -> IdentityScope:
        """Internal hook for the PRP-06 derivation path and test fixtures. Not public API."""
        if not isinstance(contract, ContractIdentityScope):
            raise TypeError("expected a validated contract IdentityScope")
        return cls(_TOKEN, contract)

    def __setattr__(self, name: str, value: object) -> NoReturn:
        raise AttributeError("IdentityScope is immutable")

    def __delattr__(self, name: str) -> NoReturn:
        raise AttributeError("IdentityScope is immutable")

    def __reduce__(self) -> NoReturn:
        raise TypeError("IdentityScope cannot be pickled or copied")

    def __copy__(self) -> NoReturn:
        raise TypeError("IdentityScope cannot be copied")

    def __deepcopy__(self, memo: object) -> NoReturn:
        raise TypeError("IdentityScope cannot be copied")

    @property
    def cloud(self) -> str:
        return self._contract.cloud

    @property
    def customer_id(self) -> str:
        return self._contract.customer_id

    @property
    def scope_hash(self) -> str:
        return self._contract.scope_hash

    @property
    def policy_version(self) -> str:
        return self._contract.policy_version

    @property
    def allowed_domains(self) -> tuple[str, ...]:
        return tuple(d.root for d in self._contract.allowed_domains)

    def to_contract(self) -> ContractIdentityScope:
        """Return a copy of the contract-shaped scope for serialization (output only)."""
        return self._contract.model_copy(deep=True)

    def __repr__(self) -> str:
        return f"IdentityScope(cloud={self.cloud!r}, scope_hash={self.scope_hash!r})"
