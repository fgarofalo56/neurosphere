"""``infra/compose/cosmos-containers.json`` is generated from the registry and pinned here.

Regenerate with ``python -m neurosphere_core.stores`` from the repository root.
"""

from __future__ import annotations

import json
from pathlib import Path

from neurosphere_core.stores import CONTAINERS, export_document, export_json
from neurosphere_core.stores.__main__ import main

_EXPORT = Path(__file__).resolve().parents[4] / "infra" / "compose" / "cosmos-containers.json"


def test_committed_export_matches_the_registry() -> None:
    assert _EXPORT.is_file()
    assert _EXPORT.read_text(encoding="utf-8") == export_json(), (
        "out of date: run python -m neurosphere_core.stores"
    )


def test_export_is_deterministic_and_order_independent() -> None:
    assert export_json() == export_json(tuple(reversed(CONTAINERS)))
    names = [c["name"] for c in export_document()["containers"]]
    assert names == sorted(names)
    assert export_json().endswith("}\n")


def test_export_is_value_free_and_complete() -> None:
    document = json.loads(export_json())
    assert document["database"] == "neurosphere"
    assert len(document["containers"]) == len(CONTAINERS)
    for entry in document["containers"]:
        assert set(entry) == {"name", "partition_key", "default_ttl", "owner"}
        assert entry["partition_key"]["kind"] in ("Hash", "MultiHash")


def test_generator_check_mode(tmp_path: Path) -> None:
    target = tmp_path / "containers.json"
    missing = main(["--check", str(target)])
    assert missing == 1
    assert not target.exists()
    written = main([str(target)])
    checked = main(["--check", str(target)])
    assert (written, checked) == (0, 0)
    assert target.read_text(encoding="utf-8") == export_json()
