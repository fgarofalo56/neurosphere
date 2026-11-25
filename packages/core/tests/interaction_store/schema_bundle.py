"""Builds the vendored RedactedContent schema bundle from ``packages/contracts/schemas``.

The runtime images do not ship the contract schema files, so ``neurosphere_core.interactions``
carries a single self-contained copy (``redacted_content.schema.json``) with every external
``$ref`` inlined into ``$defs``. ``test_schema_bundle.py`` rebuilds it and asserts equality, so
the copy cannot drift. Regenerate after a contract change with::

    python packages/core/tests/interaction_store/schema_bundle.py --write
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[4]
SCHEMAS_ROOT = REPO_ROOT / "packages" / "contracts" / "schemas"
ROOT_SCHEMA = Path("interactions") / "v1" / "redacted-content.schema.json"
BUNDLE_PATH = (
    REPO_ROOT
    / "packages"
    / "core"
    / "neurosphere_core"
    / "interactions"
    / "redacted_content.schema.json"
)
_COMMENT = (
    "GENERATED from packages/contracts/schemas (interactions/v1/redacted-content.schema.json "
    "with external $refs inlined into $defs) - do not edit. Regenerate: python "
    "packages/core/tests/interaction_store/schema_bundle.py --write"
)
_DROPPED = frozenset({"$schema", "$id", "$defs"})


def _prefix(file: Path) -> str:
    return file.name.removesuffix(".schema.json").replace("-", "_")


def build_bundle(schemas_root: Path = SCHEMAS_ROOT) -> dict[str, Any]:
    root_file = Path(os.path.normpath(schemas_root / ROOT_SCHEMA))
    cache: dict[Path, dict[str, Any]] = {}
    inlined: dict[str, Any] = {}

    def load(file: Path) -> dict[str, Any]:
        if file not in cache:
            cache[file] = json.loads(file.read_text(encoding="utf-8"))
        return cache[file]

    def resolve(ref: str, file: Path) -> str:
        target, _, fragment = ref.partition("#")
        target_file = file if not target else Path(os.path.normpath(file.parent / target))
        if target_file == root_file:
            return "#" + fragment
        prefix = _prefix(target_file)
        document = load(target_file)
        if fragment == "":
            name = prefix
            if name not in inlined:
                inlined[name] = None  # reserve before recursing (cycles)
                body = {k: v for k, v in document.items() if k not in _DROPPED}
                inlined[name] = rewrite(body, target_file)
        elif fragment.startswith("/$defs/") and "/" not in fragment[len("/$defs/") :]:
            definition = fragment[len("/$defs/") :]
            name = f"{prefix}__{definition}"
            if name not in inlined:
                inlined[name] = None
                inlined[name] = rewrite(document["$defs"][definition], target_file)
        else:
            raise ValueError(f"unsupported $ref {ref!r}")
        return "#/$defs/" + name

    def rewrite(node: Any, file: Path) -> Any:
        if isinstance(node, dict):
            return {
                k: (resolve(v, file) if k == "$ref" and isinstance(v, str) else rewrite(v, file))
                for k, v in node.items()
            }
        if isinstance(node, list):
            return [rewrite(item, file) for item in node]
        return node

    root = load(root_file)
    bundle: dict[str, Any] = {"$comment": _COMMENT}
    bundle.update({k: rewrite(v, root_file) for k, v in root.items() if k != "$defs"})
    root_defs = {k: rewrite(v, root_file) for k, v in root.get("$defs", {}).items()}
    bundle["$defs"] = {**root_defs, **{k: inlined[k] for k in sorted(inlined)}}
    return bundle


def render(bundle: dict[str, Any]) -> str:
    return json.dumps(bundle, indent=2, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    text = render(build_bundle())
    if "--write" in sys.argv[1:]:
        BUNDLE_PATH.write_text(text, encoding="utf-8", newline="\n")
    else:
        sys.stdout.write(text)
