"""Synthetic policy documents for the governance policy tests (no production data)."""

from __future__ import annotations

import copy
import itertools
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from neurosphere_core.governance.policy.models import (
    PolicyException,
    PolicyViolationEvidence,
    TargetRef,
)
from neurosphere_core.governance.policy.store import ViolationObservation

EXAMPLES = (
    Path(__file__).resolve().parents[4]
    / "packages"
    / "contracts"
    / "schemas"
    / "policy"
    / "v1"
    / "examples"
)
CLOUD = "commercial"
CUSTOMER = "acme"
DOMAIN = "commercial:acme:neurosphere:domain:support"
OTHER_DOMAIN = "commercial:acme:neurosphere:domain:finance"
AUTHOR = "commercial:acme:entra:person:p-" + "1" * 64
REVIEWER = "commercial:acme:entra:person:p-" + "2" * 64
SUBJECT = "commercial:acme:neurosphere:agent:support-bot"
OTHER_SUBJECT = "commercial:acme:neurosphere:agent:billing-bot"
ASSET = "commercial:acme:neurosphere:grounding_source:crm-notes"
T0 = datetime(2026, 11, 20, 9, 0, 0, tzinfo=UTC)
_ids = itertools.count(1)


def new_uuid() -> str:
    return str(uuid.UUID(int=next(_ids) + (4 << 76) + (2 << 62)))


def example(kind_dir: str, name: str) -> dict[str, Any]:
    return json.loads((EXAMPLES / kind_dir / name).read_text(encoding="utf-8"))


def draft(
    policy_id: str = "support-governance",
    *,
    version: int = 1,
    previous: int | None = None,
    domain: str = DOMAIN,
    kinds: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """A valid draft built from the contract's all-kinds example."""
    body = copy.deepcopy(example("valid", "policy-definition.all-kinds.json"))
    body.update(
        {
            "policy_id": policy_id,
            "policy_version": version,
            "previous_version": previous,
            "domain_id": domain,
            "status": "draft",
            "created_by": AUTHOR,
            "published_at": None,
            "published_intent_id": None,
            "published_audit_id": None,
        }
    )
    body.pop("content_sha256", None)
    if kinds is not None:
        body["rules"] = [r for r in body["rules"] if r["kind"] in kinds]
    return body


def target(canonical_id: str = SUBJECT, entity_type: str = "agent") -> TargetRef:
    return TargetRef(canonical_id=canonical_id, entity_type=entity_type)


def observation(
    *,
    run_id: str,
    subject: str = SUBJECT,
    domain: str = DOMAIN,
    policy_id: str = "support-governance",
    rule_id: str = "pii-access",
    evidence_class: str = "reads_sensitive",
    version: int = 1,
) -> ViolationObservation:
    return ViolationObservation(
        cloud="commercial",
        customer_id=CUSTOMER,
        domain_id=domain,
        policy_id=policy_id,
        policy_version=version,
        rule_id=rule_id,
        rule_kind="data_sensitivity_access",
        severity="high",
        subject=target(subject),
        evidence_class=evidence_class,
        evidence=(
            PolicyViolationEvidence.model_validate(
                {
                    "evidence_kind": "relation",
                    "ref": subject + "/reads",
                    "observed_at": "2026-11-20T09:00:00Z",
                }
            ),
            PolicyViolationEvidence.model_validate(
                {
                    "evidence_kind": "catalog_entity",
                    "ref": ASSET,
                    "observed_at": "2026-11-20T09:00:00Z",
                }
            ),
        ),
        run_id=run_id,
        correlation_id="corr-test",
    )


def exception(
    *,
    exception_id: str | None = None,
    subject: str = SUBJECT,
    domain: str = DOMAIN,
    rule_id: str = "pii-access",
    requested_at: str = "2026-11-20T09:00:00Z",
    expires_at: str = "2026-12-20T09:00:00Z",
) -> PolicyException:
    return PolicyException.model_validate(
        {
            "schema_version": "1.2.0",
            "exception_id": exception_id or new_uuid(),
            "cloud": CLOUD,
            "customer_id": CUSTOMER,
            "domain_id": domain,
            "policy_id": "support-governance",
            "rule_id": rule_id,
            "subject": {"canonical_id": subject, "entity_type": "agent"},
            "violation_id": None,
            "status": "requested",
            "reason_code": "migration_in_progress",
            "requested_by": AUTHOR,
            "requested_at": requested_at,
            "review_item_id": "hitl-item-1",
            "expires_at": expires_at,
        }
    )
