"""Seed the registered hosted demo with synthetic data (PRP-32 item 5). Operator-approved only.

    NS_LIVE_APPROVED=1 NS_ENV=prod NS_SANDBOX_HOSTED_DEPLOYMENT_ID=<id> NS_AUTH_TENANT_ID=<guid> \
      uv run python scripts/gates/hosted_demo_seed.py --operator-object-id <oid> \
      [--registration temp/hosted-demo/registration.json] [--profile small|demo]

Order: the approval check first (exit 2, nothing imported, no network), then the
``neurosphere_core`` import proof, then the registration and endpoint guard, then the synthetic
generator (deterministic seed) into its standard output directory (``temp/sandbox``), then the
hosted mode of ``scripts/sandbox/sbx_seed_stack.py`` reading that directory, with
``--operator-object-id`` as the grant principal.

Entra only: the script accepts no key or connection string (any such variable refuses) and never
creates a database, container or hub (Bicep owns them). Evidence under ``docs/evidence/PRP-32/``
holds counts only: no host, id or secret.

Exit 0 = seeded, 1 = a seed step failed, 2 = refused (nothing was contacted).
"""

from __future__ import annotations

import argparse
import contextlib
import importlib
import io
import json
import os
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

REPO: Final = Path(__file__).resolve().parents[2]
SANDBOX_SCRIPTS: Final = REPO / "scripts" / "sandbox"
DEFAULT_REGISTRATION: Final = REPO / "temp" / "hosted-demo" / "registration.json"
#: The generator's standard output directory (``python -m sandbox.generate`` default).
GENERATOR_OUTPUT_DIR: Final = REPO / "temp" / "sandbox"
EVIDENCE_DIR: Final = REPO / "docs" / "evidence" / "PRP-32"
EVIDENCE_NAME: Final = "hosted_demo_seed.json"
EXIT_FAILED: Final = 1
EXIT_REFUSED: Final = 2
KINDS: Final = (
    ("cosmos", "cosmos_host"),
    ("eventhubs", "eventhubs_host"),
    ("blob", "blob_host"),
    ("keyvault", "key_vault_host"),
)


def _refuse(message: str) -> int:
    print(f"REFUSED: {message}", file=sys.stderr)
    return EXIT_REFUSED


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Seed the registered hosted demo.")
    parser.add_argument(
        "--operator-object-id", required=True, help="your Entra object id (grant principal)"
    )
    parser.add_argument("--registration", type=Path, default=DEFAULT_REGISTRATION)
    parser.add_argument("--profile", default="small", choices=("small", "demo"))
    parser.add_argument("--input-dir", type=Path, default=GENERATOR_OUTPUT_DIR)
    parser.add_argument("--evidence-dir", type=Path, default=EVIDENCE_DIR)
    return parser


def _load_modules() -> tuple[Any, Any]:
    for path in (SANDBOX_SCRIPTS, REPO):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    return importlib.import_module("sbx_guard"), importlib.import_module("sbx_seed_stack")


def generate_input(seed_module: Any, config: Any, input_dir: Path) -> dict[str, int]:
    """Run the existing synthetic generator (deterministic seed) into ``input_dir``."""
    manifest = seed_module.generate(seed_module.generate_config(config), input_dir)
    files = manifest.get("files", {}) if isinstance(manifest, Mapping) else {}
    return {
        str(name): int(info["records"])
        for name, info in files.items()
        if isinstance(info, Mapping) and isinstance(info.get("records"), int)
    }


def write_evidence(
    evidence_dir: Path, *, profile: str, generated: Mapping[str, int], summary: Mapping[str, Any]
) -> Path:
    """Counts only. No host, id or secret is ever written."""
    evidence_dir.mkdir(parents=True, exist_ok=True)
    doc = {
        "gate": "hosted_demo_seed",
        "result": "PASS",
        "recorded": datetime.now(UTC).strftime("%Y-%m-%d"),
        "profile": profile,
        "generated_files": dict(sorted(generated.items())),
        "seeded": dict(sorted(dict(summary.get("seeded", {})).items())),
        "skipped_existing": int(summary.get("skipped_existing", 0)),
    }
    path = evidence_dir / EVIDENCE_NAME
    path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def main(argv: Sequence[str] | None = None, *, env: Mapping[str, str] | None = None) -> int:
    environ = dict(os.environ) if env is None else dict(env)
    if environ.get("NS_LIVE_APPROVED") != "1":
        print(
            "REFUSED: hosted_demo_seed.py writes to a hosted Azure environment and needs "
            "operator approval; set NS_LIVE_APPROVED=1. Nothing was contacted.",
            file=sys.stderr,
        )
        return EXIT_REFUSED

    args = build_parser().parse_args(argv)
    # Prove the interpreter has the workspace before any client exists (cf. g01_deploy_smoke).
    try:
        importlib.import_module("neurosphere_core.cloud")
    except ImportError:
        return _refuse(
            "neurosphere_core is not importable; run with "
            "`uv run python scripts/gates/hosted_demo_seed.py ...`. Nothing was contacted."
        )
    guard, seed = _load_modules()

    try:
        for kind, name in KINDS:
            registration = guard.load_registration(args.registration)
            guard.require_hosted_endpoint(
                f"https://{registration.get(name)}",
                kind=kind,
                env=environ,
                registration_path=args.registration,
            )
        config = seed.resolve_hosted_config(
            args.profile, args.operator_object_id, environ, args.registration
        )
    except (guard.GuardError, seed.ConfigError) as exc:
        return _refuse(str(exc))

    generated = generate_input(seed, config, args.input_dir)
    print(f"generated the {args.profile} synthetic world", file=sys.stderr)

    seed_args = [
        "--hosted",
        str(args.registration),
        "--profile",
        args.profile,
        "--operator-object-id",
        args.operator_object_id,
        "--input-dir",
        str(args.input_dir),
    ]
    captured = io.StringIO()
    with contextlib.redirect_stdout(captured):
        code = seed.main(seed_args, env=environ)
    if code != 0:
        print(f"FAILED: the hosted seed exited {code}", file=sys.stderr)
        return EXIT_REFUSED if code == seed.EXIT_REFUSED else EXIT_FAILED
    try:
        summary = json.loads(captured.getvalue())
    except ValueError:
        print("FAILED: the hosted seed printed no summary", file=sys.stderr)
        return EXIT_FAILED
    path = write_evidence(
        args.evidence_dir, profile=args.profile, generated=generated, summary=summary
    )
    print(f"PASS: wrote {path}")
    return 0


if __name__ == "__main__":
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
