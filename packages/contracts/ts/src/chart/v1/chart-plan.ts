/*
 * GENERATED - do not edit.
 * Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
 * Regenerate: python packages/contracts/scripts/generate.py
 * Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
 */

/**
 * Semantic version of this document within major 1. Within v1 only additive, optional changes are allowed (ADR-0004).
 *
 * This interface was referenced by `ChartPlan`'s JSON-Schema
 * via the `definition` "schema_version".
 */
export type SchemaVersion = string;
/**
 * Display text with no quotes, backslashes, backticks, braces or control characters.
 *
 * This interface was referenced by `ChartPlan`'s JSON-Schema
 * via the `definition` "safe_text".
 */
export type SafeText = string;
/**
 * This interface was referenced by `ChartPlan`'s JSON-Schema
 * via the `definition` "size_value".
 */
export type SizeValue = number | "container";
/**
 * This interface was referenced by `ChartPlan`'s JSON-Schema
 * via the `definition` "mark".
 */
export type Mark = MarkType | MarkDef;
/**
 * This interface was referenced by `ChartPlan`'s JSON-Schema
 * via the `definition` "mark_type".
 */
export type MarkType = "bar" | "line" | "area" | "point" | "rect" | "text";
/**
 * Flat snake_case field name. No dots or brackets (Vega-Lite nested access), no expression syntax.
 *
 * This interface was referenced by `ChartPlan`'s JSON-Schema
 * via the `definition` "field_name".
 */
export type FieldName = string;
/**
 * This interface was referenced by `ChartPlan`'s JSON-Schema
 * via the `definition` "data_type".
 */
export type DataType = "quantitative" | "nominal" | "ordinal" | "temporal";
/**
 * This interface was referenced by `ChartPlan`'s JSON-Schema
 * via the `definition` "aggregate_op".
 */
export type AggregateOp = "count" | "sum" | "mean" | "median" | "min" | "max" | "distinct";
/**
 * This interface was referenced by `ChartPlan`'s JSON-Schema
 * via the `definition` "time_unit".
 */
export type TimeUnit =
  | "year"
  | "quarter"
  | "month"
  | "date"
  | "day"
  | "hours"
  | "minutes"
  | "yearmonth"
  | "yearmonthdate"
  | "yearmonthdatehours"
  | "yearmonthdatehoursminutes"
  | "monthdate"
  | "hoursminutes";
/**
 * This interface was referenced by `ChartPlan`'s JSON-Schema
 * via the `definition` "bin_param".
 */
export type BinParam =
  | boolean
  | {
      maxbins: number;
    };
/**
 * This interface was referenced by `ChartPlan`'s JSON-Schema
 * via the `definition` "channel_title".
 */
export type ChannelTitle = SafeText | null;
/**
 * This interface was referenced by `ChartPlan`'s JSON-Schema
 * via the `definition` "sort_order".
 */
export type SortOrder = ("ascending" | "descending") | null;
/**
 * A scalar that Vega-Lite may compile into an expression literal; strings are charset-restricted.
 *
 * This interface was referenced by `ChartPlan`'s JSON-Schema
 * via the `definition` "safe_scalar".
 */
export type SafeScalar = number | boolean | null | string;
/**
 * This interface was referenced by `ChartPlan`'s JSON-Schema
 * via the `definition` "axis".
 */
export type Axis = {
  title?: ChannelTitle;
  format?: FormatString;
  labelAngle?: number;
  grid?: boolean;
  tickCount?: number;
} | null;
/**
 * d3-format or d3-time-format specifier.
 *
 * This interface was referenced by `ChartPlan`'s JSON-Schema
 * via the `definition` "format_string".
 */
export type FormatString = string;
/**
 * This interface was referenced by `ChartPlan`'s JSON-Schema
 * via the `definition` "legend".
 */
export type Legend = {
  title?: ChannelTitle;
  format?: FormatString;
  orient?: "left" | "right" | "top" | "bottom" | "none";
} | null;
/**
 * Transform allowlist: filter (field predicate only), aggregate, bin, timeUnit, fold. calculate, lookup, window, joinaggregate, impute, regression, loess, density, pivot, sample, flatten, extent and stack are rejected.
 *
 * This interface was referenced by `ChartPlan`'s JSON-Schema
 * via the `definition` "transform".
 */
export type Transform =
  FilterTransform | AggregateTransform | BinTransform | TimeunitTransform | FoldTransform;
/**
 * RFC 3339 timestamp in UTC (Z suffix required).
 *
 * This interface was referenced by `ChartPlan`'s JSON-Schema
 * via the `definition` "timestamp".
 */
export type Timestamp = string;

/**
 * A declarative chart produced by the copilot, a saved report or a dashboard (PRP.md section 3, NS-06, PRP-01 clarification 13). It wraps `spec`, a validated SUBSET of Vega-Lite rendered by a CSP-safe interpreter (vega-interpreter) in a sandboxed frame. The subset is enforced by explicit allowlists with additionalProperties false at every level, not by prose: marks bar, line, area, point, rect, text only; encoding channels x, y, x2, y2, color, size, opacity, text, tooltip only; transforms filter (field predicates only), aggregate, bin, timeUnit, fold only; data is inline `data.values` only, capped at 5000 rows. Therefore expr, signals, params, selections, conditions, calculate, lookup, data url, named data and top-level datasets, $schema, remote $ref, config and usermeta are all rejected because they are not on any allowlist. Field names and any string that Vega-Lite may compile into an expression (filter values, scale domains, formats, titles) are charset-restricted to exclude quotes, backslashes, backticks, braces and control characters. The spec subtree keeps Vega-Lite's own camelCase property names (timeUnit, maxbins, labelAngle, ...) so it can be passed to the compiler unchanged; this is the one documented exception to the snake_case convention. Rules JSON Schema cannot express: every encoding/transform field must exist in data.values rows or be produced by an earlier transform (tests/contracts/validators.py::check_chart_plan_field_references); mark/channel compatibility, e.g. a text mark needs a text channel (tests/contracts/validators.py::check_chart_plan_mark_channels); serialized document size <= 2 MiB (tests/contracts/validators.py::check_chart_plan_size).
 */
export interface ChartPlan {
  schema_version: SchemaVersion;
  /**
   * Evidence behind the plotted data, with data freshness (NS-06 citations with data freshness).
   *
   * @minItems 1
   * @maxItems 20
   */
  citations: [Citation, ...Citation[]];
  spec: Spec;
}
/**
 * This interface was referenced by `ChartPlan`'s JSON-Schema
 * via the `definition` "citation".
 */
export interface Citation {
  evidence_id: string;
  /**
   * Freshness: time the cited data was last observed.
   */
  as_of: string;
  label?: SafeText;
}
/**
 * Vega-Lite single-view unit spec subset. No layer, concat, facet or repeat in v1.
 *
 * This interface was referenced by `ChartPlan`'s JSON-Schema
 * via the `definition` "spec".
 */
export interface Spec {
  title?: SafeText;
  description?: SafeText;
  width?: SizeValue;
  height?: SizeValue;
  data: InlineData;
  mark: Mark;
  encoding: Encoding;
  /**
   * @maxItems 10
   */
  transform?: Transform[];
}
/**
 * Inline data only. url, name (datasets), format, sequence and generators are not allowed.
 *
 * This interface was referenced by `ChartPlan`'s JSON-Schema
 * via the `definition` "inline_data".
 */
export interface InlineData {
  /**
   * Row cap 5000.
   *
   * @maxItems 5000
   */
  values: DataRow[];
}
/**
 * This interface was referenced by `ChartPlan`'s JSON-Schema
 * via the `definition` "data_row".
 */
export interface DataRow {
  /**
   * This interface was referenced by `DataRow`'s JSON-Schema definition
   * via the `patternProperty` "^[a-z_][a-z0-9_]{0,63}$".
   */
  [k: string]: string | number | boolean | null | undefined;
}
/**
 * Mark properties take literal values only; ExprRef objects ({expr: ...}) are rejected by the typed properties.
 *
 * This interface was referenced by `ChartPlan`'s JSON-Schema
 * via the `definition` "mark_def".
 */
export interface MarkDef {
  type: MarkType;
  tooltip?: boolean;
  color?: string;
  opacity?: number;
  filled?: boolean;
  point?: boolean;
  interpolate?: "linear" | "monotone" | "step" | "step-before" | "step-after";
  size?: number;
  strokeWidth?: number;
  align?: "left" | "center" | "right";
  baseline?: "top" | "middle" | "bottom";
  dx?: number;
  dy?: number;
  fontSize?: number;
}
/**
 * This interface was referenced by `ChartPlan`'s JSON-Schema
 * via the `definition` "encoding".
 */
export interface Encoding {
  x?: PositionDef;
  y?: PositionDef;
  x2?: SecondaryDef;
  y2?: SecondaryDef;
  color?: MarkPropDef;
  size?: MarkPropDef;
  opacity?: MarkPropDef;
  text?: TextDef;
  tooltip?: TextDef | [TextDef, ...TextDef[]];
}
/**
 * This interface was referenced by `ChartPlan`'s JSON-Schema
 * via the `definition` "position_def".
 */
export interface PositionDef {
  field: FieldName;
  type: DataType;
  aggregate?: AggregateOp;
  timeUnit?: TimeUnit;
  bin?: BinParam;
  title?: ChannelTitle;
  sort?: SortOrder;
  scale?: Scale;
  axis?: Axis;
  stack?: ("zero" | "normalize" | "center") | null | false;
}
/**
 * This interface was referenced by `ChartPlan`'s JSON-Schema
 * via the `definition` "scale".
 */
export interface Scale {
  type?: "linear" | "log" | "sqrt" | "time" | "utc" | "band" | "point" | "ordinal";
  zero?: boolean;
  nice?: boolean;
  reverse?: boolean;
  /**
   * @minItems 1
   * @maxItems 64
   */
  domain?: [SafeScalar, ...SafeScalar[]];
  scheme?:
    | "category10"
    | "tableau10"
    | "set2"
    | "blues"
    | "greens"
    | "oranges"
    | "reds"
    | "purples"
    | "greys"
    | "viridis"
    | "redyellowgreen"
    | "blueorange";
}
/**
 * This interface was referenced by `ChartPlan`'s JSON-Schema
 * via the `definition` "secondary_def".
 */
export interface SecondaryDef {
  field: FieldName;
  aggregate?: AggregateOp;
  timeUnit?: TimeUnit;
  title?: ChannelTitle;
}
/**
 * This interface was referenced by `ChartPlan`'s JSON-Schema
 * via the `definition` "mark_prop_def".
 */
export interface MarkPropDef {
  field: FieldName;
  type: DataType;
  aggregate?: AggregateOp;
  timeUnit?: TimeUnit;
  bin?: BinParam;
  title?: ChannelTitle;
  sort?: SortOrder;
  scale?: Scale;
  legend?: Legend;
}
/**
 * This interface was referenced by `ChartPlan`'s JSON-Schema
 * via the `definition` "text_def".
 */
export interface TextDef {
  field: FieldName;
  type: DataType;
  aggregate?: AggregateOp;
  timeUnit?: TimeUnit;
  bin?: BinParam;
  title?: ChannelTitle;
  format?: FormatString;
}
/**
 * This interface was referenced by `ChartPlan`'s JSON-Schema
 * via the `definition` "filter_transform".
 */
export interface FilterTransform {
  filter: FieldPredicate;
}
/**
 * Vega-Lite field predicate with exactly one comparison. Expression strings, param predicates and and/or/not composition are rejected.
 *
 * This interface was referenced by `ChartPlan`'s JSON-Schema
 * via the `definition` "field_predicate".
 */
export interface FieldPredicate {
  field: FieldName;
  equal?: SafeScalar;
  lt?: SafeScalar;
  lte?: SafeScalar;
  gt?: SafeScalar;
  gte?: SafeScalar;
  /**
   * @minItems 2
   * @maxItems 2
   */
  range?: [SafeScalar, SafeScalar, ...SafeScalar[]];
  /**
   * @minItems 1
   * @maxItems 100
   */
  oneOf?: [SafeScalar, ...SafeScalar[]];
  valid?: boolean;
}
/**
 * This interface was referenced by `ChartPlan`'s JSON-Schema
 * via the `definition` "aggregate_transform".
 */
export interface AggregateTransform {
  /**
   * @minItems 1
   * @maxItems 10
   */
  aggregate: [
    {
      op: AggregateOp;
      field?: FieldName;
      as: FieldName;
    },
    ...{
      op: AggregateOp;
      field?: FieldName;
      as: FieldName;
    }[],
  ];
  /**
   * @maxItems 5
   */
  groupby?: FieldName[];
}
/**
 * This interface was referenced by `ChartPlan`'s JSON-Schema
 * via the `definition` "bin_transform".
 */
export interface BinTransform {
  bin: BinParam;
  field: FieldName;
  as: FieldName;
}
/**
 * This interface was referenced by `ChartPlan`'s JSON-Schema
 * via the `definition` "timeunit_transform".
 */
export interface TimeunitTransform {
  timeUnit: TimeUnit;
  field: FieldName;
  as: FieldName;
}
/**
 * This interface was referenced by `ChartPlan`'s JSON-Schema
 * via the `definition` "fold_transform".
 */
export interface FoldTransform {
  /**
   * @minItems 1
   * @maxItems 20
   */
  fold: [FieldName, ...FieldName[]];
  /**
   * @minItems 2
   * @maxItems 2
   */
  as?: [FieldName, FieldName, ...FieldName[]];
}
