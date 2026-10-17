"""Offline tests for the live-path control-plane provisioner (fake az runner, no network)."""

from __future__ import annotations

import json
import sys
import types
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from graph_benchmark import VARIANTS, run_benchmark
from graph_benchmark.provision import AzCliProvisioner, AzResult, ProvisioningError

SUB = "00000000-1111-2222-3333-444444444444"
SCOPE = [
    "--subscription",
    SUB,
    "--resource-group",
    "rg-g03",
    "--account-name",
    "acct1",
]


class FakeRunner:
    def __init__(self, fail_on: str | None = None) -> None:
        self.calls: list[list[str]] = []
        self.bodies: list[dict[str, Any]] = []
        self.fail_on = fail_on

    def __call__(self, args: Sequence[str]) -> AzResult:
        argv = list(args)
        self.calls.append(argv)
        if "--body" in argv:
            path = Path(argv[argv.index("--body") + 1].removeprefix("@"))
            self.bodies.append(json.loads(path.read_text(encoding="utf-8")))
        if self.fail_on and self.fail_on in argv:
            return AzResult(1, "", "boom")
        return AzResult(0, "", "")


def _prov(runner: FakeRunner) -> AzCliProvisioner:
    return AzCliProvisioner("acct1", "rg-g03", SUB, runner, sleep=lambda _s: None)


def test_database_create_and_delete_argv() -> None:
    r = FakeRunner()
    p = _prov(r)
    p.create_database("db1")
    p.delete_database("db1")
    assert r.calls[0] == ["cosmosdb", "sql", "database", "create", "--name", "db1", *SCOPE]
    assert r.calls[1] == ["cosmosdb", "sql", "database", "delete", "--name", "db1", *SCOPE, "--yes"]
    assert all("--throughput" not in c and "--max-throughput" not in c for c in r.calls)
    assert all("deployment" not in c for c in r.calls)


def test_flat_container_argv() -> None:
    r = FakeRunner()
    _prov(r).create_container("db1", "c1", VARIANTS["flat"])
    assert r.calls == [
        [
            "cosmosdb",
            "sql",
            "container",
            "create",
            "--name",
            "c1",
            "--database-name",
            "db1",
            "--partition-key-path",
            "/domain",
            *SCOPE,
        ]
    ]


@pytest.mark.parametrize("name", ["hier2", "hier3"])
def test_hierarchical_container_uses_arm_put_with_multihash(name: str) -> None:
    r = FakeRunner()
    _prov(r).create_container("db1", "c2", VARIANTS[name])
    put, show = r.calls
    url = (
        f"https://management.azure.com/subscriptions/{SUB}/resourceGroups/rg-g03/providers/"
        "Microsoft.DocumentDB/databaseAccounts/acct1/sqlDatabases/db1/containers/c2"
        "?api-version=2024-05-15"
    )
    assert put[:7] == ["rest", "--method", "put", "--subscription", SUB, "--url", url]
    assert put[7] == "--body"
    assert put[8].startswith("@")
    assert r.bodies[0]["properties"]["resource"] == {
        "id": "c2",
        "partitionKey": {"paths": list(VARIANTS[name].paths), "kind": "MultiHash", "version": 2},
    }
    assert show[:4] == ["cosmosdb", "sql", "container", "show"]


def test_hierarchical_polls_until_available() -> None:
    class Slow(FakeRunner):
        def __call__(self, args: Sequence[str]) -> AzResult:
            res = super().__call__(args)
            if "show" in args and sum("show" in c for c in self.calls) < 3:
                return AzResult(1, "", "not found")
            return res

    r = Slow()
    _prov(r).create_container("db1", "c2", VARIANTS["hier2"])
    assert sum("show" in c for c in r.calls) == 3


def test_failure_raises_provisioning_error() -> None:
    r = FakeRunner(fail_on="delete")
    with pytest.raises(ProvisioningError, match="delete database db1"):
        _prov(r).delete_database("db1")


@pytest.mark.parametrize(
    ("account", "rg", "sub"),
    [
        ("A", "rg", SUB),
        ("acct1", "rg;rm", SUB),
        ("acct1", "rg", "not-a-guid"),
        ("acct1;x", "rg", SUB),
    ],
)
def test_malformed_identifiers_rejected(account: str, rg: str, sub: str) -> None:
    with pytest.raises(ValueError):
        AzCliProvisioner(account, rg, sub, FakeRunner())


class _FakeContainer:
    def __init__(self) -> None:
        self.client_connection = types.SimpleNamespace(last_response_headers={})


class _FakeDb:
    def get_container_client(self, name: str) -> _FakeContainer:
        return _FakeContainer()


class _FakeClient:
    created_db = False
    deleted_db = False

    def __init__(self, *_a: object, **_k: object) -> None:
        pass

    def create_database(self, *_a: object) -> None:
        type(self).created_db = True
        raise AssertionError("data-plane create_database must not be used with a provisioner")

    def delete_database(self, *_a: object) -> None:
        type(self).deleted_db = True
        raise AssertionError("data-plane delete_database must not be used with a provisioner")

    def get_database_client(self, _name: str) -> _FakeDb:
        return _FakeDb()


def test_delete_runs_when_workload_raises_and_sdk_never_provisions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import azure.cosmos

    monkeypatch.setattr(azure.cosmos, "CosmosClient", _FakeClient)
    identity = types.ModuleType("azure.identity")
    identity.DefaultAzureCredential = lambda: object()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "azure.identity", identity)
    r = FakeRunner()
    with pytest.raises(ValueError, match="unknown workload"):
        run_benchmark(
            "https://acct1.documents.azure.com:443/",
            "default_azure_credential",
            workloads=("bogus",),
            provisioner=_prov(r),
        )
    verbs = [c[3] for c in r.calls if c[:3] == ["cosmosdb", "sql", "database"]]
    assert verbs == ["create", "delete"]
    assert not _FakeClient.created_db
    assert not _FakeClient.deleted_db


def test_teardown_failure_is_loud(monkeypatch: pytest.MonkeyPatch) -> None:
    import azure.cosmos

    monkeypatch.setattr(azure.cosmos, "CosmosClient", _FakeClient)
    identity = types.ModuleType("azure.identity")
    identity.DefaultAzureCredential = lambda: object()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "azure.identity", identity)
    with pytest.raises(ProvisioningError, match="delete database"):
        run_benchmark(
            "https://acct1.documents.azure.com:443/",
            "default_azure_credential",
            workloads=("bogus",),
            provisioner=_prov(FakeRunner(fail_on="delete")),
        )


def test_provisioner_rejected_for_emulator() -> None:
    with pytest.raises(ValueError, match="live Entra"):
        run_benchmark("http://localhost:8081", "emulator_key", provisioner=_prov(FakeRunner()))
