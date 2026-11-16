"""Bundle builder and renderers (PRP-56 item 4)."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest
from neurosphere_core.compliance import (
    DISCLAIMER,
    build_bundle,
    canonical_bytes,
    compute_digest,
    load_library,
    render_markdown,
    scan_for_claims,
)
from neurosphere_core.compliance.sources import (
    AuditChainSource,
    CatalogOwnershipSource,
    CostAttributionSource,
    EvaluationResultsSource,
    HitlDecisionsSource,
)
from neurosphere_core.errors import NotFoundError

from .helpers import (
    DOMAIN,
    NOW,
    FakeCatalog,
    FakeLedger,
    audit_repo_with,
    evaluation_store_with,
    hitl_store_with,
    ledger_entry,
    make_scope,
    owner,
    review_item,
)

GOLDEN = Path(__file__).parent / "golden"


async def _sources(*, catalog: bool = True, audit_records: int = 3):  # type: ignore[no-untyped-def]
    return [
        CatalogOwnershipSource(
            FakeCatalog([owner(1, by="2026-11-01T00:00:00Z", at="2026-10-20T00:00:00Z")])  # type: ignore[arg-type]
            if catalog
            else None
        ),
        AuditChainSource(await audit_repo_with(audit_records)),
        HitlDecisionsSource(await hitl_store_with([review_item(1, decided=True)])),
        EvaluationResultsSource(evaluation_store_with(2)),
        CostAttributionSource(FakeLedger([ledger_entry(DOMAIN, None)])),  # type: ignore[arg-type]
    ]


async def _bundle(framework_id: str = "nist_ai_rmf", **kw):  # type: ignore[no-untyped-def]
    return await build_bundle(
        load_library(), framework_id, DOMAIN, make_scope(), await _sources(**kw), now=NOW
    )


def _summary(bundle, control_id: str) -> str:  # type: ignore[no-untyped-def]
    return next(c.summary for c in bundle.controls if c.control.control_id == control_id)


async def test_bundle_is_deterministic_and_matches_golden() -> None:
    first, second = await _bundle(), await _bundle()
    assert canonical_bytes(first) == canonical_bytes(second)
    golden = GOLDEN / "nist_ai_rmf.bundle.json"
    if os.environ.get("NS_UPDATE_GOLDEN") == "1":
        golden.parent.mkdir(exist_ok=True)
        golden.write_bytes(canonical_bytes(first) + b"\n")
    assert canonical_bytes(first) + b"\n" == golden.read_bytes()


async def test_digest_is_sha256_over_canonical_json_without_digest() -> None:
    bundle = await _bundle()
    document = bundle.model_dump(mode="json")
    digest = document.pop("digest")
    expected = hashlib.sha256(
        json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    assert digest == f"sha256:{expected}" == compute_digest(bundle)


async def test_summaries_derive_from_observations_and_support() -> None:
    bundle = await _bundle()
    assert _summary(bundle, "nist-ai-rmf.govern-2") == "evidence_present"
    assert _summary(bundle, "nist-ai-rmf.govern-3") == "customer_responsibility"
    # map-3 needs cost_attribution (records 1) and evaluation (records 2): both present
    assert _summary(bundle, "nist-ai-rmf.map-3") == "evidence_present"


async def test_partial_and_no_evidence_summaries() -> None:
    sources = await _sources()
    sources[4] = CostAttributionSource(FakeLedger([]))  # type: ignore[arg-type]
    bundle = await build_bundle(
        load_library(), "nist_ai_rmf", DOMAIN, make_scope(), sources, now=NOW
    )
    assert _summary(bundle, "nist-ai-rmf.map-3") == "evidence_partial"
    sources[2] = HitlDecisionsSource(None)
    bundle = await build_bundle(
        load_library(), "nist_ai_rmf", DOMAIN, make_scope(), sources, now=NOW
    )
    assert _summary(bundle, "nist-ai-rmf.manage-1") == "no_evidence"


async def test_missing_store_degrades_to_unavailable_not_failure() -> None:
    bundle = await _bundle(catalog=False)
    obs = next(o for o in bundle.observations if o.source_id.root == "catalog_ownership")
    assert obs.status == "unavailable"
    assert _summary(bundle, "nist-ai-rmf.govern-2") == "no_evidence"


async def test_unwired_source_is_unavailable() -> None:
    bundle = await build_bundle(load_library(), "sr_11_7", DOMAIN, make_scope(), [], now=NOW)
    assert {o.reason_code for o in bundle.observations} == {"source_not_wired"}


async def test_unknown_framework_is_not_found() -> None:
    with pytest.raises(NotFoundError):
        await build_bundle(load_library(), "finra", DOMAIN, make_scope(), [], now=NOW)


async def test_no_pass_fail_score_in_the_bundle_json() -> None:
    text = canonical_bytes(await _bundle()).decode()
    for word in ('"pass', '"fail', "score", "percent", "compliant"):
        assert word not in text


@pytest.mark.parametrize(
    "framework_id", ["nist_ai_rmf", "sr_11_7", "hipaa_technical_safeguards", "omb_m_25_21"]
)
async def test_rendered_markdown_passes_the_claim_scan_and_lists_the_same_facts(
    framework_id: str,
) -> None:
    bundle = await _bundle(framework_id)
    markdown = render_markdown(bundle)
    assert DISCLAIMER in " ".join(markdown.split())
    assert scan_for_claims(markdown) == []
    for entry in bundle.controls:
        assert entry.control.control_id in markdown
        assert entry.summary in markdown
    assert bundle.digest in markdown
    assert (
        canonical_bytes(bundle).decode() and scan_for_claims(canonical_bytes(bundle).decode()) == []
    )


async def test_markdown_escapes_cell_content() -> None:
    bundle = await _bundle()
    hostile = bundle.controls[0].control.model_copy(update={"title": "a|b <script> `x`"})
    patched = bundle.model_copy(
        update={"controls": [bundle.controls[0].model_copy(update={"control": hostile})]}
    )
    row = next(ln for ln in render_markdown(patched).splitlines() if "a\\|b" in ln)
    assert "<script>" not in row and "\\<script\\>" in row
