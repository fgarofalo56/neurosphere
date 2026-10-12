from __future__ import annotations

from neurosphere_api.openapi_export import OPENAPI_PATH, default_app, render_openapi


def test_committed_openapi_matches_generated() -> None:
    committed = OPENAPI_PATH.read_text(encoding="utf-8")
    assert committed == render_openapi(default_app()), (
        "services/api/openapi.json drifted; run: python -m neurosphere_api.openapi_export"
    )


def test_generation_is_deterministic() -> None:
    assert render_openapi(default_app()) == render_openapi(default_app())


def test_drift_is_detected_when_a_route_is_added() -> None:
    committed = OPENAPI_PATH.read_text(encoding="utf-8")
    app = default_app()

    @app.get("/temp-drift-route")
    def temp() -> dict[str, str]:
        return {}

    assert render_openapi(app) != committed
