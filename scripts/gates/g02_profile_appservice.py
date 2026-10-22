"""G02 live run: Azure Government App Service profile deploy and smoke.

Operator-approved only. Refuses (exit 2, gate stays OPEN) unless ALL of these hold; the first
check runs before argument parsing, any other import or any command:
  1. NS_LIVE_APPROVED=1
  2. NS_GOV_SUBSCRIPTION_ID names a Government subscription (the value is never printed/written)
  3. --location is usgovvirginia, usgovarizona or usgovtexas
  4. `az cloud show` reports AzureUSGovernment
  5. NS_GOV_IMAGE_REGISTRY is set

No Government subscription exists for this project (decision D7), so this script has NEVER been
run live. It must not be run by an agent; the operator runs it with their own approval.

Approved path (creates billable resources):
  1. create a tagged resource group and deploy infra/appservice/main.bicep with Government
     parameters (a generated parameters file in a temp directory outside the repo; the template
     derives every hostname from environment(), so no commercial suffix is configured)
  2. tag every resource in that group
  3. smoke: every web app in the group reports state Running
  4. drift: `az deployment group what-if` on the same template and parameters reports no
     Create/Delete/Modify on the second pass
  5. uninstall dry-run: list the group's resources and prove only resources carrying this run's
     tags are listed for removal (shared/pre-existing resources are protected)
  6. teardown: delete the resource group only after re-reading its run-id tag and confirming
     the dry-run found no foreign resource

Evidence: docs/evidence/G02/profile-appservice-<UTC date>.md, whitelisted fields only, passed
through a credential scrubber, subscription shown only as a short hash. Exit codes: 0 PASS,
1 FAIL, 2 REFUSED.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
from pathlib import Path
from typing import Any

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")  # pyright: ignore[reportAttributeAccessIssue]

REPO = Path(__file__).resolve().parents[2]
TEMPLATE = "infra/appservice/main.bicep"
DEFAULT_IMAGE_TAG = "0.1.0"
NAME_PREFIX = "nsgov"


def _common() -> Any:
    here = str(Path(__file__).resolve().parent)
    if here not in sys.path:
        sys.path.insert(0, here)
    return importlib.import_module("_g02_profile_common")


class AppServiceProfile:
    name = "appservice"

    def __init__(self, common: Any) -> None:
        self._c = common

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--image-tag", default=DEFAULT_IMAGE_TAG)

    def validate(self, args: argparse.Namespace) -> None:
        c = self._c
        args.registry = c.valid_name(os.environ.get(c.REGISTRY_ENV, "").strip(), c.REGISTRY_ENV)
        args.image_tag = c.valid_name(str(args.image_tag), "--image-tag")

    def _params_file(self, ctx: Any) -> str:
        a = ctx.args
        tags = {t.split("=", 1)[0]: t.split("=", 1)[1] for t in ctx.tags}
        doc = {
            "$schema": "https://schema.management.azure.com/schemas/2019-04-01/"
            "deploymentParameters.json#",
            "contentVersion": "1.0.0.0",
            "parameters": {
                "namePrefix": {"value": NAME_PREFIX},
                "location": {"value": ctx.location},
                "imageRegistry": {"value": a.registry},
                "imageTag": {"value": a.image_tag},
                "tags": {"value": tags},
            },
        }
        path = ctx.work_dir / "appservice.parameters.json"
        path.write_text(json.dumps(doc), encoding="utf-8")
        return str(path)

    def deploy(self, ctx: Any) -> None:
        ctx.az(
            "deployment", "group", "create", "--resource-group", ctx.resource_group,
            "--template-file", str(REPO / TEMPLATE),
            "--parameters", f"@{self._params_file(ctx)}", "--name", f"g02-{ctx.run_id}",
        )  # fmt: skip

    def smoke(self, ctx: Any) -> None:
        apps = ctx.az(
            "webapp", "list", "--resource-group", ctx.resource_group,
            "--query", "[].{name:name,state:state}", "--output", "json", parse_json=True,
        )  # fmt: skip
        apps = list(apps or [])
        running = [x for x in apps if x.get("state") == "Running"]
        ctx.record(
            "web-apps-running",
            bool(apps) and len(running) == len(apps),
            f"running={len(running)} total={len(apps)}",
        )

    def drift(self, ctx: Any) -> int:
        what_if = ctx.az(
            "deployment", "group", "what-if", "--resource-group", ctx.resource_group,
            "--template-file", str(REPO / TEMPLATE),
            "--parameters", f"@{self._params_file(ctx)}", "--no-pretty-print",
            "--output", "json", parse_json=True,
        )  # fmt: skip
        changes = [
            ch for ch in (what_if or {}).get("changes", [])
            if ch.get("changeType") in ("Create", "Delete", "Modify")
        ]  # fmt: skip
        ctx.checks.append(
            self._c.Check(
                "bicep-what-if", "PASS" if not changes else "FAIL", f"changes={len(changes)}"
            )
        )
        return len(changes)

    def cleanup(self, ctx: Any) -> None:
        return None  # everything lives in the resource group, which the runner removes


def main(argv: list[str] | None = None, **kwargs: Any) -> int:
    if os.environ.get("NS_LIVE_APPROVED") != "1":
        print(
            "REFUSED: g02_profile_appservice.py deploys billable Azure Government resources and "
            "needs operator approval; set NS_LIVE_APPROVED=1.\n"
            "Gate G02 profile-appservice remains OPEN (not run, not passed). No evidence was "
            "written and no command was run."
        )
        return 2
    common = _common()
    return int(common.execute(AppServiceProfile(common), argv, **kwargs))


if __name__ == "__main__":
    raise SystemExit(main())
