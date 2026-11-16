"""PRP-62 item 2: models, manifest and the metadata-only reader protocol."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from neurosphere_connector import check_connector_contract  # noqa: F401  (kit import smoke)
from neurosphere_connector.manifest import manifest_issues
from neurosphere_connector_aws_bedrock.manifest import IAM_ACTIONS, build_aws_bedrock_manifest
from neurosphere_connector_aws_bedrock.models import (
    BedrockUsagePoint,
    CostWindow,
    InventoryItem,
    UsageWindow,
)
from neurosphere_connector_aws_bedrock.reader import READER_OPERATIONS, BedrockReader
from neurosphere_contracts.connectors.v1.connector_manifest import CredentialRef
from pydantic import ValidationError

_T0 = datetime(2026, 11, 1, tzinfo=UTC)


def test_manifest_is_read_only_commercial_advisory() -> None:
    m = build_aws_bedrock_manifest()
    assert manifest_issues(m.model_dump(mode="json")) == []
    assert m.advisory is True
    assert m.write_support.supported is False
    assert list(m.supported_clouds) == ["commercial"]
    assert set(m.capabilities) == {
        "catalog_discovery",
        "usage_reports",
        "cost_ingest",
        "health_reporting",
    }
    assert m.auth_mode == "workload_identity_federation"
    assert m.credential_refs == []


def test_manifest_scopes_are_read_only_actions() -> None:
    m = build_aws_bedrock_manifest()
    assert (
        tuple(sorted(str(s.root) if hasattr(s, "root") else str(s) for s in m.scopes))
        == IAM_ACTIONS
    )
    for action in IAM_ACTIONS:
        verb = action.split(":", 1)[1]
        assert verb.startswith(("List", "Get")), action


def test_static_key_manifest_carries_a_vault_reference_only() -> None:
    ref = CredentialRef(
        name="aws_access_key",
        vault_ref="https://ns-vault.vault.azure.net/secrets/aws-bedrock-reader",
    )
    m = build_aws_bedrock_manifest(auth_mode="vault_reference", credential_refs=[ref])
    assert m.auth_mode == "vault_reference"
    assert [r.name for r in m.credential_refs] == ["aws_access_key"]


def test_vault_reference_without_a_reference_is_invalid() -> None:
    with pytest.raises(Exception):  # noqa: B017  (InvalidSchemaError from the SDK)
        build_aws_bedrock_manifest(auth_mode="vault_reference")


def test_models_forbid_extra_fields_and_are_frozen() -> None:
    with pytest.raises(ValidationError):
        InventoryItem.model_validate({"id": "m", "prompt": "hello"})
    item = InventoryItem(id="m")
    with pytest.raises(ValidationError):
        item.id = "other"  # type: ignore[misc]


def test_usage_point_value_may_be_none_not_zero() -> None:
    p = BedrockUsagePoint(model_id="m", metric="Invocations", hour=_T0)
    assert p.value is None


def test_usage_window_must_be_hour_aligned_ordered_and_capped() -> None:
    UsageWindow(start=_T0, end=_T0 + timedelta(hours=3))
    with pytest.raises(ValidationError):
        UsageWindow(start=_T0 + timedelta(minutes=5), end=_T0 + timedelta(hours=3))
    with pytest.raises(ValidationError):
        UsageWindow(start=_T0, end=_T0)
    with pytest.raises(ValidationError):
        UsageWindow(start=_T0, end=_T0 + timedelta(days=8))
    with pytest.raises(ValidationError):
        UsageWindow(start=datetime(2026, 11, 1), end=datetime(2026, 11, 2))
    assert len(UsageWindow(start=_T0, end=_T0 + timedelta(hours=5)).hours()) == 5


def test_cost_window_bounds() -> None:
    w = CostWindow(start=date(2026, 11, 1), end=date(2026, 11, 4))
    assert w.days() == [date(2026, 11, 1), date(2026, 11, 2), date(2026, 11, 3)]
    with pytest.raises(ValidationError):
        CostWindow(start=date(2026, 11, 4), end=date(2026, 11, 4))
    with pytest.raises(ValidationError):
        CostWindow(start=date(2026, 1, 1), end=date(2026, 11, 4))


def test_reader_protocol_exposes_read_operations_only() -> None:
    public = {
        name
        for name in vars(BedrockReader)
        if not name.startswith("_") and callable(getattr(BedrockReader, name))
    }
    assert public == set(READER_OPERATIONS)
    forbidden = ("invoke", "converse", "log", "object", "put", "delete", "create", "update")
    for name in public:
        if name == "get_invocation_logging":  # the setting only, never log content
            continue
        assert not set(name.split("_")) & set(forbidden), name
