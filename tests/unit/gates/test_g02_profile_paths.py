"""G02 profile gates (AKS, App Service): approved-path behaviour driven through a fake runner.

No real binary is ever invoked: `execute(...)` takes an injectable runner that scripts every
az/helm/kubectl answer. Subscription ids are random GUIDs generated at runtime.
"""

from __future__ import annotations

import argparse
import importlib
import json
import subprocess
import sys
import uuid
from collections.abc import Callable, Sequence
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[3]
GATES = REPO / "scripts" / "gates"
PROFILES = ("aks", "appservice")
TAG_RUN_KEY = "neurosphere:run-id"


def _common() -> ModuleType:
    if str(GATES) not in sys.path:
        sys.path.insert(0, str(GATES))
    return importlib.import_module("_g02_profile_common")


def _profile(kind: str) -> Any:
    common = _common()
    if kind == "aks":
        return importlib.import_module("g02_profile_aks").AksProfile(common)
    return importlib.import_module("g02_profile_appservice").AppServiceProfile(common)


class FakeRunner:
    """Scripts az/helm/kubectl. ``hooks`` map a space-joined argv prefix to a callable."""

    def __init__(self, subscription: str) -> None:
        self.subscription = subscription
        self.calls: list[list[str]] = []
        self.run_id = ""
        self.rg = ""
        self.tagged: set[str] = set()
        self.extra_resources: list[str] = []  # foreign, never taggable
        self.what_if_changes: list[dict[str, str]] = []
        self.hooks: dict[str, Callable[[list[str]], subprocess.CompletedProcess[str] | None]] = {}
        self.fail_prefixes: dict[str, str] = {}  # prefix -> stderr
        self.raw_stdout: dict[str, str] = {}  # prefix -> stdout override

    def joined(self) -> list[str]:
        return [" ".join(c) for c in self.calls]

    def issued(self, prefix: str) -> bool:
        return any(j.startswith(prefix) for j in self.joined())

    def __call__(self, argv: Sequence[str]) -> Any:
        res = _common().CmdResult  # type: ignore[attr-defined]
        args = list(argv)
        self.calls.append(args)
        line = " ".join(args)
        for prefix, hook in self.hooks.items():
            if line.startswith(prefix):
                hook(args)
        for prefix, err in self.fail_prefixes.items():
            if line.startswith(prefix):
                return res(1, "", err)
        for prefix, out in self.raw_stdout.items():
            if line.startswith(prefix):
                return res(0, out, "")
        return res(0, self._answer(args, line), "")

    def _answer(self, args: list[str], line: str) -> str:
        if line.startswith("az cloud show"):
            return "AzureUSGovernment\n"
        if line.startswith("az group create"):
            self.rg = args[args.index("--name") + 1]
            self.run_id = next(a.split("=", 1)[1] for a in args if a.startswith(TAG_RUN_KEY + "="))
            return ""
        if line.startswith("az tag update"):
            rid = args[args.index("--resource-id") + 1]
            if "foreign" not in rid:
                self.tagged.add(rid)
            return ""
        if line.startswith("az resource list"):
            base = f"/subscriptions/{self.subscription}/resourceGroups/{self.rg}/providers/x"
            mine = [f"{base}/a{i}" for i in range(2)]
            if "[].id" in args:
                return json.dumps([*mine, *self.extra_resources])
            tags = {
                TAG_RUN_KEY: self.run_id,
                "neurosphere:created-by": "neurosphere",
            }
            items: list[dict[str, Any]] = [{"id": r, "tags": tags} for r in mine]
            items += [{"id": r, "tags": None} for r in self.extra_resources]
            return json.dumps(items)
        if line.startswith("az group show"):
            return json.dumps({TAG_RUN_KEY: self.run_id})
        if "what-if" in args:
            return json.dumps({"changes": self.what_if_changes})
        if line.startswith("az webapp list"):
            return json.dumps([{"name": "app", "state": "Running"}])
        if line.startswith("helm status"):
            return json.dumps({"info": {"status": "deployed"}})
        if line.startswith("helm get"):
            return "stable-output"
        return ""


class Env:
    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.subscription = str(uuid.uuid4())
        self.evidence = tmp_path / "evidence"
        self.work = tmp_path / "work"
        self.work.mkdir()
        monkeypatch.setenv("NS_GOV_SUBSCRIPTION_ID", self.subscription)
        monkeypatch.setenv("NS_GOV_IMAGE_REGISTRY", "acrgovtest")
        monkeypatch.setenv("NS_GOV_AKS_CLUSTER", "aks-test")
        monkeypatch.setenv("NS_GOV_AKS_RESOURCE_GROUP", "rg-aks-test")
        self.runner = FakeRunner(self.subscription)

    def go(self, profile: Any) -> int:
        return int(
            _common().execute(  # type: ignore[attr-defined]
                profile, [], runner=self.runner, evidence_dir=self.evidence, work_dir=self.work
            )
        )

    def evidence_text(self, kind: str) -> str:
        files = list(self.evidence.glob(f"profile-{kind}-*.md"))
        assert len(files) == 1
        return files[0].read_text(encoding="utf-8")


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Env:
    return Env(tmp_path, monkeypatch)


@pytest.mark.parametrize("kind", PROFILES)
def test_approved_success_writes_scrubbed_evidence(env: Env, kind: str) -> None:
    rc = env.go(_profile(kind))
    assert rc == 0
    text = env.evidence_text(kind)
    assert f"# G02 {kind} profile - PASS" in text
    assert env.subscription not in text
    assert env.subscription.upper() not in text
    assert "<subscription:" in text
    assert "resource group and workload objects removed" in text
    assert env.runner.issued("az group delete")
    assert "eyJ" not in text


@pytest.mark.parametrize("kind", PROFILES)
def test_credential_looking_failure_text_is_redacted(env: Env, kind: str) -> None:
    other = str(uuid.uuid4())
    failing = "az deployment group create"
    env.runner.fail_prefixes[failing] = f"denied for {env.subscription} and {other}"
    assert env.go(_profile(kind)) == 1
    text = env.evidence_text(kind)
    assert env.subscription not in text
    assert other not in text
    assert "FAIL" in text
    assert env.runner.issued("az group delete")


@pytest.mark.parametrize("kind", PROFILES)
def test_drift_is_reported(env: Env, kind: str) -> None:
    env.runner.what_if_changes = [{"changeType": "Modify"}, {"changeType": "NoChange"}]
    assert env.go(_profile(kind)) == 1
    text = env.evidence_text(kind)
    assert "Drift changes on second pass: 1" in text
    assert "[FAIL] drift-second-pass" in text
    assert env.runner.issued("az group delete")  # run-tagged group is still cleaned up


def test_plan_dry_run_targets_only_run_tagged_resources() -> None:
    c = _common()
    mine = {"neurosphere:run-id": "r1", "neurosphere:created-by": "neurosphere"}
    resources = [
        {"id": "/subscriptions/s/resourceGroups/RG-X/providers/a/1", "tags": mine},
        {"id": "/subscriptions/s/resourceGroups/rg-x/providers/a/2", "tags": None},
        {
            "id": "/subscriptions/s/resourceGroups/rg-x/providers/a/3",
            "tags": {**mine, TAG_RUN_KEY: "r2"},
        },
        {"id": "/subscriptions/s/resourceGroups/rg-other/providers/a/4", "tags": mine},
    ]
    plan = c.plan_dry_run(resources, "rg-x", "r1")  # type: ignore[attr-defined]
    assert plan.removable == ("/subscriptions/s/resourceGroups/RG-X/providers/a/1",)
    assert len(plan.protected) == 3


@pytest.mark.parametrize("kind", PROFILES)
def test_shared_resource_blocks_group_delete(env: Env, kind: str) -> None:
    foreign = "/subscriptions/x/resourceGroups/shared/providers/y/foreign-vault"
    env.runner.extra_resources = [foreign]
    assert env.go(_profile(kind)) == 1
    text = env.evidence_text(kind)
    assert "protected: 1" in text
    assert "foreign resources found in the group; not deleted" in text
    assert not env.runner.issued("az group delete")
    assert foreign not in env.runner.tagged


class _StubProfile:
    name = "stub"

    def __init__(self, cleanup_exc: BaseException) -> None:
        self._exc = cleanup_exc

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        return None

    def validate(self, args: argparse.Namespace) -> None:
        return None

    def deploy(self, ctx: Any) -> None:
        return None

    def smoke(self, ctx: Any) -> None:
        return None

    def drift(self, ctx: Any) -> int:
        return 0

    def cleanup(self, ctx: Any) -> None:
        raise self._exc


def test_cleanup_timeout_still_deletes_group(env: Env) -> None:
    exc = subprocess.TimeoutExpired(["helm", "uninstall"], 1)
    rc = env.go(_StubProfile(exc))
    assert rc == 1
    assert env.runner.issued("az group delete")
    text = env.evidence_text("stub")
    assert "TimeoutExpired" in text
    assert "FAILED" in text


def test_cleanup_json_error_still_deletes_group(env: Env) -> None:
    rc = env.go(_StubProfile(json.JSONDecodeError("bad", "x", 0)))
    assert rc == 1
    assert env.runner.issued("az group delete")
    assert "JSONDecodeError" in env.evidence_text("stub")


def test_cleanup_keyboard_interrupt_deletes_group_then_propagates(env: Env) -> None:
    with pytest.raises(KeyboardInterrupt):
        env.go(_StubProfile(KeyboardInterrupt()))
    assert env.runner.issued("az group delete")
    assert "interrupted" in env.evidence_text("stub")


def test_group_delete_failure_is_recorded_not_swallowed(env: Env) -> None:
    env.runner.fail_prefixes["az group delete"] = "boom"
    assert env.go(_profile("appservice")) == 1
    text = env.evidence_text("appservice")
    assert "group delete:" in text
    assert "FAILED" in text


def test_helm_timeout_in_aks_uninstall_still_deletes_namespace_and_group(env: Env) -> None:
    def boom(args: list[str]) -> None:
        if args[:2] == ["helm", "uninstall"]:
            raise subprocess.TimeoutExpired(args, 1)

    env.runner.hooks["helm uninstall"] = boom
    assert env.go(_profile("aks")) == 1
    assert env.runner.issued("kubectl delete namespace")
    assert env.runner.issued("az group delete")
    assert "TimeoutExpired" in env.evidence_text("aks")


@pytest.mark.parametrize("kind", PROFILES)
def test_json_decode_error_from_listing_still_tears_down(env: Env, kind: str) -> None:
    def bad(args: list[str]) -> None:
        if "[].id" in args:
            raise json.JSONDecodeError("bad", "x", 0)

    env.runner.hooks["az resource list"] = bad
    assert env.go(_profile(kind)) == 1
    assert env.runner.issued("az group delete")
    assert "JSONDecodeError" in env.evidence_text(kind)


def test_non_json_listing_output_still_tears_down(env: Env) -> None:
    env.runner.raw_stdout["az resource list"] = "not json {"
    assert env.go(_profile("appservice")) == 1
    assert env.runner.issued("az group delete")


def test_failed_helm_install_is_still_uninstalled(env: Env) -> None:
    env.runner.fail_prefixes["helm upgrade --install"] = "install failed midway"
    assert env.go(_profile("aks")) == 1
    joined = env.runner.joined()
    install = next(i for i, j in enumerate(joined) if j.startswith("helm upgrade --install"))
    uninstall = next(i for i, j in enumerate(joined) if j.startswith("helm uninstall"))
    assert uninstall > install
    assert env.runner.issued("kubectl delete namespace")
    assert env.runner.issued("az group delete")
