"""Pure logic: permission detection, diff handling and compatibility checks (no I/O).

Compatibility inputs are limited to documented fields (Models - List, api-version 2024-10-01).
Context window and tool support have no documented field there, so they are reported
``unknown`` (a warning) and never ``passed``.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Iterable, Mapping, Sequence
from datetime import date
from typing import Any, Literal

from neurosphere_contracts.actions.v1.action_intent import ProposedDiff
from neurosphere_core.errors import InvalidSchemaError, StaleVersionError
from pydantic import BaseModel, ConfigDict

__all__ = [
    "ALLOWED_PATHS",
    "DEPLOYMENT_WRITE_ACTION",
    "TERMINAL_FAILURE_STATES",
    "CompatCheck",
    "apply_patch",
    "build_put_body",
    "can_write_deployments",
    "model_of",
    "run_compatibility",
    "verification_diff",
]

DEPLOYMENT_WRITE_ACTION = "Microsoft.CognitiveServices/accounts/deployments/write"
ALLOWED_PATHS = frozenset({"/properties/model/name", "/properties/model/version"})
_ALLOWED_OPS = frozenset({"test", "replace"})
TERMINAL_FAILURE_STATES = frozenset({"Failed", "Canceled", "Disabled"})


def _matches(pattern: str, action: str) -> bool:
    regex = "^" + ".*".join(re.escape(p) for p in pattern.lower().split("*")) + "$"
    return re.fullmatch(regex, action.lower()) is not None


def can_write_deployments(permissions: Iterable[Mapping[str, Any]]) -> bool:
    """True when the ARM permission set grants deployment write (wildcards; notActions subtract).

    Each permission object grants ``actions`` minus ``notActions``; objects are unioned.
    """
    for perm in permissions:
        actions = [str(a) for a in perm.get("actions") or []]
        denied = [str(a) for a in perm.get("notActions") or []]
        if any(_matches(a, DEPLOYMENT_WRITE_ACTION) for a in actions) and not any(
            _matches(n, DEPLOYMENT_WRITE_ACTION) for n in denied
        ):
            return True
    return False


class CompatCheck(BaseModel):
    """One compatibility check. ``unknown`` is a warning and never counts as passed."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    check_id: str
    status: Literal["passed", "failed", "unknown"]
    detail: str


def model_of(deployment: Mapping[str, Any]) -> dict[str, str]:
    """The deployment's ``{format, name, version}`` as strings (missing -> empty)."""
    props = deployment.get("properties")
    model = props.get("model") if isinstance(props, dict) else None
    model = model if isinstance(model, dict) else {}
    return {k: str(model.get(k, "")) for k in ("format", "name", "version")}


def verification_diff(diff: ProposedDiff) -> ProposedDiff:
    """The post-state expectation: the ``replace`` operations only.

    ``test`` operations are preconditions on the PRE-change state (they must not hold after a
    successful swap), so they are dropped; a test-only diff verifies as written.
    """
    for op in diff.operations:
        if op.path not in ALLOWED_PATHS or op.op not in _ALLOWED_OPS:
            raise InvalidSchemaError(
                "only test/replace of the model name and version is supported",
                reason="unsupported_diff_path",
            )
    replaces = [op for op in diff.operations if op.op == "replace"]
    return ProposedDiff(format="json_patch", operations=replaces) if replaces else diff


def apply_patch(deployment: Mapping[str, Any], diff: ProposedDiff) -> dict[str, Any]:
    """Apply the (restricted) JSON Patch to a copy of the deployment resource view.

    Only ``test``/``replace`` on the model name and version are allowed; anything else raises
    ``invalid_schema`` reason ``unsupported_diff_path``. A failing ``test`` raises
    ``stale_version`` reason ``diff_test_failed``.
    """
    view = copy.deepcopy(dict(deployment))
    for op in diff.operations:
        if op.path not in ALLOWED_PATHS or op.op not in _ALLOWED_OPS:
            raise InvalidSchemaError(
                "only test/replace of the model name and version is supported",
                reason="unsupported_diff_path",
            )
        if not isinstance(op.value, str) or not op.value:
            raise InvalidSchemaError(
                "diff value must be a non-empty string", reason="unsupported_diff_path"
            )
        field = op.path.rsplit("/", 1)[1]
        model = view.setdefault("properties", {}).setdefault("model", {})
        if op.op == "test":
            if model.get(field) != op.value:
                raise StaleVersionError("diff precondition failed", reason="diff_test_failed")
        else:
            model[field] = op.value
    return view


def build_put_body(deployment: Mapping[str, Any], model: Mapping[str, str]) -> dict[str, Any]:
    """Full PUT body from the existing deployment with only the model replaced.

    PUT replaces the deployment, so ``sku``, ``tags``, ``raiPolicyName`` and
    ``versionUpgradeOption`` are preserved. Read-only members are not sent.
    """
    props_in = deployment.get("properties")
    props_in = props_in if isinstance(props_in, dict) else {}
    props: dict[str, Any] = {
        "model": {"format": model["format"], "name": model["name"], "version": model["version"]}
    }
    for key in ("versionUpgradeOption", "raiPolicyName"):
        if props_in.get(key) is not None:
            props[key] = props_in[key]
    body: dict[str, Any] = {"properties": props}
    for key in ("sku", "tags"):
        if deployment.get(key) is not None:
            body[key] = copy.deepcopy(deployment[key])
    return body


def _find(
    models: Sequence[Mapping[str, Any]], model: Mapping[str, str]
) -> Mapping[str, Any] | None:
    for entry in models:
        m = entry.get("model")
        if (
            isinstance(m, dict)
            and str(m.get("format", "")) == model["format"]
            and str(m.get("name", "")) == model["name"]
            and str(m.get("version", "")) == model["version"]
        ):
            return m
    return None


def _caps(m: Mapping[str, Any] | None) -> dict[str, str] | None:
    caps = m.get("capabilities") if m else None
    return {str(k): str(v) for k, v in caps.items()} if isinstance(caps, dict) else None


def run_compatibility(
    *,
    current: Mapping[str, Any],
    target_model: Mapping[str, str],
    models: Sequence[Mapping[str, Any]],
    today: date,
) -> list[CompatCheck]:
    """Run every documented-field check for swapping ``current`` to ``target_model``."""
    out: list[CompatCheck] = []
    cur_model = model_of(current)
    target = _find(models, target_model)
    if target is None:
        out.append(
            CompatCheck(
                check_id="target_model_exists",
                status="failed",
                detail="target model/version/format not in Models - List for the account location",
            )
        )
        return [*out, *_unknowns()]
    out.append(CompatCheck(check_id="target_model_exists", status="passed", detail="listed"))

    life = target.get("lifecycleStatus")
    out.append(
        CompatCheck(
            check_id="lifecycle_not_deprecated",
            status="failed" if life == "Deprecated" else "passed",
            detail=f"lifecycleStatus={life}",
        )
    )

    dep = target.get("deprecation")
    raw = dep.get("inference") if isinstance(dep, dict) else None
    status: Literal["passed", "failed"] = "passed"
    detail = "no inference deprecation date"
    if isinstance(raw, str) and raw:
        try:
            when = date.fromisoformat(raw[:10])
        except ValueError:
            return [
                *out,
                CompatCheck(
                    check_id="inference_not_retired",
                    status="failed",
                    detail="inference deprecation date unparseable",
                ),
                *_unknowns(),
            ]
        detail = f"inference deprecation {when.isoformat()}"
        if when <= today:
            status = "failed"
    out.append(CompatCheck(check_id="inference_not_retired", status=status, detail=detail))

    sku = current.get("sku")
    sku_name = str(sku.get("name", "")) if isinstance(sku, dict) else ""
    skus = target.get("skus")
    names = (
        {str(s.get("name", "")) for s in skus if isinstance(s, dict)}  # pyright: ignore[reportUnknownVariableType]
        if isinstance(skus, list)
        else set[str]()
    )
    out.append(
        CompatCheck(
            check_id="sku_supported",
            status="passed" if sku_name and sku_name in names else "failed",
            detail=f"deployment sku {sku_name or '<none>'} vs model skus",
        )
    )

    cur_entry = _find(models, cur_model)
    cur_caps = _caps(cur_entry)
    if cur_caps is None:
        props = current.get("properties")
        raw_caps = props.get("capabilities") if isinstance(props, dict) else None
        cur_caps = (
            {str(k): str(v) for k, v in raw_caps.items()} if isinstance(raw_caps, dict) else None
        )
    tgt_caps = _caps(target)
    if cur_caps is None or tgt_caps is None:
        out.append(
            CompatCheck(
                check_id="capability_keys_preserved",
                status="unknown",
                detail="capability map not reported for the current or target model",
            )
        )
    else:
        missing = sorted(set(cur_caps) - set(tgt_caps))
        out.append(
            CompatCheck(
                check_id="capability_keys_preserved",
                status="failed" if missing else "passed",
                detail="missing on target: " + ", ".join(missing) if missing else "all present",
            )
        )
    return [*out, *_unknowns()]


def _unknowns() -> list[CompatCheck]:
    return [
        CompatCheck(
            check_id=cid,
            status="unknown",
            detail="no documented field in Models - List; not evaluated (warning)",
        )
        for cid in ("context_window", "tool_support")
    ]
