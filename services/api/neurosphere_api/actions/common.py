"""Helpers shared by the action and review routes: caller identity, the connector probe, views.

The probe is the ONLY connector call the API makes: ``dry_run`` against the drafted
``target_version`` (the documented "plan, write nothing" method). A connector that reports the
target moved (``stale_version``) yields :data:`TARGET_CHANGED`, which never equals a drafted
version, so :class:`~neurosphere_core.actions.ActionService` fails the intent with
``stale_version`` ``target_version_changed`` through its own audited path.
"""

from __future__ import annotations

from typing import Final

from fastapi import HTTPException
from neurosphere_connector.write import WriteConnector, WriteRequest
from neurosphere_core.actions import ActionCaller, IntentKey, StoredIntent
from neurosphere_core.actions.errors import IntentNotFoundError
from neurosphere_core.actions.models import CallerChannel
from neurosphere_core.errors import DependencyTransientError, NeuroSphereError, StaleVersionError
from neurosphere_core.scope import IdentityScope

from neurosphere_api.actions.dependencies import ActionPlane
from neurosphere_api.actions.models import ActionView

__all__ = [
    "TARGET_CHANGED",
    "action_view",
    "audit_correlation_id",
    "caller_for",
    "load_intent",
    "not_found",
    "probe_target_version",
    "write_request",
]

#: Sentinel "current version" for a target the connector reports as changed. The NUL byte keeps
#: it distinct from any real version; it is only compared, never stored or returned.
TARGET_CHANGED: Final = "\x00target-changed"
WRITE_CONNECTOR_UNAVAILABLE: Final = "write_connector_unavailable"


def audit_correlation_id(request_id: str) -> str:
    """Request correlation id in audit-safe form (the PRP-06 content guard rejects GUID-shaped
    values outside server-assigned fields), same convention as ``catalog.curation``."""
    return "corr-" + request_id.replace("-", "")


def caller_for(
    scope: IdentityScope, correlation_id: str, channel: CallerChannel | None
) -> ActionCaller:
    """The verified caller. Identity comes from the server-derived scope only; this API never
    sets ``on_behalf_of`` (a surface acting for someone else must supply the real id server-side,
    see :func:`neurosphere_api.actions.service.ActionApi.confirm`)."""
    return ActionCaller.from_scope(scope, correlation_id=correlation_id, channel=channel)


def not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="not found")


async def load_intent(plane: ActionPlane, key: IntentKey) -> StoredIntent:
    """The stored intent in the caller's partition, or 404 (also for another domain's id)."""
    try:
        return await plane.actions.get(key)
    except IntentNotFoundError:
        raise not_found() from None


def write_request(stored: StoredIntent) -> WriteRequest:
    return WriteRequest(
        target=stored.intent.target,
        target_version=stored.intent.target_version,
        proposed_diff=stored.intent.proposed_diff,
    )


def connector_unavailable(cause: BaseException) -> DependencyTransientError:
    error = DependencyTransientError(
        "write connector unavailable", reason=WRITE_CONNECTOR_UNAVAILABLE
    )
    error.__cause__ = cause
    return error


async def probe_target_version(connector: WriteConnector, stored: StoredIntent) -> str:
    """Current target version as the connector sees it (``dry_run``; nothing is written)."""
    try:
        result = await connector.dry_run(write_request(stored))
    except StaleVersionError:
        return TARGET_CHANGED
    except NeuroSphereError:
        raise
    except Exception as exc:
        raise connector_unavailable(exc) from exc
    return result.target_version


def action_view(plane: ActionPlane, stored: StoredIntent) -> ActionView:
    """``ActionView`` for ``stored``. ``requires_approval`` is the value recorded at confirm
    once the intent was confirmed, else the current per-kind policy."""
    kind = stored.intent.action_kind
    confirmed = (
        stored.execution is not None
        or stored.review_item_id is not None
        or stored.state == "awaiting_approval"
    )
    requires_approval = stored.requires_approval if confirmed else plane.requires_approval(kind)
    return ActionView.build(
        stored,
        advisory=stored.advisory or plane.connector_for(kind) is None,
        requires_approval=requires_approval,
        self_approval_forbidden=plane.self_approval_forbidden(kind),
    )
