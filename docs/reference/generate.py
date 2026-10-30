"""Generate the NeuroSphere API, SDK and MCP reference pages (PRP-25 item 2).

Run from anywhere: ``uv run python docs/reference/generate.py`` (writes next to this script).

Inputs, all committed: ``services/api/openapi.json`` (PRP-05 export), the error taxonomy table
``packages/contracts/schemas/errors/v1/error-codes.json``, the connector SDK sources and the MCP
server sources. The MCP tool list is read from the live ``build_mcp_registry`` (stub ports, no I/O);
the MCP resource list is read from the server factory source with ``ast``.

Determinism (regeneration must produce no diff): pages carry a "source commit" and "generated"
date taken from ``SOURCE_STAMP.json``, not from the wall clock. The stamp records a SHA-256 over
the normalised input bytes plus the last commit that touched the inputs. When the inputs hash
matches the recorded one the recorded commit and date are reused (so shallow CI clones and later
unrelated commits cannot cause drift). When the inputs changed, the stamp is refreshed from
``git log -1`` over the inputs, falling back to ``unknown`` when git is unavailable.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
OPENAPI = "services/api/openapi.json"
ERROR_CODES = "packages/contracts/schemas/errors/v1/error-codes.json"
PY_SDK = "connectors/sdk-python/neurosphere_connector"
TS_SDK = "connectors/sdk-ts/src"
MCP_DIR = "services/api/neurosphere_api/mcp"
STAMP_NAME = "SOURCE_STAMP.json"
HTTP_METHODS = ("get", "put", "post", "patch", "delete", "options", "head")
_FLAG_RE = re.compile(r"preview|unverified|experimental|not yet verified", re.IGNORECASE)


# -- inputs and stamp ----------------------------------------------------------------------------


def input_files(root: Path) -> list[str]:
    """Repo-relative paths of every file whose content feeds the pages, sorted."""
    files = [OPENAPI, ERROR_CODES]
    files += [p.relative_to(root).as_posix() for p in (root / PY_SDK).rglob("*.py")]
    files += [p.relative_to(root).as_posix() for p in (root / TS_SDK).glob("*.ts")]
    files += [p.relative_to(root).as_posix() for p in (root / MCP_DIR / "server").glob("*.py")]
    files.append("packages/core/neurosphere_core/copilot/tools/builtin.py")
    return sorted(set(files))


def _read(root: Path, rel: str) -> str:
    return (root / rel).read_bytes().decode("utf-8").replace("\r\n", "\n")


def inputs_digest(root: Path) -> str:
    h = hashlib.sha256()
    for rel in input_files(root):
        h.update(rel.encode())
        h.update(b"\0")
        h.update(_read(root, rel).encode())
        h.update(b"\0")
    return h.hexdigest()


def _git_stamp(root: Path, files: Sequence[str]) -> tuple[str, str]:
    try:
        out = subprocess.run(  # noqa: S603 - fixed argv, repo paths only
            ["git", "log", "-1", "--format=%H%n%cs", "--", *files],  # noqa: S607
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        ).stdout.split()
    except (OSError, subprocess.SubprocessError):
        return "unknown", "unknown"
    return (out[0], out[1]) if len(out) == 2 else ("unknown", "unknown")


def resolve_stamp(root: Path, committed_stamp: Path) -> dict[str, str]:
    """Return the stamp for the current inputs (reusing the recorded one when unchanged)."""
    digest = inputs_digest(root)
    if committed_stamp.is_file():
        old = json.loads(committed_stamp.read_text(encoding="utf-8"))
        if old.get("inputs_sha256") == digest:
            return {k: str(old[k]) for k in ("inputs_sha256", "source_commit", "generated")}
    commit, date = _git_stamp(root, input_files(root))
    if date == "unknown":
        date = datetime.now(UTC).date().isoformat()
    return {"inputs_sha256": digest, "source_commit": commit, "generated": date}


def _clean(text: str) -> str:
    """No em/en dashes in docs; collapse to ASCII."""
    return text.replace(chr(0x2014), " - ").replace(chr(0x2013), "-")


def _cell(text: str) -> str:
    return _clean(" ".join(text.split())).replace("|", "\\|")


def _first_para(text: str | None) -> str:
    if not text:
        return ""
    return _clean(" ".join(text.strip().split("\n\n")[0].split()))


def _header(title: str, stamp: Mapping[str, str], sources: str) -> str:
    return (
        f"# {title}\n\n"
        "> Generated file. Do not edit; run `uv run python docs/reference/generate.py`.\n"
        f"> Source commit: `{stamp['source_commit']}`. Generated: {stamp['generated']}.\n"
        f"> Sources: {sources}.\n\n"
    )


# -- API reference -------------------------------------------------------------------------------


def _schema_label(schema: Mapping[str, Any] | None) -> str:
    if not schema:
        return "none"
    if "$ref" in schema:
        return f"`{str(schema['$ref']).rsplit('/', 1)[-1]}`"
    if "type" in schema:
        inner = schema.get("items")
        if schema["type"] == "array" and isinstance(inner, Mapping):
            return f"array of {_schema_label(inner)}"
        return f"`{schema['type']}`"
    for key in ("anyOf", "oneOf", "allOf"):
        if key in schema:
            return " or ".join(_schema_label(s) for s in schema[key])
    return "object"


def _body_label(body: Mapping[str, Any]) -> str:
    content = body.get("content", {})
    parts = [f"{mt}: {_schema_label(v.get('schema'))}" for mt, v in sorted(content.items())]
    req = "required" if body.get("required") else "optional"
    return f"{'; '.join(parts) or 'none'} ({req})"


def operations(spec: Mapping[str, Any]) -> list[tuple[str, str, Mapping[str, Any]]]:
    out = []
    for path in sorted(spec["paths"]):
        item = spec["paths"][path]
        for method in HTTP_METHODS:
            if method in item:
                out.append((method.upper(), path, item[method]))
    return out


def render_api(
    spec: Mapping[str, Any], taxonomy: Mapping[str, Any], stamp: Mapping[str, str]
) -> str:
    ops = operations(spec)
    info = spec.get("info", {})
    lines = [
        _header("API reference", stamp, f"`{OPENAPI}`, `{ERROR_CODES}`"),
        f"{info.get('title', 'API')} version {info.get('version', '?')}, OpenAPI "
        f"{spec.get('openapi', '?')}. {len(ops)} operations on {len(spec['paths'])} paths.\n\n",
        "## Status and verification\n\n",
        "This page documents the committed API contract. It is not evidence that a live "
        "deployment, provider or region behaves as described. Operations whose summary or "
        "description says preview or unverified carry a **Preview/unverified** marker, and "
        "operations the contract marks deprecated carry **Deprecated**. Capability rows that "
        "are unverified in the capability matrix stay unverified here. Availability, feature "
        "maturity and authorization are separate gates; nothing here claims an authorization "
        "or compliance status.\n\n",
        "## Error taxonomy\n\n",
        "Errors are RFC 9457 problem details (`ProblemDetails`, `application/problem+json`) "
        "with one of the codes below. The table is the committed taxonomy; a `reason` is "
        "mandatory where noted.\n\n",
        "| Code | HTTP | Retryable | Reason | Retry-After | Meaning |\n",
        "|---|---|---|---|---|---|\n",
    ]
    for c in taxonomy["codes"]:
        lines.append(
            f"| `{c['code']}` | {c['http_status']} | {'yes' if c['retryable'] else 'no'} | "
            f"{c['reason']} | {c['retry_after_seconds']} | {_cell(c['description'])} |\n"
        )
    lines.append(
        "\nFramework-level validation failures on some routes surface as the OpenAPI "
        "`HTTPValidationError` (HTTP 422) shape listed per operation below.\n\n"
    )
    tags: dict[str, list[tuple[str, str, Mapping[str, Any]]]] = {}
    for method, path, op in ops:
        tags.setdefault((op.get("tags") or ["untagged"])[0], []).append((method, path, op))
    lines.append("## Endpoint index\n\n| Tag | Method | Path | Summary |\n|---|---|---|---|\n")
    for tag in sorted(tags):
        for method, path, op in tags[tag]:
            lines.append(f"| {tag} | {method} | `{path}` | {_cell(op.get('summary', ''))} |\n")
    lines.append("\n## Endpoints\n\n")
    for tag in sorted(tags):
        lines.append(f"### Tag: {tag}\n\n")
        for method, path, op in tags[tag]:
            lines.append(f"#### {method} `{path}`\n\n")
            flags = []
            text = f"{op.get('summary', '')} {op.get('description', '')}"
            if _FLAG_RE.search(text):
                flags.append("**Preview/unverified**")
            if op.get("deprecated"):
                flags.append("**Deprecated**")
            if flags:
                lines.append(" ".join(flags) + "\n\n")
            lines.append(f"- Operation id: `{op.get('operationId', '')}`\n")
            if op.get("summary"):
                lines.append(f"- Summary: {_clean(op['summary'])}\n")
            if op.get("description"):
                lines.append(f"- Description: {_first_para(op['description'])}\n")
            params = op.get("parameters", [])
            if params:
                lines.append(
                    "- Parameters: "
                    + ", ".join(
                        f"`{p['name']}` ({p['in']}{', required' if p.get('required') else ''})"
                        for p in params
                    )
                    + "\n"
                )
            if op.get("requestBody"):
                lines.append(f"- Request body: {_body_label(op['requestBody'])}\n")
            resp = []
            for code in sorted(op.get("responses", {})):
                r = op["responses"][code]
                content = r.get("content", {})
                schema = next(iter(content.values()), {}).get("schema") if content else None
                resp.append(f"`{code}` {_schema_label(schema) if schema else 'no body'}")
            lines.append("- Responses: " + "; ".join(resp) + "\n\n")
    return "".join(lines)


# -- Python SDK ----------------------------------------------------------------------------------


def _all_names(tree: ast.Module) -> list[str]:
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets
        ):
            return sorted(ast.literal_eval(node.value))
    return []


def _import_map(tree: ast.Module) -> dict[str, str]:
    out = {}
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                out[alias.asname or alias.name] = node.module
    return out


def _sig(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    prefix = "async def" if isinstance(fn, ast.AsyncFunctionDef) else "def"
    ret = f" -> {ast.unparse(fn.returns)}" if fn.returns else ""
    return f"{prefix} {fn.name}({ast.unparse(fn.args)}){ret}"


def _py_symbol(root: Path, module: str, name: str) -> tuple[str, str, list[str]]:
    rel = module.replace(".", "/")
    path = root / "connectors/sdk-python" / (rel + ".py")
    if not path.is_file():
        path = root / "connectors/sdk-python" / rel / "__init__.py"
    tree = ast.parse(_read(root, path.relative_to(root).as_posix()))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == name:
            bases = ", ".join(ast.unparse(b) for b in node.bases)
            members = [
                _sig(m)
                for m in node.body
                if isinstance(m, ast.FunctionDef | ast.AsyncFunctionDef)
                and (not m.name.startswith("_") or m.name == "__init__")
            ]
            return (
                f"class {name}({bases})" if bases else f"class {name}",
                (_first_para(ast.get_docstring(node))),
                members,
            )
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == name:
            return _sig(node), _first_para(ast.get_docstring(node)), []
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == name for t in node.targets
        ):
            return f"{name} = {ast.unparse(node.value)}", "", []
        if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", "") == name:
            return f"{name}: {ast.unparse(node.annotation)}", "", []
    return name, "", []


def _py_package(root: Path, init_rel: str) -> list[tuple[str, str, str, list[str]]]:
    tree = ast.parse(_read(root, init_rel))
    imports = _import_map(tree)
    rows = []
    for name in _all_names(tree):
        sig, doc, members = _py_symbol(root, imports.get(name, ""), name)
        rows.append((name, sig, doc, members))
    return rows


def render_python_sdk(root: Path, stamp: Mapping[str, str]) -> tuple[str, int]:
    lines = [
        _header("Connector SDK reference (Python)", stamp, f"`{PY_SDK}/`"),
        "Package `neurosphere_connector` (connector SDK, read side) and "
        "`neurosphere_connector.write` (write path, imported explicitly; it is advisory by "
        "default and carries no Azure SDK import). Symbols are the `__all__` of each package, "
        "extracted from source with `ast`. Public methods are listed under each class.\n\n",
    ]
    count = 0
    for title, init in (
        ("`neurosphere_connector`", f"{PY_SDK}/__init__.py"),
        ("`neurosphere_connector.write`", f"{PY_SDK}/write/__init__.py"),
    ):
        rows = _py_package(root, init)
        count += len(rows)
        lines.append(f"## {title}\n\n")
        for name, sig, doc, members in rows:
            lines.append(f"### `{name}`\n\n```python\n{_clean(sig)}\n```\n\n")
            if doc:
                lines.append(f"{doc}\n\n")
            if members:
                lines.append("Methods:\n\n" + "".join(f"- `{_clean(m)}`\n" for m in members))
                lines.append("\n")
    return "".join(lines), count


# -- TypeScript SDK ------------------------------------------------------------------------------

_TS_EXPORT_RE = re.compile(r"export\s+(type\s+)?\{([^}]*)\}\s*from\s*\"([^\"]+)\";", re.DOTALL)
_TS_DECL_RE = (
    r"export\s+(?:declare\s+)?(?:abstract\s+)?(class|function|interface|type|const)\s+{n}\b"
)


def _ts_symbol(root: Path, module: str, name: str) -> tuple[str, str, str]:
    rel = f"{TS_SDK}/{module.removeprefix('./').removesuffix('.js')}.ts"
    if not (root / rel).is_file():
        return "export", "", ""
    src = _read(root, rel)
    m = re.search(_TS_DECL_RE.format(n=re.escape(name)), src)
    if not m:
        return "export", "", ""
    kind = m.group(1)
    tail = src[m.start() :]
    stop = re.search(r"\{|=|;", tail)
    header = " ".join(tail[: stop.start() if stop else 200].split())
    before = src[: m.start()].rstrip()
    doc = ""
    if before.endswith("*/"):
        block = before[before.rfind("/**") :]
        body = re.sub(r"^\s*/?\*+/?\s?", "", block, flags=re.MULTILINE)
        doc = _first_para(body)
    return kind, header, doc


def ts_symbols(root: Path) -> list[tuple[str, str, str, str, str]]:
    src = _read(root, f"{TS_SDK}/index.ts")
    rows = []
    for m in _TS_EXPORT_RE.finditer(src):
        is_type = bool(m.group(1))
        module = m.group(3)
        for raw in m.group(2).split(","):
            name = raw.strip()
            if not name:
                continue
            if module.startswith("."):
                kind, header, doc = _ts_symbol(root, module, name)
            else:
                kind, header, doc = "type", f"re-export from {module}", ""
            rows.append(
                (name, kind if not is_type or kind != "export" else "type", header, doc, module)
            )
    return sorted(rows)


def render_ts_sdk(root: Path, stamp: Mapping[str, str]) -> tuple[str, int]:
    rows = ts_symbols(root)
    lines = [
        _header("Connector SDK reference (TypeScript)", stamp, f"`{TS_SDK}/`"),
        "Package `@neurosphere/connector-sdk`. Read side only: there is no write surface in the "
        "TypeScript SDK; the `WriteConnector` interface lives in the Python SDK. Symbols are "
        "the exports of `src/index.ts`, with declaration headers and the first doc-comment "
        "paragraph extracted from source.\n\n",
        "| Symbol | Kind | Module |\n|---|---|---|\n",
    ]
    for name, kind, _h, _d, module in rows:
        lines.append(f"| `{name}` | {kind} | `{module}` |\n")
    lines.append("\n## Symbols\n\n")
    for name, _kind, header, doc, _module in rows:
        lines.append(f"### `{name}`\n\n```ts\n{_clean(header or name)}\n```\n\n")
        if doc:
            lines.append(f"{doc}\n\n")
    return "".join(lines), len(rows)


# -- MCP -----------------------------------------------------------------------------------------


def mcp_tools() -> list[dict[str, Any]]:
    """Tools from the live registry (stub ports: handlers are never invoked)."""
    for sub in ("services/api", "packages/core", "packages/contracts/python"):
        p = str(ROOT / sub)
        if p not in sys.path:
            sys.path.insert(0, p)
    from neurosphere_api.mcp.server import tools as mod

    registry = mod.build_mcp_registry(
        object(),  # type: ignore[arg-type]
        correlation_id="docs-reference",
        clock=lambda: datetime(2000, 1, 1, tzinfo=UTC),
    )
    out = []
    for spec in registry.manifest():
        ann = mod.ANNOTATIONS.get(spec.name)
        schema = spec.args_model.model_json_schema()
        required = set(schema.get("required", []))
        args = [
            (n, _schema_label(s), n in required)
            for n, s in sorted(schema.get("properties", {}).items())
        ]
        out.append(
            {
                "name": spec.name,
                "description": spec.description,
                "permission": spec.permission.value,
                "args": args,
                "read_only": ann.read_only if ann else None,
                "idempotent": ann.idempotent if ann else None,
            }
        )
    return sorted(out, key=lambda t: t["name"])


def mcp_resources(root: Path) -> list[dict[str, str]]:
    rel = f"{MCP_DIR}/server/factory.py"
    tree = ast.parse(_read(root, rel))
    consts = {
        t.id: ast.literal_eval(n.value)
        for n in tree.body
        if isinstance(n, ast.AnnAssign | ast.Assign)
        and n.value is not None
        and isinstance(n.value, ast.Constant)
        for t in ([n.target] if isinstance(n, ast.AnnAssign) else n.targets)
        if isinstance(t, ast.Name)
    }
    out = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "Resource"
        ):
            kw = {k.arg: k.value for k in node.keywords}
            vals = {}
            for key in ("name", "uri", "description", "mime_type"):
                v = kw.get(key)
                if isinstance(v, ast.Constant):
                    vals[key] = str(v.value)
                elif isinstance(v, ast.Name):
                    vals[key] = str(consts.get(v.id, v.id))
                else:
                    vals[key] = ""
            out.append(vals)
    return sorted(out, key=lambda r: r["uri"])


def render_mcp(root: Path, stamp: Mapping[str, str]) -> tuple[str, int]:
    tools = mcp_tools()
    resources = mcp_resources(root)
    lines = [
        _header("MCP reference", stamp, f"`{MCP_DIR}/server/` and the live tool registry"),
        "The NeuroSphere MCP server exposes bounded structured tools and read-only resources "
        "over streamable HTTP with OAuth 2.1 resource-server auth. Every call re-derives the "
        "caller's `IdentityScope` server-side; scope-shaped arguments (domain, customer, "
        "tenant, scope) are refused, never consulted. There is **no confirm, execute or "
        "approve tool**: an agent can draft and present a confirmation, a human confirms in "
        "the UI or REST API through the same durable action executor. Annotations are client "
        "hints, never authorization.\n\n"
        "Behaviour against live identity providers and provider backends is covered by live "
        "gates; this page documents the registered surface only and does not assert live "
        "verification.\n\n",
        "## Tools\n\n| Tool | Scope requirement | Read-only | Idempotent |\n|---|---|---|---|\n",
    ]
    for t in tools:
        ro = {True: "yes", False: "no", None: "unspecified"}[t["read_only"]]
        idem = {True: "yes", False: "no", None: "unspecified"}[t["idempotent"]]
        lines.append(f"| `{t['name']}` | `{t['permission']}` | {ro} | {idem} |\n")
    lines.append(
        "\nThe scope requirement is the permission checked on the caller's `IdentityScope` "
        "(domain-scoped) before the handler runs.\n\n"
    )
    for t in tools:
        lines.append(f"### `{t['name']}`\n\n{_clean(t['description'])}\n\n")
        lines.append(f"- Scope requirement: `{t['permission']}`\n")
        if t["args"]:
            lines.append(
                "- Arguments: "
                + ", ".join(
                    f"`{n}` ({lab}{', required' if req else ''})" for n, lab, req in t["args"]
                )
                + "\n"
            )
        lines.append("\n")
    lines.append("## Resources\n\n| Name | URI | MIME type | Description |\n|---|---|---|---|\n")
    for r in resources:
        lines.append(
            f"| `{r['name']}` | `{r['uri']}` | `{r['mime_type']}` | {_cell(r['description'])} |\n"
        )
    lines.append(
        "\n## Related surfaces\n\n"
        "- MCP server administration (register servers, sync tools, approve or revoke a tool) is "
        "REST under the `mcp-admin` tag in the [API reference](api.md).\n"
        "- The MCP client connector in `neurosphere_api.mcp.client` consumes external MCP "
        "servers; a synced tool is unusable until an administrator approves it.\n"
    )
    return "".join(lines), len(tools)


def render_index(counts: Mapping[str, int], stamp: Mapping[str, str]) -> str:
    return (
        _header("Reference", stamp, "see each page")
        + "Generated reference pages. They are rebuilt from committed inputs and checked for "
        "drift by `tests/docs/test_reference_coverage.py`.\n\n"
        "| Page | Contents | Count |\n|---|---|---|\n"
        f"| [API reference](api.md) | Every REST operation plus the error taxonomy | "
        f"{counts['operations']} operations |\n"
        f"| [Connector SDK (Python)](sdk-python.md) | Public symbols of the Python SDK | "
        f"{counts['py']} symbols |\n"
        f"| [Connector SDK (TypeScript)](sdk-ts.md) | Exports of the TypeScript SDK | "
        f"{counts['ts']} symbols |\n"
        f"| [MCP reference](mcp.md) | Tools with scope requirements, and resources | "
        f"{counts['mcp']} tools |\n\n"
        "## Regenerating\n\n"
        "Run `uv run python docs/reference/generate.py`. Pages are stamped from "
        "`SOURCE_STAMP.json`, which records a hash of the inputs and the last commit that "
        "touched them; it is refreshed only when the inputs change, so a second run produces "
        "no diff.\n"
    )


def generate(out_dir: Path, root: Path = ROOT, stamp_in: Path | None = None) -> dict[str, int]:
    """Write all pages and the stamp into ``out_dir``; return counts."""
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = resolve_stamp(root, stamp_in or HERE / STAMP_NAME)
    spec = json.loads(_read(root, OPENAPI))
    taxonomy = json.loads(_read(root, ERROR_CODES))
    py_md, py_n = render_python_sdk(root, stamp)
    ts_md, ts_n = render_ts_sdk(root, stamp)
    mcp_md, mcp_n = render_mcp(root, stamp)
    counts = {"operations": len(operations(spec)), "py": py_n, "ts": ts_n, "mcp": mcp_n}
    pages = {
        "api.md": render_api(spec, taxonomy, stamp),
        "sdk-python.md": py_md,
        "sdk-ts.md": ts_md,
        "mcp.md": mcp_md,
        "index.md": render_index(counts, stamp),
        STAMP_NAME: json.dumps(stamp, indent=2, sort_keys=True) + "\n",
    }
    for name, text in pages.items():
        (out_dir / name).write_bytes(text.encode("utf-8"))
    return counts


def main() -> int:
    counts = generate(HERE)
    print(f"wrote {HERE}: {counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
