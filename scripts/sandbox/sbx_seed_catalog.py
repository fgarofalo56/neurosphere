"""Compose-runnable catalog seeder (PRP-35 item 2).

Loads the synthetic sandbox catalog (entities and edges) into Cosmos through
``CatalogRepository``, idempotently, with no host-side dependency beyond Docker. It reuses
``sbx_seed_stack.seed_entities`` (not a fork) and the stack seed's own grants, so the scope it
writes under is exactly the workers' scope.

Safety: it refuses unless ``NS_ENV`` is exactly ``local`` and the cloud is Commercial, so a
hosted or Government profile can never receive synthetic data. The loopback-only ``sbx_guard``
rules are unchanged: the compose ``seed`` service shares the Cosmos emulator's network namespace,
so the endpoint it talks to is ``127.0.0.1:8081``.

The sandbox generator emits no aliases (``sandbox/catalog.py`` has no alias stream), so none are
seeded; edges are written under the same deterministic ids the ingestion projection uses, so a
later projection merges into them instead of duplicating them.

Exit codes: 0 seeded (or already seeded), 2 refused, 3 failed. stdout is one JSON summary line.
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import sys
import tempfile
from collections.abc import Mapping, Sequence
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any, Final

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
for _path in (HERE, REPO):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import sbx_seed_stack as seed  # noqa: E402
from neurosphere_core.catalog.repo.documents import EDGE_MODELS  # noqa: E402
from neurosphere_core.errors import NeuroSphereError  # noqa: E402
from neurosphere_core.scope import IdentityScope  # noqa: E402
from neurosphere_workers.projections.catalog.mapping import edge_id  # noqa: E402
from pydantic import ValidationError  # noqa: E402
from sbx_guard import GuardError  # noqa: E402

from sandbox.world import World  # noqa: E402

EXIT_OK: Final = 0
EXIT_REFUSED: Final = seed.EXIT_REFUSED
EXIT_FAILED: Final = seed.EXIT_FAILED
RELATIONS_FILE: Final = "relations.ndjson"
REPORTED: Final = ("entities", "edges", "grants")


def require_local_profile(environ: Mapping[str, str]) -> None:
    """Refuse anything but an explicit local Commercial profile. Raises ``seed.ConfigError``."""
    env_name = environ.get("NS_ENV", "")
    if env_name != "local":
        raise seed.ConfigError(
            f"refusing to seed synthetic data: NS_ENV is {env_name or 'unset'!r}, it must be "
            "'local' (hosted and Government profiles never receive synthetic data)"
        )
    cloud = environ.get("NS_CLOUD", "commercial")
    if cloud != "commercial":
        raise seed.ConfigError(
            f"refusing to seed synthetic data: NS_CLOUD is {cloud!r}; the synthetic sandbox is "
            "Commercial-only"
        )


class CatalogTally(seed.Tally):
    """The stack seed's tally plus an ``edges`` category."""

    def __init__(self) -> None:
        super().__init__()
        self.seeded["edges"] = 0

    def summary(self) -> seed.Doc:
        counts = {name: self.seeded[name] for name in REPORTED}
        return {"seeded": counts, "skipped_existing": self.skipped}


async def seed_edges(
    backends: seed.Backends, scope: IdentityScope, directory: Path, tally: CatalogTally
) -> None:
    """Write the generated relations through ``CatalogRepository.put_edge``.

    Ids are rewritten to the projection's deterministic id (same relation, source and target give
    the same id), so the ingestion projection later merges into these edges. Out-of-scope
    documents are skipped (fail closed). A re-run finds each edge and creates nothing.
    """
    path = directory / RELATIONS_FILE
    if not path.exists():
        return
    allowed = frozenset(scope.allowed_domains)
    for doc in seed.read_ndjson(path):
        model = EDGE_MODELS.get(str(doc.get("relation_type")))
        if (
            model is None
            or doc.get("cloud") != scope.cloud
            or doc.get("customer_id") != scope.customer_id
            or doc.get("domain_id") not in allowed
        ):
            continue
        stable = edge_id(
            doc["cloud"],
            doc["customer_id"],
            doc["relation_type"],
            doc["source_id"],
            doc["target_id"],
        )
        if await backends.catalog.get_edge(scope, stable) is not None:
            tally.record("edges", created=0, existing=1)
            continue
        edge = model.model_validate({**doc, "id": stable})
        await backends.catalog.put_edge(scope, edge, None)  # type: ignore[arg-type]
        tally.record("edges", created=1, existing=0)


async def seed_catalog(
    config: seed.SeedConfig,
    backends: seed.Backends,
    workdir: Path,
    *,
    environ: Mapping[str, str],
) -> seed.Doc:
    """Generate the world, grant the workers' scope, then seed entities and edges."""
    require_local_profile(environ)
    tally = CatalogTally()
    gen = seed.generate_config(config)
    seed.log(f"generating the {config.profile} world (seed {config.seed})")
    await asyncio.to_thread(seed.generate, gen, workdir)
    world = World(gen)
    await seed.seed_grants(backends, config, world, tally, environ)
    scope = await seed.worker_scope(backends, config)
    missing = sorted(set(seed.world_domains(world)) - set(scope.allowed_domains))
    if missing:
        raise seed.SeedError(
            f"the worker scope lacks {len(missing)} seeded domains; grants did not apply"
        )
    await seed.seed_entities(backends, scope, workdir, tally)
    await seed_edges(backends, scope, workdir, tally)
    return tally.summary()


async def _run(config: seed.SeedConfig, environ: Mapping[str, str]) -> seed.Doc:
    with tempfile.TemporaryDirectory(prefix="ns-seed-catalog-") as tmp:
        async with AsyncExitStack() as stack:
            backends = await seed.open_backends(config, stack)
            return await seed_catalog(config, backends, Path(tmp), environ=environ)


def main(argv: Sequence[str] | None = None, *, env: Mapping[str, str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Seed the synthetic sandbox catalog (local only).")
    parser.add_argument("--profile", choices=sorted(seed.load_profiles()), default="small")
    args = parser.parse_args(argv)
    environ = dict(os.environ) if env is None else dict(env)
    try:
        require_local_profile(environ)
        config = seed.resolve_config(args.profile, None, environ)
    except (GuardError, seed.ConfigError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    try:
        with seed.scoped_environ({**environ, **config.environ()}):
            summary: Any = asyncio.run(_run(config, environ))
    except (seed.SeedError, NeuroSphereError, ValidationError, OSError) as exc:
        print(f"FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_FAILED
    print(json.dumps(summary, sort_keys=True))
    return EXIT_OK


if __name__ == "__main__":
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
