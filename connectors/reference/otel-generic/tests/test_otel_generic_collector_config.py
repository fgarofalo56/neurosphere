"""The example collector config deletes every body field name and targets the edge paths."""

from __future__ import annotations

from pathlib import Path

from neurosphere_core.payload import BODY_FIELD_NAMES

CONFIG = Path(__file__).resolve().parents[1] / "collector" / "otel-collector.example.yaml"


def test_collector_config_deletes_every_body_field_name() -> None:
    text = CONFIG.read_text(encoding="utf-8")
    for name in sorted(BODY_FIELD_NAMES):
        assert f"- key: {name}\n        action: delete" in text, name


COMPOSE_CONFIG = CONFIG.with_name("otel-collector.compose.yaml")


def test_compose_collector_config_drops_every_body_name_and_keeps_credential_out() -> None:
    text = COMPOSE_CONFIG.read_text(encoding="utf-8")
    for name in sorted(BODY_FIELD_NAMES):
        assert f"- key: {name}\n        action: delete" in text, name
    assert "${env:NS_PRODUCER_CREDENTIAL}" in text
    assert "/api/v1/ingest/otlp/traces" in text
    assert "encoding: json" in text
    assert "compression: none" in text


def test_collector_config_targets_edge_paths_with_json_and_no_compression() -> None:
    text = CONFIG.read_text(encoding="utf-8")
    assert "/v1/ingest/otlp/traces" in text
    assert "/v1/ingest/otlp/metrics" in text
    assert "encoding: json" in text
    assert "compression: none" in text
    assert "${env:NS_PRODUCER_CREDENTIAL}" in text


def test_collector_configs_parse_and_drop_request_and_response_bodies() -> None:
    import yaml

    for path in (CONFIG, COMPOSE_CONFIG):
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        deleted: set[str] = set()
        for proc in (doc.get("processors") or {}).values():
            for action in proc.get("actions", []) or []:
                if action.get("action") == "delete":
                    deleted.add(action["key"])
        assert deleted >= set(BODY_FIELD_NAMES), (
            path.name,
            sorted(set(BODY_FIELD_NAMES) - deleted),
        )
