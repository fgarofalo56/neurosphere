"""The evaluation container constants equal the PRP-29 container registry entries."""

from __future__ import annotations

import pytest
from neurosphere_core.evaluation.cosmos_store import (
    DEFAULT_RESULTS_CONTAINER,
    DEFAULT_RUNS_CONTAINER,
    EVALUATION_PARTITION_KEY_PATHS,
)
from neurosphere_core.stores.containers import container_spec


@pytest.mark.parametrize("name", [DEFAULT_RESULTS_CONTAINER, DEFAULT_RUNS_CONTAINER])
def test_evaluation_containers_match_the_registry(name: str) -> None:
    spec = container_spec(name)
    assert spec.partition_key_paths == tuple(EVALUATION_PARTITION_KEY_PATHS)
    assert spec.kind == "MultiHash"
