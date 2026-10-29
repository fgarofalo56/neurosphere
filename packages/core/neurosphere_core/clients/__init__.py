"""Async Azure SDK client factories, error translation and lifetime helpers."""

from neurosphere_core.clients.errors import translate_sdk_error, translating
from neurosphere_core.clients.factories import (
    arm_client,
    assert_host_in_cloud,
    blob_account_url,
    create_checkpoint_store,
    create_cosmos_client,
    create_eventhub_consumer,
    create_eventhub_producer,
    log_analytics_client,
    log_analytics_query_host,
)
from neurosphere_core.clients.lifetime import ClientLifetime

__all__ = [
    "ClientLifetime",
    "arm_client",
    "assert_host_in_cloud",
    "blob_account_url",
    "create_checkpoint_store",
    "create_cosmos_client",
    "create_eventhub_consumer",
    "create_eventhub_producer",
    "log_analytics_client",
    "log_analytics_query_host",
    "translate_sdk_error",
    "translating",
]
