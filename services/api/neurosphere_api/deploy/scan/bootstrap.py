"""Opt-in construction of the scan service from settings (called from ``main.create``).

``NS_SCAN_ENABLED`` unset/false: nothing is configured and ``POST /v1/deploy/scan`` keeps failing
closed with 503 (``scan_not_configured``). True: a keyless credential, an ``httpx`` client and the
``HttpxResourceGraphReader`` (management host from the ``CloudProfile``) are built and attached
with ``configure_scan``. Both the client and the credential are closed at application shutdown.
"""

from __future__ import annotations

import httpx
from azure.core.credentials_async import AsyncTokenCredential
from azure.identity.aio import DefaultAzureCredential
from fastapi import FastAPI
from neurosphere_core.clients import ClientLifetime
from neurosphere_core.cloud import Settings

from neurosphere_api.deploy.scan.graph import HttpxResourceGraphReader
from neurosphere_api.deploy.scan.router import configure_scan
from neurosphere_api.deploy.scan.service import ScanService
from neurosphere_api.deploy.scan.settings import ScanSettings
from neurosphere_api.ingest.bootstrap import (
    _close_on_shutdown,  # pyright: ignore[reportPrivateUsage]
)


class _HttpxCloser:
    """Adapts ``httpx.AsyncClient.aclose`` to the ``ClientLifetime`` ``close`` contract."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def close(self) -> None:
        await self._client.aclose()


def _credential(settings: Settings) -> AsyncTokenCredential:
    """Same policy as ``neurosphere_core.clients.factories._identity`` (private there).

    Authority comes from the cloud profile. No secret is read from settings. Outside
    ``NS_ENV=local`` the environment credential (``AZURE_CLIENT_SECRET`` and friends) is excluded,
    leaving managed / workload identity; local keeps the developer chain.
    """
    return DefaultAzureCredential(
        authority=settings.cloud_profile.login_host,
        exclude_environment_credential=settings.env != "local",
    )


def configure_scan_from_settings(
    app: FastAPI, settings: Settings, scan_settings: ScanSettings | None = None
) -> bool:
    """Wire the scan service when ``NS_SCAN_ENABLED`` is set. True when configured."""
    conf = scan_settings or ScanSettings()
    if not conf.enabled:
        return False
    lifetime = ClientLifetime()
    credential = _credential(settings)
    lifetime.register(credential)  # type: ignore[arg-type]  # AsyncTokenCredential closes via close()
    client = httpx.AsyncClient(timeout=conf.request_timeout_seconds)
    lifetime.register(_HttpxCloser(client))
    reader = HttpxResourceGraphReader(
        credential,
        settings.cloud_profile,
        client=client,
        timeout_seconds=conf.request_timeout_seconds,
        page_size=conf.page_size,
        max_pages=conf.max_pages,
    )
    configure_scan(app, ScanService(reader, conf))
    app.state.scan_lifetime = lifetime
    _close_on_shutdown(app, lifetime)
    return True
