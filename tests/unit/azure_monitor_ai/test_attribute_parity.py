"""PRP-141 item 5: the connector's copied GenAI attribute tables equal the ingest edge's.

The connector cannot import the API package, so it carries copies of the edge's attribute tuples
and operation table. If the edge changes one, rows read by the connector would map differently
from the same spans pushed through OTLP. This test makes that drift a failure.
"""

from __future__ import annotations

import pytest
from neurosphere_api.ingest import otlp_mapping as edge
from neurosphere_connector_azure_monitor import genai_mapping as connector_mapping
from neurosphere_connector_azure_monitor import queries as connector_queries

TUPLES = [
    "PROVIDER_ATTRS",
    "MODEL_ATTRS",
    "INPUT_TOKEN_ATTRS",
    "OUTPUT_TOKEN_ATTRS",
    "CACHED_TOKEN_ATTRS",
    "REASONING_TOKEN_ATTRS",
    "AGENT_ID_ATTRS",
]


@pytest.mark.parametrize("name", TUPLES)
def test_attribute_tuple_equals_the_edge(name: str) -> None:
    assert getattr(connector_queries, name) == getattr(edge, name)
    assert getattr(connector_queries, name), "an empty table would match vacuously"


def test_operation_attribute_equals_the_edge() -> None:
    assert connector_queries.OPERATION_ATTR == edge.OPERATION_ATTR


def test_operation_table_equals_the_edge() -> None:
    assert connector_mapping._OPERATION_KIND == edge._OPERATION_KIND  # type: ignore[reportPrivateUsage]
    assert connector_mapping._OPERATION_KIND


def test_mapping_module_uses_the_query_constants() -> None:
    """The mapper reads the same objects the queries select (one table, not two)."""
    for name in [*TUPLES, "OPERATION_ATTR"]:
        assert getattr(connector_mapping, name) is getattr(connector_queries, name)
