"""Opt-in interaction capture at the ingest edge (PRP-103 item 4).

Component ``interaction_capture`` is OPTIONAL and never blocks readiness: every way capture can
be off reports ``disabled`` with a logged reason code, and ingest keeps serving exactly as
without capture. The reason is also on ``app.state.interaction_capture_off_reason`` (``None``
only while capture is active), because the registry carries reasons for ``failed`` only.

Gates, in order; the first that fails is the reason:

1. ``setting_off``: the PRP-99 ``interaction_capture`` stored setting (read from the
   ``STORED_SETTINGS`` snapshot, applied at restart: clarification 8) is absent or disabled.
   Nothing else is read or built: no policy container read, no key wrapper, no client.
2. ``retention_not_enabled``: the customer retention policy (``app.state.lifecycle.policy``, else
   ``NS_LIFECYCLE_POLICY_FILE``) does not opt in to bodies (PRP-102 ``content_writes_enabled``).
3. ``ingest_disabled``: no ingest service was bootstrapped, so there is nothing to attach to.
4. ``customer_unconfigured`` / ``audit_unavailable`` / ``capture_env_invalid``.
5. Content configuration from ``InteractionSettings``: ``key_vault_not_configured`` (no
   ``kek_uri`` for ``key_vault_key``), ``key_host_refused``, ``key_wrap_unavailable``,
   ``local_key_not_allowed``, ``local_key_file_missing``, ``blob_not_configured``.
6. Stores: the interaction store is the Cosmos ``interaction_index`` on the ONE shared client
   plus the content blob container; under ``NS_ENV=local`` without Cosmos it is in-memory (with
   whichever key wrapper ``InteractionSettings`` configures). The capture policy store is
   Cosmos ``interaction_capture_policies``, else in-memory under ``NS_ENV=local``. Elsewhere
   no Cosmos is ``cosmos_unconfigured``.
7. At startup (``on_startup``): one bounded read of the policies builds the
   :class:`~neurosphere_core.interactions.CaptureMatcher`; a failed read is
   ``policy_store_unavailable``. The matcher's off reason (``no_policy``, ``not_approved``,
   ``policy_limit_exceeded``...) leaves the component ``disabled``; only when some policy can
   match is the :class:`EdgeCapture` attached to ``app.state.ingest_service`` and the component
   ``ok``. With no capture attached the ingest path is unchanged.

``app.state`` (read by the item 5 status route): ``interaction_capture`` (the ``EdgeCapture``,
``None`` until startup built it), ``interaction_capture_stats`` (its ``EdgeCaptureStats``),
``interaction_capture_policy_store`` (the ``CapturePolicyStore``, ``None`` when not built) and
``interaction_capture_off_reason``.

Environment: ``NS_INTERACTION_CAPTURE_QUEUE_CAPACITY`` (default 64; shedding starts at the stored
setting's ``shed_capture_at_queue_percent``) and ``NS_INTERACTION_CAPTURE_MAX_ITEMS_PER_REQUEST``
(default 100), read only when the setting is on.

Store factory (PRP-104 item 2): :func:`interaction_store` builds the interaction store once per
composition and publishes it under :data:`INTERACTION_STORE`; capture and the interaction
explorer both obtain it there, so they share ONE instance.

Content storage accessor (PRP-104 item 4): :func:`interaction_content_storage` returns the
content container client, the content key wrapper and its key identifier, built from the same
``InteractionSettings`` as the store and memoized, so the store and the interaction exports
share ONE container client and ONE wrapper (exports live under ``exports/`` in that container).

Test seams (``ctx.overrides.backend``): ``retention_policy`` (a ``PolicyState``),
``interaction_store`` (a prebuilt capture store), ``interaction_capture_policy_store``.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final, Protocol, cast

from azure.identity.aio import DefaultAzureCredential
from azure.storage.blob.aio import ContainerClient
from neurosphere_contracts.admin.v1.system_setting import InteractionCaptureSetting
from neurosphere_core.admin.runtime import StoredSettingsSnapshot
from neurosphere_core.classification import default_detector_set
from neurosphere_core.clients.factories import ENV_BLOB_CONNECTION_STRING
from neurosphere_core.crypto import KEY_HOST_REFUSED, EnvelopeError, KeyWrapper
from neurosphere_core.errors import InvalidSchemaError
from neurosphere_core.interactions import (
    CAPTURE_SETTING_KEY,
    DEFAULT_CAPTURE_POLICY_CONTAINER,
    BlobInteractionContent,
    CaptureMatcher,
    CapturePipeline,
    CapturePolicyStore,
    CaptureStore,
    CosmosCapturePolicyStore,
    CosmosInteractionIndex,
    EncryptedInteractionStore,
    InMemoryCapturePolicyStore,
    InMemoryInteractionStore,
    InteractionSettings,
    InteractionStore,
    build_key_wrapper,
    capture_setting_enabled,
    content_writes_enabled,
)
from neurosphere_core.lifecycle.policy import PolicyState, load_policy_file
from neurosphere_core.lifecycle.settings import LifecycleSettings
from pydantic import ValidationError

from neurosphere_api.admin.system.stored import STORED_SETTINGS
from neurosphere_api.ingest.capture import (
    EdgeCapture,
    domain_audit_writer,
    max_items_per_request_from_env,
)
from neurosphere_api.runtime.builders import (
    AUDIT_REPOSITORY,
    BuildContext,
    BuilderSpec,
    ComponentUnavailableError,
    SharedKey,
)
from neurosphere_api.runtime.builders.blob import azurite_connection_string

__all__ = [
    "BUILDER",
    "COMPONENTS",
    "DEFAULT_QUEUE_CAPACITY",
    "ENV_QUEUE_CAPACITY",
    "INTERACTION_STORE",
    "InteractionContentStorage",
    "SharedInteractionStore",
    "build",
    "interaction_content_storage",
    "interaction_store",
    "queue_capacity_from_env",
]

COMPONENTS: Final = ("interaction_capture",)
_COMPONENT: Final = "interaction_capture"
ENV_QUEUE_CAPACITY: Final = "NS_INTERACTION_CAPTURE_QUEUE_CAPACITY"
DEFAULT_QUEUE_CAPACITY: Final = 64
_DEFAULT_SHED_PERCENT: Final = 80
_DEFAULT_MAX_CONTENT_CHARS: Final = 65536
_POLICY_READ_TIMEOUT_SECONDS: Final = 15.0

#: ``app.state`` attribute names (item 5 reads them).
STATE_EDGE: Final = "interaction_capture"
STATE_STATS: Final = "interaction_capture_stats"
STATE_POLICY_STORE: Final = "interaction_capture_policy_store"
STATE_OFF_REASON: Final = "interaction_capture_off_reason"

#: ``InteractionSettings`` configuration pointers -> reason codes (never values).
_POINTER_REASONS: Final[Mapping[str, str]] = {
    "/kek_uri": "key_vault_not_configured",
    "/kek_provider": "local_key_not_allowed",
    "/NS_INTERACTION_LOCAL_KEY_FILE": "local_key_file_missing",
    "/content_storage_account_resource_id": "blob_not_configured",
}

_log = logging.getLogger("neurosphere_api.runtime")


def queue_capacity_from_env(environ: Mapping[str, str] | None = None) -> int:
    """``NS_INTERACTION_CAPTURE_QUEUE_CAPACITY`` (default 64).

    Raises ``ValueError`` naming the variable (never echoing the value) unless it is an integer
    of at least 1.
    """
    env = os.environ if environ is None else environ
    raw = env.get(ENV_QUEUE_CAPACITY)
    if raw is None or not raw.strip():
        return DEFAULT_QUEUE_CAPACITY
    try:
        value = int(raw.strip())
    except ValueError:
        raise ValueError(f"{ENV_QUEUE_CAPACITY} must be an integer of at least 1") from None
    if value < 1:
        raise ValueError(f"{ENV_QUEUE_CAPACITY} must be an integer of at least 1")
    return value


def _off(ctx: BuildContext, reason: str) -> None:
    setattr(ctx.app.state, STATE_OFF_REASON, reason)
    # Off by default is the normal state, not a warning.
    level = logging.INFO if reason == "setting_off" else logging.WARNING
    _log.log(level, "component %s disabled: %s", _COMPONENT, reason)
    ctx.disabled(_COMPONENT)


def _capture_setting(ctx: BuildContext) -> InteractionCaptureSetting | None:
    snapshot = ctx.maybe_shared(STORED_SETTINGS)
    if not isinstance(snapshot, StoredSettingsSnapshot):
        return None
    entry = snapshot.entries.get(CAPTURE_SETTING_KEY)
    setting = None if entry is None else entry.setting
    if not capture_setting_enabled(setting):
        return None
    return None if setting is None else setting.interaction_capture


def _retention(ctx: BuildContext) -> PolicyState | None:
    override = ctx.overrides.backend("retention_policy")
    if isinstance(override, PolicyState):
        return override
    lifecycle = getattr(ctx.app.state, "lifecycle", None)
    policy = getattr(lifecycle, "policy", None)
    if isinstance(policy, PolicyState):
        return policy
    try:
        return load_policy_file(LifecycleSettings().policy_file)
    except ValidationError:
        return None


def _interaction_settings(
    ctx: BuildContext, setting: InteractionCaptureSetting
) -> InteractionSettings:
    try:
        return InteractionSettings.from_setting(
            setting,
            ctx.settings.cloud_profile.cloud.value,
            settings=ctx.settings,
            environ=ctx.environ,
        )
    except EnvelopeError as exc:
        reason = "key_host_refused" if exc.reason == KEY_HOST_REFUSED else "key_wrap_unavailable"
        raise ComponentUnavailableError(reason) from None
    except InvalidSchemaError as exc:
        pointer = exc.errors[0].pointer if exc.errors else ""
        raise ComponentUnavailableError(
            _POINTER_REASONS.get(pointer, "capture_settings_invalid")
        ) from None


def _cosmos_or_none(ctx: BuildContext) -> Any | None:
    """The shared Cosmos client, or ``None`` under ``NS_ENV=local`` without one."""
    try:
        return ctx.cosmos_client()
    except ComponentUnavailableError:
        if ctx.settings.env != "local":
            raise
        return None


def _content_container(ctx: BuildContext, settings: InteractionSettings) -> ContainerClient:
    if ctx.settings.env == "local":
        connection = ctx.environ.get(ENV_BLOB_CONNECTION_STRING) or azurite_connection_string()
        try:
            client = ContainerClient.from_connection_string(connection, settings.content_container)
        except ValueError:
            raise ComponentUnavailableError("blob_not_configured") from None
    else:
        # Managed or workload identity only (as the archive container): never a key.
        options: dict[str, Any] = {
            "authority": ctx.settings.cloud_profile.login_host,
            "exclude_environment_credential": True,
        }
        if settings.managed_identity_client_id is not None:
            options["managed_identity_client_id"] = settings.managed_identity_client_id
        identity = DefaultAzureCredential(**options)
        ctx.on_shutdown(identity.close)
        client = ContainerClient(
            settings.content_account_url, settings.content_container, credential=identity
        )
    ctx.on_shutdown(client.close)
    return client


#: Memoized pieces of the content side (PRP-104 item 4), shared by the store and the exports.
_INTERACTION_SETTINGS: Final[SharedKey[InteractionSettings]] = SharedKey("interaction_settings")
_KEY_WRAPPER: Final[SharedKey[KeyWrapper]] = SharedKey("interaction_key_wrapper")
_CONTENT_CONTAINER: Final[SharedKey[ContainerClient]] = SharedKey("interaction_content_container")


def _key_wrapper(ctx: BuildContext, settings: InteractionSettings) -> KeyWrapper:
    """The content key wrapper, built once per composition."""
    memo = ctx.maybe_shared(_KEY_WRAPPER)
    if memo is not None:
        return memo
    try:
        wrapper = build_key_wrapper(settings, env_settings=ctx.settings)
    except InvalidSchemaError as exc:
        pointer = exc.errors[0].pointer if exc.errors else ""
        raise ComponentUnavailableError(
            _POINTER_REASONS.get(pointer, "key_wrap_unavailable")
        ) from None
    except Exception:  # EnvelopeError, an unreadable local key file...
        raise ComponentUnavailableError("key_wrap_unavailable") from None
    ctx.publish(_KEY_WRAPPER, wrapper)
    return wrapper


def _shared_content_container(ctx: BuildContext, settings: InteractionSettings) -> ContainerClient:
    """The content container client, built once per composition."""
    memo = ctx.maybe_shared(_CONTENT_CONTAINER)
    if memo is not None:
        return memo
    client = _content_container(ctx, settings)
    ctx.publish(_CONTENT_CONTAINER, client)
    return client


def _interaction_store(
    ctx: BuildContext, settings: InteractionSettings, retention: PolicyState
) -> CaptureStore:
    override = ctx.overrides.backend("interaction_store")
    if override is not None:
        return override  # type: ignore[return-value]
    client = _cosmos_or_none(ctx)
    wrapper = _key_wrapper(ctx, settings)
    if client is None:  # NS_ENV=local only (see _cosmos_or_none)
        return InMemoryInteractionStore(wrapper, kek_uri=settings.content_kek_uri, policy=retention)
    index = CosmosInteractionIndex.from_client(client, database=ctx.store_settings().database)
    content = BlobInteractionContent(
        _shared_content_container(ctx, settings),  # type: ignore[arg-type]
        settings=ctx.settings,
    )
    return EncryptedInteractionStore(
        index, content, wrapper, kek_uri=settings.content_kek_uri, policy=retention
    )


def _policy_store(ctx: BuildContext) -> CapturePolicyStore:
    override = ctx.overrides.backend("interaction_capture_policy_store")
    if override is not None:
        return override  # type: ignore[return-value]
    client = _cosmos_or_none(ctx)
    if client is None:
        return InMemoryCapturePolicyStore()
    return CosmosCapturePolicyStore.from_client(
        client, database=ctx.store_settings().database, container=DEFAULT_CAPTURE_POLICY_CONTAINER
    )


def _customer(ctx: BuildContext) -> str:
    try:
        customer = ctx.auth_settings().resolved_customer_id(ctx.settings.env)
    except ComponentUnavailableError:
        customer = None
    if customer is None:
        raise ComponentUnavailableError("customer_unconfigured")
    return customer


class SharedInteractionStore(CaptureStore, InteractionStore, Protocol):
    """PRP-102's store seen from both sides: capture writes through it, the explorer reads it."""


#: The ONE interaction store of a composition, shared by capture and the explorer (PRP-104).
INTERACTION_STORE: Final[SharedKey[SharedInteractionStore]] = SharedKey("interaction_store")


def _stored_capture_body(ctx: BuildContext) -> InteractionCaptureSetting | None:
    """The stored setting's ``interaction_capture`` body, whether or not capture is enabled."""
    snapshot = ctx.maybe_shared(STORED_SETTINGS)
    if not isinstance(snapshot, StoredSettingsSnapshot):
        return None
    entry = snapshot.entries.get(CAPTURE_SETTING_KEY)
    setting = None if entry is None else entry.setting
    if setting is None or setting.setting_key != CAPTURE_SETTING_KEY:
        return None
    return setting.interaction_capture


def _enabled_retention(ctx: BuildContext, retention: PolicyState | None) -> PolicyState:
    state = _retention(ctx) if retention is None else retention
    if state is None or not content_writes_enabled(state):
        raise ComponentUnavailableError("retention_not_enabled")
    return state


def interaction_store(
    ctx: BuildContext,
    *,
    settings: InteractionSettings | None = None,
    retention: PolicyState | None = None,
) -> SharedInteractionStore:
    """The composition's interaction store, built once and memoized (PRP-104 item 2).

    Capture (``_build``) passes the settings and retention it already resolved; the explorer
    passes neither, and the stored ``interaction_capture`` setting is read REGARDLESS of its
    ``enabled`` flag: an operator who turns capture off still has stored, possibly held content.
    The first successful build is published under :data:`INTERACTION_STORE`, so capture and the
    explorer share one instance (it matters for the in-memory store under ``NS_ENV=local``).

    Raises :class:`ComponentUnavailableError`: ``setting_absent``, ``retention_not_enabled``, or
    whatever building the store reports (``key_vault_not_configured``, ``cosmos_unconfigured``...).
    """
    memo = ctx.maybe_shared(INTERACTION_STORE)
    if memo is not None:
        return memo
    if settings is None:
        body = _stored_capture_body(ctx)
        if body is None:
            raise ComponentUnavailableError("setting_absent")  # nothing read, nothing built
        retention = _enabled_retention(ctx, retention)
        settings = _interaction_settings(ctx, body)
    else:
        retention = _enabled_retention(ctx, retention)
    store = cast(SharedInteractionStore, _interaction_store(ctx, settings, retention))
    ctx.publish(INTERACTION_STORE, store)
    if ctx.maybe_shared(_INTERACTION_SETTINGS) is None:
        ctx.publish(_INTERACTION_SETTINGS, settings)
    return store


@dataclass(frozen=True, slots=True)
class InteractionContentStorage:
    """The content side of the store, for interaction exports (PRP-104 item 4).

    ``container`` is the content blob container client, ``wrapper`` the content key wrapper and
    ``kek_uri`` its key identifier (what an ``EncryptedObjectRef`` records): the same instances
    the interaction store uses.
    """

    container: ContainerClient
    wrapper: KeyWrapper
    kek_uri: str


def interaction_content_storage(ctx: BuildContext) -> InteractionContentStorage:
    """The content container, key wrapper and key id, memoized and shared with the store.

    Uses the settings the store was built from when it was built (else resolves them the same
    way: the stored ``interaction_capture`` setting regardless of ``enabled``, and the retention
    opt-in). Under ``NS_ENV=local`` without Cosmos the in-memory store has no container; the
    container client is then built here (Azurite) for the exports alone.

    Raises :class:`ComponentUnavailableError` with the store's reason codes (``setting_absent``,
    ``retention_not_enabled``, ``key_vault_not_configured``, ``key_wrap_unavailable``,
    ``blob_not_configured``...).
    """
    settings = ctx.maybe_shared(_INTERACTION_SETTINGS)
    if settings is None:
        body = _stored_capture_body(ctx)
        if body is None:
            raise ComponentUnavailableError("setting_absent")
        _enabled_retention(ctx, None)
        settings = _interaction_settings(ctx, body)
        ctx.publish(_INTERACTION_SETTINGS, settings)
    return InteractionContentStorage(
        container=_shared_content_container(ctx, settings),
        wrapper=_key_wrapper(ctx, settings),
        kek_uri=settings.content_kek_uri,
    )


def _build(ctx: BuildContext) -> None:
    app = ctx.app
    setting = _capture_setting(ctx)
    if setting is None:
        _off(ctx, "setting_off")  # nothing read, nothing built
        return
    retention = _retention(ctx)
    if retention is None or not content_writes_enabled(retention):
        _off(ctx, "retention_not_enabled")
        return
    ingest = getattr(app.state, "ingest_service", None)
    if ingest is None:
        _off(ctx, "ingest_disabled")
        return
    customer = _customer(ctx)
    audit = ctx.maybe_shared(AUDIT_REPOSITORY)
    if audit is None:
        raise ComponentUnavailableError("audit_unavailable")
    try:
        queue_capacity = queue_capacity_from_env(ctx.environ)
        max_items = max_items_per_request_from_env(ctx.environ)
    except ValueError as exc:
        _log.warning("component %s: %s", _COMPONENT, exc)  # names the variable only
        raise ComponentUnavailableError("capture_env_invalid") from None
    settings = _interaction_settings(ctx, setting)
    store = interaction_store(ctx, settings=settings, retention=retention)
    policy_store = _policy_store(ctx)
    setattr(app.state, STATE_POLICY_STORE, policy_store)
    detectors = default_detector_set()
    pipeline = CapturePipeline(
        store,
        queue_capacity=queue_capacity,
        shed_at_percent=setting.shed_capture_at_queue_percent or _DEFAULT_SHED_PERCENT,
        max_content_chars=settings.max_content_chars_per_interaction or _DEFAULT_MAX_CONTENT_CHARS,
        detector_set_for=lambda _target: detectors,
    )
    writer = domain_audit_writer(audit, cloud=ctx.settings.cloud_profile.cloud.value)
    setattr(app.state, STATE_OFF_REASON, "startup_pending")
    ctx.disabled(_COMPONENT)  # until the startup hook has read the policies

    async def start() -> None:
        # Never raises: capture failing to start must not fail readiness or ingest.
        try:
            # Bounded: startup hooks run in sequence, so a hung read must not hold up the rest.
            matcher = await asyncio.wait_for(
                CaptureMatcher.from_store(
                    policy_store, setting_enabled=True, retention=retention, customer_id=customer
                ),
                timeout=_POLICY_READ_TIMEOUT_SECONDS,
            )
        except Exception:  # includes TimeoutError
            _off(ctx, "policy_store_unavailable")
            return
        edge = EdgeCapture(matcher, pipeline, writer, max_items_per_request=max_items)
        setattr(app.state, STATE_EDGE, edge)
        setattr(app.state, STATE_STATS, edge.stats)
        reason = edge.status()
        if reason is not None:
            _off(ctx, reason)
            return
        ingest.attach_capture(edge)
        setattr(app.state, STATE_OFF_REASON, None)
        ctx.ok(_COMPONENT)

    ctx.on_startup(start)


def build(ctx: BuildContext) -> None:
    for name in (STATE_EDGE, STATE_STATS, STATE_POLICY_STORE):
        setattr(ctx.app.state, name, None)
    try:
        _build(ctx)
    except ComponentUnavailableError as exc:
        _off(ctx, exc.reason)
    except Exception as exc:
        # Capture is optional: an unexpected error turns it off (type logged, never the text)
        # instead of failing readiness through the composition's build_error.
        _log.warning("component %s build raised %s", _COMPONENT, type(exc).__name__)
        _off(ctx, "capture_build_error")


BUILDER: Final = BuilderSpec("interactions", COMPONENTS, build)
