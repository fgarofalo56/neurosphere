# GENERATED - do not edit.
# Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
# Regenerate: python packages/contracts/scripts/generate.py
# Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
# pyright: reportAssignmentType=false, reportInvalidTypeForm=false

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import Field, RootModel, StrictInt, StrictStr, StringConstraints


class AdminCommon(RootModel[Any]):
    root: Annotated[Any, Field(title="AdminCommon")]
    """
    Shared definitions for the operator control-plane contracts (admin v1, PRP-37). Definition library only: it declares no root instance shape and is never validated against directly, so it has no examples. No definition here can hold a credential value (A7): credentials appear only as a credential-reference.schema.json document.
    """


class SchemaVersion(RootModel[StrictStr]):
    root: Annotated[StrictStr, Field(pattern="^1\\.(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)$")]
    """
    Contract version of the document, major 1 with additive minor revisions (ADR-0004).
    """


class AdminKind(
    RootModel[
        Literal[
            "producer",
            "connector_config",
            "domain",
            "budget",
            "price_sheet",
            "review_policy",
            "system_setting",
            "notification_channel",
            "notification_subscription",
            "enforcement_binding",
        ]
    ]
):
    root: Literal[
        "producer",
        "connector_config",
        "domain",
        "budget",
        "price_sheet",
        "review_policy",
        "system_setting",
        "notification_channel",
        "notification_subscription",
        "enforcement_binding",
    ]
    """
    Kind of a versioned operator configuration document (AdminConfigDocument.kind). Each kind's body is validated in core by ADMIN_KIND_MODELS (PRP-65). Open-ended: readers must tolerate unknown values.
    """


class ConfigVersion(RootModel[StrictInt]):
    root: Annotated[StrictInt, Field(ge=1)]
    """
    Monotonic version of an operator configuration document, incremented on every accepted write.
    """


class ReasonCode(RootModel[StrictStr]):
    root: Annotated[StrictStr, Field(pattern="^[a-z][a-z0-9_]{0,63}$")]
    """
    Machine reason code in snake_case, never free text (free text could carry names, UPNs or secrets into the audit trail).
    """


class PrincipalId(RootModel[StrictStr]):
    root: Annotated[
        StrictStr,
        Field(
            max_length=512,
            pattern="^(commercial|government):[a-z0-9._-]{1,128}:entra:(person|principal):p-[0-9a-f]{64}$",
        ),
    ]
    """
    Canonical pseudonymous principal id minted by the PRP-06 pseudonymizer: cloud:customer:entra:(person|principal):p-<64 hex>. Never a UPN, email address or raw directory object id.
    """


class CustomerId(RootModel[StrictStr]):
    root: Annotated[StrictStr, Field(pattern="^[a-z0-9._-]{1,128}$")]
    """
    Customer segment of the canonical id grammar (the tenant deployment).
    """


class Cloud(RootModel[Literal["commercial", "government"]]):
    root: Literal["commercial", "government"]
    """
    Azure cloud boundary. Government data is never bridged to Commercial.
    """


class CanonicalId(RootModel[StrictStr]):
    root: Annotated[
        StrictStr,
        Field(
            max_length=512,
            pattern="^(commercial|government):[a-z0-9._-]+:[a-z0-9._-]+:[a-z0-9._-]+:[a-z0-9._/=-]+$",
        ),
    ]
    """
    Canonical id cloud:customer:source:type:id (PRP-01 clarification 7). Grammar owned by catalog/v1; duplicated here as a pattern so admin v1 has no cross-area dependency.
    """


class DomainId(RootModel[StrictStr]):
    root: Annotated[
        StrictStr,
        Field(
            max_length=512,
            pattern="^(commercial|government):[a-z0-9._-]+:[a-z0-9._-]+:domain:[a-z0-9._/=-]+$",
        ),
    ]
    """
    Canonical Domain id (type segment 'domain'). No wildcard or all-domains form exists.
    """


class RecordId(RootModel[StrictStr]):
    root: Annotated[StrictStr, Field(pattern="^[A-Za-z0-9._:-]{1,128}$")]
    """
    Identifier of a record inside a policy or configuration document (assignment, grant, budget, item).
    """


class Slug(RootModel[StrictStr]):
    root: Annotated[StrictStr, Field(pattern="^[a-z0-9][a-z0-9._-]{0,63}$")]
    """
    Lowercase operator-chosen identifier.
    """


class DisplayName(RootModel[StrictStr]):
    root: Annotated[StrictStr, Field(max_length=128, min_length=1)]
    """
    Human-readable label shown in the console. Not an identity attribute: never a person's name, UPN or email.
    """


class Timestamp(RootModel[StrictStr]):
    root: Annotated[
        StrictStr,
        Field(
            pattern="^[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])T([01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9](\\.[0-9]{1,9})?Z$"
        ),
    ]
    """
    RFC 3339 timestamp in UTC (Z suffix required).
    """


class Date(RootModel[StrictStr]):
    root: Annotated[StrictStr, Field(pattern="^[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])$")]
    """
    Calendar date YYYY-MM-DD.
    """


class Etag(RootModel[StrictStr]):
    root: Annotated[StrictStr, Field(max_length=256, min_length=1)]
    """
    Opaque optimistic-concurrency token. A mismatch on write returns the stale_version error.
    """


class Role(
    RootModel[
        Literal[
            "viewer",
            "analyst",
            "domain_steward",
            "admin",
            "security_auditor",
            "interaction_investigator",
        ]
    ]
):
    root: Literal[
        "viewer",
        "analyst",
        "domain_steward",
        "admin",
        "security_auditor",
        "interaction_investigator",
    ]
    """
    Platform role (NS-08). admin, security_auditor and interaction_investigator are privileged and always time-bound. Open-ended: readers must tolerate unknown values.
    """


class GrantPermission(RootModel[Literal["read", "export", "propose_action", "approve", "execute"]]):
    root: Literal["read", "export", "propose_action", "approve", "execute"]
    """
    Permission a resource-scoped grant may carry (mirrors scope/v1 resource_grant).
    """


class DecimalAmount(RootModel[StrictStr]):
    root: Annotated[StrictStr, Field(pattern="^(0|[1-9][0-9]{0,17})(\\.[0-9]{1,12})?$")]
    """
    Non-negative decimal string, up to 18 integer and 12 fractional digits; no exponent, no float.
    """


class Currency(RootModel[StrictStr]):
    root: Annotated[StrictStr, Field(pattern="^[A-Z]{3}$")]
    """
    ISO 4217 alphabetic currency code.
    """


class HttpsUrl(RootModel[StrictStr]):
    root: Annotated[
        StrictStr,
        Field(
            max_length=512,
            pattern="^https://[A-Za-z0-9.-]+(:[0-9]{1,5})?(/[A-Za-z0-9._~%-]{1,128})*/?$",
        ),
    ]
    """
    HTTPS URL with no query string, fragment or userinfo (so no SAS or signed URL can be stored).
    """


class AzureResourceId(RootModel[StrictStr]):
    root: Annotated[
        StrictStr,
        Field(
            max_length=1024,
            pattern="^/subscriptions/[0-9a-fA-F-]{36}/resourceGroups/[A-Za-z0-9._()-]{1,90}/providers/[A-Za-z0-9.]+(/[A-Za-z0-9._-]+/[A-Za-z0-9._-]+)+$",
        ),
    ]
    """
    Azure Resource Manager resource id (/subscriptions/<guid>/resourceGroups/<name>/providers/<namespace>/<type>/<name>...).
    """


class CostTags1(RootModel[StrictStr]):
    root: Annotated[StrictStr, Field(max_length=128, min_length=1)]


class CostTags(
    RootModel[
        dict[
            Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_.-]{0,62}$", strict=True)],
            CostTags1,
        ]
    ]
):
    root: dict[
        Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_.-]{0,62}$", strict=True)],
        CostTags1,
    ]
    """
    Cost allocation tags, the same grammar as cost/v1 CostRecord.tags (#190): at most 16 entries, keys lowercase ^[a-z][a-z0-9_.-]{0,62}$, values 1 to 128 characters. The reserved key cost_center uses the catalog/v1 Grant cost_center pattern. The generated Pydantic model keeps the key and value bounds but not the entry count or the cost_center rule (ADR-0004 projection); both are checked by tests/contracts/validators.py::validate_cost_tags.
    """


class DocPath(RootModel[StrictStr]):
    root: Annotated[
        StrictStr,
        Field(
            max_length=256,
            pattern="^docs/[A-Za-z0-9._/-]{1,200}\\.md(#[a-z0-9-]{1,64})?$",
        ),
    ]
    """
    Repository-relative documentation path (docs/...md), optionally with an anchor.
    """
