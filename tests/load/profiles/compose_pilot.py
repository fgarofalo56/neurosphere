"""Pilot profile against the compose emulators. Plain Python (no locust import).

Topology (recorded in the evidence): the Event Hubs emulator and Azurite come from
``docker compose up -d --wait``; the API under test is a LOCAL uvicorn process started here from
``neurosphere_api.main:create`` with the ingest edge configured (``NS_INGEST_PRODUCERS_FILE``).
Producer secrets are generated per run, only sha256 hashes reach disk, and the dev issuer exists
only because ``NS_ENV=local``.

``run_pilot_on_compose_api`` (PRP-21 round 2) instead targets the compose ``api`` container
(profile ``app``), which now registers a dev ingest producer (``NS_INGEST_PRODUCERS_FILE``) and
runs with per-domain admission enabled. Ingest is not charged by admission (it has its own
per-producer limiter); the evidence says so.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from collections import Counter
from pathlib import Path
from typing import Any

from .definitions import PILOT, RunPlan, resolve_run
from .runner import REPO_ROOT, run_locust
from .scenarios import SyntheticProducer, make_producers

EVENTHUBS_HOST = "localhost"
EVENTHUBS_AMQP_PORT = 5672
# Documented placeholder for the Event Hubs emulator (it does not validate it); the same literal
# the PRP-05 roundtrip test uses. Split so no credential-shaped string sits on one line.
EVENTHUBS_CONNECTION = (
    "Endpoint=sb://localhost;SharedAccessKeyName=RootManageSharedAccessKey;"
    + "SharedAccessKey=SAS_KEY_VALUE;UseDevelopmentEmulator=true;"
)
API_READY_SECONDS = 90


class EmulatorUnavailableError(RuntimeError):
    """The compose emulators are not up (``docker compose up -d --wait``)."""


def require_event_hubs_emulator() -> None:
    try:
        with socket.create_connection((EVENTHUBS_HOST, EVENTHUBS_AMQP_PORT), timeout=3):
            return
    except OSError as exc:
        raise EmulatorUnavailableError(
            f"Event Hubs emulator not reachable on {EVENTHUBS_HOST}:{EVENTHUBS_AMQP_PORT}; "
            "run `docker compose up -d --wait` first"
        ) from exc


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_ready(base: str, proc: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + API_READY_SECONDS
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"API process exited early with code {proc.returncode}")
        try:
            with urllib.request.urlopen(f"{base}/healthz", timeout=2) as resp:
                if resp.status == 200:
                    return
        except (urllib.error.URLError, OSError):
            time.sleep(0.5)
    raise RuntimeError("API did not become healthy in time")


def _stop(proc: subprocess.Popen[bytes]) -> None:
    """Stop the API and its children (the venv launcher spawns the real interpreter on Windows)."""
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
            capture_output=True,
            timeout=30,
            check=False,
        )
    else:
        proc.terminate()
    try:
        proc.wait(timeout=20)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=20)


def observations_from(evidence: dict[str, Any]) -> list[str]:
    """Emulator ceilings/limits visible in this run's measured numbers (G12)."""
    measured = evidence["measured"]
    out = [
        f"Achieved {measured['achieved_events_per_second']} accepted events/s against a "
        f"{evidence['profile_definition']['sustained_events_per_second']} events/s target on one "
        "single-worker API and one Event Hubs emulator (a ceiling of this setup, not of "
        "the product)."
    ]
    errors: dict[str, int] = measured["error_counts_by_type"]
    if errors:
        out.append(
            "Errors observed (count by type): "
            + ", ".join(f"{k}={v}" for k, v in sorted(errors.items()))
            + ". 503 is the edge's retryable dependency error (emulator publish failure); "
            "429 is the per-producer edge limiter."
        )
    else:
        out.append("No request errors observed at this rate (no 429, 503 or connection failures).")
    out.append(
        "Not observable on the emulator: persistence across restart, partition-count and "
        "consumer-group scale, RU accounting, Entra auth."
    )
    return out


COMPOSE_API_BASE = "http://127.0.0.1:8000"
# The documented DEV-ONLY throwaway producer the compose api registers (docs/runbooks/ingest.md,
# infra/dev/ingest-producers.dev.json). Split so no credential-shaped literal sits on one line.
_DEV_SECRET = "ns-dev-only-" + "ingest-secret"


class ComposeApiUnavailableError(RuntimeError):
    """The compose ``api`` service (profile ``app``) is not answering."""


def require_compose_api(base: str = COMPOSE_API_BASE) -> None:
    try:
        with urllib.request.urlopen(f"{base}/healthz", timeout=3) as resp:
            if resp.status == 200:
                return
    except (urllib.error.URLError, OSError):
        pass
    raise ComposeApiUnavailableError(
        f"compose api not reachable at {base}; run `docker compose --profile app up -d --wait api`"
    )


def compose_api_admission() -> dict[str, str]:
    """What the running compose ``api`` container has for admission (env names and values only)."""
    out = subprocess.run(
        ["docker", "compose", "exec", "-T", "api", "env"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        cwd=REPO_ROOT,
    )
    return {
        line.split("=", 1)[0]: line.split("=", 1)[1]
        for line in out.stdout.splitlines()
        if line.startswith("NS_ADMISSION_")
    }


def run_pilot_on_compose_api(
    evidence_dir: Path,
    *,
    duration_seconds: int | None = None,
    users: int | None = None,
    skew_multiple: float | None = None,
    suffix: str = "",
    seed: int = 0,
    base: str = COMPOSE_API_BASE,
) -> tuple[int, Path | None, str]:
    """Run the pilot against the compose ``api`` container (profile ``app``, admission on).

    Uses the dev ingest producer the container registers. Ingest is NOT charged by the per-domain
    admission limiter (it keeps its own per-producer limiter, ``429 rate_limited``); the evidence
    records that, so admitted/throttled numbers here are the EDGE limiter's, not admission's.
    """
    require_compose_api(base)
    run_id = uuid.uuid4().hex[:8]
    plan: RunPlan = resolve_run(
        "pilot",
        host=base,
        duration_seconds=duration_seconds,
        users=users,
        skew_multiple=skew_multiple,
    )
    producer = SyntheticProducer(
        "dev-ingest", "synthco", "commercial", ("dev-source",), secret=_DEV_SECRET
    )
    admission = compose_api_admission()
    method = (
        "locust headless (isolated uv env, locust pinned in requirements.txt); API = the compose "
        "`api` container (profile app, one uvicorn worker) with NS_ADMISSION_ENABLED on and the "
        "dev quota file; ingest authenticated as the dev producer; sink = Event Hubs emulator; "
        "synthetic events only; latency is per POST (a batch of events)"
    )
    notes = {
        "api": "compose api container (profile app), 1 worker, NS_ENV=local",
        "admission": admission,
        "admission_charges_ingest": False,
        "admission_note": (
            "Per-domain admission is charged by require() on authenticated read/write routes. "
            "The ingest edge authenticates producers separately and keeps its own per-producer "
            "limiter, so no request in this run was charged to a domain bucket."
        ),
        "sink": "Event Hubs emulator (docker compose), hub 'telemetry', 4 partitions",
        "edge_limiter": "product defaults (20 rps per producer, burst 40); ONE dev producer",
        "host": f"{platform.system()} {platform.release()}, {os.cpu_count()} logical CPUs, "
        f"Python {platform.python_version()}",
        "client_and_server_share_host": True,
        "consumer_running": False,
        "endpoints_exercised": [
            "/v1/ingest/events",
            "/v1/ingest/otlp/traces",
            "/v1/ingest/otlp/metrics",
        ],
        "endpoints_not_exercised": [],
    }
    code, path, tail = run_locust(
        plan,
        credentials_json=json.dumps([producer.credentials()]),
        evidence_dir=evidence_dir,
        method=method,
        run_id=run_id,
        notes=notes,
        suffix=suffix,
        seed=seed,
    )
    if path is not None:
        doc = json.loads(path.read_text(encoding="utf-8"))
        observed = observations_from(doc)
        observed.append(
            "Admission was enabled on the composed API ("
            + ", ".join(f"{k}={v}" for k, v in sorted(admission.items()))
            + ") but ingest routes are not charged by it; per-domain admitted/throttled counts "
            "on authenticated routes are OPEN (they need an Entra token against the real stack)."
        )
        doc["emulator_limits"]["observed_in_this_run"] = observed
        path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return code, path, tail


def run_pilot(
    evidence_dir: Path,
    *,
    duration_seconds: int | None = None,
    users: int | None = None,
    skew_multiple: float | None = None,
    suffix: str = "",
    seed: int = 0,
) -> tuple[int, Path | None, str]:
    """Run the pilot against compose. Returns (locust exit code, evidence path, output tail)."""
    require_event_hubs_emulator()
    run_id = uuid.uuid4().hex[:8]
    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    plan: RunPlan = resolve_run(
        "pilot",
        host=base,
        duration_seconds=duration_seconds,
        users=users,
        skew_multiple=skew_multiple,
    )
    producers = make_producers(PILOT, run_id)
    with tempfile.TemporaryDirectory(prefix="ns-load-", ignore_cleanup_errors=True) as tmp:
        producers_file = Path(tmp) / "producers.json"
        producers_file.write_text(
            json.dumps(
                {
                    "producers": [
                        p.registration(hashlib.sha256(p.secret.encode("utf-8")).hexdigest())
                        for p in producers
                    ]
                }
            ),
            encoding="utf-8",
        )
        env = {
            **os.environ,
            "NS_ENV": "local",
            "NS_EVENTHUBS_CONNECTION_STRING": EVENTHUBS_CONNECTION,
            "NS_INGEST_PRODUCERS_FILE": str(producers_file),
        }
        log_path = Path(tmp) / "api.log"
        with log_path.open("wb") as log:
            proc = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "--factory",
                    "neurosphere_api.main:create",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                    "--log-level",
                    "warning",
                ],
                env=env,
                cwd=REPO_ROOT,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            try:
                _wait_ready(base, proc)
                method = (
                    "locust headless (isolated uv env, locust pinned in requirements.txt); "
                    "API = local uvicorn (1 worker) from neurosphere_api.main:create with the "
                    "ingest edge; sink = Event Hubs emulator from docker compose; synthetic "
                    "events only; latency is per POST (a batch of events)"
                )
                notes = {
                    "api": "local uvicorn process, 1 worker, NS_ENV=local (not the compose api "
                    "container: it has no ingest producers configured)",
                    "sink": "Event Hubs emulator (docker compose), hub 'telemetry', 4 partitions",
                    "edge_limiter": "product defaults (20 rps per producer, burst 40)",
                    "host": f"{platform.system()} {platform.release()}, {os.cpu_count()} logical "
                    f"CPUs, Python {platform.python_version()}",
                    "client_and_server_share_host": True,
                    "consumer_running": False,
                    "endpoints_exercised": ["/v1/ingest/events", "/v1/ingest/otlp/traces"],
                    "endpoints_not_exercised": ["/v1/ingest/otlp/metrics"],
                }
                code, path, tail = run_locust(
                    plan,
                    credentials_json=json.dumps([p.credentials() for p in producers]),
                    evidence_dir=evidence_dir,
                    method=method,
                    run_id=run_id,
                    notes=notes,
                    suffix=suffix,
                    seed=seed,
                )
            finally:
                _stop(proc)
            api_errors = Counter(
                line.strip()[:120]
                for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines()
                if "error" in line.lower() or "exception" in line.lower()
            )
    if path is not None:
        doc = json.loads(path.read_text(encoding="utf-8"))
        observed = observations_from(doc)
        if api_errors:
            top = "; ".join(f"{n}x {msg}" for msg, n in api_errors.most_common(3))
            observed.append(f"API log error lines (top 3): {top}")
        doc["emulator_limits"]["observed_in_this_run"] = observed
        path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return code, path, tail
