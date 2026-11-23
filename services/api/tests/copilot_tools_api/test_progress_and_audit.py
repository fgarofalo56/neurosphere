"""Engine progress events, tool-call audit and ports (PRP-78 item 5)."""

from __future__ import annotations

import json
import logging
from types import SimpleNamespace
from typing import Any, cast

import pytest
from action_plane_harness import ALICE  # pyright: ignore[reportMissingImports]
from copilot_api_harness import (  # pyright: ignore[reportMissingImports]
    CUSTOMER,
    FINANCE,
    ScriptedAdapter,
    call,
    make_scope,
    make_world,
    query_args,
    run_turn,
    say,
)
from copilot_http_harness import COPILOT_PREFIX, make_http  # pyright: ignore[reportMissingImports]
from neurosphere_api.audit.search_store import RepositoryAuditSearchStore
from neurosphere_api.authz.read_audit import ReadAuditStats, read_audit_chain_id
from neurosphere_api.copilot import (
    AuditChangeLogReader,
    CopilotExtraPorts,
    CopilotToolAuditor,
    build_tool_ports,
)
from neurosphere_api.copilot.models import ProgressEvent
from neurosphere_api.copilot.tooling import TOOL_CALL_OPERATION
from neurosphere_api.runtime.builders import AUDIT_REPOSITORY, AUDIT_SEARCH_STORE
from neurosphere_contracts.audit.v1.audit_record import AuditRecord
from neurosphere_core.audit import (
    AuditContext,
    AuditRepository,
    InMemoryAuditStore,
    build_after,
    build_allowed,
    domain_audit_chain_id,
    make_subject,
)
from neurosphere_core.copilot.models.protocol import AdapterDescriptor
from neurosphere_core.copilot.tools import COPILOT_TOOL_NAMES
from neurosphere_core.scope import IdentityScope
from tools_harness import make_tools_engine  # pyright: ignore[reportMissingImports]

FIN_AGENT = "commercial:contoso:foundry:agent:fin-1"
PROMPT_SENTINEL = "PROMPTSENTINEL-4471"
ARG_SENTINEL = "ARGVALUESENTINEL-9913"
ARG_KEY = "sentinelkey_qq7"


def analyst() -> IdentityScope:
    return make_scope([("analyst", [FINANCE])], [FINANCE])


def tools_repo() -> AuditRepository:
    return AuditRepository(InMemoryAuditStore())


def tools_auditor(repo: object | None) -> tuple[CopilotToolAuditor, ReadAuditStats]:
    stats = ReadAuditStats()
    return CopilotToolAuditor(lambda: repo, stats), stats


async def all_records(repo: AuditRepository) -> list[AuditRecord]:
    out: list[AuditRecord] = []
    for chain in (
        domain_audit_chain_id(CUSTOMER, FINANCE),
        read_audit_chain_id(CUSTOMER),
    ):
        tail = await repo.tail(chain)
        if tail is not None:
            out.extend(await repo.read_range(chain, start=0, limit=tail.sequence + 1))
    return out


def tool_records(records: list[AuditRecord]) -> list[AuditRecord]:
    return [r for r in records if r.operation == TOOL_CALL_OPERATION]


# -- progress events ------------------------------------------------------------------------------


async def test_progress_events_bracket_each_phase_and_keep_the_wire_order() -> None:
    model = ScriptedAdapter(
        call("search_catalog", {"query": query_args("agent", domain=FINANCE)}),
        say("One agent is active [cite:r1]."),
    )
    turn = await run_turn(make_tools_engine(model, make_world()), analyst())
    assert turn.names[0] == "context"
    progress = [e.payload for e in turn.of("progress")]
    assert [(p.phase, p.iteration) for p in progress if isinstance(p, ProgressEvent)] == [
        ("model", 1),
        ("tools", 1),
        ("model", 2),
        ("checking", 2),
    ]
    names = turn.names
    assert names.index("progress") < names.index("tool")
    assert names.index("tool") > names.index("progress") and turn.terminal.name == "done"
    assert sum(n in {"done", "abstain", "denied", "error"} for n in names) == 1
    checking = [
        i for i, e in enumerate(turn.events) if getattr(e.payload, "phase", "") == "checking"
    ]
    first_token = names.index("token")
    assert checking[0] < first_token  # nothing unjudged is emitted before the check


async def test_a_denied_turn_has_no_checking_phase_and_ends_on_the_terminal() -> None:
    model = ScriptedAdapter(call("delete_everything", {}))
    turn = await run_turn(make_tools_engine(model, make_world()), analyst())
    assert turn.terminal.name == "denied"
    phases = [getattr(e.payload, "phase", None) for e in turn.of("progress")]
    assert phases == ["model", "tools"]


# -- tool-call audit ------------------------------------------------------------------------------


async def test_an_allowed_call_writes_one_record_without_values() -> None:
    repo = tools_repo()
    auditor, stats = tools_auditor(repo)
    model = ScriptedAdapter(
        call("search_catalog", {"query": query_args("agent", domain=FINANCE)}),
        say("One agent is active [cite:r1]."),
    )
    engine = make_tools_engine(model, make_world(), auditor=auditor)
    turn = await run_turn(engine, analyst(), f"Which agents? {PROMPT_SENTINEL}")
    assert turn.terminal.name == "done"
    records = tool_records(await all_records(repo))
    assert len(records) == 1
    record = records[0]
    assert record.channel == "chat"
    assert record.kind == "after" and record.outcome is not None
    assert record.outcome.result == "succeeded"
    assert record.subject is not None and record.subject.state_digest is not None
    dumped = record.model_dump_json()
    assert PROMPT_SENTINEL not in dumped and "fin-1" not in dumped
    assert not stats.snapshot()


async def test_a_refused_call_writes_one_denied_record_with_the_reason_only() -> None:
    repo = tools_repo()
    auditor, _ = tools_auditor(repo)
    model = ScriptedAdapter(
        call("search_catalog", {ARG_KEY: ARG_SENTINEL, "query": query_args("agent")})
    )
    turn = await run_turn(make_tools_engine(model, make_world(), auditor=auditor), analyst())
    assert turn.terminal.name == "denied"
    records = tool_records(await all_records(repo))
    assert len(records) == 1
    record = records[0]
    assert record.kind == "denied" and record.denial is not None
    assert record.denial.reason == "argument_not_allowed"
    assert record.chain_id == read_audit_chain_id(CUSTOMER)
    dumped = record.model_dump_json()
    assert ARG_SENTINEL not in dumped and ARG_KEY not in dumped


async def test_a_failed_call_writes_one_failed_record() -> None:
    repo = tools_repo()
    auditor, _ = tools_auditor(repo)
    world = make_world()

    async def boom(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError(ARG_SENTINEL)

    world.catalog.list_entities = boom  # type: ignore[method-assign]
    model = ScriptedAdapter(call("search_catalog", {"query": query_args("agent", domain=FINANCE)}))
    turn = await run_turn(make_tools_engine(model, world, auditor=auditor), analyst())
    assert turn.terminal.name == "error"
    records = tool_records(await all_records(repo))
    assert len(records) == 1
    assert records[0].outcome is not None and records[0].outcome.result == "failed"
    assert records[0].outcome.detail == "tool_failed"
    assert ARG_SENTINEL not in records[0].model_dump_json()


class _FailingRepository(AuditRepository):
    async def append(self, chain_id: str, draft: Any) -> Any:
        raise RuntimeError(ARG_SENTINEL)


async def test_an_audit_write_failure_is_logged_counted_and_never_changes_the_answer(
    caplog: pytest.LogCaptureFixture,
) -> None:
    auditor, stats = tools_auditor(_FailingRepository(InMemoryAuditStore()))
    model = ScriptedAdapter(
        call("search_catalog", {"query": query_args("agent", domain=FINANCE)}),
        say("One agent is active [cite:r1]."),
    )
    with caplog.at_level(logging.WARNING):
        turn = await run_turn(make_tools_engine(model, make_world(), auditor=auditor), analyst())
    assert turn.terminal.name == "done"
    assert stats.snapshot() == {"audit_write_failed": 1}
    assert ARG_SENTINEL not in caplog.text


async def test_an_unconfigured_audit_store_is_counted_and_the_answer_stands() -> None:
    auditor, stats = tools_auditor(None)
    model = ScriptedAdapter(
        call("search_catalog", {"query": query_args("agent", domain=FINANCE)}),
        say("One agent is active [cite:r1]."),
    )
    turn = await run_turn(make_tools_engine(model, make_world(), auditor=auditor), analyst())
    assert turn.terminal.name == "done"
    assert stats.snapshot() == {"audit_store_unconfigured": 1}


# -- tool availability ----------------------------------------------------------------------------


async def test_recommend_agent_is_offered_only_with_a_matcher() -> None:
    bare = ScriptedAdapter(say("nothing"))
    await run_turn(make_tools_engine(bare, make_world()), analyst())
    offered = {t.name for t in bare.requests[0].tools}
    assert "recommend_agent" not in offered and "graph_query" not in offered
    assert "get_timeline" in offered

    wired = ScriptedAdapter(say("nothing"))
    matcher = cast(Any, SimpleNamespace())
    ports = CopilotExtraPorts(matcher=matcher, graph=cast(Any, SimpleNamespace()))
    await run_turn(make_tools_engine(wired, make_world(), extra_ports=ports), analyst())
    assert {t.name for t in wired.requests[0].tools} == set(COPILOT_TOOL_NAMES)


# -- status ---------------------------------------------------------------------------------------


class _RealModel(ScriptedAdapter):
    @property
    def descriptor(self) -> AdapterDescriptor:
        return AdapterDescriptor(kind="approved_endpoint", name="real", synthetic=False)


def test_status_reports_synthetic_from_the_adapter_descriptor() -> None:
    url = f"{COPILOT_PREFIX}/status"
    synthetic = make_http(ScriptedAdapter(say("x")))
    body = synthetic.client.get(url, headers=synthetic.headers(ALICE)).json()
    assert body == {"state": "ready", "reason_code": None, "synthetic": True}
    real = make_http(_RealModel(say("x")))
    assert real.client.get(url, headers=real.headers(ALICE)).json()["synthetic"] is False
    off = make_http(ScriptedAdapter(say("x")), configured=False)
    assert off.client.get(url, headers=off.headers(ALICE)).json()["synthetic"] is False


# -- change log and ports -------------------------------------------------------------------------


async def test_the_change_log_returns_changes_only_and_never_actor_or_state() -> None:
    from datetime import UTC, datetime, timedelta

    repo = tools_repo()
    scope = make_scope([("security_auditor", [FINANCE])], [FINANCE])
    chain = domain_audit_chain_id(CUSTOMER, FINANCE)
    subject = make_subject(FIN_AGENT, "agent", state={"secret": ARG_SENTINEL})

    def ctx(operation: str) -> AuditContext:
        return AuditContext.from_scope(
            scope, correlation_id="corr-test", operation=operation, channel="rest"
        )

    await repo.append(
        chain, build_after(ctx("catalog.update"), subject, result="succeeded", verified=True)
    )
    await repo.append(chain, build_allowed(ctx("catalog.search"), subject))
    await repo.append(chain, build_allowed(ctx(TOOL_CALL_OPERATION), subject))
    reader = AuditChangeLogReader(RepositoryAuditSearchStore(repo))
    now = datetime.now(UTC)
    found = await reader.changes(
        scope, [FINANCE], now - timedelta(hours=1), now + timedelta(hours=1), limit=10
    )
    assert [c.operation for c in found] == ["catalog.update"]
    change = found[0]
    assert change.subject_id == FIN_AGENT and change.domain_id == FINANCE
    assert set(type(change).model_fields) == {
        "record_id",
        "operation",
        "subject_id",
        "outcome",
        "occurred_at",
        "domain_id",
    }
    assert ARG_SENTINEL not in change.model_dump_json()
    # a domain the caller does not hold audit.read on yields nothing
    other = make_scope([("analyst", [FINANCE])], [FINANCE])
    assert not await reader.changes(
        other, [FINANCE], now - timedelta(hours=1), now + timedelta(hours=1), limit=10
    )


def _ctx(state: object, shared: dict[str, object]) -> Any:
    return SimpleNamespace(
        app=SimpleNamespace(state=state),
        maybe_shared=lambda key: shared.get(key.name),
    )


def test_build_tool_ports_binds_each_port_only_when_its_source_exists() -> None:
    world = make_world()
    empty = build_tool_ports(_ctx(SimpleNamespace(), {}))
    assert empty == CopilotExtraPorts()

    graph = cast(Any, SimpleNamespace())
    matcher = cast(Any, SimpleNamespace())
    repo = tools_repo()
    state = SimpleNamespace(
        catalog_graph=graph, catalog_repository=world.catalog, agent_matcher=matcher
    )
    shared = {
        AUDIT_SEARCH_STORE.name: RepositoryAuditSearchStore(repo),
        AUDIT_REPOSITORY.name: repo,
    }
    ports = build_tool_ports(_ctx(state, shared))
    assert ports.graph is graph and ports.matcher is matcher
    assert ports.access is not None
    assert isinstance(ports.changes, AuditChangeLogReader)

    no_audit = build_tool_ports(_ctx(state, {}))
    assert no_audit.changes is None
    state.agent_matcher = None  # unavailable matcher: recommend_agent stays unregistered
    assert build_tool_ports(_ctx(state, shared)).matcher is None


def test_the_serialized_progress_event_carries_no_content() -> None:
    from neurosphere_api.copilot.models import SseEvent

    event = SseEvent(name="progress", payload=ProgressEvent(phase="tools", iteration=2))
    assert event.encode() == b'event: progress\ndata: {"phase":"tools","iteration":2}\n\n'
    assert json.loads(event.encode().split(b"data: ")[1])["iteration"] == 2
