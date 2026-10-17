"""Vault credential references, an injected async resolver and a rotation hook (PRP-09 cl. 5).

Manifests carry ``CredentialRef`` values only. At call time a ``CredentialBroker`` asks the
injected ``CredentialResolver`` for the value and hands back a ``SecretValue``, a wrapper whose
``repr``, ``str``, formatting, pydantic dump and JSON never expose the secret. Only
``SecretValue.reveal()`` returns it, at the point of use. When a credential rotates, call
``CredentialBroker.notify_rotated`` (or let a ``RotationSource`` resolver do so); the cache entry
is dropped, hooks run, and the next call resolves the new value without a restart.
Log lines and errors carry the logical credential name only, never a value.
"""

from __future__ import annotations

import hmac
import inspect
import logging
from collections.abc import Awaitable, Callable, Iterable, Mapping
from typing import Any, Protocol, runtime_checkable

from neurosphere_contracts.connectors.v1.connector_manifest import CredentialRef
from neurosphere_core.errors import CapabilityUnavailableError, DependencyTransientError
from neurosphere_core.observability.redaction import RedactionFilter
from pydantic import GetCoreSchemaHandler
from pydantic_core import core_schema

__all__ = [
    "CredentialBroker",
    "CredentialResolver",
    "RotationCallback",
    "RotationSource",
    "SecretValue",
    "StaticCredentialResolver",
]

_MASK = "***"
_log = logging.getLogger("neurosphere_connector.vault")
_log.addFilter(RedactionFilter())


class SecretValue:
    """A secret string that cannot leak through repr, str, format, pydantic or json."""

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = value

    def reveal(self) -> str:
        """Return the secret. Call only where it is handed to the provider client."""
        return self._value

    def __repr__(self) -> str:
        return f"SecretValue({_MASK})"

    __str__ = __repr__

    def __format__(self, format_spec: str) -> str:
        return _MASK

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, SecretValue):
            return NotImplemented
        return hmac.compare_digest(self._value.encode(), other._value.encode())

    __hash__ = None  # type: ignore[assignment]

    def __bool__(self) -> bool:
        return bool(self._value)

    def __copy__(self) -> SecretValue:
        return self

    def __deepcopy__(self, memo: dict[int, Any]) -> SecretValue:
        return self

    def __reduce__(self) -> Any:
        raise TypeError("SecretValue cannot be pickled")

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type: Any, handler: GetCoreSchemaHandler
    ) -> core_schema.CoreSchema:
        return core_schema.is_instance_schema(
            cls,
            serialization=core_schema.plain_serializer_function_ser_schema(
                lambda _v: _MASK, return_schema=core_schema.str_schema()
            ),
        )


@runtime_checkable
class CredentialResolver(Protocol):
    """Injected by the host; resolves a vault reference (managed identity) to its value."""

    async def resolve(self, ref: CredentialRef) -> SecretValue: ...


RotationCallback = Callable[[str], Awaitable[None] | None]
"""Receives the logical credential name (never a value); may be sync or async."""


@runtime_checkable
class RotationSource(Protocol):
    """Optional resolver capability: pushes rotation signals to the broker."""

    def subscribe(self, callback: Callable[[str], None]) -> None: ...


class StaticCredentialResolver:
    """In-memory resolver for tests and local sandboxes; values keyed by ``vault_ref``."""

    def __init__(self, values: Mapping[str, str]) -> None:
        self._values = dict(values)
        self._subscribers: list[Callable[[str], None]] = []

    async def resolve(self, ref: CredentialRef) -> SecretValue:
        try:
            return SecretValue(self._values[ref.vault_ref])
        except KeyError:
            raise LookupError("no such secret") from None

    def subscribe(self, callback: Callable[[str], None]) -> None:
        self._subscribers.append(callback)

    def rotate(self, ref: CredentialRef, new_value: str) -> None:
        """Replace a value and signal subscribers (what a Key Vault event bridge would do)."""
        self._values[ref.vault_ref] = new_value
        for callback in self._subscribers:
            callback(ref.name)


class CredentialBroker:
    """Resolves the connector's declared credential refs at call time, with rotation."""

    def __init__(self, resolver: CredentialResolver, refs: Iterable[CredentialRef] = ()) -> None:
        self._resolver = resolver
        self._refs = {r.name: r for r in refs}
        self._cache: dict[str, SecretValue] = {}
        self._hooks: list[RotationCallback] = []
        self._pending: list[Awaitable[None]] = []
        if isinstance(resolver, RotationSource):
            resolver.subscribe(self._on_source_signal)

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self._refs)

    def on_rotation(self, callback: RotationCallback) -> None:
        """Register a hook invoked with the credential name after a rotation signal."""
        self._hooks.append(callback)

    async def get(self, name: str) -> SecretValue:
        """Return the current value for a declared credential (cached until rotated)."""
        cached = self._cache.get(name)
        if cached is not None:
            return cached
        ref = self._refs.get(name)
        if ref is None:
            raise CapabilityUnavailableError("credential_not_declared", f"credential {name!r}")
        try:
            value = await self._resolver.resolve(ref)
        except Exception:
            # Never chain or echo the resolver's text: it may hold provider response bodies.
            _log.warning("credential resolution failed", extra={"credential": name})
            raise DependencyTransientError(
                f"credential {name!r} could not be resolved", reason="credential_resolution_failed"
            ) from None
        self._cache[name] = value
        return value

    async def notify_rotated(self, name: str | None = None) -> None:
        """Drop cached value(s) and run hooks; the next ``get`` resolves the new value."""
        names = [name] if name is not None else list(self._refs)
        for n in names:
            self._cache.pop(n, None)
            _log.info("credential rotated", extra={"credential": n})
            for hook in self._hooks:
                result = hook(n)
                if inspect.isawaitable(result):
                    await result

    def _on_source_signal(self, name: str) -> None:
        # Synchronous signal from a resolver: invalidate now; async hooks wait for a drain.
        self._cache.pop(name, None)
        for hook in self._hooks:
            result = hook(name)
            if inspect.isawaitable(result):
                self._pending.append(result)

    async def drain_rotation_hooks(self) -> None:
        """Await async hooks queued by a synchronous ``RotationSource`` signal."""
        pending, self._pending = self._pending, []
        for item in pending:
            await item
