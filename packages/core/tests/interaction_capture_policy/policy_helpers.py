"""Builders for the capture policy tests (synthetic data only)."""

from __future__ import annotations

import itertools
from datetime import UTC, datetime
from typing import Any

from neurosphere_core.audit import AuditContext, AuditRepository, InMemoryAuditStore
from neurosphere_core.lifecycle.policy import PolicyState, load_policy

CUSTOMER = "contoso"
DOMAIN = "commercial:contoso:neurosphere:domain:support"
OTHER_DOMAIN = "commercial:contoso:neurosphere:domain:sales"
SOURCE = "otel-gateway"
POLICY_ID = "support-capture"
INTENT_ID = "9d1c5e2a-7b34-4f08-a6e1-3c2b8d4f5a60"
APPROVAL_AUDIT_ID = "e3a47b19-0c52-4d86-b9f3-71a6c0d2e8b5"
NOW = datetime(2026, 11, 25, 12, 0, tzinfo=UTC)


def policy_doc(**overrides: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "schema_version": "1.2.0",
        "capture_policy_id": POLICY_ID,
        "version": 1,
        "previous_version": None,
        "display_name": "Support bot capture",
        "cloud": "commercial",
        "customer_id": CUSTOMER,
        "domain_id": DOMAIN,
        "source_ids": [SOURCE],
        "parts": ["prompt", "response"],
        "detector_set_version": "detectors-1.0",
        "customer_dictionary_ids": [],
        "redaction_mode": "redact_all_detections",
        "kept_categories": [],
        "sampling": {"rate": 1.0, "max_per_minute": 120},
        "max_part_chars": 8192,
        "retention_class": "interaction_default",
        "retention_days": 90,
        "state": "proposed",
        "approved_intent_id": None,
        "approved_audit_id": None,
        "effective_from": None,
    }
    doc.update(overrides)
    return doc


def active_doc(**overrides: Any) -> dict[str, Any]:
    base = {
        "state": "active",
        "approved_intent_id": INTENT_ID,
        "approved_audit_id": APPROVAL_AUDIT_ID,
        "effective_from": "2026-11-21T08:00:00Z",
    }
    base.update(overrides)
    return policy_doc(**base)


def retention(*, opt_in: bool = True, content_rule: bool = True) -> PolicyState:
    rules: list[dict[str, Any]] = [
        {"data_class": "telemetry", "min_retention_days": 0, "max_retention_days": 30}
    ]
    if content_rule:
        rules.append(
            {"data_class": "interaction_content", "min_retention_days": 0, "max_retention_days": 90}
        )
    return load_policy(
        {"policy_version": "v1", "rules": rules, "retain_prompt_response_bodies": opt_in}
    )


def audit_repo() -> AuditRepository:
    counter = itertools.count(1)
    return AuditRepository(
        InMemoryAuditStore(),
        clock=lambda: NOW,
        id_factory=lambda: f"00000000-0000-4000-8000-{next(counter):012d}",
    )


def make_ctx(intent_id: str | None = None) -> AuditContext:
    return AuditContext.model_validate(
        {
            "actor": {
                "principal_pseudonym": "p-7f3a9c21",
                "principal_kind": "user",
                "on_behalf_of": None,
            },
            "scope_hash": "sha256:" + "a" * 64,
            "correlation_id": "corr-103a",
            "operation": "placeholder",
            "channel": "worker",
            "intent_id": intent_id,
        }
    )
