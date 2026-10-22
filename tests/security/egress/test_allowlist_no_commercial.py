"""Static proof that the rendered Government config names no Azure Commercial host.

Result label: static and compose only; in-cluster proof OPEN (no Government subscription, D7).
This test asserts nothing about a live Government cluster, authorization or parity.

NetworkPolicy (PRP-12) is CIDR-only, so the rendered "egress allowlist" is IP ranges. The host
level is therefore scanned in the full `helm template` output, the sovereign profile manifest,
values-government.yaml and the compiled Bicep parameters.
"""

from __future__ import annotations

import ipaddress
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from .corpus import compile_corpus, concrete_host, find_hits, load_corpus

ROOT = Path(__file__).resolve().parents[3]
CHART = ROOT / "infra" / "helm"
VALUES_GOV = CHART / "values-government.yaml"
PROFILE = ROOT / "infra" / "bicep" / "params" / "government" / "sovereign-profile.yaml"
BICEPPARAM = ROOT / "infra" / "bicep" / "params" / "government" / "main.bicepparam"

# Government suffixes every egress host must sit under (anchored, whole-label).
GOV_SUFFIX = re.compile(
    r"(?:^|\.)(?:microsoftonline\.us|microsoft\.us|azure\.us|usgovcloudapi\.net|azure-api\.us"
    r"|azurewebsites\.us|azurecr\.us|loganalytics\.us)$",
    re.IGNORECASE,
)


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    # Absolute executable from shutil.which plus a fixed argv list; no shell.
    return subprocess.run(args, capture_output=True, text=True, check=False, cwd=ROOT, timeout=180)


def _helm_render() -> str:
    exe = shutil.which("helm")
    if exe is None:
        pytest.skip("helm is not installed; cannot render the Government chart")
    proc = _run([exe, "template", "neurosphere", str(CHART), "-f", str(VALUES_GOV)])
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


def _strings(node: Any, skip_keys: frozenset[str] = frozenset()) -> list[str]:
    """Every string (keys included) in a nested structure, minus skipped keys."""
    out: list[str] = []
    match node:
        case dict():
            for key, value in node.items():
                if key in skip_keys:
                    continue
                out.append(str(key))
                out.extend(_strings(value, skip_keys))
        case list():
            for item in node:
                out.extend(_strings(item, skip_keys))
        case str():
            out.append(node)
        case _:
            pass
    return out


def _assert_clean(label: str, text: str) -> None:
    hits = find_hits(text)
    assert not hits, f"Commercial host(s) in {label}: {sorted(set(hits))}"


def _profile() -> dict[str, Any]:
    return yaml.safe_load(PROFILE.read_text(encoding="utf-8"))


# --- corpus self-tests ---------------------------------------------------------------------


def test_corpus_is_large_enough_and_unique() -> None:
    corpus = load_corpus()
    assert len(corpus) >= 40
    assert len(set(corpus)) == len(corpus)


@pytest.mark.parametrize("pattern", load_corpus())
def test_corpus_catches_planted_commercial_host(pattern: str) -> None:
    host = concrete_host(pattern)
    for text in (host, f"https://{host}/path", f"endpoint: {host.upper()}:443", f"a={host},b=c"):
        assert any(p == pattern for p, _ in find_hits(text)), f"{pattern} missed in {text!r}"


@pytest.mark.parametrize(
    "text",
    [
        "documents.azure.us",
        "nsprobe.documents.azure.us",
        "management.usgovcloudapi.net",
        "login.microsoftonline.us",
        "xmanagement.azure.com.example",
        "notlogin.windows.net.attacker",
        "10.40.1.0/24",
    ],
)
def test_corpus_does_not_flag_government_or_glued_hosts(text: str) -> None:
    # Glued strings such as "xmanagement.azure.com" must not match; "notlogin.windows.net" likewise.
    assert not find_hits(text)


def test_wildcard_needs_a_label_and_exact_host_stays_whole() -> None:
    wild = dict(compile_corpus())["*.documents.azure.com"]
    assert wild.search("documents.azure.com") is None
    assert wild.search("a.b.documents.azure.com") is not None
    assert wild.search("a.documents.azure.us") is None
    exact = dict(compile_corpus())["management.azure.com"]
    assert exact.search("management.azure.com.") is not None
    assert exact.search("management.azure.us") is None


# --- sovereign profile ---------------------------------------------------------------------


def test_every_gov_host_in_profile_passes_the_corpus() -> None:
    profile = _profile()
    values: list[str] = []
    for section in ("endpoints", "privateDnsZones"):
        values.extend(_strings(profile[section]))
    values.extend(_strings(profile["egressHosts"]))
    values.extend(
        str(a["value"]) for a in profile["audiences"].values() if a.get("value") is not None
    )
    assert values
    _assert_clean("sovereign-profile.yaml", "\n".join(values))


def test_egress_hosts_are_government_suffixed_and_not_denied() -> None:
    hosts: list[str] = _profile()["egressHosts"]
    assert hosts
    for host in hosts:
        bare = host.removeprefix("*.")
        assert GOV_SUFFIX.search(bare), f"egress host {host!r} is not under a Government suffix"
        assert not find_hits(concrete_host(host)), f"egress host {host!r} matches the deny corpus"


def test_gov_suffix_rejects_commercial_hosts() -> None:
    for pattern in load_corpus():
        bare = concrete_host(pattern)
        assert not GOV_SUFFIX.search(bare), f"{bare} wrongly counted as Government"


# --- values-government.yaml ----------------------------------------------------------------


def test_values_government_has_no_commercial_host() -> None:
    values = yaml.safe_load(VALUES_GOV.read_text(encoding="utf-8"))
    scanned = _strings(
        {k: values[k] for k in ("sovereignProfile", "env", "image", "networkPolicy") if k in values}
    )
    _assert_clean("values-government.yaml", "\n".join(scanned))


# --- rendered Helm output ------------------------------------------------------------------


def test_helm_render_has_no_commercial_host() -> None:
    rendered = _helm_render()
    _assert_clean("helm template output", rendered)


def _network_policies() -> list[dict[str, Any]]:
    docs = [d for d in yaml.safe_load_all(_helm_render()) if d]
    return [d for d in docs if d.get("kind") == "NetworkPolicy"]


def test_rendered_default_deny_covers_egress() -> None:
    policies = _network_policies()
    deny = [p for p in policies if p["metadata"]["name"].endswith("-default-deny")]
    assert len(deny) == 1
    spec = deny[0]["spec"]
    assert "Egress" in spec["policyTypes"]
    assert not spec.get("egress"), "default-deny must carry no egress rules"
    assert spec["podSelector"]["matchLabels"], "default-deny must select the release pods"


def test_rendered_egress_cidrs_are_private_rfc1918() -> None:
    policies = _network_policies()
    cidrs: list[str] = []
    for policy in policies:
        for rule in policy["spec"].get("egress") or []:
            for peer in rule.get("to") or []:
                block = peer.get("ipBlock")
                if block is not None:
                    cidrs.append(block["cidr"])
    assert cidrs, "Government values should render at least one ipBlock egress allow"
    rfc1918 = [ipaddress.IPv4Network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")]
    for cidr in cidrs:
        net = ipaddress.IPv4Network(cidr, strict=False)
        assert net.prefixlen > 0, f"{cidr} is an open-to-everything range"
        assert any(net.subnet_of(p) for p in rfc1918), f"{cidr} is not a private RFC1918 range"
        assert not net.is_global, f"{cidr} is a public range"


# --- compiled Bicep parameters -------------------------------------------------------------


def test_bicep_build_params_has_no_commercial_host() -> None:
    exe = shutil.which("az")
    if exe is None:
        pytest.skip("az CLI is not installed; cannot compile the Government Bicep params")
    proc = _run([exe, "bicep", "build-params", "--file", str(BICEPPARAM), "--stdout"])
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    # "$schema" URLs (schema.management.azure.com) are tooling metadata, not deployment targets.
    inner: list[str] = []
    for value in payload.values():
        if isinstance(value, str) and value.lstrip().startswith("{"):
            inner.extend(_strings(json.loads(value), frozenset({"$schema"})))
        else:
            inner.extend(_strings(value, frozenset({"$schema"})))
    assert inner
    _assert_clean("az bicep build-params output", "\n".join(inner))
