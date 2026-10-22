"""G02 live run: Azure Government AKS profile deploy and smoke.

Operator-approved only. Refuses (exit 2, gate stays OPEN) unless ALL of these hold; the first
check runs before argument parsing, any other import or any command:
  1. NS_LIVE_APPROVED=1
  2. NS_GOV_SUBSCRIPTION_ID names a Government subscription (the value is never printed/written)
  3. --location is usgovvirginia, usgovarizona or usgovtexas
  4. `az cloud show` reports AzureUSGovernment
  5. NS_GOV_IMAGE_REGISTRY, NS_GOV_AKS_CLUSTER and NS_GOV_AKS_RESOURCE_GROUP are set

No Government subscription exists for this project (decision D7), so this script has NEVER been
run live. It must not be run by an agent; the operator runs it with their own approval.

Approved path (all of it creates billable resources):
  1. create a tagged resource group, deploy infra/bicep/params/government/main.bicepparam
  2. tag every resource in that group; create a labelled namespace on the operator's existing
     AKS cluster and `helm upgrade --install` infra/helm with infra/helm/values-government.yaml
  3. smoke: helm release status is `deployed` and every Deployment becomes Available
  4. drift: (a) `az deployment group what-if` on the same Bicep parameters reports no
     Create/Delete/Modify; (b) a second identical `helm upgrade --install` leaves
     `helm get values --all` and `helm get manifest` byte-identical
  5. uninstall dry-run: list the group's resources and prove only resources carrying this run's
     tags are listed for removal and nothing else (shared/pre-existing resources are protected)
  6. teardown: helm uninstall, delete the namespace this run created, delete the resource group
     only after re-reading its run-id tag and confirming the dry-run found no foreign resource

Evidence: docs/evidence/G02/profile-aks-<UTC date>.md, whitelisted fields only, passed through
a credential scrubber, subscription shown only as a short hash. Exit codes: 0 PASS, 1 FAIL,
2 REFUSED.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import sys
from pathlib import Path
from typing import Any

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")  # pyright: ignore[reportAttributeAccessIssue]

REPO = Path(__file__).resolve().parents[2]
BICEP_PARAMS = "infra/bicep/params/government/main.bicepparam"
HELM_CHART = "infra/helm"
HELM_VALUES = "infra/helm/values-government.yaml"
DEFAULT_IMAGE_TAG = "0.1.0"


def _common() -> Any:
    here = str(Path(__file__).resolve().parent)
    if here not in sys.path:
        sys.path.insert(0, here)
    return importlib.import_module("_g02_profile_common")


class AksProfile:
    name = "aks"

    def __init__(self, common: Any) -> None:
        self._c = common

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--image-tag", default=DEFAULT_IMAGE_TAG)

    def validate(self, args: argparse.Namespace) -> None:
        c = self._c
        args.registry = c.valid_name(os.environ.get(c.REGISTRY_ENV, "").strip(), c.REGISTRY_ENV)
        args.cluster = c.valid_name(
            os.environ.get("NS_GOV_AKS_CLUSTER", "").strip(), "NS_GOV_AKS_CLUSTER"
        )
        args.cluster_rg = c.valid_name(
            os.environ.get("NS_GOV_AKS_RESOURCE_GROUP", "").strip(), "NS_GOV_AKS_RESOURCE_GROUP"
        )
        args.image_tag = c.valid_name(str(args.image_tag), "--image-tag")

    # -- helpers
    def _kube(self, ctx: Any) -> list[str]:
        return ["--kubeconfig", str(ctx.work_dir / "kubeconfig")]

    def _helm_install(self, ctx: Any) -> None:
        a = ctx.args
        ctx.run(
            "helm", "upgrade", "--install", ctx.facts["release"], str(REPO / HELM_CHART),
            "--namespace", ctx.facts["namespace"], *self._kube(ctx),
            "--values", str(REPO / HELM_VALUES),
            "--set", f"image.registry={a.registry}", "--set", f"image.tag={a.image_tag}",
            "--wait", "--timeout", "10m",
        )  # fmt: skip

    def _helm_state(self, ctx: Any) -> str:
        base = ["--namespace", ctx.facts["namespace"], *self._kube(ctx)]
        values = ctx.run(
            "helm", "get", "values", ctx.facts["release"], "--all", "-o", "json", *base
        )
        manifest = ctx.run("helm", "get", "manifest", ctx.facts["release"], *base)
        return hashlib.sha256((values + "\n--\n" + manifest).encode("utf-8")).hexdigest()

    # -- lifecycle
    def deploy(self, ctx: Any) -> None:
        ctx.az(
            "deployment", "group", "create", "--resource-group", ctx.resource_group,
            "--parameters", str(REPO / BICEP_PARAMS), "--name", f"g02-{ctx.run_id}",
        )  # fmt: skip
        ctx.facts["release"] = f"ns-g02-{ctx.run_id}"
        ctx.facts["namespace"] = f"ns-g02-{ctx.run_id}"
        a = ctx.args
        ctx.az(
            "aks", "get-credentials", "--resource-group", a.cluster_rg, "--name", a.cluster,
            "--file", str(ctx.work_dir / "kubeconfig"), "--overwrite-existing",
        )  # fmt: skip
        ctx.run("kubectl", "create", "namespace", ctx.facts["namespace"], *self._kube(ctx))
        ctx.facts["namespace_created"] = True
        ctx.run(
            "kubectl", "label", "namespace", ctx.facts["namespace"],
            "neurosphere-gate=G02", f"neurosphere-run={ctx.run_id}", *self._kube(ctx),
        )  # fmt: skip
        self._helm_install(ctx)
        ctx.facts["release_installed"] = True

    def smoke(self, ctx: Any) -> None:
        base = ["--namespace", ctx.facts["namespace"], *self._kube(ctx)]
        status = json.loads(
            ctx.run("helm", "status", ctx.facts["release"], "-o", "json", *base) or "{}"
        )
        state = str(status.get("info", {}).get("status", ""))
        ctx.record("helm-release-deployed", state == "deployed", f"status={state}")
        ctx.run(
            "kubectl", "wait", "--for=condition=Available", "deployment", "--all",
            "--timeout=300s", *base,
        )  # fmt: skip
        ctx.record("deployments-available", True)

    def drift(self, ctx: Any) -> int:
        what_if = ctx.az(
            "deployment", "group", "what-if", "--resource-group", ctx.resource_group,
            "--parameters", str(REPO / BICEP_PARAMS), "--no-pretty-print", "--output", "json",
            parse_json=True,
        )  # fmt: skip
        changes = [
            ch for ch in (what_if or {}).get("changes", [])
            if ch.get("changeType") in ("Create", "Delete", "Modify")
        ]  # fmt: skip
        before = self._helm_state(ctx)
        self._helm_install(ctx)
        after = self._helm_state(ctx)
        helm_drift = 0 if before == after else 1
        ctx.checks.append(
            self._c.Check(
                "bicep-what-if", "PASS" if not changes else "FAIL", f"changes={len(changes)}"
            )
        )
        ctx.checks.append(
            self._c.Check("helm-second-upgrade-identical", "PASS" if not helm_drift else "FAIL")
        )
        return len(changes) + helm_drift

    def cleanup(self, ctx: Any) -> None:
        if "namespace" not in ctx.facts:
            return
        base = ["--namespace", ctx.facts["namespace"], *self._kube(ctx)]
        if ctx.facts.get("release_installed"):
            ctx.run("helm", "uninstall", ctx.facts["release"], "--wait", *base)
        if ctx.facts.get("namespace_created"):
            ctx.run(
                "kubectl", "delete", "namespace", ctx.facts["namespace"], "--wait=true",
                *self._kube(ctx),
            )  # fmt: skip


def main(argv: list[str] | None = None, **kwargs: Any) -> int:
    if os.environ.get("NS_LIVE_APPROVED") != "1":
        print(
            "REFUSED: g02_profile_aks.py deploys billable Azure Government resources and needs "
            "operator approval; set NS_LIVE_APPROVED=1.\n"
            "Gate G02 profile-aks remains OPEN (not run, not passed). No evidence was written "
            "and no command was run."
        )
        return 2
    common = _common()
    return int(common.execute(AksProfile(common), argv, **kwargs))


if __name__ == "__main__":
    raise SystemExit(main())
