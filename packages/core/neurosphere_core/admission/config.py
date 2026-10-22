"""Per-domain quota policy for admission control (PRP-21 item 2).

There is deliberately no way to express "unlimited": every limit is a finite positive rate and
a finite positive burst, both with a hard ceiling, and NaN/infinity are rejected. A missing or
unreadable policy document yields :data:`DEFAULT_LIMIT` plus a logged warning, never an open
door.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

_LOG = logging.getLogger(__name__)

MAX_RATE_PER_SECOND = 1_000_000.0
MAX_BURST = 10_000_000

Rate = Annotated[float, Field(gt=0, le=MAX_RATE_PER_SECOND, allow_inf_nan=False)]
Burst = Annotated[int, Field(ge=1, le=MAX_BURST)]


class QuotaLimit(BaseModel):
    """Token bucket parameters: sustained ``rate_per_second`` with ``burst`` capacity."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    rate_per_second: Rate
    burst: Burst


class QuotaPolicy(BaseModel):
    """Policy document: a default limit plus optional overrides keyed by canonical domain id."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    default: QuotaLimit
    domains: dict[str, QuotaLimit] = Field(default_factory=dict)

    def limit_for(self, domain: str) -> QuotaLimit:
        return self.domains.get(domain, self.default)


# Conservative: 10 requests/second sustained, burst of 20 per domain.
DEFAULT_LIMIT = QuotaLimit(rate_per_second=10.0, burst=20)
DEFAULT_POLICY = QuotaPolicy(default=DEFAULT_LIMIT)


def parse_quota_policy(document: Mapping[str, Any] | None) -> QuotaPolicy:
    """Validate a policy mapping; ``None`` or an invalid document falls back to the default."""
    if document is None:
        _LOG.warning("admission quota config absent; using conservative default limit")
        return DEFAULT_POLICY
    try:
        return QuotaPolicy.model_validate(document)
    except ValidationError as exc:
        _LOG.warning(
            "admission quota config invalid (%d errors); using conservative default limit",
            exc.error_count(),
        )
        return DEFAULT_POLICY


def load_quota_policy(path: Path | str | None) -> QuotaPolicy:
    """Load a JSON or YAML policy file. Absent/unreadable/invalid yields the default + warning."""
    if path is None:
        return parse_quota_policy(None)
    file = Path(path)
    try:
        text = file.read_text(encoding="utf-8")
        loaded: object = json.loads(text) if file.suffix == ".json" else yaml.safe_load(text)
    except (OSError, ValueError, yaml.YAMLError):
        _LOG.warning("admission quota config unreadable at %s; using conservative default", file)
        return DEFAULT_POLICY
    if not isinstance(loaded, dict):
        _LOG.warning("admission quota config is not a mapping; using conservative default")
        return DEFAULT_POLICY
    return parse_quota_policy({str(k): v for k, v in loaded.items()})  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
