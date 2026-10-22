"""Chart plan validator: the security boundary for model-proposed charts (PRP-19 item 4).

A raw chart plan is accepted only when it (1) is JSON-shaped, bounded in depth and size,
(2) carries none of the banned Vega keys anywhere outside inline data rows, (3) validates
against the generated ``ChartPlan`` model (explicit allowlists, ``extra=forbid``) and (4)
satisfies the rules JSON Schema cannot express: field references and mark/channel
compatibility. The function is pure (no I/O) so it can run before storage and again before
every render. The renderer is defence in depth only; this module is the boundary.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any

from neurosphere_contracts.chart.v1.chart_plan import ChartPlan
from pydantic import ValidationError

from neurosphere_core.errors import InvalidSchemaError, ValidationIssue

CHART_MAX_BYTES = 2 * 1024 * 1024
MAX_DEPTH = 32

# Keys that can introduce expressions, network access, interactivity or global config. None of
# them is on the schema allowlist; the deep scan rejects them early with a precise message.
BANNED_KEYS = frozenset(
    {
        "expr",
        "signal",
        "signals",
        "params",
        "param",
        "selection",
        "url",
        "href",
        "calculate",
        "lookup",
        "loader",
        "usermeta",
        "on",
        "events",
        "datasets",
        "$schema",
        "$ref",
        "config",
        "condition",
    }
)


class ChartPlanInvalidError(InvalidSchemaError):
    """A chart plan failed validation. ``violations`` lists value-free ``pointer: message``."""

    def __init__(self, violations: Iterable[ValidationIssue]) -> None:
        issues = tuple(violations)
        super().__init__(f"chart plan rejected with {len(issues)} violation(s)")
        self.errors = issues

    @property
    def violations(self) -> tuple[ValidationIssue, ...]:
        return self.errors or ()


def _pointer(parts: Iterable[object]) -> str:
    return "".join("/" + str(p).replace("~", "~0").replace("/", "~1") for p in parts)


def _scan(node: object, path: tuple[object, ...], out: list[ValidationIssue]) -> None:
    """Depth-bounded scan for banned keys. Inline data rows are skipped (field names there are
    user data and are constrained by the model)."""
    if len(path) > MAX_DEPTH:
        out.append(ValidationIssue(_pointer(path), "nesting is too deep"))
        return
    if isinstance(node, Mapping):
        for key, value in node.items():
            here = (*path, key)
            if not isinstance(key, str):
                out.append(ValidationIssue(_pointer(here), "object keys must be strings"))
                continue
            if key in BANNED_KEYS:
                out.append(ValidationIssue(_pointer(here), f"key {key!r} is not allowed"))
                continue
            if key == "values" and path[-1:] == ("data",):
                continue
            _scan(value, here, out)
    elif isinstance(node, list | tuple):
        for i, item in enumerate(node):
            _scan(item, (*path, i), out)


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def _encoding_defs(encoding: Mapping[str, Any]) -> Iterable[tuple[str, Mapping[str, Any]]]:
    for channel, definition in encoding.items():
        items = definition if isinstance(definition, list) else [definition]
        for item in items:
            yield channel, _mapping(item)


def check_field_references(plan: Mapping[str, Any]) -> list[str]:
    """Every encoding/transform field exists in data.values rows or is produced earlier."""
    spec = _mapping(plan.get("spec"))
    rows = _list(_mapping(spec.get("data")).get("values"))
    available: set[str] = {k for row in rows if isinstance(row, Mapping) for k in row}
    problems: list[str] = []

    def need(field: object, where: str) -> None:
        if isinstance(field, str) and field not in available:
            problems.append(f"{where}: field {field!r} is not available")

    for i, raw in enumerate(_list(spec.get("transform"))):
        t = _mapping(raw)
        where = f"/spec/transform/{i}"
        if "filter" in t:
            need(_mapping(t["filter"]).get("field"), where)
        elif "aggregate" in t:
            groupby = [g for g in _list(t.get("groupby")) if isinstance(g, str)]
            for g in groupby:
                need(g, where)
            outputs: list[object] = []
            for agg in _list(t.get("aggregate")):
                agg = _mapping(agg)
                if agg.get("field") is not None:
                    need(agg.get("field"), where)
                outputs.append(agg.get("as"))
            available = set(groupby) | {o for o in outputs if isinstance(o, str)}
        elif "bin" in t or "timeUnit" in t:
            need(t.get("field"), where)
            output = t.get("as")
            if isinstance(output, str):
                available.add(output)
                if "bin" in t:
                    available.add(f"{output}_end")
        elif "fold" in t:
            for f in _list(t.get("fold")):
                need(f, where)
            names = _list(t.get("as")) or ["key", "value"]
            available.update(n for n in names if isinstance(n, str))
    for channel, definition in _encoding_defs(_mapping(spec.get("encoding"))):
        need(definition.get("field"), f"/spec/encoding/{channel}")
    return problems


def check_mark_channels(plan: Mapping[str, Any]) -> list[str]:
    """Mark/channel compatibility: text needs a text channel; line, area and rect need x and
    y; bar and point need x or y; x2/y2 need x/y."""
    spec = _mapping(plan.get("spec"))
    mark = spec.get("mark")
    mark_type = mark if isinstance(mark, str) else _mapping(mark).get("type")
    channels = set(_mapping(spec.get("encoding")))
    problems: list[str] = []
    if mark_type == "text" and "text" not in channels:
        problems.append("a text mark needs a text channel")
    if mark_type in ("line", "area", "rect") and not {"x", "y"} <= channels:
        problems.append(f"a {mark_type} mark needs both x and y")
    if mark_type in ("bar", "point") and not channels & {"x", "y"}:
        problems.append(f"a {mark_type} mark needs x or y")
    for secondary, primary in (("x2", "x"), ("y2", "y")):
        if secondary in channels and primary not in channels:
            problems.append(f"{secondary} needs {primary}")
    return problems


def validate_chart_plan(raw: object) -> ChartPlan:
    """Return the validated ``ChartPlan`` or raise ``ChartPlanInvalidError`` (HTTP 422).

    Pure and idempotent: call it before storing a plan and again before every render.
    """
    if not isinstance(raw, Mapping):
        raise ChartPlanInvalidError([ValidationIssue("", "chart plan must be an object")])
    try:
        size = len(json.dumps(raw, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    except (TypeError, ValueError, RecursionError):
        raise ChartPlanInvalidError(
            [ValidationIssue("", "chart plan must be JSON-serialisable and not nested too deeply")]
        ) from None
    if size > CHART_MAX_BYTES:
        raise ChartPlanInvalidError(
            [ValidationIssue("", f"serialized chart plan is {size} bytes (> {CHART_MAX_BYTES})")]
        )

    issues: list[ValidationIssue] = []
    _scan(raw, (), issues)
    if issues:
        raise ChartPlanInvalidError(issues)

    try:
        plan = ChartPlan.model_validate(raw)
    except ValidationError as exc:
        raise ChartPlanInvalidError(
            [ValidationIssue(_pointer(e["loc"]), e["msg"]) for e in exc.errors()]
        ) from None

    rule_issues = [
        ValidationIssue("", message)
        for check in (check_field_references, check_mark_channels)
        for message in check(raw)
    ]
    if rule_issues:
        raise ChartPlanInvalidError(rule_issues)
    return plan
