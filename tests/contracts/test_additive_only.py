"""v1 schemas change additively only (ADR-0004, PRP-37 item 3).

``tests/contracts/fixtures/v1-baseline/`` is a committed snapshot of every ``*.schema.json``
under ``packages/contracts/schemas/*/v1/``. Each current schema is compared with its snapshot,
subschema by subschema (same JSON Pointer), and the suite fails when a change could make a
document that was valid before invalid now:

* a schema file, subschema, property or ``$defs`` entry disappears;
* an enum value is removed or a ``const`` changes;
* a property becomes required;
* a ``type`` is narrowed;
* a bound tightens (``maxLength``, ``maxItems``, ``maxProperties``, ``maximum`` lowered or
  added; ``minLength``, ``minItems``, ``minProperties``, ``minimum`` raised or added);
* a ``pattern`` changes (a regex change cannot be proven looser, so every change is reviewed);
* ``additionalProperties`` becomes false or a ``$ref`` target changes.

New schemas, new properties, new enum values, new ``$defs`` and appended ``allOf`` members are
not compared (additive by construction; a new conditional that narrows existing documents is a
review item, see ADR-0004). Deliberate exceptions are listed in :data:`ALLOWED_TIGHTENINGS`
with a reason and must be recorded in ADR-0004; an entry that no longer matches a change fails
the suite so the list cannot go stale.

Refresh the snapshot only when a v1 change has been accepted and recorded (it removes the
evidence of the exceptions, so empty the allowlist in the same change)::

    python tests/contracts/test_additive_only.py --refresh
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest
from contract_support import FIXTURES_DIR, SCHEMA_ROOT, iter_subschemas, resolve_pointer

BASELINE = FIXTURES_DIR / "v1-baseline"
UPPER_BOUNDS = ("maxLength", "maxItems", "maxProperties", "maximum", "exclusiveMaximum")
LOWER_BOUNDS = ("minLength", "minItems", "minProperties", "minimum", "exclusiveMinimum")

# (schema, JSON Pointer, change kind) -> reason. Every entry is recorded in ADR-0004.
ALLOWED_TIGHTENINGS: dict[tuple[str, str, str], str] = {
    (
        "connectors/v1/connector-manifest.schema.json",
        "/properties/scopes/items",
        "pattern",
    ): "PRP-37: scope names capped at 128 characters (was 256); no manifest in the repo exceeds it",
    (
        "connectors/v1/connector-manifest.schema.json",
        "/properties/documentation_url",
        "maxLength",
    ): "PRP-37: documentation_url capped at 512 characters (was 2048)",
    (
        "connectors/v1/connector-manifest.schema.json",
        "/properties/documentation_url",
        "pattern",
    ): "PRP-37: documentation_url path segments capped at 128 characters",
}


def _v1_files(root: Path) -> list[str]:
    return sorted(
        p.relative_to(root).as_posix() for p in root.glob("*/v1/*.schema.json") if p.is_file()
    )


def _types(node: dict[str, Any]) -> set[str] | None:
    kind = node.get("type")
    if kind is None:
        return None
    return {kind} if isinstance(kind, str) else set(kind)


def compare(rel: str, old: dict[str, Any], new: dict[str, Any]) -> list[tuple[str, str, str]]:
    """Return ``(pointer, kind, detail)`` for every non-additive change from ``old`` to ``new``."""
    findings: list[tuple[str, str, str]] = []
    for sub in iter_subschemas(old):
        pointer, before = sub.pointer, sub.node
        try:
            after = resolve_pointer(new, pointer)
        except (KeyError, IndexError, TypeError, ValueError):
            findings.append((pointer, "removed", "subschema no longer exists"))
            continue
        if not isinstance(after, dict):
            findings.append((pointer, "removed", "subschema is no longer an object"))
            continue
        for keyword in ("properties", "$defs", "patternProperties"):
            gone = set(before.get(keyword) or {}) - set(after.get(keyword) or {})
            if gone:
                findings.append((pointer, keyword, f"removed {sorted(gone)}"))
        if isinstance(before.get("enum"), list):
            gone_values = [v for v in before["enum"] if v not in (after.get("enum") or [])]
            if gone_values and "enum" in after:
                findings.append((pointer, "enum", f"removed values {gone_values}"))
        if "const" in before and after.get("const", object()) != before["const"]:
            findings.append((pointer, "const", "changed"))
        added_required = set(after.get("required") or []) - set(before.get("required") or [])
        if added_required:
            findings.append((pointer, "required", f"added {sorted(added_required)}"))
        old_types, new_types = _types(before), _types(after)
        if new_types is not None and (old_types is None or not old_types <= new_types):
            findings.append((pointer, "type", f"{old_types} -> {new_types}"))
        for bound in UPPER_BOUNDS:
            if bound in after and (bound not in before or after[bound] < before[bound]):
                findings.append((pointer, bound, f"{before.get(bound)} -> {after[bound]}"))
        for bound in LOWER_BOUNDS:
            if bound in after and (bound not in before or after[bound] > before[bound]):
                findings.append((pointer, bound, f"{before.get(bound)} -> {after[bound]}"))
        if "pattern" in after and after.get("pattern") != before.get("pattern"):
            findings.append((pointer, "pattern", "changed"))
        if (
            after.get("additionalProperties") is False
            and before.get("additionalProperties") is not False
        ):
            findings.append((pointer, "additionalProperties", "closed"))
        if "$ref" in before and after.get("$ref") != before["$ref"]:
            findings.append((pointer, "$ref", f"{before['$ref']} -> {after.get('$ref')}"))
        if before.get("uniqueItems") is not True and after.get("uniqueItems") is True:
            findings.append((pointer, "uniqueItems", "added"))
    return findings


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _all_findings() -> list[tuple[str, str, str, str]]:
    out = []
    for rel in _v1_files(BASELINE):
        current = SCHEMA_ROOT / rel
        if not current.is_file():
            out.append((rel, "", "removed", "schema file deleted"))
            continue
        out += [(rel, *f) for f in compare(rel, _load(BASELINE / rel), _load(current))]
    return out


def test_baseline_exists_and_covers_every_v1_schema() -> None:
    # New v1 schemas are additive; they join the snapshot at the next refresh.
    assert len(_v1_files(BASELINE)) >= 60


def test_v1_changes_are_additive() -> None:
    blocking = [
        f"{rel}{pointer} [{kind}] {detail}"
        for rel, pointer, kind, detail in _all_findings()
        if (rel, pointer, kind) not in ALLOWED_TIGHTENINGS
    ]
    assert not blocking, "non-additive v1 changes (ADR-0004):\n" + "\n".join(blocking)


def test_allowlist_has_no_stale_entries() -> None:
    found = {(rel, pointer, kind) for rel, pointer, kind, _ in _all_findings()}
    stale = set(ALLOWED_TIGHTENINGS) - found
    assert not stale, f"allowlisted tightenings that no longer occur: {sorted(stale)}"


def test_allowlisted_exceptions_are_recorded_in_adr() -> None:
    adr = (SCHEMA_ROOT.parents[2] / "docs/adr/0004-contract-versioning.md").read_text("utf-8")
    for rel, pointer, _ in ALLOWED_TIGHTENINGS:
        assert rel.rsplit("/", 1)[-1] in adr and pointer.split("/")[2] in adr, (rel, pointer)


BASE_DOC: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["a"],
    "properties": {
        "a": {"type": "string", "maxLength": 10, "pattern": "^x+$"},
        "b": {"type": ["string", "null"], "enum": ["p", "q", None]},
        "c": {"type": "array", "items": {"type": "integer", "minimum": 0}},
    },
}


def _mutated(path: list[str], key: str, value: Any) -> dict[str, Any]:
    doc = json.loads(json.dumps(BASE_DOC))
    node = doc
    for part in path:
        node = node[part]
    if value is _DELETE:
        del node[key]
    else:
        node[key] = value
    return doc


_DELETE = object()


@pytest.mark.parametrize(
    ("path", "key", "value", "kind"),
    [
        (["properties"], "c", _DELETE, "removed"),
        (["properties", "b"], "enum", ["p", None], "enum"),
        ([], "required", ["a", "b"], "required"),
        (["properties", "b"], "type", "string", "type"),
        (["properties", "a"], "maxLength", 5, "maxLength"),
        (["properties", "c", "items"], "minimum", 1, "minimum"),
        (["properties", "a"], "pattern", "^x{1,3}$", "pattern"),
        (["properties", "c"], "minItems", 1, "minItems"),
    ],
)
def test_detector_catches_each_breaking_change(
    path: list[str], key: str, value: Any, kind: str
) -> None:
    findings = compare("x/v1/x.schema.json", BASE_DOC, _mutated(path, key, value))
    assert any(k == kind for _, k, _ in findings), findings


@pytest.mark.parametrize(
    ("path", "key", "value"),
    [
        (["properties"], "d", {"type": "string"}),
        (["properties", "b"], "enum", ["p", "q", None, "r"]),
        (["properties", "a"], "maxLength", 20),
        (["properties", "b"], "type", ["string", "null", "integer"]),
        (["properties", "a"], "description", "documented"),
    ],
)
def test_detector_allows_additive_changes(path: list[str], key: str, value: Any) -> None:
    assert compare("x/v1/x.schema.json", BASE_DOC, _mutated(path, key, value)) == []


def refresh() -> None:
    """Rewrite the snapshot from the current schemas (see the module docstring)."""
    if BASELINE.exists():
        shutil.rmtree(BASELINE)
    for rel in _v1_files(SCHEMA_ROOT):
        dest = BASELINE / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes((SCHEMA_ROOT / rel).read_bytes())


if __name__ == "__main__":
    if sys.argv[1:] != ["--refresh"]:
        raise SystemExit("usage: python tests/contracts/test_additive_only.py --refresh")
    refresh()
