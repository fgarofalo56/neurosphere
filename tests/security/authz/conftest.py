"""Shared fixtures for the ABAC negative suite (PRP-06 item 6).

* ``ro_world``: session-wide, read-only world (no grants); matrix tests only append audit
  records, which every test reads as a before/after diff.
* ``world`` / ``grant_world``: function-scoped worlds for tests that mutate state (clock,
  revocation, policy store) or need scoped grants.
* ``scopes``: every principal's server-derived scope in ``ro_world``.
"""

import pytest
from neurosphere_core.scope import IdentityScope

from .cases import CASES, KINDS, privileged_grants
from .world import ALL_PRINCIPALS, Who, World, build_world


@pytest.fixture(scope="session")
def ro_world() -> World:
    return build_world()


@pytest.fixture(scope="session")
def scopes(ro_world: World) -> dict[Who, IdentityScope]:
    return {who: ro_world[who.customer].scope(who) for who in ALL_PRINCIPALS}


@pytest.fixture
def world() -> World:
    return build_world()


@pytest.fixture
def grant_world() -> World:
    return build_world(grants=privileged_grants())


def pytest_terminal_summary(terminalreporter: pytest.TerminalReporter) -> None:
    counts = {kind: len(CASES[kind]) for kind in KINDS}
    total = sum(counts.values())
    terminalreporter.section("ABAC negative suite: cases per path")
    for kind, n in counts.items():
        terminalreporter.write_line(f"{kind:>7}: {n}")
    terminalreporter.write_line(f"{'total':>7}: {total}")
