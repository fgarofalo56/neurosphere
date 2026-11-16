"""The skip-to-fail switch used by the egress, government and infra tests (issue #100)."""

from __future__ import annotations

from pathlib import Path

import pytest
from _pytest.outcomes import Failed, Skipped

from . import ci_gate


def test_missing_tool_skips_without_ci(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setattr(ci_gate.shutil, "which", lambda _name: None)
    with pytest.raises(Skipped):
        ci_gate.require_tool("helm", "helm is not installed")


@pytest.mark.parametrize("value", ["true", "1", "True"])
def test_missing_tool_fails_under_ci(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("CI", value)
    monkeypatch.setattr(ci_gate.shutil, "which", lambda _name: None)
    with pytest.raises(Failed, match="CI is set"):
        ci_gate.require_tool("helm", "helm is not installed")


@pytest.mark.parametrize("value", ["", "0", "false"])
def test_falsey_ci_value_still_skips(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("CI", value)
    monkeypatch.setattr(ci_gate.shutil, "which", lambda _name: None)
    with pytest.raises(Skipped):
        ci_gate.require_tool("az", "az CLI is not installed")


def test_present_tool_is_returned(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CI", "true")
    monkeypatch.setattr(ci_gate.shutil, "which", lambda name: f"/bin/{name}")
    assert ci_gate.require_tool("helm", "unused") == "/bin/helm"


def test_no_copy_of_skip_or_fail_remains() -> None:
    """#215: the four former copies load ci_gate.skip_or_fail instead of defining their own."""
    root = Path(__file__).resolve().parents[2]
    for rel in (
        "unit/government_profile/test_no_commercial_endpoints.py",
        "unit/government_profile/test_sovereign_hosts.py",
        "unit/infra/test_apim_v2_diagnostics_mcp_front.py",
        "unit/infra/test_helm_render.py",
    ):
        text = (root / rel).read_text(encoding="utf-8")
        assert "def _skip_or_fail" not in text, rel
        assert "_load_skip_or_fail()" in text, rel
