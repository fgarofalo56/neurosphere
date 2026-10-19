"""One generated sandbox, one catalog and one default run per session (fixed seed).

The catalog is written once during setup; no test writes to it, and the no-write test proves
the run itself leaves it byte-for-byte unchanged.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from neurosphere_workers.recommendations.duplicates import DuplicateDetector, DuplicateRun

from .support import CREATED_AT, Estate, generate_sandbox, load_estate, make_scope


@pytest.fixture(scope="session")
def sandbox_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("dup-sandbox")
    generate_sandbox(out)
    return out


@pytest.fixture(scope="session")
def estate(sandbox_dir: Path) -> Estate:
    return asyncio.run(load_estate(sandbox_dir))


@pytest.fixture(scope="session")
def default_run(estate: Estate) -> DuplicateRun:
    detector = DuplicateDetector(estate.graph, estate.repo)
    return asyncio.run(
        detector.run(
            scope=make_scope(estate.domain_ids), window=estate.window, created_at=CREATED_AT
        )
    )
