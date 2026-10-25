"""Uvicorn entry point: ``uvicorn --factory neurosphere_api.main:create``.

No application object exists at import time, so importing this module needs no environment.
``create`` builds the bare app, runs the opt-in ingest and scan bootstraps (optional components)
and then composes every store and service from settings (``neurosphere_api.runtime``). Nothing
here accepts test overrides: the only token validator reachable from this entry point is the
Entra JWKS validator.
"""

from __future__ import annotations

from fastapi import FastAPI
from neurosphere_core.cloud import load_settings

from neurosphere_api.app import create_app
from neurosphere_api.deploy.scan.bootstrap import configure_scan_from_settings
from neurosphere_api.ingest.bootstrap import configure_ingest_from_settings
from neurosphere_api.runtime import compose_app


def create() -> FastAPI:
    settings = load_settings()
    app = create_app(settings)
    configure_ingest_from_settings(app, settings)  # opt-in: NS_INGEST_PRODUCERS_FILE
    configure_scan_from_settings(app, settings)  # opt-in: NS_SCAN_ENABLED
    compose_app(app, settings)  # readiness names every component that could not be built
    return app
