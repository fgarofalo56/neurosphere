"""Live smoke against an operator-approved Azure OpenAI deployment (not run in CI).

Refuses unless NS_LIVE_APPROVED=1; reported OPEN when it did not run. Uses Entra auth only.
Required: DOCS_ASSISTANT_MODEL_ENDPOINT, DOCS_ASSISTANT_MODEL_DEPLOYMENT and
DOCS_ASSISTANT_SITE_DIR (a built docs site).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from docs_assistant.app import create
from docs_assistant.config import Settings

pytestmark = pytest.mark.live

_REQUIRED = (
    "DOCS_ASSISTANT_MODEL_ENDPOINT",
    "DOCS_ASSISTANT_MODEL_DEPLOYMENT",
    "DOCS_ASSISTANT_SITE_DIR",
)


@pytest.fixture
def live_client() -> TestClient:
    if os.environ.get("NS_LIVE_APPROVED") != "1":
        pytest.skip("OPEN: live run not approved (set NS_LIVE_APPROVED=1 with operator approval)")
    missing = [n for n in _REQUIRED if not os.environ.get(n)]
    if missing:
        pytest.skip(f"OPEN: live run needs {', '.join(missing)}")
    cfg = Settings(
        site_dir=Path(os.environ["DOCS_ASSISTANT_SITE_DIR"]),
        model_endpoint=os.environ["DOCS_ASSISTANT_MODEL_ENDPOINT"],
        model_deployment=os.environ["DOCS_ASSISTANT_MODEL_DEPLOYMENT"],
        model_auth="entra",
    )
    return TestClient(create(cfg))


def test_live_answers_and_abstains(live_client: TestClient) -> None:
    with live_client as client:
        answered = client.post("/ask", json={"question": "Which tool builds the docs site?"})
        assert answered.status_code == 200
        body = answered.json()
        assert body["abstained"] is False
        assert body["answer"]
        assert body["citations"]

        off_topic = client.post(
            "/ask", json={"question": "How do I bake sourdough bread with rye flour?"}
        )
        assert off_topic.status_code == 200
        assert off_topic.json()["abstained"] is True
        assert off_topic.json()["citations"] == []
