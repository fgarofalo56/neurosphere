"""``SynapseAnalytics``: the shared SQL adapter bound to a Synapse mode and cloud (PRP-11 item 3).

Construction validates everything that can be validated offline (config shape, cloud, region,
host form, host/mode agreement) before an executor is accepted, so a bad configuration never
yields a half-built adapter. Scope, planning, budgets and decoding are inherited unchanged.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from neurosphere_core.analytics.base import Cloud, SqlAnalytics, SqlExecutor
from neurosphere_core.analytics.base.dialect import Dialect
from neurosphere_core.analytics.synapse.config import (
    SynapseConfig,
    parse_config,
    resolve_endpoint,
)
from neurosphere_core.analytics.synapse.dialect import (
    SynapseDedicatedDialect,
    SynapseServerlessDialect,
)
from neurosphere_core.analytics.synapse.migrations import Migration, migrations_for


def dialect_for(config: SynapseConfig) -> Dialect:
    if config.mode == "dedicated":
        return SynapseDedicatedDialect()
    return SynapseServerlessDialect()


class SynapseAnalytics(SqlAnalytics):
    def __init__(
        self,
        *,
        cloud: Cloud,
        region: str,
        config: SynapseConfig | Mapping[str, Any],
        executor: SqlExecutor,
    ) -> None:
        parsed = parse_config(config)
        host = resolve_endpoint(parsed, cloud=cloud, region=region)
        super().__init__(
            backend=f"synapse-{parsed.mode}",
            cloud=cloud,
            dialect=dialect_for(parsed),
            executor=executor,
            schema=parsed.schema_name,
        )
        self.config = parsed
        self.region = region
        self.endpoint_host = host

    @property
    def mode(self) -> str:
        return self.config.mode

    def migrations(self) -> tuple[Migration, ...]:
        return migrations_for(self.config)
