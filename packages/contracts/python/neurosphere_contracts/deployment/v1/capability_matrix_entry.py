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
    One observed row of the capability matrix (NS-07, PRP-01 Clarification 17): whether a service feature is offered for a cloud, region and SKU, as stated by a cited source on a given date. Contract only; data and loader belong to PRP-02. availability, ga_status and authorization_scope are three independent fields with disjoint vocabularies and must never be merged into one status. authorization_scope records the external audit scope the cited source lists for the Azure service; it is not a claim that NeuroSphere holds FedRAMP authorization, an ATO or compliance parity. Unavailable combinations are disabled with a reason, never filled by routing to another cloud. Rules JSON Schema cannot express are checked by the Python validator check_capability_matrix in tests/contracts/test_capability_matrix.py (PRP-01 item 7): (service, feature, cloud, region, sku) is unique across a matrix; observed_on is not in the future.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    schema_version: Annotated[StrictStr, Field(pattern="^1\\.[0-9]+\\.[0-9]+$")]
    """
    Contract version of this document (semver within major 1).
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
    region: Annotated[StrictStr, Field(pattern="^[a-z][a-z0-9]{2,39}$")]
    """
    Lowercase ARM region name, or global for non-regional offerings. Government rows use usgov*/usdod* regions; Commercial rows may not.
    """
    sku: Annotated[
        StrictStr | None,
        Field(max_length=128, min_length=1, pattern="^[A-Za-z0-9][A-Za-z0-9 ._()-]*$"),
    ]
    """
    SKU or tier the row applies to; null when the row is SKU-independent.
    """
    availability: Literal["available", "limited", "unavailable", "unknown"]
    """
    Is it offered here at all. Independent of ga_status and authorization_scope.
    """
    ga_status: Literal[
        "ga", "public_preview", "private_preview", "deprecated", "retired", "unknown"
    ]
    """
    Release maturity. Independent of availability and authorization_scope.
    """
    authorization_scope: Annotated[
        list[
            Literal[
                "fedramp_high",
                "fedramp_moderate",
                "dod_il2",
                "dod_il4",
                "dod_il5",
                "dod_il6",
                "not_in_scope",
                "unknown",
            ]
        ],
        Field(min_length=1),
    ]
    """
    Audit scopes the cited source lists for this service in this cloud. not_in_scope and unknown must stand alone. Independent of availability and ga_status.
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
