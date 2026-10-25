"""Every PRP-29 item 2 and 3 store (and the containers the data builder names) matches the
``neurosphere_core.stores`` registry: container name, partition key paths and TTL."""

from __future__ import annotations

import pytest
from neurosphere_api.runtime.builders import data as data_builder
from neurosphere_core.catalog import review_queue_cosmos as review_queue
from neurosphere_core.evaluation import cosmos_store as evaluation
from neurosphere_core.hitl_cosmos import store as hitl
from neurosphere_core.lifecycle import cosmos as lifecycle
from neurosphere_core.pricing import cosmos_store as pricing
from neurosphere_core.recommendations import cosmos_store as recommendations
from neurosphere_core.stores import container_spec

# (container constant, partition key paths the store module declares)
STORE_CONTAINERS = (
    (evaluation.DEFAULT_RESULTS_CONTAINER, tuple(evaluation.EVALUATION_PARTITION_KEY_PATHS)),
    (evaluation.DEFAULT_RUNS_CONTAINER, tuple(evaluation.EVALUATION_PARTITION_KEY_PATHS)),
    (
        recommendations.DEFAULT_RECOMMENDATION_CONTAINER,
        tuple(recommendations.RECOMMENDATION_PARTITION_KEY_PATHS),
    ),
    (pricing.DEFAULT_PRICE_SNAPSHOT_CONTAINER, (pricing.PRICE_SNAPSHOT_PARTITION_KEY_PATH,)),
    (hitl.DEFAULT_ITEM_CONTAINER, tuple(hitl.ITEM_PARTITION_KEY_PATHS)),
    (hitl.DEFAULT_DECISION_CONTAINER, tuple(hitl.DECISION_PARTITION_KEY_PATHS)),
    (
        review_queue.DEFAULT_REVIEW_QUEUE_CONTAINER,
        tuple(review_queue.REVIEW_QUEUE_PARTITION_KEY_PATHS),
    ),
    (lifecycle.DEFAULT_MAPPING_CONTAINER, (lifecycle.LIFECYCLE_PARTITION_KEY_PATH,)),
    (lifecycle.DEFAULT_HOLD_CONTAINER, (lifecycle.LIFECYCLE_PARTITION_KEY_PATH,)),
    (lifecycle.DEFAULT_REQUEST_CONTAINER, (lifecycle.LIFECYCLE_PARTITION_KEY_PATH,)),
)


@pytest.mark.parametrize(("name", "paths"), STORE_CONTAINERS)
def test_store_constants_equal_the_registry(name: str, paths: tuple[str, ...]) -> None:
    spec = container_spec(name)
    assert spec.name == name
    assert spec.partition_key_paths == paths


def test_every_new_store_module_is_the_registry_owner() -> None:
    owners = {
        evaluation.__name__: (
            evaluation.DEFAULT_RESULTS_CONTAINER,
            evaluation.DEFAULT_RUNS_CONTAINER,
        ),
        recommendations.__name__: (recommendations.DEFAULT_RECOMMENDATION_CONTAINER,),
        pricing.__name__: (pricing.DEFAULT_PRICE_SNAPSHOT_CONTAINER,),
        hitl.__name__: (hitl.DEFAULT_ITEM_CONTAINER, hitl.DEFAULT_DECISION_CONTAINER),
        review_queue.__name__: (review_queue.DEFAULT_REVIEW_QUEUE_CONTAINER,),
        lifecycle.__name__: (
            lifecycle.DEFAULT_MAPPING_CONTAINER,
            lifecycle.DEFAULT_HOLD_CONTAINER,
            lifecycle.DEFAULT_REQUEST_CONTAINER,
        ),
    }
    for module, names in owners.items():
        for name in names:
            assert container_spec(name).owner == module


@pytest.mark.parametrize(
    "name",
    [
        data_builder.CATALOG_CONTAINER,
        data_builder.AGGREGATES_CONTAINER,
        data_builder.AUDIT_CHAIN_CONTAINER,
        data_builder.AUDIT_TAIL_CONTAINER,
    ],
)
def test_data_builder_container_names_are_registered(name: str) -> None:
    assert container_spec(name).name == name
