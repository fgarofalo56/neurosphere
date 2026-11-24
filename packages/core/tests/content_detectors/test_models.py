"""PRP-101 item 1: classification models and protocol."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any, get_args

import pytest
from neurosphere_contracts.catalog.v1 import common
from neurosphere_contracts.interactions.v1 import detection_finding
from neurosphere_core import classification
from neurosphere_core.classification import (
    ALL_CATEGORIES,
    COVERAGE_LABEL,
    CREDENTIAL_CATEGORIES,
    PLACEHOLDER_RE,
    SENSITIVITY_CATEGORY_FOR,
    Category,
    Detector,
    Finding,
    Match,
    PartKind,
    Redacted,
    RedactionBudget,
    RedactionConfig,
    RedactionFailed,
    SensitivityCategory,
    placeholder,
)
from pydantic import BaseModel, ValidationError

_SCHEMAS = Path(__file__).resolve().parents[4] / "packages" / "contracts" / "schemas"
_NON_CREDENTIAL = sorted(ALL_CATEGORIES - CREDENTIAL_CATEGORIES)


def _literal_values(root_model: type[BaseModel]) -> set[str]:
    return set(get_args(root_model.model_fields["root"].annotation))


def _finding(**overrides: Any) -> Finding:
    fields: dict[str, Any] = {
        "category": "email_address",
        "part": "prompt",
        "detector_id": "email",
        "detector_version": "1.0.0",
        "count": 1,
        "action": "replaced",
        "confidence": "high",
        "offsets": ((0, 24),),
        "sensitivity_category": "pii",
    }
    fields.update(overrides)
    return Finding(**fields)


# --- vocabulary parity with the contracts -------------------------------------------------


def test_categories_equal_detected_category() -> None:
    assert set(get_args(Category)) == _literal_values(detection_finding.DetectedCategory)
    assert ALL_CATEGORIES == _literal_values(detection_finding.DetectedCategory)
    assert len(get_args(Category)) == 19


def test_credential_categories_equal_credential_category() -> None:
    assert CREDENTIAL_CATEGORIES == _literal_values(detection_finding.CredentialCategory)
    assert CREDENTIAL_CATEGORIES < ALL_CATEGORIES


def test_part_kind_equals_content_part_kind() -> None:
    assert set(get_args(PartKind)) == _literal_values(detection_finding.ContentPartKind)


def test_sensitivity_category_equals_prp70_vocabulary() -> None:
    assert set(get_args(SensitivityCategory)) == _literal_values(common.SensitivityCategory)


def test_sensitivity_mapping_covers_every_category_with_valid_values() -> None:
    assert set(SENSITIVITY_CATEGORY_FOR) == ALL_CATEGORIES
    allowed = set(get_args(SensitivityCategory))
    for value in SENSITIVITY_CATEGORY_FOR.values():
        assert value is None or value in allowed


def test_sensitivity_mapping_values() -> None:
    for category in CREDENTIAL_CATEGORIES:
        assert SENSITIVITY_CATEGORY_FOR[category] == "credentials"
    assert SENSITIVITY_CATEGORY_FOR["payment_card"] == "pci"
    assert SENSITIVITY_CATEGORY_FOR["iban"] == "financial"
    for category in ("us_ssn", "email_address", "phone_number", "ip_address", "mac_address"):
        assert SENSITIVITY_CATEGORY_FOR[category] == "pii"
    assert SENSITIVITY_CATEGORY_FOR["guid"] is None
    assert SENSITIVITY_CATEGORY_FOR["customer_dictionary_term"] is None
    assert SENSITIVITY_CATEGORY_FOR["customer_identifier_pattern"] is None
    assert SENSITIVITY_CATEGORY_FOR["other"] == "other"


def test_sensitivity_mapping_is_read_only() -> None:
    with pytest.raises(TypeError):
        SENSITIVITY_CATEGORY_FOR["guid"] = "pii"  # type: ignore[index]


# --- RedactionConfig ----------------------------------------------------------------------


@pytest.mark.parametrize("category", sorted(CREDENTIAL_CATEGORIES))
def test_credential_category_cannot_be_kept(category: str) -> None:
    with pytest.raises(ValidationError, match="always redacted"):
        RedactionConfig(modes={category: "keep"})  # type: ignore[dict-item]


@pytest.mark.parametrize("category", sorted(CREDENTIAL_CATEGORIES))
def test_mode_for_credentials_is_redact_even_with_keep_default(category: str) -> None:
    config = RedactionConfig(default_mode="keep")
    assert config.mode_for(category) == "redact"


def test_mode_defaults_and_overrides() -> None:
    default = RedactionConfig()
    assert default.default_mode == "redact"
    for category in ALL_CATEGORIES:
        assert default.mode_for(category) == "redact"
    # Clarification 3: payment_card defaults to redact but is configurable.
    keep_cards = RedactionConfig(modes={"payment_card": "keep", "guid": "keep"})
    assert keep_cards.mode_for("payment_card") == "keep"
    assert keep_cards.mode_for("guid") == "keep"
    assert keep_cards.mode_for("email_address") == "redact"
    keep_all = RedactionConfig(default_mode="keep", modes={"iban": "redact"})
    assert keep_all.mode_for("iban") == "redact"
    for category in _NON_CREDENTIAL:
        if category != "iban":
            assert keep_all.mode_for(category) == "keep"


def test_redaction_config_rejects_unknown_category_and_mode() -> None:
    with pytest.raises(ValidationError):
        RedactionConfig(modes={"not_a_category": "keep"})  # type: ignore[dict-item]
    with pytest.raises(ValidationError):
        RedactionConfig(modes={"guid": "hash"})  # type: ignore[dict-item]


def test_redaction_config_modes_are_read_only() -> None:
    config = RedactionConfig(modes={"guid": "keep"})
    with pytest.raises(TypeError):
        config.modes["jwt"] = "keep"  # type: ignore[index]
    assert config.mode_for("jwt") == "redact"


# --- RedactionBudget ----------------------------------------------------------------------


def test_budget_defaults() -> None:
    budget = RedactionBudget()
    assert budget.max_input_chars == 1_000_000
    assert budget.max_seconds == 2.0
    assert budget.chunk_chars == 8192
    assert budget.chunk_overlap == 512


@pytest.mark.parametrize(
    "fields",
    [
        {"chunk_chars": 100, "chunk_overlap": 100},
        {"chunk_chars": 100, "chunk_overlap": 200},
        {"max_input_chars": 0},
        {"max_seconds": 0},
        {"max_seconds": -1.0},
        {"chunk_chars": 0},
        {"chunk_overlap": 0},
    ],
)
def test_budget_rejects_invalid(fields: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        RedactionBudget(**fields)


# --- frozen and extra="forbid" ------------------------------------------------------------


@pytest.mark.parametrize(
    "instance",
    [
        RedactionConfig(),
        RedactionBudget(),
        _finding(),
        Redacted(text="x", findings=(), set_version="1.0.0"),
        RedactionFailed(reason="detector_error"),
    ],
    ids=lambda m: type(m).__name__,
)
def test_models_are_frozen_and_forbid_extra(instance: BaseModel) -> None:
    field = next(iter(type(instance).model_fields))
    with pytest.raises(ValidationError):
        setattr(instance, field, getattr(instance, field))
    with pytest.raises(ValidationError):
        type(instance)(**instance.model_dump(), unexpected=1)


# --- Match --------------------------------------------------------------------------------


def test_match_holds_offsets_only() -> None:
    names = {f.name for f in dataclasses.fields(Match)}
    assert names == {
        "start",
        "end",
        "category",
        "confidence",
        "detector_id",
        "sensitivity_category",
    }
    match = Match(start=3, end=9, category="jwt", confidence="high", detector_id="jwt")
    assert match.sensitivity_category is None
    assert not hasattr(match, "__dict__")  # slots: no ad-hoc attributes such as text
    with pytest.raises(dataclasses.FrozenInstanceError):
        match.start = 0  # type: ignore[misc]


@pytest.mark.parametrize(("start", "end"), [(-1, 3), (5, 5), (6, 2)])
def test_match_rejects_bad_offsets_without_echoing(start: int, end: int) -> None:
    with pytest.raises(ValueError) as excinfo:
        Match(start=start, end=end, category="guid", confidence="low", detector_id="guid")
    # A fixed message: no offsets, no text.
    assert str(excinfo.value) == "match offsets must satisfy 0 <= start < end"


# --- Finding ------------------------------------------------------------------------------


@pytest.mark.parametrize("category", sorted(CREDENTIAL_CATEGORIES))
def test_finding_rejects_kept_credential(category: str) -> None:
    with pytest.raises(ValidationError, match="always replaced"):
        _finding(category=category, action="kept", sensitivity_category="credentials")
    assert _finding(category=category, sensitivity_category="credentials").action == "replaced"


def test_finding_allows_kept_non_credential() -> None:
    assert _finding(category="payment_card", action="kept", sensitivity_category="pci").action == (
        "kept"
    )


def test_finding_has_no_text_field() -> None:
    assert set(Finding.model_fields) == {
        "category",
        "part",
        "detector_id",
        "detector_version",
        "count",
        "action",
        "confidence",
        "offsets",
        "sensitivity_category",
    }


@pytest.mark.parametrize(
    "overrides",
    [
        {"detector_id": "Email"},
        {"detector_id": "-email"},
        {"detector_id": "e" * 65},
        {"detector_version": "v1.0.0"},
        {"detector_version": "1.0"},
        {"count": 0},
        {"count": 100_001},
        {"offsets": ((-1, 3),)},
        {"offsets": ((5, 2),)},
        {"offsets": tuple((i, i + 1) for i in range(65))},
        {"sensitivity_category": "secret"},
        {"category": "opaque_secret"},
        {"part": "body"},
        {"confidence": "certain"},
    ],
)
def test_finding_rejects_invalid(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        _finding(**overrides)


def test_finding_field_constraints_mirror_detection_finding() -> None:
    finding = _finding(offsets=tuple((i, i + 1) for i in range(64)), count=100_000)
    contract = detection_finding.DetectionFinding.model_validate(
        {
            **finding.model_dump(exclude={"offsets", "sensitivity_category"}),
            "spans": [{"start": s, "end": e} for s, e in finding.offsets],
        }
    )
    assert contract.count == 100_000


# --- results ------------------------------------------------------------------------------


def test_redaction_failed_holds_reason_only() -> None:
    assert set(RedactionFailed.model_fields) == {"reason"}
    for reason in ("detector_error", "budget_exhausted", "pattern_unsafe", "input_too_large"):
        assert RedactionFailed(reason=reason).reason == reason  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        RedactionFailed(reason="other")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        RedactionFailed(reason="detector_error", text="x")  # type: ignore[call-arg]


def test_redacted_set_version_uses_contract_grammar() -> None:
    assert Redacted(text="", set_version="detectors-1.0").set_version == "detectors-1.0"
    with pytest.raises(ValidationError):
        Redacted(text="", set_version="Detectors 1")


def test_redacted_fields() -> None:
    assert set(Redacted.model_fields) == {"text", "findings", "set_version"}
    redacted = Redacted(text=placeholder("jwt"), findings=(_finding(),), set_version="1.0.0")
    assert redacted.findings[0].category == "email_address"


# --- placeholder --------------------------------------------------------------------------


@pytest.mark.parametrize("category", sorted(ALL_CATEGORIES))
def test_placeholder_grammar(category: Category) -> None:
    text = placeholder(category)
    assert text == f"[[ns-redacted:{category}]]"
    found = PLACEHOLDER_RE.fullmatch(text)
    assert found is not None
    assert found.group("category") == category


def test_placeholder_matches_contract_example() -> None:
    example = json.loads(
        (
            _SCHEMAS
            / "interactions"
            / "v1"
            / "examples"
            / "valid"
            / "redacted-content.jwt-placeholder.json"
        ).read_text(encoding="utf-8")
    )
    texts = [part["text"] for part in example["parts"]]
    found = [m.group(0) for text in texts for m in PLACEHOLDER_RE.finditer(text)]
    assert found == [placeholder("jwt")]


def test_placeholder_rejects_unknown_category() -> None:
    with pytest.raises(ValueError):
        placeholder("opaque_secret")  # type: ignore[arg-type]


# --- protocol and package surface ---------------------------------------------------------


class _StubDetector:
    detector_id = "stub"
    version = "1.0.0"
    kinds = frozenset({"guid"})
    always_redact = False

    def find(self, text: str) -> tuple[Match, ...]:
        return ()


def test_detector_protocol_is_runtime_checkable() -> None:
    assert isinstance(_StubDetector(), Detector)
    assert not isinstance(object(), Detector)


def test_coverage_label() -> None:
    assert COVERAGE_LABEL == "structured identifiers only"


def test_public_exports() -> None:
    for name in classification.__all__:
        assert hasattr(classification, name), name
