"""No generated code in the governance API, its builder or the ``policy_eval`` worker (PRP-105
item 7, acceptance criterion 1).

``packages/core/tests/governance_policy/test_no_generated_code.py`` scans the engine package;
this extends the same AST check to the code around it, which the core test does not reach:
``services/api/neurosphere_api/governance/**``, ``runtime/builders/governance.py`` and
``services/workers/neurosphere_workers/policy_eval/**``. Nothing there may call ``eval``,
``exec``, ``compile`` or ``__import__``, template strings (``str.format``, ``%``, ``Template``,
jinja/mako) or build query text (SQL or Cypher keywords in a string or f-string). A planted
self-test keeps the scanner from passing vacuously. (Log calls pass ``%s`` arguments to the
logger, which is not ``%``-formatting and is not flagged.)
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Final

import pytest

REPO: Final = Path(__file__).resolve().parents[3]
SCANNED: Final = (
    "services/api/neurosphere_api/governance",
    "services/api/neurosphere_api/runtime/builders/governance.py",
    "services/workers/neurosphere_workers/policy_eval",
)
_CALLS: Final = frozenset({"eval", "exec", "compile", "__import__"})
_TEMPLATING: Final = frozenset({"format", "format_map", "substitute", "safe_substitute"})
_MODULES: Final = ("jinja", "jinja2", "mako", "string", "code", "codeop")
_QUERY: Final = re.compile(
    r"\b(SELECT|WHERE|ORDER\s+BY|FROM\s+c\b|MATCH\s*\(|RETURN\s|INSERT|UPDATE\s|DELETE\s)"
)


def _without_docstrings(tree: ast.Module) -> ast.Module:
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
            and node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        ):
            node.body[0] = ast.Pass()
    return tree


def _call_findings(node: ast.Call) -> list[str]:
    func = node.func
    out: list[str] = []
    if isinstance(func, ast.Name):
        if func.id in _CALLS:
            out.append(f"calls {func.id}()")
        if func.id == "Template":
            out.append("Template()")
        if func.id == "getattr" and node.args and isinstance(node.args[0], ast.Name):
            if node.args[0].id == "builtins":
                out.append("getattr(builtins, ...)")
    elif isinstance(func, ast.Attribute):
        receiver = func.value.id if isinstance(func.value, ast.Name) else ""
        if func.attr in _CALLS and receiver != "re":
            out.append(f"calls .{func.attr}()")
        if func.attr in _TEMPLATING:
            out.append(f"calls .{func.attr}() (string templating)")
    return out


def scan(source: str) -> list[str]:
    findings: list[str] = []
    if "jinja" in source.lower():
        findings.append("mentions jinja")
    for node in ast.walk(_without_docstrings(ast.parse(source))):
        if isinstance(node, ast.Call):
            findings.extend(_call_findings(node))
        elif isinstance(node, ast.Import):
            findings.extend(
                f"imports {a.name}" for a in node.names if a.name.split(".")[0] in _MODULES
            )
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module.split(".")[0] in _MODULES:
                findings.append(f"imports {module}")
        elif isinstance(node, ast.JoinedStr):
            text = "".join(str(p.value) for p in node.values if isinstance(p, ast.Constant))
            if _QUERY.search(text):
                findings.append("f-string builds query text")
        elif (
            isinstance(node, ast.BinOp)
            and isinstance(node.op, ast.Mod)
            and isinstance(node.left, ast.Constant)
            and isinstance(node.left.value, str)
        ):
            findings.append("%-formats a string")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if _QUERY.search(node.value):
                findings.append("query text")
    return findings


def _modules() -> list[Path]:
    out: list[Path] = []
    for entry in SCANNED:
        path = REPO / entry
        out.extend(sorted(path.rglob("*.py")) if path.is_dir() else [path])
    return out


def test_the_api_builder_and_worker_are_scanned() -> None:
    names = {p.name for p in _modules()}
    assert {"router.py", "service.py", "deps.py", "governance.py", "worker.py"} <= names


@pytest.mark.parametrize("path", _modules(), ids=lambda p: p.relative_to(REPO).as_posix())
def test_no_eval_exec_compile_templating_or_query_building(path: Path) -> None:
    findings = scan(path.read_text(encoding="utf-8"))
    assert findings == [], f"{path.relative_to(REPO).as_posix()}: {findings}"


@pytest.mark.parametrize(
    ("planted", "expected"),
    [
        ("x = eval(rule_text)", "calls eval()"),
        ("x = exec(rule_text)", "calls exec()"),
        ("x = compile(rule_text, 'r', 'eval')", "calls compile()"),
        ("import builtins\nx = builtins.exec(t)", "calls .exec()"),
        ("x = getattr(builtins, name)(t)", "getattr(builtins, ...)"),
        ("import jinja2", "mentions jinja"),
        ("from string import Template", "imports string"),
        ("x = '{0} AND {1}'.format(a, b)", "calls .format() (string templating)"),
        ("x = 'id = %s' % value", "%-formats a string"),
        ("x = f'SELECT * FROM c WHERE c.id = {value}'", "f-string builds query text"),
        ("x = 'MATCH (a)-[r]->(b) RETURN a'", "query text"),
    ],
)
def test_the_scanner_catches_each_planted_construct(planted: str, expected: str) -> None:
    assert expected in scan(planted)


def test_re_compile_logging_args_and_docstrings_are_not_findings() -> None:
    source = (
        '"""SELECT nothing: prose."""\n'
        "import logging\n"
        "import re\n"
        "PATTERN = re.compile('^a$')\n"
        "logging.getLogger(__name__).info('policy %s', 'x')\n"
    )
    assert scan(source) == []
