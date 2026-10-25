"""Prebuilt backends a TEST may hand to ``compose_app`` (PRP-29 wire contract).

``neurosphere_api.main.create`` never passes overrides, so nothing here is reachable from the
production entry point; a test-only token authenticator exists only in test code that builds
one of these. Each field replaces exactly one piece the builders would otherwise build from
settings; ``None`` means "build it from settings".

``backends`` is the extension point for later builders (items 7 and 8): a builder looks up a
named prebuilt object with :meth:`CompositionOverrides.backend` instead of this module gaining
a field per backend. Names in use are documented in ``runtime/builders/__init__.py``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from neurosphere_core.auth.revocation import RevocationStore
from neurosphere_core.auth.scope import PolicyRepository

from neurosphere_api.authz import DenialRecorder, ScopeSource, TokenAuthenticator

__all__ = ["CompositionOverrides"]


def _empty() -> Mapping[str, object]:
    return MappingProxyType({})


@dataclass(frozen=True, slots=True, kw_only=True)
class CompositionOverrides:
    #: Replaces the Entra ``JwtValidator`` (tests: a validator trusting a test-only issuer).
    authenticator: TokenAuthenticator | None = None
    #: Replaces the composed ``ScopeDeriver`` entirely (the policy and revocation components are
    #: still built, because other components consume them).
    scope_source: ScopeSource | None = None
    #: Replaces ``CosmosPolicyRepository`` (tests: ``InMemoryPolicyRepository``).
    policy_repository: PolicyRepository | None = None
    #: Replaces ``CosmosRevocationStore`` (tests: ``InMemoryRevocationStore``).
    revocation_store: RevocationStore | None = None
    #: Returns the Cosmos client (or a fake with the same slice) instead of
    #: ``neurosphere_core.clients.create_cosmos_client``. The emulator container bootstrap and
    #: the container existence check are skipped for an overridden client.
    cosmos_client_factory: Callable[[], Any] | None = None
    #: An aio Blob ``ContainerClient`` (or fake) for the replay archive (item 7).
    blob_client: Any | None = None
    #: A prebuilt copilot model adapter (item 8); never a live endpoint in tests.
    model_adapter: Any | None = None
    #: Denied-attempt recorder passed to ``configure_authz``.
    denial_recorder: DenialRecorder | None = None
    #: POSIX-seconds clock for token validation, scope derivation and revocation caching.
    clock: Callable[[], float] | None = None
    #: Named prebuilt backends for later builders (see ``runtime/builders/__init__.py``).
    backends: Mapping[str, object] = field(default_factory=_empty)

    def backend(self, name: str) -> object | None:
        return self.backends.get(name)
