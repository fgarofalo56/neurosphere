"""The containers compiled out of ``cosmos-data.bicep`` match the PRP-29 registry export exactly.

``loadJsonContent`` inlines the export at build time, so the assertions run on the compiled ARM
(its inlined variable and the expressions that read it), not on the Bicep source. A second test
pins the checked-in JSON to ``neurosphere_core.stores.containers.export_document()`` so it cannot
go stale.
"""

from __future__ import annotations

import json
from typing import Any

from neurosphere_core.stores.containers import export_document

from .conftest import CONTAINERS_JSON, DEMO_MODULES, compile_bicep, requires_az


def _inlined_registry(arm: dict[str, Any]) -> dict[str, Any]:
    inlined = [v for k, v in arm["variables"].items() if k.startswith("$fxv#")]
    assert len(inlined) == 1, "exactly one loadJsonContent value is inlined"
    return inlined[0]


def _container_resources(arm: dict[str, Any]) -> list[dict[str, Any]]:
    resources = arm["resources"]
    items = list(resources.values()) if isinstance(resources, dict) else resources
    return [r for r in items if r["type"].endswith("/sqlDatabases/containers")]


def test_checked_in_export_is_not_stale() -> None:
    on_disk = json.loads(CONTAINERS_JSON.read_text(encoding="utf-8"))
    assert on_disk == json.loads(json.dumps(export_document()))


@requires_az
def test_compiled_containers_equal_the_export() -> None:
    arm = compile_bicep(DEMO_MODULES / "cosmos-data.bicep")
    on_disk = json.loads(CONTAINERS_JSON.read_text(encoding="utf-8"))

    # The registry the loop iterates is the export, verbatim, container for container.
    inlined = _inlined_registry(arm)
    assert inlined["containers"] == on_disk["containers"]
    assert inlined["database"] == on_disk["database"] == "neurosphere"

    # The registry-shape facts the PRP pins: hierarchical keys and the two TTL containers.
    by_name = {c["name"]: c for c in inlined["containers"]}
    assert len(by_name) == len(inlined["containers"]) == 27
    assert by_name["copilot_conversations"]["default_ttl"] == -1
    assert by_name["revocations"]["default_ttl"] == -1
    # The catalog resolves to a flat /domain key while hierarchical keys are unverified.
    assert by_name["catalog"]["partition_key"] == {"kind": "Hash", "paths": ["/domain"]}
    multi = {n for n, c in by_name.items() if c["partition_key"]["kind"] == "MultiHash"}
    assert multi
    assert all(len(by_name[n]["partition_key"]["paths"]) == 2 for n in multi)

    # One resource loop over exactly that registry; each property is read from the entry.
    loops = _container_resources(arm)
    assert len(loops) == 1
    loop = loops[0]
    assert loop["copy"]["count"] == "[length(variables('registry').containers)]"
    expr = loop["properties"]["resource"]
    entry = "variables('registry').containers[copyIndex()]"
    assert f"{entry}.name" in expr
    assert f"{entry}.partition_key.paths" in expr
    assert f"{entry}.partition_key.kind" in expr
    # MultiHash gets version 2 (and only MultiHash); a null TTL emits no defaultTtl.
    assert (
        "equals(" + f"{entry}.partition_key.kind, 'MultiHash'), createObject('version', 2)" in expr
    )
    assert (
        f"if(equals({entry}.default_ttl, null()), createObject(), createObject('defaultTtl'" in expr
    )
    assert "throughput" not in json.dumps(arm).lower()
