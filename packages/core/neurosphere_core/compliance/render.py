"""Markdown rendering of an evidence bundle (PRP-56 item 4).

The Markdown lists the same facts as the JSON: no extra claim, no score. Cell content is escaped
(the bundle holds ids, titles and counts only). Every rendering carries the disclaimer fragment.
"""

from __future__ import annotations

import re

from neurosphere_contracts.compliance.v1.evidence_bundle import EvidenceBundle

from neurosphere_core.compliance.claims import DISCLAIMER

__all__ = ["render_markdown"]

_ESCAPE = re.compile(r"([\\`*\[\]<>|])")


def _cell(value: object) -> str:
    text = " ".join(str(value).split())
    return _ESCAPE.sub(r"\\\1", text)


def _measure(value: int | None) -> str:
    return "unknown" if value is None else str(value)


def render_markdown(bundle: EvidenceBundle) -> str:
    lines = [
        f"# Evidence bundle: {_cell(bundle.framework_id.root)}",
        "",
        f"This bundle maps and collects metadata. It does not determine compliance; {DISCLAIMER}.",
        "",
        f"- Domain: {_cell(bundle.domain_id)}",
        f"- Framework version: {_cell(bundle.framework_version)}",
        f"- Library version: {_cell(bundle.library_version)}",
        f"- Collection window: {bundle.window_start.root} to {bundle.window_end.root}",
        f"- Generated at: {bundle.generated_at.root}",
        f"- Digest: {bundle.digest}",
        "",
        "## Mapped controls",
        "",
        "| Control | Title | Support | Evidence sources | Evidence summary |",
        "|---|---|---|---|---|",
    ]
    for entry in bundle.controls:
        sources = ", ".join(s.root for s in entry.evidence_sources.root) or "none"
        lines.append(
            "| "
            + " | ".join(
                _cell(v)
                for v in (
                    entry.control.control_id,
                    entry.control.title,
                    entry.support_status.root,
                    sources,
                    entry.summary,
                )
            )
            + " |"
        )
    lines += ["", "## Observations", ""]
    for obs in bundle.observations:
        reason = obs.reason_code or "none"
        latest = obs.latest_at.root if obs.latest_at is not None else "unknown"
        lines.append(
            f"- {_cell(obs.source_id.root)}: status {obs.status}, reason {_cell(reason)}, "
            f"truncated {str(obs.truncated).lower()}, newest {latest}"
        )
        lines += [f"  - {_cell(m.name)}: {_measure(m.value)}" for m in obs.measures]
    lines += [
        "",
        "## What this bundle does not say",
        "",
        "It is metadata only: counts, timestamps and ids. It holds no prompts, responses or "
        "entity bodies, gives no score and makes no finding. Controls marked "
        "customer_responsibility stay with the customer. See docs/runbooks/compliance-evidence.md.",
        "",
    ]
    return "\n".join(lines)
