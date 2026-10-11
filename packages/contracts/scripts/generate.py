"""Generate Pydantic v2 and TypeScript bindings from the NeuroSphere JSON Schema contracts.

JSON Schema 2020-12 under ``packages/contracts/schemas/<area>/v<major>/*.schema.json`` is the
source of truth (PRP-01 Clarification 2). This script regenerates:

* ``packages/contracts/python/neurosphere_contracts/`` with datamodel-code-generator, and
* ``packages/contracts/ts/src/`` with json-schema-to-typescript,

using the exact generator versions pinned below (and in the member ``pyproject.toml`` /
``package.json`` plus the lockfiles; ``test_generate.py`` keeps them in step).

Output is byte-deterministic: inputs are sorted, headers are fixed text with no timestamp or
generator command line, line endings are LF, and the Python tree is formatted by the workspace
ruff. No network is used: schemas are staged into a temporary directory, every ``$ref`` is a
relative file reference, and both generators run with remote resolution disabled.

Usage::

    python packages/contracts/scripts/generate.py           # rewrite the committed bindings
    python packages/contracts/scripts/generate.py --check   # drift check, exits 1 on any diff

Exit codes: 0 success / no drift, 1 drift or generation failure, 2 toolchain missing.
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
CONTRACTS_DIR = SCRIPT_DIR.parent
REPO_ROOT = CONTRACTS_DIR.parents[1]
SCHEMA_ROOT = CONTRACTS_DIR / "schemas"
PY_PROJECT_DIR = CONTRACTS_DIR / "python"
PY_PACKAGE = "neurosphere_contracts"
PY_OUT = PY_PROJECT_DIR / PY_PACKAGE
TS_PROJECT_DIR = CONTRACTS_DIR / "ts"
TS_OUT = TS_PROJECT_DIR / "src"
TS_DRIVER = SCRIPT_DIR / "json2ts.cjs"
RUFF_CONFIG = PY_PROJECT_DIR / "pyproject.toml"

# Generator pins (ADR-0004). Changing one is a deliberate, reviewed regeneration.
DATAMODEL_CODE_GENERATOR_VERSION = "0.83.0"
JSON_SCHEMA_TO_TYPESCRIPT_VERSION = "16.0.0"

MAJOR_DIR = re.compile(r"v[1-9][0-9]*")
SCHEMA_SUFFIX = ".schema.json"

HEADER_LINES = (
    "GENERATED - do not edit.",
    "Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).",
    "Regenerate: python packages/contracts/scripts/generate.py",
    "Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).",
)
# datamodel-code-generator 0.83 emits two patterns pyright (standard) rejects although Pydantic
# accepts them at runtime: `constr(...)` as a dict-key type for patternProperties, and literal
# defaults such as `= "unknown"` / `= None` on RootModel-typed fields (validated through
# `validate_default=True`). The suppression is scoped to generated files and these two rules;
# the examples smoke test and tests/contracts (item 7) exercise the runtime behaviour.
PY_PYRIGHT_DIRECTIVE = "# pyright: reportAssignmentType=false, reportInvalidTypeForm=false"
PY_HEADER = "\n".join(f"# {line}" for line in HEADER_LINES) + "\n" + PY_PYRIGHT_DIRECTIVE
TS_HEADER = "/*\n" + "\n".join(f" * {line}" for line in HEADER_LINES) + "\n */"

DATAMODEL_CODEGEN_ARGS: tuple[str, ...] = (
    "--input-file-type",
    "jsonschema",
    "--schema-version",
    "2020-12",
    "--output-model-type",
    "pydantic_v2.BaseModel",
    "--target-python-version",
    "3.12",
    "--no-allow-remote-refs",
    "--disable-timestamp",
    "--extra-fields",
    "forbid",
    "--use-annotated",
    "--field-constraints",
    "--use-standard-collections",
    "--use-union-operator",
    "--use-double-quotes",
    "--enum-field-as-literal",
    "all",
    "--use-schema-description",
    "--use-field-description",
    "--use-title-as-name",
    # Timestamps and dates stay wire-exact strings: the schemas pair format with a pattern
    # (UTC `Z` only), Pydantic cannot apply `pattern` to datetime/date, and re-serialising a
    # datetime would change the bytes that confirmation_hash canonicalisation covers.
    "--type-mappings",
    "date-time=string",
    "date=string",
    # JSON Schema never coerces ("5" is not an integer); Pydantic lax mode would.
    "--strict-types",
    "str",
    "int",
    "float",
    "bool",
    "--formatters",
    "builtin",
    "--disable-warnings",
)


class ToolchainError(RuntimeError):
    """A generator or formatter is missing or at the wrong version."""


def discover_schemas(schema_root: Path = SCHEMA_ROOT) -> list[str]:
    """Return sorted POSIX paths ``<area>/v<major>/<name>.schema.json`` relative to the root.

    Only files directly inside a ``v<major>`` directory are schemas. ``examples/`` folders and
    data files (``transitions.json``, ``error-codes.json``, ``id-corpus.json``,
    ``confirmation-hash.json``) are excluded because they do not end in ``.schema.json`` or
    sit one level deeper.
    """
    found: list[str] = []
    for path in schema_root.glob(f"*/*/*{SCHEMA_SUFFIX}"):
        if MAJOR_DIR.fullmatch(path.parent.name) is None:
            continue
        found.append(path.relative_to(schema_root).as_posix())
    if not found:
        raise SystemExit(f"no *{SCHEMA_SUFFIX} files found under {schema_root}")
    return sorted(found)


def _run(cmd: Sequence[str], *, stdin: str | None = None, cwd: Path = REPO_ROOT) -> str:
    """Run a fixed argv (never a shell string) and return stdout; raise on failure."""
    try:
        proc = subprocess.run(  # noqa: S603 - fixed argv built in this file, no shell
            list(cmd),
            cwd=cwd,
            input=stdin,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
    except FileNotFoundError as exc:
        raise ToolchainError(f"cannot start {cmd[0]!r}: {exc}") from exc
    if proc.returncode != 0:
        raise RuntimeError(
            f"command failed ({proc.returncode}): {' '.join(cmd)}\n{proc.stdout}\n{proc.stderr}"
        )
    return proc.stdout


def _uv() -> str:
    uv = shutil.which("uv")
    if uv is None:
        raise ToolchainError("uv is not on PATH; install uv (ADR-0002) and run uv sync")
    return uv


def _datamodel_codegen_cmd() -> list[str]:
    return [
        _uv(),
        "run",
        "--frozen",
        "--package",
        "neurosphere-contracts",
        "--group",
        "dev",
        "datamodel-codegen",
    ]


def _ruff_cmd() -> list[str]:
    return [_uv(), "run", "--frozen", "--group", "dev", "ruff"]


def check_toolchain() -> None:
    """Fail unless the installed generators match the pins exactly.

    The Node side is checked first: it only reads files, whereas ``uv run`` may install the
    locked Python generator into the environment.
    """
    if shutil.which("node") is None:
        raise ToolchainError("node is not on PATH; Node 24 is required (ADR-0002)")
    jstt_pkg = TS_PROJECT_DIR / "node_modules" / "json-schema-to-typescript" / "package.json"
    if not jstt_pkg.is_file():
        raise ToolchainError(
            "json-schema-to-typescript is not installed; run pnpm install --frozen-lockfile"
        )
    jstt_version = json.loads(jstt_pkg.read_text(encoding="utf-8"))["version"]
    if jstt_version != JSON_SCHEMA_TO_TYPESCRIPT_VERSION:
        raise ToolchainError(
            f"json-schema-to-typescript {jstt_version} installed, "
            f"{JSON_SCHEMA_TO_TYPESCRIPT_VERSION} pinned"
        )
    try:
        out = _run([*_datamodel_codegen_cmd(), "--version"]).strip()
    except RuntimeError as exc:
        raise ToolchainError(f"datamodel-codegen is not runnable: {exc}") from exc
    installed = out.split()[-1] if out else ""
    if installed != DATAMODEL_CODE_GENERATOR_VERSION:
        raise ToolchainError(
            f"datamodel-code-generator {installed or '?'} installed, "
            f"{DATAMODEL_CODE_GENERATOR_VERSION} pinned"
        )


def staged_name(rel: str) -> str:
    """``telemetry/v1/telemetry-event.schema.json`` -> ``telemetry/v1/telemetry-event.json``.

    Dropping the ``.schema`` infix gives clean module names (``telemetry_event.py``,
    ``telemetry-event.ts``) instead of ``telemetry_event_schema``.
    """
    return rel.removesuffix(SCHEMA_SUFFIX) + ".json"


def _rewrite_refs(node: object) -> object:
    if isinstance(node, dict):
        out: dict[str, object] = {}
        for key, value in node.items():
            if key == "$ref" and isinstance(value, str):
                target, sep, fragment = value.partition("#")
                if "://" in target:
                    raise RuntimeError(f"remote $ref is not allowed (PRP-01): {value}")
                if target.endswith(SCHEMA_SUFFIX):
                    target = target.removesuffix(SCHEMA_SUFFIX) + ".json"
                out[key] = f"{target}{sep}{fragment}"
            else:
                out[key] = _rewrite_refs(value)
        return out
    if isinstance(node, list):
        return [_rewrite_refs(item) for item in node]
    return node


CONDITIONAL_KEYWORDS = frozenset({"if", "then", "else", "not"})
ANNOTATION_KEYWORDS = frozenset({"description", "$comment", "title", "examples"})


def _is_annotation_only(node: object) -> bool:
    return isinstance(node, dict) and set(node) <= ANNOTATION_KEYWORDS


NAME_MAP_KEYWORDS = frozenset({"properties", "$defs", "patternProperties", "dependentSchemas"})
DATA_KEYWORDS = frozenset({"const", "enum", "default", "examples"})


def _strip_conditionals(node: object) -> object:
    """Remove conditional keywords from schema objects (never from property names or data)."""
    if isinstance(node, list):
        return [_strip_conditionals(item) for item in node]
    if not isinstance(node, dict):
        return node
    out: dict[str, object] = {}
    for key, value in node.items():
        if key in CONDITIONAL_KEYWORDS:
            continue
        if key in DATA_KEYWORDS:
            out[key] = value
        elif key in NAME_MAP_KEYWORDS and isinstance(value, dict):
            out[key] = {name: _strip_conditionals(sub) for name, sub in value.items()}
        else:
            out[key] = _strip_conditionals(value)
    return out


def _drop_constraint_only_all_of(node: object, empty_defs: frozenset[str]) -> object:
    if isinstance(node, list):
        return [_drop_constraint_only_all_of(item, empty_defs) for item in node]
    if not isinstance(node, dict):
        return node
    out: dict[str, object] = {}
    for key, value in node.items():
        if key == "allOf" and isinstance(value, list):
            kept = [
                _drop_constraint_only_all_of(item, empty_defs)
                for item in value
                if isinstance(item, dict)
                and ("type" in item or "$ref" in item)
                and item.get("$ref") not in empty_defs
            ]
            if kept:
                out[key] = kept
        else:
            out[key] = _drop_constraint_only_all_of(value, empty_defs)
    return out


def shape_projection(document: dict[str, object]) -> dict[str, object]:
    """Return the shape-only view of a schema that both generators are given.

    Neither generator implements JSON Schema conditionals, and both mistranslate them when
    they are present (ADR-0004, "generator disagreement"):

    * json-schema-to-typescript 16 turns an ``allOf`` member that is only
      ``if``/``then``/``else``/``not`` (plus a description) into ``{[k: string]: unknown}``
      and intersects it with the object, silently re-opening every
      ``additionalProperties: false`` object;
    * datamodel-code-generator 0.83 distributes an ``allOf`` of ``anyOf`` branches into a
      ``RootModel`` union of numbered multiple-inheritance classes (``EvaluationResult4``)
      while still dropping the rule the branches expressed.

    The projection removes ``if``/``then``/``else``/``not``, then drops ``allOf`` members that
    no longer declare a ``type`` or ``$ref`` and local ``$defs`` that became annotation-only.
    Shapes, required lists, enums, consts, patterns, bounds and nullability are kept. The
    dropped rules are enforced only by validating against the JSON Schema itself (the source
    of truth). Measured on the in-repo examples at introduction, the unprojected and projected
    Pydantic output rejected exactly the same invalid fixtures (ADR-0004 records the counts).
    """
    stripped = _strip_conditionals(document)
    assert isinstance(stripped, dict)
    defs = stripped.get("$defs")
    empty: set[str] = set()
    if isinstance(defs, dict):
        empty = {name for name, body in defs.items() if _is_annotation_only(body)}
        stripped["$defs"] = {name: body for name, body in defs.items() if name not in empty}
    projected = _drop_constraint_only_all_of(
        stripped, frozenset(f"#/$defs/{name}" for name in empty)
    )
    assert isinstance(projected, dict)
    return projected


def typescript_projection(document: dict[str, object]) -> dict[str, object]:
    """:func:`shape_projection` plus the json-schema-to-typescript ``tsType`` fixes."""
    projected = _any_json_as_unknown(shape_projection(document))
    assert isinstance(projected, dict)
    if not any(key in projected for key in SHAPE_KEYWORDS):
        # A definition library ($defs only, never validated directly) has no instance type.
        projected["tsType"] = "never"
    return projected


SHAPE_KEYWORDS = frozenset(
    {"type", "properties", "$ref", "allOf", "anyOf", "oneOf", "enum", "const", "items"}
)


def _any_json_as_unknown(node: object, *, is_root: bool = True) -> object:
    """Map annotation-only subschemas ("any JSON value") to ``unknown``.

    json-schema-to-typescript 16 renders ``{"description": ...}`` as an open object
    (``{[k: string]: unknown}``), which would reject a string or number that the JSON Schema
    accepts. ``tsType`` is the generator's own escape hatch for this.
    """
    if isinstance(node, list):
        return [_any_json_as_unknown(item, is_root=False) for item in node]
    if not isinstance(node, dict):
        return node
    if not is_root and _is_annotation_only(node):
        return {**node, "tsType": "unknown"}
    out: dict[str, object] = {}
    for key, value in node.items():
        if key in DATA_KEYWORDS:
            out[key] = value
        elif key in NAME_MAP_KEYWORDS and isinstance(value, dict):
            out[key] = {
                name: _any_json_as_unknown(sub, is_root=False) for name, sub in value.items()
            }
        else:
            out[key] = _any_json_as_unknown(value, is_root=False)
    return out


def stage_schemas(files: Sequence[str], stage: Path, *, for_typescript: bool = False) -> list[str]:
    """Write projected copies of the schema files into ``stage``; return the staged paths.

    The directory layout is preserved and file ``$ref`` targets are renamed in step with
    :func:`staged_name`, so relative refs (``common.schema.json``,
    ``../../actions/v1/actor.schema.json``) keep resolving. Content is
    :func:`shape_projection` (Python) or :func:`typescript_projection` (TypeScript), and the
    generators never see example or data files.
    """
    staged: list[str] = []
    for rel in files:
        document = json.loads((SCHEMA_ROOT / rel).read_text(encoding="utf-8"))
        document = typescript_projection(document) if for_typescript else shape_projection(document)
        name = staged_name(rel)
        dest = stage / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(
            json.dumps(_rewrite_refs(document), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        staged.append(name)
    return sorted(staged)


def _normalise(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text.rstrip("\n") + "\n"


def generate_python(stage: Path, work: Path) -> dict[str, str]:
    """Return ``{relative posix path: content}`` for the generated Python package."""
    out = work / PY_PACKAGE
    _run(
        [
            *_datamodel_codegen_cmd(),
            "--input",
            str(stage),
            "--output",
            str(out),
            "--custom-file-header",
            PY_HEADER,
            *DATAMODEL_CODEGEN_ARGS,
        ]
    )
    root_init = out / "__init__.py"
    if not root_init.exists():
        root_init.write_text(PY_HEADER + "\n", encoding="utf-8")
    ruff = _ruff_cmd()
    config = ["--config", str(RUFF_CONFIG)]
    _run([*ruff, "check", *config, "--fix", "--exit-zero", "--quiet", str(out)])
    _run([*ruff, "format", *config, "--quiet", str(out)])
    result: dict[str, str] = {}
    for path in sorted(out.rglob("*.py")):
        rel = path.relative_to(out).as_posix()
        result[rel] = _normalise(path.read_text(encoding="utf-8"))
    return result


def _pascal(text: str) -> str:
    return "".join(part[:1].upper() + part[1:] for part in re.split(r"[^A-Za-z0-9]+", text) if part)


def _ts_index(stage: Path, files: Sequence[str]) -> str:
    """Build ``src/index.ts``: a namespace per schema plus a named export of each root type."""
    lines = [TS_HEADER, ""]
    for rel in files:
        area, major, name = rel.split("/")
        stem = name.removesuffix(".json")
        module = f"./{area}/{major}/{stem}.js"
        title = json.loads((stage / rel).read_text(encoding="utf-8"))["title"]
        namespace = _pascal(f"{area}_{stem}_{major}")
        lines.append(f'export type {{ {_pascal(title)} }} from "{module}";')
        lines.append(f'export type * as {namespace} from "{module}";')
    return "\n".join(lines) + "\n"


def generate_typescript(stage: Path, files: Sequence[str], work: Path) -> dict[str, str]:
    """Return ``{relative posix path: content}`` for the generated TypeScript sources."""
    out = work / "ts"
    job = {
        "schemaRoot": str(stage),
        "outDir": str(out),
        "banner": TS_HEADER,
        "files": list(files),
        "expectedVersion": JSON_SCHEMA_TO_TYPESCRIPT_VERSION,
    }
    node = shutil.which("node")
    if node is None:
        raise ToolchainError("node is not on PATH; Node 24 is required (ADR-0002)")
    _run([node, str(TS_DRIVER)], stdin=json.dumps(job))
    result: dict[str, str] = {}
    for path in sorted(out.rglob("*.ts")):
        rel = path.relative_to(out).as_posix()
        result[rel] = _normalise(path.read_text(encoding="utf-8"))
    result["index.ts"] = _ts_index(stage, files)
    return result


def generate_all() -> tuple[dict[str, str], dict[str, str]]:
    """Generate both trees in a temporary directory and return them in memory."""
    files = discover_schemas()
    check_toolchain()
    with tempfile.TemporaryDirectory(prefix="ns-contracts-codegen-") as tmp:
        work = Path(tmp)
        py_stage = work / "schemas-py"
        ts_stage = work / "schemas-ts"
        stage_schemas(files, py_stage)
        staged = stage_schemas(files, ts_stage, for_typescript=True)
        python_tree = generate_python(py_stage, work / "py")
        ts_tree = generate_typescript(ts_stage, staged, work)
    return python_tree, ts_tree


def read_tree(root: Path, suffix: str) -> dict[str, str]:
    """Read the committed generated tree (``__pycache__`` and other suffixes ignored)."""
    if not root.is_dir():
        return {}
    tree: dict[str, str] = {}
    for path in sorted(root.rglob(f"*{suffix}")):
        if "__pycache__" in path.parts or "node_modules" in path.parts:
            continue
        tree[path.relative_to(root).as_posix()] = path.read_bytes().decode("utf-8")
    return tree


def write_tree(root: Path, tree: dict[str, str], suffix: str) -> int:
    """Make ``root`` match ``tree`` exactly; return the number of files written or removed."""
    changes = 0
    for rel in sorted(set(read_tree(root, suffix)) - set(tree)):
        (root / rel).unlink()
        changes += 1
    for rel, content in sorted(tree.items()):
        dest = root / rel
        data = content.encode("utf-8")
        if dest.is_file() and dest.read_bytes() == data:
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        changes += 1
    for directory in sorted((p for p in root.rglob("*") if p.is_dir()), reverse=True):
        if directory.name == "__pycache__":
            continue
        if not any(directory.iterdir()):
            directory.rmdir()
    return changes


def diff_trees(label: str, committed: dict[str, str], generated: dict[str, str]) -> list[str]:
    """Return human-readable drift lines between the committed and freshly generated trees."""
    problems: list[str] = []
    for rel in sorted(set(committed) | set(generated)):
        path = f"{label}/{rel}"
        if rel not in generated:
            problems.append(f"stale (no longer generated): {path}")
        elif rel not in committed:
            problems.append(f"missing (not committed): {path}")
        elif committed[rel] != generated[rel]:
            problems.append(f"differs: {path}")
            diff = difflib.unified_diff(
                committed[rel].splitlines(),
                generated[rel].splitlines(),
                fromfile=f"committed/{path}",
                tofile=f"generated/{path}",
                lineterm="",
                n=1,
            )
            problems.extend(f"    {line}" for line in list(diff)[:40])
    return problems


def _rel(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def main(argv: Sequence[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        # Drift diffs can quote non-ASCII schema text; cp1252 consoles would raise.
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="Generate Pydantic v2 and TypeScript bindings from the contract schemas."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="regenerate into a temporary directory and fail if it differs from the committed "
        "bindings (the CI drift check); writes nothing",
    )
    args = parser.parse_args(argv)
    try:
        python_tree, ts_tree = generate_all()
    except ToolchainError as exc:
        print(f"generate.py: toolchain not ready: {exc}", file=sys.stderr)
        return 2
    except RuntimeError as exc:
        print(f"generate.py: generation failed: {exc}", file=sys.stderr)
        return 1

    if args.check:
        problems = diff_trees(_rel(PY_OUT), read_tree(PY_OUT, ".py"), python_tree)
        problems += diff_trees(_rel(TS_OUT), read_tree(TS_OUT, ".ts"), ts_tree)
        if problems:
            print("Contract bindings drifted from packages/contracts/schemas:", file=sys.stderr)
            for line in problems:
                print(line, file=sys.stderr)
            print(
                "Run `python packages/contracts/scripts/generate.py` and commit the result.",
                file=sys.stderr,
            )
            return 1
        print(
            f"OK: {len(python_tree)} Python and {len(ts_tree)} TypeScript generated files match "
            "the committed bindings."
        )
        return 0

    py_changes = write_tree(PY_OUT, python_tree, ".py")
    ts_changes = write_tree(TS_OUT, ts_tree, ".ts")
    print(
        f"Generated {len(python_tree)} Python files in {_rel(PY_OUT)} ({py_changes} changed) and "
        f"{len(ts_tree)} TypeScript files in {_rel(TS_OUT)} ({ts_changes} changed)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
