"""PRP-29 item 10: ``sbx_seed_stack.py`` against in-memory stores and a fake hub (no network).

Every category is written through a core service or store API; a second run creates nothing and
reports the existing items; no intent can reach ``executing``; non-loopback endpoints are refused;
stdout is exactly the JSON summary.
"""

from __future__ import annotations

import ast
import asyncio
import importlib.util
import json
import sys
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import pytest
from neurosphere_api.reports.store import InMemoryReportStore
from neurosphere_core.actions import InMemoryExecutionControl, InMemoryIntentStore
from neurosphere_core.audit import AuditRepository
from neurosphere_core.audit.store import InMemoryAuditStore
from neurosphere_core.auth.scope import (
    InMemoryPolicyRepository,
    NoRevocationCheck,
    PolicyHead,
    PrincipalPolicy,
)
from neurosphere_core.catalog.repo.memory import InMemoryCatalogRepository
from neurosphere_core.cloud import CloudName
from neurosphere_core.evaluation.store import InMemoryEvaluationStore
from neurosphere_core.hitl.decisions import InMemoryDecisionStore
from neurosphere_core.hitl.store import InMemoryHitlStore
from neurosphere_core.mcp.store import InMemoryMcpServerStore
from neurosphere_core.pricing import InMemoryPriceSnapshotStore
from neurosphere_core.recommendations import InMemoryRecommendationStore
from neurosphere_workers.runtime.identity import resolve_pseudonym_key
from neurosphere_workers.runtime.settings import AuthSettings

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "sandbox" / "sbx_seed_stack.py"
TENANT = "0f1e2d3c-4b5a-4968-8776-a5b4c3d2e1f0"
WORKER_OID = "6c1d2e3f-4a5b-4c6d-8e7f-90a1b2c3d4e5"
OPERATOR_OID = "55555555-5555-4555-8555-555555555555"
FAKE_LANDED = {"ledger": 40, "aggregates": 12, "catalog": 30, "archives": 6}


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("sbx_seed_stack_under_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolve string annotations through it
    spec.loader.exec_module(module)
    return module


seed = _load()


class MemoryWriter:
    """The ``PolicyWriter`` protocol over the in-memory repository."""

    def __init__(self, repo: InMemoryPolicyRepository) -> None:
        self._repo = repo

    async def upsert(self, document: dict[str, Any]) -> None:
        if "policy_version" in document:
            self._repo.put_head(PolicyHead.model_validate(document))
        else:
            self._repo.put_principal(PrincipalPolicy.model_validate(document))


class FakeHub:
    """Event Hubs stand-in: counts what is published and 'lands' it (workers are simulated)."""

    def __init__(self, landing: FakeLanding) -> None:
        self.landing = landing
        self.published: list[bytes] = []

    def publish(self, lines: Iterator[bytes], rate: float = 0.0, chunk: int = 100) -> int:
        batch = list(lines)
        self.published.extend(batch)
        messages = [json.loads(line) for line in batch]
        recorded = [
            seed._timestamp(m["data"]["recorded_at"])  # pyright: ignore[reportPrivateUsage]
            for m in messages
            if m["kind"] == "cost"
        ]
        self.landing.earliest = min(recorded)
        self.landing.watermark = max(recorded)
        self.landing.land()
        return len(batch)


class FakeLanding:
    def __init__(self, *, lands: bool = True) -> None:
        self._lands = lands
        self.state = dict.fromkeys(FAKE_LANDED, 0)
        self.reads = 0
        self.earliest: datetime | None = None
        self.watermark: datetime | None = None

    async def ledger_earliest(self) -> datetime | None:
        return self.earliest

    async def aggregate_watermark(self) -> datetime | None:
        return self.watermark

    def land(self) -> None:
        if self._lands:
            self.state = dict(FAKE_LANDED)

    async def counts(self) -> dict[str, int]:
        self.reads += 1
        return dict(self.state)


class Stack:
    def __init__(self, *, lands: bool = True) -> None:
        self.landing = FakeLanding(lands=lands)
        self.hub = FakeHub(self.landing)
        self.policy = InMemoryPolicyRepository()
        self.prices = InMemoryPriceSnapshotStore()
        self.recommendations = InMemoryRecommendationStore()
        self.hitl_store = InMemoryHitlStore()
        self.evaluations = InMemoryEvaluationStore()
        self.intents = InMemoryIntentStore()
        self.mcp = InMemoryMcpServerStore()
        audit = AuditRepository(InMemoryAuditStore())
        key = resolve_pseudonym_key(AuthSettings(), env="local")
        self.reports = InMemoryReportStore()
        self.catalog = InMemoryCatalogRepository()
        self.backends = seed.Backends(
            hub=self.hub,
            landing=self.landing,
            policy=self.policy,
            policy_writer=MemoryWriter(self.policy),
            revocation=NoRevocationCheck(),
            key=key,
            catalog=self.catalog,
            prices=self.prices,
            recommendations=self.recommendations,
            hitl=seed.make_hitl(self.hitl_store, InMemoryDecisionStore(), audit),
            evaluations=self.evaluations,
            actions=seed.make_action_service(
                cloud=CloudName.COMMERCIAL,
                policy=self.policy,
                revocation=NoRevocationCheck(),
                audit=audit,
                intents=self.intents,
                control=InMemoryExecutionControl(),
            ),
            reports=self.reports,
            mcp=self.mcp,
        )


def _config(**overrides: Any) -> Any:
    fields: dict[str, Any] = {
        "profile": "small",
        "cosmos_endpoint": "http://127.0.0.1:8081",
        "cosmos_key": "unused",
        "eventhubs_connection": "unused",
        "blob_connection": "UseDevelopmentStorage=true;",
        "database": "neurosphere_unit",
        "customer": "synthco",
        "tenant_id": TENANT,
        "worker_object_id": WORKER_OID,
        "operator_object_id": OPERATOR_OID,
        "hub_name": "telemetry",
        "archive_container": "ns-archive",
        "wait_seconds": 30.0,
        "poll_seconds": 1.0,
    }
    fields.update(overrides)
    return seed.SeedConfig(**fields)


async def _no_sleep(_seconds: float) -> None:
    return None


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.now += seconds


RUN_TIME = datetime(2026, 10, 25, 14, 0, 0, tzinfo=UTC)


def _run(
    stack: Stack, tmp_path: Path, config: Any = None, at: datetime = RUN_TIME
) -> dict[str, Any]:
    clock = _Clock()
    return asyncio.run(
        seed.run_seed(
            config or _config(),
            stack.backends,
            tmp_path,
            environ={},
            sleep=clock.sleep,
            clock=clock,
            now=lambda: at,
        )
    )


@pytest.fixture(autouse=True)
def _local_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NS_ENV", "local")
    for name in ("NS_CLOUD", "NS_AUTH_PSEUDONYM_KEY", "NS_AUTH_PSEUDONYM_KEY_REFERENCE"):
        monkeypatch.delenv(name, raising=False)


# -- every category, through the real APIs -------------------------------------------------


def test_every_category_is_written_through_a_service_or_store(tmp_path: Path) -> None:
    stack = Stack()
    summary = _run(stack, tmp_path)

    assert set(summary) == {"seeded", "skipped_existing"}
    assert set(summary["seeded"]) == set(seed.CATEGORIES)
    assert all(count > 0 for count in summary["seeded"].values()), summary
    assert stack.hub.published, "telemetry and cost were pushed through the hub seam"
    assert summary["seeded"]["ledger"] == FAKE_LANDED["ledger"]

    # prices: the store holds the synthetic sheet
    assert [s.snapshot_id for s in stack.prices.list_snapshots()] == ["sandbox-prices-2026-10"]
    # grants: worker + 5 personas + operator, all in the policy store
    assert summary["seeded"]["grants"] == 7
    # intents / reports / mcp servers are readable back from their stores
    assert summary["seeded"]["intents"] == len(seed._fixture("intents.json")["intents"])
    assert stack.intents.create_calls == summary["seeded"]["intents"]
    servers = asyncio.run(stack.mcp.list())
    assert len(servers) == summary["seeded"]["mcp_servers"]
    assert all(s.host.endswith(".invalid") for s in servers)


def test_hub_messages_are_ingestion_envelopes(tmp_path: Path) -> None:
    stack = Stack()
    _run(stack, tmp_path)
    kinds = {json.loads(line)["kind"] for line in stack.hub.published[:5]}
    assert kinds <= {"telemetry", "cost"}
    assert {json.loads(line)["kind"] for line in stack.hub.published} == {"telemetry", "cost"}


def test_no_intent_reaches_executing(tmp_path: Path) -> None:
    stack = Stack()
    _run(stack, tmp_path)
    stored = asyncio.run(stack.intents.list_in_states(list(_all_states()), limit=100))
    assert stored, "intents were drafted"
    states = {s.state for s in stored}
    assert states <= set(seed.SAFE_INTENT_STATES)
    assert {"drafted", "validated", "awaiting_confirmation"} <= states
    assert all(s.execution is None for s in stored)
    assert all(s.state != "executing" for s in stored)


def _all_states() -> tuple[str, ...]:
    from neurosphere_core.actions.state_machine import ACTION_STATES

    return ACTION_STATES


def test_seeding_refuses_to_go_past_awaiting_confirmation(tmp_path: Path) -> None:
    stack = Stack()
    with pytest.raises(seed.SeedError):
        asyncio.run(
            seed._advance(
                stack.backends,
                seed.IntentKey("c", "d", "i"),
                seed._caller("commercial:synthco:entra:person:p-x", "corr"),
                "awaiting_confirmation",
                "executing",
            )
        )


# -- idempotency ---------------------------------------------------------------------------


def test_second_run_creates_nothing_and_reports_skipped_existing(tmp_path: Path) -> None:
    stack = Stack()
    first = _run(stack, tmp_path / "one")
    after_first = _snapshot(stack)

    second = _run(stack, tmp_path / "two")

    assert all(count == 0 for count in second["seeded"].values()), second
    assert second["skipped_existing"] > 0
    assert second["skipped_existing"] >= sum(first["seeded"].values())
    assert _snapshot(stack) == after_first, "a re-run must not add or change documents"
    assert stack.landing.state == FAKE_LANDED


def _published_times(stack: Stack) -> list[datetime]:
    times: list[datetime] = []
    for line in stack.hub.published:
        data = json.loads(line)["data"]
        stamp = data.get("event_time") or data["recorded_at"]
        times.append(seed._timestamp(stamp))  # pyright: ignore[reportPrivateUsage]
    return times


def test_the_world_is_rebased_to_the_run_time(tmp_path: Path) -> None:
    """The newest event is minutes old and everything is inside the 7-day archive look-back."""
    stack = Stack()
    _run(stack, tmp_path)
    times = _published_times(stack)
    assert RUN_TIME - max(times) <= timedelta(hours=2), "newest event within the last two hours"
    assert max(times) <= RUN_TIME, "nothing is dated in the future"
    assert RUN_TIME - min(times) <= timedelta(days=7)
    day_ago = RUN_TIME - timedelta(days=1)
    assert any(t >= day_ago for t in times), "the 1-day cost window has data"


def test_rerun_on_a_later_day_is_identical_and_creates_nothing(tmp_path: Path) -> None:
    """A re-run recovers the first run's shift from the ledger: the same ids and windows, nothing
    published or created, and the data is NOT re-aged (it is just older)."""
    stack = Stack()
    _run(stack, tmp_path / "one")
    first_times = _published_times(stack)
    before = _snapshot(stack)
    recommendation_ids = sorted(stack.recommendations._items)  # pyright: ignore[reportPrivateUsage]

    later = RUN_TIME + timedelta(days=3, hours=5)
    second = _run(stack, tmp_path / "two", at=later)

    assert all(count == 0 for count in second["seeded"].values()), second
    assert _snapshot(stack) == before
    assert sorted(stack.recommendations._items) == recommendation_ids  # pyright: ignore[reportPrivateUsage]
    assert _published_times(stack) == first_times, "nothing was re-published or re-aged"


def test_entities_are_written_through_the_catalog_repository(tmp_path: Path) -> None:
    stack = Stack()
    summary = _run(stack, tmp_path)
    assert summary["seeded"]["entities"] > 0
    scope = asyncio.run(seed.worker_scope(stack.backends, _config()))
    from neurosphere_core.catalog import EntityFilter
    from neurosphere_core.paging.models import PageRequest

    kinds: set[str] = set()
    cursor: str | None = None
    while True:
        page = asyncio.run(
            stack.catalog.list_entities(
                scope, EntityFilter(), PageRequest(page_size=100, cursor=cursor)
            )
        )
        kinds |= {item.entity_type for item in page.items}
        cursor = page.next_cursor
        if cursor is None:
            break
    assert {"agent", "grounding_source", "model_deployment", "person"} <= kinds


def test_operator_gets_a_report_they_own_and_others_are_not_widened(tmp_path: Path) -> None:
    stack = Stack()
    _run(stack, tmp_path)
    operator = seed.user_principal_id(_config(), OPERATOR_OID, {})
    rows = list(stack.reports._rows.values())  # pyright: ignore[reportPrivateUsage]
    mine = [r for r in rows if r.owner == operator]
    assert mine and all(not r.shares for r in mine), "owned, not shared or published wider"
    assert {r.owner for r in rows} - {operator}, "the analyst persona's reports are unchanged"

    anonymous = Stack()
    _run(anonymous, tmp_path / "none", _config(operator_object_id=None))
    assert not [
        r
        for r in anonymous.reports._rows.values()  # pyright: ignore[reportPrivateUsage]
        if r.owner == operator
    ]


def test_watermark_wait_is_bounded_and_reports_whether_it_caught_up() -> None:
    target = RUN_TIME
    landing = FakeLanding()
    clock = _Clock()
    landing.watermark = target - timedelta(hours=2)
    assert not asyncio.run(
        seed.wait_for_watermark(
            landing, target, overall_seconds=20.0, poll=5.0, sleep=clock.sleep, clock=clock
        )
    )
    assert clock.now <= 20.0, "bounded by the one overall timeout"
    landing.watermark = target
    assert asyncio.run(
        seed.wait_for_watermark(
            landing, target, overall_seconds=20.0, poll=5.0, sleep=clock.sleep, clock=clock
        )
    )


def test_a_lagging_aggregates_role_warns_but_does_not_fail(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stack = Stack()
    stack.landing.watermark = None  # never advances
    original = stack.hub.publish

    def publish_without_watermark(
        lines: Iterator[bytes], rate: float = 0.0, chunk: int = 100
    ) -> int:
        sent = original(lines, rate, chunk)
        stack.landing.watermark = datetime(2026, 1, 1, tzinfo=UTC)
        return sent

    stack.hub.publish = publish_without_watermark  # type: ignore[method-assign]
    summary = _run(stack, tmp_path)
    assert summary["seeded"]["ledger"] > 0
    assert "has not caught up" in capsys.readouterr().err


def test_rebase_seconds_matches_ledger_on_rerun() -> None:
    now = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)
    earliest = datetime(2026, 10, 1, 0, 0, 5, tzinfo=UTC)
    newest = datetime(2026, 10, 4, 23, 0, tzinfo=UTC)
    fresh = seed.rebase_seconds(now=now, earliest=earliest, newest=newest, existing_earliest=None)
    age = now - (newest + timedelta(seconds=fresh))
    assert seed.NEWEST_AGE <= age < seed.NEWEST_AGE + timedelta(hours=1)
    assert fresh % 3600 == 0, "a whole number of hours"
    # the ledger's earliest entry differs from the generated earliest by a few seconds
    ledger = earliest + timedelta(seconds=fresh - 4)
    again = seed.rebase_seconds(
        now=now + timedelta(days=9), earliest=earliest, newest=newest, existing_earliest=ledger
    )
    assert again == fresh


def _snapshot(stack: Stack) -> dict[str, Any]:
    reviews = len(stack.hitl_store._items)  # pyright: ignore[reportPrivateUsage]
    return {
        "published": len(stack.hub.published),
        "entities": len(cast(Any, stack.catalog)._backend._docs),  # pyright: ignore
        "prices": len(stack.prices.list_snapshots()),
        "recommendations": len(stack.recommendations._items),  # pyright: ignore[reportPrivateUsage]
        "reviews": reviews,
        "intents": len(stack.intents._docs),  # pyright: ignore[reportPrivateUsage]
        "reports": len(stack.reports._rows),  # pyright: ignore[reportPrivateUsage]
        "mcp": len(asyncio.run(stack.mcp.list())),
        "principals": len(stack.policy._principals),  # pyright: ignore[reportPrivateUsage]
    }


# -- landing wait --------------------------------------------------------------------------


def test_timeout_names_what_did_not_land(tmp_path: Path) -> None:
    stack = Stack(lands=False)
    with pytest.raises(seed.LandingTimeout) as raised:
        _run(stack, tmp_path)
    message = str(raised.value)
    for name in seed.LANDED:
        assert name in message
    assert "30s" in message


def test_wait_is_bounded_and_sparse() -> None:
    landing = FakeLanding(lands=False)
    clock = _Clock()
    with pytest.raises(seed.LandingTimeout):
        asyncio.run(
            seed.wait_for_landing(
                landing, overall_seconds=20.0, poll=5.0, sleep=clock.sleep, clock=clock
            )
        )
    assert landing.reads <= 5, "one reading per poll interval, not a tight loop"


def test_wait_returns_on_the_first_complete_reading_by_default() -> None:
    landing = FakeLanding()
    landing.land()
    clock = _Clock()
    result = asyncio.run(
        seed.wait_for_landing(landing, overall_seconds=60, poll=5, sleep=clock.sleep, clock=clock)
    )
    assert result == FAKE_LANDED
    assert landing.reads == 1
    assert clock.now == 0.0, "no sleep when everything already landed"


def test_wait_requires_stable_counts() -> None:
    class Growing:
        def __init__(self) -> None:
            self.reads = 0

        async def counts(self) -> dict[str, int]:
            self.reads += 1
            grow = min(self.reads, 3)
            return {"ledger": grow, "aggregates": 2, "catalog": 2, "archives": 2}

    landing = Growing()
    clock = _Clock()
    result = asyncio.run(
        seed.wait_for_landing(
            landing, overall_seconds=60, poll=1, stable_checks=2, sleep=clock.sleep, clock=clock
        )
    )
    assert result["ledger"] == 3
    assert landing.reads == 4, "waited until two consecutive equal readings"


# -- guards and output ---------------------------------------------------------------------


def _env(**overrides: str) -> dict[str, str]:
    env = {
        "NS_ENV": "local",
        "NS_AUTH_TENANT_ID": TENANT,
        "NS_WORKER_OBJECT_ID": WORKER_OID,
    }
    env.update(overrides)
    return env


@pytest.mark.parametrize(
    "override",
    [
        {"NS_COSMOS_ENDPOINT": "https://contoso.documents.azure.com:443/"},
        {
            "NS_EVENTHUBS_CONNECTION_STRING": "Endpoint=sb://contoso.servicebus.windows.net;"
            "SharedAccessKeyName=n;" + "SharedAccessKey=" + "x" * 8
        },
        {
            "NS_BLOB_CONNECTION_STRING": "DefaultEndpointsProtocol=https;AccountName=contoso;"
            "EndpointSuffix=core.windows.net;"
        },
        {"NS_BLOB_CONNECTION_STRING": "BlobEndpoint=https://contoso.blob.core.windows.net/;"},
        {"NS_STORE_DATABASE": "sandbox-neurosphere"},
        {"NS_ENV": "azure"},
        {"NS_CLOUD": "government"},
        {"NS_WORKER_OBJECT_ID": "not-a-guid"},
    ],
    ids=["cosmos", "eventhubs", "blob-suffix", "blob-endpoint", "database", "env", "cloud", "oid"],
)
def test_unsafe_configuration_exits_non_zero_without_output(
    override: dict[str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    code = seed.main(["--profile", "small"], env=_env(**override))
    out = capsys.readouterr()
    assert code == seed.EXIT_REFUSED
    assert out.out == ""
    assert "REFUSED" in out.err


def test_loopback_defaults_are_accepted() -> None:
    config = seed.resolve_config("small", None, _env())
    assert config.cosmos_endpoint == "http://127.0.0.1:8081"
    assert "127.0.0.1" in config.eventhubs_connection
    assert config.database == "neurosphere"
    assert config.customer == "synthco"
    assert config.blob_connection.startswith("UseDevelopmentStorage")


def test_stdout_is_exactly_the_json_summary(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    summary = {"seeded": dict.fromkeys(seed.CATEGORIES, 1), "skipped_existing": 3}

    async def fake_seed(_config: Any) -> dict[str, Any]:
        seed.log("progress goes to stderr")
        return summary

    monkeypatch.setattr(seed, "_seed", fake_seed)
    code = seed.main(["--profile", "small"], env=_env())
    out = capsys.readouterr()
    assert code == 0
    assert json.loads(out.out) == summary
    assert out.out.count("\n") == 1
    assert "progress goes to stderr" in out.err


def test_run_seed_writes_nothing_to_stdout(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _run(Stack(), tmp_path)
    assert capsys.readouterr().out == ""


def test_failed_step_exits_with_the_failure_code(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    async def failing(_config: Any) -> dict[str, Any]:
        raise seed.LandingTimeout("the workers did not land: ledger")

    monkeypatch.setattr(seed, "_seed", failing)
    code = seed.main(["--profile", "small"], env=_env())
    out = capsys.readouterr()
    assert code == seed.EXIT_FAILED
    assert out.out == ""
    assert "ledger" in out.err


def test_environment_is_restored_after_a_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NS_STORE_DATABASE", raising=False)
    with seed.scoped_environ({"NS_STORE_DATABASE": "x"}):
        import os

        assert os.environ["NS_STORE_DATABASE"] == "x"
    import os

    assert "NS_STORE_DATABASE" not in os.environ


# -- structure -----------------------------------------------------------------------------


def test_only_the_policy_writer_touches_a_raw_container() -> None:
    """Raw container writes are allowed only where the store API IS the container (the policy
    document writer used by ``sbx_grant_operator.grant_operator``)."""
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    raw = {"upsert_item", "create_item", "replace_item", "delete_item"}
    offenders: list[str] = []

    class Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.owner = "<module>"

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            previous, self.owner = self.owner, node.name
            self.generic_visit(node)
            self.owner = previous

        def visit_Call(self, node: ast.Call) -> None:
            if isinstance(node.func, ast.Attribute) and node.func.attr in raw:
                if self.owner != "_CosmosPolicyWriter":
                    offenders.append(f"{self.owner}.{node.func.attr}")
            self.generic_visit(node)

    Visitor().visit(tree)
    assert offenders == []


def test_fixtures_are_synthetic_and_invalid_hosts_only() -> None:
    for name in ("personas.json", "mcp_servers.json", "intents.json", "reports.json"):
        assert seed._fixture(name)["synthetic"] is True
    for server in seed._fixture("mcp_servers.json")["servers"]:
        assert server["url"].split("/")[2].endswith(".invalid")
