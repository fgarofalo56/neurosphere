"""Interaction explorer builder (PRP-104 item 2): installs ``app.state.interaction_explorer``.

Component ``interaction_explorer`` is OPTIONAL and never blocks readiness: every way the explorer
can be off reports ``disabled`` with a logged reason code, also on
``app.state.interaction_explorer_off_reason`` (``None`` only while the explorer is installed),
and leaves ``app.state.interaction_explorer`` ``None`` (routes answer 503
``interaction_explorer_unconfigured``; the replay payload branch keeps bodies off).

The explorer does NOT depend on capture being enabled: an operator who turns capture off still
has stored, possibly legally held content to investigate. It needs, in order (first failing gate
is the reason):

1. ``setting_absent``: no ``interaction_capture`` stored setting at all (enabled or not); nothing
   is read or built.
2. ``retention_not_enabled``: the customer retention policy does not opt in to bodies.
3. Whatever building the store reports (``key_vault_not_configured``, ``key_host_refused``,
   ``blob_not_configured``, ``cosmos_unconfigured``...), through the interactions builder's
   :func:`~neurosphere_api.runtime.builders.interactions.interaction_store` factory, which also
   memoizes the store so capture and the explorer share ONE instance.
4. ``customer_unconfigured`` / ``audit_unavailable``.

An unexpected error is ``explorer_build_error`` (logged by type only). Runs after the
``interactions`` builder (``default_builders``).
"""

from __future__ import annotations

import logging
from typing import Final

from neurosphere_api.interactions.service import (
    InteractionExplorer,
    configure_interaction_explorer,
)
from neurosphere_api.runtime.builders import (
    AUDIT_REPOSITORY,
    BuildContext,
    BuilderSpec,
    ComponentUnavailableError,
)
from neurosphere_api.runtime.builders.interactions import interaction_store

__all__ = ["BUILDER", "COMPONENTS", "build"]

COMPONENTS: Final = ("interaction_explorer",)
_COMPONENT: Final = "interaction_explorer"

_log = logging.getLogger("neurosphere_api.runtime")


def _off(ctx: BuildContext, reason: str) -> None:
    configure_interaction_explorer(ctx.app, None, off_reason=reason)
    # Off by default is the normal state, not a warning.
    level = (
        logging.INFO if reason in ("setting_absent", "retention_not_enabled") else logging.WARNING
    )
    _log.log(level, "component %s disabled: %s", _COMPONENT, reason)
    ctx.disabled(_COMPONENT)


def _customer(ctx: BuildContext) -> str:
    try:
        customer = ctx.auth_settings().resolved_customer_id(ctx.settings.env)
    except ComponentUnavailableError:
        customer = None
    if customer is None:
        raise ComponentUnavailableError("customer_unconfigured")
    return customer


def _build(ctx: BuildContext) -> None:
    store = interaction_store(ctx)
    customer = _customer(ctx)
    audit = ctx.maybe_shared(AUDIT_REPOSITORY)
    if audit is None:
        raise ComponentUnavailableError("audit_unavailable")
    explorer = InteractionExplorer(
        store=store,
        audit=audit,
        cloud=ctx.settings.cloud_profile.cloud.value,
        customer_id=customer,
    )
    configure_interaction_explorer(ctx.app, explorer)
    ctx.ok(_COMPONENT)


def build(ctx: BuildContext) -> None:
    configure_interaction_explorer(ctx.app, None, off_reason="startup_pending")
    try:
        _build(ctx)
    except ComponentUnavailableError as exc:
        _off(ctx, exc.reason)
    except Exception as exc:
        # Optional: an unexpected error turns the explorer off instead of failing readiness.
        _log.warning("component %s build raised %s", _COMPONENT, type(exc).__name__)
        _off(ctx, "explorer_build_error")


BUILDER: Final = BuilderSpec("interaction_explorer", COMPONENTS, build)
