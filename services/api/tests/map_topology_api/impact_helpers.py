"""Helpers for the PRP-74 item 3 impact tests: an in-memory twin of the PRP-71 incident.

The incident is a failing service with downstream agents; unrelated agents keep their health.
Importable by bare name through ``conftest.py`` (this directory has no ``__init__.py``).
"""

from typing import Any

from map_api_helpers import (  # pyright: ignore[reportMissingImports]
    FINANCE,
    PREFIX,
    Api,
    agent_doc,
    agent_id,
    make_api,
    make_edge,
    put_points,
    service_doc,
    service_id,
    subject_point,
)
from neurosphere_core.aggregates import subject_series_key

__all__ = ["IncidentTwin", "post_impact", "twin"]

FAILING = 0.9


class IncidentTwin:
    """``svc`` fails; ``a1``, ``a2`` depend on it (depth 1); ``b1`` relies on ``a1`` (depth 2)."""

    def __init__(self, api: Api) -> None:
        self.api = api
        self.service = service_id("svc")
        self.downstream_depth_1 = [agent_id("a1"), agent_id("a2")]
        self.downstream_depth_2 = [agent_id("b1")]
        self.unrelated = agent_id("other")


def twin() -> IncidentTwin:
    api = make_api()
    api.seed(
        service_doc("svc", FINANCE),
        agent_doc("a1", FINANCE),
        agent_doc("a2", FINANCE),
        agent_doc("b1", FINANCE),
        agent_doc("other", FINANCE),
    )
    api.seed_edges(
        make_edge("a1-svc", agent_id("a1"), service_id("svc"), relation="depends_on"),
        make_edge("a2-svc", agent_id("a2"), service_id("svc"), relation="depends_on"),
        make_edge("b1-a1", agent_id("b1"), agent_id("a1")),
    )
    put_points(
        api,
        subject_point(subject_series_key("agent", agent_id("a1")), error_rate=FAILING),
        subject_point(subject_series_key("agent", agent_id("a2")), error_rate=0.0),
        subject_point(subject_series_key("agent", agent_id("other")), error_rate=0.0),
    )
    return IncidentTwin(api)


def post_impact(api: Api, who: str | None, domain: str, node_id: str, **body: Any) -> Any:
    headers = api.h.auth(who) if who else {}
    return api.h.client.post(
        f"{PREFIX}/domains/{domain}/impact",
        headers=headers,
        json={"node_id": node_id, **body},
    )
