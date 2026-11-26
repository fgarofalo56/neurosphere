"""No direct publish, no direct ``enforce`` (PRP-105 item 7, acceptance criteria 5 and 6).

Static half: every code path in the governance engine, its API, its builder and the
``policy_eval`` worker that could set a policy ``published`` (or ``retired``) or a binding mode
is enumerated with the AST, and the set must equal the reviewed list below: only
``PolicyLifecycle`` (publish, retire, and the local seed that calls it) reaches the store's
``mark_published`` / ``mark_retired``, and only ``BindingStore.set_mode`` writes a mode other
than the ``audit``/``off`` start. A new writer anywhere fails this test until it is reviewed.

Behavioural half: ``POST .../publish`` leaves the policy a draft and answers an ADVISORY intent
(no write connector before PRP-108); a policy with ``mode: enforce`` is refused
``enforce_requires_mode_change`` by the route, the lifecycle and the binding store; bindings
created at publish are ``audit`` (``off`` for an ``off`` policy).
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Final

import pytest
from neurosphere_core.auth.scope import Role
from neurosphere_core.governance.policy import LifecycleAuditContext
from neurosphere_core.governance.policy.lifecycle import PublishRefusedError

from ..authz.world import Who, build_world, run
from .govpolicy_world import GovDep, GovWorld, draft_body, install, rule

REPO: Final = Path(__file__).resolve().parents[3]
SCANNED: Final = (
    "packages/core/neurosphere_core/governance",
    "services/api/neurosphere_api/governance",
    "services/api/neurosphere_api/runtime/builders/governance.py",
    "services/workers/neurosphere_workers/policy_eval",
)
#: Store methods that change a policy's stage or a binding's mode.
STAGE_CALLS: Final = frozenset(
    {"mark_published", "mark_retired", "set_mode", "_transition", "ensure_bindings"}
)
CORE: Final = "packages/core/neurosphere_core/governance/policy"
WORKER: Final = "services/workers/neurosphere_workers/policy_eval/worker.py"
BUILDER: Final = "services/api/neurosphere_api/runtime/builders/governance.py"

#: The reviewed writer sites: (module, enclosing qualname, what it does).
EXPECTED: Final = frozenset(
    {
        # PolicyLifecycle is the one caller of the stage transitions.
        (f"{CORE}/lifecycle.py", "PolicyLifecycle.publish", "call mark_published"),
        (f"{CORE}/lifecycle.py", "PolicyLifecycle.retire", "call mark_retired"),
        (f"{CORE}/lifecycle.py", "PolicyLifecycle._ensure_bindings", "call ensure_bindings"),
        # The store implements them (the only literal published/retired status writes).
        (f"{CORE}/store.py", "DocumentPolicyDefinitionStore.mark_published", "call _transition"),
        (f"{CORE}/store.py", "DocumentPolicyDefinitionStore.mark_published", "status=published"),
        (f"{CORE}/store.py", "DocumentPolicyDefinitionStore.mark_retired", "call _transition"),
        (f"{CORE}/store.py", "DocumentPolicyDefinitionStore.mark_retired", "status=retired"),
        # Bindings: built at audit/off by ensure_bindings, re-validated by _replace, and the
        # mode itself is written only by set_mode (PRP-108's mode-change handler calls it).
        (f"{CORE}/store.py", "BindingStore.ensure_bindings", "builds EnforcementBinding"),
        (f"{CORE}/store.py", "BindingStore._replace", "builds EnforcementBinding"),
        (f"{CORE}/store.py", "BindingStore.set_mode", "call _replace with mode"),
        # The worker's due-first view forwards the protocol to the wrapped store, unchanged.
        (WORKER, "DueFirstPolicies.mark_published", "call mark_published"),
        (WORKER, "DueFirstPolicies.mark_retired", "call mark_retired"),
        # The NS_ENV=local seed publishes through the lifecycle.
        (BUILDER, "seed_policies", "call lifecycle.publish"),
    }
)


def _modules() -> list[Path]:
    out: list[Path] = []
    for entry in SCANNED:
        path = REPO / entry
        out.extend(sorted(path.rglob("*.py")) if path.is_dir() else [path])
    return out


def _const(node: ast.AST | None) -> object:
    return node.value if isinstance(node, ast.Constant) else None


def _dict_keys(node: ast.AST) -> set[object]:
    return {_const(k) for k in node.keys} if isinstance(node, ast.Dict) else set()


def _receiver(func: ast.Attribute) -> str:
    value = func.value
    if isinstance(value, ast.Attribute):
        return value.attr
    if isinstance(value, ast.Name):
        return value.id
    return ""


class _Scanner(ast.NodeVisitor):
    def __init__(self, module: str) -> None:
        self.module = module
        self.stack: list[str] = []
        self.found: set[tuple[str, str, str]] = set()

    def _add(self, what: str) -> None:
        self.found.add((self.module, ".".join(self.stack) or "<module>", what))

    def _scoped(self, node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    visit_ClassDef = _scoped  # noqa: N815
    visit_FunctionDef = _scoped  # noqa: N815
    visit_AsyncFunctionDef = _scoped  # noqa: N815

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Attribute):
            if func.attr in STAGE_CALLS:
                self._add(f"call {func.attr}")
            if func.attr == "_replace" and any("mode" in _dict_keys(a) for a in node.args):
                self._add("call _replace with mode")
            if func.attr in ("publish", "retire") and _receiver(func).endswith("lifecycle"):
                self._add(f"call lifecycle.{func.attr}")
            if func.attr in ("model_validate", "model_construct") and _receiver(func) == (
                "EnforcementBinding"
            ):
                self._add("builds EnforcementBinding")
        elif isinstance(func, ast.Name) and func.id == "EnforcementBinding":
            self._add("builds EnforcementBinding")
        for keyword in node.keywords:
            self._literal(keyword.arg, keyword.value)
        self.generic_visit(node)

    def visit_Dict(self, node: ast.Dict) -> None:
        for key, value in zip(node.keys, node.values, strict=True):
            self._literal(_const(key), value)
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            if isinstance(target, ast.Attribute):
                self._literal(target.attr, node.value)
        self.generic_visit(node)

    def _literal(self, key: object, value: ast.AST) -> None:
        constant = _const(value)
        if key == "status" and constant in ("published", "retired"):
            self._add(f"status={constant}")
        if key == "mode" and constant == "enforce":
            self._add("mode=enforce")


def scan_source(source: str, module: str = "<planted>") -> set[tuple[str, str, str]]:
    scanner = _Scanner(module)
    scanner.visit(ast.parse(source))
    return scanner.found


def scan() -> set[tuple[str, str, str]]:
    found: set[tuple[str, str, str]] = set()
    for path in _modules():
        module = path.relative_to(REPO).as_posix()
        found |= scan_source(path.read_text(encoding="utf-8"), module)
    return found


def test_every_scanned_root_exists() -> None:
    for entry in SCANNED:
        assert (REPO / entry).exists(), entry
    names = {p.name for p in _modules()}
    assert {"lifecycle.py", "store.py", "router.py", "service.py", "worker.py"} <= names


def test_only_the_lifecycle_and_set_mode_write_a_stage_or_a_mode() -> None:
    found = scan()
    unexpected = sorted(found - EXPECTED)
    missing = sorted(EXPECTED - found)
    assert not unexpected, f"new publish/enforce writer(s) need review: {unexpected}"
    assert not missing, f"the reviewed writer list is stale (code moved?): {missing}"


def test_no_api_route_or_worker_tick_reaches_a_stage_transition() -> None:
    for module, qualname, what in scan():
        if module.startswith("services/api/neurosphere_api/governance"):
            pytest.fail(f"API module writes a stage or mode: {module} {qualname} {what}")
        if module == WORKER:
            assert qualname.startswith("DueFirstPolicies."), (module, qualname, what)


@pytest.mark.parametrize(
    ("planted", "expected"),
    [
        ("async def f(s):\n    await s.mark_published('c', 'p', 1)", "call mark_published"),
        ("async def f(s):\n    await s.set_mode('c', 'b', 'enforce')", "call set_mode"),
        ("def f():\n    return {'status': 'published'}", "status=published"),
        ("def f(m):\n    return m(status='retired')", "status=retired"),
        ("def f(b):\n    b.mode = 'enforce'", "mode=enforce"),
        ("def f():\n    return {'mode': 'enforce'}", "mode=enforce"),
        ("def f(x):\n    return EnforcementBinding.model_validate(x)", "builds EnforcementBinding"),
        ("async def f(self):\n    await self.lifecycle.publish('p', 1)", "call lifecycle.publish"),
    ],
)
def test_the_scanner_catches_each_planted_writer(planted: str, expected: str) -> None:
    assert expected in {what for (_m, _q, what) in scan_source(planted)}


def test_a_comparison_or_a_docstring_is_not_a_writer() -> None:
    source = 'def f(p):\n    """status: published"""\n    return p.status == "published"\n'
    assert scan_source(source) == set()


# -- behaviour ---------------------------------------------------------------------------------

FIN: Final = "finance"
STEWARD: Final = Who("contoso", FIN, Role.DOMAIN_STEWARD)


@pytest.fixture
def gw() -> Iterator[GovWorld]:
    yield install(build_world())


def _operations(gd: GovDep) -> list[str]:
    store = gd.dep.audit_store
    chains = {chain for (chain, _doc) in store._docs}  # pyright: ignore[reportPrivateUsage]
    return [str(d["operation"]) for c in sorted(chains) for d in store.raw_documents(c)]


def _bindings(gw: GovWorld, policy_id: str) -> list[Any]:
    return run(gw.stores.bindings.list("contoso", policy_id=policy_id, include_retired=True))


def _create(gd: GovDep, **over: Any) -> Any:
    response = gd.call(
        "POST",
        f"/domains/{gd.domain(FIN)}/policies",
        gd.dep.bearer(STEWARD),
        json=draft_body(**over),
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_post_publish_drafts_an_advisory_intent_and_the_policy_stays_a_draft(
    gw: GovWorld,
) -> None:
    gd = gw["contoso"]
    created = _create(gd, rules=[rule("pii-read", "data_sensitivity_access")])
    path = f"/domains/{gd.domain(FIN)}/policies/fin-owners"
    response = gd.call(
        "POST",
        f"{path}/publish",
        gd.dep.bearer(STEWARD),
        json={"version": 1, "idempotency_key": "govpolicy-suite-publish1"},
    )
    assert response.status_code == 201, response.text
    view = response.json()
    assert view["advisory"] is True, "no platform-control write connector before PRP-108"
    assert view["intent"]["action_kind"] == "governance_policy_publish"
    assert view["intent"]["state"] == "drafted"

    scope = gd.scope_of(STEWARD)
    principal = scope.to_contract().principal.principal_id.root
    for permission in ("action.propose", "action.approve", "action.execute"):
        gd.rechecker.grant(principal, "contoso", gd.domain(FIN), permission)
    validated = gd.dep.client.post(
        f"/api/v1/actions/domains/{gd.domain(FIN)}/intents/{view['intent']['intent_id']}/validate",
        headers=gd.dep.bearer(STEWARD),
    )
    assert validated.status_code == 200, validated.text
    checks = {c["check_id"]: c for c in validated.json()["intent"]["prerequisite_results"]}
    assert "no supported write connector" in checks["write_connector_supported"]["detail"]

    after = gd.call("GET", path, gd.dep.bearer(STEWARD)).json()
    assert after["policy"]["status"] == "draft"
    assert after["etag"] == created["etag"]
    assert _bindings(gw, "fin-owners") == [], "no binding exists before a real publish"
    assert "govpolicy.publish" not in _operations(gd)


def test_mode_enforce_is_refused_by_the_route_the_lifecycle_and_the_binding_store(
    gw: GovWorld,
) -> None:
    gd = gw["contoso"]
    _create(gd, mode="enforce", rules=[rule("pii-read", "data_sensitivity_access")])
    response = gd.call(
        "POST",
        f"/domains/{gd.domain(FIN)}/policies/fin-owners/publish",
        gd.dep.bearer(STEWARD),
        json={"version": 1, "idempotency_key": "govpolicy-suite-enforce1"},
    )
    assert response.status_code == 422, response.text
    assert response.json()["reason"] == "enforce_requires_mode_change"
    assert gd.intents.create_calls == 0

    stored = run(gd.plane.policies.get("contoso", "fin-owners"))
    assert stored is not None
    scope = gd.scope_of(STEWARD)
    with pytest.raises(PublishRefusedError) as refused:
        run(
            gd.plane.lifecycle.publish(
                "fin-owners",
                1,
                expected_etag=stored.etag,
                audit_ctx=LifecycleAuditContext(
                    scope=scope,
                    correlation_id="corr-suite-enforce",
                    intent_id="00000000-0000-4000-8000-00000000e001",
                ),
            )
        )
    assert refused.value.reason == "enforce_requires_mode_change"

    with pytest.raises(Exception) as direct:
        run(
            gw.stores.bindings.ensure_bindings(
                stored.policy, ["tool_call"], "enforce", updated_by="suite"
            )
        )
    assert getattr(direct.value, "reason", None) == "enforce_requires_mode_change"
    after = run(gd.plane.policies.get("contoso", "fin-owners"))
    assert after is not None and after.policy.status == "draft"
    assert _bindings(gw, "fin-owners") == []


@pytest.mark.parametrize(("mode", "expected"), [("audit", "audit"), ("off", "off")])
def test_bindings_created_at_publish_start_in_audit_or_off(
    gw: GovWorld, mode: str, expected: str
) -> None:
    gd = gw["contoso"]
    _create(gd, mode=mode, rules=[rule("pii-read", "data_sensitivity_access")])
    stored = run(gd.plane.policies.get("contoso", "fin-owners"))
    assert stored is not None
    published = run(gd.publish_directly(gd.scope_of(STEWARD), stored))
    assert published.policy.status == "published"
    bindings = _bindings(gw, "fin-owners")
    assert bindings, "publishing created bindings"
    assert {b.binding.mode.root for b in bindings} == {expected}
    listed = gd.call("GET", f"/domains/{gd.domain(FIN)}/bindings", gd.dep.bearer(STEWARD))
    assert {b["binding"]["mode"] for b in listed.json()["items"]} == {expected}
    assert "enforce" not in {b.binding.mode.root for b in _bindings(gw, "fin-owners")}
