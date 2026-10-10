"""Tests for packages/contracts/scripts/generate.py (PRP-01 item 6).

Two groups:

* static checks that need no generator toolchain: generator pins agree across generate.py,
  the member manifests and both lockfiles; schema discovery; the shape projection; and the
  committed generated trees (header, ``extra="forbid"``, import);
* idempotence: a fresh generation is byte-identical to the committed bindings. It needs uv,
  Node and ``pnpm install``; without them it skips, unless ``NS_CODEGEN_REQUIRED=1`` (set by
  .github/workflows/contracts.yml) turns the missing toolchain into a failure.
"""

from __future__ import annotations

import importlib
import importlib.util
import inspect
import json
import os
import pkgutil
import re
import sys
import tomllib
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parent / "generate.py"


def _load_generate() -> ModuleType:
    spec = importlib.util.spec_from_file_location("ns_contracts_generate", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


gen = _load_generate()

EXPECTED_AREAS = {
    "actions",
    "audit",
    "catalog",
    "chart",
    "connectors",
    "cost",
    "deployment",
    "errors",
    "evaluation",
    "query",
    "recommendations",
    "scope",
    "telemetry",
}


# --- generator pins -----------------------------------------------------------------------


def test_python_generator_pin_matches_member_pyproject() -> None:
    data = tomllib.loads((gen.PY_PROJECT_DIR / "pyproject.toml").read_text(encoding="utf-8"))
    dev = data["dependency-groups"]["dev"]
    pins = [d for d in dev if d.startswith("datamodel-code-generator")]
    assert pins == [f"datamodel-code-generator=={gen.DATAMODEL_CODE_GENERATOR_VERSION}"], (
        "datamodel-code-generator must be exact-pinned (==) to the version in generate.py"
    )


def test_python_generator_pin_matches_uv_lock() -> None:
    lock = tomllib.loads((gen.REPO_ROOT / "uv.lock").read_text(encoding="utf-8"))
    versions = [p["version"] for p in lock["package"] if p["name"] == "datamodel-code-generator"]
    assert versions == [gen.DATAMODEL_CODE_GENERATOR_VERSION]


def test_typescript_generator_pin_matches_package_json() -> None:
    pkg = json.loads((gen.TS_PROJECT_DIR / "package.json").read_text(encoding="utf-8"))
    assert pkg["devDependencies"]["json-schema-to-typescript"] == (
        gen.JSON_SCHEMA_TO_TYPESCRIPT_VERSION
    ), "json-schema-to-typescript must be an exact version (no ^ or ~)"
    assert pkg["devDependencies"]["typescript"].startswith("~6.0."), "TypeScript 6.0.x (ADR-0002)"
    assert pkg["scripts"]["typecheck"] == "tsc -p tsconfig.json"


def test_typescript_generator_pin_matches_pnpm_lock() -> None:
    text = (gen.REPO_ROOT / "pnpm-lock.yaml").read_text(encoding="utf-8")
    block = re.search(r"^  packages/contracts/ts:\n((?:    .*\n|\n)+?)(?=^\S|^  \S)", text, re.M)
    assert block is not None, "packages/contracts/ts importer missing from pnpm-lock.yaml"
    entry = re.search(
        r"json-schema-to-typescript:\n\s+specifier: (\S+)\n\s+version: (\S+)", block.group(1)
    )
    assert entry is not None
    assert entry.groups() == (
        gen.JSON_SCHEMA_TO_TYPESCRIPT_VERSION,
        gen.JSON_SCHEMA_TO_TYPESCRIPT_VERSION,
    )


def test_pins_are_recorded_in_adr_0004() -> None:
    adr = (gen.REPO_ROOT / "docs" / "adr" / "0004-contract-versioning.md").read_text(
        encoding="utf-8"
    )
    assert f"datamodel-code-generator | {gen.DATAMODEL_CODE_GENERATOR_VERSION}" in adr
    assert f"json-schema-to-typescript | {gen.JSON_SCHEMA_TO_TYPESCRIPT_VERSION}" in adr


# --- discovery and projection -------------------------------------------------------------


def test_discovery_is_sorted_and_skips_examples_and_data_files() -> None:
    files = gen.discover_schemas()
    assert files == sorted(files)
    assert {f.split("/")[0] for f in files} == EXPECTED_AREAS
    for rel in files:
        _area, major, name = rel.split("/")
        assert re.fullmatch(r"v[1-9][0-9]*", major), rel
        assert name.endswith(".schema.json"), rel
    names = {f.rsplit("/", 1)[1] for f in files}
    for data_file in ("transitions.json", "error-codes.json", "id-corpus.json"):
        assert data_file not in names
    assert "confirmation-hash.json" not in names
    assert not any("examples" in f for f in files)


def test_staged_name_drops_schema_infix() -> None:
    assert gen.staged_name("catalog/v1/agent_version.schema.json") == (
        "catalog/v1/agent_version.json"
    )
    assert gen.staged_name("telemetry/v1/telemetry-event.schema.json") == (
        "telemetry/v1/telemetry-event.json"
    )


def test_shape_projection_removes_conditionals_but_keeps_names_and_data() -> None:
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "not": {"type": "string"},
            "if": {"const": {"if": 1}},
            "op": {"enum": ["in", "eq"]},
        },
        "allOf": [
            {"description": "rule", "if": {"required": ["op"]}, "then": {"required": ["not"]}},
            {"$ref": "#/$defs/rule_only"},
            {"$ref": "#/$defs/base"},
        ],
        "$defs": {
            "rule_only": {"description": "x", "if": {}, "then": {}, "else": {"not": {}}},
            "base": {"type": "object"},
        },
    }
    projected = gen.shape_projection(schema)
    assert set(projected["properties"]) == {"not", "if", "op"}, "property names are data"
    assert projected["properties"]["if"] == {"const": {"if": 1}}, "const values are data"
    assert projected["allOf"] == [{"$ref": "#/$defs/base"}]
    assert "rule_only" not in projected["$defs"]
    assert "if" not in json.dumps(projected["allOf"])


def test_typescript_projection_maps_any_json_to_unknown_and_libraries_to_never() -> None:
    value = gen.typescript_projection(
        {"type": "object", "properties": {"value": {"description": "any JSON"}}}
    )
    assert value["properties"]["value"]["tsType"] == "unknown"
    library = gen.typescript_projection({"title": "Lib", "$defs": {"a": {"type": "string"}}})
    assert library["tsType"] == "never"


def test_remote_refs_are_refused() -> None:
    with pytest.raises(RuntimeError, match="remote"):
        gen._rewrite_refs({"$ref": "https://example.invalid/x.schema.json"})


# --- committed generated trees ------------------------------------------------------------


def _committed_python() -> dict[str, str]:
    return gen.read_tree(gen.PY_OUT, ".py")


def _committed_ts() -> dict[str, str]:
    return gen.read_tree(gen.TS_OUT, ".ts")


def test_every_committed_generated_file_has_the_header() -> None:
    py, ts = _committed_python(), _committed_ts()
    assert py, "generated Python package is missing; run generate.py"
    assert ts, "generated TypeScript sources are missing; run generate.py"
    for rel, text in py.items():
        assert text.startswith(gen.PY_HEADER + "\n"), rel
    for rel, text in ts.items():
        assert text.startswith(gen.TS_HEADER + "\n"), rel
    for rel, text in {**py, **ts}.items():
        assert "\r" not in text, f"{rel} must use LF line endings"
        assert not re.search(r"\b20\d\d-\d\d-\d\dT\d\d:\d\d", text.split("\n\n", 1)[0]), rel


def test_one_module_per_schema() -> None:
    files = gen.discover_schemas()
    py = _committed_python()
    ts = _committed_ts()
    for rel in files:
        area, major, name = rel.split("/")
        stem = name.removesuffix(".schema.json")
        assert f"{area}/{major}/{stem.replace('-', '_')}.py" in py, rel
        assert f"{area}/{major}/{stem}.ts" in ts, rel
    assert "index.ts" in ts


def _generated_modules() -> list[ModuleType]:
    package = importlib.import_module(gen.PY_PACKAGE)
    modules = [package]
    for info in pkgutil.walk_packages(package.__path__, f"{gen.PY_PACKAGE}."):
        modules.append(importlib.import_module(info.name))
    return modules


def test_every_generated_model_forbids_extra_properties() -> None:
    from pydantic import BaseModel, RootModel

    checked = 0
    for module in _generated_modules():
        for _, cls in inspect.getmembers(module, inspect.isclass):
            if cls.__module__ != module.__name__ or not issubclass(cls, BaseModel):
                continue
            if issubclass(cls, RootModel):
                continue  # RootModel wraps a value; it has no properties to forbid
            assert cls.model_config.get("extra") == "forbid", f"{module.__name__}.{cls.__name__}"
            checked += 1
    assert checked > 50


def test_root_models_are_importable_by_schema_title() -> None:
    for rel in gen.discover_schemas():
        area, major, name = rel.split("/")
        title = json.loads((gen.SCHEMA_ROOT / rel).read_text(encoding="utf-8"))["title"]
        module = importlib.import_module(
            f"{gen.PY_PACKAGE}.{area}.{major}.{name.removesuffix('.schema.json').replace('-', '_')}"
        )
        assert hasattr(module, title), f"{module.__name__} lacks {title}"


# --- idempotence (needs the generator toolchain) ------------------------------------------


def _require_toolchain() -> None:
    try:
        gen.check_toolchain()
    except gen.ToolchainError as exc:
        if os.environ.get("NS_CODEGEN_REQUIRED") == "1":
            pytest.fail(f"NS_CODEGEN_REQUIRED=1 but the generator toolchain is missing: {exc}")
        pytest.skip(f"generator toolchain not installed: {exc}")


def test_regeneration_is_byte_identical_to_committed_output() -> None:
    _require_toolchain()
    python_tree, ts_tree = gen.generate_all()
    drift = gen.diff_trees("python", _committed_python(), python_tree)
    drift += gen.diff_trees("ts", _committed_ts(), ts_tree)
    assert not drift, "\n".join(drift[:60])
