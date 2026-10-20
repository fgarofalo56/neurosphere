"""The duplicate job has no mutation path (NS-03: consolidation REVIEW, never a merge).

Static: an AST scan of every module of the package (tests excluded) finds no catalog write API
import and no call to a mutating method. Dynamic: a full run through read-only proxies that
expose only ``neighbors`` and ``list_entities`` leaves the catalog byte-for-byte unchanged.
"""

from __future__ import annotations

import ast
import asyncio
import re
from pathlib import Path

import neurosphere_workers.recommendations.duplicates as package
from neurosphere_workers.recommendations.duplicates import DuplicateDetector

from .support import CREATED_AT, Estate, ReadOnlyGraph, ReadOnlyLister, make_scope, snapshot

PACKAGE_DIR = Path(package.__file__).resolve().parent

MUTATION = re.compile(
    r"^(update|upsert|put|merge|delete|remove|curate|lock|unlock|create|replace|deprecate|"
    r"retire|write|set|save|insert|patch|record|override|apply|execute|archive|supersede)"
    r"(_|$)"
)
FORBIDDEN_MODULE_PREFIXES = (
    "neurosphere_core.catalog.repo",
    "neurosphere_core.catalog.rules",
    "neurosphere_core.catalog.review_queue",
    "neurosphere_core.catalog.graph",
    "neurosphere_api",
)
FORBIDDEN_NAMES = {
    "CatalogRepository",
    "InMemoryCatalogRepository",
    "CosmosCatalogRepository",
    "RepositoryGraphQuery",
    "CatalogEngine",
    "EdgeOverride",
    "EdgeObservation",
    "ReviewQueue",
}
ALLOWED_AWAITED_ON_HANDLES = {"neighbors", "list_entities"}


def _modules() -> list[Path]:
    found = [
        p for p in PACKAGE_DIR.rglob("*.py") if "tests" not in p.relative_to(PACKAGE_DIR).parts
    ]
    assert {p.name for p in found} >= {"detector.py", "config.py", "models.py", "__init__.py"}
    return found


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_no_catalog_write_api_is_imported() -> None:
    for path in _modules():
        for node in ast.walk(_tree(path)):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                assert not module.startswith(FORBIDDEN_MODULE_PREFIXES), (path.name, module)
                for alias in node.names:
                    assert alias.name not in FORBIDDEN_NAMES, (path.name, alias.name)
                    assert not MUTATION.match(alias.name), (path.name, alias.name)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith(FORBIDDEN_MODULE_PREFIXES), alias.name


def test_no_mutating_method_is_called() -> None:
    offenders: list[str] = []
    for path in _modules():
        for node in ast.walk(_tree(path)):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if isinstance(func, ast.Name) and name == "set":
                continue  # the builtin ``set()`` constructor, not a method on a catalog object
            if MUTATION.match(name):
                offenders.append(f"{path.name}:{node.lineno} {name}")
    assert offenders == []


def test_only_read_operations_are_awaited_on_the_catalog_handles() -> None:
    """Every call on ``self._graph`` / ``self._agents`` is a read."""
    seen: set[str] = set()
    for path in _modules():
        for node in ast.walk(_tree(path)):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Attribute)
                and node.func.value.attr in {"_graph", "_agents"}
            ):
                seen.add(node.func.attr)
    assert seen == ALLOWED_AWAITED_ON_HANDLES


def test_only_the_presented_view_is_requested() -> None:
    for path in _modules():
        for node in ast.walk(_tree(path)):
            if isinstance(node, ast.keyword) and node.arg == "view":
                assert isinstance(node.value, ast.Constant)
                assert node.value.value == "presented"
            if isinstance(node, ast.Constant):
                assert node.value != "raw"


def test_run_through_read_only_proxies_writes_nothing(estate: Estate) -> None:
    graph, lister = ReadOnlyGraph(estate.graph), ReadOnlyLister(estate.repo)
    detector = DuplicateDetector(graph, lister)  # type: ignore[arg-type]
    before = snapshot(estate.repo)
    run = asyncio.run(
        detector.run(
            scope=make_scope(estate.domain_ids[:1]), window=estate.window, created_at=CREATED_AT
        )
    )
    assert run.agents_considered > 0
    assert graph.requests, "the job read through GraphQuery.neighbors"
    assert {r.view for r in graph.requests} == {"presented"}
    assert snapshot(estate.repo) == before
