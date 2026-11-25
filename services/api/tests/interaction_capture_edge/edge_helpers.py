"""Builders for the PRP-103 item 3 edge-capture tests (synthetic data only).

No secret-shaped literal lives here: every canary and credential-shaped value is assembled at
runtime from fragments and fresh randomness (gitleaks fingerprints literals).
"""

from __future__ import annotations

import secrets
import string
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from neurosphere_api.ingest import (
    IngestSettings,
    InMemoryPublisher,
    ProducerRegistration,
    StaticProducerRegistry,
    hash_secret,
)
from neurosphere_api.ingest.auth import RegisteredCredentialAuthenticator
from neurosphere_api.ingest.capture import EdgeCapture, domain_audit_writer
from neurosphere_api.ingest.limits import TokenBucketLimiter
from neurosphere_api.ingest.service import IngestService
from neurosphere_core.audit import AuditDraft, AuditRepository, InMemoryAuditStore
from neurosphere_core.audit.chains import domain_audit_chain_id
from neurosphere_core.audit.content_guard import assert_metadata_only
from neurosphere_core.classification import DEFAULT_SET_VERSION
from neurosphere_core.crypto import LocalFileKeyWrapper
from neurosphere_core.interactions import (
    CaptureMatcher,
    CapturePipeline,
    InMemoryCapturePolicyStore,
    InMemoryInteractionStore,
    parse_capture_policy,
)
from neurosphere_core.lifecycle.policy import PolicyState, load_policy

CUSTOMER = "cust-synthetic"
SOURCE = "src-synthetic"
OTHER_SOURCE = "src-other"
PRODUCER = "prod-synthetic"
DOMAIN = f"commercial:{CUSTOMER}:neurosphere:domain:support"
OTHER_DOMAIN = f"commercial:{CUSTOMER}:neurosphere:domain:sales"
TRACE = "0af7651916cd43dd8448eb211c80319c"
KEK_URI = "https://synthetic-kv.vault.azure.net/keys/ns-content-kek"
POLICY_ID = "support-capture"
POLICY_VERSION = 4
FIXED_NOW = datetime(2026, 11, 25, 12, 0, tzinfo=UTC)
STRUCTURED = "application/cloudevents+json"
BATCH = "application/cloudevents-batch+json"
TELEMETRY_TYPE = "com.neurosphere.telemetry.v1"
COST_TYPE = "com.neurosphere.cost.v1"
CHAIN = domain_audit_chain_id(CUSTOMER, DOMAIN)

_ALNUM = string.ascii_letters + string.digits

#: Every canary and secret-shaped value generated in the current test (leak checks).
ISSUED: list[str] = []


def _issue(value: str) -> str:
    ISSUED.append(value)
    return value


def canary() -> str:
    """``NSCANARY-`` plus random letters (left alone by the detectors, so it survives capture)."""
    return _issue("NSCANARY-" + "".join(secrets.choice(string.ascii_lowercase) for _ in range(16)))


def github_token() -> str:
    body = list("".join(secrets.choice(_ALNUM) for _ in range(36)))
    body[0], body[1], body[2] = "Q", "q", "7"
    return _issue("gh" + "p_" + "".join(body))


def card_number() -> str:
    """A Luhn-valid 16-digit Visa-shaped number, random every call."""
    digits = [4] + [secrets.randbelow(10) for _ in range(14)]
    total = 0
    for index, digit in enumerate(reversed(digits)):
        value = digit * 2 if index % 2 == 0 else digit
        total += value - 9 if value > 9 else value
    digits.append((10 - total % 10) % 10)
    return _issue("".join(map(str, digits)))


def retention(*, opt_in: bool = True) -> PolicyState:
    return load_policy(
        {
            "policy_version": "v1",
            "rules": [
                {
                    "data_class": "telemetry_event",
                    "min_retention_days": 0,
                    "max_retention_days": 30,
                },
                {
                    "data_class": "interaction_content",
                    "min_retention_days": 0,
                    "max_retention_days": 90,
                },
            ],
            "retain_prompt_response_bodies": opt_in,
        }
    )


def policy_doc(**overrides: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "schema_version": "1.2.0",
        "capture_policy_id": POLICY_ID,
        "version": POLICY_VERSION,
        "previous_version": POLICY_VERSION - 1,
        "display_name": "Support capture",
        "cloud": "commercial",
        "customer_id": CUSTOMER,
        "domain_id": DOMAIN,
        "source_ids": [SOURCE],
        "parts": ["prompt", "response"],
        "detector_set_version": DEFAULT_SET_VERSION,
        "customer_dictionary_ids": [],
        "redaction_mode": "redact_all_detections",
        "kept_categories": [],
        "sampling": {"rate": 1.0, "max_per_minute": 600},
        "max_part_chars": 8192,
        "retention_class": "interaction_default",
        "retention_days": 30,
        "state": "active",
        "approved_intent_id": "9d1c5e2a-7b34-4f08-a6e1-3c2b8d4f5a60",
        "approved_audit_id": "e3a47b19-0c52-4d86-b9f3-71a6c0d2e8b5",
        "effective_from": "2026-11-21T08:00:00Z",
    }
    doc.update(overrides)
    return doc


class RecordingAudit(AuditRepository):
    """The real repository (seal runs the content guard) that also keeps every draft and can
    be told to fail."""

    def __init__(self) -> None:
        super().__init__(InMemoryAuditStore(), clock=lambda: FIXED_NOW)
        self.drafts: list[tuple[str, AuditDraft]] = []
        self.fail = False

    async def append(self, chain_id: str, draft: AuditDraft) -> Any:
        if self.fail:
            raise RuntimeError("audit store unavailable")
        # Bind first, then check: the guard must pass on the draft itself, too.
        document = draft.model_dump(mode="json")
        assert_metadata_only(document)
        self.drafts.append((chain_id, draft))
        return await super().append(chain_id, draft)


@dataclass
class Rig:
    service: IngestService
    publisher: InMemoryPublisher
    producer: ProducerRegistration
    capture: EdgeCapture | None = None
    store: InMemoryInteractionStore | None = None
    audit: RecordingAudit | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def producer(**overrides: Any) -> ProducerRegistration:
    fields: dict[str, Any] = {
        "producer_id": PRODUCER,
        "secret_sha256": hash_secret(secrets.token_urlsafe(24)),
        "customer_id": CUSTOMER,
        "cloud": "commercial",
        "sources": {SOURCE: "application", OTHER_SOURCE: "application"},
    }
    fields.update(overrides)
    return ProducerRegistration(**fields)


def service(publisher: InMemoryPublisher, registration: ProducerRegistration) -> IngestService:
    return IngestService(
        settings=IngestSettings(),
        edge_cloud="commercial",
        authenticator=RegisteredCredentialAuthenticator(StaticProducerRegistry([registration])),
        publisher=publisher,
        limiter=TokenBucketLimiter(1000.0, 1000),
        now=lambda: FIXED_NOW,
    )


async def edge_capture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    policies: list[dict[str, Any]] | None = None,
    setting: bool = True,
    opt_in: bool = True,
    max_items_per_request: int = 100,
    pipeline_kwargs: dict[str, Any] | None = None,
) -> tuple[EdgeCapture, InMemoryInteractionStore, RecordingAudit]:
    monkeypatch.setenv("NS_ENV", "local")
    store = InMemoryInteractionStore(
        LocalFileKeyWrapper(tmp_path / "interaction-kek.bin"),
        kek_uri=KEK_URI,
        policy=retention(opt_in=opt_in),
    )
    policy_store = InMemoryCapturePolicyStore()
    for doc in [policy_doc()] if policies is None else policies:
        await policy_store.create(parse_capture_policy(doc))
    matcher = await CaptureMatcher.from_store(
        policy_store, setting_enabled=setting, retention=retention(opt_in=opt_in)
    )
    audit = RecordingAudit()
    pipeline = CapturePipeline(store, **(pipeline_kwargs or {}))
    capture = EdgeCapture(
        matcher,
        pipeline,
        domain_audit_writer(audit, cloud="commercial"),
        max_items_per_request=max_items_per_request,
    )
    return capture, store, audit


async def rig(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **kwargs: Any) -> Rig:
    publisher = InMemoryPublisher()
    registration = producer()
    svc = service(publisher, registration)
    capture, store, audit = await edge_capture(tmp_path, monkeypatch, **kwargs)
    svc.attach_capture(capture)
    return Rig(svc, publisher, registration, capture, store, audit)


def telemetry_data(event_id: str, **extra: Any) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "event_id": event_id,
        "event_time": "2026-11-25T11:59:00Z",
        "cloud": "commercial",
        "customer_id": CUSTOMER,
        "source_id": SOURCE,
        "request_id": "req-9",
        **extra,
    }


def cost_data(cost_id: str) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "cost_id": cost_id,
        "kind": "estimated",
        "amount": "1.25",
        "currency": "USD",
        "price_version": "price-synthetic-1",
        "price_effective_date": "2026-01-01",
        "cloud": "commercial",
        "customer_id": CUSTOMER,
        "source_id": SOURCE,
        "dedupe_key": "dk-1",
        "observation_source": "application",
        "recorded_at": "2026-01-01T00:00:00Z",
    }


def ce(type_: str, data: Any, ce_id: str = "ce-1", **ext: Any) -> dict[str, Any]:
    return {
        "specversion": "1.0",
        "id": ce_id,
        "source": "synthetic/producer",
        "type": type_,
        "datacontenttype": "application/json",
        "data": data,
        **ext,
    }


def attr(key: str, value: Any) -> dict[str, Any]:
    if isinstance(value, int) and not isinstance(value, bool):
        return {"key": key, "value": {"intValue": str(value)}}
    return {"key": key, "value": {"stringValue": value}}


def span(span_id: str, attrs: dict[str, Any]) -> dict[str, Any]:
    return {
        "traceId": TRACE,
        "spanId": span_id,
        "parentSpanId": "",
        "name": "chat synthetic",
        "status": {"code": 1},
        "startTimeUnixNano": "1700000000000000000",
        "endTimeUnixNano": "1700000000250000000",
        "attributes": [attr(k, v) for k, v in attrs.items()],
    }


def traces_doc(spans: list[dict[str, Any]], source: str = SOURCE) -> dict[str, Any]:
    return {
        "resourceSpans": [
            {
                "resource": {"attributes": [attr("neurosphere.source_id", source)]},
                "scopeSpans": [{"scope": {"name": "synthetic"}, "spans": spans}],
            }
        ]
    }


def metrics_doc() -> dict[str, Any]:
    return {
        "resourceMetrics": [
            {
                "resource": {"attributes": [attr("neurosphere.source_id", SOURCE)]},
                "scopeMetrics": [
                    {
                        "metrics": [
                            {
                                "name": "gen_ai.usage.input_tokens",
                                "sum": {
                                    "aggregationTemporality": 2,
                                    "dataPoints": [
                                        {
                                            "asInt": "42",
                                            "timeUnixNano": "1700000000000000000",
                                            "attributes": [
                                                attr("gen_ai.prompt", "metric-side body"),
                                            ],
                                        }
                                    ],
                                },
                            }
                        ]
                    }
                ],
            }
        ]
    }
