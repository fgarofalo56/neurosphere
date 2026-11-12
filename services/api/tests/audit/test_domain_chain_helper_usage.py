"""PRP-31 item 14b: every per-domain audit chain writer and reader goes through the one helper.

A writer that builds ``<customer>.<last segment>`` by hand would alias two sources of the same
name onto one chain again; a reader that hard-codes a source would make other sources
unauditable. Both are caught here by reading the source files.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]

#: (file, function) pairs that must delegate to the shared helper.
WRITERS = [
    ("packages/core/neurosphere_core/actions/audit.py", "action_audit_chain_id"),
    ("packages/core/neurosphere_core/hitl/auditing.py", "audit_chain_for"),
    ("services/api/neurosphere_api/catalog/service.py", "audit_chain_for"),
    ("services/api/neurosphere_api/catalog/curation/service.py", "audit_chain_id"),
    ("services/api/neurosphere_api/reports/audit.py", "_chain"),
    ("services/workers/neurosphere_workers/publication/recorder.py", "_chain"),
]
READERS = [
    ("services/api/neurosphere_api/authz/audit_mount.py", "domain_from_chain_id"),
    ("services/api/neurosphere_api/ui_adapters/audit.py", "auditable_chain"),
]
HELPERS = {
    "domain_audit_chain_id": "neurosphere_core.audit.chains",
    "domain_from_audit_chain": "neurosphere_core.audit.chains",
}


def _function(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} not found")


def _calls(node: ast.AST) -> set[str]:
    return {
        n.func.id
        for n in ast.walk(node)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }


def _imports_helper(tree: ast.Module, helper: str) -> bool:
    return any(
        isinstance(n, ast.ImportFrom)
        and n.module in (HELPERS[helper], "neurosphere_core.audit")
        and any(a.name == helper and a.asname is None for a in n.names)
        for n in tree.body
    )


@pytest.mark.parametrize(("path", "function"), WRITERS, ids=[f for _, f in WRITERS])
def test_writer_delegates_to_the_helper(path: str, function: str) -> None:
    tree = ast.parse((REPO / path).read_text(encoding="utf-8"))
    assert _imports_helper(tree, "domain_audit_chain_id"), path
    fn = _function(tree, function)
    assert "domain_audit_chain_id" in _calls(fn), f"{path}:{function}"
    # No hand-built chain id: no f-string and no ':'-split in the chain function.
    assert not any(isinstance(n, ast.JoinedStr) for n in ast.walk(fn)), f"{path}:{function}"
    assert "rsplit" not in ast.unparse(fn), f"{path}:{function}"


def test_mount_reader_delegates_to_the_inverse() -> None:
    path, function = READERS[0]
    tree = ast.parse((REPO / path).read_text(encoding="utf-8"))
    assert _imports_helper(tree, "domain_from_audit_chain")
    fn = _function(tree, function)
    assert "domain_from_audit_chain" in _calls(fn)
    code = [
        s for s in fn.body if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))
    ]
    assert "catalog" not in "".join(ast.unparse(s) for s in code)  # no hard-coded source segment


def test_adapter_reader_encodes_and_checks_the_round_trip() -> None:
    path, function = READERS[1]
    tree = ast.parse((REPO / path).read_text(encoding="utf-8"))
    assert _imports_helper(tree, "domain_audit_chain_id")
    calls = _calls(_function(tree, function))
    assert {"domain_audit_chain_id", "domain_from_chain_id"} <= calls


def test_no_other_api_or_core_module_hand_builds_a_domain_chain() -> None:
    """``<customer>.<domain_id.rsplit(':', 1)[-1]>`` must not reappear in product code."""
    offenders: list[str] = []
    roots = ("packages/core/neurosphere_core", "services/api/neurosphere_api")
    roots += ("services/workers/neurosphere_workers",)
    for root in roots:
        for file in sorted((REPO / root).rglob("*.py")):
            text = file.read_text(encoding="utf-8")
            for marker in ("}.{domain_id.rsplit(", "}.{_domain_name(domain_id)}"):
                if marker in text:
                    offenders.append(f"{file.relative_to(REPO)}: {marker}")
    assert offenders == []
