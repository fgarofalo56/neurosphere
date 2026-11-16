"""Evidence bundle builder (PRP-56 item 4).

``build_bundle`` reads the five evidence sources for one domain, maps their observations onto one
framework's controls and returns a deterministic ``EvidenceBundle``: the same library, sources and
clock give identical bytes. Summary words derive only from the observations and the support
status; there is no pass, fail, score or percentage and no sentence about the estate being
compliant. Stateless: nothing is stored.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from neurosphere_contracts.compliance.v1.evidence_bundle import EvidenceBundle
from neurosphere_contracts.compliance.v1.evidence_observation import EvidenceObservation

from neurosphere_core.compliance.models import (
    EVIDENCE_SOURCE_IDS,
    ControlLibrary,
    MappedControl,
    SummaryWord,
)
from neurosphere_core.compliance.sources.base import (
    DEFAULT_CAP,
    EvidenceSource,
    SourceRequest,
    format_utc,
)
from neurosphere_core.errors import NotFoundError
from neurosphere_core.scope import IdentityScope

__all__ = [
    "DEFAULT_WINDOW_DAYS",
    "build_bundle",
    "canonical_bytes",
    "compute_digest",
    "summarize_control",
]

DEFAULT_WINDOW_DAYS = 30
_MAX_WINDOW_DAYS = 365


def _canonical(document: Mapping[str, Any]) -> bytes:
    return json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def compute_digest(bundle: EvidenceBundle) -> str:
    """sha256 over the canonical JSON of the bundle without its ``digest`` member."""
    document = bundle.model_dump(mode="json")
    document.pop("digest", None)
    return "sha256:" + hashlib.sha256(_canonical(document)).hexdigest()


def canonical_bytes(bundle: EvidenceBundle) -> bytes:
    """The bundle's canonical JSON (the bytes the export and the golden test pin)."""
    return _canonical(bundle.model_dump(mode="json"))


def _has_evidence(observation: EvidenceObservation) -> bool:
    if observation.status not in ("observed", "partial"):
        return False
    records = next((m.value for m in observation.measures if m.name == "records"), None)
    return records is not None and records > 0


def summarize_control(
    mapped: MappedControl, observations: Mapping[str, EvidenceObservation]
) -> SummaryWord:
    """Summary word for one control. Derived only from support status and observations."""
    if mapped.mapping.support_status.root == "customer":
        return "customer_responsibility"
    wanted = [s.root for s in mapped.mapping.evidence_sources.root]
    if not wanted:
        return "no_evidence"
    found = [observations[s] for s in wanted if s in observations]
    with_evidence = [o for o in found if _has_evidence(o)]
    if not with_evidence:
        return "no_evidence"
    complete = len(with_evidence) == len(wanted) and all(
        o.status == "observed" and not o.truncated for o in with_evidence
    )
    return "evidence_present" if complete else "evidence_partial"


def _window(now: datetime, window_days: int) -> tuple[datetime, datetime]:
    end = now.astimezone(UTC).replace(microsecond=0)
    return end - timedelta(days=window_days), end


async def build_bundle(
    library: ControlLibrary,
    framework_id: str,
    domain_id: str,
    scope: IdentityScope,
    sources: Sequence[EvidenceSource],
    *,
    now: datetime,
    window_days: int = DEFAULT_WINDOW_DAYS,
    cap: int = DEFAULT_CAP,
) -> EvidenceBundle:
    """Build the bundle for ``domain_id`` and ``framework_id`` over the last ``window_days``."""
    framework = library.framework(framework_id)
    if framework is None:
        raise NotFoundError("unknown framework", reason="framework_not_found")
    if not 1 <= window_days <= _MAX_WINDOW_DAYS:
        raise ValueError(f"window_days must be 1..{_MAX_WINDOW_DAYS}")
    start, end = _window(now, window_days)
    request = SourceRequest(
        scope=scope, domain_id=domain_id, window_start=start, window_end=end, cap=cap
    )
    needed = {s.root for m in framework.controls for s in m.mapping.evidence_sources.root}
    by_id = {s.source_id: s for s in sources}
    observations: dict[str, EvidenceObservation] = {}
    for source_id in EVIDENCE_SOURCE_IDS:
        if source_id not in needed:
            continue
        source = by_id.get(source_id)
        if source is None:
            observations[source_id] = EvidenceObservation.model_validate(
                {
                    "schema_version": "1.0.0",
                    "source_id": source_id,
                    "status": "unavailable",
                    "reason_code": "source_not_wired",
                    "window_start": format_utc(start),
                    "window_end": format_utc(end),
                    "latest_at": None,
                    "truncated": False,
                    "measures": [{"name": "records", "value": None}],
                }
            )
        else:
            observations[source_id] = await source.observe(request)
    controls = [
        {
            "control": m.control.model_dump(mode="json"),
            "support_status": m.mapping.support_status.root,
            "evidence_sources": [s.root for s in m.mapping.evidence_sources.root],
            "summary": summarize_control(m, observations),
        }
        for m in framework.controls
    ]
    draft = {
        "schema_version": "1.0.0",
        "framework_id": framework_id,
        "framework_version": framework.framework.framework_version,
        "library_version": library.version,
        "domain_id": domain_id,
        "generated_at": format_utc(end),
        "window_start": format_utc(start),
        "window_end": format_utc(end),
        "controls": controls,
        "observations": [o.model_dump(mode="json") for o in observations.values()],
        "digest": "sha256:" + "0" * 64,
    }
    bundle = EvidenceBundle.model_validate(draft)
    return bundle.model_copy(update={"digest": compute_digest(bundle)})
