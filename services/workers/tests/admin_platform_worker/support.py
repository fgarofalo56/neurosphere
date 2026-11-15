"""Shared fixtures for the admin_platform worker tests (synthetic data, no network)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from neurosphere_contracts.admin.v1.price_sheet_upload import PriceSheetUpload
from neurosphere_core.admin import InMemoryAdminConfigRepository
from neurosphere_core.admin.platform import price_sheet_to_snapshot
from neurosphere_core.cloud import Settings
from neurosphere_core.ledger.prices import ModelRate, PriceVersion, Rate
from neurosphere_core.pricing.models import PriceSnapshot
from neurosphere_workers.runtime.factories import RuntimeConfig
from neurosphere_workers.runtime.settings import AuthSettings, StoreSettings, WorkerSettings

CUSTOMER = "synthco"
ACTOR = "commercial:synthco:entra:person:p-" + "0c" * 32


def runtime_config() -> RuntimeConfig:
    return RuntimeConfig(Settings(env="local"), WorkerSettings(), StoreSettings(), AuthSettings())


def repo() -> InMemoryAdminConfigRepository:
    return InMemoryAdminConfigRepository(cloud="commercial")


def token_row(model: str, kind: str, price: str) -> dict[str, Any]:
    return {
        "service_name": "Azure OpenAI",
        "sku_name": f"{model} {kind}",
        "unit_of_measure": "1M",
        "retail_price": price,
        "token_meter": {"provider": "azure_openai", "model": model, "kind": kind},
    }


def snapshot(snapshot_id: str = "aoai-2026-11", input_price: str = "2.50") -> PriceSnapshot:
    upload = PriceSheetUpload.model_validate(
        {
            "schema_version": "1.0.0",
            "snapshot_id": snapshot_id,
            "source": "provider_price_sheet",
            "source_url": "https://example.test/prices",
            "retrieval_date": "2026-11-01",
            "effective_date": "2026-11-01",
            "currency": "USD",
            "clouds": ["commercial"],
            "synthetic": False,
            "notes": "",
            "rows": [
                token_row("gpt-4.1", "input", input_price),
                token_row("gpt-4.1", "output", "10.00"),
            ],
        }
    )
    return price_sheet_to_snapshot(upload)


def file_version(version_id: str, model: str = "gpt-file", input_price: str = "1") -> PriceVersion:
    return PriceVersion(
        price_version_id=version_id,
        effective_date=date(2026, 10, 1),
        currency="USD",
        source="file",
        rates=[
            ModelRate(
                provider="azure_openai",
                model=model,
                rate=Rate(input=Decimal(input_price), output=Decimal("2")),
            )
        ],
    )
