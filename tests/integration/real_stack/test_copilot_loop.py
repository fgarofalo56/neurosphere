"""PRP-19 round 2 item 15: the copilot and report-creation loop on the compose emulators.

Needs the compose emulators ALREADY running (Cosmos on 127.0.0.1:8081); never starts or stops
compose. Each run uses a throwaway Cosmos database that is deleted afterwards.

What is real: the composed API in-process (``create_app`` + ``compose_app`` with the default
authz, data, planes, action plane, reports and copilot builders) over Cosmos; the catalog and
recommendation rows are written through the app's own stores; the model is the REAL
``ApprovedEndpointAdapter`` built through ``resolve_adapters`` / ``create_adapter`` for Commercial /
centralus / ``model_gpt_4_1_mini`` / ``Global Standard`` (the capability matrix must enable it) and
handed over via ``CompositionOverrides.model_adapter``.

What is stood in: the token validator (``conftest.py``), the policy repository (in-memory, so the
test can grant roles), the credential (a static fake ``AsyncTokenCredential``) and the HTTP
transport, which replays hand-authored provider-format streams from
``fixtures/copilot_loop/*.json``. NOT exercised: a live model, the Playwright UI, Government.

Evidence: ``temp/evidence/G12/copilot/`` by default; ``NS_EVIDENCE_WRITE=1`` refreshes the committed
``docs/evidence/G12/copilot/``.

Run: ``MSYS_NO_PATHCONV=1 uv run pytest -q -m integration
tests/integration/real_stack/test_copilot_loop.py -s``.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import TracebackType
from typing import Any, Final

import httpx
import pytest
from azure.core.credentials import AccessToken
from fastapi import FastAPI
from neurosphere_api.app import create_app
from neurosphere_api.runtime import CompositionOverrides, compose_app
from neurosphere_api.runtime.pseudonym import local_dev_pseudonym_key
from neurosphere_contracts.evaluation.v1.evaluation_result import EvaluationResult
from neurosphere_contracts.recommendations.v1.recommendation import Recommendation
from neurosphere_contracts.scope.v1.identity_scope import IdentityScope as ContractScope
from neurosphere_core.auth.jwt import JwtValidator
from neurosphere_core.auth.scope import (
    InMemoryPolicyRepository,
    PolicyHead,
    PolicyRoleAssignment,
    PrincipalPolicy,
    PrincipalPseudonymizer,
    Role,
    principal_document_id,
)
from neurosphere_core.catalog.repo.documents import parse_entity
from neurosphere_core.clients import ClientLifetime, create_cosmos_client
from neurosphere_core.cloud import CloudName, Settings
from neurosphere_core.copilot.models import (
    AdapterConfig,
    ApprovedEndpointAdapter,
    create_adapter,
    resolve_adapters,
)
from neurosphere_core.copilot.models.recorded import HttpRecording, replay_transport
from neurosphere_core.scope import IdentityScope

from .conftest import real_stack_tenant

pytestmark = pytest.mark.integration

LOOPBACK: Final = "http://127.0.0.1:8081"
CUSTOMER: Final = "synthco"  # the NS_ENV=local default customer binding
REPO_ROOT: Final = Path(__file__).resolve().parents[3]
FIXTURES: Final = Path(__file__).parent / "fixtures" / "copilot_loop"
SCHEMAS: Final = REPO_ROOT / "packages" / "contracts" / "schemas"
EVIDENCE_DIR: Final = (
    REPO_ROOT / "docs" / "evidence" / "G12" / "copilot"
    if os.environ.get("NS_EVIDENCE_WRITE") == "1"
    else REPO_ROOT / "temp" / "evidence" / "G12" / "copilot"
)
COPILOT: Final = "/api/v1/copilot"
REPORTS: Final = "/api/v1/reports/domains"
ACTIONS: Final = "/api/v1/actions/domains"
ENDPOINT: Final = "https://ns-loop-test.openai.azure.com"
MODEL_FEATURE: Final = "model_gpt_4_1_mini"
SKU: Final = "Global Standard"
USER_A: Final = "6c1d2e3f-4a5b-4c6d-8e7f-90a1b2c3d4e5"  # analyst A+B, auditor on A
USER_B: Final = "7d2e3f40-5b6c-4d7e-8f90-a1b2c3d4e5f6"  # viewer on A only
USER_C: Final = "8e3f4051-6c7d-4e8f-9a01-b2c3d4e5f607"  # viewer on an unrelated domain
USER_D: Final = "9f405162-7d8e-4f90-8b12-c3d4e5f60718"  # no policy at all


# -- the model: real adapter, fake credential, replayed provider streams ---------------------------


class _StaticCredential:
    """An ``AsyncTokenCredential`` that returns a dummy token (never a real credential)."""

    async def get_token(self, *scopes: str, **kwargs: Any) -> AccessToken:
        return AccessToken("not-a-real-token", int(time.time()) + 3600)

    async def close(self) -> None:
        return None

    async def __aenter__(self) -> _StaticCredential:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None = None,
        exc_value: BaseException | None = None,
        traceback: TracebackType | None = None,
    ) -> None:
        return None


def _expand(node: Any, subs: dict[str, str]) -> Any:
    """Substitute ``{{NAME}}`` placeholders (JSON-escaped) in every string of a fixture."""
    if isinstance(node, str):
        for name, value in subs.items():
            node = node.replace("{{" + name + "}}", value)
        return node
    if isinstance(node, list):
        return [_expand(item, subs) for item in node]
    if isinstance(node, dict):
        return {k: _expand(v, subs) for k, v in node.items()}
    return node


def _provider_chunks(item: Any) -> list[Any]:
    """Serialize object-valued ``function.arguments`` to the JSON string a provider streams, split
    over two deltas the way a real stream is."""
    if not isinstance(item, dict):
        return [item]
    for choice in item.get("choices", []):
        for part in choice.get("delta", {}).get("tool_calls", []):
            arguments = part.get("function", {}).get("arguments")
            if isinstance(arguments, dict):
                text = json.dumps(arguments)
                cut = len(text) // 2
                part["function"]["arguments"] = text[:cut]
                tail = {
                    "choices": [
                        {
                            "index": choice["index"],
                            "delta": {
                                "tool_calls": [
                                    {"index": part["index"], "function": {"arguments": text[cut:]}}
                                ]
                            },
                            "finish_reason": None,
                        }
                    ]
                }
                return [item, tail]
    return [item]


def load_passes(scenario: str, subs: dict[str, str]) -> list[HttpRecording]:
    raw = json.loads((FIXTURES / f"{scenario}.json").read_text(encoding="utf-8"))
    escaped = {name: json.dumps(value)[1:-1] for name, value in subs.items()}
    passes: list[HttpRecording] = []
    for one in raw["passes"]:
        one = _expand(one, escaped)
        stream: list[Any] = []
        for item in one["stream"]:
            stream.extend(_provider_chunks(item))
        passes.append(HttpRecording(request_body=one["request_body"], stream=tuple(stream)))
    return passes


class ScenarioTransport(httpx.AsyncBaseTransport):
    """Serves one recorded pass per model invocation, in order, from the armed scenario."""

    def __init__(self) -> None:
        self._transports: list[httpx.MockTransport] = []
        self.requests: list[httpx.Request] = []
        self.bodies: list[dict[str, Any]] = []

    def arm(self, scenario: str, subs: dict[str, str]) -> None:
        self._transports = [replay_transport(p) for p in load_passes(scenario, subs)]
        self.requests = []
        self.bodies = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        index = len(self.requests)
        self.requests.append(request)
        self.bodies.append(json.loads(request.content))
        if index >= len(self._transports):
            return httpx.Response(500, content=b"no recorded pass left for this model call")
        return await self._transports[index].handle_async_request(request)


def build_real_adapter(transport: ScenarioTransport) -> ApprovedEndpointAdapter:
    """Gating decides: no stub. The Commercial matrix row (item 8) must enable the adapter."""
    config = AdapterConfig(
        kind="approved_endpoint",
        endpoint=ENDPOINT,
        deployment="gpt-41-mini",
        model_feature=MODEL_FEATURE,
        sku=SKU,
        api_version="2024-10-21",
    )
    entries = resolve_adapters(cloud="commercial", region="centralus", configs=[config])
    entry = next(e for e in entries if e.kind == "approved_endpoint")
    assert entry.enabled, (entry.reason_code, entry.reason)
    adapter = create_adapter(
        entry, cloud="commercial", credential=_StaticCredential(), transport=transport
    )
    assert isinstance(adapter, ApprovedEndpointAdapter)
    return adapter


# -- identities and seeded data ------------------------------------------------------------


def _principal(oid: str) -> str:
    return PrincipalPseudonymizer(local_dev_pseudonym_key()).principal_id(
        cloud=CloudName.COMMERCIAL,
        customer_id=CUSTOMER,
        tenant_id=real_stack_tenant(),
        object_id=oid,
        kind="user",
    )


@dataclass(frozen=True)
class World:
    run: str
    domain_a: str
    domain_b: str
    domain_z: str
    agent_a1: str
    agent_a2: str
    agent_b1: str
    rec_id: str
    eval_a: str
    eval_b: str

    @classmethod
    def new(cls) -> World:
        run = uuid.uuid4().hex[:8]
        domain = f"commercial:{CUSTOMER}:catalog:domain:loop-%s-{run}"
        agent = f"commercial:{CUSTOMER}:foundry:agent:loop-%s-{run}"
        return cls(
            run=run,
            domain_a=domain % "a",
            domain_b=domain % "b",
            domain_z=domain % "z",
            agent_a1=agent % "a1",
            agent_a2=agent % "a2",
            agent_b1=agent % "b1",
            rec_id=f"commercial:{CUSTOMER}:neurosphere:recommendation:loop-{run}",
            eval_a=f"eval:loop-a-{run}",
            eval_b=f"eval:loop-b-{run}",
        )

    @property
    def subs(self) -> dict[str, str]:
        return {
            "DA": self.domain_a,
            "DB": self.domain_b,
            "A1": self.agent_a1,
            "A2": self.agent_a2,
            "B1": self.agent_b1,
            "REC": self.rec_id,
            "EVAL_A": self.eval_a,
            "EVAL_B": self.eval_b,
        }

    @property
    def audit_chain(self) -> str:
        return f"{CUSTOMER}.{self.domain_a.rsplit(':', 1)[-1]}"


def _policy(world: World) -> InMemoryPolicyRepository:
    repo = InMemoryPolicyRepository()
    repo.put_head(PolicyHead(customer_id=CUSTOMER, policy_version="v1"))
    grants: dict[str, list[tuple[Role, tuple[str, ...]]]] = {
        USER_A: [
            (Role.ANALYST, (world.domain_a, world.domain_b)),
            (Role.SECURITY_AUDITOR, (world.domain_a,)),
        ],
        USER_B: [(Role.VIEWER, (world.domain_a,))],
        USER_C: [(Role.VIEWER, (world.domain_z,))],
    }
    for oid, roles in grants.items():
        principal = _principal(oid)
        domains = tuple(dict.fromkeys(d for _, ds in roles for d in ds))
        repo.put_principal(
            PrincipalPolicy(
                id=principal_document_id(principal),
                customer_id=CUSTOMER,
                principal_id=principal,
                domain_memberships=domains,
                role_assignments=tuple(
                    PolicyRoleAssignment(
                        assignment_id=f"ra-{oid[:4]}-{n}",
                        role=role,
                        domain_ids=ds,
                        # Privileged roles (the auditor) are time-bound by policy (C7).
                        expires_at=datetime.now(UTC) + timedelta(hours=2),
                        reason="copilot loop test",
                    )
                    for n, (role, ds) in enumerate(roles)
                ),
            )
        )
    return repo


def _seed_scope(world: World) -> IdentityScope:
    contract = ContractScope.model_validate(
        {
            "schema_version": "1.0.0",
            "cloud": "commercial",
            "customer_id": CUSTOMER,
            "principal": {
                "principal_id": f"commercial:{CUSTOMER}:entra:person:psn_0123456789abcdef",
                "principal_pseudonym": "p-7f3a9c21",
                "principal_kind": "user",
            },
            "roles": [],
            "allowed_domains": [world.domain_a, world.domain_b],
            "allowed_resources": [],
            "policy_version": "v1",
            "derived_at": "2026-11-11T00:00:00Z",
            "scope_hash": "sha256:" + "0" * 64,
        }
    )
    return IdentityScope._from_verified_contract(contract)  # pyright: ignore[reportPrivateUsage]


def _example(rel: str) -> dict[str, Any]:
    return json.loads((SCHEMAS / rel).read_text(encoding="utf-8"))


def _agent(entity_id: str, domain: str, name: str) -> Any:
    raw = _example("catalog/v1/examples/valid/agent.minimal-and-typical.json")
    raw.update(
        id=entity_id,
        customer_id=CUSTOMER,
        domain_id=domain,
        current_version_id=None,
        external_agent_id=None,
        display_name=name,
        attributes=None,
    )
    return parse_entity(raw)


def _recommendation(world: World) -> Recommendation:
    raw = _example("recommendations/v1/examples/valid/recommendation.cost-spike-scored.json")
    raw.update(
        recommendation_id=world.rec_id,
        domain_id=world.domain_a,
        customer_id=CUSTOMER,
        cloud="commercial",
    )
    return Recommendation.model_validate(raw)


def _evaluation(evaluation_id: str, domain: str) -> EvaluationResult:
    raw = _example("evaluation/v1/examples/valid/evaluation-result.offline-llm-judge.json")
    raw.update(evaluation_id=evaluation_id, domain_id=domain, customer_id=CUSTOMER)
    return EvaluationResult.model_validate(raw)


# -- HTTP helpers -----------------------------------------------------------------------------


@dataclass
class Sse:
    status: int
    events: list[tuple[str, dict[str, Any]]]
    seconds: float

    @property
    def names(self) -> list[str]:
        return [name for name, _ in self.events]

    def of(self, name: str) -> list[dict[str, Any]]:
        return [data for n, data in self.events if n == name]

    @property
    def terminal(self) -> str:
        return self.names[-1] if self.events else "none"


def parse_sse(text: str) -> list[tuple[str, dict[str, Any]]]:
    events: list[tuple[str, dict[str, Any]]] = []
    for block in text.split("\n\n"):
        name, data = "", ""
        for line in block.splitlines():
            if line.startswith("event:"):
                name = line[6:].strip()
            elif line.startswith("data:"):
                data = line[5:].strip()
        if name:
            events.append((name, json.loads(data) if data else {}))
    return events


@dataclass
class Report:
    """What the evidence file records."""

    steps: list[tuple[str, str]] = field(default_factory=list[tuple[str, str]])
    turns: list[tuple[str, Sse]] = field(default_factory=list[tuple[str, Sse]])
    facts: dict[str, Any] = field(default_factory=dict[str, Any])
    gaps: list[str] = field(default_factory=list[str])

    def step(self, name: str, outcome: str) -> None:
        self.steps.append((name, outcome))
        print(f"STEP {name}: {outcome}")


async def ask(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    transport: ScenarioTransport,
    scenario: str,
    world: World,
    text: str,
    extra: dict[str, str] | None = None,
) -> Sse:
    transport.arm(scenario, {**world.subs, **(extra or {})})
    created = await client.post(f"{COPILOT}/conversations", headers=headers)
    assert created.status_code == 201, created.text
    started = time.monotonic()
    response = await client.post(
        f"{COPILOT}/conversations/{created.json()['id']}/messages",
        headers=headers,
        json={"text": text},
    )
    seconds = time.monotonic() - started
    assert response.status_code == 200, (response.status_code, response.text)
    return Sse(response.status_code, parse_sse(response.text), seconds)


def _before(names: list[str], first: str, second: str) -> bool:
    return first in names and second in names and names.index(first) < names.index(second)


# -- fixtures ------------------------------------------------------------


@pytest.fixture
def loopback_cosmos(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Listed before ``emulator_env`` so it keeps this 127.0.0.1 endpoint."""
    monkeypatch.setenv("NS_COSMOS_ENDPOINT", LOOPBACK)
    yield


@pytest.fixture
def throwaway_database(
    monkeypatch: pytest.MonkeyPatch, loopback_cosmos: None, emulator_env: None
) -> Iterator[str]:
    database = f"ns_copilot_{uuid.uuid4().hex[:10]}"
    monkeypatch.setenv("NS_STORE_DATABASE", database)
    monkeypatch.delenv("NS_COPILOT_MODE", raising=False)  # the adapter is handed in explicitly
    yield database


async def _drop_database(database: str) -> None:
    async with ClientLifetime() as lifetime:
        client = create_cosmos_client(Settings(env="local"), lifetime=lifetime)
        try:
            await client.delete_database(database)
        except Exception:
            pass  # best effort: a throwaway database on the emulator


@pytest.fixture
async def copilot_app(
    throwaway_database: str, stand_in_validator: JwtValidator
) -> AsyncIterator[tuple[FastAPI, World, ScenarioTransport, Any]]:
    world = World.new()
    transport = ScenarioTransport()
    settings = Settings()
    app = create_app(settings)
    registry = compose_app(
        app,
        settings,
        CompositionOverrides(
            authenticator=stand_in_validator,
            policy_repository=_policy(world),
            model_adapter=build_real_adapter(transport),
        ),
    )
    try:
        async with app.router.lifespan_context(app):
            yield app, world, transport, registry
    finally:
        await _drop_database(throwaway_database)


# -- the loop ------------------------------------------------------------


async def test_copilot_to_report_loop_on_the_emulators(
    copilot_app: tuple[FastAPI, World, ScenarioTransport, Any],
    stand_in_token: Any,
) -> None:
    app, world, transport, registry = copilot_app
    report = Report()
    started = time.monotonic()
    for name in ("catalog", "aggregates", "recommendations", "audit", "action_plane", "reports"):
        assert registry.get(name).state == "ok", (name, registry.get(name))
    assert registry.get("copilot").state == "ok", registry.get("copilot")

    # Seed through the stores the composed app itself uses (real Cosmos containers).
    seed_scope = _seed_scope(world)
    catalog = app.state.catalog_repository
    for entity_id, domain, name in (
        (world.agent_a1, world.domain_a, "Agent A1"),
        (world.agent_a2, world.domain_a, "Agent A2"),
        (world.agent_b1, world.domain_b, "Agent B1"),
    ):
        await catalog.create_entity(seed_scope, _agent(entity_id, domain, name))
    recommendation = _recommendation(world)
    await app.state.recommendation_store.put(recommendation)
    eval_a = _evaluation(world.eval_a, world.domain_a)
    eval_b = _evaluation(world.eval_b, world.domain_b)
    await app.state.evaluation_store.put_result(eval_a)
    await app.state.evaluation_store.put_result(eval_b)
    stored_a1 = await catalog.get_entity(seed_scope, world.agent_a1)
    stored_rec = await app.state.recommendation_store.get(seed_scope, world.domain_a, world.rec_id)
    assert stored_a1 is not None and stored_rec is not None
    report.facts["seeded"] = (
        "3 agents (2 in domain A, 1 in domain B), 1 recommendation in domain A, "
        "1 evaluation result each in A and B"
    )

    a, b, c, d = (stand_in_token(oid) for oid in (USER_A, USER_B, USER_C, USER_D))
    principal_b = _principal(USER_B)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://api.invalid"
    ) as client:
        # 1. status
        status = await client.get(f"{COPILOT}/status", headers=a)
        assert status.status_code == 200 and status.json()["state"] == "ready", status.text
        report.step("1 copilot status", f"ready ({status.json()})")

        # 2. a data question: query tool -> records -> chart; citations carry Cosmos freshness
        chart_turn = await ask(client, a, transport, "chart", world, "Chart the agents I can see.")
        report.turns.append(("2 data question + chart", chart_turn))
        names = chart_turn.names
        assert names[0] == "context" and chart_turn.terminal == "done", names
        assert any(
            n == "tool" and d_["status"] == "ok" and d_["name"] == "search_catalog"
            for n, d_ in chart_turn.events
        ), names
        first_ok = next(
            i for i, (n, d_) in enumerate(chart_turn.events) if n == "tool" and d_["status"] == "ok"
        )
        first_citation = names.index("citation")
        first_chart = names.index("chart")
        assert first_ok < first_citation < first_chart < names.index("done"), names
        citations = chart_turn.of("citation")
        assert {cit["record_id"] for cit in citations} == {
            world.agent_a1,
            world.agent_a2,
            world.agent_b1,
        }, citations
        for cit in citations:
            assert cit["freshness"] != "unknown", cit
            record = await catalog.get_entity(seed_scope, cit["record_id"])
            assert record is not None
            assert cit["as_of"] == record.updated_at.root, (cit, record.updated_at.root)
        chart = chart_turn.of("chart")[0]
        query_spec = chart.get("query_spec")
        assert isinstance(query_spec, dict), chart
        assert query_spec["entity"] == "agent" and query_spec["operation"] == "list", query_spec
        assert "query_spec" not in chart["chart_plan"]
        assert len(transport.requests) == 3, len(transport.requests)
        tool_names = {t["function"]["name"] for t in transport.bodies[0]["tools"]}
        assert {"search_catalog", "render_chart", "propose_action"} <= tool_names
        assert any(m["role"] == "tool" for m in transport.bodies[1]["messages"])
        assert str(transport.requests[0].url).startswith(ENDPOINT + "/openai/deployments/")
        report.step(
            "2 data question + chart",
            f"{len(citations)} citations "
            f"(freshness {sorted({x['freshness'] for x in citations})}), "
            "as_of == Cosmos updated_at, chart.query_spec present, 3 model calls",
        )

        # 3. an evidence question resolves through the item 9 reader
        evidence_turn = await ask(
            client, a, transport, "evidence", world, "What backs the cost recommendation?"
        )
        report.turns.append(("3 evidence question", evidence_turn))
        assert evidence_turn.terminal == "done", evidence_turn.events
        ev_citations = evidence_turn.of("citation")
        by_record = {cit["record_id"]: cit for cit in ev_citations}
        assert set(by_record) == {world.rec_id, world.eval_a}, ev_citations
        assert world.eval_b not in json.dumps(evidence_turn.events), evidence_turn.events
        rec_cit, eval_cit = by_record[world.rec_id], by_record[world.eval_a]
        assert rec_cit["kind"] == "evidence" and rec_cit["freshness"] != "unknown"
        assert rec_cit["as_of"] == stored_rec.created_at.root, ev_citations
        assert eval_cit["as_of"] == eval_a.completed_at.root, eval_cit
        assert eval_cit["freshness"] != "unknown", eval_cit
        report.step(
            "3 evidence question",
            f"recommendation and evaluation result cited via get_evidence, as_of == Cosmos "
            f"created_at / completed_at ({eval_cit['as_of']}); the domain B eval id was "
            "requested and NOT cited",
        )

        # 4. an action suggestion drafts an intent; it is neither confirmed nor executed
        action_turn = await ask(
            client,
            a,
            transport,
            "action",
            world,
            "Swap the model of Agent A1 for a cheaper one.",
            extra={"ETAG": str(stored_a1.etag)},
        )
        report.turns.append(("4 action suggestion", action_turn))
        assert action_turn.terminal == "done", action_turn.events
        suggestions = action_turn.of("action_suggestion")
        assert len(suggestions) == 1 and suggestions[0]["intent_id"], suggestions
        intent_id = suggestions[0]["intent_id"]
        fetched = await client.get(
            f"{ACTIONS}/{suggestions[0]['domain_id']}/intents/{intent_id}", headers=a
        )
        assert fetched.status_code == 200, fetched.text
        view = fetched.json()
        state = view.get("state") or view.get("intent", {}).get("state")
        assert state == "drafted", view
        assert not view.get("execution"), view
        report.step("4 action suggestion", f"intent {intent_id[:8]}.. fetched, state={state}")

        # 5. save the chart as a report with the received chart_plan + query_spec
        created = await client.post(
            f"{REPORTS}/{world.domain_a}/reports",
            headers=a,
            json={
                "title": "Agents from chat",
                "chart_plan": chart["chart_plan"],
                "query_spec": query_spec,
            },
        )
        assert created.status_code == 201, created.text
        report_id = created.json()["id"]
        etag = created.headers["etag"]
        owner_run = await client.post(
            f"{REPORTS}/{world.domain_a}/reports/{report_id}/run", headers=a
        )
        assert owner_run.status_code == 200, owner_run.text
        owner_rows = {
            r["record_id"] for r in owner_run.json()["chart_plan"]["spec"]["data"]["values"]
        }
        assert owner_rows == {world.agent_a1, world.agent_a2, world.agent_b1}, owner_rows
        report.step("5 save as report", f"report {report_id[:8]}.. created; owner run rows=3")

        # 6. share with B (domain A only); B's run is filtered to B's scope
        shared = await client.post(
            f"{REPORTS}/{world.domain_a}/reports/{report_id}/shares",
            headers={**a, "If-Match": etag},
            json={"principal_id": principal_b},
        )
        assert shared.status_code == 200, shared.text
        etag = shared.headers["etag"]
        b_run = await client.post(f"{REPORTS}/{world.domain_a}/reports/{report_id}/run", headers=b)
        assert b_run.status_code == 200, b_run.text
        b_rows = {r["record_id"] for r in b_run.json()["chart_plan"]["spec"]["data"]["values"]}
        assert b_rows == {world.agent_a1, world.agent_a2}, b_rows
        assert world.agent_b1 not in json.dumps(b_run.json())
        report.step("6 share + viewer run", "B sees 2 of 3 rows; domain B row filtered out")

        # 7. revoke: unshare with If-Match; B's next run is denied
        unshared = await client.delete(
            f"{REPORTS}/{world.domain_a}/reports/{report_id}/shares/{principal_b}",
            headers={**a, "If-Match": etag},
        )
        assert unshared.status_code == 200, unshared.text
        denied_run = await client.post(
            f"{REPORTS}/{world.domain_a}/reports/{report_id}/run", headers=b
        )
        assert denied_run.status_code in (403, 404), denied_run.text
        assert world.agent_a1 not in denied_run.text
        report.step("7 revoke", f"B's run after unshare -> HTTP {denied_run.status_code}")

        # 8. callers with no access get no data
        probe = await ask(client, c, transport, "probe", world, "Show me the other domain.")
        report.turns.append(("8a out-of-scope domain request (C)", probe))
        assert probe.terminal == "denied", probe.events
        assert probe.of("denied")[0]["reason_code"] == "domain_out_of_scope", probe.events
        empty = await ask(client, c, transport, "empty", world, "List the agents.")
        report.turns.append(("8b empty readable scope (C)", empty))
        assert empty.terminal == "abstain", empty.events
        assert empty.of("abstain")[0]["reason_code"] == "no_authorized_evidence", empty.events
        for turn in (probe, empty):
            assert not turn.of("citation") and not turn.of("chart") and not turn.of("token")
            assert world.agent_a1 not in json.dumps(turn.events)
        no_policy = await client.post(f"{COPILOT}/conversations", headers=d)
        assert no_policy.status_code in (401, 403), no_policy.text
        report.step(
            "8 no-access callers",
            "C: denied (domain_out_of_scope) and abstain (no_authorized_evidence), no data; "
            f"D without any grant: HTTP {no_policy.status_code} before any turn",
        )

        # 9. audit rows exist in the Cosmos audit store for report run, share and unshare
        records = await app.state.audit_repository.read_range(world.audit_chain, limit=100)
        seen = {(r.operation, r.kind) for r in records}
        for key in (
            ("report.run", "after"),
            ("report.run", "denied"),
            ("report.share", "before"),
            ("report.share", "after"),
            ("report.unshare", "before"),
            ("report.unshare", "after"),
        ):
            assert key in seen, (key, sorted(seen))
        report.facts["audit_records"] = len(records)
        report.facts["audit_seen"] = sorted(f"{op}/{kind}" for op, kind in seen)
        report.step("9 audit", f"{len(records)} records on chain {world.audit_chain}")

    report.facts["total_seconds"] = time.monotonic() - started
    path = _write_evidence(report)
    print(f"EVIDENCE: {path}")


def _write_evidence(report: Report) -> Path:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y-%m-%d")
    path = EVIDENCE_DIR / f"real-stack-loop-{stamp}.md"
    steps = "\n".join(f"| {name} | {outcome} |" for name, outcome in report.steps)
    turns = "\n".join(
        f"| {name} | {turn.seconds * 1000:.0f} ms | `{' > '.join(_compact(turn.names))}` |"
        for name, turn in report.turns
    )
    gaps = "\n".join(f"- {note}" for note in report.gaps) or "- none observed in this run"
    facts = report.facts
    body = f"""# Copilot and report loop on the compose emulators ({stamp})

Scope: **emulator, bounded feasibility, not a live claim.** The composed API runs in-process
against the compose Cosmos emulator (127.0.0.1:8081, throwaway database) with the REAL authz, data,
planes, action-plane, reports and copilot builders. The model is the real `ApprovedEndpointAdapter`
built through `resolve_adapters` / `create_adapter` for Commercial, centralus, `{MODEL_FEATURE}`,
`{SKU}` (gating enabled it from the capability matrix; nothing stubbed). Its HTTP transport replays
hand-authored provider-format streams (`tests/integration/real_stack/fixtures/copilot_loop/`); the
credential is a static fake. Test: `tests/integration/real_stack/test_copilot_loop.py`
(`pytest.mark.integration`, never runs in CI).

## Steps

| Step | Outcome |
|---|---|
{steps}

## Turns (SSE event names in order, wall time of the streamed response)

| Turn | Time | Events |
|---|---|---|
{turns}

## Counts

- Seeded: {facts["seeded"]}.
- Audit records read from the Cosmos audit chain: {facts["audit_records"]} ({", ".join(facts["audit_seen"])}).
- Whole loop: {facts["total_seconds"]:.1f} s (seeding and all nine steps; app startup excluded).

## Gaps found

{gaps}

## NOT exercised

- A live model: the G05/G17 live gate stays OPEN (`NS_LIVE_APPROVED=1` not set; no paid calls).
  Recorded streams prove the adapter, engine, tools and API plumbing, not model quality.
- The Playwright UI (chat panel, report page).
- Azure Government: this is a Commercial row only.
- Real Entra tokens (a stand-in issuer signs them) and real RBAC on a hosted endpoint.
- Emulator limits (G12): no auth, no RU accounting, so latency and throttling are not representative.
"""  # noqa: E501
    path.write_text(body, encoding="utf-8")
    return path


def _compact(names: list[str]) -> list[str]:
    """Collapse runs of the same event name (``token`` x N) for the evidence table."""
    out: list[str] = []
    for name in names:
        if out and out[-1].split(" x")[0] == name:
            head, _, count = out[-1].partition(" x")
            out[-1] = f"{head} x{int(count or 1) + 1}"
        else:
            out.append(name)
    return out
