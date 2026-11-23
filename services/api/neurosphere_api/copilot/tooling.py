"""Ports and audit for the PRP-78 copilot tools (PRP-78 item 5).

* :func:`build_tool_ports` is the ONE place the optional tool ports are bound from ``app.state``
  (PRP-80 adds ``search_docs`` here). The Tier-1 copilot builder calls it and hands the result to
  :func:`~neurosphere_api.copilot.dependencies.configure_copilot`.
* :class:`AuditChangeLogReader` feeds ``get_timeline`` from the audit chains the caller holds
  ``audit.read`` on. It maps each record to a ``ChangeRecord`` (id, operation, subject id,
  outcome, time, domain) and nothing else: never the actor, a before/after state or a digest.
  Timeline rule: only CHANGES. Allowed-read records (``build_allowed``: the read-audit trail) and
  the copilot's own ``copilot.tool_call`` records are reads, so they are excluded.
* :class:`CopilotToolAuditor` appends one record per tool invocation (operation
  ``copilot.tool_call``, channel ``chat``). The subject state digest binds
  ``{tool, outcome, reason, domain_ids, result_count}``; arguments, prompt text and rows are never
  recorded. Chain: the domain chain when exactly one domain was consulted, otherwise the
  customer's ``<customer>.read-audit`` chain (the PRP-48 allowed-read rule). Failure rule
  (PRP-48 decision 3): a failed or unconfigured write is logged without values and counted on
  ``read_audit_stats`` (``audit_write_failed`` / ``audit_store_unconfigured``); it never changes
  the answer. ``allowed`` -> allow record; ``refused`` -> denied record (taxonomy code from the
  reason); ``failed`` -> ``after`` record with result ``failed`` and the reason as detail.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Final

from neurosphere_contracts.audit.v1.audit_record import AuditRecord
from neurosphere_core.audit import (
    AuditContext,
    AuditRepository,
    build_allowed,
    build_denied,
    domain_audit_chain_id,
    make_subject,
)
from neurosphere_core.audit.builders import AuditDraft, DenialCode, build_after, is_allow_record
from neurosphere_core.auth.scope import Permission, domains_with_permission
from neurosphere_core.catalog.graph.access import AccessEngine
from neurosphere_core.copilot.tools.ports import (
    AccessReader,
    AgentMatchReader,
    ChangeLogReader,
    ChangeRecord,
    GraphReader,
)
from neurosphere_core.copilot.tools.registry import RefusalEvent, ToolCallEvent
from neurosphere_core.errors import InvalidSchemaError
from neurosphere_core.observability import get_logger
from neurosphere_core.scope import IdentityScope

from neurosphere_api.audit.search_store import AuditSearchFilter, AuditSearchStore, position_of
from neurosphere_api.authz.read_audit import ReadAuditStats, read_audit_chain_id, read_audit_stats

if TYPE_CHECKING:
    from neurosphere_api.runtime.builders import BuildContext

__all__ = [
    "TOOL_CALL_OPERATION",
    "AuditChangeLogReader",
    "CopilotExtraPorts",
    "CopilotToolAuditor",
    "build_tool_ports",
]

_LOG = get_logger("neurosphere_api.copilot.tooling")

TOOL_CALL_OPERATION: Final = "copilot.tool_call"
_MAX_PAGES: Final = 5
_CORRELATION: Final = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_REASON: Final = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_FORBIDDEN_REASONS: Final = frozenset(
    {
        "permission_denied",
        "target_out_of_scope",
        "domain_out_of_scope",
        "depth_denied",
        "scope_argument_refused",
        "tool_not_registered",
    }
)


@dataclass(frozen=True, slots=True)
class CopilotExtraPorts:
    """The optional ports of the PRP-78 tools; an absent one leaves its tool unregistered or
    reporting unavailable (see ``build_copilot_registry``)."""

    graph: GraphReader | None = None
    access: AccessReader | None = None
    changes: ChangeLogReader | None = None
    matcher: AgentMatchReader | None = None


# -- change log -----------------------------------------------------------------------------------


def _is_change(record: AuditRecord) -> bool:
    if record.operation == TOOL_CALL_OPERATION:
        return False
    detail = record.outcome.detail if record.outcome is not None else None
    return not is_allow_record(record.kind, detail)


def _to_change(record: AuditRecord, domain_id: str) -> ChangeRecord:
    subject = record.subject.target.canonical_id if record.subject is not None else None
    if record.outcome is not None:
        outcome = record.outcome.result
    else:
        outcome = "denied"
    return ChangeRecord(
        record_id=str(record.audit_id.root),
        operation=record.operation,
        subject_id=subject or record.operation,
        outcome=outcome,
        occurred_at=datetime.fromisoformat(record.recorded_at.root.replace("Z", "+00:00")),
        domain_id=domain_id,
    )


class AuditChangeLogReader:
    """``ChangeLogReader`` over the audit search store, one chain per ``audit.read`` domain."""

    def __init__(self, store: AuditSearchStore) -> None:
        self._store = store

    async def changes(
        self,
        scope: IdentityScope,
        domain_ids: Sequence[str],
        since: datetime,
        until: datetime,
        *,
        limit: int,
    ) -> Sequence[ChangeRecord]:
        # Local import: ui_adapters imports the audit package (no cycle at module load).
        from neurosphere_api.ui_adapters.audit import auditable_chain

        held = set(domains_with_permission(scope, Permission.AUDIT_READ, now=until))
        chains: dict[str, str] = {}
        for domain_id in domain_ids:
            chain = auditable_chain(scope, domain_id) if domain_id in held else None
            if chain is not None:
                chains[domain_id] = chain
        if not chains or limit <= 0:
            return ()
        flt = AuditSearchFilter(since=since, until=until)
        out: list[ChangeRecord] = []
        before = None
        for _ in range(_MAX_PAGES):
            merged = await _page(self._store, chains, flt, before, limit)
            if not merged:
                break
            for domain_id, record in merged:
                if _is_change(record):
                    out.append(_to_change(record, domain_id))
            if len(out) >= limit or len(merged) < limit:
                break
            before = position_of(merged[-1][1])
        return tuple(out[:limit])


async def _page(
    store: AuditSearchStore,
    chains: dict[str, str],
    flt: AuditSearchFilter,
    before: Any,
    limit: int,
) -> list[tuple[str, AuditRecord]]:
    from neurosphere_api.audit.search import collect

    merged, _more = await collect(store, chains, flt, before=before, limit=limit)
    return merged


# -- tool-call audit ------------------------------------------------------------------------------


def _safe_correlation(value: str) -> str:
    return value if _CORRELATION.fullmatch(value) else f"corr-{uuid.uuid4().hex}"


def _chain_for(scope: IdentityScope, domains: tuple[str, ...]) -> str:
    if len(domains) == 1:
        try:
            return domain_audit_chain_id(scope.customer_id, domains[0])
        except InvalidSchemaError:
            _LOG.debug("tool-call audit falls back to the customer chain (unencodable domain)")
    return read_audit_chain_id(scope.customer_id)


def _subject_target(scope: IdentityScope, domains: tuple[str, ...]) -> tuple[str, str]:
    if len(domains) == 1:
        return domains[0], "domain"
    return f"{scope.cloud}:{scope.customer_id}:neurosphere:service:read-audit", "service"


class CopilotToolAuditor:
    """Built once; :meth:`for_turn` binds the scope and correlation id of one turn."""

    def __init__(
        self,
        repository: Callable[[], object | None],
        stats: ReadAuditStats,
    ) -> None:
        self._repository = repository
        self._stats = stats

    @classmethod
    def from_app_state(cls, app_state: object) -> CopilotToolAuditor:
        """Resolve ``app.state.audit_repository`` per write (it may be published after startup)."""
        return cls(
            lambda: getattr(app_state, "audit_repository", None), read_audit_stats(app_state)
        )

    def for_turn(self, scope: IdentityScope, correlation_id: str) -> _TurnAuditor:
        return _TurnAuditor(self, scope, _safe_correlation(correlation_id))

    async def record(self, scope: IdentityScope, correlation_id: str, event: ToolCallEvent) -> None:
        repository = self._repository()
        if not isinstance(repository, AuditRepository):
            self._stats.add("audit_store_unconfigured")
            _LOG.warning(
                "tool-call audit skipped: audit store not configured",
                extra={"operation": TOOL_CALL_OPERATION},
            )
            return
        try:
            domains = tuple(sorted({d for d in event.domain_ids if d}))
            target, entity_type = _subject_target(scope, domains)
            subject = make_subject(
                target,
                entity_type,
                state={
                    "tool": event.tool,
                    "outcome": event.outcome,
                    "reason": event.reason,
                    "domain_ids": list(domains),
                    "result_count": max(event.record_count, 0),
                },
            )
            ctx = AuditContext.from_scope(
                scope,
                correlation_id=correlation_id,
                operation=TOOL_CALL_OPERATION,
                channel="chat",
            )
            await repository.append(_chain_for(scope, domains), _draft(ctx, subject, event))
        except Exception as exc:
            self._stats.add("audit_write_failed")
            _LOG.warning(
                "tool-call audit write failed",
                extra={"operation": TOOL_CALL_OPERATION, "error_type": type(exc).__name__},
            )


def _reason_code(reason: str | None) -> str:
    return reason if reason is not None and _REASON.fullmatch(reason) else "unspecified"


def _draft(ctx: AuditContext, subject: Any, event: ToolCallEvent) -> AuditDraft:
    if event.outcome == "allowed":
        return build_allowed(ctx, subject)
    reason = _reason_code(event.reason)
    if event.outcome == "refused":
        code: DenialCode = "forbidden" if reason in _FORBIDDEN_REASONS else "invalid_schema"
        return build_denied(ctx, code=code, reason=reason, subject=subject)
    return build_after(ctx, subject, result="failed", verified=False, detail=reason)


class _TurnAuditor:
    """``ToolCallObserver`` (and ``RefusalSink``) bound to one turn."""

    def __init__(
        self, auditor: CopilotToolAuditor, scope: IdentityScope, correlation_id: str
    ) -> None:
        self._auditor = auditor
        self._scope = scope
        self._correlation_id = correlation_id

    async def tool_called(self, event: ToolCallEvent) -> None:
        await self._auditor.record(self._scope, self._correlation_id, event)

    def refused(self, event: RefusalEvent) -> None:
        """No-op: the observer sees every refusal too, so recording here would double-count."""
        return None


# -- ports ----------------------------------------------------------------------------------------


def build_tool_ports(ctx: BuildContext) -> CopilotExtraPorts:
    """Bind the optional tool ports from the composed ``app.state`` (absent -> ``None``)."""
    from neurosphere_api.runtime.builders import AUDIT_REPOSITORY, AUDIT_SEARCH_STORE

    state = ctx.app.state
    graph = getattr(state, "catalog_graph", None)
    repository = getattr(state, "catalog_repository", None)
    access = (
        AccessEngine(repository, graph) if graph is not None and repository is not None else None
    )
    search = ctx.maybe_shared(AUDIT_SEARCH_STORE)
    audit = ctx.maybe_shared(AUDIT_REPOSITORY)
    changes = AuditChangeLogReader(search) if search is not None and audit is not None else None
    return CopilotExtraPorts(
        graph=graph,
        access=access,
        changes=changes,
        matcher=getattr(state, "agent_matcher", None),
    )
