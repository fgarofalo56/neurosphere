"""Shared types for the G03 graph benchmark: Budget, partition variants, results."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

# Ceilings copied from packages/contracts/schemas/query/v1/budget.schema.json.
_CEILINGS = {
    "timeout_ms": 30000,
    "limit": 1000,
    "max_depth": 5,
    "max_nodes": 5000,
    "max_edges": 20000,
}


@dataclass(frozen=True)
class Budget:
    """Mirror of the Budget contract (query/v1/budget.schema.json).

    ``limit`` doubles as the per-node fan-out cap (rows fetched per expanded node).
    """

    timeout_ms: int = 2000
    limit: int = 25
    max_depth: int = 3
    max_nodes: int | None = 500
    max_edges: int | None = 2000

    def __post_init__(self) -> None:
        for name, ceiling in _CEILINGS.items():
            value = getattr(self, name)
            if value is None and name in ("max_nodes", "max_edges"):
                continue
            if not isinstance(value, int) or isinstance(value, bool):
                raise ValueError(f"Budget.{name} must be an integer")
            minimum = 0 if name == "max_depth" else 1
            if not minimum <= value <= ceiling:
                raise ValueError(
                    f"Budget.{name}={value} outside contract range {minimum}..{ceiling}"
                )

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass(frozen=True)
class PartitionVariant:
    """A partition key shape. Hierarchical variants (more than one path) need new containers."""

    name: str
    paths: tuple[str, ...]

    @property
    def fields(self) -> tuple[str, ...]:
        return tuple(p.lstrip("/") for p in self.paths)

    @property
    def hierarchical(self) -> bool:
        return len(self.paths) > 1

    def values(self, doc: dict[str, Any], prefix: str = "") -> tuple[str, ...]:
        """Partition key values of ``doc`` (``prefix`` selects the dst_* fields of an edge)."""
        return tuple(str(doc[f"{prefix}{f}"]) for f in self.fields)


VARIANTS: dict[str, PartitionVariant] = {
    "flat": PartitionVariant("flat", ("/domain",)),
    "hier2": PartitionVariant("hier2", ("/tenant", "/domain")),
    "hier3": PartitionVariant("hier3", ("/tenant", "/domain", "/shard")),
}


@dataclass
class TraversalResult:
    root: str
    nodes: list[str] = field(default_factory=list)
    edges: list[str] = field(default_factory=list)
    node_depth: dict[str, int] = field(default_factory=dict)
    max_fanout_seen: int = 0
    depth_reached: int = 0
    truncated: set[str] = field(default_factory=set)
    queries: int = 0
    elapsed_ms: float = 0.0
    request_charge: float | None = None  # only set when the store measures it (live)


def percentile(values: list[float], pct: float) -> float:
    """Nearest-rank percentile; 0.0 for an empty list."""
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, -(-len(ordered) * pct // 100))  # ceil
    return ordered[int(rank) - 1]


def latency_stats(values: list[float]) -> dict[str, float | int]:
    if not values:
        return {"n": 0, "min_ms": 0.0, "p50_ms": 0.0, "p95_ms": 0.0, "max_ms": 0.0, "mean_ms": 0.0}
    return {
        "n": len(values),
        "min_ms": round(min(values), 3),
        "p50_ms": round(percentile(values, 50), 3),
        "p95_ms": round(percentile(values, 95), 3),
        "max_ms": round(max(values), 3),
        "mean_ms": round(sum(values) / len(values), 3),
    }
