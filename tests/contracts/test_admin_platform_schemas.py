"""Admin v1 sources, platform and runtime contracts (PRP-37 item 2).

Mapping tests read the core and ingest models these contracts feed (never edit them):

* a PriceSheetUpload example becomes a core PriceSnapshot through build_snapshot without loss;
* a ReviewPolicyDocument example becomes ReviewPolicyRegistry inputs without loss;
* a ProducerRecord round-trips to the ingest edge's ProducerRegistration;
* ConnectorConfig.settings refuses nested values and secret-like keys, and a Government
  credential reference names a vault.usgovcloudapi.net vault;
* AdminConfigDocument.body is pinned to the kind's own schema;
* the cross-field validators named in the schema descriptions accept the examples and reject
  the violation.
"""

from __future__ import annotations

import copy
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from contract_support import SCHEMA_ROOT, load_json, load_schema, model_for, schema_errors
from neurosphere_api.ingest.auth import ProducerRegistration
from neurosphere_core.auth.scope.permissions import Permission
from neurosphere_core.hitl.policy import ReviewPolicy, ReviewPolicyRegistry
from neurosphere_core.pricing.models import PriceRow, PriceSnapshot, TokenMeter, build_snapshot
from pydantic import ValidationError
from validators import (
    check_budget_thresholds_ascending,
    check_connector_config_cloud,
    check_price_sheet_upload,
    check_producer_sources_unique,
    check_review_policy_document,
    validate_cost_tags,
)

EXAMPLES = SCHEMA_ROOT / "admin" / "v1" / "examples"
CONNECTOR = "admin/v1/connector-config.schema.json"
PRODUCER = "admin/v1/producer-record.schema.json"
PRICE = "admin/v1/price-sheet-upload.schema.json"
REVIEW = "admin/v1/review-policy-document.schema.json"
BUDGET = "admin/v1/budget.schema.json"
SETTING = "admin/v1/system-setting.schema.json"
CHECKLIST = "admin/v1/first-run-checklist-item.schema.json"
DOCUMENT = "admin/v1/admin-config-document.schema.json"
KIND_SCHEMAS = {
    "producer": PRODUCER,
    "connector_config": CONNECTOR,
    "domain": "admin/v1/domain-definition.schema.json",
    "budget": BUDGET,
    "price_sheet": PRICE,
    "review_policy": REVIEW,
    "system_setting": SETTING,
}
# PRP-99 item 5: bodies owned by other areas; pinned in tests/contracts/test_governance_a_enums.py.
CROSS_AREA_KIND_SCHEMAS = {
    "notification_channel": "../../notifications/v1/notification-channel.schema.json",
    "notification_subscription": "../../notifications/v1/notification-subscription.schema.json",
    "enforcement_binding": "../../policy/v1/enforcement-binding.schema.json",
}


def _ex(name: str) -> dict[str, Any]:
    return load_json(EXAMPLES / "valid" / f"{name}.json")


def _examples_for(rel: str) -> list[dict[str, Any]]:
    stem = rel.rsplit("/", 1)[-1].removesuffix(".schema.json")
    return [load_json(p) for p in sorted((EXAMPLES / "valid").glob(f"{stem}.*.json"))]


# --------------------------------------------------------------------------- price sheets


def _to_snapshot(upload: dict[str, Any]) -> PriceSnapshot:
    rows = []
    for row in upload["rows"]:
        fields = {k: v for k, v in row.items() if k != "token_meter"}
        meter = row.get("token_meter")
        rows.append(
            PriceRow(
                **fields,
                token_meter=TokenMeter(**meter) if meter is not None else None,
            )
        )
    return build_snapshot(
        snapshot_id=upload["snapshot_id"],
        source=upload["source"],
        source_url=upload["source_url"],
        retrieval_date=date.fromisoformat(upload["retrieval_date"]),
        effective_date=date.fromisoformat(upload["effective_date"]),
        currency=upload["currency"],
        clouds=tuple(upload["clouds"]),
        rows=rows,
        synthetic=upload["synthetic"],
        notes=upload["notes"],
    )


@pytest.mark.parametrize("name", ["provider-sheet-government", "retail-prices"])
def test_price_sheet_upload_maps_to_price_snapshot_without_loss(name: str) -> None:
    upload = _ex(f"price-sheet-upload.{name}")
    snapshot = _to_snapshot(upload)
    assert set(load_schema(PRICE)["properties"]) - {"schema_version"} == (
        set(PriceSnapshot.model_fields) - {"content_hash"}
    )
    assert set(load_schema(PRICE)["$defs"]["price_row"]["properties"]) == set(PriceRow.model_fields)
    assert snapshot.snapshot_id == upload["snapshot_id"]
    assert snapshot.clouds == tuple(upload["clouds"])
    assert len(snapshot.rows) == len(upload["rows"])
    for row, wire in zip(snapshot.rows, upload["rows"], strict=True):
        assert row.retail_price == Decimal(wire["retail_price"])
        for field in ("service_name", "sku_name", "unit_of_measure"):
            assert getattr(row, field) == wire[field]
    assert len(snapshot.content_hash) == 64
    assert check_price_sheet_upload(upload) == []


def test_government_sheet_yields_token_rates() -> None:
    snapshot = _to_snapshot(_ex("price-sheet-upload.provider-sheet-government"))
    assert snapshot.applies_to("government") and not snapshot.applies_to("commercial")
    version = snapshot.to_price_version()
    assert version is not None


def test_retail_prices_never_apply_to_government() -> None:
    upload = _ex("price-sheet-upload.retail-prices")
    upload["clouds"] = ["government"]
    assert schema_errors(PRICE, upload)
    with pytest.raises(ValidationError):
        _to_snapshot(upload)


def test_check_price_sheet_upload() -> None:
    upload = _ex("price-sheet-upload.provider-sheet-government")
    duplicate = copy.deepcopy(upload)
    duplicate["rows"][1]["token_meter"]["kind"] = "input"
    assert any("duplicates" in p for p in check_price_sheet_upload(duplicate))
    hourly = copy.deepcopy(upload)
    hourly["rows"][0]["unit_of_measure"] = "1 Hour"
    assert any("1K or 1M" in p for p in check_price_sheet_upload(hourly))


# --------------------------------------------------------------------------- review policy


def _policy(wire: dict[str, Any], version: str) -> ReviewPolicy:
    return ReviewPolicy(
        self_approval_forbidden=wire["self_approval_forbidden"],
        approver_permission=Permission(wire["approver_permission"]),
        assignment_timeout=timedelta(seconds=wire["assignment_timeout_seconds"]),
        sla=timedelta(seconds=wire["sla_seconds"]),
        escalation_step=timedelta(seconds=wire["escalation_step_seconds"]),
        max_escalations=wire["max_escalations"],
        expiry=timedelta(seconds=wire["expiry_seconds"]),
        policy_version=version,
    )


def test_review_policy_document_maps_to_registry_without_loss() -> None:
    document = _ex("review-policy-document.defaults-with-override")
    version = document["policy_version"]
    registry = ReviewPolicyRegistry(
        kind_defaults={
            d["review_kind"]: _policy(d["policy"], version) for d in document["kind_defaults"]
        },
        action_overrides={
            (o["review_kind"], o["action_kind"]): _policy(o["policy"], version)
            for o in document["action_overrides"]
        },
    )
    override = registry.resolve("maker_checker", "budget_cap_change")
    assert override.sla == timedelta(hours=1) and override.max_escalations == 4
    default = registry.resolve("maker_checker", "agent_disable")
    assert default.sla == timedelta(days=1) and default.self_approval_forbidden
    assert registry.resolve("relationship").approver_permission is Permission.CATALOG_CURATE
    wire_policy = set(load_schema(REVIEW)["$defs"]["policy"]["properties"])
    plain = ("self_approval_forbidden", "approver_permission", "max_escalations")
    core = {
        f if f in plain else f"{f}_seconds"
        for f in ReviewPolicy.model_fields
        if f != "policy_version"
    }
    assert wire_policy == core
    assert check_review_policy_document(document) == []


def test_review_permissions_exist_in_core() -> None:
    enum = load_schema(REVIEW)["$defs"]["policy"]["properties"]["approver_permission"]["enum"]
    # PRP-99 item 5 added config.manage and govpolicy.manage (open-ended, unused by core yet).
    assert set(enum) == {"action.approve", "catalog.curate", "config.manage", "govpolicy.manage"}
    assert {Permission.ACTION_APPROVE, Permission.CATALOG_CURATE} <= {
        Permission(p) for p in enum if p in {x.value for x in Permission}
    }


def test_check_review_policy_document() -> None:
    document = _ex("review-policy-document.defaults-with-override")
    document["kind_defaults"].append(copy.deepcopy(document["kind_defaults"][0]))
    document["action_overrides"].append(copy.deepcopy(document["action_overrides"][0]))
    assert len(check_review_policy_document(document)) == 2


# --------------------------------------------------------------------------- producers


def test_producer_record_round_trips_to_producer_registration() -> None:
    record = _ex("producer-record.active")
    registration = ProducerRegistration(
        producer_id=record["producer_id"],
        secret_sha256=record["secret_sha256"],
        customer_id=record["customer_id"],
        cloud=record["cloud"],
        sources={s["source_id"]: s["observation_kind"] for s in record["sources"]},
    )
    back = {
        **record,
        "producer_id": registration.producer_id,
        "secret_sha256": registration.secret_sha256,
        "customer_id": registration.customer_id,
        "cloud": registration.cloud,
        "sources": [
            {"source_id": k, "observation_kind": v} for k, v in registration.sources.items()
        ],
    }
    assert back == record
    registration_fields = set(ProducerRegistration.model_fields)
    assert registration_fields <= set(load_schema(PRODUCER)["properties"])
    assert check_producer_sources_unique(record) == []
    record["sources"].append(copy.deepcopy(record["sources"][0]))
    assert check_producer_sources_unique(record)


def test_producer_secret_is_only_in_the_issued_response() -> None:
    issued = _ex("producer-secret-issued.rotation")
    assert load_schema("admin/v1/producer-secret-issued.schema.json")["readOnly"] is True
    assert "secret" not in load_schema(PRODUCER)["properties"]
    assert issued["shown_once"] is True
    for rel in KIND_SCHEMAS.values():
        assert "producer-secret-issued" not in str(load_schema(rel))


# --------------------------------------------------------------------------- connectors


@pytest.mark.parametrize(
    "key",
    [
        "client_secret",
        "api_key",
        "access_token",
        "password",
        "sas_url",
        "connection_string",
        "credential",
        "signature",
    ],
)
def test_connector_settings_refuse_secret_like_keys(key: str) -> None:
    config = _ex("connector-config.gateway-poll")
    config["settings"][key] = "value"
    assert schema_errors(CONNECTOR, config)


@pytest.mark.parametrize("value", [{"nested": 1}, [1, 2], 1.5, None, "x" * 513])
def test_connector_settings_refuse_non_scalar_values(value: Any) -> None:
    config = _ex("connector-config.gateway-poll")
    config["settings"]["poll_interval_seconds"] = value
    assert schema_errors(CONNECTOR, config)
    with pytest.raises(ValidationError):
        model_for(CONNECTOR).model_validate(config)


def test_government_connector_uses_government_vault() -> None:
    config = _ex("connector-config.government-billing-export")
    assert config["credential"]["secret_uri"].startswith("https://")
    assert ".vault.usgovcloudapi.net/" in config["credential"]["secret_uri"]
    assert check_connector_config_cloud(config) == []
    commercial = copy.deepcopy(config)
    commercial["credential"]["secret_uri"] = (
        "https://kv-ns-agency.vault.azure.net/secrets/billing-export"
    )
    assert check_connector_config_cloud(commercial)
    mixed = copy.deepcopy(_ex("connector-config.gateway-poll"))
    mixed["domain_ids"].append("government:agency-a:neurosphere:domain:benefits")
    assert check_connector_config_cloud(mixed)


# --------------------------------------------------------------------------- budgets and tags


def test_budget_validators() -> None:
    budget = _ex("budget.monthly-cost-center")
    assert check_budget_thresholds_ascending(budget) == []
    budget["thresholds_percent"] = [80, 50]
    assert check_budget_thresholds_ascending(budget)
    assert load_schema(BUDGET)["title"] == "SpendBudget"


def test_validate_cost_tags() -> None:
    assert validate_cost_tags(None) == []
    assert validate_cost_tags({"cost_center": "cc-1001", "team": "fin-ops"}) == []
    assert validate_cost_tags({f"k{i}": "v" for i in range(17)})
    assert validate_cost_tags({"Team": "x"})
    assert validate_cost_tags({"team": "x" * 129})
    assert validate_cost_tags({"cost_center": "cc 1001"})


# --------------------------------------------------------------------------- runtime settings


def test_system_setting_members_hold_references_only() -> None:
    defs = load_schema(SETTING)["$defs"]
    for name, body in defs.items():
        if "credential" not in body["properties"]:
            # PRP-99 item 5: notifications and enforcement settings hold no credential at all.
            assert name in {"notifications", "enforcement"}, name
            continue
        credential = body["properties"]["credential"]
        refs = [credential.get("$ref")] + [b.get("$ref") for b in credential.get("anyOf", [])]
        assert "credential-reference.schema.json" in refs, name
    keys = load_schema(SETTING)["properties"]["setting_key"]["enum"]
    assert set(keys) <= set(load_schema(SETTING)["properties"])


@pytest.mark.parametrize(
    "key", ["copilot", "judge", "search", "scan", "mcp_server", "write_target"]
)
def test_each_setting_key_requires_its_own_member(key: str) -> None:
    setting = _ex("system-setting.copilot")
    member = setting.pop("copilot")
    setting["setting_key"] = key
    if key != "copilot":
        setting["copilot"] = member
    errors = schema_errors(SETTING, setting)
    assert errors if key != "copilot" else any(e.validator == "required" for e in errors)


def test_checklist_reason_rule() -> None:
    complete = _ex("first-run-checklist-item.complete")
    assert schema_errors(CHECKLIST, {**complete, "reason": "not_configured"})
    missing = _ex("first-run-checklist-item.copilot-missing")
    for status in ("missing", "disabled", "not_applicable", "error"):
        assert schema_errors(CHECKLIST, {**missing, "status": status}) == []
        assert schema_errors(CHECKLIST, {**missing, "status": status, "reason": None})


# --------------------------------------------------------------------------- envelope


@pytest.mark.parametrize("kind", sorted(KIND_SCHEMAS))
def test_admin_config_body_is_pinned_to_its_kind(kind: str) -> None:
    envelope = _ex("admin-config-document.domain")
    bodies = _examples_for(KIND_SCHEMAS[kind])
    assert bodies, kind
    for body in bodies:
        document = {**envelope, "kind": kind, "body": body}
        assert schema_errors(DOCUMENT, document) == [], kind
        model_for(DOCUMENT).model_validate(document)
    for other, rel in KIND_SCHEMAS.items():
        if other == kind:
            continue
        for body in _examples_for(rel):
            assert schema_errors(DOCUMENT, {**envelope, "kind": kind, "body": body}), (kind, other)


def test_admin_kinds_cover_every_body_schema() -> None:
    kinds = load_schema("admin/v1/common.schema.json")["$defs"]["admin_kind"]["enum"]
    assert set(kinds) == set(KIND_SCHEMAS) | set(CROSS_AREA_KIND_SCHEMAS)
    body = load_schema(DOCUMENT)["properties"]["body"]["anyOf"]
    assert {b["$ref"] for b in body} == {r.rsplit("/", 1)[-1] for r in KIND_SCHEMAS.values()} | set(
        CROSS_AREA_KIND_SCHEMAS.values()
    )
