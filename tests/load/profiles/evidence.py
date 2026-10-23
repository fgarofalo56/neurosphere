"""Evidence JSON for a load run: tally, threshold evaluation, writer. Plain Python, no locust.

The writer records what was MEASURED beside the provisional target and the pass/fail per
threshold. It never tunes a threshold to the result and never labels one profile's run as
evidence for another.
"""

from __future__ import annotations

import json
import subprocess
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .definitions import PRD_SOURCE, PROFILES, PROVISIONAL_NOTE, RunPlan
from .scenarios import UNATTRIBUTED_DOMAIN

SCHEMA_VERSION = "1.0"
# G12 limits of the emulators, from the PRP-21 context manifest and Microsoft Learn; static facts,
# listed so nobody reads compose numbers as partition or RU capacity.
EMULATOR_LIMITS_DOCUMENTED = (
    "Event Hubs emulator: one namespace, ten hubs, no persistence, SAS only (no Entra); "
    "partition and consumer-group scale cannot be inferred from it.",
    "Cosmos DB vNext emulator: no RU accounting, so no request-unit capacity is measured.",
)


@dataclass
class Tally:
    """Counts accumulated by the load generator. Latency percentiles come from locust itself."""

    requests: int = 0
    events_sent: int = 0
    events_accepted: int = 0
    events_rejected: int = 0
    errors: Counter[str] = field(default_factory=Counter)
    error_events: int = 0
    domain_sent: Counter[str] = field(default_factory=Counter)
    domain_accepted: Counter[str] = field(default_factory=Counter)
    domain_failed: Counter[str] = field(default_factory=Counter)
    scenario_requests: Counter[str] = field(default_factory=Counter)
    scenario_accepted: Counter[str] = field(default_factory=Counter)
    agents: set[str] = field(default_factory=set)
    producers: Counter[str] = field(default_factory=Counter)

    def record(
        self,
        *,
        scenario: str,
        producer_id: str,
        domains: tuple[str, ...],
        agents: tuple[str, ...],
        status: int | None,
        accepted: int,
        rejected_indexes: tuple[int, ...] = (),
        error_type: str | None = None,
    ) -> None:
        """One request. ``status`` None means no HTTP response (connection-level failure)."""
        self.requests += 1
        self.events_sent += len(domains)
        self.scenario_requests[scenario] += 1
        self.producers[producer_id] += 1
        self.agents.update(agents)
        for d in domains:
            self.domain_sent[d] += 1
        if status == 202 and error_type is None:
            rejected = set(rejected_indexes)
            self.events_accepted += accepted
            self.events_rejected += len(rejected)
            self.scenario_accepted[scenario] += accepted
            for i, d in enumerate(domains):
                if i in rejected:
                    self.domain_failed[d] += 1
                else:
                    self.domain_accepted[d] += 1
            if rejected:
                self.errors["events_rejected_by_edge"] += len(rejected)
            return
        self.errors[error_type or f"http_{status}"] += 1
        self.error_events += len(domains)
        for d in domains:
            self.domain_failed[d] += 1


def _ratio(num: float, den: float) -> float | None:
    return round(num / den, 6) if den else None


def evaluate_thresholds(plan: RunPlan, measured: dict[str, Any]) -> list[dict[str, Any]]:
    """Pass/fail per threshold. A value that was not measured fails (never passes by omission)."""
    t = plan.profile.thresholds
    rate = measured.get("achieved_events_per_second")
    err = measured.get("error_ratio")
    p95 = measured.get("latency_ms", {}).get("p95")
    rows = [
        ("achieved_events_per_second", ">=", t.min_achieved_events_per_second, rate),
        ("error_ratio", "<=", t.max_error_ratio, err),
        ("request_latency_p95_ms", "<=", t.max_p95_ms, p95),
    ]
    out: list[dict[str, Any]] = []
    for name, op, limit, value in rows:
        if value is None:
            passed = False
        elif op == ">=":
            passed = value >= limit
        else:
            passed = value <= limit
        out.append(
            {
                "name": name,
                "operator": op,
                "threshold": limit,
                "measured": value,
                "passed": passed,
                "provisional": True,
            }
        )
    return out


def git_sha() -> str:
    try:
        done = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return done.stdout.strip() if done.returncode == 0 and done.stdout.strip() else "unknown"


def build_evidence(
    plan: RunPlan,
    tally: Tally,
    *,
    duration_seconds: float,
    latency_ms: dict[str, float | None],
    per_scenario_latency_ms: dict[str, dict[str, float | None]],
    method: str,
    environment_notes: dict[str, Any] | None = None,
    emulator_observations: list[str] | None = None,
    started_at: datetime | None = None,
) -> dict[str, Any]:
    """The full evidence document for one run."""
    profile = plan.profile
    total = tally.requests
    error_requests = sum(c for k, c in tally.errors.items() if k != "events_rejected_by_edge")
    measured: dict[str, Any] = {
        "duration_seconds": round(duration_seconds, 3),
        "requests": total,
        "events_sent": tally.events_sent,
        "events_accepted": tally.events_accepted,
        "events_rejected_by_edge": tally.events_rejected,
        "events_in_failed_requests": tally.error_events,
        "achieved_events_per_second": (
            round(tally.events_accepted / duration_seconds, 2) if duration_seconds > 0 else None
        ),
        "offered_events_per_second": (
            round(tally.events_sent / duration_seconds, 2) if duration_seconds > 0 else None
        ),
        "achieved_requests_per_second": (
            round(total / duration_seconds, 2) if duration_seconds > 0 else None
        ),
        "error_ratio": _ratio(error_requests, total),
        "error_counts_by_type": dict(sorted(tally.errors.items())),
        "latency_ms": latency_ms,
        "distinct_agents_emitted": len(tally.agents),
    }
    thresholds = evaluate_thresholds(plan, measured)
    when = started_at or datetime.now(UTC)
    return {
        "schema_version": SCHEMA_VERSION,
        "profile": profile.name,
        "evidence_for": profile.name,
        "not_evidence_for": sorted(n for n in PROFILES if n != profile.name),
        "environment_label": plan.environment_label,
        "date": when.strftime("%Y-%m-%d"),
        "started_at": when.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "git_sha": git_sha(),
        "method": method,
        "target_host_name": _hostname(plan.host),
        "profile_definition": {
            "source": PRD_SOURCE,
            "note": PROVISIONAL_NOTE,
            "agents": profile.agents,
            "sustained_events_per_second": profile.sustained_events_per_second,
            "burst_events_per_second": profile.burst_events_per_second,
            "entities": profile.entities,
            "relationships": profile.relationships,
            "subject_to": profile.subject_to,
            "catalog_scale_driven_by_this_suite": False,
        },
        "run_parameters": {
            "users": plan.users,
            "duration_seconds_requested": plan.duration_seconds,
            "batch_size": profile.batch_size,
            "domains": profile.domains,
            "skew_multiple": plan.skew_multiple,
            "hot_domain_weight_over_median": plan.skew_multiple,
            "fan_out_width": profile.fan_out_width,
            "producers": profile.producers,
            "multi_domain_sources": profile.multi_domain_sources,
            "scenario_weights": dict(profile.scenario_weights),
            "overrides_of_profile_defaults": list(plan.overrides),
        },
        "measured": measured,
        "thresholds": thresholds,
        "thresholds_all_passed": all(row["passed"] for row in thresholds),
        "scenarios": {
            name: {
                "requests": tally.scenario_requests[name],
                "events_accepted": tally.scenario_accepted[name],
                "latency_ms": per_scenario_latency_ms.get(name, {}),
            }
            for name in sorted(tally.scenario_requests)
        },
        "domains": _domain_summary(tally),
        "environment_notes": environment_notes or {},
        "emulator_limits": {
            "documented": list(EMULATOR_LIMITS_DOCUMENTED),
            "observed_in_this_run": emulator_observations or [],
        },
        "open": [
            "G07 stays OPEN: this run is bounded feasibility on emulators, not capacity evidence.",
            "Enterprise and stress profiles are operator-run at a sized environment (not run).",
        ]
        if profile.name == "pilot"
        else [
            "Operator-run result for the named environment only; "
            "G07 closes only with approved partition/cost validation."
        ],
    }


def _hostname(host: str) -> str:
    return urlsplit(host).hostname or "unknown"


def _domain_summary(tally: Tally) -> dict[str, Any]:
    # OTLP events carry no domain at the edge; they are reported apart, not as a domain.
    unattributed = tally.domain_sent.get(UNATTRIBUTED_DOMAIN, 0)
    sent = Counter({d: n for d, n in tally.domain_sent.items() if d != UNATTRIBUTED_DOMAIN})
    if not sent:
        return {"count": 0, "unattributed_events": unattributed}
    counts = sorted(sent.values())
    mid = len(counts) // 2
    median = counts[mid] if len(counts) % 2 else (counts[mid - 1] + counts[mid]) / 2
    top = sent.most_common(1)[0]
    return {
        "count": len(sent),
        "unattributed_events": unattributed,
        "median_events_per_domain": median,
        "hottest_domain": top[0],
        "hottest_domain_events": top[1],
        "hottest_over_median": round(top[1] / median, 2) if median else None,
        "hottest_domain_accepted": tally.domain_accepted[top[0]],
        "hottest_domain_failed": tally.domain_failed[top[0]],
        "events_failed_all_other_domains": sum(
            v for k, v in tally.domain_failed.items() if k != top[0]
        ),
        "top_domains": [
            {
                "domain": d,
                "sent": n,
                "accepted": tally.domain_accepted[d],
                "failed": tally.domain_failed[d],
            }
            for d, n in sent.most_common(5)
        ],
    }


def write_evidence(directory: Path, doc: dict[str, Any], *, suffix: str = "") -> Path:
    """Write ``<profile>-<date><suffix>.json`` under ``directory`` (created if absent)."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{doc['profile']}-{doc['date']}{suffix}.json"
    path.write_text(json.dumps(doc, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    return path
