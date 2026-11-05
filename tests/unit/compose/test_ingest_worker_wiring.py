"""Pins the compose `workers` ingestion wiring and the synthetic price table (PRP-07 close-out)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, cast

import yaml
from neurosphere_core.ledger import PriceTable, PriceVersion

ROOT = Path(__file__).resolve().parents[3]
PRICES = ROOT / "infra" / "dev" / "ledger-prices.dev.json"
MOUNT_TARGET = "/etc/neurosphere/ledger-prices.json"


def _workers() -> dict[str, Any]:
    doc = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    return cast(dict[str, Any], doc["services"]["workers"])


def test_workers_set_the_ingestion_env_matching_the_eventhubs_emulator() -> None:
    env = _workers()["environment"]
    hubs = json.loads((ROOT / "infra/compose/eventhubs.config.json").read_text(encoding="utf-8"))
    hub = hubs["UserConfig"]["NamespaceConfig"][0]["Entities"][0]
    assert env["NS_INGESTION_EVENTHUB_NAME"] == hub["Name"] == "telemetry"
    assert env["NS_INGESTION_CONSUMER_GROUP"] in {g["Name"] for g in hub["ConsumerGroups"]}
    for name in (
        "NS_INGESTION_COSMOS_DATABASE",
        "NS_INGESTION_CHECKPOINT_CONTAINER",
        "NS_QUARANTINE_CONTAINER",
    ):
        assert env[name]
    assert env["NS_WORKER_ROLES"] == "all"


def test_workers_mount_the_price_table_read_only() -> None:
    service = _workers()
    assert service["environment"]["NS_LEDGER_PRICE_TABLE_FILE"] == MOUNT_TARGET
    assert f"./infra/dev/ledger-prices.dev.json:{MOUNT_TARGET}:ro" in service["volumes"]


def test_price_table_validates_and_is_labelled_synthetic() -> None:
    doc = json.loads(PRICES.read_text(encoding="utf-8"))
    versions = [PriceVersion.model_validate(v) for v in doc["versions"]]
    assert versions
    assert all("SYNTHETIC" in v.source for v in versions)
    assert PriceTable(versions)


def test_workers_env_and_price_table_carry_no_secrets() -> None:
    env = _workers()["environment"]
    assert not {k for k in env if re.search(r"KEY|SECRET|CONNECTION|PASSWORD|TOKEN", k)}
    text = PRICES.read_text(encoding="utf-8")
    assert not re.search(r"(?i)accountkey|sharedaccesskey|secret|password", text)
