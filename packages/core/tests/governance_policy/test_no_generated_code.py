"""No code path in the governance package compiles, evaluates or templates rule text, and no
query is built from strings (PRP-105 acceptance criterion 1, static check).

Scans every module under ``neurosphere_core/governance`` (including the rule evaluators and
plugins later items add) with the AST, so a comment or docstring cannot trip it but a real call
can. A self-test plants each forbidden construct in a synthetic module and asserts the scanner
reports it, so the check cannot pass vacuously.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import neurosphere_core.governance as governance_pkg
import pytest

PACKAGE = Path(governance_pkg.__file__).resolve().parent
#: The one module allowed to hold query text (fixed clause constants, parameters only).
QUERY_MODULE = PACKAGE / "policy" / "cosmos_store.py"

_FORBIDDEN_CALLS = frozenset({"eval", "exec", "compile", "__import__"})
_FORBIDDEN_ATTR_CALLS = frozenset({"format", "format_map", "safe_substitute", "substitute"})
_FORBIDDEN_MODULES = ("jinja", "jinja2", "mako", "string", "code", "codeop")
#: Upper-case query keywords (SQL and Cypher); prose such as "where" is not query text.
_QUERY_WORDS = re.compile(
    r"\b(SELECT|WHERE|ORDER\s+BY|FROM\s+c\b|MATCH\s*\(|RETURN\s|INSERT|UPDATE\s|DELETE\s)"
)


def _is_query_text(value: object) -> bool:
    return isinstance(value, str) and _QUERY_WORDS.search(value) is not None


def scan(source: str, *, query_module: bool = False) -> list[str]:
    """Findings for one module's source (``query_module`` = the module allowed SQL constants)."""
    findings: list[str] = []
    if "jinja" in source.lower():
        findings.append("mentions jinja")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in _FORBIDDEN_CALLS:
                findings.append(f"calls {func.id}()")
            if isinstance(func, ast.Attribute):
                if func.attr in _FORBIDDEN_CALLS and not (
                    isinstance(func.value, ast.Name) and func.value.id == "re"
                ):
                    findings.append(f"calls .{func.attr}()")
                if func.attr in _FORBIDDEN_ATTR_CALLS:
                    findings.append(f"calls .{func.attr}() (string templating)")
                if func.attr == "query_items" and not any(
                    k.arg == "parameters" for k in node.keywords
                ):
                    findings.append("query_items without parameters")
            if (
                isinstance(func, ast.Name)
                and func.id == "getattr"
                and node.args
                and isinstance(node.args[0], ast.Name)
                and node.args[0].id == "builtins"
            ):
                findings.append("getattr(builtins, ...)")
            if isinstance(func, ast.Name) and func.id == "Template":
                findings.append("Template()")
        elif isinstance(node, ast.Import | ast.ImportFrom):
            names = (
                [a.name for a in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
            )
            for name in names:
                if name.split(".")[0] in _FORBIDDEN_MODULES:
                    findings.append(f"imports {name}")
        elif isinstance(node, ast.JoinedStr):
            text = "".join(
                str(part.value) for part in node.values if isinstance(part, ast.Constant)
            )
            if _is_query_text(text):
                findings.append("f-string builds query text")
        elif (
            isinstance(node, ast.BinOp)
            and isinstance(node.op, ast.Mod)
            and isinstance(node.left, ast.Constant)
            and isinstance(node.left.value, str)
        ):
            findings.append("%-formats a string")
        elif isinstance(node, ast.Constant) and _is_query_text(node.value) and not query_module:
            findings.append("query text outside the query module")
    if query_module:
        findings.extend(_query_module_findings(tree))
    return findings


def _query_module_findings(tree: ast.Module) -> list[str]:
    """In the query module, query text may live only in module-level constants (docstrings are
    stripped before scanning)."""
    allowed: set[int] = set()
    for stmt in tree.body:
        if isinstance(stmt, ast.AnnAssign | ast.Assign):
            allowed.update(id(sub) for sub in ast.walk(stmt) if isinstance(sub, ast.Constant))
    return [
        "query text inside a function body"
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and _is_query_text(node.value) and id(node) not in allowed
    ]


def _modules() -> list[Path]:
    return sorted(PACKAGE.rglob("*.py"))


def test_the_package_is_scanned() -> None:
    names = {p.name for p in _modules()}
    assert {"models.py", "validation.py", "store.py", "cosmos_store.py"} <= names


@pytest.mark.parametrize("path", _modules(), ids=lambda p: p.relative_to(PACKAGE).as_posix())
def test_no_eval_exec_compile_templating_or_query_building(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    findings = scan(_without_docstrings(source), query_module=path == QUERY_MODULE)
    assert findings == [], f"{path.relative_to(PACKAGE).as_posix()}: {findings}"


def _without_docstrings(source: str) -> str:
    """Drop module/class/function docstrings so prose about SQL is not mistaken for SQL."""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
            and node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        ):
            node.body[0] = ast.Pass()
    return ast.unparse(tree)


@pytest.mark.parametrize(
    ("planted", "expected"),
    [
        ("x = eval(rule_text)", "calls eval()"),
        ("x = exec(rule_text)", "calls exec()"),
        ("x = compile(rule_text, 'r', 'eval')", "calls compile()"),
        ("import builtins\nx = builtins.eval(t)", "calls .eval()"),
        ("x = getattr(builtins, name)(t)", "getattr(builtins, ...)"),
        ("import jinja2", "mentions jinja"),
        ("from string import Template", "imports string"),
        ("x = '{0} AND {1}'.format(a, b)", "calls .format() (string templating)"),
        ("x = 'id = %s' % value", "%-formats a string"),
        ("x = f'SELECT * FROM c WHERE c.id = {value}'", "f-string builds query text"),
        ("x = 'SELECT * FROM c'", "query text outside the query module"),
        ("c.query_items('q')", "query_items without parameters"),
    ],
)
def test_the_scanner_catches_each_planted_construct(planted: str, expected: str) -> None:
    assert expected in scan(planted)


def test_re_compile_is_not_a_finding() -> None:
    assert scan("import re\nPATTERN = re.compile('^a$')") == []


def test_query_text_in_a_function_body_of_the_query_module_is_a_finding() -> None:
    planted = "def q(c):\n    return c.query_items('SELECT * FROM c', parameters=[])\n"
    assert "query text inside a function body" in scan(planted, query_module=True)
    constant = "SQL = 'SELECT * FROM c'\ndef q(c):\n    return c.query_items(SQL, parameters=[])\n"
    assert scan(constant, query_module=True) == []
