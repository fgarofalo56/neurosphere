"""PRP-104 criterion 8 (GD-3): captured content never reaches the copilot or MCP.

Two structural checks, no model involved:

* the static import graph (AST, transitive, first-party only; see ``_imports``) of every module
  of ``neurosphere_api.copilot``, ``neurosphere_core.copilot`` and ``neurosphere_api.mcp`` never
  reaches the content reader, the export or the interaction store, and no reachable module names
  ``InteractionContentReader``, calls ``read_content`` or reads the explorer off ``app.state``;
* the copilot tool registry and the MCP server's tool registry, built as production builds them,
  register no tool whose name, arguments or handler touch interaction content.

The composition root is the one barrier: ``neurosphere_api.routers`` (router registry),
``neurosphere_api.runtime`` / ``neurosphere_api.runtime.builders`` (builder registry),
``neurosphere_api.app`` and ``neurosphere_api.main`` import every feature in order to REGISTER
it, which is not a data path; copilot and MCP code imports them only for the registry types and
shared keys. They are recorded, not expanded. A submodule imported directly (for example
``neurosphere_api.runtime.builders.interaction_explorer``) is still expanded and caught.
"""

from __future__ import annotations

import ast
import inspect
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any, Final

import pytest
from fastapi import FastAPI
from neurosphere_api.interactions import InteractionContentReader, InteractionExplorer
from neurosphere_api.interactions.service import STATE_ATTRIBUTE
from neurosphere_api.mcp.server.tools import StatePorts, build_mcp_registry
from neurosphere_core.copilot.tools import ToolRegistry, ToolSpec
from neurosphere_core.copilot.tools.copilot_registry import (
    COPILOT_TOOL_NAMES,
    CopilotToolDependencies,
    build_copilot_registry,
)
from neurosphere_core.interactions import EncryptedInteractionStore

from . import _imports as im

ROOT_PACKAGES: Final = (
    "neurosphere_api.copilot",
    "neurosphere_core.copilot",
    "neurosphere_api.mcp",
)
COMPOSITION_ROOT: Final = (
    "neurosphere_api.routers",
    "neurosphere_api.runtime",
    "neurosphere_api.runtime.builders",
    "neurosphere_api.app",
    "neurosphere_api.main",
)
#: Modules (and everything under them) a copilot or MCP path must never reach.
FORBIDDEN_MODULES: Final = (
    "neurosphere_api.interactions",
    "neurosphere_api.runtime.builders.interaction_explorer",
    "neurosphere_api.runtime.builders.interactions",
    "neurosphere_core.interactions.store",
    "neurosphere_core.interactions.blob_content",
)
#: Names whose mere mention in a reachable module is a content path.
FORBIDDEN_NAMES: Final = frozenset(
    {
        "InteractionContentReader",
        "InteractionExplorer",
        "InteractionExportStorage",
        "InteractionStore",
        "EncryptedInteractionStore",
        "InMemoryInteractionStore",
        "decrypt_stored",
        "configure_interaction_explorer",
    }
)
FORBIDDEN_ATTRIBUTES: Final = frozenset({"read_content", "read_many", STATE_ATTRIBUTE})


def _roots() -> list[str]:
    names: list[str] = []
    for package in ROOT_PACKAGES:
        names.extend(im.package_modules(package))
    return names


@pytest.fixture(scope="module")
def reach() -> im.Closure:
    return im.closure(_roots(), barriers=COMPOSITION_ROOT)


def test_the_roots_are_real_packages_with_modules() -> None:
    for package in ROOT_PACKAGES:
        modules = im.package_modules(package)
        assert len(modules) > 1, package
        assert all(im.parse(m) is not None for m in modules)


def test_the_walker_sees_through_nested_relative_and_parent_imports() -> None:
    """Self-check: the walker resolves the import shapes the guard relies on."""
    # The replay router reaches the content reader (absolute import of a submodule).
    replay = im.closure(["neurosphere_api.replay.router"])
    assert "neurosphere_api.interactions.content" in replay.reached
    # ``from neurosphere_api.interactions.service import ...`` also runs the package __init__,
    # which re-exports the reader: the parent package edge is followed.
    via_parent = im.closure(["neurosphere_api.interactions.service"])
    assert "neurosphere_api.interactions" in via_parent.reached
    assert "neurosphere_api.interactions.content" in via_parent.reached
    # Without the barrier, the router registry would drag every feature in.
    unbounded = im.closure(["neurosphere_api.copilot.router"])
    assert "neurosphere_api.interactions.content" in unbounded.reached


def test_copilot_and_mcp_never_import_the_content_path(reach: im.Closure) -> None:
    hits = sorted(n for n in reach.reached if im.is_under(n, FORBIDDEN_MODULES))
    assert hits == [], "\n".join(reach.path_to(n) for n in hits)
    # The composition root is reached only as an unexpanded registry import.
    assert {n for n in reach.reached if n in COMPOSITION_ROOT} <= set(COMPOSITION_ROOT)


def _mentions(tree: ast.Module) -> Iterator[tuple[int, str]]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            yield node.lineno, node.id
        elif isinstance(node, ast.Attribute) and (
            node.attr in FORBIDDEN_NAMES or node.attr in FORBIDDEN_ATTRIBUTES
        ):
            yield node.lineno, node.attr
        elif isinstance(node, ast.alias) and node.name.rsplit(".", 1)[-1] in FORBIDDEN_NAMES:
            yield getattr(node, "lineno", 0), node.name
        elif isinstance(node, ast.Constant) and node.value in FORBIDDEN_ATTRIBUTES:
            yield node.lineno, str(node.value)


def test_no_reachable_module_names_the_reader_or_calls_read_content(reach: im.Closure) -> None:
    found: list[str] = []
    for name in sorted(reach.reached):
        if name in COMPOSITION_ROOT:
            continue
        tree = im.parse(name)
        assert tree is not None, name
        found.extend(f"{name}:{line} {what}" for line, what in _mentions(tree))
    assert found == []


def test_the_scan_would_see_a_content_call() -> None:
    """Self-check: the name scan flags the shapes a regression would take."""
    sample = ast.parse(
        "from neurosphere_api.interactions import InteractionContentReader\n"
        "async def f(app, store):\n"
        "    getattr(app.state, 'interaction_explorer')\n"
        "    return await store.read_content('c', 'd', 'i')\n"
    )
    whats = {what for _line, what in _mentions(sample)}
    assert {"InteractionContentReader", "interaction_explorer", "read_content"} <= whats


# --- tool lists -----------------------------------------------------------------------------------


class _Port:
    """Stands in for any port: composing a registry never calls it."""


_CONTENT_WORDS: Final = ("interaction", "content", "payload", "capture", "transcript", "purpose")
_CONTENT_TYPES: Final = (InteractionContentReader, InteractionExplorer, EncryptedInteractionStore)


def _copilot_registry() -> ToolRegistry:
    anything: Any = _Port()
    return build_copilot_registry(
        CopilotToolDependencies(
            catalog=anything,
            metrics=anything,
            recommendations=anything,
            evidence=anything,
            drafter=anything,
            graph=anything,
            access=anything,
            changes=anything,
            matcher=anything,
        )
    )


def _mcp_registry() -> ToolRegistry:
    return build_mcp_registry(
        StatePorts(FastAPI()), correlation_id="manifest", clock=lambda: datetime.now(UTC)
    )


def _captured(handler: Any, depth: int = 0) -> Iterator[Any]:
    """Objects a handler closes over (functions followed; apps and ports are not walked)."""
    if depth > 4:
        return
    func = getattr(handler, "__func__", handler)
    for cell in getattr(func, "__closure__", None) or ():
        try:
            value = cell.cell_contents
        except ValueError:  # an empty cell
            continue
        yield value
        if inspect.isfunction(value) or inspect.ismethod(value):
            yield from _captured(value, depth + 1)


def _assert_no_content_tool(spec: ToolSpec) -> None:
    lowered = (spec.name + " " + spec.description).lower()
    assert not any(word in spec.name.lower() for word in _CONTENT_WORDS), spec.name
    assert "interaction content" not in lowered, spec.name
    module = getattr(spec.handler, "__module__", "") or ""
    assert not im.is_under(module, FORBIDDEN_MODULES), (spec.name, module)
    schema = spec.args_model.model_json_schema()
    assert "purpose_code" not in str(schema), spec.name
    assert "interaction_id" not in str(schema), spec.name
    for value in _captured(spec.handler):
        assert not isinstance(value, _CONTENT_TYPES), (spec.name, type(value).__name__)
        value_module = getattr(type(value), "__module__", "") or ""
        assert not im.is_under(value_module, FORBIDDEN_MODULES), (spec.name, value_module)


def test_copilot_tool_list_has_no_content_tool() -> None:
    registry = _copilot_registry()
    assert set(registry.names) == set(COPILOT_TOOL_NAMES)  # all ports bound: the full list
    for spec in registry.manifest():
        _assert_no_content_tool(spec)


def test_mcp_tool_list_has_no_content_tool() -> None:
    registry = _mcp_registry()
    assert len(registry.names) >= 1
    for spec in registry.manifest():
        _assert_no_content_tool(spec)
