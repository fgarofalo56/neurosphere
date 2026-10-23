"""Operator CLI for the PRP-21 load profiles.

Pilot against the compose emulators (starts a local API; needs ``docker compose up -d --wait``):

    uv run python tests/load/profiles/run_profile.py pilot --evidence-dir docs/evidence/G07/load

Enterprise and stress are operator-run at a sized environment you name; there is no default
target and nothing here is wired into CI. Producer credentials come from the environment
(``NS_LOAD_CREDENTIALS_JSON``, a JSON list of producer_id/secret/customer_id/cloud/sources):

    uv run python tests/load/profiles/run_profile.py enterprise \
        --host https://ingest.example.invalid --environment-label "<your sized environment>"
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")  # pyright: ignore[reportAttributeAccessIssue]

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from profiles.compose_pilot import run_pilot
from profiles.definitions import PROFILES, TargetRequiredError, resolve_run
from profiles.runner import REPO_ROOT, build_command, run_locust

DEFAULT_EVIDENCE_DIR = REPO_ROOT / "docs" / "evidence" / "G07" / "load"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("profile", choices=sorted(PROFILES))
    ap.add_argument("--host", help="target base URL (required for enterprise and stress)")
    ap.add_argument("--environment-label", help="name of the sized environment (operator runs)")
    ap.add_argument("--duration", type=int, help="seconds (default: profile default)")
    ap.add_argument("--users", type=int, help="concurrent locust users")
    ap.add_argument("--skew-multiple", type=float, help="hot domain weight / median domain weight")
    ap.add_argument("--evidence-dir", default=str(DEFAULT_EVIDENCE_DIR))
    ap.add_argument("--suffix", default="", help="evidence filename suffix, e.g. -probe")
    ap.add_argument("--dry-run", action="store_true", help="resolve and print the plan only")
    args = ap.parse_args(argv)
    evidence_dir = Path(args.evidence_dir)

    try:
        if args.profile == "pilot" and not args.host:
            if args.dry_run:
                plan = resolve_run("pilot", duration_seconds=args.duration, users=args.users)
                print(
                    json.dumps({"profile": "pilot", "target": "local compose", "users": plan.users})
                )
                return 0
            code, path, tail = run_pilot(
                evidence_dir,
                duration_seconds=args.duration,
                users=args.users,
                skew_multiple=args.skew_multiple,
                suffix=args.suffix,
            )
        else:
            plan = resolve_run(
                args.profile,
                host=args.host,
                duration_seconds=args.duration,
                users=args.users,
                skew_multiple=args.skew_multiple,
                environment_label=args.environment_label,
            )
            if args.dry_run:
                print(" ".join(build_command(plan)))
                return 0
            credentials = os.environ.get("NS_LOAD_CREDENTIALS_JSON")
            if not credentials:
                print(
                    "NS_LOAD_CREDENTIALS_JSON is required for an external target", file=sys.stderr
                )
                return 2
            code, path, tail = run_locust(
                plan,
                credentials_json=credentials,
                evidence_dir=evidence_dir,
                method="operator run via tests/load/profiles/run_profile.py",
                run_id=uuid.uuid4().hex[:8],
                suffix=args.suffix,
            )
    except TargetRequiredError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    print(tail)
    print(f"evidence: {path}")
    return code if path is None else 0


if __name__ == "__main__":
    raise SystemExit(main())
