"""Uvicorn entry point: ``uvicorn --factory neurosphere_api.main:create``.

No application object exists at import time, so importing this module needs no environment.
"""

from __future__ import annotations

from fastapi import FastAPI
from neurosphere_core.cloud import load_settings

from neurosphere_api.app import create_app
from neurosphere_api.ingest.bootstrap import configure_ingest_from_settings


def create() -> FastAPI:
    settings = load_settings()
    app = create_app(settings)
    configure_ingest_from_settings(app, settings)  # opt-in: NS_INGEST_PRODUCERS_FILE
    return app
