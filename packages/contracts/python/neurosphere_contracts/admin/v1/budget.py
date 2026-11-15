# GENERATED - do not edit.
# Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
# Regenerate: python packages/contracts/scripts/generate.py
# Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
# pyright: reportAssignmentType=false, reportInvalidTypeForm=false

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel, StrictInt

from . import common


class ThresholdsPercentItem(RootModel[StrictInt]):
    root: Annotated[StrictInt, Field(ge=1, le=1000)]


class SpendBudget(BaseModel):
    """
    A spend budget for one domain and period (PRP-44; evaluated against the cost ledger by PRP-46). Titled SpendBudget because query/v1 already exports a Budget (the query execution budget). amount is a decimal string in currency, never a float. thresholds_percent are alert points as integer percentages of amount (strictly ascending, so 50, 80, 100, 120). tags_filter narrows the budget to CostRecord rows whose tags contain every listed key and value; absent means every row of the domain. Rules JSON Schema cannot express (thresholds strictly ascending) are checked by tests/contracts/validators.py::check_budget_thresholds_ascending.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    schema_version: common.SchemaVersion
    budget_id: common.Slug
    domain_id: common.DomainId
    period: Literal["monthly", "quarterly", "annual"]
    amount: common.DecimalAmount
    currency: common.Currency
    thresholds_percent: Annotated[list[ThresholdsPercentItem], Field(max_length=10, min_length=1)]
    tags_filter: common.CostTags | None = None
    """
    Absent means every cost row of the domain.
    """
