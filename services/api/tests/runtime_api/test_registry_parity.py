"""Registry parity for the stores that live in ``services/`` (core tests cannot import them)."""

from __future__ import annotations

import re
from pathlib import Path

from neurosphere_api.copilot import cosmos_store as conversation_store
from neurosphere_api.reports import cosmos_store as report_store
from neurosphere_api.runtime import AuthSettings, StoreSettings
from neurosphere_api.runtime.settings import LOCAL_DEFAULT_CUSTOMER_ID
from neurosphere_core.stores import TTL_PER_ITEM, container_spec
from neurosphere_workers.ingestion import cosmos_stores as ingestion_stores
from neurosphere_workers.ingestion.settings import IngestionSettings
from neurosphere_workers.ingestion.wiring import LedgerSettings
from neurosphere_workers.projections.outbox.reader import SINK_AGGREGATES, SINK_CATALOG

_SANDBOX_CONFIG = Path(__file__).resolve().parents[4] / "sandbox" / "config.py"


def _sandbox_default_customer() -> str:
    # ``sandbox`` is a repo-root package, not importable from this test package's path.
    match = re.search(r'^DEFAULT_CUSTOMER = "([^"]+)"$', _SANDBOX_CONFIG.read_text("utf-8"), re.M)
    assert match is not None
    return match.group(1)


def test_reports_and_copilot_containers() -> None:
    reports = container_spec(report_store.DEFAULT_REPORT_CONTAINER)
    assert reports.partition_key_paths == report_store.REPORT_PARTITION_KEY_PATHS
    conversations = container_spec(conversation_store.DEFAULT_CONVERSATION_CONTAINER)
    assert conversations.partition_key_paths == (conversation_store.PARTITION_KEY_PATH,)
    assert conversations.default_ttl == TTL_PER_ITEM


def test_ingestion_and_ledger_containers() -> None:
    ingestion = IngestionSettings()
    ledger = LedgerSettings()
    names = (
        ingestion.markers_container,
        ingestion.watermarks_container,
        ledger.ledger_container,
        ledger.outbox_container,
        ledger.checkpoint_container,
    )
    for name in names:
        assert container_spec(name).partition_key_paths == (ingestion_stores.PARTITION_KEY_PATH,)
    assert ingestion.cosmos_database == StoreSettings().database


def test_projection_sink_containers_exist() -> None:
    assert container_spec(SINK_CATALOG).name == "catalog"
    assert container_spec(SINK_AGGREGATES).name == "aggregates"


def test_local_customer_default_is_the_sandbox_customer() -> None:
    assert LOCAL_DEFAULT_CUSTOMER_ID == _sandbox_default_customer()
    assert AuthSettings().resolved_customer_id("local") == LOCAL_DEFAULT_CUSTOMER_ID
    assert AuthSettings().resolved_customer_id("prod") is None
