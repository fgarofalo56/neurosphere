"""The example collector config deletes every body field name and targets the edge paths."""

from __future__ import annotations

from pathlib import Path

from neurosphere_core.payload import BODY_FIELD_NAMES

CONFIG = Path(__file__).resolve().parents[1] / "collector" / "otel-collector.example.yaml"


def test_collector_config_deletes_every_body_field_name() -> None:
    text = CONFIG.read_text(encoding="utf-8")
    for name in sorted(BODY_FIELD_NAMES):
        assert f"- key: {name}\n        action: delete" in text, name


def test_collector_config_targets_edge_paths_with_json_and_no_compression() -> None:
    text = CONFIG.read_text(encoding="utf-8")
    assert "/v1/ingest/otlp/traces" in text
    assert "/v1/ingest/otlp/metrics" in text
    assert "encoding: json" in text
    assert "compression: none" in text
    assert "${env:NS_PRODUCER_CREDENTIAL}" in text
