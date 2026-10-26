"""PRP-29 item 6: p29_entra_local.py against a fake `az` runner (no Graph call is ever made)."""

from __future__ import annotations

import copy
import importlib.util
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "gates" / "p29_entra_local.py"
APP = "11111111-1111-4111-8111-111111111111"
TENANT = "22222222-2222-4222-8222-222222222222"
APP_OBJ = "33333333-3333-4333-8333-333333333333"
SP_OBJ = "44444444-4444-4444-8444-444444444444"
ME = "55555555-5555-4555-8555-555555555555"
SECRETISH = re.compile(r"eyJ|bearer|secret|password|token=", re.IGNORECASE)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("p29_entra_local_under_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mod = _load()


class FakeAz:
    def __init__(self, app: dict[str, Any] | None = None) -> None:
        self.app: dict[str, Any] = app or {"id": APP_OBJ, "appId": APP}
        self.assignments: list[dict[str, Any]] = []
        self.calls: list[tuple[str, str]] = []

    @property
    def writes(self) -> list[tuple[str, str]]:
        return [c for c in self.calls if c[0] in ("patch", "post")]

    def __call__(self, args: Sequence[str], body: Mapping[str, Any] | None = None) -> str:
        argv = list(args)
        if argv[:2] == ["account", "show"]:
            return TENANT + "\n"
        if argv[:2] == ["ad", "signed-in-user"]:
            return ME + "\n"
        method = argv[argv.index("--method") + 1]
        url = argv[argv.index("--url") + 1]
        self.calls.append((method, url))
        if method == "get" and "/applications(" in url:
            return json.dumps(copy.deepcopy(self.app))
        if method == "get" and "/servicePrincipals(appId" in url:
            return json.dumps({"id": SP_OBJ})
        if method == "get" and url.split("?")[0].endswith("/appRoleAssignedTo"):
            return json.dumps({"value": self.assignments})
        if method == "patch":
            assert body is not None
            for key, value in body.items():
                if key == "api":
                    self.app.setdefault("api", {}).update(value)
                else:
                    self.app[key] = copy.deepcopy(value)
            return ""
        if method == "post":
            assert body is not None
            self.assignments.append(dict(body))
            return json.dumps({"id": "x"})
        raise AssertionError(f"unexpected call {method} {url}")


def run(fake: FakeAz, *extra: str, env: dict[str, str] | None = None) -> int:
    return mod.main(["--app-id", APP, "--tenant-id", TENANT, *extra], az=fake, env=env or {})


def test_dry_run_sends_no_write_and_prints_diff(capsys: pytest.CaptureFixture[str]) -> None:
    fake = FakeAz()
    assert run(fake, "--assign-self", "admin") == 0
    out = capsys.readouterr().out
    assert fake.writes == []
    assert "http://localhost:5173" in out and "would PATCH" in out
    assert '"admin"' in out and "would assign" in out


def test_apply_without_approval_exits_nonzero_and_sends_nothing() -> None:
    fake = FakeAz()
    assert run(fake, "--apply", env={}) != 0
    assert fake.calls == []
    assert run(fake, "--apply", env={"NS_LIVE_APPROVED": "0"}) != 0
    assert fake.calls == []


def test_apply_sets_everything_then_second_apply_is_noop() -> None:
    fake = FakeAz()
    env = {"NS_LIVE_APPROVED": "1"}
    assert run(fake, "--apply", "--assign-self", "admin", env=env) == 0
    assert fake.app["spa"]["redirectUris"] == list(mod.DEFAULT_REDIRECT_URIS)
    assert [r["value"] for r in fake.app["appRoles"]] == [v for v, _ in mod.ROLE_DEFINITIONS]
    assert fake.app["api"]["requestedAccessTokenVersion"] == 2
    assert fake.assignments == [
        {"principalId": ME, "resourceId": SP_OBJ, "appRoleId": mod.role_id("admin")}
    ]
    first = len(fake.writes)
    assert first == 2
    assert run(fake, "--apply", "--assign-self", "admin", env=env) == 0
    assert len(fake.writes) == first


def test_merge_keeps_foreign_uris_and_roles_and_strips_origin() -> None:
    foreign_role = {
        "allowedMemberTypes": ["User"],
        "description": "x",
        "displayName": "Foreign",
        "id": "66666666-6666-4666-8666-666666666666",
        "isEnabled": True,
        "value": "foreign",
        "origin": "Application",
    }
    fake = FakeAz(
        {
            "id": APP_OBJ,
            "appId": APP,
            "spa": {"redirectUris": ["https://foreign.example/cb", "http://localhost:5173"]},
            "appRoles": [foreign_role],
            "api": {"requestedAccessTokenVersion": None},
        }
    )
    assert run(fake, "--apply", env={"NS_LIVE_APPROVED": "1"}) == 0
    assert fake.app["spa"]["redirectUris"] == [
        "https://foreign.example/cb",
        "http://localhost:5173",
        "http://localhost:8080",
    ]
    roles = fake.app["appRoles"]
    assert roles[0]["value"] == "foreign"
    assert len(roles) == 6
    assert all("origin" not in r for r in roles)


def test_custom_redirect_uri_dry_run_writes_nothing() -> None:
    fake = FakeAz()
    assert run(fake, "--redirect-uri", "http://localhost:3000") == 0
    assert fake.writes == []


def test_role_ids_are_stable_uuid5() -> None:
    assert mod.role_id("admin") == mod.role_id("admin")
    assert len({mod.role_id(v) for v, _ in mod.ROLE_DEFINITIONS}) == 5
    assert mod.role_id("admin") == str(mod.uuid.uuid5(mod.ROLE_NAMESPACE, "admin"))
    body = mod.role_body("viewer", "d")
    assert body["allowedMemberTypes"] == ["User"] and body["isEnabled"] is True
    assert "origin" not in body


def test_warns_on_port_only_localhost_collision(capsys: pytest.CaptureFixture[str]) -> None:
    fake = FakeAz(
        {
            "id": APP_OBJ,
            "appId": APP,
            "web": {"redirectUris": ["http://localhost:9000"]},
            "publicClient": {"redirectUris": ["http://localhost:7000/other"]},
        }
    )
    assert run(fake, "--redirect-uri", "http://localhost:5173") == 0
    out = capsys.readouterr().out
    assert "WARNING" in out and "web http://localhost:9000" in out
    assert "publicClient http" not in out  # different path: no collision


def test_output_has_no_secret_token_or_user_id(capsys: pytest.CaptureFixture[str]) -> None:
    fake = FakeAz()
    run(fake, "--apply", "--assign-self", "admin", env={"NS_LIVE_APPROVED": "1"})
    cap = capsys.readouterr()
    text = cap.out + cap.err
    assert not SECRETISH.search(text)
    assert ME not in text


def test_rejects_non_guid_and_wrong_tenant() -> None:
    fake = FakeAz()
    assert mod.main(["--app-id", "nope", "--tenant-id", TENANT], az=fake, env={}) != 0
    other = "77777777-7777-4777-8777-777777777777"
    assert mod.main(["--app-id", APP, "--tenant-id", other], az=fake, env={}) != 0
    assert fake.calls == []


def test_windows_az_cmd_runs_the_bundled_python_not_cmd_exe(tmp_path: Path) -> None:
    wbin = tmp_path / "CLI2" / "wbin"
    wbin.mkdir(parents=True)
    launcher = wbin / "az.CMD"
    launcher.write_text("@echo off\n", encoding="utf-8")
    bundled = tmp_path / "CLI2" / "python.exe"
    bundled.write_bytes(b"")
    assert mod.az_command(str(launcher)) == [str(bundled), "-IBm", "azure.cli"]


def test_az_without_bundled_python_runs_as_found(tmp_path: Path) -> None:
    launcher = tmp_path / "az.cmd"
    launcher.write_text("@echo off\n", encoding="utf-8")
    assert mod.az_command(str(launcher)) == [str(launcher)]
    assert mod.az_command("/usr/bin/az") == ["/usr/bin/az"]
