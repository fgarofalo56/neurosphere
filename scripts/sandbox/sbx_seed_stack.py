"""Seed the local real stack with synthetic data through the real paths (PRP-29 item 10).

    python scripts/sandbox/sbx_seed_stack.py [--profile small|demo] [--operator-object-id <oid>]

Exit 0 and, on stdout and nothing else,
``{"seeded": {"<category>": n, ...}, "skipped_existing": n}``.
Progress and errors go to stderr. Exit 2 = refused (non-loopback endpoint, bad configuration),
3 = a landing timeout or a failed seed step.

Every category goes through the real path, never a raw document write:

* telemetry and cost -> Event Hubs (``HubSeam``) -> the ingestion/projections/aggregates workers
  (which run separately: compose ``workers`` or in-process in tests) -> ledger, aggregates,
  catalog and archive blobs. The wait is bounded by ONE timeout and checks sparsely.
  The generated world is rebased in time: its epoch is moved so the newest event is 30 minutes
  before the run (everything within the profile's days of that). A re-run recovers the first
  run's shift from the ledger, so ids, windows and keys are identical and nothing is duplicated;
  on a later day the data stays where it was (older). Drop the volumes to re-age it.
* catalog entities (domains, owners, models, grounding sources, tools, agents, people) ->
  ``CatalogRepository.create_entity`` under the workers' scope, after the edges have landed.
* grants (the worker principal, the synthetic personas and ``--operator-object-id``) ->
  ``sbx_grant_operator.grant_operator`` into the policy store.
* price sheet -> ``CosmosPriceSnapshotStore`` (sync client, off the event loop).
* recommendations -> the worker pipeline into ``CosmosRecommendationStore``; a subset is routed to
  review through ``HitlReviewRouter(HitlService)``.
* evaluations -> the worker offline pipeline with ``RecordedFixtureJudge`` into
  ``CosmosEvaluationStore``.
* intents -> ``ActionService`` (the construction of the API's planes builder), only up to
  ``drafted`` / ``validated`` / ``awaiting_confirmation``. Nothing is confirmed or executed.
* reports -> ``CosmosReportStore``; MCP servers -> ``McpRegistry`` over ``CosmosMcpServerStore``
  with ``.invalid`` hosts (never contacted).

Local emulators only: Cosmos, Event Hubs and Blob endpoints must be loopback (``sbx_guard``; there
is no override). Idempotent: a second run creates nothing and reports the existing items under
``skipped_existing``.

Environment (same names as the API and the workers, so one environment configures all three):
``NS_ENV`` (must be ``local``), ``NS_COSMOS_ENDPOINT`` (default ``http://127.0.0.1:8081``),
``NS_COSMOS_KEY`` (emulator, optional), ``NS_EVENTHUBS_CONNECTION_STRING`` (default: the emulator),
``NS_BLOB_CONNECTION_STRING`` (default: Azurite), ``NS_STORE_DATABASE`` (default ``neurosphere``;
never a ``sandbox-`` name), ``NS_AUTH_CUSTOMER_ID`` (default ``synthco``), ``NS_AUTH_TENANT_ID`` or
``NS_WORKER_TENANT_ID`` (required GUID), ``NS_WORKER_OBJECT_ID`` (required GUID; the workers' own
identity, granted here), ``NS_AUTH_PSEUDONYM_KEY[_REFERENCE]`` (optional locally),
``NS_ARCHIVE_CONTAINER`` (the workers' archive container), ``NS_INGESTION_EVENTHUB_NAME``,
``NS_SEED_WAIT_SECONDS`` (default 300; landing), ``NS_SEED_DRAIN_SECONDS`` (default 300; then
waiting for the aggregates role to reach the newest events, warning only) and
``NS_SEED_POLL_SECONDS`` (default 5).
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import contextlib
import hashlib
import io
import json
import math
import os
import sys
import tempfile
import time
import uuid
from collections.abc import Awaitable, Callable, Iterator, Mapping, Sequence
from contextlib import AsyncExitStack
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Final, Protocol, cast
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
for _path in (HERE, REPO):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import sbx_grant_operator as grants  # noqa: E402
from azure.cosmos import CosmosClient as SyncCosmosClient  # noqa: E402
from azure.cosmos.aio import CosmosClient  # noqa: E402
from neurosphere_api.recommendations.review_hitl import HitlReviewRouter  # noqa: E402
from neurosphere_api.reports.models import StoredReport  # noqa: E402
from neurosphere_api.reports.plan import strip_data  # noqa: E402
from neurosphere_api.reports.store import ReportStore  # noqa: E402
from neurosphere_contracts.recommendations.v1.recommendation import Recommendation  # noqa: E402
from neurosphere_core.actions import (  # noqa: E402
    ActionCaller,
    ActionService,
    AuditRepositoryActionAuditor,
    DraftRequest,
    ExecutionControl,
    IntentKey,
    IntentStore,
)
from neurosphere_core.actions.cosmos_store import (  # noqa: E402
    CosmosIntentStore,
)
from neurosphere_core.actions.recheck import PolicyPermissionRechecker  # noqa: E402
from neurosphere_core.audit import AuditRepository  # noqa: E402
from neurosphere_core.audit.cosmos_store import CosmosAuditStore  # noqa: E402
from neurosphere_core.auth.jwt.config import normalize_tenant_id  # noqa: E402
from neurosphere_core.auth.scope import (  # noqa: E402
    PolicyRepository,
    PrincipalPseudonymizer,
    PseudonymKey,
    RevocationChecker,
)
from neurosphere_core.capabilities import load_matrix  # noqa: E402
from neurosphere_core.catalog import CatalogRepository  # noqa: E402
from neurosphere_core.catalog.repo.documents import ENTITY_MODELS  # noqa: E402
from neurosphere_core.charts import validate_chart_plan  # noqa: E402
from neurosphere_core.cloud import CloudName, Settings, load_settings  # noqa: E402
from neurosphere_core.errors import NeuroSphereError  # noqa: E402
from neurosphere_core.evaluation.judge import (  # noqa: E402
    JudgeResponse,
    RecordedFixtureJudge,
    request_hash,
)
from neurosphere_core.evaluation.store import EvaluationStore  # noqa: E402
from neurosphere_core.hitl import HitlService, ReviewPolicyRegistry  # noqa: E402
from neurosphere_core.hitl.decisions import DecisionLog, DecisionStore  # noqa: E402
from neurosphere_core.hitl.store import HitlStore  # noqa: E402
from neurosphere_core.mcp import McpClientPolicy, McpRegistry, McpServerStore  # noqa: E402
from neurosphere_core.payload import HubMessage, HubMessageKind  # noqa: E402
from neurosphere_core.pricing import (  # noqa: E402
    InMemoryPriceSnapshotStore,
    PriceRow,
    PriceSnapshotStore,
    TokenMeter,
    build_snapshot,
)
from neurosphere_core.recommendations import RecommendationStore  # noqa: E402
from neurosphere_core.scope import IdentityScope  # noqa: E402
from neurosphere_core.stores import ensure_local_containers  # noqa: E402
from neurosphere_workers.evaluation.budget import BudgetLedger, BudgetLimits  # noqa: E402
from neurosphere_workers.evaluation.pipeline import OfflineStage  # noqa: E402
from neurosphere_workers.evaluation.pipeline import run_pipeline as run_evaluation  # noqa: E402
from neurosphere_workers.evaluation.service import OfflineRunConfig  # noqa: E402
from neurosphere_workers.recommendations.pipeline import (  # noqa: E402
    run_pipeline as run_recommendations,
)
from neurosphere_workers.recommendations.projection.models import CandidatePairConfig  # noqa: E402
from neurosphere_workers.runtime.identity import PolicyStack, build_identity  # noqa: E402
from neurosphere_workers.runtime.settings import (  # noqa: E402
    AuthSettings,
    StoreSettings,
    WorkerSettings,
)
from pydantic import ValidationError  # noqa: E402
from sbx_guard import (  # noqa: E402
    PREFIX,
    GuardError,
    is_local_host,
    require_local_connection_string,
    require_local_endpoint,
)
from sbx_seam import HubSeam  # noqa: E402

from sandbox.config import (  # noqa: E402
    CACHED_INPUT_FACTOR,
    DEFAULT_EPOCH,
    MODELS,
    PRICE_EFFECTIVE_DATE,
    PRICE_VERSION,
    PROFILES,
    BadEventRates,
    GenerateConfig,
    with_overrides,
)
from sandbox.evaluation.loader import (  # noqa: E402
    PILOT_DATASET_ID,
    PILOT_VERSION,
    load_human_labels,
    load_registry,
    pilot_request,
)
from sandbox.generate import generate  # noqa: E402
from sandbox.world import World  # noqa: E402

Doc = dict[str, Any]

EXIT_REFUSED: Final = 2
EXIT_FAILED: Final = 3
STACK_DIR: Final = REPO / "sandbox" / "stack"
DEFAULT_COSMOS_ENDPOINT: Final = "http://127.0.0.1:8081"
DEFAULT_BLOB_CONNECTION: Final = "UseDevelopmentStorage=true;"
DEFAULT_WAIT_SECONDS: Final = 300.0
DEFAULT_POLL_SECONDS: Final = 5.0
SEED_NUMBER: Final = 1
#: Fixed stamp of every seeded record: the pipelines read no wall clock, so a re-run is identical.
CREATED_AT: Final = datetime(2026, 10, 19, 12, 0, 0, tzinfo=UTC)
CONFIRMATION_TTL: Final = timedelta(days=7)
LEDGER_CONTAINER: Final = "cost-ledger"
AGGREGATES_CONTAINER: Final = "aggregates"
CATALOG_CONTAINER: Final = "catalog"
#: The newest generated event is shifted to this long before the run (the manifest's 1-day cost
#: window and 7-day archive look-back then both hold data).
NEWEST_AGE: Final = timedelta(minutes=30)
#: How far below the newest event the aggregates watermark may stop and still count as drained.
SHIFT_GRID_SECONDS: Final = 3600
DRAIN_SLACK: Final = timedelta(minutes=1)
#: Entity files written into the catalog through the repository (relations are projected edges).
ENTITY_FILES: Final = (
    "domains.ndjson",
    "owners.ndjson",
    "model_deployments.ndjson",
    "grounding_sources.ndjson",
    "tools.ndjson",
    "agents.ndjson",
    "agent_versions.ndjson",
    "persons.ndjson",
)
PRODUCER_ID: Final = "sbx-seed-stack"
RUN_PREFIX: Final = "seed-offline-"
#: States the seed is allowed to leave an intent in. ``executing`` is never reachable from here.
SAFE_INTENT_STATES: Final = ("drafted", "validated", "awaiting_confirmation")

#: Summary categories, one per kind of data a manifest page reads.
CATEGORIES: Final = (
    "catalog",
    "entities",
    "aggregates",
    "ledger",
    "archives",
    "prices",
    "recommendations",
    "reviews",
    "evaluations",
    "intents",
    "reports",
    "mcp_servers",
    "grants",
)
#: Categories the workers fill from the pushed events.
LANDED: Final = ("ledger", "aggregates", "catalog", "archives")


class SeedError(RuntimeError):
    """A seed step failed (exit 3). Messages never contain secrets."""


class ConfigError(RuntimeError):
    """The configuration is unusable or unsafe (exit 2)."""


class LandingTimeout(SeedError):  # noqa: N818 - reads as the condition, like TimeoutError
    """The workers did not land the pushed events within the overall timeout."""


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


# -- configuration ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SeedConfig:
    profile: str
    cosmos_endpoint: str
    cosmos_key: str = field(repr=False)
    eventhubs_connection: str = field(repr=False)
    blob_connection: str = field(repr=False)
    database: str
    customer: str
    tenant_id: str
    worker_object_id: str
    operator_object_id: str | None
    hub_name: str
    archive_container: str
    wait_seconds: float = DEFAULT_WAIT_SECONDS
    poll_seconds: float = DEFAULT_POLL_SECONDS
    drain_seconds: float = DEFAULT_WAIT_SECONDS
    cloud: str = "commercial"
    seed: int = SEED_NUMBER

    def environ(self) -> dict[str, str]:
        """The variables the worker settings classes and core factories read."""
        return {
            "NS_ENV": "local",
            "NS_COSMOS_ENDPOINT": self.cosmos_endpoint,
            "NS_COSMOS_KEY": self.cosmos_key,
            "NS_EVENTHUBS_CONNECTION_STRING": self.eventhubs_connection,
            "NS_BLOB_CONNECTION_STRING": self.blob_connection,
            "NS_STORE_DATABASE": self.database,
            "NS_AUTH_CUSTOMER_ID": self.customer,
            "NS_AUTH_TENANT_ID": self.tenant_id,
            "NS_WORKER_OBJECT_ID": self.worker_object_id,
            "NS_ARCHIVE_CONTAINER": self.archive_container,
        }


def _blob_host(connection: str) -> str | None:
    """The host a Blob connection string talks to (``None`` when it cannot be determined)."""
    parts = {
        key.strip().lower(): value.strip()
        for key, _, value in (p.partition("=") for p in connection.split(";") if p.strip())
    }
    if parts.get("usedevelopmentstorage", "").lower() == "true":
        return "127.0.0.1"
    endpoint = parts.get("blobendpoint")
    if endpoint:
        return urlparse(endpoint).hostname
    account, suffix = parts.get("accountname"), parts.get("endpointsuffix")
    if account and suffix:
        return f"{account}.blob.{suffix}"
    return None


def require_local_blob(connection: str) -> str:
    host = _blob_host(connection)
    if not is_local_host(host):
        raise GuardError(
            f"refusing Blob endpoint host {host!r}: only local emulator addresses are allowed; "
            "there is no override"
        )
    return connection


def _default_eventhubs_connection() -> str:
    # Assembled at runtime so no connection string is committed as a literal.
    parts = [
        "Endpoint=sb://127.0.0.1",
        "SharedAccessKeyName=RootManageSharedAccessKey",
        "SharedAccessKey=" + "SAS_KEY" + "_VALUE",
        "UseDevelopmentEmulator=true",
    ]
    return ";".join(parts) + ";"


def _float_env(environ: Mapping[str, str], name: str, default: float) -> float:
    raw = environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a number") from None
    if value <= 0:
        raise ConfigError(f"{name} must be positive")
    return value


def resolve_config(
    profile: str, operator_object_id: str | None, environ: Mapping[str, str]
) -> SeedConfig:
    """Validate the environment and return the config. Raises ``GuardError``/``ConfigError``."""
    if environ.get("NS_ENV", "local") != "local":
        raise ConfigError("the stack seed only runs with NS_ENV=local (hosted seeding is PRP-32)")
    if environ.get("NS_CLOUD", "commercial") != "commercial":
        raise ConfigError("the synthetic stack seed supports NS_CLOUD=commercial only")
    endpoint = require_local_endpoint(environ.get("NS_COSMOS_ENDPOINT") or DEFAULT_COSMOS_ENDPOINT)
    key = environ.get("NS_COSMOS_KEY") or base64.b64encode(b"sandbox-local-emulator").decode()
    hubs = require_local_connection_string(
        environ.get("NS_EVENTHUBS_CONNECTION_STRING") or _default_eventhubs_connection()
    )
    blob = require_local_blob(environ.get("NS_BLOB_CONNECTION_STRING") or DEFAULT_BLOB_CONNECTION)
    database = environ.get("NS_STORE_DATABASE") or "neurosphere"
    if database.startswith(PREFIX):
        raise ConfigError("NS_STORE_DATABASE must not be a sandbox- database")
    tenant = environ.get("NS_WORKER_TENANT_ID") or environ.get("NS_AUTH_TENANT_ID") or ""
    if grants.GUID_RE.fullmatch(tenant) is None:
        raise ConfigError("NS_AUTH_TENANT_ID (or NS_WORKER_TENANT_ID) must be a GUID")
    worker_oid = environ.get("NS_WORKER_OBJECT_ID") or ""
    if grants.GUID_RE.fullmatch(worker_oid) is None:
        raise ConfigError("NS_WORKER_OBJECT_ID must be a GUID (the identity the workers run as)")
    if operator_object_id is not None and grants.GUID_RE.fullmatch(operator_object_id) is None:
        raise ConfigError("--operator-object-id must be a GUID")
    if profile not in load_profiles():
        raise ConfigError(f"unknown profile {profile!r}")
    return SeedConfig(
        profile=profile,
        cosmos_endpoint=endpoint,
        cosmos_key=key,
        eventhubs_connection=hubs,
        blob_connection=blob,
        database=database,
        customer=environ.get("NS_AUTH_CUSTOMER_ID") or "synthco",
        tenant_id=tenant,
        worker_object_id=worker_oid,
        operator_object_id=operator_object_id,
        hub_name=environ.get("NS_INGESTION_EVENTHUB_NAME") or "telemetry",
        archive_container=environ.get("NS_ARCHIVE_CONTAINER") or "ns-archive",
        wait_seconds=_float_env(environ, "NS_SEED_WAIT_SECONDS", DEFAULT_WAIT_SECONDS),
        poll_seconds=_float_env(environ, "NS_SEED_POLL_SECONDS", DEFAULT_POLL_SECONDS),
        drain_seconds=_float_env(environ, "NS_SEED_DRAIN_SECONDS", DEFAULT_WAIT_SECONDS),
    )


# -- fixtures --------------------------------------------------------------------------------


def _fixture(name: str) -> Doc:
    return json.loads((STACK_DIR / name).read_text(encoding="utf-8"))


def load_profiles() -> dict[str, Doc]:
    return dict(_fixture("profiles.json")["profiles"])


def generate_config(config: SeedConfig) -> GenerateConfig:
    spec = load_profiles()[config.profile]
    profile = with_overrides(PROFILES[spec["base"]], **spec["overrides"])
    return GenerateConfig(
        seed=config.seed,
        profile=profile,
        cloud=config.cloud,
        customer=config.customer,
        rates=BadEventRates(duplicate=0.0, out_of_order=0.0, malformed=0.0, missing_optional=0.0),
    )


def read_ndjson(path: Path) -> list[Doc]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def hub_lines(directory: Path, not_after: datetime | None = None) -> list[bytes]:
    """Telemetry then cost, each wrapped in the ingestion envelope (``HubMessage``).

    The generator dates its invoice records at the period end, after the last usage. Rebased onto
    the run time that would be the future, so a record dated after ``not_after`` is stamped
    ``not_after`` instead (only the published copy; the ids are untouched).
    """
    received = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    lines: list[bytes] = []
    for name, kind in (("telemetry.ndjson", "telemetry"), ("cost.ndjson", "cost")):
        for doc in read_ndjson(directory / name):
            telemetry = kind == "telemetry"
            if (
                not telemetry
                and not_after is not None
                and _timestamp(doc["recorded_at"]) > not_after
            ):
                doc = {**doc, "recorded_at": not_after.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"}
            message = HubMessage(
                kind=HubMessageKind(kind),
                event_id=doc["event_id"] if telemetry else doc["cost_id"],
                cloud=doc["cloud"],
                customer_id=doc["customer_id"],
                source_id=doc["source_id"],
                producer_id=PRODUCER_ID,
                received_at=received,
                request_id=doc.get("request_id"),
                observation_kind="gateway" if telemetry else "billing",
                data=doc,
            )
            lines.append(message.to_bytes())
    return lines


# -- ports -----------------------------------------------------------------------------------


class Publisher(Protocol):
    def publish(self, lines: Iterator[bytes], rate: float = 0.0, chunk: int = 100) -> int: ...


class Landing(Protocol):
    async def counts(self) -> dict[str, int]:
        """Documents the workers landed, per ``LANDED`` category."""
        ...

    async def ledger_earliest(self) -> datetime | None:
        """The earliest ``occurred_at`` in the ledger (``None`` when it is empty)."""
        ...

    async def aggregate_watermark(self) -> datetime | None:
        """How far the aggregates role has drained (``None`` before its first checkpoint)."""
        ...


class PolicyWriter(Protocol):
    async def upsert(self, document: dict[str, Any]) -> None: ...


@dataclass
class Backends:
    """Everything the seed writes through. Real (Cosmos) or in-memory (unit tests)."""

    hub: Publisher
    landing: Landing
    policy: PolicyRepository
    policy_writer: PolicyWriter
    revocation: RevocationChecker
    key: PseudonymKey
    catalog: CatalogRepository
    prices: PriceSnapshotStore
    recommendations: RecommendationStore
    hitl: HitlService
    evaluations: EvaluationStore
    actions: ActionService
    reports: ReportStore
    mcp: McpServerStore


class Tally:
    def __init__(self) -> None:
        self.seeded: dict[str, int] = dict.fromkeys(CATEGORIES, 0)
        self.skipped = 0

    def record(self, category: str, *, created: int, existing: int) -> None:
        self.seeded[category] += created
        self.skipped += existing

    def summary(self) -> Doc:
        return {"seeded": dict(self.seeded), "skipped_existing": self.skipped}


class _NoReviewer:
    """The seed opens review items; it never decides one, so nobody is an authorized reviewer."""

    async def can_review(
        self, principal_id: str, customer_id: str, domain_id: str, permission: Any
    ) -> bool:
        return False


def make_hitl(store: HitlStore, decisions: DecisionStore, audit: AuditRepository) -> HitlService:
    return HitlService(
        store,
        DecisionLog(audit, decisions),
        audit,
        ReviewPolicyRegistry(),
        _NoReviewer(),
    )


def make_action_service(
    *,
    cloud: CloudName,
    policy: PolicyRepository,
    revocation: RevocationChecker,
    audit: AuditRepository,
    intents: IntentStore,
    control: ExecutionControl,
) -> ActionService:
    """The construction of ``neurosphere_api.runtime.builders.planes._action_plane``."""
    rechecker = PolicyPermissionRechecker(
        cloud=cloud, policy_repository=policy, revocation_checker=revocation
    )
    return ActionService(
        intents,
        auditor=AuditRepositoryActionAuditor(audit),
        rechecker=rechecker,
        execution_control=control,
    )


# -- identities and grants -------------------------------------------------------------------


def worker_stack(backends: Backends, config: SeedConfig) -> PolicyStack:
    return PolicyStack(
        policy=cast(Any, backends.policy),
        revocation=cast(Any, backends.revocation),
        key=backends.key,
        tenant_id=normalize_tenant_id(config.tenant_id),
    )


async def worker_scope(backends: Backends, config: SeedConfig) -> IdentityScope:
    """The scope the workers derive for their own identity (policy store only, no bypass)."""
    identity = build_identity(
        load_settings(),
        stack=worker_stack(backends, config),
        worker=WorkerSettings(tenant_id=config.tenant_id, object_id=config.worker_object_id),
        customer_id=config.customer,
    )
    return await identity.scope_provider.get()


def worker_principal_id(backends: Backends, config: SeedConfig) -> str:
    return PrincipalPseudonymizer(backends.key).principal_id(
        cloud=CloudName(config.cloud),
        customer_id=config.customer,
        tenant_id=normalize_tenant_id(config.tenant_id),
        object_id=config.worker_object_id,
        kind="service_principal",
    )


def user_principal_id(config: SeedConfig, object_id: str, environ: Mapping[str, str]) -> str:
    """The API's own pseudonym (``resolve_pseudonym_key``), via the operator-grant script."""
    return grants._principal_id(  # pyright: ignore[reportPrivateUsage]
        env=environ,
        tenant=config.tenant_id,
        customer=config.customer,
        cloud=config.cloud,
        object_id=object_id,
    )


def world_domains(world: World) -> tuple[str, ...]:
    return tuple(world.domain_id(i) for i in range(len(world.domains)))


async def seed_grants(
    backends: Backends,
    config: SeedConfig,
    world: World,
    tally: Tally,
    environ: Mapping[str, str],
) -> dict[str, str]:
    """Worker principal, personas and (optionally) the operator. Returns slug -> principal id."""
    domains = world_domains(world)
    principals: dict[str, str] = {}
    wanted: list[tuple[str, str, str]] = [
        ("worker", worker_principal_id(backends, config), "viewer")
    ]
    for persona in _fixture("personas.json")["personas"]:
        principal = user_principal_id(config, persona["object_id"], environ)
        principals[persona["slug"]] = principal
        wanted.append((persona["slug"], principal, persona["role"]))
    if config.operator_object_id is not None:
        operator = user_principal_id(config, config.operator_object_id, environ)
        principals["operator"] = operator
        wanted.append(("operator", operator, "admin"))
    for slug, principal, role in wanted:
        outcome = await grants.grant_operator(
            backends.policy,
            backends.policy_writer,
            customer_id=config.customer,
            principal_id=principal,
            role=role,
            domain_ids=domains,
        )
        changed = outcome != "unchanged"
        tally.record("grants", created=int(changed), existing=int(not changed))
        log(f"grant {slug}: {role} {outcome}")
    return principals


# -- prices ----------------------------------------------------------------------------------


def synthetic_snapshot() -> Any:
    """SYNTHETIC snapshot of the sandbox price sheet (USD per 1K tokens; invented numbers)."""
    rows: list[PriceRow] = []
    for spec in MODELS:
        for kind, price in (
            ("input", spec.price_in),
            ("output", spec.price_out),
            ("cached", spec.price_in * CACHED_INPUT_FACTOR),
        ):
            rows.append(
                PriceRow(
                    service_name="SYNTHETIC sandbox price sheet",
                    sku_name=f"{spec.model_name} {kind}",
                    meter_name=f"SYNTHETIC {spec.model_name} {kind} tokens",
                    unit_of_measure="1K",
                    retail_price=Decimal(price),
                    token_meter=TokenMeter(
                        provider=spec.provider,
                        model=spec.model_name,
                        model_version=spec.model_version,
                        kind=kind,  # type: ignore[arg-type]
                    ),
                )
            )
    return build_snapshot(
        snapshot_id=PRICE_VERSION,
        source="provider_price_sheet",
        source_url="https://pricing.invalid/sandbox-price-sheet",
        retrieval_date=date(2026, 10, 19),
        effective_date=date.fromisoformat(PRICE_EFFECTIVE_DATE),
        currency="USD",
        clouds=("commercial",),
        synthetic=True,
        notes="SYNTHETIC: the sandbox price sheet; invented numbers, not a provider list price.",
        rows=rows,
    )


async def seed_prices(backends: Backends, tally: Tally) -> None:
    # The snapshot protocol is synchronous (azure-cosmos sync client): keep it off the loop.
    created = await asyncio.to_thread(backends.prices.put, synthetic_snapshot())
    tally.record("prices", created=int(created), existing=int(not created))


# -- recommendations and reviews -------------------------------------------------------------


class _TallyingRecommendations:
    """Puts through the real store and records which ids were new and which already existed."""

    def __init__(self, inner: RecommendationStore, scope: IdentityScope) -> None:
        self._inner = inner
        self._scope = scope
        self.created: list[tuple[str, str]] = []
        self.existing: list[tuple[str, str]] = []

    @property
    def stored(self) -> list[tuple[str, str]]:
        return sorted(self.created + self.existing)

    async def put(self, recommendation: Recommendation) -> None:
        domain, ident = recommendation.domain_id.root, recommendation.recommendation_id.root
        found = await self._inner.get(self._scope, domain, ident)
        await self._inner.put(recommendation)
        (self.existing if found is not None else self.created).append((domain, ident))

    async def list(
        self,
        scope: IdentityScope,
        domain: str,
        kind: str | None = None,
        q: str | None = None,
        cursor: str | None = None,
        limit: int = 50,
    ) -> Any:
        return await self._inner.list(scope, domain, kind, q, cursor, limit)

    async def get(
        self, scope: IdentityScope, domain: str, recommendation_id: str
    ) -> Recommendation | None:
        return await self._inner.get(scope, domain, recommendation_id)


async def seed_recommendations(
    backends: Backends,
    scope: IdentityScope,
    directory: Path,
    review_limit: int,
    tally: Tally,
) -> None:
    pairs = CandidatePairConfig.model_validate(_fixture("pairs.json"))
    snapshots = await asyncio.to_thread(backends.prices.list_snapshots)
    store = _TallyingRecommendations(backends.recommendations, scope)
    await run_recommendations(
        directory,
        scope=scope,
        store=store,
        prices=InMemoryPriceSnapshotStore(snapshots),
        pairs=pairs,
        created_at=CREATED_AT,
    )
    tally.record("recommendations", created=len(store.created), existing=len(store.existing))
    router = HitlReviewRouter(backends.hitl)
    for domain, ident in store.stored[:review_limit]:
        known = await router.status(scope, domain, ident)
        if known is None:
            await router.route(scope, domain, ident)
        tally.record("reviews", created=int(known is None), existing=int(known is not None))


# -- evaluations -----------------------------------------------------------------------------


def recorded_programmatic_judge() -> tuple[RecordedFixtureJudge, Any]:
    """A ``RecordedFixtureJudge`` holding the recorded verdicts of the sandbox programmatic judge
    (the pilot set's ground truth, request-hash keyed). The LLM judge configs are not used: their
    Commercial capability row is unverified, so the shipped matrix refuses them."""
    registry = load_registry()
    config = registry.judge_configs.get("sbx-judge-programmatic", "1.0.0")
    dataset = registry.datasets.get(PILOT_DATASET_ID, PILOT_VERSION)
    if config is None or dataset is None:
        raise SeedError(
            "the sandbox evaluation data is missing the programmatic judge or pilot set"
        )
    truth = {label.item_id: label.value for label in load_human_labels().labels}
    responses = {
        request_hash(pilot_request(config, item)): JudgeResponse(
            value=truth[item.item_id], abstained=False, input_tokens=0, output_tokens=0
        )
        for item in dataset.items
    }
    return RecordedFixtureJudge(responses), registry


async def seed_evaluations(
    backends: Backends, scope: IdentityScope, world: World, subjects: int, tally: Tally
) -> None:
    judge, registry = recorded_programmatic_judge()
    judge_config = registry.judge_configs.get("sbx-judge-programmatic", "1.0.0")
    dataset = registry.datasets.get(PILOT_DATASET_ID, PILOT_VERSION)
    rubric = registry.rubrics.get("sbx-rubric", "1.0.0")
    if judge_config is None or dataset is None or rubric is None:
        raise SeedError("the sandbox evaluation registry is incomplete")
    matrix = load_matrix()
    limits = BudgetLimits(tokens=10_000_000, cost=Decimal("1000"))
    for index in range(min(subjects, len(world.agents))):
        agent = world.agents[index]
        domain = world.domain_id(agent.domain)
        subject = world.agent_id(index)
        before = len(await backends.evaluations.results(scope, domain, subject))
        await run_evaluation(
            registry=registry,
            judge=judge,
            matrix=matrix,
            store=backends.evaluations,
            ledger=BudgetLedger(run_limits=limits, domain_limits=limits),
            clock=lambda: CREATED_AT,
            offline=OfflineStage(
                dataset=dataset,
                config=OfflineRunConfig(
                    run_id=f"{RUN_PREFIX}{index:03d}",
                    cloud=cast(Any, scope.cloud),
                    rubric=rubric,
                    judges={"groundedness": judge_config},
                    customer_id=scope.customer_id,
                    domain_id=domain,
                    subject_id=subject,
                ),
            ),
        )
        after = len(await backends.evaluations.results(scope, domain, subject))
        tally.record("evaluations", created=max(after - before, 0), existing=min(before, after))


# -- intents ---------------------------------------------------------------------------------


def _caller(principal_id: str, correlation: str) -> ActionCaller:
    return ActionCaller.model_validate(
        {
            "principal_id": principal_id,
            "actor": {
                "principal_pseudonym": principal_id.rsplit(":", 1)[-1],
                "principal_kind": "user",
                "on_behalf_of": None,
            },
            "scope_hash": "sha256:" + hashlib.sha256(principal_id.encode()).hexdigest(),
            "correlation_id": correlation,
            "channel": "rest",
        }
    )


def _idempotency(slug: str) -> str:
    return "seed-intent-" + slug


def _draft_request(world: World, spec: Doc) -> DraftRequest:
    return DraftRequest.model_validate(
        {
            "action_kind": spec["action_kind"],
            "target": {"canonical_id": world.agent_id(spec["agent_index"]), "entity_type": "agent"},
            "target_version": "seed-v1",
            "proposed_diff": {
                "format": "json_patch",
                "operations": [{"op": "replace", "path": spec["path"], "value": spec["value"]}],
            },
            "evidence": [],
            "idempotency_key": _idempotency(spec["slug"]),
            "channel": "rest",
        }
    )


async def _advance(
    backends: Backends, key: IntentKey, caller: ActionCaller, state: str, target: str
) -> str:
    """Move an intent toward ``target`` (never past it); returns the state it ends in."""
    from neurosphere_contracts.actions.v1.action_intent import PrerequisiteResult

    if target not in SAFE_INTENT_STATES:
        raise SeedError(f"refusing to take an intent to {target!r}")
    order = {name: rank for rank, name in enumerate(SAFE_INTENT_STATES)}
    if state == "drafted" and order[target] >= order["validated"]:
        check = PrerequisiteResult.model_validate(
            {
                "check_id": "write_connector_supported",
                "status": "not_applicable",
                "detail": "advisory: no write connector is composed locally",
                "evaluated_at": CREATED_AT.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "evidence_ids": [],
            }
        )
        saved = await backends.actions.record_validation(key, caller, [check], advisory=True)
        state = saved.state
    if state == "validated" and order[target] >= order["awaiting_confirmation"]:
        saved = await backends.actions.present_confirmation(key, caller, ttl=CONFIRMATION_TTL)
        state = saved.state
    return state


async def seed_intents(
    backends: Backends, world: World, principals: Mapping[str, str], tally: Tally
) -> None:
    fixture = _fixture("intents.json")
    maker = principals[fixture["maker"]]
    for spec in fixture["intents"]:
        caller = _caller(maker, "seed-" + spec["slug"])
        domain = world.domain_id(world.agents[spec["agent_index"]].domain)
        outcome = await backends.actions.draft(
            caller,
            _draft_request(world, spec),
            customer_id=world.customer,
            domain_id=domain,
        )
        stored = outcome.stored
        key = IntentKey(world.customer, domain, stored.intent_id)
        state = await _advance(backends, key, caller, stored.state, spec["target_state"])
        if state not in SAFE_INTENT_STATES:
            raise SeedError(f"intent {spec['slug']} is in unexpected state {state!r}")
        tally.record("intents", created=int(outcome.created), existing=int(not outcome.created))


# -- reports and MCP servers -----------------------------------------------------------------


async def seed_reports(
    backends: Backends, world: World, principals: Mapping[str, str], tally: Tally
) -> None:
    fixture = _fixture("reports.json")
    owned: list[tuple[str, Doc]] = [(principals[fixture["owner"]], s) for s in fixture["reports"]]
    if "operator" in principals:
        # Owned by the signed-in operator, so their own sign-in lists and runs it. No visibility
        # rule is widened: the report store still shows it to its owner and share principals only.
        owned += [(principals["operator"], s) for s in fixture["operator_reports"]]
    for owner, spec in owned:
        domain = world.domain_id(spec["domain_index"] % len(world.domains))
        report_id = str(
            uuid.uuid5(uuid.NAMESPACE_URL, f"neurosphere:{world.customer}:{spec['slug']}")
        )
        if await backends.reports.get(world.customer, domain, report_id) is not None:
            tally.record("reports", created=0, existing=1)
            continue
        plan = validate_chart_plan(spec["chart_plan"])
        template = strip_data(plan.model_dump(mode="json", by_alias=True, exclude_unset=True))
        await backends.reports.create(
            StoredReport(
                id=report_id,
                customer_id=world.customer,
                domain_id=domain,
                owner=owner,
                title=spec["title"],
                chart_plan=template,
                query_spec=spec["query_spec"],
                metric=spec["metric"],
                created_at=CREATED_AT,
                updated_at=CREATED_AT,
            )
        )
        tally.record("reports", created=1, existing=0)


async def seed_mcp_servers(
    backends: Backends, config: SeedConfig, principals: Mapping[str, str], tally: Tally
) -> None:
    from neurosphere_core.mcp.urls import normalize_server_url, server_id_for

    registry = McpRegistry(backends.mcp, McpClientPolicy(cloud=CloudName(config.cloud)))
    actor = principals["admin"].rsplit(":", 1)[-1]
    for spec in _fixture("mcp_servers.json")["servers"]:
        if await backends.mcp.get(server_id_for(normalize_server_url(spec["url"]))) is not None:
            tally.record("mcp_servers", created=0, existing=1)
            continue
        await registry.register(spec["url"], display_name=spec["display_name"], actor=actor)
        tally.record("mcp_servers", created=1, existing=0)


# -- catalog entities ------------------------------------------------------------------------


async def seed_entities(
    backends: Backends, scope: IdentityScope, directory: Path, tally: Tally
) -> None:
    """Write the generated entities (domains, owners, models, grounding sources, tools, agents,
    people) through ``CatalogRepository.create_entity`` under the workers' own scope. The ingestion
    projection only ever writes edges, so without this the map has no nodes. Entity ids are
    canonical and independent of the time rebase, so a re-run finds them and creates nothing."""
    allowed = frozenset(scope.allowed_domains)
    for name in ENTITY_FILES:
        path = directory / name
        if not path.exists():
            continue
        for doc in read_ndjson(path):
            kind = doc.get("entity_type")
            if kind not in ENTITY_MODELS:
                continue
            domain = doc["id"] if kind == "domain" else doc.get("domain_id")
            if (
                doc.get("cloud") != scope.cloud
                or doc.get("customer_id") != scope.customer_id
                or domain not in allowed
            ):
                continue  # outside the workers' scope: fail closed, never widen
            if await backends.catalog.get_entity(scope, doc["id"]) is not None:
                tally.record("entities", created=0, existing=1)
                continue
            entity = ENTITY_MODELS[kind].model_validate(doc)
            await backends.catalog.create_entity(scope, cast(Any, entity))
            tally.record("entities", created=1, existing=0)


# -- time rebase -----------------------------------------------------------------------------


def _timestamp(text: str) -> datetime:
    return datetime.fromisoformat(text).astimezone(UTC)


def observed_bounds(directory: Path) -> tuple[datetime, datetime]:
    """``(earliest, newest)`` usage time of a generated world (telemetry and non-invoice costs).

    The newest is what the rebase pins to the run time; the earliest is the reference a re-run
    matches against the ledger's earliest ``occurred_at`` (to within seconds; the shift is a
    whole number of hours, see ``rebase_seconds``). Invoice records are dated at the period end,
    after the last usage, so they are left out here (``hub_lines`` clamps them).
    """
    costs = [
        _timestamp(doc["recorded_at"])
        for doc in read_ndjson(directory / "cost.ndjson")
        if doc.get("observation_source") != "billing"
    ]
    events = [_timestamp(doc["event_time"]) for doc in read_ndjson(directory / "telemetry.ndjson")]
    if not costs or not events:
        raise SeedError("the generated world has no telemetry or no cost records")
    both = costs + events
    return min(both), max(both)


def shifted_epoch(epoch: str, seconds: int) -> str:
    """``epoch`` (RFC 3339 UTC, whole seconds) moved by ``seconds``."""
    moved = datetime.strptime(epoch, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    return (moved + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


def rebase_seconds(
    *,
    now: datetime,
    earliest: datetime,
    newest: datetime,
    existing_earliest: datetime | None,
) -> int:
    """Seconds (a whole number of hours) to move the generated world's epoch by.

    First run (the ledger is empty): the newest usage lands between ``NEWEST_AGE`` and
    ``NEWEST_AGE`` + 1h before ``now``, so the whole world sits in the last few days. Re-run (the
    ledger holds events): the same shift the first run used, recovered from the ledger, so every
    timestamp, window, recommendation id and aggregate key is regenerated exactly as before. The
    hour grid absorbs the few seconds by which the ledger's earliest entry differs from the
    generated earliest. A re-run on a later day therefore finds the data where it was, now older,
    and creates nothing; it does not re-age it. To get fresh data drop the volumes
    (``docker compose down -v``) and seed again.
    """
    if existing_earliest is not None:
        return round((existing_earliest - earliest).total_seconds() / SHIFT_GRID_SECONDS) * (
            SHIFT_GRID_SECONDS
        )
    wanted = ((now - NEWEST_AGE) - newest).total_seconds()
    return math.floor(wanted / SHIFT_GRID_SECONDS) * SHIFT_GRID_SECONDS


# -- landing ---------------------------------------------------------------------------------


async def wait_for_landing(
    landing: Landing,
    *,
    overall_seconds: float,
    poll: float,
    stable_checks: int = 1,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, int]:
    """Wait (ONE overall timeout, sparse checks) until every landed category is non-empty.

    ``stable_checks`` > 1 also requires the counts to be unchanged across that many consecutive
    readings. The default does not: the workers keep draining the outbox for a long while after
    the first documents appear, and the seed must not fail merely because they are still busy.
    """
    deadline = clock() + overall_seconds
    previous: dict[str, int] | None = None
    streak = 0
    while True:
        counts = await landing.counts()
        full = all(counts[name] > 0 for name in LANDED)
        streak = streak + 1 if full and counts == previous else 1 if full else 0
        if full and streak >= stable_checks:
            return counts
        previous = counts
        if clock() + poll > deadline:
            empty = [name for name in LANDED if counts[name] == 0]
            if empty:
                raise LandingTimeout(
                    f"the workers did not land: {', '.join(empty)} after {overall_seconds:.0f}s "
                    "(are the ingestion, projections and aggregates roles running?)"
                )
            raise LandingTimeout(
                f"the landed counts were still changing after {overall_seconds:.0f}s: {counts}"
            )
        await sleep(poll)


async def wait_for_watermark(
    landing: Landing,
    target: datetime,
    *,
    overall_seconds: float,
    poll: float,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> bool:
    """Wait (one overall timeout, sparse checks) until the aggregates watermark reaches ``target``.

    Returns whether it did. Falling short is reported by the caller, never an error: the roles
    keep draining after the seed exits.
    """
    deadline = clock() + overall_seconds
    while True:
        mark = await landing.aggregate_watermark()
        if mark is not None and mark >= target:
            return True
        if clock() + poll > deadline:
            return False
        await sleep(poll)


# -- orchestration ---------------------------------------------------------------------------


async def run_seed(
    config: SeedConfig,
    backends: Backends,
    workdir: Path,
    *,
    environ: Mapping[str, str] | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    clock: Callable[[], float] = time.monotonic,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> Doc:
    """Seed every category and return the summary document."""
    env = dict(os.environ) if environ is None else environ
    tally = Tally()
    spec = load_profiles()[config.profile]
    gen = generate_config(config)
    log(f"generating the {config.profile} world (seed {config.seed})")
    await asyncio.to_thread(generate, gen, workdir)
    before = await backends.landing.counts()
    publishing = before["ledger"] == 0
    earliest, newest = observed_bounds(workdir)
    shift = rebase_seconds(
        now=now(),
        earliest=earliest,
        newest=newest,
        existing_earliest=None if publishing else await backends.landing.ledger_earliest(),
    )
    gen = replace(gen, epoch=shifted_epoch(DEFAULT_EPOCH, shift))
    log(f"rebasing the world to epoch {gen.epoch} (newest event {NEWEST_AGE} before now)")
    await asyncio.to_thread(generate, gen, workdir)
    world = World(gen)

    principals = await seed_grants(backends, config, world, tally, env)
    await seed_prices(backends, tally)

    if publishing:
        lines = await asyncio.to_thread(hub_lines, workdir, now() - NEWEST_AGE)
        sent = await asyncio.to_thread(backends.hub.publish, iter(lines))
        log(f"pushed {sent} telemetry and cost events to Event Hubs")
    else:
        log("the ledger already holds events; not publishing again")

    scope = await worker_scope(backends, config)
    missing = sorted(set(world_domains(world)) - set(scope.allowed_domains))
    if missing:
        raise SeedError(
            f"the worker scope lacks {len(missing)} seeded domains; grants did not apply"
        )
    await seed_recommendations(backends, scope, workdir, spec["review_limit"], tally)
    await seed_evaluations(backends, scope, world, spec["evaluation_subjects"], tally)
    await seed_intents(backends, world, principals, tally)
    await seed_reports(backends, world, principals, tally)
    await seed_mcp_servers(backends, config, principals, tally)

    log(f"waiting up to {config.wait_seconds:.0f}s for the workers to land the events")
    after = await wait_for_landing(
        backends.landing,
        overall_seconds=config.wait_seconds,
        poll=config.poll_seconds,
        sleep=sleep,
        clock=clock,
    )
    # After the wait: the entities would otherwise make the catalog look landed before the
    # projection's edges are there.
    await seed_entities(backends, scope, workdir, tally)
    # The aggregates role drains in event order, so the newest (today) buckets land last and are
    # the ones the 1-day cost window reads. Wait for them, but never fail on it.
    _, newest_rebased = observed_bounds(workdir)
    drained = await wait_for_watermark(
        backends.landing,
        newest_rebased - DRAIN_SLACK,
        overall_seconds=config.drain_seconds,
        poll=config.poll_seconds,
        sleep=sleep,
        clock=clock,
    )
    if not drained:
        log(
            "warning: the aggregates role has not caught up with the newest events yet; "
            "recent-window views fill in as it drains (re-run the seed to wait again)"
        )
    for name in LANDED:
        # A re-run that did not publish only finds what an earlier run's events produced (the
        # workers may still be draining them); none of that is new seeding.
        created = max(after[name] - before[name], 0) if publishing else 0
        tally.record(name, created=created, existing=after[name] - created)
    return tally.summary()


# -- real backends ---------------------------------------------------------------------------


class _CosmosPolicyWriter:
    def __init__(self, container: Any) -> None:
        self._container = container

    async def upsert(self, document: dict[str, Any]) -> None:
        await self._container.upsert_item(body=document)


class CosmosLanding:
    """Counts what the workers landed: Cosmos documents and archive blobs."""

    def __init__(self, cosmos: CosmosClient, config: SeedConfig) -> None:
        self._db = cosmos.get_database_client(config.database)
        self._blob_connection = config.blob_connection
        self._archive = config.archive_container

    async def _count(self, container: str, where: str) -> int:
        proxy = self._db.get_container_client(container)
        # Only fixed clause text from this module is interpolated.
        query = f"SELECT VALUE COUNT(1) FROM c WHERE {where}"  # noqa: S608
        rows: list[Any] = [row async for row in proxy.query_items(query=query)]
        return int(rows[0]) if rows else 0

    async def ledger_earliest(self) -> datetime | None:
        proxy = self._db.get_container_client(LEDGER_CONTAINER)
        query = "SELECT VALUE MIN(c.occurred_at) FROM c WHERE c.doc_type = 'entry'"
        rows: list[Any] = [row async for row in proxy.query_items(query=query)]
        return _timestamp(rows[0]) if rows and isinstance(rows[0], str) else None

    async def aggregate_watermark(self) -> datetime | None:
        proxy = self._db.get_container_client(AGGREGATES_CONTAINER)
        query = "SELECT VALUE MAX(c.watermark) FROM c WHERE c.doc_type = 'status'"
        rows: list[Any] = [row async for row in proxy.query_items(query=query)]
        return _timestamp(rows[0]) if rows and isinstance(rows[0], str) else None

    def _blobs(self) -> int:
        from azure.core.exceptions import ResourceNotFoundError
        from azure.storage.blob import ContainerClient

        client = ContainerClient.from_connection_string(self._blob_connection, self._archive)
        try:
            return sum(1 for _ in client.list_blobs())
        except ResourceNotFoundError:
            return 0
        finally:
            client.close()

    async def counts(self) -> dict[str, int]:
        return {
            "ledger": await self._count(LEDGER_CONTAINER, "c.doc_type = 'entry'"),
            "aggregates": await self._count(AGGREGATES_CONTAINER, "1=1"),
            "catalog": await self._count(CATALOG_CONTAINER, "1=1"),
            "archives": await asyncio.to_thread(self._blobs),
        }


async def open_backends(config: SeedConfig, stack: AsyncExitStack) -> Backends:
    """Cosmos-backed stores (database bootstrap on the emulator included)."""
    from neurosphere_api.reports import CosmosReportStore
    from neurosphere_core.actions.cosmos_store import CosmosExecutionControl as Control
    from neurosphere_core.catalog.repo.cosmos import CosmosCatalogRepository
    from neurosphere_core.evaluation.cosmos_store import CosmosEvaluationStore
    from neurosphere_core.hitl_cosmos.store import CosmosDecisionStore, CosmosHitlStore
    from neurosphere_core.mcp.cosmos_store import CosmosMcpServerStore
    from neurosphere_core.pricing.cosmos_store import CosmosPriceSnapshotStore
    from neurosphere_core.recommendations.cosmos_store import CosmosRecommendationStore
    from neurosphere_workers.runtime.identity import build_policy_stack

    settings = load_settings()
    cosmos = await stack.enter_async_context(
        CosmosClient(config.cosmos_endpoint, config.cosmos_key, enable_endpoint_discovery=False)
    )
    await ensure_local_containers(cosmos, Settings(env="local"), database=config.database)
    sync = SyncCosmosClient(
        config.cosmos_endpoint, config.cosmos_key, enable_endpoint_discovery=False
    )
    stack.callback(sync.close)

    auth = AuthSettings()
    policy = build_policy_stack(
        settings,
        cosmos=cosmos,
        auth=auth,
        store=StoreSettings(database=config.database),
        tenant_id=config.tenant_id,
    )
    database = cosmos.get_database_client(config.database)
    audit = AuditRepository(
        CosmosAuditStore.from_client(
            cosmos, database=config.database, container="audit", tail_container="audit_tail"
        )
    )
    return Backends(
        hub=HubSeam(
            {"NS_SANDBOX_EVENTHUBS_CONNECTION_STRING": config.eventhubs_connection},
            hub=config.hub_name,
        ),
        landing=CosmosLanding(cosmos, config),
        policy=policy.policy,
        policy_writer=_CosmosPolicyWriter(database.get_container_client(auth.policy_container)),
        revocation=policy.revocation,
        key=policy.key,
        catalog=CosmosCatalogRepository(database.get_container_client(CATALOG_CONTAINER)),
        prices=CosmosPriceSnapshotStore.from_client(sync, database=config.database),
        recommendations=CosmosRecommendationStore.from_client(cosmos, database=config.database),
        hitl=make_hitl(
            CosmosHitlStore.from_client(cosmos, database=config.database),
            CosmosDecisionStore.from_client(cosmos, database=config.database),
            audit,
        ),
        evaluations=CosmosEvaluationStore.from_client(cosmos, database=config.database),
        actions=make_action_service(
            cloud=CloudName(config.cloud),
            policy=policy.policy,
            revocation=policy.revocation,
            audit=audit,
            intents=CosmosIntentStore.from_client(cosmos, database=config.database),
            control=Control.from_client(cosmos, database=config.database),
        ),
        reports=CosmosReportStore.from_client(cosmos, database=config.database),
        mcp=CosmosMcpServerStore.from_client(cosmos, database=config.database),
    )


async def _seed(config: SeedConfig) -> Doc:
    with tempfile.TemporaryDirectory(prefix="ns-seed-") as tmp:
        async with AsyncExitStack() as stack:
            backends = await open_backends(config, stack)
            return await run_seed(config, backends, Path(tmp))


@contextlib.contextmanager
def scoped_environ(updates: Mapping[str, str]) -> Iterator[None]:
    saved = {name: os.environ.get(name) for name in updates}
    os.environ.update(updates)
    try:
        yield
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Seed the local real stack with synthetic data through the real paths."
    )
    parser.add_argument("--profile", choices=sorted(load_profiles()), default="small")
    parser.add_argument(
        "--operator-object-id", help="also grant this Entra object id admin (your sign-in)"
    )
    return parser


def main(argv: Sequence[str] | None = None, *, env: Mapping[str, str] | None = None) -> int:
    args = _parser().parse_args(argv)
    environ = dict(os.environ) if env is None else dict(env)
    try:
        config = resolve_config(args.profile, args.operator_object_id, environ)
    except (GuardError, ConfigError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    try:
        with scoped_environ({**environ, **config.environ()}):
            summary = asyncio.run(_seed(config))
    except (SeedError, NeuroSphereError, ValidationError, OSError) as exc:
        print(f"FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_FAILED
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
