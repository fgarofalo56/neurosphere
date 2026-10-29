"""Builder interface of the composition root (PRP-29 C5). Stable: items 7 and 8 fill
``data.py``, ``planes.py``, ``copilot.py`` and ``mcp.py`` without editing any other runtime file.

Builder modules
---------------
Each builder module defines three names::

    COMPONENTS: Final = ("catalog", "aggregates", ...)   # components this module reports
    def build(ctx: BuildContext) -> None: ...             # synchronous; no network I/O
    BUILDER: Final = BuilderSpec("data", COMPONENTS, build)

:func:`default_builders` returns the fixed order (the ``routers.py`` hook pattern)::

    authz -> data -> planes -> copilot -> mcp -> gateway -> edge

so a builder may consume anything an EARLIER builder published. ``compose_app(...,
builders=...)`` accepts any sequence of :class:`BuilderSpec` (tests pass stubs for components
whose real builder does not exist yet). Two builders may not claim the same component.

Reporting status
----------------
A builder reports every component in its ``COMPONENTS`` (and only those) through ``ctx``:

* ``ctx.ok(name)`` after the component is installed on ``app.state``;
* ``ctx.failed(name, reason)`` with a reason code ``[a-z][a-z0-9_]{0,63}`` (never a value);
* ``ctx.disabled(name)`` for an OPTIONAL component that is deliberately off;
* ``ctx.not_built(name)`` (placeholders).

``ctx.attempt(name, fn)`` runs ``fn()``, reports ``ok`` and returns its value, or reports
``failed`` with :class:`ComponentUnavailableError`'s reason and returns ``None``. Anything a builder
leaves unreported becomes ``not_built``; an unexpected exception from ``build`` marks every
unreported component of that builder ``failed("build_error")`` (logged by type only).

Build context
-------------
* ``ctx.app``, ``ctx.settings`` (core ``Settings``: ``env``, ``cloud_profile``),
  ``ctx.overrides`` (:class:`~neurosphere_api.runtime.overrides.CompositionOverrides`; production
  passes none), ``ctx.environ``.
* ``ctx.auth_settings()`` / ``ctx.store_settings()``: the ``NS_AUTH_`` / ``NS_STORE_`` settings,
  read once; invalid -> ``ComponentUnavailableError`` with reason ``auth_settings_invalid`` or
  ``store_settings_invalid``.
* ``ctx.cosmos_client()``: the ONE shared aio Cosmos client (``overrides.cosmos_client_factory``
  or ``neurosphere_core.clients.create_cosmos_client``; owned by the composition lifetime and
  closed at shutdown). Not configured -> ``ComponentUnavailableError("cosmos_unconfigured")``.
  ``ctx.cosmos_database()`` is the ``NS_STORE_DATABASE`` database proxy. Container names and keys
  come from ``neurosphere_core.stores`` (the registry); builders never create containers (the
  composition does that once, only when ``NS_ENV=local``).
* ``ctx.lifetime``: a ``ClientLifetime`` for anything else that must be closed at shutdown.
* ``ctx.on_startup(hook)`` / ``ctx.on_shutdown(hook)``: async hooks run in the app lifespan
  (after the Cosmos container step). A failing startup hook marks this builder's ``ok``
  components ``failed("startup_failed")``.

Shared objects
--------------
``ctx.publish(KEY, obj)`` makes an object available to later builders; ``ctx.shared(KEY)`` reads
it or raises ``ComponentUnavailableError("<key>_unavailable")``; ``ctx.maybe_shared(KEY)`` returns
``None`` instead. Keys are typed :class:`SharedKey` constants. Declared here:

=========================  =========================================================  ========
Key                        Object                                                     By
=========================  =========================================================  ========
``AUTH_SETTINGS``          ``AuthSettings`` (tenant, audiences, customer binding)     authz
``AUTHENTICATOR``          the installed ``TokenAuthenticator`` (``JwtValidator``)    authz
``SCOPE_SOURCE``           the installed ``ScopeSource`` (the composed deriver)       authz
``SCOPE_DERIVER``          the composed ``ScopeDeriver`` (absent when overridden)     authz
``PSEUDONYMIZER``          ``PrincipalPseudonymizer`` (same key as the deriver)       authz
``POLICY_REPOSITORY``      ``PolicyRepository`` (Cosmos ``policy``)                   authz
``REVOCATION_STORE``       ``RevocationStore`` (Cosmos ``revocations``)               authz
``REVOCATION_CHECKER``     ``CachedRevocationChecker`` used by the deriver            authz
``REVOCATION_HOOKS``       ``RevocationHookRegistry`` (checker + deriver invalidators) authz
``AUDIT_REPOSITORY``       ``AuditRepository`` (Cosmos ``audit``/``audit_tail``)      data
``HITL_SERVICE``           ``HitlService`` (HITL store + decision log)                data
``AGGREGATE_READER``       the aggregate reader installed on ``app.state``            data
``CATALOG_REPOSITORY``     the catalog repository installed on ``app.state``          data
``ACTION_SERVICE``         the ONE ``ActionService`` (buttons, chat and MCP share it)  planes
=========================  =========================================================  ========

A builder may declare further keys in its own module; later builders import them from there.

Override backends
-----------------
``ctx.overrides.backend(name)`` returns a named prebuilt backend from test code (``None`` in
production). Builders should accept one per store they build, named after its ``app.state``
key (``"audit_repository"``, ``"trace_reader"``, ``"intent_store"``...), so CI tests compose with
fakes and no emulator.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final, TypeVar, cast

from fastapi import FastAPI
from neurosphere_core.cloud import Settings
from neurosphere_core.errors import InvalidSchemaError
from pydantic import ValidationError
from pydantic_settings import BaseSettings

from neurosphere_api.runtime.overrides import CompositionOverrides
from neurosphere_api.runtime.settings import AuthSettings, StoreSettings
from neurosphere_api.runtime.status import ComponentRegistry

if TYPE_CHECKING:
    from neurosphere_core.actions import ActionService
    from neurosphere_core.audit import AuditRepository
    from neurosphere_core.auth.revocation import (
        CachedRevocationChecker,
        RevocationHookRegistry,
        RevocationStore,
    )
    from neurosphere_core.auth.scope import PolicyRepository, PrincipalPseudonymizer, ScopeDeriver
    from neurosphere_core.clients import ClientLifetime
    from neurosphere_core.hitl import HitlService

    from neurosphere_api.authz import ScopeSource, TokenAuthenticator

#: Module-level type variable: CodeQL reads a PEP 695 ``[T]`` used inside ``cast(T, ...)`` as
#: an uninitialized local (py/uninitialized-local-variable, which fails the PR).
_T = TypeVar("_T")

__all__ = [
    "ACTION_SERVICE",
    "AGGREGATE_READER",
    "AUDIT_REPOSITORY",
    "AUTHENTICATOR",
    "AUTH_SETTINGS",
    "CATALOG_REPOSITORY",
    "HITL_SERVICE",
    "POLICY_REPOSITORY",
    "PSEUDONYMIZER",
    "REVOCATION_CHECKER",
    "REVOCATION_HOOKS",
    "REVOCATION_STORE",
    "SCOPE_DERIVER",
    "SCOPE_SOURCE",
    "BuildContext",
    "BuilderSpec",
    "ComponentUnavailableError",
    "CompositionState",
    "SharedKey",
    "StartupHook",
    "default_builders",
]

_log = logging.getLogger("neurosphere_api.runtime")

StartupHook = Callable[[], Awaitable[None]]


class ComponentUnavailableError(Exception):
    """Raised inside a builder: the component cannot be built, for ``reason`` (a code)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class SharedKey[T]:
    """Typed name of an object one builder publishes for later builders."""

    name: str


AUTH_SETTINGS: Final[SharedKey[AuthSettings]] = SharedKey("auth_settings")
AUTHENTICATOR: Final[SharedKey[TokenAuthenticator]] = SharedKey("authenticator")
SCOPE_SOURCE: Final[SharedKey[ScopeSource]] = SharedKey("scope_source")
SCOPE_DERIVER: Final[SharedKey[ScopeDeriver]] = SharedKey("scope_deriver")
PSEUDONYMIZER: Final[SharedKey[PrincipalPseudonymizer]] = SharedKey("pseudonymizer")
POLICY_REPOSITORY: Final[SharedKey[PolicyRepository]] = SharedKey("policy_repository")
REVOCATION_STORE: Final[SharedKey[RevocationStore]] = SharedKey("revocation_store")
REVOCATION_CHECKER: Final[SharedKey[CachedRevocationChecker]] = SharedKey("revocation_checker")
REVOCATION_HOOKS: Final[SharedKey[RevocationHookRegistry]] = SharedKey("revocation_hooks")
AUDIT_REPOSITORY: Final[SharedKey[AuditRepository]] = SharedKey("audit_repository")
HITL_SERVICE: Final[SharedKey[HitlService]] = SharedKey("hitl_service")
AGGREGATE_READER: Final[SharedKey[object]] = SharedKey("aggregate_reader")
CATALOG_REPOSITORY: Final[SharedKey[object]] = SharedKey("catalog_repository")
ACTION_SERVICE: Final[SharedKey[ActionService]] = SharedKey("action_service")


@dataclass(frozen=True, slots=True)
class BuilderSpec:
    """One builder: a name, the components it reports, and its ``build`` function."""

    name: str
    components: tuple[str, ...]
    build: Callable[[BuildContext], None]


@dataclass(slots=True)
class CompositionState:
    """Everything builders share. Created by ``compose_app``; builders use ``BuildContext``."""

    app: FastAPI
    settings: Settings
    overrides: CompositionOverrides
    registry: ComponentRegistry
    environ: Mapping[str, str]
    lifetime: ClientLifetime
    #: Builds the Cosmos client from settings (``compose_app`` sets it; overrides win).
    cosmos_factory: Callable[[], Any] | None = None
    shared: dict[str, object] = field(default_factory=dict)
    owners: dict[str, str] = field(default_factory=dict)
    startup: list[tuple[str, StartupHook]] = field(default_factory=list)
    shutdown: list[StartupHook] = field(default_factory=list)
    cosmos: Any | None = None
    cosmos_error: str | None = None
    cosmos_overridden: bool = False
    _auth: AuthSettings | None = None
    _store: StoreSettings | None = None
    _settings_errors: set[str] = field(default_factory=set)

    def auth_settings(self) -> AuthSettings:
        if self._auth is None:
            self._auth = self._load("auth_settings_invalid", AuthSettings)
        return self._auth

    def store_settings(self) -> StoreSettings:
        if self._store is None:
            self._store = self._load("store_settings_invalid", StoreSettings)
        return self._store

    def _load[S: BaseSettings](self, reason: str, model: type[S]) -> S:
        if reason in self._settings_errors:
            raise ComponentUnavailableError(reason)
        try:
            return model()
        except ValidationError:
            self._settings_errors.add(reason)
            raise ComponentUnavailableError(reason) from None

    def cosmos_client(self) -> Any:
        """The shared client, built once; the failure reason is cached too."""
        if self.cosmos is not None:
            return self.cosmos
        if self.cosmos_error is not None:
            raise ComponentUnavailableError(self.cosmos_error)
        try:
            if self.overrides.cosmos_client_factory is not None:
                self.cosmos_overridden = True
                self.cosmos = self.overrides.cosmos_client_factory()
            elif self.cosmos_factory is not None:
                self.cosmos = self.cosmos_factory()
            else:
                raise ComponentUnavailableError("cosmos_unconfigured")
        except ComponentUnavailableError as exc:
            self.cosmos_error = exc.reason
            raise
        except InvalidSchemaError:
            self.cosmos_error = "cosmos_unconfigured"
            raise ComponentUnavailableError("cosmos_unconfigured") from None
        return self.cosmos


class BuildContext:
    """The view of :class:`CompositionState` handed to one builder (see module docstring)."""

    def __init__(self, state: CompositionState, spec: BuilderSpec) -> None:
        self._state = state
        self._spec = spec

    # -- environment -------------------------------------------------------------------------

    @property
    def app(self) -> FastAPI:
        return self._state.app

    @property
    def settings(self) -> Settings:
        return self._state.settings

    @property
    def overrides(self) -> CompositionOverrides:
        return self._state.overrides

    @property
    def environ(self) -> Mapping[str, str]:
        return self._state.environ

    @property
    def lifetime(self) -> ClientLifetime:
        return self._state.lifetime

    @property
    def components(self) -> tuple[str, ...]:
        return self._spec.components

    def auth_settings(self) -> AuthSettings:
        return self._state.auth_settings()

    def store_settings(self) -> StoreSettings:
        return self._state.store_settings()

    def cosmos_client(self) -> Any:
        """The shared aio Cosmos client; ``ComponentUnavailableError("cosmos_unconfigured")``."""
        return self._state.cosmos_client()

    def cosmos_database(self) -> Any:
        """``NS_STORE_DATABASE`` on the shared client."""
        return self.cosmos_client().get_database_client(self.store_settings().database)

    # -- status ------------------------------------------------------------------------------

    def _own(self, name: str) -> str:
        if name not in self._spec.components:
            raise ValueError(f"builder {self._spec.name} does not own component {name}")
        return name

    def ok(self, name: str) -> None:
        self._state.registry.ok(self._own(name))

    def failed(self, name: str, reason: str) -> None:
        self._state.registry.failed(self._own(name), reason)
        _log.warning("component %s failed: %s", name, reason)

    def disabled(self, name: str) -> None:
        self._state.registry.disabled(self._own(name))

    def not_built(self, name: str) -> None:
        self._state.registry.not_built(self._own(name))

    def attempt[T](self, name: str, fn: Callable[[], T]) -> T | None:
        """Run ``fn``; ``ok`` and its value, or ``failed(reason)`` and ``None``."""
        try:
            value = fn()
        except ComponentUnavailableError as exc:
            self.failed(name, exc.reason)
            return None
        self.ok(name)
        return value

    # -- shared objects and lifespan hooks ---------------------------------------------------

    def publish[T](self, key: SharedKey[T], value: T) -> None:
        if key.name in self._state.shared:
            raise ValueError(f"shared object already published: {key.name}")
        self._state.shared[key.name] = value

    def shared(self, key: SharedKey[_T]) -> _T:
        if key.name not in self._state.shared:
            raise ComponentUnavailableError(f"{key.name}_unavailable")
        return cast(_T, self._state.shared[key.name])

    def maybe_shared(self, key: SharedKey[_T]) -> _T | None:
        return cast(_T | None, self._state.shared.get(key.name))

    def on_startup(self, hook: StartupHook) -> None:
        self._state.startup.append((self._spec.name, hook))

    def on_shutdown(self, hook: StartupHook) -> None:
        self._state.shutdown.append(hook)


def default_builders() -> tuple[BuilderSpec, ...]:
    """The production order. Local imports keep builder modules out of import time."""
    from neurosphere_api.runtime.builders import (
        authz,
        copilot,
        data,
        edge,
        gateway,
        mcp,
        planes,
    )

    return (
        authz.BUILDER,
        data.BUILDER,
        planes.BUILDER,
        copilot.BUILDER,
        mcp.BUILDER,
        gateway.BUILDER,
        edge.BUILDER,
    )
