"""PRP-35 item 2: the compose catalog seeder (``scripts/sandbox/sbx_seed_catalog.py``).

Runs against the in-memory catalog repository; the emulator run is a compose-level check
(docs/runbooks/seeding.md).
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, cast

import pytest
from neurosphere_core.auth.scope import (
    InMemoryPolicyRepository,
    NoRevocationCheck,
    PolicyHead,
    PrincipalPolicy,
)
from neurosphere_core.catalog import EdgeFilter, EntityFilter
from neurosphere_core.catalog.repo.memory import InMemoryCatalogRepository
from neurosphere_core.paging.models import PageRequest
from neurosphere_workers.runtime.identity import resolve_pseudonym_key
from neurosphere_workers.runtime.settings import AuthSettings

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "sandbox" / "sbx_seed_catalog.py"
TENANT = "0f1e2d3c-4b5a-4968-8776-a5b4c3d2e1f0"
WORKER_OID = "6c1d2e3f-4a5b-4c6d-8e7f-90a1b2c3d4e5"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("sbx_seed_catalog_under_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


cat = _load()
seed = cat.seed


class _Writer:
    def __init__(self, repo: InMemoryPolicyRepository) -> None:
        self._repo = repo

    async def upsert(self, document: dict[str, Any]) -> None:
        if "policy_version" in document:
            self._repo.put_head(PolicyHead.model_validate(document))
        else:
            self._repo.put_principal(PrincipalPolicy.model_validate(document))


def _backends(catalog: InMemoryCatalogRepository) -> Any:
    policy = InMemoryPolicyRepository()
    return SimpleNamespace(
        policy=policy,
        policy_writer=_Writer(policy),
        revocation=NoRevocationCheck(),
        key=resolve_pseudonym_key(AuthSettings(), env="local"),
        catalog=catalog,
    )


def _env(**overrides: str) -> dict[str, str]:
    env = {"NS_ENV": "local", "NS_AUTH_TENANT_ID": TENANT, "NS_WORKER_OBJECT_ID": WORKER_OID}
    env.update(overrides)
    return env


def _config() -> Any:
    return seed.resolve_config("small", None, _env())


@pytest.fixture(autouse=True)
def _local_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NS_ENV", "local")
    for name in ("NS_CLOUD", "NS_AUTH_PSEUDONYM_KEY", "NS_AUTH_PSEUDONYM_KEY_REFERENCE"):
        monkeypatch.delenv(name, raising=False)


def _seed(backends: Any, workdir: Path) -> dict[str, Any]:
    return asyncio.run(cat.seed_catalog(_config(), backends, workdir, environ=_env()))


def _list_all(repo: InMemoryCatalogRepository, scope: Any) -> list[Any]:
    items: list[Any] = []
    cursor: str | None = None
    while True:
        page = asyncio.run(
            repo.list_entities(scope, EntityFilter(), PageRequest(page_size=100, cursor=cursor))
        )
        items += page.items
        cursor = page.next_cursor
        if cursor is None:
            return items


def test_seed_fills_entities_and_edges_then_rerun_creates_nothing(tmp_path: Path) -> None:
    repo = InMemoryCatalogRepository()
    backends = _backends(repo)
    first = _seed(backends, tmp_path / "a")
    assert first["seeded"]["entities"] > 0
    assert first["seeded"]["edges"] > 0

    scope = asyncio.run(seed.worker_scope(backends, _config()))
    entities = _list_all(repo, scope)
    assert {e.entity_type for e in entities} >= {"agent", "model_deployment", "person"}
    agent = next(e for e in entities if e.entity_type == "agent")
    edges = asyncio.run(
        repo.list_edges_by_node(
            scope, agent.id, "both", EdgeFilter(), PageRequest(page_size=100, cursor=None)
        )
    )
    assert edges.items, "an agent has seeded relations"
    ids_before = sorted(e.id for e in entities)

    second = _seed(backends, tmp_path / "b")
    assert second["seeded"] == {"entities": 0, "edges": 0, "grants": 0}
    assert second["skipped_existing"] > 0
    assert sorted(e.id for e in _list_all(repo, scope)) == ids_before


def test_seeded_edges_use_the_projection_id(tmp_path: Path) -> None:
    from neurosphere_workers.projections.catalog.mapping import edge_id

    repo = InMemoryCatalogRepository()
    backends = _backends(repo)
    _seed(backends, tmp_path)
    scope = asyncio.run(seed.worker_scope(backends, _config()))
    doc = seed.read_ndjson(tmp_path / "relations.ndjson")[0]
    stable = edge_id(
        doc["cloud"], doc["customer_id"], doc["relation_type"], doc["source_id"], doc["target_id"]
    )
    assert asyncio.run(repo.get_edge(scope, stable)) is not None


@pytest.mark.parametrize(
    "override",
    [
        {"NS_ENV": "hosted"},
        {"NS_ENV": "azure"},
        {"NS_ENV": "production"},
        {"NS_ENV": "local", "NS_CLOUD": "government"},
        {"NS_ENV": "government"},
        {"NS_ENV": ""},
    ],
    ids=["hosted", "azure", "production", "local-government-cloud", "government", "empty"],
)
def test_non_local_profiles_are_refused_with_a_message(
    override: dict[str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    code = cat.main(["--profile", "small"], env=_env(**override))
    out = capsys.readouterr()
    assert code == cat.EXIT_REFUSED != 0
    assert out.out == ""
    assert out.err.startswith("REFUSED: refusing to seed synthetic data")


def test_unset_ns_env_is_refused(capsys: pytest.CaptureFixture[str]) -> None:
    env = _env()
    del env["NS_ENV"]
    assert cat.main([], env=env) == cat.EXIT_REFUSED
    assert "unset" in capsys.readouterr().err


def test_refusal_happens_before_any_backend_is_opened(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def boom(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("a backend was opened for a refused profile")

    monkeypatch.setattr(seed, "open_backends", boom)
    assert cat.main([], env=_env(NS_ENV="hosted")) == cat.EXIT_REFUSED
    with pytest.raises(seed.ConfigError):
        asyncio.run(
            cat.seed_catalog(
                _config(),
                cast(Any, _backends(InMemoryCatalogRepository())),
                tmp_path,
                environ=_env(NS_ENV="hosted"),
            )
        )


def test_loopback_guard_still_applies() -> None:
    code = cat.main([], env=_env(NS_COSMOS_ENDPOINT="https://contoso.documents.azure.com:443/"))
    assert code == cat.EXIT_REFUSED


def test_success_prints_one_json_line(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    async def fake(_config: Any, _environ: Any) -> dict[str, Any]:
        return {"seeded": {"entities": 1, "edges": 1, "grants": 1}, "skipped_existing": 0}

    monkeypatch.setattr(cat, "_run", fake)
    assert cat.main([], env=_env()) == cat.EXIT_OK
    out = capsys.readouterr().out
    assert json.loads(out)["seeded"]["entities"] == 1


# -- compose wiring ------------------------------------------------------------------------


def _compose_seed() -> dict[str, Any]:
    import yaml

    root = SCRIPT.parents[2]
    doc = yaml.safe_load((root / "docker-compose.yml").read_text(encoding="utf-8"))
    return cast(dict[str, Any], doc["services"]["seed"])


def test_compose_seed_service_is_one_shot_loopback_and_secret_free() -> None:
    service = _compose_seed()
    assert service["profiles"] == ["seed"], "a plain `up` must never start the seeder"
    assert service["network_mode"] == "service:cosmos"
    env = service["environment"]
    assert env["NS_ENV"] == "local"
    assert env["NS_COSMOS_ENDPOINT"].startswith("http://127.0.0.1:")
    assert not {k for k in env if "KEY" in k or "CONNECTION" in k or "SECRET" in k}


def test_compose_seed_worker_oid_matches_the_makefile() -> None:
    root = SCRIPT.parents[2]
    default = _compose_seed()["environment"]["NS_WORKER_OBJECT_ID"]
    makefile = (root / "Makefile").read_text(encoding="utf-8")
    oid = default.split(":-")[1].rstrip("}")
    assert f"STACK_WORKER_OID ?= {oid}" in makefile
    assert "--profile seed run --rm --build seed" in makefile
