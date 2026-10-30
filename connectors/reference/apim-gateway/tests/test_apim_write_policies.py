"""Every policy template renders to well-formed XML; named values appear only as {{name}}."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

import pytest
from neurosphere_connector_apim_gateway.policies import (
    COUNTER_KEYS,
    TEMPLATE_NAMES,
    GrantLimits,
    McpEnforcement,
    fragment_payload,
    load_template,
    named_value_ref,
    render_api_policy,
    render_deny_fragment,
    render_grant_fragment,
    render_mcp_enforcement_fragment,
)

_PLACEHOLDER = re.compile(r"\[\[([a-z_]+)\]\]")
_REF = re.compile(r"\{\{([^}]*)\}\}")


def _parse(xml: str) -> ET.Element:
    """Parse our own rendered templates (trusted text, no external entities)."""
    return ET.fromstring(xml)  # noqa: S314


GRANTS = [
    GrantLimits(counter_key="subscription", tokens_per_minute=1000),
    GrantLimits(counter_key="oid", token_quota=50000, token_quota_period="Monthly"),  # noqa: S106
    GrantLimits(
        counter_key="oid",
        tokens_per_minute=10,
        token_quota=1,
        token_quota_period="Hourly",  # noqa: S106
    ),
]
MCPS = [
    McpEnforcement("ns-tenant-id", "ns-mcp-audience", calls=60, renewal_period_seconds=60),
    McpEnforcement(
        "ns-tenant-id",
        "ns-mcp-audience",
        calls=5,
        renewal_period_seconds=10,
        managed_identity_resource="api://mcp-backend",
    ),
]


def _all_rendered() -> list[str]:
    return [
        *(render_grant_fragment(g) for g in GRANTS),
        *(render_mcp_enforcement_fragment(m) for m in MCPS),
        render_deny_fragment(),
        render_api_policy([]),
        render_api_policy(["ns-grant-g1", "ns-mcp-enforce"], backend_id="foundry"),
    ]


def test_template_files_use_only_known_placeholders() -> None:
    known = {
        "api-policy.xml": {"includes", "backend"},
        "deny.xml": set(),
        "grant-product.xml": {"counter_key", "limit_attributes", "metric_namespace"},
        "mcp-enforcement.xml": {
            "tenant_named_value",
            "audience_named_value",
            "managed_identity",
            "calls",
            "renewal_period",
        },
    }
    assert set(TEMPLATE_NAMES) == set(known)
    for name in TEMPLATE_NAMES:
        assert set(_PLACEHOLDER.findall(load_template(name))) == known[name]
    with pytest.raises(ValueError, match="unknown"):
        load_template("../connector.py")


@pytest.mark.parametrize("xml", _all_rendered())
def test_every_rendered_fragment_parses_as_xml(xml: str) -> None:
    root = _parse(xml)
    assert root.tag in ("fragment", "policies")
    assert not _PLACEHOLDER.search(xml)
    # Named values only as {{name}} references with a valid name.
    for ref in _REF.findall(xml):
        assert named_value_ref(ref) == "{{" + ref + "}}"


def test_grant_fragment_attributes_and_metric_dimensions() -> None:
    root = _parse(render_grant_fragment(GRANTS[2]))
    limit = root.find("llm-token-limit")
    assert limit is not None
    assert limit.attrib["tokens-per-minute"] == "10"
    assert limit.attrib["token-quota"] == "1"
    assert limit.attrib["token-quota-period"] == "Hourly"
    assert limit.attrib["estimate-prompt-tokens"] == "false"
    assert limit.attrib["counter-key"] == COUNTER_KEYS["oid"]
    metric = root.find("llm-emit-token-metric")
    assert metric is not None
    dims = metric.findall("dimension")
    assert len(dims) <= 5
    assert [d.attrib["name"] for d in dims] == ["API ID", "Subscription ID", "x-ns-cost-center"]
    cost = dims[2].attrib["value"]
    assert 'GetValueOrDefault("x-ns-cost-center", "N/A")' in cost


def test_grant_with_only_tpm_omits_quota_attributes() -> None:
    limit = _parse(render_grant_fragment(GRANTS[0])).find("llm-token-limit")
    assert limit is not None
    assert "token-quota" not in limit.attrib and "token-quota-period" not in limit.attrib
    assert limit.attrib["counter-key"] == "@(context.Subscription.Id)"


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"tokens_per_minute": 0},
        {"token_quota": 10},
        {"token_quota": 10, "token_quota_period": "Fortnightly"},
        {"tokens_per_minute": 10, "metric_namespace": 'x" injected="1'},
    ],
)
def test_grant_limits_are_validated(kwargs: dict) -> None:  # type: ignore[type-arg]
    with pytest.raises(ValueError):
        GrantLimits(counter_key="subscription", **kwargs)


def test_mcp_fragment_validates_entra_and_strips_caller_credentials() -> None:
    xml = render_mcp_enforcement_fragment(MCPS[1])
    root = _parse(xml)
    token = root.find("validate-azure-ad-token")
    assert token is not None
    assert token.attrib["tenant-id"] == "{{ns-tenant-id}}"
    audiences = [a.text for a in token.iter("audience")]
    assert audiences == ["{{ns-mcp-audience}}"]
    stripped = {
        h.attrib["name"]
        for h in root.findall("set-header")
        if h.attrib["exists-action"] == "delete"
    }
    assert stripped == {"Authorization", "Ocp-Apim-Subscription-Key", "api-key", "subscription-key"}
    children = [c.tag for c in root]
    # Strip first, then attach the gateway's managed identity, then rate-limit.
    assert children.index("authentication-managed-identity") > max(
        i for i, t in enumerate(children) if t == "set-header"
    )
    mi = root.find("authentication-managed-identity")
    assert mi is not None and mi.attrib["resource"] == "api://mcp-backend"
    rate = root.find("rate-limit-by-key")
    assert rate is not None
    assert (rate.attrib["calls"], rate.attrib["renewal-period"]) == ("5", "10")
    assert '"oid"' in rate.attrib["counter-key"]
    assert "Body" not in xml  # streaming stays unbuffered


def test_mcp_fragment_without_managed_identity() -> None:
    root = _parse(render_mcp_enforcement_fragment(MCPS[0]))
    assert root.find("authentication-managed-identity") is None


@pytest.mark.parametrize(
    "kwargs",
    [
        {"tenant_named_value": "{{x}}"},
        {"audience_named_value": "a b"},
        {"calls": 0},
        {"managed_identity_resource": ""},
    ],
)
def test_mcp_inputs_are_validated(kwargs: dict) -> None:  # type: ignore[type-arg]
    base = {
        "tenant_named_value": "t",
        "audience_named_value": "a",
        "calls": 1,
        "renewal_period_seconds": 1,
    }
    with pytest.raises(ValueError):
        McpEnforcement(**{**base, **kwargs})


def test_deny_fragment_fails_closed() -> None:
    root = _parse(render_deny_fragment())
    status = root.find("return-response/set-status")
    assert status is not None and status.attrib["code"] == "503"


def test_api_policy_includes_fragments_and_backend() -> None:
    root = _parse(render_api_policy(["f1", "f2"], backend_id="b1"))
    inbound = root.find("inbound")
    assert inbound is not None
    assert [c.tag for c in inbound] == [
        "base",
        "include-fragment",
        "include-fragment",
        "set-backend-service",
    ]
    assert [c.attrib.get("fragment-id") for c in inbound.findall("include-fragment")] == [
        "f1",
        "f2",
    ]
    with pytest.raises(ValueError):
        render_api_policy(['f1" /><x y="'])


def test_fragment_payload_is_rawxml() -> None:
    payload = fragment_payload("<fragment />", description="d")
    assert payload == {"format": "rawxml", "value": "<fragment />", "description": "d"}
