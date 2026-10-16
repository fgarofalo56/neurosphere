"""Government profile: static endpoint assertions and an emulator run with Government-configured
edge and worker.

Scope (PRP-07 C16): configuration and isolation only. Nothing here claims Government parity,
availability, or authorization; the emulators carry no cloud identity, so what is proven is that
the code selects Government endpoints from ``CloudProfile`` and refuses to mix clouds.
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from azure.core.credentials import AccessToken
from neurosphere_core.clients import (
    ClientLifetime,
    blob_account_url,
    create_cosmos_client,
    create_eventhub_producer,
)
from neurosphere_core.cloud import CloudName, CloudProfile, Settings, profile_for
from neurosphere_workers.archive.factory import create_archive_sink
from neurosphere_workers.archive.settings import ArchiveSettings
from neurosphere_workers.quarantine import QuarantineSettings, create_quarantine_container
from pydantic import ValidationError

from .support import (
    Pipeline,
    Producer,
    cloudevent,
    edge_client,
    publish_raw,
    push_cloudevents,
    unique_customer,
)

pytestmark = pytest.mark.integration

COMMERCIAL_MARKERS = (".windows.net", ".azure.com", "microsoftonline.com")
GOV = profile_for(CloudName.GOVERNMENT)


class FakeCredential:
    """An async token credential that never touches the network."""

    async def get_token(self, *scopes: str, **kwargs: Any) -> AccessToken:
        return AccessToken("not-a-real-token", int(time.time()) + 3600)

    async def close(self) -> None:
        return None

    async def __aenter__(self) -> FakeCredential:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


# -- static --------------------------------------------------------------------------------------


def test_government_profile_endpoint_suffixes() -> None:
    assert GOV.cloud is CloudName.GOVERNMENT
    assert GOV.eventhubs_fqdn("ns-gov").endswith(".servicebus.usgovcloudapi.net")
    assert GOV.cosmos_endpoint("acct-gov").endswith(".documents.azure.us/")
    assert blob_account_url(GOV, "stgov") == "https://stgov.blob.core.usgovcloudapi.net/"
    assert GOV.login_host == "login.microsoftonline.us"
    assert GOV.authority_url == "https://login.microsoftonline.us/"
    assert GOV.search_endpoint("srch-gov").endswith(".search.azure.us/")


def test_no_commercial_host_appears_in_the_government_profile() -> None:
    hosts = [
        GOV.login_host,
        GOV.management_host,
        GOV.cosmos_suffix,
        GOV.eventhubs_suffix,
        GOV.search_suffix,
        GOV.eventhubs_fqdn("ns-gov"),
        GOV.cosmos_endpoint("acct-gov"),
        blob_account_url(GOV, "stgov"),
        GOV.search_endpoint("srch-gov"),
        GOV.authority_url,
        GOV.management_url,
    ]
    for host in hosts:
        assert not any(marker in host for marker in COMMERCIAL_MARKERS), host


def test_a_government_profile_cannot_be_built_with_a_commercial_host() -> None:
    with pytest.raises(ValidationError):
        CloudProfile.model_validate({**GOV.model_dump(), "cosmos_suffix": ".documents.azure.com"})


async def test_sdk_clients_are_configured_from_the_government_profile() -> None:
    settings = Settings(env="prod", cloud=CloudName.GOVERNMENT)
    credential = FakeCredential()
    async with ClientLifetime() as lifetime:
        producer = create_eventhub_producer(
            settings,
            lifetime=lifetime,
            eventhub_name="telemetry",
            namespace="ns-gov",
            credential=credential,  # type: ignore[arg-type]
        )
        assert producer._address.hostname == "ns-gov.servicebus.usgovcloudapi.net"  # type: ignore[attr-defined]

        cosmos = create_cosmos_client(
            settings,
            lifetime=lifetime,
            account="acct-gov",
            credential=credential,  # type: ignore[arg-type]
        )
        assert cosmos.client_connection.url_connection == "https://acct-gov.documents.azure.us/"

        quarantine = create_quarantine_container(
            settings,
            lifetime=lifetime,
            quarantine=QuarantineSettings(storage_account="stgov"),
            credential=credential,  # type: ignore[arg-type]
        )
        assert quarantine.url.startswith("https://stgov.blob.core.usgovcloudapi.net/")

        archive = create_archive_sink(
            settings,
            ArchiveSettings(storage_account="stgov", pseudonym_key="not-a-real-key"),  # type: ignore[arg-type]
            lifetime=lifetime,
            credential=credential,  # type: ignore[arg-type]
        )
        assert archive.cloud == "government"
        assert archive._container.url.startswith(  # type: ignore[attr-defined]
            "https://stgov.blob.core.usgovcloudapi.net/"
        )


# -- emulator: edge and worker configured for Government -----------------------------------------


def telemetry_doc(customer: str, source: str, cloud: str, suffix: str) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "event_id": f"evt-{customer}-{suffix}",
        "event_time": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "cloud": cloud,
        "customer_id": customer,
        "source_id": source,
        "domain_id": "dom-iso",
        "span_kind": "model_call",
        "outcome": "success",
        "request_id": f"req-{customer}-{suffix}",
        "provider": "azure_openai",
        "model": "synthetic-model",
        "token_breakdown": {"input": 10, "output": 5},
    }


def raw_hub_message(customer: str, source: str, cloud: str) -> dict[str, Any]:
    data = telemetry_doc(customer, source, cloud, "raw")
    return {
        "wire_version": "1",
        "kind": "telemetry",
        "event_id": data["event_id"],
        "cloud": cloud,
        "customer_id": customer,
        "source_id": source,
        "producer_id": "p-bypass",
        "received_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "request_id": data["request_id"],
        "observation_kind": "application",
        "dropped_field_counts": {},
        "data": data,
    }


async def test_clouds_never_mix_across_edge_hub_and_worker(tmp_path: Path) -> None:
    gov_settings = Settings(env="local", cloud=CloudName.GOVERNMENT)
    com_settings = Settings(env="local", cloud=CloudName.COMMERCIAL)
    gov_customer = unique_customer("gv")
    com_customer = unique_customer("cm")
    gov_producer = Producer("p-gov", gov_customer, "government", {"gov-src": "application"})
    com_producer = Producer("p-com", com_customer, "commercial", {"com-src": "application"})

    async with edge_client(gov_settings, [gov_producer, com_producer], tmp_path) as edge:
        # A Commercial registration is refused at a Government edge: nothing is published.
        refused = await edge.post(
            "/v1/ingest/events",
            headers={**com_producer.headers, "content-type": "application/cloudevents+json"},
            content=json.dumps(
                cloudevent("telemetry", telemetry_doc(com_customer, "com-src", "commercial", "e"))
            ).encode(),
        )
        assert refused.status_code == 403
        assert refused.json()["reason"] == "cloud_mismatch"

        # A Government producer claiming a Commercial event is refused as a claim mismatch.
        claimed = await edge.post(
            "/v1/ingest/events",
            headers={**gov_producer.headers, "content-type": "application/cloudevents+json"},
            content=json.dumps(
                cloudevent("telemetry", telemetry_doc(gov_customer, "gov-src", "commercial", "c"))
            ).encode(),
        )
        assert claimed.status_code == 403
        assert claimed.json()["reason"] == "claim_mismatch"

        # The legitimate Government event goes through.
        ok = await push_cloudevents(
            edge,
            gov_producer,
            [cloudevent("telemetry", telemetry_doc(gov_customer, "gov-src", "government", "ok"))],
        )
        assert ok.accepted == 1

    # A holder of hub credentials publishes a Commercial-tagged message into the same hub.
    await publish_raw(
        [
            (
                json.dumps(raw_hub_message(com_customer, "com-src", "commercial")).encode(),
                f"{com_customer}|com-src",
            )
        ]
    )

    # Government worker: accepts its own cloud, quarantines the Commercial message.
    async with Pipeline.open(gov_settings, uuid.uuid4().hex[:8]) as gov_pipe:
        gov_run = await gov_pipe.consume(expect_processed=2)
        assert gov_run.accepted == 1
        assert dict(gov_run.quarantined) == {"cloud_mismatch": 1}
        gov_archive = await gov_pipe.archive_records(gov_customer)
        assert len(gov_archive) == 1
        assert all(r["message"]["cloud"] == "government" for r in gov_archive.values())
        # Never archived under the Government account: no Commercial customer blob at all.
        assert await gov_pipe.archive_records(com_customer) == {}
        quarantined = await gov_pipe.quarantine_records()
        assert [(r["reason"], r["customer_id"]) for r in quarantined] == [
            ("cloud_mismatch", com_customer)
        ]

    # Commercial worker reads the same hub: the reverse holds.
    async with Pipeline.open(com_settings, uuid.uuid4().hex[:8]) as com_pipe:
        com_run = await com_pipe.consume(expect_processed=2)
        assert com_run.accepted == 1
        assert dict(com_run.quarantined) == {"cloud_mismatch": 1}
        com_archive = await com_pipe.archive_records(com_customer)
        assert len(com_archive) == 1
        assert all(r["message"]["cloud"] == "commercial" for r in com_archive.values())
        assert await com_pipe.archive_records(gov_customer) == {}
        quarantined = await com_pipe.quarantine_records()
        assert [(r["reason"], r["customer_id"]) for r in quarantined] == [
            ("cloud_mismatch", gov_customer)
        ]
