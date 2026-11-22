"""Worker-side telemetry agent identity resolution (PRP-137)."""

from neurosphere_workers.agent_identity.reresolve import (
    ReresolveError,
    ReresolveReport,
    reresolve_external_id,
)
from neurosphere_workers.agent_identity.sources import (
    ResolvingRecordSource,
    ResolvingTraceEventSource,
)

__all__ = [
    "ReresolveError",
    "ReresolveReport",
    "ResolvingRecordSource",
    "ResolvingTraceEventSource",
    "reresolve_external_id",
]
