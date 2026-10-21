"""One executor path (PRP-17 item 4): a repo-wide AST scan of product code.

* The only product code outside ``connectors/`` that calls a write connector's ``apply`` or
  ``rollback`` is the executor worker (``services/workers/neurosphere_workers/actions/``). The
  single named exception is the operator-approved live gate script, which exercises the
  connector itself and refuses without ``NS_LIVE_APPROVED=1``.
* No API module imports or touches a connector's apply path (``apply``/``rollback``/``verify``,
  ``ApplyResult``/``RollbackResult``, a concrete reference connector package).
* Both decision routes reach the one approval function, and only it applies an approval.
* The API never writes intents itself (only ``ActionService`` does).
* No action-plane module writes catalog metadata as an action outcome: none imports the
  catalog packages or calls a catalog write method.

Test code is out of scope (fakes call their own ``apply``); every scan has a negative control.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path
from typing import Final

REPO: Final = Path(__file__).resolve().parents[3]
PRODUCT_ROOTS: Final = ("packages", "services", "scripts")
SKIP_PARTS: Final = frozenset(
    {"tests", ".venv", "node_modules", "__pycache__", "frontend", "connectors"}
)
EXECUTOR: Final = "services/workers/neurosphere_workers/actions/"
#: path -> why it may call a connector's apply/rollback directly.
APPLY_EXCEPTIONS: Final = {
    "scripts/gates/g05_foundry_swap_live.py": (
        "operator-approved G05 live gate; exercises the connector itself and refuses without "
        "NS_LIVE_APPROVED=1; never reached from the API or the action plane"
    ),
}
WRITE_PATH: Final = frozenset({"apply", "rollback"})
API_FORBIDDEN_ATTRS: Final = WRITE_PATH | {"verify"}
API_FORBIDDEN_NAMES: Final = frozenset({"ApplyResult", "RollbackResult"})
API: Final = REPO / "services" / "api" / "neurosphere_api"
ACTION_API: Final = (API / "actions", API / "hitl")
CATALOG_MODULES: Final = ("neurosphere_core.catalog", "neurosphere_api.catalog")
CATALOG_WRITES: Final = frozenset(
    {
        "create_entity",
        "update_entity",
        "deprecate_entity",
        "put_alias",
        "put_edge",
        "record_observation",
        "put_override",
    }
)
ACTION_PLANE: Final = (
    REPO / "packages" / "core" / "neurosphere_core" / "actions",
    REPO / "packages" / "core" / "neurosphere_core" / "hitl",
    API / "actions",
    API / "hitl",
    REPO / "services" / "workers" / "neurosphere_workers" / "actions",
    REPO / "connectors" / "reference" / "foundry-actions" / "neurosphere_connector_foundry_actions",
)


def _rel(path: Path) -> str:
    return path.relative_to(REPO).as_posix()


def _product_files() -> Iterator[Path]:
    for root in PRODUCT_ROOTS:
        for path in sorted((REPO / root).rglob("*.py")):
            parts = set(path.relative_to(REPO).parts)
            if not parts & SKIP_PARTS:
                yield path


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _files(*dirs: Path) -> list[Path]:
    found: list[Path] = []
    for directory in dirs:
        if directory.is_dir():
            found.extend(
                p
                for p in sorted(directory.rglob("*.py"))
                if "tests" not in p.relative_to(REPO).parts
            )
    return found


def write_path_calls(tree: ast.AST) -> list[int]:
    """Lines calling ``x.apply(...)`` / ``x.rollback(...)`` or ``getattr(x, "apply")``."""
    lines: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in WRITE_PATH:
            lines.append(node.lineno)
        elif (
            isinstance(func, ast.Name)
            and func.id == "getattr"
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and node.args[1].value in WRITE_PATH
        ):
            lines.append(node.lineno)
    return lines


def api_apply_path_uses(tree: ast.AST, *, attrs: frozenset[str]) -> list[str]:
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in attrs:
            found.append(f"{node.lineno}:.{node.attr}")
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module.startswith("neurosphere_connector_"):
                found.append(f"{node.lineno}:import {node.module}")
            found.extend(
                f"{node.lineno}:import {a.name}"
                for a in node.names
                if a.name in API_FORBIDDEN_NAMES
            )
        elif isinstance(node, ast.Import):
            found.extend(
                f"{node.lineno}:import {a.name}"
                for a in node.names
                if a.name.startswith("neurosphere_connector_")
            )
        elif isinstance(node, ast.Name) and node.id in API_FORBIDDEN_NAMES:
            found.append(f"{node.lineno}:{node.id}")
    return found


def catalog_writes(tree: ast.AST) -> list[str]:
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module.startswith(CATALOG_MODULES):
                found.append(f"{node.lineno}:import {node.module}")
        elif isinstance(node, ast.Import):
            found.extend(
                f"{node.lineno}:import {a.name}"
                for a in node.names
                if a.name.startswith(CATALOG_MODULES)
            )
        elif isinstance(node, ast.Attribute) and node.attr in CATALOG_WRITES:
            found.append(f"{node.lineno}:.{node.attr}")
    return found


def calls_named(tree: ast.AST, name: str) -> list[int]:
    lines: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if (isinstance(func, ast.Attribute) and func.attr == name) or (
                isinstance(func, ast.Name) and func.id == name
            ):
                lines.append(node.lineno)
    return lines


def intent_store_writes(tree: ast.AST) -> list[int]:
    """Calls to ``<...intents|store|_store>.create/replace`` (only ActionService writes)."""
    lines: list[int] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if node.func.attr not in ("create", "replace"):
            continue
        owner = node.func.value
        label = owner.attr if isinstance(owner, ast.Attribute) else getattr(owner, "id", "")
        if "intent" in label or "store" in label:
            lines.append(node.lineno)
    return lines


# -- negative controls ---------------------------------------------------------------------------


def test_scanners_detect_what_they_forbid() -> None:
    sample = ast.parse(
        "from neurosphere_connector.write import ApplyResult\n"
        "from neurosphere_core.catalog.protocol import CatalogRepository\n"
        "async def f(c, repo, plane):\n"
        "    await c.apply(r)\n"
        "    await getattr(c, 'rollback')(a)\n"
        "    await repo.update_entity(s, e)\n"
        "    await plane.intents.replace(x, if_match='1')\n"
    )
    assert write_path_calls(sample) == [4, 5]
    assert any("ApplyResult" in hit for hit in api_apply_path_uses(sample, attrs=WRITE_PATH))
    assert len(catalog_writes(sample)) == 2
    assert intent_store_writes(sample) == [7]


# -- the rules -----------------------------------------------------------------------------------


def test_only_the_executor_calls_apply_or_rollback() -> None:
    files = list(_product_files())
    assert any(_rel(f).startswith("services/api/neurosphere_api/actions/") for f in files)
    offenders = {
        _rel(path): lines
        for path in files
        if (lines := write_path_calls(_tree(path)))
        and not _rel(path).startswith(EXECUTOR)
        and _rel(path) not in APPLY_EXCEPTIONS
    }
    assert not offenders, offenders
    for path, why in APPLY_EXCEPTIONS.items():
        assert (REPO / path).is_file(), f"stale exception {path}"
        assert len(why) > 40


def test_no_api_module_touches_the_connector_apply_path() -> None:
    files = _files(API)
    assert files
    offenders: dict[str, list[str]] = {}
    for path in files:
        action_api = any(path.is_relative_to(d) for d in ACTION_API)
        hits = api_apply_path_uses(
            _tree(path), attrs=API_FORBIDDEN_ATTRS if action_api else WRITE_PATH
        )
        if hits:
            offenders[_rel(path)] = hits
    assert not offenders, offenders


def test_both_decision_routes_share_the_one_approval_function() -> None:
    approval = API / "actions" / "approval.py"
    assert calls_named(_tree(approval), "apply_approval")
    for path in _files(API):
        if path != approval:
            assert not calls_named(_tree(path), "apply_approval"), _rel(path)
    for caller in (API / "actions" / "service.py", API / "hitl" / "service.py"):
        assert calls_named(_tree(caller), "decide_maker_checker"), _rel(caller)


def test_api_never_writes_intents_directly() -> None:
    offenders = {
        _rel(path): lines
        for path in _files(*ACTION_API)
        if (lines := intent_store_writes(_tree(path)))
    }
    assert not offenders, offenders


def test_no_action_plane_module_writes_catalog_metadata() -> None:
    files = _files(*ACTION_PLANE)
    assert len(files) > 10
    offenders = {_rel(path): hits for path in files if (hits := catalog_writes(_tree(path)))}
    assert not offenders, offenders
