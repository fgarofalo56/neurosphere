"""Static import graph of the repo's own packages (PRP-104 item 7; no tests in this module).

The graph is built from the AST of the source files, never by importing them, so a module that
is only reachable through a lazy or conditional import still counts. Importing ``a.b.c`` also runs
``a/__init__.py`` and ``a/b/__init__.py``, so each package ``__init__`` on the way is an edge too.
Only first-party modules (``neurosphere_*``) are followed.
"""

from __future__ import annotations

import ast
import importlib.util
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Final

FIRST_PARTY: Final = ("neurosphere_api", "neurosphere_core", "neurosphere_contracts")


@cache
def _root(top: str) -> Path | None:
    """The directory holding the top-level package ``top`` (its ``__init__`` is not executed)."""
    spec = importlib.util.find_spec(top)
    if spec is None or not spec.submodule_search_locations:
        return None
    return Path(next(iter(spec.submodule_search_locations))).resolve().parent


def module_file(name: str) -> Path | None:
    """The source file of first-party module ``name``, else None (third-party or absent)."""
    top = name.split(".", 1)[0]
    if top not in FIRST_PARTY:
        return None
    root = _root(top)
    if root is None:
        return None
    base = root.joinpath(*name.split("."))
    for candidate in (base / "__init__.py", base.with_suffix(".py")):
        if candidate.is_file():
            return candidate
    return None


def _is_package(name: str) -> bool:
    path = module_file(name)
    return path is not None and path.name == "__init__.py"


def _parents(name: str) -> Iterator[str]:
    parts = name.split(".")
    for i in range(1, len(parts)):
        yield ".".join(parts[:i])


@cache
def parse(name: str) -> ast.Module | None:
    path = module_file(name)
    if path is None:
        return None
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _resolve_relative(name: str, level: int, module: str | None) -> str:
    package = name if _is_package(name) else name.rpartition(".")[0]
    parts = package.split(".")
    if level > 1:
        parts = parts[: len(parts) - (level - 1)]
    base = ".".join(parts)
    return f"{base}.{module}" if module else base


def imports_of(name: str) -> set[str]:
    """First-party modules ``name`` imports anywhere in its source (top level or nested)."""
    tree = parse(name)
    if tree is None:
        return set()
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                out.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            target = (
                _resolve_relative(name, node.level, node.module)
                if node.level
                else node.module or ""
            )
            out.add(target)
            for alias in node.names:
                # ``from pkg import sub`` imports the submodule when one exists.
                sub = f"{target}.{alias.name}"
                if module_file(sub) is not None:
                    out.add(sub)
    resolved: set[str] = set()
    for target in out:
        if module_file(target) is None:
            continue
        resolved.add(target)
        resolved.update(p for p in _parents(target) if module_file(p) is not None)
    resolved.discard(name)
    return resolved


def package_modules(package: str) -> list[str]:
    """Every module of first-party package ``package`` (from its source tree)."""
    init = module_file(package)
    assert init is not None and init.name == "__init__.py", package
    root = init.parent
    names: list[str] = []
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root).with_suffix("")
        parts = [p for p in rel.parts if p != "__init__"]
        names.append(".".join([package, *parts]))
    return names


@dataclass
class Closure:
    """Every module reachable from the roots, with one import path to each (for messages)."""

    reached: dict[str, tuple[str, ...]] = field(default_factory=dict[str, tuple[str, ...]])

    def path_to(self, name: str) -> str:
        return " -> ".join(self.reached[name])


def is_under(name: str, prefixes: Iterable[str]) -> bool:
    return any(name == p or name.startswith(p + ".") for p in prefixes)


def closure(roots: Iterable[str], *, barriers: Iterable[str] = ()) -> Closure:
    """Breadth-first closure; a module named EXACTLY in ``barriers`` is recorded, not expanded.

    Exact names only: a submodule of a barrier package that is imported directly is still
    expanded (importing it records the barrier parent, which stays unexpanded).
    """
    stop = frozenset(barriers)
    result = Closure()
    queue: list[tuple[str, tuple[str, ...]]] = []
    for root in sorted(set(roots)):
        for start in [*_parents(root), root]:
            if module_file(start) is not None and start not in result.reached:
                result.reached[start] = (start,)
                queue.append((start, (start,)))
    while queue:
        name, path = queue.pop(0)
        if name in stop:
            continue
        for target in sorted(imports_of(name)):
            if target not in result.reached:
                result.reached[target] = (*path, target)
                queue.append((target, (*path, target)))
    return result
