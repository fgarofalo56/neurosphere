"""Builders shared by the PRP-44 core tests."""

from __future__ import annotations

from typing import Any

CUSTOMER = "contoso"
ACTOR = "commercial:contoso:entra:person:p-" + "0c" * 32
FINANCE = "commercial:contoso:neurosphere:domain:finance"
CONTROL = "commercial:contoso:neurosphere:domain:customer-control"


def domain_body(domain_id: str = FINANCE, **over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "schema_version": "1.0.0",
        "domain_id": domain_id,
        "display_name": "Finance",
        "classification": "confidential",
        "residency_region": "eastus2",
        "status": "active",
        "is_control_domain": False,
    }
    body.update(over)
    return body


def budget_body(**over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "schema_version": "1.0.0",
        "budget_id": "fin-monthly",
        "domain_id": FINANCE,
        "period": "monthly",
        "amount": "1500.50",
        "currency": "USD",
        "thresholds_percent": [50, 80, 100],
    }
    body.update(over)
    return body


def token_row(model: str, kind: str, price: str, unit: str = "1M") -> dict[str, Any]:
    return {
        "service_name": "Azure OpenAI",
        "sku_name": f"{model} {kind}",
        "unit_of_measure": unit,
        "retail_price": price,
        "token_meter": {"provider": "azure_openai", "model": model, "kind": kind},
    }


def sheet_body(**over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "schema_version": "1.0.0",
        "snapshot_id": "aoai-2026-11",
        "source": "provider_price_sheet",
        "source_url": "https://example.test/prices",
        "retrieval_date": "2026-11-01",
        "effective_date": "2026-11-01",
        "currency": "USD",
        "clouds": ["commercial"],
        "synthetic": False,
        "notes": "",
        "rows": [
            token_row("gpt-4.1", "input", "2.00"),
            token_row("gpt-4.1", "output", "8.00"),
            token_row("gpt-mini", "input", "0.40"),
            {
                "service_name": "Storage",
                "sku_name": "Hot",
                "unit_of_measure": "1 GB",
                "retail_price": "0.02",
            },
        ],
    }
    body.update(over)
    return body


def policy_settings(**over: Any) -> dict[str, Any]:
    settings: dict[str, Any] = {
        "self_approval_forbidden": True,
        "approver_permission": "action.approve",
        "assignment_timeout_seconds": 14400,
        "sla_seconds": 3600,
        "escalation_step_seconds": 7200,
        "max_escalations": 3,
        "expiry_seconds": 259200,
    }
    settings.update(over)
    return settings


def policy_body(maker_checker: dict[str, Any] | None = None, **over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "schema_version": "1.0.0",
        "policy_version": "client-chosen",
        "kind_defaults": [
            {"review_kind": "maker_checker", "policy": maker_checker or policy_settings()},
            {
                "review_kind": "relationship",
                "policy": policy_settings(approver_permission="catalog.curate"),
            },
        ],
        "action_overrides": [],
    }
    body.update(over)
    return body
