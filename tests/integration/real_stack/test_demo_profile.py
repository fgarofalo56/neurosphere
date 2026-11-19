"""PRP-71 item 6: the demo check against a local stack seeded with ``demo-world``.

Needs the demo stack: ``make demo-up`` (profile ``demo-world`` + ``infra/dev/demo-profile.env``),
the API reachable on loopback and the seeded operator's bearer token in a file:

    NS_DEMO_CHECK_TOKEN_FILE=temp/demo-check.token MSYS_NO_PATHCONV=1 uv run pytest -q \
        -m integration tests/integration/real_stack/test_demo_profile.py

(``NS_DEMO_CHECK_API_URL`` overrides the default ``http://127.0.0.1:8000``.)

This suite never starts or stops compose. It skips cleanly (with the reason) when no token file is
configured, the API is not reachable, or the stack was not seeded with ``demo-world`` (the default
real-stack job seeds the ``small`` profile, so it skips there). The token is never printed.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any, Final

import pytest

pytestmark = pytest.mark.integration

SCRIPT: Final = Path(__file__).resolve().parents[3] / "scripts" / "sandbox" / "sbx_demo_check.py"
#: A catalog agent only the curated demo world has.
DEMO_MARKER_AGENT: Final = "payment-approval-assistant"


def _load() -> ModuleType:
    if str(SCRIPT.parent) not in sys.path:
        sys.path.insert(0, str(SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("sbx_demo_check_integration", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def demo() -> ModuleType:
    return _load()


@pytest.fixture(scope="module")
def client(demo: ModuleType) -> Iterator[Any]:
    environ = dict(os.environ)
    if not (environ.get("NS_DEMO_CHECK_TOKEN_FILE") or environ.get("NS_STAND_IN_TOKEN_FILE")):
        pytest.skip("no operator token file: set NS_DEMO_CHECK_TOKEN_FILE (see the module doc)")
    try:
        base = demo.guard_environment(
            environ.get("NS_DEMO_CHECK_API_URL") or demo.DEFAULT_BASE_URL, environ
        )
        token = demo.read_token(None, environ)
    except demo.GuardError as exc:
        pytest.skip(str(exc))
    http = demo.HttpClient(base, token)
    try:
        reply = http.get(demo.DOMAINS_PATH)
    except demo.CheckError as exc:
        http.close()
        pytest.skip(f"the demo stack is not up: {exc}")
    if reply.status != 200:
        http.close()
        pytest.skip(f"the API refused the operator token ({reply.status})")
    entities = http.get(demo.ENTITIES_PATH, (("entity_type", "agent"), ("page_size", "500")))
    items = entities.body.get("items", []) if isinstance(entities.body, dict) else []
    if not any(str(i.get("id", "")).endswith(f":{DEMO_MARKER_AGENT}") for i in items):
        http.close()
        pytest.skip("the stack was not seeded with demo-world (make demo-up)")
    yield http
    http.close()


@pytest.fixture(scope="module")
def report(demo: ModuleType, client: Any) -> Any:
    return demo.run_checks(
        client,
        copilot_mode=os.environ.get("NS_DEMO_COPILOT_MODE") or "disabled",
        wait_seconds=float(os.environ.get("NS_DEMO_CHECK_WAIT_SECONDS", "180")),
    )


def test_the_demo_check_passes(demo: ModuleType, report: Any) -> None:
    assert report.ok, demo.render(report)


def test_the_incident_and_undeclared_agent_expectations_hold(report: Any) -> None:
    by_name = {s.name: s for s in report.sanity}
    for name in ("curated_agents_present", "undeclared_agents_discovered"):
        assert by_name[name].state == "pass", by_name[name]
    # Health may legitimately be "not_checked" while the map has not materialised it; a verdict of
    # fail (downstream agents healthy) is the regression this test exists to catch.
    assert by_name["outage_downstream_health"].state in {"pass", "not_checked"}, by_name[
        "outage_downstream_health"
    ]


def test_copilot_reports_pending_prp_78_while_disabled(report: Any) -> None:
    if (os.environ.get("NS_DEMO_COPILOT_MODE") or "disabled") != "disabled":
        pytest.skip("copilot is switched on in this demo profile")
    copilot = next(f for f in report.features if f.name == "copilot")
    assert copilot.state == "pending_prp_78", copilot
