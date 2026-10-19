"""Reference migration steps over ``synthetic_snapshot`` documents (tests and docs only).

Shows expand-then-contract: 0.2.0 adds ``label`` and deprecates ``legacy_label``; 0.3.0 removes it.
"""

from __future__ import annotations

from typing import Any

from neurosphere_core.migrations.models import MigrationStep, MigrationTarget

__all__ = ["sample_steps"]


def _up_expand(doc: dict[str, Any]) -> dict[str, Any]:
    doc["label"] = doc["legacy_label"]
    return doc


def _down_expand(doc: dict[str, Any]) -> dict[str, Any]:
    doc.pop("label", None)
    return doc


def _up_contract(doc: dict[str, Any]) -> dict[str, Any]:
    doc.pop("legacy_label", None)
    return doc


def _down_contract(doc: dict[str, Any]) -> dict[str, Any]:
    doc["legacy_label"] = doc["label"]
    return doc


def sample_steps(
    name: str, target: MigrationTarget = MigrationTarget.COSMOS_DOCUMENTS
) -> list[MigrationStep]:
    """Two compatible steps for scope ``name``."""
    return [
        MigrationStep(
            id=f"{name}-0001-add-label",
            version=1,
            target=target,
            name=name,
            description="Add label (copy of legacy_label); deprecate legacy_label.",
            release="0.2.0",
            deprecates=["legacy_label"],
            up=_up_expand,
            down=_down_expand,
        ),
        MigrationStep(
            id=f"{name}-0002-drop-legacy-label",
            version=2,
            target=target,
            name=name,
            description="Remove legacy_label (deprecated in 0.2.0).",
            release="0.3.0",
            removes=["legacy_label"],
            up=_up_contract,
            down=_down_contract,
        ),
    ]
