"""PRP-32 item 2: the App Service profile extensions keep today's defaults and honour their params.

``az bicep build`` emits ARM with expressions; a tiny evaluator for the scalar subset the profile
uses resolves site properties for a given parameter set. App settings (loops) are asserted on
their expression text. Skipped when ``az`` is not on PATH; the CI bicep job is the backstop.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
BICEP = ROOT / "infra" / "appservice" / "main.bicep"
GOLDEN = Path(__file__).with_name("appservice_default_profile.json")
AZ = shutil.which("az")

pytestmark = pytest.mark.skipif(
    AZ is None, reason="az CLI not on PATH; CI bicep job is the backstop"
)

SUBNET = (
    "/subscriptions/s/resourceGroups/r/providers/Microsoft.Network/virtualNetworks/v/subnets/web"
)
UAMI = (
    "/subscriptions/s/resourceGroups/r/providers/Microsoft.ManagedIdentity/userAssignedIdentities/u"
)
SITE_TYPE = "Microsoft.Web/sites"
# Keys whose ARM expression text legitimately changed (default value evaluates identically).
CHANGED_KEYS = {"acrUseManagedIdentityCreds", "acrUserManagedIdentityID", "appSettings"}
ADDED_KEYS = {"virtualNetworkSubnetId", "vnetRouteAllEnabled", "publicNetworkAccess"}


def _build() -> dict[str, Any]:
    assert AZ is not None
    proc = subprocess.run(
        [AZ, "bicep", "build", "--file", str(BICEP), "--stdout"],
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


@pytest.fixture(scope="module")
def arm() -> dict[str, Any]:
    return _build()


# --- minimal ARM expression evaluator (scalar subset) ---------------------------------------


def _tokens(src: str) -> list[str]:
    return re.findall(r"'(?:[^']|'')*'|[A-Za-z_][A-Za-z0-9_]*|-?\d+|[(),.]", src)


class _Eval:
    def __init__(self, arm: dict[str, Any], params: dict[str, Any]) -> None:
        self.arm = arm
        self.params = {
            k: params.get(k, v.get("defaultValue")) for k, v in arm["parameters"].items()
        }

    def value(self, node: Any) -> Any:
        if isinstance(node, str) and node.startswith("[") and not node.startswith("[["):
            toks = _tokens(node[1:-1])
            result, pos = self._expr(toks, 0)
            assert pos == len(toks), node
            return result
        return node

    def _expr(self, toks: list[str], pos: int) -> tuple[Any, int]:
        tok = toks[pos]
        if tok.startswith("'"):
            return tok[1:-1].replace("''", "'"), pos + 1
        if re.fullmatch(r"-?\d+", tok):
            return int(tok), pos + 1
        assert toks[pos + 1] == "(", tok
        pos += 2
        args: list[Any] = []
        while toks[pos] != ")":
            val, pos = self._expr(toks, pos)
            args.append(val)
            if toks[pos] == ",":
                pos += 1
        return self._call(tok, args), pos + 1

    def _call(self, name: str, a: list[Any]) -> Any:
        if name == "parameters":
            return self.params[a[0]]
        if name == "variables":
            return self.value(self.arm["variables"][a[0]])
        simple = {
            "if": lambda: a[1] if a[0] else a[2],
            "equals": lambda: a[0] == a[1],
            "not": lambda: not a[0],
            "and": lambda: all(a),
            "empty": lambda: not a[0],
            "null": lambda: None,
            "format": lambda: a[0].format(*a[1:]),
            "resourceId": lambda: "/".join(a),
        }
        assert name in simple, f"evaluator does not support {name}"
        return simple[name]()


def _sites(arm: dict[str, Any], params: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Resolved site properties keyed by the site name suffix (api, workers, web)."""
    ev = _Eval(arm, params)
    out: dict[str, dict[str, Any]] = {}
    for res in arm["resources"]:
        if res["type"] != SITE_TYPE:
            continue
        cond = res.get("condition")
        if cond is not None and not ev.value(cond):
            continue
        props = {k: ev.value(v) for k, v in res["properties"].items() if k != "siteConfig"}
        cfg = {
            k: ev.value(v) for k, v in res["properties"]["siteConfig"].items() if k != "appSettings"
        }
        suffix = str(ev.value(res["name"])).rsplit("-", 1)[1]
        out[suffix] = {**props, "siteConfig": cfg, "_arm": res}
    return out


# --- defaults ----------------------------------------------------------------------------------


def test_defaults_keep_the_two_app_profile(arm: dict[str, Any]) -> None:
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    old = {r["type"] + "|" + r["name"]: r for r in golden["resources"]}
    new = {r["type"] + "|" + r["name"]: r for r in arm["resources"] if "web" not in r["name"]}
    assert set(new) == set(old)
    for key, old_res in old.items():
        new_res = new[key]
        for field in ("apiVersion", "kind", "location", "tags", "identity", "sku", "dependsOn"):
            assert new_res.get(field) == old_res.get(field), (key, field)
        old_props, new_props = old_res["properties"], new_res["properties"]
        for k, v in old_props.items():
            if k == "siteConfig":
                continue
            assert new_props[k] == v, (key, k)
        assert set(new_props) - set(old_props) <= ADDED_KEYS
        if "siteConfig" not in old_props:
            continue
        old_cfg, new_cfg = old_props["siteConfig"], new_props["siteConfig"]
        for k, v in old_cfg.items():
            if k not in CHANGED_KEYS:
                assert new_cfg[k] == v, (key, k)
        assert set(new_cfg) == set(old_cfg)


def test_default_values_evaluate_to_todays_site_properties(arm: dict[str, Any]) -> None:
    sites = _sites(arm, {"namePrefix": "ns", "imageRegistry": "r.example", "imageTag": "1"})
    assert set(sites) == {"api", "workers"}
    for site in sites.values():
        cfg = site["siteConfig"]
        assert cfg["acrUseManagedIdentityCreds"] is True
        assert cfg["acrUserManagedIdentityID"] is None
        assert site["virtualNetworkSubnetId"] is None
        assert site["vnetRouteAllEnabled"] is None
        assert site["publicNetworkAccess"] is None  # Enabled leaves the property unset


def test_user_assigned_identity_keeps_acr_identity_and_kv_reference(arm: dict[str, Any]) -> None:
    base = {"namePrefix": "ns", "imageRegistry": "r.example", "imageTag": "1"}
    for site in _sites(arm, {**base, "userAssignedIdentityId": UAMI}).values():
        assert site["keyVaultReferenceIdentity"] == UAMI
        assert site["siteConfig"]["acrUserManagedIdentityID"] == UAMI
    system = _sites(arm, base)
    assert all(s["keyVaultReferenceIdentity"] is None for s in system.values())


# --- variants ----------------------------------------------------------------------------------


def test_anonymous_registry_drops_managed_identity_pull(arm: dict[str, Any]) -> None:
    params = {
        "namePrefix": "ns",
        "imageRegistry": "r.example",
        "imageTag": "1",
        "registryAuth": "anonymous",
        "frontendRepository": "neurosphere/frontend",
        "userAssignedIdentityId": UAMI,
    }
    sites = _sites(arm, params)
    assert set(sites) == {"api", "workers", "web"}
    for site in sites.values():
        cfg = site["siteConfig"]
        assert cfg["acrUseManagedIdentityCreds"] is False
        assert cfg["acrUserManagedIdentityID"] is None
    text = json.dumps(arm["resources"])
    assert "DOCKER|" in text
    assert not re.search(r"(?i)DOCKER_REGISTRY_SERVER_(USERNAME|PASSWORD)", text)


def test_frontend_site_is_hardened_and_on_8080(arm: dict[str, Any]) -> None:
    params = {
        "namePrefix": "ns",
        "imageRegistry": "r.example",
        "imageTag": "1",
        "frontendRepository": "neurosphere/frontend",
    }
    sites = _sites(arm, params)
    assert set(sites) == {"api", "workers", "web"}
    for site in sites.values():
        assert site["httpsOnly"] is True
        assert site["siteConfig"]["minTlsVersion"] == "1.2"
        assert site["siteConfig"]["ftpsState"] == "Disabled"
    web = sites["web"]
    assert web["siteConfig"]["healthCheckPath"] == "/"
    assert web["siteConfig"]["linuxFxVersion"] == "DOCKER|r.example/neurosphere/frontend:1"
    web_settings = json.dumps(web["_arm"]["properties"]["siteConfig"]["appSettings"])
    assert "WEBSITES_PORT', 'value', '8080'" in web_settings
    assert "frontendExtraSettings" in web_settings
    assert "plainSettings" not in web_settings  # backend settings never reach the frontend
    assert set(_sites(arm, {**params, "frontendRepository": ""})) == {"api", "workers"}


def test_subnet_applies_to_every_site(arm: dict[str, Any]) -> None:
    params = {
        "namePrefix": "ns",
        "imageRegistry": "r.example",
        "imageTag": "1",
        "frontendRepository": "neurosphere/frontend",
        "virtualNetworkSubnetId": SUBNET,
        "vnetRouteAllEnabled": True,
    }
    for site in _sites(arm, params).values():
        assert site["virtualNetworkSubnetId"] == SUBNET
        assert site["vnetRouteAllEnabled"] is True
    # route-all stays off when requested off, and is ignored without a subnet
    for site in _sites(arm, {**params, "vnetRouteAllEnabled": False}).values():
        assert site["vnetRouteAllEnabled"] is False
    for site in _sites(arm, {**params, "virtualNetworkSubnetId": ""}).values():
        assert site["virtualNetworkSubnetId"] is None
        assert site["vnetRouteAllEnabled"] is None


def test_public_network_access_follows_each_param(arm: dict[str, Any]) -> None:
    params = {
        "namePrefix": "ns",
        "imageRegistry": "r.example",
        "imageTag": "1",
        "frontendRepository": "neurosphere/frontend",
        "apiPublicNetworkAccess": "Disabled",
        "workersPublicNetworkAccess": "Enabled",
        "frontendPublicNetworkAccess": "Disabled",
    }
    sites = _sites(arm, params)
    assert sites["api"]["publicNetworkAccess"] == "Disabled"
    assert sites["workers"]["publicNetworkAccess"] is None
    assert sites["web"]["publicNetworkAccess"] == "Disabled"


def test_workers_bind_health_on_all_interfaces_and_extras_merge_last(arm: dict[str, Any]) -> None:
    sites = _sites(arm, {"namePrefix": "ns", "imageRegistry": "r.example", "imageTag": "1"})
    workers = json.dumps(sites["workers"]["_arm"]["properties"]["siteConfig"]["appSettings"])
    assert "'NS_WORKER_HEALTH_HOST', 'value', '0.0.0.0'" in workers
    api = json.dumps(sites["api"]["_arm"]["properties"]["siteConfig"]["appSettings"])
    assert "NS_WORKER_HEALTH_HOST" not in api
    for name, extra in (("api", "apiExtraSettings"), ("workers", "workersExtraSettings")):
        text = json.dumps(sites[name]["_arm"]["properties"]["siteConfig"]["appSettings"])
        assert text.index("kvSettings") < text.index(extra)


def test_outputs_expose_site_names_and_hosts(arm: dict[str, Any]) -> None:
    expected = {
        "apiSiteId",
        "apiSiteName",
        "workersSiteName",
        "frontendSiteName",
        "frontendHostName",
        "apiHostName",
        "frontendPrincipalId",
    }
    assert expected <= set(arm["outputs"])
    ev = _Eval(arm, {"namePrefix": "ns"})
    assert ev.value(arm["outputs"]["frontendSiteName"]["value"]) == ""
    assert ev.value(arm["outputs"]["apiSiteName"]["value"]) == "ns-api"
    assert ev.value(arm["outputs"]["workersSiteName"]["value"]) == "ns-workers"
    on = _Eval(arm, {"namePrefix": "ns", "frontendRepository": "x"})
    assert on.value(arm["outputs"]["frontendSiteName"]["value"]) == "ns-web"
    principal = arm["outputs"]["frontendPrincipalId"]["value"]
    assert principal.startswith("[if(") and ", '')]" in principal
