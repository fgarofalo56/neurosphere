"""Replay has no action capability: GET routes only and no import of any executor or connector."""

import ast
from pathlib import Path

import neurosphere_api.replay as replay_pkg
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


def _imports(path: Path) -> list[str]:
    found: list[str] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            found.append(base)
            found.extend(f"{base}.{alias.name}" for alias in node.names)
    return found


def test_replay_modules_import_no_action_capability() -> None:
    root = Path(replay_pkg.__file__).parent
    files = sorted(root.rglob("*.py"))
    assert len(files) >= 5
    offenders: list[str] = []
    for file in files:
        for name in _imports(file):
            lowered = name.lower()
            if name.startswith(FORBIDDEN_PREFIXES) or any(
                part in lowered for part in FORBIDDEN_NAMES
            ):
                offenders.append(f"{file.name}: {name}")
    assert offenders == []


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
