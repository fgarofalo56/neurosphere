"""PRP-32 item 10: ``deploy --resume-failed`` recovers ownership after a failed S3 deploy.

Every test drives the script through the shared fake `az` runner (see
``test_hosted_demo_refuses.py``): no subprocess `az`, no network. Synthetic ids only.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest


def _fakes() -> ModuleType:
    name = "hosted_demo_fakes"
    if name in sys.modules:
        return sys.modules[name]
    path = Path(__file__).with_name("test_hosted_demo_refuses.py")
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


F = _fakes()
SHARED = "hub-subnet,hub-pe,hub-dns,budget"
FOREIGN = {
    "id": F._rid("Microsoft.Storage/storageAccounts", "foreignstore"),
    "type": "Microsoft.Storage/storageAccounts",
}
_SHARED_NIC = F._rid("Microsoft.Network/networkInterfaces", "nsdemo-api-pe-nic")
# The real implicit NIC name shape is ``<pe>.nic.<id>``.
NIC = F._rid("Microsoft.Network/networkInterfaces", "nsdemo-api-pe.nic.0a1b2c3d")


def _nic(name: str) -> dict[str, str]:
    rid = F._rid("Microsoft.Network/networkInterfaces", name)
    return {"id": rid, "type": "Microsoft.Network/networkInterfaces"}


@pytest.fixture(autouse=True)
def _approved(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NS_LIVE_APPROVED", "1")
    resources = [
        _nic("nsdemo-api-pe.nic.0a1b2c3d") if r["id"] == _SHARED_NIC else r for r in F.RESOURCES
    ]
    monkeypatch.setattr(F, "RESOURCES", resources)


@pytest.fixture
def env(tmp_path: Path) -> Any:
    return F.Env(tmp_path)


def _latest(env: Any, command: str) -> Path:
    files = list((env.tmp / "ev").glob(f"*-{command}.json"))
    return max(files, key=lambda p: p.stat().st_mtime_ns)


def _creates() -> list[dict[str, Any]]:
    """The first plan: every resource and the budget are Create (the NIC is implicit)."""
    ids = [r["id"] for r in F.RESOURCES if r["id"] != NIC] + [F.BUDGET_ID]
    return [{"changeType": "Create", "resourceId": i} for i in ids]


def failed_deploy(env: Any) -> Path:
    """Plan (hash A), then a deploy that ends Failed after every resource was created."""
    env.fake.changes = _creates()
    digest = env.plan_hash()
    env.fake.deploy_state = "Failed"
    assert env.run("deploy", "--approve-plan", digest, "--approve-shared", SHARED) == 1
    env.fake.deploy_state = "Succeeded"
    env.fake.live.append(dict(FOREIGN))
    return _latest(env, "deploy")


def replan(env: Any) -> str:
    """Plan again after the failure: the resources now exist, so what-if says NoChange."""
    env.fake.changes = [{"changeType": "NoChange", "resourceId": i["id"]} for i in env.fake.live]
    assert env.run("plan") == 0
    return str(json.loads(_latest(env, "plan").read_text("utf-8"))["details"]["plan_sha256"])


def resume(env: Any, failed: Path, digest: str) -> int:
    env.fake.calls.clear()
    return env.run(
        "deploy", "--approve-plan", digest, "--approve-shared", SHARED,
        "--resume-failed", str(failed),
    )  # fmt: skip


def _rows(env: Any) -> dict[str, Any]:
    data = json.loads((env.tmp / "state" / f"register-hosted-{F.RG}.json").read_text("utf-8"))
    return {r["resource_id"].lower(): r for r in data["rows"]}


def _no_create(env: Any) -> bool:
    return env.fake.index("deployment", "group", "create") == -1


def _edit(path: Path, change: Any) -> None:
    data = json.loads(path.read_text("utf-8"))
    change(data)
    path.write_text(json.dumps(data), encoding="utf-8")


# --------------------------------------------------------------------------- happy path


def test_resume_registers_prior_plan_resources_and_budget_as_ours(env: Any) -> None:
    failed = failed_deploy(env)
    new_hash = replan(env)
    # without the register, a plain deploy would call all of this pre-existing
    assert resume(env, failed, new_hash) == 0
    rows = _rows(env)
    for r in F.RESOURCES:
        assert rows[r["id"].lower()]["created_by"] == "neurosphere", r["id"]
    assert rows[F.BUDGET_ID.lower()]["created_by"] == "neurosphere"
    foreign = rows[FOREIGN["id"].lower()]
    assert foreign["created_by"] is None
    assert foreign["consent_reference"] == "pre-existing-at-deploy"
    details = json.loads(_latest(env, "deploy").read_text("utf-8"))["details"]
    assert details["resumed_from"] == failed.name
    assert details["resume_registered_count"] == len(F.RESOURCES) + 1


def test_resume_never_claims_a_sibling_prefix_nic(env: Any) -> None:
    failed = failed_deploy(env)
    siblings = [_nic("nsdemo-api-pe2.nic.0a1b2c3d"), _nic("nsdemo-api-pe-x.nic.0a1b2c3d")]
    env.fake.live += siblings
    assert resume(env, failed, replan(env)) == 0
    rows = _rows(env)
    assert rows[NIC.lower()]["created_by"] == "neurosphere"
    for s in siblings:
        assert rows[s["id"].lower()]["created_by"] is None, s["id"]


def test_resume_deploys_even_though_the_new_plan_has_no_creates(env: Any) -> None:
    failed = failed_deploy(env)
    assert resume(env, failed, replan(env)) == 0
    assert env.fake.index("deployment", "group", "create") != -1


def test_without_the_flag_the_same_state_registers_nothing_as_ours(env: Any) -> None:
    failed_deploy(env)
    digest = replan(env)
    env.fake.calls.clear()
    assert env.run("deploy", "--approve-plan", digest, "--approve-shared", SHARED) == 0
    rows = _rows(env)
    assert rows[F.RESOURCES[0]["id"].lower()]["created_by"] is None
    assert "resumed_from" not in json.loads(_latest(env, "deploy").read_text("utf-8"))["details"]


# --------------------------------------------------------------------------- refusals


def test_resume_refuses_without_approval_env(env: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NS_LIVE_APPROVED")
    assert env.run("deploy", "--resume-failed", "x") == 2
    assert env.fake.calls == []


def test_refuses_a_failed_file_that_is_not_a_failed_deploy(env: Any) -> None:
    failed = failed_deploy(env)
    digest = replan(env)
    _edit(failed, lambda d: d.update(result="PASS"))
    assert resume(env, failed, digest) == 2
    assert _no_create(env)
    _edit(failed, lambda d: d.update(result="FAIL", command="plan"))
    assert resume(env, failed, digest) == 2
    assert _no_create(env)


def test_refuses_a_different_deployment_id(env: Any) -> None:
    failed = failed_deploy(env)
    digest = replan(env)
    _edit(failed, lambda d: d.update(deployment_id="hosted-other"))
    assert resume(env, failed, digest) == 2
    assert _no_create(env)


def test_refuses_without_a_plan_hash_approval(env: Any) -> None:
    failed = failed_deploy(env)
    digest = replan(env)
    _edit(
        failed,
        lambda d: d.update(approvals=[a for a in d["approvals"] if a["token"] != "plan-hash"]),
    )
    assert resume(env, failed, digest) == 2
    assert _no_create(env)


def test_refuses_an_unreadable_failed_file(env: Any, tmp_path: Path) -> None:
    failed_deploy(env)
    digest = replan(env)
    assert resume(env, tmp_path / "missing.json", digest) == 2
    assert _no_create(env)


def test_refuses_when_the_group_is_not_ours(env: Any) -> None:
    failed = failed_deploy(env)
    digest = replan(env)
    env.fake.rg_tags = {"neurosphere:deployment-id": "someone-else"}
    assert resume(env, failed, digest) == 2
    assert _no_create(env)


def test_refuses_without_matching_plan_evidence(env: Any) -> None:
    failed = failed_deploy(env)
    digest = replan(env)
    _edit(failed, lambda d: d["details"].update(plan_sha256="0" * 64))
    assert resume(env, failed, digest) == 2
    assert _no_create(env)


def test_refuses_when_the_plan_evidence_has_no_change_list(env: Any) -> None:
    failed = failed_deploy(env)
    digest = replan(env)
    for plan in (env.tmp / "ev").glob("*-plan.json"):
        _edit(plan, lambda d: d["details"].pop("changes", None))
    assert resume(env, failed, digest) == 2
    assert _no_create(env)


def test_refuses_when_the_register_already_has_created_rows(env: Any) -> None:
    failed = failed_deploy(env)
    digest = replan(env)
    env.fake.calls.clear()
    assert env.run("deploy", "--approve-plan", digest, "--approve-shared", SHARED) == 0
    assert resume(env, failed, digest) == 2
    assert _no_create(env)


def test_refuses_a_stale_approve_plan_hash(env: Any) -> None:
    failed = failed_deploy(env)
    replan(env)
    assert resume(env, failed, "f" * 64) == 2
    assert _no_create(env)


# --------------------------------------------------------------------------- evidence text


def test_evidence_keeps_the_whole_az_error(env: Any) -> None:
    class Failing:
        def __init__(self, inner: Any) -> None:
            self.inner = inner

        def __getattr__(self, name: str) -> Any:
            return getattr(self.inner, name)

        def __call__(self, args: Any) -> Any:
            if list(args[:4]) == ["deployment", "group", "create", "--name"] or (
                list(args[:3]) == ["deployment", "group", "create"]
            ):
                return F.R(1, "", "ResourceNotFound " + "detail " * 400 + "END-MARKER")
            return self.inner(args)

    env.fake.changes = _creates()
    digest = env.plan_hash()
    env.fake = Failing(env.fake)
    assert env.run("deploy", "--approve-plan", digest, "--approve-shared", SHARED) == 1
    text = " ".join(json.loads(_latest(env, "deploy").read_text("utf-8"))["errors"])
    assert "END-MARKER" in text and len(text) > 2500
