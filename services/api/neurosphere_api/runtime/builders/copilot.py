"""Copilot builder (PRP-29 item 8 fills this body).

PLACEHOLDER (item 1): ``copilot`` reports ``not_built`` (optional, so it does not block
readiness; copilot routes keep answering 503 ``copilot_unconfigured``). Item 8 reads
``NS_COPILOT_MODE`` (default ``disabled`` -> ``ctx.disabled("copilot")``), builds the adapter
through ``resolve_adapters`` with a managed-identity credential (or ``overrides.model_adapter``
in tests) and the ``CosmosConversationStore``, and consumes ``ACTION_SERVICE``.
"""

from __future__ import annotations

from typing import Final

from neurosphere_api.runtime.builders import BuildContext, BuilderSpec

__all__ = ["BUILDER", "COMPONENTS", "build"]

COMPONENTS: Final = ("copilot",)


def build(ctx: BuildContext) -> None:
    for name in COMPONENTS:
        ctx.not_built(name)


BUILDER: Final = BuilderSpec("copilot", COMPONENTS, build)
