"""packages/core is a leaf: it must never import the services that depend on it."""

from __future__ import annotations

import ast
from pathlib import Path

_FORBIDDEN = {"neurosphere_api", "neurosphere_workers"}
_CORE = Path(__file__).resolve().parents[1] / "neurosphere_core"


def _imported_roots(path: Path) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def test_core_does_not_import_services() -> None:
    files = list(_CORE.rglob("*.py"))
    assert files
    offenders = {
        str(f.relative_to(_CORE)): sorted(_imported_roots(f) & _FORBIDDEN)
        for f in files
        if _imported_roots(f) & _FORBIDDEN
    }
    assert not offenders, offenders
