"""Engine builder for the PRP-78 item 5 tests: the copilot_api harness plus the new seams."""

from __future__ import annotations

from copilot_api_harness import (  # pyright: ignore[reportMissingImports]
    NOW,
    ScriptedAdapter,
    World,
)
from neurosphere_api.copilot import CopilotEngine, CopilotSettings
from neurosphere_api.copilot.tooling import CopilotExtraPorts, CopilotToolAuditor


def make_tools_engine(
    adapter: ScriptedAdapter,
    world: World,
    *,
    auditor: CopilotToolAuditor | None = None,
    extra_ports: CopilotExtraPorts | None = None,
) -> CopilotEngine:
    return CopilotEngine(
        adapter=adapter,
        ports=world.ports,
        settings=CopilotSettings(),
        clock=lambda: NOW,
        extra_ports=extra_ports,
        tool_auditor=auditor,
    )
