"""Deterministic OpenAPI export: ``python -m neurosphere_api.openapi_export``.

Writes ``services/api/openapi.json`` (sorted keys, 2-space indent, LF, trailing newline).
The schema is generated from a local-profile app, so it needs no environment.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from neurosphere_core.cloud import Settings

from neurosphere_api.app import create_app

OPENAPI_PATH = Path(__file__).resolve().parents[1] / "openapi.json"


def render_openapi(app: FastAPI) -> str:
    return json.dumps(app.openapi(), indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def default_app() -> FastAPI:
    return create_app(Settings(env="local"))


def main() -> None:
    with OPENAPI_PATH.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(render_openapi(default_app()))


if __name__ == "__main__":
    main()
