"""Ownership of SDK clients and credentials: everything registered is closed once, in reverse."""

from __future__ import annotations

from contextlib import AsyncExitStack
from types import TracebackType
from typing import Protocol, Self, TypeVar


class _AsyncCloseable(Protocol):
    async def close(self) -> None: ...


T = TypeVar("T", bound=_AsyncCloseable)


class ClientLifetime:
    """Async context manager that closes every registered client/credential on exit."""

    def __init__(self) -> None:
        self._stack = AsyncExitStack()

    def register(self, resource: T) -> T:
        self._stack.push_async_callback(resource.close)
        return resource

    async def aclose(self) -> None:
        await self._stack.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()
