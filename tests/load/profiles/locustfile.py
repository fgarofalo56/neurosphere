# pyright: reportMissingImports=false, reportMissingModuleSource=false
"""Locust entry point for the PRP-21 load profiles. NEVER imported by pytest or by CI.

This is the only module that imports locust, which gevent-monkeypatches the process; it runs in
an isolated subprocess (see ``runner.py``). Everything else (profiles, scenarios, evidence) is
plain Python. Run it through ``runner.py``; invoking locust on this file directly works too and
applies the same refusal: enterprise and stress exit at import without ``NS_LOAD_HOST`` and
``NS_LOAD_ENV_LABEL``.

Configuration is by environment variable (set by ``runner.py``):

``NS_LOAD_PROFILE``           pilot | enterprise | stress
``NS_LOAD_HOST``              target base URL (required for enterprise/stress)
``NS_LOAD_ENV_LABEL``         environment label (required for enterprise/stress)
``NS_LOAD_DURATION``          seconds (also pass ``--run-time``)
``NS_LOAD_USERS``             concurrent locust users (also pass ``-u``)
``NS_LOAD_SKEW_MULTIPLE``     hot domain weight as a multiple of the median domain
``NS_LOAD_EVIDENCE_DIR``      where the evidence JSON is written
``NS_LOAD_EVIDENCE_SUFFIX``   optional filename suffix (for example ``-probe``)
``NS_LOAD_CREDENTIALS_JSON``  JSON list of producer credentials (kept in memory; never logged)
``NS_LOAD_METHOD``            method text recorded in the evidence
``NS_LOAD_NOTES_JSON``        JSON object of environment notes recorded in the evidence
``NS_LOAD_SEED``              planner seed (default 0)
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from locust import HttpUser, constant_throughput, events, task

# tests/load on sys.path so the plain modules import as ``profiles.*`` (as they do under pytest).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from profiles.definitions import resolve_run
from profiles.evidence import Tally, build_evidence, write_evidence
from profiles.scenarios import RequestPlanner, SyntheticProducer


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    return value if value else default


def _int_env(name: str) -> int | None:
    raw = _env(name)
    return int(raw) if raw else None


PLAN = resolve_run(
    _env("NS_LOAD_PROFILE", "pilot") or "pilot",
    host=_env("NS_LOAD_HOST"),
    duration_seconds=_int_env("NS_LOAD_DURATION"),
    users=_int_env("NS_LOAD_USERS"),
    skew_multiple=float(_env("NS_LOAD_SKEW_MULTIPLE") or 0) or None,
    environment_label=_env("NS_LOAD_ENV_LABEL"),
)


def _producers() -> list[SyntheticProducer]:
    raw = _env("NS_LOAD_CREDENTIALS_JSON")
    if not raw:
        raise SystemExit("NS_LOAD_CREDENTIALS_JSON is required (producer credentials, in memory)")
    return [
        SyntheticProducer(
            producer_id=item["producer_id"],
            customer_id=item["customer_id"],
            cloud=item["cloud"],
            sources=tuple(item["sources"]),
            secret=item["secret"],
        )
        for item in json.loads(raw)
    ]


TALLY = Tally()
PLANNER = RequestPlanner(
    PLAN.profile,
    _producers(),
    run_id=_env("NS_LOAD_RUN_ID", "run") or "run",
    skew_multiple=PLAN.skew_multiple,
    seed=_int_env("NS_LOAD_SEED") or 0,
)
_STATE: dict[str, float] = {}


class IngestUser(HttpUser):
    host = PLAN.host
    wait_time = constant_throughput(PLAN.per_user_requests_per_second)

    @task
    def post_batch(self) -> None:
        scenario = PLANNER.pick_scenario()
        req = PLANNER.build(scenario)
        headers = {"Authorization": req.producer.authorization, "Content-Type": req.content_type}
        with self.client.post(
            req.path, data=req.body, headers=headers, name=scenario, catch_response=True, timeout=30
        ) as response:
            status = response.status_code or None
            accepted = 0
            rejected: tuple[int, ...] = ()
            error_type: str | None = None
            if status == 202:
                try:
                    body = response.json()
                    accepted = int(body["accepted"])
                    rejected = tuple(int(r["index"]) for r in body.get("rejected", []))
                except (ValueError, KeyError, TypeError):
                    error_type = "bad_202_body"
                    response.failure(error_type)
            else:
                error_type = f"http_{status}" if status else "no_response_connection_or_timeout"
                response.failure(error_type)
            TALLY.record(
                scenario=scenario,
                producer_id=req.producer.producer_id,
                domains=req.domains,
                agents=req.agents,
                status=status,
                accepted=accepted,
                rejected_indexes=rejected,
                error_type=error_type,
            )


@events.test_start.add_listener
def _on_start(environment, **_kwargs) -> None:
    _STATE["t0"] = time.time()
    _STATE["wall"] = time.perf_counter()


@events.quitting.add_listener
def _on_quit(environment, **_kwargs) -> None:
    duration = time.perf_counter() - _STATE.get("wall", time.perf_counter())
    stats = environment.stats

    def pcts(entry) -> dict[str, float | None]:
        if not entry.num_requests:
            return {"p50": None, "p95": None, "p99": None, "max": None}
        return {
            "p50": float(entry.get_response_time_percentile(0.50)),
            "p95": float(entry.get_response_time_percentile(0.95)),
            "p99": float(entry.get_response_time_percentile(0.99)),
            "max": float(entry.max_response_time),
        }

    per_scenario = {name: pcts(entry) for (name, _method), entry in stats.entries.items()}
    notes = json.loads(_env("NS_LOAD_NOTES_JSON", "{}") or "{}")
    doc = build_evidence(
        PLAN,
        TALLY,
        duration_seconds=duration,
        latency_ms=pcts(stats.total),
        per_scenario_latency_ms=per_scenario,
        method=_env("NS_LOAD_METHOD", "locust headless via tests/load/profiles/runner.py") or "",
        environment_notes=notes,
        started_at=datetime.fromtimestamp(_STATE.get("t0", time.time()), UTC),
    )
    path = write_evidence(
        Path(_env("NS_LOAD_EVIDENCE_DIR", "temp/load") or "temp/load"),
        doc,
        suffix=_env("NS_LOAD_EVIDENCE_SUFFIX", "") or "",
    )
    print(f"evidence: {path}")
    environment.process_exit_code = 0  # pass/fail is in the evidence, not the exit code
