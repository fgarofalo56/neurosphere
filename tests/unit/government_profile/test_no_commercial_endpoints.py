"""No Azure Commercial endpoint in the Government profile (PRP-20 item 2).

Scans the Government Bicep params folder, ``values-government.yaml``, the compiled Government
params JSON and the full Helm render. Offline: skips only when ``helm`` or ``az`` is missing.
Item 3 (``tests/security/egress``) keeps its own, separate deny corpus.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
GOV_PARAMS = ROOT / "infra" / "bicep" / "params" / "government"
GOV_VALUES = ROOT / "infra" / "helm" / "values-government.yaml"
CHART = ROOT / "infra" / "helm"

# This test's own Commercial host patterns. "*." means any subdomain of the suffix.
COMMERCIAL_PATTERNS = (
    "login.microsoftonline.com",
    "login.windows.net",
    "management.azure.com",
    "management.core.windows.net",
    "*.documents.azure.com",
    "*.servicebus.windows.net",
    "*.search.windows.net",
    "*.vault.azure.net",
    "*.core.windows.net",
    "*.azure-api.net",
    "*.azurewebsites.net",
    "*.azurecr.io",
    "api.loganalytics.io",
    "*.opinsights.azure.com",
    "*.openai.azure.com",
    "*.cognitiveservices.azure.com",
    "portal.azure.com",
    "monitor.azure.com",
    "graph.microsoft.com",
)


def _compile(pattern: str) -> re.Pattern[str]:
    if pattern.startswith("*."):
        return re.compile(r"\." + re.escape(pattern[2:]) + r"(?![\w-])", re.IGNORECASE)
    return re.compile(r"(?<![\w.-])" + re.escape(pattern) + r"(?![\w-])", re.IGNORECASE)


_COMPILED = tuple((p, _compile(p)) for p in COMMERCIAL_PATTERNS)


def find_commercial(text: str) -> list[str]:
    """Return the Commercial patterns that match ``text``."""
    return [p for p, rx in _COMPILED if rx.search(text)]


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    # Callers pass an absolute executable from shutil.which plus a fixed argv list; no shell.
    return subprocess.run(args, capture_output=True, text=True, check=False, cwd=ROOT, timeout=180)


def _helm() -> str:
    exe = shutil.which("helm")
    if exe is None:
        pytest.skip("helm is not installed; the dedicated Helm CI job runs this test")
    return exe


def _az() -> str:
    exe = shutil.which("az")
    if exe is None:
        pytest.skip("az CLI is not installed; cannot compile the Government Bicep params")
    return exe


def test_scanner_catches_planted_commercial_hosts() -> None:
    planted = {
        "login.microsoftonline.com": "https://login.microsoftonline.com/tenant",
        "*.documents.azure.com": "acct.documents.azure.com",
        "*.servicebus.windows.net": "ns.servicebus.windows.net",
        "*.core.windows.net": "store.blob.core.windows.net",
        "*.azurecr.io": "reg.azurecr.io",
        "management.azure.com": "https://management.azure.com/",
    }
    for pattern, text in planted.items():
        assert pattern in find_commercial(text), text


def test_scanner_passes_government_hosts() -> None:
    gov = (
        "login.microsoftonline.us management.usgovcloudapi.net acct.documents.azure.us "
        "ns.servicebus.usgovcloudapi.net s.search.azure.us r.azurecr.us graph.microsoft.us "
        "x.blob.core.usgovcloudapi.net api.loganalytics.us monitor.azure.us portal.azure.us"
    )
    assert find_commercial(gov) == []


def test_government_params_folder_has_no_commercial_host() -> None:
    files = [p for p in GOV_PARAMS.rglob("*") if p.is_file()]
    assert files, "government params folder is empty"
    for path in files:
        assert find_commercial(path.read_text(encoding="utf-8")) == [], str(path)


def test_government_helm_values_have_no_commercial_host() -> None:
    assert find_commercial(GOV_VALUES.read_text(encoding="utf-8")) == []


def test_compiled_government_params_have_no_commercial_host() -> None:
    proc = _run(
        [
            _az(),
            "bicep",
            "build-params",
            "--file",
            str(GOV_PARAMS / "main.bicepparam"),
            "--stdout",
        ]
    )
    assert proc.returncode == 0, proc.stderr
    assert "usgovvirginia" in proc.stdout
    assert find_commercial(proc.stdout) == []


def test_helm_render_with_government_values_has_no_commercial_host() -> None:
    proc = _run([_helm(), "template", "neurosphere", str(CHART), "-f", str(GOV_VALUES)])
    assert proc.returncode == 0, proc.stderr
    assert "NS_CLOUD" in proc.stdout
    assert find_commercial(proc.stdout) == []
