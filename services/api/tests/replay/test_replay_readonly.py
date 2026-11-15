"""Replay has no action capability: GET routes only and no import of any executor or connector."""

import ast
from pathlib import Path

import neurosphere_api.replay as replay_pkg
import pytest
from neurosphere_api.replay import build_router
from replay_support import ALICE, FINANCE, TRACE, make_api  # pyright: ignore[reportMissingImports]

FORBIDDEN_PREFIXES = (
    "neurosphere_api.actions",
    "neurosphere_core.actions",
    "neurosphere_api.connectors",
    "neurosphere_connector",
    "neurosphere_connectors",
    "neurosphere_workers",
)
FORBIDDEN_NAMES = ("executor", "connector")


FORBIDDEN_SEGMENT_PREFIXES = ("actions",)
DYNAMIC_IMPORTERS = {
    "__import__",
    "import_module",
    "importlib.import_module",
    "importlib.__import__",
}
NON_LITERAL = "<non-literal dynamic import>"
PACKAGE = "neurosphere_api.replay"


def _dotted(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_dotted(node.value)}.{node.attr}"
    return ""


def _resolve(node: ast.ImportFrom, package: str) -> str:
    """Absolute base module of a ``from`` import, resolving ``node.level`` against ``package``."""
    module = node.module or ""
    if node.level == 0:
        return module
    parts = package.split(".")
    anchor = parts[: len(parts) - (node.level - 1)]
    return ".".join([*anchor, module] if module else anchor)


def _imports(path: Path, package: str = PACKAGE) -> list[str]:
    found: list[str] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = _resolve(node, package)
            found.append(base)
            found.extend(f"{base}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Call) and _dotted(node.func) in DYNAMIC_IMPORTERS:
            first = node.args[0] if node.args else None
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                found.append(first.value)
            else:
                found.append(NON_LITERAL)
    return found


def _forbidden(name: str) -> bool:
    lowered = name.lower()
    return (
        name.startswith(FORBIDDEN_PREFIXES)
        or name == NON_LITERAL
        or any(part in lowered for part in FORBIDDEN_NAMES)
        or any(seg.startswith(FORBIDDEN_SEGMENT_PREFIXES) for seg in lowered.split("."))
    )


def _offenders(files: list[Path]) -> list[str]:
    return [f"{f.name}: {n}" for f in files for n in _imports(f) if _forbidden(n)]


def test_replay_modules_import_no_action_capability() -> None:
    root = Path(replay_pkg.__file__).parent
    files = sorted(root.rglob("*.py"))
    assert len(files) >= 5
    assert _offenders(files) == []


@pytest.mark.parametrize(
    "source",
    [
        "from . import actions_x\n",
        "from .. import executor\n",
        "from ..actions import run\n",
        'import importlib\nimportlib.import_module("neurosphere_api.actions")\n',
        'x = __import__("neurosphere_core.actions")\n',
        'import importlib\nimportlib.__import__("neurosphere_api.connectors")\n',
        "import importlib\nimportlib.import_module(name)\n",
    ],
)
def test_guard_catches_forbidden_import_forms(tmp_path: Path, source: str) -> None:
    fixture = tmp_path / "bad.py"
    fixture.write_text(source, encoding="utf-8")
    assert _offenders([fixture]) != []


def test_guard_accepts_innocent_relative_imports(tmp_path: Path) -> None:
    fixture = tmp_path / "ok.py"
    fixture.write_text("from . import models\nfrom .assemble import build\n", encoding="utf-8")
    assert _offenders([fixture]) == []


def test_router_has_get_routes_only() -> None:
    methods: set[str] = set()
    paths: list[str] = []
    for route in build_router().routes:
        route_methods = getattr(route, "methods", None) or set()
        methods |= set(route_methods)
        paths.append(getattr(route, "path", ""))
    assert paths
    assert methods <= {"GET", "HEAD"}
    assert not methods & {"POST", "PUT", "PATCH", "DELETE"}


def test_write_methods_are_rejected_on_the_wire() -> None:
    api = make_api()
    url = f"/api/v1/replay/domains/{FINANCE}/traces/{TRACE}"
    for method in ("post", "put", "patch", "delete"):
        response = getattr(api.h.client, method)(url, headers=api.h.auth(ALICE))
        assert response.status_code in {404, 405}
