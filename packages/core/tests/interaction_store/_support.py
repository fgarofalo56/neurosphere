"""Builders shared by the interaction store tests. Every key and canary is generated at runtime."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from typing import Any

from neurosphere_contracts.interactions.v1.interaction_record import InteractionRecord
from neurosphere_contracts.interactions.v1.redacted_content import RedactedContent
from neurosphere_core.crypto import WrappedKey
from neurosphere_core.lifecycle.policy import PolicyState, load_policy

CUSTOMER = "acme"
DOMAIN = "commercial:acme:neurosphere:domain:support"
OTHER_DOMAIN = "commercial:acme:neurosphere:domain:sales/emea"
KEK_URI = "https://acme-kv.vault.azure.net/keys/ns-content-kek"
GOV_KEK_URI = "https://acme-kv.vault.usgovcloudapi.net/keys/ns-content-kek"
CAPTURED_AT = "2026-11-20T10:15:01Z"


def canary() -> str:
    return "NSCANARY" + uuid.uuid4().hex.upper()


def new_id() -> str:
    return str(uuid.uuid4())


def policy(*, opt_in: bool = True, rule: bool = True, max_days: int = 90) -> PolicyState:
    rules: list[dict[str, Any]] = [
        {"data_class": "telemetry_event", "min_retention_days": 0, "max_retention_days": 30}
    ]
    if rule:
        rules.append(
            {
                "data_class": "interaction_content",
                "min_retention_days": 0,
                "max_retention_days": max_days,
            }
        )
    return load_policy(
        {"policy_version": "v1", "rules": rules, "retain_prompt_response_bodies": opt_in}
    )


def record_doc(interaction_id: str, **overrides: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "schema_version": "1.2.0",
        "interaction_id": interaction_id,
        "cloud": "commercial",
        "customer_id": CUSTOMER,
        "domain_id": DOMAIN,
        "source_id": "otel-gateway",
        "event_id": "evt-" + interaction_id[:8],
        "correlation_id": "corr-" + interaction_id[:8],
        "capture_source": "edge_push",
        "occurred_at": "2026-11-20T10:15:00Z",
        "captured_at": CAPTURED_AT,
        "agent_id": "commercial:acme:neurosphere:agent:support-bot",
        "tool_id": None,
        "principal_id": None,
        "capture_policy_id": "support-capture",
        "capture_policy_version": 2,
        "detector_set_version": "detectors-1.0",
        "redaction_state": "redacted",
        "parts": [{"part": "prompt", "char_count": 40, "truncated": False}],
        "content_ref": None,
        "findings_summary": [{"category": "email_address", "count": 1, "action": "replaced"}],
        "sensitivity_categories": ["pii"],
        "data_asset_ids": [],
        "expires_at": "2027-02-18T10:15:01Z",
    }
    doc.update(overrides)
    return doc


def make_record(interaction_id: str, **overrides: Any) -> InteractionRecord:
    return InteractionRecord.model_validate(record_doc(interaction_id, **overrides))


def content_doc(interaction_id: str, *texts: str, state: str = "redacted") -> dict[str, Any]:
    kinds = ["prompt", "response", "tool_input", "tool_output", "system_instructions"]
    return {
        "schema_version": "1.0.0",
        "interaction_id": interaction_id,
        "redaction_state": state,
        "detector_set_version": "detectors-1.0",
        "parts": [
            {"part": kinds[i], "text": text, "truncated": False, "findings": []}
            for i, text in enumerate(texts or ("hello [[ns-redacted:email_address]]",))
        ],
    }


def make_content(interaction_id: str, *texts: str) -> RedactedContent:
    return RedactedContent.model_validate(content_doc(interaction_id, *texts))


def secret_shaped_texts() -> dict[str, str]:
    """Values matching the schema's ``not`` patterns, assembled from fragments at runtime."""
    alnum = "Ab3" * 10
    return {
        "private_key": "-----BEGIN " + "RSA PRIVATE" + " KEY-----",
        "jwt": "ey" + "J" + alnum[:10] + "." + alnum[:10] + "." + alnum[:6],
        "bearer": "Bear" + "er " + alnum[:16],
        "aws": "AK" + "IA" + "Q" * 16,
        "github": "gh" + "p_" + alnum[:24],
        "sk": "s" + "k-" + alnum[:24],
        "storage_key": "Account" + "Key=" + alnum[:12],
        "sas": "s" + "ig=" + alnum[:24],
        "userinfo": "https://" + "user" + ":" + "pw" + "@example.invalid/x",
    }


class FakeKeyWrapper:
    """A key wrapper that XORs with a random pad: enough to prove wrap/unwrap plumbing."""

    def __init__(self) -> None:
        self._pad = os.urandom(32)
        self.key_id_value = "test:" + uuid.uuid4().hex[:12]

    @property
    def key_id(self) -> str:
        return self.key_id_value

    async def wrap(self, data_key: bytes) -> WrappedKey:
        return WrappedKey(
            key_id=self.key_id_value,
            algorithm="test-xor",
            value=bytes(a ^ b for a, b in zip(data_key, self._pad, strict=True)),
        )

    async def unwrap(self, wrapped: WrappedKey) -> bytes:
        return bytes(a ^ b for a, b in zip(wrapped.value, self._pad, strict=True))


def at(text: str) -> datetime:
    return datetime.fromisoformat(text).astimezone(UTC)
