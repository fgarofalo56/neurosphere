"""Copilot registry composition and the tool-call observer (PRP-78 item 4)."""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass, field
from typing import Any

import pytest
from neurosphere_contracts.scope.v1.identity_scope import IdentityScope as ContractScope
from neurosphere_core.auth.scope import Permission
from neurosphere_core.copilot.tools import (
    COPILOT_TOOL_NAMES,
    TOOL_NAMES,
    CopilotToolDependencies,
    ToolBudgetError,
    ToolCallEvent,
    ToolDependencies,
    ToolRecord,
    ToolRegistry,
    ToolResult,
    ToolSpec,
    build_copilot_registry,
    build_default_registry,
)
from neurosphere_core.copilot.tools import registry as registry_module
from neurosphere_core.copilot.tools.args import ToolArgs
from neurosphere_core.copilot.tools.errors import (
    ArgumentNotAllowedError,
    ScopeArgumentRefusedError,
    ToolNotRegisteredError,
    ToolPermissionError,
    ToolTimeoutError,
)
from neurosphere_core.errors import InvalidSchemaError
from neurosphere_core.scope import IdentityScope

CUSTOMER = "contoso"
FINANCE = "commercial:contoso:catalog:domain:finance"
OPERATIONS = "commercial:contoso:catalog:domain:operations"
SENTINEL = "SENTINEL-VALUE-9f3b"


def make_scope(roles: list[tuple[str, list[str]]], allowed: list[str]) -> IdentityScope:
    contract = ContractScope.model_validate(
        {
            "schema_version": "1.0.0",
            "cloud": "commercial",
            "customer_id": CUSTOMER,
            "principal": {
                "principal_id": f"commercial:{CUSTOMER}:entra:person:psn_0123456789abcdef",
                "principal_pseudonym": "p-7f3a9c21",
                "principal_kind": "user",
            },
            "roles": [{"role": role, "domain_ids": domains} for role, domains in roles],
            "allowed_domains": allowed,
            "allowed_resources": [],
            "policy_version": "v1",
            "derived_at": "2026-10-20T00:00:00Z",
            "scope_hash": "sha256:" + hashlib.sha256(b"registry-scope").hexdigest(),
        }
    )
    return IdentityScope._from_verified_contract(contract)  # pyright: ignore[reportPrivateUsage]


def viewer() -> IdentityScope:
    return make_scope([("viewer", [FINANCE, OPERATIONS])], [FINANCE, OPERATIONS])


class Probe(ToolArgs):
    note: str = ""


@dataclass
class Recorder:
    events: list[ToolCallEvent] = field(default_factory=list[ToolCallEvent])

    async def tool_called(self, event: ToolCallEvent) -> None:
        self.events.append(event)


class BrokenObserver:
    async def tool_called(self, event: ToolCallEvent) -> None:
        raise RuntimeError(f"observer exploded {SENTINEL}")


def _result(n: int, domain_ids: tuple[str, ...] = ()) -> ToolResult:
    records = tuple(ToolRecord(record_id=f"r{i}", kind="k", data={}) for i in range(n))
    return ToolResult(tool="probe", records=records, citations=(), domain_ids=domain_ids)


def probe_spec(handler: Any) -> ToolSpec:
    return ToolSpec("probe", "probe tool", Probe, Permission.DATA_READ, handler)


def make_registry(handler: Any, observer: Any) -> ToolRegistry:
    return ToolRegistry([probe_spec(handler)], observer=observer)


async def ok_handler(scope: IdentityScope, args: Probe) -> ToolResult:
    return _result(2)


# -- composition ---------------------------------------------------------------------------------


class _Port:
    """Stands in for any port: composition never calls it."""


def _deps(**ports: Any) -> CopilotToolDependencies:
    anything: Any = _Port()
    return CopilotToolDependencies(
        catalog=anything,
        metrics=anything,
        recommendations=anything,
        evidence=anything,
        drafter=anything,
        **ports,
    )


def test_default_registry_is_exactly_the_five_tools() -> None:
    anything: Any = _Port()
    deps = ToolDependencies(
        catalog=anything,
        metrics=anything,
        recommendations=anything,
        evidence=anything,
        drafter=anything,
    )
    assert build_default_registry(deps).names == tuple(sorted(TOOL_NAMES))
    assert len(TOOL_NAMES) == 5


def test_copilot_registry_has_eight_tools_with_all_ports() -> None:
    port: Any = _Port()
    reg = build_copilot_registry(_deps(graph=port, access=port, changes=port, matcher=port))
    assert reg.names == tuple(sorted(COPILOT_TOOL_NAMES))
    assert len(reg.names) == 8


def test_copilot_registry_without_graph_or_matcher_has_six() -> None:
    reg = build_copilot_registry(_deps())
    assert reg.names == tuple(sorted((*TOOL_NAMES, "get_timeline")))
    assert len(reg.names) == 6


def test_graph_only_and_matcher_only() -> None:
    port: Any = _Port()
    assert "graph_query" in build_copilot_registry(_deps(graph=port)).names
    assert "recommend_agent" not in build_copilot_registry(_deps(graph=port)).names
    assert "recommend_agent" in build_copilot_registry(_deps(matcher=port)).names
    assert "graph_query" not in build_copilot_registry(_deps(matcher=port)).names


async def test_extra_specs_are_registered_and_duplicates_refused() -> None:
    extra = ToolSpec("search_docs", "docs", Probe, Permission.DATA_READ, ok_handler)
    reg = build_copilot_registry(_deps(), extra_specs=[extra])
    assert "search_docs" in reg.names
    clash = ToolSpec("get_timeline", "dup", Probe, Permission.DATA_READ, ok_handler)
    with pytest.raises(ValueError, match="duplicate"):
        build_copilot_registry(_deps(), extra_specs=[clash])


# -- observer ------------------------------------------------------------------------------------


async def test_success_event_has_count_and_fallback_domains() -> None:
    rec = Recorder()
    scope = viewer()
    await make_registry(ok_handler, rec).invoke("probe", {"note": SENTINEL}, scope)
    (event,) = rec.events
    assert event == ToolCallEvent(
        tool="probe",
        outcome="allowed",
        reason=None,
        domain_ids=(FINANCE, OPERATIONS),
        record_count=2,
        scope_hash=scope.scope_hash,
    )


async def test_result_domain_ids_win_over_fallback() -> None:
    async def handler(scope: IdentityScope, args: Probe) -> ToolResult:
        return _result(1, (FINANCE,))

    rec = Recorder()
    await make_registry(handler, rec).invoke("probe", {}, viewer())
    assert rec.events[0].domain_ids == (FINANCE,)


async def test_domain_ids_never_reach_the_serialized_result() -> None:
    assert "domain_ids" not in _result(1, (FINANCE,)).model_dump(mode="json")


async def test_unregistered_tool_refused_event() -> None:
    rec = Recorder()
    with pytest.raises(ToolNotRegisteredError):
        await make_registry(ok_handler, rec).invoke("nope", {}, viewer())
    (event,) = rec.events
    assert (event.outcome, event.reason, event.tool) == (
        "refused",
        "tool_not_registered",
        "<unregistered>",
    )
    assert event.record_count == 0
    assert event.domain_ids == ()


async def test_scope_shaped_key_refused_event() -> None:
    rec = Recorder()
    with pytest.raises(ScopeArgumentRefusedError):
        await make_registry(ok_handler, rec).invoke("probe", {"domain_ids": [SENTINEL]}, viewer())
    assert [(e.outcome, e.reason) for e in rec.events] == [("refused", "scope_argument_refused")]


async def test_undeclared_key_refused_event() -> None:
    rec = Recorder()
    with pytest.raises(ArgumentNotAllowedError):
        await make_registry(ok_handler, rec).invoke("probe", {"extra": SENTINEL}, viewer())
    assert [(e.outcome, e.reason) for e in rec.events] == [("refused", "argument_not_allowed")]


async def test_invalid_arguments_refused_event() -> None:
    rec = Recorder()
    with pytest.raises(InvalidSchemaError):
        await make_registry(ok_handler, rec).invoke("probe", {"note": 12}, viewer())
    assert [(e.outcome, e.reason) for e in rec.events] == [("refused", "invalid_arguments")]


async def test_handler_permission_and_budget_refusals() -> None:
    async def deny(scope: IdentityScope, args: Probe) -> ToolResult:
        raise ToolPermissionError("data.read")

    async def over_budget(scope: IdentityScope, args: Probe) -> ToolResult:
        raise ToolBudgetError("too big", reason="depth_denied")

    rec = Recorder()
    with pytest.raises(ToolPermissionError):
        await make_registry(deny, rec).invoke("probe", {}, viewer())
    with pytest.raises(ToolBudgetError):
        await make_registry(over_budget, rec).invoke("probe", {}, viewer())
    assert [(e.outcome, e.reason) for e in rec.events] == [
        ("refused", "permission_denied"),
        ("refused", "depth_denied"),
    ]


async def test_timeout_is_failed_event(monkeypatch: pytest.MonkeyPatch) -> None:
    async def slow(scope: IdentityScope, args: Probe) -> ToolResult:
        await asyncio.sleep(5)
        return _result(0)

    monkeypatch.setattr(registry_module, "DEFAULT_TIMEOUT_MS", 20)
    rec = Recorder()
    with pytest.raises(ToolTimeoutError):
        await make_registry(slow, rec).invoke("probe", {}, viewer())
    assert [(e.outcome, e.reason) for e in rec.events] == [("failed", "tool_timeout")]


async def test_unexpected_exception_is_failed_event_and_reraised_unchanged() -> None:
    boom = RuntimeError(f"boom {SENTINEL}")

    async def handler(scope: IdentityScope, args: Probe) -> ToolResult:
        raise boom

    rec = Recorder()
    with pytest.raises(RuntimeError) as info:
        await make_registry(handler, rec).invoke("probe", {}, viewer())
    assert info.value is boom
    assert [(e.outcome, e.reason) for e in rec.events] == [("failed", "tool_failed")]


async def test_observer_exception_changes_nothing() -> None:
    result = await make_registry(ok_handler, BrokenObserver()).invoke("probe", {}, viewer())
    assert len(result.records) == 2
    with pytest.raises(ToolNotRegisteredError):
        await make_registry(ok_handler, BrokenObserver()).invoke("nope", {}, viewer())


async def test_observer_called_exactly_once_per_invocation() -> None:
    rec = Recorder()
    reg = make_registry(ok_handler, rec)
    await reg.invoke("probe", {}, viewer())
    with pytest.raises(ArgumentNotAllowedError):
        await reg.invoke("probe", {"x": 1}, viewer())
    assert len(rec.events) == 2


async def test_event_never_contains_argument_values() -> None:
    rec = Recorder()
    reg = make_registry(ok_handler, rec)
    await reg.invoke("probe", {"note": SENTINEL}, viewer())
    with pytest.raises(ScopeArgumentRefusedError):
        await reg.invoke("probe", {"domain_id": SENTINEL}, viewer())
    with pytest.raises(ArgumentNotAllowedError):
        await reg.invoke("probe", {"other": SENTINEL}, viewer())
    with pytest.raises(InvalidSchemaError):
        await reg.invoke("probe", {"note": [SENTINEL]}, viewer())
    assert len(rec.events) == 4
    assert all(SENTINEL not in repr(e) for e in rec.events)


async def test_no_observer_is_fine() -> None:
    result = await ToolRegistry([probe_spec(ok_handler)]).invoke("probe", {}, viewer())
    assert len(result.records) == 2
