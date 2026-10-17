"""Per-cloud Foundry endpoint table, keyed by ``CloudName``.

Every value is copied from Microsoft Learn (observed 2026-10-17); nothing is derived from user
input except the resource and project names, which are validated before use:

- Commercial project endpoint ``https://{resource}.services.ai.azure.com/api/projects/{project}``
  and token scope ``https://ai.azure.com/.default``:
  https://learn.microsoft.com/rest/api/microsoft-foundry/aiproject (API version v1; scope
  ``https://ai.azure.com/.default``) and
  https://learn.microsoft.com/azure/foundry/how-to/develop/sdk-overview (endpoint form).
- Government project endpoint ``https://{resource}.services.ai.azure.us/api/projects/{project}``
  and token scope ``https://ai.azure.us/.default``:
  https://learn.microsoft.com/azure/foundry/concepts/foundry-azure-government and
  https://learn.microsoft.com/azure/foundry/agents/concepts/azure-government
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from neurosphere_core.cloud.profile import CloudName

__all__ = ["FOUNDRY_ENDPOINTS", "FoundryEndpoints", "project_endpoint"]

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,62}[A-Za-z0-9]$")


@dataclass(frozen=True)
class FoundryEndpoints:
    """Frozen Foundry hosts for one cloud."""

    project_host_suffix: str
    token_scope: str
    portal_url: str | None


FOUNDRY_ENDPOINTS: dict[CloudName, FoundryEndpoints] = {
    CloudName.COMMERCIAL: FoundryEndpoints(
        project_host_suffix=".services.ai.azure.com",
        token_scope="https://ai.azure.com/.default",  # noqa: S106  # public OAuth scope, not a secret
        portal_url=None,
    ),
    CloudName.GOVERNMENT: FoundryEndpoints(
        project_host_suffix=".services.ai.azure.us",
        token_scope="https://ai.azure.us/.default",  # noqa: S106  # public OAuth scope, not a secret
        portal_url="https://ai.azure.us/nextgen",
    ),
}


def project_endpoint(cloud: CloudName, resource: str, project: str) -> str:
    """Build the documented project endpoint for ``cloud`` after validating both names."""
    for label, value in (("resource", resource), ("project", project)):
        if not _NAME_RE.fullmatch(value):
            raise ValueError(f"invalid Foundry {label} name")
    host = FOUNDRY_ENDPOINTS[cloud].project_host_suffix
    return f"https://{resource}{host}/api/projects/{project}"
