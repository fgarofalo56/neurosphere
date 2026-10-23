"""Load profiles (PRP-21 item 1): the PRD section 3 scale numbers as data. Plain Python.

This module must never import locust (gevent monkey-patching would break the asyncio pytest
session); only ``locustfile.py`` does. Every number below is a PROVISIONAL PLANNING TARGET to be
measured, never a guarantee, and a result measured on one profile is never evidence for another:
a green pilot on compose says nothing about 10k or 50k events per second.

Enterprise and stress have no default target. :func:`resolve_run` refuses to build a run for them
without an explicit host, and nothing in CI or in any test starts them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from urllib.parse import urlsplit

PRD_SOURCE = "docs/PRD.md section 3 (scale profiles); PRP-21 item 1"
# Only the pilot may default to a target, and only to the local compose stack.
LOCAL_COMPOSE_HOST = "http://localhost:8000"

# Provisional thresholds. The PRD gives rates but no ingest-latency figure; the 2 s p95 bound is a
# stand-in borrowed from the dashboard planning target (PRD section 3) and is labelled as such.
PROVISIONAL_NOTE = (
    "Provisional planning targets from the PRD, measured not guaranteed. The p95 bound has no "
    "ingest-specific PRD figure; it reuses the 2 s dashboard planning target as a placeholder."
)

SCENARIOS = ("baseline_skew", "hot_key", "fan_out", "multi_domain", "otlp_traces")


@dataclass(frozen=True)
class Thresholds:
    """Pass/fail bounds evaluated against the measured run (provisional)."""

    min_achieved_events_per_second: float
    max_error_ratio: float = 0.01
    max_p95_ms: float = 2000.0


@dataclass(frozen=True)
class Profile:
    name: str
    agents: int
    sustained_events_per_second: float
    thresholds: Thresholds
    burst_events_per_second: float | None = None
    # Catalog scale the PRD attaches to this profile. The ingest suite does not generate it; it is
    # recorded so nobody reads the event numbers as covering the graph numbers.
    entities: int | None = None
    relationships: int | None = None
    subject_to: str | None = None
    requires_explicit_target: bool = True
    default_host: str | None = None
    default_duration_seconds: int = 60
    default_users: int = 100
    batch_size: int = 25
    domains: int = 20
    skew_multiple: float = 50.0
    fan_out_width: int = 25
    producers: int = 4
    multi_domain_sources: int = 8
    scenario_weights: MappingProxyType[str, int] = field(
        default_factory=lambda: MappingProxyType(
            {
                "baseline_skew": 60,
                "hot_key": 10,
                "fan_out": 10,
                "multi_domain": 10,
                "otlp_traces": 10,
            }
        )
    )


PILOT = Profile(
    name="pilot",
    agents=1_000,
    sustained_events_per_second=1_000.0,
    thresholds=Thresholds(min_achieved_events_per_second=1_000.0),
    requires_explicit_target=False,
    default_host=LOCAL_COMPOSE_HOST,
)
ENTERPRISE = Profile(
    name="enterprise",
    agents=100_000,
    sustained_events_per_second=10_000.0,
    thresholds=Thresholds(min_achieved_events_per_second=10_000.0),
    default_duration_seconds=600,
    default_users=400,
    domains=200,
    producers=40,
)
STRESS = Profile(
    name="stress",
    agents=1_000_000,
    entities=1_000_000,
    relationships=10_000_000,
    sustained_events_per_second=50_000.0,
    burst_events_per_second=150_000.0,
    thresholds=Thresholds(min_achieved_events_per_second=50_000.0),
    subject_to="partition/cost validation",
    default_duration_seconds=900,
    default_users=1_500,
    domains=1_000,
    producers=200,
)

PROFILES: MappingProxyType[str, Profile] = MappingProxyType(
    {p.name: p for p in (PILOT, ENTERPRISE, STRESS)}
)


class TargetRequiredError(ValueError):
    """Enterprise and stress refuse to start without an explicit target host."""


@dataclass(frozen=True)
class RunPlan:
    """A profile bound to a concrete target and run parameters."""

    profile: Profile
    host: str
    duration_seconds: int
    users: int
    skew_multiple: float
    environment_label: str
    overrides: tuple[str, ...] = ()

    @property
    def requests_per_second(self) -> float:
        return self.profile.sustained_events_per_second / self.profile.batch_size

    @property
    def per_user_requests_per_second(self) -> float:
        return self.requests_per_second / self.users


def domain_weights(domains: int, skew_multiple: float) -> list[float]:
    """Per-domain weights: domain 0 is hot at ``skew_multiple`` times the median of the rest.

    Non-hot domains share weight 1.0, so the median of all weights is 1.0 whenever there are at
    least three domains and the hot domain's weight is exactly ``skew_multiple`` times it.
    """
    if domains < 3:
        raise ValueError("skew needs at least 3 domains so the median is a non-hot domain")
    if skew_multiple < 1:
        raise ValueError("skew_multiple must be >= 1")
    return [float(skew_multiple)] + [1.0] * (domains - 1)


def _check_host(host: str) -> str:
    parts = urlsplit(host)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError(f"target host must be an absolute http(s) URL, got {host!r}")
    return host


def resolve_run(
    profile_name: str,
    *,
    host: str | None = None,
    duration_seconds: int | None = None,
    users: int | None = None,
    skew_multiple: float | None = None,
    environment_label: str | None = None,
) -> RunPlan:
    """Bind a profile to a target. Enterprise and stress need ``host`` and a named environment."""
    profile = PROFILES.get(profile_name)
    if profile is None:
        raise ValueError(f"unknown profile {profile_name!r}; expected one of {sorted(PROFILES)}")
    target = host or profile.default_host
    if profile.requires_explicit_target:
        if not host:
            raise TargetRequiredError(
                f"profile {profile.name!r} has no default target: pass an explicit host for a "
                "sized environment you name (it is operator-run, never CI)"
            )
        if not environment_label:
            raise TargetRequiredError(
                f"profile {profile.name!r} needs --environment-label naming the sized environment"
            )
    if not target:
        raise TargetRequiredError(f"profile {profile.name!r} has no target host")
    label = environment_label or (
        "compose (emulators), bounded feasibility only - not capacity evidence (G12)"
    )
    overrides = tuple(
        name
        for name, given, default in (
            ("duration_seconds", duration_seconds, profile.default_duration_seconds),
            ("users", users, profile.default_users),
            ("skew_multiple", skew_multiple, profile.skew_multiple),
        )
        if given is not None and given != default
    )
    return RunPlan(
        profile=profile,
        host=_check_host(target),
        duration_seconds=duration_seconds or profile.default_duration_seconds,
        users=users or profile.default_users,
        skew_multiple=skew_multiple if skew_multiple is not None else profile.skew_multiple,
        environment_label=label,
        overrides=overrides,
    )
