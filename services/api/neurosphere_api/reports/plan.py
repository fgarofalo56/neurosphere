"""Chart plan handling for saved reports: strip data on save, fill rows on run.

A saved plan is a TEMPLATE: encodings, marks and transforms with ``data.values`` stored empty.
On every run the rows come from the viewer-scoped tool records, the filled plan is re-validated
with ``neurosphere_core.charts.validate_chart_plan`` and only then returned. Tool records are
untrusted data; here they only become scalar cells under charset-safe field names.
"""

import copy
import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Final

from neurosphere_contracts.chart.v1.chart_plan import ChartPlan
from neurosphere_core.charts import ChartPlanInvalidError
from neurosphere_core.copilot.tools import Citation, ToolRecord
from neurosphere_core.errors import ValidationIssue
from pydantic import ValidationError

__all__ = [
    "build_rows",
    "check_template",
    "fill_plan",
    "numeric_fields",
    "strip_data",
]

MAX_ROWS: Final = 5000
_MAX_TEXT: Final = 1024
_MAX_DEPTH: Final = 2
_FIELD: Final = re.compile(r"^[a-z_][a-z0-9_]{0,63}$")
_EVIDENCE_ID: Final = re.compile(r"^[a-z0-9][a-z0-9._:/=-]{0,255}$")
_TIMESTAMP: Final = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,9})?Z$")
_NUMERIC_AGGREGATES: Final = frozenset({"sum", "mean", "median", "min", "max"})
_NUMBER: Final = re.compile(r"^-?(0|[1-9][0-9]*)(\.[0-9]+)?$")


def strip_data(plan: Mapping[str, Any]) -> dict[str, Any]:
    """A deep copy of ``plan`` with ``spec.data.values`` emptied: stored plans carry no rows."""
    out = copy.deepcopy(dict(plan))
    spec = out.get("spec")
    if isinstance(spec, dict):
        data = spec.get("data")
        if isinstance(data, dict):
            data["values"] = []
    return out


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def numeric_fields(plan: Mapping[str, Any]) -> frozenset[str]:
    """Fields the plan treats as numbers: quantitative channels and numeric aggregate inputs."""
    spec = _mapping(plan.get("spec"))
    found: set[str] = set()
    for definition in _mapping(spec.get("encoding")).values():
        items: Iterable[object] = definition if isinstance(definition, list) else [definition]
        for item in items:
            item = _mapping(item)
            field = item.get("field")
            if item.get("type") == "quantitative" and isinstance(field, str):
                found.add(field)
    transforms = spec.get("transform")
    for transform in transforms if isinstance(transforms, list) else []:
        for agg in _mapping(transform).get("aggregate", []) or []:
            agg = _mapping(agg)
            if agg.get("op") in _NUMERIC_AGGREGATES and isinstance(agg.get("field"), str):
                found.add(agg["field"])
    return frozenset(found)


def _field_name(raw: str) -> str | None:
    name = re.sub(r"[^a-z0-9_]", "_", raw.lower())
    if name and name[0].isdigit():
        name = "_" + name
    name = name[:64]
    return name if _FIELD.fullmatch(name) else None


def _scalar(value: object, *, numeric: bool) -> object:
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        if numeric and _NUMBER.fullmatch(value):
            return float(value)
        return value[:_MAX_TEXT]
    return None


def _flatten(prefix: str, data: Mapping[str, Any], depth: int, out: dict[str, object]) -> None:
    for key, value in data.items():
        name = _field_name(f"{prefix}_{key}" if prefix else str(key))
        if name is None:
            continue
        if isinstance(value, Mapping) and depth < _MAX_DEPTH:
            _flatten(name, value, depth + 1, out)
        elif isinstance(value, Mapping | list | tuple):
            continue
        else:
            out.setdefault(name, value)


def build_rows(records: Sequence[ToolRecord], numeric: frozenset[str]) -> list[dict[str, Any]]:
    """One flat row per record: ``record_id``, ``kind`` and the record's scalar fields."""
    rows: list[dict[str, Any]] = []
    for record in records[:MAX_ROWS]:
        flat: dict[str, object] = {"record_id": record.record_id, "kind": record.kind}
        _flatten("", record.data, 0, flat)
        rows.append({k: _scalar(v, numeric=k in numeric) for k, v in flat.items()})
    return rows


def _plan_citations(
    citations: Sequence[Citation], fallback: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """Plan citations from the run's own tool citations (record id + freshness), at most 20."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for c in citations:
        record_id = c.record_id.lower()
        if (
            c.as_of is None
            or not _TIMESTAMP.fullmatch(c.as_of)
            or not _EVIDENCE_ID.fullmatch(record_id)
            or record_id in seen
        ):
            continue
        seen.add(record_id)
        out.append({"evidence_id": record_id, "as_of": c.as_of})
        if len(out) == 20:
            break
    return out or [dict(item) for item in fallback]


def fill_plan(
    stored: Mapping[str, Any], rows: list[dict[str, Any]], citations: Sequence[Citation]
) -> dict[str, Any]:
    """The stored template with this run's rows and citations. Not yet validated."""
    plan = copy.deepcopy(dict(stored))
    spec = plan.setdefault("spec", {})
    spec.setdefault("data", {})["values"] = rows
    fallback = stored.get("citations")
    plan["citations"] = _plan_citations(citations, fallback if isinstance(fallback, list) else [])
    return plan


def check_template(stored: Mapping[str, Any]) -> ChartPlan:
    """Structural re-validation of a stored (data-less) plan when a run yields no rows.

    The full validator needs rows to resolve field references; the model alone still enforces
    every allowlist (marks, channels, transforms, no expr / url / signals).
    """
    try:
        return ChartPlan.model_validate(stored)
    except ValidationError as exc:
        raise ChartPlanInvalidError(
            [
                ValidationIssue("/" + "/".join(str(p) for p in e["loc"]), e["msg"])
                for e in exc.errors()
            ]
        ) from None
