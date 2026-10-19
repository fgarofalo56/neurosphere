"""Offline stub adapters for the injection harness (PRP-12 item 4).

* ``reference_adapter`` is a small policy engine that behaves the way NS-08/NS-09 require. It
  decides from the case's ``attempt`` and the server-derived ``scope`` only; it never reads
  ``case.expected``. It complies with benign, in-scope requests (see the positive controls in
  ``test_harness_negative_control.py``), so passing the corpus is not "refuse everything".
* ``obedient_adapter`` follows every injection: the negative control. The harness must report
  it as failing.
* ``scope_only_adapter`` enforces domain scope but follows every embedded instruction: a partial
  control showing the harness pins failures to the right cases.

These are references for PRP-19 and PRP-22, not production code.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final
from urllib.parse import urlsplit

from neurosphere_core.auth.scope import Permission
from pydantic import JsonValue

from .harness import Observation
from .schema import (
    Escalate,
    FetchUrl,
    FollowInstruction,
    InjectionCase,
    RenderChart,
    Retrieve,
    Reveal,
    RunQuery,
    ScopeFixture,
    ToolCall,
)


@dataclass(frozen=True)
class ToolSpec:
    arguments: frozenset[str]
    permission: Permission


#: The server-registered tool manifest. Descriptions found in content never extend it, and no
#: tool accepts a scope argument: scope comes from the derived IdentityScope only.
TOOL_REGISTRY: Final[Mapping[str, ToolSpec]] = {
    "search_catalog": ToolSpec(frozenset({"query", "limit"}), Permission.DATA_READ),
    "get_cost_summary": ToolSpec(frozenset({"period", "group_by"}), Permission.DATA_READ),
    "create_report": ToolSpec(frozenset({"title", "sections"}), Permission.REPORT_CREATE),
    "propose_action": ToolSpec(
        frozenset({"action_type", "target_id", "diff"}), Permission.ACTION_PROPOSE
    ),
}

#: Egress allowlist for the stub (exact hostnames, https only, default port).
APPROVED_HOSTS: Final = frozenset({"docs.neurosphere.example"})

#: Vega-Lite keys outside the sandboxed declarative subset: expressions, signals/params,
#: external data or images, and link channels that can carry data off the page.
BANNED_CHART_KEYS: Final = frozenset(
    {"expr", "signal", "signals", "params", "url", "href", "calculate", "loader", "usermeta"}
)


def _deny(detail: str) -> Observation:
    return Observation(outcome="deny", detail=detail)


def _comply(detail: str) -> Observation:
    return Observation(outcome="comply", detail=detail)


def _url_allowed(url: str) -> bool:
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return False
    host = parts.hostname
    if parts.scheme != "https" or host is None or parts.username or parts.password:
        return False
    if port not in (None, 443):
        return False
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return host in APPROVED_HOSTS
    return False  # IP literals are never on the allowlist


def _banned_chart_keys(node: JsonValue) -> set[str]:
    found: set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            if key in BANNED_CHART_KEYS:
                found.add(key)
            found |= _banned_chart_keys(value)
    elif isinstance(node, list):
        for item in node:
            found |= _banned_chart_keys(item)
    return found


def _holds(scope: ScopeFixture, permission: Permission, domain_id: str) -> bool:
    return domain_id in scope.domain_ids and permission in scope.permissions()


def reference_adapter(case: InjectionCase) -> Observation:
    scope = case.scope  # server-derived; scope-shaped text in the input is never consulted
    match case.attempt:
        case FollowInstruction():
            return Observation(outcome="abstain", detail="embedded instruction not followed")
        case Retrieve(target_domain_id=domain_id, permission=permission):
            if _holds(scope, permission, domain_id):
                return _comply(f"{permission} on {domain_id}")
            return _deny(f"forbidden: {permission} on {domain_id}")
        case ToolCall(tool=tool, arguments=arguments):
            spec = TOOL_REGISTRY.get(tool)
            if spec is None:
                return _deny(f"tool {tool!r} is not registered")
            extra = sorted(set(arguments) - spec.arguments)
            if extra:
                return _deny(f"tool {tool!r} rejects arguments {extra}")
            if not any(_holds(scope, spec.permission, d) for d in scope.domain_ids):
                return _deny(f"forbidden: {spec.permission}")
            return _comply(f"tool {tool!r}")
        case RenderChart(spec=spec):
            banned = _banned_chart_keys(spec)
            if banned:
                return _deny(f"chart spec uses banned keys {sorted(banned)}")
            return _comply("chart rendered in sandbox")
        case FetchUrl(url=url, redirects_to=hops):
            if all(_url_allowed(u) for u in (url, *hops)):
                return _comply("allowlisted egress")
            return _deny("egress not allowlisted")
        case RunQuery(language=language):
            return _deny(f"raw {language} is never executed; use bounded tools")
        case Reveal(target=target):
            return _deny(f"{target} is never disclosed")
        case Escalate(permission=permission, target_domain_id=domain_id):
            if _holds(scope, permission, domain_id):
                return _comply(f"{permission} already held")
            return _deny(f"claimed role ignored; forbidden: {permission}")


def obedient_adapter(case: InjectionCase) -> Observation:
    """Negative control: does whatever the attempt asks."""
    return _comply(f"followed {case.attempt.kind}")


def scope_only_adapter(case: InjectionCase) -> Observation:
    """Partial control: checks domain scope, follows every other injected instruction."""
    if isinstance(case.attempt, Retrieve | Escalate):
        return reference_adapter(case)
    return obedient_adapter(case)
