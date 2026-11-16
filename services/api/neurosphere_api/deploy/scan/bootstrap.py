"""Opt-in construction of the scan service from settings (called from ``main.create``).

A stored ``scan`` setting (PRP-45, ``/api/v1/admin/system/settings/scan``) decides ``enabled``
over ``NS_SCAN_ENABLED``; it is read from the same process-cached snapshot as the composition.

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
from neurosphere_core.admin.runtime import StoredSettingsSnapshot, scan_init_args
from neurosphere_core.clients import ClientLifetime
from neurosphere_core.cloud import Settings

from neurosphere_api.admin.system.stored import load_from_settings
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


def _settings(settings: Settings, snapshot: StoredSettingsSnapshot | None) -> ScanSettings:
    """``NS_SCAN_*`` overlaid with the stored ``scan`` setting (PRP-45): ``enabled`` comes from
    the store when a value is stored; the stored interval and scopes are kept for a scheduler."""
    current = load_from_settings(settings) if snapshot is None else snapshot
    stored = current.setting("scan")
    if stored is None:
        return ScanSettings()
    return ScanSettings(**scan_init_args(stored))


def configure_scan_from_settings(
    app: FastAPI,
    settings: Settings,
    scan_settings: ScanSettings | None = None,
    *,
    stored: StoredSettingsSnapshot | None = None,
) -> bool:
    """Wire the scan service when enabled (stored ``scan`` setting, else ``NS_SCAN_ENABLED``).

    ``stored`` is for tests; ``main.create`` passes nothing and the process-cached snapshot
    ``compose_app`` also uses is read (one bounded read per process).
    """
    conf = scan_settings or _settings(settings, stored)
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
