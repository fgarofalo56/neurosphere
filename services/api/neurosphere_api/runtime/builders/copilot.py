"""Copilot builder (PRP-29 item 8): ``NS_COPILOT_*`` settings to a managed-identity adapter.

``copilot`` is OPTIONAL. States:

* ``NS_COPILOT_MODE=disabled`` (default): ``disabled``; the copilot routes keep answering 503
  ``copilot_unconfigured`` and readiness reports ``composition.copilot.disabled`` (not blocking).
* ``approved_endpoint`` / ``foundry_agent``: the endpoint must belong to the deployment's cloud
  (``require_endpoint``: a Government deployment never calls a Commercial host and vice versa),
  then the existing capability-matrix gating (``resolve_adapters`` for ``NS_COPILOT_REGION`` and
  ``NS_COPILOT_MODEL_FEATURE``) must enable the adapter, and ``create_adapter`` builds
  ``ApprovedEndpointAdapter`` / ``FoundryAgentAdapter`` with an aio ``DefaultAzureCredential``
  (the environment credential is excluded outside ``NS_ENV=local``; no key is ever read). The
  conversation store is ``CosmosConversationStore`` (``copilot_conversations``), and
  ``configure_copilot`` installs both. Chat drafts through the PRP-17 ``app.state`` action plane,
  i.e. the ONE ``ACTION_SERVICE`` the planes builder published (``get_optional_action_plane``).
* A mode with a missing or invalid endpoint, deployment, region or model feature is
  ``failed("misconfigured")``; a wrong-cloud or unapproved endpoint fails with
  ``require_endpoint``'s reason (``endpoint_cloud_mismatch``, ``endpoint_not_approved``...); an
  adapter the matrix does not enable fails with the matrix reason. ``status.py``: an optional
  component that FAILED blocks readiness (503 naming ``copilot``); only ``disabled`` does not.

Settings (wire contract, plus the gating inputs ``resolve_adapters`` needs): ``NS_COPILOT_MODE``,
``NS_COPILOT_ENDPOINT``, ``NS_COPILOT_DEPLOYMENT``, ``NS_COPILOT_API_VERSION``,
``NS_COPILOT_REGION``, ``NS_COPILOT_MODEL_FEATURE``, ``NS_COPILOT_SKU`` and
``NS_COPILOT_OAUTH_SCOPE`` (an explicit token scope, required by Foundry in Government).

Refusal: any environment variable named ``NS_COPILOT_*`` whose name contains ``KEY``, ``SECRET``
or ``PASSWORD`` refuses startup with :class:`CopilotCredentialConfigError` (names only are
inspected, never values). It derives from ``BaseException`` on purpose: the composition root
turns every ``Exception`` from a builder into a readiness failure, but a credential in
configuration is a hard refusal, like a CORS wildcard, not a degraded component.

Tests pass a prebuilt adapter through ``CompositionOverrides.model_adapter`` (never a live
endpoint) and a conversation store through ``ctx.overrides.backend("copilot_conversation_store")``.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime
from typing import Any, Final, Literal

from azure.identity.aio import DefaultAzureCredential
from fastapi import Request
from neurosphere_core.copilot.models import (
    AdapterConfig,
    ModelAdapter,
    create_adapter,
    resolve_adapters,
)
from neurosphere_core.copilot.models.endpoints import require_endpoint
from neurosphere_core.errors import CapabilityUnavailableError, DependencyTransientError
from pydantic import ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from neurosphere_api.copilot import CosmosConversationStore, configure_copilot
from neurosphere_api.copilot.dependencies import get_copilot
from neurosphere_api.copilot.store import ConversationStore
from neurosphere_api.runtime.builders import (
    AGGREGATE_READER,
    CATALOG_REPOSITORY,
    BuildContext,
    BuilderSpec,
    ComponentUnavailableError,
)
from neurosphere_api.runtime.status import is_reason_code

__all__ = [
    "BUILDER",
    "COMPONENTS",
    "ENV_PREFIX",
    "MISCONFIGURED",
    "CopilotCredentialConfigError",
    "CopilotRuntimeSettings",
    "build",
    "refuse_credential_shaped_env",
]

COMPONENTS: Final = ("copilot",)
ENV_PREFIX: Final = "NS_COPILOT_"
MISCONFIGURED: Final = "misconfigured"
_CREDENTIAL_MARKERS: Final = ("KEY", "SECRET", "PASSWORD")

CopilotMode = Literal["disabled", "approved_endpoint", "foundry_agent"]


class CopilotCredentialConfigError(BaseException):
    """A credential-shaped ``NS_COPILOT_*`` variable is set: startup is refused (see module)."""


def refuse_credential_shaped_env(*environs: Mapping[str, str]) -> None:
    """Raise :class:`CopilotCredentialConfigError` naming the offending variables (never values)."""
    offending: set[str] = set()
    for environ in environs:
        for name in environ:
            upper = name.upper()
            if upper.startswith(ENV_PREFIX) and any(m in upper for m in _CREDENTIAL_MARKERS):
                offending.add(upper)
    if offending:
        raise CopilotCredentialConfigError(
            "copilot uses a managed-identity credential; remove " + ", ".join(sorted(offending))
        )


class CopilotRuntimeSettings(BaseSettings):
    """``NS_COPILOT_*``. Holds no key, secret or connection-string field (identity is MI)."""

    model_config = SettingsConfigDict(env_prefix=ENV_PREFIX, frozen=True, extra="forbid")

    mode: CopilotMode = "disabled"
    endpoint: str | None = None
    deployment: str | None = None
    api_version: str | None = None
    region: str | None = None
    model_feature: str | None = None
    sku: str | None = None
    oauth_scope: str | None = None

    @field_validator(
        "endpoint",
        "deployment",
        "api_version",
        "region",
        "model_feature",
        "sku",
        "oauth_scope",
        mode="before",
    )
    @classmethod
    def _blank_is_unset(cls, value: Any) -> Any:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value

    def adapter_config(self) -> AdapterConfig:
        """The gating input for the configured mode; missing pieces are ``misconfigured``."""
        if self.mode == "disabled":
            raise ValueError("disabled has no adapter")
        if not (self.endpoint and self.deployment and self.region and self.model_feature):
            raise ComponentUnavailableError(MISCONFIGURED)
        try:
            return AdapterConfig(
                kind=self.mode,
                endpoint=self.endpoint,
                deployment=self.deployment,
                model_feature=self.model_feature,
                sku=self.sku,
                api_version=self.api_version,
                oauth_scope=self.oauth_scope,
            )
        except ValidationError:
            raise ComponentUnavailableError(MISCONFIGURED) from None


def _reason(code: str | None, fallback: str) -> str:
    return code if code is not None and is_reason_code(code) else fallback


def _credential(ctx: BuildContext) -> DefaultAzureCredential:
    """Managed / workload identity; the developer chain only when ``NS_ENV=local``."""
    credential = DefaultAzureCredential(
        authority=ctx.settings.cloud_profile.login_host,
        exclude_environment_credential=ctx.settings.env != "local",
    )
    ctx.lifetime.register(credential)  # type: ignore[arg-type]  # closes via close()
    return credential


def _adapter(ctx: BuildContext, settings: CopilotRuntimeSettings) -> ModelAdapter:
    config = settings.adapter_config()
    cloud = ctx.settings.cloud_profile.cloud.value
    try:
        require_endpoint(cloud, config.endpoint)
    except CapabilityUnavailableError as exc:
        raise ComponentUnavailableError(_reason(exc.reason, "endpoint_refused")) from None
    region = settings.region or ""
    entries = resolve_adapters(cloud=cloud, region=region, configs=[config])
    entry = next(e for e in entries if e.kind == settings.mode)
    if not entry.enabled:
        raise ComponentUnavailableError(_reason(entry.reason_code, "capability_unavailable"))
    try:
        return create_adapter(entry, cloud=cloud, credential=_credential(ctx))
    except CapabilityUnavailableError as exc:
        raise ComponentUnavailableError(_reason(exc.reason, "capability_unavailable")) from None


def _conversation_store(ctx: BuildContext) -> ConversationStore:
    override = ctx.overrides.backend("copilot_conversation_store")
    if override is not None:
        if not isinstance(override, ConversationStore):
            raise ComponentUnavailableError("copilot_conversation_store_invalid")
        return override
    return CosmosConversationStore.from_client(
        ctx.cosmos_client(), database=ctx.store_settings().database
    )


def _date_clock(ctx: BuildContext) -> Callable[[], datetime] | None:
    clock = ctx.overrides.clock
    if clock is None:
        return None
    return lambda: datetime.fromtimestamp(clock(), UTC)


def _install(ctx: BuildContext, adapter: ModelAdapter) -> None:
    # The tool read ports (catalog, aggregates, recommendations) come from the data builder.
    ctx.shared(CATALOG_REPOSITORY)
    ctx.shared(AGGREGATE_READER)
    store = _conversation_store(ctx)
    configure_copilot(
        ctx.app, model_adapter=adapter, conversation_store=store, clock=_date_clock(ctx)
    )
    try:
        get_copilot(_state_request(ctx))
    except DependencyTransientError:
        raise ComponentUnavailableError("copilot_unconfigured") from None


def _state_request(ctx: BuildContext) -> Request:
    """A request carrying only the app: what ``get_copilot`` resolves collaborators from."""
    return Request({"type": "http", "app": ctx.app, "headers": []})


def _environs(ctx: BuildContext) -> Iterable[Mapping[str, str]]:
    return (os.environ, ctx.environ)


def build(ctx: BuildContext) -> None:
    refuse_credential_shaped_env(*_environs(ctx))
    override = ctx.overrides.model_adapter
    if override is not None:  # tests only: a prebuilt adapter, never a live endpoint
        if not isinstance(override, ModelAdapter):
            ctx.failed("copilot", "model_adapter_invalid")
            return
        ctx.attempt("copilot", lambda: _install(ctx, override))
        return
    try:
        settings = CopilotRuntimeSettings()
    except ValidationError:
        ctx.failed("copilot", MISCONFIGURED)
        return
    if settings.mode == "disabled":
        ctx.disabled("copilot")
        return
    ctx.attempt("copilot", lambda: _install(ctx, _adapter(ctx, settings)))


BUILDER: Final = BuilderSpec("copilot", COMPONENTS, build)
