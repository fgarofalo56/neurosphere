"""Settings for the ``foundry_discovery`` role (``NS_FOUNDRY_DISCOVERY_*``).

No secret settings: the Foundry call authenticates with the workload's managed identity through
the connector's ``default_token_provider``.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = ["FoundryDiscoverySettings", "ProjectRef"]

#: A configured project: ``(resource_name, project_name)``.
ProjectRef = tuple[str, str]

_DOMAIN_ID = re.compile(r"(commercial|government):[a-z0-9._-]+:[a-z0-9._-]+:domain:[a-z0-9._/=-]+")


class FoundryDiscoverySettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="NS_FOUNDRY_DISCOVERY_", frozen=True, extra="ignore", populate_by_name=True
    )

    #: Comma list of ``resource/project`` pairs (Foundry resource name, project name).
    projects: str | None = None
    #: Domain id the discovered entities are attributed to (required with ``projects``).
    domain_id: str | None = None
    #: Seconds between discovery passes (bounded below so a typo cannot hammer the API).
    interval_seconds: float = Field(default=900.0, ge=60.0, le=86400.0)
    #: Per-list cap on agents and on deployments, per project, per tick.
    max_items: int = Field(default=500, ge=1, le=5000)
    #: Per-list page budget of the REST reader, per project, per tick.
    max_pages: int = Field(default=10, ge=1, le=100)

    @field_validator("projects", "domain_id", mode="before")
    @classmethod
    def _blank(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip() or None
        return value

    @property
    def domain_id_valid(self) -> bool:
        """The domain id must be a canonical id (``cloud:customer:source:domain:id``)."""
        return self.domain_id is not None and _DOMAIN_ID.fullmatch(self.domain_id) is not None

    @property
    def unconfigured(self) -> bool:
        """True when neither a project list nor a domain id is set (the role then idles)."""
        return not self.project_pairs_raw and self.domain_id is None

    @property
    def project_pairs_raw(self) -> tuple[str, ...]:
        raw = self.projects or ""
        return tuple(dict.fromkeys(part.strip() for part in raw.split(",") if part.strip()))

    def parse_projects(self) -> tuple[ProjectRef, ...]:
        """``(resource, project)`` pairs; raises ``ValueError`` on an entry not shaped so."""
        out: list[ProjectRef] = []
        for item in self.project_pairs_raw:
            resource, sep, project = item.partition("/")
            if not sep or not resource.strip() or not project.strip() or "/" in project:
                raise ValueError("projects entries must look like resource/project")
            out.append((resource.strip(), project.strip()))
        return tuple(dict.fromkeys(out))
