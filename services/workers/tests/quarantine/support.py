"""In-memory BlobContainer, CLI loader and builders for the quarantine tests (synthetic data)."""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from types import ModuleType
from typing import Any

from azure.core.exceptions import HttpResponseError, ResourceExistsError, ResourceNotFoundError

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    # Lets the ingestion test builders be imported by their repo path, which pyright can resolve
    # (pytest's own `ingestion.support` name is invisible to it).
    sys.path.append(str(_REPO_ROOT))

from neurosphere_workers.ingestion.pipeline import process_batch  # noqa: E402
from neurosphere_workers.quarantine import BlobQuarantineSink  # noqa: E402

from services.workers.tests.ingestion.support import (  # noqa: E402  # re-exported for the tests
    T0,
    Doc,
    Harness,
    raw_event,
    raw_from_bytes,
    rich_telemetry,
    settings,
    telemetry_at,
)

__all__ = [
    "T0",
    "CliRun",
    "Doc",
    "FakeBlobContainer",
    "Harness",
    "blob_sink",
    "container_factory",
    "deps_factory",
    "load_cli",
    "quarantine_poison",
    "raw_event",
    "raw_from_bytes",
    "rich_telemetry",
    "run_cli",
    "settings",
    "telemetry_at",
]


@dataclass
class _Item:
    name: str
    metadata: Mapping[str, str] | None


class _Download:
    def __init__(self, data: bytes) -> None:
        self._data = data

    async def readall(self) -> bytes:
        return self._data


class FakeBlobContainer:
    """Behaves like ContainerClient for the calls the quarantine package makes."""

    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}
        self.meta: dict[str, dict[str, str]] = {}
        self.upload_calls = 0
        self.fail_status: int | None = None

    async def upload_blob(
        self,
        name: str,
        data: bytes,
        *,
        overwrite: bool = False,
        metadata: Mapping[str, str] | None = None,
    ) -> None:
        self.upload_calls += 1
        if self.fail_status is not None:
            err = HttpResponseError("injected")
            err.status_code = self.fail_status
            raise err
        if name in self.blobs and not overwrite:
            raise ResourceExistsError("exists")
        self.blobs[name] = data
        self.meta[name] = dict(metadata or {})

    async def download_blob(self, blob: str) -> _Download:
        if blob not in self.blobs:
            raise ResourceNotFoundError("missing")
        return _Download(self.blobs[blob])

    def list_blobs(
        self, name_starts_with: str | None = None, include: list[str] | None = None
    ) -> AsyncIterator[_Item]:
        async def gen() -> AsyncIterator[_Item]:
            for name in sorted(self.blobs):
                if name_starts_with is None or name.startswith(name_starts_with):
                    yield _Item(name, self.meta.get(name) if include else None)

        return gen()

    def names(self, prefix: str) -> list[str]:
        return sorted(n for n in self.blobs if n.startswith(prefix))


def blob_sink(container: FakeBlobContainer) -> BlobQuarantineSink:
    return BlobQuarantineSink(container)


def load_cli() -> ModuleType:
    """Import ``scripts/replay/replay.py`` by path: no pyproject or sys.path change needed."""
    module = sys.modules.get("ns_replay_cli")
    if module is None:
        path = _REPO_ROOT / "scripts" / "replay" / "replay.py"
        spec = importlib.util.spec_from_file_location("ns_replay_cli", path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules["ns_replay_cli"] = module
        spec.loader.exec_module(module)
    return module


def container_factory(container: FakeBlobContainer) -> Any:
    @asynccontextmanager
    async def factory() -> AsyncIterator[FakeBlobContainer]:
        yield container

    return factory


def deps_factory(harness: Harness) -> Any:
    @asynccontextmanager
    async def factory() -> AsyncIterator[Any]:
        yield harness.deps()

    return factory


@dataclass
class CliRun:
    code: int
    out: str
    err: str


def run_cli(
    argv: list[str], container: FakeBlobContainer, harness: Harness | None = None
) -> CliRun:
    cli = load_cli()
    out, err = StringIO(), StringIO()
    code = cli.main(
        argv,
        container_factory=container_factory(container),
        deps_factory=deps_factory(harness or Harness()),
        out=out,
        err=err,
    )
    return CliRun(code, out.getvalue(), err.getvalue())


async def quarantine_poison(container: FakeBlobContainer, harness: Harness, doc: Doc) -> None:
    """Run one event through process_batch whose archive fails 3x, into the BLOB sink."""
    deps = harness.deps()
    deps.quarantine = blob_sink(container)
    harness.archive.fail_transient(3)
    await process_batch([raw_event(doc, 0)], deps, settings())
