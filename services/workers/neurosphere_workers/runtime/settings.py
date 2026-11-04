"""Worker process settings, one class per concern. Frozen; unrelated env vars are ignored.

* ``NS_WORKER_*`` (:class:`WorkerSettings`): the role list, health bind, polling cadence and the
  worker's own workload identity.
* ``NS_STORE_*`` (:class:`StoreSettings`): the Cosmos database (and, outside local, the account).
  Same names as the API composition so one environment configures both.
* ``NS_AUTH_*`` (:class:`AuthSettings`): the deployment's tenant, customer binding, principal
  pseudonym key and policy container. Same names and semantics as the API (the key MUST be the
  same on both sides or the worker principal is unknown to the policy store).
* ``NS_WORKER_REC_*`` / ``NS_WORKER_EVAL_*``: the two periodic jobs' inputs.
* ``NS_FOUNDRY_*`` (:class:`FoundryWriteSettings`) and ``NS_APIM_*``
  (:class:`ApimWriteSettings`): the write targets (PRP-35 item 4). Same names on the API, which
  imports these classes, so one environment configures both registries. Each is OFF unless its
  ``ENABLED`` flag is set AND its target reference is complete; neither holds a secret (the
  credential is the workload identity, ``DefaultAzureCredential``).

The Cosmos emulator endpoint and key stay ``NS_COSMOS_ENDPOINT``/``NS_COSMOS_KEY`` (local only,
read by ``neurosphere_core.clients``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Final

from neurosphere_connector_foundry_actions import AccountRef
from neurosphere_core.auth.scope import DEFAULT_POLICY_CONTAINER
from neurosphere_core.cloud.profile import CloudName
from neurosphere_core.stores import DEFAULT_DATABASE
from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = [
    "LOCAL_DEFAULT_CUSTOMER_ID",
    "ApimWriteSettings",
    "AuthSettings",
    "EvalSettings",
    "FoundryWriteSettings",
    "RecommendationSettings",
    "StoreSettings",
    "WorkerSettings",
]

#: ``NS_ENV=local`` customer binding when ``NS_AUTH_CUSTOMER_ID`` is unset (the sandbox customer).
LOCAL_DEFAULT_CUSTOMER_ID: Final = "synthco"


def _blank_is_none(value: Any) -> Any:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return value


class WorkerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NS_WORKER_", frozen=True, extra="ignore")

    roles: str | None = None
    health_host: str = "127.0.0.1"
    health_port: int = Field(default=8090, ge=0, le=65535)
    #: Seconds between outbox drains / queue polls.
    poll_seconds: float = Field(default=1.0, gt=0)
    #: Seconds between price-snapshot reloads for roles that price at runtime (aggregates).
    price_refresh_seconds: float = Field(default=60.0, ge=5.0, le=3600.0)
    #: Lease owner name of the action executor; defaults to a per-process name.
    worker_id: str | None = None
    #: The worker's workload identity (Entra service principal / managed identity object id).
    tenant_id: str | None = None
    object_id: str | None = None

    @field_validator("roles", "worker_id", "tenant_id", "object_id", mode="before")
    @classmethod
    def _blank(cls, value: Any) -> Any:
        return _blank_is_none(value)


class StoreSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NS_STORE_", frozen=True, extra="ignore")

    database: str = Field(default=DEFAULT_DATABASE, min_length=1, max_length=255)
    cosmos_account: str | None = None


class AuthSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NS_AUTH_", frozen=True, extra="ignore")

    tenant_id: str | None = None
    customer_id: str | None = None
    pseudonym_key: SecretStr | None = None
    pseudonym_key_reference: str | None = None
    policy_container: str = Field(default=DEFAULT_POLICY_CONTAINER, min_length=1, max_length=255)

    @field_validator("tenant_id", "customer_id", "pseudonym_key_reference", mode="before")
    @classmethod
    def _blank(cls, value: Any) -> Any:
        return _blank_is_none(value)

    def resolved_customer_id(self, env: str) -> str | None:
        if self.customer_id is not None:
            return self.customer_id
        return LOCAL_DEFAULT_CUSTOMER_ID if env == "local" else None


class RecommendationSettings(BaseSettings):
    """``NS_WORKER_REC_*``: the periodic recommendations pipeline."""

    model_config = SettingsConfigDict(env_prefix="NS_WORKER_REC_", frozen=True, extra="ignore")

    #: Sandbox output directory the rule/duplicate/right-sizing projections read. Required.
    data_dir: Path | None = None
    #: Optional JSON file holding a ``CandidatePairConfig``. Without it no model pairing is
    #: configured, so right-sizing produces nothing (pairings are configuration, never invented).
    pairs_file: Path | None = None
    interval_seconds: float = Field(default=3600.0, gt=0)


class EvalSettings(BaseSettings):
    """``NS_WORKER_EVAL_*``: the periodic online evaluation run."""

    model_config = SettingsConfigDict(env_prefix="NS_WORKER_EVAL_", frozen=True, extra="ignore")

    #: Directory with ``datasets.json``, ``rubrics.json``, ``judge_configs.json`` and
    #: ``judge_fixtures.json`` (the sandbox evaluation layout). Required.
    data_dir: Path | None = None
    interval_seconds: float = Field(default=3600.0, gt=0)
    frame_dataset_id: str = "ns-archive-frame"
    frame_dataset_version: str = "1"
    rubric_id: str = "sbx-rubric"
    rubric_version: str = "1.0.0"
    judge_config_id: str = "sbx-judge-commercial"
    judge_config_version: str = "1.0.0"
    rate: float = Field(default=0.1, gt=0, le=1)
    seed: int = 20260101
    run_token_budget: int = Field(default=200_000, ge=0)
    domain_token_budget: int = Field(default=1_000_000, ge=0)
    run_cost_budget: str = "50"
    domain_cost_budget: str = "250"


class FoundryWriteSettings(BaseSettings):
    """``NS_FOUNDRY_*``: the ONE Foundry (Azure AI Services) account a model swap may change.

    The account's cloud is ALWAYS the deployment's cloud (``NS_CLOUD``): there is no cloud
    setting here, so a Government deployment can never be pointed at a Commercial account. A
    Government account yields the advisory connector, which is never registered.
    """

    model_config = SettingsConfigDict(env_prefix="NS_FOUNDRY_", frozen=True, extra="ignore")

    enabled: bool = False
    subscription_id: str | None = None
    resource_group: str | None = None
    account: str | None = None
    location: str | None = None

    @field_validator("subscription_id", "resource_group", "account", "location", mode="before")
    @classmethod
    def _blank(cls, value: Any) -> Any:
        return _blank_is_none(value)

    @property
    def complete(self) -> bool:
        return None not in (self.subscription_id, self.resource_group, self.account, self.location)

    def account_ref(self, cloud: CloudName) -> AccountRef | None:
        """The account in ``cloud``; ``None`` when incomplete; ``ValueError`` when malformed."""
        if not self.complete:
            return None
        return AccountRef(
            cloud=cloud,
            subscription_id=str(self.subscription_id),
            resource_group=str(self.resource_group),
            account=str(self.account),
            location=str(self.location),
        )


class ApimWriteSettings(BaseSettings):
    """``NS_APIM_*``: the ONE registered APIM gateway the gateway connector may manage.

    Only a reference: the registration itself (cloud, ARM resource id, observe/manage mode) is
    read from the gateway registry (``gateways`` container), so an unregistered gateway, or one
    registered in another cloud, is never managed. One gateway per registry: the
    ``WriteTargetRegistry`` keys connectors by manifest name (``apim-gateway``), so a second
    gateway would need a registry keyed by gateway (a follow-up, not this setting).
    """

    model_config = SettingsConfigDict(env_prefix="NS_APIM_", frozen=True, extra="ignore")

    enabled: bool = False
    #: ``gw-<32 hex>``: the id the gateway registry assigned at registration.
    gateway_id: str | None = None
    #: The domain the gateway is registered in (canonical domain id).
    domain_id: str | None = None

    @field_validator("gateway_id", "domain_id", mode="before")
    @classmethod
    def _blank(cls, value: Any) -> Any:
        return _blank_is_none(value)

    @property
    def complete(self) -> bool:
        return self.gateway_id is not None and self.domain_id is not None
