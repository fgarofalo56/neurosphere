"""The ``NS_ENV=local`` seed loader (PRP-105 item 6, clarification 11).

Only under ``NS_ENV=local``: the seed publishes synthetic fixture policies through
``PolicyLifecycle.publish`` (audited ``govpolicy.seed``); any other environment refuses to start
with ``govpolicy_seed_not_local``. A restart publishes nothing twice.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

import pytest
from govpolicy_api_harness import (  # pyright: ignore[reportMissingImports]
    FINANCE,
    VIEWER,
    compose_governance,
    rule,
)
from neurosphere_api.runtime.builders import governance as builder
from neurosphere_core.cloud import CloudName, Settings
from runtime_api.runtime_helpers import compose  # pyright: ignore[reportMissingImports]


def _seed(tmp_path: Path, **over: Any) -> Path:
    entry: dict[str, Any] = {
        "policy_id": "seed-owners",
        "domain_id": FINANCE,
        "display_name": "Seeded owners",
        "severity": "high",
        "rules": [rule()],
    }
    entry.update(over)
    path = tmp_path / "govpolicy-seed.json"
    path.write_text(json.dumps({"policies": [entry]}), encoding="utf-8")
    return path


def _operations(parts: Any) -> list[str]:
    store = parts.audit_store
    chains = {chain for (chain, _doc) in store._docs}  # pyright: ignore[reportPrivateUsage]
    return [
        str(d["operation"])
        for chain in sorted(chains)
        for d in sorted(store.raw_documents(chain), key=lambda d: d["sequence"])
    ]


@pytest.mark.parametrize("env", ["dev", "test", "staging", "prod"])
def test_a_seed_file_outside_local_refuses_to_start(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, env: Literal["dev", "test", "staging", "prod"]
) -> None:
    monkeypatch.setenv("NS_ENV", env)
    monkeypatch.setenv("NS_GOVPOLICY_LOCAL_SEED_FILE", str(_seed(tmp_path)))
    with pytest.raises(builder.GovPolicySeedNotLocalError) as refused:
        compose(
            None,
            builders=(builder.BUILDER,),
            settings=Settings(env=env, cloud=CloudName.COMMERCIAL),
        )
    assert refused.value.reason == "govpolicy_seed_not_local"
    assert str(refused.value) == "govpolicy_seed_not_local"


def test_the_local_seed_publishes_through_the_lifecycle(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    parts = compose_governance(monkeypatch, NS_GOVPOLICY_LOCAL_SEED_FILE=str(_seed(tmp_path)))
    assert parts.composed.registry.get("governance_policy").state == "ok"
    with parts.composed.client() as client:  # the lifespan runs the startup hook
        response = client.get(
            f"/api/v1/governance/policy/domains/{FINANCE}/policies/seed-owners",
            headers=parts.composed.auth(VIEWER),
        )
        assert response.status_code == 200, response.text
        policy = response.json()["policy"]
        assert policy["status"] == "published"
        assert policy["published_intent_id"] is not None
        assert policy["published_audit_id"] is not None
        bindings = client.get(
            f"/api/v1/governance/policy/domains/{FINANCE}/bindings",
            headers=parts.composed.auth(VIEWER),
        ).json()["items"]
        assert {b["binding"]["mode"] for b in bindings} <= {"audit"}
    operations = _operations(parts)
    assert "govpolicy.seed" in operations
    assert "govpolicy.publish" not in operations


async def test_a_restart_publishes_nothing_twice(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    parts = compose_governance(monkeypatch, NS_GOVPOLICY_LOCAL_SEED_FILE=str(_seed(tmp_path)))
    plane = parts.composed.app.state.governance_policy
    seed = builder.load_seed_file(_seed(tmp_path))
    first = await builder.seed_policies(plane, seed, cloud="commercial", customer_id="contoso")
    again = await builder.seed_policies(plane, seed, cloud="commercial", customer_id="contoso")
    assert (first, again) == (["seed-owners"], [])
    assert _operations(parts).count("govpolicy.seed") == 2  # one before/after pair


async def test_a_changed_seed_publishes_the_next_version(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    parts = compose_governance(monkeypatch)
    plane = parts.composed.app.state.governance_policy
    first = builder.load_seed_file(_seed(tmp_path))
    await builder.seed_policies(plane, first, cloud="commercial", customer_id="contoso")
    changed = builder.load_seed_file(_seed(tmp_path, rules=[rule(), rule("eu", "residency")]))
    republished = await builder.seed_policies(
        plane, changed, cloud="commercial", customer_id="contoso"
    )
    assert republished == ["seed-owners"]
    stored = await plane.policies.get("contoso", "seed-owners")
    assert stored is not None
    assert (stored.policy.policy_version, stored.policy.status) == (2, "published")


def test_a_malformed_seed_fails_the_component(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"policies": [{"policy_id": "x"}]}), encoding="utf-8")
    parts = compose_governance(monkeypatch, NS_GOVPOLICY_LOCAL_SEED_FILE=str(bad))
    status = parts.composed.registry.get("governance_policy")
    assert (status.state, status.code) == ("failed", "govpolicy_seed_invalid")


def test_a_seed_with_an_unavailable_kind_is_refused_at_startup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = _seed(tmp_path, rules=[rule("cards", "content_rule")])
    parts = compose_governance(monkeypatch, NS_GOVPOLICY_LOCAL_SEED_FILE=str(path))
    with parts.composed.client():
        pass
    status = parts.composed.registry.get("governance_policy")
    assert (status.state, status.code) == ("failed", "startup_failed")
    assert "govpolicy.seed" not in _operations(parts)
