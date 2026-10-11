"""Row/matrix builders shared by the capability tests."""

from __future__ import annotations

from typing import Any

from neurosphere_contracts.deployment.v1.capability_matrix_entry import CapabilityMatrixEntry
from neurosphere_core.capabilities import CapabilityMatrix, matrix_from_rows
from neurosphere_core.capabilities.loader import derive_row_id


def raw_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "schema_version": "1.1.0",
        "service": "fabric",
        "feature": "base",
        "cloud": "government",
        "region": "usgovvirginia",
        "sku": None,
        "availability": "available",
        "ga_status": "ga",
        "authorization_scope": "none_claimed",
        "source_url": "https://example.invalid/doc",
        "observed_on": "2026-10-01",
        "notes": None,
    }
    row.update(overrides)
    if "id" not in row:
        known = {k: v for k, v in row.items() if k in CapabilityMatrixEntry.model_fields}
        row["id"] = derive_row_id(CapabilityMatrixEntry.model_construct(**known))
    return row


def entry(**overrides: Any) -> CapabilityMatrixEntry:
    return CapabilityMatrixEntry.model_validate(raw_row(**overrides))


def matrix(*rows: CapabilityMatrixEntry) -> CapabilityMatrix:
    return matrix_from_rows(rows)
