"""Compliance control library and evidence bundles (PRP-56).

Metadata-only mapping from what NeuroSphere can observe about a customer's AI estate to the
controls of NIST AI RMF, SR 11-7, HIPAA technical safeguards and OMB M-25-21. It maps and
collects; it never judges. Control ids are stable: other PRPs cite them.
"""

from neurosphere_core.compliance.bundle import (
    DEFAULT_WINDOW_DAYS,
    build_bundle,
    canonical_bytes,
    compute_digest,
    summarize_control,
)
from neurosphere_core.compliance.claims import DISCLAIMER, scan_for_claims
from neurosphere_core.compliance.loader import LibraryLoadError, load_library
from neurosphere_core.compliance.models import (
    EVIDENCE_SOURCE_IDS,
    LIBRARY_VERSION,
    ControlLibrary,
    LibraryFramework,
    MappedControl,
)
from neurosphere_core.compliance.render import render_markdown
from neurosphere_core.compliance.sources.base import EvidenceSource, SourceRequest

__all__ = [
    "DEFAULT_WINDOW_DAYS",
    "DISCLAIMER",
    "EVIDENCE_SOURCE_IDS",
    "LIBRARY_VERSION",
    "ControlLibrary",
    "EvidenceSource",
    "LibraryFramework",
    "LibraryLoadError",
    "MappedControl",
    "SourceRequest",
    "build_bundle",
    "canonical_bytes",
    "compute_digest",
    "load_library",
    "render_markdown",
    "scan_for_claims",
    "summarize_control",
]
