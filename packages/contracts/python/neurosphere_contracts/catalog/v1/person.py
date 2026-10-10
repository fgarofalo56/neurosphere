# GENERATED - do not edit.
# Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
# Regenerate: python packages/contracts/scripts/generate.py
# Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
# pyright: reportAssignmentType=false, reportInvalidTypeForm=false

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr

from . import common


class Person(BaseModel):
    """
    Person as a pseudonymous principal only. There is deliberately no email, name, UPN, display_name, free-text or attributes field; re-identification is a policy-store concern, not a contract field. The id segment of the canonical ID is the pseudonym. Python validators: validate_canonical_id_fullmatch (Python re.search lets '$' match before a trailing newline; the suite re-checks every canonical ID with re.fullmatch), validate_customer_segment_matches (customer segment of every canonical ID equals customer_id), validate_timestamp_order (created_at <= updated_at), validate_person_id_is_pseudonym (id segment equals principal_pseudonym).
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    schema_version: common.SchemaVersion
    id: Annotated[
        StrictStr,
        Field(
            max_length=512,
            pattern="^(commercial|government):[a-z0-9._-]+:[a-z0-9._-]+:person:psn_[a-z0-9]{16,64}$",
        ),
    ]
    """
    Canonical ID whose id segment is the principal pseudonym (psn_...).
    """
    entity_type: Literal["person"]
    version: common.EntityVersion
    etag: common.Etag
    lifecycle_status: common.LifecycleStatus
    created_at: common.Timestamp
    updated_at: common.Timestamp
    cloud: common.Cloud
    customer_id: common.CustomerId
    principal_pseudonym: Annotated[StrictStr, Field(pattern="^psn_[a-z0-9]{16,64}$")]
    """
    Stable pseudonym produced by the pseudonymization service.
    """
    pseudonym_scheme: common.Token
    """
    Pseudonymization scheme and key version, for rotation.
    """
    principal_kind: Literal["human", "workload", "unknown"] | None = "unknown"
    domain_id: common.DomainId | None = None
    """
    Home domain when known; people may act across domains.
    """
