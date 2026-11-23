# GENERATED - do not edit.
# Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
# Regenerate: python packages/contracts/scripts/generate.py
# Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
# pyright: reportAssignmentType=false, reportInvalidTypeForm=false

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel, StrictInt, StrictStr


class Span(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    start: Annotated[StrictInt, Field(ge=0)]
    end: Annotated[StrictInt, Field(ge=0)]


class DetectedCategory(
    RootModel[
        Literal[
            "private_key",
            "jwt",
            "bearer_token",
            "cloud_access_key",
            "vendor_api_key",
            "connection_string",
            "url_with_credentials",
            "password_assignment",
            "payment_card",
            "iban",
            "us_ssn",
            "email_address",
            "phone_number",
            "ip_address",
            "mac_address",
            "guid",
            "customer_dictionary_term",
            "customer_identifier_pattern",
            "other",
        ]
    ]
):
    root: Annotated[
        Literal[
            "private_key",
            "jwt",
            "bearer_token",
            "cloud_access_key",
            "vendor_api_key",
            "connection_string",
            "url_with_credentials",
            "password_assignment",
            "payment_card",
            "iban",
            "us_ssn",
            "email_address",
            "phone_number",
            "ip_address",
            "mac_address",
            "guid",
            "customer_dictionary_term",
            "customer_identifier_pattern",
            "other",
        ],
        Field(title="DetectedCategory"),
    ]
    """
    Kind of sensitive content a detector found; open-ended: readers must tolerate unknown values. The first eight are credential categories (CredentialCategory).
    """


class CredentialCategory(
    RootModel[
        Literal[
            "private_key",
            "jwt",
            "bearer_token",
            "cloud_access_key",
            "vendor_api_key",
            "connection_string",
            "url_with_credentials",
            "password_assignment",
        ]
    ]
):
    root: Annotated[
        Literal[
            "private_key",
            "jwt",
            "bearer_token",
            "cloud_access_key",
            "vendor_api_key",
            "connection_string",
            "url_with_credentials",
            "password_assignment",
        ],
        Field(title="CredentialCategory"),
    ]
    """
    Categories that are credentials. Closed set: always replaced, never kept, and never listed in a capture policy's kept categories.
    """


class ContentPartKind(
    RootModel[Literal["prompt", "response", "tool_input", "tool_output", "system_instructions"]]
):
    root: Annotated[
        Literal["prompt", "response", "tool_input", "tool_output", "system_instructions"],
        Field(title="ContentPartKind"),
    ]
    """
    Which part of an interaction a piece of content is.
    """


class DetectionFinding(BaseModel):
    """
    One detector result for one content part of an interaction (opt-in content capture, PRP-99). A fragment: it has no schema_version of its own and is embedded by RedactedContent (and, in later items, the interaction record). It carries a category, counts and offsets into the redacted text, never the matched text. Rule JSON Schema expresses with if/then: a credential category (CredentialCategory) requires action `replaced`; a credential can never be kept. Pydantic ignores if/then (ADR-0004), so consumers validate against the JSON Schema.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    category: DetectedCategory
    part: ContentPartKind
    detector_id: Annotated[StrictStr, Field(pattern="^[a-z0-9][a-z0-9._-]{0,63}$")]
    """
    Detector that produced the finding (lowercase slug).
    """
    detector_version: Annotated[StrictStr, Field(pattern="^[0-9]+\\.[0-9]+\\.[0-9]+$")]
    """
    Detector version, semantic version without prefix.
    """
    count: Annotated[StrictInt, Field(ge=1, le=100000)]
    """
    Number of matches of this category in the part.
    """
    action: Literal["replaced", "kept"]
    """
    What redaction did with the matches: `replaced` with a placeholder, or `kept` as written (only for non-credential categories a capture policy keeps).
    """
    confidence: Literal["high", "medium", "low"]
    """
    Detector confidence.
    """
    spans: Annotated[list[Span] | None, Field(max_length=64, validate_default=True)] = []
    """
    Character offsets of the matches into the redacted text of the part. Offsets only; never the matched text.
    """
