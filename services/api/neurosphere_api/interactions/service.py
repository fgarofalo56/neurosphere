"""Interaction explorer: the metadata side (PRP-104 item 2).

:class:`InteractionExplorer` is what ``runtime/builders/interaction_explorer.py`` installs as
``app.state.interaction_explorer``: PRP-102's interaction store, the audit repository, and the
deployment's cloud and customer. ``None`` means the explorer is not configured; every route then
answers 503 ``dependency_transient`` reason ``interaction_explorer_unconfigured`` (and the replay
payload branch keeps bodies off, PRP-104 clarification 9).

:class:`InteractionExplorerService` answers searches over ``InteractionStore.query_index`` and
single-record reads over ``InteractionStore.get_metadata``. It returns ``InteractionRecord``
metadata only (findings summary and redaction state included); it never calls ``read_content``.
The customer comes from the caller's server-derived scope, never from the request, and a record
whose cloud, customer or domain differs from the deployment's and the caller's is treated as
absent (filtered from a page, 404 on a read).

No ``from __future__ import annotations``: FastAPI inspects the dependency signature.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Final

from fastapi import Depends, FastAPI, Request
from neurosphere_contracts.interactions.v1.interaction_record import InteractionRecord
from neurosphere_core.audit import AuditRepository
from neurosphere_core.errors import (
    DependencyTransientError,
    InvalidSchemaError,
    NeuroSphereError,
    NotFoundError,
)
from neurosphere_core.interactions import (
    InteractionQuery,
    InteractionStore,
    InteractionStoreError,
)
from neurosphere_core.interactions.models import INVALID_QUERY
from neurosphere_core.scope import IdentityScope
from pydantic import ValidationError

from neurosphere_api.interactions.models import InteractionPage

__all__ = [
    "OFF_REASON_ATTRIBUTE",
    "STATE_ATTRIBUTE",
    "UNCONFIGURED_REASON",
    "Explorer",
    "InteractionExplorer",
    "InteractionExplorerService",
    "InteractionSearch",
    "configure_interaction_explorer",
    "get_explorer",
]

#: ``app.state`` attribute of the installed :class:`InteractionExplorer` (``None`` when off).
STATE_ATTRIBUTE: Final = "interaction_explorer"
#: ``app.state`` attribute of the off reason code (``None`` while the explorer is installed).
OFF_REASON_ATTRIBUTE: Final = "interaction_explorer_off_reason"
#: 503 reason of every explorer route while the explorer is not configured.
UNCONFIGURED_REASON: Final = "interaction_explorer_unconfigured"


@dataclass(frozen=True, slots=True)
class InteractionExplorer:
    """Everything the explorer routes use (``app.state.interaction_explorer``).

    ``store`` is the composition's ONE interaction store (shared with capture); ``audit`` is the
    audit repository (item 3's content reads append to it fail-closed); ``cloud`` and
    ``customer_id`` are the deployment's: records of any other cloud or customer are never
    returned.
    """

    store: InteractionStore
    audit: AuditRepository
    cloud: str
    customer_id: str


def configure_interaction_explorer(
    app: FastAPI, explorer: InteractionExplorer | None, *, off_reason: str | None = None
) -> None:
    """Install (or clear, with ``None``) the explorer and its off reason on ``app.state``."""
    setattr(app.state, STATE_ATTRIBUTE, explorer)
    setattr(app.state, OFF_REASON_ATTRIBUTE, None if explorer is not None else off_reason)


def get_explorer(request: Request) -> InteractionExplorer:
    """The installed explorer, else 503 ``interaction_explorer_unconfigured``."""
    explorer = getattr(request.app.state, STATE_ATTRIBUTE, None)
    if not isinstance(explorer, InteractionExplorer):
        raise DependencyTransientError(
            "the interaction explorer is not configured in this deployment",
            reason=UNCONFIGURED_REASON,
        )
    return explorer


Explorer = Annotated[InteractionExplorer, Depends(get_explorer)]


@dataclass(frozen=True, slots=True)
class InteractionSearch:
    """Search filters from the request (the customer and domain come from scope and path)."""

    agent_id: str | None = None
    principal_id: str | None = None
    tool_id: str | None = None
    data_asset_id: str | None = None
    detected_category: str | None = None
    #: Inclusive lower bound on ``captured_at`` (``from``).
    captured_from: datetime | None = None
    #: Exclusive upper bound on ``captured_at`` (``to``).
    captured_before: datetime | None = None
    page_size: int | None = None
    continuation: str | None = None


def _store_unavailable() -> DependencyTransientError:
    return DependencyTransientError(
        "the interaction store is unavailable", reason="interaction_store_unavailable"
    )


class InteractionExplorerService:
    """Metadata search and read over the explorer's store. Never touches content."""

    def __init__(self, explorer: InteractionExplorer) -> None:
        self._explorer = explorer

    def _in_deployment(self, scope: IdentityScope) -> bool:
        return (
            scope.cloud == self._explorer.cloud and scope.customer_id == self._explorer.customer_id
        )

    def _visible(self, record: InteractionRecord, scope: IdentityScope, domain_id: str) -> bool:
        return (
            record.cloud.root == self._explorer.cloud
            and record.customer_id.root == scope.customer_id
            and record.domain_id.root == domain_id
        )

    def _query(
        self, scope: IdentityScope, domain_id: str, search: InteractionSearch
    ) -> InteractionQuery:
        fields: dict[str, object] = {
            "customer_id": scope.customer_id,
            "domain_id": domain_id,
            "agent_id": search.agent_id,
            "principal_id": search.principal_id,
            "tool_id": search.tool_id,
            "data_asset_id": search.data_asset_id,
            "detected_category": search.detected_category,
            "captured_from": search.captured_from,
            "captured_before": search.captured_before,
            "continuation": search.continuation,
        }
        if search.page_size is not None:
            fields["page_size"] = search.page_size
        try:
            return InteractionQuery.model_validate(fields)
        except ValidationError:
            # Only reason codes: the filter values are never echoed.
            raise InvalidSchemaError(
                "the interaction search filters are invalid", reason=INVALID_QUERY
            ) from None

    async def search(
        self, scope: IdentityScope, domain_id: str, search: InteractionSearch
    ) -> InteractionPage:
        query = self._query(scope, domain_id, search)
        if not self._in_deployment(scope):
            return InteractionPage(items=[], continuation=None)
        try:
            page = await self._explorer.store.query_index(query)
        except InteractionStoreError as exc:
            if exc.reason == INVALID_QUERY:
                raise InvalidSchemaError(
                    "the continuation token is not valid for this search", reason=INVALID_QUERY
                ) from None
            raise _store_unavailable() from exc
        except NeuroSphereError:
            raise
        except Exception as exc:
            raise _store_unavailable() from exc
        items = [record for record in page.items if self._visible(record, scope, domain_id)]
        return InteractionPage(items=items, continuation=page.continuation)

    async def get(
        self, scope: IdentityScope, domain_id: str, interaction_id: str
    ) -> InteractionRecord:
        record: InteractionRecord | None = None
        if self._in_deployment(scope):
            try:
                record = await self._explorer.store.get_metadata(
                    scope.customer_id, domain_id, interaction_id
                )
            except NeuroSphereError:
                raise
            except Exception as exc:
                raise _store_unavailable() from exc
        if record is None or not self._visible(record, scope, domain_id):
            raise NotFoundError("no such interaction", reason="interaction_not_found")
        if record.interaction_id.root != interaction_id:
            raise NotFoundError("no such interaction", reason="interaction_not_found")
        return record
