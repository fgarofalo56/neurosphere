"""LIVE Commercial gate (PRP-07 C15): real Event Hubs with Entra and real Cosmos.

This module cannot run without ``NS_LIVE_APPROVED=1``. Without it every test is SKIPPED with a
message starting ``OPEN:`` that names the gate, so the gate is reported open rather than green.
It is read-only (describes the hub, lists databases): it creates no cloud resources and publishes
nothing. The target is named by operator-supplied environment variables, never by this file:

* ``NS_LIVE_EVENTHUBS_NAMESPACE``  Event Hubs namespace (Entra / managed identity auth)
* ``NS_LIVE_COSMOS_ACCOUNT``       Cosmos account (Entra / managed identity auth)

Note: ``DefaultAzureCredential`` uses the signed-in identity of whoever runs this. An operator
runs it deliberately against an environment they approved.
"""

from __future__ import annotations

import os

import pytest
from azure.eventhub.aio import EventHubProducerClient
from azure.identity.aio import DefaultAzureCredential
from neurosphere_core.clients import ClientLifetime, create_cosmos_client, create_eventhub_producer
from neurosphere_core.cloud import CloudName, Settings

APPROVED = os.environ.get("NS_LIVE_APPROVED") == "1"
NAMESPACE = os.environ.get("NS_LIVE_EVENTHUBS_NAMESPACE")
COSMOS_ACCOUNT = os.environ.get("NS_LIVE_COSMOS_ACCOUNT")

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not APPROVED,
        reason=(
            "OPEN: gate 'live Commercial run (Event Hubs with Entra, real Cosmos)' did not run; "
            "it needs operator approval: set NS_LIVE_APPROVED=1 (PRP-07 C15)"
        ),
    ),
]


async def test_live_eventhubs_entra_describes_the_telemetry_hub() -> None:
    if not NAMESPACE:
        pytest.skip("OPEN: live Event Hubs gate not configured: set NS_LIVE_EVENTHUBS_NAMESPACE")
    settings = Settings(env="prod", cloud=CloudName.COMMERCIAL)
    async with ClientLifetime() as lifetime:
        producer = create_eventhub_producer(
            settings, lifetime=lifetime, eventhub_name="telemetry", namespace=NAMESPACE
        )
        assert isinstance(producer, EventHubProducerClient)
        properties = await producer.get_eventhub_properties()
        assert properties["eventhub_name"] == "telemetry"
        assert len(properties["partition_ids"]) > 0


async def test_live_cosmos_entra_lists_databases() -> None:
    if not COSMOS_ACCOUNT:
        pytest.skip("OPEN: live Cosmos gate not configured: set NS_LIVE_COSMOS_ACCOUNT")
    settings = Settings(env="prod", cloud=CloudName.COMMERCIAL)
    async with ClientLifetime() as lifetime:
        credential = lifetime.register(
            DefaultAzureCredential(authority=settings.cloud_profile.login_host)
        )
        client = create_cosmos_client(
            settings, lifetime=lifetime, account=COSMOS_ACCOUNT, credential=credential
        )
        names = [db["id"] async for db in client.list_databases()]
        assert isinstance(names, list)
