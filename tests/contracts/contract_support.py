"""Shared loaders for the PRP-01 contract test suite (item 7).

Everything here is offline: schemas are loaded from ``packages/contracts/schemas`` and
registered in a :class:`referencing.Registry` under their ``$id``, so relative ``$ref``
values resolve without any network access. Example manifests come in five layouts (one per
schema-authoring item); :func:`example_cases` normalises them into :class:`ExampleCase`.
"""

from __future__ import annotations

import functools
import hashlib
import importlib
import json
import math
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urldefrag, urljoin

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACTS_DIR = REPO_ROOT / "packages" / "contracts"
SCHEMA_ROOT = CONTRACTS_DIR / "schemas"
TESTS_DIR = Path(__file__).resolve().parent
FIXTURES_DIR = TESTS_DIR / "fixtures"

SCHEMA_SUFFIX = ".schema.json"
ID_PREFIX = "https://neurosphere.invalid/schemas/"
DRAFT_2020_12 = "https://json-schema.org/draft/2020-12/schema"
MANIFEST_NAMES = ("index.json", "manifest.json", "expectations.json")

# Definition libraries: ``$defs`` only, never validated directly, so they have no examples.
# Explicit by design; test_schemas.py checks it agrees with the manifests' own declarations.
LIBRARY_SCHEMAS = frozenset({"catalog/v1/common.schema.json"})


class NetworkBlockedError(RuntimeError):
    """Raised when a contract test tries to open a network connection (see conftest.py)."""


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


@functools.cache
def schema_files() -> tuple[str, ...]:
    """Sorted ``<area>/v<major>/<name>.schema.json`` paths relative to the schema root."""
    found = [
        p.relative_to(SCHEMA_ROOT).as_posix()
        for p in SCHEMA_ROOT.glob(f"*/*/*{SCHEMA_SUFFIX}")
        if re.fullmatch(r"v[1-9][0-9]*", p.parent.name)
    ]
    assert found, f"no schemas under {SCHEMA_ROOT}"
    return tuple(sorted(found))


@functools.cache
def load_schema(rel: str) -> dict[str, Any]:
    return load_json(SCHEMA_ROOT / rel)


def schema_id(rel: str) -> str:
    return ID_PREFIX + rel


def rel_from_uri(uri: str) -> str | None:
    """Map an absolute schema URI (fragment dropped) back to its relative path, if local."""
    base, _ = urldefrag(uri)
    if not base.startswith(ID_PREFIX):
        return None
    return base.removeprefix(ID_PREFIX)


@functools.cache
def registry() -> Registry:
    resources = [
        (load_schema(rel)["$id"], Resource.from_contents(load_schema(rel), DRAFT202012))
        for rel in schema_files()
    ]
    # No ``retrieve`` callable: an unknown URI raises instead of being fetched.
    return Registry().with_resources(resources)


@functools.cache
def validator_for(rel: str) -> Draft202012Validator:
    return Draft202012Validator(load_schema(rel), registry=registry())


def schema_errors(rel: str, instance: Any) -> list[ValidationError]:
    return list(validator_for(rel).iter_errors(instance))


def iter_error_tree(errors: Iterable[ValidationError]) -> Iterator[ValidationError]:
    """Yield every error including the ``context`` of oneOf/anyOf failures."""
    for error in errors:
        yield error
        if error.context:
            yield from iter_error_tree(error.context)


def json_pointer(path: Iterable[Any]) -> str:
    return "".join("/" + str(part).replace("~", "~0").replace("/", "~1") for part in path)


def resolve_pointer(document: Any, pointer: str) -> Any:
    """Resolve an RFC 6901 pointer; raise KeyError/IndexError when absent."""
    node = document
    if pointer in ("", "#"):
        return node
    for raw in pointer.lstrip("#").lstrip("/").split("/"):
        part = raw.replace("~1", "/").replace("~0", "~")
        node = node[int(part)] if isinstance(node, list) else node[part]
    return node


# --------------------------------------------------------------------------- examples


@dataclass(frozen=True)
class ExampleCase:
    area: str
    schema: str
    file: Path
    valid: bool
    keyword: str | None = None
    instance_path: str | None = None
    message_contains: str | None = None
    reason: str | None = None
    derived_from: Path | None = None

    @property
    def case_id(self) -> str:
        return self.file.relative_to(SCHEMA_ROOT).as_posix()

    def load(self) -> Any:
        return load_json(self.file)


def _schema_rel(path: Path) -> str:
    return path.resolve().relative_to(SCHEMA_ROOT.resolve()).as_posix()


def _manifest(examples_dir: Path) -> Path | None:
    found = [examples_dir / n for n in MANIFEST_NAMES if (examples_dir / n).is_file()]
    assert len(found) <= 1, f"more than one manifest in {examples_dir}: {found}"
    return found[0] if found else None


def _cases_from_examples_list(area: str, manifest: Path, data: dict[str, Any]) -> list[ExampleCase]:
    base = manifest.parent
    cases = []
    for entry in data["examples"]:
        valid = entry["valid"] if "valid" in entry else entry["expect"] == "valid"
        expected = entry.get("expected_error", entry)
        derived = entry.get("derived_from")
        cases.append(
            ExampleCase(
                area=area,
                schema=_schema_rel(base.parent / entry["schema"]),
                file=base / entry["file"],
                valid=valid,
                keyword=None if valid else expected.get("keyword"),
                instance_path=None if valid else expected.get("instance_path"),
                reason=entry.get("reason"),
                derived_from=base / derived if derived else None,
            )
        )
    return cases


def _cases_from_cases_list(area: str, manifest: Path, data: dict[str, Any]) -> list[ExampleCase]:
    base = manifest.parent
    cases = []
    for entry in data["cases"]:
        expected = entry.get("expected_error") or {}
        cases.append(
            ExampleCase(
                area=area,
                schema=_schema_rel(base / entry["schema"]),
                file=base / entry["file"],
                valid=bool(entry["valid"]),
                keyword=expected.get("keyword"),
                instance_path=expected.get("instance_path"),
                reason=entry.get("why"),
            )
        )
    return cases


def _cases_from_valid_invalid_maps(
    area: str, manifest: Path, data: dict[str, Any]
) -> list[ExampleCase]:
    base = manifest.parent
    cases = []
    for bucket, valid in (("valid", True), ("invalid", False)):
        for name, entry in data[bucket].items():
            cases.append(
                ExampleCase(
                    area=area,
                    schema=_schema_rel(base.parent / entry["schema"]),
                    file=base / bucket / name,
                    valid=valid,
                    keyword=entry.get("keyword"),
                    instance_path=entry.get("instance_path"),
                    message_contains=entry.get("message_contains"),
                )
            )
    return cases


def _cases_from_file_names(area: str, examples_dir: Path) -> list[ExampleCase]:
    """No manifest (actions, audit): ``<schema-stem>.<case>.json`` under valid/ or invalid/."""
    cases = []
    for bucket, valid in (("valid", True), ("invalid", False)):
        for path in sorted((examples_dir / bucket).glob("*.json")):
            stem = path.name.split(".", 1)[0]
            cases.append(
                ExampleCase(
                    area=area,
                    schema=_schema_rel(examples_dir.parent / f"{stem}{SCHEMA_SUFFIX}"),
                    file=path,
                    valid=valid,
                )
            )
    return cases


@functools.cache
def manifests() -> dict[str, tuple[Path | None, Any]]:
    out: dict[str, tuple[Path | None, Any]] = {}
    for examples_dir in sorted(SCHEMA_ROOT.glob("*/v*/examples")):
        area = examples_dir.parent.relative_to(SCHEMA_ROOT).as_posix()
        manifest = _manifest(examples_dir)
        out[area] = (manifest, load_json(manifest) if manifest else None)
    return out


@functools.cache
def example_cases() -> tuple[ExampleCase, ...]:
    cases: list[ExampleCase] = []
    for area, (manifest, data) in manifests().items():
        examples_dir = SCHEMA_ROOT / area / "examples"
        if manifest is None:
            cases.extend(_cases_from_file_names(area, examples_dir))
        elif "examples" in data:
            cases.extend(_cases_from_examples_list(area, manifest, data))
        elif "cases" in data:
            cases.extend(_cases_from_cases_list(area, manifest, data))
        elif "valid" in data and "invalid" in data:
            cases.extend(_cases_from_valid_invalid_maps(area, manifest, data))
        else:
            raise AssertionError(f"unrecognised example manifest layout: {manifest}")
    return tuple(sorted(cases, key=lambda c: c.case_id))


def valid_cases() -> list[ExampleCase]:
    return [c for c in example_cases() if c.valid]


def invalid_cases() -> list[ExampleCase]:
    return [c for c in example_cases() if not c.valid]


def example_files_on_disk() -> set[Path]:
    files: set[Path] = set()
    for examples_dir in SCHEMA_ROOT.glob("*/v*/examples"):
        for path in examples_dir.rglob("*.json"):
            if path.parent == examples_dir and path.name in MANIFEST_NAMES:
                continue
            files.add(path.resolve())
    return files


# --------------------------------------------------------------------------- schema walking

SCHEMA_MAP_KEYWORDS = frozenset({"properties", "patternProperties", "$defs", "dependentSchemas"})
SCHEMA_KEYWORDS = frozenset(
    {
        "items",
        "additionalProperties",
        "not",
        "if",
        "then",
        "else",
        "contains",
        "propertyNames",
        "unevaluatedProperties",
        "unevaluatedItems",
        "additionalItems",
    }
)
SCHEMA_LIST_KEYWORDS = frozenset({"allOf", "anyOf", "oneOf", "prefixItems"})
CONDITIONAL_KEYWORDS = frozenset({"if", "then", "else", "not", "contains"})


@dataclass(frozen=True)
class SubSchema:
    pointer: str
    keywords: tuple[str, ...]
    node: dict[str, Any]

    @property
    def under_conditional(self) -> bool:
        return any(k in CONDITIONAL_KEYWORDS for k in self.keywords)


def iter_subschemas(
    node: Any, pointer: str = "", keywords: tuple[str, ...] = ()
) -> Iterator[SubSchema]:
    """Yield every schema object, never descending into data (const, enum, default...)."""
    if not isinstance(node, dict):
        return
    yield SubSchema(pointer, keywords, node)
    for key, value in node.items():
        here = f"{pointer}/{key}"
        if key in SCHEMA_MAP_KEYWORDS and isinstance(value, dict):
            for name, sub in value.items():
                yield from iter_subschemas(sub, f"{here}/{name}", (*keywords, key))
        elif key in SCHEMA_LIST_KEYWORDS and isinstance(value, list):
            for i, sub in enumerate(value):
                yield from iter_subschemas(sub, f"{here}/{i}", (*keywords, key))
        elif key in SCHEMA_KEYWORDS:
            yield from iter_subschemas(value, here, (*keywords, key))


def refs_of(rel: str) -> list[tuple[str, str]]:
    """``(pointer, $ref value)`` for every ``$ref`` in a schema file."""
    return [
        (sub.pointer, sub.node["$ref"])
        for sub in iter_subschemas(load_schema(rel))
        if isinstance(sub.node.get("$ref"), str)
    ]


def ref_target(rel: str, ref: str) -> tuple[str | None, str]:
    """Resolve a ``$ref`` against the schema's ``$id``: ``(target rel path, fragment)``."""
    absolute = urljoin(load_schema(rel)["$id"], ref)
    base, fragment = urldefrag(absolute)
    return rel_from_uri(base), fragment


@functools.cache
def ref_graph() -> dict[str, frozenset[str]]:
    graph: dict[str, frozenset[str]] = {}
    for rel in schema_files():
        targets = {ref_target(rel, ref)[0] for _, ref in refs_of(rel)}
        graph[rel] = frozenset(t for t in targets if t is not None and t != rel)
    return graph


def reachable_from(rel: str) -> set[str]:
    seen: set[str] = set()
    stack = [rel]
    while stack:
        for target in ref_graph().get(stack.pop(), frozenset()):
            if target not in seen:
                seen.add(target)
                stack.append(target)
    return seen


# --------------------------------------------------------------------------- generated code


def pascal(text: str) -> str:
    """Same rule as packages/contracts/scripts/generate.py::_pascal."""
    return "".join(p[:1].upper() + p[1:] for p in re.split(r"[^A-Za-z0-9]+", text) if p)


def python_module_name(rel: str) -> str:
    area, major, name = rel.split("/")
    stem = name.removesuffix(SCHEMA_SUFFIX).replace("-", "_")
    return f"neurosphere_contracts.{area}.{major}.{stem}"


def model_for(rel: str) -> Any:
    module = importlib.import_module(python_module_name(rel))
    return getattr(module, pascal(load_schema(rel)["title"]))


# --------------------------------------------------------------------------- canonical JSON


def _jcs_number(value: int | float) -> str:
    if isinstance(value, bool):
        raise TypeError("bool is not a number")
    if isinstance(value, int):
        return str(value)
    if not math.isfinite(value):
        raise ValueError("RFC 8785 forbids NaN and Infinity")
    if value == int(value) and abs(value) < 1e21:
        return str(int(value))
    text = repr(value)
    # ECMAScript renders exponents as e+N / e-N without leading zeros.
    if "e" in text:
        mantissa, exponent = text.split("e")
        sign = "-" if exponent.startswith("-") else "+"
        text = f"{mantissa}e{sign}{exponent.lstrip('+-').lstrip('0') or '0'}"
    return text


def jcs(value: Any) -> str:
    """RFC 8785 JSON Canonicalization Scheme for the JSON values used in these contracts."""
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int | float):
        return _jcs_number(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return "[" + ",".join(jcs(v) for v in value) + "]"
    if isinstance(value, dict):
        keys = sorted(value, key=lambda k: k.encode("utf-16-be"))
        return (
            "{"
            + ",".join(f"{json.dumps(k, ensure_ascii=False)}:{jcs(value[k])}" for k in keys)
            + "}"
        )
    raise TypeError(f"not a JSON value: {type(value).__name__}")


def sha256_jcs(value: Any) -> str:
    return "sha256:" + hashlib.sha256(jcs(value).encode("utf-8")).hexdigest()
