"""Microsoft Fabric analytics adapter (Warehouse / lakehouse SQL analytics endpoint), PRP-11.

``FabricAnalytics`` is ``SqlAnalytics`` plus a T-SQL dialect, a cloud-validated config, feature
flags from the capability matrix and adapter-local migrations. There is no real driver here
(operator decision: no new third-party dependencies, no pyodbc / mssql-python): the caller
supplies a ``SqlExecutor``. Stub-based tests prove contract conformance ONLY; they are not
evidence that Fabric works in any cloud or region. Only the operator-approved live gate is.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from pydantic import ValidationError

from neurosphere_core.analytics.base import SqlAnalytics, SqlExecutor
from neurosphere_core.analytics.fabric.config import FabricConfig
from neurosphere_core.analytics.fabric.dialect import FabricDialect
from neurosphere_core.analytics.fabric.features import (
    FabricFeatureFlags,
    FeatureFlag,
    resolve_feature_flags,
)
from neurosphere_core.analytics.fabric.migrations import (
    MIGRATIONS,
    Migration,
    MigrationExecutor,
    MigrationReport,
    apply_migrations,
)
from neurosphere_core.analytics.fabric.stub_shims import fabric_stub_shims
from neurosphere_core.errors import InvalidSchemaError

BACKEND: Final = "fabric"

G12_PARITY_GAPS: Final[tuple[str, ...]] = (
    "T-SQL rewrites: the stub rewrites [bracket] quoting, SELECT TOP (n), DATETRUNC and "
    "APPROX_PERCENTILE_CONT ... WITHIN GROUP into SQLite SQL; real Fabric parsing, plans and "
    "error behaviour are not reproduced",
    "bracket quoting vs the stub scan-counter: the counter only matches the ANSI double-quoted "
    "table name, so a declared rewrite normalises brackets before it; any quoting the rule "
    "misses silently disables rows-scanned accounting",
    "quantile emulation: APPROX_PERCENTILE_CONT is emulated as an exact nearest-rank quantile; "
    "the real function interpolates and is approximate, covered only by the compare tolerance",
    "DATETRUNC and APPROX_PERCENTILE_CONT are documented for Fabric Warehouse and SQL analytics "
    "endpoint (Learn, 2026-10-18) but not executed here; TOP, datetime2(6), decimal(38,12) and "
    "?-placeholders over ODBC are not exercised against Fabric",
    "timestamp parameters are bound as ISO-8601 text ending in Z; whether Fabric converts that "
    "to datetime2 implicitly is unverified",
    "throttling and capacity: no Fabric capacity-unit (CU) accounting, smoothing, bursting or "
    "429/throttle behaviour; the stub's cost units are rows scanned times a constant",
    "Entra / managed-identity authentication, token refresh and endpoint TLS are not exercised: "
    "the executor is injected and there is no driver",
    "DDL migrations run against SQLite with the OBJECT_ID guard rewritten to IF NOT EXISTS; "
    "Fabric DW DDL semantics (types, no enforced constraints) are unverified",
    "Government SQL endpoint suffix .fabric.microsoft.us is INFERRED, UNVERIFIED: Learn "
    "documents only the GCC High REST host highapi.fabric.microsoft.us (G01 / G12)",
    "Commercial form <id>.<tenant>.fabric.microsoft.com (SQL analytics endpoint of a Fabric SQL "
    "database) is out of scope and not accepted",
)


class FabricAnalytics(SqlAnalytics):
    """Fabric adapter. Construct directly with a validated ``FabricConfig`` or via
    ``create_adapter``."""

    def __init__(self, *, config: FabricConfig, executor: SqlExecutor) -> None:
        super().__init__(
            backend=BACKEND,
            cloud=config.cloud,
            dialect=FabricDialect(),
            executor=executor,
            schema=config.schema_name,
        )
        self.config = config
        self.feature_flags: FabricFeatureFlags = resolve_feature_flags(
            cloud=config.cloud, region=config.region
        )


def create_adapter(
    *,
    cloud: str,
    region: str,
    config: Mapping[str, Any] | None,
    executor: SqlExecutor | None,
) -> FabricAnalytics:
    """Registry entry point (``neurosphere_core.analytics.fabric:create_adapter``).

    Fails at construction on a host/cloud/region mismatch or a missing executor."""
    data: dict[str, Any] = dict(config or {})
    for key, value in (("cloud", cloud), ("region", region)):
        if data.setdefault(key, value) != value:
            raise InvalidSchemaError(
                f"config {key} differs from the requested {key}", reason="fabric_config_mismatch"
            )
    try:
        parsed = FabricConfig.model_validate(data)
    except ValidationError as exc:
        # Messages name fields and rules only; the config holds no secrets by construction.
        problems = "; ".join(
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()
        )
        raise InvalidSchemaError(
            f"invalid Fabric configuration ({problems})", reason="fabric_config"
        ) from None
    if executor is None:
        raise InvalidSchemaError(
            "a SqlExecutor is required: this package ships no Fabric driver",
            reason="fabric_executor_required",
        )
    return FabricAnalytics(config=parsed, executor=executor)


__all__ = [
    "BACKEND",
    "G12_PARITY_GAPS",
    "MIGRATIONS",
    "FabricAnalytics",
    "FabricConfig",
    "FabricDialect",
    "FabricFeatureFlags",
    "FeatureFlag",
    "Migration",
    "MigrationExecutor",
    "MigrationReport",
    "apply_migrations",
    "create_adapter",
    "fabric_stub_shims",
    "resolve_feature_flags",
]
