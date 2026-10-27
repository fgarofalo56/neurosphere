"""Static checks on .github/workflows/release.yml (PRP-13 item 2). No network, no docker."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
RELEASE = ROOT / ".github" / "workflows" / "release.yml"
SECURITY = ROOT / ".github" / "workflows" / "security.yml"

ALLOWED_USES = {
    "actions/checkout@v7",
    "actions/upload-artifact@v7",
    "actions/download-artifact@v8",
    "actions/setup-python@v7",
    "astral-sh/setup-uv@v7",
    "azure/setup-helm@v5",
}
# Commands that publish or sign something; they must sit behind a non-dry-run guard.
GUARDED = re.compile(
    r"^\s*(docker push|docker login|cosign sign|cosign attest|helm push"
    r"|helm registry login|gh release create)\b"
    r"|\|\s*(docker login|helm registry login)\b",
    re.MULTILINE,
)
NON_DRY_GUARD = re.compile(r"dry_run\s*==\s*'false'|DRY_RUN\s*==\s*'false'")
FORBIDDEN_IN_RUN = ("${{ matrix.", "${{ inputs.", "${{ github.event")


@pytest.fixture(scope="module")
def text() -> str:
    return RELEASE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def wf(text: str) -> dict[str, Any]:
    return yaml.safe_load(text)


def _triggers(wf: dict[str, Any]) -> dict[str, Any]:
    # PyYAML (YAML 1.1) parses the bare key `on` as boolean True.
    loaded: dict[Any, Any] = wf
    on: dict[str, Any] = loaded[True] if True in loaded else loaded["on"]
    return on


def _steps(wf: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    return [(name, s) for name, job in wf["jobs"].items() for s in job.get("steps", [])]


def test_triggers(wf: dict[str, Any]) -> None:
    on = _triggers(wf)
    assert on["push"]["tags"] == ["v*.*.*"]
    dry = on["workflow_dispatch"]["inputs"]["dry_run"]
    assert dry["type"] == "boolean"
    assert dry["default"] is True
    assert set(on["pull_request"]["paths"]) == {
        "services/*/Dockerfile",
        "frontend/Dockerfile",
        "frontend/nginx.conf",
        ".dockerignore",
        ".github/workflows/release.yml",
        "infra/helm/**",
        "scripts/release/**",
    }


def test_expected_jobs(wf: dict[str, Any]) -> None:
    assert set(wf["jobs"]) == {"meta", "images", "sign", "chart", "release-notes"}
    assert wf["jobs"]["images"]["strategy"]["fail-fast"] is False
    services = {m["service"] for m in wf["jobs"]["images"]["strategy"]["matrix"]["include"]}
    assert services == {"api", "workers", "frontend"}


def test_no_suppressed_failures(text: str) -> None:
    assert "|| true" not in text
    assert "continue-on-error" not in text


def test_permissions_and_timeouts(wf: dict[str, Any]) -> None:
    assert wf["permissions"] == {}
    for name, job in wf["jobs"].items():
        assert "permissions" in job, f"job {name} has no permissions block"
        assert "timeout-minutes" in job, f"job {name} has no timeout-minutes"
    assert "concurrency" in wf


def test_id_token_only_in_sign(wf: dict[str, Any]) -> None:
    holders = {n for n, j in wf["jobs"].items() if j["permissions"].get("id-token") == "write"}
    assert holders == {"sign"}


def test_contents_write_only_in_release_notes(wf: dict[str, Any]) -> None:
    holders = {n for n, j in wf["jobs"].items() if j["permissions"].get("contents") == "write"}
    assert holders == {"release-notes"}


def test_publishing_steps_are_guarded(wf: dict[str, Any]) -> None:
    seen = 0
    for name, job in wf["jobs"].items():
        job_guard = NON_DRY_GUARD.search(str(job.get("if", ""))) is not None
        for step in job["steps"]:
            run = step.get("run", "")
            if not GUARDED.search(run):
                continue
            seen += 1
            guarded = job_guard or NON_DRY_GUARD.search(str(step.get("if", ""))) is not None
            assert guarded, f"unguarded publish step in {name}: {step.get('name')}"
    assert seen >= 6


def test_uses_are_allowed(wf: dict[str, Any]) -> None:
    for _, step in _steps(wf):
        if "uses" in step:
            assert step["uses"] in ALLOWED_USES, step["uses"]


def test_helm_pinned(wf: dict[str, Any]) -> None:
    helm = [s for _, s in _steps(wf) if s.get("uses") == "azure/setup-helm@v5"]
    assert helm
    assert all(s["with"]["version"] == "v4.3.0" for s in helm)


def test_curl_followed_by_sha256(wf: dict[str, Any]) -> None:
    downloads = 0
    for _, step in _steps(wf):
        run = step.get("run", "")
        for m in re.finditer(r"\bcurl\b", run):
            downloads += 1
            assert "sha256sum -c" in run[m.end() :], (
                f"curl without sha256sum -c: {step.get('name')}"
            )
    assert downloads >= 2  # syft and cosign


def test_no_untrusted_expressions_in_run(wf: dict[str, Any]) -> None:
    for name, step in _steps(wf):
        run = step.get("run", "")
        for bad in FORBIDDEN_IN_RUN:
            assert bad not in run, f"{bad} interpolated into run in {name}: {step.get('name')}"


def test_sign_verifies_in_workflow(wf: dict[str, Any]) -> None:
    run = "\n".join(s.get("run", "") for s in wf["jobs"]["sign"]["steps"])
    for cmd in (
        "cosign sign --yes",
        "cosign attest --yes --type cyclonedx",
        "cosign verify",
        "cosign verify-attestation --type cyclonedx",
    ):
        assert cmd in run, cmd
    assert "--certificate-identity" in run
    assert "--certificate-oidc-issuer" in run
    assert "/.github/workflows/release.yml@${GITHUB_REF}" in run


def test_no_stored_credentials(text: str) -> None:
    assert "secrets." in text
    assert set(re.findall(r"secrets\.(\w+)", text)) == {"GITHUB_TOKEN"}


def test_security_discover_step_covers_frontend() -> None:
    sec = yaml.safe_load(SECURITY.read_text(encoding="utf-8"))
    steps = sec["jobs"]["discover-images"]["steps"]
    find = next(s for s in steps if s.get("id") == "find")
    assert "frontend/Dockerfile" in find["run"]
