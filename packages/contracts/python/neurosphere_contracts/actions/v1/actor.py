# GENERATED - do not edit.
# Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
# Regenerate: python packages/contracts/scripts/generate.py
# Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
# pyright: reportAssignmentType=false, reportInvalidTypeForm=false

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr


class Actor(BaseModel):
    """
    Pseudonymous reference to the principal that performed or requested an operation (Clarification 8: no email, display name or other free-text identity field). Used by ActionIntent, ApprovalDecision and AuditRecord. Derived server-side from validated identity; never taken from a request body or model output.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    principal_pseudonym: Annotated[StrictStr, Field(pattern="^[a-z0-9][a-z0-9._-]{0,127}$")]
    """
    Stable pseudonym of the principal, as issued by the policy store. Re-identification is a policy-store concern, not a contract field.
    """
    principal_kind: Literal["user", "service_principal", "managed_identity", "agent"]
    """
    Kind of principal.
    """
    on_behalf_of: Annotated[StrictStr | None, Field(pattern="^[a-z0-9][a-z0-9._-]{0,127}$")]
    """
    Pseudonym of the user an agent, copilot or MCP client is acting for; null when the principal acts for itself.
    """
