"""PRP-19 item 6: first-token latency of the copilot SSE path on the sandbox.

Measures send -> first ``token`` SSE event over real HTTP: the composed FastAPI app (the same
composition root as ``tests/integration/copilot``) is served by uvicorn on an ephemeral loopback
port in a thread and read with an httpx streaming client, so the bytes cross a real socket and
nothing is buffered by a test client.

What is and is not measured. The model is the RECORDED-FIXTURE adapter, so provider latency is
excluded by construction; the tool round trip is the in-memory catalog. The <= 3 s first-token
figure is a PLANNING TARGET for the sandbox (PRP-19 clarification 11), never an SLA, and this
test does not assert it: it prints the target beside the measured value and asserts only a
generous sanity bound that catches a stalled stream. No live-provider number comes from CI.

Evidence is written to ``docs/evidence/G07/copilot/first-token.json`` only when
``NS_WRITE_EVIDENCE=1``; otherwise to the pytest temporary directory, so a CI run never dirties
the tree.
"""

from __future__ import annotations

import json
import os
import platform
import socket
import statistics
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import uvicorn
from action_plane_harness import ALICE  # pyright: ignore[reportMissingImports]
from integration.copilot.support import (  # pyright: ignore[reportMissingImports]
    Wiring,
    cited_answer_adapter,
    compose,
)
from neurosphere_api.copilot import PREFIX as COPILOT_PREFIX
from neurosphere_api.copilot import InMemoryConversationStore
from neurosphere_api.reports import InMemoryReportStore

MESSAGES = 30
WARMUP = 3
TARGET_SECONDS = 3.0
# A stalled stream, not a performance claim: ten times the planning target.
SANITY_BOUND_SECONDS = 30.0
_REPO = Path(__file__).resolve().parents[3]
EVIDENCE = _REPO / "docs" / "evidence" / "G07" / "copilot" / "first-token.json"


class _Server:
    """uvicorn on a loopback socket the test binds itself (port 0 -> no collisions)."""

    def __init__(self, app: Any) -> None:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.bind(("127.0.0.1", 0))
        self.port: int = self._sock.getsockname()[1]
        config = uvicorn.Config(app, log_level="warning", lifespan="off")
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(
            target=self._server.run, kwargs={"sockets": [self._sock]}, daemon=True
        )

    def __enter__(self) -> _Server:
        self._thread.start()
        deadline = time.monotonic() + 15
        while not self._server.started:
            if time.monotonic() > deadline:
                raise RuntimeError("uvicorn did not start")
            time.sleep(0.01)
        return self

    def __exit__(self, *exc: object) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=15)
        self._sock.close()


def _percentile(sorted_values: list[float], fraction: float) -> float:
    """Nearest-rank percentile of an already sorted, non-empty list."""
    rank = max(1, round(fraction * len(sorted_values)))
    return sorted_values[rank - 1]


def _first_token_seconds(client: httpx.Client, wired: Wiring, headers: dict[str, str]) -> float:
    """Create a conversation, send one message and time send -> first ``token`` event."""
    wired.use_model(cited_answer_adapter())
    created = client.post(f"{COPILOT_PREFIX}/conversations", headers=headers)
    assert created.status_code == 201, created.text
    url = f"{COPILOT_PREFIX}/conversations/{created.json()['id']}/messages"
    body = {"text": "What agents do we have?", "context": {}}
    names: list[str] = []
    started = time.perf_counter()
    first: float | None = None
    with client.stream("POST", url, headers=headers, json=body) as response:
        assert response.status_code == 200
        for line in response.iter_lines():
            if not line.startswith("event: "):
                continue
            name = line.removeprefix("event: ")
            names.append(name)
            if name == "token" and first is None:
                first = time.perf_counter() - started
            if name in {"done", "abstain", "denied", "error"}:
                break
    assert first is not None, f"no token event in {names}"
    assert names[0] == "context" and names[-1] == "done", names
    return first


def test_first_token_latency_is_recorded(tmp_path: Path) -> None:
    wired = compose(
        conversation_store=InMemoryConversationStore(), report_store=InMemoryReportStore()
    )
    headers = wired.headers(ALICE)
    samples: list[float] = []
    with _Server(wired.app) as server:
        base = f"http://127.0.0.1:{server.port}"
        with httpx.Client(base_url=base, timeout=30.0) as client:
            for _ in range(WARMUP):
                _first_token_seconds(client, wired, headers)
            for _ in range(MESSAGES):
                samples.append(_first_token_seconds(client, wired, headers))

    ordered = sorted(samples)
    p50 = statistics.median(ordered)
    p95 = _percentile(ordered, 0.95)
    worst = ordered[-1]
    result = {
        "gate": "G07",
        "measurement": "copilot send -> first token SSE event",
        "n": len(samples),
        "warmup_messages_discarded": WARMUP,
        "p50_ms": round(p50 * 1000, 2),
        "p95_ms": round(p95 * 1000, 2),
        "max_ms": round(worst * 1000, 2),
        "planning_target_ms": int(TARGET_SECONDS * 1000),
        "target_is": "planning target on the sandbox, not an SLA; not asserted",
        "within_planning_target": worst <= TARGET_SECONDS,
        "environment": {
            "date": datetime.now(UTC).strftime("%Y-%m-%d"),
            "os": platform.platform(),
            "cpu": platform.processor() or platform.machine(),
            "cpu_count": os.cpu_count(),
            "python": sys.version.split()[0],
            "server": f"uvicorn {uvicorn.__version__} in-process thread, loopback socket",
            "adapter": "recorded fixtures (FixtureAdapter; provider latency excluded)",
            "store": "in-memory conversation store; in-memory catalog tools",
            "provider": "excluded by construction; live provider number is OPEN",
        },
    }
    out = EVIDENCE if os.environ.get("NS_WRITE_EVIDENCE") == "1" else tmp_path / EVIDENCE.name
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    print(
        f"\nfirst-token (n={len(samples)}): p50={result['p50_ms']} ms "
        f"p95={result['p95_ms']} ms max={result['max_ms']} ms "
        f"| planning target <= {int(TARGET_SECONDS * 1000)} ms (not an SLA, not asserted)"
        f"\nevidence: {out}"
    )

    assert len(samples) == MESSAGES
    assert worst < SANITY_BOUND_SECONDS, "stream stalled: far beyond any sandbox expectation"
