"""Generator configuration: scale profiles, bad-event rates, the synthetic price sheet."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal

DEFAULT_EPOCH = "2026-10-01T00:00:00Z"
DEFAULT_CUSTOMER = "synthco"
CATALOG_SOURCE = "sandbox"
SCHEMA_VERSION = "1.0.0"

PRICE_VERSION = "sandbox-prices-2026-10"
PRICE_EFFECTIVE_DATE = "2026-10-01"
CACHED_INPUT_FACTOR = Decimal("0.25")

CLOUDS = ("commercial", "government")
REGIONS = {"commercial": "eastus2", "government": "usgovvirginia"}


@dataclass(frozen=True, slots=True)
class ModelSpec:
    """One synthetic model deployment (prices are USD per 1000 tokens; not real list prices)."""

    slug: str
    provider: str
    model_name: str
    model_version: str
    price_in: Decimal
    price_out: Decimal
    base_latency_ms: int
    ms_per_output_token: float
    modalities: tuple[str, ...] = ("text",)


MODELS: tuple[ModelSpec, ...] = (
    ModelSpec(
        "gpt-large",
        "azure_openai",
        "gpt-4.1",
        "2025-04-14",
        Decimal("0.0020"),
        Decimal("0.0080"),
        700,
        22.0,
    ),
    ModelSpec(
        "gpt-mini",
        "azure_openai",
        "gpt-4.1-mini",
        "2025-04-14",
        Decimal("0.0004"),
        Decimal("0.0016"),
        350,
        9.0,
    ),
    ModelSpec(
        "gpt-nano",
        "azure_openai",
        "gpt-4.1-nano",
        "2025-04-14",
        Decimal("0.0001"),
        Decimal("0.0004"),
        200,
        5.0,
    ),
    ModelSpec(
        "reasoner",
        "azure_openai",
        "o4-mini",
        "2025-04-16",
        Decimal("0.0011"),
        Decimal("0.0044"),
        1500,
        30.0,
    ),
    ModelSpec(
        "embed-large",
        "azure_openai",
        "text-embedding-3-large",
        "1",
        Decimal("0.00013"),
        Decimal("0.0"),
        120,
        0.0,
        ("embedding",),
    ),
    ModelSpec(
        "oss-chat",
        "azure_ai_foundry",
        "sandbox-open-chat-70b",
        "2026-03",
        Decimal("0.0007"),
        Decimal("0.0007"),
        500,
        14.0,
    ),
)

DOMAIN_NAMES = (
    "Customer Support",
    "Engineering",
    "Human Resources",
    "Legal Review",
    "Field Operations",
    "Finance Operations",
    "Research",
    "Facilities",
    "Security Operations",
    "Data Platform",
    "Marketing",
    "Compliance",
    "Learning",
    "Quality",
    "Logistics",
    "Communications",
    "Product",
    "Analytics",
    "Training",
    "Planning",
)
ROLE_WORDS = (
    "Triage",
    "Summarizer",
    "Router",
    "Drafter",
    "Reviewer",
    "Planner",
    "Classifier",
    "Extractor",
    "Advisor",
    "Monitor",
    "Scheduler",
    "Translator",
    "Analyst",
    "Coordinator",
)
SOURCE_KINDS = ("search_index", "vector_store", "database", "file_store", "knowledge_base", "api")
TOOL_KINDS = ("function", "api", "mcp_tool", "search", "code_interpreter")


@dataclass(frozen=True, slots=True)
class BadEventRates:
    """Fractions of the telemetry stream carrying each defect (mutually exclusive per event)."""

    duplicate: float = 0.01
    out_of_order: float = 0.01
    malformed: float = 0.005
    missing_optional: float = 0.02
    late_min_seconds: int = 30
    late_max_seconds: int = 600

    def validate(self) -> None:
        rates = (self.duplicate, self.out_of_order, self.malformed, self.missing_optional)
        if any(r < 0.0 for r in rates) or sum(rates) > 1.0:
            raise ValueError("bad-event rates must be >= 0 and sum to <= 1")
        if not 0 < self.late_min_seconds <= self.late_max_seconds:
            raise ValueError("late_min_seconds must be > 0 and <= late_max_seconds")


@dataclass(frozen=True, slots=True)
class Profile:
    name: str
    domains: int
    agents: int  # total including sub-agents
    days: int
    traces_per_agent_day: float
    subagent_fraction: float = 0.25
    persons: int = 0  # 0 -> derived from agents
    tools_per_domain: int = 4
    sources_per_domain: int = 3
    cost_spikes: int = 1
    latency_regressions: int = 1
    unused_agents: int = 1
    duplicate_pairs: int = 1
    invoiced_fraction: float = 0.1

    def validate(self) -> None:
        if self.domains < 1 or self.agents < 12 or self.days < 3:
            raise ValueError("need domains >= 1, agents >= 12, days >= 3")
        if self.sources_per_domain < 3 or self.tools_per_domain < 2:
            raise ValueError("need sources_per_domain >= 3 and tools_per_domain >= 2")
        if not 0.0 <= self.subagent_fraction <= 0.4:
            raise ValueError("subagent_fraction must be in [0, 0.4]")
        needed = self.cost_spikes + self.latency_regressions + self.unused_agents
        needed += 2 * self.duplicate_pairs
        if needed > (self.agents - int(self.agents * self.subagent_fraction)) // 2:
            raise ValueError("too many anomalies requested for this agent count")


PROFILES: dict[str, Profile] = {
    "tiny": Profile("tiny", domains=3, agents=24, days=4, traces_per_agent_day=3.0),
    "pilot": Profile(
        "pilot",
        domains=20,
        agents=1000,
        days=7,
        traces_per_agent_day=2.0,
        cost_spikes=5,
        latency_regressions=5,
        unused_agents=20,
        duplicate_pairs=10,
    ),
    # `custom` starts from pilot-like defaults; every field is overridable from the CLI.
    "custom": Profile("custom", domains=8, agents=200, days=5, traces_per_agent_day=2.0),
}


def with_overrides(profile: Profile, **overrides: object) -> Profile:
    """Apply non-None CLI overrides; anomaly counts scale for `custom` when agents is changed."""
    clean = {k: v for k, v in overrides.items() if v is not None}
    result = replace(profile, **clean)  # type: ignore[arg-type]
    if profile.name == "custom" and "agents" in clean:
        scaled = max(1, result.agents // 200)
        for key in ("cost_spikes", "latency_regressions", "duplicate_pairs"):
            if key not in clean:
                result = replace(result, **{key: scaled})
        if "unused_agents" not in clean:
            result = replace(result, unused_agents=max(1, result.agents // 50))
    result.validate()
    return result


@dataclass(frozen=True, slots=True)
class GenerateConfig:
    seed: int
    profile: Profile
    cloud: str
    epoch: str = DEFAULT_EPOCH
    customer: str = DEFAULT_CUSTOMER
    rates: BadEventRates = BadEventRates()

    def __post_init__(self) -> None:
        if self.cloud not in CLOUDS:
            raise ValueError(f"cloud must be one of {CLOUDS}")
        self.rates.validate()
        self.profile.validate()
        parse_epoch(self.epoch)


def parse_epoch(epoch: str) -> int:
    """RFC 3339 UTC (Z) start time -> integer milliseconds since the Unix epoch."""
    parsed = datetime.strptime(epoch, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    return int(parsed.timestamp()) * 1000
