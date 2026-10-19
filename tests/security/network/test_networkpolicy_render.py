"""Helm NetworkPolicy render tests (PRP-12 item 3): default-deny plus allowlist from values."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
CHART = ROOT / "infra" / "helm"
CI_VALUES = CHART / "ci" / "values-ci.yaml"


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    # Callers pass an absolute executable from shutil.which plus a fixed argv list; no shell.
    return subprocess.run(args, capture_output=True, text=True, check=False, cwd=ROOT, timeout=120)


def _helm() -> str:
    exe = shutil.which("helm")
    if exe is None:
        pytest.skip("helm is not installed; the dedicated Helm 4 CI job runs this test")
    out = _run([exe, "version", "--short"]).stdout.strip()
    match = re.match(r"v?(\d+)\.", out)
    if match is None or int(match.group(1)) != 4:
        pytest.skip(f"Helm 4 required (ADR-0002), found {out!r}")
    return exe


def _policies(*extra: str) -> list[dict[str, Any]]:
    proc = _run([_helm(), "template", "neurosphere", str(CHART), "-f", str(CI_VALUES), *extra])
    assert proc.returncode == 0, proc.stderr
    docs = [d for d in yaml.safe_load_all(proc.stdout) if d]
    return [d for d in docs if d["kind"] == "NetworkPolicy"]


def _by_name(policies: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {p["metadata"]["name"]: p for p in policies}


def test_default_deny_covers_release_pods_both_directions() -> None:
    deny = _by_name(_policies())["neurosphere-default-deny"]["spec"]
    # Scoped to this release, never the whole namespace.
    assert deny["podSelector"] == {"matchLabels": {"app.kubernetes.io/instance": "neurosphere"}}
    assert set(deny["policyTypes"]) == {"Ingress", "Egress"}
    assert "ingress" not in deny  # no rules at all means nothing is allowed
    assert "egress" not in deny


def test_no_policy_allows_everything() -> None:
    for policy in _policies():
        for rule in (*policy["spec"].get("ingress", []), *policy["spec"].get("egress", [])):
            peers = rule.get("from", rule.get("to"))
            assert peers, f"{policy['metadata']['name']}: rule without peers allows all"
            for peer in peers:
                assert peer != {}
                assert peer.get("ipBlock", {}).get("cidr") not in ("0.0.0.0/0", "::/0")


def test_dns_egress_allowed_on_port_53() -> None:
    dns = _by_name(_policies())["neurosphere-allow-dns"]["spec"]
    assert dns["policyTypes"] == ["Egress"]
    ports = {(p["protocol"], p["port"]) for r in dns["egress"] for p in r["ports"]}
    assert ports == {("UDP", 53), ("TCP", 53)}
    peer = dns["egress"][0]["to"][0]
    assert peer["podSelector"]["matchLabels"] == {"k8s-app": "kube-dns"}


def test_intra_release_traffic_limited_to_release_pods() -> None:
    spec = _by_name(_policies())["neurosphere-allow-intra-release"]["spec"]
    selector = {"matchLabels": {"app.kubernetes.io/instance": "neurosphere"}}
    assert spec["ingress"][0]["from"] == [{"podSelector": selector}]
    assert spec["egress"][0]["to"] == [{"podSelector": selector}]


def test_allowlist_entries_come_from_values() -> None:
    policies = _by_name(_policies())
    entry = policies["neurosphere-allow-egress-private-endpoints"]["spec"]["egress"][0]
    assert entry["to"] == [{"ipBlock": {"cidr": "10.40.1.0/24"}}]
    assert entry["ports"] == [{"protocol": "TCP", "port": 443}]
    extra = _by_name(
        _policies(
            "--set",
            "networkPolicy.egressAllowlist[1].name=extra",
            "--set",
            "networkPolicy.egressAllowlist[1].cidr=10.99.0.0/16",
            "--set",
            "networkPolicy.egressAllowlist[1].ports[0].port=1433",
        )
    )["neurosphere-allow-egress-extra"]["spec"]["egress"][0]
    assert extra["to"][0]["ipBlock"]["cidr"] == "10.99.0.0/16"
    assert extra["ports"] == [{"protocol": "TCP", "port": 1433}]


def test_empty_allowlist_renders_no_allowlist_policy() -> None:
    names = _by_name(_policies("--set", "networkPolicy.egressAllowlist=null"))
    assert not [n for n in names if "allow-egress-" in n]


def test_ingress_controller_policy_only_when_ingress_enabled() -> None:
    assert "neurosphere-allow-ingress-controller" not in _by_name(_policies())
    enabled = _by_name(
        _policies("--set", "ingress.enabled=true", "--set", "ingress.host=app.example.invalid")
    )
    spec = enabled["neurosphere-allow-ingress-controller"]["spec"]
    assert spec["policyTypes"] == ["Ingress"]
    assert "namespaceSelector" in spec["ingress"][0]["from"][0]


def test_disabled_renders_no_network_policy() -> None:
    assert _policies("--set", "networkPolicy.enabled=false") == []


def test_allowlist_entry_without_cidr_is_rejected() -> None:
    proc = _run(
        [
            _helm(),
            "template",
            "neurosphere",
            str(CHART),
            "-f",
            str(CI_VALUES),
            "--set",
            "networkPolicy.egressAllowlist[1].name=bad",
            "--set",
            "networkPolicy.egressAllowlist[1].ports[0].port=443",
        ]
    )
    assert proc.returncode != 0
    assert "cidr is required" in proc.stderr
