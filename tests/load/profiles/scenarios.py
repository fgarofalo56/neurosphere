"""Synthetic producers and request builders for the load scenarios. Plain Python, no locust.

Scenarios (all synthetic, all aimed at the ingest edge ``/v1/ingest/...``):

* ``baseline_skew``  - batches whose events pick a domain from the skewed distribution: one hot
  domain at ``skew_multiple`` times the median domain weight (noisy neighbor).
* ``hot_key``        - every event from one producer/source (one Event Hubs partition key,
  ``customer|source``) and one agent.
* ``fan_out``        - one batch spanning ``fan_out_width`` distinct domains and agents.
* ``multi_domain``   - a permission-heavy producer registered for many sources; each event
  carries a different source and domain, so every event is checked against the larger
  registration (the write-side analogue of a multi-domain user).
* ``otlp_traces``    - OTLP/JSON spans on ``/otlp/traces``.

The read side of "permission-heavy multi-domain users" (dashboards, search) is not driven here:
this suite targets the ingest edge only.
"""

from __future__ import annotations

import json
import random
import secrets
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .definitions import Profile, domain_weights

EVENTS_PATH = "/v1/ingest/events"
TRACES_PATH = "/v1/ingest/otlp/traces"
BATCH_CONTENT_TYPE = "application/cloudevents-batch+json"
OTLP_CONTENT_TYPE = "application/json"
CLOUDEVENT_TYPE_TELEMETRY = "com.neurosphere.telemetry.v1"  # test pins it to neurosphere_core

UNATTRIBUTED_DOMAIN = "(unattributed)"

Doc = dict[str, Any]


@dataclass(frozen=True)
class SyntheticProducer:
    producer_id: str
    customer_id: str
    cloud: str
    sources: tuple[str, ...]
    secret: str = field(default_factory=lambda: secrets.token_urlsafe(24), repr=False)

    @property
    def authorization(self) -> str:
        return f"Bearer {self.producer_id}.{self.secret}"

    def credentials(self) -> Doc:
        """What the load generator needs (includes the secret; kept in memory/env only)."""
        return {
            "producer_id": self.producer_id,
            "secret": self.secret,
            "customer_id": self.customer_id,
            "cloud": self.cloud,
            "sources": list(self.sources),
        }

    def registration(self, secret_sha256: str) -> Doc:
        """The edge-side registration (hash only)."""
        return {
            "producer_id": self.producer_id,
            "secret_sha256": secret_sha256,
            "customer_id": self.customer_id,
            "cloud": self.cloud,
            "sources": {s: "application" for s in self.sources},
        }


def make_producers(
    profile: Profile, run_id: str, cloud: str = "commercial"
) -> list[SyntheticProducer]:
    """``profile.producers`` producers; the last one is the permission-heavy multi-source one.

    Secrets are generated per run, never constants.
    """
    customer = f"load-{run_id}"
    out: list[SyntheticProducer] = []
    for i in range(profile.producers):
        multi = i == profile.producers - 1 and profile.producers > 1
        count = profile.multi_domain_sources if multi else 1
        sources = tuple(f"src-{run_id}-{i}-{k}" for k in range(count))
        out.append(SyntheticProducer(f"prod-{run_id}-{i}", customer, cloud, sources))
    return out


def timestamp_z(now: datetime | None = None) -> str:
    return (now or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


@dataclass(frozen=True)
class Request:
    """One HTTP request the load generator will send, plus what it asserts about its events."""

    scenario: str
    path: str
    content_type: str
    body: bytes
    producer: SyntheticProducer
    domains: tuple[str, ...]  # one entry per event, in send order
    agents: tuple[str, ...]

    @property
    def event_count(self) -> int:
        return len(self.domains)


class RequestPlanner:
    """Deterministic (seeded) request builder for one profile and one run."""

    def __init__(
        self,
        profile: Profile,
        producers: Sequence[SyntheticProducer],
        *,
        run_id: str,
        skew_multiple: float,
        seed: int = 0,
    ) -> None:
        if not producers:
            raise ValueError("at least one producer is required")
        self._profile = profile
        self._producers = list(producers)
        self._run = run_id
        self._rng = random.Random(seed)
        self.domain_ids = [f"dom-{i:04d}" for i in range(profile.domains)]
        self._weights = domain_weights(profile.domains, skew_multiple)
        self._counter = 0
        self._agent_cursor = 0
        self.hot_domain = self.domain_ids[0]
        self.hot_agent = f"agent-{run_id}-hot"
        single = [p for p in self._producers if len(p.sources) == 1]
        self._single = single or self._producers
        self._multi = [p for p in self._producers if len(p.sources) > 1] or self._producers[-1:]

    # -- ids -------------------------------------------------------------------------------
    def _next_id(self, prefix: str) -> str:
        self._counter += 1
        return f"{prefix}-{self._run}-{self._counter}-{uuid.uuid4().hex[:8]}"

    def _next_agent(self) -> str:
        agent = f"agent-{self._run}-{self._agent_cursor % self._profile.agents:07d}"
        self._agent_cursor += 1
        return agent

    def _pick_domain(self) -> str:
        return self._rng.choices(self.domain_ids, weights=self._weights, k=1)[0]

    # -- events ----------------------------------------------------------------------------
    def _telemetry(self, producer: SyntheticProducer, source: str, domain: str, agent: str) -> Doc:
        request_id = self._next_id("req")
        data = {
            "schema_version": "1.0.0",
            "event_id": self._next_id("evt"),
            "event_time": timestamp_z(),
            "cloud": producer.cloud,
            "customer_id": producer.customer_id,
            "source_id": source,
            "domain_id": domain,
            "external_agent_id": agent,
            "span_kind": "model_call",
            "environment": "sandbox",
            "outcome": "success",
            "request_id": request_id,
            "provider": "azure_openai",
            "model": "synthetic-model",
            "duration_ms": self._rng.randint(50, 900),
            "token_breakdown": {"input": self._rng.randint(20, 400), "output": 40},
        }
        return {
            "specversion": "1.0",
            "id": data["event_id"],
            "source": "urn:neurosphere:load-profiles",
            "type": CLOUDEVENT_TYPE_TELEMETRY,
            "data": data,
        }

    def _events_request(
        self,
        scenario: str,
        producer: SyntheticProducer,
        picks: Sequence[tuple[str, str, str]],
    ) -> Request:
        """``picks`` is (source, domain, agent) per event."""
        events = [self._telemetry(producer, s, d, a) for s, d, a in picks]
        return Request(
            scenario=scenario,
            path=EVENTS_PATH,
            content_type=BATCH_CONTENT_TYPE,
            body=json.dumps(events).encode("utf-8"),
            producer=producer,
            domains=tuple(d for _, d, _ in picks),
            agents=tuple(a for _, _, a in picks),
        )

    def pick_scenario(self) -> str:
        """Weighted scenario choice from the profile's ``scenario_weights``."""
        names = list(self._profile.scenario_weights)
        weights = [self._profile.scenario_weights[n] for n in names]
        return self._rng.choices(names, weights=weights, k=1)[0]

    def build(self, scenario: str) -> Request:
        n = self._profile.batch_size
        match scenario:
            case "baseline_skew":
                producer = self._rng.choice(self._single)
                source = producer.sources[0]
                picks = [(source, self._pick_domain(), self._next_agent()) for _ in range(n)]
                return self._events_request(scenario, producer, picks)
            case "hot_key":
                producer = self._single[0]
                picks = [(producer.sources[0], self.hot_domain, self.hot_agent)] * n
                return self._events_request(scenario, producer, picks)
            case "fan_out":
                producer = self._rng.choice(self._single)
                width = min(self._profile.fan_out_width, self._profile.domains, n)
                start = self._rng.randrange(self._profile.domains)
                picks = [
                    (
                        producer.sources[0],
                        self.domain_ids[(start + i % width) % self._profile.domains],
                        self._next_agent(),
                    )
                    for i in range(n)
                ]
                return self._events_request(scenario, producer, picks)
            case "multi_domain":
                producer = self._rng.choice(self._multi)
                picks = [
                    (
                        producer.sources[i % len(producer.sources)],
                        self._pick_domain(),
                        self._next_agent(),
                    )
                    for i in range(n)
                ]
                return self._events_request(scenario, producer, picks)
            case "otlp_traces":
                return self._otlp_request(scenario)
            case _:
                raise ValueError(f"unknown scenario {scenario!r}")

    # -- OTLP ------------------------------------------------------------------------------
    def _otlp_request(self, scenario: str) -> Request:
        n = self._profile.batch_size
        producer = self._rng.choice(self._single)
        trace = uuid.uuid4().hex
        base_ns = int(datetime.now(UTC).timestamp() * 1e9)
        domains: list[str] = []
        agents: list[str] = []
        spans: list[Doc] = []
        for i in range(n):
            # The edge's OTLP mapping carries no domain attribute, so these events are unattributed.
            agent = self._next_agent()
            domains.append(UNATTRIBUTED_DOMAIN)
            agents.append(agent)
            spans.append(
                {
                    "traceId": trace,
                    "spanId": f"{i + 1:016x}",
                    "parentSpanId": "",
                    "name": "chat synthetic",
                    "status": {"code": 1},
                    "startTimeUnixNano": str(base_ns + i * 1_000_000),
                    "endTimeUnixNano": str(base_ns + i * 1_000_000 + 250_000_000),
                    "attributes": [
                        _attr("gen_ai.operation.name", "chat"),
                        _attr("gen_ai.system", "azure_openai"),
                        _attr("gen_ai.request.model", "synthetic-model"),
                        _attr("gen_ai.usage.input_tokens", 100 + i),
                        _attr("gen_ai.usage.output_tokens", 20),
                        _attr("request_id", self._next_id("req")),
                        _attr("gen_ai.agent.id", agent),
                    ],
                }
            )
        doc = {
            "resourceSpans": [
                {
                    "resource": {"attributes": []},
                    "scopeSpans": [{"scope": {"name": "load"}, "spans": spans}],
                }
            ]
        }
        return Request(
            scenario=scenario,
            path=TRACES_PATH,
            content_type=OTLP_CONTENT_TYPE,
            body=json.dumps(doc).encode("utf-8"),
            producer=producer,
            domains=tuple(domains),
            agents=tuple(agents),
        )


def _attr(key: str, value: Any) -> Doc:
    if isinstance(value, int):
        return {"key": key, "value": {"intValue": str(value)}}
    return {"key": key, "value": {"stringValue": value}}
