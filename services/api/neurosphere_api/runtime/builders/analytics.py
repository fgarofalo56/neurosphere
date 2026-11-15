"""Analytics adapter builder (PRP-11 round 2 item 3): selects the backend named by settings.

``analytics_adapter`` is OPTIONAL: a deployment with no backend is valid and stays ready. The
dashboards never read analytics data (they serve Cosmos hot aggregates); this builder only
selects the adapter, publishes it on ``app.state`` and makes it health-reportable through the
existing ``AnalyticsProbe``:

* ``app.state.analytics_adapter``: the adapter (absent when disabled or failed);
* ``app.state.analytics_region``: the region the capability matrix was checked for;
* ``app.state.analytics_health``: an async callable running one bounded one-row statement.

Settings (names only; never a credential, the executor uses a managed-identity token):
``NS_ANALYTICS_BACKEND`` (``none`` default, ``fixture``, ``fabric``, ``synapse``,
``databricks``), ``NS_ANALYTICS_REGION`` and, for Databricks, ``NS_ANALYTICS_DATABRICKS_HOST``,
``_WAREHOUSE_ID``, ``_CATALOG``, ``_SCHEMA``. The cloud comes from ``NS_CLOUD``.

Reason codes (never values): ``analytics_settings_invalid``, ``analytics_fixture_not_local``,
``analytics_executor_unavailable`` (Fabric and Synapse: no TDS driver is approved),
``analytics_config_invalid`` (including a host of the other cloud), the matrix reason code for a
backend the capability matrix disables, ``analytics_government_unverified`` (the Databricks
token audience is verified for Commercial only), ``analytics_build_error``.

Test fakes: ``ctx.overrides.backend("analytics_http_client")`` (an ``httpx.AsyncClient``, for
example over ``httpx.MockTransport``) together with ``backend("analytics_token_provider")``.
Nothing is connected at build time.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from decimal import Decimal
from typing import Any, Final, Literal, cast

from neurosphere_core.analytics.base import (
    ExecutionLimits,
    Statement,
    create_adapter,
    list_backends,
)
from neurosphere_core.analytics.databricks import (
    DatabricksConfig,
    DatabricksStatementExecutor,
    create_databricks_executor,
)
from neurosphere_core.analytics.databricks.executor import TokenProvider
from neurosphere_core.errors import CapabilityUnavailableError, InvalidSchemaError
from pydantic import BaseModel, ConfigDict, ValidationError

from neurosphere_api.runtime.builders import (
    BuildContext,
    BuilderSpec,
    ComponentUnavailableError,
)
from neurosphere_api.runtime.status import is_reason_code

__all__ = ["BUILDER", "COMPONENTS", "AnalyticsSettings", "build"]

COMPONENTS: Final = ("analytics_adapter",)

_log = logging.getLogger("neurosphere_api.runtime")

Backend = Literal["none", "fixture", "fabric", "synapse", "databricks"]
_HEALTH_LIMITS: Final = ExecutionLimits(max_rows_scanned=1, max_cost_units=Decimal(1))
_HEALTH_STATEMENT: Final = Statement(sql="SELECT 1", params=())


class AnalyticsSettings(BaseModel):
    """``NS_ANALYTICS_*``. Credentials are never settings."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    backend: Backend = "none"
    region: str | None = None
    databricks_host: str | None = None
    databricks_warehouse_id: str | None = None
    databricks_catalog: str | None = None
    databricks_schema: str | None = None

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> AnalyticsSettings:
        env = os.environ if environ is None else environ
        values: dict[str, str] = {}
        for field, name in (
            ("backend", "NS_ANALYTICS_BACKEND"),
            ("region", "NS_ANALYTICS_REGION"),
            ("databricks_host", "NS_ANALYTICS_DATABRICKS_HOST"),
            ("databricks_warehouse_id", "NS_ANALYTICS_DATABRICKS_WAREHOUSE_ID"),
            ("databricks_catalog", "NS_ANALYTICS_DATABRICKS_CATALOG"),
            ("databricks_schema", "NS_ANALYTICS_DATABRICKS_SCHEMA"),
        ):
            if env.get(name):
                values[field] = env[name].strip().lower() if field == "backend" else env[name]
        return cls.model_validate(values)


def _matrix_reason(code: str | None) -> str:
    return code if code and is_reason_code(code) else "capability_unavailable"


def _install(ctx: BuildContext, analytics: AnalyticsSettings) -> None:
    cloud = ctx.settings.cloud_profile.cloud.value
    if analytics.backend == "fixture":
        if ctx.settings.env != "local":
            raise ComponentUnavailableError("analytics_fixture_not_local")
        region = analytics.region or "local"
        adapter: Any = create_adapter("fixture", cloud=cloud, region=region, sandbox=True)
        ctx.app.state.analytics_adapter = adapter
        ctx.app.state.analytics_region = region
        return
    if analytics.backend in ("fabric", "synapse"):
        raise ComponentUnavailableError("analytics_executor_unavailable")
    _install_databricks(ctx, analytics, cloud)


def _databricks_config(analytics: AnalyticsSettings, cloud: str) -> DatabricksConfig:
    if not (
        analytics.region
        and analytics.databricks_host
        and analytics.databricks_warehouse_id
        and analytics.databricks_catalog
        and analytics.databricks_schema
    ):
        raise ComponentUnavailableError("analytics_settings_invalid")
    try:
        return DatabricksConfig.model_validate(
            {
                "cloud": cloud,
                "region": analytics.region,
                "workspace_host": analytics.databricks_host,
                "warehouse_id": analytics.databricks_warehouse_id,
                "catalog": analytics.databricks_catalog,
                "schema_name": analytics.databricks_schema,
            }
        )
    except ValidationError:
        # Never echo input values: a host of the other cloud lands here, with no fallback.
        raise ComponentUnavailableError("analytics_config_invalid") from None


def _executor(ctx: BuildContext, config: DatabricksConfig) -> DatabricksStatementExecutor:
    client = ctx.overrides.backend("analytics_http_client")
    token = ctx.overrides.backend("analytics_token_provider")
    if client is not None and callable(token):
        ctx.on_shutdown(client.aclose)  # type: ignore[attr-defined]
        return DatabricksStatementExecutor(
            client,
            cast("TokenProvider", token),
            warehouse_id=config.warehouse_id,
            poll_interval_s=0.05,
        )
    executor, close = create_databricks_executor(
        host=config.workspace_host,
        warehouse_id=config.warehouse_id,
        authority=ctx.settings.cloud_profile.login_host,
    )
    ctx.on_shutdown(close)
    return executor


def _install_databricks(ctx: BuildContext, analytics: AnalyticsSettings, cloud: str) -> None:
    config = _databricks_config(analytics, cloud)
    try:
        statuses = list_backends(cloud=cloud, region=config.region)
    except CapabilityUnavailableError as exc:
        raise ComponentUnavailableError(_matrix_reason(exc.reason)) from None
    except InvalidSchemaError:
        raise ComponentUnavailableError("analytics_config_invalid") from None
    for status in statuses:
        if status.name == "databricks" and status.status != "supported":
            raise ComponentUnavailableError(_matrix_reason(status.reason_code))
    if cloud == "government":
        raise ComponentUnavailableError("analytics_government_unverified")
    executor = _executor(ctx, config)
    adapter: Any = create_adapter(
        "databricks",
        cloud=cloud,
        region=config.region,
        config=config.model_dump(mode="json", exclude={"cloud", "region"}),
        executor=executor,
    )

    async def health() -> bool:
        """One bounded one-row statement; raises (so the badge is ``delayed``) on failure."""
        await executor.execute(_HEALTH_STATEMENT, limits=_HEALTH_LIMITS)
        return True

    ctx.app.state.analytics_adapter = adapter
    ctx.app.state.analytics_region = config.region
    ctx.app.state.analytics_health = health


def build(ctx: BuildContext) -> None:
    try:
        analytics = AnalyticsSettings.from_env(ctx.environ)
    except ValidationError:
        ctx.failed("analytics_adapter", "analytics_settings_invalid")
        return
    if analytics.backend == "none":
        ctx.disabled("analytics_adapter")
        return
    try:
        ctx.attempt("analytics_adapter", lambda: _install(ctx, analytics))
    except Exception as exc:
        _log.error("analytics adapter build raised %s", type(exc).__name__)
        ctx.failed("analytics_adapter", "analytics_build_error")


BUILDER: Final = BuilderSpec("analytics", COMPONENTS, build)
