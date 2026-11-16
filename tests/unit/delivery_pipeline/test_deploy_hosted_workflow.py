"""PRP-63 item 4: static rules for .github/workflows/deploy-hosted.yml. No network, no Azure."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github" / "workflows" / "deploy-hosted.yml"
RELEASE = ROOT / ".github" / "workflows" / "release.yml"


@pytest.fixture(scope="module")
def text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def wf(text: str) -> dict[str, Any]:
    return yaml.safe_load(text)


@pytest.fixture(scope="module")
def jobs(wf: dict[str, Any]) -> dict[str, Any]:
    return wf["jobs"]


def _triggers(wf: dict[str, Any]) -> dict[str, Any]:
    # PyYAML reads the bare key `on` as boolean True.
    return wf.get("on") or wf[True]


def _steps_text(job: dict[str, Any]) -> str:
    return "\n".join(str(s.get("run", "")) for s in job["steps"])


def test_jobs_exist(jobs: dict[str, Any]) -> None:
    assert list(jobs) == ["resolve", "plan", "apply", "publish-release"]


def test_no_pull_request_or_push_trigger(wf: dict[str, Any]) -> None:
    triggers = _triggers(wf)
    assert set(triggers) == {"workflow_run", "workflow_dispatch"}
    assert triggers["workflow_run"]["workflows"] == ["release"]
    assert triggers["workflow_run"]["types"] == ["completed"]


def test_release_workflow_name_is_stable() -> None:
    assert yaml.safe_load(RELEASE.read_text(encoding="utf-8"))["name"] == "release"


def test_resolve_guard_requires_push_success_and_main(jobs: dict[str, Any]) -> None:
    cond = " ".join(str(jobs["resolve"]["if"]).split())
    assert "github.event.workflow_run.event == 'push'" in cond
    assert "github.event.workflow_run.conclusion == 'success'" in cond
    assert "startsWith(github.event.workflow_run.head_branch, 'v')" in cond
    assert "github.ref == 'refs/heads/main'" in cond
    for name in ("plan", "apply", "publish-release"):
        assert "resolve" in jobs[name]["needs"]


def test_tag_is_validated_and_checked_against_main(jobs: dict[str, Any]) -> None:
    script = _steps_text(jobs["resolve"])
    assert "semver=" in script and "=~ $semver" in script
    assert "merge-base --is-ancestor" in script


def test_oidc_only(text: str, jobs: dict[str, Any]) -> None:
    logins = [
        (name, s)
        for name, job in jobs.items()
        for s in job["steps"]
        if str(s.get("uses", "")).startswith("azure/login@")
    ]
    assert {n for n, _ in logins} == {"plan", "apply"}
    for _, step in logins:
        assert set(step["with"]) == {"client-id", "tenant-id", "subscription-id"}
        for value in step["with"].values():
            assert re.fullmatch(r"\$\{\{ secrets\.NS_AZURE_[A-Z_]+ \}\}", value)
    lowered = text.lower()
    for banned in ("client-secret", "azure_credentials", "creds:", "az login", "--password"):
        assert banned not in lowered


def test_id_token_only_where_login_happens(wf: dict[str, Any], jobs: dict[str, Any]) -> None:
    assert wf["permissions"] == {}
    holders = {n for n, j in jobs.items() if "id-token" in j.get("permissions", {})}
    assert holders == {"plan", "apply"}
    for name in holders:
        assert jobs[name]["permissions"]["id-token"] == "write"
    assert jobs["publish-release"]["permissions"] == {"contents": "write"}
    for name in ("resolve", "plan", "apply"):
        assert jobs[name]["permissions"].get("contents") == "read"
    writers = {n for n, j in jobs.items() if "write" in j["permissions"].values()}
    assert writers == {"plan", "apply", "publish-release"}
    assert [n for n, j in jobs.items() if j["permissions"].get("contents") == "write"] == [
        "publish-release"
    ]


def test_environments(jobs: dict[str, Any]) -> None:
    assert jobs["plan"]["environment"] == "hosted-demo-plan"
    assert jobs["apply"]["environment"] == "hosted-demo"
    assert "environment" not in jobs["publish-release"]
    assert "environment" not in jobs["resolve"]


def test_apply_deploys_the_planned_hash_for_the_tag_only(jobs: dict[str, Any]) -> None:
    assert jobs["apply"]["needs"] == ["resolve", "plan"]
    assert jobs["apply"]["env"]["PLAN_SHA256"] == "${{ needs.plan.outputs.plan_sha256 }}"
    script = _steps_text(jobs["apply"])
    assert '--approve-plan "$PLAN_SHA256"' in script
    assert jobs["plan"]["outputs"]["plan_sha256"] == "${{ steps.hash.outputs.plan_sha256 }}"
    # No teardown or first-ever deploy subcommands anywhere.
    for name in ("plan", "apply"):
        s = _steps_text(jobs[name])
        for banned in ("teardown", "seed-access", "grant-model-access", "entra-redirect"):
            assert f"hosted_demo.py {banned}" not in s


def test_plan_and_apply_build_identical_arguments(jobs: dict[str, Any]) -> None:
    def step(job: str) -> dict[str, Any]:
        return next(s for s in jobs[job]["steps"] if s.get("name") == "Write infra arguments")

    assert step("plan")["run"] == step("apply")["run"]
    assert step("plan")["env"] == step("apply")["env"]
    for key in ("IMAGE_TAG", "TAG_DELETE_AFTER", "BUDGET_START", "OPERATOR"):
        assert jobs["plan"]["env"][key] == jobs["apply"]["env"][key]


def test_live_approval_only_on_hosted_demo_steps(jobs: dict[str, Any]) -> None:
    for name, job in jobs.items():
        assert "NS_LIVE_APPROVED" not in job.get("env", {}), name
        for s in job["steps"]:
            has = "NS_LIVE_APPROVED" in s.get("env", {})
            calls_demo = "hosted_demo.py" in str(s.get("run", ""))
            assert has == calls_demo, (name, s.get("name"))
    assert "NS_LIVE_APPROVED" not in _steps_text(jobs["publish-release"])


def test_smoke_runs_in_apply_and_publish_waits_for_it(jobs: dict[str, Any]) -> None:
    assert "hosted_smoke.py" in _steps_text(jobs["apply"])
    publish = jobs["publish-release"]
    assert publish["needs"] == ["resolve", "apply"]
    assert publish["if"] == "needs.apply.result == 'success'"
    script = _steps_text(publish)
    assert "--draft=false" in script
    assert "--prerelease" not in script
    assert not [s for s in publish["steps"] if "uses" in s]  # no checkout, no login


def test_concurrency_never_cancels(wf: dict[str, Any]) -> None:
    assert wf["concurrency"]["group"] == "hosted-demo-deploy"
    assert wf["concurrency"]["cancel-in-progress"] is False


def test_every_job_has_a_timeout(jobs: dict[str, Any]) -> None:
    for name, job in jobs.items():
        assert isinstance(job.get("timeout-minutes"), int), name


def test_failures_are_not_suppressed(text: str) -> None:
    assert "continue-on-error" not in text
    assert "|| true" not in text
    assert "set +e" not in text


def test_no_untrusted_expression_in_run_blocks(jobs: dict[str, Any]) -> None:
    for name, job in jobs.items():
        for s in job["steps"]:
            run = str(s.get("run", ""))
            assert "${{" not in run, (name, s.get("name"))


def test_no_secret_literals(text: str) -> None:
    assert not re.search(r"/subscriptions/[0-9a-fA-F-]{36}", text)
    assert not re.search(
        r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b", text
    )
    # Every secrets.* reference uses an NS_ name (or the built-in token) and sits in `with`/`env`.
    for ref in re.findall(r"secrets\.([A-Za-z0-9_]+)", text):
        assert ref.startswith("NS_") or ref == "GITHUB_TOKEN", ref


def test_artifacts_have_short_retention(jobs: dict[str, Any]) -> None:
    uploads = [
        s
        for j in jobs.values()
        for s in j["steps"]
        if str(s.get("uses", "")).startswith("actions/upload-artifact@")
    ]
    assert uploads
    for s in uploads:
        assert 1 <= s["with"]["retention-days"] <= 14


def test_actions_are_pinned_to_a_major(text: str) -> None:
    for ref in re.findall(r"uses:\s*(\S+)", text):
        assert re.search(r"@v\d+$", ref), ref
