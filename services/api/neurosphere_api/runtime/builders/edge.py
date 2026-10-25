"""Ingest and scan edge status (optional components).

``main.create`` runs the existing opt-in bootstraps (``configure_ingest_from_settings``,
``configure_scan_from_settings``) before ``compose_app``; this builder only reports what they
installed: ``ok`` when the service is on ``app.state``, else ``disabled``. A bootstrap that is
misconfigured still fails startup, as before.
"""

from __future__ import annotations

from typing import Final

from neurosphere_api.runtime.builders import BuildContext, BuilderSpec

__all__ = ["BUILDER", "COMPONENTS", "build"]

COMPONENTS: Final = ("ingest", "scan")
_STATE_KEYS: Final = {"ingest": "ingest_service", "scan": "scan_service"}


def build(ctx: BuildContext) -> None:
    for name in COMPONENTS:
        if getattr(ctx.app.state, _STATE_KEYS[name], None) is not None:
            ctx.ok(name)
        else:
            ctx.disabled(name)


BUILDER: Final = BuilderSpec("edge", COMPONENTS, build)
