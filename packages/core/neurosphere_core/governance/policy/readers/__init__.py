"""Bound readers of the policy-engine ports (PRP-104 item 8).

:class:`InteractionFindingReaderAdapter` is the one binding of PRP-105's
``InteractionFindingReader`` port: detection-finding counts from the interaction metadata index,
never content.
"""

from __future__ import annotations

from neurosphere_core.governance.policy.readers.interactions import (
    MAX_INDEX_PAGES_PER_CALL,
    MAX_INTERACTION_IDS_PER_COUNT,
    IndexQueryable,
    InteractionFindingReaderAdapter,
    index_only_source,
)

__all__ = [
    "MAX_INDEX_PAGES_PER_CALL",
    "MAX_INTERACTION_IDS_PER_COUNT",
    "IndexQueryable",
    "InteractionFindingReaderAdapter",
    "index_only_source",
]
