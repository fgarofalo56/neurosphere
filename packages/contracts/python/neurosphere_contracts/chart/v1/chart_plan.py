# GENERATED - do not edit.
# Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
# Regenerate: python packages/contracts/scripts/generate.py
# Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
# pyright: reportAssignmentType=false, reportInvalidTypeForm=false

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    RootModel,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    constr,
)


class SchemaVersion(RootModel[StrictStr]):
    root: Annotated[StrictStr, Field(pattern="^1\\.(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)$")]
    """
    Semantic version of this document within major 1. Within v1 only additive, optional changes are allowed (ADR-0004).
    """


class Timestamp(RootModel[StrictStr]):
    root: Annotated[
        StrictStr,
        Field(
            pattern="^[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])T([01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9](\\.[0-9]{1,9})?Z$"
        ),
    ]
    """
    RFC 3339 timestamp in UTC (Z suffix required).
    """


class SafeText(RootModel[StrictStr]):
    root: Annotated[StrictStr, Field(pattern="^[^\"'\\\\`{}\\u0000-\\u001f]{0,200}$")]
    """
    Display text with no quotes, backslashes, backticks, braces or control characters.
    """


class SafeScalar1(RootModel[StrictStr]):
    root: Annotated[StrictStr, Field(pattern="^[^\"'\\\\`{}\\u0000-\\u001f]{0,128}$")]
    """
    A scalar that Vega-Lite may compile into an expression literal; strings are charset-restricted.
    """


class SafeScalar(RootModel[StrictFloat | StrictBool | SafeScalar1 | None]):
    root: StrictFloat | StrictBool | SafeScalar1 | None
    """
    A scalar that Vega-Lite may compile into an expression literal; strings are charset-restricted.
    """


class FieldName(RootModel[StrictStr]):
    root: Annotated[StrictStr, Field(pattern="^[a-z_][a-z0-9_]{0,63}$")]
    """
    Flat snake_case field name. No dots or brackets (Vega-Lite nested access), no expression syntax.
    """


class FormatString(RootModel[StrictStr]):
    root: Annotated[StrictStr, Field(pattern="^[A-Za-z0-9 %,.:$+#~/-]{0,32}$")]
    """
    d3-format or d3-time-format specifier.
    """


class Citation(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    evidence_id: Annotated[StrictStr, Field(pattern="^[a-z0-9][a-z0-9._:/=-]{0,255}$")]
    as_of: Timestamp
    """
    Freshness: time the cited data was last observed.
    """
    label: SafeText | None = None


class SizeValue1(RootModel[StrictInt]):
    root: Annotated[StrictInt, Field(ge=50, le=2000)]


class SizeValue(RootModel[SizeValue1 | Literal["container"]]):
    root: SizeValue1 | Literal["container"]


class DataRow1(RootModel[StrictStr]):
    root: Annotated[StrictStr, Field(max_length=1024)]


class DataRow(
    RootModel[
        dict[
            constr(pattern=r"^[a-z_][a-z0-9_]{0,63}$", strict=True),
            DataRow1 | StrictFloat | StrictBool | None,
        ]
    ]
):
    root: dict[
        constr(pattern=r"^[a-z_][a-z0-9_]{0,63}$", strict=True),
        DataRow1 | StrictFloat | StrictBool | None,
    ]


class MarkType(RootModel[Literal["bar", "line", "area", "point", "rect", "text"]]):
    root: Literal["bar", "line", "area", "point", "rect", "text"]


class MarkDef(BaseModel):
    """
    Mark properties take literal values only; ExprRef objects ({expr: ...}) are rejected by the typed properties.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    type: MarkType
    tooltip: StrictBool | None = None
    color: Annotated[StrictStr | None, Field(pattern="^#[0-9a-fA-F]{6}$")] = None
    opacity: Annotated[StrictFloat | None, Field(ge=0.0, le=1.0)] = None
    filled: StrictBool | None = None
    point: StrictBool | None = None
    interpolate: Literal["linear", "monotone", "step", "step-before", "step-after"] | None = None
    size: Annotated[StrictFloat | None, Field(ge=1.0, le=10000.0)] = None
    strokeWidth: Annotated[StrictFloat | None, Field(ge=0.0, le=20.0)] = None
    align: Literal["left", "center", "right"] | None = None
    baseline: Literal["top", "middle", "bottom"] | None = None
    dx: Annotated[StrictFloat | None, Field(ge=-100.0, le=100.0)] = None
    dy: Annotated[StrictFloat | None, Field(ge=-100.0, le=100.0)] = None
    fontSize: Annotated[StrictFloat | None, Field(ge=6.0, le=64.0)] = None


class DataType(RootModel[Literal["quantitative", "nominal", "ordinal", "temporal"]]):
    root: Literal["quantitative", "nominal", "ordinal", "temporal"]


class AggregateOp(RootModel[Literal["count", "sum", "mean", "median", "min", "max", "distinct"]]):
    root: Literal["count", "sum", "mean", "median", "min", "max", "distinct"]


class TimeUnit(
    RootModel[
        Literal[
            "year",
            "quarter",
            "month",
            "date",
            "day",
            "hours",
            "minutes",
            "yearmonth",
            "yearmonthdate",
            "yearmonthdatehours",
            "yearmonthdatehoursminutes",
            "monthdate",
            "hoursminutes",
        ]
    ]
):
    root: Literal[
        "year",
        "quarter",
        "month",
        "date",
        "day",
        "hours",
        "minutes",
        "yearmonth",
        "yearmonthdate",
        "yearmonthdatehours",
        "yearmonthdatehoursminutes",
        "monthdate",
        "hoursminutes",
    ]


class BinParam1(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    maxbins: Annotated[StrictInt, Field(ge=2, le=200)]


class BinParam(RootModel[StrictBool | BinParam1]):
    root: StrictBool | BinParam1


class ChannelTitle(RootModel[SafeText | None]):
    root: SafeText | None


class SortOrder(RootModel[Literal["ascending", "descending"] | None]):
    root: Literal["ascending", "descending"] | None


class Scale(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    type: Literal["linear", "log", "sqrt", "time", "utc", "band", "point", "ordinal"] | None = None
    zero: StrictBool | None = None
    nice: StrictBool | None = None
    reverse: StrictBool | None = None
    domain: Annotated[list[SafeScalar | None] | None, Field(max_length=64, min_length=1)] = None
    scheme: (
        Literal[
            "category10",
            "tableau10",
            "set2",
            "blues",
            "greens",
            "oranges",
            "reds",
            "purples",
            "greys",
            "viridis",
            "redyellowgreen",
            "blueorange",
        ]
        | None
    ) = None


class Axis1(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    title: ChannelTitle | None = None
    format: FormatString | None = None
    labelAngle: Annotated[StrictFloat | None, Field(ge=-90.0, le=90.0)] = None
    grid: StrictBool | None = None
    tickCount: Annotated[StrictInt | None, Field(ge=1, le=50)] = None


class Axis(RootModel[Axis1 | None]):
    root: Axis1 | None


class Legend1(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    title: ChannelTitle | None = None
    format: FormatString | None = None
    orient: Literal["left", "right", "top", "bottom", "none"] | None = None


class Legend(RootModel[Legend1 | None]):
    root: Legend1 | None


class PositionDef(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    field: FieldName
    type: DataType
    aggregate: AggregateOp | None = None
    timeUnit: TimeUnit | None = None
    bin: BinParam | None = None
    title: ChannelTitle | None = None
    sort: SortOrder | None = None
    scale: Scale | None = None
    axis: Axis | None = None
    stack: Literal["zero", "normalize", "center"] | Literal[False] | None = None


class SecondaryDef(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    field: FieldName
    aggregate: AggregateOp | None = None
    timeUnit: TimeUnit | None = None
    title: ChannelTitle | None = None


class MarkPropDef(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    field: FieldName
    type: DataType
    aggregate: AggregateOp | None = None
    timeUnit: TimeUnit | None = None
    bin: BinParam | None = None
    title: ChannelTitle | None = None
    sort: SortOrder | None = None
    scale: Scale | None = None
    legend: Legend | None = None


class TextDef(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    field: FieldName
    type: DataType
    aggregate: AggregateOp | None = None
    timeUnit: TimeUnit | None = None
    bin: BinParam | None = None
    title: ChannelTitle | None = None
    format: FormatString | None = None


class FieldPredicate(BaseModel):
    """
    Vega-Lite field predicate with exactly one comparison. Expression strings, param predicates and and/or/not composition are rejected.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    field: FieldName
    equal: SafeScalar | None = None
    lt: SafeScalar | None = None
    lte: SafeScalar | None = None
    gt: SafeScalar | None = None
    gte: SafeScalar | None = None
    range: Annotated[list[SafeScalar | None] | None, Field(max_length=2, min_length=2)] = None
    oneOf: Annotated[list[SafeScalar | None] | None, Field(max_length=100, min_length=1)] = None
    valid: StrictBool | None = None


class AggregateItem(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    op: AggregateOp
    field: FieldName | None = None
    as_: Annotated[FieldName, Field(alias="as")]


class AggregateTransform(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    aggregate: Annotated[list[AggregateItem], Field(max_length=10, min_length=1)]
    groupby: Annotated[list[FieldName] | None, Field(max_length=5)] = None


class BinTransform(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    bin: BinParam
    field: FieldName
    as_: Annotated[FieldName, Field(alias="as")]


class TimeunitTransform(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    timeUnit: TimeUnit
    field: FieldName
    as_: Annotated[FieldName, Field(alias="as")]


class FoldTransform(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    fold: Annotated[list[FieldName], Field(max_length=20, min_length=1)]
    as_: Annotated[list[FieldName] | None, Field(alias="as", max_length=2, min_length=2)] = None


class InlineData(BaseModel):
    """
    Inline data only. url, name (datasets), format, sequence and generators are not allowed.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    values: Annotated[list[DataRow], Field(max_length=5000)]
    """
    Row cap 5000.
    """


class Mark(RootModel[MarkType | MarkDef]):
    root: MarkType | MarkDef


class Tooltip(RootModel[list[TextDef]]):
    root: Annotated[list[TextDef], Field(max_length=10, min_length=1)]


class Encoding(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    x: PositionDef | None = None
    y: PositionDef | None = None
    x2: SecondaryDef | None = None
    y2: SecondaryDef | None = None
    color: MarkPropDef | None = None
    size: MarkPropDef | None = None
    opacity: MarkPropDef | None = None
    text: TextDef | None = None
    tooltip: TextDef | Tooltip | None = None


class FilterTransform(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    filter: FieldPredicate


class Transform(
    RootModel[
        FilterTransform | AggregateTransform | BinTransform | TimeunitTransform | FoldTransform
    ]
):
    root: FilterTransform | AggregateTransform | BinTransform | TimeunitTransform | FoldTransform
    """
    Transform allowlist: filter (field predicate only), aggregate, bin, timeUnit, fold. calculate, lookup, window, joinaggregate, impute, regression, loess, density, pivot, sample, flatten, extent and stack are rejected.
    """


class Spec(BaseModel):
    """
    Vega-Lite single-view unit spec subset. No layer, concat, facet or repeat in v1.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    title: SafeText | None = None
    description: SafeText | None = None
    width: SizeValue | None = None
    height: SizeValue | None = None
    data: InlineData
    mark: Mark
    encoding: Encoding
    transform: Annotated[list[Transform] | None, Field(max_length=10)] = None


class ChartPlan(BaseModel):
    """
    A declarative chart produced by the copilot, a saved report or a dashboard (PRP.md section 3, NS-06, PRP-01 clarification 13). It wraps `spec`, a validated SUBSET of Vega-Lite rendered by a CSP-safe interpreter (vega-interpreter) in a sandboxed frame. The subset is enforced by explicit allowlists with additionalProperties false at every level, not by prose: marks bar, line, area, point, rect, text only; encoding channels x, y, x2, y2, color, size, opacity, text, tooltip only; transforms filter (field predicates only), aggregate, bin, timeUnit, fold only; data is inline `data.values` only, capped at 5000 rows. Therefore expr, signals, params, selections, conditions, calculate, lookup, data url, named data and top-level datasets, $schema, remote $ref, config and usermeta are all rejected because they are not on any allowlist. Field names and any string that Vega-Lite may compile into an expression (filter values, scale domains, formats, titles) are charset-restricted to exclude quotes, backslashes, backticks, braces and control characters. The spec subtree keeps Vega-Lite's own camelCase property names (timeUnit, maxbins, labelAngle, ...) so it can be passed to the compiler unchanged; this is the one documented exception to the snake_case convention. Rules JSON Schema cannot express: every encoding/transform field must exist in data.values rows or be produced by an earlier transform (tests/contracts/validators.py::check_chart_plan_field_references); mark/channel compatibility, e.g. a text mark needs a text channel (tests/contracts/validators.py::check_chart_plan_mark_channels); serialized document size <= 2 MiB (tests/contracts/validators.py::check_chart_plan_size).
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    schema_version: SchemaVersion
    citations: Annotated[list[Citation], Field(max_length=20, min_length=1)]
    """
    Evidence behind the plotted data, with data freshness (NS-06 citations with data freshness).
    """
    spec: Spec
