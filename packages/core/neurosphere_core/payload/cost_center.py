"""Cost-center value hygiene shared by the ingest edge and the workers (PRP-46, #190).

The cost center arrives as the ``nscostcenter`` CloudEvent extension. It is untrusted text, so it
is stripped of control characters and must match the catalog Grant ``cost_center`` pattern. A
value that does not is treated as absent: it is never stored, never rejects the event and is
never logged.
"""

from __future__ import annotations

import re
from typing import Any, Final

# CloudEvents extension attribute carrying the cost center (set by the gateway poller).
COST_CENTER_EXTENSION: Final = "nscostcenter"
# Reserved CostRecord.tags key.
COST_CENTER_TAG: Final = "cost_center"

COST_CENTER_PATTERN: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")
_CONTROL: Final = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_ABSENT: Final = frozenset({"", "n/a"})


def sanitize_cost_center(value: Any) -> str | None:
    """The cost center to store, or ``None`` when the value is absent or invalid."""
    if not isinstance(value, str):
        return None
    cleaned = _CONTROL.sub("", value).strip()
    if cleaned.lower() in _ABSENT:
        return None
    if COST_CENTER_PATTERN.fullmatch(cleaned) is None:
        return None
    return cleaned
