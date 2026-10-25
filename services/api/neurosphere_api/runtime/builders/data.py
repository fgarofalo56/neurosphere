"""Data-plane builder (PRP-29 item 7 fills this body).

PLACEHOLDER (item 1): every component below reports ``not_built``, so a composed app is not
ready until item 7 lands. Item 7 builds the catalog repository, graph and review queue, the
aggregate reader, ledger, federation, evaluation and recommendation stores, the HITL-backed
review router, the replay trace reader, the map pseudonymizer and limits, the audit repository
and realtime, and publishes ``AUDIT_REPOSITORY``, ``HITL_SERVICE``, ``AGGREGATE_READER`` and
``CATALOG_REPOSITORY`` for the planes builder (see ``runtime/builders/__init__.py``).
"""

from __future__ import annotations

from typing import Final

from neurosphere_api.runtime.builders import BuildContext, BuilderSpec

__all__ = ["BUILDER", "COMPONENTS", "build"]

COMPONENTS: Final = (
    "catalog",
    "aggregates",
    "ledger",
    "federation",
    "evaluation",
    "recommendations",
    "review_router",
    "replay",
    "map",
    "audit",
    "realtime",
)


def build(ctx: BuildContext) -> None:
    for name in COMPONENTS:
        ctx.not_built(name)


BUILDER: Final = BuilderSpec("data", COMPONENTS, build)
