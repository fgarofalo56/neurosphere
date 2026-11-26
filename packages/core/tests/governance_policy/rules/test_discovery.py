"""``RuleEvaluatorRegistry.discover`` and the builtin registration (PRP-105 clarification 14)."""

from __future__ import annotations

import itertools
import textwrap
from datetime import datetime
from pathlib import Path

import pytest
from neurosphere_core.catalog.repo import InMemoryCatalogRepository
from neurosphere_core.governance.policy.rules import (
    BUILTIN_KINDS,
    PLUGIN_PACKAGE,
    RuleBuildContext,
    RuleEvaluatorRegistry,
    build_rule_registry,
)
from neurosphere_core.scope import IdentityScope

from .rules_helpers import NOW, SCOPE, FakeFindingReader, FakeSubjects, access_engine

_COUNTER = itertools.count()

_WORKING = """
from neurosphere_core.governance.policy.rules import RuleOutcome


class BudgetEvaluator:
    def __init__(self, cloud):
        self.cloud = cloud

    @property
    def kind(self):
        return "budget"

    async def evaluate(self, ctx, policy, rule):
        return RuleOutcome(kind="budget")


def build(ctx):
    return BudgetEvaluator(ctx.cloud)
"""

_DECLINES = """
def build(ctx):
    return None
"""

_RAISES = """
def build(ctx):
    raise RuntimeError("store not reachable")
"""

_NOT_AN_EVALUATOR = """
def build(ctx):
    return object()
"""

_BROKEN_IMPORT = """
import neurosphere_core.this_module_does_not_exist  # noqa: F401


def build(ctx):
    return None
"""


class _Scopes:
    async def get(self) -> IdentityScope:
        return SCOPE


def _now() -> datetime:
    return NOW


def _ctx() -> RuleBuildContext:
    repo = InMemoryCatalogRepository()
    return RuleBuildContext(
        catalog=repo,
        metrics=FakeSubjects(),
        access=access_engine(repo),
        cosmos_client=None,
        cloud="commercial",
        scope_provider=_Scopes(),
        clock=_now,
    )


def _plugin_package(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **modules: str) -> str:
    """A uniquely named plugin package on a temporary import path."""
    name = f"ns_test_rule_plugins_{next(_COUNTER)}"
    package = tmp_path / name
    package.mkdir()
    (package / "__init__.py").write_text('"""Test plugins."""\n', encoding="utf-8")
    for module, source in modules.items():
        (package / f"{module}.py").write_text(textwrap.dedent(source), encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    return name


def test_plugin_is_discovered_and_registered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = _plugin_package(tmp_path, monkeypatch, budget=_WORKING)
    registry = RuleEvaluatorRegistry(plugin_package=package)

    added = registry.discover(_ctx())

    assert added == ("budget",)
    assert registry.available_kinds == ("budget",)
    assert registry.status("budget") == "available"
    evaluator = registry.get("budget")
    assert evaluator is not None
    assert evaluator.kind == "budget"


def test_plugin_returning_none_reports_its_kind_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = _plugin_package(tmp_path, monkeypatch, identity_entitlement=_DECLINES)
    registry = RuleEvaluatorRegistry(plugin_package=package)

    assert registry.discover(_ctx()) == ()

    assert registry.status("identity_entitlement") == "evaluator_unavailable"
    assert registry.unavailable_reason("identity_entitlement") == "unavailable_in_deployment"
    (entry,) = registry.unavailable_kinds
    assert entry.kind == "identity_entitlement"
    assert entry.module == f"{package}.identity_entitlement"


def test_failing_plugins_report_plugin_failed_and_never_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = _plugin_package(
        tmp_path,
        monkeypatch,
        budget=_WORKING,
        required_attestation=_RAISES,
        odd_kind=_NOT_AN_EVALUATOR,
        broken_kind=_BROKEN_IMPORT,
        _private=_RAISES,
    )
    registry = RuleEvaluatorRegistry(plugin_package=package)

    added = registry.discover(_ctx())

    assert added == ("budget",)
    reasons = {u.kind: u.reason for u in registry.unavailable_kinds}
    assert reasons == {
        "broken_kind": "plugin_failed",
        "odd_kind": "plugin_failed",
        "required_attestation": "plugin_failed",
    }


def test_plugin_cannot_replace_a_builtin_kind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = _plugin_package(tmp_path, monkeypatch, budget=_WORKING)
    registry = build_rule_registry(_ctx(), plugin_package=package)
    first = registry.get("budget")

    assert registry.discover(_ctx()) == ()
    assert registry.get("budget") is first


def test_shipped_plugin_package_is_empty() -> None:
    registry = RuleEvaluatorRegistry()

    assert registry.discover(_ctx()) == ()
    assert registry.available_kinds == ()
    assert PLUGIN_PACKAGE == "neurosphere_core.governance.policy.rule_plugins"


def test_builtin_registration_without_a_finding_reader() -> None:
    registry = build_rule_registry(_ctx())

    assert set(registry.available_kinds) == set(BUILTIN_KINDS) - {"content_rule"}
    assert registry.unavailable_reason("content_rule") == "finding_reader_unbound"
    for later in ("budget", "identity_entitlement", "required_attestation"):
        assert registry.status(later) == "evaluator_unavailable"
        assert registry.unavailable_reason(later) == "no_evaluator"


def test_builtin_registration_with_a_finding_reader() -> None:
    registry = build_rule_registry(_ctx(), finding_reader=FakeFindingReader())

    assert set(registry.available_kinds) == set(BUILTIN_KINDS)
    assert registry.unavailable_kinds == ()


def test_duplicate_register_is_refused() -> None:
    registry = build_rule_registry(_ctx())
    existing = registry.get("residency")
    assert existing is not None

    with pytest.raises(ValueError, match="duplicate"):
        registry.register(existing)
