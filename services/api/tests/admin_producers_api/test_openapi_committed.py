"""The committed OpenAPI document carries the producer routes and no secret material."""

from __future__ import annotations

import json

from neurosphere_api.openapi_export import OPENAPI_PATH, default_app, render_openapi

PRODUCER_PREFIX = "/api/v1/admin/sources/producers"


def _committed() -> dict:
    return json.loads(OPENAPI_PATH.read_text(encoding="utf-8"))


def test_committed_openapi_lists_every_producer_route() -> None:
    paths = [p for p in _committed()["paths"] if p.startswith(PRODUCER_PREFIX)]
    assert PRODUCER_PREFIX in paths
    assert f"{PRODUCER_PREFIX}/{{producer_id}}" in paths
    for action in ("enable", "disable", "rotate"):
        assert f"{PRODUCER_PREFIX}/{{producer_id}}/{action}" in paths


def test_committed_openapi_matches_generated_for_producers() -> None:
    generated = json.loads(render_openapi(default_app()))
    committed = _committed()
    keys = [p for p in generated["paths"] if p.startswith(PRODUCER_PREFIX)]
    assert keys
    for key in keys:
        assert committed["paths"].get(key) == generated["paths"][key], key


def test_only_the_issued_contract_model_mentions_a_secret_or_digest() -> None:
    schemas = _committed()["components"]["schemas"]
    bearing = {
        name
        for name, schema in schemas.items()
        if "producer" in name.lower() and ("digest" in json.dumps(schema).lower())
    }
    assert not bearing, f"digest-bearing producer schemas: {sorted(bearing)}"
    for name, schema in schemas.items():
        if "producer" in name.lower():
            text = json.dumps(schema).lower()
            assert '"example' not in text, name
            assert '"default": "ns_' not in text, name
