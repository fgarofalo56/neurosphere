# GENERATED - do not edit.
# Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
# Regenerate: python packages/contracts/scripts/generate.py
# Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
# pyright: reportAssignmentType=false, reportInvalidTypeForm=false

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr


class CapabilityMatrixEntry(BaseModel):
    """
    One observed row of the capability matrix (NS-07, PRP-01 Clarification 17; amended in place for PRP-02 Item 0, schema_version 1.1.0): whether a service feature is offered for a cloud, region and SKU, as stated by a cited source on a given date. Contract only; data and loader belong to PRP-02. availability, ga_status and authorization_scope are three independent fields and must never be merged into one status. authorization_scope is a citation of the audit-scope text the source gives for the Azure service, or the literal none_claimed; it is never a claim that NeuroSphere or the dependency is authorized for any agency, an ATO or compliance parity. Unavailable combinations are disabled with a reason, never filled by routing to another cloud. Rules JSON Schema cannot express are checked by the Python validator check_capability_matrix in tests/contracts/validators.py (PRP-01 item 7): (service, feature, cloud, region, sku) is unique across a matrix; id is unique and equals the derived convention; observed_on is not in the future; a government wildcard region covers government regions only.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    schema_version: Annotated[StrictStr, Field(pattern="^1\\.(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)$")]
    """
    Contract version of this document (semver within major 1).
    """
    id: Annotated[StrictStr, Field(pattern="^[a-z][a-z0-9_.-]{5,254}$")]
    """
    Stable canonical citation handle for this row, used by ADRs and capability_unavailable reasons. Convention (enforced by check_capability_matrix so it cannot drift from the uniqueness key): <service>.<feature>.<cloud>.<region>.<sku-or-any>, lowercased, with any for a null sku and for the * region; a sku is lowercased and each run of characters outside a-z, 0-9, _ and - becomes a single -, trimmed of leading and trailing -.
    """
    service: Annotated[StrictStr, Field(pattern="^[a-z][a-z0-9_]{1,63}$")]
    """
    Azure service key, snake_case (for example azure_openai, cosmos_db, fabric, synapse, databricks, ai_search, event_hubs).
    """
    feature: Annotated[StrictStr, Field(pattern="^[a-z][a-z0-9_]{1,127}$")]
    """
    Feature key within the service, snake_case (for example model_gpt_4o, private_endpoint, change_feed). Use base for the service itself.
    """
    cloud: Literal["commercial", "government"]
    """
    Azure cloud this row describes.
    """
    region: Annotated[StrictStr, Field(pattern="^(\\*|[a-z][a-z0-9]{2,39})$")]
    """
    Lowercase ARM region name, global for non-regional offerings, or the wildcard * only when the cited source states the row holds for every region of the cloud. Government rows use usgov*/usdod* regions, global or *; a Government * covers Government regions only and never matches a Commercial region. Commercial rows may not use usgov*/usdod* regions.
    """
    sku: Annotated[
        StrictStr | None,
        Field(max_length=128, min_length=1, pattern="^[A-Za-z0-9][A-Za-z0-9 ._()-]*$"),
    ]
    """
    SKU or tier the row applies to; null when the row is SKU-independent (no * wildcard for sku).
    """
    availability: Literal["available", "preview", "unavailable", "unverified"]
    """
    Is it offered here at all. unverified means the source does not say. Independent of ga_status and authorization_scope.
    """
    ga_status: Literal["ga", "preview", "not_applicable", "unverified"]
    """
    Release maturity. not_applicable when maturity has no meaning (for example an unavailable row); unverified means the source does not say. Independent of availability and authorization_scope.
    """
    authorization_scope: Annotated[StrictStr, Field(max_length=500, min_length=1)]
    """
    Citation of the audit-scope document or status text the source gives for this service in this cloud (for example 'FedRAMP High audit scope per <document>, 2026-09-21' or 'FedRAMP High assessment in progress; not authorized'), or the literal none_claimed. A citation only: never a claim that NeuroSphere or the dependency is authorized for an agency. Independent of availability and ga_status.
    """
    source_url: Annotated[StrictStr, Field(max_length=2048, pattern="^https://[^\\s]+$")]
    """
    HTTPS URL of the authoritative source for this row. Recorded, never fetched by tests.
    """
    observed_on: Annotated[
        StrictStr, Field(pattern="^[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])$")
    ]
    """
    Date (YYYY-MM-DD, UTC) the source was observed.
    """
    notes: Annotated[StrictStr | None, Field(max_length=2000)]
    """
    Caveats (for example region subset, quota or preview limits); null when none.
    """
