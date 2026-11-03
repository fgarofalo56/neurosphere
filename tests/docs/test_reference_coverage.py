"""PRP-25 item 2: generated references cover the API, MCP tools and SDKs, and do not drift."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
REF = ROOT / "docs" / "reference"
PAGES = ("api.md", "index.md", "mcp.md", "sdk-python.md", "sdk-ts.md", "SOURCE_STAMP.json")


def _load_generator():
    spec = importlib.util.spec_from_file_location("ns_reference_generate", REF / "generate.py")
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def gen():
    return _load_generator()


def _text(name: str) -> str:
    return (REF / name).read_text(encoding="utf-8").replace("\r\n", "\n")


def test_every_openapi_operation_is_in_api_page() -> None:
    spec = json.loads((ROOT / "services/api/openapi.json").read_text(encoding="utf-8"))
    page = _text("api.md")
    missing = []
    for path, item in spec["paths"].items():
        for method in ("get", "put", "post", "patch", "delete", "options", "head"):
            if method in item and f"#### {method.upper()} `{path}`" not in page:
                missing.append(f"{method.upper()} {path}")
    assert not missing


def test_api_page_states_error_taxonomy() -> None:
    codes = json.loads(
        (ROOT / "packages/contracts/schemas/errors/v1/error-codes.json").read_text("utf-8")
    )["codes"]
    page = _text("api.md")
    assert "## Error taxonomy" in page
    for c in codes:
        assert f"| `{c['code']}` | {c['http_status']} |" in page


def test_every_mcp_tool_appears_with_scope(gen) -> None:
    tools = gen.mcp_tools()
    assert len(tools) >= 7
    page = _text("mcp.md")
    for t in tools:
        assert f"| `{t['name']}` | `{t['permission']}` |" in page
        assert f"### `{t['name']}`" in page
    assert not any("confirm_action" in t["name"] or "execute" in t["name"] for t in tools)


def test_mcp_resources_listed(gen) -> None:
    page = _text("mcp.md")
    resources = gen.mcp_resources(ROOT)
    assert resources
    for r in resources:
        assert f"`{r['uri']}`" in page


def test_sdk_symbols_listed(gen) -> None:
    assert "### `BaseConnector`" in _text("sdk-python.md")
    assert "### `WriteConnector`" in _text("sdk-python.md")
    ts = _text("sdk-ts.md")
    for name, *_ in gen.ts_symbols(ROOT):
        assert f"### `{name}`" in ts


def test_pages_carry_commit_and_date_and_no_em_dash() -> None:
    stamp = json.loads(_text("SOURCE_STAMP.json"))
    for name in ("api.md", "index.md", "mcp.md", "sdk-python.md", "sdk-ts.md"):
        page = _text(name)
        assert f"Source commit: `{stamp['source_commit']}`" in page
        assert f"Generated: {stamp['generated']}" in page
        assert "—" not in page


def test_regeneration_equals_committed_output(gen, tmp_path: Path) -> None:
    gen.generate(tmp_path, ROOT, REF / "SOURCE_STAMP.json")
    for name in PAGES:
        regenerated = (tmp_path / name).read_bytes().decode("utf-8").replace("\r\n", "\n")
        assert regenerated == _text(name), f"{name} drifted; run docs/reference/generate.py"
