"""Shared builders for the PRP-16 item 6 in-process slice and its measurement script.

Everything is SYNTHETIC and in memory: the sandbox benchmark data (``sandbox/evaluation``), the
recorded-fixture judge, a small invented archive-shaped record set, and a government-bound copy
of the PRP-06 authz harness (the shipped matrix enables only a Government judge, so the results
the API serves are Government results). No network, no wall clock, no credential.

TEST-ONLY objects, labelled as such wherever they are reported:

* ``OutcomeJudge``: a deterministic scorer standing in for a programmatic judge (task success and
  tool correctness read off the span ``outcome``);
* ``SLICE_PROGRAMMATIC``: a Government programmatic judge config registered only by this suite;
* ``synthetic_archive``: invented archive-shaped records that DO carry classifications (the
  sandbox telemetry carries none);
* the seeded drift windows.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[3]
for _path in (_ROOT / "services" / "api" / "tests", _ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import authz.authz_helpers as authz  # noqa: E402  # pyright: ignore[reportMissingImports]
from fastapi.testclient import TestClient  # noqa: E402
from neurosphere_api.app import create_app  # noqa: E402
from neurosphere_api.authz import configure_authz  # noqa: E402
from neurosphere_core.auth.jwt import (  # noqa: E402
    JwksCache,
    JwtConfig,
    JwtValidator,
    entra_jwks_uri,
)
from neurosphere_core.auth.scope import (  # noqa: E402
    InMemoryPolicyRepository,
    NoRevocationCheck,
    PolicyHead,
    PrincipalPolicy,
    PrincipalPseudonymizer,
    PseudonymKey,
    Role,
    ScopeDerivationConfig,
    ScopeDeriver,
    principal_document_id,
)
from neurosphere_core.capabilities import CapabilityMatrix, load_matrix  # noqa: E402
from neurosphere_core.cloud import CloudName, Settings  # noqa: E402
from neurosphere_core.evaluation.calibration import (  # noqa: E402
    HumanLabelRecord,
    JudgedItem,
    LabelSet,
    ingest_labels,
)
from neurosphere_core.evaluation.judge import (  # noqa: E402
    Judge,
    JudgeRequest,
    JudgeResponse,
    RecordedFixtureJudge,
)
from neurosphere_core.evaluation.registry import (  # noqa: E402
    DatasetItem,
    DatasetVersion,
    EvaluationRegistry,
    JudgeConfig,
    RubricVersion,
)
from neurosphere_core.evaluation.store import InMemoryEvaluationStore  # noqa: E402
from neurosphere_workers.evaluation.budget import BudgetLedger, BudgetLimits  # noqa: E402
from neurosphere_workers.evaluation.pipeline import (  # noqa: E402
    DriftCheck,
    OfflineStage,
    OnlineStage,
    PipelineSummary,
    run_pipeline,
)
from neurosphere_workers.evaluation.service import (  # noqa: E402
    OfflineRunConfig,
    OnlineRunConfig,
)
from neurosphere_workers.evaluation.source import InMemoryRecordSource  # noqa: E402

from sandbox.evaluation.loader import (  # noqa: E402
    PILOT_DATASET_ID,
    PILOT_VERSION,
    load_fixture_judge,
    load_human_labels,
    load_registry,
)

CUSTOMER = "contoso"
FIN = "government:contoso:neurosphere:domain:finance"
OPS = "government:contoso:neurosphere:domain:operations"
COMM_FIN = "commercial:contoso:neurosphere:domain:finance"
PILOT_SUBJECT = "government:contoso:foundry:agent:pilot-agent"
COMM_PILOT_SUBJECT = "commercial:contoso:foundry:agent:pilot-agent"
ALICE, BOB = authz.ALICE, authz.BOB
NOW = datetime(2026, 10, 19, 12, 0, 0, tzinfo=UTC)
HUGE = BudgetLimits(tokens=10_000_000, cost=Decimal("1000"))
RUBRIC_ID, RUBRIC_VERSION = "sbx-rubric", "1.0.0"
GOV_LLM, COMM_LLM = "sbx-judge-government", "sbx-judge-commercial"
LLM_VERSION = "1.0.0"
FRAME_ID, FRAME_VERSION = "slice-archive-frame", "1.0.0"
PILOT_TARGET_LABEL = "pilot-set target: at least 90%"

# TEST-ONLY: not part of the committed sandbox data.
SLICE_PROGRAMMATIC = JudgeConfig(
    judge_config_id="slice-programmatic-gov",
    version="1.0.0",
    judge_kind="programmatic",
    cloud="government",
    program_version="slice-outcome-1.0.0",
    approved_classifications=("public", "internal", "cui", "restricted"),
    max_output_tokens=1,
)


def clock() -> datetime:
    return NOW


# --- judges ----------


class OutcomeJudge:
    """TEST-ONLY programmatic scorer: 1.0 when the span ``outcome`` is ``success``."""

    def __init__(self) -> None:
        self.calls: list[JudgeRequest] = []

    async def score(self, request: JudgeRequest) -> JudgeResponse:
        self.calls.append(request)
        ok = request.payload.get("outcome") == "success"
        return JudgeResponse(
            value=1.0 if ok else 0.0, abstained=False, input_tokens=0, output_tokens=0
        )


class RoutingJudge:
    """Routes programmatic config ids to ``OutcomeJudge`` and everything else to the recorded
    fixture judge. Records nothing itself: the two inner judges keep their own call logs."""

    def __init__(self, llm: Judge, programmatic: OutcomeJudge, programmatic_ids: set[str]) -> None:
        self.llm = llm
        self.programmatic = programmatic
        self._ids = programmatic_ids

    async def score(self, request: JudgeRequest) -> JudgeResponse:
        if request.judge_config_id in self._ids:
            return await self.programmatic.score(request)
        return await self.llm.score(request)


class CountingLlm:
    """TEST-ONLY LLM double (no fixtures): answers 1.0 and counts every request it receives."""

    def __init__(self) -> None:
        self.calls: list[JudgeRequest] = []

    async def score(self, request: JudgeRequest) -> JudgeResponse:
        self.calls.append(request)
        return JudgeResponse(value=1.0, abstained=False, input_tokens=100, output_tokens=20)


# --- registry, labels, records -----


def build_registry() -> EvaluationRegistry:
    registry = load_registry()
    registry.judge_configs.register(SLICE_PROGRAMMATIC)
    return registry


def rubric(registry: EvaluationRegistry) -> RubricVersion:
    found = registry.rubrics.get(RUBRIC_ID, RUBRIC_VERSION)
    assert found is not None
    return found


def judge_config(
    registry: EvaluationRegistry, ident: str, version: str = LLM_VERSION
) -> JudgeConfig:
    found = registry.judge_configs.get(ident, version)
    assert found is not None
    return found


def pilot_dataset(registry: EvaluationRegistry) -> DatasetVersion:
    found = registry.datasets.get(PILOT_DATASET_ID, PILOT_VERSION)
    assert found is not None
    return found


def sandbox_label_set() -> LabelSet:
    """The versioned SYNTHETIC human-label set of the pilot set, as ingested labels."""
    data = load_human_labels()
    return ingest_labels(
        HumanLabelRecord(
            item_id=label.item_id,
            dimension="groundedness",
            label_set_version=data.version,
            value=label.value,
            labeler=label.labeller,
            labelled_at=NOW,
        )
        for label in data.labels
    )


def frame_dataset() -> DatasetVersion:
    return DatasetVersion.build(
        dataset_id=FRAME_ID,
        version=FRAME_VERSION,
        kind="sampling_frame",
        dimensions=("task_success", "tool_correctness"),
        items=(
            DatasetItem(
                item_id="frame-1",
                dimension="task_success",
                classification="public",
                payload={"frame": "SYNTHETIC archive spans"},
            ),
        ),
        data_state="redacted",
        created_at="2026-10-19T00:00:00Z",
    )


_CLASSES: tuple[str | None, ...] = ("public", "internal", "cui", "restricted", None)


def synthetic_archive(per_cell: int = 4) -> list[dict[str, Any]]:
    """SYNTHETIC archive-shaped records (the PRP-07 shape: ``doc_id`` + ``contract``) that carry a
    ``classification``, which the sandbox telemetry does not. Two domains, two agents each, every
    classification (and null), request / agent_run / tool_call spans plus one unscorable span."""
    out: list[dict[str, Any]] = []
    n = 0
    for domain in ("finance", "operations"):
        for agent in ("agent-a", "agent-b"):
            for cls in _CLASSES:
                for _ in range(per_cell):
                    for span in ("request", "tool_call"):
                        n += 1
                        out.append(_record(n, domain, agent, cls, span, ok=(n % 4 != 0)))
                n += 1
                out.append(_record(n, domain, agent, cls, "model_call", ok=True))
    return out


def _record(
    n: int, domain: str, agent: str, cls: str | None, span: str, *, ok: bool
) -> dict[str, Any]:
    contract: dict[str, Any] = {
        "schema_version": "1.0.0",
        "event_id": f"evt-{n:06d}",
        "event_time": f"2026-10-19T11:{n // 60 % 60:02d}:{n % 60:02d}Z",
        "cloud": "government",
        "customer_id": CUSTOMER,
        "domain_id": domain,
        "source_id": "src1",
        "external_agent_id": agent,
        "canonical_agent_id": f"government:{CUSTOMER}:src1:agent:{agent}",
        "span_kind": span,
        "outcome": "success" if ok else "error",
        "duration_ms": 10 + n,
        "classification": cls,
    }
    return {"doc_id": f"{n:064x}", "contract": contract}


def window(prefix: str, ones: int, zeros: int) -> tuple[JudgedItem, ...]:
    """SYNTHETIC drift window of binary groundedness scores."""
    scores = [1.0] * ones + [0.0] * zeros
    return tuple(
        JudgedItem(
            item_id=f"{prefix}-{i:03d}",
            stratum="finance/groundedness/public",
            dimension="groundedness",
            judge_config_id=GOV_LLM,
            judge_config_version=LLM_VERSION,
            score=score,
        )
        for i, score in enumerate(scores)
    )


# --- slice ----------


def offline_config(
    registry: EvaluationRegistry,
    *,
    cloud: str = "government",
    run_id: str = "pilot-gov-1",
    domain_id: str = FIN,
    subject_id: str = PILOT_SUBJECT,
) -> OfflineRunConfig:
    ident = GOV_LLM if cloud == "government" else COMM_LLM
    return OfflineRunConfig(
        run_id=run_id,
        cloud=cloud,  # type: ignore[arg-type]
        rubric=rubric(registry),
        judges={"groundedness": judge_config(registry, ident)},
        customer_id=CUSTOMER,
        domain_id=domain_id,
        subject_id=subject_id,
    )


def online_config(
    registry: EvaluationRegistry, *, run_id: str = "online-gov-1", llm: bool = False
) -> OnlineRunConfig:
    """Online run config; ``llm`` selects the Government LLM judge instead of the TEST-ONLY
    programmatic one."""
    config = judge_config(registry, GOV_LLM if llm else SLICE_PROGRAMMATIC.judge_config_id)
    return OnlineRunConfig(
        run_id=run_id,
        cloud="government",
        rubric=rubric(registry),
        judges={"task_success": config, "tool_correctness": config},
        frame_dataset_id=FRAME_ID,
        frame_dataset_version=FRAME_VERSION,
        rate=1.0,
        seed=7,
    )


def ledger(limits: BudgetLimits = HUGE) -> BudgetLedger:
    return BudgetLedger(run_limits=limits, domain_limits=limits)


@dataclass
class Slice:
    registry: EvaluationRegistry
    store: InMemoryEvaluationStore
    fixture: RecordedFixtureJudge
    outcome: OutcomeJudge
    summary: PipelineSummary
    matrix: CapabilityMatrix


async def run_slice(
    *,
    budget: BudgetLimits = HUGE,
    cloud: str = "government",
    with_online: bool = True,
    drift: bool = True,
) -> Slice:
    """The full pipeline over sandbox data into a fresh in-memory store, with the SHIPPED matrix."""
    registry = build_registry()
    fixture = load_fixture_judge()
    outcome = OutcomeJudge()
    judge = RoutingJudge(fixture, outcome, {SLICE_PROGRAMMATIC.judge_config_id})
    store = InMemoryEvaluationStore()
    matrix = load_matrix()
    domain = FIN if cloud == "government" else COMM_FIN
    subject = PILOT_SUBJECT if cloud == "government" else COMM_PILOT_SUBJECT
    config = offline_config(
        registry,
        cloud=cloud,
        run_id=f"pilot-{cloud[:4]}-1",
        domain_id=domain,
        subject_id=subject,
    )
    checks: list[DriftCheck] = []
    if drift:
        common: dict[str, Any] = {
            "cloud": cloud,
            "customer_id": CUSTOMER,
            "domain_id": domain,
            "subject_id": subject,
            "dimension": "groundedness",
            "threshold": 0.25,
            "min_n": 15,
        }
        # Stable: a recorded baseline at the pilot's own level (SYNTHETIC window).
        checks.append(DriftCheck(baseline=window("stable", 36, 4), **common))
        # Seeded shift: a SYNTHETIC baseline at 50% grounded versus the real current scores.
        checks.append(DriftCheck(baseline=window("shift", 20, 20), **common))
    summary = await run_pipeline(
        registry=registry,
        judge=judge,
        matrix=matrix,
        store=store,
        ledger=ledger(budget),
        clock=clock,
        offline=OfflineStage(dataset=pilot_dataset(registry), config=config),
        labels=sandbox_label_set(),
        online=(
            OnlineStage(
                source=InMemoryRecordSource(synthetic_archive()),
                config=online_config(registry),
                frame=frame_dataset(),
            )
            if with_online
            else None
        ),
        drift_checks=checks,
    )
    return Slice(registry, store, fixture, outcome, summary, matrix)


# --- government-bound authz harness ----------


def _pseudonymizer() -> PrincipalPseudonymizer:
    return PrincipalPseudonymizer(PseudonymKey(bytes(range(32)), reference=authz.KEY_REFERENCE))


def gov_policy(object_id: str, *domains: str) -> PrincipalPolicy:
    pid = _pseudonymizer().principal_id(
        cloud=CloudName.GOVERNMENT,
        customer_id=CUSTOMER,
        tenant_id=authz.TENANT,
        object_id=object_id,
        kind="user",
    )
    return PrincipalPolicy(
        id=principal_document_id(pid),
        customer_id=CUSTOMER,
        principal_id=pid,
        domain_memberships=(FIN, OPS),
        role_assignments=(authz.role(Role.VIEWER, *domains),),
        grants=(),
    )


@dataclass
class GovHarness:
    app: Any
    client: TestClient
    clock: authz.FakeClock

    def auth(self, object_id: str) -> dict[str, str]:
        token = authz.dev_issuer().mint(
            audience=authz.AUDIENCE, object_id=object_id, now=self.clock.now
        )
        return {"Authorization": f"Bearer {token}"}


def gov_harness(*policies: PrincipalPolicy) -> GovHarness:
    """The PRP-06 authz harness bound to the Government cloud. The app uses the DEFAULT routers
    only, so the evaluation router must come from ``REGISTERED``."""
    fake_clock = authz.FakeClock()
    repo = InMemoryPolicyRepository()
    repo.put_head(PolicyHead(customer_id=CUSTOMER, policy_version=authz.POLICY_VERSION))
    for policy in policies:
        repo.put_principal(policy)
    deriver = ScopeDeriver(
        ScopeDerivationConfig(
            cloud=CloudName.GOVERNMENT, tenant_id=authz.TENANT, customer_id=CUSTOMER
        ),
        policy_repository=repo,
        pseudonymizer=_pseudonymizer(),
        revocation_checker=NoRevocationCheck(),
        clock=fake_clock,
    )
    config = JwtConfig(
        env="local",
        cloud=CloudName.GOVERNMENT,
        tenant_id=authz.TENANT,
        audiences=(authz.AUDIENCE,),
        dev_issuer=authz.dev_issuer().trust(),
    )
    jwks = JwksCache(
        authz.StandInJwksFetcher(entra_jwks_uri(CloudName.GOVERNMENT, authz.TENANT)),
        clock=fake_clock,
        ttl_seconds=3600,
        min_refresh_interval_seconds=300,
    )
    app = create_app(Settings(env="local", cloud=CloudName.GOVERNMENT), extra_routers={})
    configure_authz(
        app,
        authenticator=JwtValidator(config, jwks, clock=fake_clock),
        scope_source=deriver,
        clock=fake_clock,
    )
    return GovHarness(app, TestClient(app, raise_server_exceptions=False), fake_clock)


def two_domain_harness(store: InMemoryEvaluationStore) -> GovHarness:
    """ALICE views finance only, BOB operations only; the store is wired like a deployment would."""
    h = gov_harness(gov_policy(ALICE, FIN), gov_policy(BOB, OPS))
    h.app.state.evaluation_store = store
    h.app.state.evaluation_pilot_dataset_ids = frozenset({PILOT_DATASET_ID})
    return h


def generate_government_telemetry(out: Path) -> Path:
    """SYNTHETIC sandbox telemetry (PRP-03 generator) for a Government customer, small profile.
    Returns the ``telemetry.ndjson`` path. The generator writes no ``classification`` field."""
    from sandbox.config import BadEventRates, GenerateConfig, Profile
    from sandbox.generate import generate

    profile = Profile(
        "custom",
        domains=2,
        agents=12,
        days=3,
        traces_per_agent_day=3.0,
        cost_spikes=0,
        latency_regressions=0,
        unused_agents=0,
        duplicate_pairs=0,
    )
    generate(
        GenerateConfig(
            seed=1,
            profile=profile,
            cloud="government",
            customer=CUSTOMER,
            rates=BadEventRates(),
        ),
        out,
    )
    return out / "telemetry.ndjson"
