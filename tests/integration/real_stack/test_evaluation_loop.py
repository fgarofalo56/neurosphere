"""PRP-16 round 2 item 13: the evaluation loop end to end against the compose emulators.

Needs the compose emulators ALREADY running (Cosmos 8081, Event Hubs 5672, Azurite 10000); this
suite never starts, stops or restarts compose. Export ``NS_PROBE_COSMOS_URL=http://127.0.0.1:8081/``.

What runs where (same split as ``test_catalog_discovery.py``): the API (``create_app`` +
``configure_ingest`` + ``compose_app``, only the token validator and the policy repository swapped)
and the ``ingestion`` and ``evaluation`` worker roles run IN THIS PROCESS against the emulators.
The evaluation role is built by the production factory (``build_evaluation``) from
``NS_WORKER_EVAL_*`` settings that mirror the compose ``workers`` service (fixture judge, the
sandbox pilot dataset, its domain and subject, the sandbox registry directory), with two test-only
differences: the calibration sample cap is 30 and the online sampling rate is 1.0 (the sandbox
slice is small; compose keeps the 0.1 default).

Flow: sandbox traces (with telemetry ``classification``) go through the real ingest edge and the
ingestion role into the archive; evaluation tick 1 (online stage + offline pilot + calibration
sample) opens ``evaluation_dispute`` review items; a steward decides >= 20 of them over the real
review API (approve and reject mixed); tick 2 (a freshly built role, so its periodic stages run
again) turns the decisions into human labels, calibrates the judge and stores the pilot results;
``/quality`` over HTTP then reports a pilot grounded rate with an interval. An out-of-scope caller
gets 403 on ``/quality`` and ``/calibration-samples``.

Evidence is written to ``temp/evidence/G12/evaluation/compose-loop-<date>.md`` (or, with
``NS_EVIDENCE_WRITE=1``, the committed ``docs/evidence/G12/evaluation/``): emulator, bounded
feasibility, NOT a live claim.

Run: ``NS_PROBE_COSMOS_URL=http://127.0.0.1:8081/ MSYS_NO_PATHCONV=1 uv run pytest -q -m integration
tests/integration/real_stack/test_evaluation_loop.py``. Emulator limits (G12): no auth, no RU
accounting.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import tempfile
import time
import uuid
from collections import Counter
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

import httpx
import pytest
from azure.core.exceptions import ResourceNotFoundError
from azure.storage.blob.aio import ContainerClient
from neurosphere_api.app import create_app
from neurosphere_api.ingest import IngestSettings
from neurosphere_api.ingest.bootstrap import configure_ingest_from_settings
from neurosphere_api.runtime import CompositionOverrides, compose_app
from neurosphere_api.runtime.pseudonym import local_dev_pseudonym_key
from neurosphere_core.auth.jwt import JwtValidator
from neurosphere_core.auth.jwt.config import normalize_tenant_id
from neurosphere_core.auth.scope import (
    InMemoryPolicyRepository,
    PolicyHead,
    PolicyRoleAssignment,
    PrincipalPolicy,
    PrincipalPseudonymizer,
    Role,
    principal_document_id,
)
from neurosphere_core.clients import ClientLifetime, create_cosmos_client
from neurosphere_core.cloud import CloudName, Settings
from neurosphere_core.stores import ensure_local_containers
from neurosphere_workers.runtime.factories import RuntimeConfig, role_factories
from neurosphere_workers.runtime.identity import resolve_pseudonym_key
from neurosphere_workers.runtime.supervisor import RoleSupervisor

from integration.ingestion.support import (
    Producer,
    azurite_connection_string,
    cloudevent,
    push_cloudevents,
    write_producers_file,
)
from integration.workers_runtime.support import (
    EVENTHUBS_CONNECTION,
    REPO_ROOT,
    WORKER_OBJECT_ID,
    WORKER_TENANT_ID,
)

from .conftest import real_stack_tenant

pytestmark = pytest.mark.integration

CUSTOMER: Final = "synthco"
SOURCE: Final = "sandbox-gateway"
ENDPOINT: Final = "http://127.0.0.1:8081"
DOMAIN: Final = "commercial:synthco:sandbox:domain:dom-001"
OTHER_DOMAIN: Final = "commercial:synthco:sandbox:domain:other-eval"
SUBJECT: Final = "commercial:synthco:sandbox:agent:a-000000"
PILOT_DATASET: Final = "sbx-groundedness-pilot"
DATA_DIR: Final = REPO_ROOT / "sandbox" / "evaluation" / "data"
#: Runs write to the gitignored ``temp/`` so a local run never dirties the tree; set
#: ``NS_EVIDENCE_WRITE=1`` to refresh the committed evidence under docs/evidence/G12/evaluation.
EVIDENCE_DIR: Final = (
    REPO_ROOT / "docs" / "evidence" / "G12" / "evaluation"
    if os.environ.get("NS_EVIDENCE_WRITE") == "1"
    else REPO_ROOT / "temp" / "evidence" / "G12" / "evaluation"
)
REVIEWER_OID: Final = "6c1d2e3f-4a5b-4c6d-8e7f-90a1b2c3d4e5"
OUT_OF_SCOPE_OID: Final = "7d2e3f40-5b6c-4d7e-8f90-a1b2c3d4e5f6"
EVAL: Final = "/api/v1/evaluation"
REVIEW: Final = "/api/v1/review"
DISPUTE: Final = "evaluation_dispute"
MIN_DECISIONS: Final = 20
SLICE_DOCS: Final = 600
POLL_SECONDS: Final = 3.0
INGEST_WAIT: Final = 180.0
TICK_WAIT: Final = 300.0


class Gaps:
    """Product gaps observed during the run; written to the evidence file, never patched."""

    def __init__(self) -> None:
        self.notes: list[str] = []

    def add(self, note: str) -> None:
        self.notes.append(note)


def _slice_docs() -> list[dict[str, Any]]:
    """A bounded slice of one sandbox domain, classified, re-timed to end a minute ago."""
    from sandbox.config import PROFILES, BadEventRates, GenerateConfig
    from sandbox.generate import generate

    rates = BadEventRates(duplicate=0.0, out_of_order=0.0, malformed=0.0, missing_optional=0.0)
    cfg = GenerateConfig(seed=7, profile=PROFILES["tiny"], cloud="commercial", rates=rates)
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        generate(cfg, out)
        lines = (out / "telemetry.ndjson").read_text(encoding="utf-8").splitlines()
    docs = [json.loads(line) for line in lines if line]
    docs = [d for d in docs if d["domain_id"] == DOMAIN]
    docs.sort(key=lambda d: d["event_time"])
    docs = docs[:SLICE_DOCS]

    def parse(value: str) -> datetime:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    shift = (datetime.now(UTC) - timedelta(seconds=60)) - parse(docs[-1]["event_time"])
    for doc in docs:
        shifted = parse(doc["event_time"]) + shift
        doc["event_time"] = shifted.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    return docs


def _principal(oid: str) -> str:
    return PrincipalPseudonymizer(local_dev_pseudonym_key()).principal_id(
        cloud=CloudName.COMMERCIAL,
        customer_id=CUSTOMER,
        tenant_id=real_stack_tenant(),
        object_id=oid,
        kind="user",
    )


def _api_policy() -> InMemoryPolicyRepository:
    """A domain steward (``catalog.curate``: allowed to decide dispute items; neither admin nor
    maker) on the pilot domain, and an analyst scoped to a different domain."""
    repo = InMemoryPolicyRepository()
    repo.put_head(PolicyHead(customer_id=CUSTOMER, policy_version="v1"))
    for oid, domain, role in (
        (REVIEWER_OID, DOMAIN, Role.DOMAIN_STEWARD),
        (OUT_OF_SCOPE_OID, OTHER_DOMAIN, Role.ANALYST),
    ):
        principal = _principal(oid)
        repo.put_principal(
            PrincipalPolicy(
                id=principal_document_id(principal),
                customer_id=CUSTOMER,
                principal_id=principal,
                domain_memberships=(domain,),
                role_assignments=(
                    PolicyRoleAssignment(
                        assignment_id=f"ra-{oid[:4]}", role=role, domain_ids=(domain,)
                    ),
                ),
            )
        )
    return repo


async def _seed_worker_policy(cosmos: Any, cfg: RuntimeConfig) -> None:
    """Grant the worker principal viewer on the pilot domain (the one derivation path)."""
    key = resolve_pseudonym_key(cfg.auth, env="local")
    principal = PrincipalPseudonymizer(key).principal_id(
        cloud=CloudName.COMMERCIAL,
        customer_id=CUSTOMER,
        tenant_id=normalize_tenant_id(WORKER_TENANT_ID),
        object_id=WORKER_OBJECT_ID,
        kind="service_principal",
    )
    policy = PrincipalPolicy(
        id=principal_document_id(principal),
        customer_id=CUSTOMER,
        principal_id=principal,
        domain_memberships=(DOMAIN,),
        role_assignments=(
            PolicyRoleAssignment(assignment_id="ra-worker", role=Role.VIEWER, domain_ids=(DOMAIN,)),
        ),
    )
    container = cosmos.get_database_client(cfg.store.database).get_container_client(
        cfg.auth.policy_container
    )
    await container.upsert_item(body=policy.model_dump(mode="json"))
    head = PolicyHead(customer_id=CUSTOMER, policy_version="it-1")
    await container.upsert_item(body=head.model_dump(mode="json"))


@pytest.fixture
def stack_env(monkeypatch: pytest.MonkeyPatch, emulator_env: None) -> dict[str, str]:
    run = uuid.uuid4().hex[:8]
    env = {
        "NS_COSMOS_ENDPOINT": ENDPOINT,
        "NS_EVENTHUBS_CONNECTION_STRING": EVENTHUBS_CONNECTION,
        "NS_BLOB_CONNECTION_STRING": azurite_connection_string(),
        "NS_STORE_DATABASE": f"it_ev_{run}",
        "NS_INGESTION_CHECKPOINT_CONTAINER": f"ns-ckpt-{run}",
        "NS_INGESTION_MAX_WAIT_SECONDS": "1",
        "NS_ARCHIVE_CONTAINER": f"ns-arch-{run}",
        "NS_QUARANTINE_CONTAINER": f"ns-quar-{run}",
        "NS_AUTH_CUSTOMER_ID": CUSTOMER,
        "NS_WORKER_TENANT_ID": WORKER_TENANT_ID,
        "NS_WORKER_OBJECT_ID": WORKER_OBJECT_ID,
        "NS_WORKER_POLL_SECONDS": "1",
        "NS_WORKER_HEALTH_PORT": "0",
        "NS_SEARCH_PROVIDER": "fixture",
        # The compose `workers` evaluation settings (docker-compose.yml), data dir on the host.
        "NS_WORKER_EVAL_DATA_DIR": str(DATA_DIR),
        "NS_WORKER_EVAL_JUDGE": "fixture",
        "NS_WORKER_EVAL_PILOT_DATASET_IDS": PILOT_DATASET,
        "NS_WORKER_EVAL_PILOT_DOMAIN_ID": DOMAIN,
        "NS_WORKER_EVAL_PILOT_SUBJECT_ID": SUBJECT,
        # Test-only: a larger sample, every archived span sampled, and each stage runs once per
        # freshly built role (the periodic interval never elapses inside a tick).
        "NS_WORKER_EVAL_CALIBRATION_SAMPLE_CAP": "30",
        "NS_WORKER_EVAL_RATE": "1.0",
        "NS_WORKER_EVAL_OFFLINE_INTERVAL_SECONDS": "86400",
        "NS_WORKER_EVAL_INTERVAL_SECONDS": "86400",
        # The API side (compose `api` service).
        "NS_EVALUATION_PILOT_DATASET_IDS": PILOT_DATASET,
    }
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    for name in ("NS_CLOUD", "NS_AUTH_PSEUDONYM_KEY", "NS_AUTH_PSEUDONYM_KEY_REFERENCE"):
        monkeypatch.delenv(name, raising=False)
    return env


async def _until[T](
    probe: Callable[[], Awaitable[T | None]], limit_s: float
) -> tuple[T | None, float]:
    """Bounded poll (3 s between probes). Returns (first truthy value or None, seconds waited)."""
    started = time.monotonic()
    value = await probe()
    while not value and time.monotonic() - started < limit_s:
        await asyncio.sleep(POLL_SECONDS)
        value = await probe()
    return value, time.monotonic() - started


@contextlib.asynccontextmanager
async def _api(validator: JwtValidator, producers_file: Path) -> AsyncIterator[httpx.AsyncClient]:
    settings = Settings()
    app = create_app(settings)
    configured = configure_ingest_from_settings(
        app,
        settings,
        IngestSettings(
            producers_file=producers_file, rate_limit_rps=100_000, rate_limit_burst=100_000
        ),
    )
    assert configured is True
    compose_app(
        app,
        settings,
        CompositionOverrides(authenticator=validator, policy_repository=_api_policy()),
    )
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://api.invalid"
        ) as client:
            yield client


async def _archive_blobs(connection: str, container: str) -> int:
    count = 0
    # The ingestion role creates the container on its first write.
    with contextlib.suppress(ResourceNotFoundError):
        async with ContainerClient.from_connection_string(connection, container) as blob:
            async for _ in blob.list_blobs():
                count += 1
    return count


async def _run_evaluation_tick(
    cfg: RuntimeConfig, done: Callable[[], Awaitable[bool]]
) -> tuple[float, dict[str, str]]:
    """Build the production evaluation role fresh (so each periodic stage runs once), run it under
    a supervisor until ``done()`` holds, then stop it. Returns (seconds, role states)."""
    supervisor = RoleSupervisor(role_factories(cfg, ("evaluation",)))
    runner = asyncio.create_task(supervisor.run())
    states: dict[str, str] = {}
    try:
        ok, seconds = await _until(lambda: _truthy(done()), TICK_WAIT)
        states = {r["name"]: f"{r['state']}:{r['reason']}" for r in supervisor.snapshot()}
        assert ok, f"evaluation tick did not finish in {TICK_WAIT}s; roles={states}"
    finally:
        supervisor.request_shutdown()
        with contextlib.suppress(Exception):
            await asyncio.wait_for(runner, timeout=120)
    return seconds, states


async def _truthy(awaitable: Awaitable[bool]) -> bool | None:
    return True if await awaitable else None


def _write_evidence(facts: dict[str, Any], gaps: Gaps) -> Path:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y-%m-%d")
    path = EVIDENCE_DIR / f"compose-loop-{stamp}.md"
    rate = facts["pilot_grounded_rate"]
    trend_states = sorted(facts["trend_calibration_states"])
    gap_lines = "\n".join(f"- {note}" for note in gaps.notes) or "- none observed in this run"
    body = f"""# Evaluation loop on the compose emulators ({stamp})

Scope: **emulator, bounded feasibility, not a live claim.** Cosmos, Event Hubs and Azurite from
`docker compose` (127.0.0.1), the API and the `ingestion` + `evaluation` worker roles in-process,
fixture judge, synthetic sandbox data only. Nothing here is a Government, hosted or FedRAMP claim,
and the live judge gate (G16) stays OPEN. Test: `tests/integration/real_stack/test_evaluation_loop.py`
(`pytest.mark.integration`, never runs in CI).

Test-only settings versus compose: `NS_WORKER_EVAL_CALIBRATION_SAMPLE_CAP=30`,
`NS_WORKER_EVAL_RATE=1.0` (compose keeps the 0.1 default), periodic intervals set long so each
freshly built role runs each stage exactly once (tick 1, tick 2).

| Measure | Value |
|---|---|
| Sandbox spans pushed through the ingest edge | {facts["spans_pushed"]} (classifications: {facts["classifications"]}) |
| Archive blobs written | {facts["archive_blobs"]} |
| Ingest to archive | {facts["ingest_seconds"]:.1f} s |
| Tick 1 (online + offline + sample) | {facts["tick1_seconds"]:.1f} s |
| `evaluation_dispute` items opened | {facts["items_opened"]} |
| Calibration-sample reads OK / payload withheld | {facts["samples_read"]} / {facts["samples_withheld"]} (classes withheld: {facts["withheld_classes"]}) |
| Items decided (approved / rejected) | {facts["decided"]} ({facts["approved"]} / {facts["rejected"]}) |
| Tick 2 (labels + calibration + pilot results) | {facts["tick2_seconds"]:.1f} s |
| Pilot grounded rate | {rate["value"]:.3f} (n={rate["n"]}, method {rate["method"]}) |
| Interval | [{rate["lower"]:.3f}, {rate["upper"]:.3f}] at level {rate["level"]} |
| Target label | {rate["target_label"]} |
| Trend calibration states (all dimensions) | {trend_states} |
| `missing_labels` (judged / labelled / missing) | {facts["missing_labels"]} |
| Online coverage (sampled / population) | {facts["coverage_sampled"]} / {facts["coverage_population"]} over {facts["coverage_strata"]} strata |
| Cohen's kappa | not exposed by `/quality`; held in the stored calibration report only |
| Out-of-scope caller | `/quality` {facts["outside_quality"]}, `/calibration-samples` {facts["outside_samples"]} |

Reviewer: a `domain_steward` on the pilot domain (holds `catalog.curate`; not an admin, not a maker).
Role states at tick end: tick 1 {facts["tick1_states"]}; tick 2 {facts["tick2_states"]}.

## Gaps found

{gap_lines}

## Emulator versus live (G12)

The emulators accept any token and do no RU accounting; the HITL, evaluation and policy stores are
real Cosmos containers on the emulator, so query shapes and partitioning are exercised, but latency
and throttling are not representative. The judge is the recorded-fixture judge: the pilot rate shows
the pipeline works end to end, not that a model meets the 90% pilot-set target.
"""  # noqa: E501
    path.write_text(body, encoding="utf-8")
    return path


async def test_evaluation_loop_labels_calibrates_and_reports_for_in_scope_caller_only(
    stack_env: dict[str, str],
    stand_in_validator: JwtValidator,
    stand_in_token: Callable[..., dict[str, str]],
    tmp_path: Path,
) -> None:
    gaps = Gaps()
    docs = _slice_docs()
    producer = Producer("p-eval", CUSTOMER, "commercial", {SOURCE: "gateway"})
    producers_file = write_producers_file(tmp_path, [producer])
    reviewer, outsider = stand_in_token(REVIEWER_OID), stand_in_token(OUT_OF_SCOPE_OID)
    cfg = RuntimeConfig.from_env()
    database = cfg.store.database
    connection = stack_env["NS_BLOB_CONNECTION_STRING"]
    archive = stack_env["NS_ARCHIVE_CONTAINER"]
    ingestion = RoleSupervisor(role_factories(cfg, ("ingestion",)))
    ingest_runner: asyncio.Task[None] | None = None
    facts: dict[str, Any] = {
        "spans_pushed": len(docs),
        "classifications": dict(
            sorted(Counter(str(d.get("classification")) for d in docs).items())
        ),
    }

    async with ClientLifetime() as lifetime:
        cosmos = create_cosmos_client(cfg.settings, lifetime=lifetime)
        try:
            await ensure_local_containers(cosmos, cfg.settings, database=database)
            await _seed_worker_policy(cosmos, cfg)
            async with _api(stand_in_validator, producers_file) as client:
                # 1. Ingest through the real edge; the ingestion role archives into Azurite.
                pushed = await push_cloudevents(
                    client, producer, [cloudevent("telemetry", d) for d in docs]
                )
                assert pushed.accepted == len(docs), pushed
                ingest_runner = asyncio.create_task(ingestion.run())

                last = {"count": -1}

                async def archive_settled() -> bool:
                    count = await _archive_blobs(connection, archive)
                    settled = count > 0 and count == last["count"]
                    last["count"] = count
                    return settled

                settled, facts["ingest_seconds"] = await _until(
                    lambda: _truthy(archive_settled()), INGEST_WAIT
                )
                facts["archive_blobs"] = last["count"]
                assert settled, f"archive did not settle; blobs={last['count']}"

                # 2. Tick 1: online stage + offline pilot + calibration sample.
                async def disputes() -> list[dict[str, Any]]:
                    got = await client.get(
                        f"{REVIEW}/domains/{DOMAIN}/items",
                        headers=reviewer,
                        params={"kind": DISPUTE, "limit": 100},
                    )
                    assert got.status_code == 200, got.text
                    return list(got.json()["items"])

                async def have_items() -> bool:
                    return len(await disputes()) >= MIN_DECISIONS

                facts["tick1_seconds"], facts["tick1_states"] = await _run_evaluation_tick(
                    cfg, have_items
                )
                items = await disputes()
                facts["items_opened"] = len(items)
                assert len(items) >= MIN_DECISIONS, len(items)
                assert {i["kind"] for i in items} == {DISPUTE}
                assert {i["state"] for i in items} == {"pending"}

                # 3. Each item's calibration context is readable; restricted payload is withheld.
                withheld_classes: dict[str, int] = {}
                read = withheld = 0
                for item in items:
                    got = await client.get(
                        f"{EVAL}/domains/{DOMAIN}/calibration-samples",
                        headers=reviewer,
                        params={"subject_ref": item["subject_ref"]},
                    )
                    assert got.status_code == 200, (item["subject_ref"], got.text)
                    sample = got.json()
                    read += 1
                    assert sample["subject_ref"] == item["subject_ref"]
                    assert sample["dimension"] and sample["dataset_id"] == PILOT_DATASET
                    classification = sample["classification"]
                    if classification in (None, "restricted"):
                        assert sample["payload"] is None, sample
                        assert sample["payload_withheld"] is True, sample
                    if sample["payload_withheld"]:
                        withheld += 1
                        key = str(classification)
                        withheld_classes[key] = withheld_classes.get(key, 0) + 1
                    else:
                        assert sample["payload"] is not None, sample
                facts.update(
                    samples_read=read, samples_withheld=withheld, withheld_classes=withheld_classes
                )
                if not withheld_classes:
                    gaps.add(
                        "Not a product defect: the 8 restricted pilot items are never judged "
                        "(fail-closed guard), so none was sampled for review and the "
                        "payload-withheld branch of the calibration-samples route is covered "
                        "only by the API unit tests, not by this loop."
                    )

                # 4. Decide >= 20 items as the steward, mixing approve and reject.
                approved = rejected = 0
                for index, item in enumerate(sorted(items, key=lambda i: i["item_id"])):
                    if index >= MIN_DECISIONS + 4:
                        break
                    verdict = "approved" if index % 3 == 0 else "rejected"
                    got = await client.post(
                        f"{REVIEW}/domains/{DOMAIN}/items/{item['item_id']}/decisions",
                        headers=reviewer,
                        json={"decision": verdict, "reason": "compose loop calibration label"},
                    )
                    assert got.status_code == 200, (got.status_code, got.text)
                    assert got.json()["state"] in ("approved", "rejected"), got.text
                    approved += verdict == "approved"
                    rejected += verdict == "rejected"
                facts.update(decided=approved + rejected, approved=approved, rejected=rejected)
                assert approved >= 1 and rejected >= 1 and approved + rejected >= MIN_DECISIONS

                # 5. Tick 2 (fresh role): labels -> calibration -> pilot results; read /quality.
                async def quality_body() -> dict[str, Any] | None:
                    got = await client.get(f"{EVAL}/domains/{DOMAIN}/quality", headers=reviewer)
                    assert got.status_code == 200, got.text
                    body: dict[str, Any] = got.json()
                    return body if body["pilot_grounded_rate"]["value"] is not None else None

                async def have_rate() -> bool:
                    return await quality_body() is not None

                facts["tick2_seconds"], facts["tick2_states"] = await _run_evaluation_tick(
                    cfg, have_rate
                )
                quality = await quality_body()
                assert quality is not None
                rate = quality["pilot_grounded_rate"]
                facts["pilot_grounded_rate"] = rate
                facts["missing_labels"] = quality["missing_labels"]
                points = [p for t in quality["trends"] for p in t["points"]]
                facts["trend_calibration_states"] = {p["calibration_state"] for p in points}
                coverage = quality["coverage"]
                facts["coverage_strata"] = len(coverage)
                facts["coverage_sampled"] = sum(c["sampled"] for c in coverage)
                facts["coverage_population"] = [c["population"] for c in coverage]

                # 6. Out-of-scope caller: 403 on both routes (details withheld).
                out_quality = await client.get(f"{EVAL}/domains/{DOMAIN}/quality", headers=outsider)
                out_sample = await client.get(
                    f"{EVAL}/domains/{DOMAIN}/calibration-samples",
                    headers=outsider,
                    params={"subject_ref": items[0]["subject_ref"]},
                )
                facts["outside_quality"] = out_quality.status_code
                facts["outside_samples"] = out_sample.status_code
                outside_text = out_quality.text + out_sample.text
        finally:
            ingestion.request_shutdown()
            if ingest_runner is not None:
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(ingest_runner, timeout=120)
            with contextlib.suppress(Exception):
                await cosmos.delete_database(database)
            for name in (
                archive,
                stack_env["NS_QUARANTINE_CONTAINER"],
                stack_env["NS_INGESTION_CHECKPOINT_CONTAINER"],
            ):
                with contextlib.suppress(Exception):
                    async with ContainerClient.from_connection_string(connection, name) as blob:
                        await blob.delete_container()

    # Pilot grounded rate: non-null, with an interval and the pilot-set target label.
    print(f"EVALUATION LOOP FACTS: {json.dumps(facts, default=sorted)}")
    evidence = _write_evidence(facts, gaps)
    print(f"EVIDENCE: {evidence}")
    assert rate["value"] is not None and 0.0 <= rate["value"] <= 1.0, rate
    assert rate["lower"] is not None and rate["upper"] is not None, rate
    assert rate["lower"] <= rate["value"] <= rate["upper"], rate
    assert rate["n"] > 0 and rate["method"] == "wilson_score", rate
    assert rate["target_label"] == "pilot-set target: at least 90%", rate

    # The judge is calibrated on the pilot trend points once >= 20 labels were decided.
    groundedness = [t for t in quality["trends"] if t["dimension"] == "groundedness"]
    assert groundedness, [t["dimension"] for t in quality["trends"]]
    assert any(p["calibration_state"] == "calibrated" for t in groundedness for p in t["points"]), (
        groundedness
    )

    # missing_labels is consistent: counts add up and never negative.
    missing = quality["missing_labels"]
    if missing["judged"] is not None and missing["labelled"] is not None:
        assert missing["missing"] == missing["judged"] - missing["labelled"], missing
        assert missing["labelled"] >= facts["decided"] or missing["labelled"] > 0, missing
        assert missing["missing"] >= 0, missing

    # Online coverage is non-zero for the classified spans (Commercial Foundry matrix row).
    assert facts["coverage_sampled"] > 0, coverage

    # Out-of-scope caller: 403, and nothing of the domain leaks in the body.
    assert facts["outside_quality"] == 403, facts["outside_quality"]
    assert facts["outside_samples"] == 403, facts["outside_samples"]
    assert PILOT_DATASET not in outside_text and "pilot_grounded_rate" not in outside_text
