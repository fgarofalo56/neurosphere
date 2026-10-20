"""Judge availability (capability matrix) and approval (classification and boundary)."""

from __future__ import annotations

import pytest
from neurosphere_contracts.deployment.v1.capability_matrix_entry import CapabilityMatrixEntry
from neurosphere_core.capabilities import load_matrix, matrix_from_rows
from neurosphere_core.evaluation.registry import (
    JudgeConfig,
    judge_approval,
    judge_availability,
)

GOV_ROW = "foundry.model_gpt_4_1.government.usgovvirginia.data-zone-standard"
GOV_UNAVAILABLE_ROW = "foundry.model_gpt_5_1.government.usgovvirginia.regional-standard"
COMM_ROW = "foundry.base.commercial.global.any"


def _llm(cloud: str = "government", row: str | None = GOV_ROW, **over: object) -> JudgeConfig:
    base: dict[str, object] = {
        "judge_config_id": "jc-llm",
        "version": "1",
        "judge_kind": "llm_judge",
        "cloud": cloud,
        "judge_model_id": f"{cloud}:c:foundry:modeldeployment:m",
        "judge_model_version": "1",
        "judge_prompt_version": "1",
        "capability_row_id": row,
        "approved_classifications": ("public", "internal", "cui"),
        "max_output_tokens": 100,
        "input_price_per_1k_tokens": "0.001",
        "output_price_per_1k_tokens": "0.002",
        "price_version": "p1",
    }
    return JudgeConfig.model_validate({**base, **over})


def _commercial_row(availability: str) -> CapabilityMatrixEntry:
    return CapabilityMatrixEntry.model_validate(
        {
            "schema_version": "1.1.0",
            "id": COMM_ROW,
            "service": "foundry",
            "feature": "base",
            "cloud": "commercial",
            "region": "global",
            "sku": None,
            "availability": availability,
            "ga_status": "unverified",
            "authorization_scope": "none_claimed",
            "source_url": "https://learn.microsoft.com/azure/foundry/reference/region-support",
            "observed_on": "2026-10-08",
            "notes": "test row",
        }
    )


def test_government_judge_available_via_government_row() -> None:
    enabled, reason = judge_availability(_llm(), load_matrix())
    assert enabled, reason


def test_unavailable_row_disables_with_reason() -> None:
    enabled, reason = judge_availability(_llm(row=GOV_UNAVAILABLE_ROW), load_matrix())
    assert not enabled
    assert "unavailable" in reason


def test_unknown_or_missing_row_is_disabled() -> None:
    matrix = load_matrix()
    assert not judge_availability(_llm(row="foundry.nope.government.x.any"), matrix)[0]
    with pytest.raises(ValueError, match="capability_row_id"):
        _llm(row=None)  # the config model itself requires a row for llm/hybrid judges
    unvalidated = _llm().model_copy(update={"capability_row_id": None})
    enabled, reason = judge_availability(unvalidated, matrix)
    assert not enabled and "capability_row_id" in reason


def test_government_config_never_resolves_to_commercial_row() -> None:
    matrix = matrix_from_rows([_commercial_row("available")])
    enabled, reason = judge_availability(_llm(row=COMM_ROW), matrix)
    assert not enabled
    assert "never bridged" in reason


def test_commercial_config_needs_available_commercial_row() -> None:
    config = _llm(cloud="commercial", row=COMM_ROW)
    assert judge_availability(config, matrix_from_rows([_commercial_row("available")]))[0]
    assert not judge_availability(config, matrix_from_rows([_commercial_row("unverified")]))[0]
    # shipped matrix only has an unverified commercial foundry row: disabled, not assumed
    assert not judge_availability(config, load_matrix())[0]


def test_programmatic_judge_needs_no_endpoint() -> None:
    prog = JudgeConfig(
        judge_config_id="jc-p",
        version="1",
        judge_kind="programmatic",
        cloud="commercial",
        program_version="p1",
        approved_classifications=("public",),
        max_output_tokens=1,
    )
    assert judge_availability(prog, load_matrix())[0]


@pytest.mark.parametrize(
    ("classification", "approved"),
    [("public", True), ("internal", True), ("cui", True), ("restricted", False)],
)
def test_approval_by_classification(classification: str, approved: bool) -> None:
    assert judge_approval(_llm(), classification, "government")[0] is approved


@pytest.mark.parametrize("classification", [None, "", "secret", "CUI", "unclassified"])
def test_null_or_unknown_classification_is_treated_as_restricted(
    classification: str | None,
) -> None:
    approved, reason = judge_approval(_llm(), classification, "government")
    assert not approved
    assert "restricted" in reason
    # even a config that approves everything *named* only approves unknowns if restricted is listed
    permissive = _llm(approved_classifications=("public", "internal", "cui", "restricted"))
    assert judge_approval(permissive, classification, "government")[0]


def test_approval_requires_matching_cloud() -> None:
    approved, reason = judge_approval(_llm(), "public", "commercial")
    assert not approved
    assert "does not match" in reason
    assert not judge_approval(_llm(cloud="commercial", row=COMM_ROW), "public", "government")[0]


def test_public_only_judge_rejects_cui() -> None:
    config = _llm(approved_classifications=("public",))
    assert judge_approval(config, "public", "government")[0]
    assert not judge_approval(config, "cui", "government")[0]
